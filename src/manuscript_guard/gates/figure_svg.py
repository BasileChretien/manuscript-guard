"""The text and the lines of an SVG figure, at the size the figure prints.

A journal states the smallest text and the thinnest line it prints, in points at the
printed size. A vector figure is scaled to the width it prints at, and everything in it
with it: text drawn at 8 units in a figure 468 units wide, printed 89 mm wide, prints at
about 4.3 pt. So each text's size and each line's width is read from the SVG and carried
to the printed page:

* a size or a width is the one set on the element, by its `style` or as an attribute, or
  inherited from the elements around it; a text's size where none is set is SVG's default
  of 16 units, and a size in `pt`, `mm` or `em` is turned into units as SVG does;
* it is multiplied by every `transform` around it, `scale` and `matrix` among them, and
  by the printed width over the width of the figure's `viewBox`;
* a `<tspan>` is a text of its own, which is how small sub- and superscripts are drawn;
* an element drawn through `<use>` is read where it is used, and nothing in `<defs>` is
  read where it is defined.

Each colour it paints is read too, for the colour check (`gates/figure_colours.py`): a
shape's fill and a line's stroke, as the element, its stylesheet or the elements around it
set them, `currentColor` the `color` it inherits, laid over white at the opacity it is drawn
at, its own and its groups'. A text's colour is kept apart, since text rarely tells one
series from another. A gradient or a pattern is not read.

A text whose anchor is outside the visible area, the `viewBox`, is cut off where it prints.
A `<style>` element's rules are read as far as `gates/svg_style.py` says: a stroke svglite
sets once for every line, and a size Illustrator sets through a class.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.colour import Paint, hex_of, over_white, parse
from manuscript_guard.gates.svg_style import READ, Sheet, declarations

SVG = "{http://www.w3.org/2000/svg}"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
#: Points in an inch, and SVG's units (CSS pixels) in one.
PT_PER_INCH = 72.0
UNITS_PER_INCH = 96.0
#: The size of a text that sets none: CSS's `medium`.
DEFAULT_FONT_UNITS = 16.0
#: How far, in units, a text may be anchored outside the visible area and still be read as
#: inside it: a rounding of the coordinates.
EDGE = 0.5
#: How deep `<use>` may refer to `<use>`; a figure that goes deeper refers to itself.
DEPTH = 16

#: A length and its unit, as SVG and CSS write one.
_LENGTH = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)\s*$")
#: How many units each absolute unit is.
_UNITS = {
    "": 1.0, "px": 1.0, "pt": UNITS_PER_INCH / PT_PER_INCH, "pc": 16.0,
    "in": UNITS_PER_INCH, "mm": UNITS_PER_INCH / 25.4, "cm": UNITS_PER_INCH / 2.54,
    "q": UNITS_PER_INCH / 101.6,
}  # fmt: skip
#: CSS's sizes by name, in units.
_NAMED = {
    "xx-small": 9.0, "x-small": 10.0, "small": 13.0, "medium": 16.0, "large": 18.0,
    "x-large": 24.0, "xx-large": 32.0, "xxx-large": 48.0,
}  # fmt: skip
#: The size in the `font` shorthand: the first length with a unit, or a size's name. A
#: number without one is a weight, "700" for bold, as matplotlib writes it before the size
#: (round 1 of #302).
_FONT_SIZE = re.compile(
    r"(?:^|\s)((?:\d+\.?\d*|\.\d+)(?:px|pt|pc|in|mm|cm|q|em|ex|rem|%)|"
    r"xx-small|x-small|small|medium|large|x-large|xx-large|xxx-large|smaller|larger)"
    r"(?:/\S+)?\s",
    re.IGNORECASE,
)
_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
#: The elements that draw a line where they have a stroke.
_STROKED = {"path", "line", "polyline", "polygon", "rect", "circle", "ellipse"}
#: The elements that fill where they have a fill: a line has no inside.
_FILLED = _STROKED - {"line"}
#: The elements whose content is drawn only where something refers to it.
_NOT_DRAWN = {"defs", "clipPath", "mask", "marker", "pattern", "symbol", "metadata",
              "title", "desc", "style", "linearGradient", "radialGradient", "filter"}  # fmt: skip

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class Mark:
    """A text or a line, with its size in units at the figure's own scale."""

    text: str  # the text, or "" for a line
    units: float  # its font size or stroke width, through every transform
    at: tuple[float, float]  # where a text is anchored, in the root's units


