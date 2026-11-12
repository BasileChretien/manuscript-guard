"""Where a line of a Word document's text stands, said as its reader finds it in Word: under
which heading, and which paragraph under it.

The audit reads a .docx a paragraph to a line, twice: its own reader's text for the numbers
(`text.docx`), and the Markdown pandoc converts it to for G6 and G14 (`auditing.gates`),
blank lines between paragraphs. A line of either is a number nobody can find in Word (the
author's audit, 2026-11-10: "line 517"), so the report names the section and the paragraph
instead, "Methods, paragraph 3", as it names a PDF's page and line (`auditing.pdf`).

A paragraph is a line that is not blank and not a heading, counted from 1 under each
heading: a list's item is one, as Word counts it; a table is one, every line of it, said "a
table". The lines before the first heading are counted under none, and a Word document's
footnotes and endnotes, read after its body, under "the notes". The two readers count alike
where they read the same paragraphs; where one drops a paragraph the other keeps (an empty
one, a caption), the numbers after it part (DESIGN.md, "Known gaps").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: What the lines before the first heading, and a document's notes, are said to be under.
NO_HEADING = "before the first heading"
NOTES = "the notes"
#: A heading's title is cut to this many characters in a place.
TITLE = 60
#: A line of a pipe table, or a grid table's line or rule: not "+0.41 points", a paragraph.
_TABLE_LINE = re.compile(r"[ \t]*(?:\||\+[-=:])")
#: A mark Markdown escapes, "Authors\' contributions", which the document prints bare.
_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")


@dataclass(frozen=True)
class Paragraph:
    """One paragraph: the title of the heading it is under, None for none; its number under
    that heading, from 1, 0 for the heading itself; and whether it is a table."""

    section: str | None
    number: int
    table: bool = False

    def said(self) -> str:
        """"Methods, paragraph 3", "Results, paragraph 2 (a table)", "the heading Methods"."""
        if self.number == 0:
            return f"the heading {self.section}"
        kind = " (a table)" if self.table else ""
        return f"{self.section or NO_HEADING}, paragraph {self.number}{kind}"

    def as_dict(self) -> dict:
        """As a finding of `audit --json` gives it, beside its line: under `heading`, since
        a finding's `section` is the report's section it is in."""
        return {"heading": self.section, "paragraph": self.number}


@dataclass(frozen=True)
class Paragraphs:
    """Where each line of a text stands, by line from 1: None for a blank one."""

    places: tuple[Paragraph | None, ...]

    def place(self, line: int | None) -> Paragraph | None:
        """Where line `line` stands; None for no line, a blank one, or one not in the text."""
        if line is None or not 0 < line <= len(self.places):
            return None
        return self.places[line - 1]

    def said(self, line: int | None) -> str:
        """Where line `line` stands, in words; "line N" where it is not a paragraph's."""
        place = self.place(line)
        return place.said() if place is not None else f"line {line}"

    def stretch(self, first: int, last: int) -> str:
        """Lines `first` to `last`, in words: "References, paragraphs 1-35", or from one
        place to another where they are under two headings."""
        start = self._nearest(first, 1)
        end = self._nearest(last, -1)
        if start is None or end is None:
            return f"lines {first}-{last}"
        if start == end:
            return start.said()
        if start.section == end.section and end.number:
            # From its heading on: the section's paragraphs, "References, paragraphs 1-33".
            first = start.number or 1
            if first == end.number:
                return f"{end.section or NO_HEADING}, paragraph {first}"
            return f"{end.section or NO_HEADING}, paragraphs {first}-{end.number}"
        return f"from {start.said()} to {end.said()}"

    def _nearest(self, line: int, step: int) -> Paragraph | None:
        """The place of `line`, or of the nearest line past it that has one, going `step`."""
        while 0 < line <= len(self.places):
            if self.places[line - 1] is not None:
                return self.places[line - 1]
            line += step
        return None


def _title(title: str) -> str:
    """A heading's title as a place names it: its emphasis and escapes taken off, cut. Its
    attributes, "{#methods .unnumbered}", `split_sections` has taken off already."""
    plain = " ".join(_ESCAPED.sub(r"\1", title.replace("*", "")).split())
    return plain if len(plain) <= TITLE else plain[: TITLE - 3].rstrip() + "..."


