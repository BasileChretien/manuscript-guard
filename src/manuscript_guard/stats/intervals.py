"""An estimate and its confidence interval as a text reports them, and what follows.

Two things follow from "OR 2.6 (95% CI 2.1-3.2), P = 0.003" where nothing the analysis
computed holds them together: a value quoted from another paper, or an estimate, its bounds
and its P bound from different keys.

* **A ratio's interval is symmetric on the log scale.** The estimate stands midway between
  the logarithms of its bounds, so its two arms, from the lower bound up to it and from it
  up to the upper bound, are equal. A bound misprinted, or the crude estimate printed with
  the adjusted interval, makes them unequal. Their difference is measured against the
  half-width, at the least over every value the printed digits allow; past `ASYMMETRY`, the
  three numbers do not belong together. "ROR 2.6, 95% CI 2.1-3.2" has arms that differ by
  2.8% of the half-width as printed, and by nothing within its rounding.
* **The interval excludes the null exactly when P is below one less its level.** A 95%
  interval from 1.1 to 2.3, beside P = 0.20, cannot both be right: the interval excludes 1
  and P says the difference is not significant at 0.05. The null is 1 for a ratio and 0 for
  a difference. Judged only where the whole rounding box excludes or includes it, and P
  falls on one side of the level as printed.

Each number is read as the range its printed digits allow, "2.1" as 2.05 to 2.15. A
sentence that calls the interval profile-likelihood, exact, bootstrap, Bayesian or
credible is read and judged on neither identity: neither holds for those. One that calls
its P one-sided, or adjusted or corrected for multiplicity, is not judged on the second.
"Adjusted" alone does not quiet either: an adjusted odds ratio's interval is as symmetric
as a crude one's.

A P is taken as the estimate's own only where no other interval stands between them, and
nothing near it says it is a P for interaction, trend or heterogeneity.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from manuscript_guard.stats.reported import _P, _SIGNS, REACH, p_range

#: Past this share of the half-width, the two arms of a ratio's interval, on the log scale,
#: differ by too much for the estimate and its bounds to belong together.
ASYMMETRY = 0.3

#: A space, or a line break that does not end the paragraph: a sentence wraps anywhere.
_S = r"(?:[ \t\N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE}]|\n(?![ \t]*\n))"
_NUMBER = r"[-\N{MINUS SIGN}]?(?:\d+(?:\.\d+)?|\.\d+)(?![\d.]\d)"
#: What names a ratio, and what a difference: the estimate's kind, and so its null.
_RATIO = (
    r"(?<![\w-])(?:a|adj\.?\s?)?(?:OR|RR|HR|IRR|ROR|PRR|SHR|sHR|GMR)(?![\w-])"
    r"|(?i:\b(?:odds|risk|rate|hazard|reporting\s+odds|incidence\s+rate|proportional\s+reporting"
    r"|prevalence|subdistribution\s+hazard)\s+ratios?\b|\brelative\s+risks?\b)"
)
#: Up to two words naming a method, before an interval's level or its name.
_METHOD = rf"(?:[A-Za-z][A-Za-z-]*{_S}+){{0,2}}"
_DIFFERENCE = (
    r"(?<![\w-])(?:MD|RD|ARD|SMD|WMD)(?![\w-])"
    r"|(?i:\b(?:mean|risk|absolute|standardi[sz]ed mean)?\s?differences?\b)"
)
#: Ratios this does not read, whose intervals need not be symmetric on the log scale (an
#: SMR's exact Poisson interval), but whose names a difference does not cross either. A
#: longer name, "standardised mortality ratio", cannot stand within the 24 characters a name
#: and its estimate may be apart, so no difference reaches across it (round 1 of #336).
_UNREAD = r"(?<![\w-])(?:SMR|SIR)(?![\w-])|(?i:\bratios?\s+of\s+means\b)"
#: Where no other estimate's name begins: "No difference in mortality, HR 0.83" names an HR,
#: and the difference is no estimate of it (round 1 of #300); nor does it of an SMR (round 2).
_NOT_A_NAME = rf"(?!{_RATIO}|{_DIFFERENCE}|{_UNREAD})"
_INTERVAL = re.compile(
    rf"(?:(?P<ratio>{_RATIO})|(?P<difference>{_DIFFERENCE}))"
    # "= 2.6", " of 2.6", " was 2.6", ", 2.6": what stands between the name and its value.
    rf"(?:{_NOT_A_NAME}(?:[^\d\n()\[\]{{}}]|\n(?![ \t]*\n))){{0,24}}?"
    # An en dash straight before the estimate's digits, and after no digit, is its minus:
    # "–1.4" (round 2 of #300). Between two numbers it joins bounds, which come later, and
    # against a name it is a dash: "OR–1.9" is 1.9 (round 1 of #336).
    rf"(?P<estimate>(?:(?<![\w.])\N{{EN DASH}}(?=\.?\d))?{_NUMBER})"
    rf"{_S}*[(\[,;]?{_S}*"
    # "exact 95% CI", "95% profile-likelihood CI": what the interval is, said before it.
    rf"{_METHOD}(?:(?P<level>\d{{2}}(?:\.\d)?){_S}?%{_S}*)?{_METHOD}"
    r"(?:CI|confidence\s+interval)s?\b"
    rf"(?:{_S}*(?P<level2>\d{{2}}(?:\.\d)?){_S}?%)?"
    rf"{_S}*[:,=]?{_S}*"
    rf"(?P<low>{_NUMBER}){_S}*"
    rf"(?P<join>to|[\N{{EN DASH}}\N{{EM DASH}}]|-{{1,3}}|[,;]){_S}*"
    rf"(?P<high>{_NUMBER})"
)
#: Any interval's name: a P after another one is that one's.
_CI_WORD = re.compile(r"\b(?:CI|CrI|confidence\s+interval|credible\s+interval)s?\b")
#: What a sentence says of an interval that neither identity holds for.
_INTERVAL_QUIET = re.compile(
    r"\b(?:profile|likelihood|exact|Clopper|Wilson|Fieller|Cornfield|Newcombe|Agresti|Firth"
    r"|penali[sz]ed|Bayes\w*|posterior|credib\w*|mid-?p|score\s+(?:test|interval)s?|CrI"
    r"|bootstrap\w*|permut\w*|Monte\s+Carlo|simulat\w*)\b",
    re.IGNORECASE,
)
#: What a sentence says of a P that the second identity does not hold for: one-sided, or
#: made larger for multiplicity. Not "adjusted" alone, which is said of estimates.
_P_QUIET = re.compile(
    r"\b(?:one[- ]sided|one[- ]tailed|Bonferroni|Holm|Hochberg|Benjamini"
    r"|[S\N{LATIN CAPITAL LETTER S WITH CARON}]id[a\N{LATIN SMALL LETTER A WITH ACUTE}]k"
    r"|false\s+discovery|FDR|Tukey|Scheff\w*|multiplicity|multiple\s+(?:comparisons|testing)"
    r"|correct(?:ed|ion)|Yates"
    r"|adjusted\s+p(?:\s?-?\s?values?)?|p(?:\s?-?\s?values?)?\s+(?:were\s+|was\s+)?adjusted)\b",
    re.IGNORECASE,
)
#: What says a P is for something other than the estimate before it.
_OTHER_P = re.compile(
    r"\b(?:interaction|trend|heterogeneity|homogeneity|inferiority|equivalence|linearity"
    r"|global|omnibus)\b",
    re.IGNORECASE,
)
#: Each kind's null: what an interval excludes when its estimate differs from no effect.
NULL = {"ratio": 1, "difference": 0}
#: How far after a P the words that say it is another one's are looked for.
_AFTER_P = 40
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z(\[])|\n[ \t]*\n")


@dataclass(frozen=True)
class ReportedInterval:
    """One estimate and its interval as the text reports them, numbers as printed."""

    kind: str  # "ratio" or "difference"
    name: str
    estimate: str
    low: str
    high: str
    #: The level the text states, "95"; empty where it states none.
    level: str
    #: The P the sentence gives after it, as (sign, printed), or None.
    p: tuple[str, str] | None
    start: int
    end: int
    #: The word of the sentence that says the interval is not the plain one.
    quiet: str | None
    #: The word of the sentence that says its P is not the plain one.
    p_quiet: str | None = None

    @property
    def written(self) -> str:
        level = f"{self.level}% " if self.level else ""
        return f"{self.name} {self.estimate} ({level}CI {self.low} to {self.high})"


def reported_intervals(text: str) -> list[ReportedInterval]:
    """Each named estimate in `text` with a confidence interval after it, in order. An
    interval whose bounds cannot be read for sure is left out: one joined by hyphens after
    a negative bound ("-0.9--0.1" is an en dash or a hyphen and a minus), or one whose
    upper bound is below its lower."""
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    found = []
    for match in _INTERVAL.finditer(text):
        if _unsure(match):
            continue
        low, high = match.group("low"), match.group("high")
        start = max((end for end in ends if end <= match.start()), default=0)
        finish = next((end for end in ends if end >= match.end()), len(text))
        another = _CI_WORD.search(text, match.end(), finish)
        stop = min(match.end() + REACH, finish, another.start() if another else finish)
        p = _P.search(text, match.end(), stop)
        if p and _OTHER_P.search(text, match.end(), min(p.end() + _AFTER_P, finish)):
            p = None
        quiet = _INTERVAL_QUIET.search(text, start, finish)
        p_quiet = _P_QUIET.search(text, start, finish)
        found.append(
            ReportedInterval(
                kind="ratio" if match.group("ratio") else "difference",
                name=" ".join((match.group("ratio") or match.group("difference")).split()),
                estimate=match.group("estimate"),
                low=low,
                high=high,
                level=match.group("level") or match.group("level2") or "",
                p=(
                    (_SIGNS[p.group("sign")], p.group(0)[p.start("mantissa") - p.start() :])
                    if p
                    else None
                ),
                start=match.start(),
                end=p.end() if p else match.end(),
                quiet=quiet.group(0) if quiet else None,
                p_quiet=p_quiet.group(0) if p_quiet else None,
            )
        )
    return found


def _unsure(match: re.Match[str]) -> bool:
    """Whether an interval's bounds cannot be read for sure: hyphens after a negative bound,
    or an upper bound below the lower."""
    low, high = _value(match.group("low")), _value(match.group("high"))
    if low is None or high is None or high < low:
        return True
    return match.group("join").startswith("--") and low < 0


def alpha_of(level: str) -> float | None:
    """One less an interval's level, as a share: 0.05 for "95", and where none is stated."""
    try:
        alpha = float((Decimal(100) - Decimal(level or "95")) / 100)
    except InvalidOperation:
        return None
    return alpha if 0 < alpha < 1 else None


