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
* a line that is neither a heading nor an option anywhere else is a `RecipeError` naming it,
  because the only honest reading of a line this reader does not understand is that the recipe
  does not fit the document;
* an item with fewer than `min_options` options is a heading mistaken for one while no item
  has been read yet, anywhere in the document — the rater's numbered instructions sit above
  the scale — and a `RecipeError` once the scale has started;
* the item numbers must run from one without a gap, and a recipe may state how many items and
  how many options each has, which the transcription is then held to.

**What is checked, and what is not.** The reader's output is its input, read line by line, so
there is nothing here to compare the items against: the profile says so in as many words
rather than claiming a verbatim check it cannot perform. What stands in for one is that a line
is placed or the reading stops — as far as the recipe's counts reach, and no further. `items`
and `options` catch whatever changes a number: a dropped option, an extra one read from a
footer, an item continued on the next page. Nothing catches a wrapped line, because wrapping
changes no number: a title running onto a second line, or a first statement whose score sits on
its second line, is read as a title and a clarification with SANRA's own counts stated.
DESIGN.md's Known gaps carries the cases, and a recipe for a new form states its counts and has
its first profile read against the form once, by eye.
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
#: It says what is true and no more: the reader places every line or stops, *where the recipe
#: says how many items and options the form prints*. Without those counts a line can still be
#: filed in the wrong place — a wrapped title, a statement whose score is on the next line —
#: and DESIGN.md's Known gaps carries the cases.
VERIFICATION = (
    "read line by line from the published form, with the item counts the recipe states; no "
    "check independent of the reader, and none of the item text against anything else"
)
#: The same for a recipe that states no counts, where not even a dropped option is caught.
VERIFICATION_UNCOUNTED = (
    "read line by line from the published form, and the recipe states no item or option count, "
    "so a line dropped or read as the wrong thing is not caught either; no check independent of "
    "the reader"
)


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
    """The items on one page of a scale. Raises rather than drop a line it cannot place.

    `started` says whether an item has been read already, on an earlier page of the same form.
    An item with too few options is then refused rather than passed over as one of the rater's
    numbered instructions, which is what "dropped" means in the test that holds this.
    Without it the rule "a numbered line with too few options is one of the rater's
    instructions, until the scale has started" began again on every page, so a last item alone
    at the top of a second page was dropped in silence.
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
    for text in pages:
        items.extend(
            parse_scale(
                text,
                min_options=recipe.min_options,
                options=recipe.options,
                stop_at=recipe.stop_at,
                started=bool(items),
            )
        )
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
