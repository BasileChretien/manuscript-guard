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
from manuscript_guard.gates.design import PLANNED, REQUIRED, _plan_sections
from manuscript_guard.gates.revision import as_quoted

#: The plan's sections that belong to one paper and are not its methods: what it changed
#: from its own plan, and the results it promised.
_OWN = tuple(re.compile(rule) for rule in (dict((n, r) for n, r, _p in REQUIRED)["deviations"],
                                           PLANNED))  # fmt: skip
#: A heading's number, "2." or "2.1", and its marks of emphasis, which name no section.
_NUMBERED = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?")
#: How many words of each side a finding shows from where the two part.
SHOWN = 8


def models_compared(earlier: dict[str, Model], here: dict[str, Model]) -> list[tuple[str, str]]:
    """Each model both projects fitted under one key that was fitted otherwise, with what
    differs in words: its family and link, its outcome, the variables entered, how each was
    entered and its reference."""
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
        (as_then, ref_then), (as_now, ref_now) = entered_then[name], entered_now[name]
        if as_then != as_now:
            said.append(f"{name} is entered as {as_then} there and as {as_now} here")
        elif ref_then != ref_now:
            said.append(f"{name} has the reference {ref_then} there and {ref_now} here")
    return said


def _family(model: Model) -> str:
    engine = model.engine or {}
    return "/".join(str(engine[part]) for part in ("family", "link") if engine.get(part))


def _outcome(model: Model) -> str:
    variables = (model.outcome or {}).get("variables") or []
    return ", ".join(map(str, variables)) or str((model.outcome or {}).get("expression"))


def _entered(model: Model) -> dict[str, tuple[str, str | None]]:
    """Each variable the model enters, by name: how it is entered and its reference."""
    found: dict[str, tuple[str, str | None]] = {}
    for term in model.terms:
        for entered in term.get("entered") or ():
            name = ", ".join(map(str, entered.get("variables") or [entered.get("expression")]))
            found.setdefault(name, (str(entered.get("as")), entered.get("reference")))
    return found


def earlier_plan(folder: Path) -> str | None:
    """The earlier project's plan as it stood when its first results were written, or as
    the copy has it where it kept no frozen one."""
    frozen = folder / "design" / "plan.frozen.yaml"
    try:
        document = read_structured(frozen)
    except ContractError:
        document = None
    if isinstance(document, dict) and isinstance(document.get("plan"), str):
        return document["plan"]
    plan = folder / "design" / "plan.md"
    return plan.read_text(encoding="utf-8", errors="replace") if plan.is_file() else None


def sections_compared(then: str, now: str) -> list[tuple[str, str, str]]:
    """Each section both plans have under one heading whose words differ: its heading, and
    a few words of each side from where they part. Words are compared as a quotation of the
    manuscript is, without comments, emphasis or line breaks, and in either case."""
    earlier = _by_title(then)
    found = []
    for title, words in _by_title(now).items():
        if title not in earlier or earlier[title][1] == words[1]:
            continue
        parted = _parting(earlier[title][1], words[1])
        found.append((words[0], " ".join(earlier[title][1][parted:parted + SHOWN]),
                      " ".join(words[1][parted:parted + SHOWN])))  # fmt: skip
    return found


def _by_title(text: str) -> dict[str, tuple[str, list[str]]]:
    """Each section's heading as written and its words, by its heading folded."""
    found: dict[str, tuple[str, list[str]]] = {}
    for section in _plan_sections(text):
        title = as_quoted(section.title).strip()
        if not title or any(own.search(title) for own in _OWN):
            continue
        found.setdefault(folded_title(title), (title, _words(section.body)))
    return found


def _words(text: str) -> list[str]:
    """A section's words as two plans are compared by: G13's reading of a quotation, without
    comments, emphasis or line breaks, and in either case."""
    return as_quoted(text).casefold().split()


def folded_title(title: str) -> str:
    """A heading as one section of two plans is matched by: without its number, emphasis
    or case."""
    return _NUMBERED.sub("", as_quoted(title)).strip().casefold()


def _parting(a: list[str], b: list[str]) -> int:
    at = 0
    while at < min(len(a), len(b)) and a[at] == b[at]:
        at += 1
    return at
