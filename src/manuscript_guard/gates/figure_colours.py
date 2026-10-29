"""G3 — a figure's colours stay apart for a reader with a colour-vision deficiency.

Two series told apart by colour alone can be one series to a reader with protanopia,
deuteranopia or tritanopia, and to anyone reading a page printed in grey. So each colour a
figure the manuscript places paints its marks in is read from the figure itself, its SVG or
its PDF (`gates/figure_svg.py`, `gates/figure_pdf.py`), and taken through what each
deficiency makes of it and through grey (`colour.py`: Machado et al. 2009, CIEDE2000):

* `figure-colours-confused`: two colours at least `colour.THRESHOLD` apart to normal vision
  are less than it apart to a reader with one of the deficiencies. A warning, never a
  failure; a note where the figure's `<name>.guard.yaml` gives a reason under
  `allow_colours` for each such pair (two series that differ by line style as well).
* `figure-greyscale-confused`: the same, in grey. A note, and a warning where the journal's
  profile says its figures print in grey (`figures.print: greyscale`) or the guard asks for
  it (`greyscale: true`).
* `figure-colours-unread`: the figure has no SVG or PDF, so its colours were not read. A
  note: a raster's colours are blended at every edge, and are not guessed at.

* `figure-colours-scale`: the figure draws a continuous scale, three or more colours chained
  within the threshold of one another, greys apart, and running through 10 of lightness or
  more (`colour.scales`), and its colours are not compared,
  a note. Which colours are the scale's and which a series' is not known from the colours,
  and every rule for telling them apart was wrong one way or the other (the review of
  #398); its review looks at it. `figure-colours-many`, the same past `MANY` colours.

A text's colour is left out: text rarely tells one series from another, and black text
beside a dark mark is no confusion of data. So is a pair already close to normal vision,
which no deficiency made so.
"""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

from manuscript_guard.colour import (
    DEFICIENCIES,
    GREYSCALE,
    SPAN,
    THRESHOLD,
    Confusion,
    confusions,
    hex_of,
    parse,
    scales,
)
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report

GATE = "G3"
#: How many pairs a finding names before it counts the rest.
NAMED = 3
#: More distinct colours than this, and a figure's colours are not compared: finding a scale
#: among them, and comparing them, take time in their square.
MANY = 300
#: A colour as `allow_colours` may write one: a hex code, `rgb()`, `hsl()` or a name.
_WRITTEN = re.compile(r"#[0-9A-Fa-f]{3,8}\b|(?:rgb|hsl)a?\([^)]*\)|[A-Za-z]+", re.IGNORECASE)


def painted(path: Path) -> list[str] | None:
    """The colours a vector figure paints its marks in, text left out, as hex codes; None
    where it is no SVG or PDF that can be read."""
    from manuscript_guard.gates.figure_pdf import read_pdf
    from manuscript_guard.gates.figure_svg import read_svg

    suffix = path.suffix.lower()
    figure = read_svg(path) if suffix == ".svg" else read_pdf(path) if suffix == ".pdf" else None
    if figure is None:
        return None
    return list(dict.fromkeys(paint.colour for paint in figure.paints if not paint.text))


def check_figure_colours(project: Project) -> Report:
    """Each figure the manuscript places, for the colours it paints."""
    from manuscript_guard.gates.figure_files import _files_of, _placed, _sidecar
    from manuscript_guard.gates.figures import _declared
    from manuscript_guard.gates.journal import figure_rules

    placed = _placed(project)
    if not placed:
        return Report()
    rules = figure_rules(project)
    findings: list[Finding] = []
    checked = 0
    for name, supplementary in placed:
        files = _files_of(project.path("figures"), name)
        # The SVG where there is one, as G3 reads the figure's text from it, else the PDF;
        # the PDF where the SVG cannot be read (round 1 of #398).
        vectors = [p for suffix in (".svg", ".pdf") for p in files if p.suffix.lower() == suffix]
        vector, colours = next(((p, c) for p in vectors if (c := painted(p)) is not None),
                               (vectors[0] if vectors else None, None))  # fmt: skip
        sidecar = project.path("figures") / f"{name}.guard.yaml"
        if colours is None:
            if files:
                findings.append(_unread(name, files[0], vector))
            continue
        checked += 1
        guard = _sidecar(sidecar)
        own = rules.get("supplementary") if supplementary else None
        held = {**rules, **own} if isinstance(own, dict) else rules
        grey = held.get("print") == "greyscale" or guard.get("greyscale") is True
        allowed = _allowed(_declared(sidecar, "allow_colours"))
        findings += _judged(name, vector, colours, grey, allowed, sidecar)
    return Report(tuple(findings)).with_counts(figures_colour_checked=checked)


def colour_findings(path: Path, name: str, *, greyscale: bool = False) -> list[Finding] | None:
    """What G3 says of the colours one vector file paints, outside the manuscript: the
    graphical abstract `communicate check` reads, which has no sidecar to allow a pair.
    None where the file is no SVG or PDF that can be read."""
    colours = painted(path)
    if colours is None:
        return None
    return _judged(name, path, colours, greyscale, {}, None)


