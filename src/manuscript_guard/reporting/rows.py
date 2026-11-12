"""A checklist set as a table in a PDF, read from where each word sits on the page.

Two checklists are published as a PDF of a table whose rows `pdftotext -layout` cannot keep
apart. The EASE SAGER checklist prints each item's number centred against its text, so the
number of a two-line item stands on a line of its own between them, and the first line of
the next item follows the last line of this one with nothing between. The MDAR checklist
prints no numbers at all: each row is a title, then its text, beside a box for the page it
is reported on. Both builds of `pdftotext` read here set those lines in different places, and
Xpdf's sets SAGER's numbers against the wrong items.

So this reader takes each word's position from poppler's `pdftotext -bbox` and reads the
table from those. What it reads by:

**The page.** Words whose middles lie within two points of each other, top to bottom, are one
line. A line is cut into the recipe's `columns` by where each word starts, in points from the
page's left edge. Reading begins after the first line whose words, joined, equal `start_after`,
and ends at the first equal to `stop_at`; a line equal to one of `ignore` is passed over
wherever it is. A word in a column the recipe calls `blank` is refused.

**A heading** is a line with words in the `section` column and nowhere else. A heading that
shares its line with an item's text or number is refused.

**`rows: centred-id`** (SAGER). Each number in the `id` column is centred against its own
text: the run of `text` lines that starts at the first line not yet read, and whose top and
bottom are as far from the number's middle as each other, give or take a point, is that
item's. A run never crosses a heading or a page. The lines on a later page above its first
heading, where no number stands among them, carry on the last item of the page before; that
is a row Word broke across the pages, with its number on the first part. A line no number's
run takes is refused, and so is a number no run is centred on.

**`rows: topics`** (MDAR). The checklist prints no numbers, so the recipe lists each row's
title as printed and gives it an identifier of the recipe's own. A row runs from the line of
the `text` column that equals its title to the next title or heading. Titles are found in the
recipe's order, each once; one not found is refused. Text after a heading and before the next
title is the section's own preamble, and is passed over. Where the recipe names a `marker`,
the line opening the box each row prints in its `form` column, every row must hold exactly one
such line: a title left out of the recipe gives the row above it two, and is refused.

The lines of an item are joined with a space, except after a line that ends in a hyphen,
where they are joined with none: Word sets no hyphen of its own unless asked, so one at the
end of a line is the text's, and here it is always a compound broken at its hyphen. The count
the recipe states in `items` is held, and so is each identifier being used once.

**What is checked.** The items are what the words' positions say, and nothing reads them a
second way: there is no comparison of the text with another extraction. The profile says so.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.reporting.transcribe import Item, RecipeError

#: Words whose vertical middles differ by no more than this, in points, are one line. The
#: lines of a checklist set at ten points stand eleven to eighteen apart.
LINE_TOLERANCE = 2.0

#: How far, in points, a run of lines may be from centred on its number. SAGER's are within a
#: tenth of a point; the next line up or down moves the middle by nine.
CENTRE_TOLERANCE = 1.0

#: The roles a column can play. `form` holds the box a row leaves for the page it is reported
#: on, read only for the recipe's `marker`.
ROLES = ("section", "id", "text", "form", "blank")
ROW_RULES = ("centred-id", "topics")

#: A SAGER number: "1", "3a", "12b".
ITEM_ID = re.compile(r"\d{1,3}[a-z]?")

_WORD = re.compile(
    r'<word xMin="(?P<x0>[-\d.]+)" yMin="(?P<y0>[-\d.]+)" xMax="(?P<x1>[-\d.]+)" '
    r'yMax="(?P<y1>[-\d.]+)">(?P<text>[^<]*)</word>'
)

VERIFICATION = {
    "centred-id": (
        "read from where each word sits on the page (poppler's pdftotext -bbox), each item's "
        "lines those centred on its number; held to the item count the recipe states; the text "
        "is compared with no other reading of the page"
    ),
    "topics": (
        "read from where each word sits on the page (poppler's pdftotext -bbox), each item "
        "running from its title, as the recipe names it, to the next; held to the item count "
        "the recipe states and to one form box per item; the text is compared with no other "
        "reading of the page"
    ),
}


@dataclass(frozen=True)
class Word:
    x0: float
    top: float
    bottom: float
    text: str

    @property
    def middle(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class Line:
    """One line of a page, cut into the recipe's columns."""

    page: int
    top: float
    bottom: float
    text: str
    cells: dict[str, str]

    @property
    def middle(self) -> float:
        return (self.top + self.bottom) / 2

    def cell(self, role: str) -> str:
        return self.cells.get(role, "")


