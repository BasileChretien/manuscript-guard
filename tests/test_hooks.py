"""The hooks.

Three properties matter more than any individual behaviour, and each has a test that would
fail loudly if it stopped holding:

* a hook never breaks the session, whatever it is handed;
* a hook blocks only what is unambiguous;
* the fast paths stay fast, because they fire on every edit and every shell command.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.hooks import HANDLERS, SUBMISSION_MARKERS, dispatch, main


def run(handler: str, payload: dict, capsys) -> dict | None:
    assert dispatch(handler, payload) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def decision(result: dict | None) -> str | None:
    if not result:
        return None
    return result.get("hookSpecificOutput", {}).get("permissionDecision")


def context(result: dict | None) -> str:
    if not result:
        return ""
    return result.get("hookSpecificOutput", {}).get("additionalContext", "")


def reason(result: dict | None) -> str:
    if not result:
        return ""
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


# ---------------------------------------------------------------- never breaks


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_input": {}},
        {"tool_input": {"file_path": ""}},
        {"tool_input": {"file_path": "/nowhere/at/all/x.md"}},
        {"tool_input": {"file_path": None}},
        {"tool_input": "not a mapping"},
        {"cwd": "/does/not/exist"},
    ],
)
@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_no_input_breaks_a_hook(handler: str, payload: dict, capsys) -> None:
    """A hook that raises in a half-configured project teaches the author to remove it."""
    assert dispatch(handler, payload) == 0


def test_an_unknown_event_is_ignored() -> None:
    assert dispatch("not-an-event", {}) == 0
    assert main(["not-an-event"]) == 0
    assert main([]) == 0


# ---------------------------------------------------------------- the write guard


@pytest.mark.parametrize(
    ("relative", "fragment"),
    [
        ("results/01_disproportionality.json", "machine-written"),
        ("results/01_disproportionality.json.sha256", "digest"),
        ("build/manuscript.docx", "regenerated"),
        ("profiles/reporting/STROBE.yaml", "transcribed"),
    ],
)
def test_generated_files_cannot_be_edited(
    project: Path, relative: str, fragment: str, capsys
) -> None:
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    result = run("guard-write", {"tool_input": {"file_path": str(target)}}, capsys)
    assert decision(result) == "deny"
    assert fragment in reason(result)
    assert relative in reason(result)


@pytest.mark.parametrize(
    "relative",
    [
        "manuscript/main.md",
        "analysis/01_disproportionality.py",
        "paper.yaml",
        "literature/ledger.yaml",
        "review/panel-1.yaml",
        "methods.lock",
        "figures/forest.py",
    ],
)
def test_files_a_person_writes_are_allowed(project: Path, relative: str, capsys) -> None:
    """Only generated files are blocked. Everything an author edits stays editable."""
    result = run("guard-write", {"tool_input": {"file_path": str(project / relative)}}, capsys)
    assert result is None


def test_a_file_outside_any_project_is_ignored(tmp_path: Path, capsys) -> None:
    loose = tmp_path / "notes.json"
    loose.touch()
    assert run("guard-write", {"tool_input": {"file_path": str(loose)}}, capsys) is None


# ---------------------------------------------------------------- after an edit


def test_unbound_numbers_are_reported_the_moment_they_are_written(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text("# Results\n\nThe odds ratio was 3.84 in 77 cases.\n", encoding="utf-8")
    result = run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys)
    text = context(result)
    assert "2 number(s) bound to nothing" in text
    assert "'3.84'" in text
    assert "{{results." in text, "the message says what to do about it"


def test_a_clean_manuscript_says_nothing(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    assert run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys) is None


def test_editing_an_analysis_file_warns_that_results_are_stale(project: Path, capsys) -> None:
    path = project / "analysis" / "01_disproportionality.py"
    result = run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys)
    assert "stale until it is re-run" in context(result)
    assert "methods" in context(result)


def test_markdown_outside_the_manuscript_is_left_alone(project: Path, capsys) -> None:
    path = project / "design" / "plan.md"
    assert run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys) is None


# ---------------------------------------------------------------- the submission guard


@pytest.mark.parametrize(
    "command",
    [
        "manuscript-guard submit",
        "cd example && manuscript-guard submit --offline",
        "FOO=1 manuscript-guard check --submission",
        "zip -r out.zip build/submission",
        "scp build/manuscript.docx server:/tmp",
    ],
)
def test_submission_shaped_commands_are_recognised(command: str) -> None:
    """Matched against the whole string: a leading assignment or `cd x &&` defeats a
    prefix rule, which is exactly how a submission slipped past the predecessor's guard."""
    assert SUBMISSION_MARKERS.search(command)


@pytest.mark.parametrize(
    "command",
    ["ls -la", "git status", "pytest -q", "python analysis/01_model.py", "manuscript-guard check"],
)
def test_ordinary_commands_are_not_touched(command: str, capsys) -> None:
    assert SUBMISSION_MARKERS.search(command) is None
    assert run("guard-submission", {"tool_input": {"command": command}}, capsys) is None


def test_a_failing_submission_blocks_the_command(project: Path, capsys) -> None:
    import shutil

    shutil.rmtree(project / "review")
    result = run(
        "guard-submission",
        {"tool_input": {"command": "manuscript-guard submit"}, "cwd": str(project)},
        capsys,
    )
    assert decision(result) == "deny"
    assert "submission check" in reason(result)
    assert "check --submission" in reason(result)


def test_a_passing_submission_is_not_blocked(project: Path, capsys) -> None:
    result = run(
        "guard-submission",
        {"tool_input": {"command": "manuscript-guard submit"}, "cwd": str(project)},
        capsys,
    )
    assert result is None


# ---------------------------------------------------------------- session start


def test_session_start_reports_the_stage_and_the_count(project: Path, capsys) -> None:
    text = context(run("session-start", {"cwd": str(project)}, capsys))
    assert "stage 'drafting'" in text
    assert "0 failing" in text


def test_session_start_names_what_becomes_due_next(tmp_path: Path, capsys) -> None:
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="Something new")
    (root / "paper.yaml").write_text(
        (root / "paper.yaml").read_text(encoding="utf-8") + "stage: design\n", encoding="utf-8"
    )
    text = context(run("session-start", {"cwd": str(root)}, capsys))
    assert "become due at 'drafting'" in text