def _value(printed: str) -> Decimal | None:
    try:
        return Decimal(printed.replace("\N{MINUS SIGN}", "-").replace("\N{EN DASH}", "-"))
    except InvalidOperation:
        return None


def _box(printed: str) -> tuple[float, float] | None:
    """The values a number printed this way stands for: half a unit of its last place
    either side."""
    value = _value(printed)
    if value is None:
        return None
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    half = Decimal(5) * Decimal(10) ** (exponent - 1)
    return float(value - half), float(value + half)


def outside_interval(interval: ReportedInterval) -> bool:
    """Whether the estimate is outside its own interval over every value the printed digits
    allow: a bound transposed past it, or an estimate from another analysis. Said of any
    interval, a ratio's or a difference's, whatever kind it is (round 1 of #300)."""
    estimate, low, high = (_box(n) for n in (interval.estimate, interval.low, interval.high))
    if estimate is None or low is None or high is None:
        return False
    return estimate[1] < low[0] or estimate[0] > high[1]


def described_outside(interval: ReportedInterval) -> str:
    return f"{interval.written}: the estimate is outside its own interval"


def asymmetry(interval: ReportedInterval) -> float | None:
    """How much the two arms of a ratio's interval differ on the log scale, as a share of
    its half-width, at the least over every value the printed digits allow; None for a
    difference, a sentence that says the interval is not the plain one, numbers that are
    not a ratio's, or an estimate outside its interval, which `outside_interval` says."""
    if interval.kind != "ratio" or interval.quiet:
        return None
    boxes = [_box(n) for n in (interval.estimate, interval.low, interval.high)]
    if any(b is None or b[0] <= 0 for b in boxes):
        return None
    (e0, e1), (l0, l1), (u0, u1) = [(math.log(a), math.log(b)) for a, b in boxes]
    if u1 <= l0 or not l0 <= e1 or not e0 <= u1:
        return None
    # The upper arm less the lower is log U + log L - 2 log E.
    lowest, highest = l0 + u0 - 2 * e1, l1 + u1 - 2 * e0
    off = 0.0 if lowest <= 0 <= highest else min(abs(lowest), abs(highest))
    return off / ((u1 - l0) / 2)


