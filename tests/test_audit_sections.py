"""`audit` reads anything a paper is written in, and what needs no outputs.

A LaTeX paper through its include tree, its tables as rows of cells; `--against` optional,
with the report saying at its top that nothing was compared; the report in sections, and as
JSON; G6 and G14 on a project made for the paper; G7's census of the reference list, and the
registries asked only with `--lookup`, here on a loopback port and nowhere else.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from manuscript_guard.audit import audit
from manuscript_guard.auditing import references as references_module
from manuscript_guard.auditing.references import census_of_text, markers_in
from manuscript_guard.cli import main
from manuscript_guard.lookup import run as lookup
from manuscript_guard.lookup.http import NoAnswer, Request, default_transport
from manuscript_guard.text.latex.structure import read_tree
from manuscript_guard.text.latex.tables import latex_tables

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
BS = chr(92)

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def tex(text: str) -> str:
    """LaTeX written with `!` for each backslash, so that none is lost on the way here."""
    return text.replace("!", BS)


def make_docx(path: Path, paragraphs: list[str], heading: str | None = None) -> Path:
    styles = (f"<w:styles {NS}><w:style w:type='paragraph' w:styleId='Heading1'>"
              "<w:name w:val='heading 1'/></w:style></w:styles>")  # fmt: skip
    body = ""
    for text in paragraphs:
        styled = "<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>" if text == heading else ""
        body += f"<w:p>{styled}<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", (2020, 1, 1, 0, 0, 0)), document)
        archive.writestr(zipfile.ZipInfo("word/styles.xml", (2020, 1, 1, 0, 0, 0)), styles)
    return path


def _source(text: str):
    return read_tree({"paper.tex": text}, "paper.tex").sources[0]


# ---------------------------------------------------------------------- a LaTeX table's cells


TABLE = tex(
    "!documentclass{article}\n"
    "!begin{document}\n"
    "!begin{tabular}{lrr}\n"
    "!toprule\n"
    " & Cases (n = 40) & Controls (n = 40) !!\n"
    "!midrule\n"
    "Male & 12 (30.0!%) & !multicolumn{1}{c}{20 (50.0)} !![2pt]\n"
    "!multirow{2}{*}{Age} & 40 & 41 !! !cline{2-3}\n"
    "A !& B & !makecell{1!!2} & 3 !! % 4 & 5 !!\n"
    "!multicolumn{2}{l}{Total} & 81 !tabularnewline\n"
    "!bottomrule\n"
    "!end{tabular}\n"
    "!end{document}\n"
)


def test_a_latex_table_is_read_as_rows_of_cells_where_latex_splits_them() -> None:
    """A row at each `!!` and `!tabularnewline`, a cell at each `&`: not an escaped one, not
    one in a comment, not a `!!` inside braces. Rules are no row, a `!multicolumn` spans
    its columns, a `!multirow` prints its text, and the space after `!![2pt]` is not read."""
    [table] = latex_tables(_source(TABLE))
    assert [[(c.text, c.line, c.span) for c in row] for row in table] == [
        [("", 5, 1), ("Cases (n = 40)", 5, 1), ("Controls (n = 40)", 5, 1)],
        [("Male", 7, 1), ("12 (30.0%)", 7, 1), ("20 (50.0)", 7, 1)],
        [("Age", 8, 1), ("40", 8, 1), ("41", 8, 1)],
        [("A & B", 9, 1), ("1 2", 9, 1), ("3", 9, 1)],
        [("Total", 10, 2), ("81", 10, 1)],
    ]


def test_a_table_with_a_width_reads_its_rows_after_its_column_specification() -> None:
    text = tex("!begin{document}\n!begin{tabular*}{!linewidth}{@{}l{r}}\nA & 1 !!\n"
               "!end{tabular*}\n!end{document}\n")  # fmt: skip
    [table] = latex_tables(_source(text))
    assert [[c.text for c in row] for row in table] == [["A", "1"]]


# ---------------------------------------------------------------------------- a LaTeX paper


PAPER = tex(
    "!documentclass{article}\n"
    "!begin{document}\n"
    "!section{Results}\n"
    "Of 412 reports, the odds ratio was 2.10 !cite{smith}.\n"
    "!input{tables}\n"
    "!begin{thebibliography}{9}\n"
    "!bibitem{smith} Smith J. Lancet. 2019;393:100-10. doi:10.5555/fictional.1\n"
    "!end{thebibliography}\n"
    "!end{document}\n"
)
TABLES = tex(
    "!begin{tabular}{lr}\n"
    "& Cases (n = 40) !!\n"
    "Male & 12 (35.0!%) !!\n"
    "Female & 28 (70.0!%) !!\n"
    "!end{tabular}\n"
)


@pytest.fixture
def latex_paper(tmp_path: Path) -> Path:
    folder = tmp_path / "paper"
    folder.mkdir()
    (folder / "paper.tex").write_text(PAPER, encoding="utf-8")
    (folder / "tables.tex").write_text(TABLES, encoding="utf-8")
    (folder / "old-draft.tex").write_text("An old draft, 999 cases.\n", encoding="utf-8")
    (tmp_path / "out.csv").write_text("n,or\n412,2.10\n", encoding="utf-8")
    return folder


def test_a_latex_paper_is_read_through_the_files_it_inputs(latex_paper: Path) -> None:
    """Its numbers where they print, at the `.tex` line; its `thebibliography` cut and named;
    a file of the folder that nothing inputs passed over, not read."""
    report = audit([latex_paper / "paper.tex"], [latex_paper.parent / "out.csv"])
    assert {path.name for path in report.papers} == {"paper.tex", "tables.tex"}
    assert not [c for c in report.unmatched if c.source.name == "paper.tex"]
    assert ("tables.tex", 3, "12") in {(c.source.name, c.line, c.text) for c in report.unmatched}
    assert report.not_audited == ["paper.tex: lines 6-8, read as the reference list"]
    assert any("old-draft.tex" in said for said in report.passed_over)
    assert not any(c.text == "999" for c in report.unmatched)


def test_a_share_in_a_latex_table_is_held_to_its_denominator(latex_paper: Path) -> None:
    report = audit([latex_paper / "paper.tex"], None)
    off = [(d.source.name, d.line) for d in report.disagreements]
    assert off == [("tables.tex", 3)], report.disagreements


def test_in_a_folder_only_a_file_with_a_document_class_starts_a_paper(
    latex_paper: Path, capsys
) -> None:
    assert main(["audit", str(latex_paper), "--against", str(latex_paper.parent / "out.csv")]) == 0
    out = capsys.readouterr().out
    assert "Audited 2 file(s)" in out and "old-draft.tex" in out


def test_a_folder_of_latex_with_no_document_class_has_nothing_to_audit(tmp_path: Path, capsys):
    (tmp_path / "part.tex").write_text("Of 412 reports.\n", encoding="utf-8")
    assert main(["audit", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "nothing to audit" in err and "part.tex" in err


def test_a_stretch_the_latex_reader_refuses_fails_strict(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(tex("!documentclass{article}\n!begin{document}\nOf 412.\n"
                         "!input{missing}\n!end{document}\n"), encoding="utf-8")  # fmt: skip
    assert main(["audit", str(paper)]) == 0
    assert main(["audit", str(paper), "--strict"]) == 1
    assert "missing" in capsys.readouterr().out


# ---------------------------------------------------------------------------- no outputs


def test_without_outputs_nothing_is_compared_and_the_report_says_so(tmp_path: Path, capsys):
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nThe ratio was 9.99 (t = 2.0, df = 100, P = 0.9).\n",
                     encoding="utf-8")  # fmt: skip
    assert main(["audit", str(paper), "--strict"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].endswith("No outputs given: no number was compared with the "
                                        "analysis.")  # fmt: skip
    assert "What a match is worth" not in out and "NOT FOUND" not in out
    assert "=== Arithmetic ===" in out and "P" in out


def test_without_outputs_a_paper_with_no_number_still_fails_strict(tmp_path: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nNothing here.\n", encoding="utf-8")
    assert main(["audit", str(paper), "--strict"]) == 1
    assert main(["audit", str(paper)]) == 0


def test_the_json_report_counts_what_strict_counts(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nThe ratio was 9.99, in 412 reports.\n", encoding="utf-8")
    outputs = tmp_path / "out.csv"
    outputs.write_text("n\n412\n", encoding="utf-8")
    assert main(["audit", str(paper), "--against", str(outputs), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["ok"] is False and said["compared"] is True
    counted = [f for f in said["findings"] if f["counted"]]
    assert [(f["section"], f["code"], f["line"]) for f in counted] == [
        ("Membership", "not-found", 3)
    ]
    assert said["what_a_match_is_worth"]["integers_1_100"] == 0.0
    assert main(["audit", str(paper), "--against", str(outputs), "--strict", "--json"]) == 1


# ---------------------------------------------------------------------------- G6 and G14


WORDS = (
    "# Methods\n\nIn response to the reviewer, we added a sensitivity analysis. The color of "
    "the PDA was recorded.\n\n# Results\n\nThe color was recorded in 412 cases.\n"
)


def test_g6_and_g14_read_a_markdown_paper_at_its_own_path(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(WORDS, encoding="utf-8")
    assert main(["audit", str(paper), "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["findings"]
    residue = [f for f in found if f["code"] == "revision-residue"]
    assert [(f["gate"], f["severity"], f["counted"], Path(f["path"]).name, f["line"])
            for f in residue] == [("G6", "warn", False, "paper.md", 3)]  # fmt: skip
    assert any(f["gate"] == "G14" and "PDA" in f["message"] for f in found), found
    assert not any("mg-audit-" in json.dumps(f) for f in found)


def test_submission_residue_and_english_are_what_check_reads(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(WORDS, encoding="utf-8")
    assert main(["audit", str(paper), "--json", "--submission-residue",
                 "--english", "british", "--strict"]) == 0  # fmt: skip
    found = json.loads(capsys.readouterr().out)["findings"]
    assert [f["severity"] for f in found if f["code"] == "revision-residue"] == ["fail"]
    spelt = [f for f in found if f["gate"] == "G14" and "color" in f["message"]]
    assert spelt and all(not f["counted"] for f in spelt), found


@needs_pandoc
def test_g6_and_g14_read_a_docx_as_init_from_converts_it(tmp_path: Path, capsys) -> None:
    (tmp_path / "paper.md").write_text("# Methods\n\nIn response to the reviewer, we added 12 "
                                       "cases.\n", encoding="utf-8")  # fmt: skip
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    assert main(["audit", str(tmp_path / "paper.docx"), "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["findings"]
    residue = [f for f in found if f["code"] == "revision-residue"]
    assert [Path(f["path"]).name for f in residue] == ["paper.docx"], found


def test_without_pandoc_a_docx_is_not_converted_and_says_so(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import document

    def absent() -> str:
        raise document.BuildError("pandoc is not on PATH")

    monkeypatch.setattr(document, "pandoc", absent)
    paper = make_docx(tmp_path / "paper.docx", ["In response to the reviewer, 12 cases."])
    assert main(["audit", str(paper)]) == 0
    out = capsys.readouterr().out
    assert "G6 and G14 were not run on paper.docx" in out and "pandoc" in out


# ---------------------------------------------------------------------------- G7's census


NUMBERED = (
    "# Results\n\nThe rate rose [1], as before [2, 4], with a median of 64 [55-72] days [5].\n\n"
    "# References\n\n"
    "1. Smith J. A cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1\n"
    "2. Jones K. A trial. BMJ 2020;370:m1. PMID: 31000001\n"
    "3. Brown L. A note. Drug Saf. 2021;44:1-2.\n"
    "4. Green M. A review. Pharmacoepidemiol Drug Saf. 2018;27:3-4.\n"
)


def test_a_numbered_list_is_held_to_the_citations_by_number(tmp_path: Path) -> None:
    """[5] cites what the list does not hold, entry 3 is cited nowhere, and the interval after
    the median is no citation."""
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    [census] = audit([paper], None).references
    assert (len(census.entries), census.dois, census.pmids, census.style) == (4, 1, 1, "numbered")
    assert [(p.code, p.line) for p in census.problems] == [
        ("citation-beyond-list", 3), ("entry-never-cited", 9)
    ]
    assert "[5] cites entry 5" in census.problems[0].message


def test_a_docx_list_word_numbers_is_numbered_by_place(tmp_path: Path) -> None:
    paper = make_docx(tmp_path / "paper.docx", [
        "The rate rose [1, 3].", "References",
        "Smith J. A cohort. Lancet. 2019;393:100-10.", "Jones K. A trial. BMJ 2020;370:m1.",
    ], heading="References")  # fmt: skip
    [census] = audit([paper], None).references
    assert census.style == "numbered by place"
    # A .docx is read a paragraph to a line, after the line its body opens with.
    assert [(p.code, p.line) for p in census.problems] == [
        ("citation-beyond-list", 2), ("entry-never-cited", 5)
    ]


def test_an_author_year_list_is_counted_and_not_held_to_numbers(tmp_path: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nThe rate rose (Smith 2019) [7].\n\n# References\n\n"
                     "Smith, J. (2019). A cohort. Lancet, 393, 100.\n", encoding="utf-8")
    [census] = audit([paper], None).references
    assert (len(census.entries), census.style, census.problems) == (1, "not numbered", [])


def test_an_interval_after_its_value_is_no_citation() -> None:
    assert markers_in("a median of 64 [55-72] and [3]", [(15, 22)]) == [(1, "[3]", [3])]


def test_with_no_list_under_a_heading_nothing_is_counted(tmp_path: Path) -> None:
    census = census_of_text(tmp_path / "p.md", "Text [1].\n", [], "Text [1].\n", [], docx=False)
    assert census.entries == () and "no reference list" in census.note


def test_a_latex_cite_is_held_to_the_bibitems(tmp_path: Path) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(tex("!documentclass{article}\n!begin{document}\nSee !cite{a,b}.\n"
                         "!begin{thebibliography}{9}\n!bibitem{a} A.\n!bibitem{c} C.\n"
                         "!end{thebibliography}\n!end{document}\n"), encoding="utf-8")
    [census] = audit([paper], None).references
    assert [(p.code, p.line) for p in census.problems] == [
        ("citation-not-listed", 3), ("entry-never-cited", 6)
    ]


# ---------------------------------------------------------------------------- G7's lookup


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        self.server.seen.append(self.path)
        name = self.path.strip("/").split("/")[0]
        status, data = self.server.answers.get(name, (404, {}))
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


DOI = "10.5555/fictional.1"
PACER = lookup.Pacer
RETRACTED = {
    "status": "ok", "message-type": "work",
    "message": {"DOI": DOI, "type": "journal-article", "title": ["A cohort"],
                "updated-by": [{"type": "retraction", "DOI": "10.5555/notice",
                                "updated": {"date-parts": [[2022, 1, 2]]}}]},
}  # fmt: skip


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch):
    """A loopback server standing in for Crossref, OpenAlex and PubMed, which the audit is
    pointed at: no test reaches a registry."""
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []
    httpd.answers = {
        "crossref": (200, RETRACTED),
        "openalex": (200, {"id": "W1", "is_retracted": True, "title": "A cohort"}),
        "pubmed": (200, {"header": {"type": "esummary"}, "result": {"uids": ["31000001"],
                   "31000001": {"uid": "31000001", "title": "A trial.", "pubtype": [
                       "Journal Article"], "articleids": []}}}),
    }
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        default_transport(Request(url + "/probe"), 5)
    except NoAnswer as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    services = lookup.Services(crossref=f"{url}/crossref/", openalex=f"{url}/openalex/doi:",
                               datacite=f"{url}/datacite/", doi_org=f"{url}/doi_org/",
                               pubmed=f"{url}/pubmed/esummary.fcgi")  # fmt: skip
    monkeypatch.setattr(lookup, "Services", lambda: services)
    monkeypatch.setattr(lookup, "Pacer", lambda: PACER(sleep=lambda seconds: None))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_nothing_is_sent_without_lookup(tmp_path: Path, registries, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", str(paper)]) == 0
    assert registries.seen == []
    assert "Nothing was looked up" in capsys.readouterr().out


def test_a_dry_run_lists_what_would_be_sent_and_sends_nothing(tmp_path: Path, registries,
                                                               capsys) -> None:  # fmt: skip
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", str(paper), "--lookup", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert registries.seen == []
    assert f"would ask Crossref and OpenAlex for doi:{DOI} (entry 1)" in out
    assert "would ask PubMed for PMID 31000001 (entry 2)" in out


def test_a_retracted_work_is_said_and_kept_only_where_asked(tmp_path: Path, registries,
                                                            capsys) -> None:  # fmt: skip
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", str(paper), "--lookup", "--strict", "--against", str(paper)]) == 0
    out = capsys.readouterr().out
    assert "entry 1 is retracted, by what Crossref and OpenAlex say" in out
    assert registries.seen and not list(tmp_path.rglob("*.json"))
    cache = tmp_path / "kept"
    assert main(["audit", str(paper), "--lookup", "--lookup-cache", str(cache)]) == 0
    capsys.readouterr()
    asked = len(registries.seen)
    assert sorted(p.name for p in cache.iterdir()) == [
        "doi_10.5555_fictional.1.json", "pmid_31000001.json"
    ]
    assert main(["audit", str(paper), "--lookup", "--lookup-cache", str(cache)]) == 0
    assert len(registries.seen) == asked, "a kept record is read, not asked for again"
    assert "entry 1 is retracted" in capsys.readouterr().out


def test_lookup_options_go_with_lookup(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", str(paper), "--dry-run"]) == 2
    assert "--lookup" in capsys.readouterr().err


def test_an_answer_that_did_not_come_is_said_and_not_kept(tmp_path: Path) -> None:
    def fails(request, timeout):
        raise NoAnswer("refused")

    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    report = audit([paper], None)
    cache = tmp_path / "kept"
    looked = references_module.look_up(report.references, cache=cache, transport=fails,
                                       pacer=lookup.Pacer(sleep=lambda s: None))  # fmt: skip
    assert any(p.code == "lookup-unanswered" for one in looked for p in one.problems)
    assert not cache.exists() or not list(cache.iterdir())
