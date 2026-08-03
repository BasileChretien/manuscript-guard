"""Reading the text of a Word document, correctly.

Two details decide whether an audit of an existing paper works at all, and both were learned
the hard way in the project that preceded this one.

**Table cells must be separated.** Word stores a row as a sequence of cells with no
separator between their text. Concatenating naively turns the row

    Unique publishers | 39 | 20 | 26 | 16

into `Unique publishers39202616`, which reads as the single number 39,202,616. No cell can
then be matched against anything, so every table in the paper is silently skipped — and a
wrong count in Table 1 survived every check for exactly that reason.

**Tracked changes must be resolved.** A document under review contains both the old text and
the new. Reading it raw gives numbers that were deleted and numbers that were inserted, mixed
together, so the audit reports corrections as errors and misses the text that will actually
be published. Insertions are kept and deletions dropped, which is what the reader will see.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")


class NotADocx(Exception):
    """The file is not a readable Word document."""


def _in_deletion(node: ET.Element, parents: dict) -> bool:
    current = parents.get(node)
    while current is not None:
        if current.tag == W + "del":
            return True
        current = parents.get(current)
    return False


def _part_text(xml: bytes) -> str:
    root = ET.fromstring(xml)
    parents = {child: parent for parent in root.iter() for child in parent}
    pieces: list[str] = []

    for node in root.iter():
        if node.tag == W + "tc":
            # Cell boundary. Without this, adjacent cells concatenate into one number.
            pieces.append(" | ")
        elif node.tag == W + "p" or node.tag == W + "tr":
            pieces.append("\n")
        elif node.tag == W + "tab":
            pieces.append("\t")
        elif node.tag == W + "t" and node.text and not _in_deletion(node, parents):
            pieces.append(node.text)

    return "".join(pieces)


def read_docx(path: Path) -> str:
    """Visible text of a .docx with tracked changes accepted, tables kept separable."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise NotADocx(f"{path.name}: not a readable .docx ({exc})") from exc

    names = set(archive.namelist())
    if "word/document.xml" not in names:
        raise NotADocx(f"{path.name}: no word/document.xml; is this really a .docx?")

    out = []
    for part in PARTS:
        if part in names:
            try:
                out.append(_part_text(archive.read(part)))
            except ET.ParseError as exc:
                raise NotADocx(f"{path.name}: {part} is malformed ({exc})") from exc

    text = "\n".join(out)
    # Collapse runs of spaces but keep line structure, so findings can cite a line.
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def is_docx(path: Path) -> bool:
    return path.suffix.lower() == ".docx"
