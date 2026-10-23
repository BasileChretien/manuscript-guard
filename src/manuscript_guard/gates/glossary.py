"""Where a manuscript defines an abbreviation outside a sentence, for G14.

Two places. A glossary, the list of abbreviations a journal asks for, defines each of its
entries where it stands. A caption or a legend has to be read alone, so it may restate a
definition the text has given, and a definition there is not given twice.

Both are read in the text G14 reads its abbreviations in, offsets kept: a Markdown file
with what is not a sentence made spaces, or a LaTeX file's words. Where a form depends on
what was typed, a table's row or a definition list's item, the file as typed (`raw`, at
the same offsets) is looked at too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

#: The headings a glossary stands under, as words of a title, case aside. Their own words:
#: a heading that only holds one of them, "Abbreviations used in the scores", is not one.
GLOSSARY_TITLES = frozenset(
    {"abbreviations", "list of abbreviations", "glossary", "acronyms", "list of acronyms"}
)

_SHORT = r"[^\W_]+(?:-[^\W_]+)*"
#: The marks a short form may wear in a glossary: `**ROR**`, `*ROR*`, `_ROR_`.
_MARKS = "*_"
#: A list item's marker, which a glossary may be written as.
_ITEM = re.compile(r"[ \t]*(?:[-+*]|\d{1,3}[.)])[ \t]+")
#: "ROR = reporting odds ratio", "ROR: ...", "ROR – ...": the short form, a sign, the
#: long form. A dash only with a space on each side, or `ROR-based` would be an entry; LaTeX
#: writes the en dash `--`, and its words keep the two hyphens.
_SEPARATED = re.compile(
    rf"[{_MARKS}]*(?P<short>{_SHORT})[{_MARKS}]*[ \t]*"
    r"(?:=|:|[ \t](?:\N{EN DASH}|\N{EM DASH}|-{1,3})[ \t])[ \t]*(?P<long>\S.*)"
)
#: The short form alone, then the long form: how a two-column table's row reads, and a
#: definition list's term with its definition.
_SPACED = re.compile(rf"[{_MARKS}]*(?P<short>{_SHORT})[{_MARKS}]*[ \t]+(?P<long>\S.*)")
#: The line of a Markdown definition list's definition: `:   reporting odds ratio`.
_DEFINITION = re.compile(r"[ \t]{0,3}:[ \t]+(?P<long>\S.*)")
#: A LaTeX table's row and a `description` item, as typed: what tells "ROR reporting odds
#: ratio" in a table or a list from a sentence that opens with an abbreviation.
_LATEX_PAIRED = re.compile(r"&|\\item\s*\[")
_BLANK = re.compile(r"\n[ \t\r]*\n")
_EDGES = " \t.,;:*_"


@dataclass(frozen=True)
class Entry:
    """One entry of a glossary: where its short form stands, the short form, and its long
    form."""

    at: int
    short: str
    long: str


def is_glossary(title: str) -> bool:
    """Whether a heading's title names a glossary: "Abbreviations", "List of acronyms",
    "GLOSSARY", with a colon or a stop after it or not."""
    words = " ".join(title.replace("*", " ").replace("_", " ").split()).strip(" .:").lower()
    return words in GLOSSARY_TITLES


def sections(
    headings: Iterable[tuple[int, int, int, str]], length: int
) -> list[tuple[int, int]]:
    """The body of each glossary among `headings`, each given as where it starts, where its
    title ends, its level and its title: from the end of its title to the next heading of
    its level or above, or the end of the file."""
    ordered = sorted(headings)
    spans = []
    for index, (_start, end, level, title) in enumerate(ordered):
        if not is_glossary(title):
            continue
        stop = next((later[0] for later in ordered[index + 1 :] if later[2] <= level), length)
        spans.append((end, stop))
    return spans


def entries(prose: str, raw: str, span: tuple[int, int]) -> list[Entry]:
    """The entries of the glossary that runs over `span` of `prose`.

    An entry is a line that opens with a short form and a sign, "=", ":" or a dash with
    spaces, or a list item that does; or a short form and its long form side by side where
    a table's row or a definition list's item puts them: a Markdown table's cells, a
    definition list's term and the `:` line under it, a LaTeX table's row or a
    `description` item. A long form runs on to the lines under it that are not an entry,
    as far as a blank line. A line that is none of these is not read."""
    start, end = span
    found: list[list] = []
    lines = _lines(prose, start, end)
    for index, (at, line) in enumerate(lines):
        if not line.strip():
            found.append([])
            continue
        entry = _entry(line, at, raw, lines[index + 1][1] if index + 1 < len(lines) else "")
        if entry is not None:
            found.append([entry[0], entry[1], [entry[2]]])
        elif found and found[-1] and not _DEFINITION.match(line) and not _TABLE_LINE.match(line):
            found[-1][2].append(line.strip())
    out = []
    for each in found:
        if not each:
            continue
        at, short, parts = each
        long = " ".join(" ".join(parts).split()).strip(_EDGES)
        if long and len(long) > len(short):
            out.append(Entry(at, short, long))
    return out


def _lines(prose: str, start: int, end: int) -> list[tuple[int, str]]:
    lines, at = [], start
    for line in prose[start:end].split("\n"):
        lines.append((at, line))
        at += len(line) + 1
    return lines


def _entry(line: str, at: int, raw: str, following: str) -> tuple[int, str, str] | None:
    """The entry a line opens, as where its short form stands, the short form and the first
    line of its long form; None where it opens none."""
    stripped = line.lstrip()
    if stripped.startswith("|"):
        return _row(line, at)
    item = _ITEM.match(line)
    begin = item.end() if item else len(line) - len(stripped)
    separated = _SEPARATED.fullmatch(line, begin)
    if separated is not None:
        return at + separated.start("short"), separated["short"], separated["long"]
    typed = raw[at : at + len(line)]
    if _LATEX_PAIRED.search(typed):
        spaced = _SPACED.fullmatch(line, begin)
        if spaced is not None:
            return at + spaced.start("short"), spaced["short"], spaced["long"]
    definition = _DEFINITION.match(following)
    term = re.fullmatch(rf"[ \t]*[{_MARKS}]*(?P<short>{_SHORT})[{_MARKS}]*[ \t]*", line)
    if definition is not None and term is not None:
        return at + term.start("short"), term["short"], definition["long"]
    return None


def _row(line: str, at: int) -> tuple[int, str, str] | None:
    """A Markdown table's row read as an entry: its first cell a short form alone, its
    second the long form."""
    bars = [index for index, char in enumerate(line) if char == "|"]
    cells = [(left + 1, line[left + 1 : right])
             for left, right in zip(bars, bars[1:], strict=False)]  # fmt: skip
    filled = [(offset, cell) for offset, cell in cells if cell.strip()]
    if len(filled) < 2:
        return None
    offset, first = filled[0]
    term = re.fullmatch(rf"[ \t]*[{_MARKS}]*(?P<short>{_SHORT})[{_MARKS}]*[ \t]*", first)
    if term is None:
        return None
    return at + offset + term.start("short"), term["short"], filled[1][1].strip()


#: A Markdown table's caption line, as pandoc reads one: `Table: ...`, or `: ...` beside a
#: table.
_TABLE_CAPTION = re.compile(r"[ ]{0,3}(?P<table>[Tt]able:|:(?![^\w\s]))")
#: A line of a table, pipe or grid.
_TABLE_LINE = re.compile(r"[ \t]{0,3}[|+]")


def markdown_captions(prose: str) -> list[tuple[int, int]]:
    """Where a Markdown file's captions and legends run: a table's caption line, `Table:`,
    or `:` next to a table, to the end of its paragraph; and a paragraph that opens with
    the display it captions, "Figure 1." or "**Table 2.**", as a legend typed in Word is.
    A figure's caption, the text of its image, is not read at all."""
    from manuscript_guard.gates.pointers import opening_pointer

    spans = []
    start = 0
    for gap in (*_BLANK.finditer(prose), None):
        end = len(prose) if gap is None else gap.start()
        paragraph = prose[start:end]
        if _legend(paragraph, opening_pointer):
            spans.append((start, end))
        else:
            spans += _table_captions(prose, start, end)
        if gap is not None:
            start = gap.end()
    return spans


