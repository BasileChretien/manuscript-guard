"""A PDF's lines rebuilt into paragraphs from where each word is set, for G6 and G14.

`auditing.pdf` reads a PDF's text a line of the PDF to a line, with no paragraph: a section
is one block from heading to heading, a legend's or a table's words are the text's, and a
sentence broken by a column, a page or a float meets nothing of itself again. Here the same
lines are read from where poppler's `pdftotext -bbox-layout` sets each word on its page, and
put back together by position (the design of 2026-11-26 and the author's answers to it):

- a word's format characters (a zero-width non-joiner after "1. Introduction") are dropped;
- the lines on one baseline a word's gap or two apart are made one, where they are lines of
  blocks of one line or of one block: a justified "Keywords:" line, a table's row;
- a line drawn again over itself is read once (`OVERLAID`);
- what a page repeats is taken out: the lines in the top or the bottom `BAND` of a page
  whose words, digits read alike, stand there on `RUNNING_SHARE` of the pages; a number
  alone there, the page's; and a column of numbers alone beside the text, the margin's line
  numbers, each kept as the printed number of the line on its baseline;
- the blocks of a page are read in bands cut by the blocks that cross its middle, and in
  each band the left column top to bottom, then the right: poppler's own flow order put a
  right column before the left on a real paper;
- a block whose first line opens on a display's label, "Figure 2.", "Fig. 2", "Table 1:",
  is a legend; the display's own text is the narrow short blocks after it (cells, labels),
  the blocks after it set at its size, and, before a figure's legend, the narrow short
  blocks just above it (the figure's own words). Each display is read as a display, as in
  a Word paper; a figure's own words stay with its legend (the author, 2026-11-26, answers
  2 and 3);
- a paragraph ends where a line ends short of its block's right edge on a stop, and at a
  block's end, unless the block ends without one: then the next body block goes on with the
  paragraph across the column, the page and any display between, which is read after it;
- a small number raised above a word's line after the word, "shown 2-4", is a citation set
  as a superscript, which G6 reads as one (answer 6).

Each line that is kept stays a line, placed by its page and its line counted down the page
in reading order, left column first, with the number the PDF prints beside it where it
prints one (answer 5). Only poppler's pdftotext gives the place of each word: Xpdf's has no
`-bbox-layout` (`reporting.rows.knows_no_bbox`), and where it is the one found the audit
reads the PDF's lines as before and says why (answer 1). The program is the one
`MANUSCRIPT_GUARD_POPPLER` names, else the `pdftotext` on PATH (docs/install.md). Every
other reader of a PDF's text keeps `auditing.pdf`'s reading (answer 4).

The markup is read by pattern, as `proof.reading` reads markup, never by an XML parser.
"""

from __future__ import annotations

import collections
import html
import math
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

#: The variable that names poppler's pdftotext, where the one on PATH is another.
POPPLER = "MANUSCRIPT_GUARD_POPPLER"

#: The top and the bottom share of a page a running head or foot stands in.
BAND = 0.075
#: A line in a page's band is a running one where its words, digits read alike, stand in
#: the same band on this share of the pages, and on two at least.
RUNNING_SHARE = 0.3
#: How near, in points, a line drawn again over another stands to it: read once.
OVERLAID = 6.0
OVERLAID_ACROSS = 20.0
#: How far a block must reach past the middle of the page, in points, to cross it.
CROSSING = 15.0
#: A block is narrow below this share of the text's usual block width, and short where
#: each of its lines has fewer characters than `SHORT_LINE` and it has `FRAGMENT_LINES`
#: lines at most: a table's cell, a figure's label.
NARROW = 0.45
SHORT_LINE = 45
FRAGMENT_LINES = 6
#: A block is set small where its lines' mean height is below this share of the body's.
SMALL = 0.82
#: A block is set at a legend's size where its height is within this of the legend's, in
#: points, and the legend is smaller than the body by `SMALLER` at least.
LEGEND_SIZE = 0.35
SMALLER = 0.3
#: A line ends short of its block where it ends this share of the block's width before its
#: right edge, and `SHORT_END` points at least.
SHORT_SHARE = 0.12
SHORT_END = 18.0
#: Lines on one baseline are made one where they stand within `BASELINE` points of it, are
#: set within `SAME_HEIGHT` of one height, and the gap between them is under this many of
#: their height.
BASELINE = 2.0
SAME_HEIGHT = 2.5
GAP = 3.0
#: A narrow short block stands right under a display, and is its own, where its top is
#: within this many of the body's line heights below the display's lowest block.
UNDER = 3.0
#: A superscript is set below this share of its line's height, its foot this share of the
#: height above the line's foot.
RAISED_HEIGHT = 0.8
RAISED_FOOT = 0.15
#: How far, in points, a margin's number may stand outside the text's edge and still be
#: beside it; how far before its line's first word a column's own number stands, at most;
#: and how many margin numbers a page shows at least for them to be read as its lines'.
MARGIN = 2.0
GUTTER = 30.0
MARGIN_RUN = 3
#: The fewest words a line of the text has, numbers at its ends aside, for its words to
#: set the text's edges.
WORDY = 3

