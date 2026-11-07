"""What a Word document holds that a person reading it does not see, and a model reading it
does (`read_hidden`).

In 2025 several preprints carried "give a positive review" in white or tiny text, for the
language models some reviewers had read them. A document built here goes to model readers
too, and agents read the Word files co-authors return. So each run of text in the body, the
notes, the headers, the footers and the comments is read as Word draws it (`hidden.styles`),
and what follows is reported, each with the words it holds:

- **hidden**: hidden by the run's own properties or by its styles (`w:vanish`), or inside a
  picture or a box Word is told not to show (`wp:docPr hidden`, VML `visibility:hidden`);
- **background**: text whose colour is too close to what is behind it to be read, a
  contrast ratio under 1.5 (`colour.contrast`): its highlight, its shading, its paragraph's
  or its table cell's, or else the page, white on paper, and the page's background where
  the document shows one;
- **tiny**: text under 3 pt;
- **zero-width**: a zero-width character inside a word, or tag characters
  (`hidden.words`);
- **to-a-model**: words telling a model what to do (`hidden.words`), wherever the file holds
  them: in the text, a tracked deletion, a field's code, a picture's alternative text, the
  document's properties, any other part of it. `printed` says whether they stand in text a
  reader sees, where a paper about such words may quote them; the same words also printed
  somewhere in the document count as printed.

Whitespace hidden is not reported, nor a run of automatic colour, which Word draws in black
or white against what is behind it. What is not read is in DESIGN.md, Known gaps.

The file is read as every untrusted Word file is (`safexml`): no part with a DTD, none past
the size limits, and two parts under one name refused, since which of them Word shows is not
known. Of its XML, the parts that hold the text are always read; the rest, for words to a
model, up to twice the limit for one part, and the parts past it are named as not read.
"""

from __future__ import annotations

import posixpath
import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.colour import RGB, contrast, hex_of
from manuscript_guard.hidden.styles import (
    WHITE,
    Styles,
    Theme,
    W,
    fill_colour,
    hex_colour,
    highlight_colour,
    on_off,
    text_colour,
)
from manuscript_guard.hidden.words import Spot, to_a_model_in, worth_reading, zero_width_in
from manuscript_guard.safexml import MAX_PART_BYTES, UnsafeDocument, open_archive, read_part

HIDDEN, BACKGROUND, TINY, ZERO_WIDTH, TO_A_MODEL = (
    "hidden", "background", "tiny", "zero-width", "to-a-model",
)  # fmt: skip
#: Text under this size, in half-points (3 pt), is too small to read.
TINY_BELOW = 6
#: Text whose contrast ratio with what is behind it is under this is not told from it.
CONTRAST_BELOW = 1.5
#: How much of what a place holds a finding quotes.
QUOTED = 160
#: How much of a document's XML, besides the parts that hold its text, is read.
READ_AT_MOST = 2 * MAX_PART_BYTES
#: A size as `w:sz` writes it: half-points, or points with `pt` after them.
_SIZE = re.compile(r"([0-9]{1,6}(?:\.[0-9]{1,4})?)(pt)?")
#: How much of a paragraph's opening words say where it is.
_OPENING = 60

_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_VML = "{urn:schemas-microsoft-com:vml}"
_RELATIONSHIPS = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
#: The notes a part holds, by the element each opens with, and the element that cites one.
_NOTES = {f"{W}footnote": f"{W}footnoteReference", f"{W}endnote": f"{W}endnoteReference"}
#: The parts that hold the text, by the element they open with: what each is called, and
#: whether a reader of the printed document sees it. Comments are read in Word's margin,
#: not in the document.
_STORIES = {
    f"{W}document": ("the body", True), f"{W}hdr": ("a header", True),
    f"{W}ftr": ("a footer", True), f"{W}footnotes": ("the footnotes", True),
    f"{W}endnotes": ("the endnotes", True), f"{W}comments": ("the comments", False),
}  # fmt: skip
_STORY_NAME = re.compile(r"word/(?:document|footnotes|endnotes|comments|header\d*|footer\d*)\.xml")
#: The text a run holds: the text proper, read by the walker, and what it reads apart.
_SHOWN = (f"{W}t",)
_GONE = (f"{W}delText",)
_CODE = (f"{W}instrText", f"{W}delInstrText")
_SPACING = {f"{W}tab": "\t", f"{W}ptab": "\t", f"{W}br": "\n", f"{W}cr": "\n",
            f"{W}noBreakHyphen": "-"}  # fmt: skip