@dataclass(frozen=True)
class RowsRecipe:
    document: str
    pages: tuple[int, ...]
    #: (role, the x in points where the column starts), left to right, the first at 0.
    columns: tuple[tuple[str, float], ...]
    rows: str
    items: int
    start_after: str | None = None
    stop_at: str | None = None
    ignore: tuple[str, ...] = ()
    #: (identifier, title as printed), for `rows: topics`.
    topics: tuple[tuple[str, str], ...] = ()
    marker: str | None = None

    @classmethod
    def from_layout(cls, document: str, layout: dict) -> RowsRecipe:
        """The recipe's `pdf-rows` keys, checked for what each reading needs."""
        columns = layout.get("columns")
        if not isinstance(columns, dict) or not columns:
            raise RecipeError("a pdf-rows recipe names its `columns`, as role: x")
        unknown = set(columns) - set(ROLES)
        if unknown:
            raise RecipeError(f"unknown column roles: {', '.join(sorted(unknown))}")
        ordered = tuple(sorted(((r, float(x)) for r, x in columns.items()), key=lambda c: c[1]))
        rows = layout.get("rows")
        if rows not in ROW_RULES:
            raise RecipeError(f"`rows` is one of {', '.join(ROW_RULES)}, not {rows!r}")
        needed = {"text", "id"} if rows == "centred-id" else {"text"}
        if layout.get("marker"):
            needed.add("form")
        missing = needed - set(columns)
        if missing or ordered[0][1] != 0:
            raise RecipeError(
                f"`rows: {rows}` needs the columns {', '.join(sorted(needed))}, the first "
                f"starting at 0"
            )
        entries = layout.get("topics") or ()
        if not all(isinstance(e, dict) and e.get("id") and e.get("topic") for e in entries):
            raise RecipeError("each of `topics` is a mapping with an `id` and a `topic`")
        topics = tuple((str(e["id"]), str(e["topic"])) for e in entries)
        if (rows == "topics") != bool(topics):
            raise RecipeError("`topics` goes with `rows: topics`, and only with it")
        if not isinstance(layout.get("items"), int):
            raise RecipeError("a pdf-rows recipe states how many `items` the checklist has")
        return cls(
            document=document,
            pages=tuple(layout.get("pages") or (1,)),
            columns=ordered,
            rows=rows,
            items=layout["items"],
            start_after=layout.get("start_after"),
            stop_at=layout.get("stop_at"),
            ignore=tuple(layout.get("ignore") or ()),
            topics=topics,
            marker=layout.get("marker"),
        )


def page_words(path: Path, page: int) -> list[Word]:
    """Every word of one page with its place, from poppler's `pdftotext -bbox`."""
    from manuscript_guard.reporting.columns import run_pdftotext

    try:
        out = run_pdftotext(path, page, "-bbox")
    except RecipeError as refused:
        if "pdftotext failed on" not in str(refused):
            raise
        # Xpdf's answers -bbox with its usage, which says nothing of the cause.
        raise RecipeError(
            f"pdftotext would not give the place of each word on page {page} of {path.name} "
            f"(-bbox), which reading a checklist laid out as rows needs. Poppler's pdftotext "
            f"gives it; Xpdf's, which Git for Windows puts on PATH, does not"
        ) from refused
    if "<page" not in out:
        raise RecipeError(
            f"pdftotext -bbox gave no page {page} of {path.name}; poppler's pdftotext is needed"
        )
    return [
        Word(
            x0=float(found["x0"]),
            top=float(found["y0"]),
            bottom=float(found["y1"]),
            text=html.unescape(found["text"]),
        )
        for found in _WORD.finditer(out)
    ]


