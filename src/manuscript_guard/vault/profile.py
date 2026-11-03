"""The data profile: what `em.profile` (`em$profile` in R) writes of a table the author's
script read, for the synthetic copy the agent works on.

The script reads the data, never the tool: it hands the table it read to the emitter, under
`vault run`, and the profile it writes, `profiles/data/<name>.profile.json`, leaves the vault
only when a person releases it. With m the data custodian's minimum cell count, each column
gives:

* always its name, its place and the type read: the data dictionary's where it has the
  column, else read from the values;
* its missing values as a count, "<m" below m, and a share only from m;
* for a coded column (binary, categorical, ordinal; with no entry in the dictionary, one of at
  most 50 values), each level of m rows or more with its count, the others folded into
  "other": how many levels, and their rows, "<m" below m;
* for numbers, dates and times, the rows read, a mean and SD (numbers only, from m rows and at
  least three), and each of the 5th to 95th centiles that has m rows below it and m above it,
  so no centile is the smallest or largest value. Dates to the month, times to the hour;
* for a withheld column (an identifier, a text, or with no entry in the dictionary every value
  different, or more than 50 different values that are neither numbers nor dates), the
  missing values and the pattern its values share, "AA-9999", where they share one.

The counts of each column add up to the table's rows, which are printed, and nought is printed
as 0, so a count "<m" is one to m-1, and the levels folded into "other" are as many rows at
least. Where a count held back could be worked out from them
(`gates.custodian.recoverable_counts`), the smallest count printed beside it is held back too,
unprinted (`null`), until none can; where none is left to hold back, the column's counts are
withheld, and the profile says why (`held`). How many levels "other" folds is not said where it
would give its count away.

At a minimum of 1 nothing is held back. With few rows, the centiles, the mean and the SD
together can give the smallest and largest values back.

The R emitter's `profile.R` does the same, rule for rule, and both write the same bytes of
the same table: `tests/data/profile` holds them to it. Numbers are written as C's `%.6g`
writes them, in both languages.
"""

from __future__ import annotations

import json
import math
import re
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from manuscript_guard import quality
from manuscript_guard.contracts.dictionary import CODED, NUMERIC, Dictionary, Variable

SCHEMA = "manuscript-guard/data-profile/1"
#: Where the profiles are, in the project.
FOLDER = PurePosixPath("profiles/data")
SUFFIX = ".profile.json"
#: The centiles a profile may give.
CENTILES = (5, 10, 25, 50, 75, 90, 95)
#: More different values than this, in a column the dictionary does not type, are not levels.
MOST_LEVELS = 50
#: The fewest rows a mean and SD are given of, whatever the custodian's minimum: two values
#: and their mean and SD are the two values.
FEWEST_FOR_MEAN = 3
#: The most decimal places a profile says numbers are written to.
MOST_DECIMALS = 6
#: What `read_as` may say of how the file was read.
READ_AS = ("delimiter", "decimal", "encoding", "quoting", "newline", "dates", "header_of")
_QUOTING = ("minimal", "all")
_NEWLINES = ("\n", "\r\n")
_DELIMITERS = (",", ";", "\t", "|")
#: The directives a date format may hold, each two digits but the year's four.
_DIRECTIVES = {"Y": 4, "m": 2, "d": 2, "H": 2, "M": 2, "S": 2}
_DECIMALS = re.compile(r"[+-]?[0-9]*\.([0-9]+)", re.ASCII)
#: Why a column's counts are withheld where nothing more can be held back.
HELD = "held back: its counts would give a count below the minimum away"
_MARK = chr(0xFEFF)


class Figure(str):
    """A number as the profile prints it: C's `%.6g`, written into the JSON as it is."""


def figure(number: float) -> Figure:
    return Figure(format(number + 0.0, ".6g"))


def check_name(name: object) -> str:
    """A profile's name, the file's label in the vault: a relative path with forward slashes
    and no `..`, so that the profile and the synthetic copy stay where they belong."""
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise ValueError(f"profile: name {name!r}: give the file's name in the vault, "
                         "\"cohort.csv\"")  # fmt: skip
    parts = name.split("/")
    bad = ("\\" in name or ":" in name or name.startswith("/")
           or any(part in ("", ".", "..") for part in parts))  # fmt: skip
    if bad:
        raise ValueError(f"profile: name {name!r} is not a file's name in the vault: a relative "
                         "path with forward slashes, no `..`")  # fmt: skip
    return name


