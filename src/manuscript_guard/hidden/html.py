"""What a page of HTML holds that a person reading it does not see (`read_page`): a stored
literature page, an e-mail's HTML, raw HTML in a Markdown file.

A page is read as a browser draws it from the styles each element carries (`style`, and the
old `color`, `bgcolor` and `hidden` attributes), and these are reported, each with its words:

- **background**: text too close in colour to what is behind it, a contrast ratio under 1.5,
  or nearly transparent (an opacity under 0.1), as for a Word document;
- **tiny**: text under 3 pt;
- **hidden**: text a page does not show, by `display: none`, `visibility: hidden`, the
  `hidden` attribute, a place far off the page, or a box of no size, reported only where it
  holds words to a model or zero-width characters (Basile, 2026-11-07): publishers hide
  their menus, dialogs and notices this way on nearly every page, and a warning on all of
  them would be read by nobody;
- **zero-width** and **to-a-model**, as `hidden.words` reads them, in the text, and in what
  a page holds and does not show: a comment, a script, a stylesheet, a template, an
  element's alternative text, title, label or data.

A stylesheet's rules, and so an element's class, are not read (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, replace
from html.parser import HTMLParser

from manuscript_guard.colour import RGB, contrast, hex_of, parse
from manuscript_guard.hidden.styles import WHITE
from manuscript_guard.hidden.word import (
    BACKGROUND,
    CONTRAST_BELOW,
    HIDDEN,
    TINY,
    TO_A_MODEL,
    ZERO_WIDTH,
    Hidden,
    quoted,
)
from manuscript_guard.hidden.words import to_a_model_in, worth_reading, zero_width_in
from manuscript_guard.safexml import UnsafeDocument

#: Text under this size, in points, is too small to read.
TINY_POINTS = 3.0
#: Text more transparent than this is not seen.
OPACITY_BELOW = 0.1
#: An element placed this far off the page, in pixels, is not seen.
OFF_PAGE = 500.0
#: The size of text where a page says none, in points.
_BASE_POINTS = 12.0
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "param", "source", "track", "wbr"})  # fmt: skip
#: Elements a browser starts on a line of their own: their text is parted from their
#: neighbours', and a stretch kept from sight does not run on past one.
_BLOCKS = frozenset({"address", "article", "aside", "blockquote", "body", "br", "caption",
                     "dd", "details", "dialog", "div", "dl", "dt", "fieldset", "figcaption",
                     "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
                     "head", "header", "hr", "html", "li", "main", "nav", "ol", "option",
                     "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot",
                     "th", "thead", "title", "tr", "ul"})  # fmt: skip
#: Elements whose text a page never shows, by what each is called.
_UNSHOWN = {"script": "a script", "style": "a stylesheet", "template": "a template"}
#: Attributes that hold words a page does not show, by what each is called.
_ATTRIBUTES = {"alt": "a picture's alternative text", "title": "an element's title",
               "aria-label": "a label read aloud", "content": "a meta element's content",
               "placeholder": "a field's placeholder", "value": "a field's value"}  # fmt: skip
#: A number as CSS writes one, with a digit before its point or not, and its unit.
_LENGTH = re.compile(r"(-?(?:[0-9]{1,7}(?:\.[0-9]{1,12})?|\.[0-9]{1,12}))"
                     r"\s*(px|pt|em|rem|%)?")  # fmt: skip
#: A colour inside a shorthand: written as a hexadecimal, a function or a word.
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|(?:rgb|hsl)a?\([^)]{0,80}\)|[a-zA-Z]+")
_NO_SIZE = re.compile(r"0(?:px|pt|em|rem|%)?")
_UNITS = {"px": 0.75, "pt": 1.0}


@dataclass(frozen=True)
class _Look:
    """How an element draws its text, as its parent's, changed by its own style."""

    hidden: str = ""
    unshown: str = ""
    colour: RGB | None = None
    opacity: float = 1.0
    #: None where a picture or a gradient is behind the text, whose colour is not known.
    behind: RGB | None = WHITE
    points: float = _BASE_POINTS


