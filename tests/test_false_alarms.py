"""The false-alarm page, docs/false-alarms.md, is the one its script draws from its counts.

`tools/corpus.py counts` writes the counts, docs/false-alarms.yaml, from a run of the corpus
of real papers and the verdicts on its findings; `tools/false_alarms.py` draws the page and
the README's line from them, with no corpus (Basile, 2026-11-25). The corpus stays outside
the repository, since its papers are other people's and its verdicts quote them, so the
counts must hold counts and nothing else. Here the committed page and line are held to the
committed counts, the counts to counts only, the shares and intervals to what they claim,
and `counts` is run over a made-up mini corpus in `tmp_path`.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


# The page's script under its own name, which the corpus tool imports from beside it.
page = _load("false_alarms", REPO / "tools" / "false_alarms.py")
tool = _load("corpus_tool_for_counts", REPO / "tools" / "corpus.py")


@pytest.fixture(scope="module")
def counts() -> dict:
    return page.load()


# ------------------------------------------------------------------ the committed page


def test_the_page_is_the_one_the_script_draws_from_the_counts() -> None:
    """It is committed, so counts drawn again that nobody drew the page from would leave it
    giving the old shares."""
    for path, text in page.drawn().items():
        on_disk = REPO / path
        assert on_disk.is_file(), f"{path} is missing: run python tools/false_alarms.py"
        assert on_disk.read_text("utf-8") == text, f"{path} is stale: run tools/false_alarms.py"


def test_the_readme_quotes_the_shares_the_counts_give_in_its_status(counts: dict) -> None:
    readme = (REPO / "README.md").read_text("utf-8")
    status = readme.split("\n## Status\n", 1)[1].split("\n## ", 1)[0]
    line = page.readme_line(page.Counts(counts))
    assert line in status.split("\n"), "the README's line is stale: run tools/false_alarms.py"
    assert page.with_line(readme, line) == readme


def test_the_page_is_linked_from_the_readme_and_the_corpus_page() -> None:
    assert "](docs/false-alarms.md)" in (REPO / "README.md").read_text("utf-8")
    assert "](false-alarms.md)" in (REPO / "docs" / "corpus.md").read_text("utf-8")


def test_the_committed_counts_hold_counts_only(counts: dict) -> None:
    page.check(counts)  # as `load` does; named here so that a reader finds it
    text = (REPO / "docs" / "false-alarms.yaml").read_text("utf-8")
    body = "\n".join(line for line in text.split("\n") if not line.startswith("#"))
    # Nothing of a sentence: no quotation mark of a message, no word run of prose.
    assert "message" not in body and "context" not in body and '"' not in body


def test_every_field_of_the_tuning_papers_has_its_name(counts: dict) -> None:
    fields = {said[1] for said in counts["tuning"]["papers"].values()}
    assert fields <= set(page.FIELDS), sorted(fields - set(page.FIELDS))
    sources = {said[2] for said in counts["tuning"]["papers"].values()}
    assert sources <= set(page.SOURCES), sorted(sources - set(page.SOURCES))


def test_the_held_out_papers_are_numbered_and_their_rows_name_no_code(counts: dict) -> None:
    held = counts.get("heldout")
    if held is None:
        pytest.skip("no held-out set measured yet")
    assert all(page.HELD.fullmatch(name) and said in page.FORMATS
               for name, said in held["papers"].items())  # fmt: skip
    assert all(len(row) == 5 and not page.CODE.fullmatch(str(row[1])) for row in held["strata"])
    drawn = page.page(page.Counts(counts))
    section = drawn.split("## Papers held out from the tuning", 1)[1].split("\n## ", 1)[0]
    assert "`G" not in section and "`audit/" not in section


# ------------------------------------------------------------ the counts hold counts only


def _corrupt(document: dict, how: str) -> dict:
    changed = copy.deepcopy(document)
    tuning = changed["tuning"]
    paper = next(iter(tuning["papers"]))
    if how == "a message in a row":
        tuning["strata"][0] = [*tuning["strata"][0][:3], "Studies show that", 1, 0]
    elif how == "a title beside a paper":
        tuning["papers"][paper] = [*tuning["papers"][paper], "A Study of Things"]
    elif how == "a field in words":
        tuning["papers"][paper] = ["docx", "a field of its own", "zenodo"]
    elif how == "a key of its own":
        tuning["sentences"] = ["Studies show that"]
    elif how == "more judged than given":
        row = tuning["strata"][0]
        tuning["strata"][0] = [*row[:3], row[3], row[3] + 1, 0]
    elif how == "a code of the held-out set":
        changed["heldout"]["strata"][0] = ["h01", "audit", "G6/ai-phrasing", 1, 1, 0]
    elif how == "a field of a held-out paper":
        changed["heldout"]["papers"]["h01"] = ["docx", "psych"]
    elif how == "a held-out paper by its slug":
        changed["heldout"]["papers"]["docx-psych-C3"] = "docx"
    elif how == "a reason in words":
        tuning["verdicts"]["left_out"] = {"studies show the moon is cheese": 1}
    elif how == "a field as a phrase":
        tuning["papers"][paper] = ["docx", "psychology-of-the-moon-trial", "zenodo"]
    elif how == "a source as a phrase":
        tuning["papers"][paper] = ["docx", "psych", "the-moon-is-cheese"]
    elif how == "a slug as a phrase":
        said = tuning["papers"].pop(paper)
        tuning["papers"]["studies-show-the-moon-is-cheese"] = said
        tuning["strata"] = [["studies-show-the-moon-is-cheese", *row[1:]] if row[0] == paper
                            else row for row in tuning["strata"]]
    elif how == "a run named in words":
        tuning["run"] = "the-moon-is-cheese"
    return changed


@pytest.mark.parametrize("how", ["a message in a row", "a title beside a paper",
                                 "a field in words", "a key of its own",
                                 "more judged than given", "a code of the held-out set",
                                 "a field of a held-out paper",
                                 "a held-out paper by its slug", "a reason in words",
                                 "a field as a phrase", "a source as a phrase",
                                 "a slug as a phrase", "a run named in words"])  # fmt: skip
def test_counts_that_hold_more_than_counts_are_refused(how: str) -> None:
    with pytest.raises(page.CountsError):
        page.check(_corrupt(MINI, how))


# -------------------------------------------------------------- the shares and intervals


def test_a_share_weighs_each_paper_s_judged_warnings_by_all_it_gave() -> None:
    """Ten judged of a hundred, all true, and two of two, both false: 2 of the 12 judged
    are false, but 2 of the 102 warnings."""
    said = page.share([("a", 100, 10, 0), ("b", 2, 0, 2)])
    assert (said.warnings, said.true, said.false, said.papers) == (102, 10, 2, 2)
    assert said.share == pytest.approx(2 / 102)


def test_a_share_with_no_false_warning_still_has_an_interval() -> None:
    """Resampling papers whose judged warnings are all true gives nothing but 0%."""
    said = page.share([(f"p{n}", 2, 2, 0) for n in range(7)] + [("q", 1, 1, 0)])
    assert said.share == 0 and said.low == 0
    assert said.high == pytest.approx(page.wilson(0.0, 15)[1]) and said.high > 0.2


def test_false_alarms_in_one_paper_widen_the_interval_past_wilson_s() -> None:
    """Five false in one paper of ten: Wilson's interval at 5 of 50 is too narrow for
    papers drawn again."""
    rows = [(f"p{n}", 5, 5, 0) for n in range(9)] + [("bad", 5, 0, 5)]
    said = page.share(rows)
    assert said.share == pytest.approx(0.1)
    assert said.high > page.wilson(0.1, 50)[1] + 0.05


def test_the_same_counts_give_the_same_interval() -> None:
    rows = [(f"p{n}", 3 + n, 2, n % 2) for n in range(8)]
    assert page.share(rows) == page.share(list(reversed(rows)))


def test_every_interval_on_the_page_holds_its_share(counts: dict) -> None:
    measured = page.Counts(counts)
    for code in measured.codes():
        said = measured.code(code)
        assert said.low <= said.share <= said.high, code


@pytest.mark.parametrize(("rows", "shown"), [
    ([("a", 5, 3, 0), ("b", 5, 3, 0), ("c", 5, 3, 0)], False),  # 9 judged
    ([("a", 10, 5, 0), ("b", 10, 5, 0)], False),  # 10 judged, 2 papers
    ([("a", 5, 4, 0), ("b", 5, 3, 0), ("c", 5, 3, 0)], True),  # 10 judged, 3 papers
])  # fmt: skip
def test_a_share_is_given_from_ten_judged_warnings_from_three_papers(rows: list,
                                                                      shown: bool) -> None:
    assert page.share(rows).shown is shown


def test_a_code_under_the_bar_gets_its_counts_and_no_share() -> None:
    drawn = page.page(page.Counts(MINI))
    shares, few = drawn.split("## Codes with too few judged warnings")
    few = few.split("\n## ", 1)[0]
    assert "`G14/abbreviation-unused`" in shares
    assert "`G6/ai-phrasing`" in few and "`G6/ai-phrasing`" not in shares
    assert "| `G6/ai-phrasing` | audit, check | 6 | 2 | 1 | 1 | 1 |" in few


def test_audit_leads_and_check_s_main_code_is_named() -> None:
    measured = page.Counts(MINI)
    drawn = page.page(measured)
    in_all = drawn.split("## In all", 1)[1].split("\n## ", 1)[0]
    assert in_all.index("| `audit` |") < in_all.index("| `check` |")
    assert "`G7/reference-uncited`, so its share is mostly that code's" in in_all
    line = page.readme_line(measured)
    assert line.startswith(page.README_START + " were measured on 4 real papers with 0.2.503: "
                           "of the warnings `audit` gives about a paper, ")
    assert "most of them `G7/reference-uncited`" in line and "held out" in line


def test_given_by_names_every_command_that_gave_the_code(counts: dict) -> None:
    """A code's warnings add up every command that gave it, whether or not that command's
    warnings were judged, so "given by" names every one of them."""
    measured = page.Counts(counts)
    drawn = page.page(measured)
    for code in measured.codes():
        gave = {page.COMMANDS[report] for report, codes in counts["tuning"]["given"].items()
                if code in codes}  # fmt: skip
        cell = ", ".join(c for c in page.ORDER if c in gave)
        assert f"| `{code}` | {cell} | {page.number(measured.warnings(code=code))} |" in drawn


def test_the_pdfs_are_compared_by_the_shares_the_counts_give() -> None:
    """The tuning papers hold journals' PDFs as the held-out ones do, so the page says no
    more of them than the two shares."""
    measured = page.Counts(MINI)
    drawn = page.page(measured)
    tuning, held = measured.overall("audit", "pdf"), measured.held("audit", "pdf")
    assert (f"`audit`'s share false on the held-out PDFs was {page.percent(held.share)}, "
            f"against {page.percent(tuning.share)} on the tuning PDFs") in drawn
    assert "typeset them" not in drawn


def test_every_code_in_the_counts_is_one_the_package_writes(counts: dict) -> None:
    source = "\n".join(p.read_text("utf-8") for p in (REPO / "src").rglob("*.py"))
    codes = {code for codes in counts["tuning"]["given"].values() for code in codes}
    unwritten = sorted(c for c in codes if f'"{c.split("/", 1)[1]}"' not in source)
    assert not unwritten, f"no code of the package writes {unwritten}"


def test_the_readme_line_is_put_in_place_of_the_one_there() -> None:
    readme = "# R\n\n## Status\n\n- **False alarms** old\n- other\n"
    assert page.with_line(readme, "- **False alarms** new") == (
        "# R\n\n## Status\n\n- **False alarms** new\n- other\n")
    with pytest.raises(page.CountsError):
        page.with_line("# R\n", "- **False alarms** new")


#: A made-up counts file, as `counts` writes one: four papers, a code over the bar, one
#: under, a code that makes most of `check`'s warnings, and a held-out set.
MINI = {
    "tuning": {
        "run": "main-012345678", "commit": "0123456789abcdef0123456789abcdef01234567",
        "version": "0.2.503", "date": "2026-11-25",
        "verdicts": {"first": 20, "batches": 6, "left_out": {"verdict unclear": 1}},
        "papers": {"docx-psych-A1": ["docx", "psych", "osf:psyarxiv"],
                   "docx-med-A2": ["docx", "med", "zenodo"],
                   "pdf-med-B1": ["pdf", "med", "pmc"],
                   "tex-stat-ap-C1": ["latex", "stat-ap", "arxiv"]},
        "given": {"audit": {"G6/ai-phrasing": 4, "G14/abbreviation-unused": 30},
                  "check": {"G7/reference-uncited": 300, "G14/abbreviation-unused": 4,
                            "G6/ai-phrasing": 2},
                  "compare": {"G14/abbreviation-unused": 1}},
        "strata": [
            ["docx-psych-A1", "audit", "G6/ai-phrasing", 4, 1, 1],
            ["docx-psych-A1", "audit", "G14/abbreviation-unused", 10, 4, 1],
            ["docx-med-A2", "audit", "G14/abbreviation-unused", 10, 5, 0],
            ["pdf-med-B1", "audit", "G14/abbreviation-unused", 10, 3, 2],
            ["tex-stat-ap-C1", "check", "G7/reference-uncited", 300, 10, 0],
            ["tex-stat-ap-C1", "check", "G14/abbreviation-unused", 4, 3, 1],
            ["tex-stat-ap-C1", "compare", "G14/abbreviation-unused", 1, 1, 0],
        ],
    },
    "heldout": {
        "run": "main-abcdef012", "commit": "abcdef0123456789abcdef0123456789abcdef01",
        "version": "0.2.502", "milestone": 1,
        "papers": {"h01": "docx", "h02": "pdf"},
        "strata": [["h01", "audit", 3, 2, 1], ["h02", "audit", 5, 1, 4],
                   ["h01", "check", 2, 2, 0]],
    },
}  # fmt: skip


def test_the_made_up_counts_are_counts() -> None:
    page.check(MINI)


# ------------------------------------------------------- counting a made-up mini corpus

SECRET = "Studies show the moon is cheese"
#: A main run's name, its commit's first nine characters after `main-`.
RUN_NAME = "main-012345678"


def warn(code: str, message: str, line: int, **extra) -> dict:
    gate, name = code.split("/")
    return {"gate": gate, "code": name, "message": message, "severity": "warn", "line": line,
            "path": "paper.docx", "context": f"{SECRET}, line {line}", **extra}  # fmt: skip


#: The judged findings, each with its verdict, and what the run gives.
JUDGED = [
    (warn("G14/abbreviation-unused", "'ABC' is defined and never used", 5), "true"),
    (warn("G14/abbreviation-unused", "'DEF' is defined and never used", 9), "false"),
    (warn("G6/vague-attribution", f"'{SECRET}' with no citation nearby", 12), "true"),
]
RUN = [
    warn("G14/abbreviation-unused", "'ABC' is defined and never used", 5),
    warn("G14/abbreviation-unused", "'DEF' is defined and never used", 9),
    warn("G14/abbreviation-unused", "'GHI' is defined and never used", 20),  # no verdict
    # the judged vague attribution, now a question: it accuses nothing
    {**warn("G6/vague-attribution", f"'{SECRET}' with no citation nearby", 12),
     "severity": "info", "question": True},
    # a reading notice, loud: never counted
    {**warn("audit/not-audited", "Limitations, read as the reference list", 30)},
]


def mini_corpus(root: Path, slug: str = "docx-psych-A1") -> Path:
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    packet = [{"slug": slug, "text": SECRET, "reports": {"audit": {
        "findings": [f for f, _ in JUDGED]}}}]
    verdicts = [{"slug": slug, "report": "audit", "index": i, "verdict": v,
                 "gate": f["gate"], "code": f["code"], "why": SECRET}
                for i, (f, v) in enumerate(JUDGED)]  # fmt: skip
    (root / "report" / "packets" / "psych.json").write_text(json.dumps(packet), "utf-8")
    (root / "report" / "judged" / "psych.json").write_text(json.dumps(verdicts), "utf-8")
    (root / "corpus" / slug).mkdir(parents=True)
    (root / "corpus" / slug / "meta.json").write_text(json.dumps({
        "slug": slug, "format": "docx", "field": "psych", "source": "osf:psyarxiv",
        "main": "paper.docx", "title": SECRET}), "utf-8")
    run = root / "runs" / RUN_NAME
    (run / slug).mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"commit": "0123456789", "version": "0.2.503",
                                              "sha": "0123456789" * 4}), "utf-8")
    (run / slug / "audit.json").write_text(json.dumps({"findings": RUN}), "utf-8")
    return root


def test_counts_holds_the_judged_warnings_reported_under_their_code(tmp_path: Path) -> None:
    root, out = mini_corpus(tmp_path / "corpus"), tmp_path / "false-alarms.yaml"
    assert tool.main(["--corpus", str(root), "counts", RUN_NAME, "--out", str(out)]) == 0
    written = yaml.safe_load(out.read_text("utf-8"))
    tuning = written["tuning"]
    assert tuning["papers"] == {"docx-psych-A1": ["docx", "psych", "osf:psyarxiv"]}
    # The notice and the question are no warning; the vague attribution, asked now, no row.
    assert tuning["given"] == {"audit": {"G14/abbreviation-unused": 3}}
    assert tuning["strata"] == [["docx-psych-A1", "audit", "G14/abbreviation-unused", 3, 1, 1]]
    assert tuning["verdicts"] == {"first": 3, "batches": 0, "left_out": {}}
    assert (tuning["run"], tuning["version"]) == (RUN_NAME, "0.2.503")
    assert "heldout" not in written
    # Nothing of the paper's text, title, findings or verdicts' reasons is written.
    assert "moon" not in out.read_text("utf-8") and "never used" not in out.read_text("utf-8")


def test_counts_keeps_the_held_out_section_unless_it_is_counted_again(tmp_path: Path) -> None:
    root, out = mini_corpus(tmp_path / "corpus"), tmp_path / "false-alarms.yaml"
    held = mini_corpus(tmp_path / "held", "pdf-med-X9")
    assert tool.main(["--corpus", str(root), "counts", RUN_NAME, "--heldout", str(held),
                      RUN_NAME, "--milestone", "2", "--out", str(out)]) == 0  # fmt: skip
    section = yaml.safe_load(out.read_text("utf-8"))["heldout"]
    # Numbered, by format alone (this one's meta says docx), its row naming no code.
    assert section["papers"] == {"h01": "docx"} and section["milestone"] == 2
    assert section["strata"] == [["h01", "audit", 3, 1, 1]]
    assert "pdf-med-X9" not in out.read_text("utf-8")
    assert tool.main(["--corpus", str(root), "counts", RUN_NAME, "--out", str(out)]) == 0
    assert yaml.safe_load(out.read_text("utf-8"))["heldout"] == section


def test_counts_of_the_held_out_set_need_its_milestone(tmp_path: Path, capsys) -> None:
    root, out = mini_corpus(tmp_path / "corpus"), tmp_path / "false-alarms.yaml"
    assert tool.main(["--corpus", str(root), "counts", RUN_NAME, "--milestone", "1",
                      "--out", str(out)]) == 2  # fmt: skip
    assert "--heldout and --milestone" in capsys.readouterr().err
    assert not out.exists()


def test_counts_that_would_hold_more_than_counts_are_not_written(tmp_path: Path,
                                                                 capsys) -> None:  # fmt: skip
    root, out = mini_corpus(tmp_path / "corpus"), tmp_path / "false-alarms.yaml"
    meta = root / "corpus" / "docx-psych-A1" / "meta.json"
    meta.write_text(json.dumps({**json.loads(meta.read_text("utf-8")),
                                "field": "Psychology of the moon"}), "utf-8")  # fmt: skip
    assert tool.main(["--corpus", str(root), "counts", RUN_NAME, "--out", str(out)]) == 2
    assert "field" in capsys.readouterr().err and not out.exists()
