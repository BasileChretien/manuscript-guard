"""A small PDF writer: pages of wrapped text in the standard fonts, with bookmarks and links
inside the document. What the audit's PDF report is written with (`auditing.report_pdf`).

No dependency. The page runs in a browser under Pyodide, and the package installs nothing a
PDF library would need there (Basile chose this over fpdf2 and over an HTML page printed by
the browser, 2026-11-10). So the text is set in the four fonts every PDF reader has
(Helvetica, its bold and its oblique, and Courier), in their Windows-1252 encoding: a
character that encoding lacks is written as the ASCII a reader would type for it ("≥" as
">=", "−" as "-", "α" as "alpha"), or as "?" where there is none (`SUBSTITUTES`). Lines are
broken at spaces by the fonts' own widths (`WIDTHS`), and a word wider than the column is
broken where it reaches the edge. Bookmarks nest by level and links go to a heading's place.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

#: A4, in points, and the margin all round.
WIDTH, HEIGHT, MARGIN = 595.28, 841.89, 56.0

#: The fonts, by the name the page's resources give them.
FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Helvetica-Oblique", "F4": "Courier"}
_KIND = {"regular": "F1", "bold": "F2", "oblique": "F3", "code": "F4"}

#: Each printable ASCII character's width, in thousandths of the size, in Helvetica and in
#: Helvetica-Bold (Adobe's metrics); the oblique is the regular's, Courier is 600 for all.
_ASCII = "".join(chr(code) for code in range(32, 127))
_REGULAR = (278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
            *(556,) * 10, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611,
            778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667,
            944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278,
            556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500,
            722, 500, 500, 500, 334, 260, 334, 584)  # fmt: skip
_BOLD = (278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
         *(556,) * 10, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778,
         722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
         667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278,
         278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500,
         389, 280, 389, 584)  # fmt: skip
WIDTHS = {"F1": dict(zip(_ASCII, _REGULAR, strict=True)),
          "F2": dict(zip(_ASCII, _BOLD, strict=True))}  # fmt: skip
WIDTHS["F3"] = WIDTHS["F1"]
#: Windows-1252's other characters a report prints, with their widths in Helvetica.
_WIDER = {"œ": 944, "Œ": 1000, "™": 1000, "‚": 222, "„": 333, "†": 556, "‡": 556,
          "‹": 333, "›": 333, "ƒ": 556, "ˆ": 333, "˜": 333, "–": 556, "—": 1000, "‘": 222,
          "’": 222, "“": 333, "”": 333, "•": 350,
          "…": 1000, "€": 556, "±": 584, "×": 584, "÷": 584, "°": 400, "µ": 556, "²": 333,
          "³": 333, "¹": 333, "§": 556, "©": 737, "®": 737, "·": 278, "«": 556, "»": 556,
          "‰": 1000, " ": 278}  # fmt: skip

#: What a character Windows-1252 lacks is written as: what a reader would type for it.
SUBSTITUTES = {"−": "-", "≥": ">=", "≤": "<=", "≠": "!=", "≈": "~", "→": "->", "←": "<-",
               "↔": "<->", "⇒": "=>", "∞": "inf", "√": "sqrt", "∑": "sum", "∆": "delta",
               "‐": "-", "‑": "-", "‒": "-", "―": "-", "′": "'", "″": '"', " ": " ",
               " ": " ", "​": "", "﻿": "", "\t": " "}  # fmt: skip
_GREEK = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota",
          "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho", "final sigma", "sigma",
          "tau", "upsilon", "phi", "chi", "psi", "omega")  # fmt: skip
# Word's optional hyphen, which Windows-1252 would print as a hyphen in mid-line.
SUBSTITUTES[chr(0xAD)] = ""
SUBSTITUTES.update({chr(0x3B1 + at): name.split()[-1] for at, name in enumerate(_GREEK)})
SUBSTITUTES.update({chr(0x391 + at): name.split()[-1].capitalize()
                    for at, name in enumerate(_GREEK) if at != 17})  # fmt: skip


def printable(text: str) -> str:
    """`text` as the standard fonts can print it: each character Windows-1252 lacks written
    as its substitute (`SUBSTITUTES`), its letters without their marks where it has none
    (an "ő" as "o"), and "?" where nothing stands in for it."""
    out = []
    # Composed first, so that a letter and its mark typed apart, "E" and U+0301, are one.
    for char in unicodedata.normalize("NFC", text):
        if char in SUBSTITUTES:
            out.append(SUBSTITUTES[char])
            continue
        try:
            char.encode("cp1252")
            out.append(char if char >= " " or char == "\n" else " ")
        except UnicodeEncodeError:
            if char in (chr(0x338), chr(0x20D2)) and out and out[-1][-1:] in tuple("<>=~"):
                out[-1] = "not " + out[-1]  # a stroke typed after a sign no form composes
                continue
            parts = unicodedata.normalize("NFKD", char)
            # A stroke through a sign negates it, as in U+2270: said, never dropped.
            negated = ("not " if {chr(0x338), chr(0x20D2)} & set(parts)
                       and not unicodedata.combining(char) else "")
            bare = negated + "".join(SUBSTITUTES.get(part, part) for part in parts
                                     if not unicodedata.combining(part))  # fmt: skip
            try:
                bare.encode("cp1252")
                out.append(bare or "?")
            except UnicodeEncodeError:
                out.append("?")
    return "".join(out)


def width(text: str, font: str, size: float) -> float:
    """How wide `text`, printable already, is set in `font` at `size`, in points."""
    if font == "F4":
        return 0.6 * size * len(text)
    table = WIDTHS[font]

    def one(char: str) -> int:
        if char in table:
            return table[char]
        if char in _WIDER:
            return _WIDER[char]
        base = unicodedata.normalize("NFKD", char)[:1]
        return table.get(base, 556)

    return sum(one(char) for char in text) * size / 1000


def wrapped(text: str, font: str, size: float, room: float) -> list[str]:
    """`text`, printable already, in lines no wider than `room`: broken at spaces, and a
    word wider than `room` broken where it reaches it."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            trial = f"{line} {word}" if line else word
            if width(trial, font, size) <= room:
                line = trial
                continue
            if line:
                lines.append(line)
            while width(word, font, size) > room and len(word) > 1:
                cut = max(1, max(at for at in range(1, len(word) + 1)
                                 if width(word[:at], font, size) <= room or at == 1))  # fmt: skip
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def fitted(text: str, font: str, size: float, room: float) -> str:
    """`text`, printable already, on one line no wider than `room`: cut, with "…", where it
    is wider (a running title that names many papers, round 1 of #635)."""
    if width(text, font, size) <= room:
        return text
    while text and width(text.rstrip() + "…", font, size) > room:
        text = text[:-1]
    return text.rstrip() + "…"


