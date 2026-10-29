"""The graphical abstract's concepts, drawn as SVG from the brief.

Two concepts are drawn, each a file the author can open, edit or hand to a designer:

- `concept-1.svg`: three panels, left to right, what was asked and how, what was found, and
  what it means;
- `concept-2.svg`: the question above its answer, and what it means below.

Every `<text>` carries `data-statement`, the id of the brief's statement it prints, and
`data-binding`, the values it prints by their bindings, space-separated; a panel's heading
carries both empty. So `communicate check` can say which statement a line restates, and
whether the value it prints is the one the results hold now.

The primary findings are set large and the secondary ones smaller, apart below a rule. The
colours are Okabe and Ito's, which stay apart for readers with a colour-vision deficiency,
and text is black. The files are written with `xml.etree`, the same bytes from the same
brief, results and size.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from manuscript_guard.communicate.brief import Brief, Statement
from manuscript_guard.communicate.templates import Template
from manuscript_guard.text.placeholders import REF_NAMESPACES, VALUE_NAMESPACES, parse

SVG_NS = "http://www.w3.org/2000/svg"
#: The bindings a statement prints words for: a value, and a pointer to a display.
PRINTED_NAMESPACES = VALUE_NAMESPACES + REF_NAMESPACES
#: The size drawn where the journal's profile gives none (decision 4 of 2026-10-28: the
#: default, with a note): 1328 by 531 pixels, the least size Elsevier's journals ask of one,
#: which is also a 5:2 band that most journals' pages and a social card hold.
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1328, 531
#: CSS pixels to points.
PT_PER_PX = 0.75
FONT = "Arial, Helvetica, sans-serif"
TEXT_COLOUR = "#000000"
BACKGROUND = "#ffffff"
#: How wide a character of the font is, on average, in ems: what a line is wrapped at.
_EM_PER_CHARACTER = 0.56
_EMPHASIS = re.compile(r"[*`]+")


@dataclass(frozen=True)
class Size:
    width: int
    height: int
    #: Where the size comes from, in words.
    why: str
    #: Whether it is the default, the journal giving none.
    default: bool


def size_of(rules: dict) -> Size:
    """The size to draw at, from the journal's `graphical_abstract` rules: its width and
    height, or one of them with its aspect ratio, each raised to its least where it gives
    one; the default where it gives neither."""
    width, height = rules.get("width_px"), rules.get("height_px")
    ratio = _ratio(rules.get("aspect_ratio"))
    if width is None and height is None and ratio is None:
        least_w, least_h = rules.get("min_width_px"), rules.get("min_height_px")
        if least_w is None and least_h is None:
            return Size(DEFAULT_WIDTH, DEFAULT_HEIGHT, "the default: the journal's profile "
                        "gives no size for a graphical abstract", True)  # fmt: skip
        width = max(DEFAULT_WIDTH, least_w or 0)
        height = max(DEFAULT_HEIGHT, least_h or 0)
        return Size(width, height, "the default raised to the least size the journal's "
                    "profile gives", False)  # fmt: skip
    if width is None and height is None:
        width = DEFAULT_WIDTH
    if width is not None and height is None:
        height = round(width / ratio) if ratio else round(width * DEFAULT_HEIGHT / DEFAULT_WIDTH)
    elif height is not None and width is None:
        width = round(height * ratio) if ratio else round(height * DEFAULT_WIDTH / DEFAULT_HEIGHT)
    width = max(width, rules.get("min_width_px") or 0)
    height = max(height, rules.get("min_height_px") or 0)
    return Size(int(width), int(height), "the journal's profile (graphical_abstract)", False)


def _ratio(said: object) -> float | None:
    if not isinstance(said, str) or ":" not in said:
        return None
    wide, high = said.split(":", 1)
    try:
        value = float(wide) / float(high)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


# ----------------------------------------------------------------------------- the words


@dataclass(frozen=True)
class _Token:
    text: str
    ref: str
    spaced: bool


def unbound_refs(statement: Statement, namespace: dict) -> list[str]:
    """The values a statement binds that nothing emits."""
    return [p.ref for p in parse(statement.text)[0]
            if p.namespace in VALUE_NAMESPACES and p.ref not in namespace]  # fmt: skip


#: What the text of a statement holds that a picture does not print: a citation, in
#: brackets or bare, and what the LaTeX reader writes in place of a cross-reference or a
#: display (the private use area's characters, a mark to its end).
_CITATION = re.compile(
    r"[ \t]*\[[^\[\]\n]*@[^\[\]\n]*\]|[ \t]*(?<![\w@])@[A-Za-z0-9_][\w:.#$%&+?<>~/-]*\w"
)
_STAND_IN = re.compile(
    "[" + chr(0xE003) + chr(0xE004) + "][^" + chr(0xE005) + "]*" + chr(0xE005)
    + "|[" + chr(0xE000) + "-" + chr(0xF8FF) + "]"
)
#: What opens a list's item or a quotation, at the start of a statement.
_MARKER = re.compile(r"\A[ \t]*(?:(?:[-*+]|\d+[.)]|>)[ \t]+)+")


@dataclass(frozen=True)
class Shown:
    """A pointer's words as the build prints them, in the shape of a value: its display."""

    display: str


