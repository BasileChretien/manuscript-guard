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
of a sentence is the reading of a sentence.
"""

from __future__ import annotations

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.stats.reported import ALPHA, described, judge, reported_tests
from manuscript_guard.text.masking import NUL, mask
from manuscript_guard.text.placeholders import substitute

GATE = "G8"


def alpha_of(results: Results) -> float:
    """The significance level the analysis emits, `param.alpha`, or 0.05."""
    value = results.values.get("param.alpha")
    level = value.value if value is not None else None
    if isinstance(level, (int, float)) and not isinstance(level, bool) and 0 < level < 1:
        return float(level)
    return ALPHA


def check_recomputed(project: Project, namespace: dict[str, Value], results: Results) -> Report:
    """Each test statistic the manuscript prints whose P does not follow from it."""
    alpha = alpha_of(results)
    displays = {ref: value.display for ref, value in namespace.items()}
    findings: list[Finding] = []
    judged = 0
    for path in source_files(project.path("manuscript")):
        printed = mask(substitute(read_text(path), displays))
        for test in reported_tests(printed):
            verdict = judge(test, alpha)
            if verdict is None:
                continue
            judged += 1
            if not verdict.inconsistent:
                continue
            findings.append(
                Finding(
                    gate=GATE,
                    code="p-decision-error" if verdict.decision else "p-inconsistent",
                    severity=WARN,
                    message=described(test, verdict, alpha),
                    path=path,
                    line=printed.count("\n", 0, test.start) + 1,
                    context=" ".join(printed[test.start : test.end].replace(NUL, " ").split()),
                    hint="check the statistic, its degrees of freedom and the P against the "
                    "analysis; two bound values may come from two analyses, the crude and "
                    "the adjusted. A one-sided, adjusted or exact test is not recomputed "
                    "where the sentence says it is one",
                )
            )
    return Report(tuple(findings), {"p_values_recomputed": judged})
