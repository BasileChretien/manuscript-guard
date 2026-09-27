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

import hashlib
import posixpath
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import UnsafeDocument, open_archive, read_part
from manuscript_guard.wordfonts import Fonts, RunFonts, symbol

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_VML_IMAGE = "{urn:schemas-microsoft-com:vml}imagedata"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
W16SE = "{http://schemas.microsoft.com/office/word/2015/wordml/symex}"

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
#: Text tracked as arriving: typed or pasted, or moved here. Skipped with `_UNSEEN`, what is
#: left is the text the document was sent with.
_ARRIVED = {W + "ins", W + "moveTo"}
_ARRIVED_OR_UNSEEN = _UNSEEN | _ARRIVED
#: The two ends of a tracked move's range, by the side of the move they mark.
_MOVE_STARTS = {W + "moveFromRangeStart": "moveFrom", W + "moveToRangeStart": "moveTo"}
_MOVE_ENDS = {W + "moveFromRangeEnd": "moveFrom", W + "moveToRangeEnd": "moveTo"}

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
    #: "table", "figure" or "equation" for a block that is not prose, "" for a paragraph.
    kind: str = ""
    #: What tells a table, a figure or an equation apart from the others in another copy of
    #: the document: a digest of a table's text, of the picture a figure shows, or of the
    #: equation. Word renumbers and renames the parts a picture is stored in when it saves;
    #: the picture stays the same. Empty when the picture could not be read.
    key: str = ""
    #: Every word of it, and its paragraph mark, tracked as arriving here: typed, pasted, or
    #: moved here. It was not here in the document as sent, whatever identifier it carries.
    arrived: bool = False
    #: What its style says it is: "heading", "caption", "reference" (an entry of the reference
    #: list), or "" for anything else. See `_roles`.
    role: str = ""

    #: What Word draws in it that is not read as text, or not read exactly, named once for
    #: each occurrence: a Wingdings character, a piece of a tall bracket, a private-use
    #: character, Symbol-font text whose font a style sets. See `wordfonts`.
    unread: tuple[str, ...] = ()

    @property
    def table(self) -> bool:
        """A table, a figure or an equation: a block that is not prose, and not compared."""
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
    #: The text of the equation it holds, None when it holds none. Word keeps maths as
    #: OMML, whose text is not `w:t`.
    maths: str | None = None
    #: How its paragraph mark was tracked: "ins", "del", "moveTo", "moveFrom", or "".
    mark: str = ""
    #: Its mark and all of its text were tracked as arriving: it was not in the document
    #: as it was sent.
    arrived: bool = False
    #: It arrived and was then deleted again, by a second reviewer: its mark carries both.
    retracted: bool = False
    #: The names of the tracked moves its moved text belongs to.
    moves: tuple[str, ...] = ()
    #: What its style says it is; see `Block.role`.
    role: str = ""
    unread: tuple[str, ...] = ()


#: A heading level, which Word writes as an outline level of 0 to 8; 9 is body text.
_HEADING_LEVELS = frozenset("012345678")
_HEADING_NAME = re.compile(r"heading [1-9]")


def _roles(archive, what: str) -> dict[str, str]:
    """Each paragraph style's role, by style id.

    By name and outline level, never by id: Word renames the ids when it saves in another
    language - a Japanese Word saved pandoc's `Heading1` as `1` and `BodyText` as `a0` - and
    keeps the built-in names ("heading 1", "caption", "Bibliography"). A heading is a style
    whose outline level, its own or one it is based on, is a heading level; a table of
    contents heading is based on heading 1 and sets its own back to body text, and is not one.
    A caption or a reference entry is named so, or based on a style that is.
    """
    if "word/styles.xml" not in archive.namelist():
        return {}
    styles: dict[str, tuple[str, str, str | None]] = {}
    for style in read_part(archive, "word/styles.xml", what=f"{what}:styles").iter(W + "style"):
        if style.get(W + "type") != "paragraph":
            continue
        name, based = style.find(W + "name"), style.find(W + "basedOn")
        level = style.find(f"{W}pPr/{W}outlineLvl")
        styles[style.get(W + "styleId", "")] = (
            (name.get(W + "val", "") if name is not None else "").strip().lower(),
            based.get(W + "val", "") if based is not None else "",
            level.get(W + "val") if level is not None else None,
        )

    def role(style_id: str) -> str:
        names: list[str] = []
        outline: str | None = None
        seen: set[str] = set()
        while style_id in styles and style_id not in seen:
            seen.add(style_id)
            name, based, level = styles[style_id]
            names.append(name)
            outline = level if outline is None else outline
            style_id = based
        if outline in _HEADING_LEVELS or (
            outline is None and any(_HEADING_NAME.fullmatch(name) for name in names)
        ):
            return "heading"
        if "caption" in names:
            return "caption"
        return "reference" if "bibliography" in names else ""

    return {style_id: role(style_id) for style_id in styles}


