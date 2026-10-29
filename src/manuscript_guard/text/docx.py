"""Reading the text of a Word document, correctly.

Two details decide whether an audit of an existing paper works at all, and both were learned
the hard way in the project that preceded this one.

**Table cells must be separated.** Word stores a row as a sequence of cells with no
separator between their text. Concatenating naively turns the row

    Unique publishers | 39 | 20 | 26 | 16

into `Unique publishers39202616`, which reads as the single number 39,202,616. No cell can
then be matched against anything, so every table in the paper is silently skipped — and a
wrong count in Table 1 survived every check for exactly that reason.

**Tracked changes must be resolved.** A document under review contains both the old text and
the new. Reading it raw gives numbers that were deleted and numbers that were inserted, mixed
together, so the audit reports corrections as errors and misses the text that will actually
be published. Insertions are kept and deletions dropped, which is what the reader will see,
and so is text moved away: the reader sees it where it was moved to. A deleted line break
or tab is dropped with the text, not read as a space, and a paragraph whose mark was deleted
or moved away runs on into the next with nothing between them, as Word joins them. A table
row deleted or moved away is dropped whole, its cells and lines with its text.

**The body and the notes are kept apart**, and the body says which of its lines are
headings. Both are for finding the reference list: the audit drops it, and used to drop
everything after its heading too — every appendix, and every footnote and endnote, because
the notes were read after the body. A heading is the only thing that says where a reference
list ends, and in Word only a paragraph's style says it is one.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.docxtext import W16SE, extended_symbol, runs_on
from manuscript_guard.safexml import UnsafeDocument, open_archive, read_part
from manuscript_guard.text.tables import Table, TableCell
from manuscript_guard.text.word_numbering import Numbering
from manuscript_guard.wordfonts import Fonts, symbol

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
BODY, NOTES = PARTS[0], PARTS[1:]

# Put in front of a heading paragraph, or one inside a table cell, while the text is
# assembled, and taken out once its line is known. XML 1.0 cannot carry these characters,
# so no document text contains them.
_HEADING_MARK = "\x1e"
_CELL_MARK = "\x1f"
# And after the cell mark, on the first line of each cell of a table that is not inside
# another: a table opens here, a row does, and a cell does, once for each column it spans.
# Inside a cell's line, around the text of a run raised as superscript, and in place of a
# footnote's or an endnote's reference mark: what a row's label points to a note with.
# Taken out with the others, so that the body reads as it did without them.
_TABLE_MARK = "\x1b"
_ROW_MARK = "\x1d"
_COLUMN_MARK = "\x1c"
_RAISED = "\x1a"
_NOTE_REFERENCE = "\x19"
# After the heading mark, on the line of a body paragraph outside a table that Word numbers:
# the numbering is the next of those `_part_text` lists, in the order of the marks.
_NUMBERED_MARK = "\x18"
_MARKS = (_HEADING_MARK, _CELL_MARK, _TABLE_MARK, _ROW_MARK, _COLUMN_MARK, _RAISED,
          _NOTE_REFERENCE, _NUMBERED_MARK)  # fmt: skip
_STRUCTURE = re.compile(f"{_CELL_MARK}({_TABLE_MARK}?)({_ROW_MARK}?)({_COLUMN_MARK}*)")
_RAISED_TEXT = re.compile(f"{_RAISED}([^{_RAISED}]*){_RAISED}")
_NOTE_REFERENCES = {W + "footnoteReference", W + "endnoteReference"}
_HEADING_NAME = re.compile(r"heading\s*[1-9]", re.IGNORECASE)


class NotADocx(Exception):
    """The file is not a readable Word document."""


@dataclass(frozen=True)
class DocxText:
    """A document's text: the body, then the footnotes and endnotes, read apart."""

    body: str
    notes: str
    #: 0-based indexes of the lines of `body` styled as a heading: a line's paragraph, or for
    #: paragraphs joined by a mark deleted or moved away, the last of them.
    headings: frozenset[int]
    #: 0-based indexes of the lines of `body` inside a table cell, where "References" is a
    #: column header rather than the start of a bibliography.
    cells: frozenset[int] = frozenset()
    #: Each table that is not inside another, as rows of cells: what `audit` reads an n (%)
    #: in. A superscript is written `^a^`, as Markdown writes one.
    tables: tuple[Table, ...] = ()
    #: Each line of `body` outside a table whose paragraph Word numbers, 1-based, with the
    #: count it is in, whether that count prints 1, 2, 3 from 1 (`word_numbering`), and its
    #: place in the count, every paragraph of it outside a table counted, an empty one too,
    #: which Word numbers (Word 16, over COM), and none in a table's cell (DESIGN.md, "Known
    #: gaps"): what says a reference list is numbered by Word rather than typed, and what
    #: number Word prints for each entry.
    numbering: tuple[tuple[int, str, bool, int], ...] = ()
    #: The level of each line in `headings`, 1 for "heading 1": by 0-based line, what the
    #: audit's Abstract against Results places a line under (`gates.reported.Walk`).
    heading_levels: tuple[tuple[int, int], ...] = ()
    #: Each line of `body` outside a table and a text box that is an item of a list Word
    #: numbers or bullets, and not a heading, 1-based, with its level, 0 the outermost
    #: (`word_numbering.Numbering.level_of`): what a flow is read from (`stats/flows.py`).
    levels: tuple[tuple[int, int], ...] = ()
    #: The text of each text box of the body, a shape's included, which a flow drawn in
    #: boxes is: read for the note that it is not read as one.
    boxed: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return _tidy(f"{self.body}\n{self.notes}") if self.notes else self.body


