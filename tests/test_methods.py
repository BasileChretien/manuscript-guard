"""G9 — the Methods still describe the code.

The gate's claim is narrow and the tests keep it that way: it verifies that somebody read
the Methods against the analysis, and that nothing has changed since. It does not verify
that the Methods are correct, and no test here pretends otherwise.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_methods, reconcile
from manuscript_guard.gates.methods import analysis_digests, compare, lock_path, methods_text

SCRIPT = Path("analysis") / "01_disproportionality.py"


def report_for(root: Path):
    project, _ = load_project(root)
    return check_methods(project)


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


def touch(root: Path, text: str = "\n# an edit\n") -> None:
    path = root / SCRIPT
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


# ---------------------------------------------------------------- the ledger


def test_an_unreconciled_project_is_told_so(project: Path) -> None:
    lock_path(load_project(project)[0]).unlink(missing_ok=True)
    report = report_for(project)
    assert "methods-never-reconciled" in codes(report)
    assert report.ok, "never reconciled is a prompt, not a failure"


def test_reconciling_records_every_analysis_file(project: Path) -> None:
    projekt, _ = load_project(project)
    path, count = reconcile(projekt)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert count == len(document["analysis"]) == 2
    assert all(len(digest) == 64 for digest in document["analysis"].values())
    assert "a person looked" in path.read_text(encoding="utf-8")


def test_a_reconciled_project_is_quiet(project: Path) -> None:
    reconcile(load_project(project)[0])
    report = report_for(project)
    assert report.ok
    assert report.counts["analysis_changed"] == 0


# ---------------------------------------------------------------- drift


def test_a_changed_script_is_caught(project: Path) -> None:
    reconcile(load_project(project)[0])
    touch(project)
    report = report_for(project)
    assert "methods-drift" in codes(report)
    assert not report.ok


def test_the_report_names_which_file_changed(project: Path) -> None:
    """A prompt to re-read everything is ignored; a prompt naming one file is acted on."""
    reconcile(load_project(project)[0])
    touch(project)
    finding = next(f for f in report_for(project).findings if f.code == "methods-drift")
    assert "01_disproportionality.py" in (finding.context or "")
    assert "changed" in (finding.context or "")


def test_a_new_script_is_caught(project: Path) -> None:
    reconcile(load_project(project)[0])
    (project / "analysis" / "02_sensitivity.py").write_text("# new\n", encoding="utf-8")
    finding = next(f for f in report_for(project).findings if f.code == "methods-drift")
    assert "added" in (finding.context or "")


def test_a_deleted_script_is_caught(project: Path) -> None:
    reconcile(load_project(project)[0])
    (project / SCRIPT).unlink()
    finding = next(f for f in report_for(project).findings if f.code == "methods-drift")
    assert "removed" in (finding.context or "")


def test_reconciling_again_clears_the_drift(project: Path) -> None:
    projekt, _ = load_project(project)
    reconcile(projekt)
    touch(project)
    assert not report_for(project).ok
    reconcile(projekt)
    assert report_for(project).ok


def test_touching_a_file_without_changing_it_is_not_drift(project: Path) -> None:
    """Digests, not timestamps: copying a tree or re-saving a file is not a change."""
    import os
    import time

    projekt, _ = load_project(project)
    reconcile(projekt)
    later = time.time() + 100
    os.utime(project / SCRIPT, (later, later))
    assert report_for(project).ok


def test_non_source_files_are_ignored(project: Path) -> None:
    reconcile(load_project(project)[0])
    (project / "analysis" / "notes.txt").write_text("scratch\n", encoding="utf-8")
    assert report_for(project).ok


# ---------------------------------------------------------------- parameters


def test_a_locked_parameter_absent_from_the_methods_is_reported(project: Path) -> None:
    projekt, _ = load_project(project)
    reconcile(projekt, parameters={"alpha": "0.05", "software": "Python 3.99"})
    report = report_for(project)
    messages = " | ".join(f.message for f in report.findings)
    assert "Python 3.99" in messages, "the Methods do not mention this, and should be told"
    assert "alpha = 0.05" not in messages, "the Methods do state the 0.05 threshold"


def test_the_methods_section_is_found_by_heading(project: Path) -> None:
    text = methods_text(load_project(project)[0])
    assert "reporting odds ratio" in text.lower()
    assert "Introduction" not in text


# ---------------------------------------------------------------- comparison helper


def test_compare_classifies_each_kind_of_change() -> None:
    drift = compare({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "9", "d": "4"})
    assert drift.changed == ("b",)
    assert drift.added == ("c",)
    assert drift.removed == ("d",)
    assert drift.any


def test_compare_of_identical_trees_is_empty() -> None:
    drift = compare({"a": "1"}, {"a": "1"})
    assert not drift.any
    assert drift.describe() == ""


def test_digests_cover_the_analysis_directory(project: Path) -> None:
    digests = analysis_digests(load_project(project)[0])
    assert set(digests) == {"analysis/00_simulate.py", "analysis/01_disproportionality.py"}
