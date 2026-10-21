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

A text's colour is left out: text rarely tells one series from another, and black text
beside a dark mark is no confusion of data. So is a pair already close to normal vision,
which no deficiency made so, and the shades of a continuous scale, colours chained within
the threshold of one another (`colour.scales`), which are compared neither with one
another nor with a grey. A figure of more than `MANY` colours is read to `BITS` bits a
channel; more than `MANY` even then, it is said (`figure-colours-many`, a note) and its
colours are not compared.
"""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

from manuscript_guard.colour import (
    DEFICIENCIES,
    GREYSCALE,
    THRESHOLD,
    Confusion,
    confusions,
    hex_of,
    parse,
)
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report

GATE = "G3"
#: How many pairs a finding names before it counts the rest.
NAMED = 3
#: More distinct colours than this, and a figure's colours are read to `BITS` bits a channel,
#: as the shades of a heat map drawn as vectors fall together; more than this even then, and
#: they are not compared, which takes time in their square (rounds 1 and 2 of #398).
MANY = 300
BITS = 5
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


def coarser(colours: list[str]) -> list[str]:
    """Each colour to `BITS` bits a channel, once each: a shift of at most half a step, about
    1.5 in CIEDE2000, well under the threshold."""
    top = 2**BITS - 1
    return list(dict.fromkeys(
        hex_of(tuple(round(channel * top) / top for channel in parse(code)[0]))
        for code in colours
    ))  # fmt: skip


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
        if len(colours) > MANY:
            colours = coarser(colours)
        if len(colours) > MANY:
            findings.append(_many(name, vector, len(colours)))
            continue
        guard = _sidecar(sidecar)
        own = rules.get("supplementary") if supplementary else None
        held = {**rules, **own} if isinstance(own, dict) else rules
        grey = held.get("print") == "greyscale" or guard.get("greyscale") is True
        allowed = _allowed(_declared(sidecar, "allow_colours"))
        found = confusions([parse(code)[0] for code in colours])
        for way in (*DEFICIENCIES, GREYSCALE):
            pairs = [c for c in found if c.seen == way]
            if not pairs:
                continue
            open_ = [c for c in pairs if _reason(c, allowed) is None]
            severity = WARN if open_ and (way != GREYSCALE or grey) else INFO
            findings.append(_confused(vector, way, open_ or pairs, allowed, severity, sidecar))
    return Report(tuple(findings)).with_counts(figures_colour_checked=checked)


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
    sidecar: Path,
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
            f"for one; or give the reason in {sidecar.name} under allow_colours, the pair "
            "and why"
        )
    return Finding(
        gate=GATE,
        code="figure-greyscale-confused" if way == GREYSCALE else "figure-colours-confused",
        severity=severity,
        message=f"{path.name}: colours that are one colour {who} (CIEDE2000; "
        f"{THRESHOLD:g} is the least taken to tell two apart): {named}{more}",
        path=path,
        hint=hint,
    )


def _many(name: str, path: Path, count: int) -> Finding:
    return Finding(
        gate=GATE,
        code="figure-colours-many",
        severity=INFO,
        message=f"figure {name!r} paints {count} colours even read to {BITS} bits a channel: "
        "its colours were not compared",
        path=path,
        hint="whether a scale reads for a reader with a colour-vision deficiency is whether its "
        "lightness runs one way: look at it under `readable-and-accessible`, or draw it with "
        "a map made to, viridis or one of Crameri's",
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