def _inside(node: ET.Element, parents: dict, tag: str) -> bool:
    current = parents.get(node)
    while current is not None:
        if current.tag == tag:
            return True
        current = parents.get(current)
    return False


#: What Word does not show at this place once every tracked change is accepted: deleted
#: text, and text moved away, which it shows where it was moved to. And a paragraph's
#: properties, where a tab *stop* is a `w:tab` too: read as a typed tab, it put a space
#: between two paragraphs joined by a deleted mark, and "-0.5" and "1" were read apart.
#: And an AlternateContent fallback, which repeats its choice for readers that predate it:
#: Word writes every text box twice, as DrawingML and again as VML, and read twice, each
#: number in a text box was reported twice.
_UNSEEN = {W + "del", W + "moveFrom", W + "pPr", MC + "Fallback"}


def _paragraphs(element: ET.Element) -> list[ET.Element]:
    """The paragraphs in `element`, leaving out any inside something `_UNSEEN` there."""
    found, pending = [], [element]
    while pending:
        for child in pending.pop():
            if child.tag not in _UNSEEN:
                if child.tag == W + "p":
                    found.append(child)
                pending.append(child)
    return found


def _row_gone(row: ET.Element) -> bool:
    """Whether Word drops a table row on accepting every tracked change.

    A deleted row is marked in its own properties, not by wrapping it, and a row moved away
    is not marked as a row at all: Word 16 moves the mark of every paragraph in it instead,
    a nested table's included. Not a text box's, whose anchor was moved with the text around
    it, so the box goes too. Either way the row's text was dropped while its row and cells
    still started lines, and a cell styled as a heading was an empty heading, which ended
    the reference list it stood in. An inserted row is kept, and so is a row not deleted,
    with any paragraph mark left in place.
    """
    if row.find(f"{W}trPr/{W}del") is not None:
        return True
    paragraphs = _paragraphs(row)
    moved = f"{W}pPr/{W}rPr/{W}moveFrom"
    return bool(paragraphs) and all(p.find(moved) is not None for p in paragraphs)