def _string(text: str) -> bytes:
    """A PDF string of `text`, printable already: Windows-1252 bytes, its parentheses and
    backslashes escaped, every byte past ASCII as an octal escape."""
    out = bytearray(b"(")
    for byte in text.encode("cp1252"):
        if byte in b"()\\":
            out += b"\\" + bytes([byte])
        elif 32 <= byte < 127:
            out.append(byte)
        else:
            out += b"\\%03o" % byte
    return bytes(out + b")")


def _unicode(text: str) -> bytes:
    """A PDF text string in UTF-16, as a bookmark's title and the document's title are, so
    that they keep every character."""
    return b"<FEFF" + text.encode("utf-16-be", "replace").hex().upper().encode() + b">"


#: A colour, as red, green and blue from 0 to 1.
Rgb = tuple[float, float, float]


def rgb(hexed: str) -> Rgb:
    """A colour from its web form, "#1d4f91"."""
    value = hexed.lstrip("#")
    return tuple(int(value[at:at + 2], 16) / 255 for at in (0, 2, 4))  # type: ignore[return-value]


def _fill(color: Rgb) -> bytes:
    return b"%.3f %.3f %.3f rg" % color


def _stroke(color: Rgb) -> bytes:
    return b"%.3f %.3f %.3f RG" % color


