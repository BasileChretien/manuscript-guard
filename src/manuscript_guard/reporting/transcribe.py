"""Turning an official checklist document into a profile, reproducibly.

Retyping two hundred checklist items is exactly the kind of work that introduces the errors
this toolkit exists to prevent, so nothing is retyped. A **recipe** describes where the
items sit in the guideline's own document — which table, which columns, how sub-items are
written — and the transcription is a deterministic function of the document plus the
recipe. Re-run it and you get the same profile; re-run it against a revised checklist and
the diff is the revision.

Every transcribed item is then verified to appear in the document's own text, using the
same comparison the literature ledger uses for a quote. A transcription that drifts fails.

The recipe is also the answer to a licensing problem. Several guidelines are published under
terms that forbid redistribution from an MIT repository. For those, the repository ships the
recipe rather than the text: the user downloads the official document themselves and the
profile is generated locally, identical to everyone else's.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# A sub-item written inside the recommendation text, as STROBE and CONSORT do:
# "(a) Indicate the study's design ..."
SUBITEM = re.compile(r"^\((?P<letter>[a-z])\)\s*(?P<rest>.+)$", re.DOTALL)
# An identifier leading its own cell, as CONSORT does: "1a. Title"
LEADING_ID = re.compile(r"^(?P<id>\d+[a-z]?)[.)]?\s+(?P<topic>.*)$")
# An extension item that names itself in its own text. Two forms in the wild:
#   RECORD    "RECORD 1.1: The type of data used should be specified ..."
#   RECORD-PE "4.a: Include details of the specific study design ..."
# The guideline name is optional so both parse with one pattern.
NAMED_ID = re.compile(
    r"(?:(?P<name>[A-Z][A-Za-z-]*)\s+)?(?P<id>\d+(?:\.[0-9a-z]+)+)\s*:\s*",
)

EMPTY = {"", "-", "—", "–", "n/a", "na"}


class RecipeError(Exception):
    """The recipe does not fit the document."""


@dataclass(frozen=True)
class Recipe:
    """Where the items are in one guideline's document."""

    name: str
    document: str
    text_column: int
    id_column: int | None = None
    topic_column: int | None = None
    tables: tuple[int, ...] | None = None          # None = every table
    header_rows: int = 1
    id_in_topic: bool = False                      # "1a. Title" in one cell
    carry_id: bool = False                         # blank id continues the previous item
    subitem_letters: bool = False                  # "(a) ..." makes 1 -> 1a
    named_id: bool = False                         # "RECORD 1.1: ..." carries its own id
    strip_prefix: str | None = None                # regex removed from the start of text
    min_text_words: int = 3

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = set(data) - known - {"schema", "meta"}
        if unknown:
            raise RecipeError(f"unknown recipe keys: {', '.join(sorted(unknown))}")
        tables = data.get("tables")
        return cls(
            **{k: v for k, v in data.items() if k in known and k != "tables"},
            tables=tuple(tables) if tables is not None else None,
        )


@dataclass
class Item:
    id: str
    topic: str
    text: str
    section: str = ""
    extras: dict = field(default_factory=dict)


