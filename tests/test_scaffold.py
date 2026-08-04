"""A fresh project must fail for the right reasons, and only those."""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.findings import merge_all
from manuscript_guard.scaffold import init_project


def test_init_creates_the_layout(tmp_path: Path) -> None:
    created = init_project(tmp_path / "paper", title="A fresh project")
    names = {p.name for p in created}
    assert {"paper.yaml", "authors.yaml", "ledger.yaml", "attested.yaml", "main.md"} <= names
    for directory in ("analysis", "results", "literature/sources", "figures"):
        assert (tmp_path / "paper" / directory).is_dir()


def test_init_is_idempotent(tmp_path: Path) -> None:
    init_project(tmp_path / "paper")
    (tmp_path / "paper" / "paper.yaml").write_text("edited by hand\n", encoding="utf-8")
    assert init_project(tmp_path / "paper") == []
    assert (tmp_path / "paper" / "paper.yaml").read_text(encoding="utf-8") == "edited by hand\n"


def test_a_fresh_project_reads_as_a_todo_list(tmp_path: Path) -> None:
    """It should fail, but every failure must be real work rather than placeholder noise."""
    root = tmp_path / "paper"
    init_project(root, title="A fresh project")

    project, contract_report = load_project(root)
    _namespace, _results, _literature, load_report = load_namespace(project)
    report = merge_all([contract_report, load_report])

    assert not report.ok
    messages = [f.message for f in report.failures]
    assert any("no results fragments" in m for m in messages)
    assert sum("authors/0/given" in m or "authors/0/family" in m for m in messages) == 2
    # Optional fields the author has not filled in must not generate failures of their own.
    assert not any("orcid" in m or "email" in m or "credit" in m for m in messages)
    assert len(report.failures) == 3


def test_a_fresh_project_starts_at_design_and_passes_there(tmp_path: Path) -> None:
    """The scaffold wrote no `stage:`, so a new project fell to the `drafting` default.

    A project on its first day was held to the standards of one with a finished draft, which
    is precisely the wall of red the stage ladder was built to prevent — and reaching the
    documented experience needed a `--stage` flag the author had no reason to know about.
    """
    root = tmp_path / "paper"
    init_project(root, title="A fresh project")
    assert "stage: design" in (root / "paper.yaml").read_text(encoding="utf-8")

    from manuscript_guard.cli import _run_gates

    report, _project, chosen, deferred = _run_gates(root)
    assert chosen == "design"
    assert report.ok, report.render(root)
    assert deferred, "the outstanding work is still listed, just not yet due"


def test_a_scaffolded_project_passes_its_own_number_gate(tmp_path: Path) -> None:
    """The first thing a new user sees must not fail the rule it is explaining.

    The guidance paragraph named `p < 0.05` as an example of a convention and quoted two
    bindings to show the syntax. All three were read as manuscript text: the p-value is a
    convention only in Methods, and the two example keys do not exist. It is an HTML comment
    now, which also stops it reaching the built document if the author forgets to delete it.
    """
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    root.mkdir()
    init_project(root, title="T")
    report, _project, _stage, _deferred = _run_gates(root, stage="drafting")
    numbers = [f for f in report.findings if f.gate == "G2"]
    assert not numbers, "\n".join(f.message for f in numbers)
