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

import hashlib
import posixpath
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import UnsafeDocument, open_archive, read_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_VML_IMAGE = "{urn:schemas-microsoft-com:vml}imagedata"
_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

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
#: The extent of one binding or citation, marked only in the build `import` compares with.
TOKEN = "mg-t-"
# Where a token opens and closes as the text is read, before whitespace is folded. Objects,
# not characters: the markers were U+E000 and U+E001 inside the text, so a genuine one - a
# glyph pasted from a PDF - vanished from every document read.
_OPEN, _CLOSE = object(), object()

#: Whitespace that is layout, not text: a source line wrapped by its author, a tab or a line
#: break in Word. A no-break space is not in it. Read as `\s`, one came back as a plain space,
#: so a merge could not carry it and refused every edited stretch that held one - and Word's
#: French AutoCorrect puts one before `:` and inside « », and authors put one in "5 mg".
_LAYOUT_CHARACTERS = " \t\n\r\f\v"
_LAYOUT = re.compile(f"[{_LAYOUT_CHARACTERS}]+")


def spaced(text: str) -> str:
    """Runs of layout whitespace as one space; every other space kept as the character it is.

    The ends are left alone. A paragraph's own are stripped by its reader, with every kind of
    space: the source paragraph is spliced without them, so they are not its text either.
    """
    return _LAYOUT.sub(" ", text)


class DocumentUnreadable(Exception):
    """The file is not a Word document this module can read safely."""


@dataclass(frozen=True)
class Block:
    """One paragraph of the body, or one table or figure, in document order."""

    #: The paragraph identifiers it carries. More than one means paragraphs were joined.
    names: tuple[str, ...] = ()
    #: What it says, with every tracked change accepted: layout whitespace as single spaces,
    #: a no-break space as itself. See `spaced`.
    text: str = ""
    #: Where each marked binding or citation sits in `text`, as (start, end). Only a
    #: document built with the tokens marked has any.
    tokens: tuple[tuple[int, int], ...] = ()
    #: "table" or "figure" for a block that is not prose, "" for a paragraph.
    kind: str = ""
    #: What tells a table or a figure apart from the others in another copy of the document:
    #: a digest of a table's text, or of the picture a figure shows. Word renumbers and
    #: renames the parts a picture is stored in when it saves; the picture stays the same.
    #: Empty when the picture could not be read.
    key: str = ""

    @property
    def table(self) -> bool:
        """A table or a figure: a block that is not prose, and not compared."""
        return bool(self.kind)


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
    tokens: tuple[tuple[int, int], ...] = ()
    #: The relationship ids of the pictures it shows, in order.
    embeds: tuple[str, ...] = ()


def _text(element: ET.Element) -> str:
    """The visible text under `element`, tracked changes accepted."""
    return _read(element)[0]


def _read(element: ET.Element) -> tuple[str, tuple[tuple[int, int], ...]]:
    """The visible text under `element`, and where each marked token sits in it."""
    out: list[object] = []
    marked: set[str] = set()

    def walk(node: ET.Element) -> None:
        if node.tag in _UNSEEN:
            return
        if node.tag == W + "t" and node.text:
            out.append(node.text)
        elif node.tag in _SPACES:
            out.append(" ")
        elif node.tag == W + "noBreakHyphen":
            out.append("-")
        elif node.tag == W + "bookmarkStart" and node.get(W + "name", "").startswith(TOKEN):
            marked.add(node.get(W + "id", ""))
            out.append(_OPEN)
        elif node.tag == W + "bookmarkEnd" and node.get(W + "id", "") in marked:
            out.append(_CLOSE)
        for child in node:
            walk(child)

    walk(element)
    return _extents(out)


