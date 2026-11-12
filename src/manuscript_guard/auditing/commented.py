"""A copy of the audited .docx with each finding as a Word comment at its place.

The report names a place, "Methods, paragraph 3"; the copy puts the finding there, in the
document the author works in (the author's audit, 2026-11-10, "an interactive" report). Each
comment is anchored on the finding's own words where they can be found: the number for a
number, the abbreviation or the quoted word for a finding on the words; else on the stretch
of its quote that stands in one paragraph. A finding with no place in the text, or whose
words are in no paragraph as Word holds them, is listed in one comment on the document's
first paragraph, so that none is lost.

**Nothing else changes.** A comment's range is put between runs, a run split where the
words begin and end (`tracked._write_comment`); no text is added, removed or moved, and the
document read with its comments taken away is the document given. Words that begin or end
inside a field, a link or anything but a plain run are anchored on their whole paragraph
instead. The comments part, its relationship and its content type are added where the
document has none. The copy `--tracked` writes is this one with G14's corrections as
tracked changes as well, and without the comments they say (`auditing.tracked_copy`).

The paragraph is found by its words, not counted, since the audit's two readers of a .docx
count its paragraphs apart where one drops one (DESIGN.md, "Known gaps"): among the
paragraphs that hold the finding's quote, the first; within it, the finding's words nearest
to where the quote has them.
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import open_archive, parse_xml, read_member
from manuscript_guard.tracked import (
    W_NS,
    Placement,
    W,
    _chars,
    _comment,
    _found,
    _Ids,
    _namespaces,
    _one_text_each,
    _pattern,
    _write_comment,
)

_DOCUMENT = "word/document.xml"
_COMMENTS = "word/comments.xml"
_RELATIONSHIPS = "word/_rels/document.xml.rels"
_TYPES = "[Content_Types].xml"
_COMMENTS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
_COMMENTS_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
_PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
#: Who the comments are by, as Word shows it beside each.
AUTHOR = "manuscript-guard audit"
#: A finding's own words as its message quotes them: 'behaviours', 'p<0.05'.
_QUOTED = re.compile(r"'([^'\n]{1,60})'")
#: Its first word, where the message opens with what it is about, a number or an
#: abbreviation: "AS is used 8 times", "5 in the Abstract ...", and not "the P value ...".
_FIRST = re.compile(r"^([^\s:;,]*[\dA-Z][^\s:;,]*)\s")
#: Where the report's quote is cut, "...", and where a table's cells part in the
#: document's own text, " | ": no paragraph of the document holds a quote across either.
_CUT = re.compile(r"\.\.\.|\s*\|\s*")


class CommentedError(Exception):
    """The copy could not be written, and the reason is in the message."""


@dataclass(frozen=True)
class Note:
    """One finding to comment: its own words, the quote around them, and what the comment
    says, a paragraph to a line. `words` and `around` may be empty: the note then goes in
    the list on the first paragraph."""

    words: str
    around: str
    comment: str
    #: Where the report says it is, "Results, paragraph 3", said with it in the list where
    #: its words are found in no paragraph (round 1 of #617).
    place: str = ""
    #: The finding's code and its line in the text the report read, by which a correction
    #: written as a tracked change is known to be its (`auditing.tracked_copy.covered`).
    code: str = ""
    line: int | None = None


@dataclass(frozen=True)
class Commented:
    """What was written: how many comments stand at their place, and the notes that stood
    nowhere and are listed on the first paragraph."""

    placed: int
    listed: tuple[Note, ...]
    #: In the copy `--tracked` writes, how many corrections are tracked changes, and each
    #: one that is not, with why.
    tracked: int = 0
    untracked: tuple[tuple[object, str], ...] = ()


def words_of(message: str, context: str | None) -> str:
    """A finding's own words, where its message names them and its quote holds them: the
    word it quotes, or the word it opens with; empty where neither is in the quote."""
    if not context:
        return ""
    for found in (*_QUOTED.findall(message), *_FIRST.findall(message)):
        if found and len(found) <= 60 and _found(" ".join(context.split()), found):
            return found
    return ""


def _fragment(around: str, words: str = "") -> str:
    """The stretch of a quote that stands in one paragraph of the document: of the pieces
    the report's cuts and a table's cells part it into (`_CUT`), the longest that holds the
    finding's words, else the longest."""
    pieces = [" ".join(piece.split()) for piece in _CUT.split(around)]
    holding = [piece for piece in pieces if words and _found(piece, words)]
    return max(holding or pieces, key=len, default="")


