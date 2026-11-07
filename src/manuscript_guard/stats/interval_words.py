"""Words that say more than the interval they report.

"Use increased the risk of bleeding (HR 1.31, 95% CI 0.92 to 1.86)" states an effect that
its own interval does not show: the interval includes 1, so the data are compatible with no
effect at all. The interval is printed in the same sentence, so this can be read without
asking what the author meant. Three things are said of an interval that includes its null,
1 for a ratio and 0 for a difference (`stats/intervals.py`):

* `claim-beyond-interval`, a warning: the sentence states an effect or a difference with no
  hedge, "increased the risk", "was associated with a higher risk", "reduced".
* `significance-beyond-interval`, a warning: the sentence calls the estimate significant.
  An interval that includes the null at a level goes with a P at or above one less that
  level, so at the paper's significance level, or any lower one, the estimate is not
  significant.
* `no-effect-from-interval`, a note: the sentence says there is no effect, "no
  difference", "did not affect", "had no effect", while its interval does not exclude
  ratios far from 1: an upper bound above 1.5, or a lower one below 1/1.5. The note gives
  those bounds. A difference is not read for this, since what is far for a difference
  depends on its scale, and nothing the project declares says it (DESIGN.md, Known gaps).

"No significant difference", "a non-significant increase" and "no evidence of" speak of
the test or the evidence, not of the effect, and are left alone; so is a sentence that
hedges ("may", "suggests"), says the estimate is uncertain ("a trend", "imprecise",
"compatible with"), calls something in it not significant ("higher, but the difference was
not significant"), or names another test ("interaction", "heterogeneity"), whose words may
be that test's. The words are lists in `data/claim_strength.yaml`, under `interval`; a
Markdown heading ends a sentence at the end of its line.

An interval is judged as `stats/intervals.py` judges one against its P, and nowhere else:
over every value its printed digits allow, never in a sentence that calls the interval
profile-likelihood, exact, bootstrap or Bayesian or its P one-sided or adjusted, never for
an estimate outside its own interval, and only at a level no higher than one less the
paper's significance level, since a 99% interval that includes 1 says nothing of P at 0.05.

The first two are said of a sentence, not of one interval: every interval in it must
include its null, and every interval it names must be one the reader reads, because the
words may be about another estimate. The third is said of each interval in a sentence that
says there is no effect.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import yaml

from manuscript_guard.claims import (
    _LETTER,
    DATA,
    EDGES,
    HEDGE,
    NEGATED,
    _capital,
    claim_words,
    lists,
    readable,
    sentence_pieces,
)
from manuscript_guard.stats.intervals import (
    _CI_WORD,
    _OTHER_P,
    NULL,
    ReportedInterval,
    _box,
    alpha_of,
    outside_interval,
    reported_intervals,
)
from manuscript_guard.stats.reported import ALPHA

CLAIM = "claim-beyond-interval"
SIGNIFICANCE = "significance-beyond-interval"
NO_EFFECT = "no-effect-from-interval"
#: Every code this module's findings carry.
CODES = (CLAIM, SIGNIFICANCE, NO_EFFECT)

#: A ratio's bound is far from 1 above this, or below its inverse.
FAR = 1.5
#: How many words before a word of effect a negation turns it round: "did not increase",
#: "was not significantly associated", "had no higher risk".
REACH = 4
#: The rung of the ladder whose words hedge: "suggests", "consistent with".
HEDGING_RUNG = "consistency"
#: A word between a form of "be" or "have" and what it says: any run of characters that
#: holds no space, no bracket and no blanked text.
_GAP_WORD = r"[^\s\x00()\[\]{},;:]+"
_TOKEN = re.compile(r"[^\s\x00]+")
_WORD_BEFORE = re.compile(r"([^\W\d_]+)\s+\Z")
_SIGNIFICAN = re.compile(r"significan", re.IGNORECASE)
#: What says a word of another test is said of a test: a P, "P-interaction" too, or the
#: word "test", "testing" and "Q-test" too (round 3 of #572).
_A_TEST = re.compile(r"(?<![\w-])[Pp](?!\w)|(?<!\w)test(?:s|ed|ing)?(?![\w-])")
#: How far from such a word a P or "test" may stand, in characters.
NEAR_A_TEST = 40
#: A Markdown heading's line, as `claims` opens a block at one.
_HEADING = re.compile(r"^[ \t\x00]*#[^\n]*", re.MULTILINE)


#: One word of a list as a pattern. Its group `lead` is the form of "be" or "have" that
#: "{be}" or "{have}" stands for, where it has one, and `tail` the listed words after it.
Phrase = re.Pattern[str]


@dataclass(frozen=True)
class Words:
    """The lists of `interval` in the data file, each as its phrases."""

    effect: tuple[Phrase, ...]
    significant: tuple[Phrase, ...]
    no_effect: tuple[Phrase, ...]
    uncertain: tuple[Phrase, ...]
    describing: frozenset[str]
    not_the_test: frozenset[str]


def _compiled(phrase: str, slots: dict[str, str]) -> Phrase:
    """A phrase of a list as a pattern, "{be}" and "{have}" put in: a word of their list,
    then at most two words."""
    head, _, rest = phrase.partition(" ")
    if head in slots:
        lead = rf"(?P<lead>{slots[head]})(?:\s+{_GAP_WORD}){{0,2}}\s+"
        tail = rest
    else:
        lead, tail = "", phrase
    words = r"\s+".join(map(re.escape, tail.split()))
    return re.compile(rf"{EDGES[0]}{lead}(?P<tail>{words}){EDGES[1]}", re.IGNORECASE)


@lru_cache(maxsize=1)
def words() -> Words:
    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))["interval"]
    slots = {
        "{be}": "|".join(map(re.escape, sorted(data["be"], key=len, reverse=True))),
        "{have}": "|".join(map(re.escape, sorted(data["have"], key=len, reverse=True))),
    }

    def phrases(name: str) -> tuple[Phrase, ...]:
        return tuple(_compiled(phrase, slots) for phrase in data[name])

    nouns = "|".join(map(re.escape, data["significant_of"]))
    of_a_result = re.compile(
        rf"{EDGES[0]}(?P<tail>significant)(?:\s+{_GAP_WORD})?\s+(?:{nouns}){EDGES[1]}",
        re.IGNORECASE,
    )
    return Words(
        effect=phrases("effect"),
        significant=(*phrases("significant"), of_a_result),
        no_effect=phrases("no_effect"),
        uncertain=phrases("uncertain"),
        describing=frozenset(data["describing"]),
        not_the_test=frozenset(data["not_the_test"]),
    )


@dataclass(frozen=True)
class Said:
    """Where a phrase was read, and its words as typed, spaces made one."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Worded:
    """What one sentence says beyond its intervals: the code, the intervals it is said of,
    the words that say it, and, for "no effect", the bounds far from 1."""

    code: str
    intervals: tuple[ReportedInterval, ...]
    words: tuple[str, ...]
    far: tuple[tuple[str, str], ...] = ()