def _hidden(root: ET.Element) -> frozenset[ET.Element]:
    """The elements Word does not show, nor anything in them, once changes are accepted."""
    return frozenset(
        node
        for node in root.iter()
        if node.tag in _UNSEEN or (node.tag == W + "tr" and _row_gone(node))
    )


def _placed(node: ET.Element, parents: dict, hidden: frozenset) -> tuple[ET.Element | None, bool]:
    """The paragraph `node` belongs to, and whether it is on the page there."""
    paragraph, seen = None, True
    current = parents.get(node)
    while current is not None:
        if paragraph is None and current.tag == W + "p":
            paragraph = current
        seen = seen and current not in hidden
        current = parents.get(current)
    return paragraph, seen


def _seen(node: ET.Element, parents: dict, hidden: frozenset) -> bool:
    """Whether `node` is on the page: neither it nor anything it sits in is `hidden`."""
    return node not in hidden and _placed(node, parents, hidden)[1]


def _heading_styles(archive: zipfile.ZipFile, names: set[str], what: str) -> dict[str, int]:
    """The paragraph style ids that are headings, each with its level.

    Read from the style's name rather than its id: the id is localised — a French Word
    writes `Titre1` — while a built-in style is named "heading 1" in every language. A
    style with an outline level and no such name is at that level, counted from 1.
    """
    found = {f"Heading{n}": n for n in range(1, 10)}
    if "word/styles.xml" not in names:
        return found
    try:
        styles = read_part(archive, "word/styles.xml", what=f"{what}:word/styles.xml")
    except UnsafeDocument:
        return found
    for style in styles.iter(W + "style"):
        name = style.find(W + "name")
        named = name is not None and _HEADING_NAME.fullmatch(name.get(W + "val", ""))
        outline = style.find(f"{W}pPr/{W}outlineLvl")
        if named:
            found[style.get(W + "styleId", "")] = int(named.group(0)[-1])
        elif outline is not None:
            found[style.get(W + "styleId", "")] = _outline_level(outline)
    return found


def _outline_level(outline: ET.Element) -> int:
    """A heading's level from its `w:outlineLvl`, which counts from 0: 1 to 9."""
    value = outline.get(W + "val", "0")
    return min(int(value), 8) + 1 if value.isascii() and value.isdigit() else 1


def _heading_level(paragraph: ET.Element, styles: dict[str, int]) -> int | None:
    """The level of a paragraph that is a heading, by its outline level or its style's,
    or None for one that is no heading."""
    props = paragraph.find(W + "pPr")
    if props is None:
        return None
    outline = props.find(W + "outlineLvl")
    if outline is not None:
        return _outline_level(outline)
    style = props.find(W + "pStyle")
    return styles.get(style.get(W + "val", "")) if style is not None else None


#: Layout elements that read as a space. A manual line break read as nothing ran the
#: numbers either side of it together: "-0.51" over "-0.72 to -0.30" became "-0.51-0.72".
#: A deleted one reads as nothing, as Word shows it: read as a space, it split "-0.51" into
#: -0.5 and 1, and parted a minus from its number.
_SPACES = {W + "tab", W + "ptab", W + "br", W + "cr"}


def _symbol(node: ET.Element) -> str:
    """A `w:sym` character: Insert > Symbol writes one, not text; see `wordfonts`. One with
    no text of its own reads as a space, so the numbers either side stay apart."""
    shown, _name = symbol(node)
    return shown if shown is not None else " "


#: Characters Word writes as elements rather than text. Read as nothing, a non-breaking
#: hyphen (Ctrl+Shift+-, used to keep a minus on its number) or a Symbol-font minus left
#: "-0.30" as 0.30, and a flipped bound matched. An emoji Word inserts is one too, in an
#: AlternateContent choice, with the character as text only in the fallback, which is not
#: read: "12", an emoji and "34" read as 1234.
_CHARACTERS = {
    W + "noBreakHyphen": lambda node: "-",
    W + "softHyphen": lambda node: "",
    W + "sym": _symbol,
    W16SE + "symEx": extended_symbol,
}


