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

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts.project import PAPER_FILE
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
    "no-digest": ANALYSIS,
    # A parameter the analysis declares and never reads is wrong as soon as it is written.
    "parameter-unread": ANALYSIS,
    # So is arithmetic the analysis declares and its own numbers break. A relation naming a
    # key may wait for the other script to run, as a binding waits for its key.
    "relation-broken": ANALYSIS,
    "flow-broken": ANALYSIS,
    "relation-unresolved": DRAFTING,
    # A model that is the wrong model is wrong as soon as it is fitted.
    "model-variable-undeclared": ANALYSIS,
    "model-outcome-kind": ANALYSIS,
    "model-categories-as-number": ANALYSIS,
    "model-binary-as-number": ANALYSIS,
    "model-level-undeclared": ANALYSIS,
    "model-reference": ANALYSIS,
    "model-not-converged": ANALYSIS,
    "model-empty-level": ANALYSIS,
    "variable-level-undeclared": ANALYSIS,
    "variable-not-binary": ANALYSIS,
    # -- drafting ---------------------------------------------------------------
    # Numbers in prose only exist once there is prose.
    "no-results-dir": DRAFTING,
    "no-results": DRAFTING,
    # A manuscript folder with nothing in it the gates read: from the stage there is prose.
    "manuscript-empty": DRAFTING,
    "authors-incomplete": DRAFTING,
    "unclassified-number": DRAFTING,
    # A count the custodian forbids may be read inside the team; not outside it, which a
    # panel sent to a model provider already is.
    "count-below-minimum": INTERNAL_REVIEW,
    "code-block-text-number": DRAFTING,
    "raw-block": DRAFTING,
    # TeX in the text that the Word writer leaves out. Pandoc is asked for it, and what it
    # takes is a number as often as not: it binds with the numbers.
    "tex-in-the-text": DRAFTING,
    "hand-authored-table": DRAFTING,
    "malformed-placeholder": DRAFTING,
    "unresolved-binding": DRAFTING,
    "unquoted-result": DRAFTING,
    "typed-parameter": DRAFTING,
    "typed-software-version": DRAFTING,
    "typed-dictionary-release": DRAFTING,
    "typed-model-kind": DRAFTING,
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
    # So does a passage recorded as a cited work's words, and only a person judges one.
    "passage-not-in-source": DRAFTING,
    "judgement-not-human": DRAFTING,
    "citation-unresolved": DRAFTING,
    # Model artefacts are never acceptable in text anyone will read.
    "model-artefact": DRAFTING,
    # A cited work that was retracted is not evidence, whatever stage the draft is at,
    # and a record edited by hand may be hiding one.
    "reference-retracted": DRAFTING,
    "lookup-record-edited": DRAFTING,
    # -- internal review --------------------------------------------------------
    # The draft is finished; now it is held to the journal's rules and read properly.
    "figure-unreviewed": INTERNAL_REVIEW,
    "figure-review-stale": INTERNAL_REVIEW,
    "figure-review-incomplete": INTERNAL_REVIEW,
    "figure-review-check-failed": INTERNAL_REVIEW,
    "figure-review-concerns": INTERNAL_REVIEW,
    "figure-review-finding": INTERNAL_REVIEW,
    "journal-profile-missing": INTERNAL_REVIEW,
    # How many rows a model lost to missing values is for the finished draft to say.
    "model-rows-dropped": INTERNAL_REVIEW,
    "over-journal-limit": INTERNAL_REVIEW,
    # A rule of the profile read wrong, or never on the journal's page.
    "journal-quote-not-on-page": INTERNAL_REVIEW,
    "journal-limit-not-in-quote": INTERNAL_REVIEW,
    "missing-required-section": INTERNAL_REVIEW,
    "missing-abstract": INTERNAL_REVIEW,
    "abstract-headings-missing": INTERNAL_REVIEW,
    "missing-required-statement": INTERNAL_REVIEW,
    # What the journal's data policy, as its profile records it, does not accept: binding when
    # the statement is, since a draft's statement is often written last.
    "data-statement-forbidden": INTERNAL_REVIEW,
    "data-identifier-missing": INTERNAL_REVIEW,
    "english-variant-mismatch": INTERNAL_REVIEW,
    "checklist-not-retrieved": INTERNAL_REVIEW,
    "checklist-not-started": INTERNAL_REVIEW,
    "checklist-item-missing": INTERNAL_REVIEW,
    "checklist-item-unanswered": INTERNAL_REVIEW,
    "checklist-non-reason": INTERNAL_REVIEW,
    "methods-drift": INTERNAL_REVIEW,
    # The same reading kept pair by pair: a step and the text pointing at it.
    "method-pair-unread": INTERNAL_REVIEW,
    "method-step-changed": INTERNAL_REVIEW,
    "method-claim-changed": INTERNAL_REVIEW,
    # A stale build is normal while drafting — you rebuild when you need the document. It
    # stops being normal once the draft is something other people read.
    "document-stale": INTERNAL_REVIEW,
    "document-unstamped": INTERNAL_REVIEW,
    # A pointer to a table or a figure the document does not place, or out of ICMJE's order:
    # tables move and are renumbered while the draft is written (Basile, 2026-10-14).
    "pointer-to-nothing": INTERNAL_REVIEW,
    "cited-out-of-order": INTERNAL_REVIEW,
    "display-not-cited": INTERNAL_REVIEW,
    # A reference list is printed for others to read from the finished draft on. While
    # drafting, an entry can be a placeholder still to be filled in from Zotero.
    "identifier-malformed": INTERNAL_REVIEW,
    "reference-field-missing": INTERNAL_REVIEW,
    # Whether each identifier names the work the entry describes: read from the lookup
    # records, which a draft may not have yet.
    "doi-unregistered": INTERNAL_REVIEW,
    "reference-not-the-work": INTERNAL_REVIEW,
    "reference-title-mismatch": INTERNAL_REVIEW,
    "reference-year-mismatch": INTERNAL_REVIEW,
    "pmid-names-another-work": INTERNAL_REVIEW,
    "pmid-unknown": INTERNAL_REVIEW,
    "lookup-date-future": INTERNAL_REVIEW,
    "lookup-record-unreadable": INTERNAL_REVIEW,
    "lookup-record-misfiled": INTERNAL_REVIEW,
    # One work cited under two keys is printed twice in the reference list.
    "reference-duplicate": INTERNAL_REVIEW,
    # A sentence a person judged the cited work does not support: a draft may hold one while
    # it is reworded, and a draft others read may not (Basile, 2026-10-20).
    "passage-does-not-support": INTERNAL_REVIEW,
    # -- submission -------------------------------------------------------------
    # The panel's verdict is the last thing to bind, because a panel reviews a draft
    # that is otherwise finished.
    # A gate not yet taught LaTeX read nothing of a LaTeX manuscript: a note while it is
    # written, a failure for the version sent anywhere.
    "not-read-in-latex": SUBMISSION,
    "no-review": SUBMISSION,
    "rounds-outstanding": SUBMISSION,
    "review-missing": SUBMISSION,
    "reading-missing": SUBMISSION,
    "point-unanswered": SUBMISSION,
    # A number typed into a reply to the reviewers: the letter is written while the
    # analysis is still being run again, and goes to the journal only at resubmission.
    "reply-unbound-number": SUBMISSION,
    # Words to the reviewers left in the manuscript: G6 warns on them until submission, and
    # fails there on those that answer one reviewer or point at this manuscript.
    "revision-residue": SUBMISSION,
    "response-claims-nothing": SUBMISSION,
    "claimed-change-did-not-happen": SUBMISSION,
            "review-stale": SUBMISSION,
    "open-major-finding": SUBMISSION,
    # A sealed reading whose words changed: a major finding softened or deleted binds
    # nothing any more, so this binds where the major findings do.
    "reading-altered": SUBMISSION,
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
        if declared not in STAGES:
            # The schema reports this too, as a finding, but the stage decides which findings
            # fail, so there is no report to put it in. It was a `ValueError` and a traceback.
            raise ContractError(
                f"{project.root / PAPER_FILE}: `stage` is {declared!r}, which is not a stage; "
                f"write one of {', '.join(STAGES)}"
            )
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
