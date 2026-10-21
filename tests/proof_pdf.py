"""Typeset proofs written out here, so that a test reads a PDF that no tool on the machine
made and every extractor reads the same bytes.

A page is a list of pieces of text, each set at a point in one of the fourteen standard
fonts, Helvetica, so that no font is embedded. The font's encoding is WinAnsi with the
codes from 128 renamed to the glyphs a typesetter sets and WinAnsi has no code for: the
minus, the ligatures, the thin space. pdftotext and pypdf both read a glyph by its name, so
"\N{MINUS SIGN}" set here comes back as U+2212 and "\N{LATIN SMALL LIGATURE FI}" as U+FB01,
as they do from a proof.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The glyphs given codes from 128 up, by the name a PDF reader maps to the character.
_EXTRA = (
    ("\N{MINUS SIGN}", "minus"),
    ("\N{LATIN SMALL LIGATURE FI}", "fi"),
    ("\N{LATIN SMALL LIGATURE FL}", "fl"),
    ("\N{THIN SPACE}", "uni2009"),
    ("\N{HYPHEN}", "uni2010"),
    ("\N{EN DASH}", "endash"),
    ("\N{EM DASH}", "emdash"),
    ("\N{LEFT SINGLE QUOTATION MARK}", "quoteleft"),
    ("\N{RIGHT SINGLE QUOTATION MARK}", "quoteright"),
    ("\N{LEFT DOUBLE QUOTATION MARK}", "quotedblleft"),
    ("\N{RIGHT DOUBLE QUOTATION MARK}", "quotedblright"),
    ("\N{MULTIPLICATION SIGN}", "multiply"),
    ("\N{LESS-THAN OR EQUAL TO}", "lessequal"),
    ("\N{GREATER-THAN OR EQUAL TO}", "greaterequal"),
    ("\N{PLUS-MINUS SIGN}", "plusminus"),
    ("\N{MIDDLE DOT}", "periodcentered"),
    ("\N{NO-BREAK SPACE}", "uni00A0"),
    ("\N{SOFT HYPHEN}", "uni00AD"),
    ("\N{LATIN SMALL LETTER E WITH ACUTE}", "eacute"),
    ("\N{LATIN SMALL LETTER E WITH GRAVE}", "egrave"),
    ("\N{LATIN SMALL LETTER O WITH DIAERESIS}", "odieresis"),
    ("\N{GREEK SMALL LETTER MU}", "uni03BC"),
    ("\N{DEGREE SIGN}", "degree"),
)
_CODES = {char: 128 + index for index, (char, _name) in enumerate(_EXTRA)}

#: Helvetica's widths, in thousandths of the size, from the space to the tilde (its AFM).
_ASCII_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556,
    556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722,
    722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722,
    667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
    556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500,
    500, 334, 260, 334, 584,
)  # fmt: skip
#: The widths of the glyphs from 128, in the order of `_EXTRA`.
_EXTRA_WIDTHS = (584, 500, 500, 167, 333, 556, 1000, 222, 222, 333, 333, 584, 549, 549, 584,
                 278, 278, 333, 556, 556, 556, 556, 400)  # fmt: skip


def width(text: str, size: float) -> float:
    """How wide `text` is set in Helvetica at `size` points."""
    total = 0
    for code in _encoded(text).replace(b"\\", b""):
        total += _ASCII_WIDTHS[code - 32] if code < 128 else _EXTRA_WIDTHS[code - 128]
    return total * size / 1000


def _to_unicode() -> bytes:
    """The map from each code to its character, which a proof's fonts carry and a reader
    prefers to the glyph's name."""
    pairs = [(code, ord(char)) for code, char in ((c, chr(c)) for c in range(32, 127))]
    pairs += [(code, ord(char)) for char, code in _CODES.items()]
    entries = b"\n".join(b"<%02X> <%04X>" % pair for pair in pairs)
    head = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            b"/CMapName /Proof def /CMapType 2 def\n1 begincodespacerange <00> <FF> "
            b"endcodespacerange\n%d beginbfchar\n" % len(pairs))  # fmt: skip
    tail = b"\nendbfchar\nendcmap CMapName currentdict /CMap defineresource pop end end"
    return head + entries + tail