_SHOWN = {W + "t", *_SPACES, *_CHARACTERS}
#: What starts a line or a cell.
_BREAKS = {W + "p", W + "tr", W + "tc"}


def _shown(node: ET.Element, fonts: Fonts, parents: dict, paragraph: ET.Element | None) -> str:
    """What one element puts on the page: its text, a space, or a character.

    Text is read as its font draws it: typed in the Symbol font, "40" can be the private-use
    U+F034 U+F030, which are not digits, and the number went unaudited. See `wordfonts`.
    """
    if node.tag == W + "t":
        run = parents.get(node)
        run = run if run is not None and run.tag == W + "r" else None
        return fonts.run(run, paragraph).read(node.text or "", missing=" ")[0]
    if node.tag == W16SE + "symEx":
        return fonts.drawn(extended_symbol(node), node.get(W16SE + "font"), missing=" ")[0]
    if node.tag in _SPACES:
        return " "
    return _CHARACTERS[node.tag](node)


def _dropped(element: ET.Element, parents: dict, hidden: frozenset) -> bool:
    """Whether `element` is a table Word drops whole: nothing in it is on the page."""
    if element.tag != W + "tbl":
        return False
    paragraphs = list(element.iter(W + "p"))
    return bool(paragraphs) and not any(_seen(p, parents, hidden) for p in paragraphs)


def _joins(root: ET.Element, parents: dict, hidden: frozenset) -> dict[ET.Element, ET.Element]:
    """Each paragraph whose mark was deleted or moved away, and the one it runs on into.

    Only its next sibling: a text box's paragraphs sit inside the paragraph that holds it,
    and nothing runs on into those. An empty element between the two - a bookmark, a
    comment's range, the end of a move - leaves them adjacent, and so does a table whose
    every row was deleted or moved away: Word 16 joins "-0.5" and "1" either side of one
    into -0.51. A table, a content control, anything else with content of its own, parts
    them, although Word 16 runs a paragraph on into the first cell of a table after it
    (DESIGN.md, Known gaps).
    """
    joins: dict[ET.Element, ET.Element] = {}
    # Only a parent of a paragraph that runs on can hold a join; most documents have none.
    holders = dict.fromkeys(parents[p] for p in root.iter(W + "p") if p in parents and runs_on(p))
    for parent in holders:
        before = None
        for child in parent:
            if child.tag == W + "p":
                if before is not None:
                    joins[before] = child
                before = child if runs_on(child) else None
            elif len(child) and not _dropped(child, parents, hidden):
                before = None
    return joins


def _line_start(
    paragraph: ET.Element, joins: dict, parents: dict, headings: dict, opens: _Opens,
    numbering: Numbering | None = None, counts: list | None = None,
    levels: list | None = None,
) -> str:  # fmt: skip
    """The break and the marks a paragraph's line starts with.

    A joined line has the last paragraph's style, because its mark is the one left: Word 16
    keeps it on accepting the change, and when Word deletes a mark itself it first copies
    the first paragraph's style onto the second. A heading style ends a reference list. Its
    numbering is the last paragraph's too, which is in its properties, beside its style.
    A heading's level goes in `levels`, in the order of the headings' lines; and with each
    count, the level of the list the line is an item of, None for a heading or a line in a
    text box.
    """
    last = paragraph
    while last in joins:
        last = joins[last]
    level = _heading_level(last, headings)
    heading = _HEADING_MARK if level is not None else ""
    if heading and levels is not None:
        levels.append(level)
    if not _inside(paragraph, parents, W + "tc"):
        numbered = numbering.of_paragraph(last) if numbering is not None else None
        if numbered is None or counts is None:
            return "\n" + heading
        listed = None if heading or _inside(paragraph, parents, W + "txbxContent") else (
            numbering.level_of(last))  # fmt: skip
        counts.append((*numbered, listed))
        return "\n" + heading + _NUMBERED_MARK
    return "\n" + heading + _CELL_MARK + opens.take()