#: A display's label at the start of a legend's first line.
LABEL = re.compile(
    r"^(?:Supplementary\s+|Suppl\.?\s+|Extended\s+Data\s+)?"
    r"(?:Figure|Fig\.?|FIGURE|FIG\.?|Table|TABLE|Scheme|Box|Chart)\s*S?\d+[A-Za-z]?"
    r"(?:\s*[.:|]|\s+[A-Z(]|\s*$)")
#: A label that is a figure's, whose own words above it are its.
FIGURE = re.compile(r"^(?:Supplementary\s+)?(?:Figure|Fig|FIGURE|FIG|Scheme|Chart)\b")
#: A number alone, as a margin numbers a line.
LONE_NUMBER = re.compile(r"^\(?\d{1,5}\)?$")
#: A page's number alone: "12", "Page 12", "12 of 20".
PAGE_NUMBER = re.compile(r"^(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?$", re.IGNORECASE)
#: A line that ends a sentence: on a stop, a bracket or a quotation mark after it, or a
#: superscript citation after the stop.
STOP = re.compile(r"[.!?:;][)\]\"'\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]*$"
                  r"|[.!?]\s*\d{1,3}(?:[,\N{EN DASH}-]\d{1,3})*$")
#: A superscript citation's words: numbers, commas and dashes.
CITATION = re.compile(r"^\d{1,3}(?:[,\N{EN DASH}\N{EM DASH}-]\d{1,3})*,?$")
#: What a superscript citation follows: a word of three letters or more, or a stop.
CITED = re.compile(r"[A-Za-z]{3}[)\].,;:]?$|[.,;:)]$")

_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
#: A box's corners, which poppler gives below zero for text set off the page.
_BOX = r'xMin="(-?[\d.]+)" yMin="(-?[\d.]+)" xMax="(-?[\d.]+)" yMax="(-?[\d.]+)"'
_BLOCK = re.compile(rf"<block {_BOX}>(.*?)</block>", re.S)
_LINE = re.compile(rf"<line {_BOX}>(.*?)</line>", re.S)
_WORD = re.compile(rf"<word {_BOX}>(.*?)</word>", re.S)


class NotRebuilt(Exception):
    """A PDF whose paragraphs are not rebuilt here, and why, said as a sentence's end."""


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    #: Whether it is a citation set as a superscript (`_raised`).
    raised: bool = False


@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    words: list[Word]
    #: The number the PDF prints beside it, in its margin.
    number: int | None = None
    #: Its line counted down its page in reading order, from 1.
    line: int = 0

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def cited(self) -> str:
        """Its words with each superscript citation bracketed after the word before it."""
        out: list[str] = []
        for word in self.words:
            if word.raised and out:
                out[-1] += "[" + word.text.rstrip(",") + "]"
            else:
                out.append(word.text)
        return " ".join(out)

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Block:
    x0: float
    y0: float
    x1: float
    y1: float
    lines: list[Line]

    @property
    def height(self) -> float:
        return sum(line.height for line in self.lines) / len(self.lines)


@dataclass
class Page:
    number: int
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)


@dataclass(frozen=True)
class Row:
    """A line kept, in the order G6 and G14 read them: its page, its line counted down that
    page in reading order, the number the PDF prints beside it, its words, its words with
    superscript citations bracketed, its paragraph's number, and the display it is of, an
    index into `Layout.displays`, or None in the text."""

    page: int
    line: int
    printed: int | None
    text: str
    cited: str
    paragraph: int
    display: int | None = None


