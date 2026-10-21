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
from manuscript_guard.gates.methods import (
    analysis_digests,
    compare,
    lock_path,
    main_methods,
    methods_text,
    supplement_methods_in,
    supplementary_methods,
)

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


def test_a_parameter_stated_in_a_methods_subsection_is_found(project: Path) -> None:
    """The Methods ended at their first subsection, so software named under `## Statistical
    analysis` was reported absent from the Methods."""
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    added = "## Statistical analysis\n\nRun in Python 3.99.\n\n# Results\n"
    main.write_text(text.replace("# Results\n", added, 1), encoding="utf-8")
    projekt, _ = load_project(project)
    reconcile(projekt, parameters={"software": "Python 3.99"})
    assert "Python 3.99" in methods_text(projekt)
    assert "methods-parameter-absent" not in codes(report_for(project))


# ---------------------------------------------------------------- the supplement's Methods


def test_every_methods_section_of_a_supplement_file_is_read_once() -> None:
    """A supplement numbers its Methods and puts its tables between them: each section that
    holds "methods" is read, with what is under it, and one inside another once. The tables
    and a heading under the results are not the Methods."""
    text = (
        "# Supplementary methods\n\nOne.\n\n## eMethods 1. Data source\n\nTwo.\n\n"
        "# eTable 1. Counts\n\nBasil.\n\n# eMethods 2. Sensitivity\n\nThree.\n\n"
        "# Results\n\n## Methods of the subgroups\n\nBasil.\n"
    )
    read = supplement_methods_in(text)
    assert read is not None
    assert [read.count(word) for word in ("One", "Two", "Three", "Basil")] == [1, 1, 1, 0]
    assert supplement_methods_in("# eTable 1\n\nBasil.\n") is None


def test_the_methods_are_the_main_text_s_and_the_supplement_s(project: Path) -> None:
    folder = project / "manuscript" / "supplementary"
    (folder / "S0_methods.md").write_text("# eMethods 1\n\nRun in R 4.6.0.\n", encoding="utf-8")
    projekt, _ = load_project(project)
    text = methods_text(projekt)
    assert text.index("reporting odds ratio") < text.index("Run in R 4.6.0.")
    assert "Run in R 4.6.0." not in main_methods(projekt)
    assert [path.name for path, _ in supplementary_methods(projekt)] == [
        "S0_methods.md",
        "S1_code_lists.md",
    ]


def test_reconcile_writes_a_lock_read_with_the_supplement(project: Path) -> None:
    projekt, _ = load_project(project)
    reconcile(projekt)
    lock = yaml.safe_load(lock_path(projekt).read_text(encoding="utf-8"))
    assert lock["schema"] == "manuscript-guard/methods-lock/2"


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
