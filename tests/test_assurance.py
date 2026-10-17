"""Item 44: `check` ends by saying what it checked, dimension by dimension, what was recorded
and by whom, and what no gate decides."""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard.assurance import DIMENSIONS, assurance, record_verified
from manuscript_guard.contracts import load_project
from manuscript_guard.findings import Finding, Report


def _said(root: Path, report: Report | None = None) -> list[str]:
    project, _ = load_project(root)
    return assurance(report or Report(), project)


def test_check_says_what_each_dimension_rests_on_and_keeps_its_exit_code(
    project: Path, capsys
) -> None:
    from manuscript_guard.cli import main

    code = main(["check", str(project)])
    printed = capsys.readouterr().out
    block = printed[printed.index("What was checked, by what"):]
    names = [line.strip() for line in block.splitlines() if line.startswith("  ") and
             not line.startswith("    ")]  # fmt: skip
    assert names == [dimension.name for dimension in DIMENSIONS]
    assert "    not checked: whether the design supports the conclusion" in block
    assert "    recorded:    no review of the design" in block
    assert "by Ada Example" in block and "by Claude Code" in block
    assert "score" in block.splitlines()[0]
    assert printed.rstrip().splitlines()[-1].endswith(("warnings", "warning", "hidden."))
    assert code == main(["check", str(project), "--json"])
    assert "What was checked" not in capsys.readouterr().out


def test_a_run_of_verify_is_said_until_the_results_change(project: Path) -> None:
    """`verify` re-runs the analysis and was said nowhere; `check` had no way to say it."""
    from manuscript_guard.verify import Comparison, VerifyReport

    assert "    recorded:    no run of `verify` in this checkout" in _said(project)
    loaded, _ = load_project(project)
    agreed = tuple(map(str, range(31)))
    record_verified(loaded, VerifyReport([Comparison("01.json", agreed=agreed)]))
    [line] = [line for line in _said(project) if "`verify` re-ran" in line]
    assert line.endswith(": 31 of 31 values reproduced")
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["cohort.n_reports"]["display"] = "4001"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    [line] = [line for line in _said(project) if "`verify` re-ran" in line]
    assert line.endswith("; the results have changed since")


def test_a_run_of_verify_that_left_a_fragment_out_says_so(project: Path) -> None:
    """Round 1 of #306: a fragment skipped (no Rscript) or whose script failed was left out of
    the count, and `check` said "reproduced 31 of 31 values" of an analysis not all re-run."""
    from manuscript_guard.verify import Comparison, VerifyReport

    loaded, _ = load_project(project)
    agreed = tuple(f"v{n}" for n in range(31))
    for name, keys in (("02_model.json", ("m.point", "m.ci_low")), ("03_r.json", ("r.n",))):
        values = {key: {"value": 1, "display": "1"} for key in keys}
        (project / "results" / name).write_text(json.dumps({"values": values}), "utf-8")
    # As verify builds them: a script that failed carries its error and no values (round 2).
    failed = Comparison("02_model.json", ran=False, error="02_model.py exited 1")
    run = VerifyReport([Comparison("01_disproportionality.json", agreed=agreed), failed],
                       skipped=[("03_r.json", "no runner for .R on this machine")])  # fmt: skip
    record_verified(loaded, run)
    [line] = [line for line in _said(project) if "`verify`" in line]
    assert line.endswith("31 of 34 values reproduced; 2 fragments not re-run; it did not pass")
    skipped = VerifyReport([Comparison("01_disproportionality.json", agreed=agreed)],
                           skipped=[("03_r.json", "no runner for .R on this machine")])  # fmt: skip
    record_verified(loaded, skipped)
    [line] = [line for line in _said(project) if "`verify`" in line]
    assert line.endswith("31 of 32 values reproduced; 1 fragment not re-run")
    record_verified(loaded, VerifyReport([Comparison("01.json", agreed=agreed)]))
    [line] = [line for line in _said(project) if "`verify`" in line]
    assert line.endswith(": 31 of 31 values reproduced")


def test_a_reporting_checklist_that_stops_its_gate_is_said_under_reporting(project: Path) -> None:
    """Round 1 of #306: the reporting gate stops under the name G8r, while its findings are
    G5's, and its failure was counted in no dimension."""
    stopped = Finding(gate="G8r", code="gate-errored", message="G8r could not run")
    [line] = [line for line in _said(project, Report((stopped,))) if "G4, G5, G13" in line]
    assert "G4, G5, G13: 1 failing, 0 warnings; G5 did not run" in line


def test_an_attested_file_of_another_shape_says_nothing_of_it(project: Path) -> None:
    attested = project / "literature" / "attested.yaml"
    attested.write_text("schema: manuscript-guard/attested/1\nentries: 3\n", encoding="utf-8")
    assert not [line for line in _said(project) if "attested" in line]


def test_a_gate_that_did_not_run_or_read_nothing_is_said(project: Path) -> None:
    stopped = Finding(gate="G15", code="gate-errored", message="G15 could not run")
    report = Report((stopped,), {"analysis_files": 2, "design_sections": 0})
    [line] = [line for line in _said(project, report) if "G9, G12, G15" in line]
    assert line.endswith("G9, G12, G15: 1 failing, 0 warnings; G15 did not run; G12 read nothing")


def test_a_project_with_no_panel_says_so(project: Path) -> None:
    for record in (project / "review").rglob("*.yaml"):
        record.unlink()
    assert "    recorded:    no panel's reading" in _said(project)