def _declarations(style: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for declaration in style.split(";"):
        name, colon, value = declaration.partition(":")
        if colon:
            found[name.strip().casefold()] = value.replace("!important", "").strip().casefold()
    return found


def _points(value: str, parent: float) -> float | None:
    """A font size in points, or None where it cannot be read."""
    length = _LENGTH.fullmatch(value.strip())
    if length is None:
        return None
    number, unit = float(length.group(1)), length.group(2) or "px"
    if unit in _UNITS:
        return number * _UNITS[unit]
    if unit == "rem":
        return number * _BASE_POINTS
    return number * parent * (0.01 if unit == "%" else 1.0)


def _pixels(value: str) -> float | None:
    length = _LENGTH.fullmatch(value.strip())
    if length is None or (length.group(2) or "px") not in _UNITS:
        return None
    return float(length.group(1)) / _UNITS[length.group(2) or "px"] * 0.75


def _hidden_by(style: dict[str, str], attributes: dict[str, str]) -> str:
    """How an element's style or attributes keep it from sight, or "" where they do not."""
    if "hidden" in attributes:
        return "hidden by its hidden attribute"
    if style.get("display") == "none":
        return "hidden by display: none"
    if style.get("visibility") in ("hidden", "collapse"):
        return "hidden by visibility: hidden"
    for name in ("left", "top", "text-indent", "margin-left", "margin-top"):
        far = _pixels(style.get(name, ""))
        if far is not None and far <= -OFF_PAGE:
            return f"placed off the page ({name}: {style[name]})"
    sized = any(_NO_SIZE.fullmatch(style.get(side, "")) for side in ("width", "height"))
    if sized and style.get("overflow") == "hidden":
        return "in a box of no size"
    if "rect(0" in style.get("clip", "").replace(" ", ""):
        return "cut out of sight (clip)"
    return ""


def _looked(parent: _Look, tag: str, attributes: dict[str, str]) -> _Look:
    style = _declarations(attributes.get("style") or "")
    look = parent
    if tag in _UNSHOWN and not look.unshown:
        look = replace(look, unshown=_UNSHOWN[tag])
    if not look.hidden and (how := _hidden_by(style, attributes)):
        look = replace(look, hidden=how)
    look = replace(look, behind=_behind(style, attributes, look.behind))
    coloured = parse(style.get("color") or attributes.get("color") or "")
    if coloured is not None:
        look = replace(look, colour=coloured[0], opacity=look.opacity * coloured[1])
    opacity = _LENGTH.fullmatch(style.get("opacity", "").strip())
    if opacity is not None and opacity.group(2) in (None, "%"):
        share = float(opacity.group(1)) / (100 if opacity.group(2) == "%" else 1)
        look = replace(look, opacity=look.opacity * min(1.0, max(0.0, share)))
    sized = style.get("font-size") or _font_size(style.get("font", ""))
    if sized and (points := _points(sized, look.points)) is not None:
        look = replace(look, points=points)
    return look


def _colour_in(value: str) -> tuple[RGB, float] | None:
    """The colour a background's value names, the shorthand's among its other words:
    `rgb(0, 0, 0)`, `black no-repeat`, `url(a.png) #000` (round 1 of #576: its first
    word alone was read)."""
    whole = parse(value)
    if whole is not None:
        return whole
    return next((found for word in _COLOUR.findall(value)
                 if (found := parse(word)) is not None), None)  # fmt: skip


def _behind(style: dict[str, str], attributes: dict[str, str], behind: RGB | None):
    """What is behind an element's text: its own background over its parent's, or None
    where a picture or a gradient is painted there, whose colours are not read."""
    painted = " ".join((style.get("background", ""), style.get("background-image", "")))
    if "url(" in painted or "gradient(" in painted:
        return None
    colour = _colour_in(style.get("background-color") or style.get("background")
                        or attributes.get("bgcolor") or "")  # fmt: skip
    if colour is None or colour[1] <= 0 or behind is None and colour[1] < 1:
        return behind
    rgb, alpha = colour
    under = behind or WHITE
    return tuple(c * alpha + b * (1 - alpha) for c, b in zip(rgb, under, strict=True))


def _font_size(font: str) -> str:
    """The size the `font` shorthand gives: its first length with a unit, before any
    line height (`2px/10px`)."""
    for word in font.split():
        size = word.split("/")[0]
        length = _LENGTH.fullmatch(size)
        if length is not None and (length.group(2) or size == "0"):
            return size
    return ""


def _kept_from_sight(look: _Look) -> tuple[str, str] | None:
    if look.hidden:
        return HIDDEN, look.hidden
    if look.opacity < OPACITY_BELOW:
        return BACKGROUND, f"nearly transparent (opacity {look.opacity:g})"
    if look.colour is not None and look.behind is not None:
        drawn = tuple(c * look.opacity + b * (1 - look.opacity)
                      for c, b in zip(look.colour, look.behind, strict=True))  # fmt: skip
        if contrast(drawn, look.behind) < CONTRAST_BELOW:  # type: ignore[arg-type]
            return BACKGROUND, f"{hex_of(drawn)} text on {hex_of(look.behind)}"  # type: ignore[arg-type]
    if look.points < TINY_POINTS:
        return TINY, f"{look.points:g} pt"
    return None


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, _Look]] = [("", _Look())]
        #: How many of each element are open, so that an end tag nothing opened is passed
        #: over at once (round 1 of #576: it looked through every open element).
        self.open: Counter[str] = Counter()
        self.pieces: list[tuple[str, tuple[str, str] | None]] = []
        self.lines: list[int] = []
        self.unshown: list[tuple[str, str, int]] = []
        #: The pieces that part one block from the next.
        self.breaks: list[int] = []

    def _parted(self, tag: str) -> None:
        if tag in _BLOCKS and (not self.breaks or self.breaks[-1] != len(self.pieces) - 1):
            self.breaks.append(len(self.pieces))
            self.pieces.append(("\n", None))
            self.lines.append(self.getpos()[0])

    def _attributes(self, tag: str, attrs) -> dict[str, str]:
        attributes = {name.casefold(): value or "" for name, value in attrs}
        line = self.getpos()[0]
        for name, value in attributes.items():
            label = _ATTRIBUTES.get(name) or ("an element's data" if name.startswith("data-")
                                              else None)  # fmt: skip
            if label and worth_reading(value):
                self.unshown.append((value, label, line))
        return attributes

    def handle_starttag(self, tag, attrs) -> None:
        tag = tag.casefold()
        self._parted(tag)
        look = _looked(self.stack[-1][1], tag, self._attributes(tag, attrs))
        if tag not in _VOID:
            self.stack.append((tag, look))
            self.open[tag] += 1

    def handle_startendtag(self, tag, attrs) -> None:
        self._parted(tag.casefold())
        self._attributes(tag.casefold(), attrs)

    def handle_endtag(self, tag) -> None:
        tag = tag.casefold()
        self._parted(tag)
        if not self.open[tag]:
            return
        while self.stack:
            closed, _look = self.stack.pop()
            self.open[closed] -= 1
            if closed == tag:
                return

    def handle_data(self, data) -> None:
        look = self.stack[-1][1]
        if look.unshown:
            self.unshown.append((data, look.unshown, self.getpos()[0]))
            return
        self.pieces.append((data, _kept_from_sight(look) if data.strip() else None))
        self.lines.append(self.getpos()[0])

    def handle_comment(self, data) -> None:
        self.unshown.append((data, "an HTML comment", self.getpos()[0]))