def lines_of(words: list[Word], page: int, columns: tuple[tuple[str, float], ...]) -> list[Line]:
    """The page's words as lines, top to bottom, each cut into columns."""
    groups: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.middle, w.x0)):
        if groups and abs(word.middle - groups[-1][0].middle) <= LINE_TOLERANCE:
            groups[-1].append(word)
        else:
            groups.append([word])
    lines = []
    for group in groups:
        group.sort(key=lambda w: w.x0)
        cells: dict[str, list[str]] = {}
        for word in group:
            role = [r for r, start in columns if word.x0 >= start][-1]
            cells.setdefault(role, []).append(word.text)
        lines.append(
            Line(
                page=page,
                top=min(w.top for w in group),
                bottom=max(w.bottom for w in group),
                text=" ".join(w.text for w in group),
                cells={role: " ".join(parts) for role, parts in cells.items()},
            )
        )
    return lines


def window(pages: list[list[Line]], recipe: RowsRecipe) -> list[Line]:
    """The lines between `start_after` and `stop_at`, with the `ignore` lines taken out."""
    started = recipe.start_after is None
    read: list[Line] = []
    for line in (line for page in pages for line in page):
        if not started:
            started = line.text == recipe.start_after
            continue
        if line.text in recipe.ignore:
            continue
        if recipe.stop_at is not None and line.text == recipe.stop_at:
            return read
        if line.cell("blank"):
            raise RecipeError(
                f"page {line.page}: {line.cell('blank')[:60]!r} stands in a column the recipe "
                f"says is blank"
            )
        read.append(line)
    if not started:
        raise RecipeError(f"no line reads {recipe.start_after!r}, where the recipe starts")
    if recipe.stop_at is not None:
        raise RecipeError(f"no line reads {recipe.stop_at!r}, where the recipe stops")
    return read


def joined(parts: list[str]) -> str:
    """Lines as one text: a space between them, none after a line ending in a hyphen."""
    text = ""
    for part in parts:
        if text and not text.endswith("-"):
            text += " "
        text += part
    return text


def _heading(line: Line) -> str | None:
    """The heading on this line, if it is one; refused where it shares the line."""
    if not line.cell("section"):
        return None
    if line.cell("text") or line.cell("id"):
        raise RecipeError(
            f"page {line.page}: the heading {line.cell('section')[:40]!r} shares its line with "
            f"{(line.cell('id') + ' ' + line.cell('text')).strip()[:40]!r}"
        )
    return line.cell("section").rstrip(":").strip()


def _segments(lines: list[Line]) -> list[tuple[str, list[Line], bool]]:
    """The lines between headings, page by page: (section, lines, opens its page)."""
    segments: list[tuple[str, list[Line], bool]] = []
    section, page = "", None
    for line in lines:
        heading = _heading(line)
        if line.page != page:
            page = line.page
            segments.append((section, [], True))
        if heading is not None:
            section = heading
            segments.append((section, [], False))
            continue
        segments[-1][1].append(line)
    return [s for s in segments if s[1]]


def _centred_runs(section: str, lines: list[Line]) -> list[Item]:
    """The items of one stretch between headings, each number taking the run centred on it."""
    text = [line for line in lines if line.cell("text")]
    numbers = [line for line in lines if line.cell("id")]
    items: list[Item] = []
    start = 0
    for number in numbers:
        identifier = number.cell("id")
        if not ITEM_ID.fullmatch(identifier):
            raise RecipeError(f"page {number.page}: {identifier!r} is not an item's number")
        end = _centred_end(text, start, number.middle)
        if end is None:
            raise RecipeError(
                f"page {number.page}: no run of lines is centred on item {identifier}"
                + (f", from {text[start].cell('text')[:40]!r}" if start < len(text) else "")
            )
        run = [line.cell("text") for line in text[start : end + 1]]
        items.append(Item(id=identifier, topic=section, text=joined(run), section=section))
        start = end + 1
    if start < len(text):
        raise RecipeError(
            f"page {text[start].page}: {text[start].cell('text')[:60]!r} is in no item's run"
        )
    return items


