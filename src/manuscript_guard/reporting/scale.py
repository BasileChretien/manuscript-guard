"""A rating scale laid out as numbered items with scored options, in a PDF.

SANRA is the case this exists for. A narrative review has no reporting guideline — PRISMA is
for systematic reviews — and the instrument editors and reviewers score one with is published
as a one-page form: numbered items, each with a clarifying line under some of the titles, then
the statements a rater chooses between with the score at the right-hand end of each line. Laid
out, with an invented item rather than a published one, since no transcribed item text is
committed here:

    3) Clarity of the thing described

    (e.g., a line some forms print under the title to explain the item)

    The thing is not described.                                                 0
    The thing is described in passing.                                          1
    The thing is described plainly.                                             2

That is neither a Word table nor two columns of a checklist, so neither of the other readers
can read it, and the alternative — retyping six items and eighteen statements — is the one
thing this package exists to refuse.

**A line is placed, or the reading stops where a count can see it** — which is the whole of
what this reader offers in place of a check, and less than it sounds: see the end of this
docstring, and DESIGN.md's Known gaps, for what no count sees.

The first version dropped whatever did not match: the parenthetical
under two items of SANRA's own form vanished from the profile, a wrapped statement would have
been cut at the line end, and an item printed with one option would have disappeared — each
silently, and each with a profile that claimed every statement was there. So:

* a line directly under a heading, before any option, is that item's clarification, which is
  what the parenthetical is, and is kept;
* any *other* line that is neither a heading nor an option is a `RecipeError` naming it —
  anywhere below the first heading of its page, since above that heading every line is passed
  over as the form's title and the rater's instructions;
* an item with fewer than `min_options` options is a heading mistaken for one while no item
  has been read yet, anywhere in the document — the rater's numbered instructions sit above
  the scale — and a `RecipeError` once the scale has started;
* the item numbers must run from one without a gap, and a recipe may state how many items and
  how many options each has, which the transcription is then held to.

**What is checked, and what is not.** The reader's output is its input, read line by line, so
there is nothing here to compare the items against: the profile says so in as many words
rather than claiming a verbatim check it cannot perform. What stands in for one is that a line
is placed or the reading stops — within two limits, both narrower than that sentence sounds.

**The first is the page.** Every line before the first numbered heading *of each page* is passed
over, because that is where a form prints its title and the rater's instructions. The line is
lost whatever the counts say; whether its loss is noticed afterwards is another matter. A
statement whose second line sits at the top of the next page goes through **in silence** where
the score is on the statement's own first line and the statement is its item's last — the shape
the test pins. Anywhere else the counts or the line rules catch what is left: a wrap before the
item's other scored lines leaves the item an option short, a wrapped first statement leaves it
with none, and a statement after the first is refused outright as a line after that item's
options.

**The second is what a count can see.** `options` refuses a dropped option, an extra one read
from a running foot, and an item whose scored lines carry on to the next page; `items` refuses a
scale read short. No count sees a wrapped line, because a wrap changes nothing's number: a title
running onto a second line is read as a title and a clarification, and a first statement whose
score sits on its second line as a clarification and a shortened first option — both with
SANRA's own counts stated. Elsewhere on a page a wrapped line is refused by the line rules, not
by a count: any statement after the first, a first statement with its score on its own line, and
any wrap under an item that already carries a clarifying line.

DESIGN.md's Known gaps carries the cases, and a recipe for a new form states its counts and has
its first profile read against the form once, by eye. Two limits, then: the page, which no count
reaches, and what a count can see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.reporting.transcribe import Item, RecipeError

#: "1) Clarity of the thing described". The number is the item's own, as the scale prints it,
#: because that is what a rater and an editor refer to.
HEADING = re.compile(r"^\s*(?P<id>\d{1,2})\)\s+(?P<topic>\S.*?)\s*$")

#: "The thing is not described.          0" — a statement, then its score at the end of the
#: line. Two spaces at least, so a sentence that merely ends in a number is not an option.
#: Where a
#: build of pdftotext leaves one space, the line is refused wherever an option is expected, and
#: read as the item's clarification when it is the first line under a title and the recipe states
#: no option count: Known gaps carries that case.
OPTION = re.compile(r"^\s*(?P<statement>\S.*?)\s{2,}(?P<score>\d{1,2})\s*$")

#: What a scale's profile records in place of a verification, because there is none to record.
#: Four sentences, because which is true depends on the counts the recipe states, and one string
#: for every recipe claimed more of some than was done. What each count buys:
#:
#: * `options` refuses a dropped option, an extra one read from a running foot, and an item whose
#:   scored lines carry on to the next page;
#: * `items` refuses a scale read short — a `stop_at` line printed before the last item, a page
#:   the recipe's `pages` leaves out;
#: * neither sees a wrapped line, because a wrap changes nothing's number, nor a statement's
#:   second line at the top of a later page, which is passed over whatever the counts say.
#:
#: "May not be caught" rather than "is not", because the line rules refuse a good deal with no
#: counts at all: an unscored line after an item's options, a second unscored line, too few
#: options once the scale has started, and a gap in the numbering. DESIGN.md's Known gaps
#: carries the cases.
_READ = "read line by line from the published form"
_NO_CHECK = "no check independent of the reader, and none of the item text against anything else"
VERIFICATION_BOTH = f"{_READ}, held to the item and option counts the recipe states; {_NO_CHECK}"
VERIFICATION_ITEMS_ONLY = (
    f"{_READ}, held to the item count the recipe states and to no option count, so a dropped or "
    f"invented option may not be caught; {_NO_CHECK}"
)
VERIFICATION_OPTIONS_ONLY = (
    f"{_READ}, held to the option count the recipe states and to no item count, so a scale read "
    f"short may not be caught; {_NO_CHECK}"
)
VERIFICATION_NEITHER = (
    f"{_READ}, held to no item or option count, so a dropped option or a scale read short may "
    f"not be caught; {_NO_CHECK}"
)


def verification_for(items: int | None, options: int | None) -> str:
    """Which of the four sentences is true of a recipe stating these counts."""
    if items is not None and options is not None:
        return VERIFICATION_BOTH
    if items is not None:
        return VERIFICATION_ITEMS_ONLY
    if options is not None:
        return VERIFICATION_OPTIONS_ONLY
    return VERIFICATION_NEITHER


@dataclass(frozen=True)
class ScaleRecipe:
    """Where one scale's items are, and what the transcription is held to."""

    document: str
    pages: tuple[int, ...]
    #: A numbered line with fewer options than this, before the scale has started, is one of
    #: the rater's instructions rather than an item.
    min_options: int = 2
    #: How many items the form prints, when the recipe says. A form that has been revised
    #: under a pinned checksum cannot reach this, but a recipe aimed at the wrong pages can.
    items: int | None = None
    #: How many options each item carries, when every item carries the same number.
    options: int | None = None
    #: The line where the items end, as the form prints it: SANRA's "Sumscore" box sits under
    #: the last item. Without it the reader refuses that line, which is the right default — a
    #: line it does not understand may be a statement that wrapped — so the boundary is the
    #: recipe's to state rather than the reader's to guess.
    stop_at: str | None = None


