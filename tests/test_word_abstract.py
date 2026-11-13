"""A Word paper's Abstract titled in a shape no heading style marks: a run-in label opening its
paragraph, "Abstract: ...", and "Abstract" alone on a line in bold in a paper that uses heading
styles elsewhere (Basile, 2026-11-14). Four papers of the real-paper corpus gave "no file has a
heading that names the Abstract" where a reader sees one: docx-med-B3 (the run-in label, in a
paper of 45 heading-styled lines), docx-med-A2, docx-psych-A1 and docx-socio-A2 (a bold
"Abstract" line, in papers whose few heading styles are on title-page lines). The cases here
are their shapes, not their text."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from test_from_word import _package

from manuscript_guard import from_word
from manuscript_guard.audit import audit
from manuscript_guard.auditing.abstract import NO_ABSTRACT, NO_RESULTS
from manuscript_guard.text.docx import read_docx_text
from manuscript_guard.text.docx_abstract import placed_headings

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

STYLES = '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'


def heading(text: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'


def para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def bold(text: str) -> str:
    return f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def bold_label(label: str, text: str) -> str:
    """A paragraph whose label is in bold and whose text goes on after it in plain type."""
    return (f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{label}</w:t></w:r>'
            f'<w:r><w:t xml:space="preserve"> {text}</w:t></w:r></w:p>')  # fmt: skip


#: The rest of a styled paper after its Abstract, whose Results report its numbers.
AFTER = (heading("Methods") + para("We read 412 records.") + heading("Results")
         + para("Of 412 patients, 77 fell."))  # fmt: skip


def paper(tmp_path: Path, abstract: str, name: str = "paper.docx", after: str = AFTER) -> Path:
    """A paper with heading styles: its title in one, then `abstract`, then `after`."""
    return _package(tmp_path / name, heading("Falls in older patients") + abstract + after, STYLES)


def titles(path: Path) -> list[str]:
    return [one.title for one in placed_headings(read_docx_text(path))]


@pytest.mark.parametrize(("abstract", "title"), [
    (para("Abstract: Of 412 patients, 77 fell."), "Abstract"),
    (para("Abstract. Of 412 patients, 77 fell."), "Abstract"),
    (para("ABSTRACT: Of 412 patients, 77 fell."), "ABSTRACT"),
    (bold_label("Abstract:", "Of 412 patients, 77 fell."), "Abstract"),
], ids=["colon", "stop", "capitals", "label in bold"])
def test_a_run_in_abstract_label_in_a_styled_paper_is_its_heading(
    tmp_path: Path, abstract: str, title: str,
) -> None:
    """docx-med-B3: "Abstract: This systematic realist review explores ..." opens the
    Abstract's paragraph, in no heading style, in a paper of 45 heading-styled lines. The label
    is the heading, and the numbers on its line are the Abstract's, compared with the Results."""
    path = paper(tmp_path, abstract)
    assert titles(path) == ["Falls in older patients", title, "Methods", "Results"]
    read = audit([path], None).abstract
    assert read.compared and read.numbers == read.matched == 2, read
    assert read.not_found == []


def test_a_bold_abstract_line_in_a_styled_paper_is_its_heading(tmp_path: Path) -> None:
    """docx-med-A2, docx-psych-A1, docx-socio-A2: "Abstract" alone on a line in bold, in a
    paper whose heading styles are elsewhere. Its paragraph is compared with the Results."""
    for at, line in enumerate(("Abstract", "ABSTRACT", "Abstract ", "1. Abstract")):
        path = paper(tmp_path, bold(line) + para("Of 412 patients, 77 fell."), f"{at}.docx")
        assert titles(path)[1].strip() == line.strip()
        read = audit([path], None).abstract
        assert read.compared and read.numbers == read.matched == 2, (line, read)