def _role(element: ET.Element, roles: dict[str, str]) -> str:
    """A paragraph's role: its style's, unless an outline level set on the paragraph itself
    says otherwise."""
    style = element.find(f"{W}pPr/{W}pStyle")
    found = roles.get(style.get(W + "val", ""), "") if style is not None else ""
    level = element.find(f"{W}pPr/{W}outlineLvl")
    if level is None:
        return found
    if level.get(W + "val") in _HEADING_LEVELS:
        return "heading"
    return "" if found == "heading" else found


def _text(element: ET.Element, fonts: Fonts | None = None) -> str:
    """The visible text under `element`, tracked changes accepted."""
    return _read(element, fonts or Fonts())[0]


def _kept(element: ET.Element) -> bool:
    """Whether any text under `element` was there when the document was sent: text neither
    deleted nor moved away, nor typed, pasted or moved here."""
    stack = [element]
    while stack:
        node = stack.pop()
        if node.tag == W + "t" and (node.text or "").strip():
            return True
        stack.extend(child for child in node if child.tag not in _ARRIVED_OR_UNSEEN)
    return False


def _read(
    element: ET.Element, fonts: Fonts
) -> tuple[str, tuple[tuple[int, int], ...], tuple[str, ...]]:
    """The visible text under `element`, where each marked token sits in it, and what
    in it is not read as text, named.

    A character is read as the font it is in draws it: Insert > Symbol writes a `w:sym`,
    and text typed in the Symbol font is in that font's encoding. See `wordfonts`.
    """
    out: list[object] = []
    marked: set[str] = set()
    unread: list[str] = []
    paragraph = element if element.tag == W + "p" else None

    def walk(node: ET.Element, run: RunFonts) -> None:
        if node.tag in _UNSEEN:
            return
        if node.tag == W + "r":
            run = fonts.run(node, paragraph)
        if node.tag == W + "t" and node.text:
            text, missing = run.read(node.text)
            out.append(text)
            unread.extend(missing)
        elif node.tag in _SPACES:
            out.append(" ")
        elif node.tag == W + "noBreakHyphen":
            out.append("-")
        elif node.tag == W + "bookmarkStart" and node.get(W + "name", "").startswith(TOKEN):
            marked.add(node.get(W + "id", ""))
            out.append(_OPEN)
        elif node.tag == W + "bookmarkEnd" and node.get(W + "id", "") in marked:
            out.append(_CLOSE)
        elif node.tag == W16SE + "symEx":
            # In the font it names, as text is in its run's: a symbol or icon font's code too.
            shown, name = fonts.drawn(extended_symbol(node), node.get(W16SE + "font"))
            out.append(shown)
            if name is not None:
                unread.append(name)
        elif node.tag == W + "sym":
            shown, name = symbol(node)
            if shown is None:
                unread.append(name)
            else:
                out.append(shown)
        for child in node:
            walk(child, run)

    walk(element, fonts.run(None, paragraph))
    text, tokens = _extents(out)
    return text, tokens, tuple(unread)


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


