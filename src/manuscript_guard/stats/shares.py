"""A count and its share, n (%), as a paper's table prints them, against the denominator the
table names.

"640 (53.3)" under "Exposed (n = 1200)" says 640 of 1200, and 640 of 1200 is 53.33%. A
count copied from another row, a share from another column, or a denominator changed after
the table was made leaves the two apart. In a paper checked with `audit` nothing the
analysis computed binds them, so they are held to each other: the share the count gives of
its denominator against the share printed, within half a unit of its last printed place.

* **A cell is read as a count and its share** where it is a whole number and a number in
  brackets after it: "640 (53.3)", "640 (53.3%)", "640 [53.3]", or with its own
  denominator, "640/1200 (53.3)". The first column is the rows' labels, and never read so.
* **Only a column of shares is read.** A row whose label, or the label of the rows it falls
  under, names a mean, a median, an SD, an IQR or a range is never read, nor a column whose
  header names one: mean (SD) and median (IQR) never fire. Of the rest, a cell is read where
  something says it is a share: a "%" in the cell, in the row's label, in the label of the
  rows it falls under or in its column's header; or the shares of its column add up to about
  100 over a run of rows, the categories of one characteristic.
* **The denominator is the cell's own, or its column's**: the "n = N" of the column's header,
  the nearest above it in a row with no count in it. With neither, nothing is checked.
* **A share of the row is not wrong.** Where a row's shares add up to about 100 across its
  columns, it is read as shares of the row's total as well, and is off only where neither
  reading gives the share printed.
* **A row whose label carries a footnote marker is uncertain**: a note under the table may
  give it another denominator, those with data, say. It is listed, and says so.

A share off from its denominator says which denominators it fits: 54.2 is 640 of 1179 to
1182, which is what a share of those with data looks like.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from manuscript_guard.text.tables import Table, TableCell

_SPACES = "\N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE} "
#: A whole number, with its thousands apart or not.
_COUNT = rf"(?:\d{{1,3}}(?:[,{_SPACES}]\d{{3}})+(?![\d.])|\d+(?![\d.,]))"
_SHARE = re.compile(
    rf"(?P<count>{_COUNT})(?:\s*/\s*(?P<over>{_COUNT}))?\s*[(\[]\s*"
    r"(?P<percent>\d{1,3}(?:\.\d+)?)\s*(?P<sign>%)?\s*[)\]]"
)
#: A denominator a header or a label names: "n = 1200", "(N=1,200)".
_N = re.compile(rf"(?<![A-Za-z])[nN]\s*=\s*(?P<n>{_COUNT})")
#: What says a number in brackets is not a share. Read before a "%": a label that names a
#: mean and an n (%) is read as neither.
_NOT_A_SHARE = re.compile(
    r"\b(?:mean|median|SD|SE|SEM|s\.d\.|standard\s+(?:deviation|error)|IQR|interquartile"
    r"|range|min(?:imum)?|max(?:imum)?|CI|percentiles?|quartiles?)\b",
    re.IGNORECASE,
)
#: A footnote marker: a superscript, `^a^` as Markdown and the table reader write it, a
#: footnote's own `[^1]`, a dagger and its kin, a raised letter; an asterisk, a hash or a
#: raised digit at the end.
_NOTE = re.compile(
    r"\^[^^\s]{1,8}\^|\[\^[^\]\s]+\]|[\N{DAGGER}\N{DOUBLE DAGGER}\N{SECTION SIGN}"
    r"\N{PILCROW SIGN}\N{DOUBLE VERTICAL LINE}ᴬ-ᵪᶛ-ᶿ]"
    r"|[*#\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}⁰-₟]+\s*$"
)
#: Emphasis around a whole cell, `**12 (3.0)**`.
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(?P<inner>.+)\1")
#: How much of a row the context shows.
_CONTEXT = 160


@dataclass(frozen=True)
class Share:
    """A cell read as a count and its share."""

    line: int
    #: The cell as printed: "1,800 (50.0)".
    printed: str
    count: int
    #: As printed, without its sign: "53.3".
    percent: str
    #: The denominator the table names for it: the cell's own, or its column's header's.
    over: int | None
    #: Whether the cell names it, "640/1200 (53.3)".
    own: bool
    #: Where the row's shares add up to about 100 across it, their counts summed.
    row_total: int | None
    #: The row's label, as printed.
    label: str
    #: Why its denominator may be another, where the table says so.
    uncertain: str | None
    context: str


@dataclass(frozen=True)
class _Row:
    """A row with a cell shaped like a count and its share, and what the table said above
    it."""

    cells: tuple[tuple[int, TableCell, re.Match[str]], ...]
    label: str
    group: str
    over: dict[int, int]
    #: Each column whose header says it holds shares (True) or another statistic (False).
    said: dict[int, bool]
    #: Rows with no count between them share a run: the categories of one characteristic.
    run: int
    context: str


def table_shares(table: Table) -> list[Share]:
    """Every cell of `table` read as a count and its share, in reading order."""
    rows = _rows(table)
    summed = _summed(rows)
    found: list[Share] = []
    for row in rows:
        read = [
            (column, cell, match) for column, cell, match in row.cells
            if _a_share(row, column, cell, (row.run, column) in summed)
        ]  # fmt: skip
        total = _row_total([match for _column, _cell, match in read])
        for column, cell, match in read:
            own = match.group("over")
            found.append(Share(
                line=cell.line, printed=" ".join(cell.text.split()),
                count=_whole(match.group("count")),
                percent=match.group("percent"),
                over=_whole(own) if own else row.over.get(column), own=bool(own),
                row_total=total, label=row.label,
                uncertain=_uncertain(row, cell), context=row.context,
            ))  # fmt: skip
    return found


def off(share: Share) -> bool:
    """Whether the share printed is not what the count gives of its denominator, nor of the
    row's total where its row reads as shares of that."""
    if share.over is None:
        return False
    if _fits(share.count, share.over, share.percent):
        return False
    return share.row_total is None or not _fits(share.count, share.row_total, share.percent)


