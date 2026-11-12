"""G10 — somebody has actually looked at the figure, recently, and said what they saw.

There is a class of error in figures that no parser reaches. A truncated y-axis that makes
a small difference look decisive. A legend naming a series the plot no longer contains. Two
panels drawn on different scales and presented side by side. A caption describing the
figure the author meant to make. Every number can trace back to the results and the picture
can still mislead.

So the reading is delegated to a model or a person, and this gate enforces the part that
*can* be checked mechanically: that a review exists, that it covered the required ground,
and that it applies to the figure as it stands rather than to some earlier version.

Every figure is asked for one: each file in `figures/`, one review for its exports in several
formats, and each figure file the manuscript places elsewhere, by `\\includegraphics` or as
an image (`placed_figures.py`), its review in the `<name>.review.yaml` beside it.

The honest limit, stated plainly because a gate whose limits are undocumented gets trusted
past them: **this verifies that a review happened, not that it was any good.** It is the
same bargain as `literature/attested.yaml`, where the toolkit records that a human vouched
for a value it could not fetch itself.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report

GATE = "G10"
REVIEW_SUFFIX = ".review.yaml"

REVIEWABLE = {".svg", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".eps", ".webp"}

# One review per figure, not per file. A figure exported as both SVG and PNG is one
# picture, and asking for it to be read twice would make the gate feel like paperwork.
# The digest is taken from the first available representation in this order, preferring
# the one whose content is most stable across renders.
PREFERENCE = [".svg", ".pdf", ".eps", ".png", ".tif", ".tiff", ".jpg", ".jpeg", ".webp"]

REQUIRED_CHECKS = {
    "values-match-results": "every number shown matches the results file",
    "axes-labelled-and-scaled": "axes carry units, and any log or truncated scale is declared",
    "caption-agrees": "the caption describes the figure that is actually drawn",
    "legend-and-marks-explained": "every mark, colour, line style and series is accounted "
    "for, and the legend states n, what the error bars are, any smoothing and what each "
    "significance marker means",
    "no-unexplained-number": "nothing appears that is neither a result nor part of the scale",
    "scale-not-misleading": "the visual encoding does not overstate the finding",
    "readable-and-accessible": "legible at print size, and not dependent on colour alone",
}


def review_path(figure: Path) -> Path:
    return figure.with_name(f"{figure.stem}{REVIEW_SUFFIX}")


def choose(paths: list[Path]) -> list[Path]:
    """One file per figure, chosen by PREFERENCE, so exports of one picture share a review."""
    by_figure: dict[tuple[Path, str], list[Path]] = {}
    for path in sorted(paths):
        by_figure.setdefault((path.parent, path.stem), []).append(path)
    order = {suffix: rank for rank, suffix in enumerate(PREFERENCE)}
    return sorted(min(found, key=lambda p: order.get(p.suffix.lower(), len(PREFERENCE)))
                  for found in by_figure.values())  # fmt: skip


def _representatives(figures_dir: Path) -> list[Path]:
    """One file per figure in `figures_dir`, chosen by PREFERENCE."""
    return choose([path for path in figures_dir.rglob("*")
                   if path.is_file() and path.suffix.lower() in REVIEWABLE])  # fmt: skip


def under(path: Path, folder: Path) -> bool:
    """Whether `path` is in `folder` or a folder of it, both resolved."""
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def reviewable(project: Project) -> list[tuple[Path, str]]:
    """Each figure G10 asks a review of, one file of it, with the name a finding gives it:
    every figure in `figures/`, by its file's name, and every figure file the manuscript
    places outside it (`placed_figures.py`), by its path from the project's root."""
    from manuscript_guard.gates.placed_figures import placed_files

    figures_dir = project.path("figures")
    found = [(path, path.name) for path in _representatives(figures_dir)] if (
        figures_dir.is_dir()) else []  # fmt: skip
    found += [(placed.path, placed.name) for placed in placed_files(project)
              if not under(placed.path, figures_dir)]  # fmt: skip
    return found


def check_figure_reviews(project: Project, content_digest) -> Report:
    """`content_digest` is injected so the gate and the renderer cannot drift apart."""
    figures = reviewable(project)
    if not figures and not project.path("figures").exists():
        return Report(counts={"figures_reviewed": 0})

    report = Report()
    reviewed = 0
    outstanding = 0

    for figure, name in figures:
        path = review_path(figure)
        if not path.exists():
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-unreviewed",
                    message=f"nobody has read {name}",
                    path=figure,
                    hint=f"review the rendered figure and record it in {path.name}; "
                    f"the figure-review skill does this",
                )
            )
            continue

        document = read_structured(path)
        schema_report = validate(document, "figure_review", path, gate=GATE)
        report = report.merge(schema_report)
        if not schema_report.ok or not isinstance(document, dict):
            outstanding += 1
            continue

        expected = content_digest(figure)
        if document["content_sha256"] != expected:
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-review-stale",
                    message=f"{name} has changed since it was reviewed",
                    path=path,
                    context=f"reviewed {document['reviewed_on']} by {document['reviewed_by']}",
                    hint="read the current figure and record a fresh review",
                )
            )
            continue

        performed = {check["id"]: check for check in document["checks"]}
        missing = sorted(set(REQUIRED_CHECKS) - set(performed))
        if missing:
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-review-incomplete",
                    message=f"{name}: {len(missing)} required check(s) not performed",
                    path=path,
                    context=", ".join(missing),
                    hint="; ".join(f"{m}: {REQUIRED_CHECKS[m]}" for m in missing[:3]),
                )
            )
            continue

        for check_id, check in sorted(performed.items()):
            if check.get("ok") or check_id not in REQUIRED_CHECKS:
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-review-check-failed",
                    message=f"{name}: {check_id} did not pass",
                    path=path,
                    context=check.get("note", ""),
                )
            )

        for finding in document.get("findings", []):
            severity = {"fail": FAIL, "warn": WARN, "info": INFO}[finding["severity"]]
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-review-finding",
                    severity=severity,
                    message=f"{name}: {finding['message']}",
                    path=path,
                    context=finding.get("where"),
                )
            )

        if document["verdict"] == "concerns":
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-review-concerns",
                    message=f"the review of {name} raised concerns",
                    path=path,
                    hint="fix the figure and re-review, or record why the concern is acceptable",
                )
            )
        else:
            reviewed += 1

    return report.with_counts(figures_reviewed=reviewed, figures_outstanding=outstanding)