def pointers(project) -> dict[str, Shown]:
    """What each `{{ref.…}}` and `{{num.…}}` binding prints, "Table 2" and "2", as the build
    numbers the displays."""
    from manuscript_guard.gates.pointers import display_numbers

    return {ref: Shown(text) for ref, text in display_numbers(project).bindings().items()}


def _clean(piece: str, opens: bool) -> str:
    piece = _STAND_IN.sub("", _CITATION.sub("", piece))
    piece = _MARKER.sub("", piece) if opens else piece
    return _EMPHASIS.sub("", piece)


def _tokens(text: str, namespace: dict) -> list[_Token]:
    """The words of a statement as printed: each binding its display, kept whole on a line, a
    pointer the number the build gives it where `namespace` has it, and the marks of
    emphasis and code, a citation, a list's or a quotation's marker taken off."""
    placeholders, _ = parse(text)
    tokens: list[_Token] = []
    at = 0
    spaced = False

    def words(piece: str, opens: bool) -> None:
        nonlocal spaced
        for found in re.finditer(r"\S+|\s+", _clean(piece, opens)):
            if found.group().isspace():
                spaced = True
            else:
                tokens.append(_Token(found.group(), "", spaced))
                spaced = False

    for placeholder in placeholders:
        words(text[at : placeholder.start], at == 0)
        at = placeholder.end
        if placeholder.is_anchor or placeholder.namespace not in PRINTED_NAMESPACES:
            continue
        value = namespace.get(placeholder.ref)
        if value is None and placeholder.namespace not in VALUE_NAMESPACES:
            continue
        shown = value.display if value is not None else placeholder.raw
        ref = placeholder.ref if placeholder.namespace in VALUE_NAMESPACES else ""
        tokens.append(_Token(shown, ref, spaced))
        spaced = False
    words(text[at:], at == 0)
    return tokens


def printed(text: str, namespace: dict) -> str:
    """A statement as the graphical abstract prints it, on one line."""
    return "".join((" " if t.spaced and i else "") + t.text
                   for i, t in enumerate(_tokens(text, namespace)))  # fmt: skip


def _lines(tokens: list[_Token], most: int) -> list[list[_Token]]:
    """The tokens wrapped at `most` characters, a token longer than a line on one alone."""
    lines: list[list[_Token]] = []
    line: list[_Token] = []
    length = 0
    for token in tokens:
        extra = len(token.text) + (1 if line and token.spaced else 0)
        if line and token.spaced and length + extra > most:
            lines.append(line)
            line, length = [], 0
            extra = len(token.text)
        line.append(token)
        length += extra
    if line:
        lines.append(line)
    return lines


# ------------------------------------------------------------------------------ drawing


@dataclass(frozen=True)
class _Fonts:
    heading: int
    primary: int
    body: int
    secondary: int


def _fonts(height: int, least_pt: float | None) -> _Fonts:
    least = math.ceil(least_pt / PT_PER_PX) if least_pt else 0
    return _Fonts(*(max(round(height * share), least) for share in (0.05, 0.07, 0.04, 0.034)))


