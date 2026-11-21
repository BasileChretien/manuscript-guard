"""The publisher's proof held to what was sent (`manuscript-guard proof`).

Each kind of change a typesetter makes is planted in a proof of a few parts, and the report
is held to what it says of it: a correction where a number, a sign, a decimal mark, a unit,
a citation, a reference, a name or an affiliation changed or a part is gone; typography,
shown and not counted, where the same value is set otherwise; a copy-edit where only words
changed. The proofs are text with pages parted by form feeds, as pdftotext writes them, and
PDFs written by `tests/proof_pdf.py`, read by pypdf and by each pdftotext on the machine.
The last tests run the command on the example's own submission pack.
"""

from __future__ import annotations

import itertools
import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.proof import reading as proof_reading
from manuscript_guard.proof.compare import ADDED, COPY_EDIT, CORRECTION, MOVED, compare
from manuscript_guard.proof.reading import UnreadableProof, readings
from manuscript_guard.proof.sent import CELL, HEADING, PARAGRAPH, REFERENCE, Part, Sent
from manuscript_guard.proof.tokens import TYPOGRAPHY

sys.path.insert(0, str(Path(__file__).parent))
from proof_pdf import typeset  # noqa: E402

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")
MINUS = "\N{MINUS SIGN}"

PARTS = (
    Part(HEADING, "Results", 'the heading "Results"'),
    Part(PARAGRAPH, "The database contained 4000 reports, of which 426 named example-drug. "
         "The reporting odds ratio was 3.84 (95% CI 2.89 to 5.12; P < 0.001), and the mean "
         f"change in weight was {MINUS}0.51 mg (SD 0.20) over 12 weeks.",
         'the paragraph "The database contained 4000 reports"'),
    Part(PARAGRAPH, "Hepatic injury was reported in 77 of these [4], as earlier work had "
         "found in a national cohort (Smith and Jones 2019).",
         'the paragraph "Hepatic injury was reported"'),
    Part(CELL, "Characteristic", 'Table 1, the header "Characteristic"', table=1),
    Part(CELL, "example-drug", 'Table 1, the header "example-drug"', table=1),
    Part(CELL, "Other drugs", 'Table 1, the header "Other drugs"', table=1),
    Part(CELL, "Female", 'Table 1, the row "Female"', table=1),
    Part(CELL, "226 (53.1)", 'Table 1, row "Female", column "example-drug"', table=1),
    Part(CELL, "1737 (48.6)", 'Table 1, row "Female", column "Other drugs"', table=1),
    Part(CELL, "Serious", 'Table 1, the row "Serious"', table=1),
    Part(CELL, "160 (37.6)", 'Table 1, row "Serious", column "example-drug"', table=1),
    Part(CELL, "1356 (37.9)", 'Table 1, row "Serious", column "Other drugs"', table=1),
    Part(HEADING, "Discussion", 'the heading "Discussion"'),
    Part(PARAGRAPH, "The reporting odds ratio observed here exceeds the class-level estimate "
         "of 2.6 reported previously, although the two are not directly comparable: that "
         "analysis pooled the class and drew on a different reporting period.",
         'the paragraph "The reporting odds ratio observed"'),
    Part(PARAGRAPH, "Several limitations follow from the design. Spontaneous reports are "
         "subject to notoriety bias, and the denominator is unknown.",
         'the paragraph "Several limitations follow"'),
    Part(HEADING, "Funding", 'the heading "Funding"'),
    Part(PARAGRAPH, "This work received no funding from any agency.",
         'the paragraph "This work received no funding"'),
    Part(REFERENCE, "1. Smith A, Jones B. Hepatic injury in a national cohort. J Imag "
         "Pharmacoepidemiol. 2019;12:101-9.", 'reference 1, "1. Smith A, Jones B."'),
    Part(REFERENCE, "2. Brown C. A disproportionality signal for a drug class. Drug Saf Rep. "
         "2020;7:45-52.", 'reference 2, "2. Brown C. A"'),
)
SENT = Sent(Path("manuscript.docx"), PARTS, (), None)


def unwrapped(parts=PARTS) -> str:
    """The parts a line each, a table's cells a row to a line, three to a row."""
    lines: list[str] = []
    row: list[str] = []
    for part in [*parts, None]:
        if part is not None and part.kind == CELL:
            row.append(part.text)
            if len(row) == 3:
                lines.append("   ".join(row))
                row = []
            continue
        if row:
            lines.append("   ".join(row))
            row = []
        if part is not None:
            lines.append(part.text)
    return "\n".join(lines)


def wrapped(text: str, width: int = 46) -> list[str]:
    """Each line wrapped to a column's width, as a proof sets it; a table's row kept whole."""
    return [piece for line in text.split("\n")
            for piece in ([line] if "   " in line else
                          textwrap.wrap(line, width, break_on_hyphens=False))]  # fmt: skip


def typeset_lines(parts=PARTS, width: int = 46) -> list[str]:
    return wrapped(unwrapped(parts), width)


def paged(lines: list[str], per_page: int = 14, head: str = "Example et al. J Imag Pharm 2026",
          first: int = 101) -> str:  # fmt: skip
    """The lines in pages, each with a running head over it and its number under it, parted
    by form feeds as pdftotext parts them."""
    pages = [lines[at : at + per_page] for at in range(0, len(lines), per_page)]
    return "\f".join(
        "\n".join([head, *page, str(first + index)]) for index, page in enumerate(pages)
    )


def edited(text: str, *edits: tuple[str, str]) -> str:
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new, 1)
    return text


def changes_of(tmp_path: Path, *edits: tuple[str, str], sent: Sent = SENT, text: str | None = None):
    """What the comparison says of a proof of `sent` with `edits` made to its parts before
    they were set, or of the proof `text`."""
    if text is None:
        text = paged(wrapped(edited(unwrapped(sent.parts), *edits)))
    proof = tmp_path / "proof.txt"
    proof.write_text(text, encoding="utf-8")
    (reading,) = readings(proof)
    return compare(sent, reading)


def corrections(result) -> list:
    return [change for change in result.changes if change.kind == CORRECTION]


def kinds(result, kind: str) -> list:
    return [change for change in result.changes if change.kind == kind]


# ---------------------------------------------------------------- what is not a change


def test_a_proof_that_prints_what_was_sent_needs_no_correction(tmp_path: Path) -> None:
    result = changes_of(tmp_path)
    assert result.changes == ()
    assert result.found == result.total


def test_running_heads_and_page_numbers_are_taken_out(tmp_path: Path) -> None:
    proof = tmp_path / "proof.txt"
    proof.write_text(paged(typeset_lines()), encoding="utf-8")
    (reading,) = readings(proof)
    assert reading.pages >= 2
    assert "Example et al. J Imag Pharm 2026" in reading.furniture
    assert "page numbers" in reading.furniture
    assert not any(line.text.startswith("Example et al.") for line in reading.lines)
    assert [line.page for line in reading.lines][:2] == [1, 1]


HEAD = "Example et al. J Imag Pharm 2026"


