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
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.citation_style import check_style
from manuscript_guard.gates.data_statement import check_data_statement
from manuscript_guard.gates.figure_files import check_figure_files
from manuscript_guard.gates.journal_latex import check_latex_profile
from manuscript_guard.gates.journal_quotes import check_quotes, manual_signable
from manuscript_guard.gates.numbers import printed_order, source_files
from manuscript_guard.paths import SHIPPED_JOURNALS
from manuscript_guard.sign_offs import settle
from manuscript_guard.text.masking import without_front_matter
from manuscript_guard.text.section_names import bare, methods_sections, names_abstract
from manuscript_guard.text.sections import Counts, measure, scannable, split_sections

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


def main_text(project: Project, *, formula: str = "") -> str:
    """The main text as G4 reads it: every main-text source, less its front matter.

    One string, so a section can run on from one file into the next. Only the first file's
    front matter is at the top of it, and a later file's block was read as prose: its words
    counted, and its closing `---`, directly under a YAML line, underlined that line into a
    heading. `title: Methods of the online appendix` satisfied a required Methods section.
    The build strips every file's block, so the gate reads none of them, and a `# Funding`
    comment in the YAML no longer stands in for a funding statement either.

    A LaTeX manuscript's main text is its document as Markdown would write what it prints
    (`text/latex/printed.py`), the files the build prints in their order: a file nothing
    inputs and the author's packages are not the text.
    """
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.printed import printed_view
        from manuscript_guard.text.latex.structure import read_document

        # The author's packages are no text; a file input is, `Methods.TEX` as `methods.tex`.
        document = read_document(folder, supplementary=False)
        return printed_view([source for source in document.sources if not source.loose
                             and not source.path.lower().endswith(".sty")],
                            formula=formula)  # fmt: skip
    # In the order the build prints them, `main.md` first and the rest by file name: read in
    # path order, an `abstract.md` beside a `main.md` written in `##` headings put the whole
    # paper under the abstract's heading.
    sources = printed_order(source_files(folder, main_text_only=True), supplementary=False)
    return "\n\n".join(without_front_matter(read_text(p)) for p in sources)


def measured(project: Project, named: str | None = None, text: str | None = None) -> Counts:
    """The main text's counts, as G4 holds them to the journal's limits: `measure` of
    `main_text`, and in a LaTeX manuscript its tables and figures as LaTeX numbers them
    (`latex_displays`). `named` is what the journal's profile calls the abstract; `text` the
    main text where the caller has read it already."""
    from manuscript_guard.text.reader import LATEX, manuscript_format

    counts = measure(main_text(project) if text is None else text, named)
    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return counts
    tables, figures = latex_displays(folder)
    return replace(counts, tables=tables, figures=figures)


