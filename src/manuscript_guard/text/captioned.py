"""Each table a paper types, with its caption and its header row, for a check that reads a
table by what its caption says it is and what its columns are headed (G8's baseline check,
`gates/baseline.py`, in `check` and in `audit --design trial`).

- A Markdown pipe table is read as `text.tables.markdown_tables` reads one, and a grid table
  from its top border: its header is the rows above its `+===+` line, each column's text
  joined across its lines. A grid table with no such line has no header, and neither is read
  in a fenced block or a comment. A simple or multiline table is not read (DESIGN.md, Known
  gaps). Its caption is pandoc's, `Table: ...` or `: ...`, in the paragraph after the table
  or before it, or a legend typed before or after it as Word's is, "Table 1. ...".
- A LaTeX table, a `tabular` or another of the environments the reader reads
  (`text.latex.tables`), has the caption of the `table` float it stands in, or a
  `longtable`'s own; its header is its first row.
- A Word table (`text.docx`), read as `audit` reads one, has the legend in the paragraph
  before it or after it, or else the paragraph before it; its header is its first row.

A table's line is its header row's, from 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.text.blocks import _GRID_TOP
from manuscript_guard.text.masking import kept_breaks, mask
from manuscript_guard.text.tables import Table, markdown_tables


@dataclass(frozen=True)
class Captioned:
    """A table's caption, its header row's cells, and the line its header row starts on."""

    caption: str
    headers: tuple[str, ...]
    line: int


#: Pandoc's caption of a table, "Table: ..." or ": ...", which opens its paragraph.
_PANDOC = re.compile(r"[ ]{0,3}(?:[Tt]able)?:[ \t]+(?=\S)")
#: A legend typed as one, "Table 1. ...", "**Table S2:** ...", "eTable 3 - ...".
_LEGEND = re.compile(
    r"[ \t]*[*_]*(?:Supplementary[ \t]+|e|S)?Table[ \t]+[A-Za-z]?\d+[A-Za-z]?[*_]*[ \t]*"
    "[.:|\N{EN DASH}\N{EM DASH}-]"
)
#: A grid table's line, and the line under its header.
_GRID_LINE = re.compile(r"[+|]")
_GRID_HEADER_RULE = re.compile(r"\+(?:[=:]+\+)+[ \t]*$")


def markdown_captioned(text: str) -> list[Captioned]:
    """Each pipe and grid table of a Markdown text, in the order they stand."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    shown = [line.rstrip("\r") for line in kept_breaks(text, mask(text)).split("\n")]
    found: list[tuple[int, Captioned]] = []
    for table in markdown_tables(text):
        first, last = table[0][0].line, table[-1][0].line
        headers = tuple(cell.text.strip() for cell in table[0])
        found.append((first, Captioned(_caption(lines, shown, first, last), headers, first)))
    for first, last, headers in _grid_tables(lines, shown):
        # Its header row's first line is the one under its top border.
        caption = _caption(lines, shown, first, last)
        found.append((first, Captioned(caption, headers, first + 1)))
    return [captioned for _first, captioned in sorted(found, key=lambda one: one[0])]


def _grid_tables(lines: list[str], shown: list[str]) -> list[tuple[int, int, tuple[str, ...]]]:
    """Each grid table with a header: its first and last lines, from 1, and its header's
    cells, each column's text across the header's lines joined by a space."""
    found = []
    index = 0
    while index < len(shown):
        if not _GRID_TOP.match(shown[index]):
            index += 1
            continue
        end = index + 1
        while end < len(shown) and _GRID_LINE.match(shown[end]):
            end += 1
        last = next((n for n in range(end - 1, index, -1) if _GRID_TOP.match(shown[n])), None)
        if last is None:
            index += 1
            continue
        rule = next((n for n in range(index + 1, last + 1)
                     if _GRID_HEADER_RULE.match(shown[n])), None)  # fmt: skip
        if rule is not None:
            found.append((index + 1, last + 1, _grid_header(lines, index, rule)))
        index = last + 1
    return found


def _grid_header(lines: list[str], top: int, rule: int) -> tuple[str, ...]:
    """The header of a grid table whose top border is line `top` and whose header ends at
    the line `rule`, from 0: its columns are where the top border's `+` stand."""
    edges = [at for at, char in enumerate(lines[top]) if char == "+"]
    columns: list[list[str]] = [[] for _ in edges[1:]]
    for line in lines[top + 1 : rule]:
        for column, (left, right) in enumerate(zip(edges, edges[1:], strict=False)):
            part = line[left + 1 : right].strip()
            if part:
                columns[column].append(part)
    return tuple(" ".join(parts) for parts in columns)


