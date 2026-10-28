"""Which skill answers a finding, and which command does the work: `next`'s routing table.

A key is a finding code, or a prefix of codes where it ends in `-`. A code is looked up as
itself first, then by the longest prefix it begins with. A code that neither names goes to
its gate's skill, with `check` (`GATE_SKILLS`): it is never dropped, and the test that every
code the package reports is in this table, or in `NO_ACTION`, says when one is added
without a route (tests/test_guide.py). Where a skill's description says it answers a code,
the code routes to that skill, and a test holds that as well.

`argv` is the command's words after the program's name, the project's folder left out: `next`
puts it where the command takes it. None where the skill does the work and no command does.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    skill: str | None
    argv: tuple[str, ...] | None = None
    who: str = "agent"


#: What stops a gate from checking anything: tier 0.
CANNOT_CHECK = frozenset({"gate-errored", "manuscript-unreadable", "schema-violation",
                          "duplicate-key"})  # fmt: skip

#: The gates upstream first: what the others rest on, then what they read.
GATE_RANK = ("G0", "G1", "G12", "G2", "G3", "G7", "G8", "G8r", "G5", "G16", "G9", "G15",
             "G10", "G4", "G14", "G6", "G13", "G11", "BUILD")  # fmt: skip

#: The skill of each gate, for a code no route names: coarser than a code's own.
GATE_SKILLS = {
    "G0": "project-setup", "G1": "results-binding", "G2": "results-binding",
    "G3": "results-binding", "G4": "journal-profile", "G5": "reporting-checklist",
    "G6": "manuscript-writing", "G7": "literature-verify", "G8": "results-binding",
    "G8r": "reporting-checklist", "G9": "methods-writer", "G10": "figure-review",
    "G11": "review-panel", "G12": "analysis-plan", "G13": "reviewer-response",
    "G14": "manuscript-writing", "G15": "methods-writer", "G16": "results-binding",
    "BUILD": "project-setup", "REWORDED": "manuscript-writing", "PACKAGE": "submission-pack",
    "VERIFY": "results-binding",
}  # fmt: skip


def _all(skill: str | None, argv: tuple[str, ...] | None, *keys: str, who: str = "agent"
         ) -> dict[str, Route]:  # fmt: skip
    route = Route(skill, argv, who)
    return dict.fromkeys(keys, route)


_VERIFY = ("verify",)
_BIND = ("bind",)

ROUTES: dict[str, Route] = {
    # -- what stops a gate --------------------------------------------------------------
    **_all("project-setup", ("check",), "gate-errored", "manuscript-unreadable",
           "schema-violation", "authors-incomplete", "two-formats", "other-format-file",
           "not-read-in-latex", "tex-", "pandoc-warning", "record-not-written",
           "rule-opens-a-block", "unclear-comment", "unclear-fence", "two-titles"),
    # -- the plan, the data and the design ----------------------------------------------
    **_all("analysis-plan", None, "no-analysis-plan", "plan-", "planned-", "feasibility-not-run",
           "not-in-dictionary", "registration-"),
    **_all("data-sources", None, "data-source-", "data-sources-schema",
           "custodian-rule-undeclared", "plan-source-unnamed", "data-statement-source-unnamed",
           "data-statement-route-differs", "dataset-not-chosen", "count-below-minimum",
           "restricted-input-tracked"),
    **_all("data-dictionary", None, "dictionary-", "plan-variable-undefined"),
    **_all("methods-review", None, "similar-", "appraisal-", "adopted-",
           "standard-redescribed"),
    # -- the results ----------------------------------------------------------------------
    **_all("results-binding", _VERIFY, "results-edited", "script-", "input-",
           "analysis-newer", "environment-changed", "no-digest", "no-results",
           "no-results-dir", "rerun-", "dataset-", "data-date-not-declared",
           "synthetic-input-quoted"),
    **_all("results-binding", _BIND, "unclassified-number", "unresolved-binding",
           "unquoted-result", "typed-", "parameter-unread", "hand-authored-table",
           "value-splits-paragraph", "duplicate-quantity", "malformed-placeholder",
           "code-block-", "raw-block", "tex-in-the-text", "unplaced-table", "divergent-display",
           "figure-number-unbound", "figure-source-", "figure-script-ignores-results",
           "figure-render-unproven", "figure-not-inspectable", "figure-no-text-layer",
           "figure-unreadable", "figure-estimates", "figure-missing", "table-missing",
           "bound-", "unit-differs-from-emitted", "estimate-outside-interval", "interval-",
           "threshold-undeclared", "prose-as-value", "quoted-alone", "front-matter-",
           "project-exemption", "code-list-does-not-match", "composition-does-not-match",
           "unemitted-table-number", "relation-", "flow-broken", "declared-same-",
           "same-as-unresolved", "family-uncorrected", "p-against-interval",
           "ratio-interval-asymmetric", "spread-label-differs", "duplicate-", "no-display",
           "variable-declared-twice", "quality-not-run", "entry-unchecked", "rule-unchecked",
           "manuscript-empty", "p-decision-error", "p-inconsistent", "summary-not-reported"),
    **_all("results-binding", ("bind", "--pointers"), "pointer-", "display-not-cited",
           "cited-out-of-order", "ref-number-unknown", "caption-names-another"),
    **_all("results-binding", ("values",), "values-file-", "value-not-printable"),
    **_all(None, ("build",), "document-stale", "document-unstamped"),
    # -- the prose ------------------------------------------------------------------------
    **_all("manuscript-writing", None, "ai-", "vague-attribution", "model-artefact",
           "revision-residue", "abbreviation-", "term-avoided", "vocabulary-conflict",
           "spelling-", "notation-", "recycled-", "earlier-output-not-compared", "no-headings",
           "fact-", "order-changed", "sign-lost", "sign-moved", "sign-new", "sign-unsure",
           "claim-", "file-lost", "file-new"),
    **_all("methods-writer", ("methods",), "methods-", "method-", "quality-not-reported"),
    **_all("methods-writer", ("models",), "model-", "models-on-different-rows", "variable-",
           "typed-model-kind", "poisson-binary-variance", "unit-rows-independent"),
    # -- the literature -------------------------------------------------------------------
    **_all("literature-verify", None, "literature-source-missing", "quote-",
           "value-not-in-quote", "quotation-", "statements-without-passage",
           "judgement-not-human", "attestation-", "source-unreadable", "unused-literature",
           "value-from-abstract", "no-reference-source", "zotero-unreadable",
           "pinning-unchecked", "no-live-citations", "citation-"),
    **_all("literature-verify", ("passages",), "passage-"),
    **_all("literature-verify", ("lookup",), "reference-", "lookup-", "doi-unregistered",
           "pmid-", "preprint-", "pages-placeholder", "identifier-malformed"),
    **_all("related-outputs", ("related",), "related-"),
    # -- figures --------------------------------------------------------------------------
    **_all("figure-review", None, "figure-unreviewed", "figure-review-", "figure-alt-"),
    **_all("figure-design", ("palettes",), "figure-colours-", "figure-greyscale-confused",
           "figure-file-size", "figure-font-", "figure-format", "figure-height",
           "figure-resolution", "figure-shrinks", "figure-text-clipped", "figure-text-small",
           "figure-line-thin", "legend-words"),
    # -- the journal and the checklist ----------------------------------------------------
    **_all("journal-profile", ("journal",), "journal-", "no-journal-chosen",
           "over-journal-limit", "near-journal-limit", "missing-", "abstract-headings-missing",
           "abstract-not-found", "data-statement-forbidden", "data-identifier-missing",
           "data-link-temporary", "data-doi-uncited", "pointer-form-unread", "english-variant-",
           "shortlist-", "latex-"),
    **_all("journal-profile", ("style",), "journal-style-"),
    **_all("reporting-checklist", ("checklist",), "checklist-", "guideline-",
           "reporting-guideline-for-design"),
    # -- the panel, the co-authors and the journal's reviewers -----------------------------
    **_all("review-panel", ("review",), "no-review", "review-", "reading-",
           "open-major-finding", "rounds-outstanding", "round-", "duplicate-reader",
           "duplicate-reading", "duplicate-reviewer", "figures-not-seen",
           "provider-not-authorised"),
    **_all("review-panel", ("review", "--design"), "design-"),
    **_all("reviewer-response", ("respond",), "point-unanswered", "claimed-change-",
           "anchor-unrecorded", "quoted-text-", "response-", "reply-unbound-number"),
    **_all("word-roundtrip", None, "comment-unanswered", "comments-", "docx-unreadable"),
    # -- what is sent ---------------------------------------------------------------------
    **_all("submission-pack", ("package",), "package-"),
    **_all("submission-pack", ("build",), "blind-document-names-author"),
    **_all("submission-pack", None, "approval-", who="author"),
    # -- what only a named person may do ----------------------------------------------------
    # Last, so that each overrides its prefix: an agent may draft, and only the person the
    # hint names signs, judges, attests, approves or reads. An agent that wrote the name
    # would pass the gate with no person behind it.
    **_all("literature-verify", None, "attestation-not-human", "attestation-thin",
           "judgement-not-human", who="author"),
    **_all("methods-review", None, "similar-decision-not-human", who="author"),
    **_all("data-sources", None, "data-source-not-a-person", who="author"),
    **_all("review-panel", None, "design-override-unsigned", "figures-not-seen", who="author"),
    **_all("journal-profile", None, "journal-manual-unsigned", who="author"),
}

#: The codes whose answer is a person's own attestation, judgement, approval, reading or
#: sign-off: each routes with `who="author"`, and a test holds the list to that.
PERSON_ONLY = frozenset({
    "attestation-not-human", "attestation-thin", "judgement-not-human",
    "similar-decision-not-human", "data-source-not-a-person", "design-override-unsigned",
    "figures-not-seen", "journal-manual-unsigned", "approval-missing", "approval-stale",
})  # fmt: skip

#: Codes that are only ever said as a note and ask nothing: no action is built for them,
#: and the test that every code is routed takes them as answered.
NO_ACTION = frozenset({"plan-complete", "reference-found", "pointers-unchecked",
                       "tex-not-judged", "tex-words-not-read"})  # fmt: skip


def route_of(code: str) -> Route | None:
    """The route for `code`: its own, else the longest prefix it begins with."""
    if code in ROUTES:
        return ROUTES[code]
    prefixes = [key for key in ROUTES if key.endswith("-") and code.startswith(key)]
    return ROUTES[max(prefixes, key=len)] if prefixes else None
