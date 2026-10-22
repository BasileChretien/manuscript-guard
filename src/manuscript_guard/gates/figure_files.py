"""G4 — the figure files meet the journal's artwork rules.

A journal's artwork guide states the formats it takes, the resolution each kind of figure
needs at the width it prints at, the largest file, and how long a legend may be. These were
free text in a profile's notes, and the first anyone heard of them was the portal refusing
the upload. A profile now carries them under `figures:`, read from the journal's own guide,
and G4 holds each figure the manuscript places (`{{figure.<name>}}`) to them:

* `figure-format`: no file of the figure is in a format the journal takes.
* `figure-resolution`: a raster's pixels, over the width it prints at, fall below the
  resolution its kind needs (halftone, combination or line art), or above a supplement's
  maximum.
* `figure-height`: a raster printed at its width is taller than the page allows.
* `figure-file-size`: a file is larger than the journal takes.
* `figure-shrinks`: a raster drawn much larger than it prints, by its own resolution
  metadata: its text shrinks with it, and text drawn at a plotting library's usual 10 pt
  prints below the journal's smallest.
* `legend-words`: the paragraph that labels a figure ("Figure 1.") holds more words than a
  legend may.

The width a figure prints at is the one its `<name>.guard.yaml` gives (`print_width_mm`), or,
where none is given, the narrowest the journal prints at, so that a resolution found too low
is too low at every width. Its kind is the sidecar's (`kind`), or halftone. A figure placed
in `manuscript/supplementary/` is held to the profile's `supplementary:` rules where it has
them. Everything is a warning, and a note where the profile says the rules apply only once
the paper is accepted.

* `figure-text-small`, `figure-line-thin`: an SVG figure's smallest text or thinnest line,
  carried through its transforms to the width it prints, is below the journal's least.
* `figure-text-clipped`: a text in an SVG figure is anchored outside what it shows.
* `figure-font-type3`, `figure-font-not-embedded`: a PDF figure uses a Type 3 font, or one
  whose file is not in it; its text and lines are held as an SVG's are.

The size of a raster is read from its own header, PNG, JPEG or TIFF, with the standard
library; an SVG's text and lines are read from its elements (`gates/figure_svg.py`), a
PDF's from its content streams (`gates/figure_pdf.py`).
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.figure_pdf import read_pdf
from manuscript_guard.gates.figure_svg import clipped, points_per_unit, read_svg
from manuscript_guard.gates.numbers import is_supplementary, source_files
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import count_words

GATE = "G4"
MM_PER_INCH = 25.4
#: The size a plotting library draws text at unless told otherwise: matplotlib's 10 pt.
DRAWN_TEXT_PT = 10.0
#: The kinds of figure a journal sets a resolution for.
KINDS = ("halftone", "combination", "line_art")
#: The suffixes a figure file can have, and the format each is.
FORMATS = {
    ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".tif": "tiff", ".tiff": "tiff",
    ".eps": "eps", ".pdf": "pdf", ".svg": "svg",
}  # fmt: skip
_RASTERS = {"png", "jpeg", "tiff"}
#: How a journal may write a format, against the name it is known by here.
_SPELLED = {"tif": "tiff", "jpg": "jpeg"}
#: A legend: the paragraph after a figure that opens with its label, bold or not.
_LEGEND = re.compile(r"^\s*(?:\*\*|__)?\s*(?:Figure|Fig\.)\s*S?\d+", re.IGNORECASE)


@dataclass(frozen=True)
class Raster:
    width: int
    height: int
    #: Pixels per inch, as the file records it; None where it records none.
    dpi: float | None


def raster_of(path: Path) -> Raster | None:
    """The pixels and resolution a PNG, JPEG or TIFF records; None for anything else, or a
    file whose header cannot be read."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            found = _png(data)
        elif data.startswith(b"\xff\xd8"):
            found = _jpeg(data)
        elif data[:4] in (b"II*\x00", b"MM\x00*"):
            found = _tiff(data)
        else:
            return None
    except (struct.error, IndexError, ValueError, ZeroDivisionError):
        return None
    # A header that records no pixels is a damaged file, not a figure of no size (round 1
    # of #291: its height divided by its width stopped `check`).
    if found is None or found.width <= 0 or found.height <= 0:
        return None
    return found


