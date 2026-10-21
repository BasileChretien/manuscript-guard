"""The data dictionary: each variable the study collects or reads, what it is and how it is coded.

`design/data_dictionary.yaml` is written at the design stage, from the analysis plan, before
the data are collected or read. One file serves three readers: G12 holds it to the plan (a
variable the plan names has an entry, and an entry is there for a reason), the data-quality
checks hold the data to it, and the export hands it to whoever builds the form.

This module reads it. The schema says the shape. What the schema cannot say is checked
here: names and ids given once, each reference to a form, a list of codes, an instrument, a
dataset or another variable resolved, codes that suit their type, bounds that are what
their type reads. A dictionary that fails either is `dictionary-invalid`, which fails at
every stage, as a malformed contract does: a check that read another variable's codes, or
an export that wrote them, would be worse than none. What is a gap in the plan rather than a
fault of the file, a categorical variable whose codes are not decided yet, or a derived
variable whose inputs are not in the dictionary, is G12's to say, and it warns.

A value is compared as text: `1` and `"1"` are one code. YAML reads some values as
something else before anything here sees them, `010` as the number 8, `8:30` as 510 and an
unquoted `No` as false, and each of those is refused with the words to write instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import ContractError, _plain, load_schema, read_text
from manuscript_guard.findings import Finding, Report

DICTIONARY = Path("design") / "data_dictionary.yaml"
SCHEMA = "data-dictionary"
GATE = "G12"
INVALID = "dictionary-invalid"

#: The types whose values are codes, those that are numbers, and those that are times.
CODED = ("binary", "categorical", "ordinal")
NUMERIC = ("continuous", "count")
TEMPORAL = ("date", "datetime", "time")
#: The types a pattern is matched against.
PATTERNED = ("text", "identifier")

_HINT = "see the data-dictionary schema, which says what each entry holds"


@dataclass(frozen=True)
class Code:
    """One allowed value and what it means, its code as text."""

    code: str
    label: str


@dataclass(frozen=True)
class Condition:
    """Where a variable is recorded: another coded variable holds one of these codes."""

    variable: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class Standard:
    """A published definition the variable follows."""

    system: str
    term: str
    version: str | None = None
    level: str | None = None
    code: str | None = None


@dataclass(frozen=True)
class Variable:
    name: str
    label: str
    definition: str
    type: str
    line: int | None = None
    question: str | None = None
    unit: str | None = None
    values: tuple[Code, ...] = ()
    code_list: str | None = None
    minimum: float | str | None = None
    maximum: float | str | None = None
    missing: tuple[Code, ...] = ()
    required: bool = False
    applies_if: Condition | None = None
    form: str | None = None
    timing: str | None = None
    recorded_by: str | None = None
    source: str | None = None
    dataset: str | None = None
    derived_from: tuple[str, ...] = ()
    derivation: str | None = None
    instrument: str | None = None
    item: str | None = None
    standard: Standard | None = None
    reporting: tuple[tuple[str, tuple[str, ...]], ...] = ()
    reason: str | None = None
    pattern: str | None = None
    within_study_period: bool = False

    @property
    def derived(self) -> bool:
        """Computed from other variables rather than recorded."""
        return bool(self.derived_from or self.derivation)


@dataclass(frozen=True)
class Form:
    id: str
    label: str
    timing: str | None = None
    recorded_by: str | None = None


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    licence: str
    version: str | None = None
    citation: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class Dataset:
    id: str
    label: str
    source: str | None = None


@dataclass(frozen=True)
class Rule:
    """What must hold across variables or rows: one of `order`, `unique` or `computed`."""

    id: str
    says: str
    order: tuple[str, ...] = ()
    unique: tuple[str, ...] = ()
    computed: bool = False


@dataclass(frozen=True)
class Dictionary:
    path: Path
    variables: tuple[Variable, ...]
    title: str | None = None
    study_period: tuple[str, str] | None = None
    datasets: tuple[Dataset, ...] = ()
    forms: tuple[Form, ...] = ()
    instruments: tuple[Instrument, ...] = ()
    code_lists: tuple[tuple[str, tuple[Code, ...]], ...] = ()
    rules: tuple[Rule, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(variable.name for variable in self.variables)

    def variable(self, name: str) -> Variable | None:
        return next((v for v in self.variables if v.name == name), None)


def dictionary_path(project: Any) -> Path:
    """Where a project's dictionary is: `project` is a Project or its root folder. (Not
    `getattr(project, "root")`: a path has a `root` too, its drive's.)"""
    root = Path(project) if isinstance(project, (str, Path)) else project.root
    return root / DICTIONARY


