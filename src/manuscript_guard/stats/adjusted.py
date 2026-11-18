"""Where a paper says its P values are adjusted for multiple comparisons, and where a table
says its shares are weighted: what makes a P larger than its statistic gives, or a share not
its count's of the column's n, something to ask the author rather than a finding (Basile,
2026-11-16, decision 31: "Both").

* **An adjustment statement** names a multiple-comparison adjustment of P values, in exact
  words, with no scoring: Bonferroni, Holm (Holm-Bonferroni), Hochberg, Benjamini-Hochberg,
  Benjamini-Yekutieli, the false discovery rate or FDR, Šidák, Tukey, Dunnett, or "adjusted
  (corrected) for multiple comparisons (testing)". "Adjusted for age and sex" names
  covariates and is none. The test's own sentence saying so is read already, and the test
  not judged (`stats/reported.QUIET`); this is a paper that says it once, in its Methods.
  An adjustment only makes a P larger, so a P stated wholly above the range its statistic
  gives is what an adjustment gives (`larger`), and is asked about; one below it is wrong
  under any adjustment, and stays a finding.
* **A weighted table** says so in its caption, its cells (its header and its rows' labels)
  or its note: "weighted %", "weighted percentages", "weighted n", "weighted statistics",
  "percentages are weighted", "survey-weighted", "inverse probability weighted", "IPW".
  "Unweighted" is none, and "weighted mean" or "weighted median" names an estimate, not the
  table's shares.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.stats.reported import Reported, Verdict, _places, _shown

#: A multiple-comparison adjustment of P values, named.
ADJUSTMENT = re.compile(
    r"\bBonferroni\b|\bHolm\b|\bHochberg\b|\bBenjamini\b|\bYekutieli\b"
    r"|(?i:\bfalse[- ]discovery[- ]rates?\b)|\bFDR\b"
    r"|\b[S\N{LATIN CAPITAL LETTER S WITH CARON}]id[a\N{LATIN SMALL LETTER A WITH ACUTE}]k\b"
    r"|\bTukey\b|\bDunnett\b"
    r"|\b(?:adjust|correct)(?:ed|ing|ions?|ments?|s)?\s+for\s+multiple\s+"
    r"(?:comparisons?|testing|tests)\b"
    r"|\bmultiple[- ](?:comparisons?|testing)[- ](?:adjustments?|corrections?)\b",
)
#: What says a table's shares or counts are weighted.
WEIGHTED = re.compile(
    r"(?i:(?<![a-z-])weighted\s*(?:\\?%|percent\w*|proportions?\b|shares?\b|n\b|counts?\b"
    r"|frequenc\w*|numbers?\b|statistics\b|estimates?\b))"
    r"|(?i:\b(?:percent\w*|proportions?|shares?|counts?|frequenc\w*|numbers|statistics"
    r"|estimates?)\s+(?:are|were|is|was)\s+weighted\b)"
    r"|(?i:\bsurvey[- ]weighted\b|\binverse[- ]probability(?:[- ]of[- ]treatment)?[- ]weight\w*)"
    r"|\bIPT?W\b"
)
#: Where a sentence ends: a stop before a capital or a bracket, or a blank line.
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z(\[])|\n[ \t]*\n")
#: How long a quote is kept whole, and how much of a longer one is kept each side of the
#: words it is quoted for.
_WHOLE, _SIDE = 160, 70


@dataclass(frozen=True)
class Said:
    """Words a text says, where they start, and the quote that shows them."""

    start: int
    quote: str


def adjustment(text: str, *, lines: bool = False, cuts: tuple[int, ...] = ()) -> Said | None:
    """The first statement in `text` that names a multiple-comparison adjustment, quoted in
    its sentence; None where there is none. With `lines`, a line ends a sentence too, as a
    paragraph does in a .docx read a paragraph to a line; and so does each offset of `cuts`,
    where a heading starts or ends."""
    found = ADJUSTMENT.search(text)
    if found is None:
        return None
    return Said(found.start(), quoted(text, found, lines=lines, cuts=cuts))


def weighting(text: str) -> Said | None:
    """The first words in `text` that say a table's shares are weighted, quoted; None where
    none do."""
    found = WEIGHTED.search(text)
    return None if found is None else Said(found.start(), quoted(text, found, lines=True))


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


__all__ = ["ADJUSTMENT", "ASK_P_HINT", "REFEREE_P", "WEIGHTED", "Said", "adjustment",
           "asked_p", "larger", "quoted", "weighting"]  # fmt: skip