@dataclass(frozen=True)
class Layout:
    """A PDF's lines as rebuilt: `rows` in reading order; `displays` the kind of each,
    "figure" or "table"; `furniture` what was taken out, once each; `running` each running
    head and foot taken out, `(page, "head" or "foot", text)`; the number of pages."""

    rows: tuple[Row, ...]
    displays: tuple[str, ...]
    furniture: tuple[str, ...]
    running: tuple[tuple[int, str, str], ...]
    pages: int


# ------------------------------------------------------------------ the program


def program() -> str | None:
    """The pdftotext that gives each word's place: the one `POPPLER` names, else the one on
    PATH; None where there is neither."""
    named = os.environ.get(POPPLER, "").strip()
    return named or shutil.which("pdftotext")


def markup(path: Path) -> tuple[str, str]:
    """What pdftotext writes of `path` with each word's place, and which pdftotext it is.
    Raises `NotRebuilt` where it cannot: none found, Xpdf's, or one that failed."""
    from manuscript_guard.proof.reading import PDFTOTEXT_SECONDS, _pdftotext_name
    from manuscript_guard.reporting.rows import knows_no_bbox

    found = program()
    if found is None:
        raise NotRebuilt("no pdftotext is installed")
    name = _pdftotext_name(found)
    try:
        done = subprocess.run([found, "-bbox-layout", "-enc", "UTF-8", str(path), "-"],
                              capture_output=True, timeout=PDFTOTEXT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        raise NotRebuilt(f"{name} did not answer within {PDFTOTEXT_SECONDS} seconds") from None
    except OSError as exc:
        raise NotRebuilt(f"{found} could not be run ({exc.strerror or exc})") from None
    said = done.stderr.decode("utf-8", errors="replace")
    if done.returncode != 0 and knows_no_bbox(said):
        raise NotRebuilt(f"{name} gives no word's place (-bbox-layout), which only poppler's "
                         f"pdftotext gives; name one in {POPPLER} (docs/install.md)")
    if done.returncode != 0:
        brief = " ".join(said.split())[:200]
        raise NotRebuilt(f"{name} failed on it (exit {done.returncode}"
                         f"{': ' + brief if brief else ''})")
    return done.stdout.decode("utf-8", errors="replace"), name


def parse(text: str) -> list[Page]:
    """The pages poppler's markup holds, each word unescaped and without format characters;
    an empty word, line or block left out."""
    pages = []
    for number, (width, height, body) in enumerate(_PAGE.findall(text), 1):
        page = Page(number, float(width), float(height))
        for *box, inner in _BLOCK.findall(body):
            lines = []
            for *edges, words in _LINE.findall(inner):
                kept = [Word(*map(float, at), _unformatted(html.unescape(said)))
                        for *at, said in _WORD.findall(words)]  # fmt: skip
                kept = [word for word in kept if word.text]
                if kept:
                    lines.append(Line(*map(float, edges), kept))
            if lines:
                page.blocks.append(Block(*map(float, box), lines))
        pages.append(page)
    return pages


def _unformatted(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


# ------------------------------------------------------------------ what pages repeat


def _shape(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.casefold().split()))


def _side(line: Line, page: Page) -> str:
    middle = (line.y0 + line.y1) / 2
    return ("head" if middle < BAND * page.height else
            "foot" if middle > (1 - BAND) * page.height else "")  # fmt: skip


def _running(pages: list[Page]) -> tuple[set[int], list[tuple[int, str, str]], list[str]]:
    """The ids of the running heads and feet and the pages' numbers, each running line
    `(page, side, text)`, and what was taken out, said."""
    gone: set[int] = set()
    numbers = False
    on: dict[tuple[str, str], set[int]] = collections.defaultdict(set)
    where: dict[tuple[str, str], list[tuple[int, Line]]] = collections.defaultdict(list)
    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                side = _side(line, page)
                if not side:
                    continue
                if PAGE_NUMBER.match(line.text.strip()):
                    gone.add(id(line))
                    numbers = True
                    continue
                on[(side, _shape(line.text))].add(page.number)
                where[(side, _shape(line.text))].append((page.number, line))
    least = max(2, math.ceil(RUNNING_SHARE * len(pages)))
    running = []
    for key, seen in on.items():
        if len(seen) >= least:
            for number, line in where[key]:
                gone.add(id(line))
                running.append((number, key[0], line.text))
    said = ["page numbers"] if numbers else []
    said += list(dict.fromkeys(text for _page, _side_, text in running))
    return gone, sorted(running), said


def _margin(page: Page) -> set[int]:
    """The ids of the page's margin numbers, each given to the line on its baseline as the
    number the PDF prints beside it: the numbers alone on their lines that stand outside the
    text's left or right edge, or just before a line of the text on their baseline (a
    column's own numbers, in the gutter, where `MARGIN_RUN` of those at least stand so on
    the page); and a number before a line's first word outside the text's left edge, which
    is taken off it."""
    lines = [line for block in page.blocks for line in block.lines]
    body = [line for line in lines if len(_words(line)) >= WORDY]
    if not body:
        return set()
    # The text's edges, read from its lines' words and not from poppler's blocks: a
    # double-spaced manuscript sets each line in a block of its own, a margin's number
    # sometimes in the same block and the same line as its line's words.
    left = min(_words(line)[0].x0 for line in body)
    right = max(_words(line)[-1].x1 for line in body)
    found: list[tuple[Line, Line | None, bool]] = []
    worded = [line for line in lines if _words(line)]
    for line in lines:
        if LONE_NUMBER.match(line.text):
            outside = line.x1 <= left + MARGIN or line.x0 >= right - MARGIN
            numbers = _beside(line, worded, outside)
            if outside or numbers is not None:
                found.append((line, numbers, outside))
    gone: set[int] = set()
    inside = sum(not outside for _number, _line, outside in found)
    for number, line, outside in found:
        if outside or inside >= MARGIN_RUN:
            gone.add(id(number))
            if line is not None:
                line.number = int(number.text.strip("()"))
    for line in body:
        first, last = line.words[0], line.words[-1]
        if LONE_NUMBER.match(first.text) and first.x1 < left - 1:
            line.number = int(first.text.strip("()"))
            line.words = line.words[1:]
        elif LONE_NUMBER.match(last.text) and last.x0 > right + 1:
            line.number = int(last.text.strip("()"))
            line.words = line.words[:-1]
    return gone


def _words(line: Line) -> list[Word]:
    """A line's words less a number alone at either end, which a margin may number it by."""
    words = line.words
    while words and LONE_NUMBER.match(words[0].text):
        words = words[1:]
    while words and LONE_NUMBER.match(words[-1].text):
        words = words[:-1]
    return words


def _beside(number: Line, body: list[Line], outside: bool) -> Line | None:
    """The line of the text a margin's `number` numbers: on its baseline, the first that
    opens within `GUTTER` points after it; else, where it stands outside the text's edges,
    the nearest after it or before it. None where there is none."""
    middle = (number.y0 + number.y1) / 2
    level = [line for line in body if line.y0 <= middle <= line.y1]
    after = [line for line in level if 0 <= line.x0 - number.x1 <= (
        math.inf if outside else GUTTER)]  # fmt: skip
    if after:
        return min(after, key=lambda line: line.x0)
    before = [line for line in level if line.x1 <= number.x0 + MARGIN]
    if outside and before:
        return max(before, key=lambda line: line.x1)
    return None


def _overlaid(page: Page) -> set[int]:
    """The ids of the lines that repeat an earlier line of the page, word for word, drawn
    over it."""
    seen: dict[str, list[Line]] = collections.defaultdict(list)
    gone = set()
    for block in page.blocks:
        for line in block.lines:
            same = seen[" ".join(line.text.split())]
            if any(abs(other.y0 - line.y0) < max(line.height, OVERLAID)
                   and abs(other.x0 - line.x0) < OVERLAID_ACROSS for other in same):
                gone.add(id(line))
            else:
                same.append(line)
    return gone


def _raised(line: Line) -> None:
    """Each word of the line that is a citation set as a superscript marked: numbers, commas
    and dashes (`CITATION`) set smaller than the line's words and raised above its foot,
    after a word of three letters or more or a stop (`CITED`). A raised number after a unit,
    "m 2", follows no such word."""
    if len(line.words) < 2:
        return
    heights = sorted(word.y1 - word.y0 for word in line.words)
    body = heights[len(heights) // 2]
    foot = max(word.y1 for word in line.words if word.y1 - word.y0 >= 0.9 * body)
    for before, word in zip(line.words, line.words[1:], strict=False):
        if (CITATION.match(word.text) and word.y1 - word.y0 < RAISED_HEIGHT * body
                and word.y1 < foot - RAISED_FOOT * body and not before.raised
                and CITED.search(before.text)):  # fmt: skip
            word.raised = True


# ------------------------------------------------------------------ reading order


def _one_baseline(blocks: list[Block]) -> list[Block]:
    """The blocks with each line made one with the lines on its baseline just right of it,
    where those are lines of blocks of one line or of its own block. Never two lines of
    blocks of several lines, which two columns' lines are."""
    owner = {id(line): block for block in blocks for line in block.lines}
    lines = sorted((line for block in blocks for line in block.lines),
                   key=lambda line: (round(line.y1), line.x0))  # fmt: skip
    gone: set[int] = set()
    for at, line in enumerate(lines):
        if id(line) in gone:
            continue
        for other in lines[at + 1:]:
            if round(other.y1) - round(line.y1) > BASELINE + 1:
                break  # the lines are in order of their foot: none further on is on it
            if id(other) in gone or abs(other.y1 - line.y1) >= BASELINE:
                continue
            block = owner[id(other)]
            if not (len(block.lines) == 1 or block is owner[id(line)]):
                continue
            if (abs(other.height - line.height) < SAME_HEIGHT
                    and 0 <= other.x0 - line.x1 < GAP * line.height):  # fmt: skip
                line.words = [*line.words, *other.words]
                line.x1 = other.x1
                owner[id(line)].x1 = max(owner[id(line)].x1, other.x1)
                if line.number is None:
                    line.number = other.number
                gone.add(id(other))
    kept = []
    for block in blocks:
        block.lines = [line for line in block.lines if id(line) not in gone]
        if block.lines:
            kept.append(block)
    return kept


def ordered(blocks: list[Block]) -> list[Block]:
    """A page's blocks in reading order by where they stand: bands cut by the blocks that
    cross the page's middle, and in each band the left column top to bottom, then the
    right; a block that crosses the middle after those above it."""
    if not blocks:
        return []
    middle = (min(block.x0 for block in blocks) + max(block.x1 for block in blocks)) / 2

    def column(block: Block) -> int:
        return 0 if (block.x0 + block.x1) / 2 < middle else 1

    crossing = sorted((block for block in blocks
                       if block.x0 < middle - CROSSING and block.x1 > middle + CROSSING),
                      key=lambda block: block.y0)  # fmt: skip
    rest = [block for block in blocks if all(block is not other for other in crossing)]
    out: list[Block] = []
    done: set[int] = set()
    for span in crossing:
        above = sorted((block for block in rest
                        if id(block) not in done and block.y0 < span.y0 - 1),
                       key=lambda block: (column(block), block.y0, block.x0))  # fmt: skip
        beside = [block for block in rest if id(block) not in done
                  and all(block is not one for one in above) and block.y0 < span.y1]
        for block in [*above, *sorted([*beside, span], key=lambda b: (b.x0, b.y0))]:
            out.append(block)
            done.add(id(block))
    out += sorted((block for block in rest if id(block) not in done),
                  key=lambda block: (column(block), block.y0, block.x0))  # fmt: skip
    return out


# ------------------------------------------------------------------ paragraphs


def _body_height(pages: list[Page]) -> float:
    counts: collections.Counter[float] = collections.Counter()
    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                counts[round(line.height * 2) / 2] += len(line.words)
    return counts.most_common(1)[0][0] if counts else 10.0


def _usual_width(pages: list[Page]) -> float:
    """The width the text's blocks are set to most often, of the blocks of four lines or
    more; where there are none, as a double-spaced manuscript sets each line in a block of
    its own, of its lines of `WORDY` words or more."""
    widths = collections.Counter(round(block.x1 - block.x0, -1) for page in pages
                                 for block in page.blocks if len(block.lines) >= 4)  # fmt: skip
    if not widths:
        widths = collections.Counter(round(line.x1 - line.x0, -1) for page in pages
                                     for block in page.blocks for line in block.lines
                                     if len(line.words) >= WORDY)  # fmt: skip
    return widths.most_common(1)[0][0] if widths else 250.0


def _kind(block: Block, height: float, width: float) -> str:
    """"legend", "fragment" (narrow and short), "small" or "body"."""
    if LABEL.match(block.lines[0].text):
        return "legend"
    if (block.x1 - block.x0 < NARROW * width and len(block.lines) <= FRAGMENT_LINES
            and all(len(line.text) < SHORT_LINE for line in block.lines)):  # fmt: skip
        return "fragment"
    return "small" if block.height < SMALL * height else "body"


def goes_on(block: Block) -> bool:
    """Whether a body block after one that ended mid-sentence goes on with its paragraph:
    whatever it opens with, "the Marlin surrogate oil" then "(MSO) and CEWAF" on a real
    paper, unless its first line is a heading (`auditing.pdf.heading_title`)."""
    from manuscript_guard.auditing.pdf import heading_title

    return heading_title(block.lines[0].text) is None


def _figure_legend(block: Block) -> bool:
    first = block.lines[0].text
    return bool(LABEL.match(first) and FIGURE.match(first))


def _ends(block: Block, edge: float | None = None) -> list[bool]:
    """For each line of a block, whether a paragraph ends after it: a line that ends short of
    the block's right edge on a stop, or the block's last line. A block of one line, as a
    double-spaced manuscript sets each, is held to `edge`, the right edge of the lines set
    beside it on the page (`_edge`), and ends its paragraph only where it ends short of it on
    a stop."""
    if len(block.lines) == 1 and edge is not None:
        return [_short(block.lines[0], block.x0, edge)]
    last = len(block.lines) - 1
    return [at == last or _short(line, block.x0, block.x1)
            for at, line in enumerate(block.lines)]  # fmt: skip


def _short(line: Line, left: float, right: float) -> bool:
    """Whether `line` ends short of `right` on a stop, the measure running from `left`."""
    return (line.x1 < right - max(SHORT_SHARE * (right - left), SHORT_END)
            and bool(STOP.search(line.text.strip())))  # fmt: skip


def _edge(block: Block, blocks: list[Block]) -> float | None:
    """For a block of one line, the right edge of the lines of the page set at its height
    and beside it, over the same measure (more than half of either's width shared); None
    for a block of several lines, whose own edge is its right one."""
    if len(block.lines) != 1:
        return None
    line = block.lines[0]
    edges = [other.x1 for one in blocks for other in one.lines
             if abs(other.height - line.height) < SAME_HEIGHT
             and min(other.x1, line.x1) - max(other.x0, line.x0)
             > 0.5 * min(other.x1 - other.x0, line.x1 - line.x0)]  # fmt: skip
    return max([block.x1, *edges])


@dataclass
class _Flow:
    """The rows as they are read, and what is open while they are."""

    height: float
    width: float
    rows: list[tuple[Line, int, int, int | None]] = field(default_factory=list)
    displays: list[str] = field(default_factory=list)
    #: The displays met while a paragraph is open across a break: read after it.
    pending: list[tuple[Line, int, int, int | None]] = field(default_factory=list)
    paragraph: int = 0
    #: The paragraph a body block ended in mid-sentence, open across the break.
    open: int | None = None
    #: The display being read, its paragraph, its legend's height, and the page and the
    #: foot of its lowest block so far.
    display: int | None = None
    display_paragraph: int = 0
    display_height: float = 0.0
    display_page: int = 0
    display_foot: float = 0.0
    #: Narrow short blocks since the last paragraph, `(page, line)`: a figure's own words,
    #: if a legend follows.
    held: list[tuple[int, Line]] = field(default_factory=list)

    def sink(self) -> list:
        return self.pending if self.open is not None else self.rows

    def flush_held(self) -> None:
        for page, line in self.held:
            self.paragraph += 1
            self.rows.append((line, page, self.paragraph, None))
        self.held = []

    def legend(self, page: int, block: Block) -> None:
        self.paragraph += 1
        self.display = len(self.displays)
        self.displays.append("figure" if FIGURE.match(block.lines[0].text) else "table")
        self.display_paragraph, self.display_height = self.paragraph, block.height
        self.display_page, self.display_foot = page, block.y1
        sink = self.sink()
        sink += [(line, page, self.paragraph, self.display) for line in block.lines]
        sink += [(line, at, self.paragraph, self.display) for at, line in self.held]
        self.held = []

    def under_display(self, page: int, block: Block) -> bool:
        """Whether `block` stands right under the display being read, or beside it: its top
        within `UNDER` of the body's lines below the display's lowest block, on its page. A
        figure's own words stand under its drawing, further down."""
        return (self.display is not None and page == self.display_page
                and block.y0 <= self.display_foot + UNDER * self.height)  # fmt: skip

    def of_display(self, kind: str, block: Block) -> bool:
        if self.display is None:
            return False
        sized = (abs(block.height - self.display_height) < LEGEND_SIZE
                 and self.display_height < self.height - SMALLER)  # fmt: skip
        return kind in ("fragment", "small") or sized

    def body(self, page: int, block: Block, kind: str, edge: float | None = None) -> None:
        """A block of the text: its lines, a paragraph ending after each line `_ends` says
        does; on the paragraph left open by the block before, where it goes on with it
        (`goes_on`); and the displays met while that paragraph was open, after the first
        paragraph that ends. `edge` is a block of one line's measure (`_edge`)."""
        self.flush_held()
        self.display = None
        joined = self.open is not None and kind == "body" and goes_on(block)
        if joined:
            current = self.open
        else:
            self.rows += self.pending
            self.pending = []
            self.paragraph += 1
            current = self.paragraph
        last = current
        ends = _ends(block, edge)
        ended = ends[-1] if edge is not None else STOP.search(block.lines[-1].text.strip())
        for at, (line, end) in enumerate(zip(block.lines, ends, strict=True)):
            self.rows.append((line, page, current, None))
            last = current
            if end:
                self.paragraph += 1
                current = self.paragraph
                if at < len(block.lines) - 1 or ended:
                    # The displays met while the paragraph went on, read after it.
                    self.rows += self.pending
                    self.pending = []
        self.open = last if kind == "body" and not ended else None
        if self.open is None:
            self.rows += self.pending
            self.pending = []

    def read(self, page: int, block: Block, figure_next: bool = False,
             edge: float | None = None) -> None:
        """`block` read where it stands: a legend opens a display; a block of the display
        being read goes to it; a narrow short one is held, for the legend of a figure it may
        stand above (`figure_next`: the next block that is not one is a figure's legend);
        any other is the text's."""
        kind = _kind(block, self.height, self.width)
        if kind == "legend":
            self.legend(page, block)
        elif kind == "fragment" and figure_next and not self.under_display(page, block):
            self.held += [(page, line) for line in block.lines]
        elif self.of_display(kind, block):
            self.sink().extend((line, page, self.display_paragraph, self.display)
                               for line in block.lines)  # fmt: skip
            self.display_foot = max(self.display_foot, block.y1)
        elif kind == "fragment":
            self.held += [(page, line) for line in block.lines]
        else:
            self.body(page, block, kind, edge)


def rebuilt(text: str) -> Layout:
    """The PDF poppler's markup `text` gives, its lines rebuilt (see the module's
    docstring)."""
    pages = parse(text)
    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                _raised(line)
    gone, running, furniture = _running(pages)
    numbered = False
    for page in pages:
        margin = _margin(page)
        numbered = numbered or bool(margin)
        gone |= margin | _overlaid(page)
    if numbered:
        furniture.append("the margin's line numbers")
    flow = _Flow(_body_height(pages), _usual_width(pages))
    for page in pages:
        blocks = []
        for block in page.blocks:
            block.lines = [line for line in block.lines if id(line) not in gone]
            if block.lines:
                blocks.append(block)
        counted = 0
        read = ordered(_one_baseline(blocks))
        kinds = [_kind(block, flow.height, flow.width) for block in read]
        for at, block in enumerate(read):
            for line in block.lines:
                counted += 1
                line.line = counted
            after = next((one for one, kind in zip(read[at + 1:], kinds[at + 1:], strict=True)
                          if kind != "fragment"), None)  # fmt: skip
            flow.read(page.number, block, after is not None and _figure_legend(after),
                      _edge(block, read))
    flow.flush_held()
    flow.rows += flow.pending
    rows = tuple(Row(page, line.line, line.number, " ".join(line.text.split()),
                     " ".join(line.cited.split()), paragraph, display)
                 for line, page, paragraph, display in flow.rows)  # fmt: skip
    return Layout(rows, tuple(flow.displays), tuple(dict.fromkeys(furniture)),
                  tuple(running), len(pages))


def read_layout(path: Path) -> tuple[Layout, str]:
    """`path`'s lines rebuilt, and which pdftotext read it. Raises `NotRebuilt`."""
    text, name = markup(path)
    layout = rebuilt(text)
    if not layout.rows:
        raise NotRebuilt(f"{name} read no word's place in it")
    return layout, name


__all__ = ["POPPLER", "Layout", "NotRebuilt", "Row", "markup", "ordered", "parse",
           "program", "read_layout", "rebuilt"]
