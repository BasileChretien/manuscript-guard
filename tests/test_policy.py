"""The stage policy: which findings bind, and when.

The property that matters most is the one that keeps this from becoming a way to hide
problems: every gate runs at every stage, and a deferred finding is demoted and counted,
never dropped.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.policy import (
    ANALYSIS,
    BINDS_AT,
    DESCRIPTIONS,
    DESIGN,
    DRAFTING,
    INTERNAL_REVIEW,
    STAGES,
    SUBMISSION,
    apply_stage,
    binds_at,
    resolve_stage,
    stage_index,
    summarise_deferred,
)


def report_with(*codes: str) -> Report:
    made = (
        Finding(gate="G", code=code, message=f"about {code}", severity=FAIL) for code in codes
    )
    return Report(tuple(made))


# ---------------------------------------------------------------- the ladder


def test_the_stages_are_ordered() -> None:
    assert [stage_index(s) for s in STAGES] == list(range(len(STAGES)))
    assert stage_index(DESIGN) < stage_index(ANALYSIS) < stage_index(DRAFTING)
    assert stage_index(DRAFTING) < stage_index(INTERNAL_REVIEW) < stage_index(SUBMISSION)


def test_every_stage_is_described() -> None:
    assert set(DESCRIPTIONS) == set(STAGES)


def test_every_declared_binding_names_a_real_stage() -> None:
    assert all(stage in STAGES for stage in BINDS_AT.values())


def test_an_unknown_stage_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        stage_index("nearly-done")


# ---------------------------------------------------------------- fail closed


def test_an_unlisted_code_binds_immediately() -> None:
    """Adding a gate must not accidentally make it optional."""
    assert binds_at("a-code-nobody-has-classified") == DESIGN
    report, deferred = apply_stage(report_with("a-code-nobody-has-classified"), DESIGN)
    assert not report.ok
    assert deferred == {}


def test_schema_violations_bind_at_every_stage() -> None:
    report, _ = apply_stage(report_with("schema-violation"), DESIGN)
    assert not report.ok


# ---------------------------------------------------------------- deferral


def test_a_finding_that_is_not_due_is_demoted_not_dropped() -> None:
    report, deferred = apply_stage(report_with("no-review"), DRAFTING)
    assert report.ok, "not due yet"
    assert len(report.findings) == 1, "still reported"
    assert report.findings[0].severity == INFO
    assert "not due until submission" in report.findings[0].message
    assert deferred == {SUBMISSION: 1}


def test_a_finding_binds_from_its_stage_onwards() -> None:
    for stage in (INTERNAL_REVIEW, SUBMISSION):
        report, _ = apply_stage(report_with("figure-unreviewed"), stage)
        assert not report.ok, stage
    for stage in (DESIGN, ANALYSIS, DRAFTING):
        report, _ = apply_stage(report_with("figure-unreviewed"), stage)
        assert report.ok, stage


def test_warnings_are_left_alone() -> None:
    """Deferral is about failures. A warning is already not fatal."""
    warning = Report((Finding(gate="G", code="no-review", message="m", severity=WARN),))
    report, deferred = apply_stage(warning, DESIGN)
    assert report.findings[0].severity == WARN
    assert deferred == {}


def test_the_summary_says_how_many_and_when() -> None:
    _report, deferred = apply_stage(
        report_with("no-review", "figure-unreviewed", "unclassified-number"), ANALYSIS
    )
    note = summarise_deferred(deferred)
    assert "3 findings not due yet" in note
    assert "1 at drafting" in note
    assert "not hidden" in note


def test_nothing_deferred_says_nothing() -> None:
    assert summarise_deferred({}) == ""


# ---------------------------------------------------------------- resolution


class _Paper:
    def __init__(self, stage=None):
        self.paper = {"stage": stage} if stage else {}


def test_submission_beats_everything() -> None:
    assert resolve_stage(_Paper("design"), "analysis", True) == SUBMISSION


def test_the_flag_beats_the_file() -> None:
    assert resolve_stage(_Paper("design"), "drafting", False) == DRAFTING


def test_the_file_is_used_when_no_flag_is_given() -> None:
    assert resolve_stage(_Paper("analysis"), None, False) == ANALYSIS


def test_the_default_is_drafting() -> None:
    assert resolve_stage(_Paper(), None, False) == DRAFTING


# ---------------------------------------------------------------- against a real project


def test_the_example_passes_at_every_stage(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    for stage in STAGES:
        report, _project, chosen, _deferred = _run_gates(project, stage=stage)
        assert chosen == stage
        assert report.ok, f"{stage}: {report.render(project)}"


def test_an_early_project_is_not_buried_in_failures(tmp_path: Path) -> None:
    """The point of the whole mechanism: starting a project must not produce a wall of red."""
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="Something new")
    (root / "analysis" / "01_model.py").write_text("# in progress\n", encoding="utf-8")

    for stage in (DESIGN, ANALYSIS):
        report, _project, _chosen, deferred = _run_gates(root, stage=stage)
        assert report.ok, f"{stage}: {report.render(root)}"
        assert deferred, "and the outstanding work is still listed"

    report, _project, _chosen, _deferred = _run_gates(root, stage=DRAFTING)
    assert not report.ok, "by drafting, the same things are due"


def test_a_deferred_finding_still_appears_in_the_output(tmp_path: Path) -> None:
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="Something new")
    report, _project, _chosen, _deferred = _run_gates(root, stage=DESIGN)
    rendered = report.render(root)
    assert "not due until drafting" in rendered


def test_the_declared_stage_is_read_from_paper_yaml(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    path = project / "paper.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["stage"] = "analysis"
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")

    _report, _project, chosen, _deferred = _run_gates(project)
    assert chosen == ANALYSIS


def test_review_findings_do_not_block_a_draft_but_do_block_submission(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    shutil.rmtree(project / "review")
    report, _project, _chosen, _deferred = _run_gates(project, stage=DRAFTING)
    assert report.ok
    report, _project, _chosen, _deferred = _run_gates(project, submission=True)
    assert not report.ok
