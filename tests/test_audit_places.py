"""How the audit's report names a place and quotes it, for its reader rather than for a
program: a .docx's place as its heading and its paragraph under it, a number's quote centred
on the number, and what a gate quotes from a converted .docx as Word prints it (the
author's audit, 2026-11-10)."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.cli import main

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


def word_document(path: Path, paragraphs: list[tuple[str, bool]]) -> Path:
    """A .docx of paragraphs, each in the style "heading 1" where its flag says so."""
    styles = (f"<w:styles xmlns:w='{W}'><w:style w:type='paragraph' w:styleId='Heading1'>"
              "<w:name w:val='heading 1'/></w:style></w:styles>")  # fmt: skip
    body = "".join(
        "<w:p>" + ("<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>" if heading else "")
        + f"<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"
        for text, heading in paragraphs
    )
    document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body>{body}</w:body>"
                "</w:document>")  # fmt: skip
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", (2020, 1, 1, 0, 0, 0)), document)
        archive.writestr(zipfile.ZipInfo("word/styles.xml", (2020, 1, 1, 0, 0, 0)), styles)
    return path


PAPER = [
    ("A cohort of readers", False),
    ("Abstract", True),
    ("Of the patients, 412 improved, and the effect held over a long and quiet follow-up "
     "that no other study of the kind has had the patience to run to its end.", False),
    ("Methods", True),
    ("We used the quantitative risk score (QRS) to rank the patients.", False),
    ("Each patient was seen twice, and the XYZ panel read every record.", False),
    ("Results", True),
    ("Of the patients, 40 improved on the quantitative risk score (QRS) by 2 points.", False),
]


# ------------------------------------------------------------------------- the places


def test_a_line_is_placed_under_its_heading_and_counted_under_it() -> None:
    from manuscript_guard.auditing.paragraphs import counted

    lines = ["Title", "", "Methods", "We did.", "", "| a |", "| b |", "", "- one", "- two",
             "Results", "It held."]  # fmt: skip
    places = counted(lines, {3: "Methods", 11: "**Results**"}, frozenset({6, 7}))
    said = [places.said(line) for line in range(1, len(lines) + 1)]
    assert said == [
        "before the first heading, paragraph 1", "line 2", "the heading Methods",
        "Methods, paragraph 1", "line 5", "Methods, paragraph 2 (a table)",
        "Methods, paragraph 2 (a table)", "line 8", "Methods, paragraph 3",
        "Methods, paragraph 4", "the heading Results", "Results, paragraph 1",
    ]
    assert places.place(6).as_dict() == {"heading": "Methods", "paragraph": 2}


@pytest.mark.parametrize(("first", "last", "said"), [
    (3, 10, "Methods, paragraphs 1-4"),
    (4, 4, "Methods, paragraph 1"),
    (1, 12, "from before the first heading, paragraph 1 to Results, paragraph 1"),
    (2, 12, "from the heading Methods to Results, paragraph 1"),
    (9, 12, "from Methods, paragraph 3 to Results, paragraph 1"),
    (5, 8, "Methods, paragraph 2 (a table)"),
])  # fmt: skip
def test_a_stretch_of_lines_is_said_as_the_paragraphs_it_holds(
    first: int, last: int, said: str
) -> None:
    """A reference list cut from its heading on is the section's paragraphs; blank lines at
    either end of a stretch are passed over to the nearest paragraph."""
    from manuscript_guard.auditing.paragraphs import counted

    lines = ["Title", "", "Methods", "We did.", "", "| a |", "| b |", "", "- one", "- two",
             "Results", "It held."]  # fmt: skip
    places = counted(lines, {3: "Methods", 11: "Results"}, frozenset({6, 7}))
    assert places.stretch(first, last) == said


def test_a_docx_s_notes_are_placed_under_the_notes() -> None:
    from manuscript_guard.auditing.paragraphs import NOTES, counted

    places = counted(["Methods", "We did.", "A note.", "Another."], {1: "Methods"},
                     notes_from=3)  # fmt: skip
    assert [places.said(line) for line in (2, 3, 4)] == [
        "Methods, paragraph 1", f"{NOTES}, paragraph 1", f"{NOTES}, paragraph 2"]


@pytest.mark.parametrize(("between", "after"), [
    # One table, its first row with an empty cell.
    ("", "Results, paragraph 3"),
    # Two tables with an empty paragraph between, which Word needs: two paragraphs, the
    # empty one none (fix round of #616, where the empty one joined them).
    ("<w:p/>", "Results, paragraph 4"),
])  # fmt: skip
def test_an_empty_cell_keeps_its_table_one_paragraph(
    tmp_path: Path, between: str, after: str
) -> None:
    """An empty cell is a blank line of the document's own text, and closed the table: the
    cells after it were a paragraph of their own, and every place after the table one too
    many (review of #616)."""
    from manuscript_guard.auditing.paragraphs import of_docx
    from manuscript_guard.text.docx import read_docx_text

    def cell(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>" if text else (
            "<w:tc><w:p/></w:tc>")  # fmt: skip

    table = "<w:tbl>" + "".join(f"<w:tr>{cell(a)}{cell(b)}</w:tr>"
                                for a, b in (("n", ""), ("12", "40"))) + "</w:tbl>"  # fmt: skip
    tables = table + (between + table if between else "")
    path = word_document(tmp_path / "paper.docx", [("Results", True), ("Before it.", False)])
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    last = "<w:p><w:r><w:t>After it.</w:t></w:r></w:p>"
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b"</w:body>", (tables + last).encode() + b"</w:body>")  # fmt: skip
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    document = read_docx_text(path)
    places = of_docx(document, document.body)
    lines = document.body.split("\n")
    assert places.said(lines.index("After it.") + 1) == after


