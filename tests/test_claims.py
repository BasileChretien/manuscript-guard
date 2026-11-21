"""How strongly a sentence claims: `reworded` warns where an edit moved it.

A polish that keeps every binding, citation and number can still make an association an
effect, drop a "may" or a "did not". Each sentence the edit changed is compared with what it
was, for the words of `data/claim_strength.yaml`: hedges, limits, negations and the ladder
from consistency to causation (adapted from the Claim-Strength Contract of
Yila-AI/awesome-research-skills).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.claims import (
    CODES,
    HEDGE,
    LIMIT,
    MOVED,
    NEGATED,
    NEGATION,
    STRONGER,
    WEAKER,
    changed,
    lists,
    moved,
    sentences,
)
from manuscript_guard.findings import WARN
from manuscript_guard.reworded import CLAIM_CODES, compare

PATH = Path("manuscript/main.md")


def told(before: str, after: str) -> list[tuple[str, str]]:
    return [(found.code, found.message.split(": ", 1)[1]) for found in moved(before, after)]


def words(text: str) -> list[tuple[str, str | int]]:
    return [word for sentence in sentences(text) for word in sentence.words]


# ----------------------------------------------------------------------------- the words


def test_every_word_of_the_lists_is_read_where_it_stands_in_lower_case() -> None:
    known = lists()
    for word, kind in known.kinds.items():
        assert words(f"Here {word} stands.") == [(word, kind)], word
    assert words("Here wasn't it.") == [("wasn't", NEGATED)]


def test_a_capital_is_read_only_where_the_word_opens_its_sentence() -> None:
    assert words("Not all were seen. Only two were.") == [("not", NEGATED), ("only", LIMIT)]
    assert words("It was in May 2020. The Only Way, a Not study.") == []
    # "May" is the month even where it opens a sentence: the list says so.
    assert words("May 2020 was the month.") == []


def test_a_word_in_a_compound_is_not_read() -> None:
    assert words("Drug-induced, all-cause and cause-specific rates; non-significant.") == [
        ("non-significant", NEGATED)
    ]


@pytest.mark.parametrize(
    "unlisted",
    ["raised", "lowered", "drives", "explains", "is responsible for", "due to",
     "attributable to", "suggestion", "increasing", "an effect of", "a reduction in"],
)  # fmt: skip
def test_a_word_or_a_form_not_in_the_list_moves_nothing(unlisted: str) -> None:
    """A known gap (DESIGN.md, Known gaps, "A word not in the list moves nothing"): neither
    the unlisted words, the forms not listed nor a noun of effect is read, so each written
    in moves no claim; "caused" in its place does."""
    assert words(f"Use {unlisted} harm.") == []
    assert told("Use preceded harm.", f"Use {unlisted} harm.") == []
    assert told("Use preceded harm.", "Use caused harm.") == [
        (STRONGER, "'caused' (causation) is new")
    ]


def test_the_noun_causes_is_read_as_causation() -> None:
    """A known gap (DESIGN.md, Known gaps, "A word not in the list moves nothing"): "the
    leading causes of death" made "the leading reasons" is a claim made weaker."""
    assert words("These are the leading causes of death.") == [("causes", lists().rungs.index(
        "causation"))]  # fmt: skip
    assert told("These are the leading causes of death.",
                "These are the leading reasons for death.") == [
        (WEAKER, "'causes' (causation) is gone")
    ]  # fmt: skip


def test_a_participle_after_an_article_is_an_adjective() -> None:
    effect = lists().kinds["increased"]
    assert words("There was an increased risk, the reduced dose and a predicted value.") == []
    assert words("Use increased the risk.") == [("increased", effect)]


def test_words_of_more_than_one_word_are_read_across_a_line_break() -> None:
    assert words("This was consistent\nwith harm, related  to dose.") == [
        ("consistent with", 0),
        ("related to", 1),
    ]


def test_what_prints_no_prose_is_not_read() -> None:
    text = (
        "Results `may` vary <!-- not --> as {{results.not}} said [@may2019].\n\n"
        "```r\n# may not\n```\n\nSee https://example.org/may/not.\n"
    )
    assert words(text) == []


def test_a_letter_that_case_folds_into_a_listed_word_is_no_word() -> None:
    """The pattern ignores case as Python does, which matches "i" to a dotless i and "s" to
    a long s; the word found then is in no list, and is passed over rather than raising."""
    dotless, dotted, long_s = chr(0x131), chr(0x130), chr(0x17F)
    assert words(f"Use m{dotless}ght harm. {dotted}ncreased. {long_s}uggests.") == []
    assert told("Use may harm.", f"Use m{dotless}ght harm.") == [(STRONGER, "'may' is gone")]


def test_a_curly_apostrophe_is_read_as_a_straight_one() -> None:
    assert words("The groups didn\N{RIGHT SINGLE QUOTATION MARK}t differ.") == [
        ("didn't", NEGATED)
    ]