def load_dictionary(project: Any) -> tuple[Dictionary | None, Report]:
    """The project's dictionary, and what is wrong with the file.

    `(None, Report())` where there is none: a dictionary is written where the data are
    planned, and a project without one is not asked for it. `(None, report)` where it
    cannot be read or is invalid, the report holding one `dictionary-invalid` for each
    fault, placed at its line.
    """
    path = dictionary_path(project)
    if not path.is_file():
        return None, Report()
    try:
        text = read_text(path)
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        document = _plain(yaml.safe_load(text))
    except (ContractError, yaml.YAMLError, ValueError, RecursionError) as exc:
        # A date YAML cannot make, 2026-02-30, is a ValueError from the constructor.
        return None, _invalid(path, [(f"cannot be read: {exc}", None)])
    misread = _misread(root)
    problems = misread + _schema_problems(document, root, misread)
    problems += _raw_faults(document, root) if not problems else []
    if problems:
        return None, _invalid(path, problems)
    dictionary = _build(path, document, root)
    problems = _problems(dictionary, root)
    if problems:
        return None, _invalid(path, problems)
    return dictionary, Report(counts={"dictionary_variables": len(dictionary.variables)})


def _invalid(path: Path, problems: list[tuple[str, int | None]]) -> Report:
    return Report(
        tuple(
            Finding(gate=GATE, code=INVALID, message=message, path=path, line=line, hint=_HINT)
            for message, line in problems
        )
    )


# -- what YAML read as something else ----------------------------------------------------

_INT = "tag:yaml.org,2002:int"
_FLOAT = "tag:yaml.org,2002:float"
_BOOL = "tag:yaml.org,2002:bool"
#: A number YAML reads as the number it looks like.
_AS_WRITTEN = {
    _INT: re.compile(r"[-+]?(?:0|[1-9][0-9]*)"),
    _FLOAT: re.compile(r"[-+]?[0-9]*\.[0-9]*(?:[eE][-+]?[0-9]+)?"),
}
#: The keys whose value is a code, compared as text, where a sign YAML drops is a misreading
#: too: a code `+1` would be "1", and `-0` "0". A bound `+3` is the number 3 (round 2 of #382).
_CODES = frozenset({"code", "item", "in"})
_CODE_AS_WRITTEN = re.compile(r"0|-?[1-9][0-9]*")
#: The keys whose value is true or false, where `yes` means what it says.
_YES_OR_NO = frozenset({"required", "within_study_period", "computed"})


def _misread(root: yaml.Node | None) -> list[tuple[str, int | None]]:
    """Each plain value YAML turned into a number other than the one written, `010` (8),
    `8:30` (510), `1_000` (1000), or into true or false from a word other than true or
    false, `No`, `off`, where the value is not a yes or a no; and each key given twice in
    one mapping, of which YAML keeps the last and says nothing.

    A code `010` compared with the data's "010" would never match, and a time bound of 510
    is no time at all. Written in quotes, each is the text it looks like. A code list given
    twice under one name is read as the second, and a variable naming it gets its codes.
    """
    found = []
    for key, node in _scalars(root, None):
        if node.style is not None:
            continue
        text = node.value
        line = node.start_mark.line + 1
        written = _CODE_AS_WRITTEN if key in _CODES and node.tag == _INT else \
            _AS_WRITTEN.get(node.tag)  # fmt: skip
        if written is not None and not written.fullmatch(text):
            read = yaml.safe_load(text)
            found.append((f"{text} is read by YAML as the number {read!r}; write it in "
                          f"quotes, '{text}', where it is a code, a time or an identifier, "
                          f"and as plain digits where it is a number", line))  # fmt: skip
        elif node.tag == _BOOL and text.lower() not in ("true", "false") and \
                key not in _YES_OR_NO:  # fmt: skip
            found.append((f"{text} is read by YAML as {yaml.safe_load(text)!r}; write it in "
                          f"quotes, '{text}', where it is a word or a code", line))  # fmt: skip
    return _twice(root, []) + found


