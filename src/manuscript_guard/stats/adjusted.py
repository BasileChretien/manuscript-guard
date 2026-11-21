"""Where a paper says its P values are adjusted for multiple comparisons, and where a table
says its shares are weighted: what makes a P larger than its statistic gives, or a share not
its count's of the column's n, something to ask the author rather than a finding (Basile,
2026-11-16, decision 31: "Both").

* **An adjustment statement** names a multiple-comparison adjustment of P values, in exact
  words, with no scoring. The false discovery rate or FDR, "adjusted (corrected) for
  multiple comparisons (testing)" and "multiple-comparison correction" stand alone. A
  method's surname, Bonferroni, Holm, Hochberg, Benjamini, Yekutieli, Šidák, Tukey or
  Dunnett, counts only beside a word of `METHOD_WORDS` in the same clause ("Holm
  correction", "Bonferroni-corrected", "Tukey's HSD"), and never followed by "et al." or
  "and colleagues", which cite a paper. A match whose clause holds a word of negation before
  it (`NEGATION`: "P values were not adjusted for multiple comparisons") is none, and the
  search goes on after it; a clause ends at `;`, `:`, `,` and the sentence's end.
  "Adjusted for age and sex" names covariates and is none. The test's own sentence saying
  so is read already, and the test not judged (`stats/reported.QUIET`); this is a paper
  that says it once, in its Methods. An adjustment only makes a P larger, so a P stated
  wholly above the range its statistic gives is what an adjustment gives (`larger`), and is
  asked about; one below it is wrong under any adjustment, and stays a finding.
* **A weighted table** says so in words of `WEIGHTED`: "weighted %", "weighted
  percentages", "weighted n", "weighted statistics", "percentages are weighted",
  "survey-weighted", "inverse probability weighted", "IPW", "IPTW", "nationally
  representative" (Basile, 2026-11-21, "Caption wording"; "non-nationally representative"
  is none). "Unweighted" is none,
  "weighted mean" or "weighted median" names an estimate, not the table's shares, and words
  whose clause holds before them a word of `NOT_WEIGHTED` ("Before IPTW") are none.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from manuscript_guard.stats.reported import Reported, Verdict, _places, _shown

#: A multiple-comparison adjustment of P values named by words that need no other.
ADJUSTMENT = re.compile(
    r"(?i:\bfalse[- ]discovery[- ]rates?\b)|\bFDR\b"
    r"|(?i:\b(?:adjust|correct)(?:ed|ing|ions?|ments?|s)?\s+for\s+multiple\s+"
    r"(?:comparisons?|testing|tests)\b)"
    r"|(?i:\bmultiple[- ](?:comparisons?|testing)[- ](?:adjustments?|corrections?)\b)",
)
#: The surname of a method of adjustment, which counts only beside a word of
#: `METHOD_WORDS` in its clause.
NAMES = re.compile(
    r"\b(?:Bonferroni|Holm|Hochberg|Benjamini|Yekutieli|Tukey|Dunnett"
    r"|[S\N{LATIN CAPITAL LETTER S WITH CARON}]id[a\N{LATIN SMALL LETTER A WITH ACUTE}]k)\b"
)
#: What makes a surname a method's.
METHOD_WORDS = re.compile(
    r"(?i:\b(?:correct(?:ions?|ed)|adjust(?:ments?|ed)|methods?|procedures?|tests?"
    r"|post[- ]hoc|step[- ]?down)\b)|\bHSD\b"
)
#: What after a surname cites a paper: "Holm et al.", "Hochberg and colleagues", a year,
#: "(Dunnett, 1955)", "Holm (1979)", or a number in brackets, "Dunnett [12]" (round 2 of
#: #703).
_CITED = re.compile(
    r"(?i:\s*(?:et\.?\s+al\b|and\s+(?:colleagues|co-?workers)\b))"
    r"|,?\s*\(?\s*(?:1[6-9]|20)\d{2}[a-z]?\b|\s*\[\s*\d"
)
#: A word of negation, which anywhere in an adjustment's clause says none was made.
NEGATION = re.compile(r"(?i:\b(?:not|without|never|nor|neither)\b|\bno\b(?!\.)|n't\b)")
#: What says a table's shares or counts are weighted.
WEIGHTED = re.compile(
    r"(?i:(?<![a-z-])weighted\s*(?:\\?%|percent\w*|proportions?\b|shares?\b|n\b|counts?\b"
    r"|frequenc\w*|numbers?\b|statistics\b|estimates?\b))"
    r"|(?i:\b(?:percent\w*|proportions?|shares?|counts?|frequenc\w*|numbers|statistics"
    r"|estimates?)\s+(?:are|were|is|was)\s+weighted\b)"
    r"|(?i:\bsurvey[- ]weighted\b|\binverse[- ]probability(?:[- ]of[- ]treatment)?[- ]weight\w*)"
    r"|\bIPT?W\b"
    # Basile, 2026-11-21, "Caption wording": a survey's shares made to stand for its nation;
    # "non-nationally representative" says they do not (round 1 of the review of #718).
    r"|(?i:(?<!non-)(?<!non )\bnationally[- ]representative\b)"
)
#: What before words of weighting in their clause says the numbers are not weighted:
#: "Before IPTW", "prior to weighting", "crude".
NOT_WEIGHTED = re.compile(
    r"(?i:\b(?:before|prior|pre|without|not|never|nor|neither|unweighted|crude)\b"
    r"|\bno\b(?!\.)|n't\b)"
)
#: Where a sentence ends: a stop before a capital or a bracket, or a blank line.
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z(\[])|\n[ \t]*\n")
#: Where a clause ends, within its sentence; and where one ends that a negation is looked
#: for in, which a comma does not end: "P values were not, however, adjusted ..." (round 2
#: of #703).
_CLAUSE_END = re.compile(r"[;:,]")
_NEGATION_END = re.compile(r"[;:]")
#: How long a quote is kept whole, and how much of a longer one is kept each side of the
#: words it is quoted for.
_WHOLE, _SIDE = 160, 70


@dataclass(frozen=True)
class Said:
    """Words a text says, where they start, and the quote that shows them."""

    start: int
    quote: str


def _ends(text: str, lines: bool, cuts: tuple[int, ...]) -> list[int]:
    """Where `text`'s sentences end, sorted: `_SENTENCE_END`, each line with `lines`, and
    each offset of `cuts`."""
    ends = [end.end() for end in _SENTENCE_END.finditer(text)] + list(cuts)
    if lines:
        ends += [at + 1 for at, char in enumerate(text) if char == "\n"]
    return sorted(ends)


def _clause(text: str, found: re.Match[str], ends: list[int],
            marks: re.Pattern[str] = _CLAUSE_END) -> tuple[int, int]:  # fmt: skip
    """Where the clause `found` stands in runs: from the last end of a sentence or a clause
    (`marks`) before it to the first after it."""
    start = ends[bisect_right(ends, found.start()) - 1] if bisect_right(ends, found.start()) \
        else 0  # fmt: skip
    after = bisect_left(ends, found.end())
    stop = ends[after] if after < len(ends) else len(text)
    start = max([start, *(mark.end() for mark in marks.finditer(text, start, found.start()))])
    following = marks.search(text, found.end(), stop)
    return start, following.start() if following else stop


def negated(before: str, after: str = "") -> bool:
    """Whether the words of a clause before an adjustment, or after it, say none was made:
    "No correction for multiple testing was applied", "Correction for multiple comparisons
    was not performed" (rounds 1 and 2 of #703)."""
    return bool(NEGATION.search(before) or NEGATION.search(after))


