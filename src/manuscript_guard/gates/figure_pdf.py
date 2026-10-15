"""The fonts, text and lines of a PDF figure, read with the standard library.

A journal's artwork guide asks for a vector figure's fonts to be embedded, and some refuse
Type 3 fonts, which matplotlib writes unless `pdf.fonttype` is set to 42. And it states the
smallest text and the thinnest line it prints, at the printed size. So a PDF figure is read
for:

* each font its pages use: Type 3, or a font whose file is not in the PDF, which the
  printer then replaces with one of its own;
* the size of each text it shows: the font size it is set at (`Tf`), carried through the
  text matrix (`Tm`, `Td`) and every transform around it (`cm`, a form's `/Matrix`), as
  the height that takes on the page;
* the width of each line it strokes (`w`), carried through the same transforms.

A PDF's objects are read where they stand and inside object streams, and a stream is
decoded where it is Flate-compressed, which is how plotting libraries write one. A stream
under another filter is not read.
"""

from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

#: How deep a form may draw a form; a figure that goes deeper draws itself.
DEPTH = 8

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_DELIMITERS = b"()<>[]{}/%"
_WHITESPACE = b" \t\r\n\f\x00"
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
_OBJECT = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_STREAM = re.compile(rb"stream\r?\n")
#: The operators that stroke the current path, and so draw a line at the current width.
_STROKES = {b"S", b"s", b"B", b"B*", b"b", b"b*"}
#: The operators that show text at the current font and size.
_SHOWS = {b"Tj", b"TJ", b"'", b'"'}


@dataclass(frozen=True)
class Ref:
    number: int


@dataclass(frozen=True)
class Name:
    name: str


@dataclass
class Font:
    """A font a page uses, by the name it has in the PDF."""

    name: str
    subtype: str
    embedded: bool


@dataclass
class PdfFigure:
    """What a PDF figure's first page shows, and how wide that page is, in points."""

    width_pt: float | None
    fonts: list[Font] = field(default_factory=list)
    #: Each text shown, as (its text where it reads as text, its height in points).
    texts: list[tuple[str, float]] = field(default_factory=list)
    #: Each line stroked, its width in points.
    lines: list[float] = field(default_factory=list)


# --------------------------------------------------------------------------- objects


class _Parser:
    """PDF's object syntax: numbers, names, strings, arrays, dictionaries, references."""

    def __init__(self, data: bytes, at: int = 0) -> None:
        self.data = data
        self.at = at

    def _space(self) -> None:
        data = self.data
        while self.at < len(data):
            if data[self.at] in _WHITESPACE:
                self.at += 1
            elif data[self.at] == ord("%"):
                end = data.find(b"\n", self.at)
                self.at = len(data) if end < 0 else end + 1
            else:
                return

    def value(self) -> object:
        self._space()
        data = self.data
        if self.at >= len(data):
            raise ValueError("the end of the data")
        here = data[self.at : self.at + 2]
        if here == b"<<":
            return self._dictionary()
        if data[self.at] == ord("<"):
            end = data.index(b">", self.at)
            raw = re.sub(rb"\s", b"", data[self.at + 1 : end])
            self.at = end + 1
            return bytes.fromhex((raw + b"0" * (len(raw) % 2)).decode("ascii"))
        if data[self.at] == ord("("):
            return self._string()
        if data[self.at] == ord("["):
            self.at += 1
            items = []
            while True:
                self._space()
                if self.at < len(data) and data[self.at] == ord("]"):
                    self.at += 1
                    return items
                items.append(self.value())
        if data[self.at] == ord("/"):
            start = self.at = self.at + 1
            while self.at < len(data) and data[self.at] not in _WHITESPACE + _DELIMITERS:
                self.at += 1
            return Name(data[start : self.at].decode("latin-1"))
        number = _NUMBER.match(data, self.at)
        if number:
            reference = re.compile(rb"(\d+)\s+(\d+)\s+R\b").match(data, self.at)
            if reference:
                self.at = reference.end()
                return Ref(int(reference.group(1)))
            self.at = number.end()
            text = number.group(0)
            return float(text) if b"." in text else int(text)
        word = re.compile(rb"[A-Za-z]+").match(data, self.at)
        if word:
            self.at = word.end()
            return {b"true": True, b"false": False, b"null": None}.get(word.group(0), word.group(0))
        raise ValueError(f"cannot read a value at {self.at}")

    def _dictionary(self) -> dict:
        self.at += 2
        result: dict = {}
        while True:
            self._space()
            if self.data[self.at : self.at + 2] == b">>":
                self.at += 2
                return result
            key = self.value()
            if not isinstance(key, Name):
                raise ValueError("a dictionary's key is a name")
            result[key.name] = self.value()

    def _string(self) -> bytes:
        data, depth, out = self.data, 0, bytearray()
        self.at += 1
        while self.at < len(data):
            char = data[self.at]
            self.at += 1
            if char == ord("\\"):
                escaped = data[self.at : self.at + 1]
                self.at += 1
                out += {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}.get(
                    escaped, escaped
                )
            elif char == ord("("):
                depth += 1
                out.append(char)
            elif char == ord(")"):
                if depth == 0:
                    return bytes(out)
                depth -= 1
                out.append(char)
            else:
                out.append(char)
        return bytes(out)


