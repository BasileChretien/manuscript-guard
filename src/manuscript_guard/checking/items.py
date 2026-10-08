"""Reading the items a project offers for checking, and giving each one a digest.

The digest is what makes an answer mean something later. A co-author answers about the item as
they saw it: this value, these sentences, this page of this document. If the manuscript changes
afterwards, their "yes" is about text nobody has now, and `checker import` has to be able to say
so. So the digest is taken here, over the item's own content, and travels with the item into the
page and back in the answers.

Evidence is deliberately outside the digest. A page image rendered at another resolution is the
same page; a sentence that changed by one word is not the same sentence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "manuscript-guard/checking/1"
#: Where a project puts them, unless told otherwise.
ITEMS = "checks/items.json"


class ItemsError(Exception):
    """The items file is missing, unreadable, or not what the schema says."""


@dataclass(frozen=True)
class Items:
    """One project's offer of work: the groups, the items, and where they were read from."""

    path: Path
    title: str
    groups: tuple[dict, ...]
    items: tuple[dict, ...]

    @property
    def by_group(self) -> dict[str, tuple[dict, ...]]:
        return {
            str(group["id"]): tuple(
                item for item in self.items if item.get("group") == group["id"]
            )
            for group in self.groups
        }

    @property
    def outstanding(self) -> tuple[dict, ...]:
        """The items a person is actually asked about: those nobody has answered already."""
        return tuple(item for item in self.items if not str(item.get("already") or "").strip())


def _words_of(block: dict) -> dict:
    """One piece of evidence as a reader reads it: its words, not its rendering.

    A quote's text, a table's cells, a text excerpt's lines, a facts table's rows, and the
    caption and note that frame them. Left out: `file`, `img`, `target`, `line` and `mark`,
    which say how it was drawn or where to look, and change nothing a person reads.
    """
    return {
        "kind": block.get("kind"),
        "caption": block.get("caption"),
        "note": block.get("note"),
        "text": block.get("text"),
        "grid": block.get("grid"),
        "row_labels": block.get("row_labels"),
        "rows": block.get("rows"),
        # The texts of a text excerpt, without their line numbers, by the same argument as a
        # sentence's line: a value that moved down a page is the same value.
        "lines": [pair[1] for pair in block.get("lines") or [] if len(pair) > 1],
    }


def digest_of(item: dict) -> str:
    """The item as a co-author sees its words: its own text, not its pictures.

    Keyed on the fields that carry meaning, in a fixed order, so the same item digests the same
    on any machine and a reordered JSON file does not invalidate a co-author's work.

    **The words of the evidence are in it**, because for most groups the evidence *is* the
    question: "Does the quoted passage say this number?" is a question about the passage, and an
    answer recorded against a passage the person never read is the thing this digest exists to
    prevent. The first version left all evidence out, on the argument that "a page re-rendered
    larger is the same page" — true of an image and false of words, and applied to both.

    What stays out, for that same argument: how a piece of evidence was drawn or where to look in
    it — an image's file, a table's outlined cell, a text excerpt's line numbers, the substrings
    to highlight. And a sentence's line number, because the line is where to find the sentence,
    not what it says, and a manuscript gains and loses lines every working day: with the line in
    the digest, adding one paragraph to the Introduction would refuse every answer about every
    sentence below it, none of which had changed.

    Not in it either, deliberately: the group's `ask`. Rewording the question put to a reader
    would otherwise discard every answer in that group, and the questions are fixed prose about
    what a group is, not about any one item. DESIGN.md's Known gaps records it.
    """
    core = {
        "id": item.get("id"),
        "group": item.get("group"),
        "title": item.get("title"),
        "facts": item.get("facts") or [],
        "sentences": [
            {"text": sentence.get("text"), "section": sentence.get("section")}
            for sentence in item.get("sentences") or []
        ],
        "evidence": [_words_of(block) for block in item.get("evidence") or []],
    }
    canonical = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def items_file(project_root: Path, path: Path | None = None) -> Path:
    return path or (project_root / ITEMS)


def load_items(project_root: Path, path: Path | None = None) -> Items:
    """Read and validate a project's items file, and digest every item."""
    from manuscript_guard.contracts._schema import read_structured

    source = items_file(project_root, path)
    if not source.is_file():
        raise ItemsError(
            f"{source} does not exist. A project says what a co-author should check by writing "
            f"it: see contracts/schemas/checking.schema.json, and the checking skill for how a "
            f"project finds its own items."
        )
    try:
        document = read_structured(source) or {}
    except Exception as exc:  # noqa: BLE001 — any unreadable file is one message to the author
        raise ItemsError(f"{source} cannot be read: {exc}") from exc
    return items_from(document, source)


def items_from(document: dict, source: Path) -> Items:
    """Check and digest one items document, wherever it came from.

    The toolkit produces its own and a project writes its own, and both come through here: the
    same schema, the same digest, the same refusals. A producer that got something wrong should
    hear about it in the same words an author would.
    """
    from manuscript_guard.contracts._schema import validate

    if document.get("schema") != SCHEMA:
        raise ItemsError(
            f"{source}: schema is {document.get('schema')!r}, and this reads {SCHEMA!r}"
        )
    report = validate(document, "checking", source)
    if report.findings:
        raise ItemsError(
            f"{source} does not fit the schema:\n  "
            + "\n  ".join(finding.message for finding in report.findings)
        )

    groups = tuple(document.get("groups") or ())
    known = {str(group["id"]) for group in groups}
    items: list[dict] = []
    seen: set[str] = set()
    for item in document.get("items") or ():
        identifier = str(item["id"])
        if identifier in seen:
            raise ItemsError(f"{source}: item {identifier} appears twice")
        seen.add(identifier)
        if item.get("group") not in known:
            raise ItemsError(
                f"{source}: item {identifier} is in group {item.get('group')!r}, which is not "
                f"one of {', '.join(sorted(known))}"
            )
        items.append({**item, "digest": digest_of(item)})

    return Items(
        path=source,
        title=str(document.get("title") or ""),
        groups=groups,
        items=tuple(items),
    )


def evidence_files(items: Items) -> list[tuple[dict, Path]]:
    """Every image an item points at, with the path it resolves to, for the bundle to carry."""
    base = items.path.parent
    found: list[tuple[dict, Path]] = []
    for item in items.items:
        for evidence in item.get("evidence") or ():
            if evidence.get("kind") == "image" and evidence.get("file"):
                found.append((evidence, (base / str(evidence["file"])).resolve()))
    return found


def as_payload(items: Items) -> dict[str, Any]:
    """The items as the page reads them: no file paths, because the files are carried inline."""
    return {
        "title": items.title,
        "groups": [dict(group) for group in items.groups],
        "items": [dict(item) for item in items.items],
    }