def test_a_line_at_the_top_of_half_the_pages_is_taken_out_as_a_running_head(
    tmp_path: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "What a page repeats is found by rule."): a
    table's header repeated at the top of half the pages is taken out with the running head,
    and its cells are reported missing; so is a line of the text that stands there as often.
    The same header atop one page of four is kept."""
    lines = typeset_lines()
    header, female, serious = (line for line in lines if "   " in line)
    pages = [[HEAD, *lines[:9], "101"], [HEAD, header, female, "102"],
             [HEAD, header, serious, *lines[12:20], "103"], [HEAD, *lines[20:], "104"]]
    result = changes_of(tmp_path, text="\f".join("\n".join(page) for page in pages))
    assert "Characteristic example-drug Other drugs" in result.reading.furniture
    assert [(c.what, c.part) for c in result.changes] == [
        ("missing", PARTS[3].label), ("missing", PARTS[4].label), ("missing", PARTS[5].label)]
    del pages[2][1]
    assert changes_of(tmp_path, text="\f".join("\n".join(page) for page in pages)).changes == ()
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "Table 1 shows the counts by year.", "one"),
                                 *PARTS[1:3],
                                 Part(PARAGRAPH, "Table 2 shows the counts by year.", "two"),
                                 *PARTS[13:15]), (), None)  # fmt: skip
    text = typeset_lines(sent.parts)
    cut = text.index("Table 2 shows the counts by year.")
    proof = "\f".join("\n".join([HEAD, *page, str(101 + k)])
                      for k, page in enumerate((text[:cut], text[cut:])))  # fmt: skip
    result = changes_of(tmp_path, sent=sent, text=proof)
    assert [(c.what, c.part, c.page) for c in result.changes] == [("missing", "one", 1),
                                                                   ("missing", "two", 2)]


def test_a_running_head_off_the_edge_or_on_a_proof_of_one_page_is_added(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "What a page repeats is found by rule."): a
    running head a reader puts in the middle of a page, here between two parts, is shown as
    added; a proof of one page has nothing taken out, and its head and number are added."""
    lines = typeset_lines()
    pages = paged(lines, per_page=7).split("\f")
    second = pages[1].split("\n")
    second.insert(second.index("Discussion"), HEAD)
    pages[1] = "\n".join(second)
    result = changes_of(tmp_path, text="\f".join(pages))
    assert HEAD in result.reading.furniture
    assert [(c.kind, c.printed, c.page) for c in result.changes] == [(ADDED, HEAD, 2)]
    result = changes_of(tmp_path, text="\n".join([HEAD, *lines, "101"]))
    assert result.reading.furniture == ()
    assert [(c.kind, c.printed) for c in result.changes] == [(ADDED, f"{HEAD} 101")]
    assert changes_of(tmp_path, text=paged(lines)).changes == ()


def test_a_word_broken_at_a_line_end_is_one_word(tmp_path: Path) -> None:
    text = paged(typeset_lines())
    text = edited(text, ("notoriety", "noto-\nriety"), ("class-level", "class-\nlevel"))
    assert changes_of(tmp_path, text=text).changes == ()


def test_a_compound_a_reader_joined_at_a_line_end_is_split_again(tmp_path: Path) -> None:
    # poppler's layout order takes the hyphen out at a line's end, a compound's own too.
    assert changes_of(tmp_path, ("class-level", "classlevel")).changes == ()


# ---------------------------------------------------------------- corrections


def test_a_digit_changed_is_a_correction_with_its_page(tmp_path: Path) -> None:
    result = changes_of(tmp_path, ("ratio was 3.84", "ratio was 3.48"))
    (change,) = corrections(result)
    assert (change.what, change.was, change.now) == ("number", "3.84", "3.48")
    assert change.part == PARTS[1].label
    assert change.page == 1
    assert "3.48" in change.printed and "3.84" in change.sent


def test_a_decimal_mark_changed_is_a_correction(tmp_path: Path) -> None:
    (change,) = corrections(changes_of(tmp_path, ("ratio was 3.84", "ratio was 3,84")))
    assert change.what == "decimal mark"


def test_a_decimal_comma_before_three_digits_is_a_number_changed(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "Numbers stand for any number in the
    alignment."): a comma before exactly three digits groups them, so "3.845" printed
    "3,845" is a correction of the number, and "3.84" printed "3,84" one of its mark."""
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "The ratio was 3.845 in the primary "
                                      "analysis of the cohort.", "p"),), (), None)  # fmt: skip
    (change,) = corrections(changes_of(tmp_path, ("3.845", "3,845"), sent=sent))
    assert (change.what, change.was, change.now) == ("number", "3.845", "3,845")
    assert change.note == "the number is printed otherwise"
    two = Sent(Path("m.docx"), (Part(PARAGRAPH, "The ratio was 3.84 in the primary analysis "
                                     "of the cohort.", "p"),), (), None)  # fmt: skip
    (change,) = corrections(changes_of(tmp_path, ("3.84", "3,84"), sent=two))
    assert (change.what, change.was, change.now) == ("decimal mark", "3.84", "3,84")


def test_a_sign_lost_is_a_correction(tmp_path: Path) -> None:
    (change,) = corrections(changes_of(tmp_path, (f"{MINUS}0.51", "0.51")))
    assert (change.what, change.was, change.now) == ("sign", f"{MINUS}0.51", "0.51")


def test_a_minus_left_at_a_line_s_end_is_the_sign_lost(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "A proof is compared as far as its text can be
    read, and no further."): a minus a reader leaves at the end of a line, apart from its
    number, is reported as the sign lost; kept with its number, it is no change."""
    text = f"The mean change in weight was {MINUS}0.51 mg over the twelve weeks of the study."
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, text, "p"),), (), None)
    broken = text.replace(f"was {MINUS}", f"was {MINUS}\n")
    (change,) = corrections(changes_of(tmp_path, sent=sent, text=broken))
    assert (change.what, change.was, change.now) == ("sign", f"{MINUS}0.51", "0.51")
    whole = text.replace(f"was {MINUS}", f"was\n{MINUS}")
    assert changes_of(tmp_path, sent=sent, text=whole).changes == ()


@pytest.mark.parametrize(("printed", "sign"), [
    ("0.71 \N{EN DASH}0.89", True), ("0.71\N{EN DASH}0.89", False),
    ("0.71 \N{EN DASH} 0.89", False),
])  # fmt: skip
def test_a_range_s_dash_spaced_on_one_side_reads_as_a_minus(
    tmp_path: Path, printed: str, sign: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A proof is compared as far as its text can be
    read, and no further."): a range's dash spaced on its left only reads as a minus, and the
    bound is reported as a sign changed; spaced on neither side or on both, it joins a
    range."""
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "The interval was 0.71-0.89 in the primary "
                                      "analysis of the cohort.", "p"),), (), None)  # fmt: skip
    result = changes_of(tmp_path, ("0.71-0.89", printed), sent=sent)
    said = [(c.what, c.was, c.now) for c in corrections(result)]
    assert said == ([("sign", "0.89", "\N{EN DASH}0.89")] if sign else [])


@pytest.mark.parametrize("glyph", ["-", "\N{HYPHEN}", "\N{EN DASH}"])
def test_a_minus_set_as_a_hyphen_is_typography(tmp_path: Path, glyph: str) -> None:
    result = changes_of(tmp_path, (f"{MINUS}0.51", f"{glyph}0.51"))
    assert corrections(result) == []
    (change,) = kinds(result, TYPOGRAPHY)
    assert "minus" in change.note


def test_a_number_set_otherwise_is_typography(tmp_path: Path) -> None:
    result = changes_of(tmp_path, ("1737 (48.6)", "1 737 (48.6)"), ("P < 0.001", "P < .001"))
    assert corrections(result) == []
    assert len(kinds(result, TYPOGRAPHY)) == 2


def test_two_cells_swapped_are_two_corrections_that_say_so(tmp_path: Path) -> None:
    result = changes_of(tmp_path, ("226 (53.1)   1737 (48.6)", "1737 (48.6)   226 (53.1)"))
    found = corrections(result)
    assert [c.part for c in found] == [PARTS[7].label, PARTS[8].label]
    assert [(c.sent, c.printed) for c in found] == [("226 (53.1)", "1737 (48.6)"),
                                                     ("1737 (48.6)", "226 (53.1)")]
    assert all("swapped" in c.note for c in found)


@pytest.mark.parametrize("edit", [
    ("0.51 mg", "0.51 \N{GREEK SMALL LETTER MU}g"),
    ("(95% CI", "(95 CI"),
    ("P < 0.001", "P = 0.001"),
    ("0.51 mg", "0.51 mM"),
])  # fmt: skip
def test_a_unit_or_a_comparator_changed_beside_a_number_is_a_correction(
    tmp_path: Path, edit: tuple[str, str]
) -> None:
    (change,) = corrections(changes_of(tmp_path, edit))
    assert change.what == "unit or symbol"


def test_a_unit_kept_in_its_case(tmp_path: Path) -> None:
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "The dose was 5 mM in the bath.", "p"),), (), None)
    (change,) = corrections(changes_of(tmp_path, ("5 mM", "5 mm"), sent=sent))
    assert change.what == "unit or symbol"


def test_a_citation_number_changed_is_a_correction(tmp_path: Path) -> None:
    (change,) = corrections(changes_of(tmp_path, ("these [4]", "these [3]")))
    assert change.what == "citation"


def test_a_superscript_citation_changed_is_a_correction(tmp_path: Path) -> None:
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "Injury was common in older patients.12 It "
                                     "was rare otherwise.", "p"),), (), None)  # fmt: skip
    (change,) = corrections(changes_of(tmp_path, ("patients.12", "patients.13"), sent=sent))
    assert change.what == "citation"


@pytest.mark.parametrize(("sent_as", "printed", "what"), [
    ("ICD10", "ICD11", "citation"), ("H2O", "H3O", "citation"), ("ICD1000", "ICD1001", "number"),
])  # fmt: skip
def test_a_number_set_against_a_word_is_told_from_a_citation_by_its_shape(
    tmp_path: Path, sent_as: str, printed: str, what: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A proof is compared as far as its text can be
    read, and no further."): a superscript loses its raise, so three digits at most set
    against a letter read as a citation's, and a change in "ICD10" or "H2O" is called a
    citation's; four digits are a number."""
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, f"Every report was coded as {sent_as} in the "
                                      "cohort as a whole.", "p"),), (), None)  # fmt: skip
    (change,) = corrections(changes_of(tmp_path, (sent_as, printed), sent=sent))
    assert change.what == what


