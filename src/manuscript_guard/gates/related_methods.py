"""G8 — the methods of an earlier output of the same data, beside this paper's.

What two Methods sections mean is not for a gate. What both projects record as data is: the
models they fitted, read from their cards, the sections of their plans that bear one
heading, and the variables of their data dictionaries that bear one name. A difference is
said and never judged: a method may rightly change between two papers, and the panel weighs
whether the paper says so.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.dictionary import _BOUNDS as _BOUND_READERS
from manuscript_guard.contracts.dictionary import (
    Code,
    Dictionary,
    Standard,
    Variable,
    dictionary_path,
    load_dictionary,
)
from manuscript_guard.contracts.models import Model
from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.design import PLANNED, REQUIRED, _plan_sections, _read_plan
from manuscript_guard.gates.revision import as_quoted
from manuscript_guard.text.sections import subsections

#: The plan's sections that belong to one paper and are not its methods, with all they hold:
#: what it changed from its own plan, and the results it promised.
_OWN = tuple(re.compile(rule) for rule in (dict((n, r) for n, r, _p in REQUIRED)["deviations"],
                                           PLANNED))  # fmt: skip
#: A heading's number, "2.", "2.1" or "2", which names no section. A longer number with no
#: point after it is a word of the heading: "2019 cohort" is not "2020 cohort" (rounds 1
#: and 2 of #402).
_NUMBERED = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.|\d+(?:\.\d+)+|\d{1,2})\s+")
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
    emphasis or line breaks, and in either case. A heading that stands twice in either plan
    is not compared (`ambiguous_headings`)."""
    earlier, here = _by_title(then), _by_title(now)
    twice = earlier.twice | here.twice
    found = []
    for key, (title, words) in here.sections.items():
        if key in twice or key not in earlier.sections or earlier.sections[key][1] == words:
            continue
        then_words = earlier.sections[key][1]
        parted = _parting(then_words, words)
        found.append((title, key, " ".join(then_words[parted:parted + SHOWN]),
                      " ".join(words[parted:parted + SHOWN])))  # fmt: skip
    return found


def ambiguous_headings(then: str, now: str) -> list[str]:
    """The headings both plans have that stand twice in either, as this plan writes them.
    Which of the two in one plan answers which in the other is not guessed: a `###
    Definition` under the Exposure and one under the Outcome are each compared with
    nothing, and said (round 1 and the post-budget round of #402, where matching by the
    headings above needed the plan's title told from its first section, and could not)."""
    earlier, here = _by_title(then), _by_title(now)
    shared = set(earlier.sections) & set(here.sections)
    return sorted(here.sections[key][0] for key in shared & (earlier.twice | here.twice))


def section_keys(text: str) -> set[str]:
    """The keys of a plan's sections that can be compared: those that stand once."""
    read = _by_title(text)
    return set(read.sections) - read.twice


class _Read:
    def __init__(self) -> None:
        self.sections: dict[str, tuple[str, list[str]]] = {}
        self.twice: set[str] = set()


def _by_title(text: str) -> _Read:
    """Each section's heading as written and its words, by its heading folded, as G12 reads
    a plan's sections; and the folded headings that stand more than once. The plan's own
    Deviations and Planned results are left out with everything under them."""
    read = _Read()
    sections = _plan_sections(text)
    left_out: set[int] = set()
    for index, section in enumerate(sections):
        if index in left_out:
            continue
        title = as_quoted(section.title).strip()
        if any(own.search(title) for own in _OWN):
            left_out.update(range(index, index + len(subsections(sections, index))))
            continue
        if not title:
            continue
        key = folded_title(title)
        if key in read.sections:
            read.twice.add(key)
        read.sections.setdefault(key, (title, _words(section.body)))
    return read


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


# ----------------------------------------------------------------------- the data dictionary

#: What is said of a part a dictionary leaves out.
_NOT_GIVEN = "not given"
#: How many words before the end of the shorter of two texts the words shown start, where
#: one only adds to the other: "'start, in days' there and 'start, in days rounded' here"
#: rather than "'' there and 'rounded' here".
_BEFORE_THE_END = 3