def _a_statement(text: str, found: re.Match[str], ends: list[int]) -> bool:
    """Whether a match of `ADJUSTMENT` or `NAMES` states an adjustment: not negated in its
    clause, before it or after it, which only `;`, `:` and the sentence's end end; and a
    surname not cited and beside a word of `METHOD_WORDS` in its clause, which a comma ends
    too."""
    low, high = _clause(text, found, ends, _NEGATION_END)
    if negated(text[low : found.start()], text[found.end() : high]):
        return False
    start, stop = _clause(text, found, ends)
    if found.re is NAMES:
        if _CITED.match(text, found.end()):
            return False
        return bool(METHOD_WORDS.search(text, start, stop))
    return True


def adjustment(text: str, *, lines: bool = False, cuts: tuple[int, ...] = ()) -> Said | None:
    """The first statement in `text` that names a multiple-comparison adjustment, quoted in
    its sentence; None where there is none. With `lines`, a line ends a sentence too, as a
    paragraph does in a .docx read a paragraph to a line; and so does each offset of `cuts`,
    where a heading starts or ends."""
    ends = _ends(text, lines, cuts)
    matches = sorted([*ADJUSTMENT.finditer(text), *NAMES.finditer(text)],
                     key=lambda one: one.start())  # fmt: skip
    for found in matches:
        if _a_statement(text, found, ends):
            return Said(found.start(), quoted(text, found, lines=lines, cuts=cuts))
    return None