def _scalars(node: yaml.Node | None, key: str | None):
    """Each scalar value, with the key it is the value of, or the key of the list it is in."""
    if isinstance(node, yaml.ScalarNode):
        yield key, node
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _scalars(item, key)
    elif isinstance(node, yaml.MappingNode):
        for name, value in node.value:
            yield from _scalars(value, name.value if isinstance(name, yaml.ScalarNode) else None)


def _twice(node: yaml.Node | None, where: list) -> list[tuple[str, int | None]]:
    """Each key given a second time in one mapping, at the second."""
    found = []
    if isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            found += _twice(item, where + [index])
    elif isinstance(node, yaml.MappingNode):
        seen = set()
        shown = "/".join(str(part) for part in where) or "the file"
        for name, value in node.value:
            said = name.value if isinstance(name, yaml.ScalarNode) else None
            if said in seen and said != "<<":
                found.append((f"{said} is given twice in {shown}; YAML reads the second and "
                              f"drops the first", name.start_mark.line + 1))  # fmt: skip
            seen.add(said)
            found += _twice(value, where + [said])
    return found


def _line(root: yaml.Node | None, where: list) -> int | None:
    """The line of the value at `where`, or of the deepest part of it that is there: of its
    key, where it is the value of one, so that a list under a name is placed at the name."""
    node, line = root, None
    for part in where:
        if isinstance(node, yaml.MappingNode):
            pair = next(((k, v) for k, v in node.value if k.value == str(part)), None)
            node, at = (pair[1], pair[0]) if pair else (None, None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            node = node.value[part] if part < len(node.value) else None
            at = node
        else:
            node = None
        if node is None:
            break
        line = at.start_mark.line + 1
    return line if line is not None else (root.start_mark.line + 1 if root else None)


def _schema_problems(
    document: Any, root: yaml.Node | None, misread: list[tuple[str, int | None]]
) -> list[tuple[str, int | None]]:
    """The schema's faults, each at its line. One on a line already said to be misread is
    left out: it is the same fault, said less usefully."""
    said = {line for _message, line in misread}
    validator = Draft202012Validator(load_schema(SCHEMA))
    found = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        where = list(error.absolute_path)
        line = _line(root, where)
        if line in said:
            continue
        shown = "/".join(str(part) for part in where) or "(root)"
        message = f"{shown}: {error.message}"
        wanted = error.validator_value if error.validator == "type" else ()
        number = isinstance(error.instance, (int, float)) and not isinstance(error.instance, bool)
        if number and "string" in wanted:
            message += "; write it in quotes, as the text it is"
        found.append((message, line))
    return found


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _raw_faults(document: dict, root: yaml.Node | None) -> list[tuple[str, int | None]]:
    """What is wrong with codes as written, which the file's objects no longer show: a code
    written `1.0`, which the schema takes for an integer and which is "1.0" as text, and a
    variable that gives its codes twice over, which would be read from its list alone."""
    places = [(["code_lists", name], codes, "code")
              for name, codes in _mapping(document.get("code_lists")).items()]  # fmt: skip
    found = []
    for index, entry in enumerate(document["variables"]):
        at = ["variables", index]
        if "values" in entry and "code_list" in entry:
            found.append((f"variable {entry['name']}: gives both values and a code_list; give "
                          "one", _line(root, at)))  # fmt: skip
        places += [(at + [key], entry.get(key), "code") for key in ("values", "missing")]
        places.append((at + ["applies_if", "in"], _mapping(entry.get("applies_if")).get("in"),
                       None))  # fmt: skip
        places.append((at, [entry], "item"))
        places.append((at + ["standard"], [_mapping(entry.get("standard"))], "code"))
        for guideline, items in _mapping(entry.get("reporting")).items():
            places.append((at + ["reporting", guideline], items, None))
    for where, items, key in places:
        for number, item in enumerate(items if isinstance(items, list) else ()):
            value = _mapping(item).get(key) if key else item
            if isinstance(value, float) and value.is_integer():
                shown = "/".join(str(part) for part in where)
                found.append((f"{shown}: {value!r} is a code with a decimal point; write it "
                              f"{int(value)}, or in quotes as the data hold it",
                              _line(root, where + [number])))  # fmt: skip
    return found


# -- the file as objects --------------------------------------------------------------------


def _text(value: Any) -> str:
    return str(value)


def _codes(entries: list | None) -> tuple[Code, ...]:
    return tuple(Code(_text(entry["code"]), entry["label"]) for entry in entries or ())


def _build(path: Path, document: dict, root: yaml.Node | None) -> Dictionary:
    lists = {name: _codes(codes) for name, codes in (document.get("code_lists") or {}).items()}
    variables = tuple(
        _variable(entry, lists, _line(root, ["variables", index]))
        for index, entry in enumerate(document["variables"])
    )
    period = document.get("study_period")
    return Dictionary(
        path=path,
        variables=variables,
        title=document.get("title"),
        study_period=(period["start"], period["end"]) if period else None,
        datasets=tuple(Dataset(**entry) for entry in document.get("datasets") or ()),
        forms=tuple(Form(**entry) for entry in document.get("forms") or ()),
        instruments=tuple(Instrument(**entry) for entry in document.get("instruments") or ()),
        code_lists=tuple(lists.items()),
        rules=tuple(
            Rule(
                id=entry["id"],
                says=entry["says"],
                order=tuple(entry.get("order") or ()),
                unique=tuple(entry.get("unique") or ()),
                computed=bool(entry.get("computed")),
            )
            for entry in document.get("rules") or ()
        ),
    )


def _variable(entry: dict, lists: dict[str, tuple[Code, ...]], line: int | None) -> Variable:
    bounds = entry.get("range") or {}
    condition = entry.get("applies_if")
    standard = entry.get("standard")
    listed = entry.get("code_list")
    return Variable(
        name=entry["name"],
        label=entry["label"],
        definition=entry["definition"],
        type=entry["type"],
        line=line,
        question=entry.get("question"),
        unit=entry.get("unit"),
        values=lists.get(listed, ()) if listed else _codes(entry.get("values")),
        code_list=listed,
        minimum=bounds.get("min"),
        maximum=bounds.get("max"),
        missing=_codes(entry.get("missing")),
        required=bool(entry.get("required")),
        applies_if=Condition(condition["variable"], tuple(_text(c) for c in condition["in"]))
        if condition
        else None,
        form=entry.get("form"),
        timing=entry.get("timing"),
        recorded_by=entry.get("recorded_by"),
        source=entry.get("source"),
        dataset=entry.get("dataset"),
        derived_from=tuple(entry.get("derived_from") or ()),
        derivation=entry.get("derivation"),
        instrument=entry.get("instrument"),
        item=_text(entry["item"]) if "item" in entry else None,
        standard=Standard(
            **{**standard, "code": _text(standard["code"]) if "code" in standard else None}
        )
        if standard
        else None,
        reporting=tuple(
            (guideline, tuple(_text(item) for item in items))
            for guideline, items in (entry.get("reporting") or {}).items()
        ),
        reason=entry.get("reason"),
        pattern=entry.get("pattern"),
        within_study_period=bool(entry.get("within_study_period")),
    )


# -- what the schema cannot say ----------------------------------------------------------------


def _problems(dictionary: Dictionary, root: yaml.Node | None) -> list[tuple[str, int | None]]:
    found = _repeated(dictionary, root)
    for name, codes in dictionary.code_lists:
        found += [(f"code list {name}: {said}", _line(root, ["code_lists", name]))
                  for said in _code_faults(codes)]  # fmt: skip
    found += _period_faults(dictionary, root)
    for variable in dictionary.variables:
        found += [(f"variable {variable.name}: {said}", variable.line)
                  for said in _variable_faults(variable, dictionary)]  # fmt: skip
    for index, rule in enumerate(dictionary.rules):
        found += [(f"rule {rule.id}: {said}", _line(root, ["rules", index]))
                  for said in _rule_faults(rule, dictionary)]  # fmt: skip
    return found


def _period_faults(dictionary: Dictionary, root: yaml.Node | None) -> list[tuple[str, int | None]]:
    """A study period whose bounds are not dates, `'2026-02-30'` in quotes, which the schema's
    pattern lets by, or whose start is after its end."""
    if dictionary.study_period is None:
        return []
    line = _line(root, ["study_period"])
    for bound in dictionary.study_period:
        try:
            date.fromisoformat(bound)
        except ValueError:
            return [(f"study_period: {bound!r} is not a date", line)]
    if dictionary.study_period[0] > dictionary.study_period[1]:
        return [("study_period: start is after end", line)]
    return []


def _repeated(dictionary: Dictionary, root: yaml.Node | None) -> list[tuple[str, int | None]]:
    """A name or an id given twice, at the second: whichever was meant, the other is read in
    its place."""
    found = []
    for kind, part, ids in (
        ("variable", "variables", dictionary.names),
        ("dataset", "datasets", [d.id for d in dictionary.datasets]),
        ("form", "forms", [f.id for f in dictionary.forms]),
        ("instrument", "instruments", [i.id for i in dictionary.instruments]),
        ("rule", "rules", [r.id for r in dictionary.rules]),
    ):
        for repeated in sorted({i for i in ids if ids.count(i) > 1}):
            second = [index for index, i in enumerate(ids) if i == repeated][1]
            found.append((f"{kind} {repeated} is given more than once",
                          _line(root, [part, second])))  # fmt: skip
    return found


def _code_faults(codes: tuple[Code, ...]) -> list[str]:
    said = [c.code for c in codes]
    return [f"code {code} is given more than once"
            for code in sorted({c for c in said if said.count(c) > 1})]  # fmt: skip


def _variable_faults(variable: Variable, dictionary: Dictionary) -> list[str]:
    return (
        _reference_faults(variable, dictionary)
        + _value_faults(variable)
        + _range_faults(variable)
        + _condition_faults(variable, dictionary)
        + _text_faults(variable, dictionary)
    )


def _reference_faults(variable: Variable, dictionary: Dictionary) -> list[str]:
    found = []
    for kind, named, known in (
        ("form", variable.form, [f.id for f in dictionary.forms]),
        ("instrument", variable.instrument, [i.id for i in dictionary.instruments]),
        ("dataset", variable.dataset, [d.id for d in dictionary.datasets]),
        ("code list", variable.code_list, [name for name, _codes in dictionary.code_lists]),
    ):
        if named is not None and named not in known:
            found.append(f"its {kind} {named} is not in the dictionary")
    if variable.item is not None and variable.instrument is None:
        found.append(f"item {variable.item} names no instrument")
    return found


def _value_faults(variable: Variable) -> list[str]:
    if variable.type not in CODED and (variable.values or variable.code_list):
        return [f"a {variable.type} variable has no codes; values and code_list are for "
                f"{', '.join(CODED)} variables"]  # fmt: skip
    # A list's own faults are said once, at the list.
    own = () if variable.code_list else variable.values
    found = _code_faults(own) + [f"missing {said}"
                                             for said in _code_faults(variable.missing)]
    if variable.type == "binary" and variable.values and len(variable.values) != 2:
        found.append(f"a binary variable has two codes, and this one has "
                     f"{len(variable.values)}")  # fmt: skip
    both = {c.code for c in variable.values} & {c.code for c in variable.missing}
    found += [f"code {code} is both a value and a missing code" for code in sorted(both)]
    return found


def _zoned(reader):
    """`fromisoformat` reading a zone written `Z`, which Python 3.10's refuses. Other forms
    3.11 reads and 3.10 does not, `20200101`, are refused on 3.10 alone."""
    return lambda bound: reader(bound[:-1] + "+00:00" if bound.endswith("Z") else bound)


#: How each type's bounds are read; None where a type has none.
_BOUNDS = {
    "continuous": float,
    "count": float,
    "date": date.fromisoformat,
    "datetime": _zoned(datetime.fromisoformat),
    "time": _zoned(time.fromisoformat),
}


def _range_faults(variable: Variable) -> list[str]:
    bounds = [b for b in (variable.minimum, variable.maximum) if b is not None]
    if not bounds:
        return []
    reader = _BOUNDS.get(variable.type)
    if reader is None:
        return [f"a {variable.type} variable has no range"]
    read = []
    for bound in bounds:
        numeric = variable.type in NUMERIC
        if numeric != isinstance(bound, (int, float)):
            wanted = "a number" if numeric else f"an ISO 8601 {variable.type}, in quotes"
            return [f"its range bound {bound!r} is not {wanted}"]
        try:
            read.append(reader(bound))
        except ValueError:
            return [f"its range bound {bound!r} is not an ISO 8601 {variable.type}"]
    try:
        above = len(read) == 2 and read[0] > read[1]
    except TypeError:
        return ["its range gives one bound a time zone and the other none"]
    return ["its range's min is above its max"] if above else []


def _condition_faults(variable: Variable, dictionary: Dictionary) -> list[str]:
    condition = variable.applies_if
    if condition is None:
        return []
    other = dictionary.variable(condition.variable)
    if other is None:
        return [f"applies_if names {condition.variable}, which is not in the dictionary"]
    if other.name == variable.name:
        return ["applies_if names the variable itself"]
    if other.type not in CODED:
        return [f"applies_if names {other.name}, a {other.type} variable, which has no codes"]
    known = {c.code for c in other.values + other.missing}
    unknown = [code for code in condition.codes if other.values and code not in known]
    return [f"applies_if names code {code}, which {other.name} does not have"
            for code in unknown]  # fmt: skip


def _text_faults(variable: Variable, dictionary: Dictionary) -> list[str]:
    found = []
    if variable.pattern is not None:
        if variable.type not in PATTERNED:
            found.append(f"a pattern is for {' and '.join(PATTERNED)} variables")
        else:
            try:
                re.compile(variable.pattern)
            except (re.error, OverflowError, RecursionError) as exc:
                found.append(f"its pattern does not compile: {exc}")
    if variable.within_study_period:
        if variable.type not in ("date", "datetime"):
            found.append("within_study_period is for date and datetime variables")
        elif dictionary.study_period is None:
            found.append("within_study_period needs the dictionary's study_period")
    return found


def _rule_faults(rule: Rule, dictionary: Dictionary) -> list[str]:
    named = rule.order + rule.unique
    unknown = [name for name in named if dictionary.variable(name) is None]
    if unknown:
        return [f"{name} is not in the dictionary" for name in unknown]
    variables = [dictionary.variable(name) for name in named]
    if rule.order:
        families = {"temporal" if v.type in ("date", "datetime") else
                    "number" if v.type in NUMERIC else v.type for v in variables}  # fmt: skip
        if len(families) > 1 or not families <= {"temporal", "number"}:
            return ["order compares dates with dates, or numbers with numbers"]
    if rule.unique and len({v.dataset for v in variables}) > 1:
        return ["unique names variables of more than one dataset"]
    return []


__all__ = [
    "CODED",
    "DICTIONARY",
    "INVALID",
    "NUMERIC",
    "PATTERNED",
    "TEMPORAL",
    "Code",
    "Condition",
    "Dataset",
    "Dictionary",
    "Form",
    "Instrument",
    "Rule",
    "Standard",
    "Variable",
    "dictionary_path",
    "load_dictionary",
]
