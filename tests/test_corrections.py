"""How the edits of G14's readings are gathered into corrections (`corrections.py`)."""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.corrections import Edit, applied, corrections
from manuscript_guard.gates.vocabulary import Passage

TEXT = "# Results\n\nIt rose (CI 80 %-93 %) and P=0.03 in 5mg.\n"


def _passage(text: str = TEXT, printed: str | None = None) -> Passage:
    return Passage(Path("main.md"), text, text if printed is None else printed,
                   lambda at: text.count("\n", 0, at) + 1)  # fmt: skip


def _at(text: str, words: str) -> int:
    return TEXT.index(words)


def test_edits_whose_stretches_overlap_are_one_correction() -> None:
    """The space before each "%" and the join of the interval they stand in are edited in
    one correction, over the interval; an edit elsewhere is a correction of its own."""
    passage = _passage()
    interval = (_at(TEXT, "CI"), _at(TEXT, ")"))
    first, second = TEXT.index(" %"), TEXT.index(" %", TEXT.index(" %") + 1)
    join = TEXT.index("-")
    p = _at(TEXT, "P=")
    edits = [
        Edit("notation-percent", passage, first, first + 1, "", (first - 2, first + 2)),
        Edit("notation-percent", passage, second, second + 1, "", (second - 2, second + 2)),
        Edit("notation-interval", passage, join, join + 1, " to ", interval),
        Edit("notation-sign-spacing", passage, p + 1, p + 1, " ", (p, p + 6)),
        Edit("notation-sign-spacing", passage, p + 2, p + 2, " ", (p, p + 6)),
    ]
    found = corrections(edits)
    assert [(one.old, one.new, one.codes) for one in found] == [
        ("CI 80 %-93 %", "CI 80% to 93%", ("notation-interval", "notation-percent")),
        ("P=0.03", "P = 0.03", ("notation-sign-spacing",)),
    ]
    assert found[0].line == 3 and found[0].path == Path("main.md")
    assert applied(TEXT, found) == "# Results\n\nIt rose (CI 80% to 93%) and P = 0.03 in 5mg.\n"


def test_one_edit_two_readings_make_is_made_once() -> None:
    """The same change from the spelling's passage and the notation's, which hold the same
    text with other sections hidden, is one."""
    at = TEXT.index("mg")
    one = Edit("notation-unit", _passage(), at, at, " ", (at - 1, at + 2))
    again = Edit("notation-unit", _passage(printed="\0" * len(TEXT)), at, at, " ",
                 (at - 1, at + 2))  # fmt: skip
    found = corrections([one, again])
    assert [(c.old, c.new) for c in found] == [("5mg", "5 mg")]


def test_two_edits_that_say_different_things_of_the_same_words_are_refused() -> None:
    """Two readings that change the same characters differently, or insert different things
    at one place, are both refused, and the rest of the stretch is still edited."""
    passage = _passage()
    at = TEXT.index("mg")
    p = _at(TEXT, "P=")
    found = corrections([
        Edit("notation-unit", passage, at, at, " ", (at - 1, at + 2)),
        # a no-break space, which says something else than the space above
        Edit("notation-space-missing", passage, at, at, chr(0xA0), (at - 1, at + 2)),
        Edit("spelling-variant", passage, p, p + 1, "p", (p, p + 1)),
        Edit("notation-sign-spacing", passage, p, p + 1, "p ", (p, p + 6)),
        Edit("notation-sign-spacing", passage, p + 2, p + 2, " ", (p, p + 6)),
    ])  # fmt: skip
    assert [(c.old, c.new) for c in found] == [("P=0.03", "P= 0.03")]


def _notation_corrected(*sentences: str) -> list[tuple[str, str]]:
    from manuscript_guard.gates.notation import notation_edits

    text = "# Results\n\n" + "".join(f"It was {said} here.\n\n" for said in sentences)
    return [(one.old, one.new) for one in corrections(notation_edits([_passage(text)]))]


def test_hyphens_that_may_hold_a_high_bound_s_sign_are_not_edited() -> None:
    """"-1.2--0.3" is read as pandoc's en dash and a high bound of 0.3, and may be a hyphen
    and -0.3: in a paper that joins with "to" it is left, where an edit would have written
    "-1.2 to 0.3" (round 1 of #636)."""
    found = _notation_corrected("CI 1.2 to 3.4", "CI 0.8 to 1.1", "CI -1.2--0.3", "CI 2.0-3.0")
    assert found == [("CI 2.0-3.0", "CI 2.0 to 3.0")]
    # After a positive low bound a minus sign would make the high bound the lower: the
    # hyphens are pandoc's dash (round 2 of #636).
    found = _notation_corrected("CI 1.2 to 3.4", "CI 0.8 to 1.1", "CI 1.2--3.4")
    assert found == [("CI 1.2--3.4", "CI 1.2 to 3.4")]


def _respelt(text: str, english: str) -> list[tuple[str, str]]:
    from manuscript_guard.gates.spelling import spelling_edits

    return [(one.old, one.new) for one in corrections(spelling_edits([_passage(text)],
                                                                     english, ()))]  # fmt: skip