@dataclass(frozen=True)
class Svg:
    """What an SVG figure draws, and how wide it is."""

    texts: tuple[Mark, ...]
    lines: tuple[Mark, ...]
    #: The visible area, (x, y, width, height) in the root's units, where it can be read.
    view: tuple[float, float, float, float] | None
    #: The figure's own width in points, where its `width` says one, and whether that
    #: width carried a unit.
    width_pt: float | None
    width_unit: bool
    #: Each colour a shape, a line or a text is painted in, once each, in the order drawn.
    paints: tuple[Paint, ...] = ()


def read_svg(path: Path) -> Svg | None:
    """The texts and lines of an SVG figure; None where it does not parse."""
    return parse_svg(path.read_text(encoding="utf-8", errors="replace"))


def parse_svg(document: str) -> Svg | None:
    """The texts and lines of an SVG figure's text; None where it does not parse."""
    try:
        root = ET.fromstring(document)
    except ET.ParseError:
        return None
    figure = _Figure({node.get("id"): node for node in root.iter() if node.get("id")},
                     Sheet(root), [])  # fmt: skip
    texts: list[Mark] = []
    lines: list[Mark] = []
    _walk(root, IDENTITY, {**START, "font": DEFAULT_FONT_UNITS}, figure, texts, lines, 0)
    width, unit = _root_width(root)
    paints = tuple(dict.fromkeys(figure.paints))
    return Svg(tuple(texts), tuple(lines), _view(root), width, unit, paints)


def _tag(node: ET.Element) -> str:
    return node.tag.removeprefix(SVG) if isinstance(node.tag, str) else ""


@dataclass(frozen=True)
class _Figure:
    """What every element of a figure is read against: the elements by id, for `<use>`,
    and the figure's stylesheet."""

    ids: dict
    sheet: Sheet
    #: Each colour painted, in the order drawn, as the walk finds it.
    paints: list


#: What the root is drawn with: SVG's initial values, a fill of black and no stroke, and a
#: text's size `DEFAULT_FONT_UNITS`, which `parse_svg` reads when it starts.
START = {
    "stroke": "none", "stroke-width": 1.0, "fill": "black", "color": "black",
    "fill-opacity": 1.0, "stroke-opacity": 1.0, "opacity": 1.0, "text": False,
    "hidden": False,
}  # fmt: skip


def _style(node: ET.Element, sheet: Sheet) -> dict[str, str]:
    """What an element is drawn with: its presentation attributes, the stylesheet's rules
    over them, and its own `style` over those."""
    said = {key: value for key, value in node.attrib.items() if key in READ}
    said.update(sheet.declared(node))
    said.update(declarations(node.get("style") or ""))
    return said


def _length(value: str, relative_to: float) -> float | None:
    """A length in units: absolute units turned into units, `em` and `%` taken of
    `relative_to`; None where it is not one."""
    value = value.strip()
    named = _NAMED.get(value.lower())
    if named is not None:
        return named
    if value.lower() == "smaller":
        return relative_to / 1.2
    if value.lower() == "larger":
        return relative_to * 1.2
    match = _LENGTH.match(value)
    if match is None:
        return None
    number, unit = float(match.group(1)), match.group(2).lower()
    if unit in ("em", "rem"):
        return number * relative_to
    if unit == "ex":
        return number * relative_to / 2
    if unit == "%":
        return number * relative_to / 100
    scale = _UNITS.get(unit)
    return None if scale is None else number * scale


def _font_size(said: dict[str, str], inherited: float) -> float:
    size = said.get("font-size")
    if size is None and "font" in said:
        match = _FONT_SIZE.search(said["font"] + " ")
        size = match.group(1) if match else None
    if size is None:
        return inherited
    found = _length(size, inherited)
    return inherited if found is None or found < 0 else found


def _multiply(left: Matrix, right: Matrix) -> Matrix:
    a, b, c, d, e, f = left
    g, h, i, j, k, m = right
    return (a * g + c * h, b * g + d * h, a * i + c * j, b * i + d * j,
            a * k + c * m + e, b * k + d * m + f)  # fmt: skip


