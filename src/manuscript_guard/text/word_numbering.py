"""How Word numbers a paragraph, as far as `audit` needs it: which count it is in, and whether
that count prints Arabic numerals from 1.

A reference list Word numbers prints no number in its text, so `audit` takes an entry's
number to be its place in the list (`auditing.references`). That holds only where Word
counts the entries 1, 2, 3: each paragraph numbered by one count, at one level, whose format
is decimal and whose text prints that level's number and no other's, starting at 1.
Anything else, a bullet, a letter, "1.1", a count that starts elsewhere, a numbering linked
to a numbering style, and a level the reader cannot resolve for sure, is said not to count
from one, so that the list is read as one that types its numbers or none.

A paragraph is numbered by its own `w:numPr`, or by its style's, through the styles it is
based on; a numbering of 0 takes a style's numbering off. A count is the abstract numbering
the paragraph's numbering points to, since numberings that share one count on together,
unless the numbering restarts the level with a start of its own. Read from ECMA-376 part 1,
17.9 (numbering), whose defaults are those of a level that leaves a property out: a format
of decimal and a start of 0.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import UnsafeDocument, read_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NUMBERING = "word/numbering.xml"
STYLES = "word/styles.xml"
#: The formats that print a level's count in Arabic numerals, "1" or "01".
_DECIMAL = frozenset({"decimal", "decimalZero"})
#: Each level a level's text prints the number of, `%1`.
_PLACES = re.compile(r"%([1-9])")


def _val(element: ET.Element | None, child: str) -> str | None:
    found = element.find(W + child) if element is not None else None
    return found.get(W + "val") if found is not None else None


def _from_one(level: ET.Element | None, at: str, start: str | None) -> bool:
    """Whether a level counts "1", "2", "3": decimal, printing its own number, from 1."""
    if level is None:
        return False
    form = _val(level, "numFmt") or "decimal"
    text = _val(level, "lvlText") or ""
    begins = start if start is not None else (_val(level, "start") or "0")
    # Its own number and no other level's: "%1.%2" prints "1.1", "1.2" (round 2 of #463).
    return form in _DECIMAL and _PLACES.findall(text) == [str(int(at) + 1)] and begins == "1"


@dataclass
class Numbering:
    """A document's numberings and its styles' numbering, read once."""

    #: numId: (abstractNumId, {ilvl: lvl}, {ilvl: start a level override gives})
    nums: dict[str, tuple[str, dict[str, ET.Element], dict[str, str]]] = field(default_factory=dict)
    #: abstractNumId: {ilvl: lvl}, None where it links to a numbering style.
    abstracts: dict[str, dict[str, ET.Element] | None] = field(default_factory=dict)
    #: styleId: (basedOn, numId, ilvl), as the style itself writes them.
    styles: dict[str, tuple[str, str | None, str | None]] = field(default_factory=dict)

    @classmethod
    def of(cls, archive: zipfile.ZipFile, names: set[str], what: str) -> Numbering:
        """The numberings of the document in `archive`; none where a part cannot be read
        safely, so that no list is taken for one Word numbers."""
        found = cls()
        try:
            if NUMBERING in names:
                found._read_numbering(read_part(archive, NUMBERING, what=f"{what}:{NUMBERING}"))
            if STYLES in names:
                found._read_styles(read_part(archive, STYLES, what=f"{what}:{STYLES}"))
        except UnsafeDocument:
            return cls()
        return found

    def _read_numbering(self, root: ET.Element) -> None:
        for abstract in root.iter(W + "abstractNum"):
            linked = abstract.find(W + "numStyleLink") is not None
            levels = {level.get(W + "ilvl", ""): level for level in abstract.iter(W + "lvl")}
            self.abstracts[abstract.get(W + "abstractNumId", "")] = None if linked else levels
        for num in root.iter(W + "num"):
            levels, starts = {}, {}
            for override in num.iter(W + "lvlOverride"):
                at = override.get(W + "ilvl", "")
                level = override.find(W + "lvl")
                if level is not None:
                    levels[at] = level
                start = _val(override, "startOverride")
                if start is not None:
                    starts[at] = start
            self.nums[num.get(W + "numId", "")] = (_val(num, "abstractNumId") or "", levels,
                                                    starts)  # fmt: skip

    def _read_styles(self, root: ET.Element) -> None:
        for style in root.iter(W + "style"):
            if style.get(W + "type") != "paragraph":
                continue
            numbered = style.find(f"{W}pPr/{W}numPr")
            self.styles[style.get(W + "styleId", "")] = (
                _val(style, "basedOn") or "",
                _val(numbered, "numId"),
                _val(numbered, "ilvl"),
            )

    def _style_numbering(self, style: str) -> tuple[str | None, str | None, str]:
        """The numbering a paragraph's style gives it, through the styles it is based on:
        its numId, its ilvl, and the style that gives the numId."""
        num, level, source, seen = None, None, "", set()
        while style in self.styles and style not in seen:
            seen.add(style)
            based, own_num, own_level = self.styles[style]
            if num is None and own_num is not None:
                num, source = own_num, style
            level = own_level if level is None else level
            style = based
        return num, level, source

    def of_paragraph(self, paragraph: ET.Element) -> tuple[str, bool] | None:
        """The count a paragraph is numbered in and whether it prints 1, 2, 3 from 1, or
        None where Word numbers it not at all. A level the reader cannot resolve for sure is
        said not to count from one (round 2 of #463): a paragraph's own `w:numPr` that
        leaves out its numId or its level, and a style's numbering whose level is not the one
        its abstract numbering links to the style by `w:pStyle`, or is not written."""
        props = paragraph.find(W + "pPr")
        own = props.find(W + "numPr") if props is not None else None
        style = _val(props, "pStyle") if props is not None else None
        own_num, own_level = _val(own, "numId"), _val(own, "ilvl")
        if own_num == "0":
            return None
        if own is not None and (own_num is None) != (own_level is None):
            num = own_num or (self._style_numbering(style)[0] if style else None)
            return None if num is None or num == "0" else (f"num {num}", False)
        if own_num is not None:
            num, level, sure = own_num, own_level, True
        else:
            num, level, source = self._style_numbering(style) if style else (None, None, "")
            if num is None or num == "0":
                return None
            level, sure = self._style_level(num, level, source)
        if not sure or num not in self.nums or not (level.isascii() and level.isdigit()):
            return (f"num {num}", False)
        abstract, overridden, starts = self.nums[num]
        levels = self.abstracts.get(abstract)
        if levels is None:
            return (f"num {num}", False)
        chosen = overridden.get(level, levels.get(level))
        # A level the numbering restarts, with a start of its own, is a count of its own;
        # any other counts on with every numbering of the same abstract numbering (Word 16,
        # over COM: a numbering with a startOverride, used after another of the same
        # abstract numbering, starts again at 1, and a third with none counts on from the
        # first).
        count = f"num {num}:{level}" if level in starts else f"abstract {abstract}:{level}"
        return (count, _from_one(chosen, level, starts.get(level)))

    def level_of(self, paragraph: ET.Element) -> int | None:
        """The level of the list a paragraph is an item of, 0 for the outermost, or None
        where Word numbers it not at all: its own `w:ilvl`, or its style's, as `of_paragraph`
        reads them; a level left out is 0, ECMA-376's default. What a flow is read from in a
        .docx (`stats/flows.py`)."""
        props = paragraph.find(W + "pPr")
        own = props.find(W + "numPr") if props is not None else None
        style = _val(props, "pStyle") if props is not None else None
        own_num, level = _val(own, "numId"), _val(own, "ilvl")
        if own_num == "0":
            return None
        if own_num is None:
            found = self._style_numbering(style) if style else (None, None, "")
            num, style_level, source = found
            if num is None or num == "0":
                return None
            if level is None:
                level = self._style_level(num, style_level, source)[0]
        return int(level) if level and level.isascii() and level.isdigit() else 0

    def _style_level(self, num: str, level: str | None, source: str) -> tuple[str, bool]:
        """The level a style's numbering numbers its paragraphs at, and whether that is
        sure: the one level of the abstract numbering linked to the style by `w:pStyle`, or
        where none is linked to any style, the level the style writes."""
        abstract = self.nums.get(num, ("", {}, {}))[0]
        levels = self.abstracts.get(abstract) or {}
        linked = {at: _val(lvl, "pStyle") for at, lvl in levels.items()}
        mine = [at for at, named in linked.items() if named == source]
        if len(mine) == 1:
            return mine[0], True
        if not any(linked.values()) and not mine and level is not None:
            return level, True
        return level or "0", False