def path_of(root: Path, name: str) -> Path:
    return root.joinpath(*FOLDER.parts, *(check_name(name) + SUFFIX).split("/"))


# ------------------------------------------------------------------- how the file was read


def _format_pattern(form: str) -> re.Pattern:
    """A date format of `%Y %m %d %H %M %S` and other characters, as a pattern with a group
    for each directive; any other directive is refused."""
    pattern, at = [], 0
    while at < len(form):
        char = form[at]
        if char != "%":
            pattern.append(re.escape(char))
            at += 1
            continue
        code = form[at + 1:at + 2]
        if code == "%":
            pattern.append("%")
        elif code in _DIRECTIVES:
            if f"(?P<{code}>" in "".join(pattern):
                raise ValueError(f"profile: date format {form!r} names %{code} twice")
            pattern.append(f"(?P<{code}>[0-9]{{{_DIRECTIVES[code]}}})")
        else:
            raise ValueError(f"profile: date format {form!r}: only %Y, %m, %d, %H, %M, %S and "
                             "%% are read")  # fmt: skip
        at += 2
    compiled = re.compile("".join(pattern), re.ASCII)
    if not {"Y", "m", "d"} <= set(compiled.groupindex):
        raise ValueError(f"profile: date format {form!r} holds no %Y, %m and %d")
    return compiled


def _sniffed(path: object) -> dict:
    """What the header line of the file says of its shape: the delimiter most often in it, a
    byte-order mark, the line ending. Nothing after the header is read."""
    with open(Path(str(path)), "rb") as handle:
        line = handle.readline(1 << 20)
    found: dict = {"newline": "\r\n" if line.endswith(b"\r\n") else "\n"}
    if line.startswith(b"\xef\xbb\xbf"):
        found["encoding"] = "utf-8-sig"
    counts = [line.count(delimiter.encode()) for delimiter in _DELIMITERS]
    if max(counts) > 0:
        found["delimiter"] = _DELIMITERS[counts.index(max(counts))]
    return found


def file_shape(name: str, read_as: Mapping | None) -> tuple[dict, dict[str, str]]:
    """The file's shape, for the synthetic copy, and the date format of each column given
    one: from `read_as`, and from a sniff of the header of `read_as["header_of"]`."""
    given = dict(read_as or {})
    unknown = sorted(set(given) - set(READ_AS))
    if unknown:
        raise ValueError(f"profile: read_as says {', '.join(unknown)}; it may say "
                         f"{', '.join(READ_AS)}")  # fmt: skip
    form = PurePosixPath(name).suffix.lower().lstrip(".")
    shape = {"format": form, "delimiter": "\t" if form in ("tsv", "tab") else ",",
             "decimal": ".", "encoding": "utf-8", "quoting": "minimal",
             "newline": "\n"}  # fmt: skip
    if given.get("header_of") is not None:
        shape.update(_sniffed(given["header_of"]))
    shape.update({key: given[key] for key in shape if key in given})
    _refuse_shape(shape)
    shape["bom"] = shape["encoding"].lower().replace("_", "-") in ("utf-8-sig", "utf8-sig")
    if shape["bom"]:
        shape["encoding"] = "utf-8"
    dates = given.get("dates") or {}
    if not isinstance(dates, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in dates.items()):  # fmt: skip
        raise ValueError("profile: read_as dates maps a column's name to its date format")
    for form_ in dates.values():
        _format_pattern(form_)
    return shape, dict(dates)


def _refuse_shape(shape: dict) -> None:
    checks = (("delimiter", lambda v: isinstance(v, str) and len(v) == 1 and v not in "\r\n\"."),
              ("decimal", lambda v: v in (".", ",")),
              ("encoding", lambda v: isinstance(v, str) and bool(v)),
              ("quoting", lambda v: v in _QUOTING),
              ("newline", lambda v: v in _NEWLINES))  # fmt: skip
    for key, fits in checks:
        if not fits(shape[key]):
            raise ValueError(f"profile: read_as {key} {shape[key]!r} is not one this reads")


