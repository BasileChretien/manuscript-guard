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
