"""A table's totals held to the counts they total, and what a count held back ("<5") still
gives away beside them.

A total printed beside its counts is arithmetic a reader can do, and two things go wrong with
it. A count copied from another row, or a total from another version of the table, and the
row no longer adds up. And a count the data custodian forbids, printed "<5" so that nobody
can name the three patients in it, is three all the same where the row's total and its other
cells are printed: the total less the others is the count. So a table is read here as lines,
each a total and the counts it totals.

* **A count** is a cell that is a whole number, "1,200", or the count of an n (%), its
  share printed or behind a bound, "12 (<0.1)", whether `stats/shares.py` marks the share
  or not, so long as its share is its n over its column's n: a category held back leaves
  the others' shares short of 100, and unmarked (round 1 of #469), and a mean and its SD,
  "54 (12)", is no count (round 2). A count held back, "<5" or "≤4", with its share after
  it in brackets or not, is each whole number from nought to the largest its bound allows
  (`gates.custodian.held_largest`). Nothing else is: a mean, a dash, an empty cell. A row
  whose label, or the label of the rows it falls under, names a mean, a median, an SD or
  another statistic holds no count, nor a row whose label ends on a unit in percent; nor a
  column whose header names one, a P or a ratio by its name ("HR", not "HR+"), or a "%"
  that says no n.
* **The header** is the table's first row, and each row before the first row with a count
  that is words or has no label: a second header row of years, " | 2019 | 2020", is no row
  of counts (round 1 of #469). A row of words further down, "NR | NR", changes no column.
* **A row total** is a row labelled Total, Totals, All or Overall, in any case, and
  nothing else but an "n = 300", an "n (%)", footnote marks and punctuation: "Total cholesterol" and
  "All other drugs" are no totals. In each column it totals the counts of the rows above it,
  back to the last row with no count in it or the last total row.
* **A column total** is a column whose header is such a label. In each row it totals the
  counts of the columns before it, back to the last total column or the column of labels.
  A header spanning several columns is no total of any one of them.
* **A line** is a total and the two or more counts it totals. A line with a cell that is no
  count in it is not read, and nor is one whose total is held back.

`sum_off`: a line whose printed numbers do not add up to its total: the integers' sum is
another, or, where counts are held back, every sum they allow is.

`over_n`: the categories of a characteristic, the rows under a label of their own, whose
shares in a column add up to 100 (`shares._summed`) and whose counts add up to more than
the n its header names. Fewer is what missing data look like, and is not said.

`recovered`: each count held back that a line gives away. Each count of a line is a range,
a printed one a single number; a count's range given the total is the total less the
others' highs, up to the total less the others' lows, within its own. Where that is one
number, the count is disclosed. The categories of a characteristic under a header that
names their column's n are a line too, the header's n their total, which holds only where
none of the column lacks the characteristic: such a line is marked not `explicit`.

Each line is read alone: two lines that disclose a count together, a row and a column, are
not put together (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from manuscript_guard.gates.custodian import _HELD_BACK, held_largest
from manuscript_guard.stats import shares
from manuscript_guard.text.tables import Table, TableCell

#: A label that says its row or column is a total, and what may follow it.
_TOTAL = re.compile(r"(?i)\s*(?:totals?|all|overall)\b(?P<rest>.*)", re.DOTALL)
#: What a total's label may hold after the word once its n is taken out.
_LEFT = re.compile(r"[\s\d,.:;()\[\]=%/*\-\N{EN DASH}\N{EM DASH}]*")
#: An "n" standing alone, "Total, n".
_BARE_N = re.compile(r"(?<![A-Za-z])[nN](?![A-Za-z])")
_WHOLE = re.compile(shares._COUNT)
#: A share in brackets after a count held back, "<5 (<1.2)".
_BRACKETED = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")
#: An n (%) whose share is behind a bound, "12 (<0.1)", "12 (<1%)".
_BOUND_SHARE = re.compile(
    rf"(?P<count>{shares._COUNT})\s*[(\[]\s*"
    r"[<>\N{LESS-THAN OR EQUAL TO}\N{GREATER-THAN OR EQUAL TO}]=?\s*\d*\.?\d+\s*%?\s*[)\]]"
)
#: A header that names a P or a ratio by its name: its column holds no count. "HR+" and
#: "ER-" name a subgroup (round 1 of #469).
_RATIO = re.compile(
    r"(?<![\w+\-\N{MINUS SIGN}(\[])(?:a?OR|a?RR|a?HR|IRR|SMD)(?![\w+\-\N{MINUS SIGN}])"
)
_P = re.compile(r"(?i)(?<![A-Za-z])p(?:[- ]?values?)?(?![A-Za-z])")
#: How much of a row the context shows.
_CONTEXT = 160


@dataclass(frozen=True)
class Count:
    """A count as printed: every number from `low` to `high`, a single one where it is
    printed, from nought to its bound where it is held back."""

    low: int
    high: int
    printed: str
    line: int
    held: bool = False


@dataclass(frozen=True)
class Member:
    """A count of a line, and where it stands: "row 'Women', column 'Cases'"."""

    count: Count
    name: str
    #: The row it is in, as printed.
    context: str = ""


@dataclass(frozen=True)
class Line:
    """A total and the counts it totals."""

    total: Member
    members: tuple[Member, ...]
    #: What the total is: "the 'Total' row, column 'Cases'".
    of: str
    #: What the members are, beside it, one and several: "row above it", "rows above it".
    part: str
    parts: str
    #: Whether the total is printed as one; False where it is the header's n.
    explicit: bool = True
    context: str = ""


@dataclass(frozen=True)
class Recovered:
    """A count held back that a line gives away, and the line."""

    member: Member
    value: int
    line: Line


@dataclass(frozen=True)
class OverN:
    """Categories whose shares add up to 100 and whose counts add up to more than their
    column's n."""

    line: int
    message: str
    context: str