#: What the parts that hold no text are called where words are found in them.
_PLACES = (
    ("docProps/core.xml", "the document's properties"),
    ("docProps/app.xml", "the application's properties"),
    ("docProps/custom.xml", "the document's custom properties"),
    ("customXml/", "custom data stored in the document"),
    ("word/settings.xml", "the document's settings"),
    ("word/glossary/", "the document's building blocks"),
)
_ATTRIBUTES = {"descr": "a picture's alternative text", "title": "a picture's title",
               "instr": "a field's code"}  # fmt: skip


@dataclass(frozen=True)
class Hidden:
    """One place a reader does not see: of which `kind`, `where`, the words it holds as a
    model reads them, `how` it is kept from sight, and the part it is in. `printed` for
    words to a model in text a reader sees; `runs`, the runs of text a span of hidden text
    holds; `model`, the rule of words to a model the words match, of a span of hidden text
    whose words are addressed to a model too."""

    kind: str
    where: str
    text: str
    how: str
    part: str
    printed: bool = False
    runs: int = 0
    model: str = ""


@dataclass(frozen=True)
class Reading:
    """What `read_hidden` found in one document, and the parts of it not read, each with
    why."""

    path: Path
    found: tuple[Hidden, ...] = ()
    unread: tuple[str, ...] = ()


def quoted(text: str) -> str:
    """What a place holds, its spaces folded and cut to `QUOTED` characters."""
    folded = " ".join(text.split())
    return folded if len(folded) <= QUOTED else folded[: QUOTED - 3].rstrip() + "..."


@dataclass
class _Paragraph:
    number: int
    style: str | None
    behind: tuple[RGB, str] | None
    pieces: list[tuple[str, tuple[str, str] | None]] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Context:
    behind: tuple[RGB, str] | None = None
    unseen: str = ""
    gone: bool = False
    paragraph: _Paragraph | None = None


@dataclass(frozen=True)
class _Page:
    """What the document is drawn on: the paper, and its background where it shows one."""

    behind: tuple[tuple[RGB, str], ...] = ((WHITE, "the page"),)


@dataclass(frozen=True)
class _Shown:
    """The headers and footers a section shows, and the notes the text cites: None where
    the main document could not be read, and each is then taken as shown."""

    parts: frozenset[str] | None = None
    notes: frozenset[tuple[str, str]] | None = None


@dataclass(frozen=True)
class _Look:
    styles: Styles
    theme: Theme
    page: _Page
    shown: _Shown = _Shown()


def _first(*elements: ET.Element | None) -> ET.Element | None:
    return next((element for element in elements if element is not None), None)


def _val(element: ET.Element | None) -> str | None:
    return None if element is None else element.get(f"{W}val")


def _half_points(element: ET.Element | None) -> float | None:
    """A size in half-points (`w:sz`), or None where it cannot be read: by its pattern,
    never by `int` alone, which raises on digits it refuses or a value too long (round 1
    of #574)."""
    size = _SIZE.fullmatch((_val(element) or "").strip())
    if size is None:
        return None
    return float(size.group(1)) * (2 if size.group(2) else 1)


def _drawn_unseen(element: ET.Element) -> str:
    """Why a picture or a box keeps what it holds from sight, or "" where it does not."""
    if element.tag in (f"{_WP}inline", f"{_WP}anchor"):
        properties = element.find(f"{_WP}docPr")
        if properties is not None and (properties.get("hidden") or "").casefold() in ("1", "true"):
            return "in a picture or a box Word is told not to show"
    if element.tag.startswith(_VML):
        style = "".join((element.get("style") or "").split()).casefold()
        if "visibility:hidden" in style:
            return "in a shape Word is told not to show"
    return ""


def _behind(direct, style, character, paragraph: _Paragraph, look: _Look):
    """What is behind a run, nearest first: its highlight, its shading, its paragraph's or
    its cell's, or the page."""
    styled = look.styles.run_property
    highlight = highlight_colour(_first(direct("highlight"), styled("highlight", style, character)))
    if highlight is not None:
        return ((highlight, "its highlight"),)
    shading = fill_colour(_first(direct("shd"), styled("shd", style, character)), look.theme)
    if shading is not None:
        return ((shading, "its shading"),)
    if paragraph.behind is not None:
        return (paragraph.behind,)
    return look.page.behind


