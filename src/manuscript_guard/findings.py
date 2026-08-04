"""The single reporting vocabulary shared by every gate.

Gates never print and never exit. They return findings, and the caller decides what a
finding means. That keeps each gate testable in isolation and lets the CLI, a hook and a
CI job present the same result three different ways.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

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

    def located(self) -> str:
        if self.path is None:
            return "-"
        where = str(self.path)
        if self.line is not None:
            where += f":{self.line}"
            if self.col is not None:
                where += f":{self.col}"
        return where

    def as_dict(self) -> dict:
        out = asdict(self)
        out["path"] = None if self.path is None else str(self.path)
        return out


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

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "counts": self.counts,
                "findings": [f.as_dict() for f in self.sorted().findings],
            },
            indent=2,
            # Escaped rather than literal. The machine-readable channel gets piped, and a
            # pipe on Windows is cp1252 — a literal em dash in a message killed `print`
            # with UnicodeEncodeError mid-document, handing the caller truncated JSON and
            # exit 2. `—` parses back to the same character everywhere.
            ensure_ascii=True,
        )

    def render(self, root: Path | None = None) -> str:
        lines: list[str] = []
        for finding in self.sorted().findings:
            where = finding.located()
            if root is not None and finding.path is not None:
                try:
                    rel = finding.path.relative_to(root)
                    where = where.replace(str(finding.path), str(rel), 1)
                except ValueError:
                    pass
            lines.append(f"  [{finding.severity.upper():4}] {finding.gate} {where}")
            lines.append(f"         {finding.message}")
            if finding.context:
                lines.append(f"         > {finding.context}")
            if finding.hint:
                lines.append(f"         hint: {finding.hint}")
        if self.counts:
            lines.append("  " + "  ".join(f"{k}={v}" for k, v in sorted(self.counts.items())))
        return "\n".join(lines) if lines else "  (nothing to report)"


def merge_all(reports: list[Report]) -> Report:
    out = Report()
    for report in reports:
        out = out.merge(report)
    return out
