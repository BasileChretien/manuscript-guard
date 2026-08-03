"""G4 — the manuscript fits the journal it is going to.

Desk rejection for a formatting breach is the cheapest possible way to lose two weeks, and
every one of its causes is mechanical: too many words, a missing declaration, a structured
abstract with the wrong headings, more figures than allowed.

The profile is data, retrieved from the journal's own instructions and stamped with the
date. Nothing here knows anything about any particular journal, which is deliberate: author
guidelines change without announcement, and a rule compiled into the tool would be wrong
eventually and silently. A profile older than a year is reported, because it probably is.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.paths import SHIPPED_JOURNALS
from manuscript_guard.text.sections import measure, split_sections

GATE = "G4"
PROFILE_DIR = SHIPPED_JOURNALS
STALE_AFTER = timedelta(days=365)


def profile_path(project: Project, slug: str) -> Path | None:
    """Project profiles win over shipped ones, so a user can correct or add a journal."""
    local = project.root / "profiles" / "journals" / f"{slug}.yaml"
    if local.exists():
        return local
    shipped = PROFILE_DIR / f"{slug}.yaml"
    return shipped if shipped.exists() else None


def available_profiles(project: Project) -> list[str]:
    found = set()
    for directory in (project.root / "profiles" / "journals", PROFILE_DIR):
        if directory.exists():
            found.update(p.stem for p in directory.glob("*.yaml"))
    return sorted(found)


def check_journal(project: Project) -> Report:
    slug = project.target_journal
    if not slug:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="no-journal-chosen",
                    severity=INFO,
                    message="no target journal, so journal rules are not checked",
                    hint="set target_journal in paper.yaml once you have chosen one",
                ),
            )
        )

    path = profile_path(project, slug)
    if path is None:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="journal-profile-missing",
                    message=f"no profile for {slug!r}",
                    hint="the journal-profile skill reads the journal's instructions and "
                    f"writes profiles/journals/{slug}.yaml; available: "
                    + (", ".join(available_profiles(project)) or "none"),
                ),
            )
        )

    document = read_structured(path)
    report = validate(document, "journal", path, gate=GATE)
    if not report.ok or not isinstance(document, dict):
        return report

    report = report.merge(_check_freshness(document, path))

    sources = source_files(project.path("manuscript"))
    text = "\n\n".join(p.read_text(encoding="utf-8") for p in sources)
    counts = measure(text)
    report = report.merge(_check_limits(document, counts, path))
    report = report.merge(_check_structure(document, text, path))
    report = report.merge(_check_statements(document, text, path))
    report = report.merge(_check_variant(document, project))

    return report.with_counts(
        abstract_words=counts.abstract_words,
        main_text_words=counts.main_text_words,
        display_items=counts.tables + counts.figures,
    )


def _check_freshness(document: dict, path: Path) -> Report:
    try:
        retrieved = date.fromisoformat(str(document["retrieved_on"]))
    except ValueError:
        return Report()
    if date.today() - retrieved <= STALE_AFTER:
        return Report()
    return Report(
        (
            Finding(
                gate=GATE,
                code="journal-profile-stale",
                severity=WARN,
                message=f"these guidelines were read on {retrieved.isoformat()}",
                path=path,
                hint=f"re-read {document.get('source_url', 'the instructions')} before "
                f"submitting; journals change them without announcement",
            ),
        )
    )


_LIMIT_LABELS = {
    "abstract_words": ("abstract", "words"),
    "main_text_words": ("main text", "words"),
    "total_words": ("abstract and main text", "words"),
    "figures": ("figures", ""),
    "tables": ("tables", ""),
    "display_items": ("figures and tables", ""),
}


def _check_limits(document: dict, counts, path: Path) -> Report:
    limits = document.get("limits", {})
    actual = {
        "abstract_words": counts.abstract_words,
        "main_text_words": counts.main_text_words,
        "total_words": counts.total_words,
        "figures": counts.figures,
        "tables": counts.tables,
        "display_items": counts.tables + counts.figures,
    }
    report = Report()
    for key, limit in limits.items():
        if key not in actual:
            continue
        value = actual[key]
        label, unit = _LIMIT_LABELS.get(key, (key, ""))
        suffix = f" {unit}" if unit else ""
        if value > limit:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="over-journal-limit",
                    message=f"{label}: {value}{suffix}, limit {limit}",
                    path=path,
                    hint=f"{value - limit}{suffix} over",
                )
            )
        elif limit and value > limit * 0.95:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="near-journal-limit",
                    severity=WARN,
                    message=f"{label}: {value}{suffix}, limit {limit}",
                    path=path,
                    hint="little room left for a reviewer's requested additions",
                )
            )
    return report


def _check_structure(document: dict, text: str, path: Path) -> Report:
    structure = document.get("structure", {})
    report = Report()
    sections = split_sections(text)
    titles = [s.title.lower() for s in sections if s.title]

    for required in structure.get("required_sections", []):
        if not any(required.lower() in title for title in titles):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="missing-required-section",
                    message=f"the journal requires a {required!r} section",
                    path=path,
                    hint="found: " + (", ".join(sorted(set(titles))) or "no headings"),
                )
            )

    wanted = structure.get("abstract_headings") or []
    if wanted:
        abstract = next((s for s in sections if s.is_abstract), None)
        if abstract is None:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="missing-abstract",
                    message="the journal requires a structured abstract and there is none",
                    path=path,
                )
            )
        else:
            body = abstract.body.lower()
            missing = [h for h in wanted if h.lower() not in body]
            if missing:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="abstract-headings-missing",
                        message=f"structured abstract is missing: {', '.join(missing)}",
                        path=path,
                        hint="the journal specifies " + ", ".join(wanted),
                    )
                )
    return report


def _check_statements(document: dict, text: str, path: Path) -> Report:
    report = Report()
    for statement in document.get("required_statements", []):
        if not re.search(statement["pattern"], text, re.IGNORECASE | re.MULTILINE):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="missing-required-statement",
                    message=f"the journal requires a {statement['id']} statement",
                    path=path,
                    hint=statement.get("why") or f"nothing matches {statement['pattern']!r}",
                )
            )
    return report


def _check_variant(document: dict, project: Project) -> Report:
    wanted = document.get("english_variant")
    if not wanted or wanted == "either" or wanted == project.english_variant:
        return Report()
    return Report(
        (
            Finding(
                gate=GATE,
                code="english-variant-mismatch",
                message=f"the journal wants {wanted}, paper.yaml says {project.english_variant}",
                hint=f"set english_variant: {wanted} in paper.yaml and re-read the prose",
            ),
        )
    )
