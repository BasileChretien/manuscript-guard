"""G5 — the reporting checklist is complete, and completed honestly.

Journals ask for a completed STROBE or CONSORT checklist at submission, and it is usually
filled in the night before by working backwards from the manuscript. That is the wrong way
round: the checklist is meant to surface what is missing while there is still time to add
it.

Producing it as a build artefact reverses that. Every item must say either where it is
addressed or why it does not apply, and "n/a" is not a reason. Where an item points at a
section, the section has to exist.

The item lists themselves are retrieved from each guideline's own site and stored with
their source. None is written from memory: a checklist whose items are approximately right
is worse than none, because it produces confident coverage of the wrong things.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, read_text, validate
from manuscript_guard.contracts.project import PAPER_FILE, Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.paths import SHIPPED_CHECKLISTS, recipes
from manuscript_guard.text.masking import mask
from manuscript_guard.text.reader import LATEX, manuscript_format
from manuscript_guard.text.sections import headings

GATE = "G5"
CHECKLIST_DIR = SHIPPED_CHECKLISTS
COMPLETION_DIR = "reporting"

_NON_REASONS = {"n/a", "na", "-", "none", "no", "not applicable", "n.a.", "nil"}


def checklist_path(project: Project, name: str) -> Path | None:
    local = project.root / "profiles" / "reporting" / f"{name}.yaml"
    if local.exists():
        return local
    shipped = CHECKLIST_DIR / f"{name}.yaml"
    return shipped if shipped.exists() else None


def available_checklists(project: Project) -> list[str]:
    found = set()
    for directory in (project.root / "profiles" / "reporting", CHECKLIST_DIR):
        if directory.exists():
            found.update(p.stem for p in directory.glob("*.yaml"))
    return sorted(found)


def recipe_names(project: Project) -> list[str]:
    """The guidelines a recipe exists for: those the package ships and any the project wrote."""
    return sorted(recipes(project.root))


def retrieval_advice(project: Project, name: str) -> str:
    """How to get a checklist that has not been retrieved.

    `fetch` and `transcribe` work from a recipe, so naming them for a guideline that has none
    sent the author to a command that answers "no recipe for ...".
    """
    known = recipe_names(project)
    if name in known:
        return (
            f"`manuscript-guard fetch {name}` then `manuscript-guard transcribe {name}` "
            "retrieve it from the guideline's own site and build it from that copy, and the "
            "reporting-checklist skill walks through it"
        )
    return (
        f"there is no recipe for {name} (recipes: {', '.join(known) or 'none'}), "
        "so `fetch` and `transcribe` cannot retrieve it; the reporting-checklist skill "
        "explains how to write one"
    )


def superseded_by(project: Project, name: str) -> str | None:
    """The guideline that replaced this one, as its recipe records from its authors' word."""
    path = recipes(project.root).get(name)
    if path is None:
        return None
    try:
        document = read_structured(path)
    except ContractError:  # an unreadable recipe is `transcribe`'s to report
        return None
    meta = document.get("meta") if isinstance(document, dict) else None
    replaced = meta.get("superseded_by") if isinstance(meta, dict) else None
    return str(replaced) if replaced else None


def _superseded(project: Project, wanted: list) -> Report:
    findings = []
    for name in wanted:
        replaced = superseded_by(project, str(name))
        if replaced:
            findings.append(
                Finding(
                    gate=GATE,
                    code="guideline-superseded",
                    severity=WARN,
                    message=f"{name} has been replaced by {replaced}, its authors say",
                    path=project.root / PAPER_FILE,
                    hint=f"name {replaced} in reporting_guideline unless the journal asks "
                    f"for {name}: `manuscript-guard fetch {replaced}` and `transcribe` "
                    "retrieve it",
                )
            )
    return Report(tuple(findings))


def completion_path(project: Project, name: str) -> Path:
    return project.root / COMPLETION_DIR / f"{name}.yaml"


#: Reporting guidelines a manuscript might claim adherence to in prose. Named rather than
#: pattern-matched, for the same reason the classifier's rules are: a shape would catch
#: every capitalised acronym in the paper.
CLAIMABLE = (
    "STROBE", "RECORD-PE", "RECORD", "CONSORT", "SPIRIT", "PRISMA", "TRIPOD", "ARRIVE",
    "READUS-PV", "READUS", "MOOSE", "SQUIRE", "STARD", "COREQ", "SRQR", "CHEERS", "ENTREQ",
)

#: Words that turn a mention of a guideline into a claim of having followed it.
_CLAIMING = re.compile(
    r"(?i)\b(?:follow\w*|adher\w*|accord\w*|conform\w*|complian\w*|compliant|prepared|"
    r"reported|written|guided|checklist|statement)\b"
)

