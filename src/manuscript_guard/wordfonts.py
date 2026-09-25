"""Which font Word draws a character in, and what the Symbol font's characters are.

Insert > Symbol with the Symbol font writes no text. Word writes an element naming the font
and the character's code in it, `<w:sym w:font="Symbol" w:char="F0B1"/>` for ±, and does so
for every character of that font (verified 2026-09-25, Word 16: ±, minus, μ, α, ≤). Text
typed with the Symbol font selected is text in that font's own encoding: an `m`, or the
private-use U+F06D, which Word draws as μ. Read as nothing, an inserted ± was dropped and the
rest of the edit merged into the source without it; read as written, "5 μg" was "5 mg".

So a character is read as what Word draws, and which font draws it is decided as Word decides
it. Each was checked against Word 16, whose own text reports a character the Symbol font
draws as U+F0xx:

- A run names up to three fonts: `ascii` draws U+0000-U+007F, `hAnsi` the rest of Latin, and
  `eastAsia` CJK. With `w:hint="eastAsia"`, some Latin-1 characters (±, °, ×...) and the
  private-use U+F000-U+F0FF go to `eastAsia` instead.
- A font comes from the run's own formatting, else its character style, else its paragraph
  style, else the document's defaults, following each style's `basedOn`; a `...Theme`
  attribute names one of the theme's fonts instead.

A Symbol code with no character of its own - a piece of a tall bracket, radical or arrow, or
no glyph at all - has no text, and nor has what another symbol font draws, inserted or typed:
Wingdings above all, whose glyphs Unicode mostly lacks. `J` typed in Wingdings is its smiley,
and read as written it merged into the source as a J. Word marks a symbol font in the
document's font table with `w:charset w:val="02"` (Word 16: Symbol, Wingdings, Webdings, and
not Segoe MDL2 Assets). A private-use character that another font draws is kept as it is.
Each is named: the import refuses a paragraph that came back holding more of one than it was
sent with, rather than merge it without, and the audit reads a space where there is no text.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from functools import cached_property
from xml.etree import ElementTree as ET

from manuscript_guard.safexml import read_part

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

#: Adobe's Symbol encoding, the font's code -> the Unicode character it draws, from the Unicode
#: Consortium's mapping (https://www.unicode.org/Public/MAPPINGS/VENDORS/ADOBE/symbol.txt).
#: Where it gives two characters for a code, the one that is not a compatibility character:
#: Greek Δ, Ω and μ rather than increment, ohm and micro, the fraction slash rather than the
#: division slash, a space rather than a no-break space. The serif and sans-serif ®, © and ™,
#: which it maps into Adobe's private-use area, are the signs themselves. The pieces of tall
#: brackets, radicals and arrows it maps there too have no text, and are left out. So is
#: 0xA0, € in Adobe's later Symbol font: the one Windows ships has no glyph there, and read
#: as €, a no-break space typed in that font would have put a euro sign in the source.
_ENCODING = {
    0x20: 0x0020, 0x21: 0x0021, 0x22: 0x2200, 0x23: 0x0023, 0x24: 0x2203, 0x25: 0x0025,
    0x26: 0x0026, 0x27: 0x220B, 0x28: 0x0028, 0x29: 0x0029, 0x2A: 0x2217, 0x2B: 0x002B,
    0x2C: 0x002C, 0x2D: 0x2212, 0x2E: 0x002E, 0x2F: 0x002F, 0x30: 0x0030, 0x31: 0x0031,
    0x32: 0x0032, 0x33: 0x0033, 0x34: 0x0034, 0x35: 0x0035, 0x36: 0x0036, 0x37: 0x0037,
    0x38: 0x0038, 0x39: 0x0039, 0x3A: 0x003A, 0x3B: 0x003B, 0x3C: 0x003C, 0x3D: 0x003D,
    0x3E: 0x003E, 0x3F: 0x003F, 0x40: 0x2245, 0x41: 0x0391, 0x42: 0x0392, 0x43: 0x03A7,
    0x44: 0x0394, 0x45: 0x0395, 0x46: 0x03A6, 0x47: 0x0393, 0x48: 0x0397, 0x49: 0x0399,
    0x4A: 0x03D1, 0x4B: 0x039A, 0x4C: 0x039B, 0x4D: 0x039C, 0x4E: 0x039D, 0x4F: 0x039F,
    0x50: 0x03A0, 0x51: 0x0398, 0x52: 0x03A1, 0x53: 0x03A3, 0x54: 0x03A4, 0x55: 0x03A5,
    0x56: 0x03C2, 0x57: 0x03A9, 0x58: 0x039E, 0x59: 0x03A8, 0x5A: 0x0396, 0x5B: 0x005B,
    0x5C: 0x2234, 0x5D: 0x005D, 0x5E: 0x22A5, 0x5F: 0x005F, 0x61: 0x03B1, 0x62: 0x03B2,
    0x63: 0x03C7, 0x64: 0x03B4, 0x65: 0x03B5, 0x66: 0x03C6, 0x67: 0x03B3, 0x68: 0x03B7,
    0x69: 0x03B9, 0x6A: 0x03D5, 0x6B: 0x03BA, 0x6C: 0x03BB, 0x6D: 0x03BC, 0x6E: 0x03BD,
    0x6F: 0x03BF, 0x70: 0x03C0, 0x71: 0x03B8, 0x72: 0x03C1, 0x73: 0x03C3, 0x74: 0x03C4,
    0x75: 0x03C5, 0x76: 0x03D6, 0x77: 0x03C9, 0x78: 0x03BE, 0x79: 0x03C8, 0x7A: 0x03B6,
    0x7B: 0x007B, 0x7C: 0x007C, 0x7D: 0x007D, 0x7E: 0x223C, 0xA1: 0x03D2,
    0xA2: 0x2032, 0xA3: 0x2264, 0xA4: 0x2044, 0xA5: 0x221E, 0xA6: 0x0192, 0xA7: 0x2663,
    0xA8: 0x2666, 0xA9: 0x2665, 0xAA: 0x2660, 0xAB: 0x2194, 0xAC: 0x2190, 0xAD: 0x2191,
    0xAE: 0x2192, 0xAF: 0x2193, 0xB0: 0x00B0, 0xB1: 0x00B1, 0xB2: 0x2033, 0xB3: 0x2265,
    0xB4: 0x00D7, 0xB5: 0x221D, 0xB6: 0x2202, 0xB7: 0x2022, 0xB8: 0x00F7, 0xB9: 0x2260,
    0xBA: 0x2261, 0xBB: 0x2248, 0xBC: 0x2026, 0xBF: 0x21B5, 0xC0: 0x2135, 0xC1: 0x2111,
    0xC2: 0x211C, 0xC3: 0x2118, 0xC4: 0x2297, 0xC5: 0x2295, 0xC6: 0x2205, 0xC7: 0x2229,
    0xC8: 0x222A, 0xC9: 0x2283, 0xCA: 0x2287, 0xCB: 0x2284, 0xCC: 0x2282, 0xCD: 0x2286,
    0xCE: 0x2208, 0xCF: 0x2209, 0xD0: 0x2220, 0xD1: 0x2207, 0xD2: 0x00AE, 0xD3: 0x00A9,
    0xD4: 0x2122, 0xD5: 0x220F, 0xD6: 0x221A, 0xD7: 0x22C5, 0xD8: 0x00AC, 0xD9: 0x2227,
    0xDA: 0x2228, 0xDB: 0x21D4, 0xDC: 0x21D0, 0xDD: 0x21D1, 0xDE: 0x21D2, 0xDF: 0x21D3,
    0xE0: 0x25CA, 0xE1: 0x2329, 0xE2: 0x00AE, 0xE3: 0x00A9, 0xE4: 0x2122, 0xE5: 0x2211,
    0xF1: 0x232A, 0xF2: 0x222B, 0xF3: 0x2320, 0xF5: 0x2321,
}  # fmt: skip

#: The Latin-1 characters `w:hint="eastAsia"` sends to the East Asian font (Word 16 agrees).
_HINTED = frozenset(
    [0xA1, 0xA4, 0xA7, 0xA8, 0xAA, 0xAD, 0xAF, *range(0xB0, 0xB5), *range(0xB6, 0xBB)]
    + [*range(0xBC, 0xC0), 0xD7, 0xF7]
)
#: Where symbol fonts keep their characters, as text: the code plus U+F000.
_PRIVATE = range(0xF000, 0xF100)
#: Every private-use character: the symbol range, icon fonts (Segoe MDL2 Assets keeps its
#: glyphs at U+E700), and the supplementary planes 15 and 16.
_PRIVATE_USE = re.compile(f"[{chr(0xE000)}-{chr(0xF8FF)}{chr(0xF0000)}-{chr(0x10FFFF)}]")


def symbol_character(code: int) -> str | None:
    """The character the Symbol font draws for `code`, given with or without U+F000; None
    when it draws a piece of something, or nothing."""
    code = code - 0xF000 if code in _PRIVATE else code
    found = _ENCODING.get(code)
    return chr(found) if found is not None else None


#: Symbol fonts wherever a document's font table does not say: Word marks one there with
#: `w:charset w:val="02"`, as it does Symbol, Wingdings and Webdings (Word 16).
_SYMBOL_FONTS = frozenset(
    {"symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings", "marlett", "mt extra"}
)


def _in_symbol_range(code: int) -> bool:
    """Whether a symbol font draws `code` as one of its own: the code, or it plus U+F000."""
    return 0x20 <= code < 0x100 or code in _PRIVATE


def drawn(
    char: str, font: str | None, symbol_fonts: frozenset[str], missing: str = ""
) -> tuple[str, str | None]:
    """What `char` shows drawn in `font`, and its name when that is no exact text.

    Word draws text in a symbol font as that font's own characters, typed or inserted: `J`
    in Wingdings is its smiley, as it reports U+F04A for it (Word 16). The Symbol font's are
    read through Adobe's encoding; another's have no text, and are named as `w:sym` names
    them, "Wingdings character F04A", so typed and inserted count as one. A private-use
    character another font draws is kept, and named without the font.
    """
    code = ord(char)
    face = font.lower() if font else ""
    if face in symbol_fonts and _in_symbol_range(code):
        glyph = code | 0xF000
        if face == "symbol":
            shown = symbol_character(code)
            if shown is None:
                return missing, f"Symbol character {glyph:04X}"
            return shown, None
        if glyph == 0xF020:
            return " ", None
        return missing, f"{font} character {glyph:04X}"
    if _PRIVATE_USE.match(char):
        return char, f"private-use character {code:04X}"
    return char, None


def symbol(node: ET.Element) -> tuple[str | None, str]:
    """What a `w:sym` shows, and how to name it when that is no text: "Wingdings character F04A"."""
    font = node.get(W + "font", "")
    raw = node.get(W + "char", "").upper()
    try:
        code = int(raw, 16)
    except ValueError:
        return None, f"{font or 'default font'} character {raw}"
    name = f"{font or 'default font'} character {code | 0xF000 if code < 0x100 else code:04X}"
    if font.lower() != "symbol":
        return None, name
    return symbol_character(code), name


@dataclass(frozen=True)
class _Style:
    based_on: str | None
    fonts: dict[str, str]


#: The run properties that name fonts, and the hint.
_FONT_KEYS = ("ascii", "hAnsi", "eastAsia", "asciiTheme", "hAnsiTheme", "eastAsiaTheme", "hint")


def _fonts_of(properties: ET.Element | None) -> dict[str, str]:
    fonts = properties.find(W + "rFonts") if properties is not None else None
    if fonts is None:
        return {}
    return {key: fonts.get(W + key) for key in _FONT_KEYS if fonts.get(W + key)}


@dataclass(frozen=True)
class RunFonts:
    """The fonts one run draws in, each with where it came from: "run" when the run names it."""

    ascii: tuple[str | None, str]
    hansi: tuple[str | None, str]
    east_asia: tuple[str | None, str]
    hint: str | None
    #: The document's symbol fonts, lower case.
    symbol_fonts: frozenset[str] = _SYMBOL_FONTS

    def _slot(self, code: int) -> tuple[str | None, str] | None:
        if code < 0x80:
            return self.ascii
        hinted = self.hint == "eastAsia"
        if code < 0x100:
            return self.east_asia if hinted and code in _HINTED else self.hansi
        if code in _PRIVATE:
            return self.east_asia if hinted else self.hansi
        return None

    @cached_property
    def _symbolic(self) -> bool:
        slots = (self.ascii, self.hansi, self.east_asia)
        return any(font and font.lower() in self.symbol_fonts for font, _ in slots)

    def read(self, text: str, missing: str = "") -> tuple[str, tuple[str, ...]]:
        """`text` as Word draws it, and what in it has no exact text, named; see `drawn`.

        What has no text is replaced by `missing`. A Symbol-font character whose font a
        style, the defaults or the theme sets is read, and named as well: the import takes a
        font set on the text itself as exact, and refuses what depends on following styles.

        A private-use character that another font draws is kept as it is, and named without
        the font: the source may hold one, pasted from an old document, and dropped from the
        text, or named after a font the co-author changed, it read as an edit, and every
        change to its paragraph was refused.

        Every occurrence is named, not each kind once: the import counts them against the
        document as sent, and a second of a code the paragraph held already was merged.
        """
        if not self._symbolic and not _PRIVATE_USE.search(text):
            return text, ()
        out: list[str] = []
        unread: list[str] = []
        for char in text:
            code = ord(char)
            font, origin = self._slot(code) or (None, "run")
            shown, name = drawn(char, font, self.symbol_fonts, missing)
            if name is not None:
                unread.append(name)
            elif origin != "run" and _is_symbol(font) and _in_symbol_range(code):
                unread.append(f"Symbol font from {origin}")
            out.append(shown)
        return "".join(out), tuple(unread)


def _is_symbol(font: str | None) -> bool:
    return font is not None and font.lower() == "symbol"


class Fonts:
    """A document's styles, defaults and theme fonts, for deciding which font a run is in."""

    def __init__(
        self,
        styles: dict[str, _Style] | None = None,
        default_paragraph: str | None = None,
        defaults: dict[str, str] | None = None,
        theme: dict[str, str] | None = None,
        symbol_fonts: frozenset[str] = _SYMBOL_FONTS,
    ) -> None:
        self.styles = styles or {}
        self.default_paragraph = default_paragraph
        self.defaults = defaults or {}
        self.theme = theme or {}
        self.symbol_fonts = symbol_fonts
        self._runs: dict[tuple, RunFonts] = {}
        # Each paragraph's style, found once for all its runs.
        self._paragraphs: dict[ET.Element, str | None] = {}

    def drawn(self, char: str, font: str | None, missing: str = "") -> tuple[str, str | None]:
        """What `char` shows in the font an element names itself, as `w16se:symEx` does."""
        return drawn(char, font, self.symbol_fonts, missing)

    @classmethod
    def of(cls, archive: zipfile.ZipFile, what: str) -> Fonts:
        """Read from `word/styles.xml`, the theme and the font table. Raises `UnsafeDocument`
        as `read_part` does."""
        names = set(archive.namelist())
        symbol_fonts = set(_SYMBOL_FONTS)
        if "word/fontTable.xml" in names:
            table = read_part(archive, "word/fontTable.xml", what=f"{what}:word/fontTable.xml")
            for font in table.iter(W + "font"):
                charset = font.find(W + "charset")
                if charset is not None and charset.get(W + "val", "").upper() == "02":
                    symbol_fonts.add(font.get(W + "name", "").lower())
        styles: dict[str, _Style] = {}
        default_paragraph = None
        defaults: dict[str, str] = {}
        if "word/styles.xml" in names:
            root = read_part(archive, "word/styles.xml", what=f"{what}:word/styles.xml")
            for style in root.iter(W + "style"):
                ident = style.get(W + "styleId", "")
                based = style.find(W + "basedOn")
                styles[ident] = _Style(
                    based.get(W + "val") if based is not None else None,
                    _fonts_of(style.find(W + "rPr")),
                )
                default = style.get(W + "default") in ("1", "true")
                if default and style.get(W + "type") == "paragraph":
                    default_paragraph = ident
            defaults = _fonts_of(root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr"))
        theme = _theme(archive, names, what)
        return cls(styles, default_paragraph, defaults, theme, frozenset(symbol_fonts))

    def _chain(self, ident: str | None) -> list[tuple[str, dict[str, str]]]:
        found: list[tuple[str, dict[str, str]]] = []
        while ident and ident in self.styles and all(ident != i for i, _ in found):
            found.append((ident, self.styles[ident].fonts))
            ident = self.styles[ident].based_on
        return found

    def run(self, run: ET.Element | None, paragraph: ET.Element | None) -> RunFonts:
        """The fonts `run`, in `paragraph`, draws in."""
        direct = _fonts_of(run.find(W + "rPr")) if run is not None else {}
        character = _style_of(run, "rPr", "rStyle")
        if paragraph is None:
            paragraph_style = self.default_paragraph
        elif paragraph in self._paragraphs:
            paragraph_style = self._paragraphs[paragraph]
        else:
            paragraph_style = _style_of(paragraph, "pPr", "pStyle") or self.default_paragraph
            self._paragraphs[paragraph] = paragraph_style
        key = (tuple(sorted(direct.items())), character, paragraph_style)
        if key not in self._runs:
            levels = [("run", direct)]
            levels += [(f"the style {i}", f) for i, f in self._chain(character)]
            levels += [(f"the style {i}", f) for i, f in self._chain(paragraph_style)]
            levels.append(("the document's defaults", self.defaults))
            self._runs[key] = RunFonts(
                self._resolve(levels, "ascii"),
                self._resolve(levels, "hAnsi"),
                self._resolve(levels, "eastAsia"),
                next((f["hint"] for _, f in levels if "hint" in f), None),
                self.symbol_fonts,
            )
        return self._runs[key]

    def _resolve(
        self, levels: list[tuple[str, dict[str, str]]], slot: str
    ) -> tuple[str | None, str]:
        for origin, fonts in levels:
            if slot + "Theme" in fonts:
                return self.theme.get(fonts[slot + "Theme"]), "the document's theme"
            if slot in fonts:
                return fonts[slot], origin
        return None, "the document's defaults"


def _style_of(element: ET.Element | None, properties: str, tag: str) -> str | None:
    # Two plain finds: a path goes through ElementPath, and this runs for every run.
    props = element.find(W + properties) if element is not None else None
    found = props.find(W + tag) if props is not None else None
    return found.get(W + "val") if found is not None else None


def _theme(archive: zipfile.ZipFile, names: set[str], what: str) -> dict[str, str]:
    """The theme's fonts by the names `w:asciiTheme` and its kin give them: "minorHAnsi"..."""
    part = None
    if "word/_rels/document.xml.rels" in names:
        part_name = "word/_rels/document.xml.rels"
        rels = read_part(archive, part_name, what=f"{what}:{part_name}")
        for relation in rels.iter(_RELS):
            if relation.get("Type", "").endswith("/theme"):
                part = posixpath.normpath(posixpath.join("word", relation.get("Target", "")))
    if part is None or part not in names:
        return {}
    root = read_part(archive, part, what=f"{what}:{part}")
    fonts: dict[str, str] = {}
    for scheme in ("major", "minor"):
        found = root.find(f".//{_A}{scheme}Font")
        if found is None:
            continue
        for element, slots in (("latin", ("Ascii", "HAnsi")), ("ea", ("EastAsia",))):
            face = found.find(_A + element)
            if face is not None and face.get("typeface"):
                fonts.update({scheme + slot: face.get("typeface") for slot in slots})
    return fonts
