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

import re
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
    # A format character a typesetter leaves after a heading's number (pdf-multi-C4).
    ("\N{ZERO WIDTH NON-JOINER}", "uni200C"),
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
                 278, 278, 333, 556, 556, 556, 556, 400, 0)  # fmt: skip


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


def pdf(pages: list[list[Piece]], author: str | None = None) -> bytes:
    """A PDF of A4-sized pages, each setting its pieces in Helvetica, with `author` as the
    Author of its Info dictionary where it is given (plain ASCII, no brackets)."""
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
    info = b""
    if author is not None:
        objects.append(b"<< /Author (" + author.encode("ascii") + b") >>")
        info = b" /Info %d 0 R" % len(objects)
    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    table = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R" % (len(objects) + 1) + info + b" >>\n"
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
    author: str | None = None,
) -> bytes:
    """Lines of text set as a journal sets them: in columns, `per_column` lines to a column,
    with a running head over each page, a running foot under it with the page's number
    after it (`first_page`, counted on), and the line numbers some proofs print in the
    margin, counted down each column. A line written "^text" is set as a superscript on the
    line before it, after that line's text. `author` is the Info dictionary's Author."""
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
    return pdf(pages, author)


def _furniture(index: int, head: str | None, foot: str | None, first: int | None) -> list[Piece]:
    pieces = []
    if head is not None:
        pieces.append(Piece(LEFT, 810.0, head, size=7.0))
    if foot is not None or first is not None:
        said = " ".join(p for p in (foot, None if first is None else str(first + index)) if p)
        pieces.append(Piece(LEFT, 40.0, said, size=7.0))
    return pieces


# ------------------------------------------------------------------ a laid-out page

#: The layout `laid_out` sets: a column's width, the body's size and its leading, and the
#: gap around a display.
COLUMN, BODY, BODY_LEADING, AROUND = 230.0, 9.0, 11.0, 14.0
#: A display set across both columns is this wide.
ACROSS = RIGHT - LEFT + COLUMN


#: Inside a word `laid_out` sets, a thin space (`THIN` points wide, read as a space), a
#: word kerned in two (its second part `KERN` points on and set `KERNED` times the size, so
#: that poppler gives two words, read as one), and small capitals (the rest `CAPS_GAP`
#: points on, set `CAPS` times the size, read as one word): "(N~=~168)", "co^hort",
#: "D`ISCUSSION".
THIN_MARK, KERN_MARK, CAPS_MARK = "~", "^", "`"
THIN, KERN, KERNED = 1.2, 0.04, 1.08
CAPS_GAP, CAPS = 0.5, 0.8
_MARKS = re.compile(f"([{re.escape(THIN_MARK + KERN_MARK + CAPS_MARK)}])")


def said(word: str) -> str:
    """A word `laid_out` sets, as pdftotext reads it: a thin space a space, a kern and small
    capitals nothing."""
    return word.replace(THIN_MARK, " ").replace(KERN_MARK, "").replace(CAPS_MARK, "")


def _parts(word: str, size: float) -> list[tuple[str, float, float]]:
    """A word's parts, each `(text, size, gap before it)`."""
    pieces = _MARKS.split(word)
    out = [(pieces[0], size, 0.0)]
    for mark, part in zip(pieces[1::2], pieces[2::2], strict=True):
        out.append((part, size * KERNED, KERN) if mark == KERN_MARK else
                   (part, size * CAPS, CAPS_GAP) if mark == CAPS_MARK else (part, size, THIN))
    return out


def _wide(word: str, size: float) -> float:
    return sum(gap + width(part, at) for part, at, gap in _parts(word, size))


@dataclass(frozen=True)
class Set:
    """A line `laid_out` sets: its words, at `size`, justified to `width` where `justified`
    (a paragraph's last line is not), each superscript `(after, text)` set raised after the
    word at index `after`; a table's row of cells, set a gap apart, where `cells`; drawn
    twice over itself where `twice`; `gap` points above it, a display's own space."""

    words: tuple[str, ...]
    size: float = BODY
    justified: bool = False
    width: float = COLUMN
    raised: tuple[tuple[int, str], ...] = ()
    cells: bool = False
    twice: bool = False
    gap: float = 0.0

    @property
    def text(self) -> str:
        """The line as pdftotext reads its words, a superscript a word after its own."""
        out = []
        for at, word in enumerate(self.words):
            out.append(said(word))
            out += [text for after, text in self.raised if after == at]
        return " ".join(out)