def test_an_exponent_that_lost_its_raise_is_typography(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "A proof is compared as far as its text can be
    read, and no further."): "10" with a raised minus and "3" read as "10-3" is shown as
    typography, the dash shown as a copy-edit, and nothing is counted."""
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, f"The rate was 5 x 10{MINUS}3 per patient-year "
                                      "in the cohort.", "p"),), (), None)  # fmt: skip
    result = changes_of(tmp_path, (f"10{MINUS}3", "10-3"), sent=sent)
    assert corrections(result) == []
    (change,) = kinds(result, TYPOGRAPHY)
    assert change.note == "the sign is set differently beside the number before it"
    assert [(c.sent, c.printed) for c in kinds(result, COPY_EDIT)] == [("", "-")]


@pytest.mark.parametrize("edit", [("Jones 2019)", "Jones 2018)"), ("(Smith and", "(Smyth and")])
def test_an_author_year_citation_changed_is_a_correction(tmp_path: Path, edit) -> None:
    (change,) = corrections(changes_of(tmp_path, edit))
    assert change.what == "citation"


@pytest.mark.parametrize("edit", [("2019;12:101-9", "2019;12:110-9"), ("Smith A, Jones B",
                                                                       "Smith A, Janes B")])
def test_a_reference_entry_changed_is_a_correction(tmp_path: Path, edit) -> None:
    (change,) = corrections(changes_of(tmp_path, edit))
    assert change.what == "reference"


def test_a_renumbered_reference_is_a_correction_in_the_list_and_the_text(tmp_path: Path) -> None:
    found = corrections(changes_of(tmp_path, ("these [4]", "these [3]"),
                                   ("1. Smith A", "2. Smith A"), ("2. Brown C", "1. Brown C")))
    assert {c.what for c in found} == {"citation", "reference"}
    assert len([c for c in found if c.what == "reference"]) == 2


def test_a_part_the_proof_leaves_out_is_a_correction(tmp_path: Path) -> None:
    text = "\n".join(line for line in typeset_lines() if "Several limitations" not in line
                     and "subject to notoriety" not in line and "denominator" not in line)
    (change,) = corrections(changes_of(tmp_path, text=paged(text.split("\n"))))
    assert (change.what, change.part) == ("missing", PARTS[14].label)


def test_a_number_the_proof_drops_from_a_sentence_is_a_correction(tmp_path: Path) -> None:
    (change,) = corrections(changes_of(tmp_path, (" over 12 weeks", " over weeks")))
    assert change.what == "number"
    assert change.note == "a number sent is not printed"


def test_a_number_dropped_beside_another_may_name_the_first_s_binding(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "Numbers stand for any number in the
    alignment."): "12 15" printed "15" reads as the first changed and the second dropped,
    two corrections, the first naming the first number's binding; printed "12", it reads as
    the second dropped."""
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "The counts were 12 15 in the two arms of "
                                      "the trial at baseline.", "p"),), (), None)  # fmt: skip

    def said(printed: str) -> list[tuple[str, str, str, str, str]]:
        proof = tmp_path / "proof.txt"
        proof.write_text(sent.parts[0].text.replace("12 15", printed), encoding="utf-8")
        (reading,) = readings(proof)
        result = compare(sent, reading, origin=lambda _part, raw: f"the binding of {raw}")
        return [(c.what, c.was, c.now, c.source, c.note) for c in corrections(result)]

    assert said("15") == [
        ("number", "12", "15", "the binding of 12", "the number is printed otherwise"),
        ("number", "", "", "the binding of 15", "a number sent is not printed"),
    ]
    assert said("12") == [("number", "", "", "the binding of 15", "a number sent is not printed")]


# ---------------------------------------------------------------- shown, not counted


def test_a_copy_edit_is_shown_and_not_counted(tmp_path: Path) -> None:
    result = changes_of(tmp_path, ("follow from the design", "arise from the design"))
    assert corrections(result) == []
    (change,) = kinds(result, COPY_EDIT)
    assert (change.sent, change.printed) == ("follow", "arise")


def test_text_the_proof_adds_between_parts_is_shown_and_not_counted(tmp_path: Path) -> None:
    text = edited(paged(typeset_lines()), ("Funding\n", "Received 3 May 2026\nFunding\n"))
    result = changes_of(tmp_path, text=text)
    assert corrections(result) == []
    (change,) = kinds(result, ADDED)
    assert "Received 3 May 2026" in change.printed


def test_the_document_s_footnotes_are_not_compared_and_the_proof_s_are_added(
    tmp_path: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The document's footnotes are not compared."):
    the document is read as `docxtext.blocks` reads its body, so a note's text is no part,
    and the proof's note is shown as added text, a number changed in it counted as nothing."""
    import zipfile

    from manuscript_guard.proof.sent import read_sent

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ("<w:p><w:r><w:t>The dose was capped for every patient in the trial.</w:t></w:r>"
            "<w:r><w:footnoteReference w:id='1'/></w:r></w:p>"
            "<w:p><w:r><w:t>Hepatic injury was rare in the cohort as a whole.</w:t></w:r></w:p>")
    notes = (f"<w:footnotes xmlns:w='{w}'><w:footnote w:id='1'><w:p><w:r><w:t>Capped at 40 mg "
             "a day.</w:t></w:r></w:p></w:footnote></w:footnotes>")  # fmt: skip
    document = tmp_path / "m.docx"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml",
                         f"<w:document xmlns:w='{w}'><w:body>{body}</w:body></w:document>")
        archive.writestr("word/footnotes.xml", notes)
    sent = read_sent(document)
    assert [part.text for part in sent.parts] == [
        "The dose was capped for every patient in the trial.",
        "Hepatic injury was rare in the cohort as a whole."]
    proof = ("The dose was capped for every patient in the trial.\nHepatic injury was rare in "
             "the cohort as a whole.\n1 Capped at 50 mg a day.")  # fmt: skip
    result = changes_of(tmp_path, sent=sent, text=proof)
    assert [(c.kind, c.printed) for c in result.changes] == [(ADDED, "1 Capped at 50 mg a day.")]


