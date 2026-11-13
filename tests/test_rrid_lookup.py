"""`lookup --resources`: each RRID the manuscript types asked of the RRID resolver once, a cell
line of Cellosaurus too, and the answer kept; and G7's reading of the records.

No test opens a connection to either service. Most answer from a table; the real transport
is run against a server on a loopback port. The answers are written in the shapes the two
services gave on 2026-11-12 (`lookup/resources.py`), with the RRIDs and names those answers
had.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from manuscript_guard import __version__
from manuscript_guard.cli import main
from manuscript_guard.contracts.project import load_project
from manuscript_guard.gates.rrids import check_rrids
from manuscript_guard.lookup import resources
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport
from manuscript_guard.lookup.resources import PROBLEMATIC
from manuscript_guard.lookup.run import Pacer
from manuscript_guard.rrids import (
    answers_digest,
    read_record,
    record_path,
    typed,
)

TODAY = date(2026, 11, 12)


# ------------------------------------------------------------------------------ answers


def _hit(curie: str, name: str, kind: str, citation: str) -> dict:
    return {"_source": {"item": {"name": name, "types": [
        {"curie": "ilx:0100789", "name": kind, "type": "category"}, {"type": "supercategory"}]},
        "rrid": {"is_unique": "false", "curie": curie, "properCitation": citation}}}  # fmt: skip


def resolved(*hits: dict, total: int | None = None) -> dict:
    return {"hits": {"total": len(hits) if total is None else total, "hits": list(hits)},
            "resolver": {"uri": "scicrunch.org/resolver"}}  # fmt: skip


NEUN = resolved(
    _hit("RRID:AB_2298772", "Anti-NeuN", "antibody", "(Millipore Cat# MAB377, RRID:AB_2298772)"),
    _hit("RRID:AB_2298772", "Anti-NeuN Antibody, clone A60", "antibody",
         "(Sigma-Aldrich Cat# MAB377, RRID:AB_2298772)"),
)  # fmt: skip
KB = resolved(_hit("RRID:CVCL_0372", "KB", "cell line", "ECACC Cat# 86103004, RRID:CVCL_0372"))
HELA = resolved(_hit("RRID:CVCL_0030", "HeLa", "cell line", "ATCC Cat# CRL-7923, RRID:CVCL_0030"))
PRISM = resolved(_hit("RRID:SCR_002798", "GraphPad Prism", "software resource",
                      "GraphPad Prism (RRID:SCR_002798)"))  # fmt: skip
CONTAMINATED = ("Contaminated. Shown to be a HeLa derivative (PubMed=4864103; PubMed=5641128). "
                "Originally thought to originate from an epidermal carcinoma of the mouth.")


def line(accession: str, name: str, *comments: tuple[str, str]) -> dict:
    return {"Cellosaurus": {"cell-line-list": [{
        "accession-list": [{"type": "primary", "value": accession}],
        "name-list": [{"type": "identifier", "value": name}],
        "comment-list": [{"category": c, "value": v} for c, v in comments],
    }]}}  # fmt: skip


CELLOSAURUS = {
    "CVCL_0372": line("CVCL_0372", "KB", ("Population", "Caucasian"),
                      ("Problematic cell line", CONTAMINATED)),
    "CVCL_0030": line("CVCL_0030", "HeLa", ("Population", "African American")),
}  # fmt: skip
RESOLVER = {"RRID:AB_2298772": NEUN, "RRID:CVCL_0372": KB, "RRID:CVCL_0030": HELA,
            "RRID:SCR_002798": PRISM}  # fmt: skip
SERVICES = resources.Services(resolver="https://resolver.test/resolver/",
                              cellosaurus="https://cellosaurus.test/cell-line/")  # fmt: skip


def _json(status: int, data: object) -> Response:
    return Response(status, {"Content-Type": "application/json"}, json.dumps(data).encode())


class Table:
    """A transport that answers as the two services did, and keeps what it was sent."""

    def __init__(self, resolver=None, cellosaurus=None, failing: frozenset[str] = frozenset()):
        self.resolver = RESOLVER if resolver is None else resolver
        self.cellosaurus = CELLOSAURUS if cellosaurus is None else cellosaurus
        self.failing = failing
        self.sent: list[tuple[Request, float]] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append((request, timeout))
        path = urlsplit(request.base).path
        name = path.rsplit("/", 1)[-1]
        if name in self.failing:
            raise NoAnswer("no answer within 30 s")
        if path.startswith("/resolver/"):
            rrid = name.removesuffix(".json")
            answer = self.resolver.get(rrid)
            if isinstance(answer, Response):
                return answer
            return _json(200, answer) if answer is not None else Response(404, {}, b"")
        answer = self.cellosaurus.get(name)
        if isinstance(answer, Response):
            return answer
        return _json(200, answer) if answer is not None else Response(404, {}, b"")


def _quiet() -> Pacer:
    return Pacer(sleep=lambda seconds: None, intervals=dict(resources.INTERVALS))


def _project(root: Path, main_text: str, supplement: str | None = None, *,
             latex: bool = False) -> Path:  # fmt: skip
    assert main(["init", str(root), *(["--latex"] if latex else [])]) == 0
    folder = root / "manuscript"
    if latex:
        (folder / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\n" + main_text + "\n\\end{document}\n",
            encoding="utf-8")  # fmt: skip
        if supplement is not None:
            (folder / "supplementary").mkdir()
            (folder / "supplementary" / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n" + supplement
                + "\n\\end{document}\n", encoding="utf-8")  # fmt: skip
        return root
    (folder / "main.md").write_text("# Methods\n\n" + main_text + "\n", encoding="utf-8")
    if supplement is not None:
        (folder / "supplementary").mkdir()
        (folder / "supplementary" / "S1.md").write_text(supplement + "\n", encoding="utf-8")
    return root


def _look_up(root: Path, transport: Table, *, again: bool = False):
    project = load_project(root)[0]
    planned = resources.plan(project, again=again)
    return resources.run(project, planned, transport=transport, services=SERVICES,
                         pacer=_quiet(), today=TODAY, said=lambda said: None)  # fmt: skip


def _found(root: Path) -> dict[str, str]:
    report = check_rrids(load_project(root)[0])
    return {f.code: f.severity for f in report.findings}


# ------------------------------------------------------------------------------ reading


def _read(root: Path) -> list[tuple[str, str, int, bool]]:
    project = load_project(root)[0]
    return [(one.rrid, one.path.relative_to(root).as_posix(), one.line, one.supplementary)
            for one in typed(project)]  # fmt: skip


def test_each_rrid_is_read_as_written_with_its_punctuation_left_out(tmp_path: Path) -> None:
    text = ("Anti-NeuN (Millipore Cat# MAB377, RRID:AB_2298772), HeLa cells (RRID: CVCL_0030);\n"
            "mice RRID:IMSR_JAX:000664. A plasmid, RRID:Addgene_12345, and RRID:MGI:3840442:\n"
            "fish RRID:ZFIN_ZDB-GENO-960809-7, flies RRID:BDSC_8848, RRID:WB-STRAIN:WBStrain1,\n"
            "an old one RRID:nif-0000-30467 and the software (RRID:SCR_002798).")  # fmt: skip
    root = _project(tmp_path / "p", text)
    assert [(rrid, at) for rrid, _path, at, _s in _read(root)] == [
        ("RRID:AB_2298772", 3), ("RRID:CVCL_0030", 3), ("RRID:IMSR_JAX:000664", 4),
        ("RRID:Addgene_12345", 4), ("RRID:MGI:3840442", 4), ("RRID:ZFIN_ZDB-GENO-960809-7", 5),
        ("RRID:BDSC_8848", 5), ("RRID:WB-STRAIN:WBStrain1", 5), ("RRID:nif-0000-30467", 6),
        ("RRID:SCR_002798", 6),
    ]  # fmt: skip


def test_what_is_not_an_rrid_is_not_read(tmp_path: Path) -> None:
    """A label in other case, two spaces, no accession, a word before it, a comment, a code
    span and a fence are not read; a line break after the colon is the one space, and the
    case of the accession is kept."""
    text = ("rrid:AB_1 and RRID:  AB_2 and RRID: none and RRID: N/A and xRRID:AB_3.\n"
            "<!-- RRID:AB_4 --> `RRID:AB_5` and RRID:\nab_6 and RRID:AB\\_7.\n\n"
            "```\nRRID:AB_8\n```\n")  # fmt: skip
    root = _project(tmp_path / "p", text)
    assert [rrid for rrid, *_rest in _read(root)] == ["RRID:ab_6", "RRID:AB_7"]


def test_a_dotted_accession_and_one_of_one_part_are_read_whole(tmp_path: Path) -> None:
    """Round 1 of #658: a dot joins parts, NXR_0.0005 was read as NXR_0; an accession of one
    part, SAMN12345678, was not read; and a word of small letters after a hyphen is no part,
    CVCL_0030-derived was read whole. The sentence's full stop is still left out."""
    text = ("Xenopus laevis (RRID:NXR_0.0005). Biosample RRID:SAMN12345678, and\n"
            "RRID:CVCL_0030-derived cells, mice RRID:MMRRC_000231-UNC and RRID:AB_2298772.\n"
            "RRID: pending, RRID:AB, RRID:NXR_0.0005. and RRID:ZFIN_ZDB-GENO-960809-7.\n"
            # Round 2: in small letters, read whole as 820eb0c read them, before a comma too;
            # a dot joins only before a digit; "-derived." still ends one.
            "RRID:zfin_zdb-geno-960809-7, RRID:mmrrc_000231-unc, RRID:wb-strain:WBStrain00000001,\n"
            "RRID:SCR_002798.Version 9 and RRID:CVCL_0030-derived.")
    root = _project(tmp_path / "p", text)
    assert [rrid for rrid, *_rest in _read(root)] == [
        "RRID:NXR_0.0005", "RRID:SAMN12345678", "RRID:CVCL_0030", "RRID:MMRRC_000231-UNC",
        "RRID:AB_2298772", "RRID:NXR_0.0005", "RRID:ZFIN_ZDB-GENO-960809-7",
        "RRID:zfin_zdb-geno-960809-7", "RRID:mmrrc_000231-unc", "RRID:wb-strain:WBStrain00000001",
        "RRID:SCR_002798", "RRID:CVCL_0030",
    ]  # fmt: skip