@dataclass(frozen=True)
class Differs:
    """One part of a variable, or of the dictionary, recorded otherwise: what the part is,
    and each side as it reads."""

    part: str
    then: str
    now: str
    verb: str = "is"

    @property
    def said(self) -> str:
        return f"its {self.part} {self.verb} {self.then} there and {self.now} here"


def read_dictionaries(
    folder: Path, project: Project
) -> tuple[tuple[Dictionary, Dictionary] | None, str | None]:
    """The copy's data dictionary and this paper's, where both are kept and both read; or
    why one does not read. Where either project keeps none, there is nothing to compare and
    nothing to say."""
    if not (dictionary_path(folder).is_file() and dictionary_path(project).is_file()):
        return None, None
    (then, then_read), (now, _now_read) = load_dictionary(folder), load_dictionary(project)
    if then is not None and now is not None:
        return (then, now), None
    said = []
    if then is None:
        # The loader says "cannot be read: <the parser's lines>" of a file YAML cannot
        # parse: said once, every line kept on one (rounds 1 and 2 of #415).
        why = then_read.findings[0].message if then_read.findings else ""
        why = " ".join(why.removeprefix("cannot be read: ").split()) or "no reason is given"
        said.append(f"its copied data dictionary cannot be read ({why})")
    if now is None:
        said.append("this paper's data dictionary cannot be read (G12 says why)")
    return None, " and ".join(said)


def shown(differs: list[Differs]) -> tuple[str, str]:
    """Each side of what is recorded otherwise, as `related` lists it."""
    return ("; ".join(f"{d.part} {d.then}" for d in differs),
            "; ".join(f"{d.part} {d.now}" for d in differs))  # fmt: skip


def variables_compared(then: Dictionary, now: Dictionary) -> list[tuple[str, list[Differs]]]:
    """Each variable both dictionaries have under one name that is recorded otherwise, in
    this dictionary's order, with each part that differs: its definition, type, codes, unit,
    range, standard, and what it is derived from and how. A variable one of the two lacks is
    compared with nothing: a variable renamed since is two variables."""
    found = []
    for variable in now.variables:
        earlier = then.variable(variable.name)
        differs = _variable_differences(earlier, variable) if earlier is not None else []
        if differs:
            found.append((variable.name, differs))
    return found


def period_compared(then: Dictionary, now: Dictionary) -> Differs | None:
    """The study period, where the two dictionaries give other ones, or one gives none."""
    if then.study_period == now.study_period:
        return None
    return Differs("study period", _period(then.study_period), _period(now.study_period))


def _period(period: tuple[str, str] | None) -> str:
    return f"{period[0]} to {period[1]}" if period else _NOT_GIVEN


def _variable_differences(then: Variable, now: Variable) -> list[Differs]:
    found = []
    if _text_words(then.definition) != _text_words(now.definition):
        found.append(_reworded("definition", then.definition, now.definition))
    if then.type != now.type:
        found.append(Differs("type", then.type, now.type))
    found += _codes_compared(then, now)
    if _unit(then) != _unit(now):
        found.append(Differs("unit", _unit(then) or _NOT_GIVEN, _unit(now) or _NOT_GIVEN))
    # A date there and a datetime here of one written bound are no two bounds: each type's
    # reader only where both give the variable one type (round 2 of #415).
    read = _BOUND_READERS.get(now.type, str) if then.type == now.type else str
    if _bounds(then, read) != _bounds(now, read):
        found.append(Differs("range", _range(then), _range(now)))
    found += _standards_compared(then.standard, now.standard)
    if _inputs(then) != _inputs(now):
        found.append(Differs("inputs", _inputs(then), _inputs(now), verb="are"))
    if _text_words(then.derivation or "") != _text_words(now.derivation or ""):
        found.append(_reworded("derivation", then.derivation, now.derivation))
    return found


def _text_words(text: str) -> list[str]:
    """A dictionary's text as two are compared by: its words, in either case, line breaks
    aside. It is YAML and not Markdown, so a `*` or a backtick in it is read as written."""
    return text.casefold().split()


