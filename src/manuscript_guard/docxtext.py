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

An identifier is an empty bookmark at the very start of its paragraph, and Word treats an
empty bookmark as belonging to neither side of it. It does not carry one with the text it
cuts, and it puts text pasted or typed at the start of a paragraph after it. Where the
tracked changes say what happened, each identifier is put back on the paragraph it names;
see `_settled`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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
#: Text tracked as arriving: typed or pasted, or moved here. Skipped with `_UNSEEN`, what is
#: left is the text the document was sent with.
_ARRIVED = {W + "ins", W + "moveTo"}
_ARRIVED_OR_UNSEEN = _UNSEEN | _ARRIVED
#: Layout elements that read as a space. `w:tab` is also the name of a tab *stop* inside
#: `w:pPr/w:tabs`, which `_UNSEEN` keeps out.
_SPACES = {W + "tab", W + "ptab", W + "br", W + "cr"}
#: The two ends of a tracked move's range, by the side of the move they mark.
_MOVE_STARTS = {W + "moveFromRangeStart": "moveFrom", W + "moveToRangeStart": "moveTo"}
_MOVE_ENDS = {W + "moveFromRangeEnd": "moveFrom", W + "moveToRangeEnd": "moveTo"}

_IDENTIFIER = re.compile(r"mg-p-[A-Za-z0-9_.-]+$")
_PICTURES = {W + "drawing", W + "pict", W + "object"}

#: Whitespace that is layout, not text: a source line wrapped by its author, a tab or a line
#: break in Word. A no-break space is not in it. Read as `\s`, one came back as a plain space,
#: so a merge could not carry it and refused every edited stretch that held one - and Word's
#: French AutoCorrect puts one before `:` and inside « », and authors put one in "5 mg".
_LAYOUT = re.compile(r"[ \t\n\r\f\v]+")


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
    """One paragraph of the body, or one table, in document order."""

    #: The paragraph identifiers it carries. More than one means paragraphs were joined.
    names: tuple[str, ...] = ()
    #: What it says, with every tracked change accepted: layout whitespace as single spaces,
    #: a no-break space as itself. See `spaced`.
    text: str = ""
    #: A table or a figure: a block that is not prose, and not compared.
    table: bool = False
    #: Every word of it, and its paragraph mark, tracked as arriving here: typed, pasted, or
    #: moved here. It was not here in the document as sent, whatever identifier it carries.
    arrived: bool = False


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
    #: How its paragraph mark was tracked: "ins", "del", "moveTo", "moveFrom", or "".
    mark: str = ""
    #: Its mark and all of its text were tracked as arriving: it was not in the document
    #: as it was sent.
    arrived: bool = False
    #: It arrived and was then deleted again, by a second reviewer: its mark carries both.
    retracted: bool = False
    #: The names of the tracked moves its moved text belongs to.
    moves: tuple[str, ...] = ()


def _text(element: ET.Element, unseen: set[str] = _UNSEEN) -> str:
    """The visible text under `element`, tracked changes accepted."""
    out: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.tag in unseen:
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
    return spaced("".join(out)).strip()


def _removes(element: ET.Element) -> bool:
    """It deleted or moved away text it was sent with: a deletion inside text that arrived
    is an edit to the arrival, and the paragraph mark's own change is in its properties."""

    def walk(node: ET.Element) -> bool:
        if node.tag in (W + "del", W + "moveFrom"):
            return True
        if node.tag in _ARRIVED or node.tag in (W + "pPr", W + "txbxContent", _MC + "Fallback"):
            return False
        return any(walk(child) for child in node)

    return any(walk(child) for child in element)


def _paragraph(element: ET.Element, *, table: bool, moves: tuple[str, ...]) -> _Paragraph:
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
    properties = element.find(f"{W}pPr/{W}rPr")
    mark = next(
        (
            kind
            for kind in ("moveFrom", "del", "moveTo", "ins")
            if properties is not None and properties.find(W + kind) is not None
        ),
        "",
    )
    runs_on = mark in ("moveFrom", "del")
    retracted = runs_on and properties is not None and any(
        properties.find(W + kind) is not None for kind in ("ins", "moveTo")
    )
    # Enter at the end of a paragraph marks its mark inserted too, and one retyped whole has
    # no text but inserted text: what it does have is the text it deleted.
    arrived = (
        mark in ("moveTo", "ins")
        and not _text(element, _ARRIVED_OR_UNSEEN)
        and not _removes(element)
    )
    return _Paragraph(
        tuple(names),
        _text(element),
        tuple(comments),
        runs_on,
        table,
        picture,
        mark=mark,
        arrived=arrived,
        retracted=retracted,
        moves=moves,
    )


def _walk_body(
    node: ET.Element, moves: dict[int, tuple[str, ...]], *, table: bool = False
) -> list[_Paragraph]:
    out: list[_Paragraph] = []
    for child in node:
        if child.tag == W + "p":
            out.append(_paragraph(child, table=table, moves=moves.get(id(child), ())))
        elif child.tag == W + "tbl":
            out.extend(_walk_body(child, moves, table=True))
        elif child.tag not in _UNSEEN and child.tag != W + "sectPr":
            # Content controls, custom XML, table rows and cells: look inside.
            out.extend(_walk_body(child, moves, table=table or child.tag == W + "tc"))
    return out