class _Canvas:
    def __init__(self, size: Size, colours: list[str], namespace: dict) -> None:
        self.size = size
        self.colours = colours
        self.namespace = namespace
        self.root = ET.Element(
            "svg",
            {
                "xmlns": SVG_NS,
                "width": str(size.width),
                "height": str(size.height),
                "viewBox": f"0 0 {size.width} {size.height}",
            },
        )
        ET.SubElement(self.root, "desc").text = (
            "Graphical abstract drawn by manuscript-guard communicate graphical-abstract from "
            "communication/brief.yaml"
        )
        self.rect(0, 0, size.width, size.height, fill=BACKGROUND)

    def rect(self, x: float, y: float, w: float, h: float, *, fill: str = "none",
             stroke: str = "", width: float = 0) -> None:  # fmt: skip
        attributes = {"x": _n(x), "y": _n(y), "width": _n(w), "height": _n(h), "fill": fill}
        if stroke:
            attributes |= {"stroke": stroke, "stroke-width": _n(width)}
        ET.SubElement(self.root, "rect", attributes)

    def line(self, x1: float, y1: float, x2: float, y2: float, colour: str, width: float) -> None:
        ET.SubElement(self.root, "line", {"x1": _n(x1), "y1": _n(y1), "x2": _n(x2),
                                          "y2": _n(y2), "stroke": colour,
                                          "stroke-width": _n(width)})  # fmt: skip

    def path(self, d: str, colour: str) -> None:
        ET.SubElement(self.root, "path", {"d": d, "fill": colour})

    def text(self, x: float, y: float, words: str, font: int, *, bold: bool = False,
             statement: str = "", refs: tuple[str, ...] = ()) -> None:  # fmt: skip
        node = ET.SubElement(
            self.root,
            "text",
            {
                "x": _n(x),
                "y": _n(y),
                "font-family": FONT,
                "font-size": str(font),
                "font-weight": "bold" if bold else "normal",
                "fill": TEXT_COLOUR,
                "data-statement": statement,
                "data-binding": " ".join(refs),
            },
        )
        node.text = words

    def statement(self, one: Statement, x: float, y: float, width: float, font: int,
                  bold: bool = False) -> float:  # fmt: skip
        """Draw a statement wrapped to `width` from `y`, its first line's baseline below it;
        give where the next one starts."""
        most = max(int(width / (font * _EM_PER_CHARACTER)), 8)
        for line in _lines(_tokens(one.text, self.namespace), most):
            y += font * 1.2
            words = "".join((" " if t.spaced and i else "") + t.text for i, t in enumerate(line))
            refs = tuple(dict.fromkeys(t.ref for t in line if t.ref))
            self.text(x, y, words, font, bold=bold, statement=one.id, refs=refs)
        return y + font * 0.5

    def written(self) -> bytes:
        ET.indent(self.root, space="  ")
        body = ET.tostring(self.root, encoding="unicode")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n").encode("utf-8")


def _n(value: float) -> str:
    """A coordinate as written: to one decimal, and no decimal where it is whole."""
    rounded = round(value, 1)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"


@dataclass(frozen=True)
class Panels:
    """What each panel holds, from the brief."""

    asked: list[Statement]
    how: list[Statement]
    primary: list[Statement]
    secondary: list[Statement]
    means: list[Statement]


def panels(brief: Brief) -> Panels:
    findings = brief.of("findings")
    return Panels(
        brief.of("question"),
        brief.of("design") + brief.of("population"),
        [one for one in findings if one.primary],
        [one for one in findings if not one.primary],
        brief.of("conclusion"),
    )


def concept_1(brief: Brief, template: Template, size: Size, colours: list[str],
              namespace: dict, least_pt: float | None = None) -> bytes:  # fmt: skip
    """Three panels, left to right."""
    canvas = _Canvas(size, colours, namespace)
    fonts = _fonts(size.height, least_pt)
    margin = round(size.height * 0.045)
    pad = margin * 0.75
    width = (size.width - 4 * margin) / 3
    height = size.height - 2 * margin
    held = panels(brief)
    for index in range(3):
        x = margin + index * (width + margin)
        canvas.rect(x, margin, width, height, stroke=colours[index], width=4)
        y = margin + pad + fonts.heading
        canvas.text(x + pad, y, template.headings[index], fonts.heading, bold=True)
        y += fonts.heading * 0.4
        inner = width - 2 * pad
        if index == 0:
            for one in held.asked:
                y = canvas.statement(one, x + pad, y, inner, fonts.body)
            for one in held.how:
                y = canvas.statement(one, x + pad, y, inner, fonts.secondary)
        elif index == 1:
            for one in held.primary:
                y = canvas.statement(one, x + pad, y, inner, fonts.primary, bold=True)
            if held.secondary:
                y += fonts.secondary * 0.5
                canvas.line(x + pad, y, x + width - pad, y, colours[index], 2)
                for one in held.secondary:
                    y = canvas.statement(one, x + pad, y, inner, fonts.secondary)
        else:
            for one in held.means:
                y = canvas.statement(one, x + pad, y, inner, fonts.body)
    return canvas.written()