def test_the_new_forms_are_recorded(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "Frogs RRID:NXR_0.0005 and RRID:SAMN12345678.")
    written, late = _look_up(root, Table(resolver={
        "RRID:NXR_0.0005": resolved(_hit("RRID:NXR_0.0005", "Xenopus laevis", "organism",
                                         "NXR_0.0005")),
        "RRID:SAMN12345678": resolved(_hit("RRID:SAMN12345678", "A biosample", "biosample",
                                           "SAMN12345678"))}))  # fmt: skip
    assert late == [] and len(written) == 2


def test_the_supplement_is_read_and_said_to_be_the_supplement(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "Cells RRID:CVCL_0030.", "Software RRID:SCR_002798.")
    assert _read(root) == [
        ("RRID:CVCL_0030", "manuscript/main.md", 3, False),
        ("RRID:SCR_002798", "manuscript/supplementary/S1.md", 1, True),
    ]


def test_a_latex_manuscript_is_read_outside_its_comments_and_code(tmp_path: Path) -> None:
    text = ("Cells (RRID:CVCL\\_0030), and RRID:~AB\\_2298772 % RRID:AB\\_9\n"
            "\\verb|RRID:AB_8| and \\texttt{RRID:AB\\_7}, mice RRID:\\,IMSR\\_JAX:000664.\n"
            "\\begin{tabular}{ll} NeuN & RRID:AB\\_10 \\\\ \\end{tabular}")  # fmt: skip
    root = _project(tmp_path / "p", text, "Software \\emph{RRID:SCR\\_002798}.", latex=True)
    assert _read(root) == [
        ("RRID:CVCL_0030", "manuscript/main.tex", 3, False),
        ("RRID:AB_2298772", "manuscript/main.tex", 3, False),
        ("RRID:IMSR_JAX:000664", "manuscript/main.tex", 4, False),
        ("RRID:AB_10", "manuscript/main.tex", 5, False),
        ("RRID:SCR_002798", "manuscript/supplementary/main.tex", 3, True),
    ]


