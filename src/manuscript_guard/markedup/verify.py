"""What the marked-up copy reads as with every change accepted, and with every one rejected.

Accepted, it must read as the revision; rejected, as the document that was sent. Both are
read here as Word's Accept All and Reject All leave them (`resolved`), then as `docxtext`
reads any document, block by block, with the footnotes in the order the text refers to them.
A copy that does not read so is not kept: the writer is wrong somewhere, and a marked-up copy
that shows a change that was not made, or hides one that was, is worse than none.

Rejecting is accepting the inverse: every insertion read as a deletion and every deletion as
an insertion, and each change of formatting read the other way round (`_inverted`).

And the copy with highlights in place of tracked changes (`highlighted`): what was inserted
highlighted, what was deleted struck through, nothing tracked. It is made from a tracked copy
that has passed the check above.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.markedup.package import (
    DOCUMENT,
    FOOTNOTES,
    M,
    MarkedUpError,
    Package,
    W,
)

_PARTS = (DOCUMENT, FOOTNOTES)
_CHANGES = frozenset(W + t for t in ("rPrChange", "pPrChange", "trPrChange", "tblPrChange",
                                     "tcPrChange", "sectPrChange", "tblGridChange",
                                     "numberingChange"))  # fmt: skip
_SWAP = {W + "ins": W + "del", W + "del": W + "ins"}
_TEXT_SWAP = {W + "t": W + "delText", W + "delText": W + "t",
              W + "instrText": W + "delInstrText", W + "delInstrText": W + "instrText"}  # fmt: skip
_DELETED_TEXT = {W + "delText": W + "t", W + "delInstrText": W + "instrText"}


def _place(node: ET.Element, parent: ET.Element | None) -> str:
    """Where a change element stands: "mark" for a paragraph's mark, "row" for a table row,
    "run" around content."""
    if parent is not None and parent.tag == W + "trPr":
        return "row"
    if parent is not None and parent.tag == W + "rPr":
        return "mark"
    return "run"


def _parents(root: ET.Element) -> dict[int, ET.Element]:
    return {id(child): parent for parent in root.iter() for child in parent}


def _inverted(root: ET.Element) -> None:
    """Every change read the other way round: rejecting this is accepting `root`."""
    parents = _parents(root)
    wrappers = [n for n in root.iter() if n.tag in _SWAP]
    for node in wrappers:
        if _place(node, parents.get(id(node))) == "run":
            for inner in node.iter():
                if inner.tag in _TEXT_SWAP:
                    inner.tag = _TEXT_SWAP[inner.tag]
        node.tag = _SWAP[node.tag]
    for change in [n for n in root.iter() if n.tag in (W + "rPrChange", W + "pPrChange")]:
        holder = parents[id(change)]
        inner = W + ("rPr" if change.tag == W + "rPrChange" else "pPr")
        # What the properties hold that a change of them records: in a paragraph's, all
        # but the mark's formatting and the section; in a run's, all.
        stays = (change.tag,) if inner == W + "rPr" else (W + "rPr", W + "sectPr", change.tag)
        now = [c for c in holder if c.tag not in stays]
        old = change.find(inner)
        if old is None:
            old = ET.SubElement(change, inner)
        was = list(old)
        for child in now:
            holder.remove(child)
        for child in was:
            old.remove(child)
        for offset, child in enumerate(was):
            holder.insert(offset, child)
        for child in now:
            old.append(child)


def _accepted(root: ET.Element) -> None:
    """Every change accepted, as Word's Accept All leaves the part."""
    parents = _parents(root)
    for node in list(root.iter()):
        if node.tag not in (W + "ins", W + "del", W + "moveFrom", W + "moveTo"):
            continue
        parent = parents.get(id(node))
        if parent is None:
            continue
        where = _place(node, parent)
        if where == "row" and node.tag == W + "del":
            row = parents[id(parent)]
            table = parents.get(id(row))
            if table is not None and row in list(table):
                table.remove(row)
            continue
        if where in ("row", "mark"):
            continue
        index = list(parent).index(node)
        parent.remove(node)
        if node.tag in (W + "ins", W + "moveTo"):
            for offset, child in enumerate(list(node)):
                parent.insert(index + offset, child)
    parents = _parents(root)
    for node in [n for n in root.iter() if n.tag in _CHANGES]:
        holder = parents.get(id(node))
        if holder is not None:
            holder.remove(node)
    _join_deleted_marks(root)