@dataclass
class _Object:
    value: object
    stream: bytes | None = None


def _objects(data: bytes) -> dict[int, _Object]:
    """Every object of a PDF, by its number: those where they stand, and those inside an
    object stream. Where a number is written twice, the later in the file is the one an
    update made, whether it stands alone or in an object stream (round 1 of #303)."""
    found: list[tuple[int, int, _Object]] = []
    for match in _OBJECT.finditer(data):
        parser = _Parser(data, match.end())
        try:
            value = parser.value()
        except (ValueError, IndexError):
            continue
        stream = None
        parser._space()
        opened = _STREAM.match(data, parser.at)
        if opened and isinstance(value, dict):
            length = value.get("Length")
            end = data.find(b"endstream", opened.end())
            if isinstance(length, int) and 0 <= length <= len(data) - opened.end():
                stream = data[opened.end() : opened.end() + length]
            elif end >= 0:
                stream = data[opened.end() : end].rstrip(b"\r\n")
        found.append((match.start(), int(match.group(1)), _Object(value, stream)))
    standing = {number: held for _at, number, held in found}
    for at, _number, held in list(found):
        if isinstance(held.value, dict) and _name(held.value.get("Type")) == "ObjStm":
            found += [(at, number, inner) for number, inner in _unpack(held, standing)]
    objects: dict[int, _Object] = {}
    for _at, number, held in sorted(found, key=lambda each: each[0]):
        objects[number] = held
    return objects


def _unpack(held: _Object, objects: dict[int, _Object]) -> list[tuple[int, _Object]]:
    """The objects an object stream holds: its header pairs a number with where it starts."""
    data = _decoded(held, objects)
    count, first = held.value.get("N"), held.value.get("First")
    if data is None or not isinstance(count, int) or not isinstance(first, int):
        return []
    numbers = [int(n) for n in _NUMBER.findall(data[:first])]
    unpacked = []
    for i in range(0, min(len(numbers), 2 * count) - 1, 2):
        try:
            unpacked.append((numbers[i], _Object(_Parser(data, first + numbers[i + 1]).value())))
        except (ValueError, IndexError):
            continue
    return unpacked


def _name(value: object) -> str:
    return value.name if isinstance(value, Name) else ""


def _resolved(value: object, objects: dict[int, _Object], depth: int = 0) -> object:
    while isinstance(value, Ref) and depth < 32:
        held = objects.get(value.number)
        value = held.value if held else None
        depth += 1
    return value


def _decoded(held: _Object, objects: dict[int, _Object]) -> bytes | None:
    """A stream's data, decoded where it is Flate-compressed or not compressed; None under
    another filter."""
    if held.stream is None or not isinstance(held.value, dict):
        return None
    filters = _resolved(held.value.get("Filter"), objects)
    names = [_name(f) for f in (filters if isinstance(filters, list) else [filters]) if f]
    data = held.stream
    for name in names:
        if name not in ("FlateDecode", "Fl"):
            return None
        try:
            data = zlib.decompressobj().decompress(data)
        except zlib.error:
            return None
    return data


# ---------------------------------------------------------------------- what is drawn


def _multiply(left: Matrix, right: Matrix) -> Matrix:
    """`left` then `right`, as PDF composes them: a point is a row vector."""
    a, b, c, d, e, f = left
    g, h, i, j, k, m = right
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j,
            e * g + f * i + k, e * h + f * j + m)  # fmt: skip


def _height(matrix: Matrix) -> float:
    """How tall a matrix makes a text 1 high: the length its upright takes."""
    return math.hypot(matrix[2], matrix[3])


def _widened(matrix: Matrix) -> float:
    """How wide a matrix makes a line 1 wide: the square root of its determinant."""
    return math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]))


