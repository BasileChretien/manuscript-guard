"""What a page of HTML holds that a person reading it does not see (`read_page`): a stored
literature page, an e-mail's HTML, raw HTML in a Markdown file.

A page is read as a browser draws it from the styles each element carries (`style`, and the
old `color`, `bgcolor` and `hidden` attributes), and these are reported, each with its words:

- **background**: text too close in colour to what is behind it, a contrast ratio under 1.5,
  or nearly transparent (an opacity under 0.1, `transparent`), as for a Word document;
- **tiny**: text under 3 pt;
- **hidden**: text a page does not show, by `display: none`, `visibility: hidden`, the
  `hidden` attribute, a place far off the page, or a box of no size, reported only where it
  holds words to a model or zero-width characters (Basile, 2026-11-07): publishers hide
  their menus, dialogs and notices this way on nearly every page, and a warning on all of
  them would be read by nobody;
- **zero-width** and **to-a-model**, as `hidden.words` reads them, in the text, and in what
  a page holds and does not show: a comment, a script, a stylesheet, a template, a
  declaration or a processing instruction, an element's alternative text, title, label or
  data.

The page is read by a scanner of this module's own, in one pass and in time linear in its
length (the security review of #576: Python's own parser took minutes over 30 KB of broken
markup). It reads the markup as written, not as a browser repairs it. A stylesheet's rules,
and so an element's class, are not read (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import html
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, replace

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

#: Text under this size, in points, is too small to read.
TINY_POINTS = 3.0
#: Text more transparent than this is not seen.
OPACITY_BELOW = 0.1
#: An element placed this far off the page, in pixels, is not seen.
OFF_PAGE = 500.0
#: The size of text where a page says none, in points, and the pixels of an em of it.
_BASE_POINTS = 12.0
_EM_PIXELS = 16.0
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
#: Elements whose text runs to their end tag, markup inside it read as text.
_RAW = ("script", "style")
#: Attributes that hold words a page does not show, by what each is called.
_ATTRIBUTES = {"alt": "a picture's alternative text", "title": "an element's title",
               "aria-label": "a label read aloud", "aria-description": "a label read aloud",
               "content": "a meta element's content", "placeholder": "a field's placeholder",
               "value": "a field's value", "label": "an option's label",
               "srcdoc": "a frame's page", "href": "a link's address"}  # fmt: skip
#: A number as CSS writes one, with a digit before its point or not, and its unit.
_LENGTH = re.compile(r"([+-]?(?:[0-9]{1,7}(?:\.[0-9]{1,30})?|\.[0-9]{1,30})"
                     r"(?:[eE][+-]?[0-9]{1,3})?)\s*(px|pt|em|rem|%|mm|cm|in|pc|q)?")  # fmt: skip
#: A function of CSS that names no colour itself, `var(--gray-100)`, whose words are
#: not colours (round 2 of #576).
_OTHER_FUNCTION = re.compile(r"\b(?!(?:rgb|hsl)a?\()[a-zA-Z][a-zA-Z0-9-]*\([^)]{0,200}\)")
#: A colour inside a shorthand: written as a hexadecimal, a function or a word.
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|(?:rgb|hsl)a?\([^)]{0,80}\)|[a-zA-Z]+")
_NO_SIZE = re.compile(r"0(?:px|pt|em|rem|%)?")
#: Points in a unit of length; an em and a rem are read against the size they stand on.
_POINTS = {"px": 0.75, "pt": 1.0, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0, "pc": 12.0,
           "q": 18 / 25.4}  # fmt: skip
#: The properties whose value a browser drops where it cannot read it, and how each is
#: read: a declaration of one written to slip past an earlier one is passed over.
_COLOURED = ("color", "-webkit-text-fill-color")
_SPACE = " \t\n\r\f"


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


def _without_comments(style: str) -> str:
    """`style` with each CSS comment taken out, in one pass."""
    out, at = [], 0
    while (opened := style.find("/*", at)) >= 0:
        out.append(style[at:opened])
        closed = style.find("*/", opened + 2)
        at = len(style) if closed < 0 else closed + 2
    return "".join(out) + style[at:]


def _colour_of(value: str) -> tuple[RGB, float] | None:
    return ((0.0, 0.0, 0.0), 0.0) if value == "transparent" else parse(value)


def _readable(name: str, value: str) -> bool:
    """Whether a browser keeps the declaration: a colour, a size and an opacity it can
    read; any other property as it is."""
    if name in _COLOURED:
        return _colour_of(value) is not None
    if name == "font-size":
        return _points(value, _BASE_POINTS) is not None
    if name == "opacity":
        found = _LENGTH.fullmatch(value)
        return found is not None and found.group(2) in (None, "%")
    return True


def _declarations(style: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for declaration in _without_comments(style).split(";"):
        name, colon, value = declaration.partition(":")
        name = name.strip().casefold()
        value = value.replace("!important", "").strip().casefold()
        if colon and _readable(name, value):
            found.pop(name, None)  # placed last, as the declaration that now wins
            found[name] = value
    return found


def _points(value: str, parent: float) -> float | None:
    """A font size in points, or None where it cannot be read."""
    length = _LENGTH.fullmatch(value.strip())
    if length is None:
        return None
    number, unit = float(length.group(1)), length.group(2) or "px"
    if unit in _POINTS:
        return number * _POINTS[unit]
    if unit == "rem":
        return number * _BASE_POINTS
    return number * parent * (0.01 if unit == "%" else 1.0)


def _pixels(value: str) -> float | None:
    length = _LENGTH.fullmatch(value.strip())
    if length is None or length.group(2) == "%":
        return None
    unit = length.group(2) or "px"
    if unit in ("em", "rem"):
        return float(length.group(1)) * _EM_PIXELS
    return float(length.group(1)) * _POINTS[unit] / 0.75


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
    coloured = _colour_of(_later(style, *_COLOURED) or attributes.get("color") or "")
    if coloured is not None:
        look = replace(look, colour=coloured[0], opacity=look.opacity * coloured[1])
    opacity = _LENGTH.fullmatch(style.get("opacity", "").strip())
    if opacity is not None and opacity.group(2) in (None, "%"):
        share = float(opacity.group(1)) / (100 if opacity.group(2) == "%" else 1)
        look = replace(look, opacity=look.opacity * min(1.0, max(0.0, share)))
    later = _later(style, "font", "font-size")
    sized = _font_size(later) if later == style.get("font") else later
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
    return next((found for word in _COLOUR.findall(_OTHER_FUNCTION.sub(" ", value))
                 if (found := parse(word)) is not None), None)  # fmt: skip


def _behind(style: dict[str, str], attributes: dict[str, str], behind: RGB | None):
    """What is behind an element's text: its own background over its parent's, or None
    where a picture or a gradient is painted there, whose colours are not read."""
    painted = " ".join((style.get("background", ""), style.get("background-image", "")))
    if "url(" in painted or "gradient(" in painted:
        return None
    colour = _colour_in(_later(style, "background-color", "background")
                        or attributes.get("bgcolor") or "")  # fmt: skip
    if colour is None or colour[1] <= 0 or behind is None and colour[1] < 1:
        return behind
    rgb, alpha = colour
    under = behind or WHITE
    return tuple(c * alpha + b * (1 - alpha) for c, b in zip(rgb, under, strict=True))


def _later(style: dict[str, str], *names: str) -> str:
    """The value of whichever of the properties a style declares last, as the later
    declaration wins in CSS (round 2 of #576), or "" where it declares none."""
    named = [name for name in style if name in names]
    return style[named[-1]] if named else ""


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


@dataclass
class _Reader:
    """A page read once from start to end, each character looked at a bounded number of
    times: what it shows and how, piece by piece, and what it holds and does not show."""

    stack: list[tuple[str, _Look]]
    #: How many of each element are open, so that an end tag nothing opened is passed over
    #: at once (round 1 of #576: it looked through every open element).
    open: Counter[str]
    pieces: list[tuple[str, tuple[str, str] | None]]
    lines: list[int]
    #: Text the page does not show: as written, as read for words, what it is, its line.
    unshown: list[tuple[str, str, str, int]]
    #: The pieces that part one block from the next.
    breaks: list[int]
    text: str = ""
    line: int = 1
    counted: int = 0

    @classmethod
    def of(cls, text: str) -> _Reader:
        reader = cls([("", _Look())], Counter(), [], [], [], [], text)
        reader._read()
        return reader

    def _line_at(self, at: int) -> int:
        self.line += self.text.count("\n", self.counted, at)
        self.counted = at
        return self.line

    def _read(self) -> None:
        text, at = self.text, 0
        while at < len(text):
            opened = text.find("<", at)
            if opened < 0:
                self._data(at, len(text))
                return
            if opened > at:
                self._data(at, opened)
            at = self._markup(opened)

    def _data(self, start: int, end: int, *, raw: bool = False) -> None:
        line = self._line_at(start)
        # A script's or a stylesheet's text holds no character reference, as a browser
        # reads it, and is decoded only for its words (the review of 1d5327d).
        data = self.text[start:end] if raw else html.unescape(self.text[start:end])
        look = self.stack[-1][1]
        if look.unshown:
            self.unshown.append((data, html.unescape(data) if raw else data, look.unshown,
                                 line))  # fmt: skip
            return
        self.pieces.append((data, _kept_from_sight(look) if data.strip() else None))
        self.lines.append(line)

    def _to(self, opened: int, ending: str, skip: int, called: str) -> int:
        """Markup that runs to `ending`, its words read as what the page does not show."""
        closed = self.text.find(ending, opened + skip)
        if ending == "-->":  # a browser ends a comment at `--!>` too
            bang = self.text.find("--!>", opened + skip, len(self.text) if closed < 0 else closed)
            if bang >= 0:
                closed, ending = bang, "--!>"
        stop = len(self.text) if closed < 0 else closed
        written = self.text[opened + skip : stop]  # a comment's references as written
        self.unshown.append((written, html.unescape(written), called, self._line_at(opened)))
        return len(self.text) if closed < 0 else closed + len(ending)

    def _markup(self, opened: int) -> int:
        text = self.text
        following = text[opened + 1 : opened + 2]
        for empty in ("<!-->", "<!--->"):
            if text.startswith(empty, opened):  # a comment a browser ends at once
                return opened + len(empty)
        if text.startswith("<!--", opened):
            return self._to(opened, "-->", 4, "an HTML comment")
        if text.startswith("<![CDATA[", opened):
            # Outside an SVG or a formula, a browser ends it at its first `>`.
            return self._to(opened, ">", 9, "a CDATA section")
        if following in ("!", "?"):
            called = "a declaration" if following == "!" else "a processing instruction"
            return self._to(opened, ">", 2, called)
        if following == "/":
            name, _attributes, stop, _closing = _tag(text, opened)
            self._line_at(opened)
            self._ended(name)
            return stop
        if not (following.isascii() and following.isalpha()):  # as a browser opens a tag
            self._data(opened, opened + 1)
            return opened + 1
        name, attributes, stop, closing = _tag(text, opened)
        self._started(name, attributes, closing, self._line_at(opened))
        if name in _RAW and not closing:
            return self._raw(name, stop)
        return stop

    def _raw(self, name: str, start: int) -> int:
        """A script's or a stylesheet's text, to its end tag, read as text."""
        # Ended as a browser ends it, at `</script` and a space, a slash or `>`, and the
        # end tag read to its own end (the review of 1d5327d).
        ending = re.compile(rf"</{name}(?=[{_SPACE}/>])", re.IGNORECASE)
        found = ending.search(self.text, start)
        stop = len(self.text) if found is None else found.start()
        if stop > start:
            self._data(start, stop, raw=True)
        self._ended(name)
        return len(self.text) if found is None else _tag(self.text, found.start())[2]

    def _started(self, tag: str, attributes: dict[str, str], closing: bool, line: int) -> None:
        self._parted(tag, line)
        for name, value in attributes.items():
            label = _ATTRIBUTES.get(name) or ("an element's data" if name.startswith("data-")
                                              else None)  # fmt: skip
            if label and worth_reading(value):
                self.unshown.append((value, value, label, line))
        if closing or tag in _VOID:
            return
        self.stack.append((tag, _looked(self.stack[-1][1], tag, attributes)))
        self.open[tag] += 1

    def _ended(self, tag: str) -> None:
        self._parted(tag, self.line)
        if not self.open[tag]:
            return
        while self.stack:
            closed, _look = self.stack.pop()
            self.open[closed] -= 1
            if closed == tag:
                return

    def _parted(self, tag: str, line: int) -> None:
        if tag in _BLOCKS and (not self.breaks or self.breaks[-1] != len(self.pieces) - 1):
            self.breaks.append(len(self.pieces))
            self.pieces.append(("\n", None))
            self.lines.append(line)


def _tag(text: str, opened: int) -> tuple[str, dict[str, str], int, bool]:
    """The tag that opens at `opened`, `<` or `</`: its name, its attributes (the first of
    each name, as a browser keeps it), where it ends and whether it closes itself. Each
    character is read once: an unclosed quote takes the rest of the page as its value."""
    at = opened + 1 + (text[opened + 1 : opened + 2] == "/")
    start = at
    while at < len(text) and text[at] not in _SPACE + "/>":
        at += 1
    name, attributes, closing = text[start:at].casefold(), {}, False
    while at < len(text):
        character = text[at]
        if character in _SPACE:
            at += 1
            continue
        if character == ">":
            return name, attributes, at + 1, closing
        if character == "/":
            at += 1
            closing = text[at : at + 1] == ">"
            continue
        start = at
        while at < len(text) and text[at] not in _SPACE + "/>=":
            at += 1
        key = text[start:at].casefold()
        while at < len(text) and text[at] in _SPACE:
            at += 1
        value = ""
        if text[at : at + 1] == "=":
            at += 1
            while at < len(text) and text[at] in _SPACE:
                at += 1
            if text[at : at + 1] in ("\"", "'"):
                closed = text.find(text[at], at + 1)
                stop = len(text) if closed < 0 else closed
                value, at = text[at + 1 : stop], stop + 1
            else:
                start = at
                while at < len(text) and text[at] not in _SPACE + ">":
                    at += 1
                value = text[start:at]
        if key:
            attributes.setdefault(key, html.unescape(value))
        elif at == start:
            at += 1  # nothing a name is made of: step past it
    return name, attributes, len(text), closing


def read_page(text: str, part: str, label: str = "the page") -> list[Hidden]:
    """What `text`, a page of HTML or a Markdown file, holds that its reader does not see
    (see the module's docstring). `part` names it in what is found, and `label` says what
    it is: "the page", "the message"."""
    reader = _Reader.of(text)
    found = _shown_text(reader, part, label)
    for written, words, called, line in reader.unshown:
        where = f"{label}, line {line}: {called}"
        found += [Hidden(ZERO_WIDTH, where, quoted(spot.said), spot.why, part)
                  for spot in zero_width_in(written)]  # fmt: skip
        found += [Hidden(TO_A_MODEL, where, quoted(spot.said), spot.why, part, model=spot.rule)
                  for spot in to_a_model_in(words)]  # fmt: skip
    return found


def _spans(pieces, breaks: list[int]) -> list[tuple[int, int, str, str, int, int]]:
    """Each stretch of text kept from sight alike: start, end, kind, how, its first piece
    and its last, two pieces kept alike with only spaces between them and in one block one
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
                spans[-1] = (last[0], end, *kept, last[4], number)
            else:
                spans.append((text_at, end, *kept, number, number))
                started.append(block)
        text_at = end
    return spans


def worth_saying(kind: str, holds_words: bool) -> bool:
    """Whether a stretch a page keeps from sight is said: text too faint or too small
    always; text the page's layout hides only where it holds words to a model or zero-width
    characters (Basile, 2026-11-07)."""
    return kind != HIDDEN or holds_words


def _own_words(pieces, first: int, last: int) -> tuple[str, bool]:
    """The rule words to a model inside a stretch's own pieces match, each read alone, and
    whether one holds a zero-width character: a hidden piece against a shown word, with no
    space between, met no word boundary in the page's text (the security review of #576)."""
    rule, zero = "", False
    for piece, _kept in pieces[first : last + 1]:
        spots = to_a_model_in(piece)
        rule = rule or (spots[0].rule if spots else "")
        zero = zero or bool(zero_width_in(piece))
    return rule, zero


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
    for number, (start, end, kind, how, first, last) in enumerate(spans):
        rule, own_zero = _own_words(reader.pieces, first, last)
        model = models.get(number) or rule
        if not worth_saying(kind, bool(model) or number in zero_inside or own_zero):
            continue
        found.append(Hidden(kind, f"{label}, line {reader.lines[first]}", quoted(text[start:end]),
                            how, part, model=model))  # fmt: skip
    return found
