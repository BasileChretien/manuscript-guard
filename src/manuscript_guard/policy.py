"""Which gates bind, at which point in the work.

A paper is not written in one pass, and a checker that demands everything from the first
day is a checker that gets switched off on the second. Someone still writing the analysis
should not be told the figures are unreviewed and no journal has been chosen; those are true
and useless.

So each finding declares the **stage at which it starts to matter**. Before that stage it is
reported and demoted; from that stage on it fails. The stage comes from `paper.yaml`, or
from `--stage` for a one-off run.

Two rules keep this from becoming a way to hide problems.

**Nothing is skipped.** Every gate runs at every stage; only severity changes. A deferred
finding is still printed, still counted, and the summary says how many are waiting and for
what. A check that quietly stopped looking would be worse than no check.

**Unlisted codes always bind.** A finding this table does not know about is a failure at
every stage. Adding a gate cannot accidentally make it optional; the author of the gate has
to decide, in this file, when it should start to matter.
"""

from __future__ import annotations

from dataclasses import replace

from manuscript_guard.findings import FAIL, INFO, Report

DESIGN = "design"
ANALYSIS = "analysis"
DRAFTING = "drafting"
INTERNAL_REVIEW = "internal-review"
SUBMISSION = "submission"

STAGES = (DESIGN, ANALYSIS, DRAFTING, INTERNAL_REVIEW, SUBMISSION)

DESCRIPTIONS = {
    DESIGN: "writing the analysis plan; no analysis or manuscript yet",
    ANALYSIS: "writing and running the analysis; the manuscript can wait",
    DRAFTING: "writing the manuscript against results that exist",
    INTERNAL_REVIEW: "draft complete; panels, checklists and the journal's rules apply",
    SUBMISSION: "the version you send anywhere",
}

# When each finding starts to fail. Everything not listed fails from the beginning.
BINDS_AT = {
    # -- analysis ---------------------------------------------------------------
    # Results must be trustworthy as soon as they exist. Their *existence* is a drafting
    # requirement, not an analysis one: results appear at the end of the analysis stage,
    # not at its start.
    "input-missing": ANALYSIS,
    "input-changed": ANALYSIS,
    "script-missing": ANALYSIS,
    "script-newer": ANALYSIS,
    "results-edited": ANALYSIS,
    # -- drafting ---------------------------------------------------------------
    # Numbers in prose only exist once there is prose.
    "no-results-dir": DRAFTING,
    "no-results": DRAFTING,
    "authors-incomplete": DRAFTING,
    "unclassified-number": DRAFTING,
    "hand-authored-table": DRAFTING,
    "malformed-placeholder": DRAFTING,
    "unresolved-binding": DRAFTING,
    "unquoted-result": DRAFTING,
    "unplaced-table": DRAFTING,
    "divergent-display": DRAFTING,
    # Figures are still being redrawn while the text is drafted; their numbers must
    # nevertheless be real from the moment they are rendered.
    "figure-number-unbound": DRAFTING,
    "figure-source-text-number": DRAFTING,
    "figure-source-hardcoded-data": DRAFTING,
    "figure-source-unclassified-number": DRAFTING,
    "figure-script-ignores-results": DRAFTING,
    # A quoted source has to be a real source as soon as it is quoted.
    "quote-not-in-source": DRAFTING,
    "value-not-in-quote": DRAFTING,
    "literature-source-missing": DRAFTING,
    "attestation-not-human": DRAFTING,
    "citation-unresolved": DRAFTING,
    # Model artefacts are never acceptable in text anyone will read.
    "model-artefact": DRAFTING,
    # -- internal review --------------------------------------------------------
    # The draft is finished; now it is held to the journal's rules and read properly.
    "figure-unreviewed": INTERNAL_REVIEW,
    "figure-review-stale": INTERNAL_REVIEW,
    "figure-review-incomplete": INTERNAL_REVIEW,
    "figure-review-check-failed": INTERNAL_REVIEW,
    "figure-review-concerns": INTERNAL_REVIEW,
    "figure-review-finding": INTERNAL_REVIEW,
    "journal-profile-missing": INTERNAL_REVIEW,
    "over-journal-limit": INTERNAL_REVIEW,
    "missing-required-section": INTERNAL_REVIEW,
    "missing-abstract": INTERNAL_REVIEW,
    "abstract-headings-missing": INTERNAL_REVIEW,
    "missing-required-statement": INTERNAL_REVIEW,
    "english-variant-mismatch": INTERNAL_REVIEW,
    "checklist-not-retrieved": INTERNAL_REVIEW,
    "checklist-not-started": INTERNAL_REVIEW,
    "checklist-item-missing": INTERNAL_REVIEW,
    "checklist-item-unanswered": INTERNAL_REVIEW,
    "checklist-non-reason": INTERNAL_REVIEW,
    "methods-drift": INTERNAL_REVIEW,
    # -- submission -------------------------------------------------------------
    # The panel's verdict is the last thing to bind, because a panel reviews a draft
    # that is otherwise finished.
    "no-review": SUBMISSION,
    "rounds-outstanding": SUBMISSION,
    "review-missing": SUBMISSION,
    "review-stale": SUBMISSION,
    "open-major-finding": SUBMISSION,
}


def stage_index(stage: str) -> int:
    try:
        return STAGES.index(stage)
    except ValueError as exc:
        raise ValueError(f"unknown stage {stage!r}; expected one of {', '.join(STAGES)}") from exc


def binds_at(code: str) -> str:
    """The stage at which this finding becomes a failure. Unknown codes bind immediately."""
    return BINDS_AT.get(code, DESIGN)


def apply_stage(report: Report, stage: str) -> tuple[Report, dict[str, int]]:
    """Demote failures that do not bind yet. Returns the report and what was deferred.

    Demoted to INFO rather than WARN: a warning is something to look at now, and these are
    things that are not yet due. Mixing them would drown the warnings that are.
    """
    here = stage_index(stage)
    deferred: dict[str, int] = {}
    out = []

    for finding in report.findings:
        if finding.severity != FAIL:
            out.append(finding)
            continue
        due = binds_at(finding.code)
        if stage_index(due) <= here:
            out.append(finding)
            continue
        deferred[due] = deferred.get(due, 0) + 1
        out.append(
            replace(
                finding,
                severity=INFO,
                message=f"{finding.message}  [not due until {due}]",
            )
        )

    return replace(report, findings=tuple(out)), deferred


def summarise_deferred(deferred: dict[str, int]) -> str:
    if not deferred:
        return ""
    in_order = sorted(deferred.items(), key=lambda item: stage_index(item[0]))
    parts = [f"{count} at {stage}" for stage, count in in_order]
    total = sum(deferred.values())
    return (
        f"{total} finding{'' if total == 1 else 's'} not due yet ({'; '.join(parts)}). "
        f"They are listed above as INFO, not hidden."
    )


def resolve_stage(project, override: str | None, submission: bool) -> str:
    """--submission wins, then --stage, then paper.yaml, then a sensible default."""
    if submission:
        return SUBMISSION
    if override:
        stage_index(override)  # validate
        return override
    declared = project.paper.get("stage")
    if declared:
        stage_index(declared)
        return declared
    return DRAFTING


__all__ = [
    "ANALYSIS",
    "BINDS_AT",
    "DESCRIPTIONS",
    "DESIGN",
    "DRAFTING",
    "INTERNAL_REVIEW",
    "STAGES",
    "SUBMISSION",
    "apply_stage",
    "binds_at",
    "resolve_stage",
    "stage_index",
    "summarise_deferred",
]