# ------------------------------------------------------------------------------ the record


def test_each_rrid_is_asked_once_and_a_cell_line_of_cellosaurus_too(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "NeuN RRID:AB_2298772 in KB cells RRID:CVCL_0372, and\n"
                    "again RRID:AB_2298772.")  # fmt: skip
    table = Table()
    written, late = _look_up(root, table)
    assert late == [] and len(written) == 2
    sent = [(urlsplit(r.base).path, dict(r.params)) for r, _timeout in table.sent]
    assert sent == [
        ("/resolver/RRID:AB_2298772.json", {}),
        ("/resolver/RRID:CVCL_0372.json", {}),
        ("/cell-line/CVCL_0372", {"format": "json", "fields": "ac,id,cc"}),
    ]
    for request, timeout in table.sent:
        assert request.headers["User-Agent"] == f"manuscript-guard/{__version__}"
        assert not request.secret and 0 < timeout <= 60
    project = load_project(root)[0]
    neun = read_record(record_path(project, "RRID:AB_2298772"))
    assert neun["status"] == "found" and neun["total"] == 2 and neun["asked_on"] == "2026-11-12"
    assert neun["hits"][0] == {"curie": "RRID:AB_2298772", "name": "Anti-NeuN",
                               "types": ["antibody"],
                               "citation": "(Millipore Cat# MAB377, RRID:AB_2298772)"}  # fmt: skip
    assert "cellosaurus" not in neun
    kb = read_record(record_path(project, "RRID:CVCL_0372"))
    assert kb["cellosaurus"] == {"status": "found", "accession": "CVCL_0372", "name": "KB",
                                 "problems": [CONTAMINATED], "licence": "CC BY 4.0"}  # fmt: skip
    assert kb["answers_sha256"] == answers_digest(kb)