def read_page(text: str, part: str, label: str = "the page") -> list[Hidden]:
    """What `text`, a page of HTML or a Markdown file, holds that its reader does not see
    (see the module's docstring). `part` names it in what is found, and `label` says what
    it is: "the page", "the message"."""
    reader = _Reader()
    try:
        reader.feed(text)
        reader.close()
    except AssertionError as exc:
        # Python's parser, before 3.13, asserts on a marked section it does not know,
        # `<![x[` (round 1 of #576).
        raise UnsafeDocument(f"{part}: the page cannot be parsed ({exc})") from exc
    found = _shown_text(reader, part, label)
    for words, called, line in reader.unshown:
        where = f"{label}, line {line}: {called}"
        found += [Hidden(ZERO_WIDTH, where, quoted(spot.said), spot.why, part)
                  for spot in zero_width_in(words)]  # fmt: skip
        found += [Hidden(TO_A_MODEL, where, quoted(spot.said), spot.why, part, model=spot.rule)
                  for spot in to_a_model_in(words)]  # fmt: skip
    return found


def _spans(pieces, breaks: list[int]) -> list[tuple[int, int, str, str, int]]:
    """Each stretch of text kept from sight alike: start, end, kind, how and the first
    piece, two pieces kept alike with only spaces between them and in one block one
    stretch."""
    text_at, spans, block, blocks = 0, [], 0, set(breaks)
    text = "".join(piece for piece, _ in pieces)
    started: list[int] = []
    for number, (piece, kept) in enumerate(pieces):
        block += number in blocks
        end = text_at + len(piece)
        if kept is not None:
            last = spans[-1] if spans else None
            if (last and (last[2], last[3]) == kept and started[-1] == block
                    and not text[last[1] : text_at].strip()):
                spans[-1] = (last[0], end, *kept, last[4])
            else:
                spans.append((text_at, end, *kept, number))
                started.append(block)
        text_at = end
    return spans