def worded(
    text: str, alpha: float = ALPHA, found: Sequence[ReportedInterval] | None = None
) -> list[Worded]:
    """Each sentence of `text` whose words say more than the intervals it reports, in
    order. `text` is as `reported_intervals` reads it, its line ends of any kind; `found`
    are its intervals where the caller has read them already. `alpha` is the paper's
    significance level."""
    intervals = list(reported_intervals(text) if found is None else found)
    if not intervals:
        return []
    # Line ends made line feeds at the same offsets: the sentences are cut on line feeds.
    text = text.replace("\r\n", " \n").replace("\r", "\n")
    read = readable(text)
    blank = _blanked(read, intervals)
    said: list[Worded] = []
    for start, first, end in sentence_pieces(text, read, cuts=heading_ends(read)):
        mine = [interval for interval in intervals if start <= interval.start < end]
        if mine:
            said += _sentence(read, blank, first, end, mine, alpha)
    return said


def heading_ends(read: str) -> list[int]:
    """Where each heading of a Markdown file ends: the line under it opens a sentence of its
    own, though no blank line stands between (round 1 of #572)."""
    return [found.end() for found in _HEADING.finditer(read)]


def _blanked(read: str, intervals: Sequence[ReportedInterval]) -> str:
    """`read` with each interval, its name, numbers and P, blanked: "the mean difference
    was" names an estimate and says nothing of it."""
    chars = list(read)
    for interval in intervals:
        chars[interval.start : interval.end] = "\x00" * (interval.end - interval.start)
    return "".join(chars)


