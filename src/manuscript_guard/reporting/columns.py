"""Reading a checklist laid out as columns on a PDF page.

ARRIVE 2.0 publishes its two sets side by side on one page and offers no Word version, so
there is no table structure to read. What there is instead is a rigid visual grid, and
`pdftotext -layout` preserves it: every line holds a slice of the left set and a slice of
the right one, and within each set the topic, the item number and the text occupy fixed
character ranges.

So the page is cut into columns, then each column into its own topic / number / text
sub-columns, discovered from the line that starts each item rather than hardcoded. Topic
words wrap into the left margin of continuation lines — "Inclusion and / exclusion /
criteria" — which is why continuation text is taken from the text sub-column only, and the
leftover margin is appended to the topic.

This is more fragile than reading a table and is treated as such: the extraction is
verified against the same de-columnised text, so an item assembled wrongly still fails.
That is a weaker guarantee than the .docx path, and it is recorded as one.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.reporting.transcribe import Item, RecipeError

# "Study design    1    For each experiment, provide brief details ..."
ITEM_LINE = re.compile(r"^(?P<topic>.{0,34}?)\s{2,}(?P<id>\d{1,2})\s{2,}(?P<text>\S.*)$")


@dataclass(frozen=True)
class ColumnRecipe:
    document: str
    pages: tuple[int, ...]
    column_split: int
    min_text_words: int = 4


def page_text(path: Path, page: int) -> str:
    if shutil.which("pdftotext") is None:
        raise RecipeError(
            "reading a column-laid-out PDF needs poppler's pdftotext; install it, or "
            "supply the checklist in another format"
        )
    finished = subprocess.run(
        ["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(path), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if finished.returncode != 0:
        raise RecipeError(f"pdftotext failed on {path.name}: {finished.stderr.strip()[:200]}")
    return finished.stdout


def split_columns(text: str, at: int) -> tuple[str, str]:
    left, right = [], []
    for line in text.splitlines():
        left.append(line[:at].rstrip())
        right.append(line[at:].rstrip())
    return "\n".join(left), "\n".join(right)


def parse_column(block: str, min_text_words: int) -> list[Item]:
    """Items in one column. Continuation lines are folded into the item above them."""
    items: list[Item] = []
    text_at = 0
    current: Item | None = None

    for line in block.splitlines():
        if not line.strip():
            continue
        match = ITEM_LINE.match(line)
        if match and match.group("id"):
            current = Item(
                id=match.group("id"),
                topic=match.group("topic").strip(),
                text=match.group("text").strip(),
            )
            text_at = match.start("text")
            items.append(current)
            continue

        if current is None:
            continue

        # Continuation. Text lives in the text sub-column; anything to its left is the
        # topic wrapping, not part of the recommendation.
        margin = line[:text_at].strip()
        body = line[text_at:].strip()
        if margin:
            current.topic = f"{current.topic} {margin}".strip()
        if body:
            current.text = f"{current.text} {body}".strip()

    return [i for i in items if len(i.text.split()) >= min_text_words]


OPENING_WORDS = 8


def opening(text: str, words: int = OPENING_WORDS) -> str:
    return " ".join(text.split()[:words])


def transcribe_columns(path: Path, recipe: ColumnRecipe) -> tuple[list[Item], str]:
    """Items from a column-laid-out PDF, and the raw page text to verify openings against.

    Only each item's opening clause is verified, not its whole text. A wrapped item is not
    contiguous in the raw page: topic words wrap into the left margin and land *between*
    the item's own text fragments, so a full-text match would fail on every multi-line item
    however correct the extraction. The opening clause always sits alone on the item's first
    line, so matching it confirms the item begins where the parser thinks it does and that
    the column was cut in the right place.

    This is weaker than the .docx path, where the whole item text is verified. Said plainly
    because it should not be mistaken for the same guarantee.
    """
    items: list[Item] = []
    haystack: list[str] = []
    for page in recipe.pages:
        raw = page_text(path, page)
        haystack.append(re.sub(r"\s+", " ", raw))
        left, right = split_columns(raw, recipe.column_split)
        for block in (left, right):
            items.extend(parse_column(block, recipe.min_text_words))
    if not items:
        raise RecipeError(f"{path.name}: no items found on pages {recipe.pages}")

    seen: set[str] = set()
    unique = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    return unique, " ".join(haystack)
