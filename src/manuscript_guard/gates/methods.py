"""G9 — does the Methods section still describe what the code does?

Methods sections go stale in a particular way. The analysis is written, the Methods are
written to match, and then the analysis changes: a filter is added, a model is swapped, a
threshold moves. Nothing forces the prose to follow, and nobody re-reads their own Methods
once they are written. The result is a paper that describes an analysis nobody ran.

No checker can read code and prose and decide whether they agree. What it can do is notice
that the code changed after the prose was last reconciled with it, and refuse to let that
pass silently. So this gate is a **reconciliation ledger**: `methods.lock` records the
analysis files as they stood when someone last read the Methods against them, and the gate
compares.

That makes the claim modest and true. It does not verify that the Methods are correct. It
verifies that somebody looked, and that nothing has changed since they did.

Two additions make the prompt useful rather than annoying. The report names *which* files
changed, so the reconciliation is targeted. And a handful of parameters that must agree —
the significance threshold, the software versions — are extracted from both sides and
compared directly, because those are checkable and they are what reviewers query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project
from manuscript_guard.emit import sha256_of
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.sections import split_sections

GATE = "G9"
LOCK = "methods.lock"
SOURCE_SUFFIXES = {".r", ".rmd", ".qmd", ".py", ".ipynb", ".sql", ".jl", ".do", ".sas"}

_METHODS_HEADING = re.compile(r"^\s*(?:materials and )?methods\b", re.IGNORECASE)


@dataclass(frozen=True)
class Drift:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def describe(self) -> str:
        parts = []
        for label, names in (
            ("changed", self.changed),
            ("added", self.added),
            ("removed", self.removed),
        ):
            if names:
                shown = ", ".join(sorted(names)[:4])
                more = f" (+{len(names) - 4} more)" if len(names) > 4 else ""
                parts.append(f"{label}: {shown}{more}")
        return "; ".join(parts)


def analysis_digests(project: Project) -> dict[str, str]:
    directory = project.path("analysis")
    if not directory.exists():
        return {}
    out = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            out[str(path.relative_to(project.root)).replace("\\", "/")] = sha256_of(path)
    return out


def lock_path(project: Project) -> Path:
    return project.root / LOCK


def read_lock(project: Project) -> dict:
    path = lock_path(project)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compare(current: dict[str, str], recorded: dict[str, str]) -> Drift:
    return Drift(
        added=tuple(sorted(set(current) - set(recorded))),
        removed=tuple(sorted(set(recorded) - set(current))),
        changed=tuple(sorted(k for k in set(current) & set(recorded) if current[k] != recorded[k])),
    )


def methods_text(project: Project) -> str:
    for path in source_files(project.path("manuscript")):
        for section in split_sections(path.read_text(encoding="utf-8")):
            if _METHODS_HEADING.match(section.title):
                return section.body
    return ""


def check_methods(project: Project) -> Report:
    current = analysis_digests(project)
    if not current:
        return Report(counts={"analysis_files": 0})

    lock = read_lock(project)
    recorded = lock.get("analysis", {})

    if not recorded:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="methods-never-reconciled",
                    severity=WARN,
                    message=f"the Methods have never been read against the {len(current)} "
                    f"analysis file(s)",
                    path=lock_path(project),
                    hint="read the Methods against the code, then run "
                    "`manuscript-guard methods --reconcile`",
                ),
            ),
            {"analysis_files": len(current)},
        )

    drift = compare(current, recorded)
    report = Report()
    if drift.any:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="methods-drift",
                message="the analysis changed after the Methods were last reconciled with it",
                path=lock_path(project),
                context=drift.describe(),
                hint="re-read the Methods against those files, then "
                "`manuscript-guard methods --reconcile`",
            )
        )

    report = report.merge(_compare_parameters(project, lock))
    return report.with_counts(
        analysis_files=len(current),
        analysis_changed=len(drift.changed) + len(drift.added) + len(drift.removed),
    )


def _compare_parameters(project: Project, lock: dict) -> Report:
    """The few things both sides state explicitly, and where disagreement is checkable."""
    report = Report()
    prose = methods_text(project)
    if not prose:
        return report

    declared = lock.get("parameters", {})
    for name, expected in declared.items():
        if str(expected).lower() in prose.lower():
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="methods-parameter-absent",
                severity=WARN,
                message=f"the Methods do not mention {name} = {expected}",
                path=lock_path(project),
                hint="either the Methods should state it, or it should not be in the lock",
            )
        )
    return report


def reconcile(project: Project, *, parameters: dict | None = None) -> tuple[Path, int]:
    """Record the analysis as it stands. Run after reading the Methods against the code."""
    from datetime import date

    current = analysis_digests(project)
    existing = read_lock(project)
    document = {
        "schema": "manuscript-guard/methods-lock/1",
        "reconciled_on": date.today().isoformat(),
        "parameters": parameters if parameters is not None else existing.get("parameters", {}),
        "analysis": current,
    }
    path = lock_path(project)
    header = (
        "# Records the analysis as it stood when the Methods were last read against it.\n"
        "# Written by `manuscript-guard methods --reconcile`. Re-run it after you have\n"
        "# re-read the Methods, not merely after the code changed: the point of the file\n"
        "# is that a person looked.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return path, len(current)
