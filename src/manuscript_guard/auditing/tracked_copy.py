"""The corrections G14 is sure of, written into the commented copy of a .docx as Word
tracked changes (`audit --tracked`, the author's audit, 2026-11-11).

The copy is the one `--commented` writes (`auditing.commented`), and each correction of
`gates.as_tracked` is in it as the change Word's Track Changes would have recorded had the
author typed it: the characters it takes away inside `w:del`, those it puts in inside
`w:ins`, by `AUTHOR`. The author accepts or rejects each in Word. A finding all of whose
corrections are written is no comment as well; every other finding is one, as
`--commented` writes it.

**A correction is placed only where it is sure.** Its words, with the words of its
paragraph either side of them, are looked for in every paragraph of the document as Word
holds it, across its runs: found nowhere, or in more than one place, or in a field, a link
or anything but a plain run, it is not written, and its finding stays a comment. Only the
characters that change are deleted and inserted (difflib's opcodes on the old words and the
new), each insertion in the run properties of the text it replaces or stands beside. No
paragraph mark is deleted: Word 16 never returns from Accept All on a deleted final one
(#396).

**The copy is read both ways before it is kept**: with every change it holds accepted, each
paragraph must read as the document's with each correction made, and with every change
rejected as the document's. Where either fails, no copy is written, and the reason is said.
"""

from __future__ import annotations

import copy
import difflib
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from manuscript_guard.auditing.gates import NOTHING_PRINTED
from manuscript_guard.tracked import _REVISIONS, _XML, W, _chars

#: Who the tracked changes are by, as Word shows it beside each.
AUTHOR = "manuscript-guard"
#: A space of the words around a correction, as a paragraph's runs may hold it.
_SPACE = r"[ \t\r\n]+"
#: A quotation mark the converted text writes straight, as the document may hold it.
_QUOTES = {"'": "['‘’]", '"': '["“”]'}


class TrackedCopyError(Exception):
    """The corrections could not be written so that the copy reads as it must."""


@dataclass(frozen=True)
class Placed:
    """A correction found once in the document: in paragraph `index`, `tracked.old` is the
    text from `start` to `end` of the paragraph's text as `tracked._chars` reads it."""

    index: int
    start: int
    end: int
    tracked: object


def _words(words: str) -> str:
    """The words around a correction as a pattern: a space any run of layout space, a
    straight quotation mark either curly one."""
    out = []
    for piece in re.split(r"( +)", words):
        if piece.startswith(" "):
            out.append(_SPACE)
        else:
            out.extend(_QUOTES.get(char) or re.escape(char) for char in piece)
    return "".join(out)


def pattern(tracked) -> re.Pattern[str]:
    """Where a correction stands in a paragraph's text: its own words exactly, in a group,
    between the words around it; whole at an end where nothing is given beside it."""
    old = tracked.old
    head = "(?<![^\\W_])" if not tracked.before and old[:1].isalnum() else ""
    tail = "(?![^\\W_])" if not tracked.after and old[-1:].isalnum() else ""
    return re.compile(_words(tracked.before) + head + "(" + re.escape(old) + ")" + tail
                      + _words(tracked.after))  # fmt: skip


def locate(texts: list[tuple[str, list]], corrections: list,
           notes: list[str] = ()) -> tuple[list[Placed], list[tuple[object, str]]]:  # fmt: skip
    """Each correction found once in the paragraphs, each its text and where each of its
    characters is (`tracked._chars`), and in plain runs; and each other one with why it is
    not. The paragraphs of the footnotes and endnotes, `notes`, are part of the text pandoc
    converts and are looked in too, though nothing is written there: a correction of a
    footnote whose words are cut to nothing either side is the bare word, which may stand
    once in the body (round 1 of #666)."""
    placed: list[Placed] = []
    left: list[tuple[object, str]] = []
    for one in corrections:
        if one.left_out:
            left.append((one, one.left_out))
            continue
        found = _places([text for text, _where in texts], pattern(one))
        elsewhere = len(_places(list(notes), pattern(one)))
        if len(found) + elsewhere != 1:
            left.append((one, "its words are in no paragraph of the document as Word holds "
                         "them" if not found and not elsewhere else "its words are in "
                         f"{len(found) + elsewhere} places in the document"))  # fmt: skip
            continue
        if not found:
            left.append((one, "its words are in a footnote or an endnote, where no change is "
                         "written"))  # fmt: skip
            continue
        index, start, end = found[0]
        if any(char.run is None for char in texts[index][1][start:end]):
            left.append((one, "its words run into a field, a link or something else that is "
                         "not plain text"))  # fmt: skip
            continue
        placed.append(Placed(index, start, end, one))
    # Two found over the same characters: neither is sure.
    clashing = {id(a) for a in placed for b in placed
                if a is not b and a.index == b.index and a.start < b.end and b.start < a.end}
    left += [(one.tracked, "another correction is found over some of the same words")
             for one in placed if id(one) in clashing]  # fmt: skip
    return [one for one in placed if id(one) not in clashing], left


