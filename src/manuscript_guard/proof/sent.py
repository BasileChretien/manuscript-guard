"""What the author sent the journal, as a proof is compared with it.

The document is the one in the submission pack (`build/submission/`), or the one named with
`--against`. It is read the way the build read it when it wrote its record of what each
block printed (`docxtext.blocks`, `roundtrip.write_printed`), from the document itself and
not from the record: the record is a reading of that document, made on the machine that
built it, and the document is what the journal was sent. Each block is a part, and each
cell of a table is a part of its own, with its row's label and its column's header, read as
`audit` reads a table (`text.docx.read_docx_text`). A figure's picture and a displayed
equation are not compared, and the report says so.

What the pack's manifest says of the document, and whether each author's approval is of
the build it came from, is read here too: a proof compared with a document nobody approved
answers the wrong question.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project

TITLE, HEADING, PARAGRAPH, CAPTION, REFERENCE, CELL, OTHER = (
    "title", "heading", "paragraph", "caption", "reference", "cell", "other"
)  # fmt: skip
PACK = "submission"
MANIFEST = "MANIFEST.yaml"
SUPPLEMENTARY = "supplementary.docx"


class NotSent(Exception):
    """There is no document to compare the proof with, or it cannot be read."""


@dataclass(frozen=True)
class Part:
    """A block of what was sent, or a cell of one of its tables."""

    kind: str
    text: str
    #: How the report names it: `the paragraph "The database contained…"`.
    label: str
    #: The paragraph's identifier, which names its source paragraph.
    identifier: str = ""
    #: For a cell: its table, from 1.
    table: int = 0


@dataclass(frozen=True)
class Sent:
    document: Path
    parts: tuple[Part, ...]
    #: What is in the document and not compared: a figure's picture, an equation.
    not_compared: tuple[str, ...]
    #: The digest of the sources it was built from, which an approval names.
    stamp: str | None


def document_for(project: Project, against: Path | None, supplementary: bool) -> Path:
    """The document the proof is compared with: `against`, or the paper (or supplement) in
    the submission pack."""
    if against is not None:
        if not against.is_file():
            raise NotSent(f"{against} does not exist")
        return against
    pack = project.path("build") / PACK
    found = sorted(path for path in pack.glob("*.docx") if path.is_file())
    if supplementary:
        found = [path for path in found if path.name == SUPPLEMENTARY]
    else:
        found = [path for path in found if path.name != SUPPLEMENTARY]
    if len(found) == 1:
        return found[0]
    what = "supplement" if supplementary else "paper"
    if not found:
        raise NotSent(
            f"no {what} in {pack}: run `manuscript-guard submit` to make the pack the journal "
            "was sent, or name the document with --against"
        )
    names = ", ".join(path.name for path in found)
    raise NotSent(f"{pack} holds more than one {what} ({names}); name one with --against")


def read_sent(document: Path) -> Sent:
    from manuscript_guard.docxtext import DocumentUnreadable, blocks
    from manuscript_guard.roundtrip import RoundTripError, stamp_of
    from manuscript_guard.safexml import UnsafeDocument
    from manuscript_guard.text.docx import NotADocx, read_docx_text

    try:
        found = blocks(document)
        tables = read_docx_text(document).tables
        stamp = stamp_of(document)
    except (DocumentUnreadable, NotADocx, RoundTripError, UnsafeDocument, OSError) as exc:
        raise NotSent(f"{document.name} cannot be read as a Word document: {exc}") from exc
    whole = len(tables) == sum(1 for block in found if block.kind == "table")
    parts: list[Part] = []
    skipped: list[str] = []
    counts = {"table": 0, "figure": 0, "equation": 0, REFERENCE: 0}
    for block in found:
        if block.kind:
            counts[block.kind] += 1
            number = counts[block.kind]
            if block.kind == "table" and whole:
                parts += _cells(tables[number - 1], number)
            elif block.kind == "table":
                skipped.append(f"Table {number}: its cells could not be told apart")
            elif block.kind == "figure":
                skipped.append(f"Figure {number}: its picture (its caption is compared)")
            else:
                skipped.append(f"displayed equation {number}")
            continue
        if not block.text.strip():
            continue
        kind = _kind(block.role, block.style)
        if kind == REFERENCE:
            counts[REFERENCE] += 1
        parts.append(Part(kind, block.text, _label(kind, block.text, counts[REFERENCE]),
                          block.names[0] if block.names else ""))  # fmt: skip
    return Sent(document, tuple(parts), tuple(skipped), stamp)


def _kind(role: str, style: str) -> str:
    if style in ("title", "subtitle"):
        return TITLE
    return {"heading": HEADING, "caption": CAPTION, "reference": REFERENCE}.get(
        role, PARAGRAPH if role == "" else OTHER
    )


def _opening(text: str, words: int = 7) -> str:
    said = text.split()
    return " ".join(said[:words]) + ("\N{HORIZONTAL ELLIPSIS}" if len(said) > words else "")


def _label(kind: str, text: str, reference: int) -> str:
    if kind == REFERENCE:
        return f'reference {reference}, "{_opening(text, 5)}"'
    name = {TITLE: "the title", HEADING: "the heading", CAPTION: "the caption",
            PARAGRAPH: "the paragraph", OTHER: "the text"}[kind]  # fmt: skip
    return f'{name} "{_opening(text)}"'


#: A superscript as `read_docx_text` writes it in a cell, `^a^`: printed, it is the letter.
_SCRIPT = re.compile(r"\^([^^\s]*)\^")


def _cells(table, number: int) -> list[Part]:
    """Each cell of a table as a part, named by its row's label and its column's header."""
    header: list[str] = []
    for cell in table[0] if table else ():
        header += [_SCRIPT.sub(r"\1", cell.text)] * max(cell.span, 1)
    parts = []
    for at, row in enumerate(table):
        label_of_row = _SCRIPT.sub(r"\1", row[0].text) if row else ""
        column = 0
        for cell in row:
            text = _SCRIPT.sub(r"\1", cell.text)
            heading = header[column] if column < len(header) else ""
            column += max(cell.span, 1)
            if not text.strip():
                continue
            if at == 0:
                label = f'Table {number}, the header "{_opening(text, 5)}"'
            elif cell is row[0]:
                label = f'Table {number}, the row "{_opening(text, 5)}"'
            else:
                label = (f'Table {number}, row "{_opening(label_of_row, 5)}", column '
                         f'"{_opening(heading, 5)}"')  # fmt: skip
            parts.append(Part(CELL, text, label, table=number))
    return parts


# ---------------------------------------------------------------- the pack and its approvals


def provenance(project: Project, document: Path, stamp: str | None) -> list[str]:
    """What the report says of the document compared with: whether the pack's manifest
    lists it and for which round, whether each author approved its build, and whether the
    source has changed since."""
    said = [_in_pack(project, document)]
    said.append(_approved(project, stamp))
    if stamp is not None:
        from manuscript_guard.gates.review import document_digest

        if document_digest(project) != stamp:
            said.append(
                "The manuscript has changed since this document was built: the source each "
                "correction names is the source as it stands now, which may already hold the "
                "correction."
            )
    return [line for line in said if line]


def _in_pack(project: Project, document: Path) -> str:
    pack = project.path("build") / PACK
    if document.parent.resolve() != pack.resolve():
        return f"It is not the pack's copy in {pack}: it was named with --against."
    try:
        manifest = yaml.safe_load((pack / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return f"The pack has no readable {MANIFEST}, so which round it was is not known."
    if not isinstance(manifest, dict):
        return f"The pack's {MANIFEST} is not a manifest, so which round it was is not known."
    entry = next((item for item in manifest.get("files") or [] if isinstance(item, dict)
                  and item.get("file") == document.name), None)  # fmt: skip
    round_ = manifest.get("submission", "a submission")
    on = manifest.get("assembled_on", "an unrecorded day")
    if entry is None:
        return f"The pack's {MANIFEST} does not list {document.name}."
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    if entry.get("sha256") != digest:
        return (f"Its bytes are not those the pack's {MANIFEST} lists for it: it is not the "
                "file the pack held when it was assembled.")  # fmt: skip
    return f"It is the file the pack's {MANIFEST} lists, for the {round_}, assembled on {on}."


def _approved(project: Project, stamp: str | None) -> str:
    from manuscript_guard.approvals import DIRECTORY, authors_of, name_of, slug_of

    authors = authors_of(project)
    if not authors:
        return ""
    if stamp is None:
        return "It carries no build stamp, so no approval can be matched to it."
    missing, other = [], []
    for author in authors:
        path = project.root / DIRECTORY / f"{slug_of(author)}.yaml"
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            record = None
        if not isinstance(record, dict):
            missing.append(name_of(author))
        elif record.get("document_sha256") != stamp:
            other.append(name_of(author))
    if not missing and not other:
        return "Every author's approval is of the build it came from."
    said = []
    if other:
        said.append(f"approved another build: {', '.join(other)}")
    if missing:
        said.append(f"no approval: {', '.join(missing)}")
    return "Not every author approved the build it came from (" + "; ".join(said) + ")."