# ------------------------------------------------------------------------- reading a value


def _by_format(form: str, kind: str):
    pattern = _format_pattern(form)

    def read(item: object) -> str | None:
        if not isinstance(item, str):
            return quality.date_of(item) if kind == "date" else quality.datetime_of(item)
        found = pattern.fullmatch(item.strip(quality._BLANK))
        if found is None:
            return None
        parts = found.groupdict()
        day = quality._calendar(parts["Y"], parts["m"], parts["d"])
        if day is None or int(parts["Y"]) < 1:
            return None
        if kind == "date":
            return day.isoformat()
        clock = quality._clock(parts.get("H") or "00", parts.get("M") or "00",
                               parts.get("S") or "00")  # fmt: skip
        return f"{day.isoformat()}T{clock}" if clock else None

    return read


def _date_reader(kind: str, form: str | None):
    """How a value of a date or date and time column is read, as its ISO date and time."""
    if form is not None:
        return _by_format(form, kind)
    return quality.date_of if kind == "date" else quality.datetime_of


def _type_read(present: list, form: str | None) -> str:
    """The type a column's values are, where the dictionary does not say: numbers, dates,
    dates and times, times, or text."""
    if not present:
        return "text"
    if form is not None:
        return "datetime" if "%H" in form else "date"
    for kind, read in (("continuous", quality.number_of), ("date", quality.date_of),
                       ("datetime", quality.datetime_of), ("time", quality.time_of)):  # fmt: skip
        if all(read(item) is not None for item in present):
            return kind
    return "text"


def _kind(variable: Variable | None, kind: str, texts: list[str]) -> str:
    """What the profile gives of a column: levels, a number's, a date's or a time's
    distribution, or nothing of its values."""
    if variable is not None:
        if kind in CODED:
            return "levels"
        if kind in NUMERIC:
            return "number"
        return {"date": "date", "datetime": "date", "time": "time"}.get(kind, "withheld")
    distinct = len(set(texts))
    if distinct == len(texts):
        return "withheld"
    if kind in ("date", "datetime"):
        return "date"
    if distinct <= MOST_LEVELS:
        return "levels"
    return {"continuous": "number", "time": "time"}.get(kind, "withheld")


# --------------------------------------------------------------------- counts and margins


def _shown(count: int, minimum: int) -> int | str:
    return quality.held_back(count, minimum) or count


def _range(one: object, total: int | None, minimum: int, bound) -> tuple[int, float]:
    """What a count printed as `one` can be, `bound` narrowing it where more is known."""
    from manuscript_guard.gates import custodian

    if isinstance(one, int):
        return one, one
    least = custodian.HELD_LEAST
    low, high = (0, math.inf if total is None else total) if one is None else (least, minimum - 1)
    if bound is not None:
        low, high = max(low, bound[0]), min(high, bound[1])
    return low, high


def _given_away(shown: list, total: int | None, minimum: int, bounds) -> list[int]:
    """The places of the counts held back that are worked out: alone, by what is known of
    each, or beside the total and the others."""
    from manuscript_guard.gates.custodian import recoverable_counts

    alone = [at for at, one in enumerate(shown) if not isinstance(one, int)
             and (pinned := _range(one, total, minimum, bounds[at]))[0] == pinned[1]
             and 1 <= pinned[0] < minimum]  # fmt: skip
    if alone or total is None:
        return alone
    return recoverable_counts(total, shown, minimum, bounds)


def _unheld(shown: list) -> list | None:
    """What a column whose counts give one held back away, and that has none left to hold
    back beside it, prints: nothing of its counts."""
    return None