@pytest.mark.parametrize("abstract", [
    bold("Abstracts were screened by two reviewers.") + para("Of 412 patients, 77 fell."),
    para("Abstracts of 412 patients were read: 77 fell."),
    para("The abstract: of 412 patients, 77 fell."),
    para("Abstract:") + para("Of 412 patients, 77 fell."),
    # docx-ecol-B2: "Abstract" alone on a line in plain type, in a styled paper. Not read.
    para("Abstract") + para("Of 412 patients, 77 fell."),
    "<w:tbl><w:tr><w:tc>" + para("Abstract: Of 412 patients, 77 fell.") + "</w:tc></w:tr></w:tbl>",
], ids=["bold sentence", "a sentence", "after a word", "label alone", "plain line", "in a cell"])
def test_abstract_in_a_sentence_or_in_plain_type_is_no_heading(
    tmp_path: Path, abstract: str,
) -> None:
    path = paper(tmp_path, abstract)
    assert titles(path) == ["Falls in older patients", "Methods", "Results"]
    read = audit([path], None).abstract
    assert not read.compared and read.why_not == NO_ABSTRACT


def test_the_abstract_ends_at_a_typed_title_before_the_next_heading(tmp_path: Path) -> None:
    """docx-med-B3 and docx-socio-A2: the next heading after the Abstract was an empty
    paragraph in a heading style, or the title page again, and the Introduction or the
    Acknowledgments typed in bold before it ended the Abstract for a reader. It ends there, and
    that title is a heading too: "In 2019, 15 of 30 died" is the Introduction's, not the
    Abstract's. A structured abstract's own parts in bold are the Abstract's, up to the
    Introduction, as `section_levels` places them."""
    intro = bold("Introduction") + para("In 2019, 15 of 30 died.")
    path = paper(tmp_path, bold("Abstract") + para("Of 412 patients, 77 fell.") + intro,
                 "bold.docx")  # fmt: skip
    assert titles(path) == ["Falls in older patients", "Abstract", "Introduction", "Methods",
                            "Results"]  # fmt: skip
    report = audit([path], None)
    assert report.abstract.compared and report.abstract.numbers == 2, report.abstract
    lines = read_docx_text(path).body.split("\n")
    died = next(at for at, line in enumerate(lines, 1) if "died" in line)
    assert report.places[path].said(died) == "Introduction, paragraph 1"
    path = paper(tmp_path, para("Abstract: Of 412 patients, 77 fell.") + intro, "run-in.docx")
    assert audit([path], None).abstract.numbers == 2
    parts = (bold("Abstract") + bold("Background") + para("Falls harm.") + bold("Results")
             + para("Of 412 patients, 77 fell.") + intro)  # fmt: skip
    path = paper(tmp_path, parts, "parts.docx")
    assert titles(path) == ["Falls in older patients", "Abstract", "Introduction", "Methods",
                            "Results"]  # fmt: skip
    read = audit([path], None).abstract
    assert read.compared and read.numbers == read.matched == 2, read


#: Structured Abstracts whose parts are typed in bold and run up to the Introduction, a
#: heading styled as one, with `{}` for the number their Results give: parts that name
#: sections and one that does not, "Objective"; JAMA's, of which only "Results" names one;
#: and a run-in label over parts (round 1 of #683: each was cut at its first part named, and
#: its Results' number was the paper's, found where it differed).
STRUCTURED = {
    "parts in bold": (bold("Abstract") + bold("Objective") + para("To count falls.")
                      + bold("Methods") + para("We read records.") + bold("Results")
                      + para("Of 412, {} fell.") + bold("Conclusion")
                      + para("Falls are common.")),
    "JAMA's parts": (bold("Abstract") + bold("Importance") + para("Falls harm.")
                     + bold("Objective") + para("To count falls.")
                     + bold("Design, Setting, and Participants") + para("A cohort.")
                     + bold("Results") + para("Of 412, {} fell.")
                     + bold("Conclusions and Relevance") + para("Falls are common.")),
    "run-in, then parts": (para("Abstract: Falls harm the old.") + bold("Methods")
                           + para("We read records.") + bold("Results")
                           + para("Of 412, {} fell.") + bold("Conclusions")
                           + para("Falls are common.")),
}  # fmt: skip
#: The main text after them, opening on a heading styled as its Introduction.
INTRODUCED = (heading("Introduction") + para("Falls harm.") + heading("Methods")
              + para("We read 412 records.") + heading("Results") + para("Of 412, 77 fell."))


