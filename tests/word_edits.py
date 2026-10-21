"""What Word does to a document of suggested edits, as Word 16 was seen to do it.

`review --suggestions` writes each edit as a tracked change inside a bookmark `mg-s-<n>`,
with its finding as a comment (`manuscript_guard.tracked`). The author decides each in
Word, and the tests import what Word would have saved. Each step here was made in Word 16
over COM on 2026-10-20 and the XML it saved was read, so these are Word's edits, not ones
that only look like them:

- Accepting a change unwraps the insertion and drops the deletion; rejecting drops the
  insertion and makes the deleted text text again. The bookmark and the comment stay,
  around what is left.
- Accepting the deletion and rejecting the insertion leaves nothing inside the bookmark, and
  Word removes the bookmark, the comment's range, its mark and the comment itself.
- A reply is a comment of its own, anchored over the same words, and
  `word/commentsExtended.xml` names the paragraph of the comment it answers
  (`w15:paraIdParent`). Word gives every comment's paragraph a `w14:paraId` when it saves.
- Text typed with Track Changes on is an insertion by the author, outside any change of
  the reviewer's.

Word also merges runs and renumbers ids when it saves, which no reader here may depend on;
`tests/test_suggestions.py` holds a document Word itself saved for that.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.tracked import _namespaces, _serialised

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
W14, W15 = "{" + W14_NS + "}", "{" + W15_NS + "}"
_EXTENDED_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
)
_EXTENDED_REL = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
#: Who decides in Word: the author of the paper.
AUTHOR = "Ana Author"


def _read(document: Path) -> tuple[list[str], dict[str, bytes]]:
    with zipfile.ZipFile(document) as archive:
        names = archive.namelist()
        return names, {name: archive.read(name) for name in names}


def _write(target: Path, names: list[str], parts: dict[str, bytes]) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            out.writestr(name, parts[name])


def _span(paragraph: ET.Element, number: int) -> tuple[int, int, str] | None:
    """Where the bookmark of suggestion `number` starts and ends among the paragraph's
    children, and its id."""
    children = list(paragraph)
    start = next(
        (i for i, c in enumerate(children)
         if c.tag == W + "bookmarkStart" and c.get(W + "name") == f"mg-s-{number}"),
        None,
    )  # fmt: skip
    if start is None:
        return None
    ident = children[start].get(W + "id")
    end = next(
        i for i, c in enumerate(children)
        if i > start and c.tag == W + "bookmarkEnd" and c.get(W + "id") == ident
    )  # fmt: skip
    return start, end, ident


def _unwrap(paragraph: ET.Element, element: ET.Element) -> None:
    at = list(paragraph).index(element)
    paragraph.remove(element)
    for offset, inner in enumerate(list(element)):
        for node in inner.iter():
            if node.tag == W + "delText":
                node.tag = W + "t"
        paragraph.insert(at + offset, inner)


def _comment_ids(paragraph: ET.Element, start: int) -> list[str]:
    """The comments whose range opens inside the suggestion's bookmark."""
    children = list(paragraph)
    return [c.get(W + "id") for c in children[start:] if c.tag == W + "commentRangeStart"][:1]


def decide(
    document: Path,
    target: Path,
    choices: dict[int, str],
    replies: dict[int, str] | None = None,
    typed: dict[int, str] | None = None,
) -> Path:
    """`document` with each suggestion decided as `choices` says: "accept", "reject", or
    "deletion" (the deletion accepted and the insertion rejected); one not named is left
    undecided. `replies` are written to a suggestion's comment by the author, as Word writes
    a reply. `typed` is text typed with Track Changes on just inside a suggestion's
    bookmark once it is decided."""
    names, parts = _read(document)
    declared = _namespaces(parts["word/document.xml"])
    root = ET.fromstring(parts["word/document.xml"])
    comments = ET.fromstring(parts["word/comments.xml"])
    gone_comments: set[str] = set()
    anchors: dict[int, str] = {}
    for paragraph in root.iter(W + "p"):
        for number, how in choices.items():
            span = _span(paragraph, number)
            if span is None:
                continue
            start, end, _ident = span
            inside = list(paragraph)[start : end + 1]
            anchors[number] = (_comment_ids(paragraph, start) or [""])[0]
            for element in inside:
                if element.tag == W + "del":
                    if how == "reject":
                        _unwrap(paragraph, element)
                    else:
                        paragraph.remove(element)
                elif element.tag == W + "ins":
                    if how == "accept":
                        _unwrap(paragraph, element)
                    else:
                        paragraph.remove(element)
            if how == "deletion":
                ident = anchors[number]
                gone_comments.add(ident)
                for element in list(paragraph):
                    named = element.get(W + "name") == f"mg-s-{number}"
                    tied = element.tag in (W + "commentRangeStart", W + "commentRangeEnd") and (
                        element.get(W + "id") == ident
                    )
                    marked = element.find(W + "commentReference") is not None and (
                        element.find(W + "commentReference").get(W + "id") == ident
                    )
                    bookmark_end = element.tag == W + "bookmarkEnd" and element.get(
                        W + "id"
                    ) == span[2]
                    if named or tied or marked or bookmark_end:
                        paragraph.remove(element)
            if typed and number in typed:
                again = _span(paragraph, number)
                if again is not None:
                    insertion = ET.Element(W + "ins", {W + "id": "9000", W + "author": AUTHOR,
                                                        W + "date": "2026-10-21T09:00:00Z"})
                    t = ET.SubElement(ET.SubElement(insertion, W + "r"), W + "t")
                    t.text = typed[number]
                    paragraph.insert(again[0] + 1, insertion)
    for comment in list(comments):
        if comment.get(W + "id") in gone_comments:
            comments.remove(comment)
    for number, text in (replies or {}).items():
        _reply(root, comments, parts, names, anchors.get(number) or _anchor(root, number), text)
    parts["word/document.xml"] = _serialised(root, declared)
    parts["word/comments.xml"] = _serialised(comments, _namespaces(parts["word/comments.xml"]))
    _write(target, names, parts)
    return target


