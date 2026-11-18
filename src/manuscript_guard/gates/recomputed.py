"""G8 — a P value follows from the statistic reported beside it.

The rest of G8 holds a quantity to itself. This holds two quantities to each other where
the analysis did not: "t(23) = 2.45, p = .041" as the manuscript prints it, bindings
substituted, when the statistic was quoted from another paper, typed, or bound from a
different key than the P (the crude statistic beside the adjusted P). The P a t, F,
chi-squared or z statistic gives is worked out from the statistic and its degrees of
freedom, over every value their printed digits allow, and compared with the P the sentence
gives (`stats/reported.py` says how both are read).

`p-inconsistent`: the two do not meet. `p-decision-error`: they fall on either side of the
significance level, the one the analysis emits as `param.alpha` or 0.05. Both are warnings:
a test the sentence does not call one-sided or adjusted may still be one, and the reading
of a sentence is the reading of a sentence. Where the manuscript says anywhere that its P
values are adjusted for multiple comparisons (`stats/adjusted.py`), a P stated wholly above
the range its statistic gives is what an adjustment gives, and either is a question to the
author (`findings.Question`), at INFO, never counted, quoting the statement and its place; a
P below it stays a warning (Basile, 2026-11-16, decision 31).

And an estimate printed with its confidence interval (`stats/intervals.py`): one outside its
own interval, `interval-excludes-estimate`; a ratio's interval that its estimate does not
stand in the middle of on the log scale, `ratio-interval-asymmetric`; and an interval that
excludes its null beside a P above one less its level, or includes it beside a P below,
`p-against-interval`. Warnings too.

And the words of a sentence against the interval it prints (`stats/interval_words.py`): an
effect stated with no hedge beside an interval that includes its null,
`claim-beyond-interval`, and the estimate called significant, `significance-beyond-interval`,
both warnings; and a sentence that says there is no effect while its ratio's interval does
not exclude ratios far from 1, `no-effect-from-interval`, a note.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import INFO, WARN, Finding, Question, Report
from manuscript_guard.stats.adjusted import ASK_P_HINT, adjustment, asked_p, larger
from manuscript_guard.stats.interval_words import HINTS, NO_EFFECT, Worded, worded
from manuscript_guard.stats.interval_words import described as described_words
from manuscript_guard.stats.intervals import (
    ASYMMETRY,
    asymmetry,
    described_against,
    described_asymmetry,
    described_outside,
    outside_interval,
    p_against,
    reported_intervals,
)
from manuscript_guard.stats.reported import ALPHA, described, judge, reported_tests
from manuscript_guard.text.masking import NUL, mask
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.reader import bound_files

GATE = "G8"


def alpha_of(results: Results) -> float:
    """The significance level the analysis emits, `param.alpha`, or 0.05."""
    value = results.values.get("param.alpha")
    level = value.value if value is not None else None
    if isinstance(level, (int, float)) and not isinstance(level, bool) and 0 < level < 1:
        return float(level)
    return ALPHA


def check_recomputed(project: Project, namespace: dict[str, Value], results: Results) -> Report:
    """Each test statistic the manuscript prints whose P does not follow from it: a question
    where the manuscript says its P values are adjusted and the P is larger (`_p_finding`).
    An interval's P (`p-against-interval`) stays a warning there: an adjustment may widen the
    interval as well as raise the P, or neither, so no exact rule says which way it would
    make them disagree."""
    alpha = alpha_of(results)
    displays = {ref: value.display for ref, value in namespace.items()}
    findings: list[Finding] = []
    judged = judged_intervals = 0
    # Each file as Markdown writes it, its values put in: a LaTeX file's Markdown view, which
    # holds its lines where the `.tex` has them, `\\mg{results.key}` as `{{results.key}}`.
    # Nothing reads TeX after, so a `%` in a display is the character (step 8).
    files = []
    for bound in bound_files(project):
        put = _put_in(bound.view, displays) if bound.latex else substitute(bound.view, displays)
        # Read as masked, a comment's line breaks hidden with it, so that no sentence ends at
        # a blank line inside one; and each finding's line counted in `put`, at the same
        # offsets with every line break, where a P after a comment of several lines was said
        # that many lines too early.
        files.append((bound, put, mask(put)))
    adjusted = adjustment_said(project.root, [(bound.path, put, printed, bound.latex)
                                              for bound, put, printed in files])  # fmt: skip
    for bound, put, printed in files:
        path = bound.path
        for test in reported_tests(printed):
            verdict = judge(test, alpha)
            if verdict is None:
                continue
            judged += 1
            if not verdict.inconsistent:
                continue
            findings.append(_p_finding(test, verdict, alpha, adjusted, path, put, printed))
        intervals = reported_intervals(printed)
        for interval in intervals:
            judged_intervals += 1
            findings += _interval_findings(interval, printed, path, put)
        findings += [_worded_finding(said, printed, path, alpha, put)
                     for said in worded(printed, alpha, intervals)]  # fmt: skip
    return Report(
        tuple(findings),
        {"p_values_recomputed": judged, "printed_intervals_read": judged_intervals},
    )


#: What the warning on a P that does not follow from its statistic advises.
HINT = ("check the statistic, its degrees of freedom and the P against the analysis; two "
        "bound values may come from two analyses, the crude and the adjusted. A one-sided, "
        "adjusted or exact test is not recomputed where the sentence says it is one")


@dataclass(frozen=True)
class Adjusted:
    """Where the manuscript says its P values are adjusted: the file, the line from 1, the
    file as a question names it from another ("manuscript/methods.md"), and the quote."""

    path: Path
    line: int
    named: str
    quote: str

    def said(self, path: Path) -> str:
        """'("...", line 12)', or with the file's name where `path` is another file."""
        place = f"line {self.line}" if self.path == path else f"{self.named}:{self.line}"
        return f'("{self.quote}", {place})'


