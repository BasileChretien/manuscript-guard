"""`vault synthesize`: the synthetic copy of a file of the vault, drawn from its released
profile.

It reads the released profile (`profiles/data/<name>.profile.json`), the data dictionary and
a seed (`profiles/data/<name>.synthetic.yaml`, written on first use and kept after), and
nothing else: never the data. So it discloses what the profile disclosed and no more, and
anyone may run it, the agent included. It writes `data/synthetic/<name>` in the profile's
shape (its columns in order, delimiter, decimal mark, quoting, line ending, encoding, date
formats), as CSV or TSV.

Each column is drawn alone:

* a level by the released counts, the levels folded into "other" as one level named `other`;
* a number, date or time by the inverse of the distribution the released centiles draw,
  straight between them and continued straight beyond the outer two, so that no real
  smallest or largest value is made; with fewer than two centiles, evenly about the mean
  with its SD, or the one value given;
* a missing value at the released rate;
* an identifier by its released pattern, its letters X and its last run of digits the row's
  number after a 9, and with no pattern `SYN` and the row's number.

A row that breaks a rule of the dictionary across variables (an order, a key that must be
unique) is drawn again, up to `REDRAWS` times, and then the copy is refused, naming the
rule. A variable that applies only where another holds certain codes is left empty
elsewhere. Only `random.Random(seed).random()` is drawn from, and only exact arithmetic and
Python's own formatting turn it into text, so that the same profile and seed give the same
bytes on every platform.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path, PurePosixPath

from manuscript_guard import quality
from manuscript_guard.contracts.dictionary import Dictionary, Variable
from manuscript_guard.vault import profile as profiling

SEED_SCHEMA = "manuscript-guard/synthetic/1"
SEED_SUFFIX = ".synthetic.yaml"
#: Where the synthetic copies are written, in the project.
OUT = PurePosixPath("data/synthetic")
#: The formats a copy is written in.
FORMATS = ("csv", "tsv")
#: Rows drawn where the profile holds the table's rows back.
DEFAULT_ROWS = 1000
#: How many times a row that breaks a rule is drawn again before the copy is refused.
REDRAWS = 1000
#: The largest seed written on first use.
_SEEDS = 2**31 - 1
_SECONDS = 24 * 60 * 60


class Refused(Exception):
    """Why no copy was written, in a sentence for whoever ran it."""


# --------------------------------------------------------------------------- the inputs


def _read_profile(path: Path) -> dict:
    from jsonschema import Draft202012Validator

    from manuscript_guard.contracts._schema import load_schema

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"{path.name} does not read as JSON: {exc}") from exc
    errors = list(Draft202012Validator(load_schema("data-profile")).iter_errors(document))
    if errors:
        where = "/".join(str(part) for part in errors[0].absolute_path) or "(root)"
        raise Refused(f"{path.name} is not a data profile: {where}: {errors[0].message}")
    return document


def _seed_of(root: Path, name: str, rows: object) -> tuple[int, int, bool]:
    """The seed and the rows to draw, from the seed file, written where there is none."""
    import yaml

    path = seed_path(root, name)
    if path.exists():
        try:
            kept = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise Refused(f"{path.name} does not read: {exc}") from exc
        seed, count = (kept or {}).get("seed"), (kept or {}).get("rows")
        whole = [isinstance(one, int) and not isinstance(one, bool) and one >= 0
                 for one in (seed, count)]  # fmt: skip
        if not isinstance(kept, dict) or kept.get("schema") != SEED_SCHEMA or not all(whole):
            raise Refused(f"{path.name} is not a seed file: it says `schema: {SEED_SCHEMA}`, "
                          "and a seed and the rows to draw, each a whole number")  # fmt: skip
        return seed, count, False
    seed = random.SystemRandom().randrange(1, _SEEDS)
    count = rows if isinstance(rows, int) else DEFAULT_ROWS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((
        f"# The seed `manuscript-guard vault synthesize` drew data/synthetic/{name} from.\n"
        "# Kept, so that the same profile and seed give the same copy; change the seed, or\n"
        "# the rows, to draw another.\n"
        f"schema: {SEED_SCHEMA}\nseed: {seed}\nrows: {count}\n").encode())  # fmt: skip
    return seed, count, True


def seed_path(root: Path, name: str) -> Path:
    return root.joinpath(*profiling.FOLDER.parts,
                         *(profiling.check_name(name) + SEED_SUFFIX).split("/"))  # fmt: skip


def names_in(root: Path) -> list[str]:
    """The name of each profile the project holds."""
    folder = root.joinpath(*profiling.FOLDER.parts)
    if not folder.is_dir():
        return []
    return sorted(path.relative_to(folder).as_posix()[: -len(profiling.SUFFIX)]
                  for path in folder.rglob("*" + profiling.SUFFIX))  # fmt: skip


# ------------------------------------------------------------------------ one column


def _estimates(shown: list, total: int | None, minimum: int) -> list[float]:
    """What each count of a column is taken to be: itself where printed; where held back,
    an even share of what the total leaves, no more than the minimum allows behind "<m"."""
    known = sum(one for one in shown if isinstance(one, int))
    held = [at for at, one in enumerate(shown) if not isinstance(one, int)]
    left = max(total - known, 0) if total is not None else None
    out = [float(one) if isinstance(one, int) else 0.0 for one in shown]
    for at in held:
        if left is None:
            out[at] = minimum / 2
        elif shown[at] is None:
            out[at] = left / len(held)
        else:
            out[at] = min(left / len(held), minimum - 1)
    unbounded = [at for at in held if shown[at] is None]
    if left is not None and unbounded:
        rest = left - sum(out[at] for at in held if shown[at] is not None)
        for at in unbounded:
            out[at] = max(rest, 0.0) / len(unbounded)
    return out


def _pick(u: float, weights: list[float]) -> int:
    """The place `u` falls at among the weights, each its share of their sum."""
    whole = sum(weights)
    if whole <= 0:
        return min(int(u * len(weights)), len(weights) - 1)
    reached = 0.0
    for at, weight in enumerate(weights):
        reached += weight / whole
        if u < reached:
            return at
    return max(at for at, weight in enumerate(weights) if weight > 0)


def _inverse(points: list[tuple[float, float]], u: float) -> float:
    """The value at `u` of the straight lines through the centiles, continued beyond them."""
    if u <= points[0][0]:
        (p0, q0), (p1, q1) = points[0], points[1]
    elif u >= points[-1][0]:
        (p0, q0), (p1, q1) = points[-2], points[-1]
    else:
        at = next(at for at in range(1, len(points)) if u <= points[at][0])
        (p0, q0), (p1, q1) = points[at - 1], points[at]
    return q0 + (u - p0) * (q1 - q0) / (p1 - p0)


@dataclass
class _Drawn:
    """One column's value in a row: as rules read it, and as written."""

    value: object
    text: str


