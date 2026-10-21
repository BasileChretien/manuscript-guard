"""Colours as a reader sees them: with a colour-vision deficiency, and printed in grey.

About one man in twelve and one woman in two hundred of European descent see colour with a
deficiency, most of them red and green less apart than others do. Two series a figure tells
apart by colour alone can then be one series. So the colours a figure paints are taken
through what each of the three dichromacies makes of them, and through grey, and a pair that
is distinct to normal vision and is not after is said.

* **What a deficiency makes of a colour** is Machado, Oliveira and Fernandes's model at full
  severity (IEEE TVCG 15(6):1291-1298, 2009, doi:10.1109/TVCG.2009.113): a matrix for
  protanopia, deuteranopia and tritanopia each, as the authors' page prints them (Table 1,
  severity 1.0), applied to linear RGB, as colorspacious and R's colorspace apply them
  (Zeileis et al., Journal of Statistical Software 96(1), 2020, doi:10.18637/jss.v096.i01).
* **Grey** is the grey of the same relative luminance, Y of sRGB's linear values with the
  coefficients of IEC 61966-2-1, which is how a conversion to greyscale keeps lightness.
* **How far apart two colours are** is CIEDE2000 (CIE 142-2001; as implemented and tested
  by Sharma, Wu and Dalal, Color Research and Application 30(1):21-30, 2005), between their
  CIELAB values under D65.
* **A scale** is left out: colours chained within the threshold of one another, three or
  more, are the shades of a colormap, compared with nothing (round 1 of #398). What a
  deficiency does to a scale is whether its lightness still runs one way, a question for
  the figure's review, not this.
* **Distinct** is a difference of at least `THRESHOLD`, 10. No standard sets one. A
  difference of about 2 is the least an observer sees side by side in large patches; marks
  as small as a figure's lines and points need far more (Szafir, IEEE TVCG 24(1):392-401,
  2018); Adobe's Leonardo takes 11 as passing for a simulated deficiency. 10 is a choice,
  written down here and in DESIGN.md, and a pair already below it to normal vision is not
  said, since a deficiency did not make it so.

Everything is the standard library's: no gate may need numpy.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

#: sRGB, each channel from 0 to 1.
RGB = tuple[float, float, float]
Lab = tuple[float, float, float]

THRESHOLD = 10.0
#: Colours chained within the threshold of one another, this many or more, are the shades
#: of one scale: a colormap, a gradient of points. Their neighbours sit just over the
#: threshold apart, and anything that takes their chroma away brings them under it.
SCALE = 3
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia")
GREYSCALE = "greyscale"

#: Machado et al. (2009), Table 1, severity 1.0, rows as printed.
MACHADO_2009 = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}
#: Linear sRGB to CIE XYZ, and the D65 white, IEC 61966-2-1.
_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
_WHITE = (0.95047, 1.0, 1.08883)

#: The colours CSS names (CSS Color Module Level 4, section 6.1), each as its hex code.
_NAMES = (
    "aliceblue:f0f8ff antiquewhite:faebd7 aqua:00ffff aquamarine:7fffd4 azure:f0ffff "
    "beige:f5f5dc bisque:ffe4c4 black:000000 blanchedalmond:ffebcd blue:0000ff "
    "blueviolet:8a2be2 brown:a52a2a burlywood:deb887 cadetblue:5f9ea0 chartreuse:7fff00 "
    "chocolate:d2691e coral:ff7f50 cornflowerblue:6495ed cornsilk:fff8dc crimson:dc143c "
    "cyan:00ffff darkblue:00008b darkcyan:008b8b darkgoldenrod:b8860b darkgray:a9a9a9 "
    "darkgreen:006400 darkgrey:a9a9a9 darkkhaki:bdb76b darkmagenta:8b008b "
    "darkolivegreen:556b2f darkorange:ff8c00 darkorchid:9932cc darkred:8b0000 "
    "darksalmon:e9967a darkseagreen:8fbc8f darkslateblue:483d8b darkslategray:2f4f4f "
    "darkslategrey:2f4f4f darkturquoise:00ced1 darkviolet:9400d3 deeppink:ff1493 "
    "deepskyblue:00bfff dimgray:696969 dimgrey:696969 dodgerblue:1e90ff firebrick:b22222 "
    "floralwhite:fffaf0 forestgreen:228b22 fuchsia:ff00ff gainsboro:dcdcdc "
    "ghostwhite:f8f8ff gold:ffd700 goldenrod:daa520 gray:808080 green:008000 "
    "greenyellow:adff2f grey:808080 honeydew:f0fff0 hotpink:ff69b4 indianred:cd5c5c "
    "indigo:4b0082 ivory:fffff0 khaki:f0e68c lavender:e6e6fa lavenderblush:fff0f5 "
    "lawngreen:7cfc00 lemonchiffon:fffacd lightblue:add8e6 lightcoral:f08080 "
    "lightcyan:e0ffff lightgoldenrodyellow:fafad2 lightgray:d3d3d3 lightgreen:90ee90 "
    "lightgrey:d3d3d3 lightpink:ffb6c1 lightsalmon:ffa07a lightseagreen:20b2aa "
    "lightskyblue:87cefa lightslategray:778899 lightslategrey:778899 "
    "lightsteelblue:b0c4de lightyellow:ffffe0 lime:00ff00 limegreen:32cd32 linen:faf0e6 "
    "magenta:ff00ff maroon:800000 mediumaquamarine:66cdaa mediumblue:0000cd "
    "mediumorchid:ba55d3 mediumpurple:9370db mediumseagreen:3cb371 "
    "mediumslateblue:7b68ee mediumspringgreen:00fa9a mediumturquoise:48d1cc "
    "mediumvioletred:c71585 midnightblue:191970 mintcream:f5fffa mistyrose:ffe4e1 "
    "moccasin:ffe4b5 navajowhite:ffdead navy:000080 oldlace:fdf5e6 olive:808000 "
    "olivedrab:6b8e23 orange:ffa500 orangered:ff4500 orchid:da70d6 palegoldenrod:eee8aa "
    "palegreen:98fb98 paleturquoise:afeeee palevioletred:db7093 papayawhip:ffefd5 "
    "peachpuff:ffdab9 peru:cd853f pink:ffc0cb plum:dda0dd powderblue:b0e0e6 purple:800080 "
    "rebeccapurple:663399 red:ff0000 rosybrown:bc8f8f royalblue:4169e1 "
    "saddlebrown:8b4513 salmon:fa8072 sandybrown:f4a460 seagreen:2e8b57 seashell:fff5ee "
    "sienna:a0522d silver:c0c0c0 skyblue:87ceeb slateblue:6a5acd slategray:708090 "
    "slategrey:708090 snow:fffafa springgreen:00ff7f steelblue:4682b4 tan:d2b48c "
    "teal:008080 thistle:d8bfd8 tomato:ff6347 turquoise:40e0d0 violet:ee82ee "
    "wheat:f5deb3 white:ffffff whitesmoke:f5f5f5 yellow:ffff00 yellowgreen:9acd32"
)
NAMED = dict(pair.split(":") for pair in _NAMES.split())

_HEX = re.compile(r"#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_FUNCTION = re.compile(r"rgba?\(([^)]*)\)", re.IGNORECASE)
_HSL = re.compile(r"hsla?\(([^)]*)\)", re.IGNORECASE)
_CHANNEL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?%?")
#: What paints nothing.
NOTHING = ("none", "transparent")


def parse(text: str) -> tuple[RGB, float] | None:
    """A colour as CSS and SVG write one, `#1f77b4`, `#abc`, `rgb(31, 119, 180)`,
    `rgba(0, 0, 0, 0.5)`, `rgb(12% 47% 71% / 50%)` or a name, and its opacity; None for
    anything else, `none`, a gradient's `url(#id)` or `currentColor` among them."""
    value = text.strip().lower()
    if value in NAMED:
        value = "#" + NAMED[value]
    found = _HEX.fullmatch(value)
    if found:
        digits = found.group(1)
        if len(digits) in (3, 4):
            digits = "".join(digit * 2 for digit in digits)
        channels = [int(digits[i : i + 2], 16) / 255 for i in range(0, len(digits), 2)]
        alpha = channels[3] if len(channels) == 4 else 1.0
        return (channels[0], channels[1], channels[2]), alpha
    found = _HSL.fullmatch(value)
    if found:
        return _hsl(found.group(1))
    found = _FUNCTION.fullmatch(value)
    if not found:
        return None
    parts = _CHANNEL.findall(found.group(1))
    if len(parts) not in (3, 4):
        return None
    rgb = tuple(_channel(part, 255) for part in parts[:3])
    alpha = _channel(parts[3], 1) if len(parts) == 4 else 1.0
    return (rgb[0], rgb[1], rgb[2]), alpha


