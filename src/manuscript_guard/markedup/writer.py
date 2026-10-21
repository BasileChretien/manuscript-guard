"""The revision's document with every change since the document sent written in as Word's.

A story (the body, a table cell, a footnote) is merged block by block (`align.steps`): an
identical block is the revision's own, an inserted one is the revision's with all of it
tracked as inserted, a deleted one is the document sent's with all of it tracked as deleted,
and an edited paragraph is merged atom by atom (`atoms`, `align.changes`). Text the revision
kept is its own runs; text deleted is the sent document's runs, with their formatting, inside
`w:del`; a word whose formatting alone changed keeps the revision's and records the sent one
in `w:rPrChange`, and a paragraph whose style or numbering changed records the old in
`w:pPrChange`. A table of the same columns is merged row by row and cell by cell; a row
added or removed is tracked as a row. Every change is by one author on one date.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from manuscript_guard.markedup import align
from manuscript_guard.markedup.atoms import CONTAINERS, MARKS, MATHS, Atom, Read, look, read
from manuscript_guard.markedup.atoms import signature as atom_signature
from manuscript_guard.markedup.atoms import words as atom_words
from manuscript_guard.markedup.package import (
    DOCUMENT,
    FOOTNOTES,
    NUMBERING,
    Carried,
    MarkedUpError,
    Package,
    W,
)

_XML = "{http://www.w3.org/XML/1998/namespace}"
#: The blocks of a story that are compared; anything else beside them is a mark, kept from
#: the revision where it stands.
_UNITS = frozenset((W + "p", W + "tbl", W + "sdt", W + "customXml"))
#: What stays where it is in its story, whatever is merged around it.
_FIXED_LAST = frozenset((W + "sectPr",))
#: The order of a paragraph's properties, so that what is added goes where Word reads it.
_PPR_LAST = (W + "rPr", W + "sectPr", W + "pPrChange")
#: The text of a run, as deleted and as kept.
_DELETED_TEXT = {W + "t": W + "delText", W + "instrText": W + "delInstrText"}
_KEPT_TEXT = {v: k for k, v in _DELETED_TEXT.items()}


def deleted_text(element: ET.Element) -> ET.Element:
    """`element` with its text and field codes as Word writes them deleted."""
    for node in element.iter():
        if node.tag in _DELETED_TEXT:
            node.tag = _DELETED_TEXT[node.tag]
    return element


def _mark_paragraph(paragraph: ET.Element, change: ET.Element) -> None:
    """Track `paragraph`'s mark as `change` (inserted or deleted)."""
    properties = paragraph.find(W + "pPr")
    if properties is None:
        properties = ET.Element(W + "pPr")
        paragraph.insert(0, properties)
    mark = properties.find(W + "rPr")
    if mark is None:
        mark = ET.Element(W + "rPr")
        before = next((i for i, c in enumerate(properties) if c.tag in _PPR_LAST[1:]), None)
        properties.insert(len(properties) if before is None else before, mark)
    mark.insert(0, change)


def _number_look(package: Package, number_id: str, level: str) -> tuple:
    """What a list's numbering draws at a level, which tells two lists apart where their
    numbers do not: two builds number their lists in their own order."""
    tree = package.tree(NUMBERING)
    if tree is None:
        return (number_id, level)
    instance = next((n for n in tree.iter(W + "num") if n.get(W + "numId") == number_id), None)
    abstract = None if instance is None else instance.find(W + "abstractNumId")
    for definition in tree.iter(W + "abstractNum"):
        if abstract is None or definition.get(W + "abstractNumId") != abstract.get(W + "val"):
            continue
        for lvl in definition.iter(W + "lvl"):
            if lvl.get(W + "ilvl") == level:
                shown = [lvl.find(W + t) for t in ("numFmt", "lvlText")]
                return tuple(n.get(W + "val", "") if n is not None else "" for n in shown)
    return (number_id, level)


def _properties_key(paragraph: ET.Element, package: Package) -> tuple:
    """A paragraph's properties as compared: what shows, its list by what it draws."""
    properties = paragraph.find(W + "pPr")
    if properties is None:
        return ()
    out = []
    for child in properties:
        if child.tag in _PPR_LAST:
            continue
        if child.tag == W + "numPr":
            number = child.find(W + "numId")
            level = child.find(W + "ilvl")
            out.append(("list", _number_look(
                package,
                "" if number is None else number.get(W + "val", ""),
                "0" if level is None else level.get(W + "val", "0"),
            )))  # fmt: skip
            continue
        out.append(ET.tostring(child, encoding="unicode"))
    return tuple(sorted(out, key=str))


