"""Re-running the analysis and comparing what comes out.

Every other check on `results/` asks whether the file has been *disturbed*. That is a
question about a digest, and a digest can be recomputed: edit a fragment, run `sha256sum`
into the sidecar, and G1 sees nothing. The same is true one level up — change the input data
and rewrite the declared input hash in the same file it protects. The integrity checks
detect accident and drift, which is what they were built for, and an author willing to spend
thirty seconds walks past them.

This asks a different question: **does the analysis still produce these numbers?** A digest
can be forged. A result cannot be forged into existence — either the code emits it or it
does not. So the analysis is re-run into a scratch directory and the fragments are compared
value by value.

Deliberately a separate command rather than part of `check`. It executes the project's own
code, which `check` must never do — a gate that runs arbitrary code cannot be run on a
manuscript someone sent you. And it is slow, in proportion to the analysis rather than to
the manuscript.

What it cannot do is make a non-deterministic analysis agree with itself. A simulation
without a seed, a bootstrap, a model with a random start: those differ every run and the
report says so rather than calling them tampering. Setting a seed is the fix, and it is a
thing worth being told about anyway.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.findings import FAIL, WARN, Finding, Report

GATE = "VERIFY"

# How to run an analysis, by suffix. R is invoked through Rscript rather than R CMD BATCH so
# that a non-zero exit is a non-zero exit.
RUNNERS: dict[str, list[str]] = {
    ".py": [sys.executable],
    ".r": ["Rscript", "--vanilla"],
    ".rmd": ["Rscript", "--vanilla", "-e", "rmarkdown::render(commandArgs(TRUE)[1])"],
    ".qmd": ["quarto", "render"],
}

TIMEOUT = 1800


class VerifyError(Exception):
    """The verification could not be run at all."""


@dataclass
class Comparison:
    """What one fragment's re-run produced, against what is on disk."""

    fragment: str
    ran: bool = True
    agreed: tuple[str, ...] = ()
    differed: tuple[tuple[str, object, object], ...] = ()
    only_on_disk: tuple[str, ...] = ()
    only_on_rerun: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.ran and not (self.differed or self.only_on_disk or self.only_on_rerun)


@dataclass
class VerifyReport:
    comparisons: list[Comparison] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.comparisons)


def runner_for(script: Path) -> list[str] | None:
    """The command that runs this script, or None when nothing here knows how."""
    template = RUNNERS.get(script.suffix.lower())
    if template is None:
        return None
    if shutil.which(template[0]) is None and template[0] != sys.executable:
        return None
    return template


def _values_of(document: dict) -> dict[str, object]:
    """Value and display for every key, which is what a claim actually rests on."""
    out: dict[str, object] = {}
    for key, spec in document.get("values", {}).items():
        out[key] = (spec.get("value"), spec.get("display"))
    for key, spec in document.get("tables", {}).items():
        out[f"<table {key}>"] = [list(row) for row in spec.get("rows", [])]
    return out


def _run(script: Path, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    command = [*runner_for(script), str(script)]  # type: ignore[misc]
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, check=False, env=env
    )


