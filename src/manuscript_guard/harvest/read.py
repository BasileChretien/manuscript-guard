"""Reading an output file as a table of cells, and each cell as the value it shows.

Three shapes are read, and nothing else:

- a `.csv` or `.tsv` with one header row, every row as wide as the header;
- a `.json` object whose every member is a scalar, read as the two columns `name` and
  `value`, its rows named by `name`: the same table a two-column CSV with `row_key: name`
  gives;
- a `.json` array of objects of scalars, one record a row, which needs `row_key`.

Anything else, a nested object, a list in a record, `true`, NaN, a ragged row, two columns or
rows whose names make one key, is refused rather than flattened by a guess.

A cell's display is the output's own text, stripped of the spaces around it, unless the
entry gives `digits`; then a number is shown to that many places, and a number that would
show as nought is refused, as the emitter refuses it. A cell is read as the emitter reads a
display (`contracts.values`): one number with at most a unit after it is a number, its unit
recorded, a whole number an integer; a comparator in front of one ("<5", "<0.001") is a
number held back, whose value is not known and is recorded as none; anything else is text,
which the emitter then refuses where it carries a number no gate can trace. A cell of the
row key's column is a label, the row's name. An empty cell, or JSON's null, holds nothing.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass

from manuscript_guard.contracts.values import _NUMERIC_DISPLAY, _number_of
from manuscript_guard.harvest.config import Entry, HarvestError

#: The name of an object's members, and of their values, read as a table.
NAME, VALUE = "name", "value"


@dataclass(frozen=True)
class Cell:
    """One cell as the results file records it: its value, its display and its unit."""

    value: object
    display: str
    unit: str | None = None
    label: bool = False


@dataclass(frozen=True)
class Harvest:
    """An output read as a table: its headers as written, the key part each names, and each
    row's name with its cells, None where a cell holds nothing."""

    columns: tuple[str, ...]
    slugs: tuple[str, ...]
    rows: tuple[tuple[str, tuple[Cell | None, ...]], ...]

    def values(self, key: str) -> dict[str, Cell]:
        """Each cell that holds something, under `<key>.<row>.<column>`."""
        return {
            f"{key}.{row}.{column}": cell
            for row, cells in self.rows
            for column, cell in zip(self.slugs, cells, strict=True)
            if cell is not None
        }


def slug(text: str) -> str:
    """A header or a row's name as one part of a results key: its letters and digits, without
    accents, lower case, each run of anything else one underscore."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


class _Number(str):
    """A JSON number as the output wrote it, so that its display is the output's text."""