def _operations(data: bytes):
    """A content stream's operations, each its operands and its operator."""
    parser = _Parser(data)
    operands: list = []
    while True:
        parser._space()
        if parser.at >= len(data):
            return
        word = re.compile(rb"[A-Za-z'\"*]+[0-9*]?").match(data, parser.at)
        if word and word.group(0) not in (b"true", b"false", b"null"):
            parser.at = word.end()
            if word.group(0) == b"BI":
                # An inline image: its data runs to "EI" and is no operand.
                end = data.find(b"EI", parser.at)
                parser.at = len(data) if end < 0 else end + 2
                operands = []
                continue
            yield operands, word.group(0)
            operands = []
            continue
        try:
            operands.append(parser.value())
        except (ValueError, IndexError):
            parser.at += 1


def _numbers(operands: list, count: int) -> list[float] | None:
    numbers = [x for x in operands if isinstance(x, (int, float)) and not isinstance(x, bool)]
    return [float(x) for x in numbers[-count:]] if len(numbers) >= count else None


def _shown(operands: list) -> str:
    """What a text-showing operation shows, where its bytes read as text."""
    parts = []
    for operand in operands:
        for item in operand if isinstance(operand, list) else [operand]:
            if isinstance(item, bytes):
                parts.append(item.replace(b"\x00", b"").decode("latin-1"))
    text = "".join(parts)
    return text if text.isprintable() else ""


#: The graphics state a stream starts with: the line width, the font size, and whether the
#: font is a composite one, whose bytes are glyph numbers and not characters.
State = tuple[float, float, bool]
START: State = (1.0, 0.0, False)


def _composite(resources: dict, name: object, objects: dict[int, _Object]) -> bool:
    """Whether the font a page's resources name is a composite (Type 0) one."""
    fonts = _resolved(resources.get("Font"), objects)
    font = _resolved(fonts.get(name.name), objects) if isinstance(fonts, dict) and isinstance(
        name, Name) else None  # fmt: skip
    return isinstance(font, dict) and _name(font.get("Subtype")) == "Type0"


def _draw(
    data: bytes,
    resources: dict,
    ctm: Matrix,
    objects: dict[int, _Object],
    figure: PdfFigure,
    depth: int,
    state: State = START,
) -> None:
    """What one content stream draws, with the transform and the graphics state it is drawn
    under: a form takes over the state of what draws it (round 1 of #303)."""
    stack: list[tuple[Matrix, State]] = []
    width, size, composite = state
    tm = tlm = IDENTITY
    for operands, op in _operations(data):
        if op == b"q":
            stack.append((ctm, (width, size, composite)))
        elif op == b"Q" and stack:
            ctm, (width, size, composite) = stack.pop()
        elif op == b"cm" and (n := _numbers(operands, 6)):
            ctm = _multiply((n[0], n[1], n[2], n[3], n[4], n[5]), ctm)
        elif op == b"w" and (n := _numbers(operands, 1)):
            width = n[0]
        elif op in _STROKES:
            figure.lines.append(width * _widened(ctm))
        elif op == b"BT":
            tm = tlm = IDENTITY
        elif op == b"Tf" and (n := _numbers(operands, 1)):
            size = n[0]
            composite = _composite(resources, operands[0] if operands else None, objects)
        elif op == b"Tm" and (n := _numbers(operands, 6)):
            tm = tlm = (n[0], n[1], n[2], n[3], n[4], n[5])
        elif op in (b"Td", b"TD") and (n := _numbers(operands, 2)):
            tm = tlm = _multiply((1.0, 0.0, 0.0, 1.0, n[0], n[1]), tlm)
        elif op in _SHOWS and size:
            # A composite font's bytes are glyph numbers: the text is not quoted.
            shown = "" if composite else _shown(operands)
            figure.texts.append((shown, abs(size) * _height(_multiply(tm, ctm))))
        elif op == b"Do" and operands and isinstance(operands[-1], Name) and depth < DEPTH:
            _form(operands[-1].name, resources, ctm, objects, figure, depth,
                  (width, size, composite))  # fmt: skip


def _form(
    name: str,
    resources: dict,
    ctm: Matrix,
    objects: dict[int, _Object],
    figure: PdfFigure,
    depth: int,
    state: State = START,
) -> None:
    """What a form drawn by `Do` draws, under its own `/Matrix`."""
    forms = _resolved(resources.get("XObject"), objects)
    ref = forms.get(name) if isinstance(forms, dict) else None
    held = objects.get(ref.number) if isinstance(ref, Ref) else None
    if held is None or not isinstance(held.value, dict):
        return
    data = _decoded(held, objects) if _name(held.value.get("Subtype")) == "Form" else None
    if data is None:
        return
    own = _form_matrix(held, objects)
    inner = _resolved(held.value.get("Resources"), objects)
    _draw(data, inner if isinstance(inner, dict) else resources,
          _multiply(own, ctm), objects, figure, depth + 1, state)  # fmt: skip