# ------------------------------------------------------------------------------ a count


def count_in(text: str, line: int = 0, *, share: bool = True) -> Count | None:
    """The count a cell or a display prints, or None: a whole number, the n of an n (%)
    unless `share` is False, as it is for a display, or a count held back."""
    cleaned = shares._clean(text)[0]
    printed = " ".join(text.split())
    if _WHOLE.fullmatch(cleaned):
        number = shares._whole(cleaned)
        return Count(number, number, printed, line)
    found = shares._SHARE.fullmatch(cleaned) or _BOUND_SHARE.fullmatch(cleaned)
    if found is not None:
        if not share:
            return None
        number = shares._whole(found["count"])
        return Count(number, number, printed, line)
    head = _BRACKETED.sub("", cleaned)
    held = _HELD_BACK.fullmatch(head)
    largest = held_largest(head)
    # A bound that is a whole number: "<0.001" is a P, and holds no count back.
    if held is None or largest is None or Decimal(held["bound"]) % 1 or largest < 0:
        return None
    return Count(0, largest, printed, line, held=True)


def is_total(text: str) -> bool:
    """Whether a label says its row or column is a total."""
    cleaned = shares._clean(text)[0]
    found = _TOTAL.fullmatch(cleaned)
    if found is None:
        return False
    rest = _BARE_N.sub(" ", shares._SAYS_SHARES.sub(" ", shares._N.sub(" ", found["rest"])))
    return bool(_LEFT.fullmatch(rest))


def _not_counts(text: str) -> bool:
    """Whether a header says its column holds something other than counts."""
    return bool(shares._NOT_A_SHARE.search(text) or _RATIO.search(text) or _P.search(text)) \
        or ("%" in text and not shares._SAYS_SHARES.search(text))  # fmt: skip


def _no_counts(label: str, group: str) -> bool:
    """Whether a row's label, or the label over its rows, says its numbers are no counts."""
    return bool(shares._NOT_A_SHARE.search(label) or shares._NOT_A_SHARE.search(group)) or (
        bool(shares._UNIT.search(label)) and not shares._SAYS_SHARES.search(label))


# ------------------------------------------------------------------------------ the rows