def _hsl(inside: str) -> tuple[RGB, float] | None:
    """`hsl(h, s%, l%)` or `hsla(...)`, its hue in degrees, as CSS Color Level 4 turns one
    into RGB."""
    parts = _CHANNEL.findall(inside)
    if len(parts) not in (3, 4):
        return None
    hue = float(parts[0].rstrip("%")) % 360
    saturation, lightness = (_channel(part, 100) for part in parts[1:3])
    alpha = _channel(parts[3], 1) if len(parts) == 4 else 1.0

    def f(n: float) -> float:
        k = (n + hue / 30) % 12
        a = saturation * min(lightness, 1 - lightness)
        return lightness - a * max(-1.0, min(k - 3, 9 - k, 1.0))

    return (f(0), f(8), f(4)), alpha


def _channel(text: str, full: float) -> float:
    value = float(text[:-1]) / 100 if text.endswith("%") else float(text) / full
    return min(1.0, max(0.0, value))


def hex_of(rgb: RGB) -> str:
    return "#" + "".join(f"{round(min(1.0, max(0.0, c)) * 255):02x}" for c in rgb)


def over_white(rgb: RGB, alpha: float) -> RGB:
    """The colour painted at `alpha` over white, as it shows on a page."""
    alpha = min(1.0, max(0.0, alpha))
    # White's part added last, whole, so that a colour painted at full opacity is itself to
    # the bit: `c * 1 + 1 - 1` is not always `c`.
    white = 1 - alpha
    return (rgb[0] * alpha + white, rgb[1] * alpha + white, rgb[2] * alpha + white)


