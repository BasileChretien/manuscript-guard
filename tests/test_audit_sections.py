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


#: Two numberings of one count, decimal from 1 ("1."), and one of bullets.
NUMBERINGS = (
    f"<w:numbering {NS}>"
    "<w:abstractNum w:abstractNumId='0'><w:lvl w:ilvl='0'><w:start w:val='1'/>"
    "<w:numFmt w:val='decimal'/><w:lvlText w:val='%1.'/></w:lvl></w:abstractNum>"
    "<w:abstractNum w:abstractNumId='1'><w:lvl w:ilvl='0'><w:start w:val='1'/>"
    "<w:numFmt w:val='bullet'/><w:lvlText w:val='-'/></w:lvl></w:abstractNum>"
    "<w:num w:numId='1'><w:abstractNumId w:val='0'/></w:num>"
    "<w:num w:numId='2'><w:abstractNumId w:val='1'/></w:num>"
    "<w:num w:numId='3'><w:abstractNumId w:val='0'/></w:num>"
    "</w:numbering>"
)


def make_docx(
    path: Path, paragraphs: list[str], heading: str | None = None,
    numbered: dict[str, str] | None = None, numberings: str = "",
) -> Path:  # fmt: skip
    """A .docx of `paragraphs`, `heading` styled as one, and each of `numbered` numbered by
    Word with the numbering it names (`NUMBERINGS`, or `numberings`), or with the
    paragraph properties it gives, where they start with `<`."""
    styles = (f"<w:styles {NS}><w:style w:type='paragraph' w:styleId='Heading1'>"
              "<w:name w:val='heading 1'/></w:style></w:styles>")  # fmt: skip
    body = ""
    for text in paragraphs:
        styled = "<w:pStyle w:val='Heading1'/>" if text == heading else ""
        num = (numbered or {}).get(text)
        if num is not None and num.startswith("<"):
            styled += num
        elif num is not None:
            styled += f"<w:numPr><w:ilvl w:val='0'/><w:numId w:val='{num}'/></w:numPr>"
        styled = f"<w:pPr>{styled}</w:pPr>" if styled else ""
        body += f"<w:p>{styled}<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", (2020, 1, 1, 0, 0, 0)), document)
        archive.writestr(zipfile.ZipInfo("word/styles.xml", (2020, 1, 1, 0, 0, 0)), styles)
        if numbered:
            archive.writestr(zipfile.ZipInfo("word/numbering.xml", (2020, 1, 1, 0, 0, 0)),
                             numberings or NUMBERINGS)  # fmt: skip
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


def _document(text: str) -> str:
    return tex(f"!documentclass{{article}}\n!begin{{document}}\n{text}\n!end{{document}}\n")


def test_two_documents_in_a_folder_are_two_papers_and_neither_is_refused(
    tmp_path: Path, capsys
) -> None:
    """Round 1 of #463: each of a folder's complete documents is an entry, read as one, and
    the other's `tex-second-document` refusal is no stretch that could not be read."""
    (tmp_path / "main.tex").write_text(_document("Of 412 reports."), encoding="utf-8")
    (tmp_path / "supplement.tex").write_text(_document("Of 40 cases."), encoding="utf-8")
    report = audit([tmp_path / "main.tex", tmp_path / "supplement.tex"], None)
    assert report.unreadable == []
    assert {path.name for path in report.papers} == {"main.tex", "supplement.tex"}
    assert main(["audit", str(tmp_path), "--strict"]) == 0
    assert "Could not read" not in capsys.readouterr().out


def test_a_passed_over_file_is_refused_nothing(tmp_path: Path, capsys) -> None:
    """Round 1 of #463: a `.tex` nothing inputs is not read, so what the reader would refuse
    in it is not counted; it is named as passed over."""
    (tmp_path / "main.tex").write_text(_document("Of 412 reports."), encoding="utf-8")
    (tmp_path / "notes.tex").write_text(tex("!catcode`@=11 Of 3.\n"), encoding="utf-8")
    report = audit([tmp_path / "main.tex"], None)
    assert report.unreadable == []
    assert [said.split(": ", 1)[1] for said in report.passed_over] == [
        "no entry inputs it, so it was not read; name it, or \\input it from the paper's main "
        "file"
    ]
    assert main(["audit", str(tmp_path / "main.tex"), "--strict"]) == 0


