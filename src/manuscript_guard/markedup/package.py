"""The two documents as packages of parts, and what of the one sent is carried into the other.

The marked-up copy is the revision's own document with the changes written into it. What the
revision no longer holds, a deleted paragraph or a replaced picture, comes from the document
that was sent, and anything it points at in its own package has to come with it: the picture
it shows, the numbering of the list it was in, a style the revision's document does not have,
the footnote it referred to. `Carried` does that, once for each thing, with names of its own
in the revision's package. A link's address is not carried: a deleted link is written as its
words, which is all a deletion shows. Anything else a deleted part points at is refused.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import posixpath
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from manuscript_guard.safexml import UnsafeDocument, open_archive, parse_xml, read_member

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
R = "{" + R_NS + "}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL = "{" + _RELS_NS + "}Relationship"
_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"

DOCUMENT = "word/document.xml"
FOOTNOTES = "word/footnotes.xml"
NUMBERING = "word/numbering.xml"
STYLES = "word/styles.xml"
CUSTOM = "docProps/custom.xml"
TYPES = "[Content_Types].xml"

#: What a picture's file may be, by extension, and the media type it is declared with.
_MEDIA = {
    "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "gif": "image/gif",
    "tif": "image/tiff", "tiff": "image/tiff", "bmp": "image/bmp", "emf": "image/x-emf",
    "wmf": "image/x-wmf", "svg": "image/svg+xml",
}  # fmt: skip


class MarkedUpError(Exception):
    """The marked-up copy cannot be made, and the reason is in the message."""


def _namespaces(data: bytes) -> list[tuple[str, str]]:
    return [
        (prefix, uri)
        for _event, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",))
    ]


#: The prefix a default namespace is written under before it is made the default again.
_OWN_PREFIX = "mgmarkedup"


def serialised(root: ET.Element, declared: Sequence[tuple[str, str]]) -> bytes:
    """A part written back under the prefixes it declared; and one whose elements are in
    the namespace it declared as its default (the package's content types, its
    relationships) with that namespace as its default again. Written with `ns0:`, Word
    reads them, and other readers of a package need not."""
    default = None
    for prefix, uri in declared:
        if prefix:
            # A prefix ElementTree keeps for itself (`ns0`) is refused: it is written under
            # one of ElementTree's own, and declared again below under the part's.
            with contextlib.suppress(ValueError):
                ET.register_namespace(prefix, uri)
        elif root.tag.startswith("{" + uri + "}"):
            default = uri
    if default is None:
        body = ET.tostring(root, encoding="unicode")
    else:
        # `default_namespace` refuses the parts' attributes, which have no namespace: a
        # prefix of this module's own, taken off again. Only the elements carry it.
        ET.register_namespace(_OWN_PREFIX, default)
        body = ET.tostring(root, encoding="unicode")
        body = body.replace(f"<{_OWN_PREFIX}:", "<").replace(f"</{_OWN_PREFIX}:", "</")
        body = body.replace(f"xmlns:{_OWN_PREFIX}=", "xmlns=")
    return _with_declarations(body, declared)


def _with_declarations(body: str, declared: Sequence[tuple[str, str]]) -> bytes:
    """The part with every namespace it declared declared again on its root. ElementTree
    declares only the namespaces an element or attribute uses, and a part saved by Word
    names others in `mc:Ignorable`, which Word reads as corrupt where they are not declared
    (round 1 of #396)."""
    end = body.index(">")
    closed = body[end - 1] == "/"
    head, tail = (body[: end - 1], body[end - 1 :]) if closed else (body[:end], body[end:])
    for prefix, uri in declared:
        if prefix and f"xmlns:{prefix}=" not in head:
            head += f' xmlns:{prefix}="{escape(uri, {chr(34): "&quot;"})}"'
    declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    return (declaration + head + tail).encode("utf-8")


def _rels_name(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", f"{name}.rels")


@dataclass
class Package:
    """A .docx read into memory: every part's bytes, and the parts this module edits parsed."""

    name: str
    names: list[str]
    parts: dict[str, bytes]
    trees: dict[str, ET.Element] = field(default_factory=dict)
    declared: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: Each part as parsed, so that one read and not changed is written back as it was.
    as_read: dict[str, str] = field(default_factory=dict)

    @classmethod
    def read(cls, path: Path) -> Package:
        try:
            with open_archive(path) as archive:
                names = archive.namelist()
                parts = {name: read_member(archive, name) for name in names}
        except UnsafeDocument as exc:
            raise MarkedUpError(f"{path.name} cannot be read: {exc}") from exc
        if DOCUMENT not in parts:
            raise MarkedUpError(f"{path.name} is not a Word document: it has no {DOCUMENT}")
        return cls(path.name, names, parts)

    def tree(self, part: str) -> ET.Element | None:
        """The part parsed, kept so that edits to it are written back; None where absent."""
        if part not in self.trees:
            if part not in self.parts:
                return None
            try:
                self.trees[part] = parse_xml(self.parts[part], what=f"{self.name}:{part}")
            except UnsafeDocument as exc:
                raise MarkedUpError(f"{self.name} cannot be read: {exc}") from exc
            self.declared[part] = _namespaces(self.parts[part])
            self.as_read[part] = ET.tostring(self.trees[part], encoding="unicode")
        return self.trees[part]

    def body(self) -> ET.Element:
        found = self.tree(DOCUMENT).find(W + "body")
        if found is None:
            raise MarkedUpError(f"{self.name} has no body")
        return found

    def relationships(self, part: str = DOCUMENT) -> dict[str, tuple[str, str, str]]:
        """Each relationship of `part` by id: its type, its target and its target mode."""
        rels = self.tree(_rels_name(part))
        if rels is None:
            return {}
        return {
            rel.get("Id", ""): (
                rel.get("Type", ""),
                rel.get("Target", ""),
                rel.get("TargetMode", ""),
            )
            for rel in rels.iter(_REL)
        }

    def target_part(self, part: str, target: str) -> str:
        if target.startswith("/"):
            return target[1:]
        return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))

    def picture(self, rid: str, part: str = DOCUMENT) -> str:
        """A digest of the picture relationship `rid` of `part` shows, "" where it is none."""
        kind, target, mode = self.relationships(part).get(rid, ("", "", ""))
        if kind != _IMAGE or mode == "External":
            return ""
        data = self.parts.get(self.target_part(part, target))
        return "" if data is None else hashlib.sha256(data).hexdigest()

    def link(self, rid: str, part: str = DOCUMENT) -> str:
        kind, target, _mode = self.relationships(part).get(rid, ("", "", ""))
        return target if kind == _HYPERLINK else ""

    def write(self, target: Path) -> None:
        import zipfile

        for part, root in self.trees.items():
            if ET.tostring(root, encoding="unicode") != self.as_read.get(part):
                self.parts[part] = serialised(root, self.declared[part])
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for name in self.names:
                out.writestr(name, self.parts[name])

    def add_part(self, name: str, data: bytes) -> None:
        if name not in self.parts:
            self.names.append(name)
        self.parts[name] = data