def test_the_ladder_runs_from_consistency_to_causation() -> None:
    assert lists().rungs == (
        "consistency", "association", "prediction", "contribution", "effect", "causation",
    )  # fmt: skip
    assert {lists().kinds[word] for word in ("may", "could", "appears")} == {HEDGE}


# ------------------------------------------------------------------------ the sentences


def test_a_sentence_ends_at_a_stop_and_a_space_before_a_capital_or_a_block() -> None:
    text = "One may be. Two, e.g. three, 0.5 four.\n\n# Five\n- six\n- seven\n"
    assert [sentence.key for sentence in sentences(text)] == [
        "One may be.", "Two, e.g. three, 0.5 four.", "# Five", "- six", "- seven",
    ]  # fmt: skip
    assert [sentence.line for sentence in sentences(text)] == [1, 1, 3, 4, 5]


def test_a_value_of_the_front_matter_is_its_own_sentence() -> None:
    text = "---\ntitle: X may cause Y\nabstract: Use did not differ\n---\n\nBody.\n"
    found = sentences(text)
    assert [(sentence.line, sentence.words) for sentence in found][:2] == [
        (2, (("may", HEDGE), ("cause", 5))),
        (3, (("not", NEGATED),)),
    ]


def test_only_the_sentences_an_edit_changed_are_lined_up() -> None:
    before = "Kept one. This may hold. Kept two.\n\nMoved here.\n\nCut here may.\n"
    after = "Kept one. This holds. Kept two.\n\nNew here may.\n\nMoved here.\n"
    units = changed(sentences(before), sentences(after))
    assert [([s.key for s in was], [s.key for s in now]) for was, now in units] == [
        (["This may hold."], ["This holds."]),
    ]


def test_a_stretch_of_unequal_length_is_compared_whole() -> None:
    before = "Kept. X may cause Y, which was associated with Z. Kept too."
    after = "Kept. X may cause Y. This was associated with Z. Kept too."
    (unit,) = changed(sentences(before), sentences(after))
    assert (len(unit[0]), len(unit[1])) == (1, 2)
    assert moved(before, after) == []


# ------------------------------------------------------------------------- what is told


def test_an_association_made_an_effect_is_a_stronger_claim() -> None:
    assert told(
        "Use was associated with a higher risk of injury.", "Use increased the risk of injury."
    ) == [(STRONGER, "'associated' (association) is now 'increased' (effect)")]


def test_a_cause_made_an_association_is_a_weaker_claim() -> None:
    assert told("Exposure caused harm.", "Exposure was associated with harm.") == [
        (WEAKER, "'caused' (causation) is now 'associated' (association)")
    ]


def test_a_word_made_another_of_its_rung_or_class_is_free() -> None:
    assert told("Use was associated with harm.", "Use was linked to harm.") == []
    assert told("Use may cause harm.", "Use might cause harm.") == []
    assert told("The groups did not differ.", "The groups never differed.") == []


def test_a_hedge_or_a_limit_gone_is_stronger_and_new_is_weaker() -> None:
    assert told("Use may be linked to harm.", "Use is linked to harm.") == [
        (STRONGER, "'may' is gone")
    ]
    assert told("This holds in women.", "This holds only in women.") == [
        (WEAKER, "'only' is new")
    ]
    assert told("Use may harm.", "Use might possibly harm.") == [
        (WEAKER, "'may' is now 'might' and 'possibly'")
    ]


def test_a_negation_gone_or_new_says_the_opposite_whatever_else_moved() -> None:
    assert told("The groups did not differ.", "The groups differed.") == [
        (NEGATION, "'not' is gone")
    ]
    assert told("Use may cause harm.", "Use does not cause harm.") == [
        (NEGATION, "'may' is gone; 'not' is new")
    ]


def test_negations_are_counted_not_read() -> None:
    """A known gap (DESIGN.md, Known gaps, "Negations are counted, not read"): "not
    uncommon" made "common" is a negation gone, and "failed to show" made "did not show" a
    negation new, though neither says the opposite."""
    assert told("This is not uncommon.", "This is common.") == [(NEGATION, "'not' is gone")]
    assert told("Use failed to show harm.", "Use did not show harm.") == [
        (NEGATION, "'not' is new")
    ]


def test_moves_both_ways_are_a_claim_moved() -> None:
    assert told("Use may cause harm.", "Use was associated with harm.") == [
        (MOVED, "'may' is gone; 'cause' (causation) is now 'associated' (association)")
    ]


def test_a_sentence_is_read_by_its_lowest_rung_where_words_only_left_or_came() -> None:
    assert told(
        "Use was associated with increased mortality.", "Use increased mortality."
    ) == [(STRONGER, "'associated' (association) is gone")]
    assert told("Use preceded harm.", "This is consistent with use preceding harm.") == [
        (WEAKER, "'consistent with' (consistency) is new")
    ]
    assert told("Use preceded harm.", "Use caused harm.") == [
        (STRONGER, "'caused' (causation) is new")
    ]


