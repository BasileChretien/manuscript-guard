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


def test_the_gates_run_even_when_there_are_no_results_yet(tmp_path: Path) -> None:
    """This test exists because the one above used to pass for the wrong reason.

    The gates sat behind `if contract_report.ok and load_report.ok`. A project with no
    results — the ordinary state at design and analysis, and precisely what the test above
    builds — failed that condition, so none of the twelve ran. The loading failures were
    then demoted by the stage policy and the run printed "0 failing, 0 warnings" over a
    manuscript that had never been looked at. Passing quietly and passing because nothing
    was checked are different answers, and only one of them is true.
    """
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="Something new")
    (root / "manuscript" / "main.md").write_text(
        "# Introduction\n\nDelving into it, the odds ratio was 7.77 across 12345 reports.\n",
        encoding="utf-8",
    )

    report, _project, _chosen, _deferred = _run_gates(root, stage=DESIGN)
    codes = {f.code for f in report.findings}
    assert "unclassified-number" in codes, "G2 did not run"
    assert "ai-phrasing" in codes, "G6 did not run"
    assert report.ok, "and none of it is due yet, so the run still passes"


def test_a_gate_that_crashes_is_reported_rather_than_dropped(project: Path, monkeypatch) -> None:
    """A gate that raised used to take every gate after it out of the run with it."""
    from manuscript_guard import cli

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "check_writing", explode)
    report, _project, _chosen, _deferred = cli._run_gates(project)
    assert not report.ok
    failure = next(f for f in report.failures if f.code == "gate-errored")
    assert "RuntimeError: boom" in failure.message
    assert "a bug in manuscript-guard" in failure.hint


def test_a_file_a_gate_cannot_read_is_named_and_not_called_a_bug(project: Path) -> None:
    """A review record saved as UTF-16. The gate did not run, and the reason is the file's own.

    It read "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0", with no
    file named, under a hint that began with a bug in the tool.
    """
    from manuscript_guard import cli

    record = project / "review" / "round-1" / "biostatistician.yaml"
    record.write_bytes(record.read_text(encoding="utf-8").encode("utf-16"))

    report, _project, _chosen, _deferred = cli._run_gates(project)
    failure = next(f for f in report.failures if f.code == "gate-errored")
    assert failure.gate == "G11"
    assert failure.message == (
        f"G11 could not run: {record}: cannot read as UTF-8: the file is UTF-16. "
        "Save the file as UTF-8."
    )
    assert "bug" not in failure.hint
    assert "has not been checked by this gate" in failure.hint


#: The gates that read the text of the manuscript, in the order they run. G11 reads its
#: bytes for the digest and G13 reads it only once a revision round is open.
READ_THE_MANUSCRIPT = "G2, G7, G4, G8r, G6, G9, G14, G15 and BUILD"


def in_a_code_page(path: Path) -> int:
    """One accented letter in code page 1252 on a last line of its own; returns that line."""
    data = path.read_bytes()
    path.write_bytes(data + b"\nCaf\xe9 society.\n")
    return data.count(b"\n") + 2


@pytest.mark.parametrize("stage", STAGES)
def test_a_manuscript_file_that_is_not_utf8_is_one_finding_that_names_it(
    stage: str, project: Path
) -> None:
    """Saved from an editor that writes the code page. Every gate that read the file raised,
    and each was reported as `gate-errored`: seven findings that read "G2 could not run:
    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9 in position 6105", none naming
    the file, under a hint that began with a bug in the tool. It fails at every stage, as
    those did."""
    from manuscript_guard import cli

    source = project / "manuscript" / "main.md"
    line = in_a_code_page(source)

    report, _project, _chosen, _deferred = cli._run_gates(project, stage=stage)
    (failure,) = (f for f in report.failures if f.code == "manuscript-unreadable")
    # G11 reads the bytes, not the text, so it ran: the file changed after the panel read
    # it, which is a finding of its own once the review binds.
    others = {f.code for f in report.failures} - {"manuscript-unreadable"}
    assert others == ({"review-stale", "rounds-outstanding"} if stage == SUBMISSION else set())
    assert (failure.gate, failure.path, failure.line) == ("G0", source, line)
    assert failure.message == (
        f"manuscript/main.md: cannot read as UTF-8: the byte 0xe9 on line {line} is not UTF-8. "
        "Save the file as UTF-8."
    )
    assert failure.hint == f"{READ_THE_MANUSCRIPT} read the manuscript and did not run"
    assert not [f for f in report.findings if f.code == "gate-errored"]


def test_each_manuscript_file_that_is_not_utf8_is_named(project: Path) -> None:
    """A gate stops at the first file it cannot read, so the gates alone would name one file
    at a time, and which one would depend on the gate: G4 does not read the supplement."""
    from manuscript_guard import cli

    main = project / "manuscript" / "main.md"
    extra = project / "manuscript" / "supplementary" / "zz_notes.md"
    in_a_code_page(main)
    extra.write_bytes("# Notes\n\nText.\n".encode("utf-16"))

    report, _project, _chosen, _deferred = cli._run_gates(project)
    unread = [f for f in report.failures if f.code == "manuscript-unreadable"]
    said = {f.path: (f.line, f.message) for f in unread}
    assert set(said) == {main, extra}
    assert said[extra] == (
        None,
        "manuscript/supplementary/zz_notes.md: cannot read as UTF-8: the file is UTF-16. "
        "Save the file as UTF-8.",
    )
    assert {f.code for f in report.failures} == {"manuscript-unreadable"}


