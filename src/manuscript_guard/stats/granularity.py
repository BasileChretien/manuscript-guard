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

Two tests go further, each on an SD printed with its mean.

* **GRIMMER** (Anaya, *PeerJ Preprints* 2016, e2400v1, doi:10.7287/peerj.preprints.2400v1)
  holds the SD of n whole numbers to the mean: the sum of their squares is a whole number,
  of the parity of their total, and no less than that of the total spread as evenly as it
  can be. `sd_possible` is a port of `GRIMMER_test` of rsprite2 (Lukas Wallrich; MIT; its
  `R/core-functions.R` at commit 78231f75751eb5f34cd53f5d8391a4baf7b2cb3b of 2026-09-09,
  version 0.2.1.9002, read 2026-11-12), which takes the analytic form of Aurélien Allard
  (2018) and extends it to several items. Its rounding rules are kept: the mean's and the
  SD's last places are those printed, noughts at the end counted; both ends of half a unit
  either side are taken, for the mean and for the SD; the SD's lower end is never below
  nought; every whole total the mean allows is tried; one number has no SD and fails. Its
  arithmetic is in floating point with a tolerance, 1e-10; here it is exact, in whole
  numbers and fractions, so the tolerance has nothing to do and is not kept. rsprite2 stops
  past a million totals to try; this says the SD is not assessable past 100,000, since G7
  runs inside `check`. ATTRIBUTION.md has its notice.
