"""A date the analysis states, read and written one way wherever it is read or written.

The emitters take a date as ISO 8601 text at the precision the author knows it to: a year
("2023"), a month ("2023-12") or a day ("2023-12-31"). It is printed in the English the
paper declares ("1 March 2024" in British English, "March 1, 2024" in American English, the
month and the year alike in both), and a display written by hand is read back and held to
the date it is the display of: before, nothing compared a string value with its display, so
`em.value("period.start", "2015-01-01", display="1 January 2016")` printed another year.

A year, a month and a day are each a span of days, and a comparison is between spans: data
covering "2023" end on 31 December 2023, and a report of "2023-12" lies within them.
"""

from __future__ import annotations

import calendar
import numbers
import re
from dataclasses import dataclass
from datetime import date

#: The precisions a date is stated to, finest last.
PRECISIONS = ("year", "month", "day")

# Digits 0 to 9 only, as the R emitter reads them: Python's \d is any script's digit.
_ISO = re.compile(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?")

# `calendar.month_name` follows the locale it is imported under, and a date printed for an
# English paper is English whatever the machine's locale: written out here.
_NAMES = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip
#: Each month by its name and by the first three letters of it, and September by "Sept".
_MONTHS = {name.lower(): number for number, name in enumerate(_NAMES, 1)}
_MONTHS |= {name[:3].lower(): number for number, name in enumerate(_NAMES, 1)}
_MONTHS["sept"] = 9

_MONTH = r"([A-Za-z]{3,9})\.?"
_DAY = r"([0-9]{1,2})(?:st|nd|rd|th)?"
_YEAR = r"([0-9]{4})"
#: The ways a display writes a date, each read whole: "1 March 2024", "March 1, 2024", "Mar.
#: 1 2024", "1st March 2024", "March 2024", and the ISO forms.
_WRITTEN = (
    ("dmy", re.compile(rf"{_DAY} {_MONTH},? {_YEAR}")),
    ("mdy", re.compile(rf"{_MONTH} {_DAY},? {_YEAR}")),
    ("my", re.compile(rf"{_MONTH},? {_YEAR}")),
)


@dataclass(frozen=True)
class Dated:
    """A date at the precision it was stated to: a year, a month of a year, or a day."""

    year: int
    month: int | None = None
    day: int | None = None

    @property
    def precision(self) -> str:
        return "day" if self.day else "month" if self.month else "year"

    @property
    def first(self) -> date:
        """The first day of the span."""
        return date(self.year, self.month or 1, self.day or 1)

    @property
    def last(self) -> date:
        """The last day of the span."""
        if self.day:
            return date(self.year, self.month, self.day)  # type: ignore[arg-type]
        month = self.month or 12
        return date(self.year, month, calendar.monthrange(self.year, month)[1])

    @property
    def iso(self) -> str:
        if self.day:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if self.month:
            return f"{self.year:04d}-{self.month:02d}"
        return f"{self.year:04d}"

    def within(self, other: Dated) -> bool:
        """Whether every day of this span is a day of `other`."""
        return other.first <= self.first and self.last <= other.last


def _dated(year: int, month: int | None, day: int | None) -> Dated | None:
    """The date, or None where there is no such day: 2023-02-30, or month 13."""
    try:
        date(year, month or 1, day or 1)
    except ValueError:
        return None
    if year < 1:
        return None
    return Dated(year, month, day)


def parse_iso(text: object) -> Dated | None:
    """`text` as an ISO 8601 date to a year, a month or a day, or None where it is not one."""
    if not isinstance(text, str):
        return None
    found = _ISO.fullmatch(text.strip())
    if found is None:
        return None
    year, month, day = (int(part) if part else None for part in found.groups())
    return _dated(year, month, day)  # type: ignore[arg-type]


def written(dated: Dated, english: str | None = None) -> str:
    """How the paper prints the date: day, month and year in the order its English writes
    them ("1 March 2024", "March 1, 2024"), a month as "March 2024", a year as itself."""
    if dated.month is None:
        return str(dated.year)
    month = _NAMES[dated.month - 1]
    if dated.day is None:
        return f"{month} {dated.year}"
    if english == "en-US":
        return f"{month} {dated.day}, {dated.year}"
    return f"{dated.day} {month} {dated.year}"


def read_written(text: str) -> Dated | None:
    """The date a display writes, in any of the forms `written` and an author write, or None
    where the display is no date. Read whole: "1 March 2024 onwards" is not a date."""
    plain = " ".join(text.replace("\N{NO-BREAK SPACE}", " ").split())
    iso = parse_iso(plain)
    if iso is not None:
        return iso
    for order, pattern in _WRITTEN:
        found = pattern.fullmatch(plain)
        if found is None:
            continue
        day: str | None = None
        if order == "dmy":
            day, name, year = found.groups()
        elif order == "mdy":
            name, day, year = found.groups()
        else:
            name, year = found.groups()
        month = _MONTHS.get(name.lower())
        if month is None:
            return None
        return _dated(int(year), month, int(day) if day else None)
    return None


def display_problem(value: str, display: str) -> str | None:
    """What is wrong with `display` as the display of the ISO date `value`, or None.

    A display is the date itself or a coarser statement of it, as a rounding is of a number:
    2015-03-01 may be printed "1 March 2015", "March 2015" or "2015", and not "1 March 2016"
    nor "the spring of 2015".

    Only a day is a date beyond doubt. "2010-12" is also the period 2010 to 2012 written
    short, and "2015" a label, as they were before dates were read: a year or a month is held
    to a display that reads as a date, and one that does not is left as it was."""
    dated = parse_iso(value)
    if dated is None or display == value:
        return None
    shown = read_written(display)
    if shown is None and dated.precision != "day":
        return None
    if shown is None:
        return (
            f"display {display!r} is not a date, and the value is the date {dated.iso}. Write "
            f"the date alone, \"{written(dated)}\" or \"{written(dated, 'en-US')}\", and the "
            f"words around it in the text"
        )
    if PRECISIONS.index(shown.precision) > PRECISIONS.index(dated.precision):
        return (
            f"display {display!r} names a {shown.precision}, and the value is the "
            f"{dated.precision} {dated.iso}: a display may state a date less precisely, "
            f"never more"
        )
    if not dated.within(shown):
        return f"display {display!r} is {shown.iso}, and the value is {dated.iso}"
    return None


def as_dated(item: object) -> Dated | None:
    """One entry of the data's own dates as a date at its precision, or None where it is
    missing (None, NaN, NaT, an empty string). A `date`, a `datetime` or a pandas
    `Timestamp` is a day; a NumPy `datetime64` is read from its ISO text; a string is ISO to
    a year, a month or a day, a time after the day left out; a whole number is a year.
    Anything else raises, naming it: a column of codes passed by mistake is not a column of
    dates nobody could read."""
    # pandas' NA and NaT first: compared with anything, NA is neither true nor false.
    if item is None or type(item).__name__ in ("NaTType", "NAType"):
        return None
    if isinstance(item, str) and not item.strip():
        return None
    if isinstance(item, float) and item != item:  # NaN
        return None
    # A pandas Timestamp is a datetime, and a datetime a date.
    if isinstance(item, date):
        return Dated(item.year, item.month, item.day)
    if type(item).__name__ == "datetime64":
        text = str(item)
        return None if text == "NaT" else _from_text(text, item)
    if isinstance(item, bool):
        raise ValueError(f"{item!r} is not a date")
    if isinstance(item, str):
        return _from_text(item, item)
    # NumPy's integers are no `int`, and a column of years read by NumPy is made of them.
    if isinstance(item, numbers.Integral) or (
        isinstance(item, numbers.Real) and float(item).is_integer()
    ):
        year = int(item)
        if 1000 <= year <= 9999:
            return Dated(year)
    raise ValueError(f"{item!r} is not a date")


def _from_text(text: str, item: object) -> Dated:
    """An ISO date, with a time after the day left out: "2023-12-31T08:00:00"."""
    day = re.split(r"[T ]", text.strip(), maxsplit=1)[0]
    dated = parse_iso(day)
    if dated is None:
        raise ValueError(f"{item!r} is not a date written as ISO 8601")
    return dated
