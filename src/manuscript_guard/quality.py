"""What the data hold, against what the data dictionary says they should hold.

The author's script reads the data, never the tool. It hands a table to
`Emitter.check_data`, which runs the checks `design/data_dictionary.yaml` declares and emits a
count for each under `quality.`: how many rows hold no value, a value of the wrong type, one
out of its range, a code the dictionary does not list, a text that does not match its
pattern, a date outside the study period, a value where the variable does not apply; and how
many rows break each rule across variables or rows. Counts only: no value of any row leaves
the script.

The R emitter's `check_data` does the same, check for check. What both read a value as is
written down here once, so that the two languages count alike:

* missing: no value (None, NaN, NaT, pandas' NA), a text that is blank, or one of the
  variable's `missing` codes;
* a value as text: a truth value is "true" or "false", an integer its digits, a whole
  number held as a float its digits ("3", not "3.0") below 2 to the 53rd, where a float
  stops holding every whole number, any other number to fifteen significant digits, a date
  in ISO 8601, a text as it is;
* a number: a number, or a text that is one in decimal notation, finite;
* a date: a date, the date of a date and time, or a text `YYYY-MM-DD` that is a day of the
  calendar; a date and time: one, or a text `YYYY-MM-DD HH:MM[:SS]`, with `T` or a space,
  compared as the time on the clock it was written with: an offset after it is not applied;
* a code: the value as text, compared with each code as text, so 1 and "1" are one code.
"""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from manuscript_guard.contracts.dictionary import (
    CODED,
    DICTIONARY,
    NUMERIC,
    TEMPORAL,
    Dictionary,
    Variable,
    load_dictionary,
)

#: What every key the checks emit opens with.
PREFIX = "quality."

#: Each check, in the order a variable's are emitted.
CHECKS = (
    "missing",
    "wrong_type",
    "out_of_range",
    "not_allowed",
    "not_matching",
    "outside_period",
    "not_applicable",
)

#: Names a variable cannot take, since its counts would sit beside the rows and the rules.
RESERVED = frozenset({"rows", "rule"})

_BLANK = " \t\r\n"
#: Below this a float holds every whole number, and both languages print its digits alike.
#: Above it R on Windows prints digits a float does not hold (2.4e24 as ...67242404).
_EXACT = 2**53
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
_DATETIME = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?",
    re.ASCII,
)
_TIME = re.compile(r"(\d{2}):(\d{2})(?::(\d{2}))?", re.ASCII)


@dataclass(frozen=True)
class Count:
    """One count the checks emit: its key under `quality.`, and the rows it counted, by
    their place in the table from nought."""

    key: str
    rows: tuple[int, ...]

    @property
    def value(self) -> int:
        return len(self.rows)


def slug(name: str) -> str:
    """A variable's name as a result key holds it: in lower case, a dot an underscore."""
    return re.sub(r"[^a-z0-9_]", "_", name.lower())


def is_missing(item: object) -> bool:
    """None, a value unequal to itself (NaN, NaT), or pandas' NA."""
    from manuscript_guard.emit import _is_missing

    return _is_missing(item)


def _truth(item: object) -> bool:
    return isinstance(item, bool) or type(item).__name__ in ("bool_", "bool")


def _when(item: object) -> datetime | date | time | None:
    """A date, time or date and time object as Python's own, NumPy's converted."""
    if isinstance(item, (datetime, date, time)):
        return item
    if type(item).__name__ == "datetime64":
        converted = item.astype("datetime64[us]").item()  # type: ignore[attr-defined]
        return converted if isinstance(converted, (datetime, date)) else None
    return None


def text_of(item: object) -> str:
    """A value as text, as both emitters write it (the module's docstring)."""
    if _truth(item):
        return "true" if item else "false"
    if isinstance(item, numbers.Integral):
        return str(int(item))
    if isinstance(item, (numbers.Real, Decimal)):
        number = float(item)
        if math.isinf(number):
            return "inf" if number > 0 else "-inf"
        exact = number.is_integer() and abs(number) < _EXACT
        return str(int(number)) if exact else format(number, ".15g")
    when = _when(item)
    if isinstance(when, datetime):
        return when.replace(tzinfo=None).isoformat(timespec="seconds")
    if isinstance(when, (date, time)):
        return when.isoformat()
    return str(item)