#: Case-sensitive, because several of these acronyms are ordinary English words. Matched
#: case-insensitively, "According to the medical record" claimed adherence to RECORD and
#: "patients who arrive at the emergency department" claimed ARRIVE — so the gate warned
#: about a guideline on the Methods section of essentially every observational paper, which
#: teaches an author to stop reading its output. Guideline names are published in capitals
#: and written that way; requiring the published casing costs nothing and removes the family.
_NAMED = re.compile(r"\b(" + "|".join(sorted(CLAIMABLE, key=len, reverse=True)) + r")\b")

#: Sentence-ish. A claim and the guidelines it names sit in one sentence, and "followed
#: STROBE and RECORD-PE" names two - a single regex spanning verb to name caught only the
#: first, because the match consumed the text the second one needed.
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]|\n|$)")


def _claimed_in_prose(project: Project, declared: set[str]) -> Report:
    """A guideline the manuscript says it followed must be one the project completed.

    The worked example said "Analyses followed STROBE and RECORD-PE" while declaring a
    different profile entirely — and RECORD-PE was the wrong guideline for its design. No
    gate reconciled the sentence with the checklist, so a reader who went looking for the
    RECORD-PE items would find none. An adherence claim nothing checks is exactly the
    untraceable assertion this toolkit exists to remove, and it is a claim about the paper's
    own conduct, which makes it worse than an unbound number.
    """
    report = Report()
    named = _claims(_prose_texts(project))

    for name, path in sorted(named.items()):
        if any(name == entry or name in entry or entry in name for entry in declared):
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="guideline-claimed-not-declared",
                severity=WARN,
                message=f"the manuscript says it followed {name}, which is not in "
                f"`reporting_guideline:`",
                path=path,
                hint=f"declare {name} and complete its checklist, or drop the sentence; a "
                f"reader will look for those items",
            )
        )
    return report


def _for_design(project: Project, declared: set[str], wanted: list | None = None) -> Report:
    """Said where paper.yaml names a study design and none of its guidelines, which are named
    as paper.yaml writes them (`wanted`), not in the capitals they are compared in.

    The same table gives the plan's sections and the guidelines (`data/study_types.yaml`):
    a cohort study is reported with STROBE, or an extension of it such as RECORD, and a
    paper that declares a design and no guideline for it is checked against none of them.
    A guideline counts by its name, or the name an extension or a version adds to
    (STROBE-ME, TRIPOD+AI).
    """
    from manuscript_guard.gates.design import study_types

    design = project.study_type
    types = study_types()
    if design is None or design not in types:
        return Report()
    names = [str(name).upper() for name in types[design]["guidelines"]]
    if any(given.startswith(name) for given in declared for name in names):
        return Report()
    named = [str(name) for name in wanted] if wanted else sorted(declared)
    said = ", ".join(sorted(named, key=str.upper)) if named else "none"
    return Report(
        (
            Finding(
                gate=GATE,
                code="reporting-guideline-for-design",
                severity=WARN,
                message=f"a {types[design]['label']} is reported with "
                f"{' or '.join(types[design]['guidelines'])}, and paper.yaml declares {said}",
                hint="add the guideline to reporting_guideline in paper.yaml, or say why "
                "another one fits this design better",
            ),
        )
    )


def _claims(texts: list[tuple[Path, str]]) -> dict[str, Path]:
    """Each guideline a sentence of the texts says was followed, with the first file that
    says so."""
    named: dict[str, Path] = {}
    for path, text in texts:
        for sentence in _SENTENCE.finditer(text):
            said = sentence.group(0)
            if not _CLAIMING.search(said):
                continue
            for name in _NAMED.findall(said):
                named.setdefault(name.upper(), path)
    return named


def _prose_texts(project: Project) -> list[tuple[Path, str]]:
    """Each manuscript file as its claims are read, so that a claim inside a comment or code
    does not count: a comment reaches no document, and an author explaining a guideline in a
    note to themselves is not claiming to have followed it. A Markdown file is masked; a
    LaTeX file is its Markdown view, where a comment and what `\\iffalse` leaves out are
    spaces, with its code, `\\verb` and `\\texttt`, blanked as well (step 8)."""
    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return [(path, mask(read_text(path))) for path in source_files(folder)]
    from manuscript_guard.text.latex.views import files

    # A file nothing inputs and an author's package print nothing (round 1 of G8r in step 8).
    return [(found.path, _latex_prose(found.source, found.view)) for found in files(folder)
            if not found.source.loose and found.path.suffix.lower() != ".sty"]  # fmt: skip


def _latex_prose(source, view: str) -> str:
    """A LaTeX file's Markdown view with its code blanked, and a reference list typed in
    `thebibliography`, which cites a guideline's statement and claims nothing, as a Markdown
    paper's list from `references.bib` is never read (round 2 of G8r in step 8)."""
    return _blanked(view, (*source.reading.code, *source.reading.references))


def _blanked(text: str, spans) -> str:
    out = list(text)
    for start, end in spans:
        for index in range(start, end):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


