"""G12 — a panel reads the plan before there are results.

A review panel reads the manuscript, which is written once the analysis has run: by then
the design is spent, and a reviewer who says the comparison cannot answer the question is
saying it too late. So a design round is a panel that reads `design/plan.md`, and the
feasibility results (`feasibility.*`), at the `design` stage. Its remits ask whether the
design supports the inference the plan intends, and name the risks of the study type:
confounding, selection, immortal time, missing data, multiplicity, leakage.

It is kept apart from the manuscript's rounds, in `review/design/`: `panel-<n>.yaml` names
the readers and their remits, and `round-<n>/<reviewer>.yaml` is a reading, written by
`manuscript-guard review --record <reviewer> --design --round <n> --verdict <verdict>` with
the digest of the plan it read. So a design round never counts toward the manuscript's
rounds, and a manuscript round never answers the design.

A reading of a plan that has changed since is stale. A major finding not answered, by a
resolution or by an override with its reason, is a warning, and a failure at submission
only: what an unanswered design objection means is the author's to weigh while there is
still an analysis to change. A reading is sealed as a manuscript reading is
(`review --seal <reviewer> --design --round <n>`), and one changed after its seal fails at
submission.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.review import _answered, _check_seal, review_root

GATE = "G12"
DESIGN_DIR = "design"
SCHEMA = "manuscript-guard/design-review/1"
#: What every key a feasibility script emits opens with, as G12 asks for them.
FEASIBILITY = "feasibility."


def design_root(project: Project) -> Path:
    return review_root(project) / DESIGN_DIR


def design_panel_path(project: Project, round_number: int) -> Path:
    return design_root(project) / f"panel-{round_number}.yaml"


def design_record_path(project: Project, round_number: int, reviewer: str) -> Path:
    return design_root(project) / f"round-{round_number}" / f"{reviewer}.yaml"


def design_panels(project: Project) -> list[tuple[int, Path]]:
    root = design_root(project)
    found = []
    for path in sorted(root.glob("panel-*.yaml")) if root.is_dir() else []:
        number = path.stem.split("-", 1)[1]
        if number.isascii() and number.isdigit():
            found.append((int(number), path))
    return sorted(found)


def plan_digest(project: Project) -> str:
    """What a design round reads: the plan's bytes, and each feasibility result's value and
    display, by key. A plan edited, or the data counted again, is another plan to read."""
    from manuscript_guard.gates.design import plan_path

    digest = hashlib.sha256()
    plan = plan_path(project)
    digest.update(plan.read_bytes() if plan.is_file() else b"")
    counted: dict[str, list] = {}
    results = project.path("results")
    for path in sorted(results.glob("*.json")) if results.is_dir() else []:
        try:
            document = read_structured(path)
        except ContractError:
            continue
        values = document.get("values") if isinstance(document, dict) else None
        for key, spec in (values or {}).items() if isinstance(values, dict) else ():
            if key.startswith(FEASIBILITY) and isinstance(spec, dict):
                counted[key] = [spec.get("value"), spec.get("display")]
    digest.update(json.dumps(counted, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def check_design_rounds(project: Project, *, submission: bool = False) -> Report:
    """Each design round's readings against the plan as it stands, and their major
    findings answered."""
    found = design_panels(project)
    if not found:
        # Nothing, counts included: a project with no design round reads as it did before.
        return Report()
    severity = FAIL if submission else WARN
    current = plan_digest(project)
    report = Report()
    open_major = 0
    rounds: list[tuple[int, Report, bool]] = []
    for number, path in found:
        try:
            panel = read_structured(path)
        except ContractError as exc:
            report = report.with_findings(_finding("design-panel-unreadable", str(exc), path))
            continue
        checked = validate(panel, "panel", path, gate=GATE)
        report = report.merge(checked)
        if not checked.ok or not isinstance(panel, dict):
            continue
        said, fresh = Report(), True
        for reviewer in panel["reviewers"]:
            read, read_current, opened = _reading(project, number, reviewer, current, severity)
            said = said.merge(read)
            fresh = fresh and read_current
            open_major += opened
        rounds.append((number, said, fresh))
    # The latest round that read the plan as it stands supersedes every earlier one that read
    # another (round 1 of #308: the further round the stale reading's hint asks for left it
    # stale for good). Their open majors still bind: a later reading does not answer them.
    latest = max((number for number, _said, fresh in rounds if fresh), default=0)
    for number, said, fresh in rounds:
        if not fresh and number < latest:
            said = Report(tuple(
                replace(f, code="design-review-superseded", severity=INFO,
                        message=f"{f.message} [superseded by design round {latest}]",
                        hint=f"design round {latest} read the plan as it stands")
                if f.code == "design-review-stale" else f
                for f in said.findings
            ))  # fmt: skip
        report = report.merge(said)
    return report.with_counts(
        design_rounds=len(found), design_rounds_current=sum(fresh for *_r, fresh in rounds),
        design_open_major=open_major,
    )  # fmt: skip


def _reading(
    project: Project, number: int, reviewer: dict, current: str, severity: str
) -> tuple[Report, bool, int]:
    """What one reviewer's reading says: the report, whether it read the plan as it stands,
    and how many of its major findings are open."""
    name = reviewer["id"]
    path = design_record_path(project, number, name)
    report = Report()
    if reviewer.get("readers"):
        report = report.with_findings(_finding(
            "design-readers-unread",
            f"design round {number}: {name} names readers, and a design round reads the "
            "reviewer's own record only", path, severity=WARN,
            hint="file the reading as the reviewer's record, without --reading",
        ))  # fmt: skip
    if not path.is_file():
        return report.with_findings(_finding(
            "design-review-missing", f"design round {number}: {name} has not read the plan",
            path, severity=WARN,
            hint=f"once they have, `manuscript-guard review --record {name} --design --round "
            f"{number} --verdict <verdict>`",
        )), False, 0  # fmt: skip
    try:
        document = read_structured(path)
    except ContractError as exc:
        return report.with_findings(_finding("design-review-unreadable", str(exc), path)), \
            False, 0  # fmt: skip
    checked = validate(document, "design-review", path, gate=GATE)
    if not checked.ok or not isinstance(document, dict):
        return report.merge(checked), False, 0
    fresh = document["plan_sha256"] == current
    if not fresh:
        report = report.with_findings(_finding(
            "design-review-stale",
            f"design round {number}: {name} read a plan that has changed since", path,
            severity=WARN, context=f"read {document['reviewed_on']} by "
            f"{document['reviewed_by']}",
            hint="the plan or the feasibility results changed after the reading; record a "
            "further design round that reads the plan as it stands",
        ))  # fmt: skip
    sealed = _check_seal(path, document, number, name, severity)
    report = report.with_findings(*(
        replace(f, gate=GATE, code=f"design-{f.code}", message=f"design {f.message}",
                hint=(f.hint or "").replace("review --seal <reviewer> --round <n>",
                                            "review --seal <reviewer> --design --round <n>")
                .replace(", with `--reading <reader>` for a named reading", ""))
        for f in sealed.findings
    ))  # fmt: skip
    opened = 0
    for finding in document.get("findings") or []:
        if finding.get("severity") == "major" and not _answered(finding):
            opened += 1
            report = report.with_findings(_finding(
                "design-major-open",
                f"design round {number}: {name} {finding.get('id')}: "
                f"{str(finding.get('finding', ''))[:120]}", path, severity=severity,
                hint="answer it in `resolution` with what the plan now does, or in "
                "`overridden` with why it stands; a design objection answered before the "
                "analysis is one the analysis can still meet",
            ))  # fmt: skip
    return report, fresh, opened


def _finding(
    code: str, message: str, path: Path, *, severity: str = FAIL, hint: str | None = None,
    context: str | None = None,
) -> Finding:
    return Finding(gate=GATE, code=code, severity=severity, message=message, path=path,
                   hint=hint, context=context)  # fmt: skip
