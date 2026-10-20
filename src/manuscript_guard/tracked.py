"""Suggested edits written into a built document as Word tracked changes, and read back.

A reading of a review panel can suggest an edit for one of its findings (`suggestions`).
Here each placed edit is written into the built document as the change Word's Track Changes
would have recorded had the reader typed it: the old words inside `w:del`, the new inside
`w:ins`, both authored by the reader, with the finding as a Word comment over them. The
author accepts or rejects each in Word, and `import` reads what was decided.

**Nothing else in the document changes.** An edit is made on the runs the build wrote, and
only on runs that hold nothing but text: never inside a field, a link, a footnote, a symbol,
or across a bookmark the build placed. Words that sit anywhere else, or that the paragraph
holds more than once, are not written, and the edit says why. Read with every change
rejected the document is the build, and read with every change accepted it is the build
with each edit made: `write` reads it both ways before it keeps the file.

**Each edit is bookmarked**, `mg-s-<n>`, from in front of the deletion to after the
insertion. In Word 16 (verified 2026-10-20 over COM) the bookmark stays when either change
is accepted or rejected, one at a time or with Accept All or Reject All, and so does the
comment, so once the author has decided, the text inside the bookmark is the new words or
the old: that is how `decided` tells the two apart. Words typed inside it as well are
neither. Where the deletion is accepted and the insertion rejected, nothing is left inside
it, and Word removes the bookmark and the comment together: that edit was neither accepted
nor refused, and is said to be gone.

**What the document records of its suggestions** is a list in its properties
(`SUGGESTIONS_PROPERTY`): for each, its number, the round, reviewer, reader and finding it
belongs to, the author its changes are under, and digests of its old words, its new words
and its comment. Never the words: a document's properties stay with it through everything
an author deletes before sending it on, and the words are in the review record.
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from manuscript_guard.safexml import UnsafeDocument, open_archive, parse_xml, read_member

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"
W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
_XML = "{http://www.w3.org/XML/1998/namespace}"
_DOCUMENT = "word/document.xml"
_COMMENTS = "word/comments.xml"
_EXTENDED = "word/commentsExtended.xml"
_CUSTOM = "docProps/custom.xml"

#: The bookmark around one suggested edit. A paragraph identifier is `mg-p-...` and a token
#: of the marked build `mg-t-...`; neither reader looks at this one.
SUGGESTION = "mg-s-"
_SUGGESTION = re.compile(r"mg-s-(\d+)$")

#: The list of suggestions a document carries, over as many properties as it takes, each
#: short of the 255 characters Word may cut a text property to.
SUGGESTIONS_PROPERTY = "manuscript-guard-suggestions"
_CHUNK = 240
_PROPERTY = re.compile(
    rf'<property\b[^>]*\bname="{SUGGESTIONS_PROPERTY}-(\d+)"[^>]*>\s*<vt:lpwstr>(.*?)</vt:lpwstr>',
    re.DOTALL,
)

#: What a run may hold for an edit to be made in it: its properties and its text.
_PLAIN = frozenset({W + "rPr", W + "t"})
#: Every element of a tracked change, by which `pending` finds what is still undecided.
_REVISIONS = frozenset(
    W + tag
    for tag in ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange",
                "tblPrChange", "trPrChange", "tcPrChange", "numberingChange",
                "cellIns", "cellDel")
)  # fmt: skip
#: What is not read as text once every change is accepted.
_GONE = frozenset({W + "del", W + "moveFrom", W + "delText", W + "delInstrText"})

#: The keys of one suggestion as the document records it, and their types.
_OFFERED = {
    "n": int,
    "round": int,
    "reviewer": str,
    "reader": (str, type(None)),
    "finding": str,
    "index": int,
    "author": str,
    "old": str,
    "new": str,
    "comment": str,
}


class TrackedError(Exception):
    """The document could not be read or written, and the reason is in the message."""


@dataclass(frozen=True)
class Placement:
    """One edit to write: in the paragraph carrying `paragraph`, `old` as Word shows it
    becomes `new`, authored by `author` on `date`, with `comment` over it."""

    number: int
    paragraph: str
    old: str
    new: str
    author: str
    date: str
    comment: str


@dataclass(frozen=True)
class Written:
    """What became of one placement: written, or not, and why not."""

    number: int
    dropped: str = ""


@dataclass(frozen=True)
class Reply:
    """A reply in Word to a suggestion's comment: who wrote it, when, and what."""

    author: str
    date: str
    text: str


