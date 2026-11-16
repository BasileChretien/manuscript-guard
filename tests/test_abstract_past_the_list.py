"""The lines between a reference list's end and the next heading, searched for the Abstract's
numbers (`auditing.abstract._past_the_lists`; Basile, 2026-11-15).

A list that holds an entry ends at a display, and a list under no heading at a caption or
back matter too (`audit.bibliography_spans`); the lines after it, before the next heading,
stood under "References", which reports nothing, so a PDF's table typed as text, or a Word or
Markdown caption or legend there, was never searched for the Abstract's numbers, as a Word
paper's tables always were. pdf-psych-B3 of the real-paper corpus had its Abstract's "33.2%"
in the table after its references, with no heading after them, and said not found.

What stays unsearched: a note's line, a section after that reports nothing, the list's own
entries and, in LaTeX, the lines after the list, which stand under the section before it
(DESIGN.md, "Known gaps").
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.audit import audit

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import _CAPTION_STYLE, heading, make_docx, para  # noqa: E402
from test_audit_pdf import write  # noqa: E402

needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                     reason="pdftotext is not installed")  # fmt: skip

#: The Abstract's sentence, with the number the paper reports only after its references.
SAID = "Of 194 patients, 33.2% were women."
#: The paper before its references, in the order a heading stands over each part.
PARTS = (("Abstract", SAID), ("Introduction", "Falls harm [1]."),
         ("Methods", "We read 194 records [2]."), ("Results", "Of 194 patients, most were women."),
         ("Discussion", "Women fall."))  # fmt: skip
ENTRIES = ("1. Smith J, Jones K. Title. Lancet. 2019;393:100-10.",
           "2. Doe A. Title. BMJ 2021;372:m71.")  # fmt: skip


def not_found(paper: Path) -> list[str]:
    report = audit([paper], None)
    assert report.abstract is not None and report.abstract.compared, report.abstract
    return [c.text for c in report.abstract.not_found]


# ------------------------------------------------------------------------------- a PDF


def _pdf_lines(after: list[str]) -> list[str]:
    lines = ["A study of things"]
    for title, text in PARTS:
        lines += [title, text]
    return [*lines, "References", *ENTRIES, *after]


@needs_pdftotext
def test_a_pdf_s_table_after_its_references_is_searched(tmp_path: Path) -> None:
    """pdf-psych-B3's shape: "References", its entries, then "Table 1" and its rows as lines
    of text, with no heading after. The list ends at the caption, and the row's "33.2" is
    the Abstract's "33.2%" found."""
    paper = write(tmp_path / "paper.pdf", _pdf_lines(["Table 1. Baseline",
                                                      "Women 194 33.2"]), per_column=40)
    assert not_found(paper) == []


@needs_pdftotext
def test_a_pdf_s_section_after_the_table_that_reports_nothing_is_not_searched(
    tmp_path: Path,
) -> None:
    """The stretch ends at the next heading: a "Funding" after the table reports nothing, and
    the number there is not found."""
    paper = write(tmp_path / "paper.pdf", _pdf_lines(["Table 1. Baseline", "Women 194 12",
                                                      "Funding", "Grant 33.2 paid for it."]),
                  per_column=40)  # fmt: skip
    assert not_found(paper) == ["33.2%"]


# ------------------------------------------------------------------------------ a .docx


def _docx_body(after: str) -> str:
    body = para("A study of things")
    for title, text in PARTS:
        body += heading(title) + para(text)
    return body + heading("References") + "".join(para(entry) for entry in ENTRIES) + after


#: A paragraph in a caption style, by its name (`DocxText.captions`).
_LEGEND = '<w:p><w:pPr><w:pStyle w:val="Legend"/></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>'


@pytest.mark.parametrize("after", [
    _LEGEND.format("Of them 33.2% were women."),
    para("Figure 1. Of them 33.2% were women."),
    para("Fig 1.") + para("Of them 33.2% were women."),
], ids=["a caption style", "a typed legend", "a paragraph after a typed caption"])
def test_a_docx_s_caption_after_its_references_is_searched(tmp_path: Path, after: str) -> None:
    """A styled "References", its entries, then a paragraph in a caption style, a legend typed
    "Figure 1." or the paragraph after a typed caption, holding the Abstract's number, and
    no heading after: it is found, as a table there always was."""
    paper = make_docx(tmp_path / "paper.docx", _docx_body(after), _CAPTION_STYLE)
    assert not_found(paper) == []


