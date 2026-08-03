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

from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.sections import headings

GATE = "G5"
CHECKLIST_DIR = Path(__file__).parent.parent.parent.parent / "profiles" / "reporting"
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


def completion_path(project: Project, name: str) -> Path:
    return project.root / COMPLETION_DIR / f"{name}.yaml"


def check_reporting(project: Project) -> Report:
    wanted = project.reporting_guidelines
    if not wanted:
        return Report(counts={"checklists": 0})

    report = Report()
    complete = 0
    manuscript = "\n\n".join(
        p.read_text(encoding="utf-8") for p in source_files(project.path("manuscript"))
    )
    known_headings = {h.lower() for h in headings(manuscript)}

    for name in wanted:
        path = checklist_path(project, name)
        if path is None:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="checklist-not-retrieved",
                    message=f"{name} is required but its item list has not been retrieved",
                    hint="the reporting-checklist skill fetches it from the guideline's own "
                    "site and records the source; available: "
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
        raise FileNotFoundError(
            f"no checklist for {name}; retrieve it first with the reporting-checklist skill"
        )
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