def test_a_file_a_class_inputs_is_the_class_text(tmp_path: Path) -> None:
    """Round 1 of #463: a journal's class inputs its list of journals, which is not the
    paper's; it is passed over as the class's, not as a file no entry inputs."""
    (tmp_path / "main.tex").write_text(tex("!documentclass{journal}\n!begin{document}\nOf 412."
                                           "\n!end{document}\n"), encoding="utf-8")  # fmt: skip
    (tmp_path / "journal.cls").write_text(tex("!input{journals}\n"), encoding="utf-8")
    (tmp_path / "journals.tex").write_text("Journal 1, Journal 2.\n", encoding="utf-8")
    report = audit([tmp_path / "main.tex"], None)
    [said] = report.passed_over
    assert said.endswith("journals.tex: a class or a package the paper loads inputs it, so it "
                         "is theirs and not the paper's text, and was not read"), said


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


# ------------------------------------------------------------- totals and small cells


TOTALS = """# Results

| Characteristic | Cases (n = 120) | Controls (n = 100) |
|---|---|---|
| Sex | | |
| Men | 60 | 50 |
| Women | <5 | 47 |
| Other | 56 | 3 |
| Total | 120 | 99 |
| Region | | |
| North | 70 (50.0) | 40 (50.0) |
| South | 70 (50.0) | 40 (50.0) |
"""