def _most(nodes: Iterable[ET.Element], attribute: str) -> int:
    values = [int(v) for n in nodes if (v := n.get(attribute, "")).lstrip("-").isdigit()]
    return max(values, default=0)


class Carried:
    """What of the document sent is carried into the revision's package, each thing once."""

    def __init__(self, before: Package, after: Package) -> None:
        self.before = before
        self.after = after
        self._pictures: dict[tuple[str, str], str] = {}
        self._numbers: dict[str, str] = {}
        self._notes: dict[str, str] = {}
        self._styles: set[str] = set()
        trees = [after.tree(DOCUMENT), after.tree(FOOTNOTES)]
        self._drawing = max(
            (_most(t.iter(WP + "docPr"), "id") for t in trees if t is not None), default=0
        )
        self._media = 0
        #: How a story of the document sent is written deleted; set by the writer.
        self.deleted_story = None

    # -- what a deleted part points at ----------------------------------------------------

    def carry(self, element: ET.Element, part: str = DOCUMENT) -> ET.Element:
        """`element`, from the document sent, pointing at what it points at in the revision's
        package. Bookmarks and comments are left out: the revision's are the document's."""
        element = copy.deepcopy(element)
        _drop_marks(element)
        for node in element.iter():
            for name in [a for a in node.attrib if a.startswith(R)]:
                if node.tag == W + "hyperlink":
                    continue
                rid = node.get(name, "")
                node.set(name, self._relationship(rid, part))
            if node.tag in (WP + "docPr", PIC + "cNvPr") and node.get("id", "").isdigit():
                self._drawing += 1
                node.set("id", str(self._drawing))
            if node.tag == W + "numId" and node.get(W + "val", "") not in ("", "0"):
                node.set(W + "val", self.number(node.get(W + "val", "")))
            if node.tag in (W + "pStyle", W + "rStyle", W + "tblStyle"):
                self.style(node.get(W + "val", ""))
            if node.tag == W + "footnoteReference" and part == DOCUMENT:
                node.set(W + "id", self.note(node.get(W + "id", "")))
        return element

    def _relationship(self, rid: str, part: str) -> str:
        key = (part, rid)
        if key in self._pictures:
            return self._pictures[key]
        kind, target, mode = self.before.relationships(part).get(rid, ("", "", ""))
        if kind != _IMAGE or mode == "External":
            raise MarkedUpError(
                f"a deleted part of {self.before.name} points at something other than a "
                f"picture ({kind.rsplit('/', 1)[-1] or 'nothing'}), which cannot be carried"
            )
        source = self.before.target_part(part, target)
        data = self.before.parts.get(source)
        if data is None:
            raise MarkedUpError(f"{self.before.name} names a picture it does not hold: {source}")
        extension = source.rsplit(".", 1)[-1].lower() if "." in source else ""
        if extension not in _MEDIA:
            raise MarkedUpError(
                f"{self.before.name} holds a picture of a kind not carried: {source}"
            )
        self._media += 1
        name = f"word/media/marked-up-{self._media}.{extension}"
        while name in self.after.parts:
            self._media += 1
            name = f"word/media/marked-up-{self._media}.{extension}"
        self.after.add_part(name, data)
        self._declare(extension)
        new_id = self._add_relationship(
            part, _IMAGE, posixpath.relpath(name, posixpath.dirname(part))
        )
        self._pictures[key] = new_id
        return new_id

    def _declare(self, extension: str) -> None:
        types = self.after.tree(TYPES)
        tag = "{" + _TYPES_NS + "}Default"
        if any(d.get("Extension", "").lower() == extension for d in types.iter(tag)):
            return
        ET.SubElement(types, tag, {"Extension": extension, "ContentType": _MEDIA[extension]})
        self.after.declared[TYPES] = [("", _TYPES_NS)]

    def _add_relationship(self, part: str, kind: str, target: str) -> str:
        name = _rels_name(part)
        rels = self.after.tree(name)
        if rels is None:
            data = f'<Relationships xmlns="{_RELS_NS}"/>'.encode()
            self.after.add_part(name, data)
            rels = self.after.tree(name)
        taken = {rel.get("Id", "") for rel in rels.iter(_REL)}
        number = 1
        while f"rIdMarkedUp{number}" in taken:
            number += 1
        new_id = f"rIdMarkedUp{number}"
        ET.SubElement(rels, _REL, {"Id": new_id, "Type": kind, "Target": target})
        self.after.declared[name] = [("", _RELS_NS)]
        return new_id

    def number(self, number_id: str) -> str:
        """The revision's numbering for list `number_id` of the document sent: a copy of it,
        so that a deleted item keeps its list's look and joins none of the revision's lists."""
        if number_id in self._numbers:
            return self._numbers[number_id]
        old = self.before.tree(NUMBERING)
        new = self.after.tree(NUMBERING)
        if old is None or new is None:
            raise MarkedUpError(f"{self.before.name} numbers a list it has no numbering for")
        instance = next((n for n in old.iter(W + "num") if n.get(W + "numId") == number_id), None)
        abstract_id = None if instance is None else instance.find(W + "abstractNumId")
        definition = next(
            (
                a
                for a in old.iter(W + "abstractNum")
                if abstract_id is not None
                and a.get(W + "abstractNumId") == abstract_id.get(W + "val")
            ),
            None,
        )
        if definition is None:
            raise MarkedUpError(f"{self.before.name} numbers a list it does not define")
        abstract = copy.deepcopy(definition)
        fresh_abstract = str(_most(new.iter(W + "abstractNum"), W + "abstractNumId") + 1)
        abstract.set(W + "abstractNumId", fresh_abstract)
        for linked in (W + "numStyleLink", W + "styleLink"):
            for node in abstract.findall(linked):
                abstract.remove(node)
        fresh_number = str(_most(new.iter(W + "num"), W + "numId") + 1)
        made = copy.deepcopy(instance)
        made.set(W + "numId", fresh_number)
        made.find(W + "abstractNumId").set(W + "val", fresh_abstract)
        # Every abstract definition before the first instance, as Word requires.
        children = list(new)
        first = next((i for i, c in enumerate(children) if c.tag == W + "num"), len(children))
        new.insert(first, abstract)
        new.append(made)
        self._numbers[number_id] = fresh_number
        return fresh_number

    def style(self, style_id: str) -> None:
        """Copy style `style_id` of the document sent, and those it is based on, where the
        revision's document has no style of that id."""
        if not style_id or style_id in self._styles:
            return
        self._styles.add(style_id)
        new = self.after.tree(STYLES)
        old = self.before.tree(STYLES)
        if new is None or old is None:
            return
        if any(s.get(W + "styleId") == style_id for s in new.iter(W + "style")):
            return
        found = next((s for s in old.iter(W + "style") if s.get(W + "styleId") == style_id), None)
        if found is None:
            return
        new.append(copy.deepcopy(found))
        for linked in ("basedOn", "next", "link"):
            node = found.find(W + linked)
            if node is not None:
                self.style(node.get(W + "val", ""))

    def note(self, note_id: str) -> str:
        """The footnote `note_id` of the document sent, carried whole into the revision's
        notes as deleted, and its id there."""
        if note_id in self._notes:
            return self._notes[note_id]
        old = self.before.tree(FOOTNOTES)
        new = self.after.tree(FOOTNOTES)
        found = (
            None
            if old is None
            else next((n for n in old.iter(W + "footnote") if n.get(W + "id") == note_id), None)
        )
        if found is None or new is None:
            raise MarkedUpError(f"{self.before.name} refers to a footnote it does not hold")
        fresh = str(_most(new.iter(W + "footnote"), W + "id") + 1)
        self._notes[note_id] = fresh
        note = ET.Element(W + "footnote", {W + "id": fresh})
        for child in self.deleted_story(list(found), FOOTNOTES):
            note.append(child)
        new.append(note)
        return fresh


#: What the document sent marks that the marked-up copy takes from the revision alone.
_MARKS = frozenset(
    W + tag
    for tag in ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd",
                "proofErr", "permStart", "permEnd")
)  # fmt: skip


def _drop_marks(element: ET.Element) -> None:
    for parent in list(element.iter()):
        for child in list(parent):
            if (
                child.tag in _MARKS
                or child.tag == W + "r"
                and child.find(W + "commentReference") is not None
            ):
                parent.remove(child)


_PROPERTY_NAME = re.compile(r'name="([^"]*)"')