#: What follows the display a typed legend opens with: a stop, a colon or a dash, past the
#: marks of bold or italics. "Table 2 shows ..." opens a sentence, not a legend.
_AFTER_POINTER = re.compile(r"[*_]*[ \t]*[.:|\N{EN DASH}\N{EM DASH}-]")


def _legend(paragraph: str, opening_pointer) -> bool:
    """Whether a paragraph is a legend typed as one: "Figure 1. ...", "**Table 2.** ..."."""
    found = opening_pointer(paragraph.lstrip())
    if found is None:
        return False
    return _AFTER_POINTER.match(paragraph.lstrip(), found.end()) is not None


def _table_captions(prose: str, start: int, end: int) -> list[tuple[int, int]]:
    """The caption line of a table in the paragraph from `start` to `end`, to the paragraph's
    end: `Table:` anywhere, and `:` where a table's line is next to it, in the paragraph or
    across the blank line above or below it."""
    lines = [line for _at, line in _lines(prose, start, end)]
    above = prose[:start].rstrip().rsplit("\n", 1)[-1]
    below = prose[end:].lstrip("\r\n").split("\n", 1)[0]
    at = start
    for index, line in enumerate(lines):
        caption = _TABLE_CAPTION.match(line)
        if caption is not None:
            previous = lines[index - 1] if index else above
            following = lines[index + 1] if index + 1 < len(lines) else below
            if caption["table"] != ":" or any(
                _TABLE_LINE.match(near) for near in (previous, following)
            ):
                return [(at, end)]
        at += len(line) + 1
    return []


def latex_captions(source) -> list[tuple[int, int]]:
    """Where the text of each `\\caption` of a LaTeX file runs, inside its braces."""
    from manuscript_guard.text.latex.printed import caption_spans

    return caption_spans(source)