def _namespaces(data: bytes) -> list[tuple[str, str]]:
    """Each prefix the part declares, so that it is written back under the same names."""
    return [
        (prefix, uri)
        for _event, (prefix, uri) in ET.iterparse(io.BytesIO(data), events=("start-ns",))
    ]


def _serialised(root: ET.Element, declared: Sequence[tuple[str, str]]) -> bytes:
    for prefix, uri in declared:
        if prefix:
            ET.register_namespace(prefix, uri)
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body).encode("utf-8")


@dataclass
class _Char:
    run: ET.Element | None
    text: ET.Element | None
    offset: int


def _identified(paragraph: ET.Element) -> list[str]:
    return [
        node.get(W + "name", "")
        for node in paragraph.iter(W + "bookmarkStart")
        if node.get(W + "name", "").startswith("mg-p-")
    ]


def _chars(paragraph: ET.Element) -> tuple[str, list[_Char]]:
    """The paragraph's text, each character with the run and `w:t` it is in where an edit
    can be made there, and with none where it cannot: inside a field, a link, or a run that
    holds more than text."""
    text: list[str] = []
    where: list[_Char] = []
    depth = 0

    def opaque(node: ET.Element) -> None:
        for inner in node.iter():
            if inner.tag == W + "t":
                for char in inner.text or "":
                    text.append(char)
                    where.append(_Char(None, None, 0))
            elif inner.tag in (W + "tab", W + "br", W + "cr", W + "sym", W + "noBreakHyphen"):
                text.append(" ")
                where.append(_Char(None, None, 0))

    for child in paragraph:
        if child.tag == W + "pPr":
            continue
        if child.tag != W + "r":
            opaque(child)
            continue
        opened = depth
        for node in child.iter(W + "fldChar"):
            kind = node.get(W + "fldCharType", "")
            depth += kind == "begin"
            depth -= kind == "end" and depth > 0
        if opened or depth or {node.tag for node in child} - _PLAIN:
            opaque(child)
            continue
        for t in child.findall(W + "t"):
            for index, char in enumerate(t.text or ""):
                text.append(char)
                where.append(_Char(child, t, index))
    return "".join(text), where


def _one_text_each(paragraph: ET.Element) -> None:
    """Give every plain run with several `w:t` a run for each, so that a split is of one."""
    for run in list(paragraph):
        if run.tag != W + "r":
            continue
        texts = run.findall(W + "t")
        if len(texts) < 2 or {node.tag for node in run} - _PLAIN:
            continue
        properties = run.find(W + "rPr")
        place = list(paragraph).index(run)
        for index, t in enumerate(texts):
            single = ET.Element(W + "r")
            if properties is not None:
                single.append(copy.deepcopy(properties))
            single.append(copy.deepcopy(t))
            paragraph.insert(place + 1 + index, single)
        paragraph.remove(run)


def _split(paragraph: ET.Element, run: ET.Element, t: ET.Element, at: int) -> ET.Element:
    """Split `run` so that its text from `at` on is in a run of its own placed after it,
    and return that run. The run's own element keeps the text before `at`, so offsets
    before the split still hold."""
    after = copy.deepcopy(run)
    after_t = after.find(W + "t")
    whole = t.text or ""
    t.text, after_t.text = whole[:at], whole[at:]
    for node in (t, after_t):
        node.set(_XML + "space", "preserve")
    paragraph.insert(list(paragraph).index(run) + 1, after)
    return after


class _Ids:
    """The next free id of each kind in the document: revisions, bookmarks, comments."""

    def __init__(self, document: ET.Element, comments: ET.Element) -> None:
        def most(nodes: Iterable[ET.Element]) -> int:
            values = [int(n.get(W + "id", "")) for n in nodes if n.get(W + "id", "").isdigit()]
            return max(values, default=-1)

        self.revision = most(n for n in document.iter() if n.tag in _REVISIONS) + 1
        self.bookmark = most(document.iter(W + "bookmarkStart")) + 1
        self.comment = max(most(comments.iter(W + "comment")),
                           most(document.iter(W + "commentRangeStart"))) + 1  # fmt: skip

    def take(self, kind: str) -> str:
        value = getattr(self, kind)
        setattr(self, kind, value + 1)
        return str(value)


def _initials(author: str) -> str:
    letters = [word[0] for word in re.findall(r"[^\W\d_]+", author)]
    return "".join(letters[:3]).upper() or "R"


