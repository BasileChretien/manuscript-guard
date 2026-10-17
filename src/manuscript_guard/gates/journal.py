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

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.figure_files import check_figure_files
from manuscript_guard.gates.journal_quotes import check_quotes
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.paths import SHIPPED_JOURNALS
from manuscript_guard.text.masking import without_front_matter
from manuscript_guard.text.section_names import bare, methods_sections, names_abstract
from manuscript_guard.text.sections import measure, scannable, split_sections

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


TEMPLATE = "TEMPLATE"


def available_profiles(project: Project) -> list[str]:
    """Journals a project could target. Excludes the template, which names no journal."""
    found = set()
    for directory in (project.root / "profiles" / "journals", PROFILE_DIR):
        if directory.exists():
            found.update(p.stem for p in directory.glob("*.yaml"))
    return sorted(found - {TEMPLATE})


def main_text(project: Project) -> str:
    """The main text as G4 reads it: every main-text source, less its front matter.

    One string, so a section can run on from one file into the next. Only the first file's
    front matter is at the top of it, and a later file's block was read as prose: its words
    counted, and its closing `---`, directly under a YAML line, underlined that line into a
    heading. `title: Methods of the online appendix` satisfied a required Methods section.
    The build strips every file's block, so the gate reads none of them, and a `# Funding`
    comment in the YAML no longer stands in for a funding statement either.
    """
    sources = source_files(project.path("manuscript"), main_text_only=True)
    return "\n\n".join(without_front_matter(read_text(p)) for p in sources)


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
    report = report.merge(check_quotes(project, slug, document, path))

    # The main text only. A journal's word count, display-item count and required sections
    # are about the paper; a supplement counted against them turned a compliant submission
    # into an over-length one, and the author's recourse was to cut material the journal was
    # never going to count in the first place.
    text = main_text(project)
    named = abstract_title_of(document)
    counts = measure(text, named)
    report = report.merge(_check_limits(document, counts, path))
    report = report.merge(_check_abstract_found(document, text, path))
    report = report.merge(_check_structure(document, text, path))
    report = report.merge(_check_statements(document, text, path))
    report = report.merge(_check_variant(document, project))
    report = report.merge(check_figure_files(project, document, path))

    return report.with_counts(
        abstract_words=counts.abstract_words,
        main_text_words=counts.main_text_words,
        display_items=counts.tables + counts.figures,
    )


def abstract_title_of(document: dict) -> str | None:
    """What the profile calls the abstract where it is not "Abstract" ("Summary")."""
    named = (document.get("structure") or {}).get("abstract_title")
    return str(named) if named else None


def abstract_title(project: Project) -> str | None:
    """The abstract's title in the target journal's profile, for the gates that read the
    abstract and are not G4. None where there is no profile, or none that can be read: G4
    says what is wrong with it."""
    document = _profile(project)
    return None if document is None else abstract_title_of(document)


def blinding(project: Project) -> str | None:
    """How the target journal's peer review is blinded, as its profile says ("double"), for
    the build. None where the profile says nothing, or cannot be read: G4 says why."""
    document = _profile(project)
    return None if document is None else document.get("blinding")


def _profile(project: Project) -> dict | None:
    """The target journal's profile, where there is one that can be read and is valid."""
    slug = project.target_journal
    path = profile_path(project, slug) if slug else None
    if path is None:
        return None
    try:
        document = read_structured(path)
    except (ContractError, OSError):
        return None
    if not isinstance(document, dict) or not validate(document, "journal", path).ok:
        return None
    return document


def _check_abstract_found(document: dict, text: str, path: Path) -> Report:
    """Said where the profile limits the abstract and no heading names one: the limit was
    checked against nothing, and the abstract's words counted as main text."""
    limit = (document.get("limits") or {}).get("abstract_words")
    named = abstract_title_of(document)
    if limit is None or any(s.names_abstract(named) for s in split_sections(text)):
        return Report()
    looked = '"Abstract"' + (f' and "{named}"' if named else "")
    return Report(
        (
            Finding(
                gate=GATE,
                code="abstract-not-found",
                severity=WARN,
                message=f"no heading names the abstract (looked for {looked}), so its limit "
                f"of {limit} words was not checked and its words were counted as main text",
                path=path,
                hint="put the abstract under a heading; where the journal calls it something "
                'else, say so in the profile: `structure: {abstract_title: "Summary"}`',
            ),
        )
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


def _present(required: str, sections, named: str | None) -> bool:
    """Whether a heading answers a section the journal requires: its name in one of the
    paper's headings, as G4 has always read one. The Methods by the test G9 reads them by
    (`text.section_names.methods_sections`), so that what G4 counts present is what G9
    reads; the abstract by the title G14 and the word count read it by. "Materials and
    methods" is held to its own words, as every other required section is."""
    if bare(required).casefold() == "methods":
        return bool(methods_sections(sections, named))
    titles = paper_titles(sections, named)
    if names_abstract(required, named):
        return any(names_abstract(title, named) for title in titles)
    return any(required.lower() in title for title in titles)


def paper_titles(sections, named: str | None) -> list[str]:
    """The titles of the paper's sections, lower-cased, less the headings inside the
    abstract. A structured abstract's "Methods" and "Results" are the abstract's: read as
    the paper's, they answered a required Methods section in a paper with none, while G9,
    which reads the Methods, passed them over."""
    titles: list[str] = []
    chain: list = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        if section.title and not any(s.names_abstract(named) for s in chain):
            titles.append(section.title.lower())
        chain.append(section)
    return titles


def _check_structure(document: dict, text: str, path: Path) -> Report:
    structure = document.get("structure", {})
    report = Report()
    sections = split_sections(text)
    named = abstract_title_of(document)
    titles = paper_titles(sections, named)

    for required in structure.get("required_sections", []):
        if not _present(required, sections, named):
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
        abstract = next((s for s in sections if s.names_abstract(named)), None)
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
            # Comments and listings blanked, as for the required statements below: a
            # heading in `<!-- Conclusions: to write -->` is one the abstract does not print.
            body = scannable(abstract.enclosed).lower()
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
    # Read where a statement can be: HTML comments and fenced code blanked, as the heading
    # scan blanks them. `# Funding` is a heading in Markdown and a comment in R and Python,
    # so inside `<!-- -->` it met the funding statement and printed nothing, and inside a
    # listing it printed as a line of code. A statement is prose an editor reads.
    printed = scannable(text)
    report = Report()
    for statement in document.get("required_statements", []):
        if not re.search(statement["pattern"], printed, re.IGNORECASE | re.MULTILINE):
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