class _Opens:
    """What the next line in a cell opens: a table, a row, a cell. Set by the table, the row
    and the cell elements of a table that is not inside another, and taken by the first
    paragraph after them, which is the cell's, or the first of a table inside it."""

    def __init__(self) -> None:
        self.table, self.row, self.columns = False, False, 0

    def take(self) -> str:
        marks = (_TABLE_MARK if self.table else "") + (_ROW_MARK if self.row else "") + \
            _COLUMN_MARK * self.columns  # fmt: skip
        self.table, self.row, self.columns = False, False, 0
        return marks


#: The most columns a Word table has: a larger span is no table Word made, and one of
#: 999999999 built a string of marks of about a gigabyte (round 1 of #314).
_MOST_COLUMNS = 63


def _span(cell: ET.Element) -> int:
    """How many grid columns a cell spans."""
    span = cell.find(f"{W}tcPr/{W}gridSpan")
    value = span.get(W + "val", "1") if span is not None else "1"
    if not (value.isascii() and value.isdigit() and int(value) > 0):
        return 1
    return min(int(value), _MOST_COLUMNS)


def _raised(node: ET.Element, parents: dict) -> bool:
    """Whether a run's text is raised as superscript, as a footnote marker typed is."""
    run = parents.get(node)
    if run is None or run.tag != W + "r":
        return False
    align = run.find(f"{W}rPr/{W}vertAlign")
    return align is not None and align.get(W + "val") == "superscript"


def _part_text(
    root: ET.Element, headings: dict[str, int] | None = None, fonts: Fonts | None = None,
    numbering: Numbering | None = None, counts: list | None = None,
    levels: list | None = None,
) -> str:  # fmt: skip
    """The part's text, a line to a paragraph, with the marks of what its lines are; with
    `numbering`, each line Word numbers outside a table is marked and its count put in
    `counts`, in order, and each heading's level in `levels`."""
    headings = headings or {}
    fonts = fonts or Fonts()
    parents = {child: parent for parent in root.iter() for child in parent}
    hidden = _hidden(root)
    joins = _joins(root, parents, hidden)
    # Each paragraph's line, shared with the paragraph it runs on into. A text box's
    # paragraphs get lines of their own, after the line of the paragraph holding it: read
    # where the box is anchored, they split that paragraph in two.
    lines: dict[ET.Element, list[str]] = {}
    pieces: list[str | list[str]] = []
    opens = _Opens()

    for node in root.iter():
        if node.tag in _BREAKS and not _seen(node, parents, hidden):
            # Its text is not read, so it starts no line either: the fallback copy of a text
            # box gave each of its lines twice, and a deleted one, or a table row deleted or
            # moved away, left empty lines, where a heading's ended the reference list.
            continue
        if node.tag == W + "tc":
            # Cell boundary. Without this, adjacent cells concatenate into one number.
            pieces.append(" | ")
            if not _inside(node, parents, W + "tc"):
                opens.columns += _span(node)
        elif node.tag == W + "tr":
            pieces.append("\n")
            if not _inside(node, parents, W + "tc"):
                opens.row, opens.columns = True, 0
        elif node.tag == W + "tbl":
            if not _inside(node, parents, W + "tc") and _seen(node, parents, hidden):
                opens.table, opens.row, opens.columns = True, False, 0
        elif node.tag == W + "p":
            if node not in lines:
                lines[node] = [_line_start(node, joins, parents, headings, opens, numbering,
                                           counts, levels)]  # fmt: skip
                pieces.append(lines[node])
            if node in joins:
                lines[joins[node]] = lines[node]
        elif node.tag in _SHOWN:
            owner, seen = _placed(node, parents, hidden)
            if seen:
                shown = _shown(node, fonts, parents, owner)
                if shown and owner is not None and _raised(node, parents) and \
                        _inside(owner, parents, W + "tc"):  # fmt: skip
                    shown = _RAISED + shown + _RAISED
                (lines[owner] if owner is not None else pieces).append(shown)
        elif node.tag in _NOTE_REFERENCES:
            owner, seen = _placed(node, parents, hidden)
            if seen and owner is not None and owner in lines and \
                    _inside(owner, parents, W + "tc"):  # fmt: skip
                lines[owner].append(_NOTE_REFERENCE)

    return "".join(piece if isinstance(piece, str) else "".join(piece) for piece in pieces)