def extended_symbol(node: ET.Element) -> str:
    """A `w16se:symEx` character, by its code point: an emoji inserted in Word can be one.

    Word writes it in an AlternateContent choice, with the character as text only in the
    fallback, which is not read. Read as nothing, an emoji the author inserted never came
    back, and one already in the source was deleted from it. The audit's reader uses this too.

    Only a character that document text could hold. A control character would pass for the
    mark the audit's reader puts on a heading's line, and a lone surrogate cannot be printed.
    """
    try:
        code = int(node.get(W16SE + "char", ""), 16)
    except ValueError:
        return " "
    text = 0x20 <= code < 0xD800 or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF
    return chr(code) if text else " "


def runs_on(paragraph: ET.Element) -> bool:
    """Whether a paragraph's mark was deleted, or moved away, as a tracked change.

    Once the change is accepted the paragraph runs on into the next one, with nothing
    between them: Word joins "-0.5" and "1" into "-0.51". The audit's reader uses this too.
    """
    mark = paragraph.find(f"{W}pPr/{W}rPr")
    return mark is not None and (
        mark.find(W + "del") is not None or mark.find(W + "moveFrom") is not None
    )


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


def _paragraph(
    element: ET.Element,
    *,
    table: bool,
    moves: tuple[str, ...],
    fonts: Fonts,
    roles: dict[str, str],
) -> _Paragraph:
    names: list[str] = []
    comments: list[str] = []
    for node in element.iter():
        if node.tag == W + "bookmarkStart":
            name = node.get(W + "name", "")
            if _IDENTIFIER.match(name) and name not in names:
                names.append(name)
        elif node.tag == W + "commentRangeStart":
            comments.append(node.get(W + "id", ""))
    # What a reader sees once every tracked change is accepted. A picture or an equation
    # deleted, or moved away, with Track Changes on is still in the XML, and read from there
    # it came back as if untouched: the deletion or the move said "nothing came back".
    seen = list(_visible(element))
    picture = any(node.tag in _PICTURES for node in seen)
    embeds = tuple(
        rid
        for node in seen
        if (rid := node.get(_R + "embed") or (node.tag == _VML_IMAGE and node.get(_R + "id")))
    )
    properties = element.find(f"{W}pPr/{W}rPr")
    mark = next(
        (
            kind
            for kind in ("moveFrom", "del", "moveTo", "ins")
            if properties is not None and properties.find(W + kind) is not None
        ),
        "",
    )
    joined = runs_on(element)
    retracted = joined and properties is not None and any(
        properties.find(W + kind) is not None for kind in ("ins", "moveTo")
    )
    # Enter at the end of a paragraph marks its mark inserted too, and one retyped whole has
    # no text but inserted text: what it does have is the text it deleted.
    arrived = mark in ("moveTo", "ins") and not _kept(element) and not _removes(element)
    text, tokens, unread = _read(element, fonts)
    maths = None
    if any(node.tag == _M + "oMath" for node in seen):
        # Word deletes an equation run by run with Track Changes on, leaving the `m:oMath`
        # around nothing: an equation with no text left is gone.
        maths = "".join(node.text or "" for node in seen if node.tag == _M + "t") or None
    return _Paragraph(
        tuple(names),
        text,
        tuple(comments),
        joined,
        table,
        picture,
        tokens,
        embeds,
        maths,
        mark=mark,
        arrived=arrived,
        retracted=retracted,
        moves=moves,
        role=_role(element, roles),
        unread=unread,
    )


def _visible(element: ET.Element):
    """Every node under `element`, `element` included, outside the subtrees `_UNSEEN` hides."""
    stack = [element]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for child in reversed(node) if child.tag not in _UNSEEN)