@dataclass
class _Column:
    spec: dict
    variable: Variable | None
    minimum: int
    total: int | None
    weights: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        kind = self.spec["kind"]
        if kind == "levels":
            shown = [one["count"] for one in self.spec["levels"]]
            if "other" in self.spec:
                shown.append(self.spec["other"]["count"])
            shown.append(self.spec["missing"])
        elif kind == "withheld":
            shown = [self.spec["missing"], None]
        else:
            shown = [self.spec["missing"], self.spec["unread"], self.spec["n"]]
        self.weights = _estimates(shown, self.total, self.minimum)

    @property
    def name(self) -> str:
        return self.spec["name"]


# --------------------------------------------------------------------- drawing a value


def _number(column: _Column, u: float, shape: dict) -> _Drawn | None:
    spec = column.spec
    points = [(int(c) / 100, float(v)) for c, v in spec["centiles"].items()]
    if len(points) >= 2:
        value = _inverse(points, u)
    elif "mean" in spec and "sd" in spec:
        half = math.sqrt(3) * float(spec["sd"])
        value = float(spec["mean"]) - half + 2 * half * u
    elif points:
        value = points[0][1]
    elif "mean" in spec:
        value = float(spec["mean"])
    else:
        return None
    variable = column.variable
    whole = spec["type"] == "count"
    if variable is not None:
        low, high = (quality.number_of(variable.minimum), quality.number_of(variable.maximum))
        value = max(value, low) if low is not None else value
        value = min(value, high) if high is not None else value
    if whole:
        value = max(value, 0.0)
    places = 0 if whole else spec.get("decimals", 0)
    text = format(value, f".{places}f")
    if text.lstrip("-").strip("0.") == "":
        text = text.lstrip("-")
    shown = text.replace(".", shape["decimal"]) if shape["decimal"] != "." else text
    return _Drawn(float(text), shown)