def _tidy(text: str) -> str:
    # Collapse runs of spaces but keep line structure, so findings can cite a line.
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def read_docx_text(path: Path) -> DocxText:
    """Visible text of a .docx with tracked changes accepted, tables kept separable.

    The document may have come from a collaborator, so it is parsed through `safexml`:
    size-capped, compression-ratio-checked, and refused outright if a part declares a DTD.
    """
    try:
        archive = open_archive(path)
    except UnsafeDocument as exc:
        raise NotADocx(str(exc)) from exc

    names = set(archive.namelist())
    if BODY not in names:
        raise NotADocx(f"{path.name}: no word/document.xml; is this really a .docx?")

    try:
        fonts = Fonts.of(archive, path.name)
    except UnsafeDocument:
        # As for the heading styles: what cannot be read safely is not read, and only the
        # fonts a run names itself are known.
        fonts = Fonts()

    def root_of(part: str) -> ET.Element:
        try:
            return read_part(archive, part, what=f"{path.name}:{part}")
        except UnsafeDocument as exc:
            raise NotADocx(str(exc)) from exc

    def text_of(part: str) -> str:
        return _part_text(root_of(part), None, fonts)

    counts: list = []
    heads: list[int] = []
    body_root = root_of(BODY)
    raw = _part_text(body_root, _heading_styles(archive, names, path.name),
                     fonts, Numbering.of(archive, names, path.name), counts, heads)  # fmt: skip
    raw, counts = _numbered_lines(raw, counts)
    marked = _tidy(raw)
    lines = marked.split("\n")
    marked_lines = [i + 1 for i, line in enumerate(lines) if _NUMBERED_MARK in line[:2]]
    # A mark for each count kept; were they ever to differ, no line is said to be numbered,
    # rather than a count given to the wrong line.
    same = len(marked_lines) == len(counts)
    numbering = tuple(zip(marked_lines, counts, strict=True)) if same else ()
    heading_lines = [i for i, line in enumerate(lines) if line.startswith(_HEADING_MARK)]
    headings = frozenset(heading_lines)
    # A level for each heading's line, in order; were they ever to differ, every heading is
    # said to be at level 1 rather than a level given to the wrong line.
    heading_levels = tuple(zip(heading_lines, heads if len(heads) == len(heading_lines)
                               else [1] * len(heading_lines), strict=True))  # fmt: skip
    cells = frozenset(i for i, line in enumerate(lines) if _CELL_MARK in line[:2])
    # The notes keep what they always had, the cell mark of a table in a note among it; the
    # marks the tables are read by go from both.
    notes = _unmarked(_tidy("\n".join(text_of(part) for part in NOTES if part in names)),
                      _MARKS[2:])  # fmt: skip
    body = _unmarked(marked, _MARKS)
    return DocxText(body=body, notes=notes, headings=headings, cells=cells,
                    tables=_tables(lines),
                    numbering=tuple((line, *count[:3]) for line, count in numbering),
                    heading_levels=heading_levels,
                    levels=tuple((line, count[3]) for line, count in numbering
                                 if count[3] is not None),
                    boxed=_boxes(body_root, fonts))  # fmt: skip


