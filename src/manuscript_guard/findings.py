"""The single reporting vocabulary shared by every gate.

Gates never print and never exit. They return findings, and the caller decides what a
finding means. That keeps each gate testable in isolation and lets the CLI, a hook and a
CI job present the same result three different ways.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from manuscript_guard.keys import Keyed, keyed_json
from manuscript_guard.keys import key as key_of

FAIL = "fail"
WARN = "warn"
INFO = "info"

_ORDER = {FAIL: 0, WARN: 1, INFO: 2}


@dataclass(frozen=True)
class Finding:
    """One problem, located as precisely as the gate can manage.

    `hint` is not decoration. A gate that reports "unclassified number" without saying
    what the author should do about it converts a useful check into an obstacle, and
    obstacles get switched off.
    """

    gate: str
    code: str
    message: str
    severity: str = FAIL
    path: Path | None = None
    line: int | None = None
    col: int | None = None
    context: str | None = None
    hint: str | None = None
    #: What the finding is about, the sentence it stands in and its offset there, which make
    #: its key in `--json` (`keys`): never compared, so that two findings alike but for
    #: them are one, as they were.
    subject: str | None = field(default=None, compare=False, repr=False)
    sentence: str | None = field(default=None, compare=False, repr=False)
    at: int | None = field(default=None, compare=False, repr=False)

    def located(self) -> str:
        if self.path is None:
            return "-"
        where = str(self.path)
        if self.line is not None:
            where += f":{self.line}"
            if self.col is not None:
                where += f":{self.col}"
        return where

    @property
    def question(self) -> bool:
        """Whether it is a question to the author (`Question`), which no other finding is."""
        return False

    def keyed(self) -> Keyed:
        """What its key is made of (`keys.Keyed`)."""
        return Keyed(self.gate, self.code, self.subject, self.sentence, self.at, self.context,
                     self.message)  # fmt: skip

    @property
    def key(self) -> str:
        """Its key, with no ordinal: `keys.assign` gives that among the findings of a run."""
        return key_of(self.keyed())

    def as_dict(self) -> dict:
        out = {name: value for name, value in asdict(self).items()
               if name not in ("subject", "sentence", "at")}  # fmt: skip
        out["path"] = None if self.path is None else str(self.path)
        return keyed_json([self.keyed()], [out])[0]


@dataclass(frozen=True)
class Question(Finding):
    """A question to the author: what a gate saw where no exact rule can decide, one question,
    and the answer that ends it. It never fails and is never counted as a warning, so it
    changes no exit code at any stage: a note (INFO), which `--json` marks
    `"question": true` and the text shows apart, under `QUESTIONS` (Basile, 2026-11-16,
    decisions 27 and 30). The stage leaves it as it is: `policy.apply_stage` moves only
    failures."""

    severity: str = INFO

    @property
    def question(self) -> bool:
        return True

    def as_dict(self) -> dict:
        return {**super().as_dict(), "question": True}


#: The heading the text puts the questions to the author under, apart from the findings.
QUESTIONS = "Questions for the author (they never fail, and are not counted as warnings):"


@dataclass(frozen=True)
class Report:
    """An immutable collection of findings, plus counters a gate wants on the record.

    `counts` carries the denominators that make a pass meaningful: "0 unclassified out of
    412 numeric tokens examined" is a result, while "0 unclassified" alone is compatible
    with having examined nothing.
    """

    findings: tuple[Finding, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == FAIL)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == WARN)

    @property
    def ok(self) -> bool:
        return not self.failures

    def with_findings(self, *findings: Finding) -> Report:
        return replace(self, findings=self.findings + findings)

    def with_counts(self, **counts: int) -> Report:
        return replace(self, counts={**self.counts, **counts})

    def merge(self, other: Report) -> Report:
        merged = dict(self.counts)
        for key, value in other.counts.items():
            merged[key] = merged.get(key, 0) + value
        return Report(self.findings + other.findings, merged)

    def sorted(self) -> Report:
        return replace(
            self,
            findings=tuple(
                sorted(
                    self.findings,
                    key=lambda f: (_ORDER.get(f.severity, 9), str(f.path or ""), f.line or 0),
                )
            ),
        )

    def to_json(self, *, stage: str | None = None, assurance: list[str] | None = None) -> str:
        """The report as `check --json` prints it. `check` adds the stage it held the
        manuscript to and the lines its text output ends with, so that a report kept apart
        from its run, a CI job's artefact, says both. Never the tool's version: the reading
        of `check` in tests/readings.py compares this whole, and would differ on every
        release."""
        said: dict = {"ok": self.ok}
        if stage is not None:
            said["stage"] = stage
        said["counts"] = self.counts
        found = self.sorted().findings
        said["findings"] = keyed_json([f.keyed() for f in found], [f.as_dict() for f in found])
        if assurance is not None:
            said["assurance"] = assurance
        return json.dumps(
            said,
            indent=2,
            # Escaped rather than literal. The machine-readable channel gets piped, and a
            # pipe on Windows is cp1252 — a literal em dash in a message killed `print`
            # with UnicodeEncodeError mid-document, handing the caller truncated JSON and
            # exit 2. `—` parses back to the same character everywhere.
            ensure_ascii=True,
        )

    def render(self, root: Path | None = None) -> str:
        """The findings, failures first, a few lines each; then the questions to the author,
        apart, under `QUESTIONS`; then the counts."""
        lines: list[str] = []
        found = self.sorted().findings
        for finding in found:
            if not finding.question:
                lines += _rendered(finding, root)
        asked = [finding for finding in found if finding.question]
        if asked:
            lines += ["", QUESTIONS] if lines else [QUESTIONS]
            for finding in asked:
                lines += _rendered(finding, root)
        if self.counts:
            lines.append("  " + "  ".join(f"{k}={v}" for k, v in sorted(self.counts.items())))
        return "\n".join(lines) if lines else "  (nothing to report)"


def _rendered(finding: Finding, root: Path | None) -> list[str]:
    """One finding as `Report.render` prints it: its severity, gate and place, its message,
    its context and its hint."""
    where = finding.located()
    if root is not None and finding.path is not None:
        try:
            rel = finding.path.relative_to(root)
            where = where.replace(str(finding.path), str(rel), 1)
        except ValueError:
            pass
    lines = [f"  [{finding.severity.upper():4}] {finding.gate} {where}",
             f"         {finding.message}"]  # fmt: skip
    if finding.context:
        lines.append(f"         > {finding.context}")
    if finding.hint:
        lines.append(f"         hint: {finding.hint}")
    return lines


def merge_all(reports: list[Report]) -> Report:
    out = Report()
    for report in reports:
        out = out.merge(report)
    return out