def _quoted(fragment: str, edged: bool) -> re.Pattern[str]:
    """A quote's stretch as a paragraph holds it, across runs and layout space: whole at its
    ends where `edged`, so that "12" is not the 12 of "2012" (round 1 of #617); else from
    and to anywhere, as a gate's quote is cut at a character count, inside a word."""
    if edged:
        return _pattern(fragment)
    return re.compile(r"\s+".join(map(re.escape, fragment.split(" "))))


def _middle(fragment: str, words: str) -> int:
    """Where the finding's words are in its quote: of their places there, the one nearest
    the middle, which the report centres a quote on (`audit.around`)."""
    places = _found(fragment, words) or [max(0, fragment.find(words))]
    middle = (len(fragment) - len(words)) / 2
    return min(places, key=lambda at: abs(at - middle))


def _span(text: str, note: Note, edged: bool = True) -> tuple[int, int] | None:
    """Where the note's words are in a paragraph's text, nearest to where its quote has
    them; or the quote's stretch itself where the words are not given or not in it."""
    fragment = _fragment(note.around, note.words)
    at = None
    if fragment:
        at = _quoted(fragment, edged).search(text)
        if at is None:
            return None
    if note.words:
        starts = _found(text, note.words)
        if starts:
            aim = 0 if at is None else at.start() + _middle(fragment, note.words)
            start = min(starts, key=lambda one: abs(one - aim))
            return start, _pattern(note.words).match(text, start).end()
        if at is None:
            return None
    return (at.start(), at.end()) if at is not None else None


def _one_of(found: list[tuple[int, tuple[int, int]]]) -> tuple[int, tuple[int, int]] | None:
    """The one paragraph that holds a quote, or None where several do."""
    return found[0] if len(found) == 1 else None


def _paragraph(texts: list[tuple[str, list]], note: Note) -> tuple[int, tuple[int, int]] | None:
    """The first paragraph that holds the note's quote, its stretch whole at its ends, else
    from and to anywhere; and where its words are in it. A quote that is its words alone,
    a table's cell, "12", held by more than one paragraph tells none of them apart, and is
    listed with its place rather than put on the first (round 1 of #617). A quote in no
    paragraph as Word holds it (a gate's, from the text pandoc converts the document to, may
    carry a link's address or a mark Word does not print): the first paragraph that holds
    its words, where they are a word and not a number, which would stand in too many."""
    bare = _fragment(note.around, note.words).split() == note.words.split()
    for edged in (True, False):
        found = []
        for index, (text, _where) in enumerate(texts):
            span = _span(text, note, edged)
            if span is not None:
                found.append((index, span))
                if not bare:
                    break
        if found:
            return _one_of(found)
    if not re.search(r"[^\W\d_]", note.words):
        return None
    alone = Note(note.words, "", note.comment)
    for index, (text, _where) in enumerate(texts):
        span = _span(text, alone)
        if span is not None:
            return index, span
    return None


def notes_of(report, paper: Path) -> list[Note]:
    """Every finding of the audit `report` on `paper`, and those on no file (a paper or an
    output that could not be read), as a note: anchored on its own words where its message
    names them and its quote holds them (`words_of`), else on its quote; with the place the
    report gives it, for the list on the first paragraph where it stands nowhere. Each says
    its section, its message, its hint, and whether `--strict` counts it, all as a reader is
    told them, who runs no script and types no flag (`reader.for_a_reader`). A finding on
    another file the audit read, a supplement, an output, the journal's profile, is that
    file's, and not the document's."""
    from manuscript_guard.auditing.reader import FAILS, for_a_reader
    from manuscript_guard.auditing.report import items

    target = paper.resolve()
    placers = report.placers
    notes: list[Note] = []
    for item in items(report):
        if item.path is not None and Path(item.path).resolve() != target:
            continue
        said = f"{item.section}: {item.message}"
        if item.hint:
            said += f"\nHint: {item.hint}"
        said = for_a_reader(said)
        if item.counted:
            said += f"\n{FAILS}"
        placer = item.placer if item.placer is not None else placers.get(item.path)
        where = placer.said(item.line) if placer is not None and item.line else ""
        if item.path is None or item.line is None or not item.context:
            notes.append(Note("", "", said, where, item.code, item.line))
            continue
        notes.append(Note(words_of(item.message, item.context), item.context, said, where,
                          item.code, item.line))  # fmt: skip
    return notes


def _whole(paragraph: ET.Element, identifier: str) -> None:
    """A comment over the whole paragraph: its range from after the paragraph's properties
    to its end."""
    children = list(paragraph)
    start = 1 if children and children[0].tag == W + "pPr" else 0
    paragraph.insert(start, ET.Element(W + "commentRangeStart", {W + "id": identifier}))
    paragraph.append(ET.Element(W + "commentRangeEnd", {W + "id": identifier}))
    reference = ET.SubElement(paragraph, W + "r")
    ET.SubElement(ET.SubElement(reference, W + "rPr"), W + "rStyle").set(
        W + "val", "CommentReference")  # fmt: skip
    ET.SubElement(reference, W + "commentReference", {W + "id": identifier})