def _printed_manuscript(project: Project) -> str:
    """The manuscript whose headings a checklist's answer may point at: a LaTeX one as its
    documents print, its headings `#` lines (step 8)."""
    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return "\n\n".join(read_text(p) for p in source_files(folder))
    from manuscript_guard.text.latex.printed import printed_document

    return "\n\n".join(printed_document(folder, supplementary=part) for part in (False, True))


def check_reporting(project: Project) -> Report:
    wanted = project.reporting_guidelines
    declared = {str(name).upper() for name in wanted}
    claims = _claimed_in_prose(project, declared).merge(
        _for_design(project, declared, list(wanted))
    )
    if not wanted:
        return claims.with_counts(checklists=0)

    report = claims.merge(_superseded(project, wanted))
    complete = 0
    known_headings = {h.lower() for h in headings(_printed_manuscript(project))}

    for name in wanted:
        path = checklist_path(project, name)
        if path is None:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="checklist-not-retrieved",
                    message=f"{name} is required but its item list has not been retrieved",
                    hint=f"{retrieval_advice(project, name)}; available: "
                    + (", ".join(available_checklists(project)) or "none"),
                )
            )
            continue

        document = read_structured(path)
        schema_report = validate(document, "reporting", path, gate=GATE)
        report = report.merge(schema_report)
        if not schema_report.ok or not isinstance(document, dict):
            continue

        item_report, done = _check_completion(project, name, document, known_headings)
        report = report.merge(item_report)
        complete += int(done)

    return report.with_counts(checklists=len(wanted), checklists_complete=complete)


def _check_completion(
    project: Project, name: str, checklist: dict, known_headings: set[str]
) -> tuple[Report, bool]:
    path = completion_path(project, name)
    items = checklist["items"]

    if not path.exists():
        return (
            Report(
                (
                    Finding(
                        gate=GATE,
                        code="checklist-not-started",
                        message=f"{name} has {len(items)} items and none are answered",
                        path=path,
                        hint=f"run `manuscript-guard checklist {name}` to write the file, "
                        f"then say where each item is addressed",
                    ),
                )
            ),
            False,
        )

    document = read_structured(path)
    schema_report = validate(document, "reporting_completion", path, gate=GATE)
    if not schema_report.ok or not isinstance(document, dict):
        return schema_report, False

    answered = {entry["id"]: entry for entry in document.get("items", [])}
    report = Report()
    outstanding = 0

    for item in items:
        entry = answered.get(item["id"])
        label = f"{name} {item['id']} ({item['topic']})"

        if entry is None:
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="checklist-item-missing",
                    message=f"{label} is not in the completed checklist",
                    path=path,
                    context=item["text"][:140],
                    hint=f"re-run `manuscript-guard checklist {name}` to add new items",
                )
            )
            continue

        where = str(entry.get("where", "")).strip()
        reason = str(entry.get("not_applicable", "")).strip()

        if not where and not reason:
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="checklist-item-unanswered",
                    message=f"{label} is neither addressed nor excluded",
                    path=path,
                    context=item["text"][:140],
                )
            )
            continue

        if reason and reason.lower() in _NON_REASONS:
            outstanding += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="checklist-non-reason",
                    message=f"{label}: {reason!r} is a tick, not a reason",
                    path=path,
                    hint="say why the item does not apply, e.g. 'no interventions were "
                    "assigned'; a reviewer reads this file",
                )
            )
            continue

        if where and not _points_somewhere_real(where, known_headings):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="checklist-location-unknown",
                    severity=WARN,
                    message=f"{label} points at {where!r}, which is not a heading",
                    path=path,
                    hint="headings: " + (", ".join(sorted(known_headings)) or "none"),
                )
            )

    unknown = sorted(set(answered) - {i["id"] for i in items})
    for extra in unknown:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="checklist-item-unknown",
                severity=WARN,
                message=f"{name}: item {extra!r} is not in the published checklist",
                path=path,
                hint="the checklist may have been revised; re-retrieve it",
            )
        )

    return report, outstanding == 0


def _points_somewhere_real(where: str, known_headings: set[str]) -> bool:
    lowered = where.lower()
    return any(heading and (heading in lowered or lowered in heading) for heading in known_headings)


def scaffold_completion(project: Project, name: str) -> tuple[Path, int, int]:
    """Write or extend the completion file, preserving answers already given."""
    import yaml

    source = checklist_path(project, name)
    if source is None:
        raise FileNotFoundError(f"no checklist for {name}; {retrieval_advice(project, name)}")
    checklist = read_structured(source)
    path = completion_path(project, name)

    existing: dict[str, dict] = {}
    if path.exists():
        current = read_structured(path) or {}
        existing = {e["id"]: e for e in current.get("items", [])}

    items = []
    added = 0
    for item in checklist["items"]:
        if item["id"] in existing:
            items.append(existing[item["id"]])
        else:
            added += 1
            items.append({"id": item["id"], "where": "", "note": item["topic"]})

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "manuscript-guard/reporting-completion/1",
                "guideline": name,
                "items": items,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path, len(items), added