def to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def to_encoded(channel: float) -> float:
    channel = min(1.0, max(0.0, channel))
    if channel <= 0.0031308:
        return channel * 12.92
    return 1.055 * channel ** (1 / 2.4) - 0.055


def _times(matrix, vector) -> tuple[float, float, float]:
    return (
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
        matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
    )


def simulate(rgb: RGB, deficiency: str) -> RGB:
    """`rgb` as a reader with `deficiency` sees it, or grey for `GREYSCALE`."""
    linear = tuple(to_linear(c) for c in rgb)
    if deficiency == GREYSCALE:
        grey = to_encoded(_times(_TO_XYZ, linear)[1])
        return (grey, grey, grey)
    seen = _times(MACHADO_2009[deficiency], linear)
    return (to_encoded(seen[0]), to_encoded(seen[1]), to_encoded(seen[2]))


def lab(rgb: RGB) -> Lab:
    """CIELAB under D65."""
    xyz = _times(_TO_XYZ, tuple(to_linear(c) for c in rgb))

    def f(t: float) -> float:
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = (f(value / white) for value, white in zip(xyz, _WHITE, strict=True))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(first: Lab, second: Lab) -> float:
    """The CIEDE2000 difference of two CIELAB colours, with kL = kC = kH = 1, as Sharma, Wu
    and Dalal (2005) write it out and test it."""
    l1, a1, b1 = first
    l2, a2, b2 = second
    mean_c = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(mean_c**7 / (mean_c**7 + 25**7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    delta_l = l2 - l1
    delta_c = c2p - c1p
    if c1p * c2p == 0:
        delta_h = 0.0
    elif abs(h2p - h1p) <= 180:
        delta_h = h2p - h1p
    else:
        delta_h = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    delta_hh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_h / 2))
    mean_l = (l1 + l2) / 2
    mean_cp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        mean_h = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        mean_h = (h1p + h2p) / 2
    else:
        mean_h = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(mean_h - 30))
        + 0.24 * math.cos(math.radians(2 * mean_h))
        + 0.32 * math.cos(math.radians(3 * mean_h + 6))
        - 0.20 * math.cos(math.radians(4 * mean_h - 63))
    )
    delta_theta = 30 * math.exp(-(((mean_h - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(mean_cp**7 / (mean_cp**7 + 25**7))
    s_l = 1 + 0.015 * (mean_l - 50) ** 2 / math.sqrt(20 + (mean_l - 50) ** 2)
    s_c = 1 + 0.045 * mean_cp
    s_h = 1 + 0.015 * mean_cp * t
    r_t = -math.sin(math.radians(2 * delta_theta)) * r_c
    return math.sqrt(
        (delta_l / s_l) ** 2
        + (delta_c / s_c) ** 2
        + (delta_hh / s_h) ** 2
        + r_t * (delta_c / s_c) * (delta_hh / s_h)
    )


def difference(first: RGB, second: RGB) -> float:
    """How far apart two sRGB colours are, CIEDE2000."""
    return ciede2000(lab(first), lab(second))


def scales(colours: Iterable[RGB], threshold: float = THRESHOLD) -> set[str]:
    """The hex codes of `colours` that are the shades of a scale: chained within `threshold`
    of one another to normal vision, `SCALE` or more."""
    distinct = sorted({hex_of(colour) for colour in colours})
    labs = [lab(parse(code)[0]) for code in distinct]
    normal = {(i, j): ciede2000(labs[i], labs[j])
              for i in range(len(labs)) for j in range(i + 1, len(labs))}  # fmt: skip
    return {distinct[i] for i in _shades(len(labs), normal, threshold)}


def _shades(count: int, normal: dict[tuple[int, int], float], threshold: float) -> set[int]:
    """The indexes in groups of `SCALE` or more, a group being what is chained by pairs
    less than `threshold` apart."""
    parent = list(range(count))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (i, j), apart in normal.items():
        if apart < threshold:
            parent[root(i)] = root(j)
    sizes: dict[int, int] = {}
    for i in range(count):
        sizes[root(i)] = sizes.get(root(i), 0) + 1
    return {i for i in range(count) if sizes[root(i)] >= SCALE}


@dataclass(frozen=True)
class Paint:
    """A colour a figure paints a mark or a text in, as it shows laid over white."""

    colour: str  # its hex code
    text: bool  # whether a text is painted in it


@dataclass(frozen=True)
class Confusion:
    """Two colours distinct to normal vision that are not as `seen`."""

    first: str  # hex
    second: str  # hex
    seen: str  # a deficiency, or GREYSCALE
    normal: float  # their difference to normal vision
    after: float  # and as seen


def confusions(
    colours: Iterable[RGB],
    seen: Iterable[str] = (*DEFICIENCIES, GREYSCALE),
    threshold: float = THRESHOLD,
) -> list[Confusion]:
    """Each pair of `colours` at least `threshold` apart to normal vision and less than it
    as each of `seen` makes them, in the order of `seen` and then of the colours, each pair
    once, by its hex codes. The shades of a scale (`scales`) are compared with nothing."""
    distinct = sorted({hex_of(colour) for colour in colours})
    rgbs = [parse(code)[0] for code in distinct]
    labs = [lab(rgb) for rgb in rgbs]
    normal = {
        (i, j): ciede2000(labs[i], labs[j])
        for i in range(len(rgbs))
        for j in range(i + 1, len(rgbs))
    }
    shades = _shades(len(rgbs), normal, threshold)
    found = []
    for way in seen:
        after = [lab(simulate(rgb, way)) for rgb in rgbs]
        for (i, j), apart in normal.items():
            if apart < threshold or i in shades or j in shades:
                continue
            now = ciede2000(after[i], after[j])
            if now < threshold:
                found.append(Confusion(distinct[i], distinct[j], way, apart, now))
    return found