def described(share: Share) -> str:
    """What is wrong with a share that is `off`, and which denominators it would fit."""
    assert share.over is not None
    places = _places(share.percent)
    exact = Fraction(100 * share.count, share.over) if share.over else None
    gives = "no share" if exact is None else f"{float(exact):.{places + 1}f}%"
    said = (
        f"n (%) {share.printed}: {share.count} of {share.over} is {gives}, "
        f"not {share.percent}"
    )
    fits = _denominators(share.count, share.percent)
    if fits is not None:
        low, high = fits
        said += f"; {share.percent}% is {share.count} of {low}" + (
            f" to {high}" if high != low else ""
        )
    if share.uncertain:
        said += f" (uncertain: {share.uncertain})"
    return said


# ------------------------------------------------------------------------------ the rows


def _rows(table: Table) -> list[_Row]:
    rows: list[_Row] = []
    over: dict[int, int] = {}
    said: dict[int, bool] = {}
    group, run = "", 0
    for row in table:
        placed = list(_columns(row))
        label = row[0].text if row else ""
        shaped = tuple(
            (column, cell, match) for column, cell in placed[1:]
            if (match := _SHARE.fullmatch(_clean(cell.text)[0])) is not None
        )  # fmt: skip
        if not shaped:
            run += 1
            if any(cell.text.strip() for _column, cell in placed[1:]):
                group = ""
                for column, cell in placed[1:]:
                    _header(cell, column, over, said)
            elif label.strip():
                group = label
            continue
        context = " | ".join(" ".join(cell.text.split()) for cell in row)
        if len(context) > _CONTEXT:
            context = context[: _CONTEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"
        rows.append(_Row(shaped, label, group, dict(over), dict(said), run, context))
    return rows


def _columns(row: tuple[TableCell, ...]) -> Iterator[tuple[int, TableCell]]:
    """Each cell with the first column it stands in, a cell spanning several counted as
    each of them."""
    column = 0
    for cell in row:
        yield column, cell
        column += max(cell.span, 1)


def _header(cell: TableCell, column: int, over: dict[int, int], said: dict[int, bool]) -> None:
    """What a header cell says of the columns under it: their denominator, where it names
    one, and whether they hold shares."""
    named = {_whole(match.group("n")) for match in _N.finditer(cell.text)}
    for each in range(column, column + max(cell.span, 1)):
        if len(named) == 1:
            over[each] = next(iter(named))
        if _NOT_A_SHARE.search(cell.text):
            said[each] = False
        elif "%" in cell.text:
            said[each] = True


def _barred(row: _Row, column: int) -> bool:
    """Whether the row's label, the label over it or the column's header names another
    statistic."""
    return bool(_NOT_A_SHARE.search(row.label) or _NOT_A_SHARE.search(row.group)) or \
        row.said.get(column) is False  # fmt: skip


def _a_share(row: _Row, column: int, cell: TableCell, summed: bool) -> bool:
    if _barred(row, column):
        return False
    return "%" in cell.text or "%" in row.label or "%" in row.group or \
        row.said.get(column) is True or summed  # fmt: skip


def _summed(rows: list[_Row]) -> set[tuple[int, int]]:
    """Each run and column whose shares add up to about 100: a characteristic's categories,
    with nothing else to say they are shares."""
    printed: dict[tuple[int, int], list[str]] = {}
    for row in rows:
        for column, _cell, match in row.cells:
            if not _barred(row, column):
                printed.setdefault((row.run, column), []).append(match.group("percent"))
    return {where for where, percents in printed.items() if _about_100(percents)}


def _row_total(matches: list[re.Match[str]]) -> int | None:
    percents = [match.group("percent") for match in matches]
    if not _about_100(percents):
        return None
    return sum(_whole(match.group("count")) for match in matches)


def _about_100(percents: list[str]) -> bool:
    """Whether two or more printed shares add up to 100, within what their rounding allows."""
    if len(percents) < 2:
        return False
    total = sum(Fraction(Decimal(p)) for p in percents)
    return abs(total - 100) <= sum(_half(p) for p in percents)


def _uncertain(row: _Row, cell: TableCell) -> str | None:
    if _NOTE.search(row.label):
        return "the row's label carries a footnote marker, and a note may give it another " \
            "denominator"  # fmt: skip
    if _N.search(row.label):
        return "the row's label names an n of its own"
    if _clean(cell.text)[1]:
        return "the cell carries a footnote marker, and a note may give it another denominator"
    if _NOTE.search(row.group) or _N.search(row.group):
        return "the label of the rows it falls under carries a footnote marker or an n of " \
            "its own"  # fmt: skip
    return None


# --------------------------------------------------------------------------- arithmetic


def _whole(printed: str) -> int:
    return int(re.sub(rf"[,{_SPACES}]", "", printed))


def _places(percent: str) -> int:
    return len(percent.partition(".")[2])


def _half(percent: str) -> Fraction:
    """Half a unit in the last printed place: "53.3" stands for 53.25 to 53.35."""
    return Fraction(1, 2 * 10 ** _places(percent))


def _fits(count: int, over: int, percent: str) -> bool:
    if over <= 0:
        return False
    return abs(Fraction(100 * count, over) - Fraction(Decimal(percent))) <= _half(percent)


def _denominators(count: int, percent: str) -> tuple[int, int] | None:
    """The denominators of which `count` is the printed share, lowest and highest, or None
    where there are none or no end to them."""
    printed, half = Fraction(Decimal(percent)), _half(percent)
    if count <= 0 or printed - half <= 0:
        return None
    low = math.ceil(Fraction(100 * count) / (printed + half))
    high = math.floor(Fraction(100 * count) / (printed - half))
    return (low, high) if low <= high else None


def _clean(text: str) -> tuple[str, bool]:
    """A cell's text without the emphasis around it or a footnote marker after it, and
    whether it had a marker."""
    text = " ".join(text.split())
    emphasis = _EMPHASIS.fullmatch(text)
    text = emphasis.group("inner").strip() if emphasis else text
    noted = False
    while text and (marker := _NOTE.search(text)) is not None and marker.end() == len(text):
        text, noted = text[: marker.start()].rstrip(), True
    return text, noted
