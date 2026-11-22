"""Where each table's and each figure's own text runs, which G14 reads apart from the text.

"A caption, legend or note defines for its own table or figure only: its definitions cover
the uses in that table, and are never compared with the text's" (Basile, 2026-11-21, "Table
stands alone"). A display's own text is found by its shape, never by its words:

* in Markdown, a table's lines (`text.tables.table_spans`); its caption, pandoc's (`Table:`,
  or `:` beside it) or a legend that opens with its number, "**Table 2.** ...", above it or
  under it; APA's number alone above its title, "Table 1." then "*Means by group.*"; and the
  notes under it, each paragraph that opens with a note's mark ("Note", "Abbreviations", a
  footnote's) or pairs a short form with its long form, "ICC: intraclass correlation"
  (`noted`). A legend with no table beside it, a figure's, is a display of its own, and so
  are the notes under it. A heading, or anything G14 does not read, ends a display;
* in LaTeX, a table's float, `table` or `sidewaystable`, whole; and a `tabular` or its kin
  that stands in no float. A figure's float is not read by G14 at all.

Each display is a span `[start, end)` of the file, in order, none inside another.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from manuscript_guard.text.masking import kept_breaks, mask
from manuscript_guard.text.tables import table_spans

#: Pandoc's caption line of a table: `Table: ...`, or `: ...`.
_PANDOC = re.compile(r"[ ]{0,3}(?:[Tt]able:|:(?![^\w\s]))")
#: A legend PLOS writes, its number before the display's name: "**S1 Table.** ...", "S2 Fig.".
_NUMBER_FIRST = re.compile(
    r"[\s*_]*S\d+[ \t]+(?:Table|Fig(?:ure)?)\b[*_]*[ \t]*[.:|\N{EN DASH}\N{EM DASH}-]")
#: What may stand around a legend's number when it is all the paragraph holds: "Table 1.",
#: "**Table 1**", "*Table 1:*".
_MARKS = " \t*_.:\N{EN DASH}\N{EM DASH}-"

TABLE, CAPTION, LEGEND, TEXT, BARRIER = "table", "caption", "legend", "text", "barrier"


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    #: A legend that holds its number alone, "Table 1.", whose title is the next paragraph.
    bare: bool = False


def markdown_displays(
    text: str,
    prose: str,
    captions: Iterable[tuple[int, int]],
    noted: Callable[[int, int], bool],
) -> tuple[tuple[int, int], ...]:
    """Each display of a Markdown file. `prose` is the text G14 reads, of `text`'s length,
    what it does not read spaces; `captions` where its captions and legends run
    (`glossary.markdown_captions`); `noted(start, end)` whether the paragraph there is a
    note."""
    blocks = _blocks(text, prose, tuple(captions))
    units: list[list[int]] = [[at] for at, block in enumerate(blocks) if block.kind == TABLE]
    owner = {unit[0]: unit for unit in units}
    taken: set[int] = set(owner)
    for at, block in enumerate(blocks):
        if at in taken or block.kind not in (CAPTION, LEGEND):
            continue
        found = _placed(blocks, at, owner, taken)
        if found is None:
            found = [at]
            if block.bare and _kind(blocks, at + 1) == TEXT:
                found.append(at + 1)
            units.append(found)
        taken.update(found)
    for unit in units:
        after = max(unit) + 1
        while (_kind(blocks, after) == TEXT and after not in taken
               and noted(blocks[after].start, blocks[after].end)):  # fmt: skip
            unit.append(after)
            taken.add(after)
            after += 1
    spans = sorted((blocks[min(unit)].start, blocks[max(unit)].end) for unit in units)
    return tuple(spans)


def _placed(blocks: list[_Block], at: int, owner: dict[int, list[int]], taken: set[int]
            ) -> list[int] | None:  # fmt: skip
    """The caption or legend at `at` given to the table it captions, the blocks it brings
    with it: pandoc's to the table above it where that one has no caption of pandoc's yet,
    else to the one under it, as pandoc reads it; a legend to the table under it, across its
    title where it holds its number alone, else to the one above it. None where no table
    stands beside it."""
    block = blocks[at]
    above, below = at - 1, at + 1
    if block.kind == CAPTION:
        if _kind(blocks, above) == TABLE and not any(
            blocks[each].kind == CAPTION for each in owner[above][1:]
        ):
            owner[above].append(at)
            return [at]
        if _kind(blocks, below) == TABLE:
            owner[below].append(at)
            return [at]
        return None
    if block.bare and _kind(blocks, below) == TEXT and _kind(blocks, below + 1) == TABLE \
            and below not in taken:  # fmt: skip
        owner[below + 1] += [at, below]
        return [at, below]
    if _kind(blocks, below) == TABLE:
        owner[below].append(at)
        return [at]
    if _kind(blocks, above) == TABLE and not any(
        blocks[each].kind == LEGEND for each in owner[above][1:]
    ):
        owner[above].append(at)
        return [at]
    return None


def _kind(blocks: list[_Block], at: int) -> str:
    return blocks[at].kind if 0 <= at < len(blocks) else BARRIER


def _blocks(text: str, prose: str, captions: tuple[tuple[int, int], ...]) -> list[_Block]:
    """The file as blocks, in order: each table whole, and each paragraph outside the
    tables, a caption, a legend or a paragraph of text, read line by line from where its
    first line starts. A blank line ends a paragraph, and so does a table's line. A line G14
    reads nothing of, a hidden heading's, is a barrier of its own, blank lines around it or
    none: a heading glued to the paragraph under it ends a display all the same (round 1 of
    #759)."""
    tables = _table_offsets(text)
    found: list[_Block] = [_Block(start, end, TABLE) for start, end in tables]
    captions = tuple(sorted(captions))
    run: list[tuple[int, int]] = []

    def close() -> None:
        if run:
            found.append(_paragraph(text, prose, run[0][0], run[-1][1], captions))
            run.clear()

    at = 0
    for line in text.split("\n"):
        start, end = at, at + len(line)
        at = end + 1
        if _near(tables, start, max(end, start + 1)) or not line.strip():
            close()
        elif not prose[start:end].strip():
            close()
            found.append(_Block(start, end, BARRIER))
        else:
            run.append((start, end))
    close()
    return sorted(found, key=lambda block: block.start)


def _paragraph(text: str, prose: str, start: int, end: int,
               captions: tuple[tuple[int, int], ...]) -> _Block:  # fmt: skip
    if _near(captions, start, end):
        if _PANDOC.match(text, start):
            return _Block(start, end, CAPTION)
        return _Block(start, end, LEGEND, _bare(prose[start:end].strip()))
    if _NUMBER_FIRST.match(prose, start):
        return _Block(start, end, LEGEND)
    return _Block(start, end, TEXT)


def _bare(legend: str) -> bool:
    """Whether a legend holds its display's number and nothing more, "Table 1.", as APA
    types it over the table's title."""
    from manuscript_guard.gates.pointers import opening_pointer

    pointer = opening_pointer(legend)
    return pointer is not None and not legend[pointer.end():].strip(_MARKS)


def _near(spans, start: int, end: int) -> list[tuple[int, int]]:
    """The spans of `spans`, in order and none inside another, that overlap `[start, end)`."""
    at = max(bisect_right(spans, (start, start)) - 1, 0)
    found = []
    while at < len(spans) and spans[at][0] < end:
        if spans[at][1] > start:
            found.append(spans[at])
        at += 1
    return found


def _table_offsets(text: str) -> list[tuple[int, int]]:
    """Where each Markdown table runs, from its first line's start to its last line's end,
    read in the masked text, so that one in a fenced block or a comment is none."""
    lines = text.split("\n")
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line) + 1
    return [(starts[first], starts[last - 1] + len(lines[last - 1]))
            for first, last in table_spans(kept_breaks(text, mask(text)))]  # fmt: skip


def latex_displays(source) -> tuple[tuple[int, int], ...]:
    """Each display of a LaTeX file (`text.latex.structure.Source`): each table's float
    whole, the outermost where one holds another, and each table that stands in none."""
    from manuscript_guard.text.captioned import _floats

    floats = _outermost(_floats(source.text))
    loose = [(start, end) for start, end in source.reading.tables
             if not any(low <= start and end <= high for low, high in floats)]  # fmt: skip
    return tuple(_outermost([*floats, *loose]))


def _outermost(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """The spans no other holds, in order; two that overlap made one."""
    found: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if found and start < found[-1][1]:
            found[-1] = (found[-1][0], max(found[-1][1], end))
        else:
            found.append((start, end))
    return found
