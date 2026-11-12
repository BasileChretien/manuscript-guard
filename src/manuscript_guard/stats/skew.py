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
names, with a floor of 0 (`auditing/skew.py`). There a row is passed over, and said, where
it is not a mean (SD) of the measure named: a standard error, a percentage, counts and their
shares under a table that says n (%), or a change, which can be negative.
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
#: What names a change, which can be negative: the words, "from baseline", or a delta.
_CHANGE = re.compile(
    r"(?i:\b(?:change[sd]?|differences?|delta)\b|\bfrom\s+baseline\b)"
    r"|[\N{GREEK CAPITAL LETTER DELTA}\N{INCREMENT}]"
)
#: What says a table's cells are counts and their shares: n (%), N (%), No. (%) or n/N (%).
_N_PERCENT = re.compile(r"(?<![\w.])(?:[nN]|No\.|n/N)\s*\(\s*%\s*\)")
#: A count and its share, as such a table prints one: a whole number, and a decimal of 100
#: or less in brackets.
_COUNT_SHARE = re.compile(r"(?P<count>\d+)\s*\(\s*(?P<share>\d*\.\d+)\s*\)")
#: What says a header's column holds means as well: "mean", "SD".
_MEAN_NAMED = re.compile(r"(?i:\bmean\b)|\bSD\b")
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
PERCENT = "its label names a percentage"
PERCENT_HEADER = "the header over its cells names a percentage"
COUNTS = "its cells are counts and their shares, as the table says n (%)"
CHANGE = "its label names a change or a difference, which can be negative"


def table_spreads(
    table: Table, labels: tuple[str, ...], caption: str = ""
) -> tuple[list[Spread], list[Passed]]:
    """Each cell shaped as a mean and its SD in a row whose label holds one of `labels`, at
    word edges and in any case, in reading order; and each such row passed over, with why.
    A row is passed over whole where its label names a standard error, a change or a
    percentage. A cell is passed over where the header over it names a standard error or a
    percentage, and where it is a count and its share, "5 (12.5)", and the `caption` or a
    header says n (%). The header is the table's first row: a second header row is read as
    a row."""
    found: list[Spread] = []
    passed: list[Passed] = []
    header = table[0] if table else ()
    se_columns = _columns_naming(header, lambda text: _SE.search(text) is not None)
    # A header of "n (%) or mean (SD)" holds means too: its counts are told by their shape.
    percent_columns = _columns_naming(
        header, lambda text: "%" in text and _MEAN_NAMED.search(text) is None)
    counted = _N_PERCENT.search(caption) is not None or any(
        _N_PERCENT.search(cell.text) for cell in header)
    # What leaves a cell of a named row out, in order, each said once for the row.
    left_outs = (
        (SE_HEADER, lambda column, match: column in se_columns),
        (PERCENT_HEADER, lambda column, match: column in percent_columns),
        (COUNTS, lambda column, match: counted and _count_and_share(match)),
    )
    for row in table:
        label = row[0].text if row else ""
        if not any(names(wanted, label) for wanted in labels):
            continue
        shaped = [(column, cell, _CELL.fullmatch(_clean(cell.text)[0]))
                  for column, cell in list(_columns(row))[1:]]  # fmt: skip
        shaped = [(column, cell, match) for column, cell, match in shaped if match is not None]
        if not shaped:
            continue
        context, line = _context(row), shaped[0][1].line
        why = (SE_LABEL if _SE.search(label) else CHANGE if _CHANGE.search(label)
               else PERCENT if "%" in label else None)  # fmt: skip
        if why is not None:
            passed.append(Passed(line, label, why, context))
            continue
        for reason, left_out in left_outs:
            if any(left_out(column, match) for column, _cell, match in shaped):
                passed.append(Passed(line, label, reason, context))
            shaped = [one for one in shaped if not left_out(one[0], one[2])]
        for _column, cell, match in shaped:
            found.append(Spread(
                line=cell.line, printed=" ".join(cell.text.split()),
                mean=match["mean"].replace("\N{MINUS SIGN}", "-"),
                sd=match["bracketed"] or match["signed"], label=label, context=context,
            ))  # fmt: skip
    return found, passed


def _columns_naming(header, says) -> set[int]:
    """The columns under a header cell, its first column's aside, of which `says` holds."""
    return {each for column, cell in list(_columns(header))[1:] if says(cell.text)
            for each in range(column, column + max(cell.span, 1))}  # fmt: skip


def _count_and_share(match: re.Match[str]) -> bool:
    """Whether a cell read as a mean and its SD is a whole count and a share of 100 or less
    in round brackets, "5 (12.5)", as a table of n (%) prints one."""
    shaped = _COUNT_SHARE.fullmatch(match.group())
    return shaped is not None and Decimal(shaped["share"]) <= 100


def caption_of(lines: list[str], table: Table) -> str:
    """The paragraph above a table and the one below it, where a caption, or a note saying
    its cells are n (%), stands: up to `_CAPTION_LINES` lines each way, to a blank line."""
    if not table or not table[0]:
        return ""
    first = min(cell.line for cell in table[0])
    last = max(cell.line for row in table for cell in row)
    above, below = [], []
    for at in range(first - 2, max(first - 2 - _CAPTION_LINES, -1), -1):
        if at < 0 or at >= len(lines):
            break
        if not lines[at].strip():
            if above:
                break
            continue
        above.insert(0, lines[at])
    for at in range(last, min(last + _CAPTION_LINES, len(lines))):
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
