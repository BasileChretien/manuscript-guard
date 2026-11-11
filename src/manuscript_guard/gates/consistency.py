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

Two keys holding the same value are not shown by that to be one quantity. The results file
records no more of a key than its value, display, unit and the script that wrote it, and none
of these tells one quantity under two names from two that agree: a count of 2 beside a
median ratio of 2.00, or one line of a loop writing 0.00 for two subgroups. So a value held
by two keys is a warning where they are written alike and a note where they are written two
ways; only a pair the author declared one quantity (`same_as`) fails when it disagrees.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Shown, Value, shown_in
from manuscript_guard.findings import INFO, WARN, Finding, Report

GATE = "G8"


def check_consistency(results: Results) -> Report:
    report = Report()
    # Keyed on the value AND its unit. A count of 56 sources and a share of 56.0% are not
    # the same quantity, and before this they collided: the check saw one number written two
    # ways and failed the build, which left the author no fix except to distort the paper
    # until the arithmetic coincidence went away. Two keys are candidates for being the same
    # quantity only if they measure the same kind of thing, and the unit is what says so.
    #
    # The cost is real and worth naming: a percentage emitted once with unit="%" and once
    # with the unit forgotten no longer collides. That is a narrower miss than failing on
    # coincidence, and `same_as` exists for the author who wants two keys held together
    # regardless.
    #
    # At nought and one a value written whole and one written with decimals are two kinds as
    # well: a count of none, "0", beside an interval's bound clamped at nought, "0.00", or a
    # count of one beside a share at one, failed a study's build as one quantity written two
    # ways (the athlete-leakage study, 2026-11-06). The kind is read from the display, not from
    # the number's type, which follows how it was serialised: R writes a double 0 as `0`. The
    # cost, at those three values only: one quantity written "1" in one place and "1.0" in
    # another is no longer said, and `same_as` holds such a pair. Elsewhere the two kinds stay
    # together, so that a count emitted again with decimals is still said.
    #
    # Written two ways, the pair is a note and fails nothing. It failed at drafting, and two
    # rebuilds of real papers showed what that cost (2026-11-11). In one (arXiv 2409.10841)
    # a count of two conditions, "2", and a median ratio of 2.00, and a share at "0.0" and a
    # smallest difference at "0.00", were taken for one quantity, and the hint said to emit
    # them once, which would have made the paper wrong. In the other (PsyArXiv d8hkq_v1,
    # APA style) one correlation was printed ".47" in the text and "0.47" beside its
    # interval, under two keys as the results-binding skill says to emit a second display,
    # and that failed. Nothing the file records tells these from one quantity emitted twice
    # by mistake: not the script, which writes both, nor the line, since one line of a loop
    # writes 0.00 for two subgroups. A pair the author ties with `same_as` is held by
    # `_check_declared_pairs` instead, and is not said here (the author's decision on #628).
    by_value: dict[tuple[str, str | None, str | None], list[str]] = defaultdict(list)

    for key, value in results.values.items():
        if not value.quoted:
            continue
        if isinstance(value.value, (int, float)) and not isinstance(value.value, bool):
            number = float(value.value)
            kind = _kind(value.display) if number in (0.0, 1.0, -1.0) else None
            by_value[(f"{number:.12g}", value.unit, kind)].append(key)

    tied = _declared_together(results)
    collisions = 0
    for (literal, _unit, kind), keys in sorted(by_value.items(),
                                               key=lambda kv: (kv[0][0], kv[0][2] or "")):
        if len(keys) < 2:
            continue
        collisions += 1
        if len({tied(k) for k in keys}) == 1:
            continue
        displays = {results.values[k].display for k in keys}
        same_display = len(displays) == 1
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="duplicate-quantity" if same_display else "divergent-display",
                severity=WARN if same_display else INFO,
                message=(
                    f"{len(keys)} quoted keys hold the value {literal}"
                    + (f", written {kind}" if kind else "") + ": " + ", ".join(sorted(keys))
                ),
                path=results.values[keys[0]].source,
                context="displays: " + ", ".join(sorted(displays)),
                hint=(
                    "if these are the same quantity, emit it once and reference the one key; "
                    "if they are genuinely different quantities that happen to coincide, "
                    "nothing needs to change"
                    if same_display
                    else "a note: two keys holding one value are not shown by that to be one "
                    "quantity. Two quantities that happen to agree need nothing, and a `unit` "
                    "on each key keeps them apart. One quantity printed two ways on purpose, a "
                    "coarser rounding or a form without the leading zero: declare the second "
                    "`same_as` the first, and G8 holds the two together. One quantity emitted "
                    "twice by mistake: emit it once and quote the one key"
                ),
            )
        )

    report = report.merge(_check_declared_pairs(results))
    report = report.merge(_families(results))
    return report.with_counts(value_collisions=collisions)