def _walk_body(
    node: ET.Element,
    moves: dict[int, tuple[str, ...]],
    roles: dict[str, str],
    *,
    fonts: Fonts,
    table: bool = False,
) -> list[_Paragraph]:
    out: list[_Paragraph] = []
    for child in node:
        if child.tag == W + "tr" and child.find(f"{W}trPr/{W}del") is not None:
            # A table row deleted with Track Changes on: gone once the change is accepted.
            continue
        if child.tag == W + "p":
            found = moves.get(id(child), ())
            out.append(_paragraph(child, table=table, moves=found, fonts=fonts, roles=roles))
        elif child.tag == W + "tbl":
            out.extend(_walk_body(child, moves, roles, fonts=fonts, table=True))
        elif child.tag not in _UNSEEN and child.tag != W + "sectPr":
            # Content controls, custom XML, table rows and cells: look inside.
            inside = table or child.tag == W + "tc"
            out.extend(_walk_body(child, moves, roles, fonts=fonts, table=inside))
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
        # Enter at the end of the moved copy marks its mark inserted, not moved.
        arrived = [i for i in involved if out[i].mark in ("moveTo", "ins") and out[i].arrived]
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
            roles = _roles(archive, document.name)
            # Which font a run is in decides what its text is; see `wordfonts`.
            fonts = Fonts.of(archive, document.name)
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc
    body = root.find(W + "body")
    body = body if body is not None else root
    return _settled(_walk_body(body, _move_names(body), roles, fonts=fonts))


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
        if paragraph.maths is not None and not paragraph.names and not paragraph.text:
            # Display maths: an equation and no text. Read as an empty paragraph, it could be
            # dragged into another section or deleted and import said "nothing came back".
            out.extend(_fold(pending))
            pending = []
            out.append(Block(kind="equation", key=_digest([paragraph.maths])))
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
    the file it names are not: Word renumbers and renames them on every save. A picture that
    cannot be read gets no digest, and its figure is then known by its place alone.
    """
    if not wanted:
        return {}
    rels = "word/_rels/document.xml.rels"
    try:
        with open_archive(document) as archive:
            if rels not in archive.namelist():
                return {}
            digests: dict[str, str | None] = {}
            found = {}
            for rel in read_part(archive, rels, what=f"{document.name}:{rels}").iter(_RELS):
                rid, target = rel.get("Id", ""), rel.get("Target", "")
                if rid not in wanted or rel.get("TargetMode") == "External" or not target:
                    continue
                part = target[1:] if target.startswith("/") else posixpath.normpath(
                    f"word/{target}"
                )
                if part not in digests:
                    digests[part] = _digest_of(archive, part)
                if digests[part]:
                    found[rid] = digests[part]
            return found
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc


def _digest_of(archive: zipfile.ZipFile, part: str) -> str | None:
    """A digest of one part, or None when it cannot be read.

    Reading a picture is not what the import is for, so a part it cannot read must not stop
    it: a missing part, a compression `zipfile` does not support, an encrypted or corrupt one.
    Each decompressor fails in its own way - a list of the exceptions missed `lzma.LZMAError`
    and the import died with a traceback - so any failure means only that the figure is
    known by its place.
    """
    try:
        return hashlib.sha256(archive.read(part)).hexdigest()
    except Exception:
        return None


def _fold(run: list[_Paragraph]) -> list[Block]:
    if not run:
        return []
    # One holding only a symbol with no text is not an empty line: left out, its identifier
    # was dropped, and a paragraph joined in Word was reported deleted.
    kept = [p for p in run if p.text or p.unread or p is run[-1]]
    names = tuple(dict.fromkeys(n for p in kept for n in p.names))
    text = spaced(" ".join(p.text for p in kept if p.text)).strip()
    # Token extents are read from the build import compares with, which has no tracked
    # changes to fold; offsets into a joined paragraph would need shifting, so none are kept.
    tokens = kept[0].tokens if len(kept) == 1 else ()
    unread = tuple(u for p in run for u in p.unread)
    arrived = all(p.arrived for p in kept)
    # The role of the paragraph the block opens with, which carries its identifier: a
    # paragraph run on into the heading after it is that paragraph, joined, not a heading.
    role = kept[0].role
    return [
        Block(names=names, text=text, tokens=tokens, unread=unread, arrived=arrived, role=role)
    ]


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
            fonts = Fonts.of(archive, document.name)
    except UnsafeDocument as exc:
        raise DocumentUnreadable(str(exc)) from exc
    out = []
    for comment in root.iter(W + "comment"):
        attributes = {key.removeprefix(W): value for key, value in comment.attrib.items()}
        text = " ".join(_text(p, fonts) for p in comment.iter(W + "p"))
        out.append((attributes, spaced(text).strip()))
    return out
