"""A typeset proof read into lines, each with its page and the line number the proof prints
beside it, without what every page repeats.

A PDF is read by `pdftotext` where it is installed, in two orders: the order of the page's
layout, which poppler and Xpdf each work out their own way, and the order the PDF draws its
text in (`-raw`). Neither is right for every proof. On two columns Xpdf's layout order read
across the gutter, a line of each column in turn; a typesetter that draws a float late puts
it late in the drawing order. So both are read, and the caller keeps the reading in which
more of what was sent is found, and says which it kept. Without `pdftotext`, pypdf reads the
drawing order. A proof sent as XML (JATS) or HTML is read as text, one line to a paragraph,
a cell or a heading; one saved as text is read with its pages parted by form feeds, as
`pdftotext` writes them.

What a page repeats is taken out before anything is compared: the running head and foot
(a line that, digits aside, stands on half the pages or more), the page number (a number
alone on its line that counts up with the pages), and the line numbers some proofs print in
the margin. Those are kept where they stand at the start of a line, and the report gives
them; poppler gives them as a column of their own, and they are dropped.
"""

from __future__ import annotations

import html
import math
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.audit import UnreadableText, read_text

PDF_SUFFIXES = frozenset({".pdf"})
XML_SUFFIXES = frozenset({".xml", ".nxml"})
HTML_SUFFIXES = frozenset({".html", ".htm", ".xhtml"})
TEXT_SUFFIXES = frozenset({".txt"})
SUFFIXES = PDF_SUFFIXES | XML_SUFFIXES | HTML_SUFFIXES | TEXT_SUFFIXES

#: The longest `pdftotext` is waited for, as for a stored source (`literature.sources`).
PDFTOTEXT_SECONDS = 120


class UnreadableProof(Exception):
    """The proof could not be read, or holds no text."""


@dataclass(frozen=True)
class Line:
    text: str
    #: The page it is on, from 1; None for a proof with no pages (XML, HTML).
    page: int | None = None
    #: The line number the proof prints beside it, where it prints one.
    number: int | None = None


@dataclass(frozen=True)
class Reading:
    #: What read it, said in the report: "pdftotext 24.04.0 (poppler), layout order".
    reader: str
    lines: tuple[Line, ...]
    pages: int
    #: What was taken out as what every page repeats, once each.
    furniture: tuple[str, ...] = ()
    #: Whether the proof prints line numbers, so that a line can be named by its own.
    numbered: bool = False


def readings(path: Path) -> list[Reading]:
    """Every reading of the proof this machine can make, the likeliest first. Raises
    `UnreadableProof` where there is none, or none holds any text."""
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise UnreadableProof(
            f"{path.name}: a proof is read from a .pdf, an .xml (JATS), an .html or a .txt "
            f"file, not from {suffix or 'a file with no extension'}"
        )
    if suffix in PDF_SUFFIXES:
        found = [_paged(reader, pages) for reader, pages in _pdf_pages(path)]
    else:
        try:
            raw = read_text(path)
        except (OSError, UnreadableText) as exc:
            raise UnreadableProof(f"{path.name}: {exc}") from exc
        if suffix in TEXT_SUFFIXES:
            found = [_paged("the text as saved", raw.split("\f"))]
        else:
            markup = _jats(raw) if suffix in XML_SUFFIXES else raw
            lines = tuple(Line(line) for line in _lines(_untagged(markup)))
            found = [Reading("the text of its markup", lines, 0)]
    found = [reading for reading in found if reading.lines]
    if not found:
        raise UnreadableProof(
            f"{path.name} holds no text that can be read: a proof that is a scanned image "
            "has to be checked by eye"
        )
    return found


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


# ---------------------------------------------------------------- PDF


