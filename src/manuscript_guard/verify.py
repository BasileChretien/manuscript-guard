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

**And it cannot hide from the code it runs.** An adversarial review made this concrete: the
scratch run once announced itself twice over, through a `MANUSCRIPT_GUARD_VERIFY` variable
in the environment and through the literal string `manuscript-guard-verify-` in the temp
directory name. Either was enough for two lines in an analysis to copy a stashed fragment
into place under verification and compute honestly the rest of the time — 17/17 reproduced,
exit 0, over a manuscript whose headline estimate was invented. Both signals are gone, and
neither should come back.

That removes the easy tells, not the possibility. A script can still read `__file__`, notice
it is somewhere under the system temp directory, and behave differently; short of running
the analysis in a sandbox that lies about the filesystem, it always could. So the honest
statement of what this command proves is:

> Re-running the analysis produced these numbers. If the analysis is written to detect that
> it is being re-run, this proves nothing.

That is still far stronger than a digest, which can be recomputed by anyone who can edit the
file, and it is the difference between an author who edited a results file and an author who
wrote code to deceive their own toolkit. It does not reach the second.
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
        return bool(self.comparisons) and all(c.ok for c in self.comparisons)

    @property
    def verified_nothing(self) -> bool:
        """No fragment was actually re-run.

        `all([])` is True, so a run in which every fragment was skipped — an R project on a
        machine without Rscript, or `--only` naming a fragment that no longer exists —
        reported success and exited 0. The printed report said so in words; the exit code,
        which is what CI reads, did not. That is the same "not checked looks like checked"
        failure this command exists to close one level down.
        """
        return not self.comparisons


def runner_for(script: Path) -> list[str] | None:
    """The command that runs this script, or None when nothing here knows how."""
    template = RUNNERS.get(script.suffix.lower())
    if template is None:
        return None
    if shutil.which(template[0]) is None and template[0] != sys.executable:
        return None
    return template


def _same(before: object, after: object) -> bool:
    """Equality that treats two NaNs as agreeing.

    `float('nan') == float('nan')` is False, so a results value that is legitimately NaN
    both on disk and on re-run was reported as a difference every single time — a permanent
    red that teaches an author to stop reading this command.
    """
    if isinstance(before, float) and isinstance(after, float):
        return before == after or (before != before and after != after)
    if isinstance(before, tuple) and isinstance(after, tuple) and len(before) == len(after):
        return all(_same(a, b) for a, b in zip(before, after, strict=True))
    return bool(before == after)


def _values_of(document: dict) -> dict[str, object]:
    """Value and display for every key, which is what a claim actually rests on.

    Table captions and column headers are included because they are rendered with the table
    and are claims like any other: a caption reading "the reporting odds ratio of 12.34
    (95% CI 8.00 to 19.00)" survived a hand-edited, re-signed fragment precisely because
    nothing here looked at it.
    """
    out: dict[str, object] = {}
    for key, spec in document.get("values", {}).items():
        out[key] = (spec.get("value"), spec.get("display"))
    for key, spec in document.get("tables", {}).items():
        out[f"<table {key} rows>"] = [list(row) for row in spec.get("rows", [])]
        out[f"<table {key} columns>"] = list(spec.get("columns", []))
        out[f"<table {key} caption>"] = spec.get("caption", "")
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
    if only:
        unknown = sorted(set(only) - {f.stem for f in fragments})
        if unknown:
            raise VerifyError(
                f"--only names no fragment: {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(f.stem for f in fragments))}"
            )

    # A neutral prefix. `manuscript-guard-verify-` put the literal string into the scratch
    # path, so an analysis needed no environment variable to know it was being verified —
    # `if 'manuscript-guard-verify-' in __file__` was enough. See the module docstring on
    # what this command can and cannot prove.
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch) / root.name
        try:
            # symlinks=True: copy links, do not follow them. Following them dereferenced a
            # directory junction pointing at the project itself, re-copying the whole tree at
            # every level until the OS stopped it — an unprivileged directory entry turning a
            # routine verify into a disk-churning crash.
            shutil.copytree(
                root, work, symlinks=True, ignore=shutil.ignore_patterns("build", ".git")
            )
        except (OSError, shutil.Error) as exc:
            raise VerifyError(f"could not stage a copy of the project: {exc}") from exc
        # Emptied rather than left in place, so a script that fails to write is not silently
        # compared against the copy of the file it was meant to produce.
        for stale in sorted((work / results_dir.relative_to(root)).rglob("*"), reverse=True):
            stale.unlink() if stale.is_file() else stale.rmdir()

        # No MANUSCRIPT_GUARD_VERIFY here, and there must never be one: it told the analysis
        # it was being verified, and two lines then made the script honest under verification
        # and dishonest everywhere else.
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

        for fragment in fragments:
            on_disk = json.loads(fragment.read_text(encoding="utf-8"))
            named = on_disk.get("provenance", {}).get("generated_by")
            if only and fragment.stem not in only:
                report.skipped.append((fragment.name, "excluded by --only"))
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
        if _same(before[key], after[key]):
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