def _rounded(x: float, y: float, w: float, h: float, r: float) -> bytes:
    """The path of a rectangle whose bottom-left corner is (x, y), its corners rounded by `r`
    (Bezier quarter circles, k = 0.5523)."""
    r = max(0.0, min(r, w / 2, h / 2))
    if not r:
        return b"%.2f %.2f %.2f %.2f re" % (x, y, w, h)
    k = r * 0.5523
    return (b"%.2f %.2f m %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l "
            b"%.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c h"
            % (x + r, y, x + w - r, y, x + w - r + k, y, x + w, y + r - k, x + w, y + r,
               x + w, y + h - r, x + w, y + h - r + k, x + w - r + k, y + h, x + w - r, y + h,
               x + r, y + h, x + r - k, y + h, x, y + h - r + k, x, y + h - r,
               x, y + r, x, y + r - k, x + r - k, y, x + r, y))  # fmt: skip


@dataclass
class _Page:
    commands: list[bytes] = field(default_factory=list)
    #: Each link on the page: its rectangle and the key of the place it goes to.
    links: list[tuple[tuple[float, float, float, float], str]] = field(default_factory=list)
    #: Each link out of the document: its rectangle and its address.
    uris: list[tuple[tuple[float, float, float, float], str]] = field(default_factory=list)


@dataclass(frozen=True)
class Margins:
    """What every page carries besides its flow (`Pdf.frame`): a running title at the top
    of every page but the first, and at the foot a line of text, a link where `uri` is
    given, and the page's number of all; in `color`, at `size`."""

    running: str = ""
    foot: str = ""
    uri: str = ""
    color: Rgb = (0.4, 0.4, 0.4)
    rule: Rgb = (0.85, 0.85, 0.85)
    size: float = 7.5
    #: The place the running title links to, where it is a link: the report's summary.
    home: str = ""


