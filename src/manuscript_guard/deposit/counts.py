"""The counts a deposited fragment would publish that the data custodian forbids.

G2 reads the counts the manuscript prints. A deposit publishes more: the whole fragment,
each value beside its display, every table cell, and the cards of the models and variables,
which count the events at each level and the rows a variable is missing from. "<5" in the
paper holds nothing back when the file beside it says 3. So where `paper.yaml` declares the
custodian's minimum, each fragment is read for a count from one to below it:

- a value that is a count as G2 reads one (`is_count`: a whole number with no unit that is
  neither a parameter, a software version nor a label), whatever its display says;
- a table cell, past the first column, that is a whole number alone, over its denominator,
  with its share in brackets, or both: "3", "3/412", "3 (0.7%)", "3/412 (0.7%)", the share
  with a middle dot or a decimal comma or behind a bound, "3 (<1%)" (`count_in_cell`). The
  first column names the rows, and a row named "2" is a category;
- in a model card, the rows it read, used and dropped, its events, and its events at each
  level of each variable;
- in a variable card, the rows it is missing from.

A cell that reads as a count and is none, a reference ratio of 1 typed bare, is said like the
rest, and the data custodian signs the list off where it is acceptable to them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import RESULTS, Value
from manuscript_guard.findings import FAIL, Finding
from manuscript_guard.gates.custodian import is_count, minimum_cell_count
from manuscript_guard.sign_offs import Signable, digest_of, settle

GATE = "PACKAGE"
SMALL_COUNTS = f"{GATE}/custodian/small-counts"
ROLE = "data_custodian"

#: A share as a cell writes it in brackets: a number with a point, a middle dot or a decimal
#: comma, a percent sign or none, behind a bound or not ("0.7", "0·7%", "<1%", "≤0,7").
_SHARE = (
    r"[<>\N{LESS-THAN OR EQUAL TO}\N{GREATER-THAN OR EQUAL TO}]?\s*"
    r"\d+(?:[.,\N{MIDDLE DOT}]\d+)?\s*%?"
)
#: A cell that states one count: the count alone, over its denominator, with its share in
#: brackets, or both ("3/412 (0.7%)", round 1 of #388). The count is a whole number with no
#: sign and no point.
_COUNT_CELL = re.compile(
    rf"\s*(?P<count>\d+)\s*(?:/\s*\d+\s*)?(?:\(\s*{_SHARE}\s*\))?\s*"
)

#: The fields of a model card that count rows or events.
_MODEL_COUNTS = ("n_input", "n_used", "n_dropped", "events")


@dataclass(frozen=True)
class Small:
    """One count below the minimum: the fragment, where in it, and the count."""

    fragment: str
    where: str
    count: int


def read_fragment(path) -> dict:
    """A fragment as the file holds it, or nothing where it is not JSON: the loading of the
    results says so, as `G0`, and `package` refuses while it does."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def count_in_cell(text: str) -> int | None:
    """The count a table cell states, or None where it states none or several."""
    found = _COUNT_CELL.fullmatch(text)
    return int(found["count"]) if found else None


def _whole(number: object) -> int | None:
    return number if isinstance(number, int) and not isinstance(number, bool) else None


def _values(document: dict) -> list[tuple[str, int]]:
    """The counts among the values, read from the file as it would be deposited."""
    out = []
    for key, spec in sorted((document.get("values") or {}).items()):
        if not isinstance(spec, dict):
            continue
        value = Value(key=key, value=spec.get("value"), display=str(spec.get("display")),
                      origin=RESULTS, unit=spec.get("unit"), role=spec.get("role"),
                      label=bool(spec.get("label")))  # fmt: skip
        if is_count(value):
            out.append((key, value.value))
    return out


def _cells(document: dict) -> list[tuple[str, int]]:
    out = []
    for key, table in sorted((document.get("tables") or {}).items()):
        for row_at, row in enumerate(table.get("rows") or [], 1):
            for column_at, cell in enumerate(row[1:], 2):
                count = count_in_cell(str(cell)) if isinstance(cell, (str, int)) else None
                if count is not None:
                    out.append((f"table {key}, row {row_at}, column {column_at}", count))
    return out


def _cards(document: dict) -> list[tuple[str, int]]:
    out = []
    for key, card in sorted((document.get("models") or {}).items()):
        if not isinstance(card, dict):
            continue
        for field in _MODEL_COUNTS:
            if (count := _whole(card.get(field))) is not None:
                out.append((f"model {key}, {field}", count))
        for variable, levels in sorted((card.get("events_by_level") or {}).items()):
            for level, number in sorted((levels or {}).items()):
                if (count := _whole(number)) is not None:
                    out.append((f"model {key}, events_by_level {variable} {level}", count))
    for key, card in sorted((document.get("variables") or {}).items()):
        observed = card.get("observed") if isinstance(card, dict) else None
        if isinstance(observed, dict) and (count := _whole(observed.get("missing"))) is not None:
            out.append((f"variable {key}, missing", count))
    return out


def small_counts(project: Project, results: Results) -> list[Small]:
    """Every count below the custodian's minimum in the fragments as they would be deposited,
    in the order of the fragments and of the keys."""
    minimum = minimum_cell_count(project)
    if minimum is None:
        return []
    found = []
    for fragment in sorted(results.fragments, key=lambda f: f.path.name):
        document = read_fragment(fragment.path)
        named = fragment.path.relative_to(project.root).as_posix()
        for where, count in _values(document) + _cells(document) + _cards(document):
            if 1 <= count < minimum:
                found.append(Small(named, where, count))
    return found


def small_count_signable(project: Project, results: Results) -> Signable | None:
    """The small counts as one statement the data custodian may sign off, or None where the
    fragments hold none."""
    found = small_counts(project, results)
    if not found:
        return None
    minimum = minimum_cell_count(project)
    findings = tuple(
        Finding(
            gate=GATE,
            code="package-small-count",
            message=f"{small.fragment}: {small.where} is {small.count}, below the data "
            f"custodian's minimum of {minimum}, and the package deposits the fragment whole",
            severity=FAIL,
            path=project.root / small.fragment,
            hint="hold it back in the analysis, as fewer than the minimum or merged with "
            "another category, and run it again",
        )
        for small in found
    )
    digest = digest_of("small-counts", minimum, [(s.fragment, s.where, s.count) for s in found])
    return Signable(ROLE, SMALL_COUNTS, digest, findings)


def settled_small_counts(project: Project, results: Results) -> tuple[Signable | None, tuple]:
    """The signable and its findings as they stand: refused, or signed off."""
    signable = small_count_signable(project, results)
    return signable, (settle(project, signable) if signable else ())


__all__ = ["SMALL_COUNTS", "Small", "count_in_cell", "settled_small_counts", "small_counts"]
