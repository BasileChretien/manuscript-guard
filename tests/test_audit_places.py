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
    markdown = "\n\n".join(f"# {said}" if heading else said for said, heading in PAPER)
    (tmp_path / "paper.md").write_text(markdown + "\n", encoding="utf-8")
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    report, text = _audited(capsys, str(tmp_path / "paper.docx"))
    assert "Methods, paragraph 2: XYZ" in text, text
    assert "it was defined at paper.docx, Methods, paragraph 1" in text, text
    assert "pandoc converts it to" not in text
    xyz = [f for f in report["findings"] if f["code"] == "abbreviation-undefined"
           and f["message"].startswith("XYZ")]  # fmt: skip
    assert [(f["heading"], f["paragraph"]) for f in xyz] == [("Methods", 2)]