def _pdf_pages(path: Path) -> list[tuple[str, list[str]]]:
    if shutil.which("pdftotext"):
        name = _pdftotext_name()
        found = []
        for order, extra in (("layout order", []), ("drawing order", ["-raw"])):
            text = _pdftotext(path, extra)
            if text is not None:
                found.append((f"{name}, {order}", text.split("\f")))
        if found:
            return found
    try:
        import pypdf
    except ImportError as exc:
        raise UnreadableProof(
            f"{path.name}: cannot read a PDF here. Install poppler's pdftotext, or "
            "`pip install pypdf`, or save the proof's text as .txt"
        ) from exc
    try:
        reader = pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide variety
        raise UnreadableProof(f"{path.name}: pypdf could not read it: {exc}") from exc
    return [(f"pypdf {getattr(pypdf, '__version__', '')}".strip() + ", drawing order", pages)]


def _pdftotext(path: Path, extra: list[str]) -> str | None:
    """What `pdftotext` reads, in UTF-8 and read as UTF-8 (`literature.sources` says why),
    or None where it failed or read nothing."""
    try:
        done = subprocess.run(
            ["pdftotext", *extra, "-enc", "UTF-8", str(path), "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PDFTOTEXT_SECONDS, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not (done.stdout or "").strip():
        return None
    return done.stdout


def _pdftotext_name() -> str:
    """Which pdftotext it is: poppler's and Xpdf's read a page differently."""
    try:
        done = subprocess.run(
            ["pdftotext", "-v"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return "pdftotext"
    said = f"{done.stdout}\n{done.stderr}"
    version = re.search(r"pdftotext version (\S+)", said)
    family = "Xpdf" if "Glyph & Cog" in said else "poppler" if "oppler" in said else ""
    name = f"pdftotext {version.group(1)}" if version else "pdftotext"
    return f"{name} ({family})" if family else name


# ---------------------------------------------------------------- what pages repeat

#: A number alone on its line, as a page is numbered: "12", "Page 12", "12 of 20".
_LONE = re.compile(r"(?:page\s+)?(\d{1,5})(?:\s*(?:of|/)\s*\d{1,5})?", re.IGNORECASE)
#: A line number in front of a line.
_PREFIX = re.compile(r"(\d{1,5}) (?=\S)")
#: The steps line numbers count by: every line, every fifth, every tenth.
_STEPS = (1, 5, 10)
#: The fewest numbers alone in a row that are a column of line numbers.
_RUN = 5
#: How far from one, or from the page before, a page's line numbers may start: the lines of
#: a heading or a running head the journal leaves unnumbered.
_SLACK = 3


def _paged(reader: str, raw_pages: list[str]) -> Reading:
    if raw_pages and not raw_pages[-1].strip():
        raw_pages = raw_pages[:-1]
    pages = [_lines(page) for page in raw_pages]
    taken: list[str] = []
    pages, numbered = _margin_numbers(pages, taken)
    pages = _without_page_numbers(pages, taken)
    pages = _without_running_lines(pages, taken)
    lines = tuple(
        Line(text, index + 1, number) for index, page in enumerate(pages) for text, number in page
    )
    return Reading(reader, lines, len(raw_pages), tuple(dict.fromkeys(taken)), numbered)


def _margin_numbers(
    pages: list[list[str]], taken: list[str]
) -> tuple[list[list[tuple[str, int | None]]], bool]:
    """Each page's lines with the line number printed in front of each, where the proof
    prints them so, and without a column of them where the reader gave them as one."""
    last = [0]
    pages = [_without_number_columns(lines, taken, last) for lines in pages]
    step = _numbering(pages)
    if step is None:
        return [[(line, None) for line in lines] for lines in pages], False
    out: list[list[tuple[str, int | None]]] = []
    last[0] = 0
    for lines in pages:
        out.append(_numbered(lines, step, last))
    return out, True


def _starts_numbering(first: int, step: int, last: list[int]) -> bool:
    """Whether line numbers may start at `first`: from the top, a page's own from one, or
    on from the last line number of the page before. A column of years is none of these."""
    return first <= step or first == last[0] + step


def _without_number_columns(lines: list[str], taken: list[str], last: list[int]) -> list[str]:
    """The lines without each run of `_RUN` or more numbers alone on their lines that count
    up by one of `_STEPS` from where line numbers start: a column of line numbers, given
    apart from the text."""
    keep = [True] * len(lines)
    index = 0
    while index < len(lines):
        end = index
        while end < len(lines) and lines[end].isdigit() and len(lines[end]) <= 5:
            end += 1
        values = [int(line) for line in lines[index:end]]
        if len(values) >= _RUN:
            step = values[1] - values[0]
            steady = all(b - a == step for a, b in zip(values, values[1:], strict=False))
            if step in _STEPS and steady and _starts_numbering(values[0], step, last):
                for at in range(index, end):
                    keep[at] = False
                last[0] = values[-1]
                taken.append(f"line numbers {values[0]}-{values[-1]}")
        index = max(end, index + 1)
    return [line for line, kept in zip(lines, keep, strict=True) if kept]


def _numbering(pages: list[list[str]]) -> int | None:
    """The step the proof's lines are numbered by in front of them, judged over the whole
    proof, or None where they are not: the numbers count up by the step nearly always, stand
    on enough of the lines, its running head and number aside, and each page's start at one,
    or one on from the page before, give or take the lines of a heading the journal does not
    number. A page alone may be short, the first or the last of a paper."""
    found = [[(at, int(m.group(1))) for at, line in enumerate(lines)
              if (m := _PREFIX.match(line))] for lines in pages]  # fmt: skip
    count = sum(map(len, found))
    if count < _RUN:
        return None
    last = 0
    for page in found:
        if not page:
            continue
        start = page[0][1] - page[0][0]
        if abs(start - 1) > _SLACK and abs(start - last - 1) > _SLACK:
            return None
        last = page[-1][1]
    steps = [b - a for page in found for (_i, a), (_j, b) in zip(page, page[1:], strict=False)]
    lines = max(sum(map(len, pages)) - 2 * len(pages), 1)
    for step in _STEPS:
        if steps and sum(s == step for s in steps) >= 0.8 * len(steps) and count >= (
                0.8 * lines / step):  # fmt: skip
            return step
    return None


def _numbered(lines: list[str], step: int, last: list[int]) -> list[tuple[str, int | None]]:
    """A page's lines, each with the number the proof prints in front of it, taken off it,
    or the number it would have between two numbered every `step` lines. A number in front
    of a line is taken for its number only where it is the one the count is at, give or take
    a line or two, so that "12 patients", unnumbered between two fifths, keeps its 12."""
    out: list[tuple[str, int | None]] = []
    expected: int | None = None
    for line in lines:
        found = _PREFIX.match(line)
        number = int(found.group(1)) if found else None
        if number is not None and (
            abs(number - (expected if expected is not None else last[0] + 1)) <= _SLACK
            or expected is None and abs(number - 1) <= _SLACK
        ) and (step == 1 or number % step == 0):
            out.append((line[found.end():], number))
            expected = number + 1
            last[0] = number
            continue
        out.append((line, expected))
        expected = expected + 1 if expected is not None else None
    return out


def _without_page_numbers(
    pages: list[list[tuple[str, int | None]]], taken: list[str]
) -> list[list[tuple[str, int | None]]]:
    """Without the page's number: a number alone on its line, at the page's top or bottom,
    that is the page's index and the same offset on most pages."""
    if len(pages) < 2:
        return pages
    offsets: dict[int, set[int]] = defaultdict(set)
    for index, page in enumerate(pages):
        for at, (text, _number) in enumerate(page):
            found = _LONE.fullmatch(text)
            if found and _at_an_edge(at, page):
                offsets[int(found.group(1)) - index].add(index)
    if not offsets:
        return pages
    offset, on = max(offsets.items(), key=lambda item: len(item[1]))
    if len(on) < max(2, math.ceil(0.6 * len(pages))):
        return pages
    taken.append("page numbers")
    out = []
    for index, page in enumerate(pages):
        kept, dropped = [], False
        for at, (text, number) in enumerate(page):
            found = _LONE.fullmatch(text)
            if (not dropped and found and int(found.group(1)) - index == offset
                    and _at_an_edge(at, page)):  # fmt: skip
                dropped = True
                continue
            kept.append((text, number))
        out.append(kept)
    return out


def _shape(text: str) -> str:
    return re.sub(r"\d+", "#", text.casefold())


def _without_running_lines(
    pages: list[list[tuple[str, int | None]]], taken: list[str]
) -> list[list[tuple[str, int | None]]]:
    """Without each line that, its digits aside, stands on half the pages or more: a running
    head or foot, which holds the journal's name, the authors' and the page."""
    if len(pages) < 2:
        return pages
    least = max(2, math.ceil(0.5 * len(pages)))
    on: dict[tuple[str, str], list[list[str]]] = defaultdict(list)
    for page in pages:
        shapes = Counter(_shape(text) for text, _n in page)
        for at, (text, _n) in enumerate(page):
            # Once on its page, and on the same side of every page it stands on, the top
            # for a head and the bottom for a foot: a table's rows share a shape, digits
            # aside, many to a page, and a line of the text may happen to stand on the top
            # of one page and the foot of the next.
            side = _edge(at, page)
            if shapes[_shape(text)] == 1 and side:
                on[(_shape(text), side)].append(re.findall(r"\d+", text))
    # Not a number alone, and its numbers the same on every page but one, the page's own.
    running = {
        found for found, numbers in on.items()
        if len(numbers) >= least and sum(c.isalpha() for c in found[0]) >= 3
        and sum(len(set(column)) > 1 for column in zip(*numbers, strict=False)) <= 1
    }  # fmt: skip
    if not running:
        return pages
    out = []
    for page in pages:
        kept = []
        for at, (text, number) in enumerate(page):
            if (_shape(text), _edge(at, page)) in running:
                taken.append(text)
                continue
            kept.append((text, number))
        out.append(kept)
    return out


#: How many lines at the top and at the bottom of a page a running head or foot is looked
#: for in, at most: the head, the foot, the page's number, a line the publisher prints down
#: the margin. A fifth of the page at most, and two lines at least, so that a short last
#: page still has its head and its number.
_EDGE = 4


def _edge(at: int, page: list) -> str:
    """"top" or "bottom" where line `at` stands among the first or the last lines of its
    page, "" where it stands in between."""
    edge = max(2, min(_EDGE, len(page) // 5))
    return "top" if at < edge else "bottom" if at >= len(page) - edge else ""


def _at_an_edge(at: int, page: list) -> bool:
    return bool(_edge(at, page))


# ---------------------------------------------------------------- markup

#: The elements that start a line of their own: a paragraph, a heading, a cell, an item.
_BLOCK = (
    "p|div|h[1-6]|li|tr|td|th|table|caption|figcaption|title|article-title|section|sec|"
    "label|ref|mixed-citation|element-citation|aff|contrib|abstract|kwd|kwd-group|"
    "corresp|author-notes|fn|disp-formula|fig|table-wrap|front|back|body|br|hr|dt|dd"
)
_BLOCK_TAG = re.compile(rf"</?(?:{_BLOCK})\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")
_DROPPED = re.compile(
    r"<!--.*?-->|<\?.*?\?>|<!DOCTYPE[^>\[]*(?:\[.*?\])?\s*>|<(script|style)\b.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
#: A JATS name, surname first, written as a page prints it: given names first.
_NAME = re.compile(
    r"<surname>(?P<family>[^<]*)</surname>\s*<given-names[^>]*>(?P<given>[^<]*)</given-names>"
)


def _jats(text: str) -> str:
    return _NAME.sub(r"<given-names>\g<given></given-names> <surname>\g<family></surname>", text)


def _untagged(markup: str) -> str:
    """The text of XML or HTML, one line to each element that starts one. Read by pattern
    and not parsed: an entity the document declares is not expanded, and nothing it names
    is fetched."""
    text = _CDATA.sub(lambda m: html.escape(m.group(1)), _DROPPED.sub(" ", markup))
    text = _BLOCK_TAG.sub("\n", text)
    return html.unescape(_TAG.sub("", text))
