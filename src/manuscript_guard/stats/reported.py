"""A test statistic and its P value as a text reports them, and whether the two agree.

"t(23) = 2.45, p = .041" says two things, and the second follows from the first: a t of
2.45 on 23 degrees of freedom has a two-sided P of 0.022. A paper's own numbers are bound,
so their arithmetic is the analysis's. A statistic quoted from another paper, or a P bound
from one key beside a statistic bound from another (the crude beside the adjusted), is not,
and nothing else reads it.

This reads t, F, chi-squared and z with the P after them in the same sentence, in the forms
a results sentence writes them: "t(23) = 2.45, p = .041", "*F*(2, 45) = 3.21, *P* = 0.049",
"chi-squared(1, N = 90) = 4.5, p < .05", "t = 2.45, df = 23, P = 0.041", "z = 2.10,
P = 3.6 x 10^-2^". Both numbers are read as the ranges their printed digits allow, "2.45"
as 2.445 to 2.455, and the P the statistic gives is worked out over the whole range. The
two disagree when the ranges do not meet, and the disagreement is a decision error when
they fall on either side of alpha.

A test the sentence calls one-sided, adjusted or corrected, Welch's, a sphericity-corrected
one, an exact or permutation test, or one run by simulation, is read and not judged: its P
does not follow from the statistic by the textbook formula, and the sentence says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import product

from manuscript_guard.stats.special import p_chi2, p_f, p_t, p_z

#: The significance level a decision is judged at, where nothing declares another.
ALPHA = 0.05
#: How far after its statistic a P is looked for, in characters.
REACH = 160

# Markdown emphasis round a symbol: *t*, _F_, **P**.
_EMPH = r"[*_]{0,2}"
# A space of any width, and at most one line break: a sentence is wrapped where the editor
# wraps it.
_SPACE = r"[ \t\N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE}]"
_GAP = rf"{_SPACE}*(?:\n{_SPACE}*)?"
# Nothing of a word or a number before a symbol: "at(3)" is no t.
_ALONE = r"(?<![\w.])"
_CHI = (
    r"(?:\N{GREEK SMALL LETTER CHI}|\N{GREEK CAPITAL LETTER CHI}|chi)" + _EMPH
    + r"(?:\^2\^|\N{SUPERSCRIPT TWO}|<sup>2</sup>|2|[- ]squared?)"
)
_SYMBOL = (
    _ALONE + _EMPH
    + r"(?:(?P<t>t)|(?P<F>F)|(?P<chi2>" + _CHI + r")|(?P<z>[zZ]))" + _EMPH
)
_DF = r"\d+(?:\.\d+)?"
_MINUS = r"[-\N{MINUS SIGN}\N{EN DASH}]"
# Not the whole part of a decimal written with a middle dot or a comma, "2·45" or "2,45":
# such a number is not read at all (round 1 of #285). A number that has its point already
# is not one, and a comma after it is the sentence's, "2.45,12" with a reference (round 1
# of #336).
_VALUE = (
    rf"(?P<stat>{_MINUS}?\d*(?P<stat_point>\.)?\d+)(?![\d]|\.\d)"
    r"(?(stat_point)|(?![\N{MIDDLE DOT},]\d))"
)
_N = rf"[,;]{_GAP}{_EMPH}[nN]{_EMPH}{_GAP}={_GAP}\d[\d,]*"
_IN_BRACKETS = (
    rf"{_GAP}\({_GAP}(?P<d1>{_DF})(?:{_GAP},{_GAP}(?P<d2>{_DF}))?(?:{_N})?{_GAP}\)"
)
_AFTER = (
    rf"(?:{_GAP}[,;])?{_GAP}(?:with{_GAP})?{_EMPH}(?:d\.?f\.?|DF){_EMPH}{_GAP}={_GAP}"
    rf"(?P<a1>{_DF})(?:{_GAP}(?:,|and){_GAP}(?P<a2>{_DF}))?(?![\d]|\.\d)"
)
_STATISTIC = re.compile(
    _SYMBOL + rf"(?:{_IN_BRACKETS})?{_GAP}[=:]{_GAP}" + _VALUE + rf"(?:{_AFTER})?"
)

_SUPERSCRIPT = str.maketrans(
    "\N{SUPERSCRIPT ZERO}\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}"
    "\N{SUPERSCRIPT FOUR}\N{SUPERSCRIPT FIVE}\N{SUPERSCRIPT SIX}\N{SUPERSCRIPT SEVEN}"
    "\N{SUPERSCRIPT EIGHT}\N{SUPERSCRIPT NINE}\N{SUPERSCRIPT MINUS}",
    "0123456789-",
)
_RAISED = (
    "[\N{SUPERSCRIPT MINUS}]?[\N{SUPERSCRIPT ZERO}\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}"
    "\N{SUPERSCRIPT THREE}\N{SUPERSCRIPT FOUR}-\N{SUPERSCRIPT NINE}]+"
)
_TIMES = rf"{_SPACE}?[x\N{{MULTIPLICATION SIGN}}\N{{MIDDLE DOT}}\N{{DOT OPERATOR}}*]{_SPACE}?10"
# As a statistic's value: a whole part followed by a middle dot or a comma and a digit is
# no P read, unless what follows is a power of ten, "4·10^-5^".
_P_NUMBER = (
    r"(?P<mantissa>\d*(?P<p_point>\.)?\d+)(?P<power>"
    rf"[eE](?P<e1>[-+\N{{MINUS SIGN}}]?\d+)"
    rf"|{_TIMES}(?:\^(?P<e2>{_MINUS}?\d+)\^?"
    rf"|<sup>(?P<e3>{_MINUS}?\d+)</sup>"
    rf"|(?P<e4>{_RAISED})"
    rf"|(?P<e5>{_MINUS}\d+))"
    r")?(?!\d)(?(p_point)|(?(power)|(?![\N{MIDDLE DOT},]\d)))"
)
# The escape `mask` blanks before `<` and `>` may stand before the sign.
_P = re.compile(
    _ALONE + _EMPH + r"[pP]" + _EMPH + rf"(?:{_SPACE}?-?{_SPACE}?values?)?{_GAP}\x00?"
    r"(?P<sign>[=<>\N{LESS-THAN OR EQUAL TO}\N{GREATER-THAN OR EQUAL TO}]|&lt;|&gt;)"
    + _GAP + _P_NUMBER
)
_SIGNS = {
    "=": "=",
    "<": "<",
    "&lt;": "<",
    "\N{LESS-THAN OR EQUAL TO}": "<",
    ">": ">",
    "&gt;": ">",
    "\N{GREATER-THAN OR EQUAL TO}": ">",
}
# Where a sentence ends: a stop before a capital or a bracket, or a blank line.
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z(\[])|\n[ \t]*\n")
#: What a sentence says of a test that makes its P something the textbook formula does not
#: give.
QUIET = re.compile(
    r"\b(?:one[- ]sided|one[- ]tailed|adjust\w*|correct(?:ed|ion)|Bonferroni|Holm|Hochberg"
    r"|Benjamini|[S\N{LATIN CAPITAL LETTER S WITH CARON}]id[a\N{LATIN SMALL LETTER A WITH ACUTE}]k"
    r"|false discovery|FDR|Tukey|Scheff\w*|Dunnett|Games[- ]Howell|Welch|Greenhouse|Huynh"
    r"|Satterthwaite|exact"
    r"|permut\w*|randomi[sz]ation test|Monte Carlo|bootstrap\w*|simulat\w*)\b",
    re.IGNORECASE,
)
_KINDS = {"t": "t", "F": "F", "chi2": "chi-squared", "z": "z"}


@dataclass(frozen=True)
class Reported:
    """One test as the text reports it, its numbers as they are printed."""

    kind: str  # "t", "F", "chi2" or "z"
    statistic: str
    df: tuple[str, ...]
    sign: str  # "=", "<" or ">"
    p: str
    start: int
    end: int
    #: The word of the sentence that says the P is not the textbook one, or None.
    quiet: str | None

    @property
    def written(self) -> str:
        df = f"({', '.join(self.df)})" if self.df else ""
        return f"{_KINDS[self.kind]}{df} = {self.statistic}"


@dataclass(frozen=True)
class Verdict:
    """The P a reported statistic gives, against the P the text gives."""

    low: float
    high: float
    reported_low: float
    reported_high: float
    #: The two ranges do not meet.
    inconsistent: bool
    #: They fall on either side of alpha.
    decision: bool


def reported_tests(text: str) -> list[Reported]:
    """Each test statistic in `text` with a P after it in its sentence, in order."""
    statistics = list(_STATISTIC.finditer(text))
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    found: list[Reported] = []
    for index, match in enumerate(statistics):
        kind = next(name for name in _KINDS if match.group(name))
        df = tuple(d for d in (match.group("d1"), match.group("d2")) if d) or tuple(
            d for d in (match.group("a1"), match.group("a2")) if d
        )
        if len(df) != {"t": 1, "F": 2, "chi2": 1, "z": 0}[kind]:
            continue
        if match.group("d1") and match.group("a1"):
            continue
        following = statistics[index + 1] if index + 1 < len(statistics) else None
        p = _P.search(text, match.end(), _reach(match, following, ends, len(text)))
        # A P the reach cuts through is no P read: "0.0412" read to the reach is "0.04"
        # (round 1 of #285). Read whole, it may be no P at all: "0" cut before "·022"
        # (round 1 of #336).
        whole = None if p is None else _P.match(text, p.start())
        if whole is None or whole.end() != p.end():
            continue
        start = max((end for end in ends if end <= match.start()), default=0)
        finish = next((end for end in ends if end >= p.end()), len(text))
        quiet = QUIET.search(text, start, finish)
        found.append(
            Reported(
                kind=kind,
                statistic=match.group("stat"),
                df=df,
                sign=_SIGNS[p.group("sign")],
                p=p.group(0)[p.start("mantissa") - p.start() :],
                start=match.start(),
                end=p.end(),
                quiet=quiet.group(0) if quiet else None,
            )
        )
    return found


def _reach(match: re.Match, following: re.Match | None, ends: list[int], length: int) -> int:
    """How far after a statistic its P is looked for: to the end of its sentence, and not
    past the next statistic, whose P a P there is."""
    return min(
        match.end() + REACH,
        following.start() if following is not None else length,
        next((end for end in ends if end > match.end()), length),
    )


def _range(printed: str) -> tuple[float, float]:
    """The values a number printed this way stands for: half a unit of its last place
    either side."""
    value = Decimal(printed)
    half = Decimal(5) * Decimal(10) ** (value.as_tuple().exponent - 1)
    return float(value - half), float(value + half)


def _number(printed: str) -> Decimal:
    return Decimal(
        printed.replace("\N{MINUS SIGN}", "-").replace("\N{EN DASH}", "-")
    )


def _p_range(test: Reported) -> tuple[float, float] | None:
    return p_range(test.sign, test.p)


def p_range(sign: str, printed: str) -> tuple[float, float] | None:
    """The values a P printed with this sign stands for: "= 0.041" as 0.0405 to 0.0415,
    "< 0.05" as 0 to 0.05. None where the number cannot be read."""
    match = re.fullmatch(_P_NUMBER, printed)
    if match is None:
        return None
    exponent = next((e for e in match.group("e1", "e2", "e3", "e4", "e5") if e), "0")
    try:
        power = int(exponent.translate(_SUPERSCRIPT).replace("\N{MINUS SIGN}", "-")
                    .replace("\N{EN DASH}", "-"))
        mantissa = Decimal(match.group("mantissa"))
    except (ValueError, InvalidOperation):
        return None
    value = mantissa.scaleb(power)
    if value > 1:
        # No P: "P = 2" read as a P gave a range from 1.95 down to 1 (round 1 of #285).
        return None
    if sign == "<":
        return 0.0, float(value)
    if sign == ">":
        return float(value), 1.0
    half = Decimal(5) * Decimal(10) ** (mantissa.as_tuple().exponent - 1 + power)
    return max(0.0, float(value - half)), min(1.0, float(value + half))


def _p(kind: str, statistic: float, df: tuple[float, ...]) -> float:
    if kind == "t":
        return p_t(statistic, df[0])
    if kind == "F":
        return p_f(statistic, df[0], df[1])
    if kind == "chi2":
        return p_chi2(statistic, df[0])
    return p_z(statistic)


def judge(test: Reported, alpha: float = ALPHA) -> Verdict | None:
    """Whether the P agrees with its statistic; None where it cannot be said: a test the
    sentence says is not the textbook one, or numbers that cannot be read."""
    if test.quiet:
        return None
    reported = _p_range(test)
    try:
        statistic = _number(test.statistic)
        dfs = [_range(d) if "." in d else (float(d), float(d)) for d in test.df]
    except InvalidOperation:
        return None
    if reported is None or any(low <= 0 for low, _high in dfs):
        return None
    if test.kind in ("F", "chi2") and statistic < 0:
        return None
    low, high = _range(str(abs(statistic)))
    try:
        corners = [
            _p(test.kind, s, tuple(d))
            for s, *d in product((max(low, 0.0), high), *dfs)
        ]
    except (ArithmeticError, ValueError):
        # A series that does not converge, on numbers no paper prints: said nothing of,
        # rather than the gate erroring (round 1 of #285).
        return None
    recomputed = (min(corners), max(corners))
    inconsistent = recomputed[1] < reported[0] or recomputed[0] > reported[1]
    below = reported[1] < alpha or (test.sign == "<" and reported[1] <= alpha)
    above = reported[0] >= alpha
    decision = (below and recomputed[0] >= alpha) or (above and recomputed[1] < alpha)
    return Verdict(
        low=recomputed[0],
        high=recomputed[1],
        reported_low=reported[0],
        reported_high=reported[1],
        inconsistent=inconsistent,
        decision=decision,
    )


def described(test: Reported, verdict: Verdict, alpha: float = ALPHA) -> str:
    """What a finding says of a test whose P does not follow from its statistic."""
    sided = " two-sided" if test.kind in ("t", "z") else ""
    places = _places(test)
    low, high = _shown(verdict.low, places), _shown(verdict.high, places)
    gives = (
        f"{test.written} gives a{sided} P of {low}"
        if low == high
        else f"{test.written} gives a{sided} P between {low} and {high}"
    )
    said = f"P {test.sign} {test.p}"
    if verdict.decision:
        return f"{gives}, and the text says {said}, on the other side of {alpha:g}"
    return f"{gives}, and the text says {said}"


def _places(test: Reported) -> int:
    """One decimal more than the P is printed with, and three at least: enough to show how
    the two differ."""
    match = re.fullmatch(_P_NUMBER, test.p)
    if match is None or any(match.group("e1", "e2", "e3", "e4", "e5")):
        return 3
    return max(3, -Decimal(match.group("mantissa")).as_tuple().exponent + 1)


def _shown(p: float, places: int) -> str:
    return f"{p:.2g}" if p < 0.001 else f"{p:.{places}f}"