@dataclass
class _Unit:
    element: ET.Element
    same: tuple
    words: list
    paragraph: Read | None = None
    columns: tuple | None = None


def _shape(table: ET.Element) -> tuple | None:
    """A table's columns, None where a cell spans or merges and the table cannot be merged
    cell by cell."""
    grid = table.find(W + "tblGrid")
    columns = 0 if grid is None else len(grid.findall(W + "gridCol"))
    for row in table.findall(W + "tr"):
        cells = row.findall(W + "tc")
        for cell in cells:
            properties = cell.find(W + "tcPr")
            if properties is not None and (
                properties.find(W + "vMerge") is not None
                or properties.find(W + "gridSpan") is not None
                or properties.find(W + "hMerge") is not None
            ):
                return None
        if len(cells) != columns:
            return None
    return (columns,)


class Writer:
    """Writes one marked-up copy: the revision's package with the changes in it."""

    def __init__(self, before: Package, after: Package, *, author: str, date: str) -> None:
        self.before, self.after = before, after
        self.author, self.date = author, date
        self.carried = Carried(before, after)
        self.carried.deleted_story = self.deleted_story
        trees = [after.tree(p) for p in (DOCUMENT, FOOTNOTES, "word/comments.xml")]
        self._id = 1 + max(
            (
                int(value)
                for tree in trees
                if tree is not None
                for node in tree.iter()
                if (value := node.get(W + "id", "")).isdigit()
            ),
            default=0,
        )
        self.counts: Counter = Counter()
        self._merged_notes: set[str] = set()

    # -- changes ---------------------------------------------------------------------------

    def change(self, kind: str) -> ET.Element:
        made = ET.Element(
            W + kind, {W + "id": str(self._id), W + "author": self.author, W + "date": self.date}
        )
        self._id += 1
        return made

    # -- units -----------------------------------------------------------------------------

    def _unit(self, element: ET.Element, package: Package, part: str) -> _Unit:
        if element.tag == W + "p":
            found = read(element, package, part)
            same = ("p", _properties_key(element, package), atom_signature(found))
            return _Unit(element, same, atom_words(found), paragraph=found)
        if element.tag == W + "tbl":
            rows = []
            words: list = []
            for row in element.findall(W + "tr"):
                cells = []
                for cell in row.findall(W + "tc"):
                    inner = [self._unit(c, package, part) for c in cell if c.tag in _UNITS]
                    cells.append(tuple(u.same for u in inner))
                    words += [w for u in inner for w in u.words]
                rows.append(tuple(cells))
            return _Unit(element, ("tbl", tuple(rows)), words, columns=_shape(element))
        shown = "".join(t.text or "" for t in element.iter(W + "t"))
        return _Unit(element, ("other", element.tag, shown), [])

    def _score(self, old: list[_Unit], new: list[_Unit], *, cell: bool):
        def score(i: int, j: int) -> float:
            a, b = old[i], new[j]
            if a.same[0] != b.same[0]:
                return 0.0
            if cell and a.same[0] == "p":
                # A cell's paragraphs are its value: "426" is edited to "430", in its cell,
                # however little the two have in common.
                return 0.01 + align.alike(a.words, b.words)
            if a.same[0] == "tbl":
                if a.columns is not None and a.columns == b.columns:
                    return 1.0 + align.alike(a.words, b.words)
                return align.alike(a.words, b.words)
            if a.same[0] != "p":
                return 0.0
            shortest, longest = sorted((len(a.words), len(b.words)))
            if shortest <= align.ALIKE * longest:
                return 0.0
            value = align.alike(a.words, b.words)
            return value if value > align.ALIKE else 0.0

        return score

    def merge_story(
        self,
        old_children: list[ET.Element],
        new_children: list[ET.Element],
        part: str,
        *,
        cell: bool = False,
    ) -> list[ET.Element]:
        """The children of a story, `new_children` with every change from `old_children`
        written in. In a table's `cell`, paragraphs are paired in order whatever they say."""
        old = [self._unit(c, self.before, part) for c in old_children if c.tag in _UNITS]
        new = [self._unit(c, self.after, part) for c in new_children if c.tag in _UNITS]
        steps = align.steps(old, new, lambda u: u.same, self._score(old, new, cell=cell))
        at_new = {j: k for k, (_tag, _i, j) in enumerate(steps) if j is not None}
        out: list[ET.Element] = []
        done = 0

        def through(last: int) -> None:
            nonlocal done
            while done <= last:
                out.extend(self._render(steps[done], old, new, part))
                done += 1

        j = 0
        for child in new_children:
            if child.tag in _UNITS:
                through(at_new[j])
                j += 1
            elif child.tag in _FIXED_LAST:
                through(len(steps) - 1)
                out.append(child)
            else:
                out.append(child)
        through(len(steps) - 1)
        return _last_mark_kept(self._apart(out))

    def _apart(self, out: list[ET.Element]) -> list[ET.Element]:
        """Two tables kept apart by an empty paragraph tracked as deleted, where a deleted
        one comes to stand against an inserted one: Word runs two tables that touch into
        one."""
        kept: list[ET.Element] = []
        last_block = None
        for child in out:
            if child.tag == W + "tbl" and last_block is not None and last_block.tag == W + "tbl":
                between = ET.Element(W + "p")
                _mark_paragraph(between, self.change("del"))
                kept.append(between)
            if child.tag in _UNITS:
                last_block = child
            kept.append(child)
        return kept

    def _render(self, step, old: list[_Unit], new: list[_Unit], part: str) -> list[ET.Element]:
        tag, i, j = step
        if tag == "equal":
            self._notes_alike(old[i].element, new[j].element)
            return [new[j].element]
        if tag == "insert":
            self.counts["blocks inserted"] += 1
            return [self.inserted(new[j].element, part)]
        if tag == "delete":
            self.counts["blocks deleted"] += 1
            return [self.deleted(old[i].element, part)]
        a, b = old[i], new[j]
        if a.same[0] == "p":
            self.counts["paragraphs edited"] += 1
            return [self._edited_paragraph(a, b, part)]
        if a.same[0] == "tbl" and a.columns is not None and a.columns == b.columns:
            self.counts["tables edited"] += 1
            return [self._edited_table(a.element, b.element, part)]
        self.counts["blocks replaced"] += 1
        return self._replaced(a.element, b.element, part)

    def _replaced(self, old: ET.Element, new: ET.Element, part: str) -> list[ET.Element]:
        """`old` deleted and `new` inserted in its place."""
        return [self.deleted(old, part), self.inserted(new, part)]

    # -- inserted and deleted blocks ---------------------------------------------------------

    def inserted(self, element: ET.Element, part: str) -> ET.Element:
        """The revision's `element`, all of it tracked as inserted."""
        for note in element.iter(W + "footnoteReference"):
            self._note_inserted(note.get(W + "id", ""))
        if element.tag == W + "tbl":
            for row in element.findall(W + "tr"):
                _row_change(row, self.change("ins"))
                for cell in row.findall(W + "tc"):
                    for child in cell:
                        if child.tag in _UNITS:
                            self._inserted_in_place(child)
            return element
        self._inserted_in_place(element)
        return element

    def _inserted_in_place(self, element: ET.Element) -> None:
        if element.tag == W + "tbl":
            self.inserted(element, DOCUMENT)
            return
        if element.tag != W + "p":
            for paragraph in element.iter(W + "p"):
                self._inserted_in_place(paragraph)
            return
        self.counts["words inserted"] += _word_count(element)
        children = [c for c in element if c.tag != W + "pPr"]
        for child in children:
            element.remove(child)
        for child in self._wrapped(children, "ins"):
            element.append(child)
        _mark_paragraph(element, self.change("ins"))

    def _wrapped(self, children: Iterable[ET.Element], kind: str) -> list[ET.Element]:
        """`children` of a paragraph tracked as `kind`: runs and equations inside one
        change, a link or another container with the change inside it."""
        out: list[ET.Element] = []
        group: ET.Element | None = None
        for child in children:
            if child.tag == W + "r" or child.tag in MATHS:
                if group is None:
                    group = self.change(kind)
                    out.append(group)
                group.append(deleted_text(child) if kind == "del" else child)
                continue
            group = None
            if child.tag in CONTAINERS:
                content = child.find(W + "sdtContent") if child.tag == W + "sdt" else child
                if content is not None:
                    inner = list(content)
                    for node in inner:
                        content.remove(node)
                    for node in self._wrapped(inner, kind):
                        content.append(node)
            out.append(child)
        return out

    def deleted(self, element: ET.Element, part: str) -> ET.Element:
        """The sent document's `element`, all of it tracked as deleted."""
        made = self.carried.carry(element, part)
        if made.tag == W + "tbl":
            for row in made.findall(W + "tr"):
                _row_change(row, self.change("del"))
                for cell in row.findall(W + "tc"):
                    for child in cell:
                        if child.tag in _UNITS:
                            self._deleted_in_place(child)
            return made
        self._deleted_in_place(made)
        return made

    def _deleted_in_place(self, element: ET.Element) -> None:
        if element.tag == W + "tbl":
            for row in element.findall(W + "tr"):
                _row_change(row, self.change("del"))
                for cell in row.findall(W + "tc"):
                    for child in cell:
                        if child.tag in _UNITS:
                            self._deleted_in_place(child)
            return
        if element.tag != W + "p":
            for paragraph in element.iter(W + "p"):
                self._deleted_in_place(paragraph)
            return
        self.counts["words deleted"] += _word_count(element)
        children = [c for c in element if c.tag != W + "pPr"]
        for child in children:
            element.remove(child)
        for child in self._wrapped(_flattened(children), "del"):
            element.append(child)
        _mark_paragraph(element, self.change("del"))

    def deleted_story(self, children: list[ET.Element], part: str) -> list[ET.Element]:
        """A story of the document sent, every block of it tracked as deleted."""
        return [self.deleted(child, part) for child in children if child.tag in _UNITS]

    # -- footnotes ---------------------------------------------------------------------------

    def _note(self, package: Package, note_id: str) -> ET.Element | None:
        tree = package.tree(FOOTNOTES)
        if tree is None:
            return None
        return next((n for n in tree.iter(W + "footnote") if n.get(W + "id") == note_id), None)

    def _notes_alike(self, old: ET.Element, new: ET.Element) -> None:
        """The notes two identical blocks refer to, merged."""
        olds = list(old.iter(W + "footnoteReference"))
        news = list(new.iter(W + "footnoteReference"))
        for a, b in zip(olds, news, strict=False):
            self._note_merged(a.get(W + "id", ""), b.get(W + "id", ""))

    def _note_merged(self, old_id: str, new_id: str) -> None:
        if new_id in self._merged_notes:
            return
        self._merged_notes.add(new_id)
        old, new = self._note(self.before, old_id), self._note(self.after, new_id)
        if old is None or new is None:
            raise MarkedUpError("a footnote referred to is not in the document")
        merged = self.merge_story(list(old), list(new), FOOTNOTES)
        for child in list(new):
            new.remove(child)
        for child in merged:
            new.append(child)

    def _note_inserted(self, new_id: str) -> None:
        if new_id in self._merged_notes:
            return
        self._merged_notes.add(new_id)
        note = self._note(self.after, new_id)
        if note is None:
            raise MarkedUpError("a footnote referred to is not in the document")
        for child in list(note):
            if child.tag in _UNITS:
                self._inserted_in_place(child)

    # -- an edited paragraph -----------------------------------------------------------------

    def _edited_paragraph(self, old: _Unit, new: _Unit, part: str) -> ET.Element:
        a, b = old.paragraph.atoms, new.paragraph.atoms
        out = ET.Element(new.element.tag, dict(new.element.attrib))
        properties = new.element.find(W + "pPr")
        if properties is not None:
            out.append(properties)
        if _properties_key(old.element, self.before) != _properties_key(new.element, self.after):
            self._properties_changed(out, old.element, part)
        emit = _Emitter(self, part, new.paragraph.marks)
        ops = align.changes(
            [x.key for x in a], [x.key for x in b],
            [max(len(x.text), 1) for x in a], [max(len(x.text), 1) for x in b],
            [x.word for x in a],
        )  # fmt: skip
        for tag, i1, i2, j1, j2 in ops:
            if tag == "equal":
                for k in range(i2 - i1):
                    emit.marks_before(j1 + k)
                    emit.equal(a[i1 + k], b[j1 + k])
                continue
            emit.marks_before(j1)
            if i2 > i1:
                emit.deleted(a[i1:i2])
            for k in range(j1, j2):
                emit.marks_before(k)
                emit.inserted(b[k])
        emit.marks_before(len(b))
        for child in emit.finished():
            out.append(child)
        return out

    def _properties_changed(self, paragraph: ET.Element, old: ET.Element, part: str) -> None:
        properties = paragraph.find(W + "pPr")
        if properties is None:
            properties = ET.Element(W + "pPr")
            paragraph.insert(0, properties)
        before = ET.Element(W + "pPr")
        sent = old.find(W + "pPr")
        if sent is not None:
            carried = self.carried.carry(sent, part)
            for child in carried:
                if child.tag not in _PPR_LAST:
                    before.append(child)
        change = self.change("pPrChange")
        change.append(before)
        properties.append(change)
        self.counts["paragraphs restyled"] += 1

    # -- an edited table ----------------------------------------------------------------------

    def _edited_table(self, old: ET.Element, new: ET.Element, part: str) -> ET.Element:
        old_rows, new_rows = old.findall(W + "tr"), new.findall(W + "tr")

        def row_same(row: ET.Element, package: Package) -> tuple:
            return tuple(
                tuple(self._unit(c, package, part).same for c in cell if c.tag in _UNITS)
                for cell in row.findall(W + "tc")
            )

        a = [row_same(r, self.before) for r in old_rows]
        b = [row_same(r, self.after) for r in new_rows]

        def score(i: int, j: int) -> float:
            shared = sum(x == y for x, y in zip(a[i], b[j], strict=False))
            return shared + 0.01

        steps = align.steps(a, b, lambda row: row, score)
        out = ET.Element(new.tag, dict(new.attrib))
        for child in new:
            if child.tag != W + "tr":
                out.append(child)
        for tag, i, j in steps:
            if tag == "equal":
                self._notes_alike(old_rows[i], new_rows[j])
                out.append(new_rows[j])
            elif tag == "insert":
                self.counts["rows inserted"] += 1
                out.append(self._row(new_rows[j], inserted=True, part=part))
            elif tag == "delete":
                self.counts["rows deleted"] += 1
                out.append(self._row(old_rows[i], inserted=False, part=part))
            else:
                out.append(self._edited_row(old_rows[i], new_rows[j], part))
        return out

    def _row(self, row: ET.Element, *, inserted: bool, part: str) -> ET.Element:
        if inserted:
            for note in row.iter(W + "footnoteReference"):
                self._note_inserted(note.get(W + "id", ""))
            _row_change(row, self.change("ins"))
            for cell in row.findall(W + "tc"):
                for child in cell:
                    if child.tag in _UNITS:
                        self._inserted_in_place(child)
            return row
        made = self.carried.carry(row, part)
        _row_change(made, self.change("del"))
        for cell in made.findall(W + "tc"):
            for child in cell:
                if child.tag in _UNITS:
                    self._deleted_in_place(child)
        return made

    def _edited_row(self, old: ET.Element, new: ET.Element, part: str) -> ET.Element:
        out = ET.Element(new.tag, dict(new.attrib))
        for child in new:
            if child.tag != W + "tc":
                out.append(child)
        for old_cell, new_cell in zip(old.findall(W + "tc"), new.findall(W + "tc"), strict=True):
            cell = ET.Element(new_cell.tag, dict(new_cell.attrib))
            fixed = [c for c in new_cell if c.tag == W + "tcPr"]
            for child in fixed:
                cell.append(child)
            merged = self.merge_story(
                [c for c in old_cell if c.tag != W + "tcPr"],
                [c for c in new_cell if c.tag != W + "tcPr"],
                part,
                cell=True,
            )
            for child in merged:
                cell.append(child)
            out.append(cell)
        return out


