"""G2: a comparison of a statistic typed beside a binding holds of the value emitted.

The emitter refuses a display "<2.53" for a value of 2.532: a comparator display says on
which side of the number the value lies, and the value has to lie there (`contracts/values`,
and `mg_check_display` in the R package). Typed in the sentence instead, the same claim
went through: "all Fs < {{results.f_max}}" printed "all Fs < 2.53" of 2.532, "all ps >
{{results.p_min}}" printed ".260" of .2596, and "{{results.t_min}} < ts" printed "4.27" of
4.268, with every gate green (a psychology preprint rebuilt with the R emitter, PsyArXiv
fyxeq_v2).

There the binding is the bound of a set of statistics: every F lies below 2.53. It is not
always so. "Incidence in the exposed was greater than {{results.inc_unexposed}}" compares
two incidences, and the binding is the other side of the comparison: 2.528 printed 2.53 is
not contradicted by it. So a comparison is read only beside a statistic's symbol, from a
closed list, where the binding is the bound:

- the symbol right before the sign or the phrase: "all Fs <", "*p* less than";
- or right after a sign that follows the binding: "{{results.t_min}} < ts".

A plural, "ps", "Fs", "p-values", says every one of a set lies beyond the number, and the
binding is the set's extreme: a contradiction fails. A singular symbol, "p <" or "z >", may
stand before a threshold rather than a bound: "(z > {{results.z_crit}})" is true of a z
above 1.96 when the critical value 1.959964 prints "1.96", and "p < {{results.alpha}}" of a
p below a corrected alpha of 0.008333 printed "0.0083". There a contradiction is a warning,
with the same message.

The value is held to the comparison as the emitter holds a display's: below the number
printed, or at it, for "<", "≤" and "less than"; above it, or at it, for ">", "≥" and
"greater than". Like the display rule the bound is not strict, and the number compared with
is the one printed. A sign after the binding says the other side lies beyond the number, so
the value is held to the opposite side: "{{results.t_min}} < ts" says the ts are above
4.27, and the smallest of them is held to 4.27 or more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import number_in
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.bound_units import _GAP
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.reader import bound_files

GATE = "G2"
#: How far before a binding a comparator and its statistic are looked for.
_WINDOW = 120

#: Each comparator as it is typed, and whether it says the value is below the number after
#: it. The entities and the escapes are what pandoc prints as the sign.
_BELOW = ("<=", "\N{LESS-THAN OR EQUAL TO}", "\N{LESS-THAN OR SLANTED EQUAL TO}", "&le;",
          "&lt;", "\\<", "<")  # fmt: skip
_ABOVE = (">=", "\N{GREATER-THAN OR EQUAL TO}", "\N{GREATER-THAN OR SLANTED EQUAL TO}", "&ge;",
          "&gt;", "\\>", ">")  # fmt: skip
_SIGN = "|".join(sorted(map(re.escape, (*_BELOW, *_ABOVE)), key=len, reverse=True))
_SPACE = r"[ \t\N{NO-BREAK SPACE}]+"
_WORDS = rf"(?:less|greater){_SPACE}than(?:{_SPACE}or{_SPACE}equal{_SPACE}to)?"
#: Italics around a symbol, as Markdown marks them.
_ITALIC = r"[*_]{0,2}"
#: The statistics whose symbol a comparison is read beside: one letter, and one with its
#: index, typed, a superscript or pandoc's superscript.
_LETTERS = ("p", "P", "F", "t", "r", "z", "d")
_INDEXED = ("\N{GREEK SMALL LETTER CHI}", "R", "I")
_TWO = r"(?:2|\N{SUPERSCRIPT TWO}|\^2\^)"
#: A symbol stands alone: not inside a word, nor after an apostrophe, where "wasn't" ends
#: in a "t"; and not inside an HTML tag, "<p>" or "</p>".
_NOT_IN_A_WORD = r"(?<![^\W_])(?<!['\N{RIGHT SINGLE QUOTATION MARK}])"
_NOT_IN_A_TAG = r"(?<!<)(?<!</)"
_SYMBOL = (
    rf"(?:(?:{'|'.join(_LETTERS)})|(?:{'|'.join(_INDEXED)}){_ITALIC}{_TWO})"
)
#: A statistic, plural or singular. The plural is the symbol with an "s", or a p value
#: written out in the plural.
_STATISTIC = (
    rf"{_NOT_IN_A_WORD}{_NOT_IN_A_TAG}(?:"
    rf"(?P<plural>{_ITALIC}(?:{_SYMBOL}{_ITALIC}s"
    rf"|[pP]{_ITALIC}(?:-|{_SPACE})values){_ITALIC})"
    rf"|(?P<singular>{_ITALIC}{_SYMBOL}{_ITALIC}))"
)
#: A statistic, then a comparator, sign or words, ending right before a binding. The
#: symbols are matched as cased, the comparator in any case.
_BEFORE = re.compile(rf"{_STATISTIC}{_GAP}(?P<op>(?i:{_SIGN}|{_WORDS})){_GAP}\Z")


def _after_pattern(gap: str = _GAP, sign: str = rf"(?i:{_SIGN})") -> re.Pattern[str]:
    """A sign right after a binding, then, past a gap with one line break at most, a
    statistic, "all" before it allowed, which no letter or hyphen follows. Words after a
    binding ("4.27 less than") compare nothing."""
    return re.compile(
        rf"{_GAP}(?P<op>{sign}){gap}(?:all{_SPACE})?{_STATISTIC}(?![^\W_]|-)"
    )


_AFTER = _after_pattern()
#: What a warning beside a single statistic adds to its hint.
_THRESHOLD = (". Beside one statistic the value may be the threshold it is compared with, "
              "which is no bound: then nothing is wrong")  # fmt: skip


@dataclass(frozen=True)
class Compared:
    """A comparator typed beside a binding: the key, where the binding starts, the
    comparator as typed, whether it says the value is below the number printed, and
    whether the statistic it compares is a plural, a set the binding bounds."""

    key: str
    start: int
    op: str
    below: bool
    plural: bool


def _side(op: str) -> bool:
    """Whether a comparator says what stands after it is above what stands before it."""
    folded = op.casefold()
    return folded in _BELOW or folded.startswith("less")


def _states_a_set(found: re.Match[str]) -> bool:
    """Whether the statistic of a comparison read is a plural."""
    return found["plural"] is not None


def _before(text: str, start: int) -> tuple[str, bool, bool] | None:
    """The comparator ending right before the binding at `start`, after a statistic's
    symbol, whether it holds the value below the number printed, and whether the statistic
    is a plural; None where there is none."""
    found = _BEFORE.search(text, max(0, start - _WINDOW), start)
    if found is None:
        return None
    return found["op"], _side(found["op"]), _states_a_set(found)


def _after(text: str, end: int) -> tuple[str, bool, bool] | None:
    """The sign right after the binding ending at `end`, before a statistic, as `_before`
    gives one: "{{results.t}} < ts" holds the value above the number printed."""
    found = _AFTER.match(text, end)
    if found is None:
        return None
    return found["op"], not _side(found["op"]), _states_a_set(found)


def comparisons_at(text: str) -> list[Compared]:
    """Each comparator typed right before or right after a results binding of `text`, with
    the side of the number printed it holds the value to."""
    found = []
    for placeholder in parse(text)[0]:
        if placeholder.namespace != "results":
            continue
        for read in (_before(text, placeholder.start), _after(text, placeholder.end)):
            if read is not None:
                found.append(Compared(placeholder.key, placeholder.start, *read))
    return found


def contradicted(value: object, display: str, below: bool) -> bool:
    """Whether a value is on the wrong side of the number its display prints, as the emitter
    holds a comparator display: below means at the number or under it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    shown = number_in(display)
    if shown is None:
        return False
    return not (float(value) <= shown if below else float(value) >= shown)


def check_bound_comparisons(project: Project, results: Results) -> Report:
    """A finding for each comparison typed beside a binding that its value contradicts: a
    failure beside a plural, a warning beside a singular, which may be a threshold's."""
    report = Report()
    for bound in bound_files(project):
        path, text = bound.path, bound.view
        for compared in comparisons_at(text):
            value = results.values.get(compared.key)
            if value is None or not contradicted(value.value, value.display, compared.below):
                continue
            side = "below" if compared.below else "above"
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="comparison-contradicted",
                    severity=FAIL if compared.plural else WARN,
                    message=f"results.{compared.key} prints {value.display!r} beside "
                    f"{compared.op!r}, which says the value is {side} {value.display}, or at "
                    f"it, but the value is {value.value!r}",
                    path=path,
                    line=text.count("\n", 0, compared.start) + 1,
                    hint="emit the value with the digits that keep the comparison true, or "
                    "write the bound the value meets; a display of the same claim, "
                    f"display=\"{'<' if compared.below else '>'}{value.display}\", is refused "
                    "by the emitter for the same reason"
                    + ("" if compared.plural else _THRESHOLD),
                )
            )
    return report
