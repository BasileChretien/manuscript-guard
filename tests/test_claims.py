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