def worth_saying(kind: str, holds_words: bool) -> bool:
    """Whether a stretch a page keeps from sight is said: text too faint or too small
    always; text the page's layout hides only where it holds words to a model or zero-width
    characters (Basile, 2026-11-07)."""
    return kind != HIDDEN or holds_words


def _shown_text(reader: _Reader, part: str, label: str) -> list[Hidden]:
    text = "".join(piece for piece, _ in reader.pieces)
    spans = _spans(reader.pieces, reader.breaks)
    ends = [end for _start, end, *_rest in spans]
    starts, at = [], 0
    for piece, _kept in reader.pieces:
        starts.append(at)
        at += len(piece)

    def line_of(offset: int) -> int:
        return reader.lines[max(0, bisect_right(starts, offset) - 1)]

    def span_of(spot) -> int | None:
        inside = bisect_right(ends, spot.start)
        return inside if inside < len(spans) and spans[inside][0] < spot.end else None

    models: dict[int, str] = {}
    found: list[Hidden] = []
    for spot in to_a_model_in(text):
        inside = span_of(spot)
        if inside is not None:
            models.setdefault(inside, spot.rule)
        else:
            found.append(Hidden(TO_A_MODEL, f"{label}, line {line_of(spot.start)}",
                                quoted(spot.said), spot.why, part, printed=True,
                                model=spot.rule))  # fmt: skip
    zero = zero_width_in(text)
    zero_inside = {span_of(spot) for spot in zero} - {None}
    for spot in zero:
        found.append(Hidden(ZERO_WIDTH, f"{label}, line {line_of(spot.start)}",
                            quoted(spot.said), spot.why, part))  # fmt: skip
    for number, (start, end, kind, how, first) in enumerate(spans):
        if not worth_saying(kind, number in models or number in zero_inside):
            continue
        found.append(Hidden(kind, f"{label}, line {reader.lines[first]}", quoted(text[start:end]),
                            how, part, model=models.get(number, "")))  # fmt: skip
    return found
