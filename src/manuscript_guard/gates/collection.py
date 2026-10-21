"""G12 — is what the study will collect what its plan needs, and no more?

A plan that sets out an analysis of data that do not exist yet has a second thing to settle
before they do: exactly what will be collected. `design/data_dictionary.yaml` says it, and
this holds it to the plan both ways. Every variable the plan names has an entry, with its
definition: a covariate the analysis adjusts for and nobody collects is found when the
data come in, which is too late. And every entry is there because something needs it: a
variable the plan names, an input of one, the variable that decides whether one is asked,
a reporting-checklist item, or a reason the author wrote. Data nobody needs are still data
to collect, to clean and to protect.

The plan names a variable by writing it in backticks, exactly as the dictionary names it,
`age`, anywhere outside its Deviations section (Basile, 2026-10-21). A name in backticks
that the dictionary does not have is reported where it reads as a variable's: letters,
digits and underscores. Code is written otherwise, `glm()` or `stats::glm`, and a result's
key has a dot. The Deviations are not read, since what they name was dropped or changed.

Everything here warns, at every stage, as the rest of G12 does. A dictionary that does not
read at all is `dictionary-invalid`, said by the loader, and fails.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.dictionary import CODED, DICTIONARY, Dictionary, Variable
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.design import PLANNED, REQUIRED
from manuscript_guard.text.blocks import find_headings
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import mask

GATE = "G12"
#: What reads as a variable's name in the plan: letters, digits and underscores, from a
#: letter. A dotted name is a variable only where the dictionary has it.
VARIABLE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
#: Words in backticks that are values, not variables.
LITERALS = frozenset({"NA", "NULL", "TRUE", "FALSE", "None", "True", "False", "NaN", "Inf"})
_DEVIATIONS = dict((name, rule) for name, rule, _purpose in REQUIRED)["deviations"]


@dataclass(frozen=True)
class Named:
    """A name the plan gives in backticks, and the line of its first mention."""

    name: str
    line: int


def is_deviations(title: str) -> bool:
    """Whether a heading heads the plan's Deviations. "Planned results and amendments" is the
    list of planned results, since its planned results come first; "Changes to the planned
    results" is the Deviations (G12 reads the list the same way)."""
    changed = re.search(_DEVIATIONS, title)
    listed = re.search(PLANNED, title)
    return bool(changed) and not (listed and listed.start() < changed.start())


def variables_named(text: str, names: Collection[str]) -> tuple[list[Named], list[Named]]:
    """What the plan names, read against the dictionary's names: the dictionary's variables
    it names, and the names it gives that read as a variable's and that the dictionary does
    not have. Each once, at its first mention, in the plan's order.

    Every code span of the plan is read but those in a Deviations section and the sections
    under it, and those that masking hides: a fence, a comment, front matter."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    known = set(names)
    left_out = _deviations(text)
    found: dict[str, dict[str, Named]] = {"used": {}, "undefined": {}}
    for start, end in code_spans(mask(text)):
        if any(low <= start < high for low, high in left_out):
            continue
        said = text[start:end].strip("`").strip()
        kind = _reads_as(said, known)
        if kind is not None:
            _first(found[kind], Named(said, text.count("\n", 0, start) + 1))
    return list(found["used"].values()), list(found["undefined"].values())


def _reads_as(said: str, known: Collection[str]) -> str | None:
    """What a code span of the plan is: a variable the dictionary has, a name that reads as a
    variable's and that it does not have, or neither."""
    if said in known:
        return "used"
    if VARIABLE.fullmatch(said) and said not in LITERALS:
        return "undefined"
    return None


def _first(found: dict[str, Named], named: Named) -> None:
    """Keep a name at its first mention."""
    found.setdefault(named.name, named)


def _deviations(text: str) -> list[tuple[int, int]]:
    """Where each Deviations section is, from its heading to the next heading at its level
    or above."""
    headings = find_headings(text)
    found = []
    for index, heading in enumerate(headings):
        if not is_deviations(heading.title):
            continue
        end = next((later.start for later in headings[index + 1 :]
                    if later.level <= heading.level), len(text))  # fmt: skip
        found.append((heading.start, end))
    return found


def needed(dictionary: Dictionary, named: Collection[str]) -> set[str]:
    """The variables a plan that names these needs: those it names, and, again and again,
    the inputs of each and the variable that decides whether each is asked."""
    wanted = {name for name in named if dictionary.variable(name) is not None}
    waiting = list(wanted)
    while waiting:
        variable = dictionary.variable(waiting.pop())
        further = list(variable.derived_from)
        if variable.applies_if is not None:
            further.append(variable.applies_if.variable)
        for name in further:
            if name not in wanted and dictionary.variable(name) is not None:
                wanted.add(name)
                waiting.append(name)
    return wanted


def check_collection(
    plan: Path, text: str | None, dictionary: Dictionary, checklists: dict[str, set[str] | None]
) -> Report:
    """The dictionary against the plan, where there is one, and against itself.

    `checklists` holds, for each guideline an entry names, the item ids of its checklist,
    or None where the project has none to read."""
    report = _entries(dictionary).merge(_reporting(dictionary, checklists))
    if text is None:
        return report
    used, undefined = variables_named(text, dictionary.names)
    findings = [_undefined(plan, one, dictionary) for one in undefined]
    wanted = needed(dictionary, [one.name for one in used])
    findings += [
        _unused(dictionary.path, variable)
        for variable in dictionary.variables
        if variable.name not in wanted and not variable.reporting and not variable.reason
    ]
    counts = {"plan_variables": len(used) + len(undefined)}
    return report.merge(Report(tuple(findings), counts))