def _extents(raw: list[object]) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Fold whitespace as the rest of this module does, keeping each token's extent.

    A token's extent starts at its first visible character and ends after its last, so a
    space pandoc put inside the bookmark belongs to the prose around it. Only layout
    whitespace is folded, as `spaced` folds it: a no-break space is a character of the text.
    The ends are stripped of every kind of space, as a paragraph's text is.
    """
    out: list[str] = []
    spans: list[list[int]] = []
    open_: list[int] = []
    space = False
    for char in (c for piece in raw for c in ([piece] if piece in (_OPEN, _CLOSE) else piece)):
        if char is _OPEN:
            spans.append([-1, -1])
            open_.append(len(spans) - 1)
        elif char is _CLOSE:
            if open_:
                span = spans[open_.pop()]
                span[1] = len(out)
                if span[0] < 0:
                    span[0] = len(out)
        elif char in _LAYOUT_CHARACTERS:
            space = True
        else:
            if space and out:
                out.append(" ")
            space = False
            for index in open_:
                if spans[index][0] < 0:
                    spans[index][0] = len(out)
            out.append(char)
    text = "".join(out)
    lead = len(text) - len(text.lstrip())
    text = text.strip()
    return text, tuple(
        (max(start - lead, 0), min(end - lead, len(text))) for start, end in spans if start >= 0
    )


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
    embeds = tuple(
        rid
        for node in element.iter()
        if (rid := node.get(_R + "embed") or (node.tag == _VML_IMAGE and node.get(_R + "id")))
    )
    mark = element.find(f"{W}pPr/{W}rPr")
    runs_on = mark is not None and (
        mark.find(W + "del") is not None or mark.find(W + "moveFrom") is not None
    )
    text, tokens = _read(element)
    return _Paragraph(
        tuple(names), text, tuple(comments), runs_on, table, picture, tokens, embeds
    )


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
    paragraphs = paragraphs_of(document)
    pictures = _pictures(document, {r for p in paragraphs for r in p.embeds})
    out: list[Block] = []
    pending: list[_Paragraph] = []
    cells: list[str] | None = None
    for paragraph in paragraphs:
        if paragraph.table:
            if cells is None:
                out.extend(_fold(pending))
                pending, cells = [], []
            cells.append(paragraph.text)
            continue
        if cells is not None:
            out.append(Block(kind="table", key=_digest(cells)))
            cells = None
        if paragraph.picture and not paragraph.names and not paragraph.text:
            # A figure: a picture and no text. Read as an empty paragraph it was no boundary
            # at all, and a paragraph moved past it went unseen.
            out.extend(_fold(pending))
            pending = []
            seen = [pictures.get(rid) for rid in paragraph.embeds]
            key = _digest(seen) if seen and all(seen) else ""
            out.append(Block(kind="figure", key=key))
            continue
        pending.append(paragraph)
        if not paragraph.runs_on:
            out.extend(_fold(pending))
            pending = []
    if cells is not None:
        out.append(Block(kind="table", key=_digest(cells)))
    out.extend(_fold(pending))
    return out


def _digest(parts: Iterable[str | None]) -> str:
    return hashlib.sha256("\x00".join(part or "" for part in parts).encode("utf-8")).hexdigest()


def _pictures(document: Path, wanted: set[str]) -> dict[str, str]:
    """A digest of each picture the body shows, by relationship id.

    What tells one figure from another in a document Word has saved. The relationship id and
    the file it names are not: Word renumbers and renames them on every save.
    """
    if not wanted:
        return {}
    rels = "word/_rels/document.xml.rels"
    try:
        with open_archive(document) as archive:
            if rels not in archive.namelist():
                return {}
            found = {}
            for rel in read_part(archive, rels, what=f"{document.name}:{rels}").iter(_RELS):
                rid, target = rel.get("Id", ""), rel.get("Target", "")
                if rid not in wanted or rel.get("TargetMode") == "External" or not target:
                    continue
                part = target[1:] if target.startswith("/") else posixpath.normpath(
                    f"word/{target}"
                )
                try:
                    found[rid] = hashlib.sha256(archive.read(part)).hexdigest()
                except (KeyError, OSError, zipfile.BadZipFile):
                    continue
            return found
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc


def _fold(run: list[_Paragraph]) -> list[Block]:
    if not run:
        return []
    kept = [p for p in run if p.text or p is run[-1]]
    names = tuple(dict.fromkeys(n for p in kept for n in p.names))
    text = spaced(" ".join(p.text for p in kept if p.text)).strip()
    # Token extents are read from the build import compares with, which has no tracked
    # changes to fold; offsets into a joined paragraph would need shifting, so none are kept.
    tokens = kept[0].tokens if len(kept) == 1 else ()
    return [Block(names=names, text=text, tokens=tokens)]


def comment_anchors(document: Path) -> dict[str, str]:
    """Which paragraph each comment is attached to, by the comment's id."""
    found: dict[str, str] = {}
    for paragraph in paragraphs_of(document):
        if paragraph.names:
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
        out.append((attributes, spaced(text).strip()))
    return out