def test_a_docx_s_notes_and_a_section_after_the_stretch_are_not_searched(
    tmp_path: Path,
) -> None:
    """The stretch runs to the next heading: a "Funding" after the legend reports nothing;
    and with no heading after the list, a footnote read after the body is still a note's
    line, where citations are written."""
    funded = _docx_body(para("Figure 1. Of them 12 fell.") + heading("Funding")
                        + para("Grant 33.2 paid for it."))  # fmt: skip
    assert not_found(make_docx(tmp_path / "funded.docx", funded)) == ["33.2%"]
    noted = make_docx(tmp_path / "noted.docx", _docx_body(para("Figure 1. Of them 12 fell.")))
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    notes = (f"<?xml version='1.0'?><w:footnotes xmlns:w='{w}'><w:footnote w:id='1'><w:p><w:r>"
             "<w:t>Smith 2019, 33.2.</w:t></w:r></w:p></w:footnote></w:footnotes>")
    with zipfile.ZipFile(noted, "a") as archive:
        archive.writestr(zipfile.ZipInfo("word/footnotes.xml", (2020, 1, 1, 0, 0, 0)), notes)
    assert not_found(noted) == ["33.2%"]


# --------------------------------------------------------------------------- Markdown


def _markdown(after: str) -> str:
    text = "# A study of things\n\n"
    for title, said in PARTS:
        text += f"## {title}\n\n{said}\n\n"
    return text + "## References\n\n" + "".join(f"{e}\n\n" for e in ENTRIES) + after


@pytest.mark.parametrize("after", [
    "Figure 1. Of them 33.2% were women.\n",
    "![A chart](figure.png)\n\nOf them 33.2% were women.\n",
    "Table 1. Baseline\n\nOf them 33.2% were women.\n",
], ids=["a typed legend", "an image and its legend", "a paragraph after a typed caption"])
def test_a_markdown_caption_after_its_references_is_searched(tmp_path: Path, after: str) -> None:
    """The Markdown `init --from` writes of the same paper reads alike."""
    paper = tmp_path / "paper.md"
    paper.write_text(_markdown(after), encoding="utf-8")
    assert not_found(paper) == []


@pytest.mark.parametrize("after", [
    "Figure 1. Of them 12 fell.\n\n## Funding\n\nGrant 33.2 paid for it.\n",
    "Figure 1. Of them 12 fell.[^1]\n\n[^1]: Smith 2019, 33.2.\n",
], ids=["a section after that reports nothing", "a note"])
def test_what_stands_past_a_markdown_list_unsearched_stays_so(tmp_path: Path, after: str) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(_markdown(after), encoding="utf-8")
    assert not_found(paper) == ["33.2%"]


@pytest.mark.parametrize("listed", [
    "\\begin{thebibliography}{9}\n\\bibitem{a} Smith J. Title. Lancet. 2019;393:100-10.\n"
    "\\end{thebibliography}",
    "\\bibliography{refs}",
], ids=["thebibliography", "bibliography"])
def test_a_latex_paper_s_lines_after_its_list_stand_under_the_section_before_it(
    tmp_path: Path, listed: str
) -> None:
    """Not changed (Basile's decision named Word, PDF and Markdown): LaTeX prints no heading
    for a reference list, so what stands after it is under the section before it, searched
    where that section reports and not under a Discussion (DESIGN.md, "Known gaps"), where
    it is asked about as the Discussion's (decision 27, part B)."""
    def latex(before: str) -> str:
        return ("\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\n"
                + SAID.replace("%", "\\%") + "\n\\end{abstract}\n\\section{Methods}\n"
                "We read 194 records.\n\\section{Results}\nMost were women.\n" + before + listed
                + "\nTable 1. Baseline\nWomen 194 33.2\n\\end{document}\n")  # fmt: skip

    paper = tmp_path / "paper.tex"
    paper.write_text(latex("\\section{Discussion}\nWomen fall.\n"), encoding="utf-8")
    assert not_found(paper) == []
    assert [c.text for c, *_rest in audit([paper], None).abstract.only_in] == ["33.2%"]
    paper.write_text(latex(""), encoding="utf-8")
    assert not_found(paper) == []


