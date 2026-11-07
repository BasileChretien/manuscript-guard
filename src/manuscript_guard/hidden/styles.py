"""How a run of a Word document looks once its styles, the document's defaults and its theme
are applied: whether it is hidden, its size, its colour and what is behind it.

Each property is read as Word resolves it, which Word 365 was asked (2026-11-07, a document
built for each case, `Range.Font` read over COM):

- A run's own properties come first and are absolute, `w:vanish w:val="0"` included.
- Then its character style, then its paragraph's style, the default paragraph style where
  the paragraph names none, then the document's defaults (`w:docDefaults`). Each style is
  read along its `w:basedOn` chain, the nearest value winning: a style based on one that
  hides, and itself saying nothing, hides.
- Hiding (`w:vanish`) is an on-off property, and styles toggle it (ISO/IEC 29500-1,
  17.7.3): a level counts only where its value differs from the defaults', and two levels
  that do cancel. A paragraph style that hides holding a character style that hides shows
  its text; with the defaults hiding, a character style saying `w:val="0"` shows its text,
  and one hiding in a paragraph whose style says `w:val="0"` shows it too.
- A colour that names a theme colour (`w:themeColor`) is that colour, tinted or shaded as
  `w:themeTint` and `w:themeShade` say, whatever `w:val` holds.

A table style's properties, and the conditional formats of its rows and columns, are not
read (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from manuscript_guard.colour import RGB

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
#: The values of an on-off property that turn it off.
_OFF = frozenset({"0", "false", "off"})
#: How far along `w:basedOn` a style is followed: no document needs more, and a chain that
#: loops would never end.
_DEPTH = 32
WHITE: RGB = (1.0, 1.0, 1.0)
#: The colours a run can be highlighted in (ST_HighlightColor), as Word paints them.
HIGHLIGHTS: dict[str, str] = {
    "black": "000000", "blue": "0000FF", "cyan": "00FFFF", "green": "00FF00",
    "magenta": "FF00FF", "red": "FF0000", "yellow": "FFFF00", "white": "FFFFFF",
    "darkBlue": "000080", "darkCyan": "008080", "darkGreen": "008000",
    "darkMagenta": "800080", "darkRed": "800000", "darkYellow": "808000",
    "darkGray": "808080", "lightGray": "C0C0C0",
}  # fmt: skip
#: What a theme colour a run names is called in the theme, through the document's mapping
#: of its background and text colours (`w:clrSchemeMapping`) where it is one of those.
_MAPPED = {"background1": "bg1", "text1": "t1", "background2": "bg2", "text2": "t2"}
_MAPPING_DEFAULT = {"bg1": "light1", "t1": "dark1", "bg2": "light2", "t2": "dark2"}
_SCHEME = {
    "dark1": "dk1", "light1": "lt1", "dark2": "dk2", "light2": "lt2",
    **{f"accent{n}": f"accent{n}" for n in range(1, 7)},
    "hyperlink": "hlink", "followedHyperlink": "folHlink",
}  # fmt: skip


def on_off(element: ET.Element | None) -> bool | None:
    """An on-off property's value, or None where it is not given."""
    if element is None:
        return None
    return element.get(f"{W}val", "1").strip().casefold() not in _OFF


def hex_colour(value: str | None) -> RGB | None:
    """Six hexadecimal digits as a colour; None for `auto` or anything else."""
    value = (value or "").strip()
    if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
        return None
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


@dataclass(frozen=True)
class _Style:
    kind: str
    based_on: str | None
    run: ET.Element | None
    paragraph: ET.Element | None


@dataclass
class Styles:
    """A document's styles part, read once, with what each run's styles make of a property."""

    styles: dict[str, _Style] = field(default_factory=dict)
    defaults: ET.Element | None = None
    default_paragraph: str | None = None

    @classmethod
    def read(cls, root: ET.Element | None) -> Styles:
        found = cls()
        if root is None:
            return found
        defaults = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
        found.defaults = defaults
        for style in root.iter(f"{W}style"):
            name = style.get(f"{W}styleId")
            if not name or name in found.styles:
                continue
            based = style.find(f"{W}basedOn")
            kind = style.get(f"{W}type", "paragraph")
            found.styles[name] = _Style(
                kind,
                None if based is None else based.get(f"{W}val"),
                style.find(f"{W}rPr"),
                style.find(f"{W}pPr"),
            )
            default = style.get(f"{W}default", "").strip().casefold() in ("1", "true", "on")
            if kind == "paragraph" and default and found.default_paragraph is None:
                found.default_paragraph = name
        return found

    def paragraph_style(self, named: str | None) -> str | None:
        """The style a paragraph is in: the one it names, if the document has it as a
        paragraph style, or else the default paragraph style."""
        style = self.styles.get(named or "")
        if style is not None and style.kind == "paragraph":
            return named
        return self.default_paragraph

    def _chain(self, name: str | None, kind: str) -> list[_Style]:
        chain: list[_Style] = []
        seen: set[str] = set()
        while name and name not in seen and len(chain) < _DEPTH:
            style = self.styles.get(name)
            if style is None or style.kind != kind:
                break
            seen.add(name)
            chain.append(style)
            name = style.based_on
        return chain

    def _in_chain(self, tag: str, name: str | None, kind: str) -> ET.Element | None:
        for style in self._chain(name, kind):
            if style.run is not None and (found := style.run.find(f"{W}{tag}")) is not None:
                return found
        return None

    def run_property(self, tag: str, paragraph: str | None, character: str | None):
        """The nearest value of the run property `tag` the styles give: the character
        style's, the paragraph style's, the defaults'. None where none gives it."""
        for name, kind in ((character, "character"), (paragraph, "paragraph")):
            if (found := self._in_chain(tag, name, kind)) is not None:
                return found
        return None if self.defaults is None else self.defaults.find(f"{W}{tag}")

    def toggled(self, tag: str, paragraph: str | None, character: str | None):
        """An on-off run property as the styles leave it (see the module's docstring), and
        the styles that turned it, the character style's first; none where the defaults
        alone set it."""
        default = bool(on_off(None if self.defaults is None else self.defaults.find(f"{W}{tag}")))
        value, turned = default, []
        for name, kind in ((character, "character"), (paragraph, "paragraph")):
            level = on_off(self._in_chain(tag, name, kind))
            if level is not None and level != default:
                value = not value
                turned.append(name)
        return value, turned

    def paragraph_shading(self, name: str | None) -> ET.Element | None:
        for style in self._chain(name, "paragraph"):
            if style.paragraph is not None and (shd := style.paragraph.find(f"{W}shd")) is not None:
                return shd
        return None