def _unseen(run: ET.Element, text: str, context: _Context, look: _Look) -> tuple[str, str] | None:
    """Whether a run with `text` in it is kept from sight, and how: (kind, how) or None."""
    paragraph = context.paragraph
    if paragraph is None or not text.strip():
        return None
    if context.unseen:
        return HIDDEN, context.unseen
    properties = run.find(f"{W}rPr")

    def direct(tag: str) -> ET.Element | None:
        return None if properties is None else properties.find(f"{W}{tag}")

    character = _val(direct("rStyle"))
    style = paragraph.style
    if how := _vanished(run, style, look):
        return HIDDEN, how
    styled = look.styles.run_property
    colour = text_colour(_first(direct("color"), styled("color", style, character)), look.theme)
    if colour is not None:
        for back, name in _behind(direct, style, character, paragraph, look):
            if contrast(colour, back) < CONTRAST_BELOW:
                return BACKGROUND, f"{hex_of(colour)} text on {name} ({hex_of(back)})"
    complex_script = bool(on_off(direct("cs")) or on_off(direct("rtl")))
    tag = "szCs" if complex_script else "sz"
    size = _half_points(_first(direct(tag), styled(tag, style, character)))
    if size is not None and size < TINY_BELOW:
        return TINY, f"{size / 2:g} pt"
    return None


def _vanished(run: ET.Element, style: str | None, look: _Look) -> str:
    """How a run is hidden by its own formatting or its styles (`w:vanish`), whatever it
    holds, or "" where it is not."""
    properties = run.find(f"{W}rPr")
    own = None if properties is None else properties.find(f"{W}vanish")
    vanish = on_off(own)
    if vanish is not None:
        return "hidden by its own formatting" if vanish else ""
    character = None if properties is None else _val(properties.find(f"{W}rStyle"))
    hides, turned = look.styles.toggled("vanish", style, character)
    if not hides:
        return ""
    named = " and ".join(f"'{name}'" for name in turned)
    return (f"hidden by the style {named}" if len(turned) == 1
            else f"hidden by the styles {named}" if turned
            else "hidden by the document's default formatting")  # fmt: skip


def _read_run(run: ET.Element, context: _Context, look: _Look) -> None:
    paragraph = context.paragraph
    if paragraph is None:
        return
    written: list[str] = []
    for child in run:
        if child.tag in _SHOWN:
            (paragraph.gone if context.gone else written).append(child.text or "")
        elif child.tag in _SPACING:
            written.append(_SPACING[child.tag])
        elif child.tag in _GONE:
            paragraph.gone.append(child.text or "")
        elif child.tag in _CODE:
            paragraph.codes.append(child.text or "")
    text = "".join(written)
    if text:
        paragraph.pieces.append((text, _unseen(run, text, context, look)))


def _paragraph_of(element: ET.Element, number: int, context: _Context, look: _Look) -> _Paragraph:
    properties = element.find(f"{W}pPr")
    named = None if properties is None else _val(properties.find(f"{W}pStyle"))
    style = look.styles.paragraph_style(named)
    shading = None if properties is None else properties.find(f"{W}shd")
    fill = fill_colour(_first(shading, look.styles.paragraph_shading(style)), look.theme)
    behind = (fill, "the paragraph's shading") if fill is not None else context.behind
    return _Paragraph(number, style, behind)


def _cell_behind(element: ET.Element, holder: str, name: str, look: _Look, context: _Context):
    fill = fill_colour(element.find(f"{W}{holder}/{W}shd"), look.theme)
    return (fill, name) if fill is not None else context.behind