@dataclass(frozen=True)
class _Row:
    label: str
    #: The first column past the label.
    start: int
    counts: dict[int, Count]
    total: bool
    group: str
    categories: bool
    #: Rows with no count between them, and no total row, share a run.
    run: int
    names: dict[int, str]
    totals: frozenset[int]
    barred: frozenset[int]
    over: dict[int, int]
    context: str


@dataclass
class _Head:
    """What the header rows said of each column so far."""

    names: dict[int, str]
    totals: set[int]
    barred: set[int]
    over: dict[int, int]

    def read(self, cell: TableCell, column: int) -> None:
        text = " ".join(cell.text.split())
        if not text:
            return
        span = range(column, column + max(cell.span, 1))
        named = {shares._whole(m["n"]) for m in shares._N.finditer(text)}
        if _marker(text):
            # "n (%)" or "N = 120" under the column's name: its n, and nothing else (round 2
            # of #469: it undid the Total column).
            for each in span if len(named) == 1 else ():
                self.over[each] = next(iter(named))
            return
        for each in span:
            self.names[each] = text
            self.totals.discard(each)
            self.barred.discard(each)
            if _not_counts(text):
                self.barred.add(each)
            if len(named) == 1:
                self.over[each] = next(iter(named))
        if cell.span <= 1 and is_total(text):
            self.totals.add(column)


def _marker(text: str) -> bool:
    """Whether a header cell holds only an n or an n (%) marker: "n (%)", "N = 120"."""
    rest = _BARE_N.sub(" ", shares._SAYS_SHARES.sub(" ", shares._N.sub(" ", text)))
    return bool(_LEFT.fullmatch(rest))


def _says_a_count(cell: TableCell, column: int, over: dict[int, int],
                  marked: frozenset[int]) -> bool:  # fmt: skip
    """Whether a cell shaped like an n (%) is one: `stats/shares.py` reads its share as one,
    or its share is its n over its own denominator or its column's n, within the rounding it
    is printed to. A mean and its SD, "54 (12)", is neither (round 2 of #469)."""
    found = shares._SHARE.fullmatch(shares._clean(cell.text)[0])
    if found is None or id(cell) in marked:
        return True
    denominator = shares._whole(found["over"]) if found["over"] else over.get(column)
    return denominator is not None and shares._fits(shares._whole(found["count"]),
                                                    denominator, found["percent"])


def _a_header(texts: list[str]) -> bool:
    """Whether the cells of a row with no count in it are headers: words, with no number
    but an n."""
    said = [shares._N.sub(" ", text) for text in texts if text.strip()]
    return bool(said) and not any(re.search(r"\d", text) for text in said)


def _heading(index: int, rows: list[_Row], label: str, texts: list[str]) -> bool:
    """Whether a row is the header's: the first, or one before the first row with a count
    that is words or has no label (a row of years under a spanning "Year"). Further down,
    a row of words changes no column (round 1 of #469: "NR | NR" undid the Total column
    for every row below it)."""
    return not index or (not rows and (not label.strip() or _a_header(texts)))