def _anchor(root: ET.Element, number: int) -> str:
    for paragraph in root.iter(W + "p"):
        span = _span(paragraph, number)
        if span is not None:
            return (_comment_ids(paragraph, span[0]) or [""])[0]
    raise AssertionError(f"suggestion {number} is not in the document")


def _reply(
    root: ET.Element,
    comments: ET.Element,
    parts: dict[str, bytes],
    names: list[str],
    parent: str,
    text: str,
) -> None:
    """A reply to the comment `parent`, as Word 16 saves one."""
    ET.register_namespace("w14", W14_NS)
    ET.register_namespace("w15", W15_NS)
    # Word's paragraph ids are unique in the document; these go on from the highest there.
    taken = [int(p.get(W14 + "paraId"), 16)
             for p in comments.iter(W + "p") if p.get(W14 + "paraId")]  # fmt: skip
    counter = [max(taken, default=0x1000)]

    def para_id() -> str:
        counter[0] += 1
        return f"{counter[0]:08X}"

    for comment in comments.iter(W + "comment"):
        for paragraph in comment.iter(W + "p"):
            if paragraph.get(W14 + "paraId") is None:
                paragraph.set(W14 + "paraId", para_id())
    above = next(c for c in comments.iter(W + "comment") if c.get(W + "id") == parent)
    parent_para = list(above.iter(W + "p"))[-1].get(W14 + "paraId")
    ident = str(1 + max(int(c.get(W + "id")) for c in comments.iter(W + "comment")))
    reply = ET.SubElement(comments, W + "comment", {W + "id": ident, W + "author": AUTHOR,
                                                    W + "date": "2026-10-21T09:00:00Z",
                                                    W + "initials": "BC"})  # fmt: skip
    paragraph = ET.SubElement(reply, W + "p", {W14 + "paraId": para_id()})
    ET.SubElement(ET.SubElement(paragraph, W + "r"), W + "annotationRef")
    ET.SubElement(ET.SubElement(paragraph, W + "r"), W + "t").text = text
    # Anchored over the same words as the comment it answers.
    for p in root.iter(W + "p"):
        children = list(p)
        for i, child in enumerate(children):
            if child.tag == W + "commentRangeStart" and child.get(W + "id") == parent:
                p.insert(i + 1, ET.Element(W + "commentRangeStart", {W + "id": ident}))
            if child.tag == W + "commentRangeEnd" and child.get(W + "id") == parent:
                p.insert(i + 2, ET.Element(W + "commentRangeEnd", {W + "id": ident}))
    extended = parts.get("word/commentsExtended.xml")
    ex = ET.fromstring(extended) if extended else ET.Element(W15 + "commentsEx")
    known = {node.get(W15 + "paraId") for node in ex}
    for comment in comments.iter(W + "comment"):
        for p in comment.iter(W + "p"):
            pid = p.get(W14 + "paraId")
            if pid not in known:
                attributes = {W15 + "paraId": pid, W15 + "done": "0"}
                if comment is reply:
                    attributes[W15 + "paraIdParent"] = parent_para
                ET.SubElement(ex, W15 + "commentEx", attributes)
                known.add(pid)
    parts["word/commentsExtended.xml"] = ET.tostring(ex, encoding="utf-8", xml_declaration=True)
    if "word/commentsExtended.xml" not in names:
        names.append("word/commentsExtended.xml")
        types = parts["[Content_Types].xml"].decode("utf-8")
        parts["[Content_Types].xml"] = types.replace(
            "</Types>",
            f'<Override PartName="/word/commentsExtended.xml" ContentType="{_EXTENDED_TYPE}"/>'
            "</Types>",
        ).encode("utf-8")
        rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
        parts["word/_rels/document.xml.rels"] = re.sub(
            "</Relationships>",
            f'<Relationship Id="rIdMgExtended" Type="{_EXTENDED_REL}" '
            'Target="commentsExtended.xml"/></Relationships>',
            rels,
        ).encode("utf-8")
