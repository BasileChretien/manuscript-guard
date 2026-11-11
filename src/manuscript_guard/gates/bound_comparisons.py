"""G2: a comparison typed beside a binding holds of the value emitted, not only of its print.

The emitter refuses a display "<2.53" for a value of 2.532: a comparator display says on
which side of the number the value lies, and the value has to lie there (`contracts/values`,
and `mg_check_display` in the R package). Typed in the sentence instead, the same claim
went through: "all Fs < {{results.f_max}}" printed "all Fs < 2.53" of 2.532, "all ps >
{{results.p_min}}" printed ".260" of .2596, and "{{results.t_min}} < ts" printed "4.27" of
4.268, with every gate green (a psychology preprint rebuilt with the R emitter, PsyArXiv
fyxeq_v2).

So the comparator written right before or right after each results binding is read, and
the value is held to it as the emitter holds a display's: below the number printed, or at
it, for "<", "≤" and "less than"; above it, or at it, for ">", "≥" and "greater than". Like
the display rule the bound is not strict, and the number compared with is the one printed.
A comparator after the binding says the other side lies beyond the number, so the value is
held to the opposite side: "{{results.t_min}} < ts" says the ts are above 4.27, and the
smallest of them is held to 4.27 or more.

A comparison between two numbers is not read: where the other side of the comparator is a
typed number or another binding, the sentence compares the two, and neither is a bound on a
quantity. Nor is "no less than" or "not greater than", nor anything that is no comparator
but looks like one: an HTML tag, an arrow, a blockquote's marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import number_in
from manuscript_guard.findings import FAIL, Finding, Report
from manuscript_guard.gates.bound_units import _GAP
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.reader import bound_files

GATE = "G2"
#: How far either side of a binding a comparator and what it compares are looked for.
_WINDOW = 120

#: Each comparator as it is typed, and whether it says the value is below the number after
#: it. The entities and the escapes are what pandoc prints as the sign.
_BELOW = ("<=", "≤", "⩽", "&le;", "&lt;", "\\<", "<")
_ABOVE = (">=", "≥", "⩾", "&ge;", "&gt;", "\\>", ">")
_SIGN = "|".join(sorted(map(re.escape, (*_BELOW, *_ABOVE)), key=len, reverse=True))
_WORDS = r"(?:less|greater)[ \t ]+than(?:[ \t ]+or[ \t ]+equal[ \t ]+to)?"
#: A comparator, sign or words, ending right before a binding.
_BEFORE = re.compile(rf"(?P<op>{_SIGN}|(?<![\w-]){_WORDS}){_GAP}\Z", re.IGNORECASE)
#: A sign right after a binding. Words after one ("4.27 less than") compare nothing.
_AFTER = re.compile(rf"{_GAP}(?P<op>{_SIGN})")
#: What a sign is part of when it is no comparator: an arrow, a double sign.
_SIGN_AFTER = re.compile(r"[-=<>]\Z")
#: A `>` that closes an HTML tag or a comment opened before it on the line.
_TAG_OPEN = re.compile(r"<[/!A-Za-z][^<>\n]*\Z")
#: A `>` that is a blockquote's marker: at the start of a line, after others.
_QUOTE_MARK = re.compile(r"(?:\A|\n)[ \t]*(?:>[ \t]*)*\Z")
#: A comparison turned round by the word before it: "no less than" is "at least".
_NEGATED = re.compile(r"(?<!\w)(?:no|not|n't)[ \t ]*\Z", re.IGNORECASE)
#: The other side of a comparator before a binding, where it is a number or a binding.
_NUMBER_BEFORE = re.compile(rf"(?:\d|%|\}}\}})[*_]*{_GAP}\Z")
#: The other side of a sign after a binding, where it is a number or a binding.
_NUMBER_AFTER = re.compile(rf"{_GAP}[*_]*(?:[-+−]?\.?\d|\{{\{{|\\mg\{{)")


@dataclass(frozen=True)
class Compared:
    """A comparator typed beside a binding: the key, where the binding starts, the
    comparator as typed, and whether it says the value is below the number printed."""

    key: str
    start: int
    op: str
    below: bool


def _side(op: str) -> bool:
    """Whether a comparator says what stands after it is above what stands before it."""
    folded = op.casefold()
    return folded in _BELOW or folded.startswith("less")


def _before(text: str, start: int) -> tuple[str, bool] | None:
    """The comparator ending right before the binding at `start`, and whether it holds the
    value below the number printed; None where there is none, or one comparing two numbers."""
    found = _BEFORE.search(text, max(0, start - _WINDOW), start)
    if found is None:
        return None
    # What stands before the comparator on its line, and no more than a window of it, so
    # that a file of many bindings is read in one pass.
    at = found.start()
    head = text[max(text.rfind("\n", max(0, at - _WINDOW), at) + 1, at - _WINDOW, 0): at]
    op = found["op"]
    if op.startswith(("<", ">")) and _SIGN_AFTER.search(head):
        return None
    if op == ">" and (_TAG_OPEN.search(head) or _QUOTE_MARK.search(head)):
        return None
    if op[0].isalpha() and _NEGATED.search(head):
        return None
    if _NUMBER_BEFORE.search(head):
        return None
    return op, _side(op)


def _after(text: str, end: int) -> tuple[str, bool] | None:
    """The sign right after the binding ending at `end`, and whether it holds the value below
    the number printed: "{{results.t}} < ts" holds it above."""
    found = _AFTER.match(text, end)
    if found is None:
        return None
    op, tail = found["op"], text[found.end(): found.end() + _WINDOW]
    if op == "<" and re.match(r"[/!A-Za-z<\-=]", tail):
        return None
    if op == ">" and tail.startswith((">", "=")):
        return None
    if not tail.strip(" \t ") or tail.lstrip(" \t ").startswith(("\n", "\r")):
        return None
    if _NUMBER_AFTER.match(tail):
        return None
    return op, not _side(op)


def comparisons_at(text: str) -> list[Compared]:
    """Each comparator typed right before or right after a results binding of `text`, with
    the side of the number printed it holds the value to."""
    found = []
    for placeholder in parse(text)[0]:
        if placeholder.namespace != "results":
            continue
        for read in (_before(text, placeholder.start), _after(text, placeholder.end)):
            if read is not None:
                found.append(Compared(placeholder.key, placeholder.start, read[0], read[1]))
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
    """A failure for each comparison typed beside a binding that its value contradicts."""
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
                    severity=FAIL,
                    message=f"results.{compared.key} prints {value.display!r} beside "
                    f"{compared.op!r}, which says the value is {side} {value.display}, or at "
                    f"it, but the value is {value.value!r}",
                    path=path,
                    line=text.count("\n", 0, compared.start) + 1,
                    hint="emit the value with the digits that keep the comparison true, or "
                    "write the bound the value meets; a display of the same claim, "
                    f"display=\"{'<' if compared.below else '>'}{value.display}\", is refused "
                    "by the emitter for the same reason",
                )
            )
    return report