def _centred_end(text: list[Line], start: int, middle: float) -> int | None:
    """The last line of the run from `start` whose top and bottom are centred on `middle`."""
    for end in range(start, len(text)):
        if abs((text[start].top + text[end].bottom) / 2 - middle) <= CENTRE_TOLERANCE:
            return end
    return None


def read_centred(lines: list[Line]) -> list[Item]:
    items: list[Item] = []
    for section, segment, opens_page in _segments(lines):
        carried = opens_page and items and not any(line.cell("id") for line in segment)
        if carried:
            # A row broken across the pages: its number was on the part before the break.
            more = [line.cell("text") for line in segment if line.cell("text")]
            last = items[-1]
            items[-1] = Item(id=last.id, topic=last.topic, text=joined([last.text, *more]),
                             section=last.section)
            continue
        items.extend(_centred_runs(section, segment))
    return items


def read_topics(lines: list[Line], recipe: RowsRecipe) -> list[Item]:
    """Each row from its title to the next, and one form box in each."""
    topics = list(recipe.topics)
    rows: list[tuple[str, str, str, Line, list[str]]] = []
    current: list[str] | None = None
    section = ""
    for line in lines:
        heading = _heading(line)
        if heading is not None:
            section, current = heading, None
            continue
        cell = " ".join(line.cell("text").split())
        if topics and cell == topics[0][1]:
            identifier, title = topics.pop(0)
            current = []
            rows.append((identifier, title, section, line, current))
        elif cell and current is not None:
            current.append(cell)
    if topics:
        raise RecipeError(
            f"the title {topics[0][1]!r} ({topics[0][0]}) is not found where the recipe puts it"
        )
    if recipe.marker:
        _one_box_each(lines, rows, recipe.marker)
    for identifier, title, _section, _line, text in rows:
        if not text:
            raise RecipeError(f"{identifier} ({title}) has no text under its title")
    return [
        Item(id=identifier, topic=title, text=joined(text), section=section)
        for identifier, title, section, _line, text in rows
    ]


def _one_box_each(lines: list[Line], rows: list, marker: str) -> None:
    """Every row holds one line opening with `marker`, and every such line is in a row.

    A row reaches from half a line above its title, since a box of two lines is centred on a
    title of one, to where the next row or heading reaches."""
    starts = [
        ((line.page, line.top - (line.bottom - line.top) / 2), identifier)
        for identifier, _title, _section, line, _text in rows
    ] + [((line.page, line.top), None) for line in lines if _heading(line) is not None]
    starts.sort(key=lambda s: s[0])
    held = {identifier: 0 for identifier, *_rest in rows}
    for line in lines:
        if not line.cell("form").startswith(marker):
            continue
        before = [owner for place, owner in starts if place <= (line.page, line.middle)]
        if not before or before[-1] is None:
            raise RecipeError(f"page {line.page}: a form box stands under no item's title")
        held[before[-1]] += 1
    wrong = {identifier: n for identifier, n in held.items() if n != 1}
    if wrong:
        said = ", ".join(f"{identifier} has {n}" for identifier, n in wrong.items())
        raise RecipeError(
            f"each row has one form box ({marker!r}), and {said}; a title the recipe leaves "
            f"out gives the row above it two"
        )


def transcribe_rows(path: Path, recipe: RowsRecipe) -> list[Item]:
    """Apply a pdf-rows recipe to a PDF."""
    pages = [lines_of(page_words(path, page), page, recipe.columns) for page in recipe.pages]
    try:
        lines = window(pages, recipe)
        items = read_centred(lines) if recipe.rows == "centred-id" else read_topics(lines, recipe)
    except RecipeError as refused:
        raise RecipeError(f"{path.name}: {refused}") from refused
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise RecipeError(f"{path.name}: item {item.id} is read twice")
        seen.add(item.id)
    if len(items) != recipe.items:
        raise RecipeError(
            f"{path.name}: {len(items)} items read, and the recipe says the checklist has "
            f"{recipe.items}"
        )
    return items
