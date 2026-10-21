"""Palettes by name, for a figure script that stays the author's.

The colours are other people's: MetBrewer, MoMAColors, NatParksPalettes, PNWColors and
wesanderson, palettes drawn from paintings, photographs and films; Okabe and Ito's eight;
ColorBrewer's schemes; viridis and its family; cividis; and Fabio Crameri's scientific
colour maps. `tools/derive_palettes.py` reads each from its collection's own file into
`data/palettes.json`, with what the toolkit's own colour check (`colour.py`, the rule G3
holds a figure to) says of it, beside what its collection claims.

```python
from manuscript_guard import palettes

palettes.colours("met/Archambault", 4)   # four hex codes, in the collection's own order
palettes.use("okabe-ito")                 # matplotlib's colour cycle for the next axes
cmap = palettes.cmap("crameri/batlow")    # a matplotlib colormap
```

R has the same, `mg_palette()`, `scale_colour_mg()` and `scale_fill_mg()` in the
manuscriptguard package, from the same file. Nothing here draws a figure.

**What the check says of a palette** (`assess`), for each number of colours a figure may
take from it, in the order its collection gives them for that many:

* `distinct`: the most colours that are all at least `colour.THRESHOLD` apart to normal
  vision (`normal`), and to a reader with each of protanopia, deuteranopia and tritanopia
  as well (`cvd`), and in grey (`greyscale`);
* `lightness`: whether lightness, CIELAB L*, rises or falls all along it (`monotone`), turns
  once (`diverging`), or neither; and whether each deficiency keeps that (`lightness_kept`),
  which is what an ordered or a diverging scale asks of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from manuscript_guard.colour import (
    DEFICIENCIES,
    GREYSCALE,
    THRESHOLD,
    difference,
    hex_of,
    lab,
    parse,
    simulate,
)

DATA = Path(__file__).parent / "data" / "palettes.json"
#: A palette with this many colours or more is a continuous map, sampled where a figure
#: asks for fewer, and not a set of colours to take from in order: unless its collection
#: calls it qualitative, as Crameri's categorical maps are, a hundred colours taken first
#: to last.
CONTINUOUS = 64
#: The most colours of a set the check counts as told apart: no figure tells more categories
#: by colour alone.
MOST = 20
#: How many colours along a continuous map its lightness is judged at. Its 256 colours,
#: rounded to 8 bits a channel, step back and forth by a fraction of a unit where the map
#: does not.
SAMPLES = 11
#: A step of lightness smaller than this, in CIELAB L*, is no step: the rounding of a colour
#: to 8 bits a channel moves its lightness by up to about a quarter of a unit.
FLAT = 0.5
KINDS = ("qualitative", "sequential", "diverging", "multi-sequential", "cyclic")


class PaletteError(ValueError):
    """A palette that is not there, or a number of colours it cannot give."""


@dataclass(frozen=True)
class Palette:
    name: str
    collection: str
    #: As the collection states it, or None where it states none (the artists' palettes,
    #: which are offered for either use).
    kind: str | None
    colours: tuple[str, ...]
    #: For each colour, the rank at which a discrete palette of that many takes it.
    order: tuple[int, ...] | None
    #: Each number of colours the collection gives a palette of its own for (ColorBrewer).
    by_n: dict[str, tuple[str, ...]]
    claims_cvd: bool | None
    distinct: dict[str, int | None]
    lightness: str
    lightness_kept: bool

    @property
    def continuous(self) -> bool:
        return is_continuous(self.kind, len(self.colours))


def is_continuous(kind: str | None, count: int) -> bool:
    return count >= CONTINUOUS and kind != "qualitative"


@cache
def _document() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def collections() -> dict[str, dict]:
    """Each collection: where it lives, its licence, who holds it, what it claims."""
    return _document()["collections"]


def names() -> list[str]:
    return list(_document()["palettes"])


def palette(name: str) -> Palette:
    """The palette called `name`, `met/Archambault`, or by its last part alone,
    `Archambault`, where only one collection has a palette of that name."""
    held = _document()["palettes"]
    found = name if name in held else _by_short_name(name, held)
    entry = held[found]
    return Palette(
        name=found,
        collection=entry["collection"],
        kind=entry["kind"],
        colours=tuple(entry["colours"]),
        order=tuple(entry["order"]) if entry.get("order") else None,
        by_n={n: tuple(codes) for n, codes in (entry.get("by_n") or {}).items()},
        claims_cvd=entry["claims_cvd"],
        distinct=entry["distinct"],
        lightness=entry["lightness"],
        lightness_kept=entry["lightness_kept"],
    )


def _by_short_name(name: str, held: dict) -> str:
    wanted = name.lower()
    found = [key for key in held if key.split("/")[-1].lower() == wanted]
    if len(found) == 1:
        return found[0]
    if found:
        raise PaletteError(f"{len(found)} palettes are called {name!r}: {', '.join(found)}")
    raise PaletteError(f"no palette is called {name!r}; `manuscript-guard palettes` lists them")


def colours(name: str, n: int | None = None, *, reverse: bool = False) -> list[str]:
    """`n` colours of the palette, as hex codes: as many as it has where `n` is None.

    Of a set of colours, the `n` its collection gives for that many: ColorBrewer's own
    scheme of `n`, or the colours whose rank in the collection's order is at most `n`, in
    the palette's sequence, as MetBrewer, MoMAColors, NatParksPalettes and PNWColors give
    them, or the first `n`. Fewer than ColorBrewer's smallest scheme are evenly spaced along
    it. More than it has is refused: ask `ramp` for that. Of a continuous map, `n` evenly
    spaced along it."""
    found = palette(name)
    if n is None:
        chosen = list(found.colours)
    elif n < 1:
        raise PaletteError(f"a palette of {n} colours")
    elif found.continuous:
        chosen = ramp(name, n)
    else:
        chosen = _discrete(found, n)
    return chosen[::-1] if reverse else chosen


def _discrete(found: Palette, n: int) -> list[str]:
    if n > len(found.colours):
        raise PaletteError(
            f"{found.name} has {len(found.colours)} colours, and {n} were asked for; "
            "`ramp` interpolates more, which are no longer as far apart"
        )
    own = found.by_n.get(str(n))
    if own is not None:
        return list(own)
    if found.by_n:
        return _fewer(found.by_n[min(found.by_n, key=int)], n)
    if found.order:
        return [code for code, rank in zip(found.colours, found.order, strict=True) if rank <= n]
    return list(found.colours[:n])


def ramp(name: str, n: int) -> list[str]:
    """`n` colours evenly spaced along the palette, each between two of its colours taken
    in a straight line through sRGB, as R's `colorRampPalette` takes them."""
    stops = [parse(code)[0] for code in palette(name).colours]
    if n == 1:
        return [hex_of(stops[0])]
    out = []
    for index in range(n):
        at = index / (n - 1) * (len(stops) - 1)
        low = min(int(at), len(stops) - 2)
        part = at - low
        out.append(hex_of(tuple(
            stops[low][c] + (stops[low + 1][c] - stops[low][c]) * part for c in range(3)
        )))  # fmt: skip
    return out


