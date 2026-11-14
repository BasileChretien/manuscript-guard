"""A run-in "Keywords:" under a Word paper's Abstract, after its words and before any part
title of it, ends the Abstract (Basile, 2026-11-15). Two papers of the real-paper corpus lost
their comparison to it: docx-psych-B2, a one-paragraph Abstract, "Keywords:", an Introduction
with no heading, then Results, Discussion and Conclusion typed in bold, which were read as the
Abstract's own parts; and docx-psych-A1, an Abstract of run-in parts ("Background: …"),
"Keywords:", an Introduction with no heading, then "Method", over which the Abstract ran. The
cases here are their shapes, not their text."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from test_from_word import _package
from test_word_abstract import STYLES, _headings, bold, heading, para

from manuscript_guard import from_word
from manuscript_guard.audit import audit
from manuscript_guard.text.docx import read_docx_text
from manuscript_guard.text.docx_abstract import placed_headings

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

#: An Introduction with no heading, the paper's title in bold over it as docx-psych-B2 repeats
#: it, its numbers other papers' (docx-psych-A1's "up to 45% of children", "80%").
UNHEADED = (bold("Falls in Older Patients: A Cohort") + para("Up to 45% of older people fall.")
            + para("Rates as high as 80% (Hicks et al., 2004) were seen."))  # fmt: skip


def b2(abstract: str = "Of 412 patients, 77 fell.", results: str = "Of 412 patients, 77 fell.",
       keywords: str = "Keywords: falls; older adults; cohort") -> str:  # fmt: skip
    """docx-psych-B2's shape, a paper with no heading style: a one-paragraph Abstract, the
    keywords' line, an Introduction with no heading, then Results, Discussion and Conclusion
    typed in bold, and Methods last."""
    return (bold("Abstract") + para(abstract) + para(keywords) + UNHEADED + bold("Results")
            + para(results) + bold("Discussion") + para("Falls are common.")
            + bold("Conclusion") + para("They matter.") + bold("Methods")
            + para("We read 412 records."))  # fmt: skip


#: docx-psych-A1's shape, a paper whose heading styles stand on its authors' line alone: a
#: bold "Abstract", its parts run-in labels inside its paragraphs, the keywords' line, an
#: Introduction with no heading, then a bold "Method", and the Results styled after it.
A1 = (heading("Ana Martin, Paul Girard") + bold("Abstract")
      + para("Background: Falls harm older people.") + para("Methods: We read 412 records.")
      + para("Results: Of 412 patients, 77 fell.") + para("Conclusions: Falls are common.")
      + para("Keywords: falls; older adults") + UNHEADED + bold("Method")
      + para("We read 412 records.") + heading("Results") + para("Of 412 patients, 77 fell."))


def titles(path: Path) -> list[tuple[int, str]]:
    return [(one.level, " ".join(one.title.split()))
            for one in placed_headings(read_docx_text(path))]  # fmt: skip


def test_keywords_after_a_one_paragraph_abstract_leave_the_results_the_paper_s(
    tmp_path: Path,
) -> None:
    """docx-psych-B2: read as the Abstract's parts, "Results", "Discussion" and "Conclusion"
    left the paper no Results outside it, and the Abstract was compared with nothing. The
    keywords' line ends the Abstract: the Results are the paper's own, at level 1, and the
    Introduction under the keywords reports nothing."""
    path = _package(tmp_path / "paper.docx", b2(), "")
    assert titles(path) == [(1, "Abstract"), (1, "Keywords"), (1, "Results"),
                            (1, "Discussion"), (1, "Conclusion"), (1, "Methods")]  # fmt: skip
    report = audit([path], None)
    read = report.abstract
    assert read.compared and read.numbers == read.matched == 2 and read.not_found == [], read
    lines = read_docx_text(path).body.split("\n")
    fell = next(at for at, line in enumerate(lines, 1) if "45%" in line)
    assert report.places[path].said(fell) == "Keywords, paragraph 3"


def test_a_contents_list_on_the_cover_still_lets_the_keywords_end_the_abstract(
    tmp_path: Path,
) -> None:
    """docx-psych-B2 repeats "Abstract" in a contents list on its cover, so its titles are
    placed by those in bold alone: the keywords' line, in plain type, ends the Abstract
    there too."""
    cover = (para("The present document contains the following:") + para("Abstract")
             + para("Introduction") + para("Methods"))  # fmt: skip
    path = _package(tmp_path / "paper.docx", cover + b2(), "")
    assert [title for _level, title in titles(path)] == [
        "Abstract", "Keywords", "Results", "Discussion", "Conclusion", "Methods"]
    read = audit([path], None).abstract
    assert read.compared and read.numbers == read.matched == 2, read


def test_the_introduction_after_the_keywords_is_not_the_abstract_s(tmp_path: Path) -> None:
    """docx-psych-A1: the Abstract ran on to "Method", over its Introduction, and once the
    paper was compared its Introduction's 45% and 80% were the Abstract's numbers, not found.
    The keywords' line ends the Abstract: those numbers are compared with nothing."""
    path = _package(tmp_path / "paper.docx", A1, STYLES)
    assert titles(path) == [(1, "Ana Martin, Paul Girard"), (1, "Abstract"), (1, "Keywords"),
                            (1, "Method"), (1, "Results")]  # fmt: skip
    read = audit([path], None).abstract
    assert read.compared and read.not_found == [], read
    assert read.numbers == read.matched == 3, read