def _paragraphs(root: ET.Element, look: _Look) -> list[_Paragraph]:
    """Each paragraph of a part, in the order of the document, with its runs read; a text
    box's paragraphs among them, where its own paragraph holds it. Read without recursion,
    so that no depth of nesting stops it."""
    found: list[_Paragraph] = []
    stack: list[tuple[ET.Element, _Context]] = [(root, _Context())]
    while stack:
        element, context = stack.pop()
        tag = element.tag
        if tag == _FALLBACK:
            continue
        if tag == f"{W}tbl":
            context = replace(context, behind=_cell_behind(element, "tblPr", "the table's shading",
                                                           look, context))  # fmt: skip
        elif tag == f"{W}tc":
            context = replace(context, behind=_cell_behind(element, "tcPr", "the cell's shading",
                                                           look, context))  # fmt: skip
        elif tag in (f"{W}del", f"{W}moveFrom"):
            context = replace(context, gone=True)
        elif tag == f"{W}p":
            paragraph = _paragraph_of(element, len(found) + 1, context, look)
            found.append(paragraph)
            context = replace(context, paragraph=paragraph, behind=paragraph.behind)
        elif tag == f"{W}r":
            if context.paragraph is None:
                # A run outside any paragraph, which Word refuses and another reader may
                # not: read as a paragraph of its own, so that its text is not passed over.
                paragraph = _Paragraph(len(found) + 1, look.styles.paragraph_style(None),
                                       context.behind)  # fmt: skip
                found.append(paragraph)
                context = replace(context, paragraph=paragraph)
            _read_run(element, context, look)
            # A picture or a box in a run Word hides is hidden with it (round 1 of #574).
            how = context.unseen or _vanished(element, context.paragraph.style, look)
            if how and not context.unseen:
                context = replace(context, unseen=f"in a picture or a box in a run {how}")
        elif why := _drawn_unseen(element):
            context = replace(context, unseen=why)
        stack.extend((child, context) for child in reversed(list(element)))
    return found


def _spans(pieces) -> list[tuple[int, int, str, str, int]]:
    """The spans of a paragraph's text kept from sight: start, end, kind, how and how many
    runs, two runs kept alike with only spaces between them one span."""
    text = "".join(piece for piece, _ in pieces)
    spans: list[tuple[int, int, str, str, int]] = []
    at = 0
    for piece, unseen in pieces:
        end = at + len(piece)
        if unseen is not None:
            last = spans[-1] if spans else None
            if last and (last[2], last[3]) == unseen and not text[last[1] : at].strip():
                spans[-1] = (last[0], end, *unseen, last[4] + 1)
            else:
                spans.append((at, end, *unseen, 1))
        at = end
    return spans


def _where(label: str, paragraph: _Paragraph) -> str:
    shown = "".join(p for p, unseen in paragraph.pieces if unseen is None)
    opening = " ".join(shown.split()[:8])
    opening = opening if len(opening) <= _OPENING else opening[: _OPENING - 3] + "..."
    begins = f", which begins {opening!r}" if opening else ""
    return f"{label}, paragraph {paragraph.number}{begins}"


def _story(root: ET.Element, part: str, look: _Look, printed_said: set[str]) -> list[Hidden]:
    """What a part that holds text hides: a note at a time where it holds notes, each
    printed only where the text cites it, and a header or a footer printed only where a
    section shows it (round 1 of #574)."""
    label, printed = _STORIES[root.tag]
    shown = look.shown
    notes = [note for note in root if note.tag in _NOTES]
    if notes:
        found: list[Hidden] = []
        for note in notes:
            number = note.get(f"{W}id", "")
            cited = shown.notes is None or (note.tag, number) in shown.notes
            found += _items(_paragraphs(note, look), f"{label}, note {number}", part,
                            printed and cited, printed_said)  # fmt: skip
        return found
    if root.tag in (f"{W}hdr", f"{W}ftr") and shown.parts is not None:
        printed = part in shown.parts
    return _items(_paragraphs(root, look), label, part, printed, printed_said)


def _items(paragraphs: list[_Paragraph], label: str, part: str, printed: bool,
           printed_said: set[str]) -> list[Hidden]:  # fmt: skip
    found: list[Hidden] = []
    for paragraph in paragraphs:
        if not (paragraph.pieces or paragraph.gone or paragraph.codes):
            continue
        where = _where(label, paragraph)
        text = "".join(piece for piece, _ in paragraph.pieces)
        spans = _spans(paragraph.pieces)
        items = [Hidden(kind, where, quoted(text[start:end]), how, part, runs=runs)
                 for start, end, kind, how, runs in spans]  # fmt: skip
        found += [Hidden(ZERO_WIDTH, where, quoted(spot.said), spot.why, part)
                  for spot in zero_width_in(text)]  # fmt: skip
        ends = [end for _start, end, *_rest in spans]
        for spot in to_a_model_in(text):
            # The first span ending after the words start, found by bisection: spans are
            # in order and apart, and a look through each was quadratic (round 1 of #574).
            inside = bisect_right(ends, spot.start)
            if inside < len(spans) and spans[inside][0] < spot.end:
                if not items[inside].model:
                    items[inside] = replace(items[inside], model=spot.rule)
                continue
            if printed:
                printed_said.add(quoted(spot.said).casefold())
            found.append(_model(spot, where, part, printed=printed))
        found += items
        found += _unprinted(" ".join(paragraph.gone), f"{where}: a tracked deletion", part)
        found += _unprinted(" ".join(paragraph.codes), f"{where}: a field's code", part)
    return found