def test_a_number_in_an_entry_of_the_list_is_still_not_found(tmp_path: Path) -> None:
    """The list's own lines are blanked: an Abstract's "393" that is only an entry's volume
    is not found, in each reader, with a caption after the list."""
    said = PARTS[0][1].replace("194 patients", "393 patients")
    markdown = tmp_path / "paper.md"
    markdown.write_text(_markdown("Figure 1. Of them 33.2% were women.\n").replace(
        PARTS[0][1], said, 1), encoding="utf-8")  # fmt: skip
    assert not_found(markdown) == ["393"]
    body = _docx_body(para("Figure 1. Of them 33.2% were women.")).replace(PARTS[0][1], said, 1)
    assert not_found(make_docx(tmp_path / "paper.docx", body)) == ["393"]


#: An entry after a caption in the middle of a list, a float on a references page or a
#: caption between its columns, whose volume is the Abstract's "393" (round 1 of #692).
_RESUMED = "3. Brown T. Title. Lancet. 2019;393:100-10."


def _said_393(text: str) -> str:
    return text.replace(PARTS[0][1], PARTS[0][1].replace("194 patients", "393 patients"), 1)


@needs_pdftotext
def test_a_pdf_s_entry_after_a_caption_in_its_list_is_the_list_s_again(tmp_path: Path) -> None:
    """The list ends at the caption, but the entry after it resumes the list for the Abstract
    against Results, to where a PDF's list ends: its volume is not the Abstract's "393"."""
    lines = _pdf_lines(["Table 1. Baseline", "Women 194 12", _RESUMED])
    lines = [_said_393(line) for line in lines]
    assert not_found(write(tmp_path / "paper.pdf", lines, per_column=40)) == ["393", "33.2%"]


def test_a_docx_s_entry_after_a_caption_in_its_list_is_the_list_s_again(tmp_path: Path) -> None:
    body = _said_393(_docx_body(para("Table 1. Baseline") + para(_RESUMED)))
    assert not_found(make_docx(tmp_path / "paper.docx", body)) == ["393", "33.2%"]
    # The legend after the entries that resume the list, before the next heading, is searched.
    body = _said_393(_docx_body(para("Table 1. Baseline") + para(_RESUMED)
                                + _LEGEND.format("Of them 33.2% were women.")))  # fmt: skip
    paper = make_docx(tmp_path / "legend.docx", body, _CAPTION_STYLE)
    assert not_found(paper) == ["393"]


def test_a_markdown_entry_after_a_caption_in_its_list_is_the_list_s_again(
    tmp_path: Path,
) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(_said_393(_markdown(f"Table 1. Baseline\n\nWomen 194 12\n\n{_RESUMED}\n")),
                     encoding="utf-8")  # fmt: skip
    assert not_found(paper) == ["393", "33.2%"]


def test_a_markdown_list_ended_by_a_thematic_break_has_what_follows_searched(
    tmp_path: Path,
) -> None:
    """A Markdown list ends at a thematic break, as well as at a display: what follows it,
    before the next heading, is searched too."""
    paper = tmp_path / "paper.md"
    paper.write_text(_markdown("---\n\nGrant 33.2 paid for it.\n"), encoding="utf-8")
    assert not_found(paper) == []


def test_an_entry_with_no_reference_s_shape_after_a_caption_is_searched(tmp_path: Path) -> None:
    """What stays (DESIGN.md, "Known gaps"): an entry the reader does not take for one, with
    no year, journal or pages, does not resume the list, and its number is searched."""
    from manuscript_guard.audit import looks_like_reference

    shapeless = "Brown T, volume 393"
    assert not looks_like_reference(shapeless)
    paper = tmp_path / "paper.md"
    paper.write_text(_said_393(_markdown(f"Table 1. Baseline\n\n{shapeless}\n")),
                     encoding="utf-8")  # fmt: skip
    assert not_found(paper) == ["33.2%"]