def test_keywords_before_an_abstract_s_titled_parts_end_nothing(tmp_path: Path) -> None:
    """A journal may set the keywords between the Abstract's title and its first part: where
    the parts are titles of their own lines, they stay the Abstract's, and its own "Results"
    is not the paper's."""
    body = (bold("Abstract") + para("Keywords: falls; older adults") + bold("Background")
            + para("Falls harm.") + bold("Results") + para("Of 412 patients, 78 fell.")
            + bold("Conclusions") + para("They matter.") + bold("Introduction")
            + para("Falls harm older people.") + bold("Methods") + para("We read 412 records.")
            + bold("Results") + para("Of 412 patients, 77 fell."))  # fmt: skip
    path = _package(tmp_path / "paper.docx", body, "")
    assert titles(path) == [(1, "Abstract"), (2, "Background"), (2, "Results"),
                            (2, "Conclusions"), (1, "Introduction"), (1, "Methods"),
                            (1, "Results")]  # fmt: skip
    read = audit([path], None).abstract
    assert read.compared and [c.text for c in read.not_found] == ["78"], read


@pytest.mark.parametrize("keywords", [
    "The keywords: falls; older adults were searched.",
    "Keywords were searched in 3 databases.",
    "Keywords:",
    "Keywords:falls",
], ids=["a sentence's", "opening a sentence", "nothing after it", "no space after it"])
def test_keywords_in_a_sentence_end_nothing(tmp_path: Path, keywords: str) -> None:
    """"Keywords" in a sentence, or a label with no words after it, ends nothing: the titles
    after the Abstract are read as they were, its parts."""
    path = _package(tmp_path / "paper.docx", b2(keywords=keywords), "")
    assert titles(path) == [(1, "Abstract"), (2, "Results"), (2, "Discussion"),
                            (2, "Conclusion"), (1, "Methods")]  # fmt: skip
    assert not audit([path], None).abstract.compared


def test_keywords_in_a_table_s_cell_end_nothing(tmp_path: Path) -> None:
    """Only a line a title can be typed as ends the Abstract, in no table's cell, as a typed
    title is read."""
    cell = "<w:tbl><w:tr><w:tc>" + para("Keywords: falls; older adults") + "</w:tc></w:tr></w:tbl>"
    body = b2().replace(para("Keywords: falls; older adults; cohort"), cell)
    path = _package(tmp_path / "paper.docx", body, "")
    assert [level for level, _title in titles(path)] == [1, 2, 2, 2, 1]


