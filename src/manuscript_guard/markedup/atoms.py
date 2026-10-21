"""A paragraph read as what the two documents are compared by: its atoms, in order.

An atom is a word, a space, a mark of punctuation, a tab or a break, a picture, a footnote's
reference, or a thing that is compared whole: a field (a citation of a live build, known by
what it cites and not by Zotero's words, `citationfields`), a link, an equation. What it is
compared by is its `key`; how its words look is its `look`, compared apart, so that a word
set in italics is a change of formatting and not a word deleted and typed again.

Marks the reader does not see, a bookmark or the start of a comment, are not atoms. They are
kept from the revision, where they stand between its atoms, and left out of what the
document sent contributes: the revision's identifiers are the document's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from manuscript_guard.markedup.package import M, Package, W

#: A word: letters and digits, with the stops, commas, apostrophes and hyphens inside it, so
#: that "3.84", "41,200" and "example-drug" are one word each. Then a run of layout space,
#: then any other single character, a no-break space among them.
_TOKEN = re.compile(r"[^\W_]+(?:[.,'’\-‐‑][^\W_]+)*|[ \t\r\n]+|.", re.DOTALL)
_WORD = re.compile(r"[^\W_]")

#: What a reader does not see, kept from the revision where it stands.
MARKS = frozenset(
    W + tag
    for tag in ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd",
                "proofErr", "permStart", "permEnd", "moveFromRangeStart", "moveFromRangeEnd",
                "moveToRangeStart", "moveToRangeEnd")
)  # fmt: skip
#: Containers of runs, compared whole by the words they show.
CONTAINERS = frozenset(W + tag for tag in ("hyperlink", "fldSimple", "smartTag", "customXml",
                                           "sdt", "dir", "bdo"))  # fmt: skip
MATHS = frozenset((M + "oMath", M + "oMathPara"))
_PICTURES = frozenset(W + tag for tag in ("drawing", "pict", "object"))
#: The parts of a run's properties that do not show: its language, its proofing, a
#: formatting change already tracked, and the script hint Word adds.
_UNSHOWN = frozenset(W + tag for tag in ("lang", "noProof", "rPrChange", "webHidden",
                                         "specVanish"))  # fmt: skip
_UNSHOWN_ATTRIBUTES = frozenset((W + "hint",))
#: What is read as a space in a run, as `docxtext` reads it.
_SPACES = {W + "tab": "\t", W + "ptab": "\t", W + "br": "\n", W + "cr": "\n"}
_LAYOUT_ONLY = frozenset((W + "lastRenderedPageBreak",))


@dataclass
class Atom:
    """One thing compared: what it is compared by, how it looks, what it prints."""

    key: tuple
    look: str
    text: str
    #: The run it is in, for a run's content that is not text; None otherwise.
    run: ET.Element | None = None
    #: The run's content it is, for anything in a run that is not text.
    child: ET.Element | None = None
    #: What it is written as, for a field, a link or an equation: the elements themselves.
    nodes: tuple[ET.Element, ...] = ()
    #: For a word, a space or a mark of text: each run it is in, with its part of the text.
    pieces: tuple[tuple[ET.Element, str], ...] = ()

    @property
    def word(self) -> bool:
        """It counts as a word in saying how alike two paragraphs are."""
        if self.key[0] == "t":
            return bool(_WORD.search(self.text))
        return self.key[0] in _WHOLE


#: Atoms that count as one word each: everything that is not text, a space or a field's
#: workings.
_WHOLE = frozenset(("picture", "note", "citation", "field", "link", "maths", "sym", "other"))


@dataclass
class Read:
    """A paragraph as compared: its atoms, and each mark with the atom it stands before."""

    atoms: list[Atom] = field(default_factory=list)
    marks: list[tuple[int, ET.Element]] = field(default_factory=list)


def look(run: ET.Element | None) -> str:
    """How a run's words look: its properties, without those that do not show."""
    properties = None if run is None else run.find(W + "rPr")
    if properties is None:
        return ""
    parts = []
    for child in properties:
        if child.tag in _UNSHOWN:
            continue
        attributes = sorted(
            (k, v) for k, v in child.attrib.items()
            if k not in _UNSHOWN_ATTRIBUTES and "rsid" not in k
        )  # fmt: skip
        if child.tag == W + "rFonts" and not attributes:
            continue
        parts.append(f"{child.tag}{attributes}")
    return "|".join(sorted(parts))


def _shown(nodes: list[ET.Element]) -> str:
    """The words a group of elements shows: its text, a field's result and not its code."""
    out: list[str] = []
    depth_code: list[bool] = []

    def walk(node: ET.Element) -> None:
        if node.tag == W + "fldChar":
            kind = node.get(W + "fldCharType", "")
            if kind == "begin":
                depth_code.append(True)
            elif kind == "separate" and depth_code:
                depth_code[-1] = False
            elif kind == "end" and depth_code:
                depth_code.pop()
            return
        if node.tag in (W + "t", M + "t") and not any(depth_code):
            out.append(node.text or "")
        elif node.tag in _SPACES and not any(depth_code):
            out.append(" ")
        for child in node:
            if child.tag in (W + "rPr", W + "pPr", W + "del", W + "moveFrom"):
                continue
            walk(child)

    for node in nodes:
        walk(node)
    return "".join(out)


