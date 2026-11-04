"""What a reader of a profile's column can work out of its counts, and the holding back that
keeps any of them from being worked out.

A column's counts are the whole of the table's rows, which the profile prints. A reader knows
each count by what is printed of it, and by how the profile chose to print it:

* a count printed is itself; printed counts are nought or the minimum or more;
* a count printed "<m" is one to m - 1, since nought is printed as 0
  (`gates.custodian.HELD_LEAST`);
* a count held back beside one held behind the minimum (`None`) was a printed count above
  nought, so the minimum or more, and the smallest of them: at most every count still printed
  after it, and below every count still printed before it, since of two alike the first is
  held;
* what the rest of the column says of a count (`Cell.least`, `Cell.most`): the levels folded
  into "other", the mean and decimals of a number's values, the centiles, the pattern of a
  withheld column's values.

Every choice the profile makes of what to print is made from what it prints: a count is held
beside where any count is held behind the minimum, and one only, the smallest above nought.
A rule that held more only while something could still be worked out would say, by holding,
that it could, and a reader of the column would know the more. So where one count held beside
leaves a count worked out, the column's counts are withheld instead (`unsafe`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

INF = math.inf


@dataclass(frozen=True)
class Cell:
    """One count of a column: what it is, how it is printed (itself, "<m", or None), what
    else a reader knows of it, and whether it is ever printed (the rows a withheld column
    holds are not)."""

    count: int
    shown: object
    least: float = 0
    most: float = INF
    hidden: bool = False


def _printed(cell: Cell) -> bool:
    return isinstance(cell.shown, int) and not isinstance(cell.shown, bool) and not cell.hidden


def known(cell: Cell, total: int, minimum: int) -> tuple[float, float]:
    """What a reader knows a count to be from how it is printed and the rest of the column."""
    from manuscript_guard.gates import custodian

    if _printed(cell):
        return cell.shown, cell.shown
    if cell.shown is None:
        low, high = 0, total
    else:
        low, high = custodian.HELD_LEAST, minimum - 1
    return max(low, cell.least), min(high, cell.most)


def ranges(cells: Sequence[Cell], total: int, minimum: int) -> list[tuple[float, float]]:
    """What a reader works out each count to be, beside the total: each from what is known of
    it, and the total less what the others can be."""
    own = [known(cell, total, minimum) for cell in cells]
    lows = math.fsum(low for low, _high in own)
    highs = math.fsum(high for _low, high in own)
    out = []
    for low, high in own:
        out.append((max(low, total - (highs - high)), min(high, total - (lows - low))))
    return out


def unsafe(cells: Sequence[Cell], total: int, minimum: int) -> bool:
    """Whether a reader works out a count the column does not print: one printed "<m" or held
    back, to a single value; or one never printed to a value under the minimum."""
    for cell, (low, high) in zip(cells, ranges(cells, total, minimum), strict=True):
        if _printed(cell) or low != high:
            continue
        if not cell.hidden or 1 <= low < minimum:
            return True
    return False


def beside_bounds(cells: Sequence[Cell], chosen: int, minimum: int) -> tuple[float, float]:
    """What a reader knows of the count held back beside one held behind the minimum: it was
    printed, so the minimum or more; and it was the smallest printed above nought, so at most
    each count printed after it and below each printed before it."""
    most = INF
    for at, cell in enumerate(cells):
        if at != chosen and _printed(cell) and cell.shown > 0:
            most = min(most, cell.shown - 1 if at < chosen else cell.shown)
    return minimum, most


def beside(cells: Sequence[Cell], minimum: int) -> list[Cell]:
    """Where a count is held behind the minimum, the smallest count printed above nought is
    held back beside it, with what a reader knows of it; else the cells as they are."""
    cells = list(cells)
    if not any(isinstance(cell.shown, str) for cell in cells):
        return cells
    candidates = [at for at, cell in enumerate(cells) if _printed(cell) and cell.count > 0]
    if not candidates:
        return cells
    chosen = min(candidates, key=lambda at: (cells[at].count, at))
    least, most = beside_bounds(cells, chosen, minimum)
    held = cells[chosen]
    cells[chosen] = replace(held, shown=None, least=max(held.least, least),
                            most=min(held.most, most))  # fmt: skip
    return cells