def _last_mark_kept(story: list[ET.Element]) -> list[ET.Element]:
    """The last paragraph of a story with its mark untracked, its words tracked as they
    are. Word cannot take away a story's last mark, the document's or a cell's: given one
    tracked as deleted, Word 16's Accept All never returns (seen over COM, 2026-10-21). Kept,
    the paragraph is left empty where its words go, and an empty paragraph reads as nothing."""
    last = next((child for child in reversed(story) if child.tag in _UNITS), None)
    if last is not None and last.tag == W + "p":
        mark = last.find(f"{W}pPr/{W}rPr")
        for change in [] if mark is None else [c for c in mark if c.tag in (W + "ins", W + "del")]:
            mark.remove(change)
    return story


def _row_change(row: ET.Element, change: ET.Element) -> None:
    properties = row.find(W + "trPr")
    if properties is None:
        properties = ET.Element(W + "trPr")
        exceptions = row.find(W + "tblPrEx")
        row.insert(0 if exceptions is None else list(row).index(exceptions) + 1, properties)
    last = properties.find(W + "trPrChange")
    properties.insert(len(properties) if last is None else list(properties).index(last), change)


def _flattened(children: Iterable[ET.Element]) -> list[ET.Element]:
    """A deleted paragraph's content as runs and equations: a link or a container gives up
    its runs, since a deletion shows words and not where they pointed."""
    out: list[ET.Element] = []
    for child in children:
        if child.tag == W + "r" or child.tag in MATHS:
            out.append(child)
        elif child.tag in MARKS:
            continue
        else:
            content = child.find(W + "sdtContent") if child.tag == W + "sdt" else child
            out.extend(_flattened(list(child if content is None else content)))
    return out