def _model(spot: Spot, where: str, part: str, *, printed: bool) -> Hidden:
    return Hidden(TO_A_MODEL, where, quoted(spot.said), spot.why, part, printed=printed,
                  model=spot.rule)


def _unprinted(text: str, where: str, part: str) -> list[Hidden]:
    """What a text no reader of the document sees holds: zero-width characters inside
    words, and words to a model."""
    if not worth_reading(text):
        return []
    found = [Hidden(ZERO_WIDTH, where, quoted(spot.said), spot.why, part)
             for spot in zero_width_in(text)]  # fmt: skip
    return found + [_model(spot, where, part, printed=False) for spot in to_a_model_in(text)]


def _also_printed(item: Hidden, printed_said: set[str]) -> bool:
    """Whether words to a model found where a reader does not look are printed too."""
    return item.kind == TO_A_MODEL and not item.printed and item.text.casefold() in printed_said


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _place(part: str, tag: str, attribute: str | None) -> str:
    if attribute in _ATTRIBUTES:
        return _ATTRIBUTES[attribute]
    if tag == "docVar":
        return "a document variable"
    named = next((said for prefix, said in _PLACES if part.startswith(prefix)), None)
    if named is not None:
        return f"{named} ({attribute or tag})"
    return f"{part}, where the document's text is not ({attribute or tag})"


def _strings(root: ET.Element, part: str, story: bool) -> Iterator[tuple[str, str]]:
    """Each text and attribute value of a part, with what it is called, but the text a
    story's walker reads: its runs' text outside a fallback copy."""
    stack: list[tuple[ET.Element, bool]] = [(root, False)]
    while stack:
        element, in_fallback = stack.pop()
        tag = _local(element.tag)
        read_apart = story and not in_fallback and element.tag in (*_SHOWN, *_GONE, *_CODE)
        if not read_apart and element.text and worth_reading(element.text):
            where = "a copy Word keeps for older readers and does not show" if in_fallback else None
            yield element.text, where or _place(part, tag, None)
        for name, value in element.attrib.items():
            if worth_reading(value):
                yield value, _place(part, tag, _local(name))
        # What stands after an element inside its parent (round 1 of #574).
        if element.tail and worth_reading(element.tail):
            yield element.tail, _place(part, tag, None)
        inside = in_fallback or element.tag == _FALLBACK
        stack.extend((child, inside) for child in reversed(list(element)))


def _targets(archive, names: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    """The parts the main document names for its styles, theme and settings, by kind,
    where its relationships can be read, Word's usual names where they cannot; and the part
    each of its relationships names, by its identifier."""
    found = {"styles": "word/styles.xml", "theme": "word/theme/theme1.xml",
             "settings": "word/settings.xml"}  # fmt: skip
    links: dict[str, str] = {}
    main = "word/document.xml"
    try:
        if "_rels/.rels" in names:
            for link in read_part(archive, "_rels/.rels").iter(_RELATIONSHIPS):
                if (link.get("Type") or "").endswith("/officeDocument"):
                    main = posixpath.normpath((link.get("Target") or "").lstrip("/"))
                    break
        folder, name = posixpath.split(main)
        rels = posixpath.join(folder, "_rels", f"{name}.rels")
        if rels in names:
            for link in read_part(archive, rels).iter(_RELATIONSHIPS):
                kind = (link.get("Type") or "").rsplit("/", 1)[-1]
                target = (link.get("Target") or "").strip()
                if not target or link.get("TargetMode") == "External":
                    continue
                path = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                          else posixpath.join(folder, target))  # fmt: skip
                links[link.get("Id") or ""] = path
                if kind in found:
                    found[kind] = path
    except UnsafeDocument:
        pass
    return {**found, "main": main}, links