@dataclass(frozen=True)
class Piece:
    """Text set at (x, y) points from the bottom left of a page, at `size` points, raised by
    `rise` points (a superscript)."""

    x: float
    y: float
    text: str
    size: float = 9.0
    rise: float = 0.0


def _encoded(text: str) -> bytes:
    out = bytearray()
    for char in text:
        if char in _CODES:
            code = _CODES[char]
        elif 32 <= ord(char) < 127:
            code = ord(char)
        else:
            raise ValueError(f"no code for {char!r} in the proof's font")
        if code in (0x28, 0x29, 0x5C):
            out += b"\\"
        out.append(code)
    return bytes(out)


def _content(pieces: list[Piece]) -> bytes:
    lines = []
    for piece in pieces:
        lines.append(
            b"BT /F1 %g Tf %g Ts %g %g Td (" % (piece.size, piece.rise, piece.x, piece.y)
            + _encoded(piece.text)
            + b") Tj ET"
        )
    return b"\n".join(lines)


def pdf(pages: list[list[Piece]]) -> bytes:
    """A PDF of A4-sized pages, each setting its pieces in Helvetica."""
    differences = b"[128 " + b" ".join(b"/" + name.encode() for _c, name in _EXTRA) + b"]"
    widths = b" ".join(b"%d" % w for w in (*_ASCII_WIDTHS, *_EXTRA_WIDTHS))
    font = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type "
            b"/Encoding /BaseEncoding /WinAnsiEncoding /Differences " + differences
            + b" >> /FirstChar 32 /LastChar %d /Widths [" % (127 + len(_EXTRA)) + widths
            + b"] /ToUnicode 4 0 R >>")  # fmt: skip
    cmap = _to_unicode()
    count = len(pages)
    # 1 catalog, 2 pages, 3 font, 4 its map, then a page and its contents for each page.
    kids = b" ".join(b"%d 0 R" % (5 + 2 * index) for index in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % count,
        font,
        b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream",
    ]
    for index, pieces in enumerate(pages):
        stream = _content(pieces)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>" % (6 + 2 * index)
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    table = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    return body + b"startxref\n%d\n%%%%EOF\n" % table


#: Where a page's two columns start, and how far apart its lines are.
LEFT, RIGHT, TOP, LEADING = 56.0, 310.0, 780.0, 11.0


def typeset(
    lines: list[str],
    *,
    columns: int = 2,
    per_column: int = 60,
    head: str | None = None,
    foot: str | None = None,
    first_page: int | None = None,
    line_numbers: bool = False,
) -> bytes:
    """Lines of text set as a journal sets them: in columns, `per_column` lines to a column,
    with a running head over each page, a running foot under it with the page's number
    after it (`first_page`, counted on), and the line numbers some proofs print in the
    margin, counted down each column. A line written "^text" is set as a superscript on the
    line before it, after that line's text."""
    pages: list[list[Piece]] = []
    page: list[Piece] = []
    column, row, number = 0, 0, 0
    previous: Piece | None = None
    for text in lines:
        if text.startswith("^") and previous is not None:
            x = previous.x + width(previous.text, previous.size) + 0.5
            page.append(Piece(x, previous.y, text[1:], size=6.0, rise=3.0))
            continue
        if row == per_column:
            row, column = 0, column + 1
        if column == columns:
            pages.append(page)
            page, column = [], 0
        if not page:
            page = _furniture(len(pages), head, foot, first_page)
        x = LEFT if column == 0 else RIGHT
        y = TOP - LEADING * row
        number += 1
        if line_numbers:
            page.append(Piece(x - 22, y, str(number), size=6.0))
        previous = Piece(x, y, text)
        page.append(previous)
        row += 1
    if page:
        pages.append(page)
    return pdf(pages)


def _furniture(index: int, head: str | None, foot: str | None, first: int | None) -> list[Piece]:
    pieces = []
    if head is not None:
        pieces.append(Piece(LEFT, 810.0, head, size=7.0))
    if foot is not None or first is not None:
        said = " ".join(p for p in (foot, None if first is None else str(first + index)) if p)
        pieces.append(Piece(LEFT, 40.0, said, size=7.0))
    return pieces