def _places(texts: list[str], found: re.Pattern[str]) -> list[tuple[int, int, int]]:
    """Every place the pattern matches, overlapping ones too: paragraph, start and end of
    its group."""
    places = []
    for index, text in enumerate(texts):
        at = 0
        while (match := found.search(text, at)) is not None:
            places.append((index, match.start(1), match.end(1)))
            at = match.start() + 1
    return places


#: The kinds of finding G14 says once for each word, a word of the other English and an
#: abbreviation defined and not used again: a correction of one is the finding's where its
#: words hold the finding's own. Any other kind is said once for a form, "P=0.03", and
#: corrected at places whose words are others, "P=0.01": each correction of the kind is
#: taken for the finding's.
_ONE_PER_WORD = frozenset({"spelling-variant", "abbreviation-unused"})


def _holds(old: str, words: str) -> bool:
    return bool(words) and re.search(r"(?<![^\W_])" + re.escape(words) + r"(?![^\W_])", old,
                                     re.IGNORECASE) is not None  # fmt: skip


def _its(note, tracked) -> bool:
    """Is the correction `tracked` one of the note's finding (`_ONE_PER_WORD`)?"""
    return note.code in tracked.codes and (note.code not in _ONE_PER_WORD
                                           or _holds(tracked.old, note.words))  # fmt: skip


def covered(notes: list, placed: list[Placed], left: list[tuple[object, str]]) -> set[int]:
    """The notes whose findings are said by the tracked changes alone, by index: a placed
    correction of the note's finding stands on its line and holds its own words, and no
    correction of the finding was left out, which its comment then has to say: none of
    its places, a correction refused for changing words another changes otherwise among them
    (`gates._refused`), but one that changes nothing the document prints."""
    out = set()
    for index, note in enumerate(notes):
        if not note.code or note.line is None or not note.words:
            continue
        if any(_its(note, one) for one, why in left if why != NOTHING_PRINTED):
            continue
        if any(_its(note, one.tracked) and one.tracked.line == note.line
               and _holds(one.tracked.old, note.words) for one in placed):  # fmt: skip
            out.add(index)
    return out


class _Revisions:
    """The next revision id, and those taken for this copy's own changes."""

    def __init__(self, ids, date: str) -> None:
        self.ids, self.date, self.taken = ids, date, set()

    def element(self, kind: str) -> ET.Element:
        identifier = self.ids.take("revision")
        self.taken.add(identifier)
        return ET.Element(W + kind, {W + "id": identifier, W + "author": AUTHOR,
                                     W + "date": self.date})  # fmt: skip


def _boundary(paragraph: ET.Element, at: int, revisions: _Revisions) -> None:
    """A run boundary in front of character `at` of the paragraph's text, where it is in a
    plain run: the run split there, a change of its formatting recorded in it given an id of
    its own in the copy (round 1 of #666)."""
    _text, where = _chars(paragraph)
    if at <= 0 or at >= len(where) or where[at].run is None or where[at].offset == 0:
        return
    char = where[at]
    after = copy.deepcopy(char.run)
    after_t = after.find(W + "t")
    whole = char.text.text or ""
    char.text.text, after_t.text = whole[: char.offset], whole[char.offset :]
    for node in (char.text, after_t):
        node.set(_XML + "space", "preserve")
    for inner in after.iter():
        if inner.tag in _REVISIONS and inner.get(W + "id") is not None:
            inner.set(W + "id", revisions.ids.take("revision"))
    paragraph.insert(list(paragraph).index(char.run) + 1, after)


