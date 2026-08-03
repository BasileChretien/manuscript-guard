"""G3 — numbers drawn inside a figure are traceable too.

A figure is the easiest place for a stale number to survive. It is rendered once, looked at
rather than read, and no prose check ever touches it.

Two checks, because neither alone is enough:

1. **The script reads the results.** A figure script that never opens the results file is
   drawing from somewhere else, and nothing downstream can tell where.
2. **The rendered text is accounted for.** Every numeric atom in the figure's own text
   layer must match a results display string, or classify as a convention, label or term
   exactly as prose does.

Check 2 needs a text layer, so it works on SVG and on PDF when `pdftotext` is available.
Raster output cannot be inspected at all, and that is reported rather than passed over:
a figure this gate cannot read is a figure nobody has checked.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.figure_source import check_figure_source
from manuscript_guard.text.tokens import find_atoms

GATE = "G3"

SCRIPT_SUFFIXES = {".r", ".rmd", ".qmd", ".py", ".jl"}
TEXT_FORMATS = {".svg", ".pdf"}
OPAQUE_FORMATS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".eps"}

_USES_API = re.compile(r"manuscript_?guard|load_results|read_results", re.IGNORECASE)
_NAMES_RESULTS = re.compile(r"""['"`]results['"`]|\bresults[/\\]""")
_READS_JSON = re.compile(r"\.json\b|from_?JSON|read_json|jsonlite", re.IGNORECASE)


def _reads_results(text: str) -> bool:
    """Whether a figure script appears to obtain its values from the results file.

    A heuristic, and treated as one. Path joining means the results file rarely appears as
    a single literal, so this looks for the directory name and a JSON read separately.
    """
    if _USES_API.search(text):
        return True
    return bool(_NAMES_RESULTS.search(text) and _READS_JSON.search(text))


def check_figures(project: Project, results: Results) -> Report:
    figures_dir = project.path("figures")
    if not figures_dir.exists():
        return Report(counts={"figure_scripts": 0, "figures_checked": 0})

    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    allowed = {v.display for v in results.values.values()}
    allowed |= {v.display.replace(",", "") for v in results.values.values()}

    report = Report()
    scripts: list[Path] = []
    numeric_output: set[str] = set()
    inspected = 0
    opaque = 0

    for path in sorted(figures_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()

        if suffix in SCRIPT_SUFFIXES:
            scripts.append(path)
            continue

        if suffix in OPAQUE_FORMATS:
            # Silent when a vector export of the same figure exists: that sibling carries
            # the text layer, so the numbers are checked and warning again would be noise.
            if any(path.with_suffix(vector).exists() for vector in TEXT_FORMATS):
                continue
            opaque += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-not-inspectable",
                    severity=WARN,
                    message=f"{path.name} has no text layer, so its numbers cannot be checked",
                    path=path,
                    hint="export SVG or PDF alongside it if the figure carries numeric annotations",
                )
            )
            continue

        if suffix not in TEXT_FORMATS:
            continue

        text = _extract_text(path)
        if text is None:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-unreadable",
                    severity=WARN,
                    message=f"could not read a text layer from {path.name}",
                    path=path,
                    hint="install poppler's pdftotext to inspect PDF figures",
                )
            )
            continue

        inspected += 1
        declared = _sidecar_allowlist(path)
        atoms = find_atoms(text, text)
        if atoms:
            numeric_output.add(path.stem)
        for atom in atoms:
            if atom.text in allowed or atom.text.replace(",", "") in allowed:
                continue
            if atom.text in declared:
                continue
            if classifier.classify(atom).kind != UNCLASSIFIED:
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-number-unbound",
                    message=f"{atom.text!r} appears in {path.name} but matches no results value",
                    path=path,
                    context=atom.line_text.strip()[:160],
                    hint=(
                        "draw the annotation from results rather than typing it and re-render; "
                        f"if it is an axis tick or scale label, declare it in "
                        f"{path.stem}.guard.yaml with a reason"
                    ),
                )
            )

    for script in scripts:
        # The source check is the one that catches a script which reads the results and
        # still types one annotation by hand. It runs whatever the script does next.
        report = report.merge(check_figure_source(script, classifier))

        if _reads_results(script.read_text(encoding="utf-8", errors="replace")):
            continue
        draws_numbers = script.stem in numeric_output
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="figure-script-ignores-results",
                # A figure with no numbers in it — a flow diagram, a map — has no reason to
                # read the results, so that case is advice rather than a verdict. A figure
                # that does print numbers while its script never opens the results file is
                # drawing them from somewhere nothing downstream can check.
                severity=FAIL if draws_numbers else WARN,
                message=(
                    f"{script.name} prints numbers but never reads the results file"
                    if draws_numbers
                    else f"{script.name} never reads the results file"
                ),
                path=script,
                hint="take every annotated value from results/ so the figure cannot go stale",
            )
        )

    return report.with_counts(
        figure_scripts=len(scripts), figures_checked=inspected, figures_opaque=opaque
    )