@dataclass(frozen=True)
class Heard:
    """What one sentence's words say, read apart from its intervals."""

    #: Words of effect that no negation turns round, and those one does, each shown from
    #: its negation: "did not affect".
    stated: tuple[Said, ...]
    turned: tuple[Said, ...]
    #: Words of significance: all of them, those no negation turns round, and those one
    #: does: "the difference was not significant".
    significant: tuple[Said, ...]
    tested: tuple[Said, ...]
    untested: tuple[Said, ...]
    #: Words that say there is no effect.
    none: tuple[Said, ...]
    hedged: bool
    unsure: bool
    #: Whether the sentence names another test, its words perhaps of that one: "the test
    #: for interaction was significant".
    another_test: bool


def heard(blank: str, first: int, end: int) -> Heard:
    """What the sentence `blank[first:end]` says, its intervals blanked."""
    listed = words()
    starts = [token.start() for token in _TOKEN.finditer(blank, first, end)]
    negations = _negations(blank, first, end)

    def negation(one: Said) -> int | None:
        """Where the negation that turns `one` round starts: among the `REACH` words before
        it, or inside it, "was not associated"."""
        before = [at for at in starts if at < one.start][-REACH:]
        reach = before[0] if before else one.start
        return next((at for at, stop in negations if reach <= at and stop <= one.end), None)

    effect = _read(blank, first, end, listed.effect, listed.describing)
    significant = [one for one in _read(blank, first, end, listed.significant)
                   if not _not_the_test(blank, first, one, listed.not_the_test)]  # fmt: skip
    kinds = {kind for _word, kind in claim_words(blank, first, end)}
    return Heard(
        stated=tuple(one for one in effect if negation(one) is None),
        turned=tuple(_from(blank, at, one) for one in effect
                     if (at := negation(one)) is not None),  # fmt: skip
        significant=tuple(significant),
        tested=tuple(one for one in significant if negation(one) is None),
        untested=tuple(one for one in significant if negation(one) is not None),
        none=tuple(_read(blank, first, end, listed.no_effect)),
        hedged=HEDGE in kinds or lists().rungs.index(HEDGING_RUNG) in kinds,
        unsure=bool(_read(blank, first, end, listed.uncertain)),
        another_test=_another_test(blank, first, end),
    )


def _another_test(blank: str, first: int, end: int) -> bool:
    """Whether the sentence names another test: a word of `stats/intervals.py`'s list
    ("interaction", "heterogeneity", "trend") with a P or the word "test" at most
    `NEAR_A_TEST` characters from it, as that module reads one after a P. "An interaction
    with warfarin" and "global cognition" name none (round 2 of #572)."""
    for word in _OTHER_P.finditer(blank, first, end):
        near = (max(first, word.start() - NEAR_A_TEST), min(end, word.end() + NEAR_A_TEST))
        if _A_TEST.search(blank, *near):
            return True
    return False


def claims_effect(said: Heard) -> bool:
    """Whether a sentence states an effect or a difference, with no hedge, no word that
    says it is uncertain, nothing called not significant ("higher, but the difference was
    not significant") and no other test named."""
    return (bool(said.stated) and not said.hedged and not said.unsure and not said.untested
            and not said.another_test)  # fmt: skip