def test_a_word_quoted_in_single_marks_keeps_its_spelling_and_an_apostrophe_is_none() -> None:
    """A title quoted in single marks, straight or curly, is somebody else's, ended by a
    question mark, opened on a figure or holding a plural's apostrophe; an apostrophe inside
    a word or after a plural opens no quotation, and the words after it are respelt (rounds
    2 and 3 of #636)."""
    paragraphs = (
        "As 'Does tumor color matter?' asked, we looked.",
        "As '2020 tumor color survey' said.",
        "As 'The parents' tumor color choices' reported.",
        "As \N{LEFT SINGLE QUOTATION MARK}Tumor color\N{RIGHT SINGLE QUOTATION MARK} said.",
        # after a bracket and a mark of emphasis (round 4 of #636)
        "As reported ('tumor color in children'), we looked, and *'tumor color'* too.",
        "The patients' color and the study's tumor and the color we don't know.",
        "Colour and tumour and centre and fibre and labelled.",
    )
    text = "# Results\n\n" + "\n\n".join(paragraphs) + "\n"
    assert _respelt(text, "en-GB") == [("color", "colour"), ("tumor", "tumour"),
                                       ("color", "colour")]  # fmt: skip


def test_an_apostrophe_opening_a_word_quotes_up_to_a_mark_that_may_close() -> None:
    """"'Tis" may open a quotation: with a plural's apostrophe after it in its paragraph,
    the words between are held back; with none, they are respelt (round 3 of #636, a Known
    gap)."""
    assert _respelt("# Results\n\n'Tis said the color was the patients' choice.\n",
                    "en-GB") == []  # fmt: skip
    assert _respelt("# Results\n\n'Tis said the color was seen.\n", "en-GB") == [
        ("color", "colour")]


def test_a_space_put_after_a_respelt_word_is_no_edit_of_either() -> None:
    """"colour+5" in an American paper is a word to respell and a space to put after it,
    at the end of the respelling: neither is made (round 3 of #636, a Known gap)."""
    from manuscript_guard.gates.notation import notation_edits
    from manuscript_guard.gates.spelling import spelling_edits

    passage = _passage("# Results\n\nIt was colour+5 here, and color and center.\n")
    edits = notation_edits([passage]) + spelling_edits([passage], "en-US", ())
    assert [(one.code, one.new) for one in edits] == [("notation-space-missing", " "),
                                                      ("spelling-variant", "color")]  # fmt: skip
    assert corrections(edits) == []


def test_a_stray_double_mark_holds_back_the_respellings_after_it() -> None:
    """An inch mark is a straight double mark like any other: the words after it in its
    paragraph are taken to be quoted, and are not respelt, though the finding counts them;
    the words before it are (round 2 of #636, a Known gap)."""
    text = "# Results\n\nThe color seen; a 2\" incision; the color again.\n"
    assert _respelt(text, "en-GB") == [("color", "colour")]


def test_a_space_put_where_another_edit_changes_the_words_is_no_edit() -> None:
    """In a paper that joins with a hyphen, "CI 0.05 to+0.77" is a join to change and a
    space to put after the "to" the change takes away: neither is made, where together they
    wrote "CI 0.05- +0.77" (round 1 of #636)."""
    found = _notation_corrected("CI 1.2-3.4", "CI 0.8-1.1", "CI 0.05 to+0.77")
    assert found == []


def test_the_join_written_is_the_kept_form_set_evenly() -> None:
    """The kept form's first use typed with a space on one side of its hyphen, "1.2 -3.4",
    is not copied: the join written is the hyphen alone, which reads as no minus sign
    (round 1 of #636)."""
    found = _notation_corrected("CI 1.2 -3.4", "CI 2.0-3.0", "CI 0.8 to 1.1")
    assert found == [("CI 0.8 to 1.1", "CI 0.8-1.1")]


PROJECT_PAPER = (
    "# Methods\n\nThe reporting odds ratio (ROR) was computed. PRR (proportional reporting "
    "ratio) was not. The hazard ratio [HR] was given. The information component (IC; a "
    "measure) was read.\n\nThe odds ratio (OR) was used: OR was 2.\n\n# Results\n\nThe "
    "colour was seen; P=0.03 and P = 0.04 and P = 0.05.\n\n# Acknowledgements\n\nFunded by "
    "the National Institutes of Health (NIH).\n"
)


def test_a_project_s_edits_are_g14_s_three_readings_read_as_check_reads_them(
    tmp_path: Path,
) -> None:
    """`language_edits` reads the manuscript as `check_language` does, and gives the edits of
    the three readings: each abbreviation defined and not used again written out, in either
    order and with a sentence's capital, but not one whose bracket holds more, one used
    again or a funder's; a word of the other English respelt; and a sign spaced as most are.
    Edited, the manuscript gives no edit, and only the finding no edit was sure of stays."""
    from manuscript_guard.contracts.project import Project
    from manuscript_guard.gates.language import check_language, language_edits

    (tmp_path / "manuscript").mkdir()
    paper = tmp_path / "manuscript" / "main.md"
    paper.write_text(PROJECT_PAPER, encoding="utf-8", newline="\n")
    project = Project(root=tmp_path, paper={"english_variant": "en-US"}, authors=None)
    found = corrections(language_edits(project))
    assert [(one.codes, one.old, one.new) for one in found] == [
        (("abbreviation-unused",), "reporting odds ratio (ROR)", "reporting odds ratio"),
        (("abbreviation-unused",), "PRR (proportional reporting ratio)",
         "Proportional reporting ratio"),
        (("abbreviation-unused",), "hazard ratio [HR]", "hazard ratio"),
        (("spelling-variant",), "colour", "color"),
        (("notation-sign-spacing",), "P=0.03", "P = 0.03"),
    ]  # fmt: skip
    paper.write_text(applied(PROJECT_PAPER, found), encoding="utf-8", newline="\n")
    assert corrections(language_edits(project)) == []
    left = [(f.code, f.message.split(" ")[0]) for f in check_language(project).findings]
    assert left == [("abbreviation-unused", "IC")]