#: An entry after a mid-list caption wrapped over two lines, as a PDF sets it, neither line
#: of a reference's shape; `{}` its number (round 2 of #692).
_WRAPPED = ("{} Brown T, Jones K. A title about falls", "in older adults. Lancet. 2019;393:100-10.")
#: The forms a list numbers its entries in, `{}` the number.
_FORMS = ("{}.", "{})", "[{}]")


def _numbered(form: str) -> list[str]:
    """`ENTRIES` numbered in `form`."""
    return [form.format(at) + entry[entry.index(" "):] for at, entry in enumerate(ENTRIES, 1)]


@needs_pdftotext
@pytest.mark.parametrize("form", _FORMS)
def test_a_pdf_s_wrapped_entry_with_the_list_s_next_number_resumes_the_list(
    tmp_path: Path, form: str
) -> None:
    """Basile, 2026-11-15: a line that opens with the list's next entry number, in the form
    the list numbers its entries in, resumes the list for the Abstract against Results,
    whatever its shape: the entry's volume is not the Abstract's "393"."""
    lines = [*_pdf_lines(["Table 1. Baseline", "Women 194 12", _WRAPPED[0].format(
        form.format(3)), _WRAPPED[1]])]  # fmt: skip
    lines = [_said_393(line) for line in lines]
    at = lines.index("References")
    lines[at + 1:at + 3] = _numbered(form)
    assert not_found(write(tmp_path / "paper.pdf", lines, per_column=40)) == ["393", "33.2%"]


@needs_pdftotext
@pytest.mark.parametrize("number", ["7.", "3)", "[3]", "2."],
                         ids=["another number", "a parenthesis", "brackets", "the last"])
def test_a_pdf_s_entry_with_any_other_number_resumes_nothing(tmp_path: Path,
                                                              number: str) -> None:  # fmt: skip
    """Only the next number in the list's own form: "7." after "2.", "3)" or "[3]" after a
    list numbered "1.", "2.", and "2." again, resume nothing, and the volume is searched."""
    lines = _pdf_lines(["Table 1. Baseline", "Women 194 12", _WRAPPED[0].format(number),
                        _WRAPPED[1]])  # fmt: skip
    lines = [_said_393(line) for line in lines]
    assert not_found(write(tmp_path / "paper.pdf", lines, per_column=40)) == ["33.2%"]


@pytest.mark.parametrize("form", _FORMS)
def test_a_docx_or_markdown_entry_with_the_next_number_resumes_the_list(
    tmp_path: Path, form: str
) -> None:
    """The same in a .docx and in Markdown, an entry with the next number and no reference's
    shape, its year left out."""
    shapeless = f"{form.format(3)} Brown T, Jones K. A title about falls, volume 393"
    entries = _numbered(form)
    body = _docx_body(para("Table 1. Baseline") + para(shapeless))
    for entry, numbered in zip(ENTRIES, entries, strict=True):
        body = body.replace(entry, numbered)
    assert not_found(make_docx(tmp_path / "paper.docx", _said_393(body))) == ["393", "33.2%"]
    text = _markdown(f"Table 1. Baseline\n\n{shapeless}\n")
    for entry, numbered in zip(ENTRIES, entries, strict=True):
        text = text.replace(entry, numbered)
    paper = tmp_path / "paper.md"
    paper.write_text(_said_393(text), encoding="utf-8")
    assert not_found(paper) == ["393", "33.2%"]


#: Entries that hold no number of their own, an author-year list's.
_UNNUMBERED = ("Smith, J., and Jones, K. (2019). Falls in nurses. Lancet, 393, 100-110.",
               "Doe, A. (2021). Falls at home. BMJ, 372, 71-80.")  # fmt: skip


def test_a_numbered_heading_gives_an_unnumbered_list_no_next_number(tmp_path: Path) -> None:
    """The next number is read from the list's entries, never from its heading: under "7.
    References", an author-year list has none, and "8. …" after a caption is the paper's
    text, searched (the check of #692's last commit)."""
    body = _docx_body(para("Table 1. Baseline") + para("8. Older adults: 33.2% fell."))
    body = body.replace(heading("References"), heading("7. References"))
    for entry, unnumbered in zip(ENTRIES, _UNNUMBERED, strict=True):
        body = body.replace(entry, unnumbered)
    assert not_found(make_docx(tmp_path / "paper.docx", body)) == []