def _sidecar_allowlist(figure: Path) -> frozenset[str]:
    """Axis ticks and scale labels, declared once per figure and reviewable.

    A figure legitimately contains numbers that are neither results nor prose conventions:
    the ticks on its axes. Rather than weakening the gate for every number in every figure,
    those are declared in a sidecar next to the figure, with a reason, so the exemption is
    small, explicit and visible in review.
    """
    import yaml

    sidecar = figure.with_name(f"{figure.stem}.guard.yaml")
    if not sidecar.exists():
        return frozenset()
    document = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
    return frozenset(str(item["value"]) for item in document.get("allow", []) if "value" in item)


SVG_NS = "{http://www.w3.org/2000/svg}"
# Plotting libraries stamp a render timestamp and their own version into the SVG. Neither
# is figure content, and the timestamp changes on every render — which would also make a
# figure's review permanently out of date. Both are excluded here and by content_digest().
_METADATA_TAGS = {f"{SVG_NS}metadata", f"{SVG_NS}desc", f"{SVG_NS}title", "metadata"}


_ID_REFERENCE = re.compile(r"#([A-Za-z_][\w:.-]*)")


def _canonicalise_ids(root: ET.Element) -> None:
    """Rename generated element ids to id0, id1, … in document order.

    Matplotlib names its reusable path definitions with a random suffix — `id="mfd722ab4a3"`
    — regenerated on every render. Two renders of an identical figure therefore differ in
    every id and in every reference to one. Without this, no digest of the file is stable,
    and a review would go stale the moment the build ran, which trains an author to stop
    reading the gate. Renaming in document order keeps the digest sensitive to structure
    and content while blind to naming.
    """
    mapping: dict[str, str] = {}
    for element in root.iter():
        identifier = element.get("id")
        if identifier is not None and identifier not in mapping:
            mapping[identifier] = f"id{len(mapping)}"
    if not mapping:
        return
    for element in root.iter():
        identifier = element.get("id")
        if identifier in mapping:
            element.set("id", mapping[identifier])
        for key, value in list(element.attrib.items()):
            if "#" in value:
                element.set(
                    key,
                    _ID_REFERENCE.sub(lambda m: "#" + mapping.get(m.group(1), m.group(1)), value),
                )


def content_digest(figure: Path) -> str:
    """Digest of what the figure shows, ignoring how it was rendered.

    Used by the review gate to tell "this figure changed" from "this figure was rendered
    again". Two things have to be normalised away first: the render timestamp that
    plotting libraries stamp into the metadata, and their randomly generated element ids.
    """
    import hashlib

    if figure.suffix.lower() == ".svg":
        try:
            root = ET.fromstring(figure.read_text(encoding="utf-8", errors="replace"))
        except ET.ParseError:
            return hashlib.sha256(figure.read_bytes()).hexdigest()
        for parent in root.iter():
            for child in list(parent):
                if child.tag in _METADATA_TAGS:
                    parent.remove(child)
        _canonicalise_ids(root)
        return hashlib.sha256(ET.tostring(root, encoding="utf-8")).hexdigest()
    return hashlib.sha256(figure.read_bytes()).hexdigest()


def _svg_content_nodes(root: ET.Element):
    for node in root:
        if node.tag in _METADATA_TAGS:
            continue
        yield node
        yield from _svg_content_nodes(node)


def _extract_text(path: Path) -> str | None:
    if path.suffix.lower() == ".svg":
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
        except ET.ParseError:
            return None
        return "\n".join(
            node.text for node in _svg_content_nodes(root) if node.text and node.text.strip()
        )

    if shutil.which("pdftotext") is None:
        return None
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None