def _word_count(paragraph: ET.Element) -> int:
    return sum(len((t.text or "").split()) for t in paragraph.iter(W + "t"))


def _made_run(
    source: ET.Element | None, *, text: str = "", child: ET.Element | None = None
) -> ET.Element:
    """A run with `source`'s properties holding `text`, or a copy of `child`."""
    run = ET.Element(W + "r")
    properties = None if source is None else source.find(W + "rPr")
    if properties is not None:
        made = copy.deepcopy(properties)
        for change in made.findall(W + "rPrChange"):
            made.remove(change)
        run.append(made)
    if child is None:
        written = ET.SubElement(run, W + "t")
        written.text = text
        written.set(_XML + "space", "preserve")
    else:
        run.append(copy.deepcopy(child))
    return run


def _runs_of(atom: Atom) -> list[ET.Element]:
    """An atom of a run as runs: a word as one for each run it is in, anything else as one."""
    if atom.pieces:
        return [_made_run(run, text=piece) for run, piece in atom.pieces]
    return [_made_run(atom.run, child=atom.child)]


def _segments(
    old: tuple[tuple[ET.Element, str], ...], new: tuple[tuple[ET.Element, str], ...]
) -> list[tuple[str, ET.Element, ET.Element]]:
    """One word's text cut where the revision's runs are cut or the sent document's runs'
    properties differ: each part, and the run it is in on each side. Not where the sent
    document's runs alone were cut, as Word cuts them, so that a word set in italics whose
    old letters lay in two plain runs is one change of formatting and not two. The two
    sides hold the same text."""

    def ends(pieces: tuple[tuple[ET.Element, str], ...]) -> list[int]:
        out, at = [], 0
        for _run, piece in pieces:
            at += len(piece)
            out.append(at)
        return out

    text = "".join(piece for _run, piece in new)
    old_ends, new_ends = ends(old), ends(new)
    cuts = sorted(set(old_ends) | set(new_ends))
    out: list[tuple[str, ET.Element, ET.Element]] = []
    start = 0
    for cut in cuts:
        was = old[next(i for i, end in enumerate(old_ends) if end >= cut)][0]
        now = new[next(i for i, end in enumerate(new_ends) if end >= cut)][0]
        # Merged only where the old runs look alike in one language, hidden alike: the
        # part's old properties are the first run's, and Reject All gives them back (round 4).
        if out and out[-1][1] is now and _given_back(out[-1][2]) == _given_back(was):
            out[-1] = (out[-1][0] + text[start:cut], now, out[-1][2])
        else:
            out.append((text[start:cut], now, was))
        start = cut
    return out


