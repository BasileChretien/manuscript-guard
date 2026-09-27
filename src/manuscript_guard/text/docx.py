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
or moved away runs on into the next with nothing between them, as Word joins them.

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

from manuscript_guard.docxtext import runs_on
from manuscript_guard.safexml import UnsafeDocument, open_archive, read_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
W16SE = "{http://schemas.microsoft.com/office/word/2015/wordml/symex}"

PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
BODY, NOTES = PARTS[0], PARTS[1:]

# Put in front of a heading paragraph, or one inside a table cell, while the text is
# assembled, and taken out once its line is known. XML 1.0 cannot carry these characters,
# so no document text contains them.
_HEADING_MARK = "\x1e"
_CELL_MARK = "\x1f"
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


def _placed(node: ET.Element, parents: dict) -> tuple[ET.Element | None, bool]:
    """The paragraph `node` belongs to, and whether it is on the page there."""
    paragraph, seen = None, True
    current = parents.get(node)
    while current is not None:
        if paragraph is None and current.tag == W + "p":
            paragraph = current
        seen = seen and current.tag not in _UNSEEN
        current = parents.get(current)
    return paragraph, seen


def _seen(node: ET.Element, parents: dict) -> bool:
    """Whether `node` is on the page: nothing it sits in is `_UNSEEN`."""
    return _placed(node, parents)[1]


def _heading_styles(archive: zipfile.ZipFile, names: set[str], what: str) -> frozenset[str]:
    """The paragraph style ids that are headings.

    Read from the style's name rather than its id: the id is localised — a French Word
    writes `Titre1` — while a built-in style is named "heading 1" in every language.
    """
    found = {f"Heading{n}" for n in range(1, 10)}
    if "word/styles.xml" not in names:
        return frozenset(found)
    try:
        styles = read_part(archive, "word/styles.xml", what=f"{what}:word/styles.xml")
    except UnsafeDocument:
        return frozenset(found)
    for style in styles.iter(W + "style"):
        name = style.find(W + "name")
        named = name is not None and _HEADING_NAME.fullmatch(name.get(W + "val", ""))
        if named or style.find(f"{W}pPr/{W}outlineLvl") is not None:
            found.add(style.get(W + "styleId", ""))
    return frozenset(found)


def _is_heading(paragraph: ET.Element, styles: frozenset[str]) -> bool:
    props = paragraph.find(W + "pPr")
    if props is None:
        return False
    style = props.find(W + "pStyle")
    styled = style is not None and style.get(W + "val") in styles
    return styled or props.find(W + "outlineLvl") is not None


#: Layout elements that read as a space. A manual line break read as nothing ran the
#: numbers either side of it together: "-0.51" over "-0.72 to -0.30" became "-0.51-0.72".
#: A deleted one reads as nothing, as Word shows it: read as a space, it split "-0.51" into
#: -0.5 and 1, and parted a minus from its number.
_SPACES = {W + "tab", W + "ptab", W + "br", W + "cr"}

# The Symbol font's characters, by their code in that font, that can stand beside a number.
_SYMBOL_FONT = {0x2D: "−", 0xB1: "\xb1", 0xA3: "≤", 0xB3: "≥", 0xB4: "\xd7"}


def _symbol(node: ET.Element) -> str:
    """A `w:sym` character: a minus inserted from the Symbol font is an element, not text."""
    if node.get(W + "font", "").lower() != "symbol":
        return " "
    try:
        code = int(node.get(W + "char", ""), 16)
    except ValueError:
        return " "
    return _SYMBOL_FONT.get(code - 0xF000 if code >= 0xF000 else code, " ")


def _symbol_extended(node: ET.Element) -> str:
    """A `w16se:symEx` character: an emoji Word inserts itself, by its code point.

    Only a character that document text could hold. A control character would pass for the
    mark put on a heading's line, and a lone surrogate cannot be printed in the report.
    """
    try:
        code = int(node.get(W16SE + "char", ""), 16)
    except ValueError:
        return " "
    text = 0x20 <= code < 0xD800 or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF
    return chr(code) if text else " "


#: Characters Word writes as elements rather than text. Read as nothing, a non-breaking
#: hyphen (Ctrl+Shift+-, used to keep a minus on its number) or a Symbol-font minus left
#: "-0.30" as 0.30, and a flipped bound matched. An emoji Word inserts is one too, in an
#: AlternateContent choice, with the character as text only in the fallback, which is not
#: read: "12", an emoji and "34" read as 1234.
_CHARACTERS = {
    W + "noBreakHyphen": lambda node: "-",
    W + "softHyphen": lambda node: "",
    W + "sym": _symbol,
    W16SE + "symEx": _symbol_extended,
}