def _png(data: bytes) -> Raster:
    width, height = struct.unpack(">II", data[16:24])
    dpi = None
    at = 8
    while at + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[at : at + 8])
        if kind == b"pHYs":
            x, _y, unit = struct.unpack(">IIB", data[at + 8 : at + 17])
            dpi = x * 0.0254 if unit == 1 else None
            break
        if kind == b"IDAT":
            break
        at += 12 + length
    return Raster(width, height, dpi)


def _jpeg(data: bytes) -> Raster | None:
    at, dpi, size = 2, None, None
    while at + 4 <= len(data) and data[at] == 0xFF:
        marker = data[at + 1]
        length = struct.unpack(">H", data[at + 2 : at + 4])[0]
        body = data[at + 4 : at + 2 + length]
        if marker == 0xE0 and body.startswith(b"JFIF\x00"):
            units, x = body[7], struct.unpack(">H", body[8:10])[0]
            dpi = float(x) if units == 1 else x * 2.54 if units == 2 else None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", body[1:5])
            size = (width, height)
            break
        at += 2 + length
    return Raster(size[0], size[1], dpi) if size else None


def _tiff(data: bytes) -> Raster | None:
    order = "<" if data[:2] == b"II" else ">"
    (offset,) = struct.unpack(order + "I", data[4:8])
    (count,) = struct.unpack(order + "H", data[offset : offset + 2])
    tags: dict[int, float] = {}
    for index in range(count):
        entry = data[offset + 2 + 12 * index : offset + 14 + 12 * index]
        tag, kind, _n = struct.unpack(order + "HHI", entry[:8])
        if kind == 3:
            tags[tag] = struct.unpack(order + "H", entry[8:10])[0]
        elif kind == 4:
            tags[tag] = struct.unpack(order + "I", entry[8:12])[0]
        elif kind == 5:
            (at,) = struct.unpack(order + "I", entry[8:12])
            numerator, denominator = struct.unpack(order + "II", data[at : at + 8])
            tags[tag] = numerator / denominator
    if 256 not in tags or 257 not in tags:
        return None
    dpi = tags.get(282)
    if dpi is not None and tags.get(296, 2) == 3:
        dpi *= 2.54
    elif dpi is not None and tags.get(296, 2) != 2:
        dpi = None
    return Raster(int(tags[256]), int(tags[257]), dpi)


def check_figure_files(project: Project, profile: dict, profile_path: Path) -> Report:
    """Each figure the manuscript places, against the profile's `figures:` rules."""
    rules = profile.get("figures")
    if not isinstance(rules, dict):
        return Report()
    severity = INFO if rules.get("applies_from") == "acceptance" else WARN
    findings: list[Finding] = []
    manuscript = project.path("manuscript")
    latex = _latex(manuscript)
    placed = _placed(project)
    for name, supplementary in placed:
        own = rules.get("supplementary") if supplementary else None
        held = {**rules, **own} if isinstance(own, dict) else rules
        files = _files_of(project.path("figures"), name)
        if not files:
            continue
        side = _sidecar(project.path("figures") / f"{name}.guard.yaml")
        findings += _format(name, files, held, profile_path)
        for path in files:
            findings += _file(path, held, side, supplementary, profile_path)
    if latex:
        findings += _latex_legends(manuscript, rules)
    else:
        findings += _legends(project, manuscript, rules, profile_path)
    return Report(tuple(_with(finding, severity) for finding in findings))


def _latex(manuscript: Path) -> bool:
    from manuscript_guard.text.reader import LATEX, manuscript_format

    return manuscript_format(manuscript) == LATEX


def _with(finding: Finding, severity: str) -> Finding:
    from dataclasses import replace

    return replace(finding, severity=severity)


def _placed(project: Project) -> list[tuple[str, bool]]:
    """Each figure a manuscript file places, once, and whether a supplementary file does: a
    LaTeX file's `\\mg{figure.key}` as a Markdown file's `{{figure.key}}`."""
    from manuscript_guard.text.reader import bound_files

    manuscript = project.path("manuscript")
    seen: dict[str, bool] = {}
    for bound in bound_files(project):
        for placeholder in bound.placeholders:
            if placeholder.namespace == "figure":
                supplementary = is_supplementary(manuscript, bound.path)
                seen[placeholder.key] = seen.get(placeholder.key, True) and supplementary
    return sorted(seen.items())


