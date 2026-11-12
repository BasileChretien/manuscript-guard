"""A mean and its SD for a variable that cannot fall below a floor.

Altman and Bland (*BMJ* 1996;313:1200, doi:10.1136/bmj.313.7066.1200) note that for a
variable that cannot be negative, a mean less than twice its standard deviation shows that
the data are skewed: a normal distribution reaches two SDs either side of its mean, and here
the lower one would be below zero. The mean (SD) then describes the data badly; a median and
an interquartile range, or a transformation, would serve. Their rule is for a floor of 0.
From another floor the check is the Cochrane Handbook's (*Cochrane Handbook for Systematic
Reviews of Interventions*, version 6.5.1, section 10.5.3: the observed mean minus the lowest
possible value, over the SD, below 2), and a message cites the one it applied.

* **Skewed** is the mean minus the floor less than twice the SD, both as printed or as
  emitted. Exactly twice is not: a ratio of 2 is where the rule starts to say nothing.
* The SD is read, never a standard error. A standard error would need the n to give the SD,
  and an SE read as an SD says nothing about the data's spread.

`check` reads it for a mean whose variable the data dictionary gives a `range.min`, its
floor (`gates/summaries.py`); `audit --non-negative` for the rows of a table the auditor
names, with a floor of 0 (`auditing/skew.py`). There a cell is read only where it can be
said to be a mean (SD) of the measure named, and anything unsure is passed over and said
(`table_spreads`).
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
#: The source of the check from a floor other than 0, as a message cites it: the Handbook's
#: chapter 10 (Deeks, Higgins, Altman, McKenzie, Veroniki and Simmonds, editors), read on
#: 2026-11-12 at cochrane.org/handbook, whose suggested citation gives version 6.5.1.
HANDBOOK = ("Cochrane Handbook for Systematic Reviews of Interventions, version 6.5.1, "
            "section 10.5.3")
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
#: What names a change, which can be negative: the words, "from baseline", or a delta. Not
#: a time to one, "time to change of therapy", "days to treatment change" (`_TO_ONE`).
_CHANGE = re.compile(
    r"(?i:\b(?:change[sd]?|differences?|delta)\b|\bfrom\s+baseline\b)"
    r"|[\N{GREEK CAPITAL LETTER DELTA}\N{INCREMENT}]"
)
#: What stands before a change that makes it the event a time runs to: "to", one word apart
#: at most ("to change", "to treatment change").
_TO_ONE = re.compile(r"(?i)\bto\s+(?:[\w-]+\s+)?\Z")
#: What says a table's cells are counts and their shares: n (%), N (%), No. (%) or n/N (%).
#: A bare "%", "Missing, %", says it of no table.
_N_PERCENT = re.compile(r"(?<![\w.])(?:[nN]|No\.|n/N)\s*\(\s*%\s*\)")
#: What says a label, or a column's header, is of a mean and its SD: "mean", "SD", "± SD".
_MEAN_NAMED = re.compile(r"(?i:\bmean\b)|\bSD\b")
#: What says a label is a category, whose cells are counts: a comparator, n (%), a "%", yes,
#: n/N, or "no" where neither a point nor "of" follows it ("No. of days" is a number).
_CATEGORY = re.compile(
    r"[<>\N{GREATER-THAN OR EQUAL TO}\N{LESS-THAN OR EQUAL TO}%]"
    r"|(?i:\byes\b|\bno\b(?!\s*\.)(?!\s+of\b))|(?<![\w/])n/N(?![\w/])"
)
#: An HTML tag in a label, "<sup>a</sup>", taken off before the label is read: its "<" is
#: no comparator. A "<" before a space or a digit, "< 50", opens no tag.
_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
#: A line that opens a table's caption: "Table 2.", "Table S1", "**Table 3**",
#: "Supplementary Table 2", and pandoc's "Table: ..." and ": ...". Below a table it is
#: another table's, and the paragraph read there ends before it.
_CAPTION_OPENS = re.compile(
    r"^\s*(?:(?:\*\*|__)?(?:Supplementary\s+)?Table\s+S?\d+\b|Table:|:\s)", re.IGNORECASE
)
#: How far above or below a table a caption saying n (%) is looked for: its paragraph.
_CAPTION_LINES = 3
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


def source(floor: object) -> str:
    """Whom the rule is cited from for `floor`: Altman and Bland for 0, the Handbook for any
    other."""
    return CITATION if _decimal(floor) == 0 else HANDBOOK


def said(mean: str, sd: str, floor: str) -> str:
    """What is said of a mean and an SD that are skewed: the three numbers and the source."""
    return (
        f"the mean {mean} is less than twice the SD {sd} above the floor {floor}, so the data "
        f"are skewed and the mean (SD) describes them badly ({source(floor)})"
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
CATEGORY = "its label names a category, so its cells are counts and their shares"
MAYBE_COUNT = "in a table of counts and their shares, it may be a count"
CHANGE = "its label names a change or a difference, which can be negative"


def table_spreads(
    table: Table, labels: tuple[str, ...], caption: str = ""
) -> tuple[list[Spread], list[Passed]]:
    """Each cell shaped as a mean and its SD in a row whose label holds one of `labels`, at
    word edges and in any case, in reading order; and each such row passed over, with why.

    What can be said exactly decides, and what is unsure is said as not read (round 3 of
    #660), in this order, the label's HTML tags taken off:

    1. a label that names a standard error is not read, nor a cell under a header of the
       table's first row that names one;
    2. a label that names a change is not read (`names_a_change`);
    3. a label that names a mean or an SD is read, whatever the caption says, and so is a
       cell under a first-row header that names one;
    4. a label that names a category holds counts, and is not read;
    5. in a table that says n (%), in the `caption` or a cell of its first row, a cell
       whose first number has a point is read, since a count is whole, and one whose first
       number is whole may be a count, and is not read;
    6. anything else is read.
    """
    found: list[Spread] = []
    passed: list[Passed] = []
    header = table[0] if table else ()
    se_columns = _columns_naming(header, lambda text: _SE.search(text) is not None)
    mean_columns = _mean_columns(header)
    counted = _N_PERCENT.search(caption) is not None or any(
        _N_PERCENT.search(cell.text) for cell in header)
    for row in table:
        label = row[0].text if row else ""
        # A space for each tag, so that "Weight<sup>a</sup>" keeps "Weight" a word of its own.
        plain = _TAG.sub(" ", label)
        if not any(names(wanted, plain) for wanted in labels):
            continue
        shaped = [(column, cell, _CELL.fullmatch(_clean(cell.text)[0]))
                  for column, cell in list(_columns(row))[1:]]  # fmt: skip
        shaped = [(column, cell, match) for column, cell, match in shaped if match is not None]
        if not shaped:
            continue
        context, line = _context(row), shaped[0][1].line
        why = SE_LABEL if _SE.search(plain) else CHANGE if names_a_change(plain) else None
        if why is not None:
            passed.append(Passed(line, label, why, context))
            continue
        whys = [_cell_left_out(column, match, plain, se_columns, mean_columns, counted)
                for column, _cell, match in shaped]  # fmt: skip
        passed += [Passed(line, label, why, context) for why in _LEFT_OUT if why in whys]
        shaped = [one for one, why in zip(shaped, whys, strict=True) if why is None]
        for _column, cell, match in shaped:
            found.append(Spread(
                line=cell.line, printed=" ".join(cell.text.split()),
                mean=match["mean"].replace("\N{MINUS SIGN}", "-"),
                sd=match["bracketed"] or match["signed"], label=label, context=context,
            ))  # fmt: skip
    return found, passed


def _mean_columns(header) -> set[int]:
    """The columns under a first-row header that names a mean or an SD: "Mean (SD)"."""
    return _columns_naming(header, names_a_mean)


#: Why a cell of a row read is left out, in the order a row's reasons are said.
_LEFT_OUT = (SE_HEADER, CATEGORY, MAYBE_COUNT)


def _cell_left_out(column: int, match: re.Match[str], label: str, se_columns: set[int],
                   mean_columns: set[int], counted: bool) -> str | None:  # fmt: skip
    """Why a cell of a row whose label names no standard error and no change is left out,
    by rules 1 and 3 to 5 of `table_spreads`; None where it is read."""
    if column in se_columns:
        return SE_HEADER
    if names_a_mean(label) or column in mean_columns:
        return None
    if _CATEGORY.search(label):
        return CATEGORY
    if counted and _may_be_a_count(match):
        return MAYBE_COUNT
    return None


def names_a_mean(label: str) -> bool:
    """Whether a row's label, or a column's header, says its cells are a mean and its SD:
    "mean", "SD"."""
    return _MEAN_NAMED.search(label) is not None


def names_a_change(label: str) -> bool:
    """Whether a row's label names a change, which can be negative: not a time to one,
    "days to treatment change" (round 2 of #660); "from baseline to week 12" is one."""
    return any(_TO_ONE.search(label, 0, match.start()) is None
               for match in _CHANGE.finditer(label))  # fmt: skip


def _may_be_a_count(match: re.Match[str]) -> bool:
    """Whether a cell read as a mean and its SD may be a count and its share: its first
    number is whole, as a count is."""
    return "." not in match["mean"]


def _columns_naming(header, says) -> set[int]:
    """The columns under a header cell, its first column's aside, of which `says` holds."""
    return {each for column, cell in list(_columns(header))[1:] if says(cell.text)
            for each in range(column, column + max(cell.span, 1))}  # fmt: skip


def caption_of(lines: list[str], table: Table) -> str:
    """The paragraph above a table and the one below it, where a caption, or a note saying
    its cells are n (%), stands: up to `_CAPTION_LINES` lines each way, to a blank line. The
    one below stops at a line that opens another table's caption, "Table 2." (round 2 of
    #660), and the one above at the line that opens this table's."""
    if not table or not table[0]:
        return ""
    first = min(cell.line for cell in table[0])
    last = max(cell.line for row in table for cell in row)
    above: list[str] = []
    for at in range(first - 2, max(first - 2 - _CAPTION_LINES, -1), -1):
        if at < 0 or at >= len(lines):
            break
        if not lines[at].strip():
            if above:
                break
            continue
        above.insert(0, lines[at])
        if _CAPTION_OPENS.match(lines[at]):
            break
    below: list[str] = []
    for at in range(last, min(last + _CAPTION_LINES, len(lines))):
        if _CAPTION_OPENS.match(lines[at]):
            break
        if not lines[at].strip():
            if below:
                break
            continue
        below.append(lines[at])
    return "\n".join(above + below)


def _context(row) -> str:
    context = " | ".join(" ".join(cell.text.split()) for cell in row)
    if len(context) > _CONTEXT:
        context = context[: _CONTEXT - 1] + "\N{HORIZONTAL ELLIPSIS}"
    return context
