"""`audit --design trial`: a randomised trial's table of baseline characteristics with a
column of P values, in a paper written outside manuscript-guard.

The reader declares the design; nothing here guesses it. Each table the audit reads as rows
of cells is read as `check` reads one (`gates.baseline`): a Markdown pipe or grid table, a
.docx's table, and a LaTeX file's tables through its reader, each with its caption
(`text.captioned`). One whose caption names a table of baseline characteristics and whose
header row has a P header is a warning, `baseline-p-values`, which `--strict` does not count.
A PDF's tables are read as lines of text, with no cells, so none of them is read, and the
report says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.gates.baseline import CODE, HINT, SAYS, names_baseline, p_columns

#: The design `--design` takes for this check: a randomised trial's.
TRIAL = "trial"
#: The designs `--design` takes that this check reads.
DESIGNS = (TRIAL,)
#: The report's section.
SECTION = "Baseline tables"
#: What is said of a PDF, whose tables are not read.
UNREAD = ("its tables are lines of text, not rows of cells, so no table's caption and header "
          "were read for P values at baseline")  # fmt: skip


@dataclass(frozen=True)
class Baseline:
    """A table of baseline characteristics with a column of P values: where its header row
    is, its caption, and the P headers. `source` and `context` as the report lists them."""

    source: Path
    line: int
    caption: str
    headers: tuple[str, ...]

    @property
    def message(self) -> str:
        return said(self)

    @property
    def context(self) -> str:
        return self.caption


@dataclass
class BaselineRead:
    """What `--design trial` read: how many tables, how many captioned as of baseline
    characteristics, each of those with a column of P values, and the files whose tables
    were not read."""

    design: str
    tables: int = 0
    baseline: int = 0
    found: list[Baseline] = field(default_factory=list)
    unread: list[Path] = field(default_factory=list)


def baseline_tables(sources: list, design: str) -> BaselineRead:
    """Each table of each source (`audit._Source`) captioned as of baseline characteristics
    with a column of P values."""
    from manuscript_guard.text.captioned import docx_captioned, latex_captioned, markdown_captioned
    from manuscript_guard.text.docx import is_docx

    read = BaselineRead(design)
    for source in sources:
        path = source.path
        if source.latex is not None:
            tables = latex_captioned(source.latex)
        elif path.suffix.lower() == ".pdf":
            read.unread.append(path)
            continue
        elif is_docx(path):
            tables = docx_captioned(source.text.split("\n"), list(source.tables))
        else:
            tables = markdown_captioned(source.text)
        read.tables += len(tables)
        for table in tables:
            if not names_baseline(table.caption):
                continue
            read.baseline += 1
            headers = p_columns(table.headers)
            if headers:
                read.found.append(Baseline(path, table.line, table.caption, headers))
    return read


def said(one: Baseline) -> str:
    """What the report says of one table."""
    named = " and ".join(repr(header) for header in one.headers)
    return (f"a table captioned as of baseline characteristics has a column of P values "
            f"({named}), and the study is a randomised trial (--design): {SAYS}")  # fmt: skip


def items(read: BaselineRead | None) -> list:
    """Each table with P values at baseline, a warning not counted; each file whose tables
    were not read, a note."""
    if read is None:
        return []
    from manuscript_guard.auditing.report import Item
    from manuscript_guard.findings import INFO, WARN

    return [*(Item(SECTION, "audit", CODE, said(one), WARN, False, one.source, one.line,
                   one.caption, HINT) for one in read.found),
            *(Item(SECTION, "audit", "baseline-tables-not-read", f"{path.name}: {UNREAD}", INFO,
                   False, path) for path in read.unread)]  # fmt: skip


def lines(read: BaselineRead, show, listed) -> list[str]:
    """The section's text: what was read, then each table, with `listed` the report's way of
    listing items under their files."""
    out = [f"  {read.tables} table{'s' if read.tables != 1 else ''} read, "
           f"{read.baseline} captioned as of baseline characteristics."]  # fmt: skip
    out += listed("A COLUMN OF P VALUES IN A TABLE OF BASELINE CHARACTERISTICS (not counted by "
                  "--strict):", read.found, show)  # fmt: skip
    if not read.found:
        out.append("  No table of baseline characteristics read has a column of P values.")
    out += [f"  {show(path)}: {UNREAD}." for path in read.unread]
    return out


def counts(read: BaselineRead | None) -> dict[str, int]:
    if read is None:
        return {}
    return {"baseline_tables_read": read.tables, "baseline_tables": read.baseline,
            "baseline_p_values": len(read.found)}  # fmt: skip


__all__ = ["DESIGNS", "SECTION", "TRIAL", "Baseline", "BaselineRead", "baseline_tables",
           "counts", "items", "lines", "said"]  # fmt: skip
