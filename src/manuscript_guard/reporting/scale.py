"""A rating scale laid out as numbered items with scored options, in a PDF.

SANRA is the case this exists for. A narrative review has no reporting guideline — PRISMA is
for systematic reviews — and the instrument editors and reviewers score one with is published
as a one-page form: numbered items, each with a clarifying line under some of the titles, then
the statements a rater chooses between with the score at the right-hand end of each line.

    5) Scientific reasoning

    (e.g., incorporation of appropriate evidence, such as RCTs in clinical medicine)

    The article's point is not based on appropriate arguments.                   0
    Appropriate evidence is introduced selectively.                             1
    Appropriate evidence is generally present.                                  2

That is neither a Word table nor two columns of a checklist, so neither of the other readers
can read it, and the alternative — retyping six items and eighteen statements — is the one
thing this package exists to refuse.

**Every line between the first item and the last is accounted for or the transcription
stops.** The first version of this reader dropped whatever did not match: the parenthetical
under items 5 and 6 of SANRA's own form vanished from the profile, a wrapped statement would
have been cut at the line end, and an item printed with one option would have disappeared —
each silently, and each with a profile that claimed every statement was there. So:

* a line directly under a heading, before any option, is that item's clarification, which is
  what the parenthetical is, and is kept;
* a line that is neither a heading nor an option anywhere else is a `RecipeError` naming it,
  because the only honest reading of a line this reader does not understand is that the recipe
  does not fit the document;
* an item with fewer than `min_options` options is a heading mistaken for one while no item
  has been read yet — the rater's numbered instructions sit above the scale — and a
  `RecipeError` once the scale has started;
* the item numbers must run from one without a gap, and a recipe may state how many items and
  how many options each has, which the transcription is then held to.

**What is checked, and what is not.** The reader's output is its input, read line by line, so
there is nothing here to compare the items against: the profile says so in as many words
rather than claiming a verbatim check it cannot perform. What stands in for one is that
nothing may be dropped, which is weaker than a Word table's item-by-item verification and
stronger than the silence it replaced. DESIGN.md's Known gaps carries this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.reporting.transcribe import Item, RecipeError

#: "1) Justification of the article's importance for the readership". The number is the item's
#: own, as the scale prints it, because that is what a rater and an editor refer to.
HEADING = re.compile(r"^\s*(?P<id>\d{1,2})\)\s+(?P<topic>\S.*?)\s*$")

#: "The importance is not justified.          0" — a statement, then its score at the end of
#: the line. Two spaces at least, so a sentence that merely ends in a number is not an option.
#: Where a build of pdftotext leaves one space the line stops the transcription rather than
#: disappearing from it.
OPTION = re.compile(r"^\s*(?P<statement>\S.*?)\s{2,}(?P<score>\d{1,2})\s*$")

#: What a scale's profile records in place of a verification, because there is none to record.
VERIFICATION = (
    "read line by line from the published form; every line of every item accounted for, "
    "and the scores in the order printed — no check independent of the reader"
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
) -> list[Item]:
    """The items on one page of a scale. Raises rather than drop a line it cannot place."""
    items: list[Item] = []
    reading: _Reading | None = None

    def finish(current: _Reading) -> None:
        if len(current.options) < min_options:
            if not items:
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