def _placement(note: Note, words: str, date: str) -> Placement:
    return Placement(0, "", words, "", AUTHOR, date, note.comment, comment_only=True)


def _listing(listed: list[Note]) -> str:
    """The comment on the first paragraph: the findings that stand nowhere in the text."""
    head = (f"{len(listed)} finding{'s' if len(listed) != 1 else ''} of the audit "
            f"{'have' if len(listed) != 1 else 'has'} no place in the text:")  # fmt: skip
    return "\n".join([head, *((f"{note.place}: " if note.place else "")
                              + note.comment.replace("\n", " ") for note in listed)])


def _parts_for_comments(parts: dict[str, bytes]) -> None:
    """The comments part, its relationship and its content type, where the document has
    none of them."""
    if _COMMENTS not in parts:
        parts[_COMMENTS] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                            f'<w:comments xmlns:w="{W_NS}"/>').encode()  # fmt: skip
    if _RELATIONSHIPS not in parts:
        parts[_RELATIONSHIPS] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                                 f'<Relationships xmlns="{_PACKAGE}"></Relationships>'
                                 ).encode()  # fmt: skip
    relationships = parse_xml(parts[_RELATIONSHIPS], what=_RELATIONSHIPS)
    if not any(node.get("Type") == _COMMENTS_RELATIONSHIP for node in relationships):
        taken = {node.get("Id") for node in relationships}
        number = next(n for n in range(1, len(taken) + 2) if f"rIdMgComments{n}" not in taken)
        parts[_RELATIONSHIPS] = _before_end(
            parts[_RELATIONSHIPS], b"</Relationships>",
            f'<Relationship Id="rIdMgComments{number}" Type="{_COMMENTS_RELATIONSHIP}" '
            'Target="comments.xml"/>', _RELATIONSHIPS)  # fmt: skip
    types = parse_xml(parts[_TYPES], what=_TYPES)
    if not any(node.get("PartName") == "/" + _COMMENTS for node in types):
        parts[_TYPES] = _before_end(
            parts[_TYPES], b"</Types>",
            f'<Override PartName="/{_COMMENTS}" ContentType="{_COMMENTS_TYPE}"/>', _TYPES)
    for name in (_RELATIONSHIPS, _TYPES):
        parse_xml(parts[name], what=name)


def _before_end(part: bytes, end: bytes, element: str, name: str) -> bytes:
    """The package part with `element` put in front of its closing tag, `end`, the rest of
    it as Word wrote it: these parts hold no prefix, and ElementTree writes none back but
    its own."""
    at = part.rfind(end)
    if at >= 0:
        return part[:at] + element.encode() + part[at:]
    # A part with nothing in it may be written as one empty element, "<Relationships/>".
    empty = re.search(rb"<" + re.escape(end[2:-1]) + rb"\b([^>]*?)\s*/>", part)
    if empty is None:
        raise CommentedError(f"{name} does not end as a Word document's does")
    return (part[:empty.start()] + b"<" + end[2:-1] + empty.group(1) + b">" + element.encode()
            + end + part[empty.end():])  # fmt: skip


def _written(root: ET.Element, declared: list[tuple[str, str]]) -> bytes:
    """A part as `tracked._serialised` writes one, but registering no prefix ElementTree
    keeps for its own, "ns0", which another tool may have written and which ElementTree
    refuses to be given (round 1 of #617)."""
    for prefix, uri in declared:
        if prefix and not re.fullmatch(r"ns\d+", prefix):
            ET.register_namespace(prefix, uri)
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body).encode()


#: The first element's start tag of a part, after its XML declaration.
_ROOT = re.compile(rb"<(?![?!])[^>]*?(/?)>")


def _declared_again(part: bytes, declared: list[tuple[str, str]]) -> bytes:
    """The part with every namespace its original declared declared again on its root.
    ElementTree writes only those its elements use, and a Word document names others in
    `mc:Ignorable`, "w15 w16se ...": without their declarations Word says the file is
    damaged (Word 16, 2026-11-10, on the author's paper)."""
    root = _ROOT.search(part)
    if root is None:
        return part
    tag = root.group(0)
    present = set(re.findall(rb"xmlns:([\w.-]+)=", tag))
    missing = "".join(f' xmlns:{prefix}="{uri}"' for prefix, uri in dict(declared).items()
                      if prefix and prefix.encode() not in present)  # fmt: skip
    if not missing:
        return part
    end = root.end() - len(root.group(1)) - 1
    return part[:end] + missing.encode() + part[end:]


