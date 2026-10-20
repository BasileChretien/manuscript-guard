"""G11, for the comments co-authors leave in Word: each is answered, or it is reported.

`import` files every comment of a returned document as a finding, in a record of its own
kind under `review/comments/` (`filed_comments`). Here each record is read, and a finding
with neither a `resolution` nor an `overridden` reason is reported, whatever its severity:
a warning while the paper is written, a failure in `check --submission`. The author chose
that on 2026-10-20: a co-author's note left unanswered at submission is what filing them is
for, and one line answers a remark that needs nothing done.

A comment made on a paragraph that has changed since is said to be, so that one the change
may have answered is told apart from one nobody looked at. The paragraph is found by its
text, as G13 finds a reviewer's (`revision._passages`): a paragraph added above it since
moves its identifier, and its text is still there. That is information and never an answer:
the author still says what was done.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.filed_comments import made_on
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.text.shown import one_line

GATE = "G11"
#: How much of a comment a finding shows.
SHOWN = 120
#: What is shown of a comment with no words: a picture alone, or an empty comment.
NO_WORDS = "(no words: a picture, or nothing Word keeps as text)"


def _answered(finding: dict) -> bool:
    return bool(
        str(finding.get("resolution", "")).strip() or str(finding.get("overridden", "")).strip()
    )


def check_comments(project, *, submission: bool = False) -> Report:
    """Every filed comment that is not answered, and every record that cannot be counted."""
    from manuscript_guard.filed_comments import records, words_digest
    from manuscript_guard.gates.revision import _passages

    severity = FAIL if submission else WARN
    report = Report()
    filed = unanswered = 0
    passages: set[str] | None = None
    for path in records(project):
        document, problems = _read(path)
        report = report.merge(problems)
        if document is None:
            continue
        if words_digest(document) != document.get("words_sha256"):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="comments-altered",
                    severity=severity,
                    message=f"{_who(path, document)}: the comments record has been changed "
                    "since it was filed",
                    path=path,
                    hint="the seal covers what the commenter wrote: each finding's words, "
                    "place and replies, and the findings themselves. Put them back as they "
                    "were (`git diff` shows what changed), and answer a comment in "
                    "`resolution:` or `overridden:` instead",
                )
            )
        for finding in document["findings"]:
            filed += 1
            if _answered(finding):
                continue
            unanswered += 1
            if passages is None and finding.get("paragraph_sha256"):
                try:
                    passages = _passages(project)
                except ContractError:
                    # A manuscript file that cannot be read is reported once, by
                    # `check`; the comments are reported all the same, and whether
                    # their paragraphs changed is not said.
                    passages = frozenset()
            report = report.with_findings(_unanswered(path, document, finding, passages,
                                                      severity))  # fmt: skip
    return report.with_counts(review_comments=filed, review_comments_open=unanswered)


def _read(path: Path) -> tuple[dict | None, Report]:
    try:
        document = read_structured(path)
    except (ContractError, OSError, ValueError, RecursionError):
        return None, Report().with_findings(
            Finding(
                gate=GATE,
                code="comments-unreadable",
                message=f"{path.parent.name}/{path.name} cannot be read as a comments record",
                path=path,
                hint="while it cannot be parsed none of its comments is counted, its "
                "unanswered ones included. It must be UTF-8 YAML; a value that holds a colon "
                "and a space needs quotes: resolution: 'Done: it now says reporting'",
            )
        )
    schema_report = validate(document, "comments", path, gate=GATE)
    if not schema_report.ok or not isinstance(document, dict):
        return None, schema_report
    return document, schema_report


def _who(path: Path, document: dict) -> str:
    return f"{one_line(str(document['commenter']), 60)} ({path.parent.name})"


def _unanswered(path: Path, document: dict, finding: dict, passages, severity: str) -> Finding:
    notes = []
    # `passages` is a frozenset where the manuscript could not be read, and says nothing.
    known = isinstance(passages, set)
    if known and finding.get("paragraph_sha256") and finding["paragraph_sha256"] not in passages:
        notes.append("the paragraph has changed since")
    if finding.get("unmatched"):
        notes.append("made on a paragraph not matched to the source when it was filed")
    if finding.get("resolved_in_word"):
        notes.append("resolved in Word")
    on = made_on(finding["block"])
    on += f" {finding['where']}" if finding.get("where") else ""
    said = f"  [{'; '.join(notes)}]" if notes else ""
    anchored = finding.get("anchored") or ""
    words = one_line(finding["finding"], SHOWN) or NO_WORDS
    return Finding(
        gate=GATE,
        code="comment-unanswered",
        severity=severity,
        message=f"{_who(path, document)} {finding['id']}, {on}: {words}{said}",
        path=path,
        context=f"made on: {one_line(anchored, 140)}" if anchored else None,
        hint="answer it in this record: what was done in `resolution` (with `resolved_on`), "
        "or why it is left in `overridden`, with who decided in `overridden_by`. A reply in "
        "Word, or Word's Resolve, is not an answer: neither says what was done",
    )


__all__ = ["GATE", "check_comments"]
