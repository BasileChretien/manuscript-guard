"""G12 — was there a plan before there was an analysis?

The strongest thing anyone can do for the credibility of a result is to write down what
they intended to do before they did it. Not because deviating is wrong — most real analyses
deviate — but because a deviation that was declared is a decision, and a deviation nobody
recorded is indistinguishable from having tried several things and reported the best one.

This gate **warns and never blocks**, by explicit decision. Blocking would be the stronger
discipline and it would be unworkable: exploratory work is real work, and a gate that
prevents you writing code until a plan is agreed is a gate that gets bypassed on the first
afternoon it costs you something.

So it does the useful part instead. It notices that analysis code exists with no plan behind
it, and it insists that the plan's sections say something rather than existing. A plan whose
"Deviations from the plan" heading is empty is a plan nobody has revisited, which is the
common case and the one worth naming.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.methods import analysis_digests
from manuscript_guard.text.sections import split_sections

GATE = "G12"
PLAN = Path("design") / "plan.md"

# Each entry: heading pattern, and what it is for. Wording is matched loosely because an
# author's headings are their own.
REQUIRED = (
    ("question", r"(?i)\b(research )?question|objective", "what is being asked"),
    ("design", r"(?i)\bdesign\b", "the study design and why it suits the question"),
    ("population", r"(?i)\bpopulation|participants|data source\b", "who or what is included"),
    ("exposure", r"(?i)\bexposure|intervention|predictor\b", "what is being compared"),
    ("outcome", r"(?i)\boutcome|endpoint\b", "what is being measured"),
    ("analysis", r"(?i)\banalysis|statistical\b", "the estimator and the model"),
    (
        "deviations",
        r"(?i)\bdeviation|changes? (from|to) the plan|amendments?\b",
        "what changed after the plan was agreed, or that nothing did",
    ),
)

# A section that exists but says nothing useful.
_EMPTY = re.compile(r"^\s*(?:tbd|todo|n/?a|-+|\.+|see below)?\s*$", re.IGNORECASE)


def plan_path(project: Project) -> Path:
    return project.root / PLAN


def check_design(project: Project) -> Report:
    path = plan_path(project)
    analysis = analysis_digests(project)

    if not path.exists():
        if not analysis:
            return Report(counts={"design_sections": 0})
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="no-analysis-plan",
                    severity=WARN,
                    message=f"{len(analysis)} analysis file(s) exist and there is no {PLAN}",
                    path=path,
                    hint="write down what you intended before you did it; the design-gate "
                    "skill has the outline. A deviation that was declared is a decision",
                )
            ,),
            {"design_sections": 0},
        )

    text = path.read_text(encoding="utf-8")
    sections = split_sections(text)
    report = Report()
    covered = 0

    for name, pattern, purpose in REQUIRED:
        matching = [s for s in sections if re.search(pattern, s.title)]
        if not matching:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="plan-section-missing",
                    severity=WARN,
                    message=f"the plan says nothing about {name}",
                    path=path,
                    hint=purpose,
                )
            )
            continue
        if all(_EMPTY.match(s.body.strip()) for s in matching):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="plan-section-empty",
                    severity=WARN,
                    message=f"the plan's {name} section is a heading with nothing under it",
                    path=path,
                    line=matching[0].line,
                    hint=purpose,
                )
            )
            continue
        covered += 1

    if covered == len(REQUIRED):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="plan-complete",
                severity=INFO,
                message=f"analysis plan covers all {covered} expected sections",
                path=path,
            )
        )

    return report.with_counts(design_sections=covered, design_expected=len(REQUIRED))
