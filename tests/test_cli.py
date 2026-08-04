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
from manuscript_guard.emit import write_digest

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
def test_build_skip_checks_builds_under_a_name_that_says_so(project: Path, capsys) -> None:
    """An unchecked build must not be able to pass for a checked one.

    Left as `manuscript.docx` it is the file a co-author opens and a journal receives —
    and reverting the source afterwards makes `check` pass while the stale document still
    holds the wrong number, with nothing on disk recording which one was skipped.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n99999 loose.\n", encoding="utf-8")
    assert run("build", str(project), "--offline", "--skip-checks") == 0
    assert (project / "build" / "manuscript.UNCHECKED.docx").exists()
    assert not (project / "build" / "manuscript.docx").exists()
    assert "UNCHECKED" in capsys.readouterr().out


@needs_pandoc
def test_a_clean_build_keeps_the_plain_name(project: Path) -> None:
    assert run("build", str(project), "--offline") == 0
    assert (project / "build" / "manuscript.docx").exists()


@needs_pandoc
def test_a_rerun_analysis_makes_the_built_document_stale(project: Path) -> None:
    """The commoner way a build goes stale, and the first version could not see it.

    The stamp compared `manuscript_digest`, which covers `manuscript/*.md` — so re-running
    the analysis on new data with the prose untouched left the digest identical while the
    .docx still showed the old number. An adversarial review walked an ROR from 3.84 to
    28.80 with `check --submission` reporting nothing at all.
    """
    import json

    assert run("build", str(project), "--offline") == 0
    assert run("check", str(project), "--stage", "internal-review") == 0

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["value"] = 28.80
    document["values"]["ror.point"]["display"] = "28.80"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    # Asserted by code rather than by exit status, and the test stops here: changing a
    # result legitimately unsettles the figure and its review as well, so a bare exit code
    # would not show which check fired, and rebuilding is blocked by those other findings.
    # What is under test is that the prose never moved and the document went stale anyway.
    assert "document-stale" in {f.code for f in _findings(project)}


def _findings(project: Path):
    from manuscript_guard.cli import _run_gates

    report, _p, _s, _d = _run_gates(project, stage="internal-review")
    return report.findings


@needs_pandoc
def test_a_document_with_no_stamp_is_reported_rather_than_skipped(project: Path) -> None:
    """A missing stamp was a `continue`, so deleting one file disabled the check."""
    from manuscript_guard.build.document import SOURCE_STAMP

    assert run("build", str(project), "--offline") == 0
    (project / "build" / f"manuscript.docx{SOURCE_STAMP}").unlink()

    assert run("check", str(project), "--stage", "internal-review") == 0
    out = capsys_text(project)
    assert "no record of the source" in out


def capsys_text(project: Path) -> str:
    from manuscript_guard.cli import _run_gates

    report, _p, _s, _d = _run_gates(project, stage="internal-review")
    return report.render(project)


@needs_pandoc
def test_a_built_document_that_no_longer_matches_its_source_is_reported(project: Path) -> None:
    """Nothing linked the .docx to the manuscript it came from.

    So editing the source and forgetting to rebuild left every gate green over a document
    still holding the old number — and that document is the file a co-author opens and a
    journal receives. Not due until internal review, because a stale build while drafting
    is normal: you rebuild when you need it.
    """
    assert run("build", str(project), "--offline") == 0
    assert run("check", str(project), "--stage", "internal-review") == 0

    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later thought.\n", encoding="utf-8")

    assert run("check", str(project), "--stage", "drafting") == 0, "not due yet while drafting"
    assert run("check", str(project), "--stage", "internal-review") == 1
    assert run("build", str(project), "--offline") == 0
    assert run("check", str(project), "--stage", "internal-review") == 0


@needs_pandoc
def test_an_overridden_submission_pack_records_that_in_its_manifest(project: Path) -> None:
    """The pack was byte-indistinguishable from one that passed. Six months later nobody
    can tell, and the manifest's whole purpose is to be the thing you can tell from."""
    shutil.rmtree(project / "review")
    assert run("submit", str(project), "--offline", "--skip-checks") == 0
    manifest = (project / "build" / "submission" / "MANIFEST.yaml").read_text(encoding="utf-8")
    assert "SKIPPED" in manifest


@needs_pandoc
def test_a_checked_submission_pack_says_so(project: Path) -> None:
    assert run("submit", str(project), "--offline") == 0
    manifest = (project / "build" / "submission" / "MANIFEST.yaml").read_text(encoding="utf-8")
    assert "checks: passed" in manifest


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


def test_explain_agrees_with_check(project: Path, capsys) -> None:
    """The debugging command was giving a different answer from the gate it explains.

    `explain` classified with no section, so every `methods_only` rule fired everywhere: a
    fabricated `p < 0.001` in the Results was reported as a recognised convention while
    `check` failed it. That answer is the input to deciding whether to add a `conventions:`
    exemption — the one mechanism that makes G2 vacuous — so being wrong here is worse than
    being silent.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(
        "# Methods\n\nSignificance was set at p < 0.05.\n\n"
        "# Results\n\nThe excess was significant (p < 0.001).\n",
        encoding="utf-8",
    )
    assert run("explain", str(path)) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    methods = next(line for line in lines if " 0.05 " in f" {line} ")
    results = next(line for line in lines if " 0.001 " in f" {line} ")
    assert methods.startswith("ok"), "a threshold in Methods is a convention"
    assert results.startswith("FAIL"), "the same characters in Results are a finding"

    assert run("check", str(project)) == 1


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
