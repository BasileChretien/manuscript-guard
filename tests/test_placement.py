"""What G7 says of a quote its stored source does not hold (`literature/placement.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.literature.placement import GAP, layout_text, place, said, why_not_found
from manuscript_guard.literature.sources import contains

QUOTE = "The crude incidence of drug-induced hepatic injury was 14 per 100 000 person-years."
OPENING = "Methods.\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "The crude incidence of drug-induced hepatic injury was 14 per "
            "100\N{MIDDLE DOT}000 person-years.",
            "its words are all there, in order and together, and between '100' and '000' "
            "(line 2) the source has '\N{MIDDLE DOT}' where the quote has ' '",
        ),
        (
            "The crude incidence of drug-induced hepatic injury was 14 per 100 000 "
            "person-years; more.",
            "its words are all there, in order and together, and after 'years' (line 2) the "
            "source has ';' where the quote has '.'",
        ),
        (
            "The crude incidence of drug-induced hepatic\n41\n42\ninjury was 14 per 100 000 "
            "person-years.",
            "its words are all there in order; the source has '41 42' between 'hepatic' and "
            "'injury' (line 3): numbers, such as line numbers or a column of figures",
        ),
        (
            "The crude incidence of drug-induced hepatic   Table 2 shows the cohort\ninjury "
            "was 14 per 100 000 person-years.",
            "its words are all there in order; the source has 'Table 2 shows the cohort' "
            "between 'hepatic' and 'injury' (line 2): words the quote leaves out, or a "
            "column, a footnote or a running header",
        ),
        (
            "The crude incidence of drug-induced hepa-\ntic injury was 14 per 100 000 "
            "person-years.",
            "its words are all there in order; 'hepa' and 'tic' are one word, split by a "
            "hyphen (line 2)",
        ),
        (
            "The crude incidence of drug-induced hepa\N{SOFT HYPHEN}tic injury was 14 per "
            "100 000 person-years.",
            "its words are all there in order; 'hepa' and 'tic' are one word, split by a "
            "hyphen (line 2)",
        ),
        (
            "The crude incidence of drug-induced liver injury was 14 per 100 000 "
            "person-years.",
            "6 of its 15 words are there in order (line 2): 'The crude incidence of "
            "drug-induced'; after 'induced' the quote has 'hepatic', where the source has "
            "'liver injury was'",
        ),
        (
            "A crude incidence of drug-induced hepatic injury was 14 per 100 000 "
            "person-years.",
            "14 of its 15 words are there in order (line 2): 'crude incidence of "
            "drug-induced hepatic injury was 14 per 100 000 person-years'; its first word, "
            "'The', is not before them",
        ),
    ],
)
def test_a_quote_its_source_does_not_hold_is_placed(source: str, expected: str) -> None:
    source = OPENING + source + "\n"
    assert not contains(source, QUOTE)
    placement = place(source, QUOTE)
    assert placement is not None
    assert said(placement) == expected


def test_a_source_that_holds_nothing_of_the_quote_in_order_places_nothing() -> None:
    assert place("Nothing here is about it at all.\n", QUOTE) is None
    assert place(OPENING + "injury hepatic\n", QUOTE) is None
    assert place(QUOTE, "hepatic") is None


def test_words_further_apart_than_the_gap_are_not_read_as_the_quote() -> None:
    near = "hepatic " + " ".join(["x"] * GAP) + " injury"
    far = "hepatic " + " ".join(["x"] * (GAP + 1)) + " injury"
    assert place(near, "hepatic injury") is not None
    assert place(far, "hepatic injury") is None


def test_more_than_two_interruptions_are_counted_not_listed() -> None:
    source = "a 1 b 2 c 3 d 4 e"
    placement = place(source, "a b c d e")
    assert placement is not None and len(placement.breaks) == 4
    assert said(placement).endswith("; and 2 more")


def test_the_lines_of_a_page_are_its_own_and_a_pdf_s_are_not_given(tmp_path: Path) -> None:
    """An HTML page's tags are blanked where they stand, so a line is the file's line; the
    text read from a PDF has lines of its reader's making, and none are given."""
    page = tmp_path / "source.html"
    page.write_text(
        "<html>\n<head><script>var x = 1;\nvar y = 2;</script></head>\n<body>\n"
        "<p>The crude incidence of drug-induced hepatic</p>\n<p>12</p>\n"
        "<p>injury was 14 per 100 000 person-years.</p>\n</body></html>\n",
        encoding="utf-8",
    )
    assert layout_text(page).count("\n") == page.read_text(encoding="utf-8").count("\n")
    why = why_not_found(page, QUOTE)
    assert why is not None and "'12' between 'hepatic' and 'injury' (line 6)" in why
    placement = place(layout_text(page), QUOTE)
    assert placement is not None and "(line" not in said(placement, numbered=False)


def test_a_source_that_cannot_be_read_again_places_nothing(tmp_path: Path) -> None:
    assert why_not_found(tmp_path / "gone.txt", QUOTE) is None
    assert why_not_found(tmp_path / "source.docx", QUOTE) is None


def test_an_interruption_holding_one_of_the_quote_s_words_is_one_interruption() -> None:
    """Round 1 of #301: a running header with "The" in it was read as the quote's "the", and
    the break named between the wrong words. Of the readings that find as many words, the
    one with the fewest interruptions is taken."""
    source = "the risk of\n12\nThe New England Journal of Medicine\nthe disease was low\n"
    placement = place(source, "the risk of the disease was low")
    assert placement is not None
    assert said(placement) == (
        "its words are all there in order; the source has '12 The New England Journal of "
        "Medicine' between 'of' and 'the' (line 2): words the quote leaves out, or a column, "
        "a footnote or a running header"
    )
