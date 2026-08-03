"""G7L — the literature chain, verified rather than trusted.

Every ledger entry carries a verbatim quote and the value it supports. Two questions follow
and both have machine-checkable answers:

1. **Is the quote actually in the stored source?** If not, either the source was replaced
   or the quote was reconstructed from memory. Both are how a number that no paper contains
   ends up cited to a paper.
2. **Is the value actually in the quote?** A quote that does not contain the number it is
   offered as evidence for is not evidence for it.

Together these verify the chain from manuscript to published sentence without anyone
re-reading the paper. That is the strongest thing this toolkit can say about a number it
did not compute.

Attestations are held to a different and stricter rule. An entry in `attested.yaml` says a
*person* read something the toolkit could not, and takes responsibility for it. A language
model cannot do that, so it may not sign one.
"""

from __future__ import annotations

import re

from manuscript_guard.contracts.literature import ABSTRACT_ONLY, ATTESTED, Literature
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.literature.sources import (
    UnreadableSource,
    contains,
    read_source,
    states_value,
)

GATE = "G7"

# A model may draft an attestation for a person to sign; it may not be the signatory.
_MODEL_NAME = re.compile(
    r"\b(claude|gpt|chatgpt|o[1-4]\b|gemini|llama|mistral|copilot|assistant|"
    r"anthropic|openai|deepseek|qwen|grok|ai\b|bot\b|llm\b)",
    re.IGNORECASE,
)


def check_literature_chain(project: Project, literature: Literature) -> Report:
    report = Report()
    root = project.path("literature")
    verified = 0
    unverifiable = 0

    for key, value in sorted(literature.values.items()):
        detail = value.detail or {}

        if value.origin == ATTESTED:
            report = report.merge(_check_attestation(key, value, detail))
            continue

        source_file = detail.get("source_file")
        quote = detail.get("quote", "")
        if not source_file:
            continue

        path = root / source_file
        if not path.exists():
            continue  # already reported as literature-source-missing

        try:
            text = read_source(path)
        except UnreadableSource as exc:
            unverifiable += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="source-unreadable",
                    severity=WARN,
                    message=f"{key}: {exc}",
                    path=value.source,
                    hint="the quote cannot be verified against a source nothing can read",
                )
            )
            continue

        if not contains(text, quote):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="quote-not-in-source",
                    message=f"{key}: the recorded quote does not appear in {source_file}",
                    path=value.source,
                    context=quote[:140],
                    hint="copy the sentence from the source rather than retyping it; if the "
                    "source was replaced, re-extract the value",
                )
            )
            continue

        if not states_value(quote, value.display):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="value-not-in-quote",
                    message=f"{key}: {value.display!r} does not appear in the quote that is "
                    f"offered as evidence for it",
                    path=value.source,
                    context=quote[:140],
                    hint="quote the sentence that states the value, or record the value as "
                    "the source writes it",
                )
            )
            continue

        verified += 1
        if detail.get("depth") == ABSTRACT_ONLY:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="value-from-abstract",
                    severity=INFO,
                    message=f"{key} comes from an abstract, not a full text",
                    path=value.source,
                    hint="fine to keep; worth knowing before it is quoted precisely in the "
                    "Discussion",
                )
            )

    return report.with_counts(
        literature_verified=verified, literature_unverifiable=unverifiable
    )


def _check_attestation(key: str, value, detail: dict) -> Report:
    """An attestation must be signed by a person, and say something."""
    report = Report()
    attester = str(detail.get("attested_by", "")).strip()

    if _MODEL_NAME.search(attester):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="attestation-not-human",
                message=f"{key}: {attester!r} cannot sign an attestation",
                path=value.source,
                hint="attested.yaml records that a person read a source the toolkit could "
                "not retrieve, and takes responsibility for the value. A model may draft "
                "the entry; a named person must sign it",
            )
        )

    statement = str(detail.get("statement", "")).strip()
    if len(statement.split()) < 8:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="attestation-thin",
                severity=WARN,
                message=f"{key}: the attestation says very little",
                path=value.source,
                context=statement[:120],
                hint="say what was read and why it could not be stored, so a reader in two "
                "years can judge the value without asking you",
            )
        )

    return report