def test_a_heading_with_no_words_is_no_heading() -> None:
    """An empty paragraph in a heading style is marked a heading by the document's reader:
    the paragraphs after it were "before the first heading" (review of #616)."""
    from manuscript_guard.auditing.paragraphs import counted

    places = counted(["Methods", "We did.", "", "We did again."], {1: "Methods", 3: ""})
    assert places.said(4) == "Methods, paragraph 2"


@pytest.mark.parametrize(("markdown", "line", "said"), [
    # A line broken in a paragraph (Shift+Enter): pandoc ends it with a backslash.
    ("# M\n\nDesign:\\\nWe used it.\n\nThen this.\n", 6, "M, paragraph 2"),
    ("# M\n\nDesign:\\\nWe used it.\n\nThen this.\n", 4, "M, paragraph 1"),
    # A backslash pandoc escaped, "\\\\", ends the line and breaks nothing.
    ("# M\n\n- a\\\\\n- b\n", 4, "M, paragraph 2"),
    # The notes pandoc writes after the last paragraph.
    ("# R\n\nWords.[^1]\n\n[^1]: A note.\n", 5, "the notes, paragraph 1"),
])  # fmt: skip
def test_the_converted_text_s_line_breaks_and_notes_are_placed(
    markdown: str, line: int, said: str
) -> None:
    from manuscript_guard.auditing.paragraphs import of_markdown

    assert of_markdown(markdown).said(line) == said


# ------------------------------------------------------------------------- the quotes


def test_a_number_s_quote_is_centred_on_it() -> None:
    """The line's first 140 characters were quoted, so a number past them was not in its own
    quote (the author's Abstract, a paragraph to a line in a .docx)."""
    from manuscript_guard.audit import AROUND, around
    from manuscript_guard.text.tokens import find_atoms

    line = " ".join(f"word{n}" for n in range(60)) + " and 412 patients " + " ".join(
        f"tail{n}" for n in range(60))  # fmt: skip
    atom = next(atom for atom in find_atoms(line, line) if atom.text == "412")
    quoted = around(atom)
    assert "412" in quoted and quoted.startswith("...") and quoted.endswith("...")
    assert len(quoted) <= 2 * AROUND + len("412") + 6
    assert line[:140] not in quoted
    plain = "Of 40 patients, 12 improved."
    short = next(atom for atom in find_atoms(plain, plain) if atom.text == "12")
    assert around(short) == "Of 40 patients, 12 improved."


