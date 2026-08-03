"""G8 — the same quantity is written the same way everywhere.

Most of this gate's work is done by construction rather than by checking. Because the
display string is fixed when a value is emitted, and because prose can only quote a value
through its key, one quantity cannot be rounded two ways in two sections. That is the
point of putting formatting in the results file instead of in the manuscript.

What remains is the failure mode construction cannot prevent: two *different* keys that
hold the same quantity. That happens when two scripts compute the same thing, or when a
key is emitted twice under different names during a refactor, and it reintroduces exactly
the divergence the design was meant to remove — one of the pair gets updated and the other
does not.
"""

from __future__ import annotations

from collections import defaultdict

from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, WARN, Finding, Report

GATE = "G8"


def check_consistency(results: Results) -> Report:
    report = Report()
    by_value: dict[str, list[str]] = defaultdict(list)

    for key, value in results.values.items():
        if not value.quoted:
            continue
        if isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
            by_value[f"{float(value.value):.12g}"].append(key)

    collisions = 0
    for literal, keys in sorted(by_value.items()):
        if len(keys) < 2:
            continue
        collisions += 1
        displays = {results.values[k].display for k in keys}
        same_display = len(displays) == 1
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="duplicate-quantity" if same_display else "divergent-display",
                severity=WARN if same_display else FAIL,
                message=(
                    f"{len(keys)} quoted keys hold the value {literal}: " + ", ".join(sorted(keys))
                ),
                path=results.values[keys[0]].source,
                context="displays: " + ", ".join(sorted(displays)),
                hint=(
                    "if these are the same quantity, emit it once and reference the one key; "
                    "if they are genuinely different quantities that happen to coincide, "
                    "nothing needs to change"
                    if same_display
                    else "the same value is written two different ways; pick one display and "
                    "emit the quantity once"
                ),
            )
        )

    report = report.merge(_check_declared_pairs(results))
    return report.with_counts(value_collisions=collisions)


def _check_declared_pairs(results: Results) -> Report:
    """Keys the author declared to be one quantity, which must therefore agree.

    Everything above works by coincidence of value: two keys are noticed because they
    happen to hold the same number. That fires while a duplicate still agrees and goes
    silent the moment it stops — which is precisely when it has become a problem. A paper
    could carry `ror.point` at 0.95 and `ror.abstract` at 3.84 and nothing would say a word,
    because nothing in the results file recorded that the two were meant to be the same
    thing.

    `same_as` records it. It is a declaration rather than an inference because the question
    is about intent: `ror.point`, `ror.ci_low` and `ror.ci_high` share everything a
    heuristic could see and are supposed to differ. The limit is honest — this protects the
    pairs someone thought to declare — but a declared pair cannot drift in silence.
    """
    report = Report()
    declared = 0
    for key, value in results.values.items():
        if not value.same_as:
            continue
        declared += 1
        other = results.values.get(value.same_as)
        if other is None:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="same-as-unresolved",
                    message=f"{key} declares same_as {value.same_as!r}, which no analysis emits",
                    path=value.source,
                    hint="a declaration pointing at nothing checks nothing; fix the key or "
                    "remove the declaration",
                )
            )
            continue
        if value.value != other.value:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="declared-same-but-differs",
                    message=f"{key} is declared the same quantity as {value.same_as}, but they "
                    f"hold {value.value!r} and {other.value!r}",
                    path=value.source,
                    context=f"displays: {value.display} and {other.display}",
                    hint="emit the quantity once and quote the one key; two keys for one "
                    "number is how an abstract comes to disagree with its own results",
                )
            )
        elif value.display != other.display:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="declared-same-but-displayed-differently",
                    message=f"{key} and {value.same_as} are the same quantity but are written "
                    f"{value.display!r} and {other.display!r}",
                    path=value.source,
                    hint="pick one display, or round both with the same `digits`",
                )
            )
    return report.with_counts(declared_pairs=declared)