def test_the_gates_that_do_not_read_the_manuscript_still_report(project: Path) -> None:
    """What `check` is for when one file cannot be read: everything else it can still say."""
    from manuscript_guard import cli

    in_a_code_page(project / "manuscript" / "main.md")
    shutil.rmtree(project / "review")
    (project / "figures" / "forest.review.yaml").unlink()

    report, _project, _chosen, _deferred = cli._run_gates(project, submission=True)
    codes = {f.code for f in report.failures}
    assert "manuscript-unreadable" in codes
    assert "no-review" in codes, "G11 did not run"
    assert "figure-unreviewed" in codes, "G10 did not run"
    assert "gate-errored" not in codes


def test_a_gate_that_reads_a_manuscript_file_reports_it_where_nothing_else_has(
    project: Path, monkeypatch
) -> None:
    """The finding comes from reading every file before the gates run. A file that goes bad
    after that, or one only a gate finds, is still said by the gate that met it."""
    from manuscript_guard import cli
    from manuscript_guard.contracts import Unreadable

    source = project / "manuscript" / "main.md"

    def refuse(*_args, **_kwargs):
        raise Unreadable(source, "cannot read: Permission denied")

    monkeypatch.setattr(cli, "check_writing", refuse)
    report, _project, _chosen, _deferred = cli._run_gates(project)
    failure = next(f for f in report.failures if f.code == "gate-errored")
    assert failure.message == f"G6 could not run: {source}: cannot read: Permission denied"
    assert "bug" not in failure.hint


#: A key of `paper.yaml` that only a gate reads, in a shape the schema refuses, the place the
#: schema's finding names, and the gate that raised on it.
NOT_THE_SHAPE = {
    "terms: 5": ("terms", 5, "terms: ", "G2"),
    "conventions: abc": ("conventions", "abc", "conventions: ", "G2"),
    "conventions: [abc]": ("conventions", ["abc"], "conventions/0: ", "G2"),
    "conventions: a pattern that does not compile": (
        "conventions",
        [{"pattern": "[0-9", "why": "a count"}],
        "conventions/0/pattern: ",
        "G2",
    ),
    "conventions: a pattern the compiler refuses with another error": (
        "conventions",
        [{"pattern": "(?a)(?u)x", "why": "pasted"}],
        "conventions/0/pattern: ",
        "G2",
    ),
    "reporting_guideline: 5": ("reporting_guideline", 5, "reporting_guideline: ", "G8r"),
    "review: [1]": ("review", [1], "review: ", "G11"),
    "review: rounds in words": (
        "review",
        {"rounds_required": "two"},
        "review/rounds_required: ",
        "G11",
    ),
}


@pytest.mark.parametrize("case", list(NOT_THE_SHAPE))
def test_a_setting_in_the_wrong_shape_is_one_finding_that_names_the_key(
    case: str, project: Path
) -> None:
    """Beside the schema's finding stood "G2 could not run: TypeError: 'int' object is not
    iterable", under the hint that begins with a bug in the tool. The gate now runs as if the
    key were not set, and the schema's finding fails at every stage."""
    from manuscript_guard import cli

    key, value, where, gate = NOT_THE_SHAPE[case]
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document[key] = value
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    report, _project, _chosen, _deferred = cli._run_gates(project, stage=DESIGN)
    assert not report.ok
    assert [f.message for f in report.findings if f.code == "gate-errored"] == [], gate
    violations = [f for f in report.failures if f.code == "schema-violation"]
    assert len(violations) == 1
    assert violations[0].message.startswith(where)


def test_a_crash_in_the_literature_chain_is_reported_under_its_own_gate(
    project: Path, monkeypatch
) -> None:
    """It was reported as "G5 could not run", and G5 is the reporting checklist: the reader
    was sent to a checklist that had been checked, away from the ledger that had not. Every
    finding the literature chain makes is a G7 finding, and so is its failure to run."""
    from manuscript_guard import cli
    from manuscript_guard.gates import literature

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "check_literature_chain", explode)
    report, _project, _chosen, _deferred = cli._run_gates(project)
    failure = next(f for f in report.failures if f.code == "gate-errored")
    assert failure.gate == literature.GATE == "G7"
    assert failure.message.startswith("G7 could not run")


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


def test_every_way_of_saying_submission_gives_the_same_verdict(project: Path) -> None:
    """G11's severity was set from the raw `--submission` flag, not from the resolved stage.

    So `--submission` failed, `--stage submission` passed, and a paper.yaml declaring
    `stage: submission` — what an author naturally writes when submitting — never had the
    review gate enforced by `check` at all. Three spellings of one thing, two answers.
    """
    from manuscript_guard.cli import _run_gates

    shutil.rmtree(project / "review")
    path = project / "paper.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["stage"] = SUBMISSION
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")

    by_flag, _p, _s, _d = _run_gates(project, submission=True)
    by_stage, _p, _s, _d = _run_gates(project, stage=SUBMISSION)
    by_declaration, _p, _s, _d = _run_gates(project)

    assert not by_flag.ok
    assert not by_stage.ok
    assert not by_declaration.ok


def test_a_reading_the_panel_asked_for_binds_where_a_missing_review_does() -> None:
    """G11 only warns before a submission, so this decides nothing today. It is declared so
    that the day G11's severity stops depending on the flag, a missing reading is deferred
    with the missing review it is a kind of, and not failed from the first day."""
    assert binds_at("reading-missing") == binds_at("review-missing") == SUBMISSION