def _undefined(plan: Path, one: Named, dictionary: Dictionary) -> Finding:
    like = [name for name in dictionary.names if name.casefold() == one.name.casefold()]
    hint = (f"the dictionary has `{like[0]}`; write the name as it does" if like else
            f"add an entry for `{one.name}` to {DICTIONARY.as_posix()}, with its definition, "
            f"type and codes; where it is code and not a variable, write `{one.name}()` or "
            "leave out the backticks")  # fmt: skip
    return Finding(
        gate=GATE,
        code="plan-variable-undefined",
        severity=WARN,
        message=f"the plan names `{one.name}`, which {DICTIONARY.as_posix()} does not define",
        path=plan,
        line=one.line,
        hint=hint,
    )


def _unused(path: Path, variable: Variable) -> Finding:
    return Finding(
        gate=GATE,
        code="dictionary-entry-unused",
        severity=WARN,
        message=f"{variable.name} is in the dictionary and nothing needs it: the plan does not "
        "name it, no variable the plan names is derived from it or asked by it, and no "
        "reporting item asks for it",
        path=path,
        line=variable.line,
        hint=f"name `{variable.name}` in the plan where the analysis uses it, give the "
        "reporting item that needs it (`reporting:`) or why it is collected (`reason:`), or "
        "leave it out: data nobody needs are still data to collect and to protect",
    )


def _entries(dictionary: Dictionary) -> Report:
    """What an entry leaves unsaid, whatever the plan: codes not decided, a derivation
    without its inputs or inputs without it, an input the dictionary does not have, a
    variable derived in the end from itself."""
    findings = []
    for variable in dictionary.variables:
        findings += [
            Finding(gate=GATE, code=code, severity=WARN, message=said, path=dictionary.path,
                    line=variable.line, hint=hint)
            for code, said, hint in _gaps(variable, dictionary)
        ]  # fmt: skip
    for cycle in _cycles(dictionary):
        findings.append(
            Finding(
                gate=GATE,
                code="dictionary-derivation-cycle",
                severity=WARN,
                message="each is derived from the next: " + " from ".join([*cycle, cycle[0]]),
                path=dictionary.path,
                line=dictionary.variable(cycle[0]).line,
                hint="a derived variable is computed from variables that are recorded; say "
                "which of these is recorded, and leave derived_from out of its entry",
            )
        )
    return Report(tuple(findings))


def _gaps(variable: Variable, dictionary: Dictionary) -> list[tuple[str, str, str]]:
    name = variable.name
    found = []
    if variable.type in CODED and not variable.values:
        found.append(("dictionary-codes-undecided",
                      f"{name} is {variable.type} and its codes are not given",
                      "list them under values, or name a code_list: the form, the export and "
                      "the data checks need them"))  # fmt: skip
    if variable.derived_from and not variable.derivation:
        found.append(("dictionary-derivation-unsaid",
                      f"{name} names the variables it is derived from and not how",
                      "say how under derivation, as the analysis will compute it"))  # fmt: skip
    if variable.derivation and not variable.derived_from:
        found.append(("dictionary-derivation-unsaid",
                      f"{name} says how it is derived and not from which variables",
                      "name them under derived_from, so that each is collected"))  # fmt: skip
    for missing in (n for n in variable.derived_from if dictionary.variable(n) is None):
        found.append(("dictionary-input-undefined",
                      f"{name} is derived from {missing}, which the dictionary does not "
                      "define, so nothing collects it",
                      f"add an entry for {missing}, or correct derived_from"))  # fmt: skip
    return found


def _cycles(dictionary: Dictionary) -> list[list[str]]:
    """Each cycle of derivations once, from its variable that comes first in the dictionary.

    A depth-first walk of the inputs: a cycle is an input already on the path walked."""
    found: list[list[str]] = []
    seen: set[frozenset[str]] = set()
    done: set[str] = set()

    def walk(path: list[str]) -> None:
        for name in dictionary.variable(path[-1]).derived_from:
            if dictionary.variable(name) is None:
                continue
            if name in path:
                cycle = path[path.index(name):]
                if frozenset(cycle) not in seen:
                    seen.add(frozenset(cycle))
                    first = min(cycle, key=dictionary.names.index)
                    at = cycle.index(first)
                    found.append(cycle[at:] + cycle[:at])
            elif name not in done:
                walk([*path, name])
        done.add(path[-1])

    for variable in dictionary.variables:
        if variable.name not in done:
            walk([variable.name])
    return found


def _reporting(dictionary: Dictionary, checklists: dict[str, set[str] | None]) -> Report:
    """Each reporting item an entry names, looked for in its guideline's checklist."""
    findings = []
    for variable in dictionary.variables:
        for guideline, items in variable.reporting:
            known = checklists.get(guideline)
            if known is None:
                findings.append(Finding(
                    gate=GATE, code="dictionary-reporting-unchecked", severity=INFO,
                    message=f"{variable.name} is said to be needed by {guideline}, of which "
                    "the project holds no checklist, so its items were not looked for",
                    path=dictionary.path, line=variable.line,
                    hint="the reporting-checklist skill retrieves it"))  # fmt: skip
                continue
            for item in (one for one in items if one not in known):
                findings.append(Finding(
                    gate=GATE, code="dictionary-reporting-item-unknown", severity=WARN,
                    message=f"{variable.name} is said to be needed by {guideline} item {item}, "
                    f"which the {guideline} checklist does not have",
                    path=dictionary.path, line=variable.line,
                    hint="give the item as the checklist numbers it"))  # fmt: skip
    return Report(tuple(findings))


__all__ = [
    "LITERALS",
    "VARIABLE",
    "Named",
    "check_collection",
    "is_deviations",
    "needed",
    "variables_named",
]