def cycle(name: str, n: int | None = None):
    """A matplotlib colour cycle of the palette's `n` colours, for `axes.prop_cycle`."""
    from cycler import cycler

    return cycler(color=colours(name, n))


def use(name: str, n: int | None = None) -> None:
    """Make the palette matplotlib's colour cycle for the axes drawn after this."""
    import matplotlib

    matplotlib.rcParams["axes.prop_cycle"] = cycle(name, n)


def cmap(name: str, n: int | None = None, *, reverse: bool = False):
    """A matplotlib colormap of the palette: each of its colours where `n` is None, else `n`
    of them, as `colours` gives them; a continuous map is smooth, a set of colours is
    listed."""
    from matplotlib.colors import LinearSegmentedColormap, ListedColormap

    found = palette(name)
    chosen = colours(name, n, reverse=reverse)
    title = f"{found.name}{'_r' if reverse else ''}"
    if found.continuous and n is None:
        return LinearSegmentedColormap.from_list(title, chosen, N=len(chosen))
    return ListedColormap(chosen, name=title)


# -------------------------------------------------------------- what the check says of one


def assess(entry: dict) -> dict:
    """What the toolkit's colour check says of a palette, from its colours and order (see
    the module's docstring). `entry` is as the data file holds one."""
    codes = entry["colours"]
    continuous = is_continuous(entry["kind"], len(codes))
    # A continuous map's lightness is judged at evenly spaced points along it.
    rgbs = [parse(code)[0] for code in (_samples(codes) if continuous else codes)]
    if continuous:
        distinct = {"normal": None, "cvd": None, "greyscale": None}
    else:
        subsets = [_subset(entry, n) for n in range(1, min(len(codes), MOST) + 1)]
        distinct = {
            "normal": _most(subsets, ()),
            "cvd": _most(subsets, DEFICIENCIES),
            "greyscale": _most(subsets, (GREYSCALE,)),
        }
    pattern = _lightness([lab(rgb)[0] for rgb in rgbs])
    kept = all(
        _lightness([lab(simulate(rgb, way))[0] for rgb in rgbs]) == pattern
        for way in DEFICIENCIES
    )
    return {"distinct": distinct, "lightness": pattern, "lightness_kept": kept}