def _scalar(value: object, where: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return str(value)
    raise HarvestError(f"{where} is {json.dumps(value)[:40]}, which is no number, text or null")


def _unique(pairs: list[tuple[str, object]]) -> dict:
    names = [name for name, _value in pairs]
    twice = sorted({name for name in names if names.count(name) > 1})
    if twice:
        raise HarvestError(f"the member {twice[0]!r} is written twice in one object")
    return dict(pairs)


def _refuse_constant(name: str) -> object:
    raise HarvestError(f"{name} is no number a paper prints")


def records(data: bytes, suffix: str, entry: Entry) -> tuple[list[str], list[list[str | None]]]:
    """The output's headers and rows of cell texts, by its suffix."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HarvestError(f"{entry.output} is not UTF-8 text: {exc}") from exc
    if suffix == ".json":
        return _json_records(text, entry)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t" if suffix == ".tsv" else ",")
    try:
        lines = [row for row in reader if row]
    except csv.Error as exc:
        raise HarvestError(f"{entry.output} cannot be read as {suffix[1:].upper()}: {exc}") from exc
    if not lines:
        raise HarvestError(f"{entry.output} holds no header row")
    header, rows = lines[0], lines[1:]
    for number, row in enumerate(rows, 2):
        if len(row) != len(header):
            raise HarvestError(f"{entry.output}, line {number}: {len(row)} cells under a header "
                               f"of {len(header)}")  # fmt: skip
    return header, [list(row) for row in rows]


def _json_records(text: str, entry: Entry) -> tuple[list[str], list[list[str | None]]]:
    try:
        document = json.loads(
            text, parse_float=_Number, parse_int=_Number, parse_constant=_refuse_constant,
            object_pairs_hook=_unique,
        )  # fmt: skip
    except json.JSONDecodeError as exc:
        raise HarvestError(f"{entry.output} is not JSON: {exc}") from exc
    if isinstance(document, dict):
        if entry.row_key is not None or entry.columns is not None:
            raise HarvestError(f"{entry.output} is one object, read as the columns {NAME!r} and "
                               f"{VALUE!r}: it takes no row_key and no columns")  # fmt: skip
        rows = [[name, _scalar(value, f"{entry.output}: {name!r}")] for name, value in
                document.items()]  # fmt: skip
        return [NAME, VALUE], rows
    if not isinstance(document, list) or not all(isinstance(r, dict) for r in document):
        raise HarvestError(f"{entry.output} is neither an object of scalars nor an array of "
                           "records")  # fmt: skip
    if entry.row_key is None:
        raise HarvestError(f"{entry.output} is an array of records: give row_key, the member "
                           "that names each row")  # fmt: skip
    header: list[str] = []
    for record in document:
        header += [name for name in record if name not in header]
    rows = [[_scalar(record.get(name), f"{entry.output}, record {number}: {name!r}")
             for name in header] for number, record in enumerate(document, 1)]  # fmt: skip
    return header, rows


def cell(text: str | None, digits: int | None, *, label: bool = False) -> Cell | None:
    """What one cell's text shows: None for nothing, a label for a row's name, a number with
    its unit, a number held back, or text."""
    if text is None or not text.strip():
        return None
    shown = text.strip()
    if label:
        return Cell(shown, shown, label=True)
    match = _NUMERIC_DISPLAY.match(shown)
    if match is None:
        return Cell(shown, shown)
    unit = (match.group("unit") or "").strip() or None
    if match.group("compare"):
        return Cell(None, shown, unit)
    number, exponent = _number_of(match)
    value: int | float = int(number) if "." not in number and not exponent else float(number)
    if digits is None:
        return Cell(value, shown, unit)
    return Cell(value, _rounded(match, shown, value, digits), unit)


def _rounded(match: re.Match, shown: str, value: float, digits: int) -> str:
    """`value` to `digits` places, with the sign, the thousands commas and the unit the output
    wrote it with; refused where a number that is not nought would show as nought."""
    ends = [match.end(name) for name in ("number", "exp", "sup") if match.end(name) != -1]
    grouped = "," in match.group("number")
    magnitude = f"{abs(float(value)):{',' if grouped else ''}.{digits}f}"
    if float(value) != 0.0 and float(magnitude.replace(",", "")) == 0.0:
        raise HarvestError(f"{shown!r} to {digits} decimal place(s) shows as {magnitude}, "
                           "which is not this number")  # fmt: skip
    return (match.group("sign") or "") + magnitude + shown[max(ends):]


def read_output(data: bytes, suffix: str, entry: Entry) -> Harvest:
    """The output's bytes, read by `entry`, as the table and the values it records."""
    header, rows = records(data, suffix, entry)
    if suffix == ".json" and header == [NAME, VALUE]:
        row_key: str | None = NAME
    else:
        row_key = entry.row_key
    for name in [*([row_key] if row_key else []), *(entry.columns or ())]:
        if name not in header:
            raise HarvestError(f"{entry.output} has no column {name!r}; its columns are "
                               f"{', '.join(repr(h) for h in header)}")  # fmt: skip
    if isinstance(entry.digits, dict):
        unknown = sorted(set(entry.digits) - set(header))
        if unknown:
            raise HarvestError(f"digits names {unknown[0]!r}, which is no column of "
                               f"{entry.output}")  # fmt: skip
    wanted = list(entry.columns) if entry.columns is not None else list(header)
    if row_key is not None:
        wanted = [row_key, *(name for name in wanted if name != row_key)]
    slugs = _names([slug(name) for name in wanted], wanted, "column", entry)
    at = [header.index(name) for name in wanted]
    named = [_row_name(row, header, row_key, number) for number, row in enumerate(rows, 1)]
    names = _names(named, [str(n) for n in named], "row", entry)
    read = tuple(
        (name, tuple(cell(row[index], entry.digits_for(wanted[place]),
                          label=wanted[place] == row_key) for place, index in enumerate(at)))
        for name, row in zip(names, rows, strict=True)
    )  # fmt: skip
    return Harvest(tuple(wanted), tuple(slugs), read)


def _row_name(row: list[str | None], header: list[str], row_key: str | None, number: int) -> str:
    if row_key is None:
        return str(number)
    named = row[header.index(row_key)]
    if named is None or not named.strip():
        raise HarvestError(f"row {number} has no {row_key!r} to name it")
    return slug(named) or named.strip()


def _names(slugs: list[str], written: list[str], what: str, entry: Entry) -> list[str]:
    """The key parts, refused where one is empty or two are the same."""
    for part, text in zip(slugs, written, strict=True):
        if not re.fullmatch(r"[a-z0-9_]+", part):
            raise HarvestError(f"{entry.output}: the {what} {text!r} names no key: a key part "
                               "is made of letters and digits")  # fmt: skip
    for index, part in enumerate(slugs):
        if part in slugs[:index]:
            first = written[slugs.index(part)]
            raise HarvestError(f"{entry.output}: the {what}s {first!r} and {written[index]!r} "
                               f"both make the key part {part!r}")  # fmt: skip
    return slugs
