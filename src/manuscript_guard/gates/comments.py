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

import re
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.filed_comments import SUPPLEMENTARY, made_on
from manuscript_guard.filed_comments import _digest as digest_of
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
    places = _Places(project)
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
                                                      severity, places))  # fmt: skip
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


class _Places:
    """Where in the manuscript a comment's paragraph is now, for a finding to name it as the
    author finds it: a file and a line. The source files are read once, at the first comment
    that asks (`_passages` reads them once more, for whether a paragraph changed)."""

    def __init__(self, project) -> None:
        self.project = project
        self._read: list[tuple[Path, str, int, bool, list]] | None = None

    def _files(self) -> list[tuple[Path, str, int, bool, list]]:
        """Each source file: its path, its text, where its body starts past the front
        matter, whether it is the supplement's, and its tagged paragraphs."""
        if self._read is None:
            from manuscript_guard.gates.numbers import is_supplementary
            from manuscript_guard.roundtrip import _body, _sources, identified

            root = self.project.path("manuscript")
            try:
                self._read = [
                    (path, raw, len(raw) - len(_body(raw)), is_supplementary(root, path),
                     identified(raw, relative))
                    for path, relative, raw in _sources(self.project)
                ]  # fmt: skip
            except (ContractError, OSError, UnicodeDecodeError):
                self._read = []
        return self._read

    def of(self, finding: dict, supplementary: bool) -> str:
        """" in manuscript/main.md, line 34" for the paragraph the comment was made on, in
        the comment's own document (the paper or its supplement). The paragraph its
        identifier names, where it still has the digest filed with the comment; else the
        one paragraph with that digest, where only one has it; else, where the commented
        words stand once in the document's body, the paragraph its identifier names if they
        are in it, or the line they are on. Empty where none of these holds: two paragraphs
        that read the same, or words that stand twice, are not guessed between."""
        files = [entry for entry in self._files() if entry[3] == supplementary]
        paragraphs = {name: (path, raw, text, start) for path, raw, _body, _supp, tagged in files
                      for name, text, start in tagged}  # fmt: skip
        digest = finding.get("paragraph_sha256")
        named = paragraphs.get(finding.get("where") or "")
        if digest and named and digest_of(named[2]) == digest:
            return self._line(named[0], named[1], named[3])
        same = [entry for entry in paragraphs.values() if digest and digest_of(entry[2]) == digest]
        if len(same) == 1:
            return self._line(same[0][0], same[0][1], same[0][3])
        # "text" has no paragraph in the source, the title above all: its words are quoted,
        # since where else the body holds them is not where it is (round 2 of #511).
        anchored = _plain(finding.get("anchored") or "") if finding["block"] != "text" else ""
        found = [(path, raw, at) for path, raw, body, _supp, _tagged in files
                 for at in _plain_finds(raw, anchored, body)] if anchored else []  # fmt: skip
        if len(found) != 1:
            return ""
        path, raw, at = found[0]
        if named and named[0] == path and named[3] <= at < named[3] + len(named[2]):
            return self._line(path, raw, named[3])
        return self._line(path, raw, at)

    def _line(self, path: Path, raw: str, start: int) -> str:
        try:
            shown = path.relative_to(self.project.root).as_posix()
        except ValueError:
            shown = path.name
        return f" in {shown}, line {raw.count(chr(10), 0, start) + 1}"


def _plain(text: str) -> str:
    """Words as they are compared with the source: the mark of a cut taken off, every run of
    white space one space."""
    return " ".join(text.removesuffix(" [...]").split())


def _plain_finds(raw: str, words: str, body: int) -> list[int]:
    """Where in `raw`, past `body`, the words stand, line breaks and runs of spaces read as
    one space."""
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words.split()))
    return [found.start() for found in pattern.finditer(raw, body)]


def _unanswered(path: Path, document: dict, finding: dict, passages, severity: str,
                places: _Places) -> Finding:  # fmt: skip
    notes = []
    # `passages` is a frozenset where the manuscript could not be read, and says nothing.
    known = isinstance(passages, set)
    if known and finding.get("paragraph_sha256") and finding["paragraph_sha256"] not in passages:
        notes.append("the paragraph has changed since")
    if finding.get("unmatched"):
        notes.append("made on a paragraph not matched to the source when it was filed")
    if finding.get("resolved_in_word"):
        notes.append("resolved in Word")
    anchored = finding.get("anchored") or ""
    # Where it is, as the author finds it: a file and a line, or the words it was made on.
    # The paragraph's identifier, `mg-p-main3f2a1c-34`, is found in no file the author opens.
    plain = _plain(anchored)
    at = f', at the words "{one_line(plain, 60)}"' if plain else ""
    supplementary = document.get("document") == SUPPLEMENTARY
    on = made_on(finding["block"]) + (places.of(finding, supplementary) or at)
    said = f"  [{'; '.join(notes)}]" if notes else ""
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