def _move_names(body: ET.Element) -> dict[int, tuple[str, ...]]:
    """The tracked moves each paragraph's moved text belongs to, by `id()` of the paragraph.

    Word marks a move with a range on each side, a start and an end sharing an id, and names
    the two ranges alike. The ends need not sit in the paragraph they begin in, or in any
    paragraph, so the ranges are followed through the body in document order.
    """
    found: dict[int, list[str]] = {}
    open_ranges: dict[tuple[str, str], str] = {}

    def walk(node: ET.Element, paragraph: ET.Element | None) -> None:
        if node.tag in _MOVE_STARTS:
            open_ranges[(_MOVE_STARTS[node.tag], node.get(W + "id", ""))] = node.get(
                W + "name", ""
            )
        elif node.tag in _MOVE_ENDS:
            open_ranges.pop((_MOVE_ENDS[node.tag], node.get(W + "id", "")), None)
        elif node.tag in (W + "moveFrom", W + "moveTo") and paragraph is not None:
            side = node.tag.removeprefix(W)
            names = found.setdefault(id(paragraph), [])
            names += [
                name
                for (kind, _id), name in open_ranges.items()
                if kind == side and name not in names
            ]
        # A paragraph mark's own move is in its properties, and says nothing about a range.
        if node.tag in (W + "pPr", W + "txbxContent", _MC + "Fallback"):
            return
        here = node if node.tag == W + "p" else paragraph
        for child in node:
            walk(child, here)

    walk(body, None)
    return {key: tuple(names) for key, names in found.items()}


def _settled(paragraphs: list[_Paragraph]) -> list[_Paragraph]:
    """Each identifier on the paragraph it names, where tracked changes say Word left it.

    - A paragraph moved with Track Changes on leaves its identifier in the moved-from copy.
      Word names each move, with the same name on the paragraphs it left and those it
      arrived as, so the identifier goes to the paragraph it became. Only a move of whole
      paragraphs is read, with as many arriving as leaving: the identifier then has exactly
      one place to go. Anything else keeps its identifiers where they are, and the import
      reports it rather than guessing.
    - A paragraph that arrived, mark and every word of it, in front of an identified one
      took that one's identifier, which goes back to the paragraph it names. That is a paste
      landing at the start of a paragraph, and Enter pressed there. It goes past a paragraph
      that arrived and was deleted again, and no further: a paragraph deleted whole takes
      its own identifier back and is reported deleted. Only a recorded move gives one to an
      empty line; text typed on the empty line an HTML comment renders as is text typed
      where that paragraph renders nothing, and is refused as such.

    Moves come first, so that an identifier a move carries is not then taken for one that
    slid.
    """
    out = list(paragraphs)
    carried: set[str] = set()
    for move in dict.fromkeys(name for paragraph in out for name in paragraph.moves):
        involved = [i for i, paragraph in enumerate(out) if move in paragraph.moves]
        left = [i for i in involved if out[i].mark == "moveFrom" and not out[i].text]
        arrived = [i for i in involved if out[i].mark == "moveTo" and out[i].arrived]
        if not left or len(left) != len(arrived) or len(left) + len(arrived) != len(involved):
            continue
        for was, now in zip(left, arrived, strict=True):
            carried.update(out[was].names)
            out[now] = replace(out[now], names=out[was].names + out[now].names)
            out[was] = replace(out[was], names=())
    for index, paragraph in enumerate(out):
        slid = tuple(name for name in paragraph.names if name not in carried)
        if not (paragraph.arrived and slid) or paragraph.table:
            continue
        after = next(
            (
                i
                for i in range(index + 1, len(out))
                if not out[i].arrived and not (out[i].retracted and not out[i].text)
            ),
            None,
        )
        if after is None or out[after].table:
            continue
        if not out[after].text and not out[after].runs_on and paragraph.mark != "moveTo":
            continue
        out[after] = replace(out[after], names=slid + out[after].names)
        out[index] = replace(paragraph, names=tuple(n for n in paragraph.names if n in carried))
    return out


def paragraphs_of(document: Path, part: str = "word/document.xml") -> list[_Paragraph]:
    """Every paragraph in one part of the document, in order, tables included, each carrying
    the identifiers of the paragraph it is (see `_settled`)."""
    try:
        with open_archive(document) as archive:
            if part not in archive.namelist():
                return []
            root = read_part(archive, part, what=f"{document.name}:{part}")
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc
    body = root.find(W + "body")
    body = body if body is not None else root
    return _settled(_walk_body(body, _move_names(body)))


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
    text = spaced(" ".join(p.text for p in kept if p.text)).strip()
    return [Block(names=names, text=text, arrived=all(p.arrived for p in kept))]


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