def _comment(identifier: str, placement: Placement) -> ET.Element:
    comment = ET.Element(
        W + "comment",
        {
            W + "id": identifier,
            W + "author": placement.author,
            W + "date": placement.date,
            W + "initials": _initials(placement.author),
        },
    )
    paragraph = ET.SubElement(comment, W + "p")
    ET.SubElement(ET.SubElement(paragraph, W + "pPr"), W + "pStyle").set(W + "val", "CommentText")
    mark = ET.SubElement(paragraph, W + "r")
    ET.SubElement(ET.SubElement(mark, W + "rPr"), W + "rStyle").set(W + "val", "CommentReference")
    ET.SubElement(mark, W + "annotationRef")
    t = ET.SubElement(ET.SubElement(paragraph, W + "r"), W + "t")
    t.text = placement.comment
    t.set(_XML + "space", "preserve")
    return comment


def _pattern(old: str) -> re.Pattern[str]:
    """The words as the build printed them, whole, a space matching any run of layout space
    in the runs, where `docxtext` folds it to one."""
    head = "(?<![^\\W_])" if old[:1].isalnum() else ""
    tail = "(?![^\\W_])" if old[-1:].isalnum() else ""
    return re.compile(head + r"[ \t\r\n]+".join(re.escape(w) for w in old.split(" ")) + tail)


def _found(text: str, old: str) -> list[int]:
    pattern, found, at = _pattern(old), [], 0
    while (match := pattern.search(text, at)) is not None:
        found.append(match.start())
        at = match.start() + 1
    return found


def _locate(paragraph: ET.Element, placement: Placement) -> tuple[int, int] | str:
    """Where the placement's words are in the paragraph's text, or why nowhere."""
    text, where = _chars(paragraph)
    starts = _found(text, placement.old)
    if not starts:
        return "its words are not in the paragraph as the build printed it"
    if len(starts) > 1:
        return f"its words are in the paragraph {len(starts)} times as the build printed it"
    end = _pattern(placement.old).match(text, starts[0]).end()
    if any(char.run is None for char in where[starts[0] : end]):
        return "its words run into a field, a link or something else that is not plain text"
    children = list(paragraph)
    runs = {id(char.run) for char in where[starts[0] : end]}
    first = children.index(where[starts[0]].run)
    last = children.index(where[end - 1].run)
    if any(node.tag != W + "r" or id(node) not in runs for node in children[first : last + 1]):
        return "its words run across a bookmark or another mark the build placed"
    return starts[0], end


def _write_one(
    paragraph: ET.Element,
    placement: Placement,
    span: tuple[int, int],
    ids: _Ids,
    comments: ET.Element,
) -> None:
    """Write one located edit. Edits in one paragraph are written from the last to the
    first, so that what an earlier one located is where it was."""
    _text, where = _chars(paragraph)
    start, end = span
    first, last = where[start], where[end - 1]
    if last.offset + 1 < len(last.text.text or ""):
        _split(paragraph, last.run, last.text, last.offset + 1)
    head = first.run
    if first.offset > 0:
        head = _split(paragraph, first.run, first.text, first.offset)
        if last.run is first.run:
            last = _Char(head, head.find(W + "t"), last.offset - first.offset)
    children = list(paragraph)
    lo, hi = children.index(head), children.index(last.run)
    covered = children[lo : hi + 1]

    def change(kind: str) -> ET.Element:
        return ET.Element(W + kind, {W + "id": ids.take("revision"),
                                     W + "author": placement.author,
                                     W + "date": placement.date})  # fmt: skip

    deletion = change("del")
    for run in covered:
        paragraph.remove(run)
        for t in run.findall(W + "t"):
            t.tag = W + "delText"
        deletion.append(run)
    insertion = change("ins")
    run = ET.SubElement(insertion, W + "r")
    properties = covered[0].find(W + "rPr")
    if properties is not None:
        run.append(copy.deepcopy(properties))
    t = ET.SubElement(run, W + "t")
    t.text = placement.new
    t.set(_XML + "space", "preserve")
    bookmark, note = ids.take("bookmark"), ids.take("comment")
    reference = ET.Element(W + "r")
    ET.SubElement(ET.SubElement(reference, W + "rPr"), W + "rStyle").set(
        W + "val", "CommentReference"
    )
    ET.SubElement(reference, W + "commentReference", {W + "id": note})
    pieces = [
        ET.Element(W + "bookmarkStart", {W + "id": bookmark,
                                         W + "name": f"{SUGGESTION}{placement.number}"}),
        ET.Element(W + "commentRangeStart", {W + "id": note}),
        deletion,
        insertion,
        ET.Element(W + "bookmarkEnd", {W + "id": bookmark}),
        ET.Element(W + "commentRangeEnd", {W + "id": note}),
        reference,
    ]  # fmt: skip
    for offset, piece in enumerate(pieces):
        paragraph.insert(lo + offset, piece)
    comments.append(_comment(note, placement))