def _judged(
    name: str,
    vector: Path,
    colours: list[str],
    grey: bool,
    allowed: dict[frozenset[str], str],
    sidecar: Path | None,
) -> list[Finding]:
    """The findings of one figure's colours: a scale or too many are not compared, and each
    way of seeing that confuses two of the rest is one finding."""
    if len(colours) > MANY:
        return [_many(name, vector, len(colours))]
    shades = scales([parse(code)[0] for code in colours])
    if shades:
        return [_scale(name, vector, len(shades))]
    findings = []
    found = confusions([parse(code)[0] for code in colours])
    for way in (*DEFICIENCIES, GREYSCALE):
        pairs = [c for c in found if c.seen == way]
        if not pairs:
            continue
        open_ = [c for c in pairs if _reason(c, allowed) is None]
        severity = WARN if open_ and (way != GREYSCALE or grey) else INFO
        findings.append(_confused(vector, way, open_ or pairs, allowed, severity, sidecar))
    return findings


def _allowed(declared: list[tuple[str, str]]) -> dict[frozenset[str], str]:
    """Each declared exemption, a colour or the pairs of the colours it names, with its
    reason. A colour may be written as a hex code, `rgb()`, `hsl()` or a name; a word that
    is none is passed over."""
    out = {}
    for value, why in declared:
        codes = sorted({hex_of(found[0]) for word in _WRITTEN.findall(value)
                        if (found := parse(word)) is not None})  # fmt: skip
        if len(codes) == 1:
            out[frozenset(codes)] = why
        for pair in combinations(codes, 2):
            out[frozenset(pair)] = why
    return out


def _reason(pair: Confusion, allowed: dict[frozenset[str], str]) -> str | None:
    """The reason the guard gives for this pair, or for either colour of it."""
    for key in (frozenset((pair.first, pair.second)), frozenset((pair.first,)),
                frozenset((pair.second,))):  # fmt: skip
        if key in allowed:
            return allowed[key]
    return None


def _confused(
    path: Path,
    way: str,
    pairs: list[Confusion],
    allowed: dict[frozenset[str], str],
    severity: str,
    sidecar: Path | None,
) -> Finding:
    worst = sorted(pairs, key=lambda c: c.after)
    named = "; ".join(
        f"{c.first} and {c.second}, {c.normal:.0f} apart to normal vision, {c.after:.1f}"
        for c in worst[:NAMED]
    )
    more = f"; and {len(pairs) - NAMED} more pairs" if len(pairs) > NAMED else ""
    who = "printed in grey" if way == GREYSCALE else f"to a reader with {way}"
    reasons = sorted({r for c in pairs if (r := _reason(c, allowed)) is not None})
    if severity == INFO and reasons:
        hint = "the figure's guard file gives the reason: " + "; ".join(reasons)
    else:
        hint = (
            "tell the series apart by something besides colour as well (a marker, a line "
            "style, a label on the line), or take colours that stay apart, Okabe and Ito's "
            "for one"
        )
        if sidecar is not None:
            hint += f"; or give the reason in {sidecar.name} under allow_colours, the pair and why"
    return Finding(
        gate=GATE,
        code="figure-greyscale-confused" if way == GREYSCALE else "figure-colours-confused",
        severity=severity,
        message=f"{path.name}: colours that are one colour {who} (CIEDE2000; "
        f"{THRESHOLD:g} is the least taken to tell two apart): {named}{more}",
        path=path,
        hint=hint,
    )


_SCALE_HINT = (
    "look at it under `readable-and-accessible` in its review: whether its series stay apart "
    "for a reader with a colour-vision deficiency, and whether the scale's lightness runs one "
    "way, as viridis, cividis and Crameri's maps are drawn to; or draw the scale and the "
    "series as figures of their own, and the series' colours are compared"
)


def _many(name: str, path: Path, count: int) -> Finding:
    return Finding(
        gate=GATE,
        code="figure-colours-many",
        severity=INFO,
        message=f"figure {name!r} paints {count} colours: they were not compared for readers "
        "with a colour-vision deficiency",
        path=path,
        hint="look at it under `readable-and-accessible` in its review: so many colours are a "
        "scale or more categories than colour alone can tell apart; draw a panel of series "
        "as a figure of its own, and its colours are compared",
    )


def _scale(name: str, path: Path, count: int) -> Finding:
    return Finding(
        gate=GATE,
        code="figure-colours-scale",
        severity=INFO,
        message=f"figure {name!r} draws a continuous scale ({count} shades, each within "
        f"{THRESHOLD:g} of another and running through {SPAN:g} of lightness): its colours "
        "were not compared for readers with a colour-vision deficiency, since which are the "
        "scale's and which a series' is not known from the colours",
        path=path,
        hint=_SCALE_HINT,
    )


def _unread(name: str, path: Path, vector: Path | None) -> Finding:
    why = (
        f"{vector.name} could not be read"
        if vector is not None
        else "it has no SVG or PDF, and a raster's colours are blended at every edge"
    )
    return Finding(
        gate=GATE,
        code="figure-colours-unread",
        severity=INFO,
        message=f"the colours of figure {name!r} were not checked for readers with a "
        f"colour-vision deficiency: {why}",
        path=path,
        hint="save it as SVG or PDF beside the raster, from the same script, and the colours "
        "it paints are read from that",
    )