def counted(lines: list[str], headings: dict[int, str], tables: frozenset[int] = frozenset(),
            notes_from: int | None = None,
            continued: frozenset[int] = frozenset()) -> Paragraphs:  # fmt: skip
    """The places of `lines`, under `headings` (each title by its line, from 1; one with no
    words is no heading): every line in `tables` (from 1) one paragraph with the lines of the
    table next to it, a blank one among them, as an empty cell is, keeping the table open
    (review of #616); every line in `continued` the paragraph of the line before it; and
    every line from `notes_from` on under `NOTES`."""
    places: list[Paragraph | None] = []
    section: str | None = None
    number = 0
    in_table = False
    for at, text in enumerate(lines, 1):
        if notes_from is not None and at == notes_from:
            section, number, in_table = NOTES, 0, False
        if at in headings and headings[at].strip():
            section, number, in_table = _title(headings[at]), 0, False
            places.append(Paragraph(section, 0))
            continue
        if at in continued and places and places[-1] is not None and text.strip():
            places.append(places[-1])
            continue
        if not text.strip():
            places.append(None)
            in_table = in_table and at in tables
            continue
        table = at in tables
        if not (table and in_table):
            number += 1
        in_table = table
        places.append(Paragraph(section, number, table))
    return Paragraphs(tuple(places))


#: A line pandoc ends with a backslash where Word breaks the line inside a paragraph
#: (Shift+Enter): the next line is the same paragraph (review of #616). On Windows the text
#: comes back from pandoc with its lines ended "\r\n".
_BROKEN_LINE = re.compile(r"(?<!\\)(?:\\\\)*\\\r?$")
#: A footnote's or an endnote's text, which pandoc writes after the document's last
#: paragraph: "[^1]: ...".
_NOTE = re.compile(r"\[\^[^\]\s]+\]:")


def of_markdown(text: str) -> Paragraphs:
    """The places of the Markdown pandoc converts a .docx to, a paragraph to a line
    (`from_word.WRITER`, `--wrap=none`) but where a line break in a paragraph ends a line
    with a backslash (`_BROKEN_LINE`): its headings as `split_sections` reads them; its
    tables by their lines, which open with `|`, or with `+-`, `+=` or `+:` in a grid table
    (`_TABLE_LINE`); and its notes, from the first note pandoc writes at its end (`_NOTE`)."""
    from manuscript_guard.text.sections import scannable, split_sections

    lines = text.split("\n")
    headings = {section.line: section.title for section in split_sections(scannable(text))
                if section.level}  # fmt: skip
    tables = frozenset(at for at, line in enumerate(lines, 1) if _TABLE_LINE.match(line))
    continued = frozenset(at + 1 for at, line in enumerate(lines, 1)
                          if _BROKEN_LINE.search(line))  # fmt: skip
    notes = next((at for at, line in enumerate(lines, 1) if _NOTE.match(line)), None)
    return counted(lines, headings, tables, notes, continued)


def of_docx(document, text: str) -> Paragraphs:
    """The places of `text`, a .docx's body then its notes as the audit reads them
    (`audit.read_paper`): its headings by their styles, or by its typed titles where it
    has no heading style (`text.docx.typed_heading_levels`), as the audit places its
    Abstract; its tables by their cells."""
    from manuscript_guard.text.docx import typed_heading_levels

    body = document.body.split("\n")
    levels = document.heading_levels or typed_heading_levels(document) or ()
    headings = {at + 1: body[at] for at, _level in levels if at < len(body)}
    notes = len(body) + 1 if document.notes else None
    return counted(text.split("\n"), headings, _tables(body, document.cells), notes)


#: A line of a table in the document's own text that holds no cell's words: where a row
#: starts, a cell's mark alone (`text.docx`, " | "). Not an empty line: an empty cell's is
#: among the cells already, and an empty paragraph between two tables is no table's (fix
#: round of #616).
_BETWEEN_CELLS = re.compile(r"\s*\|[\s|]*")


def _tables(body: list[str], cells: frozenset[int]) -> frozenset[int]:
    """The lines of the tables of a .docx's own text, from 1: its cells' lines, and the
    lines between and before them that hold no words, a row's start or an empty cell, which
    the cells' lines alone left out, so that a table of two rows was three paragraphs (review
    of #616)."""
    found = {at + 1 for at in cells}
    for at in sorted(cells):
        before = at - 1
        while before >= 0 and before not in cells and _BETWEEN_CELLS.fullmatch(body[before]):
            if before + 1 in found:
                break
            found.add(before + 1)
            before -= 1
    return frozenset(found)