def test_a_hedge_moved_to_the_next_sentence_is_told_in_each() -> None:
    assert told("A may cause B. C reduces D.", "A causes B. C may reduce D.") == [
        (STRONGER, "'may' is gone"),
        (WEAKER, "'may' is new"),
    ]


def test_a_hedge_carried_across_a_split_sentence_is_no_change() -> None:
    """A known gap (DESIGN.md, Known gaps, "A stretch compared whole hides a word that moved
    between its sentences"): one sentence split in two, its "may" carried from the first
    half to the second, is compared whole and is no change; in a stretch of as many
    sentences on each side the same move is told in each."""
    assert told("Use may be linked to harm and to death.",
                "Use is linked to harm. This may extend to death.") == []  # fmt: skip
    assert told("Use may be linked to harm. Death followed.",
                "Use is linked to harm. Death may have followed.") == [
        (STRONGER, "'may' is gone"), (WEAKER, "'may' is new"),
    ]  # fmt: skip


def _units(before: str, after: str) -> list[tuple[list[str], list[str]]]:
    return [([one.key for one in was], [one.key for one in now])
            for was, now in changed(sentences(before), sentences(after))]  # fmt: skip


def test_a_sentence_that_stands_twice_lines_nothing_up() -> None:
    """A known gap (DESIGN.md, Known gaps, "A sentence that stands twice in a text lines
    nothing up."): "Twice." at the end of a stretch is set aside as unchanged; in the middle
    of one with as many sentences on each side it is compared with what stands at its
    place, and in one with more on one side it is read with the rest of the stretch."""
    assert _units("Kept. Twice. Use may harm. Twice. End.",
                  "Kept. Twice. Use harms. Other. Twice. End.") == [
        (["Use may harm."], ["Use harms.", "Other."]),
    ]  # fmt: skip
    assert _units("Kept. Use may harm. Twice. Age was linked to risk. End. Twice.",
                  "Kept. Twice. Use harms. Age caused risk. End. Twice.") == [
        (["Use may harm."], ["Twice."]), (["Twice."], ["Use harms."]),
        (["Age was linked to risk."], ["Age caused risk."]),
    ]  # fmt: skip
    assert _units("Kept. Use may harm. Twice. Age was linked to risk. End. Twice.",
                  "Kept. Use harms. Twice. Age caused risk. Extra. End. Twice.") == [
        (["Use may harm.", "Twice.", "Age was linked to risk."],
         ["Use harms.", "Twice.", "Age caused risk.", "Extra."]),
    ]  # fmt: skip


def test_a_sentence_deleted_and_another_added_in_one_stretch_pair_with_their_neighbours() -> None:
    """A known gap (DESIGN.md, Known gaps, "A stretch with as many sentences before as after
    is compared sentence by sentence in order"): a sentence deleted and another added pair
    each with its neighbour, and the edit warns twice of a claim made stronger."""
    before = "Kept. Use may be linked to harm. Age was associated with risk. Kept."
    after = "Kept. Age was linked to risk. Smoking increased risk. Kept."
    assert _units(before, after) == [
        (["Use may be linked to harm."], ["Age was linked to risk."]),
        (["Age was associated with risk."], ["Smoking increased risk."]),
    ]
    found = moved(before, after)
    assert [(one.code, one.severity) for one in found] == [(STRONGER, WARN), (STRONGER, WARN)]


def test_a_finding_is_a_warning_on_the_line_the_sentence_stands_on_now() -> None:
    before = "# Results\n\nKept.\nUse was associated\nwith harm.\n"
    after = "# Results\n\nKept.\n\nAdded first.\n\nUse caused\nharm.\n"
    (found,) = moved(before, after, PATH)
    assert (found.gate, found.severity, found.path, found.line) == ("REWORDED", WARN, PATH, 7)
    # A sentence was added beside it, so the stretch is read whole, and placed on the
    # sentence that holds the word that came.
    assert found.message == (
        "these sentences claim more than they did before the edit: 'associated' "
        "(association) is now 'caused' (causation)"
    )
    assert found.hint


def test_reworded_compare_reports_the_claims_beside_the_facts() -> None:
    report = compare("Use did not differ (P = 0.2).", "Use differed (P = 0.2).")
    assert [(found.code, found.severity) for found in report.findings] == [(NEGATION, WARN)]
    assert report.ok
    assert CLAIM_CODES == CODES == {STRONGER, WEAKER, MOVED, NEGATION}


@pytest.mark.parametrize(
    "before, after",
    [
        ("A moved paragraph may hold.\n\nAnother.\n", "Another.\n\nA moved paragraph may hold.\n"),
        ("One may.\n\nTwo not.\n", "One may.\n"),
        ("One may.\n", "One may.\n\nTwo not.\n"),
        ("Rewrapped, it may\nnot hold.\n", "Rewrapped, it may not\nhold.\n"),
    ],
)
def test_a_paragraph_moved_added_deleted_or_rewrapped_is_no_change_of_claim(
    before: str, after: str
) -> None:
    assert moved(before, after) == []