def _code(nodes: list[ET.Element]) -> str:
    return "".join(n.text or "" for g in nodes for n in g.iter(W + "instrText"))


#: What an equation holds that is formatting and not the equation: its runs' Word
#: properties, and the properties Word keeps for its controls.
_MATHS_FORMAT = frozenset((W + "rPr", M + "ctrlPr"))


def _maths_values(node: ET.Element | None) -> tuple:
    """What a property element of an equation sets: each value under it, by name, in order;
    nothing where it sets none. A switch written bare, `<m:nor/>` or `<m:degHide/>`, is on,
    as OMML reads it (round 3 of #396); a property element holding nothing sets nothing."""
    if node is None:
        return ()
    found = []
    for inner in node.iter():
        if inner is node or inner.tag in _MATHS_FORMAT:
            continue
        name = inner.tag.rsplit("}", 1)[-1]
        values = sorted(
            (k.rsplit("}", 1)[-1], v) for k, v in inner.attrib.items() if k.startswith(M)
        )
        if not values and not len(inner) and not name.endswith("Pr"):
            values = [("val", "on")]
        if values:
            found.append((name, tuple(values)))
    return tuple(found)


def _maths_key(equation: ET.Element) -> str:
    """An equation as compared: its structure, the values of its own properties and its text.
    A superscript made a subscript, an accent or a root taken off keeps its letters and is
    another equation (round 1 of #396: compared by its letters, it was none). What Word adds
    when it saves an equation it did not change is left out: a property element that sets
    nothing, and the cutting of its text into runs, consecutive runs alike read as one
    (round 2)."""
    parts: list[tuple] = []

    def walk(node: ET.Element) -> None:
        if node.tag in _MATHS_FORMAT:
            return
        name = node.tag.rsplit("}", 1)[-1]
        if node.tag == M + "r":
            text = "".join(t.text or "" for t in node.iter(M + "t"))
            # What else a run holds, a break or a symbol, is part of it, and so is in its key.
            held = tuple(
                child.tag for child in node if child.tag not in (M + "t", M + "rPr", W + "rPr")
            )
            values = (_maths_values(node.find(M + "rPr")), held)
            if parts and parts[-1][0] == "run" and parts[-1][1] == values and not held:
                parts[-1] = ("run", values, parts[-1][2] + text)
            else:
                parts.append(("run", values, text))
            return
        if node.tag.startswith(M) and name.endswith("Pr"):
            values = _maths_values(node)
            if values:
                parts.append(("set", name, values))
            return
        attributes = sorted(
            (k.rsplit("}", 1)[-1], v) for k, v in node.attrib.items() if k.startswith(M)
        )
        parts.append(("open", name, tuple(attributes)))
        for child in node:
            walk(child)
        parts.append(("close",))

    walk(equation)
    return repr(parts)


def _field_key(nodes: list[ET.Element]) -> tuple:
    from manuscript_guard.citationfields import citation_of

    code = _code(nodes)
    found = citation_of(code)
    if found is not None:
        # And by the words it shows: Zotero writes them anew at each refresh, and a copy
        # that showed the revision's words where the document sent showed others would
        # read, rejected, as neither (round 1 of #396).
        return ("citation", found.identity, _shown(nodes))
    return ("field", " ".join(code.split()[:2]), _shown(nodes))


def _field_kinds(run: ET.Element) -> list[str]:
    return [n.get(W + "fldCharType", "") for n in run.iter(W + "fldChar")]


def _field_end(children: list[ET.Element], start: int) -> int | None:
    """The index of the run that closes the field opened at `start`, None where the
    paragraph does not close it."""
    depth = 0
    for index in range(start, len(children)):
        node = children[index]
        if node.tag != W + "r":
            continue
        for kind in _field_kinds(node):
            depth += kind == "begin"
            depth -= kind == "end"
            if depth == 0:
                return index
    return None


def _pictures_key(node: ET.Element, package: Package, part: str) -> tuple:
    from manuscript_guard.markedup.package import R

    digests = [
        package.picture(value, part)
        for inner in node.iter()
        for name, value in inner.attrib.items()
        if name.startswith(R)
    ]
    return ("picture", tuple(digests))


def _link_key(node: ET.Element, package: Package, part: str) -> tuple:
    from manuscript_guard.markedup.package import R

    target = node.get(W + "anchor") or package.link(node.get(R + "id", ""), part)
    return ("link", target, _shown([node]))