def _set(line: Set, x: float, y: float) -> list[Piece]:
    """The pieces of `line` set from (x, y): word by word, spread to its width where it is
    justified, a table's cells 12 points apart."""
    widths = [_wide(word, line.size) for word in line.words]
    space = width(" ", line.size)
    if line.cells:
        space = 12.0
    elif line.justified and len(line.words) > 1:
        space = (line.width - sum(widths)) / (len(line.words) - 1)
    pieces, at = [], x
    for index, (word, wide) in enumerate(zip(line.words, widths, strict=True)):
        part_at = at
        for part, size, gap in _parts(word, line.size):
            part_at += gap
            pieces.append(Piece(part_at, y, part, size=size))
            if line.twice:
                pieces.append(Piece(part_at, y, part, size=size))
            part_at += width(part, size)
        at += wide
        for after, text in line.raised:
            if after == index:
                pieces.append(Piece(at + 0.5, y, text, size=6.0, rise=3.0))
                at += width(text, 6.0) + 0.5
        at += space
    return pieces


def laid_out(
    pages: list[tuple[list, list, list]],
    *,
    head: str | None = None,
    foot: str | None = None,
    line_numbers: bool = False,
) -> tuple[bytes, list[tuple[int, int, str, int | None]]]:
    """A PDF of `pages`, each the lines set across both columns at its top, then its left
    column's and its right column's, each column from below what is set across, each line a
    `Set` or a dict of its fields; with a running head, a foot with the page's number, and
    the line numbers a proof prints beside each body line in the outer margin, counted on
    over the paper. A display, its lines set smaller than the body's, stands `AROUND` points
    from the text. Gives the PDF and each line set, `(page, line, text, number)`: its line
    counted down its page in reading order, what is set across first, then the left column
    and the right, and the number printed beside it, where one is."""
    out: list[list[Piece]] = []
    places: list[tuple[int, int, str, int | None]] = []
    number = 0
    for index, (across, left, right) in enumerate(pages):
        page = _furniture(index, head, foot, 1)
        counted = 0
        y = TOP
        for line in map(_as_set, across):
            y -= line.gap
            page += _set(line, LEFT, y)
            counted += 1
            places.append((index + 1, counted, line.text, None))
            y -= line.size * 1.22
        below = y - (AROUND if across else 0)
        for x, column in ((LEFT, left), (RIGHT, right)):
            y, body = below, None
            for line in map(_as_set, column):
                if body is not None and body != (line.size == BODY):
                    y -= AROUND
                body = line.size == BODY
                y -= line.gap
                page += _set(line, x, y)
                printed = None
                if line_numbers and body:
                    number += 1
                    printed = number
                    # In the outer margin: before the left column, after the right.
                    at = x - 16 if x == LEFT else x + COLUMN + 12
                    page.append(Piece(at, y, str(number), size=6.0))
                counted += 1
                places.append((index + 1, counted, line.text, printed))
                y -= BODY_LEADING if body else line.size * 1.22
        out.append(page)
    return pdf(out), places


def _as_set(line) -> Set:
    if isinstance(line, Set):
        return line
    return Set(**{**line, "words": tuple(line["words"]),
                  "raised": tuple(tuple(one) for one in line.get("raised", ()))})


_PLACES: dict[str, bool] = {}


def knows_word_places() -> bool:
    """Whether the pdftotext the audit rebuilds a PDF's paragraphs with gives each word's
    place (`auditing.pdf_layout.program`): poppler's does, Xpdf's does not. Asked once for
    each program."""
    import tempfile
    from pathlib import Path

    from manuscript_guard.auditing import pdf_layout

    program = pdf_layout.program() or ""
    if program not in _PLACES:
        with tempfile.TemporaryDirectory(prefix="mg-places-") as folder:
            paper = Path(folder) / "paper.pdf"
            paper.write_bytes(typeset(["Methods", "The cohort was kept."], columns=1))
            try:
                pdf_layout.markup(paper)
            except pdf_layout.NotRebuilt:
                _PLACES[program] = False
            else:
                _PLACES[program] = True
    return _PLACES[program]
