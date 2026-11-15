"""The audit's masked text keeps every line of a Markdown paper where the paper has it.

`init --from` writes an HTML comment of several lines over every main.md it makes (the
converted paper's cover), and the mask turned a comment's line breaks to NUL, so that a
paragraph pandoc reads across a comment stays one paragraph. The audit takes lines from that
text, beside sections placed on the file's own lines: every number after the comment was put
as many lines too early, in the section above, and none of an Abstract's numbers was found in
the Results that repeat them (found building #691)."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.audit import _masked, audit
from manuscript_guard.text.masking import mask

COMMENT = "<!--\nAbstract\nIntroduction\n-->\n\n"
BODY = ("# Abstract\n\nOf 412 nurses, 77 fell (18.7%).\n\n# Introduction\n\nFalls harm nurses.\n\n"
        "# Results\n\nOf 412 nurses, 77 fell (18.7%).\n\n# Discussion\n\nFalls are common.\n")


def _paper(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "main.md"
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.mark.parametrize("comment", ["", "<!-- note -->\n\n", COMMENT,
                                     "<!--\n" + "note\n" * 12 + "-->\n\n"])  # fmt: skip
def test_an_abstract_after_a_comment_of_several_lines_is_matched(
    tmp_path: Path, comment: str
) -> None:
    """The paper `init --from` writes: its cover in a comment, then an Abstract whose
    numbers the Results repeat, and no Methods. All three were not found under a comment
    of four lines; all three are found."""
    read = audit([_paper(tmp_path, comment + BODY)], None).abstract
    assert read.compared
    assert (read.numbers, read.matched, read.not_found) == (3, 3, [])


def test_a_test_after_the_comment_is_reported_on_its_own_line(tmp_path: Path) -> None:
    """A t statistic and a P that do not meet: the finding names the line they are on, not
    one the comment's height above it."""
    sentence = "The groups differed, t(23) = 2.45, p = 0.40."
    text = COMMENT + BODY.replace("Falls are common.", sentence)
    found = audit([_paper(tmp_path, text)], None).disagreements
    assert [d.line for d in found] == [text.count("\n", 0, text.index(sentence)) + 1]


def test_a_share_after_the_comment_is_reported_on_its_own_line(tmp_path: Path) -> None:
    """A share its counts do not give, written in the Discussion: said at its line."""
    sentence = "In all, 100 of 400 nurses (40.0%) fell again."
    text = COMMENT + BODY.replace("Falls are common.", sentence)
    found = [d for d in audit([_paper(tmp_path, text)], None).disagreements
             if "40.0%" in d.context]  # fmt: skip
    assert [d.line for d in found] == [text.count("\n", 0, text.index(sentence)) + 1]


def test_a_citation_after_the_comment_is_reported_on_its_own_line(tmp_path: Path) -> None:
    """G7's census: a marker citing an entry the reference list does not hold, at its line."""
    sentence = "Falls are common [3]."
    text = (COMMENT + BODY.replace("Falls are common.", sentence)
            + "\n# References\n\n1. Smith J. Falls. J Nurs. 2019;12:45-67.\n\n"
              "2. Jones K. Nurses. J Nurs. 2020;13:1-9.\n")  # fmt: skip
    report = audit([_paper(tmp_path, text)], None)
    found = [p for census in report.references for p in census.problems
             if p.code == "citation-beyond-list"]  # fmt: skip
    assert [p.line for p in found] == [text.count("\n", 0, text.index(sentence)) + 1]


#: Each construct the mask hides, over several lines.
HIDDEN = {
    "comment": "<!--\none\n\ntwo\n-->\n",
    "comment in a paragraph": "Some text <!-- one\n\ntwo --> and more.\n",
    "fenced block": "```\none\n\ntwo\n```\n",
    "front matter": "---\ntitle: One\nauthor: Two\n---\n",
    "script": "<script>\nvar one = 1;\n\nvar two = 2;\n</script>\n",
    "style": "<style>\np { margin: 1px; }\n\nh1 { margin: 2px; }\n</style>\n",
    "footnote": "Text.[^1]\n\n[^1]: One, 12\n    two, 34.\n",
    "table": "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n",
    "line ends of a comment, CRLF": "<!--\r\none\r\n\r\ntwo\r\n-->\r\n",
}


@pytest.mark.parametrize("construct", HIDDEN)
def test_a_finding_after_what_the_mask_hides_is_on_its_own_line(
    tmp_path: Path, construct: str
) -> None:
    """Whatever the mask hides over several lines, a finding after it is said at its line;
    and what is read is masked as `mask` masks it, a comment's line breaks hidden with it."""
    sentence = "The groups differed, t(23) = 2.45, p = 0.40."
    text = f"# Abstract\n\n{HIDDEN[construct]}\n{sentence}\n"
    assert _masked(text, printed_as_typed=False) == mask(text)
    found = audit([_paper(tmp_path, text)], None).disagreements
    assert [d.line for d in found] == [text.count("\n", 0, text.index(sentence)) + 1]


#: A comment holding a blank line, typed inside a paragraph.
IN_A_PARAGRAPH = "<!-- see\n\nnotes -->"


def test_a_p_after_a_comment_in_its_sentence_is_read_with_its_statistic(
    tmp_path: Path,
) -> None:
    """Round 1 of #693: a blank line inside a comment ended the sentence where the comment's
    line breaks were kept in what is read, so the P after it was out of its statistic's
    reach, and a P that does not follow from it went unsaid. It is said, at its line."""
    sentence = f"The groups differed, t(23) = 2.45 {IN_A_PARAGRAPH} p = 0.40."
    text = COMMENT + BODY.replace("Falls are common.", sentence)
    found = audit([_paper(tmp_path, text)], None).disagreements
    assert [d.line for d in found] == [text.count("\n", 0, text.index(sentence)) + 1]


def test_a_word_that_makes_a_p_quiet_is_read_across_a_comment_in_its_sentence(
    tmp_path: Path,
) -> None:
    """Round 1 of #693: "Welch's" before a comment holding a blank line was cut off from the
    statistic after it, so its P was recomputed as a plain t test's and said to differ."""
    sentence = f"The groups differed, Welch's {IN_A_PARAGRAPH} t(23) = 2.45, p = 0.40."
    text = COMMENT + BODY.replace("Falls are common.", sentence)
    assert audit([_paper(tmp_path, text)], None).disagreements == []
