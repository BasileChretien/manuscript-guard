"""A paper's tables as rows of cells, where `audit` reads what a row's cells say together.

The rest of the audit reads a table as text, a cell to a line, and that is enough to find a
number. An n (%) is a number and its share of something named elsewhere in the table: the
column's header, the row's label, or the label of the rows it falls under. So a table is
read here as rows of cells, each cell with its text and the line it is on.

A Markdown table is a pipe table: a header row, a rule under it, and the rows under that
while each has a pipe. Read from the masked text, so that one in a code block or a comment
is not a table, and its cells from the text itself. A grid table or a simple table is not
read (DESIGN.md, Known gaps). A .docx table is read as Word lays it out
(`text.docx.read_docx_text`), a cell spanning columns counted as each of them.

Both write a superscript as Markdown does, `^a^`: in a .docx, a run raised as superscript
and a footnote's or an endnote's reference mark, which is how a row's label points to a
note under the table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.text.blocks import _TABLE_RULE
from manuscript_guard.text.masking import kept_breaks, mask

#: A pipe that is a cell's edge: not escaped.
_EDGE = re.compile(r"(?<!\\)\|")


@dataclass(frozen=True)
class TableCell:
    #: What the cell shows, a superscript written `^a^`.
    text: str
    #: The line it starts on, from 1, in the text `audit` reads.
    line: int
    #: How many of the table's columns it spans.
    span: int = 1


Table = tuple[tuple[TableCell, ...], ...]


def markdown_tables(text: str) -> list[Table]:
    """Each pipe table in a Markdown text, its header row first. The mask is read with every
    line break of the text, so that its lines are the text's: one under a comment of several
    lines was read a line out for each (corpus round, 2026-10-23)."""
    lines = text.split("\n")
    shown = kept_breaks(text, mask(text)).split("\n")
    tables: list[Table] = []
    index = 0
    while index + 1 < len(shown):
        if not _row_shaped(shown[index]) or not _TABLE_RULE.match(shown[index + 1]):
            index += 1
            continue
        rows = [_cells(lines[index], index + 1)]
        end = index + 2
        while end < len(shown) and _row_shaped(shown[end]):
            rows.append(_cells(lines[end], end + 1))
            end += 1
        tables.append(tuple(rows))
        index = end
    return tables


def _row_shaped(line: str) -> bool:
    """A line with a cell's edge in it, not indented as code."""
    return bool(_EDGE.search(line)) and not line.startswith(("    ", "\t"))


def _cells(line: str, number: int) -> tuple[TableCell, ...]:
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return tuple(TableCell(part.strip(), number) for part in _EDGE.split(inner))