#: The colours of the theme Word draws with where a document has none: its background white,
#: its text black.
_DEFAULT_THEME: dict[str, RGB] = {"lt1": (1.0, 1.0, 1.0), "dk1": (0.0, 0.0, 0.0)}


@dataclass
class Theme:
    """The theme's colours, by the names a run gives them."""

    colours: dict[str, RGB] = field(default_factory=lambda: dict(_DEFAULT_THEME))
    mapping: dict[str, str] = field(default_factory=lambda: dict(_MAPPING_DEFAULT))

    @classmethod
    def read(cls, theme: ET.Element | None, settings: ET.Element | None) -> Theme:
        found = cls()
        scheme = None if theme is None else theme.find(f".//{_A}clrScheme")
        for slot in [] if scheme is None else list(scheme):
            name = slot.tag.removeprefix(_A)
            colour = slot.find(f"{_A}srgbClr")
            value = None if colour is None else colour.get("val")
            if value is None and (system := slot.find(f"{_A}sysClr")) is not None:
                value = system.get("lastClr")
            if (rgb := hex_colour(value)) is not None:
                found.colours[name] = rgb
        mapping = None if settings is None else settings.find(f"{W}clrSchemeMapping")
        if mapping is not None:
            for key in _MAPPING_DEFAULT:
                if value := mapping.get(f"{W}{key}"):
                    found.mapping[key] = value
        return found

    def colour(self, name: str | None) -> RGB | None:
        if not name:
            return None
        name = self.mapping.get(_MAPPED.get(name, ""), name) if name in _MAPPED else name
        return self.colours.get(_SCHEME.get(name, ""))


def _lightened(rgb: RGB, tint: str | None, shade: str | None) -> RGB:
    """A theme colour with Word's tint (towards white) or shade (towards black), each a
    fraction in hexadecimal of 255, applied to its HSL lightness."""
    hue, light, saturation = colorsys.rgb_to_hls(*rgb)
    for value, lighter in ((tint, True), (shade, False)):
        try:
            fraction = int((value or "").strip(), 16) / 255
        except ValueError:
            continue
        fraction = min(1.0, max(0.0, fraction))
        light = light * fraction + (1 - fraction) if lighter else light * fraction
    return colorsys.hls_to_rgb(hue, light, saturation)


def text_colour(element: ET.Element | None, theme: Theme) -> RGB | None:
    """A run's colour (`w:color`), or None where it is automatic or not given: Word draws
    automatic text in black or white, whichever stands out from what is behind it."""
    if element is None:
        return None
    themed = theme.colour(element.get(f"{W}themeColor"))
    if themed is not None:
        return _lightened(themed, element.get(f"{W}themeTint"), element.get(f"{W}themeShade"))
    return hex_colour(element.get(f"{W}val"))


def fill_colour(element: ET.Element | None, theme: Theme) -> RGB | None:
    """What shading (`w:shd`) paints behind text, or None where it paints nothing: its
    fill, or with a solid pattern the pattern's colour, or a percentage of the pattern's
    colour over the fill."""
    if element is None:
        return None
    themed = theme.colour(element.get(f"{W}themeFill"))
    fill = (
        _lightened(themed, element.get(f"{W}themeFillTint"), element.get(f"{W}themeFillShade"))
        if themed is not None
        else hex_colour(element.get(f"{W}fill"))
    )
    pattern = (element.get(f"{W}val") or "clear").strip()
    if pattern in ("clear", "nil"):
        return fill
    ink = hex_colour(element.get(f"{W}color")) or (0.0, 0.0, 0.0)
    if pattern == "solid":
        return ink
    if pattern.startswith("pct") and pattern[3:].isdigit():
        share = min(100, int(pattern[3:])) / 100
        under = fill or WHITE
        return tuple(i * share + u * (1 - share) for i, u in zip(ink, under, strict=True))  # type: ignore[return-value]
    return fill


def highlight_colour(element: ET.Element | None) -> RGB | None:
    if element is None:
        return None
    return hex_colour(HIGHLIGHTS.get((element.get(f"{W}val") or "").strip()))