def _transform(text: str | None) -> Matrix:
    """What a `transform` attribute does, its functions applied right to left."""
    matrix = IDENTITY
    for name, arguments in _TRANSFORM.findall(text or ""):
        n = [float(x) for x in _NUMBER.findall(arguments)]
        own = IDENTITY
        if name == "matrix" and len(n) == 6:
            own = (n[0], n[1], n[2], n[3], n[4], n[5])
        elif name == "translate" and n:
            own = (1.0, 0.0, 0.0, 1.0, n[0], n[1] if len(n) > 1 else 0.0)
        elif name == "scale" and n:
            own = (n[0], 0.0, 0.0, n[1] if len(n) > 1 else n[0], 0.0, 0.0)
        elif name == "rotate" and n:
            angle = math.radians(n[0])
            cos, sin = math.cos(angle), math.sin(angle)
            own = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(n) == 3:
                about = (1.0, 0.0, 0.0, 1.0, n[1], n[2])
                own = _multiply(_multiply(about, own), (1.0, 0.0, 0.0, 1.0, -n[1], -n[2]))
        elif name == "skewX" and n:
            own = (1.0, 0.0, math.tan(math.radians(n[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and n:
            own = (1.0, math.tan(math.radians(n[0])), 0.0, 1.0, 0.0, 0.0)
        matrix = _multiply(matrix, own)
    return matrix


def _first(value: str | None) -> float:
    numbers = _NUMBER.findall(value or "")
    return float(numbers[0]) if numbers else 0.0


def _walk(
    node: ET.Element,
    matrix: Matrix,
    state: dict,
    figure: _Figure,
    texts: list[Mark],
    lines: list[Mark],
    depth: int,
) -> None:
    tag = _tag(node)
    if tag in _NOT_DRAWN:
        return
    said = _style(node, figure.sheet)
    if said.get("display", "").lower() == "none":
        return
    matrix = _multiply(matrix, _transform(node.get("transform")))
    state = _inherit(state, said, node.get("id"))
    if tag == "use":
        _use(node, matrix, state, figure, texts, lines, depth)
        return
    if tag in ("text", "tspan"):
        # A `<tspan>` without its own position is drawn on from its text's.
        x = _first(node.get("x")) if node.get("x") is not None else state.get("x", 0.0)
        y = _first(node.get("y")) if node.get("y") is not None else state.get("y", 0.0)
        state = {**state, "x": x, "y": y}
        if node.text and node.text.strip():
            height = _height(matrix) * state["font"]
            texts.append(Mark(node.text.strip(), height, _apply(matrix, x, y)))
            _paint(figure, state, "fill", text=True)
    if tag in _FILLED:
        _paint(figure, state, "fill", text=False)
    if tag in _STROKED and state["stroke"] not in ("none", "transparent", ""):
        width = state["stroke-width"] * _widened(matrix)
        if width > 0:
            lines.append(Mark("", width, _apply(matrix, 0.0, 0.0)))
            _paint(figure, state, "stroke", text=False)
    for child in node:
        _walk(child, matrix, state, figure, texts, lines, depth)


def _own(said: dict[str, str], key: str, state: dict) -> str:
    """An element's own colour, else its parent's; `inherit` says the parent's too."""
    value = said.get(key, "inherit").strip().lower()
    return state[key] if value == "inherit" else value


#: The group matplotlib draws a text's glyphs in, and the glyph Cairo draws one through.
_GLYPHS = re.compile(r"text_\d+|glyph\d")


def _drawn_text(node_id: str | None) -> bool:
    return node_id is not None and _GLYPHS.match(node_id) is not None


def _inherit(state: dict, said: dict[str, str], node_id: str | None = None) -> dict:
    """What an element draws with: its own size, stroke, width and colours, else its
    parent's. Its `opacity` is not inherited and lays the whole element over what is under
    it, so it is multiplied into its groups'."""
    width = _length(said["stroke-width"], state["font"]) if "stroke-width" in said else None
    return {
        **state,
        "font": _font_size(said, state["font"]),
        "stroke": said.get("stroke", state["stroke"]).strip().lower(),
        "stroke-width": state["stroke-width"] if width is None else width,
        "fill": _own(said, "fill", state),
        "color": _own(said, "color", state),
        # A text drawn as glyphs, as matplotlib draws one by default and Cairo always.
        "text": state["text"] or _drawn_text(node_id),
        "fill-opacity": _opacity(said.get("fill-opacity"), state["fill-opacity"]),
        "stroke-opacity": _opacity(said.get("stroke-opacity"), state["stroke-opacity"]),
        "opacity": state["opacity"] * _opacity(said.get("opacity"), 1.0),
        # `visibility` is inherited, and a child may show itself in a hidden group.
        "hidden": _own(said, "visibility", {"visibility": "hidden" if state["hidden"]
                                            else "visible"}) in ("hidden", "collapse"),
    }


def _opacity(value: str | None, otherwise: float) -> float:
    """An opacity as SVG writes one, a number or a percentage, kept from 0 to 1."""
    if value is None:
        return otherwise
    match = _LENGTH.match(value)
    if match is None or match.group(2) not in ("", "%"):
        return otherwise
    number = float(match.group(1)) / (100 if match.group(2) == "%" else 1)
    return min(1.0, max(0.0, number))


def _paint(figure: _Figure, state: dict, which: str, *, text: bool) -> None:
    """The colour `which`, the fill or the stroke, paints, where it paints one."""
    if state["hidden"]:
        return
    written = state[which]
    found = parse(state["color"] if written == "currentcolor" else written)
    if found is None:
        return
    rgb, alpha = found
    seen = alpha * state[f"{which}-opacity"] * state["opacity"]
    if seen > 0:
        figure.paints.append(Paint(hex_of(over_white(rgb, seen)), text or state["text"]))


def _use(
    node: ET.Element,
    matrix: Matrix,
    state: dict,
    figure: _Figure,
    texts: list[Mark],
    lines: list[Mark],
    depth: int,
) -> None:
    """What a `<use>` draws: what it refers to, moved to its x and y, with its style."""
    href = (node.get(XLINK_HREF) or node.get("href") or "").removeprefix("#")
    used = figure.ids.get(href)
    if used is None or depth >= DEPTH:
        return
    state = {**state, "text": state["text"] or _drawn_text(href)}
    placed = _multiply(matrix, (1.0, 0.0, 0.0, 1.0, _first(node.get("x")), _first(node.get("y"))))
    # A `<symbol>` is drawn where it is used, though not where it is defined.
    for child in list(used) if _tag(used) == "symbol" else [used]:
        _walk(child, placed, state, figure, texts, lines, depth + 1)


def _height(matrix: Matrix) -> float:
    """How tall a matrix makes a text of height 1: the length its vertical takes. Under a
    rotation it is 1; under `scale(2, 0.5)` it is 0.5, where the square root of the
    determinant would say 1."""
    return math.hypot(matrix[2], matrix[3])


def _widened(matrix: Matrix) -> float:
    """How wide a matrix makes a line of width 1: the square root of its determinant."""
    return math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]))


def _apply(matrix: Matrix, x: float, y: float) -> tuple[float, float]:
    return (matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5])


