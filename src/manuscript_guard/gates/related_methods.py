"""G8 — the methods of an earlier output of the same data, beside this paper's.

What two Methods sections mean is not for a gate. What both projects record as data is: the
models they fitted, read from their cards, and the sections of their plans that bear one
heading. A difference is said and never judged: a method may rightly change between two
papers, and the panel weighs whether the paper says so.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.models import Model
from manuscript_guard.gates.design import PLANNED, REQUIRED, _plan_sections, _read_plan
from manuscript_guard.gates.revision import as_quoted
from manuscript_guard.text.sections import subsections

#: The plan's sections that belong to one paper and are not its methods, with all they hold:
#: what it changed from its own plan, and the results it promised.
_OWN = tuple(re.compile(rule) for rule in (dict((n, r) for n, r, _p in REQUIRED)["deviations"],
                                           PLANNED))  # fmt: skip
#: A heading's number, "2." or "2.1", which names no section. A number with no point after
#: it is a word of the heading: "2019 cohort" is not "2020 cohort" (round 1 of #402).
_NUMBERED = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.|\d+(?:\.\d+)+)\s+")
#: How many words of each side a finding shows from where the two part.
SHOWN = 8


def models_compared(earlier: dict[str, Model], here: dict[str, Model]) -> list[tuple[str, str]]:
    """Each model both projects fitted under one key that was fitted otherwise, with what
    differs in words: its family and link, its outcome, the variables entered, and how
    each was entered, its expression and its reference."""
    found = []
    for key in sorted(set(earlier) & set(here)):
        said = _model_differences(earlier[key], here[key])
        if said:
            found.append((key, "; ".join(said)))
    return found


def _model_differences(then: Model, now: Model) -> list[str]:
    said = []
    if _family(then) != _family(now):
        said.append(f"its family is {_family(then) or 'not said'} there and "
                    f"{_family(now) or 'not said'} here")  # fmt: skip
    if _outcome(then) != _outcome(now):
        said.append(f"its outcome is {_outcome(then)} there and {_outcome(now)} here")
    entered_then, entered_now = _entered(then), _entered(now)
    for name in sorted(set(entered_then) - set(entered_now)):
        said.append(f"it enters {name} there and not here")
    for name in sorted(set(entered_now) - set(entered_then)):
        said.append(f"it enters {name} here and not there")
    for name in sorted(set(entered_then) & set(entered_now)):
        if entered_then[name] != entered_now[name]:
            said.append(_entered_otherwise(name, entered_then[name], entered_now[name]))
    return said


def _entered_otherwise(name: str, then: list[tuple], now: list[tuple]) -> str:
    """How one variable is entered otherwise, in the fewest words that say it."""
    if len(then) == len(now) == 1 and then[0][:2] == now[0][:2]:
        return f"{name} has the reference {then[0][2]} there and {now[0][2]} here"
    if len(then) == len(now) == 1 and then[0][0] == now[0][0]:
        return f"{name} is entered as {then[0][1]} there and as {now[0][1]} here"
    return (f"{name} is entered as {'; '.join(_described(e) for e in then)} there and as "
            f"{'; '.join(_described(e) for e in now)} here")  # fmt: skip


def _described(entered: tuple) -> str:
    expression, kind, reference = entered
    return f"{expression} ({kind}" + (f", reference {reference})" if reference else ")")


def _family(model: Model) -> str:
    engine = model.engine or {}
    return "/".join(str(engine[part]) for part in ("family", "link") if engine.get(part))


def _outcome(model: Model) -> str:
    """The outcome as the formula writes it: `I(score > 5)` and `I(score > 7)` are two."""
    outcome = model.outcome or {}
    return str(outcome.get("expression") or ", ".join(map(str, outcome.get("variables") or [])))


def _entered(model: Model) -> dict[str, list[tuple]]:
    """Every way the model enters each variable, by the variable: its expression, as what,
    and its reference. A variable entered twice (`age` and `I(age**2)`, or alone and in an
    interaction) keeps both (round 1 of #402)."""
    found: dict[str, list[tuple]] = {}
    for term in model.terms:
        for entered in term.get("entered") or ():
            name = ", ".join(map(str, entered.get("variables") or [entered.get("expression")]))
            found.setdefault(name, []).append(
                (str(entered.get("expression")), str(entered.get("as")), entered.get("reference"))
            )
    return {name: sorted(ways, key=repr) for name, ways in found.items()}


def earlier_plan(folder: Path) -> str | None:
    """The earlier project's plan as it stood when its first results were written, or as
    the copy has it where it kept no frozen one, read as G12 reads a plan: its line endings
    made `\\n` and a byte-order mark left out."""
    frozen = folder / "design" / "plan.frozen.yaml"
    try:
        document = read_structured(frozen)
    except ContractError:
        document = None
    if isinstance(document, dict) and isinstance(document.get("plan"), str):
        text = document["plan"].removeprefix(chr(0xFEFF))
        return text.replace("\r\n", "\n").replace("\r", "\n")
    plan = folder / "design" / "plan.md"
    return this_plan(plan) if plan.is_file() else None


def this_plan(path: Path) -> str:
    """A plan read as G12 reads it, so that one not in UTF-8 is read, not refused."""
    return _read_plan(path)[0]


def sections_compared(then: str, now: str) -> list[tuple[str, str, str, str]]:
    """Each section both plans have under one heading whose words differ: its heading as
    this plan writes it, the key it is matched by, and a few words of each side from where
    they part. Words are compared as a quotation of the manuscript is, without comments,
    emphasis or line breaks, and in either case."""
    earlier = _by_title(then)
    found = []
    for key, (title, words) in _by_title(now).items():
        if key not in earlier or earlier[key][1] == words:
            continue
        parted = _parting(earlier[key][1], words)
        found.append((title, key, " ".join(earlier[key][1][parted:parted + SHOWN]),
                      " ".join(words[parted:parted + SHOWN])))  # fmt: skip
    return found


def section_keys(text: str) -> set[str]:
    """The keys of a plan's sections that are compared."""
    return set(_by_title(text))


def _by_title(text: str) -> dict[str, tuple[str, list[str]]]:
    """Each section's heading as written and its words, by its heading folded with those
    above it: a `### Definition` under the Exposure is not the one under the Outcome. The
    plan's own Deviations and Planned results are left out with everything under them."""
    found: dict[str, tuple[str, list[str]]] = {}
    sections = _plan_sections(text)
    left_out: set[int] = set()
    above: list[tuple[int, str]] = []
    for index, section in enumerate(sections):
        while above and above[-1][0] >= section.level:
            above.pop()
        title = as_quoted(section.title).strip()
        above.append((section.level, title))
        if index in left_out:
            continue
        if any(own.search(title) for own in _OWN):
            left_out.update(range(index, index + len(subsections(sections, index))))
            continue
        if not title:
            continue
        written = " / ".join(written for _level, written in above)
        found.setdefault(section_key(written), (written, _words(section.body)))
    return found


def _words(text: str) -> list[str]:
    """A section's words as two plans are compared by: G13's reading of a quotation, without
    comments, emphasis or line breaks, and in either case."""
    return as_quoted(text).casefold().split()


def folded_title(title: str) -> str:
    """A heading as one section of two plans is matched by: without its number, emphasis
    or case."""
    return _NUMBERED.sub("", as_quoted(title)).strip().casefold()


def section_key(written: str) -> str:
    """How a section is named in `methods:`, its headings from the outermost parted by `/`,
    as a key: each heading folded."""
    return " / ".join(folded_title(part) for part in written.split("/"))


def _parting(a: list[str], b: list[str]) -> int:
    at = 0
    while at < min(len(a), len(b)) and a[at] == b[at]:
        at += 1
    return at