def _change(paragraph: ET.Element, lo: int, hi: int, inserted: str, revisions: _Revisions,
            *, opens: bool) -> None:  # fmt: skip
    """Characters `lo` to `hi` of the paragraph's text deleted, each run of them in a
    `w:del` of its own, and `inserted` put in their place, in the run properties of the
    first; or, where nothing is deleted, put in at `lo` in those of the character before
    it, or of the one after where `lo` `opens` the corrected words."""
    _boundary(paragraph, lo, revisions)
    _boundary(paragraph, hi, revisions)
    _text, where = _chars(paragraph)
    if hi > lo:
        runs = list(dict.fromkeys(where[at].run for at in range(lo, hi)))
        properties = runs[0].find(W + "rPr")
        for run in runs:
            place = list(paragraph).index(run)
            paragraph.remove(run)
            for t in run.findall(W + "t"):
                t.tag = W + "delText"
            deletion = revisions.element("del")
            deletion.append(run)
            paragraph.insert(place, deletion)
        place = list(paragraph).index(deletion) + 1
    elif not opens:
        beside = where[lo - 1].run
        properties, place = beside.find(W + "rPr"), list(paragraph).index(beside) + 1
    else:
        beside = where[lo].run
        properties, place = beside.find(W + "rPr"), list(paragraph).index(beside)
    if not inserted:
        return
    insertion = revisions.element("ins")
    run = ET.SubElement(insertion, W + "r")
    if properties is not None:
        copied = copy.deepcopy(properties)
        # The text put in is new: a change of formatting the run it copies recorded is that
        # run's, and its id would be two revisions' (round 1 of #666).
        for change in copied.findall(W + "rPrChange"):
            copied.remove(change)
        run.append(copied)
    t = ET.SubElement(run, W + "t")
    t.text = inserted
    t.set(_XML + "space", "preserve")
    paragraph.insert(place, insertion)


def _opcodes(old: str, new: str) -> list[tuple[str, int, int, int, int]]:
    """How `old` becomes `new`, character by character: difflib's opcodes."""
    return difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()


def write_changes(paragraphs: list[ET.Element], placed: list[Placed], ids, date: str) -> set[str]:
    """Each placed correction written as tracked changes, from the last in its paragraph to
    the first and within one from its last change to its first, so that what was located
    before is where it was; the ids of the revisions written."""
    revisions = _Revisions(ids, date)
    for one in sorted(placed, key=lambda one: (one.index, one.start), reverse=True):
        old, new = one.tracked.old, one.tracked.new
        for tag, i1, i2, j1, j2 in reversed(_opcodes(old, new)):
            if tag != "equal":
                _change(paragraphs[one.index], one.start + i1, one.start + i2, new[j1:j2],
                        revisions, opens=i1 == 0)  # fmt: skip
    return revisions.taken


def distinct(document: ET.Element, ids) -> None:
    """Every revision of the document with an id no other has: a run split where a comment
    or a change begins (`tracked._split`) carries a change of its formatting into both
    halves, under one id, and each after the first is given a new one."""
    seen: set[str] = set()
    for node in document.iter():
        identifier = node.get(W + "id") if node.tag in _REVISIONS else None
        if identifier is None:
            continue
        if identifier in seen:
            identifier = ids.take("revision")
            node.set(W + "id", identifier)
        seen.add(identifier)


def expected(texts: list[str], placed: list[Placed]) -> list[str]:
    """The paragraphs' texts with each placed correction made."""
    out = list(texts)
    for one in sorted(placed, key=lambda one: (one.index, one.start), reverse=True):
        text = out[one.index]
        out[one.index] = text[: one.start] + one.tracked.new + text[one.end :]
    return out


def resolved_texts(document: ET.Element, taken: set[str], *, accept: bool) -> list[str]:
    """The text of each paragraph of a copy of `document` with the revisions `taken`
    accepted, or rejected, as Word's Accept All and Reject All leave them; any other
    revision as it stands."""
    root = copy.deepcopy(document)
    gone, kept = ("del", "ins") if accept else ("ins", "del")
    for parent in list(root.iter()):
        for index, child in reversed(list(enumerate(parent))):
            if child.tag not in (W + gone, W + kept) or child.get(W + "id") not in taken:
                continue
            parent.remove(child)
            if child.tag == W + kept:
                for offset, inner in enumerate(list(child)):
                    for node in inner.iter(W + "delText"):
                        node.tag = W + "t"
                    parent.insert(index + offset, inner)
    return [_chars(paragraph)[0] for paragraph in root.iter(W + "p")]


def check(document: bytes, taken: set[str], original: list[str], wanted: list[str]) -> None:
    """Refuse a copy whose document part, read back, does not read as `wanted` with every
    change of its own accepted and as `original` with every one rejected."""
    from manuscript_guard.safexml import parse_xml

    root = parse_xml(document, what="word/document.xml")
    if resolved_texts(root, taken, accept=False) != original:
        raise TrackedCopyError("with every change rejected, the copy does not read as the "
                               "document")  # fmt: skip
    if resolved_texts(root, taken, accept=True) != wanted:
        raise TrackedCopyError("with every change accepted, the copy does not read as the "
                               "document with its corrections made")  # fmt: skip


__all__ = ["AUTHOR", "Placed", "TrackedCopyError", "check", "covered", "distinct", "expected",
           "locate", "pattern", "resolved_texts", "write_changes"]