def held_beside(
    counts: Sequence[int],
    total: int | None,
    minimum: int,
    bounds: Sequence | None = None,
    hidden: Sequence[int] = (),
) -> list | None:
    """How each count of a column is printed: itself, "<m" below the minimum, or None where
    it is held back beside a count that the total and the others would give away, or that
    gives itself away. The counts add up to `total`, which is printed, or None where it is
    held back; `bounds` says what more is known of a count, `hidden` which are never printed.
    None where no count is left to hold back and one would still be given away."""
    bounds = list(bounds) if bounds is not None else [None] * len(counts)
    shown: list = [None if at in hidden else _shown(count, minimum)
                   for at, count in enumerate(counts)]  # fmt: skip
    for at in _given_away(shown, None, minimum, bounds):
        shown[at] = None
    while _given_away(shown, total, minimum, bounds):
        exact = [at for at, one in enumerate(shown) if isinstance(one, int)]
        if not exact:
            return _unheld(shown)
        some = [at for at in exact if counts[at] > 0] or exact
        shown[min(some, key=lambda at: counts[at])] = None
    return shown


def _share(count: int, shown: object, rows: int, minimum: int) -> Figure | None:
    if isinstance(shown, int) and count >= minimum and count > 0 and rows > 0:
        return figure(count / rows)
    return None


# --------------------------------------------------------------------------- the columns


@dataclass(frozen=True)
class _Column:
    name: str
    variable: Variable | None
    kind: str
    role: str
    form: str | None
    present: list
    missing: int


def _decimals(present: list) -> int:
    """The decimal places the column's numbers are most often written to; of two as often,
    the more."""
    places = Counter()
    for item in present:
        text = item.strip(quality._BLANK) if isinstance(item, str) else quality.text_of(item)
        found = _DECIMALS.fullmatch(text)
        places[len(found[1]) if found else 0] += 1
    most = max(places.values())
    return min(max(place for place, seen in places.items() if seen == most), MOST_DECIMALS)


def _centiles(values: list, minimum: int, show) -> dict:
    """Each centile whose value has `minimum` rows below it and `minimum` above, the value
    being the smallest whose rows at or below it are the centile's share or more."""
    ordered = sorted(values)
    n = len(ordered)
    found = {}
    for centile in CENTILES if n else ():
        value = ordered[_centile_index(centile, n)]
        below = bisect_left(ordered, value)
        above = n - bisect_right(ordered, value)
        if _enough(below, above, minimum):
            found[str(centile)] = show(value)
    return found


def _centile_index(centile: int, n: int) -> int:
    """The place, from nought, of the centile's value among `n` sorted: the first whose rows
    at or below it are the centile's share of `n` or more."""
    return (centile * n + 99) // 100 - 1


def _enough(below: int, above: int, minimum: int) -> bool:
    """Whether a centile has rows enough on each side of it to be given."""
    return below >= minimum and above >= minimum


def _kept(count: int, minimum: int) -> bool:
    """Whether a level has rows enough to be given by its name."""
    return count >= minimum


def _mean_sd(values: list[float]) -> tuple[Figure, Figure]:
    n = len(values)
    mean = math.fsum(values) / n
    spread = math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (n - 1))
    return figure(mean), figure(spread)


def _month(iso: str) -> int:
    return int(iso[:4]) * 12 + int(iso[5:7]) - 1


def _month_shown(month: int) -> str:
    return f"{month // 12:04d}-{month % 12 + 1:02d}"


def _distribution(column: _Column, rows: int | None, minimum: int) -> dict:
    """What a number, date or time column gives beyond its missing values."""
    if column.role == "number":
        read = [quality.number_of(item) for item in column.present]
    elif column.role == "date":
        reader = _date_reader(column.kind, column.form)
        read = [reader(item) for item in column.present]
        read = [None if one is None else _month(one) for one in read]
    else:
        read = [quality.time_of(item) for item in column.present]
        read = [None if one is None else int(one[:2]) for one in read]
    values = [one for one in read if one is not None]
    counts = [column.missing, len(read) - len(values), len(values)]
    shown = held_beside(counts, rows, minimum)
    if shown is None:
        return _withheld(column, rows, minimum, held=True)
    missing, unread, n = shown
    out = _missing(column, missing, rows, minimum) | {"unread": unread, "n": n}
    enough = len(values) >= minimum
    if column.role == "number":
        if len(values) >= max(minimum, FEWEST_FOR_MEAN):
            out["mean"], out["sd"] = _mean_sd(values)
        if enough and values:
            whole = column.kind == "count"
            out["decimals"] = 0 if whole else _decimals(
                [item for item, one in zip(column.present, read, strict=True) if one is not None])
        out["centiles"] = _centiles(values, minimum, figure)
    elif column.role == "date":
        out["centiles"] = _centiles(values, minimum, _month_shown)
    else:
        out["centiles"] = _centiles(values, minimum, lambda hour: f"{hour:02d}:00")
    return out