def test_a_total_off_categories_over_n_and_a_count_given_away_count_for_strict(
    tmp_path: Path, capsys
) -> None:
    """Exact arithmetic, which --strict counts (the author, 2026-10-28): the controls add up
    to 100 and their total prints 99; the regions add up to 140 of 120 cases; and the women
    held back are 4, which the total row gives away, where the minimum is 5."""
    paper = tmp_path / "paper.md"
    paper.write_text(TOTALS, encoding="utf-8")
    assert main(["audit", str(paper), "--minimum-cell-count", "5", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    counted = [(f["section"], f["code"], f["line"]) for f in said["findings"] if f["counted"]]
    assert counted == [
        ("Arithmetic", "sum-off", 9), ("Arithmetic", "over-header-n", 11),
        ("Small cells recoverable by subtraction", "count-recoverable", 7)]  # fmt: skip
    assert (said["counts"]["totals_off"], said["counts"]["over_header_n"],
            said["counts"]["recoverable"]) == (1, 1, 1)  # fmt: skip
    assert main(["audit", str(paper), "--strict"]) == 1
    out = capsys.readouterr().out
    assert "=== Small cells recoverable by subtraction ===" in out
    assert "<5 in row 'Women', column 'Cases (n = 120)' can only be 4" in out
    assert "No minimum given (--minimum-cell-count)" in out
    # Under a minimum of four, a count of four is no small cell.
    assert main(["audit", str(paper), "--minimum-cell-count", "4", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert "count-recoverable" not in {f["code"] for f in said["findings"]}


def test_a_count_only_the_header_n_gives_away_is_listed_and_not_counted(
    tmp_path: Path, capsys
) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(TOTALS.replace("| Total | 120 | 99 |\n", "").replace("70 (50.0) | 40",
                                                                         "60 (50.0) | 40"),
                     encoding="utf-8")  # fmt: skip
    assert main(["audit", str(paper), "--strict"]) == 0
    out = capsys.readouterr().out
    assert "GIVEN AWAY BY ITS COLUMN'S N" in out and "can only be 4" in out


def test_a_latex_tables_total_is_held_to_its_counts(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(tex(
        "!documentclass{article}\n!begin{document}\n!begin{tabular}{lrr}\n"
        " & Cases & Controls !!\n!midrule\nMen & 60 & 50 !!\nWomen & 40 & 47 !!\n"
        "!midrule\nTotal & 100 & 99 !!\n!end{tabular}\n!end{document}\n"), encoding="utf-8")
    assert main(["audit", str(paper), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert [(f["code"], f["line"]) for f in said["findings"] if f["code"] == "sum-off"] == [
        ("sum-off", 9)]


def test_a_minimum_below_one_is_refused(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(TOTALS, encoding="utf-8")
    assert main(["audit", str(paper), "--minimum-cell-count", "0"]) == 2
    assert "--minimum-cell-count is a whole number from 1" in capsys.readouterr().err


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
    # The note is audit's, not `init --from`'s (round 1 of #463).
    assert ("pandoc is not on PATH; audit needs it to convert paper.docx to the text G6 and "
            "G14 read") in out and "init needs it" not in out  # fmt: skip


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


SMITH, JONES = "Smith J. A cohort. Lancet. 2019;393:100-10.", "Jones K. A trial. BMJ 2020;370:m1."


def test_a_docx_list_word_numbers_is_numbered_by_place(tmp_path: Path) -> None:
    paper = make_docx(tmp_path / "paper.docx", ["The rate rose [1, 3].", "References", SMITH,
                                                JONES], heading="References",
                      numbered={SMITH: "1", JONES: "1"})  # fmt: skip
    [census] = audit([paper], None).references
    assert census.style == "numbered by place"
    # A .docx is read a paragraph to a line, after the line its body opens with.
    assert [(p.code, p.line) for p in census.problems] == [
        ("citation-beyond-list", 2), ("entry-never-cited", 5)
    ]


@pytest.mark.parametrize(
    "numbered",
    [None, {SMITH: "2", JONES: "2"}, {SMITH: "1", JONES: "2"},
     {"Methods.": "3", SMITH: "1", JONES: "1"}],
    ids=["not numbered", "bullets", "two numberings", "a count begun before the list"],
)
def test_a_bracket_in_the_text_numbers_no_list_word_does_not_count(tmp_path: Path,
                                                                   numbered) -> None:  # fmt: skip
    """Round 1 of #463: one bracketed number in an author-year paper, `range [0, 100]`, made
    every entry "cited nowhere". A list is numbered by place only where Word counts it 1, 2,
    3; numberings 1 and 3 share a count, so 3 numbering the Methods begins it there."""
    paper = make_docx(tmp_path / "paper.docx", ["Methods.", "Scores range [0, 100] (Smith "
                                                "2019).", "References", SMITH, JONES],
                      heading="References", numbered=numbered)  # fmt: skip
    [census] = audit([paper], None).references
    assert (census.style, census.problems) == ("not numbered", [])


def test_a_docx_whose_last_heading_is_the_reference_list_is_counted(tmp_path: Path) -> None:
    """Round 1 of #463: an empty list under a final heading, with `[1]` in the text, raised
    ValueError on `max()` of no entries."""
    paper = make_docx(tmp_path / "paper.docx", ["Text [1].", "References"],
                      heading="References")  # fmt: skip
    [census] = audit([paper], None).references
    assert (census.entries, census.problems) == ((), [])


def test_an_author_year_list_is_counted_and_not_held_to_numbers(tmp_path: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nThe rate rose (Smith 2019) [7].\n\n# References\n\n"
                     "Smith, J. (2019). A cohort. Lancet, 393, 100.\n", encoding="utf-8")
    [census] = audit([paper], None).references
    assert (len(census.entries), census.style, census.problems) == (1, "not numbered", [])


@pytest.mark.parametrize(
    ("typed", "numbers"),
    [(("1.", "2.", "3."), [1, 2, 3]), (("1.", "1.", "1."), [1, 2, 3]),
     (("4.", "4.", "4."), [4, 5, 6]), (("1.", "1)", "1)"), [1, 1, 2]),
     (("1" + BS + ".", "2" + BS + ".", "3" + BS + "."), [1, 2, 3]),
     (("1" + BS + ".", "1" + BS + ".", "3" + BS + "."), [1, 1, 3])],
    ids=["typed in order", "1. on every entry", "from 4", "a new stop starts a new list",
         "escaped by pandoc", "escaped, printed as typed"],
)
def test_a_markdown_list_is_numbered_as_pandoc_prints_it(tmp_path: Path, typed, numbers) -> None:
    """Round 1 of #463: a list numbered `1.` on every entry is 1, 2, 3, as pandoc prints it,
    where it was held as one entry; and a number pandoc escaped, `1!.`, is read as typed."""
    paper = tmp_path / "paper.md"
    listed = "\n".join(f"{stop} Author {at}. A work. J Ex. 2019;1:1-2."
                       for at, stop in enumerate(typed))  # fmt: skip
    paper.write_text(f"# Results\n\nIt rose [1-3].\n\n# References\n\n{listed}\n",
                     encoding="utf-8")  # fmt: skip
    [census] = audit([paper], None).references
    assert census.style == "numbered"
    assert [entry.number for entry in census.entries] == numbers


@pytest.mark.parametrize(
    "written",
    ["[10.5555/fictional.1](https://doi.org/10.5555/fictional.1)",
     "(doi:10.5555/fictional.1).", "https://doi.org/10.5555/fictional.1;",
     "[https://doi.org/10.5555/fictional.1](https://doi.org/10.5555/fictional.1)"],
    ids=["a link's text", "in brackets", "before a stop", "a link to itself"],
)
def test_a_doi_ends_where_the_sentence_takes_over(written: str) -> None:
    """Round 1 of #463: `_DOI` ran on through `](`, and the DOI looked up was none."""
    assert references_module.identifiers(f"Smith J. A cohort. {written}") == (
        ("10.5555/fictional.1",), ()
    )


def test_a_doi_keeps_the_brackets_it_opens() -> None:
    doi = "10.1016/s0140-6736(19)30000-0"
    assert references_module.identifiers(f"Lancet. ({doi})") == ((doi,), ())


def test_a_bibitem_is_reported_in_the_file_that_holds_it(tmp_path: Path, capsys) -> None:
    """Round 1 of #463: a `thebibliography` in a file the paper inputs had its lines shown
    against the paper's main file."""
    (tmp_path / "main.tex").write_text(_document("See !cite{a}.\n!input{refs}"),
                                       encoding="utf-8")  # fmt: skip
    (tmp_path / "refs.tex").write_text(tex("!begin{thebibliography}{9}\n!bibitem{a} A.\n"
                                           "!bibitem{x} X.\n!end{thebibliography}\n"),
                                       encoding="utf-8")  # fmt: skip
    [census] = audit([tmp_path / "main.tex"], None).references
    assert [(p.code, p.path.name, p.line) for p in census.problems] == [
        ("entry-never-cited", "refs.tex", 3)
    ]
    assert main(["audit", str(tmp_path / "main.tex"), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)["findings"]
    assert [(Path(f["path"]).name, f["line"]) for f in said
            if f["code"] == "entry-never-cited"] == [("refs.tex", 3)]  # fmt: skip
    assert main(["audit", str(tmp_path / "main.tex")]) == 0
    assert "refs.tex line 3: \\bibitem{x} is cited nowhere" in capsys.readouterr().out


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
    # Every registry a DOI may be asked of is named (round 1 of #463).
    assert ("would ask Crossref and OpenAlex, then DataCite and doi.org where Crossref has no "
            f"record, for doi:{DOI} (entry 1)") in out  # fmt: skip
    assert "would ask PubMed for PMID 31000001 (entry 2)" in out


def test_a_doi_and_a_pmid_no_registry_knows_are_said(tmp_path: Path, registries,
                                                     capsys) -> None:  # fmt: skip
    """Round 1 of #463: a DOI no registry knows was not reported, and "no registry said a
    work was retracted" covered a DOI that was never checked."""
    registries.answers = {"pubmed": (200, {"header": {"type": "esummary"}, "result": {
        "uids": ["31000001"], "31000001": {"uid": "31000001", "error": "cannot get document "
                                           "summary"}}}),
        "doi_org": (404, {"responseCode": 100})}  # fmt: skip
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", str(paper), "--lookup", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)["findings"]
    assert [(f["code"], f["line"]) for f in said
            if f["code"] in ("doi-unregistered", "pmid-unknown")] == [
        ("doi-unregistered", 7), ("pmid-unknown", 8)]  # fmt: skip
    assert main(["audit", str(paper), "--lookup"]) == 0
    assert "no registry said a work was retracted" not in capsys.readouterr().out


def test_no_retraction_says_how_many_were_asked_and_known(tmp_path: Path, registries,
                                                          capsys) -> None:  # fmt: skip
    found = {"status": "ok", "message-type": "work",
             "message": {"DOI": DOI, "type": "journal-article", "title": ["A cohort"]}}
    registries.answers["crossref"] = (200, found)
    registries.answers["openalex"] = (200, {"id": "W1", "is_retracted": False,
                                            "title": "A cohort"})  # fmt: skip
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", str(paper), "--lookup"]) == 0
    assert ("no registry said a work was retracted, withdrawn or under concern: 2 asked, 2 "
            "known to a registry that answered") in capsys.readouterr().out


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


@pytest.mark.parametrize(
    ("given", "error"),
    [(["--dry-run"], "manuscript-guard audit: --dry-run and --lookup-cache go with --lookup"),
     (["--against", "absent.csv"], "manuscript-guard audit: absent.csv does not exist")],
    ids=["a lookup option alone", "a path not there"],
)
def test_under_json_an_audit_that_did_not_happen_says_why_on_stdout(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, given, error
) -> None:
    """Round 1 of #463: with `--json`, exit 2 printed nothing to stdout, and a script reading
    it was handed nothing to parse."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.md").write_text(NUMBERED, encoding="utf-8")
    assert main(["audit", "paper.md", "--json", *given]) == 2
    captured = capsys.readouterr()
    said = json.loads(captured.out)
    assert (said["ok"], said["error"]) == (False, error)
    assert error in captured.err


def test_the_help_names_every_registry_a_doi_is_asked_of(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["audit", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "DataCite and then doi.org about one Crossref has no record of" in out


def test_the_docs_name_every_registry_and_every_exit_2() -> None:
    """Round 1 of #463: docs/audit.md named Crossref and OpenAlex only, and said the audit
    exits 2 only when nothing could be read."""
    docs = Path(__file__).resolve().parents[1] / "docs" / "audit.md"
    said = " ".join(docs.read_text(encoding="utf-8").split())
    assert "DataCite about one Crossref has no record of and doi.org" in said
    assert "or `--dry-run` or `--lookup-cache` given without `--lookup`" in said
    assert "exits 2 only when nothing could be read" not in said


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


# ---------------------------------------------------------------------- round 2 of #463


@pytest.mark.parametrize(
    "defined",
    ["!let!toprule!hline", "!def!toprule{!hline}", "!newcommand{!midrule}{!hline}",
     "!renewcommand{!bottomrule}{!hline}", "!newcommand{!rowcolor}[1]{}",
     "!usepackage{booktabs}!renewcommand{!bottomrule}{!hline}",
     "!usepackage{colortbl}!let!cellcolor!relax"],
)
def test_an_author_s_own_rule_or_colour_command_is_not_refused(defined: str) -> None:
    """Round 2 of #463: the mask's new table commands refused an author's own definition of
    them as defined again, and read the rest of the file as typed, for every gate."""
    text = tex(f"!documentclass{{article}}\n{defined}\n!begin{{document}}\nOf 412.\n"
               "!end{document}\n")  # fmt: skip
    assert read_tree({"p.tex": text}, "p.tex").refusals == ()


def test_every_rule_and_colour_before_a_cell_prints_nothing_in_it() -> None:
    """Round 2 of #463: a `!multicolumn` after these opened no cell, and an overhang's
    lengths were read as the cell's text."""
    rules = ["!columncolor{red}", "!arrayrulecolor{blue}", "!rowcolors{2}{gray}{white}",
             "!Xhline{2pt}", "!hdashline", "!cdashline{1-2}", "!noalign{!vskip 2pt}",
             "!rowcolor{gray}[2pt][3pt]"]  # fmt: skip
    rows = "\n".join(f"{rule} !multicolumn{{2}}{{l}}{{A}} & {at} !!"
                     for at, rule in enumerate(rules))  # fmt: skip
    text = tex("!documentclass{article}\n!begin{document}\n!begin{tabular}{lrr}\n"
               f"{rows}\n!end{{tabular}}\n!end{{document}}\n")  # fmt: skip
    found = [[(c.text, c.span) for c in row] for table in latex_tables(_source(text))
             for row in table]  # fmt: skip
    assert found == [[("A", 2), (str(at), 1)] for at in range(len(rules))]


def test_a_colour_s_overhangs_are_no_numbers_of_the_paper(tmp_path: Path) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(_document("!begin{tabular}{lr}\n!rowcolor{gray}[2pt][3pt] A & 412 !!\n"
                               "!end{tabular}"), encoding="utf-8")  # fmt: skip
    report = audit([paper], [])
    assert [c.text for c in report.unmatched] == ["412"]


def test_an_unreadable_tex_beside_a_markdown_paper_is_passed_over(tmp_path: Path) -> None:
    """Round 2 of #463: a `.tex` that could not be read was taken for an entry, and failed
    `--strict` beside a Markdown paper."""
    (tmp_path / "paper.md").write_text("# Results\n\nOf 412 reports.\n", encoding="utf-8")
    (tmp_path / "old.tex").write_bytes("Of 3".encode("utf-16-le"))
    assert main(["audit", str(tmp_path), "--strict"]) == 0


@pytest.mark.parametrize(
    "written",
    ["10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E.",
     "*doi:10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E*",
     "<https://doi.org/10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E>",
     "`10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E`"],
    ids=["a SICI DOI", "in emphasis", "in an autolink", "in code"],
)
def test_a_sici_doi_keeps_its_angle_brackets(written: str) -> None:
    """Round 2 of #463: a SICI DOI was cut at its `<`, and emphasis and code marks were kept
    after a DOI."""
    assert references_module.identifiers(f"Smith J. {written}") == (
        ("10.1002/(sici)1097-0258(19980430)17:8<857::aid-sim777>3.0.co;2-e",), ()
    )


def test_a_citation_pandoc_escaped_is_read(tmp_path: Path) -> None:
    """Round 2 of #463: `!![3!!]`, as pandoc writes a citation it escapes, was not read."""
    paper = tmp_path / "paper.md"
    paper.write_text(NUMBERED.replace("[1]", BS + "[1" + BS + "]").replace("[5]", BS + "[5"
                     + BS + "]"), encoding="utf-8")  # fmt: skip
    [census] = audit([paper], None).references
    assert [(p.code, p.line) for p in census.problems] == [
        ("citation-beyond-list", 3), ("entry-never-cited", 9)
    ]


TWO_LEVELS = (
    f"<w:numbering {NS}><w:abstractNum w:abstractNumId='0'><w:lvl w:ilvl='0'><w:start "
    "w:val='1'/><w:numFmt w:val='decimal'/><w:lvlText w:val='%1.'/></w:lvl><w:lvl "
    "w:ilvl='1'><w:start w:val='1'/><w:numFmt w:val='decimal'/><w:lvlText w:val='%1.%2'/>"
    "</w:lvl></w:abstractNum><w:num w:numId='1'><w:abstractNumId w:val='0'/></w:num>"
    "</w:numbering>"
)


SUPERSCRIPT_TWO = chr(0xB2)


@pytest.mark.parametrize(
    ("props", "numberings"),
    [("<w:numPr><w:ilvl w:val='1'/><w:numId w:val='1'/></w:numPr>", TWO_LEVELS),
     ("<w:numPr><w:numId w:val='1'/></w:numPr>", TWO_LEVELS),
     (f"<w:numPr><w:ilvl w:val='{SUPERSCRIPT_TWO}'/><w:numId w:val='1'/></w:numPr>",
      TWO_LEVELS.replace("w:ilvl='1'", f"w:ilvl='{SUPERSCRIPT_TWO}'"))],
    ids=["another level's number printed", "no level written", "a level not a digit"],
)
def test_a_level_word_may_not_count_1_2_3_is_no_numbering(
    tmp_path: Path, props: str, numberings: str
) -> None:
    """Round 2 of #463: "%1.%2" prints 1.1, 1.2; a level left out is not resolved for sure;
    and a superscript two, taken for a digit, raised."""
    paper = make_docx(tmp_path / "paper.docx", ["The rate rose [1, 3].", "References", SMITH,
                                                JONES], heading="References",
                      numbered={SMITH: props, JONES: props}, numberings=numberings)  # fmt: skip
    [census] = audit([paper], None).references
    assert (census.style, census.problems) == ("not numbered", [])


def test_an_empty_numbered_paragraph_takes_its_number(tmp_path: Path) -> None:
    """Round 2 of #463: Word prints the number of an empty paragraph of a numbered list
    (Word 16, over COM: 1, 2, 3 for the empty one, 4), and every entry after it was
    numbered one less."""
    paper = make_docx(tmp_path / "paper.docx", ["The rate rose [1, 3].", "References", SMITH,
                                                "", JONES], heading="References",
                      numbered={SMITH: "1", "": "1", JONES: "1"})  # fmt: skip
    [census] = audit([paper], None).references
    assert census.style == "numbered by place"
    assert [entry.number for entry in census.entries] == [1, 3]
    assert census.problems == []


def test_the_docs_say_when_the_count_line_appears() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs" / "audit.md"
    said = " ".join(docs.read_text(encoding="utf-8").split())
    assert "where no registry reported anything of any entry" in said
    assert "an entry answered from the records kept counts as asked" in said


# ------------------------------------------------------------ the fix-only round of #463


def test_an_escaped_interval_after_its_value_is_no_citation(tmp_path: Path) -> None:
    """Fix-only round of #463: an escaped `!![55-72!!]` was read as a citation once escaped
    citations were, and a two-entry list reported it beyond itself."""
    paper = tmp_path / "paper.md"
    paper.write_text(f"# Results\n\nMedian 64 {BS}[55-72{BS}] days {BS}[1{BS}], {BS}[2{BS}].\n\n"
                     "# References\n\n1. A. J Ex. 2019;1:1-2.\n2. B. J Ex. 2019;1:1-2.\n",
                     encoding="utf-8")  # fmt: skip
    [census] = audit([paper], None).references
    assert (census.markers, census.problems) == (2, [])


@pytest.mark.parametrize("tag", ["</span> more", "<br> more", "<br>. more", "<br/>PMID",
                                 "<i>J</i>"])  # fmt: skip
def test_a_tag_after_a_doi_is_none_of_it(tag: str) -> None:
    """Fix-only rounds of #463: a `<` kept in a DOI read a tag after it into the DOI, also
    where text follows the tag at once."""
    assert references_module.identifiers(f"doi:10.1000/xyz{tag}")[0] == ("10.1000/xyz",)


def test_a_folder_with_only_an_unreadable_tex_says_it_could_not_be_read(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "old.tex").write_bytes("Of 3".encode("utf-16-le"))
    assert main(["audit", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "old.tex could not be read" in err and "documentclass" not in err
