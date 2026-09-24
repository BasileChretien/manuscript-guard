"""Reading a Word document the way the person who opens it sees it.

A returned .docx is read for two things: which paragraph is which, from the invisible
identifier each one carries as a bookmark, and what each paragraph now says. Both used to be
regular expressions over the XML, and the text one wrote XML into the manuscript: `<w:t[^>]*>`
matches `<w:tab/>`, `<w:tabs>` and `<w:textAlignment .../>` as well as `<w:t>`, and the lazy
match then ran on to the next `</w:t>`. A paragraph with a tab in it merged
`</w:r><w:r><w:t xml:space="preserve">` into the source.

So the document is parsed, and a paragraph's text is its `w:t` elements and nothing else,
read as if every tracked change had been accepted: inserted text counts, deleted and
moved-away text does not, and a paragraph whose mark was deleted runs on into the next one,
which is what Word shows once the change is accepted. A paragraph deleted with Track Changes
on used to come back as an empty paragraph and be refused as "a number or a citation
changed".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import UnsafeDocument, open_archive, read_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

#: Subtrees whose text is not on the page once every tracked change is accepted, or is not
#: this paragraph's text at all: a text box holds paragraphs of its own, and an
#: AlternateContent fallback repeats its choice.
_UNSEEN = {
    W + "del",
    W + "moveFrom",
    W + "pPr",
    W + "rPr",
    W + "txbxContent",
    _MC + "Fallback",
}
#: Layout elements that read as a space. `w:tab` is also the name of a tab *stop* inside
#: `w:pPr/w:tabs`, which `_UNSEEN` keeps out.
_SPACES = {W + "tab", W + "ptab", W + "br", W + "cr"}

_IDENTIFIER = re.compile(r"mg-p-[A-Za-z0-9_.-]+$")
_PICTURES = {W + "drawing", W + "pict", W + "object"}


class DocumentUnreadable(Exception):
    """The file is not a Word document this module can read safely."""


@dataclass(frozen=True)
class Block:
    """One paragraph of the body, or one table, in document order."""

    #: The paragraph identifiers it carries. More than one means paragraphs were joined.
    names: tuple[str, ...] = ()
    #: What it says, whitespace-normalised, with every tracked change accepted.
    text: str = ""
    #: A table or a figure: a block that is not prose, and not compared.
    table: bool = False


@dataclass(frozen=True)
class _Paragraph:
    names: tuple[str, ...]
    text: str
    comments: tuple[str, ...]
    #: Its paragraph mark was deleted as a tracked change, so it runs on into the next one.
    runs_on: bool
    table: bool
    #: It holds a picture: a figure, when it has no text and no identifier.
    picture: bool = False


def _text(element: ET.Element) -> str:
    """The visible text under `element`, tracked changes accepted."""
    out: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag in _UNSEEN:
            return
        if node.tag == W + "t" and node.text:
            out.append(node.text)
        elif node.tag in _SPACES:
            out.append(" ")
        elif node.tag == W + "noBreakHyphen":
            out.append("-")
        for child in node:
            walk(child)

    walk(element)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _paragraph(element: ET.Element, *, table: bool) -> _Paragraph:
    names: list[str] = []
    comments: list[str] = []
    for node in element.iter():
        if node.tag == W + "bookmarkStart":
            name = node.get(W + "name", "")
            if _IDENTIFIER.match(name) and name not in names:
                names.append(name)
        elif node.tag == W + "commentRangeStart":
            comments.append(node.get(W + "id", ""))
    picture = any(node.tag in _PICTURES for node in element.iter())
    mark = element.find(f"{W}pPr/{W}rPr")
    runs_on = mark is not None and (
        mark.find(W + "del") is not None or mark.find(W + "moveFrom") is not None
    )
    return _Paragraph(tuple(names), _text(element), tuple(comments), runs_on, table, picture)


def _walk_body(node: ET.Element, *, table: bool = False) -> list[_Paragraph]:
    out: list[_Paragraph] = []
    for child in node:
        if child.tag == W + "p":
            out.append(_paragraph(child, table=table))
        elif child.tag == W + "tbl":
            out.extend(_walk_body(child, table=True))
        elif child.tag not in _UNSEEN and child.tag != W + "sectPr":
            # Content controls, custom XML, table rows and cells: look inside.
            out.extend(_walk_body(child, table=table or child.tag == W + "tc"))
    return out


def paragraphs_of(document: Path, part: str = "word/document.xml") -> list[_Paragraph]:
    """Every paragraph in one part of the document, in order, tables included."""
    try:
        with open_archive(document) as archive:
            if part not in archive.namelist():
                return []
            root = read_part(archive, part, what=f"{document.name}:{part}")
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc
    body = root.find(W + "body")
    return _walk_body(body if body is not None else root)


def blocks(document: Path) -> list[Block]:
    """The body as a reader sees it once every tracked change is accepted.

    Each table is one block: its cells carry no identifiers and are not compared. A
    paragraph whose mark was deleted is folded into the one after it - a join, which is how
    Word shows it. If nothing of it is left, it was deleted outright and its identifier goes
    with it rather than being carried into its neighbour, where it would read as a join.
    """
    out: list[Block] = []
    pending: list[_Paragraph] = []
    table_open = False
    for paragraph in paragraphs_of(document):
        if paragraph.table:
            if not table_open:
                out.extend(_fold(pending))
                pending = []
                out.append(Block(table=True))
            table_open = True
            continue
        table_open = False
        if paragraph.picture and not paragraph.names and not paragraph.text:
            # A figure: a picture and no text. Read as an empty paragraph it was no boundary
            # at all, and a paragraph moved past it went unseen.
            out.extend(_fold(pending))
            pending = []
            out.append(Block(table=True))
            continue
        pending.append(paragraph)
        if not paragraph.runs_on:
            out.extend(_fold(pending))
            pending = []
    out.extend(_fold(pending))
    return out


def _fold(run: list[_Paragraph]) -> list[Block]:
    if not run:
        return []
    kept = [p for p in run if p.text or p is run[-1]]
    names = tuple(dict.fromkeys(n for p in kept for n in p.names))
    text = re.sub(r"\s+", " ", " ".join(p.text for p in kept if p.text)).strip()
    return [Block(names=names, text=text)]


def comment_anchors(document: Path) -> dict[str, str]:
    """Which paragraph each comment is attached to, by the comment's id.

    Not a table cell's bookmark, which `blocks` already refuses as an identity: every build
    before identifiers moved off tables put one in each pipe table's first cell, and a cell
    is never the source block the identifier names.
    """
    found: dict[str, str] = {}
    for paragraph in paragraphs_of(document):
        if paragraph.names and not paragraph.table:
            for ident in paragraph.comments:
                found[ident] = paragraph.names[0]
    return found


def comment_texts(document: Path) -> list[tuple[dict[str, str], str]]:
    """Each comment's attributes and its text, from `word/comments.xml`."""
    try:
        with open_archive(document) as archive:
            if "word/comments.xml" not in archive.namelist():
                return []
            root = read_part(archive, "word/comments.xml", what=f"{document.name}:comments")
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc
    out = []
    for comment in root.iter(W + "comment"):
        attributes = {key.removeprefix(W): value for key, value in comment.attrib.items()}
        text = " ".join(_text(p) for p in comment.iter(W + "p"))
        out.append((attributes, re.sub(r"\s+", " ", text).strip()))
    return out
