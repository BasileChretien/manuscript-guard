"""A mean of whole numbers against how many numbers it is the mean of.

The mean of N whole numbers is a whole total over N, so not every mean can be printed for
it: 28 answers on a scale of 1 to 7 average 97/28 = 3.46 or 98/28 = 3.50, never 3.47. This is
the granularity test of Brown and Heathers (*Social Psychological and Personality Science*
2017;8:363-9), for means of integer data such as a Likert-type scale, given the sample size
and the number of items.

* **A mean is possible** where some whole total over N, rounded to the places printed, is
  the mean printed. Rounding either way is allowed: the mean stands for every value within
  half a unit of its last place, both ends included, so 3.465 is 3.47 rounded half up and
  3.46 rounded half to even, and both are taken.
* **N is the sample size times the number of items** each person answered, where the mean
  is of their item means: 28 people answering 3 items give means in steps of 1/84.
* **Where every mean that can be printed is possible for N**, the test says nothing: the
  mean is not assessable. That is so where N is 10 to the power of the places printed or
  more, so two places test samples under 100 and one place under 10. It is also so for a
  few N just under, whose totals and the ties between them, each read both ways, print
  every mean: 8 at one place, 80 and 96 at two, 800, 960 and 992 at three.

What the paper prints is not known to be whole numbers. Nothing here guesses it: the ledger
says so of a value it holds (`mean_of_whole_numbers`), and `audit --whole-numbers` names the
rows of a table that hold means of whole numbers. A table's n is its column's, as for its
shares (`stats/shares.py`).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import cache

from manuscript_guard.stats.shares import _N, _NOTE, _clean, _columns, _whole
from manuscript_guard.text.tables import Table, TableCell

#: A mean as a table cell prints it: alone, with its SD in brackets, or with a plus-minus
#: sign and its SD. A minus sign may stand before it.
_NUMBER = r"\d+(?:\.\d+)?"
_MEAN = re.compile(
    rf"(?P<mean>[-\N{{MINUS SIGN}}]?{_NUMBER})"
    rf"(?:\s*[(\[]\s*{_NUMBER}\s*[)\]]|\s*(?:\N{{PLUS-MINUS SIGN}}|\+/-)\s*{_NUMBER})?"
)
#: How much of a row the context shows.
_CONTEXT = 160
#: How far from the n given the sample sizes a mean fits are looked for.
_SEARCH = 1000


@dataclass(frozen=True)
class Mean:
    """A cell of a row named as means of whole numbers, with the n its column names."""

    line: int
    #: The cell as printed: "3.47 (1.20)".
    printed: str
    #: The mean as printed, its sign an ASCII minus: "3.47".
    mean: str
    n: int
    #: The row's label, as printed.
    label: str
    #: Why its n may be another, where the table says so.
    uncertain: str | None
    context: str


def places(mean: str) -> int:
    """How many places the mean is printed to."""
    return len(mean.partition(".")[2])


def assessable(mean: str, n: int, items: int = 1) -> bool:
    """Whether a mean printed as `mean` can be told possible or not for `n` people answering
    `items` items each: some mean printed to its places is no whole total over them."""
    return _some_mean_is_none(n * items, places(mean))


@cache
def _some_mean_is_none(count: int, places_: int) -> bool:
    """Whether some mean printed to `places_` is no whole total over `count`. Never for 10 to
    the power of the places or more; always for fewer than half that, since each total
    prints at most two means; between, each mean of one unit is tried, which is enough,
    since a mean a unit up is a total `count` up."""
    scale = 10**places_
    if count >= scale:
        return False
    if 2 * count < scale:
        return True
    return any(low > high for low, high in
               (_span(Fraction(k, scale), places_, count) for k in range(scale)))  # fmt: skip


def possible(mean: str, n: int, items: int = 1) -> bool | None:
    """Whether `mean` can be the mean of `n` times `items` whole numbers, rounded to the
    places it is printed to; None where it is not assessable, or `n` or `items` is not a
    count."""
    if n < 1 or items < 1 or not assessable(mean, n, items):
        return None
    low, high = _totals(mean, n * items)
    return low <= high


def nearest(mean: str, n: int, items: int = 1) -> tuple[str, str]:
    """The means printed to the same places of the two whole totals over `n` times `items`
    either side of `mean`."""
    count = n * items
    below = math.floor(Fraction(Decimal(mean)) * count)
    return _printed(Fraction(below, count), places(mean)), \
        _printed(Fraction(below + 1, count), places(mean))  # fmt: skip


def fitting(mean: str, n: int, items: int = 1) -> tuple[int | None, int | None]:
    """The nearest sample sizes below and above `n` for which `mean` is possible, each None
    where there is none short of 1 or of the size at which every mean is."""
    limit = min(math.ceil(Fraction(10 ** places(mean), items)), n + _SEARCH)
    below = next((m for m in range(n - 1, max(n - _SEARCH, 0), -1)
                  if possible(mean, m, items)), None)  # fmt: skip
    above = next((m for m in range(n + 1, limit) if possible(mean, m, items)), None)
    return below, above


def described(mean: str, n: int, items: int = 1) -> str:
    """Why `mean`, which is not `possible`, cannot be a mean of `n` (times `items`) whole
    numbers, and of how many it can."""
    count = n * items
    low, high = nearest(mean, n, items)
    below = math.floor(Fraction(Decimal(mean)) * count)
    of = f"{n} whole numbers" if items == 1 else f"{n} people answering {items} items each"
    said = (
        f"{mean} cannot be the mean of {of}: the totals either side, {below} and "
        f"{below + 1} over {count}, give {low} and {high}"
    )
    fewer, more = fitting(mean, n, items)
    sizes = [str(size) for size in (fewer, more) if size is not None]
    if sizes:
        said += f"; it can be the mean of {' or '.join(sizes)}" + (
            " whole numbers" if items == 1 else f" people answering {items} items each"
        )
    return said


def as_mean(text: str) -> str | None:
    """`text` as a mean the test reads, an ASCII minus for a minus sign, or None where it is
    not a decimal number."""
    text = text.strip().replace("\N{MINUS SIGN}", "-")
    if not re.fullmatch(rf"-?{_NUMBER}", text):
        return None
    try:
        Decimal(text)
    except InvalidOperation:  # pragma: no cover - the pattern admits only decimals
        return None
    return text


# ------------------------------------------------------------------------------ the table


def names(label: str, text: str) -> bool:
    """Whether a row's label `text` holds `label`, at word edges, in any case, its spaces
    taken as one."""
    wanted = r"\s+".join(re.escape(word) for word in label.split())
    return bool(wanted) and re.search(rf"(?<!\w){wanted}(?!\w)", text, re.IGNORECASE) is not None


def table_means(table: Table, labels: tuple[str, ...]) -> list[Mean]:
    """Each cell shaped as a mean in a row whose label holds one of `labels`, under a column
    whose header names its n, in reading order. Every other cell, in a row named or not, is
    read for the n it names, which then holds for the column under it: a header whose first
    cell is the scale's name is still a header (round 1 of #331)."""
    found: list[Mean] = []
    over: dict[int, int] = {}
    for row in table:
        placed = list(_columns(row))
        label = row[0].text if row else ""
        named = any(names(wanted, label) for wanted in labels)
        context = " | ".join(" ".join(cell.text.split()) for cell in row)
        if len(context) > _CONTEXT:
            context = context[: _CONTEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"
        for column, cell in placed[1:]:
            text, noted = _clean(cell.text)
            shaped = _MEAN.fullmatch(text) if named else None
            if shaped is None:
                _header(cell, column, over)
                continue
            if column not in over:
                continue
            found.append(Mean(
                line=cell.line, printed=" ".join(cell.text.split()),
                mean=shaped.group("mean").replace("\N{MINUS SIGN}", "-"), n=over[column],
                label=label, uncertain=_uncertain(label, noted), context=context,
            ))  # fmt: skip
    return found


def _header(cell: TableCell, column: int, over: dict[int, int]) -> None:
    """The n a cell names, where it names one, for each column it spans."""
    named = {_whole(match.group("n")) for match in _N.finditer(cell.text)}
    if len(named) == 1:
        for each in range(column, column + max(cell.span, 1)):
            over[each] = next(iter(named))


def _uncertain(label: str, noted: bool) -> str | None:
    if _NOTE.search(label):
        return "the row's label carries a footnote marker, and a note may give it another n"
    if _N.search(label):
        return "the row's label names an n of its own"
    if noted:
        return "the cell carries a footnote marker, and a note may give it another n"
    return None


# --------------------------------------------------------------------------- arithmetic


def _totals(mean: str, count: int) -> tuple[int, int]:
    """The least and the greatest whole total over `count` within half a unit of `mean`'s
    last place; the first above the second where there is none."""
    return _span(Fraction(Decimal(mean)), places(mean), count)


def _span(printed: Fraction, places_: int, count: int) -> tuple[int, int]:
    half = Fraction(1, 2 * 10**places_)
    return math.ceil((printed - half) * count), math.floor((printed + half) * count)


def _printed(value: Fraction, places_: int) -> str:
    """`value` rounded half up to `places_`, as a decimal."""
    step = Fraction(1, 10**places_)
    units = math.floor(value / step + Fraction(1, 2))
    return f"{Decimal(units).scaleb(-places_):.{places_}f}"