def concept_2(brief: Brief, template: Template, size: Size, colours: list[str],
              namespace: dict, least_pt: float | None = None) -> bytes:  # fmt: skip
    """The question above its answer, and what it means below."""
    canvas = _Canvas(size, colours, namespace)
    fonts = _fonts(size.height, least_pt)
    margin = round(size.height * 0.045)
    inner = size.width - 2 * margin
    held = panels(brief)
    canvas.rect(0, 0, margin / 2, size.height, fill=colours[0])
    y = float(margin)
    for one in held.asked:
        y = canvas.statement(one, margin, y, inner, fonts.body)
    # An arrow down, from the question to the answer.
    middle = size.width / 2
    tip = y + fonts.body * 1.2
    canvas.path(f"M {_n(middle - fonts.body * 0.6)} {_n(y)} L {_n(middle + fonts.body * 0.6)} "
                f"{_n(y)} L {_n(middle)} {_n(tip)} Z", colours[1])  # fmt: skip
    y = tip
    for one in held.primary:
        y = canvas.statement(one, margin, y, inner, fonts.primary, bold=True)
    for one in held.secondary:
        y = canvas.statement(one, margin, y, inner, fonts.secondary)
    if held.means:
        y += fonts.secondary * 0.5
        canvas.line(margin, y, size.width - margin, y, colours[2], 2)
        y += fonts.heading * 0.2
        canvas.text(margin, y + fonts.heading * 1.2, template.headings[2], fonts.heading,
                    bold=True)  # fmt: skip
        y += fonts.heading * 1.6
        for one in held.means:
            y = canvas.statement(one, margin, y, inner, fonts.body)
    return canvas.written()


# --------------------------------------------------------------------- what is written beside


def _alt_words(text: str, pointers: dict) -> str:
    """A statement as its alternative text gives it: its values by their bindings, which
    `communicate check` reads with each display as the build reads a figure's; each pointer
    the number the build gives it, or nothing; and what the picture leaves out taken off."""
    placeholders, _ = parse(text)
    out, at = [], 0
    for placeholder in placeholders:
        out.append(_clean(text[at : placeholder.start], at == 0))
        at = placeholder.end
        if placeholder.namespace in VALUE_NAMESPACES:
            out.append(placeholder.raw)
        elif placeholder.namespace in REF_NAMESPACES and placeholder.ref in pointers:
            out.append(pointers[placeholder.ref].display)
    out.append(_clean(text[at:], at == 0))
    return " ".join("".join(out).split())


def alt_text(brief: Brief, template: Template, pointers: dict | None = None) -> str:
    """The graphical abstract's alternative text, the same for both concepts: each panel's
    heading and its main statements, the question, the primary findings and the conclusion;
    what the panels give besides, the design, the population and the secondary findings, is
    left to the picture, as a figure's alternative text leaves its detail to the legend."""
    held = panels(brief)
    parts = []
    for heading, statements in zip(
        template.headings, (held.asked, held.primary, held.means), strict=True
    ):
        said = " ".join(_alt_words(one.text, pointers or {}) for one in statements)
        if said:
            parts.append(f"{heading}: {said}")
    return "Graphical abstract. " + " ".join(parts) + "\n"


def concept_md(brief: Brief, template: Template, why: str, size: Size) -> str:
    held = panels(brief)

    def ids(statements: list[Statement], primary: bool = False) -> str:
        if not statements:
            return "nothing in the brief"
        return ", ".join(f"{one.id}{' (primary)' if primary else ''}" for one in statements)

    lines = [
        "# The graphical abstract: its concepts",
        "",
        "Written by `manuscript-guard communicate graphical-abstract` from "
        "`communication/brief.yaml`, and written again, over this file and the two "
        "concepts, each time it runs. `validation-report.md` is what `communicate check "
        "--only graphical-abstract` said of them when they were drawn.",
        "",
        f"- Template: {template.name}, {why}.",
        f"- Size: {size.width} by {size.height} pixels, {size.why}.",
        "- Colours: Okabe and Ito's, which stay apart for readers with a colour-vision "
        "deficiency; text is black on white.",
        "",
        "## concept-1.svg: three panels, left to right",
        "",
        f"1. {template.headings[0]}: {ids(held.asked + held.how)}",
        f"2. {template.headings[1]}: {ids(held.primary, True)}"
        + (f"; then, smaller: {ids(held.secondary)}" if held.secondary else ""),
        f"3. {template.headings[2]}: {ids(held.means)}",
        "",
        "## concept-2.svg: the question, then its answer",
        "",
        f"1. The question: {ids(held.asked)}",
        f"2. The answer: {ids(held.primary, True)}"
        + (f"; then, smaller: {ids(held.secondary)}" if held.secondary else ""),
        f"3. {template.headings[2]}: {ids(held.means)}",
        "",
        "Each `<text>` names its statement (`data-statement`) and the values it prints "
        "(`data-binding`). Edit a statement's `text` in the brief and draw them again, "
        "rather than editing the words in the SVG: the check holds each line to its "
        "statement and each value to the results.",
        "",
    ]
    return "\n".join(lines)