@dataclass(frozen=True)
class AgainstP:
    """What an interval says of its null, against what its P says."""

    excludes: bool
    alpha: float
    null: int


def p_against(interval: ReportedInterval) -> AgainstP | None:
    """Where the interval and its P disagree about the null, what each says; None where
    they agree, or it cannot be said: no P, a sentence that says either is not the plain
    one, a rounding box that straddles the null or the level."""
    if interval.p is None or interval.quiet or interval.p_quiet:
        return None
    sign, printed = interval.p
    reported = p_range(sign, printed)
    low, high = _box(interval.low), _box(interval.high)
    if reported is None or low is None or high is None:
        return None
    alpha = alpha_of(interval.level)
    if alpha is None:
        return None
    null = NULL[interval.kind]
    excludes = low[0] > null or high[1] < null
    includes = low[1] < null < high[0]
    below = reported[1] < alpha or (sign == "<" and reported[1] <= alpha)
    above = reported[0] >= alpha
    if (excludes and above) or (includes and below):
        return AgainstP(excludes=excludes, alpha=alpha, null=null)
    return None


def described_asymmetry(interval: ReportedInterval, share: float) -> str:
    return (
        f"{interval.written}: on the log scale the interval's two arms differ by at least "
        f"{share:.0%} of its half-width, where a ratio's interval has them equal"
    )


def described_against(interval: ReportedInterval, verdict: AgainstP) -> str:
    sign, printed = interval.p or ("=", "")
    side = "above" if verdict.excludes else "below"
    holds = "excludes" if verdict.excludes else "includes"
    return (
        f"{interval.written} {holds} {verdict.null}, and P {sign} {printed} is {side} "
        f"{verdict.alpha:g}"
    )