def _missing(column: _Column, shown: object, rows: int | None, minimum: int) -> dict:
    out: dict = {"missing": shown}
    share = _share(column.missing, shown, rows or 0, minimum)
    if share is not None:
        out["missing_share"] = share
    return out


def _levels(column: _Column, rows: int | None, minimum: int) -> dict:
    """Each level of `minimum` rows or more with its count, in the dictionary's order and
    then in the order of their text; the rest folded into "other"."""
    counted = Counter(quality.text_of(item) for item in column.present)
    listed = [coded.code for coded in column.variable.values] if column.variable else []
    rank = {code: at for at, code in enumerate(dict.fromkeys(listed))}
    order = sorted(counted, key=lambda level: (rank.get(level, len(rank)), level))
    kept = [level for level in order if _kept(counted[level], minimum)]
    folded = [level for level in order if not _kept(counted[level], minimum)]
    counts = [counted[level] for level in kept]
    bounds: list = [None] * len(counts)
    said = None
    if folded:
        counts.append(sum(counted[level] for level in folded))
        said, bound = _other_bounds(len(folded), counts[-1], minimum)
        bounds.append(bound)
    shown = held_beside([*counts, column.missing], rows, minimum, [*bounds, None])
    if shown is None:
        return _withheld(column, rows, minimum, held=True)
    *shown, missing = shown
    out = _missing(column, missing, rows, minimum)
    out["levels"] = [{"level": level, "count": count}
                     for level, count in zip(kept, shown, strict=False)]  # fmt: skip
    if folded:
        out["other"] = {"levels": said, "count": shown[-1]}
    return out


def _other_bounds(levels: int, count: int, minimum: int) -> tuple[int | None, tuple | None]:
    """How many levels "other" is said to fold, and what that says of its count: at least
    one row each, under the minimum each. Not said where its count is held back and that
    would give it away: `levels` levels of fewer than `minimum` rows in all are `levels` rows
    at least, and `minimum` - 1 at most."""
    if count < minimum and levels >= minimum - 1:
        return None, None
    return levels, (levels, levels * (minimum - 1))


def shape_of(text: str) -> str:
    """A value's pattern: 9 for a digit, A and a for a letter in each case, ? for any other
    letter than ASCII's, every other character as it is."""
    return "".join(
        "9" if "0" <= char <= "9" else "A" if "A" <= char <= "Z" else "a" if "a" <= char <= "z"
        else char if char.isascii() else "?"
        for char in text
    )


def _withheld(column: _Column, rows: int | None, minimum: int, held: bool = False) -> dict:
    """A column given nothing of its values: its missing values, and where it is withheld by
    its kind, the pattern its values share; where by its counts, why."""
    present = len(column.present)
    shown = held_beside([column.missing, present], rows, minimum, hidden=(1,))
    assert shown is not None  # the present rows are never printed, so nothing is worked out
    out: dict = {"kind": "withheld"} if held else {}
    out |= _missing(column, shown[0], rows, minimum)
    if held:
        out["held"] = HELD
        return out
    shapes = {shape_of(quality.text_of(item)) for item in column.present}
    if present >= minimum and len(shapes) == 1:
        out["pattern"] = shapes.pop()
    return out


def _column(column: _Column, rows: int | None, minimum: int) -> dict:
    out: dict = {"name": column.name, "type": column.kind,
                 "typed_by": "dictionary" if column.variable else "values", "kind": column.role}
    if column.role == "levels":
        given = _levels(column, rows, minimum)
    elif column.role == "withheld":
        given = _withheld(column, rows, minimum)
    else:
        given = _distribution(column, rows, minimum)
    out["kind"] = given.pop("kind", column.role)
    if column.form is not None and out["kind"] == "date":
        out["format"] = column.form
    return out | given


