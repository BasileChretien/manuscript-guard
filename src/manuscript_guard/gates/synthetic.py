"""G1 — a result the manuscript quotes from a run that read synthetic data.

A binding proves where a number came from, not that the data it came from were real. An
analysis is often written against simulated data, a dummy extract or a test fixture while
access to the real data is waited for, and a number from that run passes every other gate.
So an input can be declared synthetic (`em.add_input(path, synthetic=True)`, or
`em$add_input(path, synthetic = TRUE)` in R), and G1 says of every run that read one which
of its results the manuscript quotes (`synthetic-input-quoted`): a warning while the paper is
written, and a failure at submission, so `submit` refuses.

A paper that is a demonstration, a worked example or a teaching paper, says so in
`paper.yaml` (`demonstration: true`): the finding is then information, and the title page of
the submission pack says the data are synthetic.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report

GATE = "G1"
#: How many quoted keys a finding names before it counts the rest.
_NAMED = 5


def is_demonstration(project: Project) -> bool:
    return project.paper.get("demonstration") is True


def quoted_refs(project: Project) -> set[str]:
    """Every binding the manuscript's sources use, as `results.<key>` or `table.<key>`."""
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.placeholders import parse

    refs: set[str] = set()
    directory = project.path("manuscript")
    for path in source_files(directory) if directory.is_dir() else ():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # G2 says why
        refs |= {placeholder.ref for placeholder in parse(text)[0]}
    return refs


def check_synthetic_inputs(
    project: Project, results: Results, *, submission: bool = False
) -> Report:
    """For each run that read an input declared synthetic, the results of it the manuscript
    quotes: a warning, a failure at submission, information in a demonstration."""
    demonstration = is_demonstration(project)
    severity = INFO if demonstration else FAIL if submission else WARN
    refs: set[str] | None = None
    report = Report()
    for fragment in results.fragments:
        synthetic = sorted(
            str(record["path"]) for record in fragment.inputs
            if isinstance(record, dict) and record.get("synthetic") and record.get("path")
        )  # fmt: skip
        if not synthetic:
            continue
        if refs is None:
            refs = quoted_refs(project)
        keys = sorted(
            [f"results.{key}" for key, value in results.values.items()
             if value.source == fragment.path and f"results.{key}" in refs]
            + [f"table.{key}" for key, table in results.tables.items()
               if table.source == fragment.path and f"table.{key}" in refs]
        )  # fmt: skip
        if not keys:
            continue
        named = ", ".join(keys[:_NAMED]) + (f" and {len(keys) - _NAMED} more"
                                            if len(keys) > _NAMED else "")  # fmt: skip
        report = report.with_findings(Finding(
            gate=GATE,
            code="synthetic-input-quoted",
            severity=severity,
            message=f"{len(keys)} result(s) the manuscript quotes come from a run that read "
            f"synthetic data ({', '.join(synthetic)}): {named}"
            + ("; the paper is a demonstration" if demonstration else ""),
            path=fragment.path,
            hint=None if demonstration else
            "run the analysis on the real data before the paper is submitted: a binding "
            "proves where a number came from, not that the data were real. A worked example "
            "or a teaching paper says so with `demonstration: true` in paper.yaml",
        ))  # fmt: skip
    return report