def latex_displays(folder: Path) -> tuple[int, int]:
    """The tables and the figures of a LaTeX manuscript's main text, as a journal counts its
    display items: one for each display a float's caption numbers, as G2's pointers count
    them (`printed(..., pointing=True)`), whatever the float places; and one for each
    `\\mg{table.key}` or `\\mg{figure.key}` that stands in no float or in one whose display
    the view cannot count, a float with no caption it reads among them, as before.

    Counted by its bindings alone, a figure placed with `\\includegraphics` and captioned
    counted as none, and a journal's limit on display items let it through (round 1 of step
    6, Known gaps)."""
    from manuscript_guard.text.latex.printed import (
        DISPLAY,
        MARK_END,
        _passed_over,
        _pointing_events,
        printed,
    )
    from manuscript_guard.text.latex.structure import read_document
    from manuscript_guard.text.latex.views import bindings

    sources = [source for source in read_document(folder, supplementary=False).sources
               if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
    marks = re.compile(f"{DISPLAY}([^{MARK_END}]*){MARK_END}")
    view = printed(sources, pointing=True).text
    # Each display a caption numbers; not a float of a group's, whose mark the group's is.
    kinds = [found[1][:1] for found in marks.finditer(view)]
    tables, figures = kinds.count("t"), kinds.count("f")
    # A binding outside every float is in the view as it is.
    tables += len(re.findall(r"\{\{table\.[a-z0-9_.]+\}\}", view))
    figures += len(re.findall(r"\{\{figure\.[a-z0-9_.]+\}\}", view))
    # A binding in a float, or another span, whose display the view cannot count.
    for source in sources:
        read, _comments = _passed_over(source.reading)
        placed = [p for p in bindings(source)[0]
                  if read(p.start) and p.ref.startswith(("table.", "figure."))]  # fmt: skip
        for start, end, written in _pointing_events(source):
            codes = [found[1][:1] for found in marks.finditer(written)]
            if not codes or not all(code in "TF" for code in codes):
                continue
            inside = [p.ref for p in placed if start <= p.start < end]
            tables += sum(ref.startswith("table.") for ref in inside)
            figures += sum(ref.startswith("figure.") for ref in inside)
    return tables, figures


#: What G4 reads from the project's records rather than from the manuscript's text, each as a
#: sentence: on a paper that is in no project (`audit --journal`, `records=False`) none of
#: them runs, and the audit says so of each (`auditing.journal`).
FROM_RECORDS = (
    "the profile's quotes, held to the journal's stored page",
    "the profile's rules no gate checks, signed off by the corresponding author (listed "
    "instead as the editor's checklist)",
    "the citation style kept for the offline build",
    "the figure files' artwork",
    "the LaTeX class rules",
    "the English paper.yaml declares (the profile's English is the one G14 holds the paper to)",
)


def check_journal(project: Project, *, records: bool = True,
                  cited: set[str] | None = None) -> Report:  # fmt: skip
    """G4 on the project's manuscript. With `records` False, only what reads the manuscript's
    text and the profile: its limits, its abstract, its sections and statements, its data
    statement and the profile's age, for a paper in no project, whose DOIs cited are `cited`
    (the reference list as the audit read it): `FROM_RECORDS` is what is left out."""
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
    if records:
        report = report.merge(check_quotes(project, slug, document, path))
        signable = manual_signable(slug, document, path)
        if signable is not None:
            report = report.with_findings(*settle(project, signable))

    # The main text only. A journal's word count, display-item count and required sections
    # are about the paper; a supplement counted against them turned a compliant submission
    # into an over-length one, and the author's recourse was to cut material the journal was
    # never going to count in the first place.
    text = main_text(project)
    named = abstract_title_of(document)
    counts = measured(project, named, text)
    report = report.merge(_check_limits(document, counts, path))
    report = report.merge(_check_abstract_found(document, text, path))
    report = report.merge(_check_structure(document, text, path))
    report = report.merge(_check_statements(document, text, path))
    report = report.merge(check_data_statement(document, text, path, project, cited=cited))
    if records:
        report = report.merge(_check_variant(document, project))
        report = report.merge(check_style(project, document, path))
        report = report.merge(check_figure_files(project, document, path))
        report = report.merge(check_latex_profile(project, document, path))

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


def figure_rules(project: Project) -> dict:
    """The target journal's artwork rules (`figures:`), for the checks of G3 that read them.
    Empty where there is no profile, none that can be read, or it says nothing of figures:
    G4 says why."""
    document = _profile(project)
    rules = None if document is None else document.get("figures")
    return rules if isinstance(rules, dict) else {}


def box_rules_of(project: Project) -> list:
    """The boxes the target journal asks for (`boxes:`), for G8, which reads a box's numbers
    as a summary's. None where there is no profile, or none that can be read, and not a box
    whose heading is no regular expression: G4 says why."""
    from manuscript_guard.text.boxes import box_rules

    document = _profile(project)
    return [] if document is None else box_rules(document)[0]


def abbreviations_asked(project: Project) -> tuple[bool, frozenset[str]]:
    """What the target journal asks to be defined though G14 would let it stand: whether the
    statistical abbreviations are (`abbreviations.define_statistics`), and which by name
    (`abbreviations.define`). Nothing where there is no profile, or none that can be read:
    G4 says why."""
    document = _profile(project)
    rules = (document or {}).get("abbreviations") or {}
    return bool(rules.get("define_statistics")), frozenset(map(str, rules.get("define") or ()))


def text_recycling(project: Project) -> str | None:
    """What the target journal says of text reused from its authors' earlier papers, in its
    page's words where the profile quotes them (`quotes.text_recycling`), else as the
    profile states it. None where the profile says nothing, or cannot be read."""
    document = _profile(project)
    if document is None or not document.get("text_recycling"):
        return None
    return (document.get("quotes") or {}).get("text_recycling") or document["text_recycling"]


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
    """A warning for the instructions read too long ago, and one for each block read from a
    page of its own on a date of its own (`graphical_abstract`, `sharing`), which is held to
    its age as the instructions' date is (round 1 of #464: it was never read)."""
    dated = [("", document)] + [(name, document[name]) for name in ("graphical_abstract",
             "sharing") if isinstance(document.get(name), dict)
             and document[name].get("retrieved_on")]  # fmt: skip
    findings = []
    for name, block in dated:
        try:
            retrieved = date.fromisoformat(str(block["retrieved_on"]))
        except ValueError:
            continue
        if date.today() - retrieved <= STALE_AFTER:
            continue
        these = f"the {name} rules were" if name else "these guidelines were"
        # The block's own page where it names one and no address (round 2 of #464: the hint
        # named the instructions' address).
        source = block.get("source_url") or (
            f"its page ({block['page_file']})" if name and block.get("page_file")
            else document.get("source_url", "the instructions"))  # fmt: skip
        findings.append(
            Finding(
                gate=GATE,
                code="journal-profile-stale",
                severity=WARN,
                message=f"{these} read on {retrieved.isoformat()}",
                path=path,
                hint=f"re-read {source} before submitting; journals change them without "
                "announcement",
            )
        )
    return Report(tuple(findings))


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


_ENGLISH_NAMES = {"en-GB": "British English", "en-US": "American English"}


def _check_variant(document: dict, project: Project) -> Report:
    wanted = document.get("english_variant")
    declared = project.english_variant
    if not wanted or wanted == "either" or wanted == declared:
        return Report()
    if declared is None:
        # A paper that declares no English has nothing to compare, and G14 holds it to the
        # English most of its words are in, which may not be the journal's: a note, never a
        # failure (Basile, 2026-10-23).
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="english-variant-undeclared",
                    severity=INFO,
                    message=f"the journal asks for {_ENGLISH_NAMES.get(wanted, wanted)} "
                    f"({wanted}), and paper.yaml declares no English",
                    hint=f"declare english_variant: {wanted} in paper.yaml to be held to it; "
                    "until then G14 holds the paper to the English most of its words are in",
                ),
            )
        )
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
