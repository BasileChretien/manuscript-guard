"""A mean and its SD for a variable that cannot fall below a floor.

Altman and Bland (*BMJ* 1996;313:1200, doi:10.1136/bmj.313.7066.1200) note that for a
variable that cannot be negative, a mean less than twice its standard deviation shows that
the data are skewed: a normal distribution reaches two SDs either side of its mean, and here
the lower one would be below zero. The mean (SD) then describes the data badly; a median and
an interquartile range, or a transformation, would serve. The same reasoning holds for any
floor, the distance from it taking the mean's place, as the Cochrane Handbook gives the
check (section 10.5.3: the observed mean minus the lowest possible value, over the SD).

* **Skewed** is the mean minus the floor less than twice the SD, both as printed or as
  emitted. Exactly twice is not: a ratio of 2 is where the rule starts to say nothing.
* The SD is read, never a standard error. A standard error would need the n to give the SD,
  and an SE read as an SD says nothing about the data's spread.

`check` reads it for a mean whose variable the data dictionary gives a `range.min`, its
floor (`gates/summaries.py`); `audit --non-negative` for the rows of a table the auditor
names, with a floor of 0 (`auditing/skew.py`).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from manuscript_guard.stats.granularity import _NUMBER, names
from manuscript_guard.stats.shares import _clean, _columns
from manuscript_guard.text.tables import Table

#: The note the rule is from, as a message cites it. Its PubMed record (PMID 8916759) was read
#: on 2026-11-12 for the title, the authors, the volume and the page; the BMJ's and PubMed
#: Central's pages refused an automated reader that day, so the rule as worded here, and its
#: floor other than zero, were read in the Cochrane Handbook's section 10.5.3, which gives it
#: from this note.
CITATION = "Altman and Bland, BMJ 1996;313:1200"
#: How many SDs above the floor a mean has to be.
TIMES = 2

#: A mean and its SD as a table cell prints them: "12.3 (4.5)", "12.3 ± 4.5" or "12.3 +/- 4.5".
#: A minus sign may stand before the mean, and no nought before a point.
_CELL = re.compile(
    rf"(?P<mean>[-\N{{MINUS SIGN}}]?{_NUMBER})\s*"
    rf"(?:\(\s*(?P<bracketed>{_NUMBER})\s*\)"
    rf"|(?:\N{{PLUS-MINUS SIGN}}|\+/-)\s*(?P<signed>{_NUMBER}))"
)
#: What names a standard error: SE, SEM, s.e. or s.e.m., or the words, in any case.
_SE = re.compile(
    r"(?<![\w.])(?:SEM?|S\.E\.(?:M\.)?|s\.e\.(?:m\.)?)(?![\w])|(?i:\bstandard\s+errors?\b)"
)
#: How much of a row the context shows.
_CONTEXT = 160


def skewed(mean: object, sd: object, floor: object = 0) -> bool | None:
    """Whether `mean` minus `floor` is less than `TIMES` times `sd`: None where one of them is
    not a finite number, or the SD is negative. Each is taken as it is written, a float by
    its shortest repr, so that 9 and 4.5 are exactly twice and not skewed."""
    parts = [_decimal(value) for value in (mean, sd, floor)]
    if any(part is None for part in parts):
        return None
    mean_, sd_, floor_ = parts
    if sd_ < 0:
        return None
    return mean_ - floor_ < TIMES * sd_


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (int, float)):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            read = Decimal(value.strip().replace("\N{MINUS SIGN}", "-"))
        except InvalidOperation:
            return None
        return read if read.is_finite() else None
    return None


def said(mean: str, sd: str, floor: str) -> str:
    """What is said of a mean and an SD that are skewed: the three numbers and the source."""
    return (
        f"the mean {mean} is less than twice the SD {sd} above the floor {floor}, so the data "
        f"are skewed and the mean (SD) describes them badly ({CITATION})"
    )


# ------------------------------------------------------------------------------ the table


@dataclass(frozen=True)
class Spread:
    """A cell of a named row read as a mean and its SD."""

    line: int
    #: The cell as printed: "12.3 (4.5)".
    printed: str
    #: The mean and the SD as printed, the mean's sign an ASCII minus.
    mean: str
    sd: str
    #: The row's label, as printed.
    label: str
    context: str

    @property
    def skewed(self) -> bool:
        return bool(skewed(self.mean, self.sd))


@dataclass(frozen=True)
class Passed:
    """A named row whose cells were not read, and why."""

    line: int
    label: str
    why: str
    context: str


#: Why a named row is not read.
SE_LABEL = "its label names a standard error, and an SE is not an SD"
SE_HEADER = "the header over its cells names a standard error, and an SE is not an SD"
PERCENT = "its label names a percentage: its cells are counts and their shares"


def table_spreads(table: Table, labels: tuple[str, ...]) -> tuple[list[Spread], list[Passed]]:
    """Each cell shaped as a mean and its SD in a row whose label holds one of `labels`, at
    word edges and in any case, in reading order; and each such row passed over, with why:
    its label names a standard error or a percentage, or the header over a cell shaped so
    names a standard error. The header is the table's first row."""
    found: list[Spread] = []
    passed: list[Passed] = []
    se_columns: set[int] = set()
    for at, row in enumerate(table):
        placed = list(_columns(row))
        label = row[0].text if row else ""
        if at == 0:
            se_columns = {each for column, cell in placed[1:] if _SE.search(cell.text)
                          for each in range(column, column + max(cell.span, 1))}  # fmt: skip
        if not any(names(wanted, label) for wanted in labels):
            continue
        shaped = [(column, cell, _CELL.fullmatch(_clean(cell.text)[0]))
                  for column, cell in placed[1:]]  # fmt: skip
        shaped = [(column, cell, match) for column, cell, match in shaped if match is not None]
        if not shaped:
            continue
        context = _context(row)
        line = shaped[0][1].line
        why = SE_LABEL if _SE.search(label) else PERCENT if "%" in label else None
        if why is not None:
            passed.append(Passed(line, label, why, context))
            continue
        if any(column in se_columns for column, _cell, _match in shaped):
            passed.append(Passed(line, label, SE_HEADER, context))
        for column, cell, match in shaped:
            if column in se_columns:
                continue
            found.append(Spread(
                line=cell.line, printed=" ".join(cell.text.split()),
                mean=match["mean"].replace("\N{MINUS SIGN}", "-"),
                sd=match["bracketed"] or match["signed"], label=label, context=context,
            ))  # fmt: skip
    return found, passed


def _context(row) -> str:
    context = " | ".join(" ".join(cell.text.split()) for cell in row)
    if len(context) > _CONTEXT:
        context = context[: _CONTEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"
    return context