def _given_back(run: ET.Element) -> tuple:
    """What a reformatted word's old run gives back at Reject All that two runs may not
    share: how it looks, its language, and its being hidden on the web or always (#410).
    Not the order of its properties, an empty `w:rPr`, Word's proofing mark or its script
    hint, which made one word two Formatted marks (the last round of #396)."""
    kept = [c for c in run.findall(f"{W}rPr/*") if c.tag in _GIVEN_BACK]
    return look(run), sorted((c.tag, sorted(c.attrib.items())) for c in kept)


#: What `atoms.look` leaves out that a part of a word keeps apart all the same.
_GIVEN_BACK = frozenset(W + tag for tag in ("lang", "webHidden", "specVanish"))


class _Emitter:
    """The content of one edited paragraph, as it is written: runs kept, deleted and
    inserted, each change one `w:del` or `w:ins` around as many runs as follow each other."""

    def __init__(self, writer: Writer, part: str, marks: list[tuple[int, ET.Element]]) -> None:
        self.writer = writer
        self.part = part
        self.marks = list(marks)
        self.items: list[tuple[str, ET.Element]] = []

    def marks_before(self, index: int) -> None:
        while self.marks and self.marks[0][0] <= index:
            self.items.append(("", self.marks.pop(0)[1]))

    def equal(self, old: Atom, new: Atom) -> None:
        if new.nodes:
            for node in new.nodes:
                self.items.append(("", node))
            return
        if new.key[0] == "note":
            self.writer._note_merged(old.child.get(W + "id", ""), new.child.get(W + "id", ""))
        if old.look == new.look:
            self.items += [("", run) for run in _runs_of(new)]
            return
        self.writer.counts["words reformatted"] += 1
        if not new.pieces:
            for run in _runs_of(new):
                self._look_changed(run, old.run)
                self.items.append(("", run))
            return
        # A word whose look changed in part: cut where either side's runs are cut, so that
        # each part records what it looked like.
        for text, now, was in _segments(old.pieces, new.pieces):
            run = _made_run(now, text=text)
            if look(was) != look(now):
                self._look_changed(run, was)
            self.items.append(("", run))

    def _look_changed(self, run: ET.Element, was: ET.Element | None) -> None:
        properties = run.find(W + "rPr")
        if properties is None:
            properties = ET.Element(W + "rPr")
            run.insert(0, properties)
        change = self.writer.change("rPrChange")
        before = ET.SubElement(change, W + "rPr")
        sent = None if was is None else was.find(W + "rPr")
        if sent is not None:
            for child in self.writer.carried.carry(sent, self.part):
                if child.tag != W + "rPrChange":
                    before.append(child)
        properties.append(change)

    def deleted(self, atoms: list[Atom]) -> None:
        for atom in atoms:
            if atom.nodes:
                nodes = [self.writer.carried.carry(n, self.part) for n in atom.nodes]
                for node in _flattened(nodes):
                    self.items.append(("del", deleted_text(node)))
            else:
                for run in _runs_of(atom):
                    self.items.append(
                        ("del", deleted_text(self.writer.carried.carry(run, self.part)))
                    )
            self.writer.counts["words deleted"] += atom.word

    def inserted(self, atom: Atom) -> None:
        self.writer.counts["words inserted"] += atom.word
        if atom.key[0] == "note":
            self.writer._note_inserted(atom.child.get(W + "id", ""))
        if not atom.nodes:
            self.items += [("ins", run) for run in _runs_of(atom)]
            return
        for node in atom.nodes:
            for found in node.iter(W + "footnoteReference"):
                self.writer._note_inserted(found.get(W + "id", ""))
            if node.tag == W + "r" or node.tag in MATHS:
                self.items.append(("ins", node))
            elif node.tag in MARKS:
                self.items.append(("", node))
            else:
                for made in self.writer._wrapped([node], "ins"):
                    self.items.append(("", made))

    def finished(self) -> list[ET.Element]:
        out: list[ET.Element] = []
        group: ET.Element | None = None
        kind = ""
        for wanted, node in self.items:
            if not wanted:
                group, kind = None, ""
                _joined(out, node)
                continue
            if group is None or kind != wanted:
                group, kind = self.writer.change(wanted), wanted
                out.append(group)
            _joined(list(group), node, into=group)
        return out


def _joined(siblings: list[ET.Element], run: ET.Element, into: ET.Element | None = None) -> None:
    """Append `run`, run into the run before it where both are text alone and look alike."""
    target = siblings if into is None else list(into)
    last = target[-1] if target else None
    if (
        last is not None
        and run.tag == W + "r"
        and last.tag == W + "r"
        and _text_only(run)
        and _text_only(last)
        and _properties(last) == _properties(run)
        and last[-1].tag == run[-1].tag
    ):
        last[-1].text = (last[-1].text or "") + (run[-1].text or "")
        return
    if into is None:
        siblings.append(run)
    else:
        into.append(run)


def _text_only(run: ET.Element) -> bool:
    children = [c for c in run if c.tag != W + "rPr"]
    return len(children) == 1 and children[0].tag in (W + "t", W + "delText")


def _properties(run: ET.Element) -> str:
    found = run.find(W + "rPr")
    return "" if found is None else ET.tostring(found, encoding="unicode")