@dataclass
class _Reading:
    """One item being read, and the line it started on, for an error that names its place."""

    heading: re.Match[str]
    line_number: int
    clarification: str = ""
    options: tuple[tuple[str, str], ...] = ()


def parse_scale(
    text: str,
    *,
    min_options: int = 2,
    options: int | None = None,
    stop_at: str | None = None,
    started: bool = False,
) -> list[Item]:
    """The items on one page of a scale. Raises rather than drop a line it cannot place, except
    above the first heading of the page, where every line is passed over.

    That exception is the form's title and the rater's instructions, and it is also why a
    statement's second line at the top of a later page is lost without a word.

    `started` says whether an item has been read already, on an earlier page of the same form.
    An item with too few options is then refused rather than passed over as one of the rater's
    numbered instructions. Without it the rule "a numbered line with too few options is one of
    the rater's instructions, until the scale has started" began again on every page, so a last
    item alone at the top of a second page was passed over in silence.
    """
    items: list[Item] = []
    reading: _Reading | None = None

    def finish(current: _Reading) -> None:
        if len(current.options) < min_options:
            if not items and not started:
                return  # the rater's instructions, above the scale
            raise RecipeError(
                f"line {current.line_number}: item {current.heading.group('id')} "
                f"({current.heading.group('topic')[:40]}) has "
                f"{len(current.options)} scored option(s), fewer than the {min_options} a scale "
                f"item is read as having; the recipe does not fit this document"
            )
        if options is not None and len(current.options) != options:
            raise RecipeError(
                f"line {current.line_number}: item {current.heading.group('id')} has "
                f"{len(current.options)} options, and the recipe says every item has {options}"
            )
        spoken = " ".join(f"{score} {statement}" for statement, score in current.options)
        items.append(
            Item(
                id=current.heading.group("id"),
                topic=current.heading.group("topic"),
                text=f"{current.clarification} {spoken}".strip(),
                # The parts again, apart: the text joins them for a reader, and taking the
                # scores off a joined string would cut a statement at its own number.
                extras={
                    "clarification": current.clarification,
                    "statements": [statement for statement, _score in current.options],
                    "scores": [score for _statement, score in current.options],
                },
            )
        )

    for number, line in enumerate(text.splitlines(), start=1):
        if stop_at is not None and line.strip() == stop_at:
            break
        found = HEADING.match(line)
        if found is not None:
            if reading is not None:
                finish(reading)
            reading = _Reading(heading=found, line_number=number)
            continue
        if not line.strip():
            continue
        if reading is None:
            continue  # the form's title and the rater's instructions, above the first item
        option = OPTION.match(line)
        if option is not None:
            reading.options = (*reading.options, (option.group("statement"), option.group("score")))
            continue
        if reading.options:
            raise RecipeError(
                f"line {number}: {line.strip()[:60]!r} comes after item "
                f"{reading.heading.group('id')}'s options and is neither a heading nor an "
                f"option; a statement that wrapped, or a footer, would be written wrong"
            )
        if reading.clarification:
            raise RecipeError(
                f"line {number}: item {reading.heading.group('id')} has a second unscored line, "
                f"{line.strip()[:60]!r}; the recipe reads one clarification per item"
            )
        reading.clarification = line.strip()
    if reading is not None:
        finish(reading)
    return items