def _mark(paragraph: ET.Element) -> ET.Element | None:
    found = paragraph.find(f"{W}pPr/{W}rPr")
    return found


def _join_deleted_marks(root: ET.Element) -> None:
    """A paragraph whose mark was deleted runs into the paragraph after it. With nothing after
    it to run into, it goes where it holds nothing, and stays otherwise."""
    for container in list(root.iter()):
        children = list(container)
        for index in range(len(children) - 1, -1, -1):
            paragraph = children[index]
            if paragraph.tag != W + "p":
                continue
            mark = _mark(paragraph)
            if mark is None:
                continue
            deleted = [c for c in mark if c.tag in (W + "del", W + "moveFrom")]
            for change in [c for c in mark if c.tag in (W + "ins", W + "moveTo", W + "del",
                                                        W + "moveFrom")]:  # fmt: skip
                mark.remove(change)
            if not deleted:
                continue
            content = [c for c in paragraph if c.tag != W + "pPr"]
            after = children[index + 1] if index + 1 < len(children) else None
            if after is not None and after.tag == W + "p":
                place = 1 if after.find(W + "pPr") is not None else 0
                for offset, child in enumerate(content):
                    paragraph.remove(child)
                    after.insert(place + offset, child)
                container.remove(paragraph)
            elif not "".join(t.text or "" for t in paragraph.iter(W + "t")).strip() and not any(
                n.tag in (W + "drawing", M + "oMath") for n in paragraph.iter()
            ):
                container.remove(paragraph)


def resolved(document: Path, *, accept: bool, target: Path) -> Path:
    """`document` with every change accepted, or every one rejected, written to `target`."""
    package = Package.read(document)
    for part in _PARTS:
        root = package.tree(part)
        if root is None:
            continue
        if not accept:
            _inverted(root)
        _accepted(root)
    package.write(target)
    return target


def _readable(document: Path) -> list[tuple]:
    from manuscript_guard.docxtext import DocumentUnreadable, blocks

    try:
        found = blocks(document)
    except DocumentUnreadable as exc:
        raise MarkedUpError(f"{document.name} cannot be read: {exc}") from exc
    return [(b.kind, b.key) if b.kind else (b.role, b.text) for b in found if b.kind or b.text] + [
        ("note", text) for text in _notes(Package.read(document))
    ]


def _notes(package: Package) -> list[str]:
    """Each footnote's text, in the order the body refers to them."""
    notes = package.tree(FOOTNOTES)
    if notes is None:
        return []
    by_id = {n.get(W + "id"): n for n in notes.iter(W + "footnote")}
    out = []
    for reference in package.body().iter(W + "footnoteReference"):
        note = by_id.get(reference.get(W + "id"))
        if note is not None:
            out.append(
                " ".join("".join(t.text or "" for t in p.iter(W + "t")) for p in note.iter(W + "p"))
            )
    return out


def _first_difference(got: list[tuple], wanted: list[tuple]) -> str:
    for index, (a, b) in enumerate(zip(got, wanted, strict=False)):
        if a != b:
            return f"block {index + 1}: {str(a)[:120]!r} where {str(b)[:120]!r} was expected"
    return f"{len(got)} blocks where {len(wanted)} were expected"