def _files_of(folder: Path, name: str) -> list[Path]:
    """The figure's files, one per format it was saved in."""
    return [folder / f"{name}{suffix}" for suffix in FORMATS
            if (folder / f"{name}{suffix}").is_file()]  # fmt: skip


def _sidecar(path: Path) -> dict:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


def _finding(code: str, message: str, path: Path, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=WARN, message=message, path=path, hint=hint)


def _format(name: str, files: list[Path], rules: dict, profile_path: Path) -> list[Finding]:
    written = [str(f).lower().lstrip(".") for f in rules.get("formats") or ()]
    if not written:
        return []
    accepted = {_SPELLED.get(f, f) for f in written}
    formats = {FORMATS[path.suffix.lower()] for path in files}
    if formats & accepted:
        return []
    return [
        _finding(
            "figure-format",
            f"figure {name!r} is in {', '.join(sorted(formats))}, and the journal takes "
            f"{', '.join(written)}",
            files[0],
            f"save it from its script in one of these as well; the journal's rules are in "
            f"{profile_path.name}",
        )
    ]


def _file(path: Path, rules: dict, side: dict, supplementary: bool, profile_path: Path
          ) -> list[Finding]:  # fmt: skip
    findings = []
    largest = rules.get("max_file_mb")
    size = path.stat().st_size
    if isinstance(largest, (int, float)) and size > largest * 1024 * 1024:
        findings.append(
            _finding(
                "figure-file-size",
                f"{path.name} is {size / 1024 / 1024:.1f} MB, and the journal takes files up to "
                f"{largest:g} MB",
                path,
                "save it compressed (TIFF with LZW, PNG), or at the resolution the journal "
                "asks and no more",
            )
        )
    if FORMATS[path.suffix.lower()] == "svg":
        return findings + _vector(path, rules, side)
    if FORMATS[path.suffix.lower()] == "pdf":
        return findings + _pdf(path, rules, side)
    if FORMATS[path.suffix.lower()] not in _RASTERS:
        return findings
    raster = raster_of(path)
    if raster is None:
        return findings
    width_mm, said = _width(rules, side)
    if width_mm is None:
        return findings
    kind = side.get("kind") if side.get("kind") in KINDS else "halftone"
    dpi = raster.width / (width_mm / MM_PER_INCH)
    where = f"at {width_mm:g} mm wide{'' if said else ', the narrowest the journal prints at'}"
    needed = (rules.get("min_dpi") or {}).get(kind)
    if isinstance(needed, (int, float)) and dpi < needed:
        findings.append(
            _finding(
                "figure-resolution",
                # Rounded toward the side it fails, so that it is never printed at its limit.
                f"{path.name} prints {where} at {math.floor(dpi * 10) / 10:.1f} dpi, and a "
                f"{kind.replace('_', ' ')} figure needs {needed:g}",
                path,
                f"render it with more pixels ({needed:g} dpi at the width it prints), or give "
                f"its print width and kind in {path.stem}.guard.yaml (print_width_mm, kind)",
            )
        )
    most = rules.get("max_dpi")
    if isinstance(most, (int, float)) and dpi > most:
        findings.append(
            _finding(
                "figure-resolution",
                f"{path.name} prints {where} at {math.ceil(dpi * 10) / 10:.1f} dpi, and the "
                f"journal takes no more than {most:g}"
                f"{' for a supplementary figure' if supplementary else ''}",
                path,
                f"render it at {most:g} dpi at the width it prints",
            )
        )
    tallest = rules.get("max_height_mm")
    height_mm = width_mm * raster.height / raster.width
    if isinstance(tallest, (int, float)) and height_mm > tallest:
        findings.append(
            _finding(
                "figure-height",
                f"{path.name} printed {where} is {height_mm:.0f} mm high, and the page takes "
                f"{tallest:g} mm",
                path,
                "draw it less tall, or in two panels the journal can set apart",
            )
        )
    smallest = rules.get("min_text_pt")
    if raster.dpi and isinstance(smallest, (int, float)):
        drawn_mm = raster.width / raster.dpi * MM_PER_INCH
        shrink = drawn_mm / width_mm
        if DRAWN_TEXT_PT / shrink < smallest:
            findings.append(
                _finding(
                    "figure-shrinks",
                    f"{path.name} was drawn {drawn_mm:.0f} mm wide and prints {where}: text "
                    f"drawn at {DRAWN_TEXT_PT:g} pt prints at {DRAWN_TEXT_PT / shrink:.1f} pt, "
                    f"and the journal's smallest is {smallest:g} pt",
                    path,
                    "draw it at the size it prints (in matplotlib, figsize in inches at the "
                    "print width) and raise the dpi instead",
                )
            )
    return findings