@dataclass
class Pdf:
    """A document being set: text flows from the top of the first page down, and on to a
    new page where the next line would pass the bottom margin."""

    title: str
    producer: str = "manuscript-guard"
    pages: list[_Page] = field(default_factory=list)
    #: Each bookmark: its level from 1, its title, its page and its height there.
    outline: list[tuple[int, str, int, float]] = field(default_factory=list)
    #: Each place a link can go to, by key: its page and its height there.
    places: dict[str, tuple[int, float]] = field(default_factory=dict)
    y: float = 0.0
    #: What every page carries besides its flow; none where None.
    frame: Margins | None = None
    author: str = ""
    subject: str = ""
    _done: bool = field(default=False, repr=False)

    def _room(self, height: float) -> None:
        """A new page where `height` more does not fit above the bottom margin."""
        if not self.pages or self.y - height < MARGIN:
            self.pages.append(_Page())
            self.y = HEIGHT - MARGIN

    def gap(self, height: float) -> None:
        if self.pages and self.y - height > MARGIN:
            self.y -= height

    def heading(self, text: str, level: int = 1, key: str | None = None) -> None:
        """A heading, bold, larger by its level, kept with the line after it, and a bookmark
        to it; a place links can go to under `key`."""
        size = {1: 16.0, 2: 13.0}.get(level, 11.0)
        self.gap(size * 0.6)
        lines = wrapped(printable(text), "F2", size, WIDTH - 2 * MARGIN)
        # Kept with what follows it: a heading of the next level, its own room, and a line.
        self._room(size * 1.3 * len(lines) + {1: 96.0, 2: 66.0}.get(level, 40.0))
        top = self.y
        self.outline.append((level, text, len(self.pages) - 1, top))
        if key is not None and key not in self.places:
            # The first heading of a key is its place: two papers' words, the first's.
            self.places[key] = (len(self.pages) - 1, top)
        self._lines(lines, "F2", size, 0.0, 0.0)
        self.gap(size * 0.3)

    def text(self, text: str, *, kind: str = "regular", size: float = 10.0,
             indent: float = 0.0, gray: float = 0.0, link: str | None = None) -> None:  # fmt: skip
        """`text`, wrapped to the column less `indent`, in `kind` ("regular", "bold",
        "oblique", "code") and `gray` (0 black); each of its lines a link to `link`."""
        font = _KIND[kind]
        lines = wrapped(printable(text), font, size, WIDTH - 2 * MARGIN - indent)
        self._lines(lines, font, size, indent, gray, link)

    def row(self, name: str, said: str, *, link: str | None = None, column: float = 150.0,
            size: float = 9.5) -> None:  # fmt: skip
        """A row of a table of two columns: `name` in bold, a link to `link`, and `said`
        wrapped beside it."""
        names = wrapped(printable(name), "F2", size, column - 8)
        saids = wrapped(printable(said), "F1", size, WIDTH - 2 * MARGIN - column)
        step = size * 1.3
        self._room(step * max(len(names), len(saids)))
        top = self.y
        for at, line in enumerate(names):
            self._line(line, "F2", size, MARGIN, top - at * step, 0.0, link)
        for at, line in enumerate(saids):
            self._line(line, "F1", size, MARGIN + column, top - at * step, 0.0)
        self.y = top - step * max(len(names), len(saids)) - 2

    def _lines(self, lines: list[str], font: str, size: float, indent: float, gray: float,
               link: str | None = None) -> None:  # fmt: skip
        step = size * 1.3
        for line in lines:
            self._room(step)
            self._line(line, font, size, MARGIN + indent, self.y, gray, link)
            self.y -= step

    def _line(self, line: str, font: str, size: float, x: float, top: float, gray: float,
              link: str | None = None, color: Rgb | None = None) -> None:  # fmt: skip
        page = self.pages[-1]
        base = top - size
        if color is not None:
            paint, after = _fill(color) + b" ", b" 0 g"
        else:
            paint, after = (f"{gray:.2f} g ".encode(), b" 0 g") if gray else (b"", b"")
        page.commands.append(paint + b"BT /%s %.1f Tf %.2f %.2f Td " % (font.encode(), size, x,
                             base) + _string(line) + b" Tj ET" + after)
        if link is not None and line:
            page.links.append(((x, base - 2, x + width(line, font, size), top), link))

    # What a designed page is drawn with, besides the flowing text: shapes under the text
    # that follows them, a line set where it is told to stand, a bookmark and a place with
    # nothing printed, and an area that links. Each on the current page, at heights in
    # points from the page's foot, as the flow's `y` is.

    def ensure(self, height: float) -> float:
        """The top of `height` points of room on this page, or on a new one where it does not
        fit; the flow then stands there."""
        self._room(height)
        return self.y

    def wrap(self, text: str, kind: str, size: float, room: float) -> list[str]:
        """`text` as the fonts print it, in lines no wider than `room`."""
        return wrapped(printable(text), _KIND[kind], size, room)

    def measure(self, text: str, kind: str, size: float) -> float:
        """How wide one line of `text` is, as the fonts print it."""
        return width(printable(text), _KIND[kind], size)

    def rect(self, x: float, top: float, w: float, h: float, color: Rgb,
             radius: float = 0.0) -> None:  # fmt: skip
        """A rectangle filled in `color`, its top-left corner at (x, top), its corners rounded
        by `radius`; under whatever is drawn after it."""
        self.pages[-1].commands.append(b"q " + _fill(color) + b" " + _rounded(
            x, top - h, w, h, radius) + b" f Q")

    def rule(self, x1: float, y1: float, x2: float, y2: float, color: Rgb,
             thickness: float = 0.6) -> None:  # fmt: skip
        """A straight line from (x1, y1) to (x2, y2)."""
        self.pages[-1].commands.append(b"q " + _stroke(color) + b" %.2f w %.2f %.2f m %.2f %.2f "
                                       b"l S Q" % (thickness, x1, y1, x2, y2))

    def put(self, text: str, *, x: float, top: float, kind: str = "regular",
            size: float = 10.0, color: Rgb | None = None, link: str | None = None,
            uri: str | None = None) -> float:  # fmt: skip
        """One line of `text`, its top at `top`, from `x`; a link to the place `link` or out
        to `uri`. Its width."""
        font = _KIND[kind]
        line = printable(text)
        self._line(line, font, size, x, top, 0.0, link, color)
        wide = width(line, font, size)
        if uri:
            self.pages[-1].uris.append(((x, top - size - 2, x + wide, top), uri))
        return wide

    def link_area(self, x: float, top: float, w: float, h: float, key: str) -> None:
        """An area of the page that links to the place `key`, a tile or a card."""
        self.pages[-1].links.append(((x, top - h, x + w, top), key))

    def bookmark(self, text: str, level: int = 1, key: str | None = None) -> None:
        """A bookmark at the flow's place, and the place `key`, with nothing printed: what a
        heading drawn by other means is found by."""
        if not self.pages:
            self._room(0)
        self.outline.append((level, text, len(self.pages) - 1, self.y))
        if key is not None and key not in self.places:
            self.places[key] = (len(self.pages) - 1, self.y)

    def _framed(self) -> None:
        """Each page's margins as `frame` says: the running title over every page but the
        first, and the foot's line, its link and the page's number, on every page."""
        frame = self.frame
        if frame is None or self._done:
            return
        self._done = True
        count = len(self.pages)
        for at, page in enumerate(self.pages):
            mine = Pdf(self.title, pages=[page])
            foot = MARGIN * 0.55
            mine.rule(MARGIN, foot + frame.size + 5, WIDTH - MARGIN, foot + frame.size + 5,
                      frame.rule, 0.5)  # fmt: skip
            number = f"Page {at + 1} of {count}"
            numbered = mine.measure(number, "regular", frame.size)
            if frame.foot:
                said = fitted(printable(frame.foot), "F1", frame.size,
                              WIDTH - 2 * MARGIN - numbered - 12)  # fmt: skip
                mine.put(said, x=MARGIN, top=foot + frame.size, size=frame.size,
                         color=frame.color, uri=frame.uri or None)  # fmt: skip
            mine.put(number, x=WIDTH - MARGIN - numbered, top=foot + frame.size, size=frame.size,
                     color=frame.color)  # fmt: skip
            if at and frame.running:
                top = HEIGHT - MARGIN * 0.45
                running = fitted(printable(frame.running), "F1", frame.size, WIDTH - 2 * MARGIN)
                mine.put(running, x=MARGIN, top=top, size=frame.size, color=frame.color,
                         link=frame.home or None)  # fmt: skip
                mine.rule(MARGIN, top - frame.size - 5, WIDTH - MARGIN, top - frame.size - 5,
                          frame.rule, 0.5)  # fmt: skip

    def bytes(self) -> bytes:
        """The document, every link resolved to its place, a link to none dropped."""
        if not self.pages:
            self._room(0)
        self._framed()
        return _Writer(self).written()