def _boxes(root: ET.Element, fonts: Fonts) -> tuple[str, ...]:
    """The text of each text box in `root` that is on the page, once: not the fallback copy
    Word writes of each, nor one in text deleted or moved away, nor a box inside another,
    which is read with it."""
    parents = {child: parent for parent in root.iter() for child in parent}
    hidden = _hidden(root)
    return tuple(
        _unmarked(_tidy(_part_text(box, None, fonts)), _MARKS).strip()
        for box in root.iter(W + "txbxContent")
        if _seen(box, parents, hidden) and not _inside(box, parents, W + "txbxContent")
    )


def _numbered_lines(raw: str, counts: list) -> tuple[str, list]:
    """`raw` without the numbering mark of a line that holds nothing else, and the counts of
    the marks kept: an empty line is one `_tidy` may fold into the blank lines around it, as
    it did before lines were marked, and a mark on it would keep it and move every line
    after it down one. Each count kept carries its place in its count, which the empty
    paragraph takes too: Word prints its number, and the next one's after it (round 2 of
    #463)."""
    parts: list[str] = []
    kept = []
    places: dict[str, int] = {}
    at = 0
    for index, found in enumerate(re.finditer(_NUMBERED_MARK, raw)):
        end = raw.find("\n", found.end())
        rest = raw[found.end() : end if end >= 0 else len(raw)]
        parts.append(raw[at : found.start()])
        count, from_one, listed = counts[index]
        places[count] = places.get(count, 0) + 1
        if rest:
            parts.append(_NUMBERED_MARK)
            kept.append((count, from_one, places[count], listed))
        at = found.end()
    parts.append(raw[at:])
    return "".join(parts), kept


def _unmarked(text: str, marks: tuple[str, ...]) -> str:
    """`text` without `marks`. One inside a line, a raised run's, can stand between two
    spaces that `_tidy` then left apart, so they are made one again: where there was no
    such mark, there are no two spaces to make one."""
    for mark in marks:
        text = text.replace(mark, "")
    return re.sub(r"[ \t]+", " ", text)


def _tables(lines: list[str]) -> tuple[Table, ...]:
    """The tables the marks lay out (`_TABLE_MARK`), each cell's text from its lines, each
    line without the cell boundary the next cell put at its end."""
    tables: list[list[list[tuple[list[str], int, int]]]] = []
    cell: tuple[list[str], int, int] | None = None
    for number, line in enumerate(lines):
        start = line.find(_CELL_MARK, 0, 2)
        if start < 0:
            continue
        opened = _STRUCTURE.match(line, start)
        assert opened is not None
        table, row, columns = opened.group(1), opened.group(2), len(opened.group(3))
        if table or (columns and not tables):
            tables.append([])
        if columns and (row or not tables[-1]):
            tables[-1].append([])
        if columns:
            cell = ([], number + 1, columns)
            tables[-1][-1].append(cell)
        if cell is not None:
            text = line[opened.end() :].rstrip()
            cell[0].append(text[:-1] if text.endswith("|") else text)
    return tuple(
        tuple(tuple(TableCell(_cell_text(texts), line, span) for texts, line, span in row)
              for row in table)
        for table in tables
    )  # fmt: skip


def _cell_text(texts: list[str]) -> str:
    """A cell's lines as one, a raised run written `^a^` and a note's reference `^*^`."""
    joined = " ".join(texts).replace(_RAISED * 2, "")
    joined = _RAISED_TEXT.sub(
        lambda raised: f"^{raised.group(1).strip()}^" if raised.group(1).strip() else " ",
        joined,
    )
    return " ".join(joined.replace(_NOTE_REFERENCE, "^*^").split())


def read_docx(path: Path) -> str:
    """The whole visible text, body then notes. See `read_docx_text`."""
    return read_docx_text(path).text


def is_docx(path: Path) -> bool:
    return path.suffix.lower() == ".docx"
