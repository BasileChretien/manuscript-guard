"""`audit --non-negative`: a mean and its SD, in the rows of a table the auditor names, held
to a floor of 0.

The auditor names the rows whose variable cannot be negative, a weight, a concentration, a
length of stay, by a word or words of their label, as `--whole-numbers` names its rows. Each
cell there printed as a mean and its SD, "12.3 (4.5)" or "12.3 ± 4.5", is read, and one whose
mean is less than twice its SD shows skewed data (`stats/skew.py`): a warning in the
Arithmetic section, `mean-sd-skewed`, which `--strict` does not count. A named row whose
label, or the table's first row over its cells, names a standard error is not read, nor one
whose label names a change or a percentage, a cell under a header naming a percentage, or a
count and its share where the caption or the header says n (%); each is said as a note, and
a label under which nothing was read is said too.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.audit import AuditReport, Disagreement
from manuscript_guard.stats.granularity import names
from manuscript_guard.stats.skew import caption_of, said, table_spreads
from manuscript_guard.text.tables import Table

CODE = "mean-sd-skewed"
#: The floor `--non-negative` holds a mean to.
FLOOR = "0"
#: The flag, as the text names it.
FLAG = "--non-negative"


def non_negative_means(
    report: AuditReport, path: Path, tables: list[Table], text: str = ""
) -> list[Disagreement]:
    """Each mean and its SD in a row --non-negative named, returned where the mean is less
    than twice the SD; each named row not read is kept in the report, and a label under
    which a cell was read, or a row passed over, is taken off the labels that read nothing.
    `text` is the paper's, whose lines the tables' cells name: the paragraph above or below
    a table is read for a caption that says its cells are n (%)."""
    found = []
    lines = text.split("\n")
    for table in tables:
        spreads, passed = table_spreads(table, report.non_negative, caption_of(lines, table))
        for spread in spreads:
            report.spreads_read += 1
            _found(report, spread.label)
            if spread.skewed:
                found.append(Disagreement(
                    path, spread.line, f"{spread.printed}: {said(spread.mean, spread.sd, FLOOR)}",
                    spread.context, code=CODE,
                ))  # fmt: skip
        for row in passed:
            _found(report, row.label)
            report.non_negative_unread.append(Disagreement(
                path, row.line, f"{FLAG} row {row.label!r}: not read, as {row.why}", row.context,
            ))  # fmt: skip
    return found


def _found(report: AuditReport, label: str) -> None:
    report.non_negative_unfound = [
        wanted for wanted in report.non_negative_unfound if not names(wanted, label)
    ]


def unfound(label: str) -> str:
    """What is said of a label under which nothing was read."""
    return f"{FLAG} {label!r}: no mean (SD) was read in a row whose label holds it"


def lines(report: AuditReport, show) -> list[str]:
    """What the Arithmetic section says of --non-negative: how many were read, each row not
    read, and each label that read nothing. The skewed ones are among the numbers that do not
    fit the ones beside them."""
    if not report.non_negative:
        return []
    skewed = sum(1 for d in report.disagreements if d.code == CODE)
    out = [
        f"Means and SDs of variables that cannot be negative ({FLAG}): {report.spreads_read} "
        f"read in the rows named, {skewed} with a mean less than twice its SD."
    ]
    by_paper: dict[Path, list[Disagreement]] = {}
    for item in report.non_negative_unread:
        by_paper.setdefault(item.source, []).append(item)
    for source, listed in by_paper.items():
        out.append(f"  {show(source)}")
        out += [f"    {show.at(source, item.line)}: {item.message}" for item in listed]
    out += [f"  {unfound(label)}" for label in report.non_negative_unfound]
    return out


def items(report: AuditReport, item, section: str) -> list:
    """The report's items for --non-negative beyond the skewed means: each row not read and
    each label that read nothing, notes."""
    from manuscript_guard.findings import INFO

    return [
        *(item(section, "audit", "non-negative-unread", d.message, INFO, False, d.source,
               d.line, d.context) for d in report.non_negative_unread),
        *(item(section, "audit", "non-negative-unfound", unfound(label), INFO, False)
          for label in report.non_negative_unfound),
    ]  # fmt: skip