def calls_significant(said: Heard) -> bool:
    """Whether a sentence calls its estimate significant, with no word that says it is
    uncertain and no other test named."""
    return bool(said.tested) and not said.unsure and not said.another_test


def says_no_effect(said: Heard) -> bool:
    """Whether a sentence says there is no effect, and not of the test ("no significant
    difference"), with no hedge, no word that says it is uncertain and no other test
    named."""
    return (bool(said.none or said.turned) and not said.significant and not said.hedged
            and not said.unsure and not said.another_test)  # fmt: skip


def _sentence(
    read: str, blank: str, first: int, end: int, mine: list[ReportedInterval], alpha: float
) -> list[Worded]:
    """What one sentence, `blank[first:end]`, says beyond the intervals `mine`."""
    said = heard(blank, first, end)
    found: list[Worded] = []
    if _whole(read, first, end, mine, alpha):
        if claims_effect(said):
            found.append(Worded(CLAIM, tuple(mine), _texts(said.stated)))
        if calls_significant(said):
            found.append(Worded(SIGNIFICANCE, tuple(mine), _texts(said.tested)))
    if says_no_effect(said):
        for interval in mine:
            far = far_bounds(interval) if judged(interval, alpha) else ()
            if far:
                found.append(Worded(NO_EFFECT, (interval,), _texts(said.none + said.turned),
                                    far))  # fmt: skip
    return found


def _from(blank: str, at: int, one: Said) -> Said:
    """`one` read from `at`, where the negation before it starts."""
    start = min(at, one.start)
    shown = " ".join(blank[start : one.end].replace("\x00", " ").split())
    return Said(start, one.end, shown)


def _texts(said: Sequence[Said]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(one.text for one in sorted(said, key=lambda one: one.start)))


def _read(
    blank: str, first: int, end: int, phrases: Sequence[Phrase],
    describing: frozenset[str] = frozenset(),
) -> list[Said]:  # fmt: skip
    """Each phrase of `phrases` read in `blank[first:end]`, in order, none overlapping one
    before it. A word typed with a capital is read only where it opens the sentence, and a
    word ending in "ed" not directly after a word of `describing`."""
    found: list[Said] = []
    for phrase in phrases:
        for match in phrase.finditer(blank, first, end):
            lead = match.group("lead") if "lead" in phrase.groupindex else None
            tail = match.group("tail")
            typed = f"{lead} {tail}" if lead else tail
            if typed != typed.lower():
                opens = _LETTER.search(blank, first, match.start()) is None
                if not _capital(typed.lower(), typed, opens):
                    continue
            if lead is None and tail.lower().endswith("ed") and _before(
                    blank, first, match.start()) in describing:  # fmt: skip
                continue
            found.append(Said(match.start(), match.end(), " ".join(match.group().split())))
    kept: list[Said] = []
    for one in sorted(found, key=lambda one: (one.start, -one.end)):
        if not kept or one.start >= kept[-1].end:
            kept.append(one)
    return kept


def _before(blank: str, first: int, at: int) -> str | None:
    """The word directly before `at`, in lower case, with nothing but spaces between."""
    word = _WORD_BEFORE.search(blank, max(first, at - 40), at)
    return word.group(1).lower() if word else None


def _not_the_test(blank: str, first: int, one: Said, words: frozenset[str]) -> bool:
    """Whether the word directly before "significant" says it is not the test's:
    "clinically significant"."""
    at = [found.start() for found in _SIGNIFICAN.finditer(blank, one.start, one.end)]
    return bool(at) and _before(blank, first, at[-1]) in words


def _negations(blank: str, first: int, end: int) -> list[tuple[int, int]]:
    """Where each negation of the ladder's lists stands in the sentence."""
    known = lists()
    found = []
    for match in known.pattern.finditer(blank, first, end):
        typed = match.group()
        word = " ".join(typed.lower().split())
        if known.kind(word) != NEGATED:
            continue
        if typed != typed.lower():
            opens = _LETTER.search(blank, first, match.start()) is None
            if not _capital(word, typed, opens):
                continue
        found.append((match.start(), match.end()))
    return found