def weighting(text: str) -> Said | None:
    """The first words in `text` that say a table's shares are weighted and whose clause
    holds no word of `NOT_WEIGHTED` before them, quoted; None where none do."""
    ends = _ends(text, True, ())
    for found in WEIGHTED.finditer(text):
        start, _stop = _clause(text, found, ends)
        if not NOT_WEIGHTED.search(text, start, found.start()):
            return Said(found.start(), quoted(text, found, lines=True))
    return None


def quoted(text: str, found: re.Match[str], *, lines: bool = False,
           cuts: tuple[int, ...] = ()) -> str:  # fmt: skip
    """The sentence `found` stands in, as one line, cut to `_SIDE` characters each side of it
    at a space where it is longer than `_WHOLE`; `lines` and `cuts` as `adjustment` has
    them."""
    ends = [end.end() for end in _SENTENCE_END.finditer(text)] + list(cuts)
    if lines:
        ends += [at + 1 for at, char in enumerate(text) if char == "\n"]
    start = max((end for end in ends if end <= found.start()), default=0)
    stop = min((end for end in ends if end >= found.end()), default=len(text))
    sentence = _plain(text[start:stop])
    if len(sentence) <= _WHOLE:
        return sentence
    before = _plain(text[start : found.start()])
    words = _plain(found.group(0))
    after = _plain(text[found.end() : stop])
    head = before[-_SIDE:].partition(" ")[2] if len(before) > _SIDE else before
    tail = after[:_SIDE].rpartition(" ")[0] if len(after) > _SIDE else after
    return ("..." if head != before else "") + " ".join(
        part for part in (head, words, tail) if part) + ("..." if tail != after else "")


def _plain(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split())


def larger(verdict: Verdict) -> bool:
    """Whether the P stated lies wholly above the range its statistic gives: what adjusting
    it for multiple comparisons makes of it."""
    return verdict.reported_low > verdict.high


def asked_p(test: Reported, verdict: Verdict, said: str) -> str:
    """The question asked of a P larger than its statistic gives, in a paper that says
    `said`, its statement quoted with its place: '("...", line 12)'."""
    places = _places(test)
    low, high = _shown(verdict.low, places), _shown(verdict.high, places)
    gives = low if low == high else f"{low} to {high}"
    return (f"The paper says its P values are adjusted {said}. P {test.sign} {test.p} is "
            f"larger than the {gives} that {test.written} gives on its own. Is it the "
            "adjusted P? If not, check the statistic and the P against the analysis.")


#: How a question on a P an adjustment may explain is answered (`asked_p`).
ASK_P_HINT = ("if it is the adjusted P, say so beside the test (\"Holm-adjusted P = ...\"): a "
              "test its sentence calls adjusted is not recomputed. If not, the statistic or the "
              "P is misprinted, or the two come from different analyses")
#: The same question as a referee's draft says it, naming the author and no answer to type.
REFEREE_P = ("{described}; the paper says its P values are adjusted {said}, and an adjustment "
             "makes a P larger: the author is asked whether it is the adjusted P.")


__all__ = ["ADJUSTMENT", "ASK_P_HINT", "METHOD_WORDS", "NAMES", "NEGATION", "NOT_WEIGHTED",
           "REFEREE_P", "WEIGHTED", "Said", "adjustment", "asked_p", "larger", "negated", "quoted",
           "weighting"]  # fmt: skip