def test_the_label_is_read_in_the_shapes_it_is_typed_in() -> None:
    from manuscript_guard.text.section_names import keywords_end, run_in_keywords

    assert [run_in_keywords(text) for text in (
        "Keywords: falls", " Key words: falls", "KEYWORDS: falls", "Key Words: falls",
        "KEY WORDS: falls", "Keywords : falls", "Keywords:\N{NO-BREAK SPACE}falls")] == [
        "Keywords:", "Key words:", "KEYWORDS:", "Key Words:", "KEY WORDS:", "Keywords :",
        "Keywords:"]  # fmt: skip
    assert [run_in_keywords(text) for text in (
        "keywords: falls", "Keywords were read", "The keywords: falls", "Keywords:",
        "Keywords. Falls")] == [None] * 5  # fmt: skip
    # Words before the first label; none before it, as above a structured abstract's parts.
    assert keywords_end([True, True, True], [False, True, False]) == 1
    assert keywords_end([True, True], [True, False]) is None
    assert keywords_end([True, True, True], [True, False, True]) is None
    assert keywords_end([False, True], [False, False]) is None


#: Papers in each shape, and the headings both readers take.
AGREED = {
    "docx-psych-B2's": (b2(), "", ["Abstract", "Keywords", "Results", "Discussion",
                                   "Conclusion", "Methods"]),
    "Key words": (b2(keywords="Key words: falls; cohort"), "",
                  ["Abstract", "Key words", "Results", "Discussion", "Conclusion", "Methods"]),
    "in capitals": (b2(keywords="KEYWORDS: falls; cohort"), "",
                    ["Abstract", "KEYWORDS", "Results", "Discussion", "Conclusion", "Methods"]),
    "docx-psych-A1's": (A1, STYLES, ["Ana Martin, Paul Girard", "Abstract", "Keywords", "Method",
                                     "Results"]),
    "a run-in Abstract": (heading("Falls") + para("Abstract: Of 412 patients, 77 fell.")
                          + para("Keywords: falls") + para("Falls harm older people.")
                          + heading("Methods") + para("We read 412 records."), STYLES,
                          ["Falls", "Abstract", "Keywords", "Methods"]),
    "a styled Abstract": (heading("Abstract") + para("Of 412 patients, 77 fell.")
                          + para("Key Words: falls") + para("Falls harm older people.")
                          + heading("Methods") + para("We read 412 records."), STYLES,
                          ["Abstract", "Key Words", "Methods"]),
    "in a table's cell": (heading("Abstract") + para("Of 412 patients, 77 fell.")
                          + "<w:tbl><w:tr><w:tc>" + para("Keywords: falls")
                          + "</w:tc></w:tr></w:tbl>" + para("Falls harm older people.")
                          + heading("Methods") + para("We read 412 records."), STYLES,
                          ["Abstract", "Methods"]),
    "no words after them": (heading("Falls") + bold("Abstract") + para("Of 412, 77 fell.")
                            + para("Keywords: falls") + heading("Methods")
                            + para("We read 412 records."), STYLES,
                            ["Falls", "Abstract", "Methods"]),
    "before titled parts": (bold("Abstract") + para("Keywords: falls") + bold("Background")
                            + para("Falls harm.") + bold("Results") + para("Of 412, 77 fell.")
                            + bold("Introduction") + para("Falls harm.") + bold("Methods")
                            + para("We read."), "",
                            ["Abstract", "Background", "Results", "Introduction", "Methods"]),
    "in a sentence": (b2(keywords="Keywords were searched in 3 databases."), "",
                      ["Abstract", "Results", "Discussion", "Conclusion", "Methods"]),
}  # fmt: skip


@needs_pandoc
@pytest.mark.parametrize("kind", list(AGREED))
def test_the_audit_and_init_take_the_same_end_at_the_keywords(tmp_path: Path, kind: str) -> None:
    """`init --from` ends the Abstract where the audit does: the keywords' run-in label made a
    heading of its own over the keywords, at the Abstract's level, the titles after it at
    the levels the audit gives them; and neither where it ends nothing."""
    body, styles, expected = AGREED[kind]
    path = _package(tmp_path / "paper.docx", body, styles)
    audited = titles(path)
    assert [title for _level, title in audited] == expected
    converted = from_word.convert(path)
    assert _headings(converted.text) == expected
    written = converted.text.split("-->", 1)[-1]
    levels = [len(line) - len(line.lstrip("#")) for line in written.split("\n")
              if line.startswith("#")]  # fmt: skip
    assert levels == [level for level, _title in audited]
    keywords = next((title for title in expected if title.casefold().startswith("key")), None)
    assert converted.keywords_heading == keywords
    if keywords:
        assert f"{keywords}:" not in written and "falls" in written