def _reworded(part: str, then: str | None, now: str | None) -> Differs:
    """A few words of each side from where they part, or from a little before where one
    only runs on past the other."""
    if then is None or now is None:
        shown = (f"'{' '.join(_text_words(text)[:SHOWN])}'" if text else _NOT_GIVEN
                 for text in (then, now))  # fmt: skip
        return Differs(part, *shown)
    a, b = _text_words(then), _text_words(now)
    start = min(_parting(a, b), max(0, min(len(a), len(b)) - _BEFORE_THE_END))
    return Differs(part, f"'{' '.join(a[start:start + SHOWN])}'",
                   f"'{' '.join(b[start:start + SHOWN])}'")  # fmt: skip


def _folded(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _codes_compared(then: Variable, now: Variable) -> list[Differs]:
    """Each code one side has and the other lacks, each code labelled otherwise, and an
    ordinal scale's codes in another order. A list of codes named and the same codes
    written out are the same codes."""
    there, here = _labels(then.values), _labels(now.values)
    found = []
    for code in [*there, *(c for c in here if c not in there)]:
        if _folded(there.get(code)) != _folded(here.get(code)):
            found.append(Differs(f"code {code}", there.get(code) or _NOT_GIVEN,
                                 here.get(code) or _NOT_GIVEN))  # fmt: skip
    if then.type == now.type == "ordinal":
        found += _order_compared(list(there), list(here))
    return found


def _order_compared(there: list[str], here: list[str]) -> list[Differs]:
    """An ordinal scale's codes both sides have, where they run in another order."""
    order_then = [code for code in there if code in here]
    order_now = [code for code in here if code in there]
    if order_then == order_now:
        return []
    return [Differs("order of codes", ", ".join(order_then), ", ".join(order_now))]


def _labels(codes: tuple[Code, ...]) -> dict[str, str]:
    return {code.code: code.label for code in codes}


def _unit(variable: Variable) -> str:
    """A unit as written, its case included: mg and Mg are two units."""
    return " ".join((variable.unit or "").split())


def _bounds(variable: Variable, read: Callable[[str], object]) -> tuple:
    """A range's bounds as numbers where they are, so that 110 and 110.0 are one bound,
    and otherwise by `read`: a date or a time read as the loader reads it, since YAML gives
    an unquoted timestamp in ISO form and a quoted one as typed, and `2015-01-01 10:00:00Z`
    and `2015-01-01T10:00:00+00:00` are one instant (round 1 of #415)."""
    return tuple(None if bound is None else float(bound) if _number(bound) else read(bound)
                 for bound in (variable.minimum, variable.maximum))  # fmt: skip


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _range(variable: Variable) -> str:
    low, high = variable.minimum, variable.maximum
    if low is not None and high is not None:
        return f"{low} to {high}"
    if low is not None:
        return f"from {low}"
    return f"up to {high}" if high is not None else _NOT_GIVEN


#: The parts of a standard compared one by one where both follow one system, and whether
#: each is read in either case: a term or a level is the same in capitals, a release or a
#: code is compared as written.
_STANDARD_PARTS = (("version", False), ("level", True), ("term", True), ("code", False))


def _standards_compared(then: Standard | None, now: Standard | None) -> list[Differs]:
    if then is None and now is None:
        return []
    if then is None or now is None or _folded(then.system) != _folded(now.system):
        return [Differs("standard", _standard(then), _standard(now))]
    found = []
    for part, folded in _STANDARD_PARTS:
        a, b = getattr(then, part), getattr(now, part)
        read = _folded if folded else (lambda text: " ".join((text or "").split()))
        if read(a) != read(b):
            found.append(Differs(f"{now.system} {part}", a or _NOT_GIVEN, b or _NOT_GIVEN))
    return found


def _standard(standard: Standard | None) -> str:
    if standard is None:
        return _NOT_GIVEN
    parts = (standard.system, standard.version, standard.level, standard.term)
    shown = " ".join(part for part in parts if part)
    return f"{shown} ({standard.code})" if standard.code else shown


def _inputs(variable: Variable) -> str:
    return ", ".join(sorted(variable.derived_from)) or "none"