def _days_in(year: int, month: int) -> int:
    after = date(year + month // 12, month % 12 + 1, 1)
    return (after - date(year, month, 1)).days


def _month_value(text: str) -> float:
    return int(text[:4]) * 12 + int(text[5:7]) - 1


def render(form: str, parts: dict[str, int]) -> str:
    """A date and time written in a format of `%Y %m %d %H %M %S`."""
    widths = profiling._DIRECTIVES
    out, at = [], 0
    while at < len(form):
        if form[at] == "%" and form[at + 1:at + 2] in widths:
            code = form[at + 1]
            out.append(f"{parts[code]:0{widths[code]}d}")
            at += 2
        elif form[at] == "%" and form[at + 1:at + 2] == "%":
            out.append("%")
            at += 2
        else:
            out.append(form[at])
            at += 1
    return "".join(out)


def _date(column: _Column, u: float, clock: float) -> _Drawn | None:
    spec = column.spec
    points = [(int(c) / 100, _month_value(v)) for c, v in spec["centiles"].items()]
    if len(points) >= 2:
        month = _inverse(points, u)
    elif points:
        month = points[0][1] + 0.5
    else:
        return None
    index = math.floor(month)
    year, month_ = divmod(index, 12)
    if not 1 <= year <= 9999:
        year, month_ = min(max(year, 1), 9999), 0 if year < 1 else 11
    days = _days_in(year, month_ + 1)
    day = min(1 + math.floor((month - index) * days), days)
    seconds = min(math.floor(clock * _SECONDS), _SECONDS - 1)
    parts = {"Y": year, "m": month_ + 1, "d": day, "H": seconds // 3600,
             "M": seconds // 60 % 60, "S": seconds % 60}  # fmt: skip
    timed = spec["type"] == "datetime"
    default = "%Y-%m-%d %H:%M:%S" if timed else "%Y-%m-%d"
    iso = render("%Y-%m-%dT%H:%M:%S" if timed else "%Y-%m-%d", parts)
    return _Drawn(iso, render(spec.get("format", default), parts))


def _time(column: _Column, u: float) -> _Drawn | None:
    points = [(int(c) / 100, int(v[:2])) for c, v in column.spec["centiles"].items()]
    if len(points) >= 2:
        hours = _inverse(points, u)
    elif points:
        hours = points[0][1] + 0.5
    else:
        return None
    minutes = min(max(math.floor(hours * 60), 0), 24 * 60 - 1)
    text = f"{minutes // 60:02d}:{minutes % 60:02d}"
    return _Drawn(text, text)


def identifier(pattern: str | None, row: int) -> str:
    """An identifier of the released pattern, or `SYN` and the row's number: its letters X,
    any other letter X, and in its last run of digits the row's number after a 9, the runs
    before it 9s."""
    number = str(row)
    if not pattern:
        return f"SYN{number}"
    runs = [at for at, char in enumerate(pattern) if char == "9"]
    last: list[int] = []
    for at in reversed(runs):
        if last and at != last[-1] - 1:
            break
        last.append(at)
    last.reverse()
    digits = number.zfill(len(last))[-len(last):] if last else ""
    if len(last) >= 2 and len(number) < len(last):
        digits = "9" + number.zfill(len(last) - 1)
    fill = dict(zip(last, digits, strict=True))
    return "".join(fill.get(at, {"9": "9", "A": "X", "a": "x", "?": "X"}.get(char, char))
                   for at, char in enumerate(pattern))  # fmt: skip


def _withheld(column: _Column, row: int) -> _Drawn:
    kind = column.spec["type"]
    if kind in ("continuous", "count") and "pattern" not in column.spec:
        return _Drawn(float(row), str(row))
    if kind in ("date", "datetime"):
        day = (date(2000, 1, 1) + timedelta(days=row - 1)).isoformat()
        return _Drawn(day, day)
    if kind == "time":
        return _Drawn("00:00", "00:00")
    text = identifier(column.spec.get("pattern"), row)
    return _Drawn(text, text)


def _draw(column: _Column, row: int, u, shape: dict) -> _Drawn | None:
    """One value of a column, or None for a missing one."""
    kind = column.spec["kind"]
    cell = _pick(u(), column.weights)
    if kind == "levels":
        levels = [one["level"] for one in column.spec["levels"]]
        if "other" in column.spec:
            levels.append("other")
        return _Drawn(levels[cell], levels[cell]) if cell < len(levels) else None
    if cell == 0:
        return None
    if kind == "withheld":
        return _withheld(column, row)
    if kind == "number":
        return _number(column, u(), shape)
    if kind == "date":
        return _date(column, u(), u())
    return _time(column, u())


# ------------------------------------------------------------------------------ rules


@dataclass
class _Rules:
    """The rules of the dictionary across the columns drawn."""

    order: list = field(default_factory=list)
    unique: list = field(default_factory=list)
    applies: list = field(default_factory=list)
    seen: dict = field(default_factory=dict)

    def broken(self, values: dict[str, object]) -> str | None:
        for rule, variables in self.order:
            if quality.check_order(variables, [[values[v.name]] for v in variables]):
                return rule.id
        for rule, variables in self.unique:
            if self._key(variables, values) in self.seen[rule.id]:
                return rule.id
        return None

    def _key(self, variables: list[Variable], values: dict) -> tuple | None:
        items = [values[v.name] for v in variables]
        if any(item is None for item in items):
            return None
        return tuple(quality._key_text(v, item) for v, item in zip(variables, items, strict=True))

    def keep(self, values: dict[str, object]) -> None:
        for rule, variables in self.unique:
            key = self._key(variables, values)
            if key is not None:
                self.seen[rule.id].add(key)


def _rules(dictionary: Dictionary | None, names: set[str]) -> tuple[_Rules, list[str]]:
    rules, notes = _Rules(), []
    if dictionary is None:
        return rules, notes
    for rule in dictionary.rules:
        ruled = rule.order or rule.unique
        if rule.computed:
            notes.append(f"rule {rule.id} is computed by the analysis, and is not held here")
        elif ruled and set(ruled) <= names:
            variables = [dictionary.variable(name) for name in ruled]
            (rules.order if rule.order else rules.unique).append((rule, variables))
            rules.seen.setdefault(rule.id, set())
    for variable in dictionary.variables:
        condition = variable.applies_if
        if variable.name in names and condition is not None and condition.variable in names:
            rules.applies.append((variable.name, condition.variable, frozenset(condition.codes)))
    return rules, notes


# ------------------------------------------------------------------------------ the copy


@dataclass
class Copy:
    """What `synthesize` wrote, or would write."""

    name: str
    path: Path
    rows: int
    seed: int
    seeded: bool
    notes: list[str]


def _row(columns: list[_Column], rules: _Rules, row: int, u, shape: dict) -> list[str]:
    for _ in range(REDRAWS):
        drawn = {column.name: _draw(column, row, u, shape) for column in columns}
        for name, other, codes in rules.applies:
            value = drawn[other]
            if value is None or value.text not in codes:
                drawn[name] = None
        values = {name: None if one is None else one.value for name, one in drawn.items()}
        broken = rules.broken(values)
        if broken is None:
            rules.keep(values)
            return ["" if drawn[c.name] is None else drawn[c.name].text for c in columns]
    raise Refused(f"row {row} broke rule {broken} of the data dictionary in each of "
                  f"{REDRAWS} draws: the released profile cannot be drawn to meet it")  # fmt: skip


def _written(header: list[str], rows: list[list[str]], shape: dict) -> bytes:
    text = io.StringIO()
    quoting = csv.QUOTE_ALL if shape["quoting"] == "all" else csv.QUOTE_MINIMAL
    writer = csv.writer(text, delimiter=shape["delimiter"], quoting=quoting,
                        lineterminator=shape["newline"])  # fmt: skip
    writer.writerow(header)
    writer.writerows(rows)
    try:
        return text.getvalue().encode(shape["encoding"])
    except (LookupError, UnicodeError) as exc:
        raise Refused(f"the copy cannot be written in {shape['encoding']}: {exc}") from exc


def synthesize(root: Path, name: str) -> Copy:
    """Draw the synthetic copy of `name` from its released profile, and write it."""
    path = profiling.path_of(root, name)
    if not path.is_file():
        raise Refused(f"no released profile of {name} at {path.relative_to(root).as_posix()}: "
                      "the profile script writes it under `vault run`, and a person releases "
                      "it")  # fmt: skip
    document = _read_profile(path)
    if document["name"] != name:
        raise Refused(f"{path.name} is the profile of {document['name']}, not of {name}")
    shape = document["file"]
    if shape["format"] not in FORMATS:
        raise Refused(f"{name} is a .{shape['format'] or '(no extension)'} file, and the copy is "
                      "written as CSV or TSV only: export the extract to CSV inside the vault, "
                      "register that, and profile it")  # fmt: skip
    dictionary = profiling.dictionary_of(root)
    seed, count, seeded = _seed_of(root, name, document["rows"])
    total = document["rows"] if isinstance(document["rows"], int) else None
    minimum = document["minimum_cell_count"]
    columns = [_Column(spec, dictionary.variable(spec["name"]) if dictionary else None,
                       minimum, total) for spec in document["columns"]]  # fmt: skip
    rules, notes = _rules(dictionary, {column.name for column in columns})
    u = random.Random(seed).random
    rows = [_row(columns, rules, row, u, shape) for row in range(1, count + 1)]
    out = root.joinpath(*OUT.parts, *name.split("/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_written([column.name for column in columns], rows, shape))
    return Copy(name, out, count, seed, seeded, notes)


def command(root: Path, names: list[str]) -> int:
    """`vault synthesize [NAME ...]`: each copy named, or one for each profile released."""
    import sys

    prefix = "manuscript-guard: vault synthesize"
    wanted = names or names_in(root)
    if not wanted:
        print(f"{prefix}: no released profile in {profiling.FOLDER}/: the profile script "
              "writes one under `vault run`, and a person releases it", file=sys.stderr)
        return 2
    failed = False
    for name in wanted:
        try:
            copy = synthesize(root, name)
        except (Refused, ValueError) as exc:
            print(f"{prefix}: {name}: refused, nothing written: {exc}", file=sys.stderr)
            failed = True
            continue
        seeded = "a new seed, written to" if copy.seeded else "the seed in"
        print(f"{prefix}: wrote {copy.path.relative_to(root).as_posix()}, {copy.rows} rows, "
              f"drawn with {seeded} {seed_path(root, name).relative_to(root).as_posix()} from "
              "the released profile alone: its columns are drawn apart, so a model fitted on "
              "it shows nothing of the data")  # fmt: skip
        for note in copy.notes:
            print(f"{prefix}: {name}: {note}")
    return 2 if failed else 0