def check(made: Path, before: Path, after: Path) -> None:
    """Refuse a copy that does not read as `after` accepted and as `before` rejected."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        accepted = _readable(resolved(made, accept=True, target=folder / "accepted.docx"))
        rejected = _readable(resolved(made, accept=False, target=folder / "rejected.docx"))
    wanted_after, wanted_before = _readable(after), _readable(before)
    if accepted != wanted_after:
        raise MarkedUpError(
            "with every change accepted, the marked-up copy does not read as the revision ("
            + _first_difference(accepted, wanted_after)
            + "); it was not kept"
        )
    if rejected != wanted_before:
        raise MarkedUpError(
            "with every change rejected, the marked-up copy does not read as the document "
            "sent (" + _first_difference(rejected, wanted_before) + "); it was not kept"
        )


# -- the highlighted copy ----------------------------------------------------------------------

#: The order of a run's properties (`CT_RPr`), so that what is added goes where Word reads it.
_RPR_ORDER = [W + t for t in (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
    "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
    "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
    "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
    "specVanish", "oMath", "rPrChange",
)]  # fmt: skip
HIGHLIGHT = "yellow"


def _set(run: ET.Element, tag: str, attributes: dict[str, str]) -> None:
    """Give `run` (a `w:r`, or an equation's `m:r`) the property `tag`, in its place."""
    properties = run.find(W + "rPr")
    if properties is None:
        properties = ET.Element(W + "rPr")
        run.insert(0 if run.tag == W + "r" else _math_rpr_place(run), properties)
    existing = properties.find(tag)
    if existing is not None:
        existing.attrib.update(attributes)
        return
    rank = _RPR_ORDER.index(tag)
    place = next(
        (
            i
            for i, c in enumerate(properties)
            if c.tag in _RPR_ORDER and _RPR_ORDER.index(c.tag) > rank
        ),
        len(properties),
    )
    properties.insert(place, ET.Element(tag, attributes))


def _math_rpr_place(run: ET.Element) -> int:
    """In an equation's run, Word's properties follow the run's own maths properties."""
    return 1 if len(run) and run[0].tag == M + "rPr" else 0


def _runs(node: ET.Element) -> list[ET.Element]:
    return [n for n in node.iter() if n.tag in (W + "r", M + "r")]


#: The order of a paragraph's properties (`CT_PPr`) up to its shading, where a picture's
#: mark goes.
_PPR_BEFORE_SHADING = [W + t for t in (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
    "suppressLineNumbers", "pBdr",
)]  # fmt: skip
#: The shading of a paragraph that holds a picture inserted, and one deleted. A picture
#: takes no highlight and no strike, so its paragraph is marked instead.
INSERTED_PICTURE, DELETED_PICTURE = "FFFF00", "FFC7CE"
_PICTURES = (W + "drawing", W + "pict", W + "object")


def _shaded(paragraph: ET.Element | None, fill: str) -> None:
    if paragraph is None:
        return
    properties = paragraph.find(W + "pPr")
    if properties is None:
        properties = ET.Element(W + "pPr")
        paragraph.insert(0, properties)
    for old in properties.findall(W + "shd"):
        properties.remove(old)
    place = sum(1 for child in properties if child.tag in _PPR_BEFORE_SHADING)
    properties.insert(place, ET.Element(W + "shd", {W + "val": "clear", W + "color": "auto",
                                                    W + "fill": fill}))  # fmt: skip


def _paragraph_of(node: ET.Element, parents: dict[int, ET.Element]) -> ET.Element | None:
    while node is not None and node.tag != W + "p":
        node = parents.get(id(node))
    return node


def _highlighted(root: ET.Element) -> None:
    parents = _parents(root)
    for node in [n for n in root.iter() if n.tag in (W + "ins", W + "del")]:
        parent = parents.get(id(node))
        where = _place(node, parent)
        if where in ("row", "mark"):
            parent.remove(node)
            continue
        if any(inner.tag in _PICTURES for inner in node.iter()):
            fill = INSERTED_PICTURE if node.tag == W + "ins" else DELETED_PICTURE
            _shaded(_paragraph_of(parent, parents), fill)
        if node.tag == W + "ins":
            for run in _runs(node):
                _set(run, W + "highlight", {W + "val": HIGHLIGHT})
        else:
            for inner in node.iter():
                if inner.tag in _DELETED_TEXT:
                    inner.tag = _DELETED_TEXT[inner.tag]
            for run in _runs(node):
                _set(run, W + "strike", {})
        index = list(parent).index(node)
        parent.remove(node)
        for offset, child in enumerate(list(node)):
            parent.insert(index + offset, child)
    parents = _parents(root)
    for change in [n for n in root.iter() if n.tag in _CHANGES]:
        holder = parents[id(change)]
        holder.remove(change)
        if change.tag == W + "rPrChange":
            _set(parents[id(holder)], W + "highlight", {W + "val": HIGHLIGHT})
        elif change.tag == W + "pPrChange":
            for run in _runs(parents[id(holder)]):
                _set(run, W + "highlight", {W + "val": HIGHLIGHT})


def highlighted(document: Path, target: Path) -> Path:
    """The tracked copy `document` with its changes shown as highlights, none tracked."""
    package = Package.read(document)
    for part in _PARTS:
        root = package.tree(part)
        if root is not None:
            _highlighted(root)
    package.write(target)
    return target