def verify(project, *, only: list[str] | None = None) -> VerifyReport:
    """Re-run each analysis into a copy of the project and compare the fragments.

    The copy is what makes this safe to run on a project you care about: the analysis writes
    into the scratch tree, and the real `results/` is never touched. It also means an
    analysis that reads a relative path still finds its data.
    """
    root = Path(project.root)
    results_dir = project.path("results")
    fragments = sorted(results_dir.glob("*.json")) if results_dir.exists() else []
    if not fragments:
        raise VerifyError(f"no results fragments in {results_dir}")

    report = VerifyReport()
    with tempfile.TemporaryDirectory(prefix="manuscript-guard-verify-") as scratch:
        work = Path(scratch) / root.name
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("build", ".git"))
        # Emptied rather than left in place, so a script that fails to write is not silently
        # compared against the copy of the file it was meant to produce.
        for stale in (work / results_dir.relative_to(root)).glob("*"):
            stale.unlink()

        env = {**os.environ, "MANUSCRIPT_GUARD_VERIFY": "1", "PYTHONDONTWRITEBYTECODE": "1"}

        for fragment in fragments:
            on_disk = json.loads(fragment.read_text(encoding="utf-8"))
            named = on_disk.get("provenance", {}).get("generated_by")
            if only and fragment.stem not in only:
                continue
            if not named:
                report.skipped.append((fragment.name, "no generated_by in its provenance"))
                continue

            script = work / named
            if not script.exists():
                report.comparisons.append(
                    Comparison(fragment.name, ran=False, error=f"{named} does not exist")
                )
                continue
            if runner_for(script) is None:
                report.skipped.append(
                    (fragment.name, f"no runner for {script.suffix} on this machine")
                )
                continue

            try:
                finished = _run(script, work, env)
            except (OSError, subprocess.SubprocessError) as exc:
                report.comparisons.append(
                    Comparison(fragment.name, ran=False, error=f"{named} could not run: {exc}")
                )
                continue
            if finished.returncode != 0:
                tail = (finished.stderr or finished.stdout or "").strip()[-400:]
                report.comparisons.append(
                    Comparison(
                        fragment.name,
                        ran=False,
                        error=f"{named} exited {finished.returncode}\n{tail}",
                    )
                )
                continue

            produced = work / fragment.relative_to(root)
            if not produced.exists():
                report.comparisons.append(
                    Comparison(
                        fragment.name,
                        ran=False,
                        error=f"{named} ran but wrote no {fragment.name}",
                    )
                )
                continue

            report.comparisons.append(
                _compare(fragment.name, on_disk, json.loads(produced.read_text(encoding="utf-8")))
            )

    return report


def _compare(name: str, on_disk: dict, rerun: dict) -> Comparison:
    before, after = _values_of(on_disk), _values_of(rerun)
    agreed, differed = [], []
    for key in sorted(set(before) & set(after)):
        if before[key] == after[key]:
            agreed.append(key)
        else:
            differed.append((key, before[key], after[key]))
    return Comparison(
        fragment=name,
        agreed=tuple(agreed),
        differed=tuple(differed),
        only_on_disk=tuple(sorted(set(before) - set(after))),
        only_on_rerun=tuple(sorted(set(after) - set(before))),
    )


def to_report(result: VerifyReport) -> Report:
    """The findings, in the same shape every gate produces."""
    report = Report()
    for comparison in result.comparisons:
        if not comparison.ran:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="rerun-failed",
                    message=f"{comparison.fragment}: {comparison.error}",
                    hint="an analysis that cannot be re-run cannot be verified; that is "
                    "worth knowing regardless of whether anything was tampered with",
                )
            )
            continue
        for key, was, now in comparison.differed:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="rerun-differs",
                    severity=FAIL,
                    message=f"{comparison.fragment}: {key} is {was!r} on disk, but re-running "
                    f"the analysis produced {now!r}",
                    hint="either the fragment was edited after it was written, or the "
                    "analysis is not deterministic — set a seed and try again",
                )
            )
        for key in comparison.only_on_disk:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="rerun-missing-value",
                    message=f"{comparison.fragment}: {key} is on disk but the re-run did not "
                    f"produce it",
                    hint="a value the analysis does not emit did not come from the analysis",
                )
            )
        for key in comparison.only_on_rerun:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="rerun-extra-value",
                    severity=WARN,
                    message=f"{comparison.fragment}: the re-run produced {key}, which is not "
                    f"on disk",
                    hint="the fragment on disk is older than the analysis; re-run it",
                )
            )
    return report.with_counts(
        fragments_rerun=len(result.comparisons),
        values_reproduced=sum(len(c.agreed) for c in result.comparisons),
        fragments_skipped=len(result.skipped),
    )


def render(result: VerifyReport, root: Path) -> str:
    lines = [to_report(result).render(root)]
    for name, why in result.skipped:
        lines.append(f"  [SKIP] {name}: {why}")
    reproduced = sum(len(c.agreed) for c in result.comparisons)
    total = reproduced + sum(len(c.differed) for c in result.comparisons)
    lines.append("")
    if total:
        lines.append(f"{reproduced}/{total} values reproduced by re-running the analysis.")
    if result.skipped:
        lines.append(
            f"{len(result.skipped)} fragment(s) not verified. Nothing was checked for those, "
            f"which is different from their having passed."
        )
    return "\n".join(lines)


__all__ = ["Comparison", "VerifyError", "VerifyReport", "render", "to_report", "verify"]