def test_a_second_run_asks_nothing_and_again_asks_all(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "Cells RRID:CVCL_0030.")
    _look_up(root, Table())
    table = Table()
    assert _look_up(root, table) == ([], []) and table.sent == []
    _look_up(root, table, again=True)
    assert len(table.sent) == 2


def test_an_rrid_the_resolver_does_not_know_is_recorded_as_absent(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "RRID:AB_0000000000 and RRID:SCR_404404.")
    _look_up(root, Table(resolver={"RRID:SCR_404404": resolved(total=0)}))
    project = load_project(root)[0]
    for rrid in ("RRID:AB_0000000000", "RRID:SCR_404404"):
        record = read_record(record_path(project, rrid))
        assert (record["status"], record["total"], record["hits"]) == ("absent", 0, [])
    assert _found(root) == {"rrid-unresolved": "warn"}


@pytest.mark.parametrize(
    "answer",
    [
        Response(500, {}, b"down"),
        Response(429, {}, b""),
        Response(200, {}, b"<html>maintenance</html>"),
        _json(200, {"hits": {"total": "2", "hits": []}}),
        _json(200, {"hits": {"total": 1, "hits": [{"_source": "x"}]}}),
        _json(200, {"hits": {"total": 2, "hits": []}}),
    ],
    ids=["500", "429", "a page", "a total that is text", "a hit of no shape", "no hits"],
)
def test_an_answer_that_is_not_one_records_nothing(tmp_path: Path, answer: Response) -> None:
    root = _project(tmp_path / "p", "NeuN RRID:AB_2298772.")
    written, late = _look_up(root, Table(resolver={"RRID:AB_2298772": answer}))
    assert written == [] and [one.rrid for one, _why in late] == ["RRID:AB_2298772"]
    assert not record_path(load_project(root)[0], "RRID:AB_2298772").exists()
    assert _found(root) == {"rrid-not-looked-up": "warn"}


