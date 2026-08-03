"""The command line: exit codes, and the refusals that only exist there.

Added after a coverage audit found cli.py at 14%, and confirmed by mutation that the most
important refusal in the toolkit was untested: disabling the guard that stops `submit`
assembling a pack while the submission check fails broke no test at all.

Exit codes are part of the contract — hooks and CI read them — so they are asserted rather
than assumed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manuscript_guard.cli import main

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def run(*argv: str) -> int:
    return main(list(argv))


# ---------------------------------------------------------------- check


def test_check_exits_zero_on_a_clean_project(project: Path, capsys) -> None:
    assert run("check", str(project)) == 0
    assert "0 failing" in capsys.readouterr().out


def test_check_exits_one_when_a_gate_fails(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nAn unbound number: 4321.\n", encoding="utf-8"
    )
    assert run("check", str(project)) == 1
    out = capsys.readouterr().out
    assert "[FAIL] G2" in out
    assert "'4321' is not bound to any source" in out


def test_check_json_carries_the_finding_code(project: Path, capsys) -> None:
    """The rendered report shows gate and message; --json is where a machine reads codes."""
    import json

    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nAn unbound number: 4321.\n", encoding="utf-8"
    )
    assert run("check", str(project), "--json") == 1
    payload = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in payload["findings"]}
    assert "unclassified-number" in codes


def test_check_reports_the_stage_it_ran_at(project: Path, capsys) -> None:
    assert run("check", str(project), "--stage", "analysis") == 0
    assert "stage: analysis" in capsys.readouterr().out


def test_check_outside_a_project_exits_two(tmp_path: Path, capsys) -> None:
    """Cannot-run is a different answer from failed, and CI needs to tell them apart."""
    assert run("check", str(tmp_path)) == 2
    assert "no paper.yaml" in capsys.readouterr().err


def test_check_submission_is_stricter_than_a_draft(project: Path) -> None:
    shutil.rmtree(project / "review")
    assert run("check", str(project)) == 0
    assert run("check", str(project), "--submission") == 1


# ---------------------------------------------------------------- submit


@needs_pandoc
def test_submit_refuses_while_the_submission_check_fails(project: Path, capsys) -> None:
    """The guarantee in submission.py's own docstring, and it was untested.

    A mutation that replaced this guard with `if False` left all 376 other tests passing.
    """
    shutil.rmtree(project / "review")
    assert run("submit", str(project), "--offline") == 1
    assert "not assembled" in capsys.readouterr().out
    assert not (project / "build" / "submission").exists()


@needs_pandoc
def test_submit_assembles_once_the_check_passes(project: Path, capsys) -> None:
    assert run("submit", str(project), "--offline") == 0
    pack = project / "build" / "submission"
    assert (pack / "MANIFEST.yaml").exists()
    assert (pack / "title-page.md").exists()
    assert "covering letter" in capsys.readouterr().out


@needs_pandoc
def test_submit_can_be_overridden_deliberately(project: Path) -> None:
    shutil.rmtree(project / "review")
    assert run("submit", str(project), "--offline", "--skip-checks") == 0
    assert (project / "build" / "submission" / "MANIFEST.yaml").exists()


# ---------------------------------------------------------------- build


@needs_pandoc
def test_build_refuses_while_a_gate_fails(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n99999 loose.\n", encoding="utf-8")
    assert run("build", str(project), "--offline") == 1


@needs_pandoc
def test_build_skip_checks_builds_anyway(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n99999 loose.\n", encoding="utf-8")
    assert run("build", str(project), "--offline", "--skip-checks") == 0
    assert (project / "build" / "manuscript.docx").exists()


# ---------------------------------------------------------------- audit


def test_audit_is_advisory_by_default(project: Path, capsys) -> None:
    paper = project / "loose.md"
    paper.write_text("The ratio was 9.99.\n", encoding="utf-8")
    assert run("audit", str(paper), "--against", str(project / "results")) == 0
    assert "9.99" in capsys.readouterr().out


def test_audit_strict_exits_one_on_an_unmatched_number(project: Path) -> None:
    paper = project / "loose.md"
    paper.write_text("The ratio was 9.99.\n", encoding="utf-8")
    assert run("audit", str(paper), "--against", str(project / "results"), "--strict") == 1


def test_audit_strict_exits_zero_when_everything_matches(project: Path) -> None:
    paper = project / "loose.md"
    paper.write_text("Hepatic injury was reported in 77 cases.\n", encoding="utf-8")
    assert run("audit", str(paper), "--against", str(project / "results"), "--strict") == 0


def test_audit_with_nothing_to_read_exits_two(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run("audit", str(empty), "--against", str(tmp_path)) == 2
    assert "nothing to audit" in capsys.readouterr().err


# ---------------------------------------------------------------- the rest


def test_stages_lists_every_stage(capsys) -> None:
    assert run("stages") == 0
    out = capsys.readouterr().out
    for stage in ("design", "analysis", "drafting", "internal-review", "submission"):
        assert stage in out
    assert "fails at every stage" in out


def test_explain_shows_the_rule_behind_each_number(project: Path, capsys) -> None:
    assert run("explain", str(project / "manuscript" / "main.md")) == 0
    out = capsys.readouterr().out
    assert "convention" in out
    assert "rate-denominator" in out or "confidence-level" in out


def test_methods_reports_and_reconciles(project: Path, capsys) -> None:
    assert run("methods", str(project)) == 0
    (project / "analysis" / "01_disproportionality.py").write_text("# changed\n", encoding="utf-8")
    assert run("methods", str(project)) == 1
    assert run("methods", str(project), "--reconcile") == 0
    assert run("methods", str(project)) == 0


def test_review_prints_the_digest_a_record_must_carry(project: Path, capsys) -> None:
    assert run("review", str(project), "--digest") == 0
    digest = capsys.readouterr().out.strip()
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_checklist_scaffolds_and_is_idempotent(project: Path, capsys) -> None:
    assert run("checklist", "DEMO-OBS", "--path", str(project)) == 0
    assert "all already present" in capsys.readouterr().out
