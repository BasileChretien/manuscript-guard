"""A rating scale laid out as numbered items with scored options, in a PDF.

SANRA is the case this exists for. A narrative review has no reporting guideline — PRISMA is
for systematic reviews — and the instrument editors and reviewers actually score one with is
published as a one-page form: numbered items, each followed by the statements a rater chooses
between, with the score at the right-hand end of each line.

    1) Justification of the article's importance for the readership

    The importance is not justified.                                        0
    The importance is alluded to, but not explicitly justified.             1
    The importance is explicitly justified.                                 2

That is neither a Word table nor two columns of a checklist, so neither of the other readers
can read it, and the alternative — retyping six items and eighteen statements — is the one
thing this package exists to refuse.

What is weaker here than in a Word table, and said so in the profile: an item's own name and
each of its statements are checked verbatim against the page text they were read from, which
catches a statement assembled out of two lines but not a page whose layout was misread from
the start. A rating scale is not a reporting checklist either: its items are what a reviewer
scores, not what a journal requires to be reported, and `applies_to` in the recipe is where
that belongs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.reporting.transcribe import Item, RecipeError

#: "1) Justification of the article's importance for the readership". The number is the
#: item's own, as the scale prints it, because that is what a rater and an editor refer to.
HEADING = re.compile(r"^\s*(?P<id>\d{1,2})\)\s+(?P<topic>\S.*?)\s*$")

#: "The importance is not justified.          0" — a statement, then its score at the end of
#: the line. Two spaces at least, so a sentence that merely ends in a number is not an option.
OPTION = re.compile(r"^\s*(?P<statement>\S.*?)\s{2,}(?P<score>\d{1,2})\s*$")


@dataclass(frozen=True)
class ScaleRecipe:
    """Where one scale's items are: which pages, and how few options is too few."""

    document: str
    pages: tuple[int, ...]
    #: An item printed with fewer options than this is a heading the reader has mistaken for
    #: one — a section title, or a numbered sentence in the instructions above the scale.
    min_options: int = 2


def parse_scale(text: str, *, min_options: int = 2) -> list[Item]:
    """The items on one page of a scale, each with its scored options in its text."""
    items: list[Item] = []
    heading: re.Match[str] | None = None
    options: list[tuple[str, str]] = []

    def flush() -> None:
        if heading is None:
            return
        if len(options) >= min_options:
            items.append(
                Item(
                    id=heading.group("id"),
                    topic=heading.group("topic"),
                    text=" ".join(f"{score} {statement}" for statement, score in options),
                    # The statements again, apart: the text carries them with their scores,
                    # and taking the scores off a joined string would cut any statement that
                    # holds a number of its own. Nothing but verification reads this.
                    extras={"statements": [statement for statement, _score in options]},
                )
            )

    for line in text.splitlines():
        found = HEADING.match(line)
        if found is not None:
            flush()
            heading, options = found, []
            continue
        if heading is None:
            continue
        option = OPTION.match(line)
        if option is not None:
            options.append((option.group("statement"), option.group("score")))
    flush()
    return items


def transcribe_scale(path: Path, recipe: ScaleRecipe) -> tuple[list[Item], str]:
    """Apply a scale recipe to a PDF. Returns the items and the text they were read from."""
    from manuscript_guard.reporting.columns import page_text

    pages = [page_text(path, page) for page in recipe.pages]
    items: list[Item] = []
    for text in pages:
        items.extend(parse_scale(text, min_options=recipe.min_options))
    if not items:
        raise RecipeError(
            f"{path.name}: no numbered item with scored options on page(s) "
            f"{', '.join(str(p) for p in recipe.pages)}; the recipe does not fit this document"
        )
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise RecipeError(
                f"{path.name}: item {item.id} appears twice; the recipe reads a page it should not"
            )
        seen.add(item.id)
    return items, "\n".join(pages)
