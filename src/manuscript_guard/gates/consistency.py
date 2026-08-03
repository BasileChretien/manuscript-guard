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

    return report.with_counts(value_collisions=collisions)
