"""A checklist read from the table of the paper that published it.

Several guidelines publish their checklist only as a table inside the statement paper. TRIPOD+AI
is one: there is no checklist file to download, only the paper. Europe PMC serves an open
paper's full text as JATS XML, and the table is there as rows and cells, which is a better
source than the typeset PDF.

Two things differ from a checklist file:

* **The document is the paper, not the checklist.** A recipe of this kind says which table of
  which paper it read (`read_from`), and the profile carries that, because a paper's table and
  the guideline's own checklist file can differ: a column, a footnote, a revision.
* **The digest is over the rows, not the bytes.** Europe PMC can regenerate its XML (attribute
  order, whitespace, a new metadata element) with nothing in the table changed, so the recipe
  records `rows_sha256`, a digest of the cells as read, and a changed table is still caught.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.reporting.transcribe import RecipeError
from manuscript_guard.safexml import UnsafeDocument, parse_xml

#: Elements whose text is a block of its own: words on either side are not one word.
_BLOCKS = {"p", "break", "list-item", "title", "label", "td", "th", "tr", "caption"}
#: More columns or rows than this in one span is not a checklist; refused rather than built.
MOST_SPAN = 64
#: The document type some of Europe PMC's full texts open with: a name and the address of
#: an external DTD, nothing between brackets. The parser never fetches the DTD, and with no
#: internal subset there is no entity to expand, so it is set aside before parsing; a
#: document that declares anything more is refused (`_DECLARES`).
_EXTERNAL_DOCTYPE = re.compile(
    rb'\A(\s*(?:<\?xml[^>]*\?>)?\s*)<!DOCTYPE\s+article'
    rb'(?:\s+PUBLIC\s+"[^"<>\[\]]*"\s+"[^"<>\[\]]*"|\s+SYSTEM\s+"[^"<>\[\]]*")?\s*>'
)
#: A declaration anywhere in the document. The parser's own check reads the first 8 KB, which
#: is all an office part needs; a downloaded paper is read whole, or a document type with an
#: entity after a long comment is parsed and its entity read into the checklist.
_DECLARES = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def read_article(path: Path) -> ET.Element:
    """The article, parsed safely: size-capped, in UTF-8, and refused if it declares
    anything but the external document type some full texts open with."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in data[:1024]:
        # UTF-16, which a search of the bytes for a declaration does not read.
        raise UnsafeDocument(f"{path.name} is not UTF-8, as Europe PMC serves a full text")
    data = _EXTERNAL_DOCTYPE.sub(rb"\1", data, count=1)
    if _DECLARES.search(data):
        raise UnsafeDocument(
            f"{path.name} declares a DTD or an entity beyond the document type a full text "
            "names. Refusing to parse it."
        )
    root = parse_xml(data, what=path.name)
    if _local(root.tag) != "article":
        raise RecipeError(
            f"{path.name} is not a JATS article (its root is <{_local(root.tag)}>). Save the "
            "paper's full text from Europe PMC: "
            "https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/fullTextXML"
        )
    return root


def text_of(element: ET.Element) -> str:
    """The text of an element, with a space wherever a block or a line break ends."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        block = _local(node.tag) in _BLOCKS
        if block:
            parts.append(" ")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if block:
            parts.append(" ")

    walk(element)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def article_text(path: Path) -> str:
    """All the text of the article, what a transcribed item is verified against."""
    return text_of(read_article(path))


def table_rows(path: Path, which: str) -> tuple[list[list[str]], list[list[str]]]:
    """The head and body rows of one table, named by its `id` or by its label ("Table 2").

    A cell that spans columns is followed by empty cells, and one that spans rows leaves an
    empty cell in the rows below, so a column number in the recipe means the same column in
    every row. A table set as several <table> elements in one wrap is read as one."""
    root = read_article(path)
    wraps = [w for w in root.iter() if _local(w.tag) == "table-wrap"]
    wanted = _label(which)
    found = [w for w in wraps if w.get("id") == which or _label(_child_text(w, "label")) == wanted]
    if len(found) != 1:
        named = ", ".join(
            f"{w.get('id') or '?'} ({_child_text(w, 'label') or 'no label'})" for w in wraps
        )
        how = "no table" if not found else f"{len(found)} tables"
        raise RecipeError(f"{path.name}: {how} named {which!r}; the tables are: {named or 'none'}")
    head: list[list[str]] = []
    body: list[list[str]] = []
    for table in (t for t in found[0].iter() if _local(t.tag) == "table"):
        for section, rows in (("thead", head), ("tbody", body)):
            for part in (p for p in table if _local(p.tag) == section):
                rows.extend(_grid([r for r in part if _local(r.tag) == "tr"]))
        # A table with no <tbody> holds its rows directly.
        rows_direct = [r for r in table if _local(r.tag) == "tr"]
        body.extend(_grid(rows_direct))
    if not body:
        raise RecipeError(f"{path.name}: table {which!r} has no rows")
    return head, body


def rows_digest(head: list[list[str]], body: list[list[str]]) -> str:
    """A digest of the cells as read: unchanged when only the XML around them changes."""
    canonical = json.dumps({"head": head, "body": body}, ensure_ascii=False,
                           separators=(",", ":"))  # fmt: skip
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _grid(rows: list[ET.Element]) -> list[list[str]]:
    grid: list[list[str]] = []
    below: dict[int, int] = {}  # column -> rows a cell above still spans into
    for row in rows:
        cells = [c for c in row if _local(c.tag) in ("td", "th")]
        out: list[str] = []
        index = column = 0
        while index < len(cells) or any(c >= column for c in below):
            if column in below:
                out.append("")
                left = below.pop(column) - 1
                if left:
                    below[column] = left
                column += 1
                continue
            if index >= len(cells):
                out.append("")
                column += 1
                continue
            cell = cells[index]
            index += 1
            across, down = _span(cell.get("colspan")), _span(cell.get("rowspan"))
            out.extend([text_of(cell)] + [""] * (across - 1))
            if down > 1:
                for spanned in range(column, column + across):
                    below[spanned] = down - 1
            column += across
        grid.append(out)
    return grid


def _span(value: str | None) -> int:
    if value is None or not value.strip().isdigit():
        return 1
    return min(max(int(value), 1), MOST_SPAN)


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local(child.tag) == name:
            return text_of(child)
    return ""


def _label(text: str) -> str:
    return re.sub(r"[\s.:]+", " ", text).strip().lower()


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""