def test_a_paragraph_set_elsewhere_is_moved_and_still_compared(tmp_path: Path) -> None:
    lines = typeset_lines()
    funding = [k for k, line in enumerate(lines) if line in ("Funding", PARTS[16].text)]
    moved = [line for k, line in enumerate(lines) if k not in funding]
    moved[1:1] = [lines[k] for k in funding]
    text = edited(paged(moved), ("no funding from", "no funding at all from"))
    result = changes_of(tmp_path, text=text)
    assert [c.what for c in kinds(result, MOVED)] == ["place"]
    assert corrections(result) == []
    assert [c.printed for c in kinds(result, COPY_EDIT)] == ["at all"]


def _spelt(n: int) -> str:
    """A word of its own for every `n`, of letters only."""
    return "w" + "".join(chr(97 + (n // 26**k) % 26) for k in range(2))


@pytest.mark.parametrize(("every", "found"), [(3, False), (4, False), (5, True)])
def test_a_paragraph_set_elsewhere_is_found_by_runs_of_four_keys(
    tmp_path: Path, every: int, found: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The alignment chooses between readings within
    limits."): a short paragraph the proof sets elsewhere with a word changed every four
    tokens or fewer shares no run of four keys there, and reads as missing, its text as
    added; one changed every fifth token is found moved."""
    parts = (Part(PARAGRAPH, "Alpha " + " ".join(map(_spelt, range(30))) + ".", "first"),
             Part(PARAGRAPH, "Bravo " + " ".join(map(_spelt, range(100, 116))) + ".", "short"),
             Part(PARAGRAPH, "Charlie " + " ".join(map(_spelt, range(200, 230))) + ".", "third"))
    words = parts[1].text.rstrip(".").split()
    moved = " ".join(f"x{w}" if k % every == every - 1 else w for k, w in enumerate(words))
    text = "\n".join([parts[0].text, parts[2].text, moved + "."])
    result = changes_of(tmp_path, sent=Sent(Path("m.docx"), parts, (), None), text=text)
    if found:
        assert [c.what for c in kinds(result, MOVED)] == ["place"]
        assert corrections(result) == [] and kinds(result, ADDED) == []
    else:
        assert [(c.kind, c.what, c.part) for c in result.changes] == [
            (CORRECTION, "missing", "short"), (ADDED, "text", "")]
        assert result.changes[1].printed == moved + "."


@pytest.mark.parametrize(("words", "missing"), [(392, True), (393, False)])
def test_a_paragraph_left_out_beside_one_ending_alike_is_left_out_whole_within_400_tokens(
    tmp_path: Path, words: int, missing: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The alignment chooses between readings within
    limits."): a paragraph left out next to one copy-edited, both ending in the same words,
    is left out whole where the stretch is 400 tokens or fewer; past that it reads as part
    of a copy-edit of the first."""
    tail = "and the same words close it."
    first = f"Alpha one two three remained {tail}"
    second = " ".join(map(_spelt, range(words))) + f" {tail}"
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, first, "first"),
                                 Part(PARAGRAPH, second, "second")), (), None)  # fmt: skip
    result = changes_of(tmp_path, sent=sent, text=first.replace("remained", "stayed"))
    said = [(c.kind, c.what, c.part) for c in result.changes]
    assert said == [(COPY_EDIT, "words", "first")] + (
        [(CORRECTION, "missing", "second")] if missing else [])


def test_a_table_set_on_another_page_is_compared_where_it_is(tmp_path: Path) -> None:
    lines = typeset_lines()
    rows = [k for k, line in enumerate(lines) if "   " in line]
    table = [lines[k] for k in rows]
    rest = [line for k, line in enumerate(lines) if k not in rows]
    text = paged(rest[:-2] + table + rest[-2:])
    text = edited(text, ("160 (37.6)", "106 (37.6)"))
    result = changes_of(tmp_path, text=text)
    (change,) = corrections(result)
    assert (change.part, change.was, change.now) == (PARTS[10].label, "160", "106")
    assert kinds(result, MOVED) == []


def test_line_numbers_in_the_margin_name_the_line(tmp_path: Path) -> None:
    set_lines = wrapped(edited(unwrapped(), ("ratio was 3.84", "ratio was 3.48")))
    lines = [f"{number} {line}" for number, line in enumerate(set_lines, start=1)]
    proof = tmp_path / "proof.txt"
    proof.write_text(paged(lines), encoding="utf-8")
    (reading,) = readings(proof)
    assert reading.numbered
    (change,) = corrections(compare(SENT, reading))
    assert change.line == next(n for n, line in enumerate(set_lines, 1) if "3.48" in line)


@pytest.mark.parametrize(("step", "first", "where", "read"), [
    (1, 1, "start", True), (5, 1, "start", True), (10, 1, "start", True),
    (2, 1, "start", False), (1, 50, "start", False), (1, 1, "end", False),
])  # fmt: skip
def test_line_numbers_are_read_at_a_line_s_start_from_one_by_one_five_or_ten(
    tmp_path: Path, step: int, first: int, where: str, read: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "What a page repeats is found by rule."): a proof's
    line numbers are read only at the start of a line, counting from one, by one, five or
    ten: by two, from 50, or after the line, they are not."""
    lines = wrapped(unwrapped(PARTS * 2), 44)
    numbered = [(f"{n} {line}" if where == "start" else f"{line} {n}") if n % step == 0
                else line for n, line in enumerate(lines, first)]  # fmt: skip
    proof = tmp_path / "proof.txt"
    proof.write_text("\n".join(numbered), encoding="utf-8")
    (reading,) = readings(proof)
    assert reading.numbered is read


@pytest.mark.parametrize("count", [4, 5])
def test_line_numbers_are_read_on_five_lines_at_least(tmp_path: Path, count: int) -> None:
    """A known gap (DESIGN.md, Known gaps, "What a page repeats is found by rule."): four
    lines numbered from one are no line numbers, five are."""
    words = ("Alpha", "Bravo", "Charlie", "Delta", "Echo")
    proof = tmp_path / "proof.txt"
    proof.write_text("\n".join(f"{n} {word} reads a line of its own here."
                               for n, word in enumerate(words[:count], 1)), encoding="utf-8")
    (reading,) = readings(proof)
    assert reading.numbered is (count == 5)


def test_a_correction_where_no_line_number_is_read_is_named_by_its_page(tmp_path: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "What a page repeats is found by rule."): line
    numbers a reader gives as a column of their own are dropped, and a correction is named
    by its page and a quotation, as on a proof with no line numbers."""
    set_lines = wrapped(edited(unwrapped(), ("ratio was 3.84", "ratio was 3.48")))
    for text in ("\n".join([*map(str, range(1, 31)), *set_lines]), paged(set_lines)):
        (change,) = corrections(changes_of(tmp_path, text=text))
        assert (change.page, change.line) == (1, None)
        assert change.printed == "\N{HORIZONTAL ELLIPSIS}reporting odds ratio was 3.48 (95% CI" \
            "\N{HORIZONTAL ELLIPSIS}"
    assert "line numbers 1-30" in changes_of(tmp_path, text="\n".join(
        [*map(str, range(1, 31)), *set_lines])).reading.furniture  # fmt: skip


def test_a_column_of_line_numbers_is_taken_out(tmp_path: Path) -> None:
    lines = typeset_lines()
    text = "\n".join([*map(str, range(1, 31)), *lines])
    result = changes_of(tmp_path, text=text)
    assert result.changes == ()


def test_years_in_a_table_are_not_line_numbers(tmp_path: Path) -> None:
    sent = Sent(Path("m.docx"), tuple(Part(CELL, str(year), f"cell {year}", table=1)
                                      for year in range(2015, 2023)), (), None)  # fmt: skip
    text = "\n".join(str(year) for year in range(2015, 2023))
    assert changes_of(tmp_path, sent=sent, text=text).changes == ()


def _passages(count: int, words: int) -> tuple[Sent, list[str]]:
    """`count` paragraphs of `words` words each, as text reads: words of letters drawn from a
    vocabulary of 1728, a number every seventh word; and their lines as a proof sets them.
    Words with digits in them, "w123x7", stood for "w # x #" in the alignment, the same keys
    from end to end, which no text is (round 1 of #397, on CI)."""
    import random

    syllables = ("ka", "lo", "mi", "ne", "ru", "sa", "ti", "vo", "pe", "du", "ga", "ho")
    vocabulary = ["".join(s) for s in itertools.product(syllables, repeat=3)]
    drawn = random.Random(7)
    parts = tuple(
        Part(PARAGRAPH, " ".join(drawn.choice(vocabulary) if n % 7 else
                                 f"{drawn.randrange(1, 100)}.{drawn.randrange(10)}"
                                 for n in range(words)) + ".", f"paragraph {k}")
        for k in range(count)
    )  # fmt: skip
    return Sent(Path("m.docx"), parts, (), None), typeset_lines(parts, width=60)


def test_a_passage_the_paper_repeats_is_lined_up_with_its_repetition(tmp_path: Path) -> None:
    # No run of words stands once on each side, and the whole is too long for difflib: the
    # runs that stand as often on each side anchor it.
    def spelt(n: int) -> str:
        return "w" + "".join(chr(97 + (n // 26**k) % 26) for k in range(2))

    passage = " ".join(map(spelt, range(450))) + "."
    sent = Sent(Path("m.docx"), tuple(Part(PARAGRAPH, passage, label)
                                      for label in ("once", "again", "more")), (), None)
    lines = typeset_lines(sent.parts, width=60)
    where = [k for k, line in enumerate(lines) if f" {spelt(200)} " in line]
    lines[where[1]] = lines[where[1]].replace(f" {spelt(200)} ", " changed ")
    # A line before and after, so that what is alike at either end does not line it all up.
    lines = ["Received 3 May 2026", *lines, "Accepted 9 June 2026"]
    result = changes_of(tmp_path, sent=sent, text="\n".join(lines))
    assert result.found == result.total - 1
    (change,) = kinds(result, COPY_EDIT)
    assert (change.part, change.sent, change.printed) == ("again", spelt(200), "changed")
    assert corrections(result) == []


def test_lining_up_a_proof_takes_time_in_proportion_to_its_length(assert_linear) -> None:
    from manuscript_guard.proof.reading import Line, Reading

    def build(count: int):
        sent, lines = _passages(count, 30)
        # A word copy-edited on every ninth line.
        lines = [f"changed {line.split(' ', 1)[1]}" if k % 9 == 0 and " " in line else line
                 for k, line in enumerate(lines)]  # fmt: skip
        return sent, Reading("text", tuple(Line(line, 1 + k // 50) for k, line in
                                           enumerate(lines)), 1)  # fmt: skip

    assert_linear(build, lambda given: compare(*given), 4, "the proof's comparison")


def test_a_proof_unlike_what_was_sent_is_compared_in_time_near_its_length() -> None:
    """Where nothing anchors, a text of the same keys from end to end, the comparison
    gives up on the stretch rather than trying every run against every other: it took
    minutes at 128 paragraphs (round 1 of #397, on CI)."""
    import time

    from manuscript_guard.proof.reading import Line, Reading

    parts = tuple(Part(PARAGRAPH, " ".join(f"w{n}x{k}" for n in range(30)) + ".", f"p{k}")
                  for k in range(128))  # fmt: skip
    lines = [line.replace("x1", "y1", 1) if k % 9 == 0 else line
             for k, line in enumerate(typeset_lines(parts, width=60))]  # fmt: skip
    reading = Reading("text", tuple(Line(line, 1 + k // 50) for k, line in enumerate(lines)), 1)
    started = time.perf_counter()
    compare(Sent(Path("m.docx"), parts, (), None), reading)
    assert time.perf_counter() - started < 20


def test_a_table_broken_across_a_page_needs_no_correction(tmp_path: Path) -> None:
    # Review of #397, round 2: counting a number put between two cells as a correction made
    # "Table 1 (continued)" one, on a proof that prints what was sent. What a proof adds
    # between two parts is shown and not counted (DESIGN.md, Known gaps).
    row = "Female   226 (53.1)   1737 (48.6)"
    result = changes_of(tmp_path, (row, f"Table 1 (continued)\n{row}"))
    assert corrections(result) == []
    (added,) = kinds(result, ADDED)
    assert added.printed == "Table 1 (continued)"


def test_a_row_the_proof_repeats_is_shown_as_added(tmp_path: Path) -> None:
    # DESIGN.md, Known gaps: shown, and not counted.
    result = changes_of(tmp_path, ("Female   226 (53.1)   1737 (48.6)",
                                   "Female   226 (53.1)   1737 (48.6)\n"
                                   "Female   226 (53.1)   1737 (48.6)"))  # fmt: skip
    assert corrections(result) == []
    assert [c.printed for c in kinds(result, ADDED)] == ["Female 226 (53.1) 1737 (48.6)"]


def test_a_paragraph_the_proof_prints_other_text_in_place_of_is_missing(tmp_path: Path) -> None:
    # Review of #397, round 1: left out where the proof prints a running head it does not
    # repeat, a paragraph was a copy-edit of that head.
    result = changes_of(tmp_path, (PARTS[16].text, "Journal of Imaginary Pharmacology 2026"))
    (change,) = corrections(result)
    assert (change.what, change.part) == ("missing", PARTS[16].label)


def test_a_heading_the_journal_renames_is_a_copy_edit(tmp_path: Path) -> None:
    result = changes_of(tmp_path, ("Funding\n", "Financial support\n"))
    assert corrections(result) == []
    assert [(c.sent, c.printed) for c in kinds(result, COPY_EDIT)] == [
        ("Funding", "Financial support")]


@pytest.mark.parametrize("edit", [("over 12 weeks", "over 12 wk"),
                                  ("over 12 weeks", "over 12 week")])
def test_a_unit_of_time_abbreviated_is_a_copy_edit(tmp_path: Path, edit) -> None:
    # Review of #397, round 2: spelt-out units of time taken for units made the AMA's "wk"
    # a correction.
    result = changes_of(tmp_path, edit)
    assert corrections(result) == []
    assert kinds(result, COPY_EDIT)


@pytest.mark.parametrize("printed", ["months", "days", "fortnights", "decades"])
def test_a_unit_of_time_spelt_out_as_another_is_a_correction(tmp_path: Path, printed) -> None:
    (change,) = corrections(changes_of(tmp_path, ("over 12 weeks", f"over 12 {printed}")))
    assert change.what == "unit or symbol"
    assert "12 weeks" in change.sent and f"12 {printed}" in change.printed


@pytest.mark.parametrize("kind, what", [(PARAGRAPH, "unit or symbol"), (REFERENCE, "reference")])
@pytest.mark.parametrize("sent_as", ["12-week", "12 weeks"])
def test_a_unit_of_time_joined_to_its_number_is_beside_it(
    tmp_path: Path, kind, what, sent_as
) -> None:
    # Review of #408: read as a unit first, it was named "unit or symbol" in a reference;
    # and past the hyphen "12-week" was not beside its number.
    sent = Sent(Path("m.docx"), (Part(kind, f"1. Smith A. A {sent_as} trial of example-drug. "
                                      "J Imag Pharm. 2019;12:101-9.", "p"),), (), None)
    printed = sent_as.replace("week", "month")
    (change,) = corrections(changes_of(tmp_path, (sent_as, printed), sent=sent))
    assert change.what == what


@pytest.mark.parametrize("edit", [("consecutive weeks", "consecutive months"),
                                  ("day-28", "month-28")])
def test_a_unit_of_time_a_word_away_from_its_number_is_a_copy_edit(tmp_path: Path, edit) -> None:
    # A limit (DESIGN.md, Known gaps): the unit is read only beside a number, or after one
    # and a hyphen, and not before a hyphen and its number (review of #408, round 2).
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, "Patients were followed for 12 consecutive "
                                      "weeks, and mortality at day-28 was low.", "p"),), (), None)
    result = changes_of(tmp_path, edit, sent=sent)
    assert corrections(result) == []
    assert kinds(result, COPY_EDIT)


@pytest.mark.parametrize(("sent_as", "printed", "kind"), [
    # Case aside: a heading in capitals, a name's case in the body.
    ("The Results of the cohort were clear.", "The RESULTS of the cohort were clear.", None),
    ("As Smith found in the cohort.", "As smith found in the cohort.", None),
    # A litre's and a microgram's two spellings are one; "hours" and "h" are not.
    ("The dose was 5 mL in the bath.", "The dose was 5 ml in the bath.", None),
    ("The dose was 5 mcg in the bath.", "The dose was 5 \N{MICRO SIGN}g in the bath.", None),
    ("Patients were seen after 12 hours of rest.", "Patients were seen after 12 h of rest.",
     CORRECTION),
    # An abbreviation G14 does not know is a word, though it names another unit.
    ("They were followed for 12 weeks in all.", "They were followed for 12 mo in all.",
     COPY_EDIT),
    ("They were followed for 12 weeks in all.", "They were followed for 12 d in all.",
     COPY_EDIT),
    # A unit is read only beside its number.
    ("They were followed for two weeks in all.", "They were followed for two months in all.",
     COPY_EDIT),
    # A stretch after a number and a hyphen holds a unit anywhere in it.
    ("They took a 12-fold larger dose daily.", "They took a 12-point mg dose daily.",
     CORRECTION),
    ("They took a 12-fold larger dose daily.", "They took a 12-point big dose daily.",
     COPY_EDIT),
])  # fmt: skip
def test_a_case_change_or_a_style_s_synonym_is_seen_only_as_the_units_g14_knows(
    tmp_path: Path, sent_as: str, printed: str, kind: str | None
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A case change and a style's synonym are not
    seen."): words are compared case aside, a litre's and a microgram's two spellings are
    one, an abbreviation G14 does not know is a word, and a unit is read only beside its
    number, or anywhere in a stretch after a number and a hyphen."""
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, sent_as, "p"),), (), None)
    result = changes_of(tmp_path, sent=sent, text=printed)
    said = [(c.kind, c.what) for c in result.changes]
    assert said == ({None: [], CORRECTION: [(CORRECTION, "unit or symbol")],
                     COPY_EDIT: [(COPY_EDIT, "words")]}[kind])  # fmt: skip


def test_a_dash_at_a_line_end_joins_no_word(tmp_path: Path) -> None:
    # Review of #397, round 1: an em dash the proof sets at a line's end, folded to a hyphen,
    # joined "mg" and "twice", and "mgtwice" for "mg" was a unit changed.
    text = "The dose was 5 mg, twice daily, for a week of treatment."
    sent = Sent(Path("m.docx"), (Part(PARAGRAPH, text, "p"),), (), None)
    proof = "The dose was 5 mg\N{EM DASH}\ntwice daily\N{EM DASH}for a week of treatment."
    result = changes_of(tmp_path, sent=sent, text=proof)
    assert corrections(result) == []
    assert {c.kind for c in result.changes} == {COPY_EDIT}


# ---------------------------------------------------------------- reading a proof


def test_a_pdf_is_read_by_pypdf_where_pdftotext_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pypdf")
    monkeypatch.setattr(proof_reading.shutil, "which", lambda _name: None)
    proof = tmp_path / "proof.pdf"
    lines = wrapped(edited(unwrapped(), ("ratio was 3.84", "ratio was 3.48")))
    proof.write_bytes(typeset(lines, per_column=12, head="Example et al. J Imag Pharm 2026",
                              first_page=101))  # fmt: skip
    (reading,) = readings(proof)
    assert reading.reader.startswith("pypdf")
    (change,) = corrections(compare(SENT, reading))
    assert (change.was, change.now, change.page) == ("3.84", "3.48", 1)


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is not installed")
def test_a_pdf_is_read_by_pdftotext_in_both_orders(tmp_path: Path) -> None:
    proof = tmp_path / "proof.pdf"
    lines = wrapped(edited(unwrapped(), (f"{MINUS}0.51", "0.51")))
    proof.write_bytes(typeset(lines, per_column=12, head="Example et al. J Imag Pharm 2026",
                              first_page=101, line_numbers=True))  # fmt: skip
    found = readings(proof)
    assert [reading.reader.rsplit(", ", 1)[1] for reading in found] == ["layout order",
                                                                         "drawing order"]
    from manuscript_guard.proof.compare import best

    result = best(SENT, found)
    (change,) = corrections(result)
    assert change.what == "sign"


def test_a_pdf_with_no_text_is_refused(tmp_path: Path) -> None:
    proof = tmp_path / "scan.pdf"
    proof.write_bytes(typeset([]))
    with pytest.raises(UnreadableProof, match="no text"):
        readings(proof)


def test_a_proof_of_another_kind_is_refused(tmp_path: Path) -> None:
    proof = tmp_path / "proof.docx"
    proof.write_bytes(b"PK")
    with pytest.raises(UnreadableProof, match="a proof is read from"):
        readings(proof)


def test_pdftotext_is_given_a_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []

    def run(command, **options):
        seen.append(options)
        raise proof_reading.subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(proof_reading.shutil, "which", lambda name: name)
    monkeypatch.setattr(proof_reading.subprocess, "run", run)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    proof = tmp_path / "proof.pdf"
    proof.write_bytes(typeset(["text"]))
    with pytest.raises(UnreadableProof):
        readings(proof)
    assert seen and all(options.get("timeout") for options in seen)


def test_a_jats_proof_is_read_as_text(tmp_path: Path) -> None:
    proof = tmp_path / "proof.xml"
    proof.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE article [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        "<article><front><contrib><name><surname>Example</surname><given-names>Ada"
        "</given-names></name></contrib></front><body><sec><title>Results</title><p>The "
        "ratio was 3.84 &#x2014; and &amp;x;</p></sec></body></article>",
        encoding="utf-8",
    )
    (reading,) = readings(proof)
    texts = [line.text for line in reading.lines]
    assert "Ada Example" in texts
    assert "Results" in texts
    assert "The ratio was 3.84 \N{EM DASH} and &x;" in texts
    assert not any("passwd" in text for text in texts)


def test_a_jats_reference_keeps_its_names_as_printed(tmp_path: Path) -> None:
    # Review of #397, round 1: the given-names-first rewrite ran over the reference list, and
    # each Vancouver reference "Smith A" read "A Smith", a correction of every reference.
    proof = tmp_path / "proof.xml"
    proof.write_text(
        "<article><front><contrib><name><surname>Example</surname><given-names>Ada"
        "</given-names></name></contrib></front><back><ref-list><ref><mixed-citation>"
        "<string-name><surname>Smith</surname> <given-names>A</given-names></string-name>, "
        "<string-name><surname>Jones</surname> <given-names>B</given-names></string-name>. "
        "Hepatic injury in a national cohort.</mixed-citation></ref></ref-list></back>"
        "</article>",
        encoding="utf-8",
    )
    (reading,) = readings(proof)
    texts = [line.text for line in reading.lines]
    assert "Ada Example" in texts
    assert "Smith A, Jones B. Hepatic injury in a national cohort." in texts


def test_an_html_proof_is_read_as_text(tmp_path: Path) -> None:
    proof = tmp_path / "proof.html"
    proof.write_text("<html><head><style>p{}</style><script>var a=1;</script></head><body>"
                     "<h1>Results</h1><p>The ratio was <b>3.84</b>.</p></body></html>",
                     encoding="utf-8")  # fmt: skip
    (reading,) = readings(proof)
    assert [line.text for line in reading.lines] == ["Results", "The ratio was 3.84."]


# ---------------------------------------------------------------- the title page


def _front(root: Path, tmp_path: Path, text: str):
    from manuscript_guard.contracts.project import load_project
    from manuscript_guard.proof.front import check_front

    proof = tmp_path / "front.txt"
    proof.write_text(text, encoding="utf-8")
    (reading,) = readings(proof)
    return check_front(load_project(root)[0], reading)[0]


FRONT = (
    "Reporting of hepatic injury with example-drug\n"
    "Ada Example1,*, Blaise Sample2\n"
    "1 Department of Clinical Pharmacology, Example University Graduate School of\n"
    "Medicine, Springfield, Japan\n"
    "2 Regional Pharmacovigilance Centre, Department of Pharmacology, Hopital\n"
    "Universitaire d Exemple, Villeneuve, France\n"
    "*Correspondence: ada.example@invalid.example\n"
)


def test_a_title_page_as_authors_yaml_has_it_needs_nothing(
    built_example: Path, tmp_path: Path
) -> None:
    assert _front(built_example, tmp_path, FRONT) == []


@pytest.mark.parametrize(("edit", "what", "note"), [
    (("2 Regional Pharmacovigilance Centre, Department of Pharmacology, Hopital\n"
      "Universitaire d Exemple, Villeneuve, France\n", ""), "affiliation", "not in the proof"),
    (("Universitaire d Exemple", "Universitaire Exemple"), "affiliation",
     "the affiliation is printed otherwise"),
    (("Blaise Sample2", "Blaise Simple2"), "author's name", "the name is printed otherwise"),
    (("Ada Example1,*, Blaise Sample2", "Blaise Sample2, Ada Example1,*"), "authors' order",
     ""),
    (("ada.example@invalid", "ada.exemple@invalid"), "e-mail address", "printed otherwise"),
])  # fmt: skip
def test_a_title_page_changed_is_a_correction(built_example: Path, tmp_path: Path, edit, what, note
                                              ) -> None:  # fmt: skip
    (change,) = _front(built_example, tmp_path, edited(FRONT, edit))
    assert (change.kind, change.what, change.note) == (CORRECTION, what, note)


@pytest.mark.parametrize("marks", ["1,2", "1-3", "1,2,*", "1\N{DAGGER}"])
def test_a_name_with_its_affiliation_marks_set_against_it_is_found(
    built_example: Path, tmp_path: Path, marks: str
) -> None:
    # Review of #397, round 1: "Example1,2" was not "Example".
    assert _front(built_example, tmp_path, edited(FRONT, ("Ada Example1,*", f"Ada Example{marks}"))
                  ) == []  # fmt: skip


def test_a_name_with_letters_for_its_affiliation_marks_is_printed_otherwise(
    built_example: Path, tmp_path: Path
) -> None:
    """A known gap (DESIGN.md, Known gaps, "Affiliation marks are read as digits and
    signs."): "Examplea,b" is not the name, and is reported as printed otherwise, where
    "Example1,2" is."""
    (change,) = _front(built_example, tmp_path, edited(FRONT, ("Ada Example1,*", "Ada Examplea,b")))
    assert (change.kind, change.what, change.sent, change.printed, change.note) == (
        CORRECTION, "author's name", "Ada Example", "Ada Examplea,b",
        "the name is printed otherwise")  # fmt: skip
    assert _front(built_example, tmp_path, edited(FRONT, ("Ada Example1,*", "Ada Example1,2"))
                  ) == []  # fmt: skip


def test_the_title_page_is_held_by_its_words_and_not_its_layout(
    built_example: Path, tmp_path: Path
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The title page is held to `authors.yaml` by its
    words, not its layout."): which mark ties an author to an affiliation, and which marks
    the corresponding one, are not read; a name in capitals is found; an ORCID iD the proof
    does not print as text is not compared, one it prints is."""
    names = "Ada Example1,*, Blaise Sample2"
    for front in (edited(FRONT, (names, "Ada Example2, Blaise Sample1,*")),
                  edited(FRONT, (names, "ADA EXAMPLE1,*, BLAISE SAMPLE2")), FRONT):  # fmt: skip
        assert _front(built_example, tmp_path, front) == []
    wrong = FRONT + "ORCID: 0000-0002-1825-0097; 0000-0001-5109-3701\n"
    assert [c.what for c in _front(built_example, tmp_path, wrong)] == ["ORCID iD", "ORCID iD"]


@pytest.mark.parametrize("edit", [
    ("Centre, Department of Pharmacology, Hopital", "Centre, Hopital"),
    ("Springfield, Japan", "Japan, Springfield"),
])  # fmt: skip
def test_an_affiliation_the_journal_rewords_is_printed_otherwise(
    built_example: Path, tmp_path: Path, edit: tuple[str, str]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The title page is held to `authors.yaml` by its
    words, not its layout."): a department dropped or a country moved is reported as the
    affiliation printed otherwise."""
    (change,) = _front(built_example, tmp_path, edited(FRONT, edit))
    assert (change.kind, change.what, change.note) == (
        CORRECTION, "affiliation", "the affiliation is printed otherwise")


@pytest.mark.parametrize(("printed", "said"), [
    ("Blaise van der Sample2", []),
    ("Blaise Sample2", [("author's name", "not in the proof")]),
])  # fmt: skip
def test_a_particle_set_otherwise_is_found_and_one_dropped_is_reported(
    project: Path, tmp_path: Path, printed: str, said: list[tuple[str, str]]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The title page is held to `authors.yaml` by its
    words, not its layout."): "van der" for "Van der" is found, case aside; dropped, the
    name is reported."""
    _authors_edited(project, ("family: Sample", "family: Van der Sample"))
    text = edited(FRONT, ("Blaise Sample2", printed))
    assert [(c.what, c.note) for c in _front(project, tmp_path, text)] == said


@pytest.mark.parametrize(("printed", "said"), [
    ("jean-\npierre.example@uni.example",
     [("printed otherwise", "jean-pierre.example@uni.example")]),
    ("jeanpierre.example@uni.example", []),
])  # fmt: skip
def test_an_address_with_no_hyphen_broken_at_a_line_s_end_is_read_with_one(
    project: Path, tmp_path: Path, printed: str, said: list[tuple[str, str]]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The title page is held to `authors.yaml` by its
    words, not its layout."): an address the typesetter breaks with a hyphen it never had,
    beside the "@", is read with that hyphen and reported printed otherwise."""
    _authors_edited(project, ("ada.example@invalid.example", "jeanpierre.example@uni.example"))
    found = _front(project, tmp_path, edited(FRONT, ("ada.example@invalid.example", printed)))
    assert [(c.note, c.printed) for c in found if c.what == "e-mail address"] == said
    assert [c.what for c in found] == ["e-mail address"] * len(said)


def _authors_edited(project: Path, *edits: tuple[str, str]) -> None:
    path = project / "authors.yaml"
    path.write_text(edited(path.read_text(encoding="utf-8"), *edits), encoding="utf-8")


def test_an_orcid_ending_in_x_is_found(project: Path, tmp_path: Path) -> None:
    # Review of #397, round 1: the words were casefolded before the pattern read them.
    _authors_edited(project, ("0000-0001-5109-3700", "0000-0002-1694-233X"))
    text = FRONT + "ORCID: 0000-0002-1825-0097; 0000-0002-1694-233X\n"
    assert _front(project, tmp_path, text) == []


@pytest.mark.parametrize(("address", "broken"), [
    ("ada.example@s.mail.nagoya-u.ac.jp", "ada.example@s.mail.nagoya-\nu.ac.jp"),
    ("jean-pierre.example@uni.example", "jean-\npierre.example@uni.example"),
])  # fmt: skip
def test_an_address_broken_at_its_hyphen_is_found(
    project: Path, tmp_path: Path, address: str, broken: str
) -> None:
    # Review of #397: the hyphen of "nagoya-u" (round 1) and of "jean-pierre" (round 2) was
    # taken for a line end's.
    _authors_edited(project, ("ada.example@invalid.example", address))
    assert _front(project, tmp_path, edited(FRONT, ("ada.example@invalid.example", broken))) == []


def test_a_name_printed_with_initials_is_typography(built_example: Path, tmp_path: Path) -> None:
    (change,) = _front(built_example, tmp_path, edited(FRONT, ("Blaise Sample2", "B. Sample2")))
    assert (change.kind, change.what) == (TYPOGRAPHY, "author's name")


def test_an_orcid_printed_wrong_is_a_correction(built_example: Path, tmp_path: Path) -> None:
    right = FRONT + "ORCID: 0000-0002-1825-0097; 0000-0001-5109-3700\n"
    assert _front(built_example, tmp_path, right) == []
    wrong = edited(right, ("0000-0001-5109-3700", "0000-0001-5109-3701"))
    found = _front(built_example, tmp_path, wrong)
    assert [(c.what, c.note) for c in found] == [
        ("ORCID iD", "not in the proof"), ("ORCID iD", "the proof prints an ORCID iD no author has")
    ]


# ---------------------------------------------------------------- the command


def _pack(project: Path) -> Path:
    """The example's submission pack, built offline, its checks skipped: what the journal
    would have been sent."""
    assert main(["submit", str(project), "--offline", "--skip-checks"]) in (0, 1)
    return project / "build" / "submission" / "manuscript.docx"


@pytest.fixture(scope="module")
def packed(tmp_path_factory: pytest.TempPathFactory, built_example: Path) -> Path:
    if not PANDOC:
        pytest.skip("pandoc is not installed")
    root = tmp_path_factory.mktemp("proof") / "paper"
    shutil.copytree(built_example, root)
    _pack(root)
    return root


def _proof_lines(root: Path, *edits: tuple[str, str]) -> list[str]:
    """The example's pack set as a journal sets it, `edits` made first: the title, the title
    page, then every part."""
    from manuscript_guard.proof.sent import read_sent

    sent = read_sent(root / "build" / "submission" / "manuscript.docx")
    title, rest = sent.parts[0], sent.parts[1:]
    text = "\n".join([title.text, *FRONT.split("\n")[1:-1], unwrapped(rest)])
    return wrapped(edited(text, *edits))


def _typeset(root: Path, *edits: tuple[str, str]) -> Path:
    proof = root / "proof.pdf"
    proof.write_bytes(typeset(_proof_lines(root, *edits), per_column=56,
                              head="Example et al. J Imag Pharmacoepidemiol 2026",
                              first_page=101))  # fmt: skip
    return proof


def _pdf_readable() -> bool:
    if shutil.which("pdftotext"):
        return True
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


needs_a_pdf_reader = pytest.mark.skipif(not _pdf_readable(), reason="no PDF reader")


@needs_pandoc
@needs_a_pdf_reader
def test_the_proof_of_the_example_as_sent_needs_no_correction(
    packed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proof = _typeset(packed)
    assert main(["proof", str(proof), str(packed)]) == 0
    out = capsys.readouterr().out
    assert "Corrections to ask for (0)" in out
    assert "It is the file the pack's MANIFEST.yaml lists, for the first submission" in out
    assert "Nothing has been sent" in out


@needs_pandoc
@needs_a_pdf_reader
def test_the_proof_of_the_example_with_its_planted_faults(
    packed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proof = _typeset(
        packed,
        ("a reporting odds ratio of 3.84 (95% CI", "a reporting odds ratio of 3.48 (95% CI"),
        ("serious (36.4%)", "serious (36,4%)"),
        ("77 (18.1)   194 (5.4)", "194 (5.4)   77 (18.1)"),
        ("2 Regional Pharmacovigilance Centre, Department of Pharmacology, Hopital\n"
         "Universitaire d Exemple, Villeneuve, France\n", ""),
        ("Cohort, 2010", "Cohort, 2011"),
        ("Blaise Sample2", "Blaise Simple2"),
    )
    out = tmp_path / "reply.md"
    assert main(["proof", str(proof), str(packed), "--out", str(out)]) == 1
    said = capsys.readouterr().out
    assert "from {{results.ror.point}} in manuscript/main.md, line" in said
    assert "from {{table.baseline}}" in said
    reply = out.read_text(encoding="utf-8")
    assert 'replace "3.48" with "3.84"' in reply
    assert 'replace "36,4" with "36.4"' in reply
    assert 'replace "194 (5.4)" with "77 (18.1)"' in reply
    assert said.count("swapped with Table 1") == 2
    assert 'restore "Regional Pharmacovigilance Centre' in reply
    assert 'replace "2011" with "2010" (reference, reference 1' in reply
    assert 'replace "Blaise Simple2" with "Blaise Sample"' in reply
    assert main(["proof", str(proof), str(packed), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["corrections"] == len([c for c in report["changes"]
                                         if c["kind"] == CORRECTION]) >= 6  # fmt: skip


@needs_pandoc
@needs_a_pdf_reader
def test_a_supplement_typeset_on_its_own_is_held_to_the_packs(
    packed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuscript_guard.proof.sent import read_sent

    sent = read_sent(packed / "build" / "submission" / "supplementary.docx")
    lines = wrapped(edited(unwrapped(sent.parts), ("interval of 2.89 to", "interval of 2.98 to")))
    proof = packed / "supplement-proof.pdf"
    proof.write_bytes(typeset(lines, per_column=56, head="Example et al. Supplementary material",
                              first_page=1))  # fmt: skip
    assert main(["proof", str(proof), str(packed), "--supplementary"]) == 1
    out = capsys.readouterr().out
    assert "Compared with: build/submission/supplementary.docx" in out
    assert "Corrections to ask for (1)" in out
    assert "1. p. 1: number, the paragraph \"The primary analysis reports" in out
    assert "interval of 2.98 to 5.12" in out
    # The title page is the paper's: a supplement's proof is not held to it.
    assert "author's name:" not in out and "affiliation:" not in out


@needs_pandoc
@needs_a_pdf_reader
def test_a_proof_of_the_paper_and_its_supplement_in_one_file_is_compared_once_with_each(
    packed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DESIGN.md, Known gaps: the supplement's text is added text to the paper's run, and its
    change is the supplement's run's to find."""
    from manuscript_guard.proof.sent import read_sent

    supplement = read_sent(packed / "build" / "submission" / "supplementary.docx")
    changed = edited(unwrapped(supplement.parts), ("interval of 2.89 to", "interval of 2.98 to"))
    lines = [*_proof_lines(packed), *wrapped(changed)]
    proof = packed / "both-proof.pdf"
    # One column: the supplement's rows of four cells, set a line each, run wider than a
    # column of two and into the next.
    proof.write_bytes(typeset(lines, columns=1, per_column=60,
                              head="Example et al. J Imag Pharmacoepidemiol 2026",
                              first_page=101))  # fmt: skip
    assert main(["proof", str(proof), str(packed)]) == 0
    paper = capsys.readouterr().out
    assert "Corrections to ask for (0)" in paper
    assert "Text the proof adds" in paper
    assert main(["proof", str(proof), str(packed), "--supplementary"]) == 1
    supplement_run = capsys.readouterr().out
    assert "Corrections to ask for (1)" in supplement_run
    assert "interval of 2.98 to 5.12" in supplement_run


def test_no_pack_is_no_comparison(built_example: Path, tmp_path: Path,
                                  capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    proof = tmp_path / "proof.txt"
    proof.write_text("Results\n", encoding="utf-8")
    assert main(["proof", str(proof), str(built_example)]) == 2
    assert "manuscript-guard submit" in capsys.readouterr().err


@needs_pandoc
def test_a_proof_of_another_paper_is_no_comparison(
    packed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proof = tmp_path / "other.txt"
    proof.write_text(paged(typeset_lines()), encoding="utf-8")
    assert main(["proof", str(proof), str(packed)]) == 2
    assert "is not this document's proof" in capsys.readouterr().err


@needs_pandoc
def test_a_document_named_with_against_is_said_to_be_outside_the_pack(
    packed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy = tmp_path / "final.docx"
    shutil.copy2(packed / "build" / "submission" / "manuscript.docx", copy)
    proof = tmp_path / "proof.txt"
    proof.write_text("\n".join(_proof_lines(packed)), encoding="utf-8")
    assert main(["proof", str(proof), str(packed), "--against", str(copy)]) == 0
    out = capsys.readouterr().out
    assert "it was named with --against" in out
    assert "no approval: Ada Example, Blaise Sample" in out