def _view(root: ET.Element) -> tuple[float, float, float, float] | None:
    numbers = [float(x) for x in _NUMBER.findall(root.get("viewBox") or "")]
    if len(numbers) == 4 and numbers[2] > 0 and numbers[3] > 0:
        return (numbers[0], numbers[1], numbers[2], numbers[3])
    width = _length(root.get("width") or "", DEFAULT_FONT_UNITS)
    height = _length(root.get("height") or "", DEFAULT_FONT_UNITS)
    if width and height and width > 0 and height > 0:
        return (0.0, 0.0, width, height)
    return None


def _root_width(root: ET.Element) -> tuple[float | None, bool]:
    """The figure's own width in points, and whether its `width` carried a unit."""
    match = _LENGTH.match(root.get("width") or "")
    if match is None or match.group(2) == "%":
        return None, False
    units = _length(match.group(0), DEFAULT_FONT_UNITS)
    if units is None or units <= 0:
        return None, False
    return units * PT_PER_INCH / UNITS_PER_INCH, bool(match.group(2))


def points_per_unit(svg: Svg, width_mm: float | None) -> float | None:
    """How many points one unit of the figure prints at: the printed width over the width
    of its visible area; at its own width where none is given."""
    if svg.view is None:
        return None
    if width_mm is not None:
        return width_mm / 25.4 * PT_PER_INCH / svg.view[2]
    if svg.width_pt is None:
        return None
    return svg.width_pt / svg.view[2]


def clipped(svg: Svg) -> list[Mark]:
    """The texts anchored outside the visible area."""
    if svg.view is None:
        return []
    x0, y0, width, height = svg.view
    return [
        mark
        for mark in svg.texts
        if not (x0 - EDGE <= mark.at[0] <= x0 + width + EDGE
                and y0 - EDGE <= mark.at[1] <= y0 + height + EDGE)  # fmt: skip
    ]