def _content_atom(run: ET.Element, child: ET.Element, package: Package, part: str) -> Atom:
    """A run's content that is not text, as one atom."""
    tag, shown = child.tag, look(run)
    if tag in _SPACES:
        return Atom(("space", tag, child.get(W + "type", "")), shown, " ", run, child)
    if tag == W + "noBreakHyphen":
        return Atom(("t", "-nb"), shown, "-", run, child)
    if tag == W + "softHyphen":
        return Atom(("soft",), shown, "", run, child)
    if tag == W + "sym":
        key = ("sym", child.get(W + "font", ""), child.get(W + "char", "").upper())
        return Atom(key, shown, "\N{WHITE SQUARE}", run, child)
    if tag in _PICTURES:
        return Atom(_pictures_key(child, package, part), "", "\N{WHITE SQUARE}", run, child)
    if tag in (W + "footnoteReference", W + "endnoteReference"):
        return Atom(("note", tag), shown, "\N{SUPERSCRIPT ONE}", run, child)
    if tag == W + "fldChar":
        return Atom(("fld", child.get(W + "fldCharType", "")), "", "", run, child)
    if tag == W + "instrText":
        return Atom(("code", child.text or ""), "", "", run, child)
    return Atom(("other", tag, ET.tostring(child, encoding="unicode")), shown, "", run, child)


class _Reader:
    """Reads a paragraph's atoms in order. Text is read across runs, so that a word Word
    split over two runs, as it does when it saves, is one word."""

    def __init__(self, package: Package, part: str) -> None:
        self.package, self.part = package, part
        self.found = Read()
        self.stream: list[tuple[ET.Element, str]] = []
        self.waiting: list[tuple[int, ET.Element]] = []

    def text(self, run: ET.Element, text: str) -> None:
        if text:
            self.stream.append((run, text))

    def mark(self, mark: ET.Element) -> None:
        if self.stream:
            self.waiting.append((sum(len(t) for _r, t in self.stream), mark))
        else:
            self.found.marks.append((len(self.found.atoms), mark))

    def atom(self, atom: Atom) -> None:
        self.flush()
        self.found.atoms.append(atom)

    def flush(self) -> None:
        """The text read so far as words, spaces and marks, each with the runs it is in."""
        text = "".join(t for _r, t in self.stream)
        starts, at = [], 0
        for _run, piece in self.stream:
            starts.append(at)
            at += len(piece)
        waiting = list(self.waiting)
        for match in _TOKEN.finditer(text):
            low, high = match.span()
            while waiting and waiting[0][0] <= low:
                self.found.marks.append((len(self.found.atoms), waiting.pop(0)[1]))
            pieces = tuple(
                (run, piece[max(low, start) - start : min(high, start + len(piece)) - start])
                for (run, piece), start in zip(self.stream, starts, strict=True)
                if max(low, start) < min(high, start + len(piece))
            )
            shown = "+".join(dict.fromkeys(look(run) for run, _piece in pieces))
            self.found.atoms.append(Atom(("t", match.group()), shown, match.group(), pieces=pieces))
        for _offset, mark in waiting:
            self.found.marks.append((len(self.found.atoms), mark))
        self.stream, self.waiting = [], []

    def run(self, run: ET.Element) -> None:
        for child in run:
            if child.tag == W + "rPr" or child.tag in _LAYOUT_ONLY:
                continue
            if child.tag == W + "t":
                self.text(run, child.text or "")
            else:
                self.atom(_content_atom(run, child, self.package, self.part))


def read(paragraph: ET.Element, package: Package, part: str) -> Read:
    """`paragraph` as its atoms and marks. A field the paragraph opens and does not close is
    read run by run, as are its code and its words."""
    reader = _Reader(package, part)
    children = [c for c in paragraph if c.tag != W + "pPr"]
    index = 0
    while index < len(children):
        child = children[index]
        opens = child.tag == W + "r" and "begin" in _field_kinds(child)
        end = _field_end(children, index) if opens else None
        if child.tag in MARKS:
            reader.mark(child)
        elif end is not None:
            group = children[index : end + 1]
            reader.atom(Atom(_field_key(group), "", _shown(group), nodes=tuple(group)))
            index = end
        elif child.tag == W + "r":
            reader.run(child)
        elif child.tag == W + "hyperlink":
            reader.atom(Atom(_link_key(child, package, part), "", _shown([child]), nodes=(child,)))
        elif child.tag in MATHS:
            text = "".join(t.text or "" for t in child.iter(M + "t"))
            reader.atom(Atom(("maths", _maths_key(child)), "", text, nodes=(child,)))
        elif child.tag == W + "fldSimple":
            key = ("field", " ".join(child.get(W + "instr", "").split()[:2]), _shown([child]))
            reader.atom(Atom(key, "", _shown([child]), nodes=(child,)))
        else:
            key = ("other", child.tag, _shown([child]))
            reader.atom(Atom(key, "", _shown([child]), nodes=(child,)))
        index += 1
    reader.flush()
    return reader.found


def words(paragraph: Read) -> list[tuple]:
    """The keys of the atoms that are words, for how alike two paragraphs are."""
    return [atom.key for atom in paragraph.atoms if atom.word]


def signature(paragraph: Read) -> tuple:
    """What two paragraphs that print the same thing alike have equal: every atom and how
    it looks."""
    return tuple((atom.key, atom.look) for atom in paragraph.atoms)