def _rows(table: Table) -> list[_Row]:
    marked = frozenset(id(cell) for _row, read in shares._read(table)
                       for _column, cell, _match, _total in read)  # fmt: skip
    head = _Head({}, set(), set(), {})
    rows: list[_Row] = []
    run, group, categories = 0, "", False
    for index, row in enumerate(table):
        placed = list(shares._columns(row))
        if not placed:
            continue
        label = placed[0][1]
        start = max(label.span, 1)
        others = placed[1:]
        counts: dict[int, Count] = {}
        texts = [cell.text for _column, cell in others]
        heading = _heading(index, rows, label.text, texts)
        if not heading and not _no_counts(label.text, group):
            for column, cell in others:
                if cell.span > 1 or column in head.barred:
                    continue
                count = count_in(cell.text, cell.line)
                if count is not None and _says_a_count(cell, column, head.over, marked):
                    counts[column] = count
        if not counts:
            run += 1
            if heading:
                group, categories = "", False
                for column, cell in others:
                    head.read(cell, column)
            elif label.text.strip() and all(shares._P_ONLY.fullmatch(t) for t in texts):
                group, categories = label.text, True
            else:
                group, categories = "", False
            continue
        context = " | ".join(" ".join(cell.text.split()) for cell in row)
        if len(context) > _CONTEXT:
            context = context[: _CONTEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"
        total = is_total(label.text)
        rows.append(_Row(" ".join(label.text.split()), start, counts, total, group,
                         categories, run, dict(head.names), frozenset(head.totals),
                         frozenset(head.barred), dict(head.over), context))  # fmt: skip
        if total:
            run += 1
    return rows


def _column(row: _Row, column: int) -> str:
    named = row.names.get(column, "")
    return repr(named) if named else f"{column + 1}"


# ----------------------------------------------------------------------------- the lines


def table_lines(table: Table) -> list[Line]:
    """Every line of `table`: its total rows', its total columns', and its characteristics'
    under a header that names their column's n."""
    rows = _rows(table)
    return [*_row_totals(rows), *_column_totals(rows), *_header_lines(rows)]


def _row_totals(rows: list[_Row]) -> Iterable[Line]:
    for at, row in enumerate(rows):
        if not row.total:
            continue
        above = _run_above(rows, at)
        for column, total in sorted(row.counts.items()):
            counts = [other.counts.get(column) for other in above]
            if total.held or len(counts) < 2 or None in counts:
                continue
            name = _column(row, column)
            yield Line(
                Member(total, f"row {row.label!r}, column {name}"),
                tuple(Member(count, f"row {other.label!r}, column {name}", other.context)
                      for other, count in zip(above, counts, strict=True)),  # fmt: skip
                f"the {row.label!r} row, column {name},", "row above it", "rows above it",
                True, row.context,
            )


def _run_above(rows: list[_Row], at: int) -> list[_Row]:
    """The rows a total row totals: those above it back to the last row with no count in it
    or the last total row."""
    return [other for other in rows[:at] if other.run == rows[at].run]


def _column_totals(rows: list[_Row]) -> Iterable[Line]:
    for row in rows:
        before = row.start - 1
        for column in sorted(row.totals):
            if column < row.start:
                continue
            between = _closed_by(row, before, column)
            before = column
            total = row.counts.get(column)
            counts = [row.counts.get(c) for c in between]
            if total is None or total.held or len(counts) < 2 or None in counts:
                continue
            yield Line(
                Member(total, f"row {row.label!r}, column {_column(row, column)}"),
                tuple(Member(count, f"row {row.label!r}, column {_column(row, c)}", row.context)
                      for c, count in zip(between, counts, strict=True)),  # fmt: skip
                f"the {_column(row, column)} column, row {row.label!r},", "cell before it",
                "cells before it", True, row.context,
            )


def _closed_by(row: _Row, before: int, column: int) -> list[int]:
    """The columns a total column totals: those after the last total column or the labels,
    `before`, up to it, bar those whose header names no count."""
    return [c for c in range(before + 1, column) if c not in row.barred]


def _header_lines(rows: list[_Row]) -> Iterable[Line]:
    """The categories of each characteristic, in each column whose header names its n, with
    a count held back among them."""
    runs: dict[int, list[_Row]] = {}
    for row in rows:
        if row.categories and not row.total:
            runs.setdefault(row.run, []).append(row)
    for members in runs.values():
        first = members[0]
        for column, n in sorted(first.over.items()):
            counts = [row.counts.get(column) for row in members]
            if len(counts) < 2 or None in counts or not any(c.held for c in counts):
                continue
            name = _column(first, column)
            group = " ".join(first.group.split())
            total = Count(n, n, f"n = {n}", first.counts[column].line)
            yield Line(
                Member(total, f"column {name}"),
                tuple(Member(count, f"row {row.label!r}, column {name}", row.context)
                      for row, count in zip(members, counts, strict=True)),  # fmt: skip
                f"the header of column {name}", f"category of {group!r}",
                f"categories of {group!r}", False, first.context,
            )


# ---------------------------------------------------------------------- the arithmetic


def feasible(line: Line) -> tuple[tuple[int, int], ...] | None:
    """Each member's range, given the line's total: the total less the others' highs, up to
    the total less the others' lows, within its own. None where no counts the members allow
    add up to the total, which is a sum that is off."""
    total = line.total.count.low
    lows = sum(member.count.low for member in line.members)
    highs = sum(member.count.high for member in line.members)
    if not lows <= total <= highs:
        return None
    return tuple(
        (max(m.count.low, total - (highs - m.count.high)),
         min(m.count.high, total - (lows - m.count.low)))
        for m in line.members
    )  # fmt: skip


def sum_off(line: Line) -> str | None:
    """What is wrong with a line printed as its total, or None: also where it is the
    header's n, which only `over_n` holds counts to."""
    if not line.explicit or feasible(line) is not None:
        return None
    low = sum(member.count.low for member in line.members)
    high = sum(member.count.high for member in line.members)
    adds = f"{low}" if low == high else f"{low} to {high}"
    return (f"{line.of} prints {line.total.count.printed}, and the "
            f"{len(line.members)} {line.parts} add up to {adds}")  # fmt: skip


def recovered(lines: Iterable[Line]) -> list[Recovered]:
    """Each count held back that a line gives away, once, by the first line that does: a
    printed total before the header's n."""
    found: dict[int, Recovered] = {}
    for line in sorted(lines, key=lambda line: not line.explicit):
        ranges = feasible(line)
        for member, (low, high) in zip(line.members, ranges or (), strict=False):
            if member.count.held and low == high and id(member.count) not in found:
                found[id(member.count)] = Recovered(member, low, line)
    return sorted(found.values(), key=lambda one: (one.member.count.line, one.member.name))


def said(found: Recovered) -> str:
    """How a count held back is given away."""
    line = found.line
    others = len(line.members) - 1
    them = (f"the other {line.part} leaves" if others == 1
            else f"the other {others} {line.parts} leave")  # fmt: skip
    return (f"{found.member.count.printed} in {found.member.name} can only be {found.value}: "
            f"{line.of} prints {line.total.count.printed}, and {them} {found.value} of it")


def sums_off(table: Table) -> list[tuple[Line, str]]:
    """Each line of `table` printed as its total that does not add up, with what is wrong:
    a total that is a row's and a column's, the grand total, said once."""
    found: dict[int, tuple[Line, str]] = {}
    for line in table_lines(table):
        wrong = sum_off(line)
        if wrong and id(line.total.count) not in found:
            found[id(line.total.count)] = (line, wrong)
    return list(found.values())


# ------------------------------------------------------------------- the header's n


def over_n(table: Table) -> list[OverN]:
    """The categories of each characteristic whose shares in a column add up to 100 and
    whose counts add up to more than the column's n."""
    rows = shares._rows(table)
    summed = shares._summed(rows)
    head = table[0] if table else ()
    found = []
    for (run, column), (total, _members, _whole) in sorted(summed.items()):
        first = next(row for row in rows if row.run == run)
        n = first.over.get(column)
        if n is None or not _exceeds(total, n):
            continue
        name = next((cell.text for c, cell in shares._columns(head) if c == column), "")
        where = repr(" ".join(name.split())) if name.strip() else f"{column + 1}"
        found.append(OverN(
            first.cells[0][1].line,
            f"the categories of {' '.join(first.group.split())!r} in column {where} add up "
            f"to {total}, more than its n = {n}, and their shares to 100",
            first.context,
        ))  # fmt: skip
    return found


def _exceeds(total: int, n: int) -> bool:
    """Whether categories' counts contradict their column's n: more than it. Fewer is what
    missing data look like."""
    return total > n


__all__ = [
    "Count",
    "Line",
    "Member",
    "OverN",
    "Recovered",
    "count_in",
    "feasible",
    "is_total",
    "over_n",
    "recovered",
    "said",
    "sum_off",
    "sums_off",
    "table_lines",
]