def _read_column(table: quality.Table, name: str, variable: Variable | None,
                 forms: dict[str, str]) -> _Column:  # fmt: skip
    values = table.column(name)
    codes = quality.missing_codes(variable)
    present = [item for item in values if not quality.absent(item, codes)]
    form = forms.get(_unmarked(name))
    kind = variable.type if variable is not None else _type_read(present, form)
    role = _kind(variable, kind, [quality.text_of(item) for item in present])
    if form is not None and role != "date":
        form = None
    return _Column(_unmarked(name), variable, kind, role, form, present,
                   len(values) - len(present))  # fmt: skip


def profile(
    data: object,
    *,
    name: str,
    minimum: int,
    dictionary: Dictionary | None = None,
    dataset: str | None = None,
    read_as: Mapping | None = None,
) -> dict:
    """The profile of a table, as a document for `dumps`."""
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError("profile: the data custodian's minimum cell count is a whole number "
                         "from 1")  # fmt: skip
    check_name(name)
    shape, forms = file_shape(name, read_as)
    table = quality.Table(data)
    variables = {}
    if dictionary is not None:
        variables = {v.name: v for v in quality.variables_of(dictionary, dataset)}
    unknown = sorted(set(forms) - {_unmarked(name) for name in table.names})
    if unknown:
        raise ValueError(f"profile: read_as dates names {', '.join(unknown)}, which the table "
                         "has no column of")  # fmt: skip
    shown = quality.held_back(table.rows, minimum)
    rows = None if shown else table.rows
    names = list(table.names)
    if names and names[0].startswith(_MARK):
        shape["bom"], shape["encoding"] = True, "utf-8"
    columns = [
        _column(_read_column(table, column, variables.get(_unmarked(column)), forms), rows,
                minimum)
        for column in names
    ]
    return {"schema": SCHEMA, "name": name, "dataset": dataset, "minimum_cell_count": minimum,
            "rows": shown or table.rows, "file": shape, "columns": columns}  # fmt: skip


def _unmarked(name: str) -> str:
    return name[len(_MARK):] if name.startswith(_MARK) else name


# --------------------------------------------------------------------------- the JSON


def dumps(document: object, indent: int = 0) -> str:
    """The profile as JSON, two spaces to a level, as the R emitter writes it too: a
    `Figure` as it is, a text as Python's `json` writes it with its characters kept."""
    pad = " " * indent
    inner = " " * (indent + 2)
    if document is None:
        return "null"
    if document is True or document is False:
        return "true" if document else "false"
    if isinstance(document, Figure):
        return str(document)
    if isinstance(document, int):
        return str(document)
    if isinstance(document, str):
        return json.dumps(document, ensure_ascii=False)
    if isinstance(document, Mapping):
        if not document:
            return "{}"
        items = [f"{inner}{json.dumps(str(key), ensure_ascii=False)}: {dumps(value, indent + 2)}"
                 for key, value in document.items()]  # fmt: skip
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(document, (list, tuple)):
        if not document:
            return "[]"
        items = [f"{inner}{dumps(value, indent + 2)}" for value in document]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    raise TypeError(f"profile: cannot write a {type(document).__name__}")


def write(root: Path, document: dict) -> Path:
    path = path_of(root, document["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((dumps(document) + "\n").encode("utf-8"))
    return path


def minimum_of(root: Path) -> int:
    """The data custodian's minimum cell count, refused where `paper.yaml` declares none."""
    minimum = quality.minimum_cell_count(root)
    if minimum is None or minimum < 1:
        raise ValueError(
            "profile: paper.yaml declares no `custodian: {minimum_cell_count: N}`, and every "
            "count of the profile is held to it: write the custodian's, or 1 where there is "
            "no rule"
        )
    return minimum


def dictionary_of(root: Path) -> Dictionary | None:
    """The project's data dictionary where it has one, refused where it does not read."""
    from manuscript_guard.contracts.dictionary import load_dictionary

    dictionary, report = load_dictionary(root)
    if report.findings:
        listed = "; ".join(finding.message for finding in report.findings[:5])
        raise ValueError(f"profile: the data dictionary does not read: {listed}")
    return dictionary