def _samples(codes: list[str]) -> list[str]:
    return [codes[round(i * (len(codes) - 1) / (SAMPLES - 1))] for i in range(SAMPLES)]


def _fewer(scheme, n: int) -> list[str]:
    """Fewer colours than ColorBrewer's smallest scheme: evenly spaced along it, its two ends
    for two, so a diverging scheme gives both arms and not one arm and its middle."""
    if n == 1:
        return [scheme[0]]
    return [scheme[round(i * (len(scheme) - 1) / (n - 1))] for i in range(n)]


def _subset(entry: dict, n: int) -> list[str]:
    by_n = entry.get("by_n") or {}
    if str(n) in by_n:
        return by_n[str(n)]
    if by_n:
        return _fewer(by_n[min(by_n, key=int)], n)
    if entry.get("order"):
        return [c for c, rank in zip(entry["colours"], entry["order"], strict=True) if rank <= n]
    return entry["colours"][:n]


def _apart(codes: list[str], seen: tuple[str, ...]) -> bool:
    """Whether every two of `codes` are at least the threshold apart to normal vision and as
    each of `seen` makes them."""
    rgbs = [parse(code)[0] for code in codes]
    ways = [lambda rgb: rgb, *[lambda rgb, way=way: simulate(rgb, way) for way in seen]]
    return all(
        difference(way(rgbs[i]), way(rgbs[j])) >= THRESHOLD
        for way in ways
        for i in range(len(rgbs))
        for j in range(i + 1, len(rgbs))
    )


def _most(subsets: list[list[str]], seen: tuple[str, ...]) -> int:
    """The largest n whose colours are all at least the threshold apart to normal vision and
    as each of `seen` makes them; 1 where no two are. A smaller n may not be: ColorBrewer's
    scheme of seven is no part of its scheme of ten."""
    best = 1
    for codes in subsets:
        if len(codes) >= 2 and _apart(codes, seen):
            best = max(best, len(codes))
    return best


def _lightness(values: list[float]) -> str:
    # A step of less than `FLAT` turns nothing.
    signs = [b > a for a, b in zip(values, values[1:], strict=False) if abs(b - a) >= FLAT]
    if not signs:
        return "neither"
    turns = sum(1 for a, b in zip(signs, signs[1:], strict=False) if a != b)
    return "monotone" if turns == 0 else "diverging" if turns == 1 else "neither"


# ---------------------------------------------------------------- sized to the journal

#: The size of a figure's text where the journal's least is smaller: a size many artwork
#: guides give for text at print size. The journal's own guide wins: pass `size`.
TEXT_PT = 7.0
#: The thinnest axis or tick line drawn, where the journal's least is thinner.
LINE_PT = 0.5