@pytest.mark.parametrize(
    "answer",
    [
        {"Cellosaurus": {"cell-line-list": [{"accession-list": 5}]}},
        {"Cellosaurus": {"cell-line-list": [{"accession-list": [{"type": "primary",
                                                                 "value": "CVCL_0372"}],
                                             "comment-list": "none"}]}},
        line("CVCL_0372", "   "),
        {"Cellosaurus": {"cell-line-list": [{"accession-list": [{"type": "primary",
                                                                 "value": "CVCL_0372"}],
                                             "name-list": [{"type": "identifier",
                                                            "value": 7}],
                                             "comment-list": [{"category": PROBLEMATIC,
                                                               "value": 7}]}]}},
    ],
    ids=["accessions a number", "comments a string", "a name of spaces", "values numbers"],
)
def test_a_cellosaurus_answer_of_another_shape_raises_nothing(tmp_path: Path, answer) -> None:
    """Round 1 of #658: `"accession-list": 5` raised a TypeError, and a name of spaces made
    the record fail its schema in `write_record`: each is read as far as it goes, or no
    answer, and nothing raises."""
    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372.")
    written, late = _look_up(root, Table(cellosaurus={"CVCL_0372": answer}))
    assert len(written) + len(late) == 1
    for _one, record, _path in written:
        assert record["cellosaurus"].get("name", "KB").strip()


