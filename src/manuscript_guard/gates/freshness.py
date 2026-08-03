"""G1 — are the results still the results?

Three questions, in descending order of how badly a wrong answer would hurt:

1. Did a declared input file change after the fragment was written? Detected by hash, not
   by timestamp, because a data file can be regenerated with identical content, and
   because copying a tree resets every timestamp.
2. Was the script that produced the fragment modified afterwards?
3. Did anything else under the analysis directory change afterwards?

The first two fail. The third only warns: a shared helper may well have changed without
affecting any number, and blocking the build on that would train the author to switch the
gate off.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.emit import DIGEST_SUFFIX, read_digest, sha256_of
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.paths import SOURCE_SUFFIXES

GATE = "G1"

__all__ = ["SOURCE_SUFFIXES", "check_freshness"]


def check_freshness(project: Project, results: Results) -> Report:
    report = Report()
    analysis_dir = project.path("analysis")
    checked_inputs = 0

    for fragment in results.fragments:
        stamp = fragment.path.stat().st_mtime
        report = report.merge(_check_digest(fragment.path))

        for declared in fragment.inputs:
            checked_inputs += 1
            input_path = project.root / declared["path"]
            if not input_path.exists():
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="input-missing",
                        message=f"input {declared['path']} no longer exists",
                        path=fragment.path,
                        hint=f"restore it, or re-run {fragment.generated_by}",
                    )
                )
                continue
            if sha256_of(input_path) != declared["sha256"]:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="input-changed",
                        message=f"input {declared['path']} changed since these results "
                        f"were written",
                        path=fragment.path,
                        context=f"written {fragment.generated_at} by {fragment.generated_by}",
                        hint=f"re-run {fragment.generated_by}",
                    )
                )

        script_path = project.root / fragment.generated_by
        if not script_path.exists():
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="script-missing",
                    message=f"the script that produced these results is gone: "
                    f"{fragment.generated_by}",
                    path=fragment.path,
                    hint="results with no reproducible origin cannot back a claim",
                )
            )
        else:
            # By digest when the fragment records one, by mtime otherwise. The mtime test
            # was the only test, and `touch` defeats it: edit the analysis, stamp the
            # fragment forward, and the change was invisible. G1's own docstring says
            # hashes are used "because timestamps lie" — which was true of the inputs and
            # not of the code that read them. Fragments written before this field existed
            # still get the old test, so an older project degrades rather than breaking.
            declared = fragment.generated_by_sha256
            changed = (
                sha256_of(script_path) != declared
                if declared
                else script_path.stat().st_mtime > stamp
            )
            if changed:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="script-newer",
                        message=f"{fragment.generated_by} has changed since it wrote "
                        f"{fragment.path.name}",
                        path=script_path,
                        hint=f"re-run {fragment.generated_by}",
                    )
                )

    if results.fragments and analysis_dir.exists():
        newest_fragment = max(f.path.stat().st_mtime for f in results.fragments)
        declared_scripts = {
            (project.root / f.generated_by).resolve() for f in results.fragments
        }
        for path in sorted(analysis_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if path.resolve() in declared_scripts:
                continue
            if path.stat().st_mtime > newest_fragment:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="analysis-newer",
                        severity=WARN,
                        message=f"{_rel(path, project.root)} changed after the newest "
                        f"results fragment",
                        path=path,
                        hint="if any results depend on it, re-run them",
                    )
                )

    return report.with_counts(
        fragments_checked=len(results.fragments), inputs_checked=checked_inputs
    )


def _check_digest(path: Path) -> Report:
    """Has the fragment been edited since the analysis wrote it?"""
    declared = read_digest(path)
    if declared is None:
        return Report(
            (
                Finding(
                    gate=GATE,
                    # A failure, not a warning. A fragment with no sidecar is a file nobody
                    # can show was written by an analysis, and the emitter always writes
                    # one — so its absence means the file was made some other way. Hand-write
                    # `results/national.json` with a headline estimate and a confidence
                    # interval the analysis never produced, omit the sidecar, and while this
                    # was a warning the whole thing passed `check --submission` cleanly.
                    # Deferred to `analysis` by the stage policy, since at `design` there is
                    # no analysis to have written anything.
                    code="no-digest",
                    message=f"{path.name} has no {DIGEST_SUFFIX} sidecar, so nothing shows an "
                    f"analysis wrote it",
                    path=path,
                    hint="re-run the analysis through emit(); a fragment written by hand "
                    "cannot be a result",
                ),
            )
        )
    actual = sha256_of(path)
    if actual == declared:
        return Report()
    return Report(
        (
            Finding(
                gate=GATE,
                code="results-edited",
                message=f"{path.name} has been modified since the analysis wrote it",
                path=path,
                context=f"declared {declared[:12]}…, actual {actual[:12]}…",
                hint="results are machine-written; change the analysis and re-run it "
                "rather than editing this file",
            ),
        )
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