def figure_style(
    root: str | Path = ".", width: str | float = "single", ratio: float = 0.62,
    size: float | None = None,
) -> dict:
    """matplotlib settings for a figure that prints at the target journal's width with its
    text and lines no smaller than the journal takes (its profile's `figures:`): the figure's
    size in inches, `width` being "single" (the narrowest width the journal prints at),
    "double" (the widest) or millimetres; every text at `size` points, or `TEXT_PT` where the
    journal's least is smaller; lines no thinner than its least; and fonts kept as text in an
    SVG and embedded whole in a PDF, as G3 and G4 read them. For
    `matplotlib.rcParams.update`."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.journal import figure_rules

    project, _ = load_project(Path(root))
    rules = figure_rules(project)
    least_text = _number(rules.get("min_text_pt")) or 0.0
    least_line = _number(rules.get("min_line_pt")) or 0.0
    text = size if size is not None else max(TEXT_PT, least_text)
    line = max(LINE_PT, least_line)
    inches = _width_mm(rules, width) / 25.4
    return {
        "figure.figsize": (inches, inches * ratio),
        "font.size": text, "axes.titlesize": text, "axes.labelsize": text,
        "xtick.labelsize": text, "ytick.labelsize": text, "legend.fontsize": text,
        "legend.title_fontsize": text, "figure.titlesize": text,
        "axes.linewidth": line, "xtick.major.width": line, "ytick.major.width": line,
        "xtick.minor.width": line, "ytick.minor.width": line, "grid.linewidth": line,
        "lines.linewidth": max(1.0, 2 * line), "patch.linewidth": line,
        "svg.fonttype": "none", "pdf.fonttype": 42, "ps.fonttype": 42,
    }  # fmt: skip


def _number(value: object) -> float | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    return float(value) if ok else None


def _width_mm(rules: dict, width: str | float) -> float:
    if isinstance(width, (int, float)) and not isinstance(width, bool):
        return float(width)
    widths = [w for w in rules.get("widths_mm") or () if _number(w)]
    if not widths:
        raise PaletteError("the journal's profile gives no widths_mm: pass the width in mm")
    if width == "double":
        return float(max(widths))
    if width == "single":
        return float(min(widths))
    raise PaletteError(f"a width is 'single', 'double' or millimetres, not {width!r}")


# ------------------------------------------------------------- choosing one, and saying so

#: How many colours of a set `--safe` asks every reader to tell apart, where the figure's
#: number is not given.
SAFE_AT = 3


def chosen(
    kind: str | None = None, colours: int | None = None, safe: bool = False,
    collection: str | None = None,
) -> list[Palette]:
    """The palettes of `kind`, with at least `colours` colours, from `collection`, and, with
    `safe`, only those every reader can read for that use (`readable`). A palette whose
    collection states no kind is offered for a set of colours, and also for an ordered or a
    diverging scale where its lightness runs one way or turns once."""
    out = []
    for name in names():
        found = palette(name)
        if collection and found.collection.lower() != collection.lower():
            continue
        if kind and not _of_kind(found, kind):
            continue
        if colours and not found.continuous and len(found.colours) < colours:
            continue
        if safe and not readable(found, kind, colours):
            continue
        out.append(found)
    return out


def _of_kind(found: Palette, kind: str) -> bool:
    if found.kind is not None:
        return found.kind == kind
    return kind == "qualitative" or found.lightness == {
        "sequential": "monotone", "diverging": "diverging"}.get(kind)  # fmt: skip


def readable(found: Palette, kind: str | None = None, colours: int | None = None) -> bool:
    """Whether every reader can read the palette for this use: as a set of colours, that the
    `colours` of them it gives for that many (`SAFE_AT` where not given) stay apart for each
    deficiency; as an ordered or a diverging scale, or a continuous map, that its lightness
    runs one way or turns once, and still does for each deficiency, and, where a number of
    classes is given and the palette is no continuous map, that the colours it gives for
    that many stay apart for each deficiency as well (round 1 of #406: Blues was offered for
    five classes, of which no two stay apart with tritanopia). Those very colours are
    tested, and not how many stay apart at most (round 2: ten of PuOr's do, and its seven
    do not)."""
    as_scale = found.continuous or kind in ("sequential", "diverging") or (
        kind is None and found.kind in ("sequential", "diverging"))  # fmt: skip
    if as_scale:
        wanted = {"sequential": ("monotone",), "diverging": ("diverging",)}.get(
            kind or found.kind or "", ("monotone", "diverging"))  # fmt: skip
        ordered = found.lightness in wanted and found.lightness_kept
        if not ordered or found.continuous or not colours:
            return ordered
    n = colours or SAFE_AT
    return n <= len(found.colours) and _apart(_discrete(found, n), DEFICIENCIES)


def row(found: Palette) -> dict:
    about = collections()[found.collection]
    return {
        "name": found.name, "collection": found.collection, "kind": found.kind,
        "colours": len(found.colours), "distinct": found.distinct,
        "lightness": found.lightness, "lightness_kept": found.lightness_kept,
        "claims_cvd": found.claims_cvd, "licence": about["licence"],
    }  # fmt: skip


def table(rows: list[Palette], colours: int | None = None) -> list[str]:
    """The palettes as a table to read: each one's kind, its number of colours, how many
    stay apart to normal vision, for every deficiency and in grey, its lightness, and what
    its collection claims."""
    lines = [f"{'name':<26} {'kind':<17} {'n':>3}  {'apart: all/cvd/grey':<20} "
             f"{'lightness':<22} collection claims"]  # fmt: skip
    for found in rows:
        apart = "continuous" if found.continuous else "/".join(
            str(found.distinct[key]) for key in ("normal", "cvd", "greyscale"))  # fmt: skip
        light = found.lightness + ("" if found.lightness_kept else ", not kept")
        claims = {True: "cvd-friendly", False: "not cvd-friendly", None: "-"}[found.claims_cvd]
        lines.append(f"{found.name:<26} {found.kind or '-':<17} {len(found.colours):>3}  "
                     f"{apart:<20} {light:<22} {claims}")  # fmt: skip
    lines += ["", "apart: how many colours, in the collection's order, stay at least 10 apart "
              "(CIEDE2000) to normal vision, for a reader with protanopia, deuteranopia or "
              "tritanopia, and in grey. Licences: `manuscript-guard palettes --show <name>`."]
    return lines


def _lightness_said(found: Palette) -> str:
    # Whether a deficiency keeps a lightness that orders nothing is no use to a reader.
    if found.lightness not in ("monotone", "diverging"):
        return "its lightness neither runs one way nor turns once"
    runs = "runs one way" if found.lightness == "monotone" else "turns once"
    kept = "and" if found.lightness_kept else "but not"
    return f"its lightness {runs}, {kept} for each deficiency"


def describe(found: Palette, codes: list[str]) -> list[str]:
    """One palette: its colours, what the check says of it, what its collection claims, its
    licence, and how to use it from Python and from R."""
    about = collections()[found.collection]
    shown = ", ".join(codes) if len(codes) <= 16 else ", ".join(codes[:8]) + f", ... ({len(codes)})"
    if found.continuous:
        verdict = f"a continuous map; {_lightness_said(found)}"
    else:
        verdict = (f"{found.distinct['normal']} of its colours stay apart to normal vision, "
                   f"{found.distinct['cvd']} for every colour-vision deficiency, "
                   f"{found.distinct['greyscale']} in grey; {_lightness_said(found)}")
    claims = {True: "calls it colour-blind friendly", False: "does not call it colour-blind "
              "friendly", None: "says nothing of colour-vision deficiency"}[found.claims_cvd]
    return [
        f"{found.name}  ({found.collection}: {about['about']})",
        f"  kind: {found.kind or 'not stated by the collection'}",
        f"  colours: {shown}",
        f"  the check: {verdict}",
        f"  the collection {claims}",
        f"  licence: {about['licence']}, {about['holder']}; {about['home']}",
        f"  Python: palettes.colours({found.name!r}, n)  palettes.use({found.name!r})  "
        f"palettes.cmap({found.name!r})",
        f"  R: mg_palette(\"{found.name}\", n)  scale_colour_mg(\"{found.name}\")",
    ]