def _p_finding(test, verdict, alpha: float, adjusted: Adjusted | None, path: Path, put: str,
               printed: str) -> Finding:  # fmt: skip
    """The warning on a P that does not follow from its statistic, or, where the manuscript
    says its P values are adjusted and the P is larger, the question (decision 31)."""
    line = put.count("\n", 0, test.start) + 1
    context = " ".join(printed[test.start : test.end].replace(NUL, " ").split())
    code = "p-decision-error" if verdict.decision else "p-inconsistent"
    if adjusted is not None and larger(verdict):
        return Question(gate=GATE, code=code, message=asked_p(test, verdict, adjusted.said(path)),
                        path=path, line=line, context=context, hint=ASK_P_HINT)  # fmt: skip
    return Finding(gate=GATE, code=code, severity=WARN, message=described(test, verdict, alpha),
                   path=path, line=line, context=context, hint=HINT)  # fmt: skip


def adjustment_said(root: Path, files: list[tuple[Path, str, str, bool]]) -> Adjusted | None:
    """The first statement the manuscript's files make that its P values are adjusted for
    multiple comparisons (`stats.adjusted.adjustment`), outside a reference list typed in a
    Markdown file. Each file is given as its path, its text with every line break, that text
    masked, and whether it is a LaTeX file's view, which prints no reference list."""
    for path, put, printed, latex in files:
        said = adjustment(printed if latex else _without_lists(printed))
        if said is not None:
            try:
                named = path.relative_to(root).as_posix()
            except ValueError:
                named = path.name
            return Adjusted(path, put.count("\n", 0, said.start) + 1, named, said.quote)
    return None


def _without_lists(text: str) -> str:
    """`text` with each reference list typed in it blanked, its line breaks kept."""
    from manuscript_guard.text.reference_lists import reference_lists

    for start, end in reference_lists(text):
        text = text[:start] + "".join(c if c == "\n" else " " for c in text[start:end]) + \
            text[end:]  # fmt: skip
    return text


def _put_in(view: str, displays: dict[str, str]) -> str:
    """A LaTeX file's Markdown view with each value put in, its line breaks kept: one between
    `\\mg` and its brace is kept beside the display, so the lines after it stay the `.tex`
    lines (round 1 of step 8): before it where nothing but spaces follows it on its line, so
    that no line of nothing but spaces ends the paragraph between a statistic and its P
    (rounds 2 and 3). A split binding alone on its line makes such a line on one side or the
    other (DESIGN.md, step 8's limits)."""
    out = view
    for placeholder in sorted(parse(view)[0], key=lambda p: p.start, reverse=True):
        if placeholder.is_anchor:
            written = ""
        elif placeholder.ref in displays:
            written = displays[placeholder.ref]
        else:
            continue
        breaks = "\n" * view.count("\n", placeholder.start, placeholder.end)
        rest = view.find("\n", placeholder.end)
        if not view[placeholder.end : len(view) if rest < 0 else rest].strip():
            written = breaks + written
        else:
            written = written + breaks
        out = out[: placeholder.start] + written + out[placeholder.end :]
    return out


def _interval_findings(interval, printed: str, path, lined: str) -> list[Finding]:
    """What an estimate and its interval, and the P beside them, say against each other, at
    its line of `lined`, the text `printed` masks."""
    context = " ".join(printed[interval.start : interval.end].replace(NUL, " ").split())
    line = lined.count("\n", 0, interval.start) + 1
    found = []
    if outside_interval(interval):
        found.append(
            Finding(
                gate=GATE,
                code="interval-excludes-estimate",
                severity=WARN,
                message=described_outside(interval),
                path=path,
                line=line,
                context=context,
                hint="a bound is misprinted, or the estimate and its interval come from "
                "different analyses; check all three against the analysis",
            )
        )
    share = asymmetry(interval)
    if share is not None and share > ASYMMETRY:
        found.append(
            Finding(
                gate=GATE,
                code="ratio-interval-asymmetric",
                severity=WARN,
                message=described_asymmetry(interval, share),
                path=path,
                line=line,
                context=context,
                hint="check the estimate and both bounds against the analysis: one may be "
                "misprinted, or bound from another row or another model. A profile, exact "
                "or bootstrap interval is not judged where the sentence says it is one",
            )
        )
    verdict = p_against(interval)
    if verdict is not None:
        found.append(
            Finding(
                gate=GATE,
                code="p-against-interval",
                severity=WARN,
                message=described_against(interval, verdict),
                path=path,
                line=line,
                context=context,
                hint="the interval and the P come from different analyses, or one is "
                "misprinted; check both against the analysis. An adjusted or one-sided P "
                "is not judged where the sentence says it is one",
            )
        )
    return found


def _worded_finding(said: Worded, printed: str, path, alpha: float, lined: str) -> Finding:
    """What a sentence's words say beyond its interval, at its first interval."""
    first, last = said.intervals[0], said.intervals[-1]
    return Finding(
        gate=GATE,
        code=said.code,
        severity=INFO if said.code == NO_EFFECT else WARN,
        message=described_words(said, alpha),
        path=path,
        line=lined.count("\n", 0, first.start) + 1,
        context=" ".join(printed[first.start : last.end].replace(NUL, " ").split()),
        hint=HINTS[said.code],
    )