def write(source: Path, target: Path, notes: list[Note], *, date: str,
          corrections: list | None = None) -> Commented:  # fmt: skip
    """Copy the .docx `source` to `target` with each note as a Word comment by `AUTHOR` on
    `date`, at its words where they stand, and the rest listed on the first paragraph. Given
    `corrections` (`gates.Tracked`), each that is found once is a tracked change as well,
    and a note all of whose corrections are is no comment (`auditing.tracked_copy`)."""
    try:
        with open_archive(source) as archive:
            names = archive.namelist()
            parts = {name: read_member(archive, name) for name in names}
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommentedError(f"{source.name} cannot be read: {exc}") from None
    if _DOCUMENT not in parts or _TYPES not in parts:
        raise CommentedError(f"{source.name} has no document part: it is not a Word document")
    from manuscript_guard.auditing.tracked_copy import TrackedCopyError

    try:
        return _commented(parts, names, target, notes, date, source.name, corrections)
    except TrackedCopyError as exc:
        raise CommentedError(f"its corrections could not be written as tracked changes: "
                             f"{exc}") from None  # fmt: skip
    except (ET.ParseError, ValueError) as exc:
        raise CommentedError(f"{source.name} could not be commented: {exc}") from None


def _commented(parts: dict[str, bytes], names: list[str], target: Path, notes: list[Note],
               date: str, name: str, corrections: list | None) -> Commented:  # fmt: skip
    """`write`, once the document's parts are read."""
    from manuscript_guard.auditing import tracked_copy

    original = [_chars(one)[0] for one in parse_xml(parts[_DOCUMENT], what=_DOCUMENT)
                .iter(W + "p")]  # fmt: skip
    _parts_for_comments(parts)
    declared = _namespaces(parts[_DOCUMENT])
    document = parse_xml(parts[_DOCUMENT], what=_DOCUMENT)
    comments = parse_xml(parts[_COMMENTS], what=_COMMENTS)
    paragraphs = list(document.iter(W + "p"))
    for paragraph in paragraphs:
        _one_text_each(paragraph)
    texts = [_chars(paragraph) for paragraph in paragraphs]
    changes, untracked = tracked_copy.locate(texts, corrections or [])
    said = tracked_copy.covered(notes, changes, untracked) if corrections is not None else set()
    notes = [note for index, note in enumerate(notes) if index not in said]
    located: list[tuple[int, tuple[int, int], Note]] = []
    listed: list[Note] = []
    for note in notes:
        place = _paragraph(texts, note) if note.words or note.around else None
        if place is None:
            listed.append(note)
        else:
            located.append((place[0], place[1], note))
    ids = _Ids(document, comments)
    for index, (start, end), note in sorted(located, key=lambda one: (one[0], one[1]),
                                            reverse=True):  # fmt: skip
        paragraph = paragraphs[index]
        _text, where = _chars(paragraph)
        words = _text[start:end]
        if where[start].run is None or where[end - 1].run is None:
            identifier = ids.take("comment")
            _whole(paragraph, identifier)
            comments.append(_comment(identifier, _placement(note, words, date)))
        else:
            _write_comment(paragraph, _placement(note, words, date), (start, end), ids,
                           comments)  # fmt: skip
    if listed and not paragraphs:
        raise CommentedError(f"{name} has no paragraph to put a comment on")
    if listed:
        identifier = ids.take("comment")
        _whole(paragraphs[0], identifier)
        comments.append(_comment(identifier, _placement(Note("", "", _listing(listed)), "",
                                                        date)))  # fmt: skip
    taken = tracked_copy.write_changes(paragraphs, changes, ids, date)
    parts[_DOCUMENT] = _declared_again(_written(document, declared), declared)
    tracked_copy.check(parts[_DOCUMENT], taken, original,
                       tracked_copy.expected(original, changes))  # fmt: skip
    kept = _namespaces(parts[_COMMENTS])
    parts[_COMMENTS] = _declared_again(_written(comments, kept), kept)
    names = [*names, *(name for name in parts if name not in names)]
    with tempfile.TemporaryDirectory() as scratch:
        made = Path(scratch) / "commented.docx"
        with zipfile.ZipFile(made, "w", zipfile.ZIP_DEFLATED) as out:
            for name in names:
                out.writestr(name, parts[name])
        try:
            # Made while the audit ran, it may be a copy the author is working on: never
            # written over (round 1 of #617).
            with open(target, "xb") as out:
                out.write(made.read_bytes())
        except FileExistsError:
            raise CommentedError(f"{target.name} is there already, and was not written "
                                 "over") from None  # fmt: skip
    return Commented(len(located), tuple(listed), len(changes), tuple(untracked))