* **DEBIT** (Heathers and Brown, "DEBIT: A Simple Consistency Test For Binary Data", 2019,
  <https://osf.io/5vb3u>, read 2026-11-12; no DOI) holds the mean and SD of n numbers
  each 0 or 1 to each other: k ones among n have the mean k/n and the sample SD
  sqrt(k(n - k) / (n(n - 1))), the one the paper says is "invariably used". rsprite2 has
  no DEBIT, so it is written from the paper. A pair is possible where some k gives both,
  each within half a unit of its last place. The paper takes an SD of 0.37 for 0.365 to
  below 0.375; both ends are taken here, as for GRIM and GRIMMER, which can only pass more.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from manuscript_guard.stats.shares import _N, _NOTE, _clean, _columns, _whole
from manuscript_guard.text.tables import Table, TableCell

#: A mean as a table cell prints it: alone, with its SD in brackets, or with a plus-minus
#: sign and its SD. A minus sign may stand before it, and no nought before its point,
#: ".47 (.12)" (round 1 of #331).
_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_MEAN = re.compile(
    rf"(?P<mean>[-\N{{MINUS SIGN}}]?{_NUMBER})"
    rf"(?:\s*[(\[]\s*{_NUMBER}\s*[)\]]|\s*(?:\N{{PLUS-MINUS SIGN}}|\+/-)\s*{_NUMBER})?"
)
#: The spread after a mean `_MEAN` read, in brackets or after a plus-minus sign.
_SPREAD = re.compile(
    rf"[(\[]\s*(?P<bracketed>{_NUMBER})\s*[)\]]"
    rf"|(?:\N{{PLUS-MINUS SIGN}}|\+/-)\s*(?P<signed>{_NUMBER})"
)
#: What names a spread an SD, in a row's label or a header.
_SD_NAMED = re.compile(
    r"(?<![A-Za-z])(?:SDs?|S\.\s?D\.|s\.d\.)(?![A-Za-z])|(?i:\bstandard\s+deviations?\b)"
)
#: What names a spread other than an SD: a standard error, an interval, an interquartile
#: range, a range, quartiles or percentiles (`stats/shares.py` reads such a row as no share).
_OTHER_NAMED = re.compile(
    r"(?<![A-Za-z])(?:SEM?s?|S\.\s?E\.(?:\s?M\.)?|s\.e\.(?:m\.)?|IQR|CI|CrI)(?![A-Za-z])"
    r"|(?i:\bstandard\s+errors?\b|\binterquartile\b|\branges?\b|\bconfidence\b"
    r"|\bpercentiles?\b|\bquartiles?\b)"
)
#: The most totals, or counts of ones, a test tries: a tenth of rsprite2's limit on what it
#: enumerates, since G7 runs inside `check` (round 1 of #665: a million took seconds).
_MOST_TOTALS = 100_000
#: What names a percentage in a label or a header.
_PERCENT = "%"
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
    #: The spread printed with it, in brackets or after a plus-minus sign: "1.20"; None
    #: where it stands alone.
    spread: str | None = None
    #: Why the spread is not read as an SD, where its label or a header names it otherwise:
    #: a standard error, an interquartile range (`_not_an_sd`).
    not_an_sd: str | None = None
    #: Why the mean is not read as a proportion of numbers each 0 or 1, for DEBIT: it has no
    #: point or is outside 0 to 1, or its label or a header names a percentage
    #: (`_not_a_proportion`).
    not_a_proportion: str | None = None


def places(mean: str) -> int:
    """How many places the mean is printed to."""
    return len(mean.partition(".")[2])


def assessable(mean: str, n: int, items: int = 1) -> bool:
    """Whether a mean printed as `mean` can be told possible or not for `n` people answering
    `items` items each: some mean printed to its places is no whole total over them."""
    return _some_mean_is_none(n * items, places(mean))


def _some_mean_is_none(count: int, places_: int) -> bool:
    """Whether some mean printed to `places_` is no whole total over `count`. Never for 10 to
    the power of the places or more. Below that, the `count` totals of one unit each print
    one mean, and a total half a unit from two printed means, a tie, prints both; some mean
    is none where totals and ties are fewer than the means a unit holds. A total is a tie
    where 2 * 10**places_ * total / count is odd: k * count / g for odd k below
    g = gcd(count, 2 * 10**places_), where 2 * 10**places_ / g is odd. Worked out, not
    searched, since the search took seconds at four places (round 2 of #331); a test holds
    it to the search at one, two and three."""
    scale = 10**places_
    if count >= scale:
        return False
    common = math.gcd(count, 2 * scale)
    ties = common // 2 if (2 * scale // common) % 2 == 1 else 0
    return count + ties < scale


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
    """The nearest sample sizes below and above `n` for which `mean` is a whole total over
    them, each None where there is none short of 1 or of 10 to the power of its places. A
    size at which every mean is possible, 96 at two places, is one (round 2 of #331)."""
    limit = min(math.ceil(Fraction(10 ** places(mean), items)), n + _SEARCH)

    def fits(size: int) -> bool:
        low, high = _totals(mean, size * items)
        return low <= high

    below = next((m for m in range(n - 1, max(n - _SEARCH, 0), -1) if fits(m)), None)
    above = next((m for m in range(n + 1, limit) if fits(m)), None)
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


# ----------------------------------------------------------------------- the SD: GRIMMER


def as_spread(text: str) -> str | None:
    """`text` as an SD the tests read, a decimal of nought or more, or None."""
    text = text.strip()
    return text if re.fullmatch(_NUMBER, text) else None


def sd_possible(mean: str, sd: str, n: int, items: int = 1) -> bool | None:
    """Whether `sd` can be the SD of `n` people's means of `items` whole numbers each, whose
    mean is `mean`, each rounded to the places printed: rsprite2's `GRIMMER_test` (see the
    module's docstring). False for one person, and where `mean` is no whole total over
    them; None where `n` or `items` is not a count, or more than 100,000 totals would be
    tried."""
    if n < 1 or items < 1:
        return None
    if n == 1:
        return False
    totals = _centred_totals(mean, n * items)
    if totals is None:
        return None
    bounds = _SquareBounds.of(sd, n, items)
    return any(_square_sums(total, bounds) is not None for total in bounds.tried(totals))


def sd_described(mean: str, sd: str, n: int, items: int = 1) -> str:
    """Why `sd`, which is not `sd_possible`, cannot go with `mean` for `n` (times `items`)
    whole numbers, and the SDs nearest it that can, printed to its places."""
    of = f"{n} whole numbers" if items == 1 else f"{n} people answering {items} items each"
    said = f"an SD of {sd} cannot go with a mean of {mean} of {of}"
    if n == 1:
        return said + ": one number has no SD"
    below, above = _nearest_sds(mean, sd, n, items)
    if below is None and above is None:
        return said
    either = " and ".join(shown for shown in (below, above) if shown is not None)
    return said + (
        f": the SDs nearest it that such numbers can have print as {either}"
        if below is not None and above is not None
        else f": the nearest SD that such numbers can have prints as {either}"
    )


def _centred_totals(mean: str, count: int) -> range | None:
    """The whole totals over `count` within half a unit of `mean`'s last place, of the
    numbers less the whole part of `mean`, as rsprite2 centres them; None where they are
    more than 100,000."""
    value = Fraction(Decimal(mean))
    low, high = _span(value - math.floor(value), places(mean), count)
    if high - low + 1 > _MOST_TOTALS:
        return None
    return range(low, high + 1)


@dataclass(frozen=True)
class _SquareBounds:
    """The bounds an SD's half unit puts on a sum of squares of `n` whole sums of `items`
    numbers, as whole numbers: for a total T, (n - 1)(items * sd)^2 + T^2/n at each end of
    the SD's interval is (scale * sd_num + T^2 * sd_den) / (n * sd_den). Worked out once,
    so that each of up to 100,000 totals costs a few whole-number operations rather than
    fractions (round 1 of #665)."""

    n: int
    low: int
    low_den: int
    high: int
    high_den: int
    #: Whether the SD's interval reaches below nought, where no SD lies below it.
    from_nought: bool

    @classmethod
    def of(cls, sd: str, n: int, items: int) -> _SquareBounds:
        low_sd, high_sd = _interval(sd)
        low, high = max(low_sd, Fraction(0)) ** 2, high_sd**2
        scale = (n - 1) * items * items * n
        return cls(n, scale * low.numerator, low.denominator, scale * high.numerator,
                   high.denominator, low_sd <= 0)  # fmt: skip

    def least(self, total: int) -> int:
        """The least whole sum of squares at or above the interval's lower end."""
        return -(-(self.low + total * total * self.low_den) // (self.n * self.low_den))

    def most(self, total: int) -> int:
        """The greatest whole sum of squares at or below the interval's upper end."""
        return (self.high + total * total * self.high_den) // (self.n * self.high_den)

    def tried(self, totals: range) -> Iterator[int]:
        """The totals worth trying: each whose evenest sums can be within the interval, and
        the first and the last of each run whose cannot, where the SD nearest above the
        interval may be. The evenest sums of a total T = n * w + o exceed T^2 / n by
        o(n - o) / n, so they are within the interval only where o(n - o) is at most n times
        (n - 1)(items * upper end)^2, which is `high / high_den`: a run of remainders in the
        middle is skipped whole (round 1 of #665)."""
        n = self.n

        def fits(over: int) -> bool:
            return over * (n - over) * self.high_den <= self.high

        # The greatest remainder up to n / 2 that fits; those from it to n - it fit.
        edge = n // 2
        if not fits(edge):
            square = max(0, n * n - 4 * (self.high // self.high_den))
            edge = min(max(0, (n - math.isqrt(square)) // 2), n // 2)
            while edge < n // 2 and fits(edge + 1):
                edge += 1
            while edge > 0 and not fits(edge):
                edge -= 1
        total = totals.start
        while total < totals.stop:
            over = total % n
            if fits(over):
                yield total
                total += 1
                continue
            last = min(total + (n - edge - 1 - over), totals.stop - 1)
            yield total
            if last != total:
                yield last
            total = last + 1


def _evenest(total: int, n: int) -> int:
    """The least sum of squares of `n` whole numbers totalling `total`: as even as can be."""
    whole, over = divmod(total, n)
    return (n - over) * whole**2 + over * (whole + 1) ** 2


def _square_sums(total: int, bounds: _SquareBounds) -> tuple[int, int] | None:
    """The least and the greatest sum of squares of n whole sums totalling `total` whose SD
    prints as the SD `bounds` was made from: within its half a unit, of the parity of
    `total`, and no less than the evenest sums'; None where there is none, as soon as the
    evenest sums' is past the upper end. rsprite2's loop body, in whole numbers."""
    most = bounds.most(total)
    evenest = _evenest(total, bounds.n)
    if evenest > most:
        return None
    least = max(bounds.least(total), evenest)
    least += (total - least) % 2
    return (least, most) if least <= most else None


def _nearest_sds(mean: str, sd: str, n: int, items: int) -> tuple[str | None, str | None]:
    """The SDs printed to `sd`'s places nearest below and above it that `n` whole sums of
    `items` numbers with `mean` can have: the sums of squares either side of its interval
    for each total, of the total's parity and no less than its least. Each SD's square is
    (sum * n - total^2) / (n(n - 1) items^2), whose denominator is one for every total, so
    the numerators are compared as whole numbers."""
    totals = _centred_totals(mean, n * items) or range(0)
    bounds = _SquareBounds.of(sd, n, items)
    below: int | None = None
    above: int | None = None
    for total in bounds.tried(totals):
        evenest = _evenest(total, n)
        under = bounds.least(total) - 1
        under -= (under - total) % 2
        beyond = bounds.most(total) + 1
        beyond += (beyond - total) % 2
        beyond = max(beyond, evenest)
        if not bounds.from_nought and under >= evenest:
            spread = under * n - total * total
            below = spread if below is None else max(below, spread)
        spread = beyond * n - total * total
        above = spread if above is None else min(above, spread)
    shown, over = places(sd), n * (n - 1) * items * items
    return (None if below is None else _printed_root(Fraction(below, over), shown),
            None if above is None else _printed_root(Fraction(above, over), shown))  # fmt: skip


# ---------------------------------------------------------------------- binary data: DEBIT


def binary_possible(mean: str, sd: str, n: int) -> bool | None:
    """Whether `mean` and `sd` can be the mean and sample SD of `n` numbers each 0 or 1,
    each rounded to the places printed: some count of ones k gives k/n and
    sqrt(k(n - k) / (n(n - 1))) within half a unit of each (DEBIT, see the module's
    docstring). False for one number, which has no SD; None where `n` is not a count, or
    more than 100,000 counts would be tried."""
    if n < 1:
        return None
    if n == 1:
        return False
    ones = _ones(mean, n)
    if ones is None:
        return None
    low, high = _interval(sd)
    low = max(low, Fraction(0))
    return any(low**2 <= _binary_variance(k, n) <= high**2 for k in ones)


def binary_described(mean: str, sd: str, n: int) -> str:
    """Why `mean` and `sd`, not `binary_possible`, cannot be those of `n` numbers each 0
    or 1: no count of ones gives the mean, or those that do give other SDs."""
    of = f"{n} numbers each 0 or 1"
    if n == 1:
        return f"an SD of {sd} cannot go with one number: one number has no SD"
    ones = list(_ones(mean, n) or ())
    shown = places(sd)
    if not ones:
        below = math.floor(Fraction(Decimal(mean)) * n)
        near = [k for k in (below, below + 1) if 0 <= k <= n]
        given = " and ".join(f"{k} ones give {_printed(Fraction(k, n), places(mean))}"
                             for k in near)  # fmt: skip
        return f"{mean} cannot be the mean of {of}" + (f": {given}" if given else "")
    sds = [_printed_root(_binary_variance(k, n), shown) for k in ones]
    if len(ones) == 1:
        gives = f"{ones[0]} ones of {n} give the mean, and an SD of {sds[0]}"
    else:
        gives = (f"{ones[0]} to {ones[-1]} ones of {n} give the mean, and SDs of "
                 f"{min(sds, key=Decimal)} to {max(sds, key=Decimal)}")  # fmt: skip
    return f"an SD of {sd} cannot go with a mean of {mean} of {of}: {gives}"


def _ones(mean: str, n: int) -> range | None:
    """The counts of ones among `n` whose share is within half a unit of `mean`'s last
    place; None where they are more than 100,000."""
    low, high = _span(Fraction(Decimal(mean)), places(mean), n)
    low, high = max(low, 0), min(high, n)
    if high - low + 1 > _MOST_TOTALS:
        return None
    return range(low, high + 1)


def _binary_variance(ones: int, n: int) -> Fraction:
    """The sample variance of `ones` ones and `n - ones` noughts: k(n - k) / (n(n - 1))."""
    return Fraction(ones * (n - ones), n * (n - 1))


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
    # The columns whose n a row of means named in one of its other cells, "3.1 (1.0), n =
    # 25": the means below are held to it, and are uncertain (round 2 of #331).
    from_means: set[int] = set()
    # What the header cells over each column, and the header's first cell over all of
    # them, call the spread a mean is printed with (`_spread_named`).
    spread_over: dict[int, str] = {}
    spread_of_all = _spread_named(table[0][0].text) if table and table[0] else None
    # And whether a header over each column, and the header's first cell, names a
    # percentage, "n (%)": its cells are no proportions for DEBIT (round 1 of #665).
    percent_over: dict[int, bool] = {}
    percent_of_all = bool(table and table[0] and _PERCENT in table[0][0].text)
    for at, row in enumerate(table):
        placed = list(_columns(row))
        label = row[0].text if row else ""
        named = any(names(wanted, label) for wanted in labels)
        means = named and any(_MEAN.fullmatch(_clean(cell.text)[0]) for _c, cell in placed[1:])
        context = " | ".join(" ".join(cell.text.split()) for cell in row)
        if len(context) > _CONTEXT:
            context = context[: _CONTEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"
        for column, cell in placed[1:]:
            text, noted = _clean(cell.text)
            shaped = _MEAN.fullmatch(text) if named else None
            if shaped is None:
                _spread_header(cell, column, spread_over)
                set_here = _header(cell, column, over)
                if at == 0 or set_here:
                    _percent_header(cell, column, percent_over)
                # A mean that names its n is a row of means too, read or not (round 1 of
                # #336); a cell of the first row, the header, is none, "0.5 (n = 40)" in a
                # dose table being a header (the post-budget round of #336).
                of_means = means or (at > 0 and _names_its_n(text))
                from_means = (from_means | set_here) if of_means else (from_means - set_here)
                continue
            if column not in over:
                continue
            uncertain = _uncertain(label, noted) or (
                "its column's n is one a row of means names, not a header's"
                if column in from_means else None
            )  # fmt: skip
            found.append(Mean(
                line=cell.line, printed=" ".join(cell.text.split()),
                mean=shaped.group("mean").replace("\N{MINUS SIGN}", "-"), n=over[column],
                label=label, uncertain=uncertain, context=context,
                spread=_spread_of(text, shaped),
                not_an_sd=_not_an_sd(label, spread_over.get(column), spread_of_all),
                not_a_proportion=_not_a_proportion(
                    shaped.group("mean"), label, percent_over.get(column, False), percent_of_all
                ),
            ))  # fmt: skip
    return found


def table_binary(table: Table, labels: tuple[str, ...]) -> list[Mean]:
    """Each mean printed with its spread in a row whose label holds one of `labels`, under a
    column whose header names its n, as `table_means` finds them: the means and SDs of
    numbers each 0 or 1 that DEBIT holds to each other and to n."""
    return [mean for mean in table_means(table, labels) if mean.spread is not None]


def _names_its_n(text: str) -> bool:
    """Whether a cell is a mean and the n it is over, "3.1 (1.0), n = 25" or "3.1 (1.0)
    (n = 25)": a number with its spread or its point beside an n. A header's year, "2019
    (n = 120)", or a count, "12 (n = 25)", is none (round 2 of #336)."""
    rest = re.sub(r"[(\[]\s*[)\]]", "", _N.sub("", text)).strip(" ,;")
    shaped = _MEAN.fullmatch(rest) if _N.search(text) else None
    return shaped is not None and (shaped.end("mean") < shaped.end() or "." in shaped["mean"])


def _header(cell: TableCell, column: int, over: dict[int, int]) -> set[int]:
    """The n a cell names, where it names one, for each column it spans; the columns set."""
    named = {_whole(match.group("n")) for match in _N.finditer(cell.text)}
    if len(named) != 1:
        return set()
    spanned = set(range(column, column + max(cell.span, 1)))
    for each in spanned:
        over[each] = next(iter(named))
    return spanned


def _uncertain(label: str, noted: bool) -> str | None:
    if _NOTE.search(label):
        return "the row's label carries a footnote marker, and a note may give it another n"
    if _N.search(label):
        return "the row's label names an n of its own"
    if noted:
        return "the cell carries a footnote marker, and a note may give it another n"
    return None


def _spread_of(text: str, shaped: re.Match[str]) -> str | None:
    """The spread a cell read as a mean prints after it, "1.20" of "3.47 (1.20)" or of
    "3.47 ± 1.20"; None where the mean stands alone."""
    rest = _SPREAD.fullmatch(text[shaped.end("mean"):].strip())
    return None if rest is None else rest["bracketed"] or rest["signed"]


def _spread_named(text: str) -> str | None:
    """What `text` calls a spread: "SD" where it names an SD and nothing else, "other"
    where it names another (a standard error, an interquartile range) and no SD, "both"
    where it names an SD and another; None where it names none."""
    sd, other = _SD_NAMED.search(text) is not None, _OTHER_NAMED.search(text) is not None
    return ("both" if other else "SD") if sd else ("other" if other else None)


def _spread_header(cell: TableCell, column: int, over: dict[int, str]) -> None:
    """What a cell that is no mean calls the spread of the columns it spans, where it calls
    it anything: the latest such cell over a column says it."""
    named = _spread_named(cell.text)
    if named is not None:
        for each in range(column, column + max(cell.span, 1)):
            over[each] = named


def _percent_header(cell: TableCell, column: int, over: dict[int, bool]) -> None:
    """Whether a header cell, the first row's or one that names an n, says the columns it
    spans hold percentages: the latest such cell over a column says it. A body cell's
    "12 (40%)" says nothing of the column."""
    for each in range(column, column + max(cell.span, 1)):
        over[each] = _PERCENT in cell.text


def _not_a_proportion(mean: str, label: str, column: bool, table: bool) -> str | None:
    """Why a mean printed with its spread is no proportion of numbers each 0 or 1: a count
    and its share, "85 (52.1)", has no point, and a percentage and its SD, "19.0 (39.2)",
    is above 1 (round 1 of #665); or its label, the header over its column or the header's
    first cell names a percentage. None where it can be one."""
    value = mean.replace("\N{MINUS SIGN}", "-")
    if "." not in value:
        return "the mean has no point, as a count has"
    if not 0 <= Decimal(value) <= 1:
        return "the mean is outside 0 to 1"
    for named, where in ((_PERCENT in label, "the row's label"),
                         (column, "the header over its column"),
                         (table, "the table's header")):  # fmt: skip
        if named:
            return f"{where} names a percentage"
    return None


def _not_an_sd(label: str, column: str | None, table: str | None) -> str | None:
    """Why a spread is not read as an SD: what the row's label calls it, or else the
    header over its column, or else the header's first cell. Where none names one, the
    spread is read as an SD, as a mean's is unless a table says otherwise."""
    for named, where in ((_spread_named(label), "the row's label"),
                         (column, "the header over its column"),
                         (table, "the table's header")):  # fmt: skip
        if named == "other":
            return f"{where} names it as a spread other than an SD"
        if named == "both":
            return f"{where} names an SD and another spread"
        if named == "SD":
            return None
    return None


# --------------------------------------------------------------------------- arithmetic


def _totals(mean: str, count: int) -> tuple[int, int]:
    """The least and the greatest whole total over `count` within half a unit of `mean`'s
    last place; the first above the second where there is none."""
    return _span(Fraction(Decimal(mean)), places(mean), count)


def _span(printed: Fraction, places_: int, count: int) -> tuple[int, int]:
    half = Fraction(1, 2 * 10**places_)
    return math.ceil((printed - half) * count), math.floor((printed + half) * count)


def _interval(printed: str) -> tuple[Fraction, Fraction]:
    """What a number printed as `printed` stands for: half a unit of its last place either
    side, both ends taken."""
    value, half = Fraction(Decimal(printed)), Fraction(1, 2 * 10 ** places(printed))
    return value - half, value + half


def _printed_root(square: Fraction, places_: int) -> str:
    """The square root of `square`, rounded half up to `places_`, worked out exactly: the
    whole part of twice the root over the unit is that of the root of four times the square
    over the unit squared, and halving it, a half up, is the rounding."""
    scaled = square * 4 * 10 ** (2 * places_)
    twice = math.isqrt(scaled.numerator * scaled.denominator) // scaled.denominator
    return f"{Decimal((twice + 1) // 2).scaleb(-places_):.{places_}f}"


def _printed(value: Fraction, places_: int) -> str:
    """`value` rounded half up to `places_`, as a decimal."""
    step = Fraction(1, 10**places_)
    units = math.floor(value / step + Fraction(1, 2))
    return f"{Decimal(units).scaleb(-places_):.{places_}f}"