def cell_text(cell: ET.Element) -> str:
    parts = []
    for para in cell.iter(W + "p"):
        chunk = "".join(t.text or "" for t in para.iter(W + "t"))
        if chunk.strip():
            parts.append(chunk.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def read_tables(path: Path) -> list[list[list[str]]]:
    """Every table in a .docx, as rows of cell strings."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    tables: list[list[list[str]]] = []
    for table in root.iter(W + "tbl"):
        rows = []
        for row in table.iter(W + "tr"):
            cells = [cell_text(c) for c in row.findall(W + "tc")]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def document_text(path: Path) -> str:
    """All the text in the document, for verifying transcribed items against.

    Runs are joined with nothing and paragraphs with a space. Word splits a run wherever
    formatting or spell-check state changes, often mid-word, so joining runs with a space
    turns "study's" into "study 's" and makes a correct transcription look wrong.
    """
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    paragraphs = []
    for para in root.iter(W + "p"):
        chunk = "".join(t.text or "" for t in para.iter(W + "t"))
        if chunk.strip():
            paragraphs.append(chunk.strip())
    return re.sub(r"\s+", " ", " ".join(paragraphs))


def _clean(value: str) -> str:
    return value.strip()


def _is_section(row: list[str], recipe: Recipe) -> bool:
    """A heading row rather than an item.

    The distinction that matters: a row where the *only* filled cell is the text column is
    a continuation of the previous item — STROBE writes item 1(b) that way — while a row
    whose only filled cell is elsewhere is a section heading. Treating both as headings
    silently drops every sub-item, which is what happened first time round: STROBE came out
    with 22 items instead of its 34 rows.
    """
    filled = [index for index, cell in enumerate(row) if _clean(cell)]
    if not filled:
        return True
    if len(row) <= recipe.text_column:
        return True
    if not _clean(row[recipe.text_column]):
        return True
    return len(filled) == 1 and filled[0] != recipe.text_column


def transcribe(path: Path, recipe: Recipe) -> list[Item]:
    """Apply a recipe to a document. Raises RecipeError when it plainly does not fit."""
    tables = read_tables(path)
    if not tables:
        raise RecipeError(f"{path.name} has no tables")
    chosen = (
        [tables[i] for i in recipe.tables if i < len(tables)]
        if recipe.tables is not None
        else tables
    )
    if not chosen:
        raise RecipeError(
            f"{path.name}: recipe selects tables {recipe.tables}, document has {len(tables)}"
        )

    items: list[Item] = []
    section = ""
    topic = ""
    last_id = ""
    header_seen = 0

    for table in chosen:
        for row in table:
            if header_seen < recipe.header_rows and recipe.tables != ():
                header_seen += 1
                if _looks_like_header(row):
                    continue

            if _is_section(row, recipe):
                filled = [_clean(c) for c in row if _clean(c)]
                if filled:
                    section = filled[0]
                continue

            text = _clean(row[recipe.text_column]) if recipe.text_column < len(row) else ""
            if not text or text.lower() in EMPTY:
                continue

            identifier = ""
            if recipe.id_in_topic and recipe.topic_column is not None:
                match = LEADING_ID.match(_clean(row[recipe.topic_column]))
                if match:
                    identifier, topic = match.group("id"), match.group("topic")
                else:
                    topic = _clean(row[recipe.topic_column]) or topic
            else:
                if recipe.topic_column is not None and recipe.topic_column < len(row):
                    topic = _clean(row[recipe.topic_column]) or topic
                if recipe.id_column is not None and recipe.id_column < len(row):
                    identifier = _clean(row[recipe.id_column])

            if recipe.named_id:
                # One cell often holds several extension items, each naming itself:
                # "RECORD 6.1: ... RECORD 6.2: ... RECORD 6.3: ...". Emitting only the
                # first loses two thirds of RECORD.
                for sub_id, sub_text in _split_named(text):
                    if len(sub_text.split()) < recipe.min_text_words:
                        continue
                    items.append(
                        Item(id=sub_id, topic=topic or section, text=sub_text, section=section)
                    )
                continue

            # Footnote markers ride along with the number in some documents: STROBE's
            # item 15 appears as "15*".
            identifier = identifier.strip(" *†‡§.")

            if not identifier and recipe.carry_id:
                identifier = last_id
            if identifier:
                last_id = re.sub(r"[a-z]$", "", identifier)

            if recipe.subitem_letters:
                match = SUBITEM.match(text)
                if match:
                    identifier = f"{last_id or identifier}{match.group('letter')}"
                    text = match.group("rest").strip()

            if recipe.strip_prefix:
                text = re.sub(recipe.strip_prefix, "", text).strip()

            if not identifier or len(text.split()) < recipe.min_text_words:
                continue

            items.append(Item(id=identifier, topic=topic or section, text=text, section=section))

    if not items:
        raise RecipeError(f"{path.name}: the recipe matched no items")
    return _deduplicate(items)


def _split_named(text: str) -> list[tuple[str, str]]:
    """Split a cell holding several self-naming items into (id, text) pairs."""
    marks = list(NAMED_ID.finditer(text))
    if not marks:
        return []
    out = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end() : end].strip()
        if body:
            out.append((mark.group("id"), body))
    return out


def _looks_like_header(row: list[str]) -> bool:
    joined = " ".join(row).lower()
    return any(
        marker in joined
        for marker in ("item no", "item #", "item description", "checklist item", "recommendation")
    )


def _deduplicate(items: list[Item]) -> list[Item]:
    """Keep the first of any repeated identifier, and say nothing: a checklist that
    genuinely repeats an id is a document quirk, not the author's problem."""
    seen: set[str] = set()
    out = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return out


def verify(items: list[Item], path: Path) -> list[str]:
    """Item texts that do not appear in the document. Empty means the transcription holds."""
    from manuscript_guard.literature.sources import contains

    haystack = document_text(path)
    return [item.id for item in items if not contains(haystack, item.text)]