def _whole(read: str, first: int, end: int, mine: Sequence[ReportedInterval],
           alpha: float) -> bool:  # fmt: skip
    """Whether every interval of a sentence is judged and includes its null, and the
    sentence names no interval the reader does not read: the words may be about it."""
    named = len(_CI_WORD.findall(read, first, end))
    return named == len(mine) and all(judged(one, alpha) and includes_null(one)
                                      for one in mine)  # fmt: skip


def judged(interval: ReportedInterval, alpha: float = ALPHA) -> bool:
    """Whether an interval is judged at all: one `stats/intervals.py` would judge against
    its P, an estimate inside it, at a level whose interval says something of P at
    `alpha`."""
    if interval.quiet or interval.p_quiet or outside_interval(interval):
        return False
    level = alpha_of(interval.level)
    return level is not None and level >= alpha - 1e-9


def includes_null(interval: ReportedInterval) -> bool:
    """Whether the interval includes its null over every value its printed digits allow."""
    low, high = _box(interval.low), _box(interval.high)
    if low is None or high is None:
        return False
    return low[1] < NULL[interval.kind] < high[0]


def far_bounds(interval: ReportedInterval) -> tuple[tuple[str, str], ...]:
    """The bounds of a ratio's interval that includes 1 that are far from 1 over every value
    their digits allow, each as ("low", printed) or ("high", printed): the lower below
    1/1.5, the upper above 1.5. None for a difference, or an interval that does not include
    1."""
    if interval.kind != "ratio" or not includes_null(interval):
        return ()
    low, high = _box(interval.low), _box(interval.high)
    if low is None or high is None:
        return ()
    far = []
    if low[1] < 1 / FAR:
        far.append(("low", interval.low))
    if high[0] > FAR:
        far.append(("high", interval.high))
    return tuple(far)


def _listed(shown: Sequence[str]) -> str:
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _quoted(words: Sequence[str]) -> str:
    return _listed([f"'{word}'" for word in words])


def _include(intervals: Sequence[ReportedInterval]) -> str:
    return _listed([f"{one.written} includes {NULL[one.kind]}" for one in intervals])


def described(said: Worded, alpha: float = ALPHA) -> str:
    """What a finding says of a sentence."""
    if said.code == CLAIM:
        return (f"{_include(said.intervals)}, and the sentence states an effect or a "
                f"difference with no hedge: {_quoted(said.words)}")  # fmt: skip
    if said.code == SIGNIFICANCE:
        which = "it is not" if len(said.intervals) == 1 else "none is"
        return (f"{_include(said.intervals)}, so {which} significant at {alpha:g}, and the "
                f"sentence says {_quoted(said.words)}")  # fmt: skip
    (interval,) = said.intervals
    reach = " or ".join(f"as {side} as {bound}" for side, bound in said.far)
    return (f"{interval.written} includes 1 and the sentence says {_quoted(said.words)}, "
            f"but the interval does not exclude a ratio {reach}")


HINTS = {
    CLAIM: "an interval that includes no effect is compatible with none: report the estimate "
    "with what its interval allows, or hedge the claim; if the words are right, check the "
    "bounds against the analysis. An exact, profile-likelihood, bootstrap or Bayesian "
    "interval is not judged where the sentence says it is one",
    SIGNIFICANCE: "an interval that includes no effect goes with a P at or above one less "
    "its level: if the test was significant, the interval or the P comes from another "
    "analysis, so check both. A one-sided or adjusted P is not judged where the sentence "
    "says it is one",
    NO_EFFECT: "an interval that includes 1 shows no effect only where it also excludes the "
    "effects that would matter: say which effects it does not rule out, or call the result "
    "inconclusive",
}