def _vector(path: Path, rules: dict, side: dict) -> list[Finding]:
    """An SVG figure's smallest text and thinnest line at the size it prints, and any text
    anchored outside what it shows (`gates/figure_svg.py`)."""
    svg = read_svg(path)
    if svg is None:
        return []
    findings = [
        _finding(
            "figure-text-clipped",
            f"{path.name}: the text '{mark.text[:40]}' is anchored at ({mark.at[0]:.0f}, "
            f"{mark.at[1]:.0f}), outside what the figure shows (its viewBox, "
            f"{' '.join(f'{v:g}' for v in svg.view or ())}), and is cut off where it prints",
            path,
            "move the text inside the figure, or draw the figure with room for it (in "
            "matplotlib, savefig with bbox_inches='tight')",
        )
        for mark in clipped(svg)[:3]
    ]
    width_mm, said = _width(rules, side)
    per_unit = points_per_unit(svg, width_mm)
    if per_unit is None:
        return findings
    if width_mm is not None:
        where = f"at {width_mm:g} mm wide{'' if said else ', the narrowest the journal prints at'}"
    else:
        where = f"at its own width, {svg.width_pt:.0f} pt" + (
            "" if svg.width_unit else " (its width has no unit, and is read as pixels)"
        )
    texts = [(mark.text, mark.units) for mark in svg.texts]
    return findings + _too_small(path, texts, [m.units for m in svg.lines], per_unit, where, rules)


def _pdf(path: Path, rules: dict, side: dict) -> list[Finding]:
    """A PDF figure's fonts, and its smallest text and thinnest line at the size it prints
    (`gates/figure_pdf.py`)."""
    figure = read_pdf(path)
    if figure is None:
        return []
    findings = []
    for font in figure.fonts:
        # A subset's name carries six letters and a plus sign before the font's own.
        name = re.sub(r"^[A-Z]{6}\+", "", font.name)
        if font.subtype == "Type3":
            findings.append(
                _finding(
                    "figure-font-type3",
                    f"{path.name}: its font {name} is a Type 3 font, which some journals' "
                    "production refuses, and whose text does not search or edit as text",
                    path,
                    "in matplotlib, set rcParams['pdf.fonttype'] = 42 before saving, which "
                    "embeds the font whole",
                )
            )
        elif not font.embedded:
            findings.append(
                _finding(
                    "figure-font-not-embedded",
                    f"{path.name}: its font {name} is not in the PDF, so a printer sets its "
                    "text in a font of its own",
                    path,
                    "save it with its fonts embedded (in R, cairo_pdf() or embedFonts(); in "
                    "matplotlib, pdf.fonttype 42)",
                )
            )
    if figure.width_pt is None or figure.width_pt <= 0:
        return findings
    width_mm, said = _width(rules, side)
    if width_mm is None:
        per_point, where = 1.0, f"at its own width, {figure.width_pt:.0f} pt"
    else:
        per_point = width_mm / MM_PER_INCH * 72 / figure.width_pt
        where = f"at {width_mm:g} mm wide{'' if said else ', the narrowest the journal prints at'}"
    return findings + _too_small(path, figure.texts, figure.lines, per_point, where, rules)