def test_a_record_its_schema_refuses_is_reported_and_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record `write_record` refuses is a failure for that RRID, as an answer that did not
    come is: the others are written, and the command says so and exits 1."""
    from manuscript_guard.contracts._schema import ContractError

    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372 and RRID:SCR_002798.")
    real = resources.write_record

    def refusing(project, record):
        if record["rrid"] == "RRID:CVCL_0372":
            raise ContractError("the record for RRID:CVCL_0372 is not valid: name: ''")
        return real(project, record)

    monkeypatch.setattr(resources, "write_record", refusing)
    written, late = _look_up(root, Table())
    assert [one.rrid for one, _r, _p in written] == ["RRID:SCR_002798"]
    assert [one.rrid for one, _why in late] == ["RRID:CVCL_0372"]


def test_the_command_ends_an_answer_of_another_shape_with_a_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372.")
    table = Table(cellosaurus={"CVCL_0372": {"Cellosaurus": {"cell-line-list": [
        {"accession-list": 5}]}}})  # fmt: skip
    monkeypatch.setattr(resources, "default_transport", table)
    monkeypatch.setattr(resources, "Pacer", lambda **given: Pacer(sleep=lambda s: None, **given))
    assert main(["lookup", str(root), "--resources"]) == 1
    said = capsys.readouterr().out
    assert "RRID:CVCL_0372: no answer" in said and "nothing recorded" in said
    # An answer did come when its record is one the schema refuses (round 2 of #658).
    monkeypatch.setattr(resources, "default_transport", Table())
    monkeypatch.setattr(resources, "write_record", _refused)
    assert main(["lookup", str(root), "--resources"]) == 1
    said = capsys.readouterr().out
    assert "RRID:CVCL_0372: an answer of another shape (" in said and "did not come" not in said


def _refused(project, record):
    from manuscript_guard.contracts._schema import ContractError

    raise ContractError(f"the record for {record['rrid']} is not valid: name: ''")


def test_an_outage_of_cellosaurus_records_nothing_for_the_cell_line(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372 and RRID:SCR_002798.")
    written, late = _look_up(root, Table(failing=frozenset({"CVCL_0372"})))
    assert [one.rrid for one, _r, _p in written] == ["RRID:SCR_002798"]
    assert [(one.rrid, why) for one, why in late] == [("RRID:CVCL_0372", "no answer within 30 s")]
    assert _found(root) == {"rrid-not-looked-up": "warn"}


def test_a_line_cellosaurus_does_not_have_is_said_and_nothing_is_flagged(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "Cells RRID:CVCL_0030.")
    _look_up(root, Table(cellosaurus={}))
    record = read_record(record_path(load_project(root)[0], "RRID:CVCL_0030"))
    assert record["cellosaurus"] == {"status": "absent", "licence": "CC BY 4.0"}
    assert _found(root) == {}


def test_a_problematic_line_is_quoted_and_warns(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372.")
    _look_up(root, Table())
    [said] = check_rrids(load_project(root)[0]).findings
    assert (said.code, said.severity, said.line) == ("cell-line-problematic", "warn", 3)
    assert CONTAMINATED in said.message and "KB" in said.message


def test_a_record_edited_or_of_another_rrid_is_not_read(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "Cells RRID:CVCL_0372.")
    _look_up(root, Table())
    path = record_path(load_project(root)[0], "RRID:CVCL_0372")
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["cellosaurus"]["problems"] = []
    path.write_text(yaml.safe_dump(record), encoding="utf-8")
    assert _found(root) == {"rrid-record-edited": "warn"}
    record = {**record, "rrid": "RRID:cvcl_0372"}
    path.write_text(yaml.safe_dump({**record, "answers_sha256": answers_digest(record)}),
                    encoding="utf-8")  # fmt: skip
    assert _found(root) == {"rrid-record-misfiled": "warn"}
    path.write_text("schema: manuscript-guard/rrid/1\n", encoding="utf-8")
    assert _found(root) == {"schema-violation": "fail"}


def test_a_record_of_an_rrid_no_longer_typed_is_not_read(tmp_path: Path) -> None:
    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372.")
    _look_up(root, Table())
    (root / "manuscript" / "main.md").write_text("# Methods\n\nNo cells.\n", encoding="utf-8")
    report = check_rrids(load_project(root)[0])
    # No count where nothing is typed: a paper with no RRID reads as it did before, as one
    # with no registration does (round 1 of #658, the differential's `check`).
    assert report.findings == () and not {"rrids", "rrids_looked_up"} & set(report.counts)


# ------------------------------------------------------------------------------ the command


def test_the_command_says_what_it_would_ask_and_sends_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "p", "NeuN RRID:AB_2298772 in KB cells RRID:CVCL_0372.")
    assert main(["lookup", str(root), "--resources", "--dry-run"]) == 0
    said = capsys.readouterr().out
    assert "RRID:AB_2298772: would ask the RRID resolver (no record)" in said
    assert "RRID:CVCL_0372: would ask the RRID resolver, and Cellosaurus (no record)" in said
    assert "2 to look up, 0 not; nothing was sent" in said
    assert not (root / "literature" / "rrids").exists()


def test_the_command_with_no_rrid_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "p", "No resource is named here.")
    assert main(["lookup", str(root), "--resources"]) == 0
    assert "types no RRID" in capsys.readouterr().out
    assert main(["lookup", str(root), "--resources", "--journals"]) == 2


def test_the_command_with_no_manuscript_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "p", "")
    (root / "manuscript" / "main.md").unlink()
    assert main(["lookup", str(root), "--resources"]) == 2
    assert "nothing to look up" in capsys.readouterr().err


def test_an_unreadable_record_is_not_written_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "p", "Cells RRID:CVCL_0030.")
    path = record_path(load_project(root)[0], "RRID:CVCL_0030")
    path.parent.mkdir(parents=True)
    path.write_text("not: [a record\n", encoding="utf-8")
    assert main(["lookup", str(root), "--resources", "--dry-run", "--again"]) == 0
    assert "RRID:CVCL_0030: not looked up: its record cannot be read" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == "not: [a record\n"


def test_check_reads_the_records(tmp_path: Path) -> None:
    from manuscript_guard.cli import _run_gates

    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372 and RRID:AB_0000000000.")
    report, *_ = _run_gates(root, stage="submission")
    assert {f.code for f in report.findings if f.gate == "G7"} >= {"rrid-not-looked-up"}
    _look_up(root, Table())
    report, *_ = _run_gates(root, stage="submission")
    said = {f.code: f.severity for f in report.findings if f.code.startswith(("rrid", "cell"))}
    assert said == {"rrid-unresolved": "warn", "cell-line-problematic": "warn"}


# --------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        self.server.seen.append((self.path, self.headers.get("User-Agent")))
        status, payload = self.server.respond(self.path)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []

    def respond(path: str) -> tuple[int, bytes]:
        if path == "/resolver/RRID:CVCL_0372.json":
            return 200, json.dumps(KB).encode()
        if path.startswith("/cell-line/CVCL_0372?"):
            return 200, json.dumps(CELLOSAURUS["CVCL_0372"]).encode()
        return 404, b""

    httpd.respond = respond
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        default_transport(Request(httpd.url + "/probe"), 5)
    except NoAnswer as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_the_real_transport_looks_up_a_cell_line(tmp_path: Path, server) -> None:
    root = _project(tmp_path / "p", "KB cells RRID:CVCL_0372 and RRID:AB_0000000000.")
    project = load_project(root)[0]
    services = resources.Services(resolver=f"{server.url}/resolver/",
                                  cellosaurus=f"{server.url}/cell-line/")  # fmt: skip
    written, late = resources.run(project, resources.plan(project), services=services,
                                  pacer=_quiet(), today=TODAY, said=lambda said: None)
    assert late == [] and len(written) == 2
    paths = [urlsplit(path) for path, _agent in server.seen]
    assert [p.path for p in paths] == ["/resolver/RRID:CVCL_0372.json", "/cell-line/CVCL_0372",
                                       "/resolver/RRID:AB_0000000000.json"]  # fmt: skip
    assert parse_qs(paths[1].query) == {"format": ["json"], "fields": ["ac,id,cc"]}
    assert {agent for _path, agent in server.seen} == {f"manuscript-guard/{__version__}"}
    kb = read_record(record_path(project, "RRID:CVCL_0372"))
    assert kb["cellosaurus"]["problems"] == [CONTAMINATED]
    assert read_record(record_path(project, "RRID:AB_0000000000"))["status"] == "absent"
    for path in (root / "literature" / "rrids").glob("*.yaml"):
        assert "127.0.0.1" not in path.read_text(encoding="utf-8")


def test_the_pace_is_one_request_a_second_to_each_host() -> None:
    assert resources.INTERVALS == {"scicrunch.org": 1.0, "api.cellosaurus.org": 1.0}
    assert {urlsplit(base).hostname for base in (resources.Services().resolver,
                                                 resources.Services().cellosaurus)} == set(
        resources.INTERVALS)  # fmt: skip


# ------------------------------------------- one reading of an RRID, in three places (#663)
#
# G2 (`data/structural.yaml`, `rrid`) and G14 (`gates/language.py`, `_RRID`) each carry a
# copy of `rrids.py`'s reading, which a YAML rule and a masked view cannot import. These
# tests hold the three to one another over every accession, gap, trail and case the
# generated inputs draw, so that a change to one that is not made to the others fails here.


def _rrid_disagreements() -> list[tuple[str, str, str]]:
    """Each typed RRID whose accession the three readings do not read alike."""
    from generated import RRID_ACCESSIONS, RRID_JOINED, RRID_TRAILS

    from manuscript_guard import rrids
    from manuscript_guard.classify import STRUCTURAL, _load_rules
    from manuscript_guard.gates import language

    structural = next(rule.pattern for rule in _load_rules("structural.yaml", "structural",
                                                           STRUCTURAL) if rule.id == "rrid")
    accessions = {a.removesuffix(".Version") for a in (*RRID_ACCESSIONS, *RRID_JOINED)}
    wrong = []
    for accession in sorted(accessions):
        for written in (accession, accession.lower()):
            for gap in ("", " ", "\n"):
                for trail in RRID_TRAILS:
                    text = f"Cells (RRID:{gap}{written}{trail}) were used."
                    typed = rrids.TYPED.search(text)
                    g14 = language._RRID.search(text)
                    g2 = structural.search(text)
                    said = {
                        "rrids.py": typed["accession"] if typed else None,
                        "G14": g14["accession"] if g14 else None,
                        "G2": g2[0].removeprefix("RRID:").lstrip() if g2 else None,
                    }
                    covered = written + trail if trail in ("-derived", ".Version") else written
                    if said["rrids.py"] != written:
                        wrong.append((text, "rrids.py", str(said["rrids.py"])))
                    if said["G14"] != written:
                        wrong.append((text, "G14", str(said["G14"])))
                    if said["G2"] != covered:
                        wrong.append((text, "G2", str(said["G2"])))
    return wrong


def test_g2_g14_and_rrids_py_read_an_rrid_alike() -> None:
    """The copies of the reading agree with `rrids.py` on each accession: G2's covers the
    word after it too ("-derived", ".Version"), which measures nothing, as its rule says."""
    assert _rrid_disagreements() == []


def test_a_copy_of_the_rrid_reading_that_drifts_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """G14's copy given round 1's joiner, where a `.` joined before a letter too, is caught."""
    import re

    from manuscript_guard.gates import language

    drifted = language._RRID.pattern.replace(r"\.(?=[0-9])", r"\.")
    assert drifted != language._RRID.pattern
    monkeypatch.setattr(language, "_RRID", re.compile(drifted))
    assert any(where == "G14" for _text, where, _said in _rrid_disagreements())
