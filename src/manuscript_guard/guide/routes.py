"""Which skill answers a finding, and which command does the work: `next`'s routing table.

A key is a finding code, or a prefix of codes where it ends in `-`. A code is looked up as
itself first, then by the longest prefix it begins with. A code that neither names goes to
its gate's skill, with `check` (`GATE_SKILLS`): it is never dropped, and the test that every
code the package reports is in this table, or in `NO_ACTION`, says when one is added
without a route (tests/test_guide.py). Where a skill's description says it answers a code,
the code routes to that skill, and a test holds that as well. A code two contracts raise is
told apart by the file its finding names (`route_for`).

`argv` is the command's words after the program's name, the project's folder left out: `next`
puts it where the command takes it. None where the skill does the work and no command does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.literature import ATTESTED_FILE, LEDGER_FILE
from manuscript_guard.findings import Finding
from manuscript_guard.gates.harvested import RECEIPT_CONTEXT


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
           "count-recoverable", "restricted-input-tracked"),
    **_all("data-dictionary", None, "dictionary-", "plan-variable-undefined"),
    **_all("methods-review", None, "similar-", "appraisal-", "adopted-",
           "standard-redescribed"),
    # -- the results ----------------------------------------------------------------------
    **_all("results-binding", _VERIFY, "results-edited", "script-", "input-",
           "analysis-newer", "environment-changed", "no-digest", "no-results",
           "no-results-dir", "rerun-", "dataset-", "data-date-not-declared",
           "synthetic-input-quoted"),
    # An output harvested is taken in again from the file; what the script writes is shown by
    # `verify`, and a site's receipt is the site's to write again (`verify --receipt SITE`).
    **_all("results-binding", ("harvest",), "harvested-output-"),
    **_all("results-binding", _VERIFY, "harvest-declared"),
    **_all("results-binding", None, "receipt-"),
    **_all("results-binding", None, "input-at-site", who="author"),
    **_all("results-binding", _BIND, "unclassified-number", "unresolved-binding",
           "unquoted-result", "typed-", "parameter-unread", "hand-authored-table",
           "value-splits-paragraph", "duplicate-quantity", "malformed-placeholder",
           "code-block-", "raw-block", "tex-in-the-text", "unplaced-table", "divergent-display",
           "figure-number-unbound", "figure-source-", "figure-script-ignores-results",
           "figure-render-unproven", "figure-not-inspectable", "figure-no-text-layer",
           "figure-unreadable", "figure-estimates", "figure-missing", "table-missing",
           "unit-differs-from-emitted", "estimate-outside-interval", "interval-",
           "threshold-undeclared", "prose-as-value", "quoted-alone",
           "project-exemption", "code-list-does-not-match", "composition-does-not-match",
           "unemitted-table-number", "relation-", "flow-broken", "declared-same-",
           "same-as-unresolved", "family-uncorrected", "p-against-interval",
           "ratio-interval-asymmetric", "spread-label-differs", "quality-not-run",
           "entry-unchecked", "rule-unchecked", "manuscript-empty", "p-decision-error",
           "p-inconsistent", "summary-not-reported"),
    # What the results' contract refuses is put right in the script that emits it, so `bind`
    # does nothing for it. The literature's own `duplicate-key` and `no-display` are told
    # apart by the file they name (`route_for`).
    **_all("results-binding", ("check",), "duplicate-key", "duplicate-table", "duplicate-step",
           "duplicate-model", "no-display", "variable-declared-twice", "bound-dangling",
           "bound-duplicated", "bound-uncheckable"),
    **_all("project-setup", ("check",), "front-matter-unreadable"),
    **_all("manuscript-writing", None, "front-matter-abstract"),
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
    # Neither is answered by asking the registries: one is rebuilt from what is cited, the
    # other is put right in Zotero.
    **_all("literature-verify", ("sync-bib",), "reference-uncited"),
    **_all("literature-verify", None, "reference-duplicate", "reference-title-duplicate"),
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
    # A box the journal prints beside the abstract, held to the profile's rule for it, and
    # the graphical abstract it asks for: the skill reads the rule and says what to write.
    **_all("journal-profile", ("check",), "box-", "graphical-abstract-missing"),
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
    # Said by `deposit` itself, which takes a target and a bundle; a custodian signs off.
    **_all("submission-pack", None, "deposit-"),
    **_all("submission-pack", None, "deposit-not-authorised", who="author"),
    # The DOI is put right in paper.yaml, as the receipt has it: not by writing the package
    # again, which `package-` would offer.
    **_all("submission-pack", None, "package-doi-test-prefix", "deposit-doi-differs"),
    **_all("submission-pack", ("build",), "blind-document-names-author"),
    **_all("submission-pack", None, "approval-", who="author"),
    # -- what is said of the paper outside it ---------------------------------------------
    # `communicate check` says these, never `check`: the text, the brief or the graphical
    # abstract is put right and the check run again, as the research-communication skill
    # says. The paper's DOI is asked of Crossref again, and the embargo waited out.
    **_all("research-communication", ("communicate", "check"), "comm-", "brief-"),
    **_all("research-communication", ("lookup", "--paper"), "comm-doi-unknown",
           "comm-doi-title-differs", "comm-doi-not-looked-up"),
    **_all("research-communication", ("communicate", "status"), "comm-embargo"),
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
    # A reviewer's or a co-author's finding left as it stands records who decided
    # (`overridden_by`, the manifest's `decided_by`): the decision is the author's.
    **_all("word-roundtrip", None, "comment-unanswered", who="author"),
    **_all("review-panel", ("review",), "open-major-finding", who="author"),
    **_all("review-panel", ("review", "--design"), "design-major-open", who="author"),
    # A co-author's flag is closed by the text or code put right and their later answer:
    # the author settles it with them, and the recap shows what each flag says.
    **_all("co-author-checking", ("checker", "recap"), "coauthor-flag-open", who="author"),
}

#: The codes whose answer is a person's own attestation, judgement, approval, reading or
#: sign-off, or a decision to leave a finding as it stands: each routes with
#: `who="author"`, and a test holds the list to that.
PERSON_ONLY = frozenset({
    "attestation-not-human", "attestation-thin", "judgement-not-human",
    "similar-decision-not-human", "data-source-not-a-person", "design-override-unsigned",
    "figures-not-seen", "journal-manual-unsigned", "approval-missing", "approval-stale",
    "comment-unanswered", "open-major-finding", "design-major-open",
})  # fmt: skip

#: A code both the literature's contract and the results' raise. The literature's names its
#: ledger or attested.yaml, and is put right there; the results' is put right in the script.
_LITERATURE_FILES = frozenset({LEDGER_FILE, ATTESTED_FILE})
LITERATURE_ROUTES = {
    "duplicate-key": Route("literature-verify", ("check",)),
    "no-display": Route("literature-verify", ("check",)),
}

#: Codes that are only ever said as a note and ask nothing: no action is built for them,
#: and the test that every code is routed takes them as answered.
NO_ACTION = frozenset({"plan-complete", "reference-found", "pointers-unchecked",
                       "tex-not-judged", "tex-words-not-read",
                       # What `compare` says of two versions of someone else's paper, to its
                       # editor or referee: facts in its own report, which `check` and `next`
                       # never see and the author has nothing to do about.
                       *(f"{part}-{what}" for part in ("section", "table", "figure")
                         for what in ("same", "changed", "new", "gone")),
                       "section-moved", "table-not-read", "version-not-numbered",
                       "quotation-unpaired",
                       # And of a version that is a PDF (`auditing.pdf`).
                       "version-pdf", "displays-not-compared"})  # fmt: skip


#: A finding of a run at the site that holds the data: answered there, by a new run and its
#: receipt, which nothing at the centre runs (`gates/harvested.py`).
_AT_SITE = RECEIPT_CONTEXT
SITE_ROUTE = Route("results-binding", None, who="author")


def route_of(code: str) -> Route | None:
    """The route for `code`: its own, else the longest prefix it begins with."""
    if code in ROUTES:
        return ROUTES[code]
    prefixes = [key for key in ROUTES if key.endswith("-") and code.startswith(key)]
    return ROUTES[max(prefixes, key=len)] if prefixes else None


def route_for(finding: Finding) -> Route | None:
    """The route for a finding: the literature's where its code is one the literature and
    the results both raise and it names a literature file, else its code's."""
    if (finding.context or "").startswith(_AT_SITE):
        return SITE_ROUTE
    named = Path(finding.path).name if finding.path is not None else None
    if finding.code in LITERATURE_ROUTES and named in _LITERATURE_FILES:
        return LITERATURE_ROUTES[finding.code]
    return route_of(finding.code)