def _caption(lines: list[str], shown: list[str], first: int, last: int) -> str:
    """The caption of the table on lines `first` to `last` (from 1): pandoc's after it, then
    pandoc's or a legend before it, then a legend after it; "" where there is none. Pandoc's
    caption between two tables is the one's above it."""
    after, _beyond = _paragraph(lines, shown, last + 1, 1)
    before, beyond = _paragraph(lines, shown, first - 1, -1)
    if before and _PANDOC.match(before[0]) and _table_above(shown, beyond):
        before = []
    for paragraph, shapes in ((after, (_PANDOC,)), (before, (_PANDOC, _LEGEND)),
                              (after, (_LEGEND,))):  # fmt: skip
        if paragraph and any(shape.match(paragraph[0]) for shape in shapes):
            return _said(paragraph)
    return ""


def _paragraph(lines: list[str], shown: list[str], start: int, step: int
               ) -> tuple[list[str], int]:  # fmt: skip
    """The paragraph next to a table, from line `start` (from 1) on in the direction of
    `step`, past one blank line at most, its lines in their order, and the line past it;
    [] where a table's line or the end of the text comes first."""
    at = start
    if 1 <= at <= len(lines) and not shown[at - 1].strip():
        at += step
    taken: list[str] = []
    while 1 <= at <= len(lines) and shown[at - 1].strip():
        if _GRID_LINE.match(shown[at - 1].lstrip()):
            break
        taken.append(lines[at - 1])
        at += step
    return (taken if step > 0 else taken[::-1]), at


def _table_above(shown: list[str], at: int) -> bool:
    """Whether a table's line stands at line `at` (from 1), or past one blank line above."""
    if 1 <= at <= len(shown) and not shown[at - 1].strip():
        at -= 1
    return 1 <= at <= len(shown) and _GRID_LINE.match(shown[at - 1].lstrip()) is not None


def _said(paragraph: list[str]) -> str:
    """A caption's paragraph as one line, pandoc's mark taken off."""
    text = " ".join(" ".join(paragraph).split())
    found = _PANDOC.match(text)
    return text[found.end():] if found else text


# ---------------------------------------------------------------------------------- LaTeX

#: Where a table float begins or ends.
_FLOAT = re.compile(r"\\(?P<edge>begin|end)\s*\{(?:sideways)?table\*?\}")


def latex_captioned(source) -> list[Captioned]:
    """Each table typed in a LaTeX file (`text.latex.structure.Source`), with the caption of
    the float it stands in or its own, a `longtable`'s."""
    from manuscript_guard.text.latex.printed import caption_spans
    from manuscript_guard.text.latex.tables import spanned_tables

    captions = caption_spans(source)
    floats = _floats(source.text)
    found = []
    for (start, end), table in spanned_tables(source):
        around = next(((low, high) for low, high in floats if low <= start and end <= high),
                      (start, end))  # fmt: skip
        caption = next((source.text[opened:closed] for opened, closed in captions
                        if around[0] <= opened and closed <= around[1]), "")  # fmt: skip
        headers = tuple(cell.text.strip() for cell in table[0])
        found.append(Captioned(" ".join(caption.split()), headers, table[0][0].line))
    return found


def _floats(text: str) -> list[tuple[int, int]]:
    """Where each table float runs, innermost first where one holds another."""
    opened: list[int] = []
    spans: list[tuple[int, int]] = []
    for edge in _FLOAT.finditer(text):
        if edge["edge"] == "begin":
            opened.append(edge.start())
        elif opened:
            spans.append((opened.pop(), edge.end()))
    return spans


# ----------------------------------------------------------------------------------- Word


def docx_captioned(lines: list[str], tables: list[Table]) -> list[Captioned]:
    """Each table of a .docx as `audit` reads it, `lines` being its text a paragraph to a
    line: its caption the legend before it or after it, or else the paragraph before it."""
    found = []
    for table in tables:
        cells = [cell.line for row in table for cell in row]
        first, last = min(cells), max(cells)
        inside = set(range(first, last + 1))
        before = _beside(lines, first - 1, -1, inside)
        after = _beside(lines, last + 1, 1, inside)
        shaped = [said for said in (before, after) if _LEGEND.match(said) or _PANDOC.match(said)]
        caption = _said([(shaped or [before])[0]])
        found.append(Captioned(caption, tuple(cell.text.strip() for cell in table[0]), first))
    return found


def _beside(lines: list[str], start: int, step: int, inside: set[int]) -> str:
    """The first line with text from `start` (from 1) in the direction of `step`, not one
    of the table's own: a line of nothing but a cell's edge, as a row is read, is passed
    over."""
    at = start
    while 1 <= at <= len(lines):
        if at not in inside and lines[at - 1].strip(" \t|"):
            return lines[at - 1].strip()
        at += step
    return ""


__all__ = ["Captioned", "docx_captioned", "latex_captioned", "markdown_captioned"]