def _below(item: int, children: dict[int, list[int]]) -> int:
    """How many bookmarks stand under `item` at every level, all open: an open item's
    `/Count` (PDF 32000, table 153)."""
    return sum(1 + _below(child, children) for child in children[item])


class _Writer:
    """The objects of a `Pdf`, numbered, with their byte offsets in the cross-reference
    table: the catalog, the page tree, the fonts, each page and its contents, the
    bookmarks, and the document's information."""

    def __init__(self, pdf: Pdf) -> None:
        self.pdf = pdf
        self.objects: list[bytes] = []

    def add(self, body: bytes = b"") -> int:
        self.objects.append(body)
        return len(self.objects)

    def written(self) -> bytes:
        pdf = self.pdf
        catalog, tree = self.add(), self.add()
        fonts = {name: self.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s "
                                b"/Encoding /WinAnsiEncoding >>" % base.encode())
                 for name, base in FONTS.items()}  # fmt: skip
        resources = b"<< /Font << " + b" ".join(b"/%s %d 0 R" % (name.encode(), number)
                                                for name, number in fonts.items()) + b" >> >>"
        numbers = [self.add() for _page in pdf.pages]
        for number, page in zip(numbers, pdf.pages, strict=True):
            stream = b"\n".join(page.commands)
            contents = self.add(b"<< /Length %d >>\nstream\n" % len(stream) + stream
                                + b"\nendstream")  # fmt: skip
            links = [self.add(b"<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] "
                              b"/Border [0 0 0] /Dest [%d 0 R /XYZ 0 %.2f 0] >>"
                              % (*rect, numbers[pdf.places[key][0]], pdf.places[key][1]))
                     for rect, key in page.links if key in pdf.places]  # fmt: skip
            # A link out: its address as ASCII, as a URI action takes it (PDF 32000, 12.6.4.7).
            links += [self.add(b"<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] "
                               b"/Border [0 0 0] /A << /S /URI /URI " % rect
                               + _string(address.encode("ascii", "ignore").decode()) + b" >> >>")
                      for rect, address in page.uris]  # fmt: skip
            annots = (b" /Annots [" + b" ".join(b"%d 0 R" % one for one in links) + b"]"
                      if links else b"")  # fmt: skip
            self.objects[number - 1] = (
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources %s "
                b"/Contents %d 0 R%s >>" % (tree, WIDTH, HEIGHT, resources, contents, annots))
        self.objects[tree - 1] = (b"<< /Type /Pages /Kids [" + b" ".join(
            b"%d 0 R" % number for number in numbers) + b"] /Count %d >>" % len(numbers))
        outlines = self._outline(numbers)
        self.objects[catalog - 1] = (b"<< /Type /Catalog /Pages %d 0 R" % tree
                                     + (b" /Outlines %d 0 R /PageMode /UseOutlines" % outlines
                                        if outlines else b"") + b" >>")  # fmt: skip
        info = self.add(b"<< /Title " + _unicode(pdf.title) + b" /Producer "
                        + _unicode(pdf.producer)
                        + (b" /Author " + _unicode(pdf.author) if pdf.author else b"")
                        + (b" /Subject " + _unicode(pdf.subject) if pdf.subject else b"")
                        + b" >>")  # fmt: skip
        return self._file(catalog, info)

    def _outline(self, numbers: list[int]) -> int:
        """The bookmarks, each under the last one before it of a lower level; 0 for none."""
        items = self.pdf.outline
        if not items:
            return 0
        root = self.add()
        mine = [self.add() for _item in items]
        parents: list[int] = []
        children: dict[int, list[int]] = {root: []}
        stack: list[tuple[int, int]] = []
        for at, (level, _title, _page, _top) in enumerate(items):
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else root
            parents.append(parent)
            children.setdefault(parent, []).append(mine[at])
            children.setdefault(mine[at], [])
            stack.append((level, mine[at]))
        for at, (_level, title, page, top) in enumerate(items):
            number, parent = mine[at], parents[at]
            siblings = children[parent]
            place = siblings.index(number)
            body = (b"<< /Title " + _unicode(title) + b" /Parent %d 0 R" % parent
                    + b" /Dest [%d 0 R /XYZ 0 %.2f 0]" % (numbers[page], top))  # fmt: skip
            if place:
                body += b" /Prev %d 0 R" % siblings[place - 1]
            if place + 1 < len(siblings):
                body += b" /Next %d 0 R" % siblings[place + 1]
            if children[number]:
                body += b" /First %d 0 R /Last %d 0 R /Count %d" % (
                    children[number][0], children[number][-1], _below(number, children))
            self.objects[number - 1] = body + b" >>"
        top_level = children[root]
        self.objects[root - 1] = (b"<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>"
                                  % (top_level[0], top_level[-1], len(items)))  # fmt: skip
        return root

    def _file(self, catalog: int, info: int) -> bytes:  # noqa: D102 - the file as written
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(self.objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        start = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objects) + 1)
        out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
        out += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(self.objects) + 1, catalog, info, start))  # fmt: skip
        return bytes(out)