def _families(results: Results) -> Report:
    """A family of more than one p value is corrected for multiple comparisons, or says why
    not.

    Families are declared, never guessed: a p value says which it is one of (`family`), and
    the analysis declares the correction (`correction()`), "none" with its reason. A family
    with more than one p value and no declaration is a warning: the paper reports several
    tests and does not say how their chance findings are accounted for.
    """
    report = Report()
    members: dict[str, list[str]] = defaultdict(list)
    for key, value in results.values.items():
        if value.family and value.of and not value.over:
            members[value.family].append(key)
    for family, keys in sorted(members.items()):
        if len(keys) < 2 or family in results.corrections:
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="family-uncorrected",
                severity=WARN,
                message=f"the {family!r} family holds {len(keys)} p values and the analysis "
                f"declares no correction for it: {', '.join(sorted(keys))}",
                path=results.values[keys[0]].source,
                hint=f'declare it: em.correction("{family}", "holm"), or "none" with the '
                "reason",
            )
        )
    return report


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

    A declared pair may be printed two ways (the author's decision on #628): APA's ".47" in
    the text beside "0.47" with its interval, or a coarser rounding in the abstract. The two
    still hold one value, exactly, as before: two displays of one value, not two values. The
    displays may differ only in form: a leading zero, trailing zeros, one a rounding of the
    other. A pair whose displays differ otherwise, by a unit one of them lacks or a
    comparator, still fails.
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
        elif value.display != other.display and not _same_form(value, other):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="declared-same-but-displayed-differently",
                    message=f"{key} and {value.same_as} are the same quantity but are written "
                    f"{value.display!r} and {other.display!r}",
                    path=value.source,
                    hint="two displays of one quantity may differ by a leading zero, trailing "
                    "zeros or a rounding, and by nothing else: pick one display, or print the "
                    "unit in both or in neither",
                )
            )
    return report.with_counts(declared_pairs=declared)


def _declared_together(results: Results) -> Callable[[str], str]:
    """Which keys `same_as` ties together, as a function from a key to one key standing for
    all those tied to it, either way and through a chain."""
    parent: dict[str, str] = {}

    def root(key: str) -> str:
        while parent.get(key, key) != key:
            key = parent[key]
        return key

    for key, value in results.values.items():
        if value.same_as and value.same_as in results.values:
            first, second = root(key), root(value.same_as)
            if first != second:
                parent[first] = second
    return root


def _numbers(value: Value, other: Value) -> tuple[Shown, Shown] | None:
    """What the two displays state, where both values are numbers and both displays state a
    number without a comparator; None otherwise."""
    if not all(isinstance(v.value, (int, float)) and not isinstance(v.value, bool)
               for v in (value, other)):
        return None
    shown = (shown_in(value.display), shown_in(other.display))
    if shown[0] is None or shown[1] is None or shown[0].compare or shown[1].compare:
        return None
    return shown[0], shown[1]


def _same_form(value: Value, other: Value) -> bool:
    """Whether two displays of one value differ only in form: by a leading zero, trailing
    zeros, or as one a rounding of the other ("0.47", ".47", "0.470", "0.5"), with the same
    unit text."""
    shown = _numbers(value, other)
    if shown is None or shown[0].unit != shown[1].unit:
        return False
    finer, coarser = sorted(shown, key=lambda s: s.half_unit)
    return abs(finer.number - coarser.number) <= _within(coarser, finer.number)


def _within(shown: Shown, number: object) -> float:
    """How far a number may lie from what a display states and still be rounded to it: half
    a unit in its last place, with the slack `_check_display_matches` gives."""
    return shown.half_unit + abs(float(number)) * 1e-9


def _kind(display: str) -> str:
    """How a value at nought or one is written: "whole", with no decimal point ("0", "1"), or
    "with decimals" ("0.00", "1.0"), whatever type its number came in as."""
    return "with decimals" if "." in str(display) else "whole"