@pytest.mark.parametrize("kind", list(STRUCTURED))
def test_a_structured_abstract_s_parts_in_bold_run_to_the_next_heading(
    tmp_path: Path, kind: str,
) -> None:
    """The next heading's title is read with the parts: a styled Introduction ends them, as a
    typed one does, and the Abstract's own Results are the Abstract's, compared with the
    paper's. Cut at its first part named, the Abstract's "Results" was the paper's."""
    expected = ["Falls in older patients", "Abstract", "Introduction", "Methods", "Results"]
    for number in (77, 78):
        path = paper(tmp_path, STRUCTURED[kind].format(number), f"{number}.docx", INTRODUCED)
        assert titles(path) == expected
        read = audit([path], None).abstract
        assert read.compared, read
        assert [c.text for c in read.not_found] == ([] if number == 77 else ["78"]), read


@needs_pandoc
@pytest.mark.parametrize("kind", list(STRUCTURED))
def test_init_from_runs_a_structured_abstract_to_the_next_heading(
    tmp_path: Path, kind: str,
) -> None:
    path = paper(tmp_path, STRUCTURED[kind].format(78), after=INTRODUCED)
    converted = from_word.convert(path)
    assert _headings(converted.text) == [
        "Falls in older patients", "Abstract", "Introduction", "Methods", "Results"]
    assert converted.abstract_headings == ("Abstract",)


@needs_pandoc
@pytest.mark.parametrize("space", ["\N{NO-BREAK SPACE}", "\N{THIN SPACE}"],
                         ids=["no-break", "thin"])
def test_a_run_in_label_before_a_space_pandoc_keeps_keeps_the_words_after_it(
    tmp_path: Path, space: str,
) -> None:
    """pandoc keeps a no-break space or a thin space inside one piece of text, "Abstract:",
    the space and "412" together: taken off as the label's word, the 412 went with it, which
    the audit still reads (round 1 of #683)."""
    path = paper(tmp_path, para(f"Abstract:{space}412 patients were followed, and 77 fell."))
    converted = from_word.convert(path)
    body = converted.text[converted.text.find("-->") + 1 :]
    assert _headings(converted.text)[:2] == ["Falls in older patients", "Abstract"]
    assert "412 patients were followed, and 77 fell." in body and "Abstract:" not in body


def test_an_abstract_that_nothing_ends_is_not_read(tmp_path: Path) -> None:
    """docx-psych-A1 puts its only heading styles on its authors' lines, before the Abstract:
    with no heading after it, the Abstract ends at its Method typed in bold. With neither a
    heading nor a typed title after it, where it ends is not read, and neither is it."""
    authors = heading("Ana Martin, Paul Girard")
    body = bold("Abstract") + para("Of 412 patients, 77 fell.") + para("Falls harm.")
    path = _package(tmp_path / "ended.docx", authors + body + bold("Method") + para("We read."),
                    STYLES)  # fmt: skip
    assert titles(path) == ["Ana Martin, Paul Girard", "Abstract", "Method"]
    read = audit([path], None).abstract
    assert not read.compared and read.why_not.startswith(NO_RESULTS[:40])
    path = _package(tmp_path / "open.docx", authors + body, STYLES)
    assert titles(path) == ["Ana Martin, Paul Girard"]
    assert audit([path], None).abstract.why_not == NO_ABSTRACT