def _too_small(
    path: Path,
    texts: list[tuple[str, float]],
    lines: list[float],
    per_unit: float,
    where: str,
    rules: dict,
) -> list[Finding]:
    """A vector figure's smallest text and thinnest line, each in its own units, against the
    journal's least once printed: each times the points one unit prints at."""
    findings = []
    for marks, limit, what, hint in (
        (texts, rules.get("min_text_pt"), "text",
         "draw its text larger, or the figure at the width it prints (in matplotlib, figsize "
         "in inches at the print width) with text at the journal's size"),
        ([("", width) for width in lines], rules.get("min_line_pt"), "line",
         "draw its lines wider, or the figure at the width it prints"),
    ):  # fmt: skip
        if not marks or not isinstance(limit, (int, float)) or isinstance(limit, bool):
            continue
        below = [(text, units) for text, units in marks if units * per_unit < limit]
        if not below:
            continue
        text, units = min(below, key=lambda mark: mark[1])
        printed = math.floor(units * per_unit * 100) / 100
        named = f" '{text[:40]}'" if text else ""
        many = f"; {len(below)} {what}s are below it" if len(below) > 1 else ""
        findings.append(
            _finding(
                "figure-text-small" if what == "text" else "figure-line-thin",
                f"{path.name}: its {'smallest' if what == 'text' else 'thinnest'} {what}{named} "
                f"prints at {printed:.2f} pt {where}, and the journal's least is {limit:g} pt"
                f"{many}",
                path,
                hint + f", or give its print width in {path.stem}.guard.yaml (print_width_mm)",
            )
        )
    return findings


def _width(rules: dict, side: dict) -> tuple[float | None, bool]:
    """The width a figure prints at, in millimetres, and whether its sidecar says so."""
    said = side.get("print_width_mm")
    if isinstance(said, (int, float)) and not isinstance(said, bool) and said > 0:
        return float(said), True
    widths = [w for w in rules.get("widths_mm") or () if isinstance(w, (int, float)) and w > 0]
    return (float(min(widths)), False) if widths else (None, False)


def _legends(project: Project, manuscript: Path, rules: dict, profile_path: Path
             ) -> list[Finding]:  # fmt: skip
    limit = rules.get("legend_words")
    if not isinstance(limit, int):
        return []
    findings = []
    for path in source_files(manuscript):
        text = read_text(path)
        placeholders, _ = parse(text)
        for placeholder in placeholders:
            if placeholder.namespace != "figure":
                continue
            legend = _legend_after(text, placeholder.end)
            if legend is None:
                continue
            words = count_words(legend)
            if words > limit:
                findings.append(
                    Finding(
                        gate=GATE,
                        code="legend-words",
                        severity=WARN,
                        message=f"the legend of figure {placeholder.key!r} is {words} words, "
                        f"and the journal takes {limit}",
                        path=path,
                        line=placeholder.line,
                        hint="move what the legend explains into the text, or into the "
                        "Methods",
                    )
                )
    return findings


#: The words of the label LaTeX prints before a figure's caption: "Figure 1".
_LABEL_WORDS = 2


def _latex_legends(manuscript: Path, rules: dict) -> list[Finding]:
    """`_legends` of a LaTeX manuscript: a figure's legend is the caption LaTeX numbers it by,
    in a float that holds a figure, its words counted as the main text's are, in the view a
    caption is printed in (`figure_captions`, step 13)."""
    limit = rules.get("legend_words")
    if not isinstance(limit, int):
        return []
    from manuscript_guard.text.latex.printed import figure_captions

    findings = []
    for supplementary in (False, True):
        for path, line, legend in figure_captions(manuscript, supplementary=supplementary):
            # And the label LaTeX prints before a caption, "Figure 1", which a Markdown legend
            # types and counts (round 2 of step 13, part 2).
            words = count_words(legend) + _LABEL_WORDS
            if words > limit:
                findings.append(
                    Finding(
                        gate=GATE,
                        code="legend-words",
                        severity=WARN,
                        message=f"the legend of the figure captioned at {path}:{line} is "
                        f"{words} words, and the journal takes {limit}",
                        path=manuscript / path,
                        line=line,
                        hint="move what the legend explains into the text, or into the "
                        "Methods",
                    )
                )
    return findings


def _legend_after(text: str, end: int) -> str | None:
    """The paragraph after a figure, where it opens with the figure's label."""
    rest = text[end:].lstrip("\n")
    paragraph = re.split(r"\n[ \t]*\n", rest, maxsplit=1)[0]
    return paragraph if _LEGEND.match(paragraph) else None