def _form_matrix(held: _Object, objects: dict[int, _Object]) -> Matrix:
    """A form's `/Matrix`, which maps it into the space of what draws it."""
    matrix = _resolved(held.value.get("Matrix"), objects) if isinstance(held.value, dict) else None
    numbers = [x for x in matrix if isinstance(x, (int, float))] if isinstance(matrix, list) else []
    if len(numbers) != 6:
        return IDENTITY
    a, b, c, d, e, f = (float(x) for x in numbers)
    return (a, b, c, d, e, f)


def _fonts(resources: dict, objects: dict[int, _Object], seen: dict[str, Font]) -> None:
    """The fonts a page's or a form's resources name, and whether each is Type 3 or has
    no font file in the PDF."""
    fonts = _resolved(resources.get("Font"), objects)
    for value in (fonts or {}).values() if isinstance(fonts, dict) else ():
        font = _resolved(value, objects)
        if not isinstance(font, dict):
            continue
        base = _name(font.get("BaseFont")) or "a font with no name"
        subtype = _name(font.get("Subtype"))
        described = font
        if subtype == "Type0":
            descendants = _resolved(font.get("DescendantFonts"), objects)
            first = descendants[0] if isinstance(descendants, list) and descendants else None
            described = _resolved(first, objects) if first is not None else {}
        descriptor = _resolved(
            described.get("FontDescriptor") if isinstance(described, dict) else None, objects
        )
        embedded = subtype == "Type3" or (
            isinstance(descriptor, dict)
            and any(key in descriptor for key in ("FontFile", "FontFile2", "FontFile3"))
        )
        seen.setdefault(base, Font(base, subtype, embedded))
    forms = _resolved(resources.get("XObject"), objects)
    for value in (forms or {}).values() if isinstance(forms, dict) else ():
        form = _resolved(value, objects)
        inner = _resolved(form.get("Resources"), objects) if isinstance(form, dict) else None
        if isinstance(inner, dict) and inner is not resources:
            _fonts(inner, objects, seen)


def _inherited(page: dict, key: str, objects: dict[int, _Object]) -> object:
    """A page's value of `key`, its own or its parents' up the page tree."""
    node, steps = page, 0
    while isinstance(node, dict) and steps < 32:
        if key in node:
            return _resolved(node[key], objects)
        node = _resolved(node.get("Parent"), objects)
        steps += 1
    return None


def read_pdf(path: Path) -> PdfFigure | None:
    """A PDF figure's first page: its width, the fonts it uses, the size of each text it
    shows and the width of each line it strokes; None where no page can be read."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return parse_pdf(data)


def parse_pdf(data: bytes) -> PdfFigure | None:
    """What a PDF's bytes draw on its first page; None where no page can be read."""
    if not data.startswith(b"%PDF"):
        return None
    objects = _objects(data)
    pages = [
        held.value
        for _number, held in sorted(objects.items())
        if isinstance(held.value, dict) and _name(held.value.get("Type")) == "Page"
    ]
    if not pages:
        return None
    page = pages[0]
    figure = PdfFigure(_printed_width(page, objects))
    resources = _inherited(page, "Resources", objects)
    resources = resources if isinstance(resources, dict) else {}
    seen: dict[str, Font] = {}
    _fonts(resources, objects, seen)
    figure.fonts = list(seen.values())
    # A page's contents may be several streams, which draw as one: a transform one opens,
    # the next draws under (round 1 of #303).
    contents = _resolved(page.get("Contents"), objects)
    streams = []
    for ref in contents if isinstance(contents, list) else [page.get("Contents")]:
        held = objects.get(ref.number) if isinstance(ref, Ref) else None
        data = _decoded(held, objects) if held else None
        if data is not None:
            streams.append(data)
    _draw_page(streams, resources, objects, figure)
    return figure


def _draw_page(
    streams: list[bytes], resources: dict, objects: dict[int, _Object], figure: PdfFigure
) -> None:
    """A page's content streams, drawn as the one stream they are."""
    _draw(b"\n".join(streams), resources, IDENTITY, objects, figure, 0)


def _printed_width(page: dict, objects: dict[int, _Object]) -> float | None:
    """How wide a page prints: its CropBox, where it has one, else its MediaBox, and its
    height where `/Rotate` turns it a quarter (round 1 of #303)."""
    for key in ("CropBox", "MediaBox"):
        box = _inherited(page, key, objects)
        numbers = [float(x) for x in box if isinstance(x, (int, float))] if isinstance(
            box, list) else []  # fmt: skip
        if len(numbers) == 4:
            turned = _inherited(page, "Rotate", objects)
            quarter = isinstance(turned, int) and turned % 180 == 90
            return abs(numbers[3] - numbers[1]) if quarter else abs(numbers[2] - numbers[0])
    return None