_SHOWN = {W + "t", *_SPACES, *_CHARACTERS}
#: What starts a line or a cell.
_BREAKS = {W + "p", W + "tr", W + "tc"}


def _shown(node: ET.Element) -> str:
    """What one element puts on the page: its text, a space, or a character."""
    if node.tag == W + "t":
        return node.text or ""
    if node.tag in _SPACES:
        return " "
    return _CHARACTERS[node.tag](node)


def _joins(root: ET.Element, parents: dict) -> dict[ET.Element, ET.Element]:
    """Each paragraph whose mark was deleted or moved away, and the one it runs on into.

    Only its next sibling: a text box's paragraphs sit inside the paragraph that holds it,
    and nothing runs on into those. An empty element between the two - a bookmark, a
    comment's range, the end of a move - leaves them adjacent. A table, a content control,
    anything with content of its own, parts them, although Word 16 runs a paragraph on into
    the first cell of a table after it (DESIGN.md, Known gaps).
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
            elif len(child):
                before = None
    return joins


def _line_start(paragraph: ET.Element, joins: dict, parents: dict, headings: frozenset) -> str:
    """The break and the marks a paragraph's line starts with.

    A joined line has the last paragraph's style, because its mark is the one left: Word 16
    keeps it on accepting the change, and when Word deletes a mark itself it first copies
    the first paragraph's style onto the second. A heading style ends a reference list.
    """
    last = paragraph
    while last in joins:
        last = joins[last]
    heading = _HEADING_MARK if _is_heading(last, headings) else ""
    cell = _CELL_MARK if _inside(paragraph, parents, W + "tc") else ""
    return "\n" + heading + cell


def _part_text(root: ET.Element, headings: frozenset[str] = frozenset()) -> str:
    parents = {child: parent for parent in root.iter() for child in parent}
    joins = _joins(root, parents)
    # Each paragraph's line, shared with the paragraph it runs on into. A text box's
    # paragraphs get lines of their own, after the line of the paragraph holding it: read
    # where the box is anchored, they split that paragraph in two.
    lines: dict[ET.Element, list[str]] = {}
    pieces: list[str | list[str]] = []

    for node in root.iter():
        if node.tag in _BREAKS and not _seen(node, parents):
            # Its text is not read, so it starts no line either: the fallback copy of a text
            # box gave each of its lines twice, and a deleted one left empty lines, where a
            # heading's ended the reference list it was in.
            continue
        if node.tag == W + "tc":
            # Cell boundary. Without this, adjacent cells concatenate into one number.
            pieces.append(" | ")
        elif node.tag == W + "tr":
            pieces.append("\n")
        elif node.tag == W + "p":
            if node not in lines:
                lines[node] = [_line_start(node, joins, parents, headings)]
                pieces.append(lines[node])
            if node in joins:
                lines[joins[node]] = lines[node]
        elif node.tag in _SHOWN:
            owner, seen = _placed(node, parents)
            if seen:
                (lines[owner] if owner is not None else pieces).append(_shown(node))

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

    def text_of(part: str, styles: frozenset[str] = frozenset()) -> str:
        try:
            return _part_text(read_part(archive, part, what=f"{path.name}:{part}"), styles)
        except UnsafeDocument as exc:
            raise NotADocx(str(exc)) from exc

    marked = _tidy(text_of(BODY, _heading_styles(archive, names, path.name)))
    lines = marked.split("\n")
    headings = frozenset(i for i, line in enumerate(lines) if line.startswith(_HEADING_MARK))
    cells = frozenset(i for i, line in enumerate(lines) if _CELL_MARK in line[:2])
    notes = _tidy("\n".join(text_of(part) for part in NOTES if part in names))
    body = marked.replace(_HEADING_MARK, "").replace(_CELL_MARK, "")
    return DocxText(body=body, notes=notes, headings=headings, cells=cells)


def read_docx(path: Path) -> str:
    """The whole visible text, body then notes. See `read_docx_text`."""
    return read_docx_text(path).text


def is_docx(path: Path) -> bool:
    return path.suffix.lower() == ".docx"