def _shown(main: ET.Element | None, links: dict[str, str], settings: ET.Element | None) -> _Shown:
    """The headers and footers the sections show, and the notes the text cites: a section's
    default header and footer, its first-page ones where it has a title page
    (`w:titlePg`), its even-page ones where the document has them (`w:evenAndOddHeaders`)."""
    if main is None:
        return _Shown()
    even = settings is not None and bool(on_off(settings.find(f"{W}evenAndOddHeaders")))
    parts: set[str] = set()
    for section in main.iter(f"{W}sectPr"):
        first = bool(on_off(section.find(f"{W}titlePg")))
        for reference in (*section.findall(f"{W}headerReference"),
                          *section.findall(f"{W}footerReference")):  # fmt: skip
            kind = reference.get(f"{W}type") or "default"
            shows = kind == "default" or (kind == "first" and first) or (kind == "even" and even)
            target = links.get(reference.get(_R_ID) or "")
            if shows and target:
                parts.add(target)
    notes = {(note, cite.get(f"{W}id", "")) for note, cited in _NOTES.items()
             for cite in main.iter(cited)}  # fmt: skip
    return _Shown(frozenset(parts), frozenset(notes))


def _optional(archive, name: str, names: set[str]) -> ET.Element | None:
    if name not in names:
        return None
    try:
        return read_part(archive, name)
    except UnsafeDocument:
        return None


def _page(main: ET.Element | None, settings: ET.Element | None, theme: Theme) -> _Page:
    background = None if main is None else main.find(f"{W}background")
    shown = settings is not None and bool(on_off(settings.find(f"{W}displayBackgroundShape")))
    if background is None or not shown:
        return _Page()
    colour = theme.colour(background.get(f"{W}themeColor"))
    colour = colour or hex_colour(background.get(f"{W}color"))
    if colour is None:
        return _Page()
    return _Page(((WHITE, "the page"), (colour, "the page's background")))


def read_hidden(path: Path) -> Reading:
    """What `path`, a Word document, holds that a person reading it does not see (see the
    module's docstring). Raises `UnsafeDocument` where it cannot be read as a Word document
    is, or where a part that holds its text cannot."""
    with open_archive(path) as archive:
        listed = Counter(info.filename for info in archive.infolist())
        twice = sorted(name for name, count in listed.items() if count > 1)
        if twice:
            raise UnsafeDocument(
                f"{path.name} holds two parts named {twice[0]}, and which of them Word shows "
                "is not known"
            )
        names = set(listed)
        targets, links = _targets(archive, names)
        settings = _optional(archive, targets["settings"], names)
        theme = Theme.read(_optional(archive, targets["theme"], names), settings)
        main = _optional(archive, targets["main"], names)
        look = _Look(Styles.read(_optional(archive, targets["styles"], names)), theme,
                     _page(main, settings, theme), _shown(main, links, settings))  # fmt: skip
        return _read_parts(path, archive, look)


def _size(count: int) -> str:
    return f"{count // 1024 // 1024} MB" if count >= 1024 * 1024 else f"{count} bytes"


def _read_parts(path: Path, archive, look: _Look) -> Reading:
    found: list[Hidden] = []
    unread: list[str] = []
    printed_said: set[str] = set()
    budget = READ_AT_MOST
    for info in archive.infolist():
        name = info.filename
        if not name.lower().endswith((".xml", ".rels")):
            continue
        story = bool(_STORY_NAME.fullmatch(name))
        if not story and info.file_size > budget:
            unread.append(f"{name}: past the {_size(READ_AT_MOST)} read of the parts that "
                          "hold no text")  # fmt: skip
            continue
        try:
            root = read_part(archive, name)
        except UnsafeDocument as exc:
            if story:
                raise
            unread.append(f"{name}: {exc}")
            continue
        if not story:
            budget -= info.file_size
        is_story = root.tag in _STORIES
        if is_story:
            found += _story(root, name, look, printed_said)
        for text, where in _strings(root, name, is_story):
            found += _unprinted(text, where, name)
    found = [replace(item, printed=True) if _also_printed(item, printed_said) else item
             for item in found]  # fmt: skip
    return Reading(path, tuple(found), tuple(unread))
