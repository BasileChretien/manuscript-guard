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
import xml.etree.ElementTree as ET
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.figure_source import check_figure_source
from manuscript_guard.paths import FIGURE_SCRIPT_SUFFIXES
from manuscript_guard.render import same_render
from manuscript_guard.text.tokens import find_atoms

GATE = "G3"

SCRIPT_SUFFIXES = FIGURE_SCRIPT_SUFFIXES
TEXT_FORMATS = {".svg", ".pdf"}
OPAQUE_FORMATS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".eps"}

# Naming the toolkit is not the same as reading the results from it. This matched a bare
# `manuscript_guard` anywhere, so `from manuscript_guard.render import record` — which the
# example figure script now needs in order to prove its own outputs — counted as reading
# results, and a script that hardcoded every number passed. Matched on the reading API.
_USES_API = re.compile(
    r"\b(?:load_results|read_results|mg_read_results)\b|manuscript_?guard[.:]+results",
    re.IGNORECASE,
)
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
    # Figures whose text could not be read at all. A script behind one of these must not
    # have its results check softened on the grounds that "it draws no numbers": nobody
    # knows whether it draws numbers.
    unreadable: set[str] = set()
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
            # Skipped only when a manifest says this raster and its vector sibling came out
            # of the same run, and both still match the digests it recorded. The pairing
            # used to be assumed from the filename alone: render both honestly, then
            # re-render only the PNG from a script elsewhere, and the retouched PNG went
            # into the .docx while G3 read the correct SVG.
            siblings = [
                path.with_suffix(vector)
                for vector in TEXT_FORMATS
                if path.with_suffix(vector).exists()
            ]
            if siblings:
                if any(same_render(path, sibling) for sibling in siblings):
                    continue
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="figure-render-unproven",
                        severity=WARN,
                        message=f"{path.name} is not checked because {siblings[0].name} exists, "
                        f"but nothing shows the two were rendered together",
                        path=path,
                        hint="call manuscript_guard.render.record(__file__, *outputs) at the "
                        "end of the figure script, so the pairing is recorded rather than "
                        "assumed from the filename",
                    )
                )
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
            unreadable.add(path.stem)
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
        elif not text.strip():
            # No text at all, in a format that has a text layer. matplotlib's default
            # `svg.fonttype` is 'path', which draws every label as outlines — so an SVG full
            # of annotations reads as empty, `figures_checked` counted it, and a figure
            # nobody had read looked read. Both halves of G3 were defeated by that one
            # setting, since a script whose figure yields no atoms is also not "drawing
            # numbers" and its results check dropped from FAIL to WARN.
            unreadable.add(path.stem)
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-no-text-layer",
                    message=f"{path.name} is a {suffix} but contains no text at all, so "
                    f"nothing in it was checked",
                    path=path,
                    hint="matplotlib draws text as outlines unless you set "
                    "rcParams['svg.fonttype'] = 'none'; for a figure that genuinely has no "
                    "text, declare it in "
                    f"{path.stem}.guard.yaml under `no_text` with a reason",
                )
            )
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
        # "Draws no numbers" is only a reason to soften this when someone actually looked.
        # A figure whose text could not be read is not a figure without numbers, and the
        # softening used to apply to both — so on a machine without pdftotext, or with
        # matplotlib's default outlined SVG text, a script that ignores the results and
        # types numbers anyway dropped to a warning.
        unknown = script.stem in unreadable
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="figure-script-ignores-results",
                # A figure with no numbers in it — a flow diagram, a map — has no reason to
                # read the results, so that case is advice rather than a verdict. A figure
                # that does print numbers while its script never opens the results file is
                # drawing them from somewhere nothing downstream can check.
                severity=FAIL if (draws_numbers or unknown) else WARN,
                message=(
                    f"{script.name} prints numbers but never reads the results file"
                    if draws_numbers
                    else f"{script.name} never reads the results file, and its output could "
                    f"not be read to see whether that matters"
                    if unknown
                    else f"{script.name} never reads the results file"
                ),
                path=script,
                hint="take every annotated value from results/ so the figure cannot go stale",
            )
        )

    return report.with_counts(
        figure_scripts=len(scripts),
        figures_checked=inspected - len(unreadable & {p.stem for p in scripts}),
        figures_opaque=opaque,
        figures_unreadable=len(unreadable),
    )


def _sidecar_allowlist(figure: Path) -> frozenset[str]:
    """Axis ticks and scale labels, declared once per figure and reviewable.

    A figure legitimately contains numbers that are neither results nor prose conventions:
    the ticks on its axes. Rather than weakening the gate for every number in every figure,
    those are declared in a sidecar next to the figure, with a reason, so the exemption is
    small, explicit and visible in review.
    """
    sidecar = figure.with_name(f"{figure.stem}.guard.yaml")
    return frozenset(entry for entry, _why in _declared(sidecar, "allow"))


def _declared(sidecar: Path, section: str) -> list[tuple[str, str]]:
    """`(value, why)` pairs from a `.guard.yaml`, refusing any entry with no reason.

    Every hint in this gate and both module docstrings say a declaration carries a reason.
    `why` was optional in the code, so `- value: '1'` on its own exempted a number with no
    argument recorded anywhere — which is the shape of allowlist the whole design is
    written against. An entry without one is ignored rather than honoured: an exemption
    nobody justified is an exemption nobody can review.
    """
    import yaml

    if not sidecar.exists():
        return []
    try:
        document = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    out = []
    for item in document.get(section, []) or []:
        if not isinstance(item, dict) or "value" not in item:
            continue
        why = str(item.get("why", "")).strip()
        if why:
            out.append((str(item["value"]), why))
    return out


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

    Covers **every rendered format of the figure**, not just the one the reviewer looked at.
    G10 used to digest the vector alone, because that is the file it can read — but the
    .docx embeds the raster, so the picture that actually ships was under no review
    currency at all: replace the PNG and the review stayed green. Reviewing the SVG and
    shipping a different PNG is the whole of that gap.
    """
    import hashlib

    siblings = sorted(
        path
        for path in figure.parent.glob(f"{figure.stem}.*")
        if path.suffix.lower() in TEXT_FORMATS | OPAQUE_FORMATS
    )
    if len(siblings) > 1:
        combined = hashlib.sha256()
        for path in siblings:
            combined.update(path.name.encode("utf-8"))
            combined.update(_one_digest(path).encode("ascii"))
        return combined.hexdigest()
    return _one_digest(figure)


def _one_digest(figure: Path) -> str:
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

    # The same poppler-then-pypdf chain the literature reader uses. This had only the
    # poppler half, which was wrong twice on a machine with pypdf and no pdftotext: the
    # figure was reported `figure-unreadable` while the project's literature PDFs read
    # fine, and — less visibly — `figure-script-ignores-results` quietly fell from FAIL to
    # WARN, because deciding that a script "draws numbers" requires having read the
    # rendered figure first. A script that ignores the results and types numbers anyway
    # only warned there.
    from manuscript_guard.literature.sources import UnreadableSource, _read_pdf

    try:
        return _read_pdf(path)
    except UnreadableSource:
        return None