def test_a_run_in_label_is_read_in_a_paper_placed_by_its_typed_titles(tmp_path: Path) -> None:
    """With no heading style, the paper is placed by its typed titles, and a run-in label
    where none names the Abstract is its heading there too."""
    body = (para("Abstract: Of 412 patients, 77 fell.") + para("METHODS") + para("We read.")
            + para("RESULTS") + para("Of 412 patients, 77 fell."))  # fmt: skip
    path = _package(tmp_path / "typed.docx", body, "")
    assert titles(path) == ["Abstract", "METHODS", "RESULTS"]
    read = audit([path], None).abstract
    assert read.compared and read.numbers == read.matched == 2, read


def test_a_run_in_label_s_line_is_the_abstract_s_first_paragraph(tmp_path: Path) -> None:
    """Its line is a paragraph, said as one, and its sentences are read: it is no heading's
    line alone."""
    path = paper(tmp_path, para("Abstract: Of 412 patients, 77 fell.") + para("It was so."))
    report = audit([path], None)
    lines = read_docx_text(path).body.split("\n")
    first = next(at for at, line in enumerate(lines, 1) if line.startswith("Abstract:"))
    place = report.places[path]
    assert [place.said(first), place.said(first + 1)] == [
        "Abstract, paragraph 1", "Abstract, paragraph 2"]


def _headings(text: str) -> list[str]:
    """The titles of the Markdown `init --from` writes, as plain words."""
    found = []
    for line in text.split("\n"):
        if line.startswith("#"):
            title = re.sub(r"\s*\{[^}]*\}\s*$", "", line.lstrip("#").strip())
            found.append(title.replace("\\", ""))
    return found


#: A styled paper's Abstract in each shape, as `w:p` XML, and the headings both readers take.
SHAPES = {
    "run-in": (para("Abstract: Of 412 patients, 77 fell."), ["Abstract"]),
    "run-in, label in bold": (bold_label("Abstract:", "Of 412 patients, 77 fell."),
                              ["Abstract"]),
    "run-in, a space before the colon": (para("Abstract : Of 412 patients, 77 fell."),
                                         ["Abstract"]),
    # pandoc reads an indented paragraph as a block quote (docx-med-B3's is one).
    "run-in, indented": ('<w:p><w:pPr><w:ind w:left="720"/></w:pPr><w:r><w:t xml:space='
                         '"preserve">Abstract: Of 412 patients, 77 fell.</w:t></w:r></w:p>',
                         ["Abstract"]),
    "in bold": (bold("Abstract") + para("Of 412 patients, 77 fell."), ["Abstract"]),
    "in bold, ended": (bold("ABSTRACT") + para("Of 412 patients, 77 fell.") + bold("Introduction")
                       + para("In 2019, 15 died."), ["ABSTRACT", "Introduction"]),
    "plain": (para("Abstract") + para("Of 412 patients, 77 fell."), []),
    "a bold sentence": (bold("Abstracts were screened by two reviewers."), []),
}  # fmt: skip


@needs_pandoc
@pytest.mark.parametrize("kind", list(SHAPES))
def test_the_audit_and_init_take_the_same_abstract_headings(tmp_path: Path, kind: str) -> None:
    """`init --from` makes the same headings of each shape as the audit places the paper by:
    a run-in label a heading "Abstract" over the paragraph's text, a bold "Abstract" line a
    heading, and the title typed after it that ends it; a plain "Abstract" and a sentence in
    bold neither."""
    abstract, made = SHAPES[kind]
    path = paper(tmp_path, abstract)
    expected = ["Falls in older patients", *made, "Methods", "Results"]
    assert [" ".join(title.split()) for title in titles(path)] == expected
    converted = from_word.convert(path)
    assert _headings(converted.text) == expected
    assert converted.abstract_headings == tuple(made)
    body = converted.text[converted.text.find("-->") + 1 :]
    if kind.startswith("run-in"):
        assert "Abstract:" not in body and "Of 412 patients, 77 fell." in body