def transcribe_scale(path: Path, recipe: ScaleRecipe) -> tuple[list[Item], str]:
    """Apply a scale recipe to a PDF. Returns the items and the text they were read from."""
    from manuscript_guard.reporting.columns import page_text

    pages = [page_text(path, page) for page in recipe.pages]
    items: list[Item] = []
    for number, text in zip(recipe.pages, pages, strict=True):
        try:
            items.extend(
                parse_scale(
                    text,
                    min_options=recipe.min_options,
                    options=recipe.options,
                    stop_at=recipe.stop_at,
                    started=bool(items),
                )
            )
        except RecipeError as refused:
            # `parse_scale` counts lines within the page it was given, so on a form of several
            # pages "line 12" named two places. The page goes in front here, where it is known.
            raise RecipeError(f"{path.name}, page {number}: {refused}") from refused
    if not items:
        raise RecipeError(
            f"{path.name}: no numbered item with scored options on page(s) "
            f"{', '.join(str(p) for p in recipe.pages)}; the recipe does not fit this document"
        )
    numbers = [item.id for item in items]
    expected = [str(n) for n in range(1, len(numbers) + 1)]
    if numbers != expected:
        raise RecipeError(
            f"{path.name}: the items read are {', '.join(numbers)}, and a scale's run from 1 "
            f"without a gap; a page read twice or an item dropped reads like this"
        )
    if recipe.items is not None and len(items) != recipe.items:
        raise RecipeError(
            f"{path.name}: {len(items)} items read, and the recipe says the form has "
            f"{recipe.items}"
        )
    return items, "\n".join(pages)
