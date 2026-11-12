"""G15 — a summary is the summary its variable calls for: a mean and its SD of skewed data.

A model is the model its variables call for (`gates/models.py`); so is a summary. A mean
names the variable of the data dictionary it is of (`em.value(..., variable="crp")`), and
the dictionary gives the variable's floor, its `range.min`. Each SD of that mean, a value
with `spread="sd"` and `of` the mean's key, is then held to it: where the mean is less than
twice the SD above the floor, the data are skewed, and the mean (SD) describes them badly:
Altman and Bland's rule (BMJ 1996;313:1200) for a floor of 0, the Cochrane Handbook's check
(section 10.5.3) for another, and the message cites the one applied (`stats/skew.py`). That
is `mean-sd-skewed`, a warning
at every stage, since a skewed variable may still be reported so for a reason: the trial's
registration, a meta-analysis that will pool means. `skewed_ok="<reason>"` on the mean says
so, and stands the warning down; only a sentence does, not a blank.

What is not read: a standard error (`spread="se"`), whose SD needs the n the value does not
carry; a mean whose variable has no floor in the dictionary that is a number, a date's
"20200101" being text; and a project with no
dictionary, or one that does not read, which G12 reports. A `variable` the dictionary has no
entry for is G16's `not-in-dictionary` (`gates/data_quality.py`), as is any variable the
analysis names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from manuscript_guard.contracts.dictionary import load_dictionary
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.stats import skew

GATE = "G15"
CODE = "mean-sd-skewed"
#: The spreads held to a floor: an SD. An SE gives the SD only with the n.
READ = frozenset({"sd"})


@dataclass(frozen=True)
class Held:
    """A mean and an SD of it held to the floor of the mean's variable, and whether they
    are skewed with no reason given."""

    mean: Value
    sd: Value
    floor: object
    warned: bool


def stands_down(reason: object) -> bool:
    """Whether `skewed_ok` stands the warning down: a sentence, not a blank, a number or a
    list."""
    return isinstance(reason, str) and bool(reason.strip())


def floor(minimum: object) -> int | float | None:
    """A dictionary's `range.min` as a floor: a number, and not a truth value. A date's,
    "20200101", is text and no floor (round 1 of #660)."""
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)):
        return None
    return minimum


def held(values: Mapping[str, Value], floor_of: Callable[[str], object]) -> list[Held]:
    """Each SD of a mean that names its variable, against the floor `floor_of` gives the
    variable (None where it has none), in the order of the SDs' keys."""
    out = []
    for value in sorted(values.values(), key=lambda value: value.key):
        if value.spread not in READ or not value.of:
            continue
        mean = values.get(value.of)
        if mean is None or not mean.variable:
            continue
        floor = floor_of(mean.variable)
        verdict = None if floor is None else skew.skewed(mean.value, value.value, floor)
        if verdict is None:
            continue
        out.append(Held(mean, value, floor, verdict and not stands_down(mean.skewed_ok)))
    return out


def check_summaries(project: Project, results: Results) -> Report:
    """Each mean that names its variable, and each SD of it, against the variable's floor."""
    if not any(value.variable for value in results.values.values()):
        return Report()
    dictionary, _report = load_dictionary(project)
    if dictionary is None:
        return Report()

    def floor_of(name: str) -> object:
        entry = dictionary.variable(name)
        return None if entry is None else floor(entry.minimum)

    found = held(results.values, floor_of)
    findings = tuple(_finding(one) for one in found if one.warned)
    return Report(findings, {"means_held_to_a_floor": len(found)})


def _finding(one: Held) -> Finding:
    mean, sd, floor = one.mean, one.sd, str(one.floor)
    return Finding(
        gate=GATE,
        code=CODE,
        severity=WARN,
        message=f"{mean.key} ({mean.variable}, floor {floor} in the data dictionary) and its "
        f"SD {sd.key}: {skew.said(mean.display, sd.display, floor)}",
        path=mean.source,
        hint="report a median and an interquartile range instead, or a transformation; or, "
        "where the mean (SD) is wanted all the same, give the reason on the mean with "
        f'skewed_ok="..." in em.value("{mean.key}", ...)',
    )