def number_of(item: object) -> float | None:
    """A value as a finite number, or None where it is not one."""
    if _truth(item):
        return None
    if isinstance(item, (numbers.Real, Decimal)):
        number = float(item)
    elif isinstance(item, str) and _DECIMAL.fullmatch(item.strip(_BLANK)):
        number = float(item.strip(_BLANK))
    else:
        return None
    return number if math.isfinite(number) else None


def _calendar(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def date_of(item: object) -> str | None:
    """A value as an ISO date, or None where it is not one."""
    when = _when(item)
    if isinstance(when, datetime):
        return when.date().isoformat()
    if isinstance(when, date):
        return when.isoformat()
    if isinstance(item, str):
        found = _DATE.fullmatch(item.strip(_BLANK))
        day = _calendar(*found.groups()) if found else None
        return day.isoformat() if day else None
    return None


def datetime_of(item: object) -> str | None:
    """A value as an ISO date and time to the second, or None where it is not one."""
    when = _when(item)
    if isinstance(when, datetime):
        return when.replace(tzinfo=None, microsecond=0).isoformat()
    if isinstance(when, date):
        return f"{when.isoformat()}T00:00:00"
    if not isinstance(item, str):
        return None
    found = _DATETIME.fullmatch(item.strip(_BLANK))
    if found is None:
        return None
    year, month, day, hour, minute, second = found.groups()
    clock = _clock(hour, minute, second or "00")
    day_ = _calendar(year, month, day)
    return f"{day_.isoformat()}T{clock}" if day_ and clock else None


def _clock(hour: str, minute: str, second: str) -> str | None:
    if int(hour) > 23 or int(minute) > 59 or int(second) > 59:
        return None
    return f"{hour}:{minute}:{second}"


def time_of(item: object) -> str | None:
    """A value as an ISO time to the second, or None where it is not one."""
    when = _when(item)
    if isinstance(when, time):
        return when.replace(tzinfo=None, microsecond=0).isoformat()
    if not isinstance(item, str):
        return None
    found = _TIME.fullmatch(item.strip(_BLANK))
    return _clock(found[1], found[2], found[3] or "00") if found else None


_READ = {"date": date_of, "datetime": datetime_of, "time": time_of}


def _bound(variable: Variable, which: str) -> object:
    """A variable's range bound, read as its values are; refused where it cannot be."""
    given = variable.minimum if which == "min" else variable.maximum
    if given is None:
        return None
    kind = variable.type
    read = number_of(given) if kind in NUMERIC else _READ[kind](given) if kind in _READ else None
    if read is None:
        raise ValueError(
            f"data dictionary: {variable.name}'s range {which} {given!r} is not a {kind} value"
        )
    return read


def codes_of(variable: Variable) -> frozenset[str] | None:
    """A coded variable's allowed codes as text, its own or its code list's; None where none
    are decided yet."""
    return frozenset(coded.code for coded in variable.values) if variable.values else None


def checks_of(variable: Variable, dictionary: Dictionary) -> tuple[str, ...]:
    """The checks a dictionary entry asks for, in the order they are emitted."""
    kind = variable.type
    ranged = variable.minimum is not None or variable.maximum is not None
    asked = {"missing"}
    if kind in NUMERIC or kind in TEMPORAL:
        asked.add("wrong_type")
        if ranged:
            asked.add("out_of_range")
    if kind in CODED and codes_of(variable) is not None:
        asked.add("not_allowed")
    if variable.pattern:
        asked.add("not_matching")
    dated = kind in ("date", "datetime") and dictionary.study_period is not None
    if variable.within_study_period and dated:
        asked.add("outside_period")
    if variable.applies_if is not None:
        asked.add("not_applicable")
    return tuple(check for check in CHECKS if check in asked)


def pattern_of(variable: Variable) -> re.Pattern | None:
    """A variable's pattern, compiled as R's `perl = TRUE` reads it: `\\d` and `\\w` in
    ASCII."""
    return re.compile(variable.pattern, re.ASCII) if variable.pattern else None


def missing_codes(variable: Variable | None) -> frozenset[str]:
    return frozenset(coded.code for coded in variable.missing) if variable else frozenset()


def absent(item: object, codes: frozenset[str]) -> bool:
    """Whether a value is missing, as the module's docstring says."""
    if is_missing(item):
        return True
    if isinstance(item, str) and not item.strip(_BLANK):
        return True
    return bool(codes) and text_of(item) in codes


class Table:
    """The columns of a table the script read, however it holds them: a pandas or polars
    data frame, a mapping of a column's name to its values, or a list of rows, each a
    mapping of a column's name to its value (what `csv.DictReader` gives)."""

    def __init__(self, data: object) -> None:
        if isinstance(data, Mapping):
            data = {
                name: values if hasattr(values, "__len__") else list(values)
                for name, values in data.items()
            }
        self._data = data
        if isinstance(data, Mapping):
            self.names = tuple(str(name) for name in data)
            lengths = {len(values) for values in data.values()}
            if len(lengths) > 1:
                raise ValueError("check_data: the columns given are not all of one length")
            self.rows = lengths.pop() if lengths else 0
        elif hasattr(data, "columns") and hasattr(data, "__getitem__"):
            self.names = tuple(str(name) for name in data.columns)
            self.rows = len(data)  # type: ignore[arg-type]
        elif isinstance(data, Sequence) and all(isinstance(row, Mapping) for row in data):
            self.names = tuple(dict.fromkeys(str(name) for row in data for name in row))
            self.rows = len(data)
        else:
            raise TypeError(
                "check_data: give a data frame, a mapping of columns to their values, or a "
                f"list of rows each a mapping; not a {type(data).__name__}"
            )
        if len(set(self.names)) != len(self.names):
            raise ValueError("check_data: the table has two columns of one name")

    def column(self, name: str) -> list:
        data = self._data
        if isinstance(data, Mapping):
            return list(next(values for key, values in data.items() if str(key) == name))
        if hasattr(data, "columns"):
            return list(data[next(c for c in data.columns if str(c) == name)])  # type: ignore[index]
        return [next((v for k, v in row.items() if str(k) == name), None) for row in data]  # type: ignore[union-attr]


def _applies(variable: Variable, table: Table, dictionary: Dictionary) -> list | None:
    """For each row, whether the variable applies to it: True, False, or None where the
    variable it depends on holds no value."""
    condition = variable.applies_if
    if condition is None:
        return None
    other = condition.variable
    if other not in table.names:
        raise ValueError(
            f"check_data: {variable.name} applies only where {other} holds one of "
            f"{', '.join(condition.codes)}, and the table has no column {other}"
        )
    codes = frozenset(condition.codes)
    unknown = missing_codes(dictionary.variable(other))
    return [
        None if absent(item, unknown) else text_of(item) in codes for item in table.column(other)
    ]


def check_variable(
    variable: Variable, values: Sequence, dictionary: Dictionary, applies: list | None = None
) -> dict[str, list[int]]:
    """The rows each of a variable's checks counts."""
    kind = variable.type
    found: dict[str, list[int]] = {check: [] for check in checks_of(variable, dictionary)}
    unknown = missing_codes(variable)
    codes = codes_of(variable) if "not_allowed" in found else None
    pattern = pattern_of(variable)
    low, high = _bound(variable, "min"), _bound(variable, "max")
    period = dictionary.study_period if "outside_period" in found else None
    for row, item in enumerate(values):
        here = True if applies is None else applies[row]
        if absent(item, unknown):
            if here:
                found["missing"].append(row)
            continue
        if here is False:
            found["not_applicable"].append(row)
        if pattern is not None and not pattern.fullmatch(text_of(item)):
            found["not_matching"].append(row)
        if kind in CODED:
            if codes is not None and text_of(item) not in codes:
                found["not_allowed"].append(row)
            continue
        if kind in NUMERIC:
            read = number_of(item)
            if read is None or (kind == "count" and (read < 0 or not read.is_integer())):
                found["wrong_type"].append(row)
                continue
        elif kind in TEMPORAL:
            read = _READ[kind](item)
            if read is None:
                found["wrong_type"].append(row)
                continue
            if period and not period[0] <= read[:10] <= period[1]:
                found["outside_period"].append(row)
        else:
            continue
        if (low is not None and read < low) or (high is not None and read > high):
            found["out_of_range"].append(row)
    return found


def _family(variables: Sequence[Variable]) -> str:
    """What an order rule compares its variables as: numbers, dates, dates and times, or
    times. A rule over variables of two families is refused."""
    kinds = {variable.type for variable in variables}
    if kinds <= set(NUMERIC):
        return "number"
    if kinds <= {"date", "datetime"}:
        return "date" if "date" in kinds else "datetime"
    if kinds == {"time"}:
        return "time"
    raise ValueError(
        "data dictionary: an order rule compares numbers, dates or times, one of them; "
        f"not {', '.join(sorted(kinds))}"
    )


def _comparable(variable: Variable, family: str):
    """How an order rule reads one of its variables: as its own type, and, where the rule
    holds a date, a date and time by its day."""
    if family == "number":
        return number_of
    read = _READ[variable.type]
    if family == "date" and variable.type == "datetime":
        return lambda item: (read(item) or "")[:10] or None
    return read


def check_order(variables: Sequence[Variable], columns: Sequence[Sequence]) -> list[int]:
    """The rows where each value is present and of its type, and one is greater than the
    next."""
    family = _family(variables)
    readers = [_comparable(variable, family) for variable in variables]
    unknown = [missing_codes(variable) for variable in variables]
    broken = []
    for row, items in enumerate(zip(*columns, strict=True)):
        if any(absent(item, codes) for item, codes in zip(items, unknown, strict=True)):
            continue
        values = [read(item) for read, item in zip(readers, items, strict=True)]
        if any(value is None for value in values):
            continue
        if any(earlier > later for earlier, later in zip(values, values[1:], strict=False)):
            broken.append(row)
    return broken


def _key_text(variable: Variable, item: object) -> str:
    """A value as a key compares it: a number or a date as itself, so that "1.0" and 1 are
    one key, and anything else as text."""
    kind = variable.type
    if kind in NUMERIC:
        read = number_of(item)
        return text_of(read) if read is not None else text_of(item)
    if kind in _READ:
        return _READ[kind](item) or text_of(item)
    return text_of(item)


def check_unique(variables: Sequence[Variable], columns: Sequence[Sequence]) -> list[int]:
    """The rows whose values of the key are those of a row before them. A row with a part
    of its key missing is no duplicate: it is counted as missing."""
    unknown = [missing_codes(variable) for variable in variables]
    seen: set[tuple[str, ...]] = set()
    repeated = []
    for row, items in enumerate(zip(*columns, strict=True)):
        if any(absent(item, codes) for item, codes in zip(items, unknown, strict=True)):
            continue
        key = tuple(_key_text(v, item) for v, item in zip(variables, items, strict=True))
        if key in seen:
            repeated.append(row)
        seen.add(key)
    return repeated


def rows_key(dataset: str | None) -> str:
    """The key of the count of rows checked: `rows`, or `rows.<dataset>`."""
    return "rows" if dataset is None else f"rows.{dataset}"


def variables_of(dictionary: Dictionary, dataset: str | None) -> list[Variable]:
    """The entries a check of `dataset` reads: those that name it, or, for no dataset, those
    that name none."""
    listed = [entry.id for entry in dictionary.datasets]
    if dataset is not None and dataset not in listed:
        named = f"it lists {', '.join(listed)}" if listed else "it lists none"
        raise ValueError(f"check_data: the data dictionary lists no dataset {dataset!r}; {named}")
    return [variable for variable in dictionary.variables if variable.dataset == dataset]


def refuse_clashes(dictionary: Dictionary) -> None:
    """Refuse two variables whose counts would go under one key, or a name kept for the
    rows and the rules."""
    seen: dict[str, str] = {}
    for name in dictionary.names:
        key = slug(name)
        if key in RESERVED:
            raise ValueError(
                f"data dictionary: a variable named {name} would put its counts beside "
                f"quality.{key}; rename it"
            )
        if key in seen:
            raise ValueError(
                f"data dictionary: {seen[key]} and {name} would both be counted under "
                f"quality.{key}; rename one"
            )
        seen[key] = name


def _computed(rule_id: str, flags: object, dictionary: Dictionary, rows: int) -> Count:
    """The count of a rule the script found the rows of, as one truth value for each row."""
    rule = next((rule for rule in dictionary.rules if rule.id == rule_id), None)
    if rule is None:
        raise ValueError(f"check_data: the data dictionary has no rule {rule_id!r}")
    if not rule.computed:
        raise ValueError(
            f"check_data: rule {rule_id!r} is not `computed: true`; check_data finds the rows "
            "of an order or a unique rule itself"
        )
    given = list(flags)  # type: ignore[call-overload]
    if len(given) != rows:
        raise ValueError(
            f"check_data: rule {rule_id!r} was given {len(given)} truth values for a table "
            f"of {rows} rows; give one for each row, true where the row breaks the rule"
        )
    if not all(_truth(flag) for flag in given):
        raise ValueError(
            f"check_data: rule {rule_id!r} was given something other than true or false for "
            "a row; say for every row whether it breaks the rule"
        )
    return Count(f"rule.{rule_id}", tuple(row for row, flag in enumerate(given) if flag))


def check(
    dictionary: Dictionary,
    data: object,
    *,
    dataset: str | None = None,
    computed: Mapping[str, object] | None = None,
) -> tuple[int, list[Count]]:
    """The rows of a table, and each count its checks find: the variables of `dataset` the
    table has a column for, the order and unique rules over them, and the computed rules
    given. A variable with no column is not checked, and G16 names it."""
    refuse_clashes(dictionary)
    table = Table(data)
    variables = variables_of(dictionary, dataset)
    present = [variable for variable in variables if variable.name in table.names]
    if not present and not computed:
        where = "" if dataset is None else f" of dataset {dataset}"
        listed = ", ".join(variable.name for variable in variables[:5]) or "none"
        raise ValueError(
            f"check_data: the table has no column the data dictionary lists{where} "
            f"(it lists {listed})"
        )
    counts = []
    for variable in present:
        applies = _applies(variable, table, dictionary)
        found = check_variable(variable, table.column(variable.name), dictionary, applies)
        stem = slug(variable.name)
        counts += [Count(f"{stem}.{name}", tuple(rows)) for name, rows in found.items()]
    here = {variable.name for variable in present}
    for rule in dictionary.rules:
        names = rule.order or rule.unique
        if not names or not set(names) <= here:
            continue
        ruled = [dictionary.variable(name) for name in names]
        columns = [table.column(name) for name in names]
        rows = check_order(ruled, columns) if rule.order else check_unique(ruled, columns)
        counts.append(Count(f"rule.{rule.id}", tuple(rows)))
    for rule_id, flags in (computed or {}).items():
        counts.append(_computed(rule_id, flags, dictionary, table.rows))
    return table.rows, counts


def held_back(count: int, minimum: int | None) -> str | None:
    """How a count below the data custodian's minimum is printed: "<5" for 1 to 4. None
    for any other count, which prints as itself."""
    return f"<{minimum}" if minimum is not None and 0 < count < minimum else None


def minimum_cell_count(root: Path) -> int | None:
    """The custodian's minimum, where the project's `paper.yaml` declares one."""
    from manuscript_guard.contracts._schema import ContractError, read_structured
    from manuscript_guard.contracts.project import PAPER_FILE

    path = root / PAPER_FILE
    try:
        paper = read_structured(path) if path.is_file() else None
    except ContractError:
        return None
    custodian = paper.get("custodian") if isinstance(paper, dict) else None
    minimum = custodian.get("minimum_cell_count") if isinstance(custodian, dict) else None
    return minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else None


def read_dictionary(root: Path) -> Dictionary:
    """The project's data dictionary, refused where there is none or it does not read."""
    dictionary, report = load_dictionary(root)
    if report.findings:
        listed = "; ".join(
            f"line {finding.line}: {finding.message}" if finding.line else finding.message
            for finding in report.findings[:5]
        )
        raise ValueError(f"check_data: {DICTIONARY.as_posix()} does not read: {listed}")
    if dictionary is None:
        raise FileNotFoundError(
            f"check_data: no data dictionary at {root / DICTIONARY}; write one first (the "
            "analysis-plan skill has the outline)"
        )
    return dictionary
