"""How Word numbers a paragraph, as far as `audit` needs it: which count it is in, and whether
that count prints Arabic numerals from 1.

A reference list Word numbers prints no number in its text, so `audit` takes an entry's
number to be its place in the list (`auditing.references`). That holds only where Word
counts the entries 1, 2, 3: each paragraph numbered by one count, at one level, whose format
is decimal and whose text prints that level's number, starting at 1. Anything else, a
bullet, a letter, a count that starts elsewhere, a numbering linked to a numbering style, is
said not to count from one, so that the list is read as one that types its numbers or none.

A paragraph is numbered by its own `w:numPr`, or by its style's, through the styles it is
based on; a numbering of 0 takes a style's numbering off. A count is the abstract numbering
the paragraph's numbering points to, since numberings that share one count on together,
unless the numbering restarts the level with a start of its own. Read from ECMA-376 part 1,
17.9 (numbering), whose defaults are those of a level that leaves a property out: a format
of decimal and a start of 0.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import UnsafeDocument, read_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NUMBERING = "word/numbering.xml"
STYLES = "word/styles.xml"
#: The formats that print a level's count in Arabic numerals, "1" or "01".
_DECIMAL = frozenset({"decimal", "decimalZero"})


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
    return form in _DECIMAL and f"%{int(at) + 1}" in text and begins == "1"


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

    def _style_numbering(self, style: str) -> tuple[str | None, str | None]:
        num, level, seen = None, None, set()
        while style in self.styles and style not in seen:
            seen.add(style)
            based, own_num, own_level = self.styles[style]
            num = own_num if num is None else num
            level = own_level if level is None else level
            style = based
        return num, level

    def of_paragraph(self, paragraph: ET.Element) -> tuple[str, bool] | None:
        """The count a paragraph is numbered in and whether it prints 1, 2, 3 from 1, or
        None where Word numbers it not at all."""
        props = paragraph.find(W + "pPr")
        own = props.find(W + "numPr") if props is not None else None
        style = _val(props, "pStyle") if props is not None else None
        styled_num, styled_level = self._style_numbering(style) if style else (None, None)
        num = _val(own, "numId") or styled_num
        level = _val(own, "ilvl") or styled_level or "0"
        if num is None or num == "0":
            return None
        if num not in self.nums or not level.isdigit():
            return (f"num {num}", False)
        abstract, overridden, starts = self.nums[num]
        levels = self.abstracts.get(abstract)
        if levels is None:
            return (f"num {num}", False)
        chosen = overridden.get(level, levels.get(level))
        # A level the numbering restarts, with a start of its own, is a count of its own;
        # any other counts on with every numbering of the same abstract numbering, which
        # can only make a count seem to start before the list, never after.
        count = f"num {num}:{level}" if level in starts else f"abstract {abstract}:{level}"
        return (count, _from_one(chosen, level, starts.get(level)))
