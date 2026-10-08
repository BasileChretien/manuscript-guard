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

**The reading's rules are the whole of what this reader offers in place of a check**, and they
are stated below: what is read on each page, what each line becomes, what is counted. What those
rules refuse and what they let through follows from them, and is pinned in the tests DESIGN.md's
Known gaps names rather than written out here.

The first version dropped whatever did not match: the parenthetical
under two items of SANRA's own form vanished from the profile, a wrapped statement would have
been cut at the line end, and an item printed with one option would have disappeared — each
silently, and each with a profile that claimed every statement was there. So:

The rules it reads by are below, under "What is read" and the two headings after it, stated once
rather than twice.

**What is checked, and what is not.** The reader's output is its input, read line by line, so
there is nothing here to compare the items against: the profile says so in as many words rather
than claiming a verbatim check it cannot perform. What stands in for one is the reading's own
rules, and they are the whole of it.

**What is read.** On each page of the recipe's `pages`, the lines from the first numbered heading
to a line equal to `stop_at`, or to the end of that page. A line above that heading is passed
over — it is where a form prints its title and the rater's instructions — and so is every line
after `stop_at` on that page. Each page is read afresh, so a `stop_at` on one does not end the
next.

**What each line becomes.** A line opening with a number and a bracket starts an item. A line
whose text is followed by two spaces or more and a one- or two-digit number at its end is one of
that item's options. The first non-blank unscored line under a heading, before any option, is
that item's clarification. A blank line is skipped. Any other line is a `RecipeError` naming it.

**What is counted.** An item read with fewer than `min_options` options is refused, once any item
has been read anywhere in the document. The item numbers must run from one without a gap. `items`
is compared with how many items were read, and `options` with how many options each item has —
each only if the recipe states it.

That is all of it. Which misprints and which wrapped lines those rules refuse, which they write
wrongly, and which they pass over, follows from them; the cases are pinned in the tests
DESIGN.md's Known gaps names, because a shape is exact in a test and has not stayed exact in a
paragraph. A recipe for a new form states its counts and has its first profile read against the
published form once, by eye.
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
