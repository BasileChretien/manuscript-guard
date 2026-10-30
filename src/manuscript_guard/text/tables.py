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

from manuscript_guard.text.blocks import _GRID_TOP, _TABLE_RULE
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


#: A line of dashes in runs, a rule of a simple or a multiline table: "-------   ------".
_DASHES = re.compile(r" {0,3}(-+)(?:[ \t]+-+)*[ \t]*")
#: A grid table's row or border, which goes on from its top border.
_GRID_LINE = re.compile(r"[+|]")


def table_lines(text: str) -> frozenset[int]:
    """The lines, from 0, of every table in a Markdown text: a pipe table, a grid table, a
    simple table and a multiline table, as pandoc's manual shapes them. `text` is read as
    given, so a caller that wants a table in a listing or a comment left out masks it first.

    Pandoc writes a Word table as a simple or a multiline table where its cells allow, so a
    paper converted from Word has those more than pipe tables. Each is read only where it
    has every part pandoc's manual gives it, and is otherwise not a table: a column's
    dashes in one run, which a setext heading's underline and a rule are, open none, nor
    does a line of dashes that no other closes before two blank lines. Read wrong, prose
    would be left out of what a rate counts; so the reading errs towards prose (DESIGN.md,
    Known gaps)."""
    return _Tables(text.split("\n")).lines()


#: A block quotation's marks at the start of a line, nested ones among them.
_QUOTED = re.compile(r"^(?: {0,3}>[ \t]?)+")
#: A list item's marker before the rest of its line.
_LIST_MARK = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
#: A simple or multiline table's columns: two runs of dashes or more, three dashes each.
_COLUMNS = re.compile(r"-{3,}(?:[ \t]+-{3,})+")


def count_tables(text: str) -> tuple[int, bool]:
    """How many tables a Markdown text prints, of the four kinds `table_lines` reads, and
    whether every line shaped as a table's rule or border was read as part of one. One in a
    fenced block, an HTML comment or the front matter is not one (`mask`); one in a block
    quotation is read as its quotation holds it. A table indented in a list item is not read,
    and its rule says so: the count is then not exact, and `audit --journal` says the table
    limits were not checked, rather than counting it as none. A table written in HTML is not
    counted either (`audit --journal` says that too)."""
    lines = [_QUOTED.sub("", line) for line in kept_breaks(text, mask(text)).split("\n")]
    spans = _Tables(lines).spans()
    inside = {at for start, end in spans for at in range(start, end)}
    unread = any(at not in inside and _table_shaped(line) for at, line in enumerate(lines))
    return len(spans), not unread


def _table_shaped(line: str) -> bool:
    """Whether a line, its indentation and any list marker set aside, is a table's rule or
    border: a pipe table's rule, a grid table's border, or a simple table's columns."""
    bare = _LIST_MARK.sub("", line).strip()
    return (("|" in bare and _TABLE_RULE.match(bare) is not None) or bool(_GRID_TOP.match(bare))
            or bool(_COLUMNS.fullmatch(bare)))  # fmt: skip


class _Tables:
    def __init__(self, lines: list[str]) -> None:
        self.text = lines
        count = len(lines)
        self.runs = [_dash_runs(line) for line in lines]
        blank = [not line.strip() for line in lines]
        # From each line, the first line of dashes with a blank line or the end under it,
        # and the first of two blank lines, past which no table's rows run. Found once, so
        # that a text of openers no line closes is read in one pass and not one per opener.
        self.closing: list[int | None] = [None] * (count + 1)
        self.gap = [count] * (count + 1)
        for at in range(count - 1, -1, -1):
            closes = self.runs[at] and (at + 1 == count or blank[at + 1])
            self.closing[at] = at if closes else self.closing[at + 1]
            two = blank[at] and at + 1 < count and blank[at + 1]
            self.gap[at] = at if two else self.gap[at + 1]

    def lines(self) -> frozenset[int]:
        return frozenset(at for start, end in self.spans() for at in range(start, end))

    def spans(self) -> list[tuple[int, int]]:
        """Each table, as its lines `[start, end)`, in order."""
        found: list[tuple[int, int]] = []
        index = 0
        while index < len(self.text):
            end = self._from(index)
            if end is None:
                index += 1
                continue
            found.append((index, end))
            index = end
        return found

    def _from(self, index: int) -> int | None:
        """The line after the last of a table that opens on line `index`, or None."""
        lines = self.text
        line = lines[index]
        below = lines[index + 1] if index + 1 < len(lines) else ""
        if _row_shaped(line) and _TABLE_RULE.match(below):
            end = index + 2
            while end < len(lines) and _row_shaped(lines[end]):
                end += 1
            return end
        if _GRID_TOP.match(line):
            end = index + 1
            while end < len(lines) and _GRID_LINE.match(lines[end]):
                end += 1
            # A grid table ends on a border, and one never closed is text.
            return next((n + 1 for n in range(end - 1, index, -1) if _GRID_TOP.match(lines[n])),
                        None)  # fmt: skip
        opens_block = index == 0 or not lines[index - 1].strip()
        if not opens_block or not line.strip() or not below.strip():
            return None
        if self.runs[index] == 1:
            return self._multiline(index)
        if self.runs[index] >= 2:
            # Headless: its rows run to a line of dashes with a blank line or the end under it.
            return self._closed(index + 1)
        if self.runs[index + 1] >= 2:
            # A simple table's header over its columns' dashes: its rows run to a blank line.
            end = index + 2
            while end < len(lines) and lines[end].strip():
                end += 1
            return end
        return None

    def _multiline(self, index: int) -> int | None:
        """A multiline table opening on a line of dashes in one run: its header runs down to
        its columns' dashes, and its rows, a blank line between each two, to a closing line."""
        for at in range(index + 1, len(self.text)):
            if not self.text[at].strip():
                return None
            if self.runs[at]:
                return self._closed(at + 1) if self.runs[at] >= 2 else None
        return None

    def _closed(self, start: int) -> int | None:
        """The line after the first closing line of dashes from `start`, or None where two
        blank lines or the end come first."""
        closing = self.closing[start]
        return closing + 1 if closing is not None and closing < self.gap[start] else None


def _dash_runs(line: str) -> int:
    """How many runs of dashes a line of dashes holds, and 0 for any other line. A first
    run of one dash is a list item's marker or a rule's, "- - -", and opens no table."""
    found = _DASHES.fullmatch(line)
    if found is None or len(found.group(1)) < 2:
        return 0
    return len(line.split())


def _row_shaped(line: str) -> bool:
    """A line with a cell's edge in it, not indented as code."""
    return bool(_EDGE.search(line)) and not line.startswith(("    ", "\t"))


def _cells(line: str, number: int) -> tuple[TableCell, ...]:
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return tuple(TableCell(part.strip(), number) for part in _EDGE.split(inner))