@pytest.mark.parametrize(("quoted", "said"), [
    ("the sign has no space once, as in 'p\\<0.05'", "the sign has no space once, as in 'p<0.05'"),
    ("the P value is written '*p*' once", "the P value is written 'p' in italics once"),
    ("written '**P**' twice", "written 'P' in bold twice"),
    ("a backslash typed, 'a\\\\b'", "a backslash typed, 'a\\b'"),
    ("Authors\\' contributions", "Authors' contributions"),
    ("no escape here: p < 0.05", "no escape here: p < 0.05"),
])  # fmt: skip
def test_what_a_gate_quotes_from_a_converted_docx_is_said_as_word_prints_it(
    quoted: str, said: str
) -> None:
    """Markdown's escapes and emphasis, which the Word document has none of: "p\\<0.05" and
    "'*p*'" in the author's report."""
    from manuscript_guard.auditing.gates import as_in_word

    assert as_in_word(quoted) == said


def test_a_phrasing_finding_does_not_open_with_its_rule_s_name(tmp_path: Path) -> None:
    """"importance-tail: An "-ing" tail asserting significance ..." named a rule of G6's
    that no reader of the report knows; the audit says what the rule is about."""
    from manuscript_guard.auditing.gates import _putting_back
    from manuscript_guard.findings import Finding

    put_back = _putting_back(tmp_path / "manuscript", {"main.md": tmp_path / "paper.md"})
    found = put_back(Finding(gate="G6", code="ai-phrasing", severity="warn",
                             message="importance-tail: An \"-ing\" tail asserting significance"))
    assert found.message == "An \"-ing\" tail asserting significance"
    other = put_back(Finding(gate="G14", code="abbreviation-undefined", severity="warn",
                             message="AS: used and not defined"))  # fmt: skip
    assert other.message == "AS: used and not defined"


# ------------------------------------------------------------------------- the report


def _audited(capsys, *argv: str) -> tuple[dict, str]:
    main(["audit", *argv, "--json"])
    report = json.loads(capsys.readouterr().out)
    main(["audit", *argv])
    return report, capsys.readouterr().out


def test_a_docx_s_numbers_are_placed_by_heading_and_paragraph(tmp_path: Path, capsys) -> None:
    """The Abstract's number not found is at "Abstract, paragraph 1", in the text and in
    the JSON, its quote centred on it; never "line 3"."""
    paper = word_document(tmp_path / "paper.docx", PAPER)
    report, text = _audited(capsys, str(paper))
    assert "Abstract, paragraph 1: 412" in text, text
    found = [f for f in report["findings"] if f["code"] == "abstract-not-found"]
    assert [(f["heading"], f["paragraph"]) for f in found] == [("Abstract", 1)]


@needs_pandoc
def test_a_docx_s_words_are_placed_by_heading_and_paragraph(tmp_path: Path, capsys) -> None:
    """G14 reads the text pandoc converts a .docx to, whose lines are nobody's: its findings
    and the places their messages name are the document's headings and paragraphs, and the
    report no longer says which converted text its lines were of."""
    # A paragraph with a line broken inside it, which pandoc writes on two lines, before the
    # one with XYZ (review of #616).
    paper = [*PAPER[:5], ("Design: a cohort\\\nseen at two sites.", False), *PAPER[5:]]
    markdown = "\n\n".join(f"# {said}" if heading else said for said, heading in paper)
    (tmp_path / "paper.md").write_text(markdown + "\n", encoding="utf-8")
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    report, text = _audited(capsys, str(tmp_path / "paper.docx"))
    assert "Methods, paragraph 3: XYZ" in text, text
    # A place in the paper the finding is on, named without the paper's name again (the
    # author's audit, 2026-11-11).
    assert "it was defined at Methods, paragraph 1" in text, text
    assert "at paper.docx, Methods" not in text
    assert "pandoc converts it to" not in text
    xyz = [f for f in report["findings"] if f["code"] == "abbreviation-undefined"
           and f["message"].startswith("XYZ")]  # fmt: skip
    assert [(f["heading"], f["paragraph"]) for f in xyz] == [("Methods", 3)]
    # The draft of a referee's report places them the same way (review of #616).
    draft = tmp_path / "draft.md"
    main(["audit", str(tmp_path / "paper.docx"), "--report-draft", str(draft)])
    capsys.readouterr()
    said = [line for line in draft.read_text(encoding="utf-8").splitlines()
            if line.startswith("- `abbreviation-undefined`")]  # fmt: skip
    assert said == ["- `abbreviation-undefined` (G14, warn): 1, at paper.docx Methods, "
                    "paragraph 3"], said