def _with_offered(existing: str, offered: Sequence[dict]) -> str:
    """The custom-properties part with the list of suggestions in it, every other property
    kept: the build's stamp, its record of paragraphs, and whatever pandoc and Word put
    there."""
    from manuscript_guard.roundtrip import _CUSTOM_PROPERTY, _CUSTOM_XML, _PROPERTY_ELEMENT

    encoded = json.dumps(list(offered), ensure_ascii=True, separators=(",", ":"))
    chunks = [encoded[i : i + _CHUNK] for i in range(0, len(encoded), _CHUNK)] or [""]
    kept = [
        element
        for element in _PROPERTY_ELEMENT.findall(existing)
        if f'name="{SUGGESTIONS_PROPERTY}-' not in element
    ]
    ours = [
        _CUSTOM_PROPERTY.format(name=f"{SUGGESTIONS_PROPERTY}-{number}", value=escape(chunk))
        for number, chunk in enumerate(chunks, start=1)
    ]
    numbered = [
        re.sub(r'\bpid="\d+"', f'pid="{i}"', element, count=1)
        for i, element in enumerate(kept + ours, start=2)
    ]
    return _CUSTOM_XML.format(properties="".join(numbered))


def write(
    source: Path, target: Path, placements: Sequence[Placement], offered: Sequence[dict]
) -> list[Written]:
    """Copy the built document `source` to `target` (which may be `source`) with each
    placement written as a tracked change, and say of each whether it was. `offered` is what
    the document records of each suggestion, by its number: only those written are kept."""
    with open_archive(source) as archive:
        names = archive.namelist()
        parts = {name: read_member(archive, name) for name in names}
    if _DOCUMENT not in parts or _COMMENTS not in parts or _CUSTOM not in parts:
        raise TrackedError(f"{source.name} is not a document this tool built")
    declared = _namespaces(parts[_DOCUMENT])
    document = parse_xml(parts[_DOCUMENT], what=_DOCUMENT)
    comments = parse_xml(parts[_COMMENTS], what=_COMMENTS)
    paragraphs: dict[str, ET.Element] = {}
    for paragraph in document.iter(W + "p"):
        for name in _identified(paragraph):
            paragraphs.setdefault(name, paragraph)

    said: dict[int, str] = {}
    located: dict[int, tuple[ET.Element, Placement, tuple[int, int]]] = {}
    for placement in placements:
        paragraph = paragraphs.get(placement.paragraph)
        if paragraph is None:
            said[placement.number] = "its paragraph is not in the document as built"
            continue
        _one_text_each(paragraph)
        span = _locate(paragraph, placement)
        if isinstance(span, str):
            said[placement.number] = span
            continue
        clash = next(
            (n for n, (p, _pl, (a, b)) in located.items()
             if p is paragraph and a < span[1] and span[0] < b),
            None,
        )  # fmt: skip
        if clash is not None:
            said[placement.number] = "another edit changes some of the same words"
            said[clash] = said[placement.number]
            del located[clash]
            continue
        located[placement.number] = (paragraph, placement, span)
    ids = _Ids(document, comments)
    for _n, (paragraph, placement, span) in sorted(
        located.items(), key=lambda item: item[1][2][0], reverse=True
    ):
        _write_one(paragraph, placement, span, ids, comments)

    parts[_DOCUMENT] = _serialised(document, declared)
    parts[_COMMENTS] = _serialised(comments, _namespaces(parts[_COMMENTS]))
    keep = [entry for entry in offered if entry.get("n") in located]
    parts[_CUSTOM] = _with_offered(parts[_CUSTOM].decode("utf-8"), keep).encode("utf-8")
    written = [Written(p.number, said.get(p.number, "")) for p in placements]
    with tempfile.TemporaryDirectory() as scratch:
        made = Path(scratch) / target.name
        with zipfile.ZipFile(made, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                out.writestr(name, parts[name])
        _check(source, made, [located[n][1] for n in sorted(located)])
        os.replace(made, target)
    return written


def resolved(document: Path, *, accept: bool, target: Path) -> Path:
    """`document` with every tracked change accepted or every one rejected, as Word's
    Accept All and Reject All leave it: for checking what was written, and for the tests."""
    with open_archive(document) as archive:
        names = archive.namelist()
        parts = {name: read_member(archive, name) for name in names}
    root = parse_xml(parts[_DOCUMENT], what=_DOCUMENT)
    gone, kept = ("del", "ins") if accept else ("ins", "del")
    for parent in list(root.iter()):
        for index, child in reversed(list(enumerate(parent))):
            if child.tag == W + gone:
                parent.remove(child)
            elif child.tag == W + kept:
                parent.remove(child)
                for offset, inner in enumerate(list(child)):
                    for node in inner.iter():
                        if node.tag == W + "delText":
                            node.tag = W + "t"
                    parent.insert(index + offset, inner)
    parts[_DOCUMENT] = _serialised(root, _namespaces(parts[_DOCUMENT]))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            out.writestr(name, parts[name])
    return target


def _check(built: Path, made: Path, placements: Sequence[Placement]) -> None:
    """Refuse to keep a document that does not read as the build with every change
    rejected, and as the build with each edit made with every change accepted."""
    from manuscript_guard.docxtext import blocks

    before = blocks(built)
    with tempfile.TemporaryDirectory() as scratch:
        rejected = blocks(resolved(made, accept=False, target=Path(scratch) / "rejected.docx"))
        accepted = blocks(resolved(made, accept=True, target=Path(scratch) / "accepted.docx"))
    expected = {}
    for block in before:
        if block.names and not block.table:
            expected[block.names[0]] = block.text
    # From the last edit in a paragraph to the first, so that the offsets before hold.
    order = sorted(placements, key=lambda p: -_found(expected[p.paragraph], p.old)[0])
    for placement in order:
        text = expected[placement.paragraph]
        start = _found(text, placement.old)[0]
        end = _pattern(placement.old).match(text, start).end()
        expected[placement.paragraph] = text[:start] + placement.new + text[end:]

    def texts(found: list) -> list[tuple[tuple[str, ...], str]]:
        return [(b.names, b.text) for b in found]

    if texts(rejected) != texts(before):
        raise TrackedError("with every change rejected, the document does not read as built")
    wanted = [
        (b.names, expected[b.names[0]] if b.names and not b.table else b.text) for b in before
    ]
    if texts(accepted) != wanted:
        raise TrackedError(
            "with every change accepted, the document does not read as the edits say"
        )


def _parts(document: Path, *wanted: str) -> dict[str, bytes]:
    try:
        with open_archive(document) as archive:
            names = set(archive.namelist())
            return {name: read_member(archive, name) for name in wanted if name in names}
    except (OSError, zipfile.BadZipFile, UnsafeDocument) as exc:
        raise TrackedError(f"{document.name} is not a readable .docx: {exc}") from exc


def offered_of(document: Path) -> list[dict] | None:
    """The suggestions the document records, or None where it records none. A list that
    does not read as one this tool writes raises `TrackedError`."""
    custom = _parts(document, _CUSTOM).get(_CUSTOM)
    if custom is None:
        return None
    chunks = sorted(
        (int(number), value) for number, value in _PROPERTY.findall(custom.decode("utf-8"))
    )
    if not chunks:
        return None
    from html import unescape

    try:
        listed = json.loads("".join(unescape(value) for _n, value in chunks))
    except ValueError:
        listed = None
    ok = isinstance(listed, list) and all(
        isinstance(entry, dict)
        and set(entry) == set(_OFFERED)
        and all(isinstance(entry[key], kind) and not isinstance(entry[key], bool)
                for key, kind in _OFFERED.items())
        for entry in listed
    )  # fmt: skip
    if not ok or len({entry["n"] for entry in listed}) != len(listed):
        raise TrackedError(
            f"{document.name} records suggestions in a form this version does not write"
        )
    return listed


@dataclass
class _Walk:
    """What `decided` gathers: for each suggestion's bookmark, the text inside it and the
    identifiers of the paragraph it starts in."""

    inside: set[str]
    texts: dict[str, list[str]]
    where: dict[str, tuple[str, ...]]
    names: dict[str, str]
    paragraph: tuple[str, ...] = ()


def _walk(node: ET.Element, gone: bool, walk: _Walk) -> None:
    if node.tag == W + "p":
        walk.paragraph = tuple(_identified(node))
    if node.tag == W + "bookmarkStart":
        found = _SUGGESTION.match(node.get(W + "name", ""))
        if found:
            number = found.group(1)
            walk.names[node.get(W + "id", "")] = number
            walk.inside.add(number)
            walk.texts.setdefault(number, [])
            walk.where.setdefault(number, walk.paragraph)
    elif node.tag == W + "bookmarkEnd":
        walk.inside.discard(walk.names.get(node.get(W + "id", ""), ""))
    elif node.tag == W + "t" and not gone and node.text:
        for number in walk.inside:
            walk.texts[number].append(node.text)
    elif node.tag in (W + "tab", W + "br", W + "cr") and not gone:
        for number in walk.inside:
            walk.texts[number].append(" ")
    for child in node:
        _walk(child, gone or child.tag in _GONE, walk)
    if node.tag == W + "p":
        for number in walk.inside:
            walk.texts[number].append(" ")


def decided(document: Path) -> dict[int, tuple[str, tuple[str, ...]]]:
    """For each suggestion's bookmark still in the document, the text inside it with every
    change accepted, its spaces folded, and the identifiers of the paragraph it starts in.
    A suggestion whose bookmark is gone is not in it."""
    data = _parts(document, _DOCUMENT).get(_DOCUMENT)
    if data is None:
        raise TrackedError(f"{document.name} has no {_DOCUMENT}")
    walk = _Walk(set(), {}, {}, {})
    _walk(parse_xml(data, what=_DOCUMENT), False, walk)
    return {
        int(number): (" ".join("".join(pieces).split()), walk.where[number])
        for number, pieces in walk.texts.items()
    }


def pending(document: Path, authors: Iterable[str]) -> int:
    """How many tracked changes by `authors` the document still holds."""
    wanted = set(authors)
    data = _parts(document, _DOCUMENT).get(_DOCUMENT)
    if data is None:
        raise TrackedError(f"{document.name} has no {_DOCUMENT}")
    root = parse_xml(data, what=_DOCUMENT)
    return sum(
        1 for node in root.iter() if node.tag in _REVISIONS and node.get(W + "author") in wanted
    )


@dataclass(frozen=True)
class Comment:
    """A comment in the document, with the ids of its paragraphs, which a reply's
    `w15:paraIdParent` names."""

    identifier: str
    author: str
    date: str
    text: str
    paragraphs: tuple[str, ...]


def comments_of(document: Path) -> tuple[list[Comment], dict[str, str]]:
    """Every comment, and for each paragraph of a reply the paragraph of the comment it
    replies to, as Word records a reply in `word/commentsExtended.xml` (verified in Word 16
    on 2026-10-20). A document without that part has no replies."""
    from manuscript_guard.docxtext import spaced

    parts = _parts(document, _COMMENTS, _EXTENDED)
    found = []
    if _COMMENTS in parts:
        for node in parse_xml(parts[_COMMENTS], what=_COMMENTS).iter(W + "comment"):
            text = " ".join(
                "".join(t.text or "" for t in p.iter(W + "t")) for p in node.iter(W + "p")
            )
            found.append(
                Comment(
                    identifier=node.get(W + "id", ""),
                    author=node.get(W + "author", ""),
                    date=node.get(W + "date", "")[:10],
                    text=spaced(text).strip(),
                    paragraphs=tuple(
                        p.get(W14 + "paraId", "") for p in node.iter(W + "p")
                        if p.get(W14 + "paraId")
                    ),
                )
            )  # fmt: skip
    parents = {}
    if _EXTENDED in parts:
        for node in parse_xml(parts[_EXTENDED], what=_EXTENDED).iter(W15 + "commentEx"):
            if node.get(W15 + "paraIdParent"):
                parents[node.get(W15 + "paraId", "")] = node.get(W15 + "paraIdParent", "")
    return found, parents


def replies_to(
    comment: Comment, comments: Sequence[Comment], parents: dict[str, str]
) -> list[Reply]:
    """The replies Word records to `comment`, in the order of the comments."""
    own = set(comment.paragraphs)
    return [
        Reply(other.author, other.date, other.text)
        for other in comments
        if other is not comment and any(parents.get(p) in own for p in other.paragraphs)
    ]


__all__ = [
    "SUGGESTION",
    "SUGGESTIONS_PROPERTY",
    "Comment",
    "Placement",
    "Reply",
    "TrackedError",
    "Written",
    "comments_of",
    "decided",
    "offered_of",
    "pending",
    "replies_to",
    "resolved",
    "write",
]
