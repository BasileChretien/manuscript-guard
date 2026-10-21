"""The example's manuscript in LaTeX, `tests/data/latex/manuscript/` (DESIGN.md, "LaTeX
manuscripts", "Tests"). Run against the example's analysis, results and citation keys, it
binds the same keys under the same headings as the example, and G2 counts and judges its
numbers as it counts and judges the example's."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.gates import check_numbers
from manuscript_guard.text.latex import views
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import chain_at, heading_index

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"


@pytest.fixture
def twin(project: Path) -> Path:
    """The example project with the twin for its manuscript."""
    folder = project / "manuscript"
    shutil.rmtree(folder)
    shutil.copytree(TWIN, folder)
    return project


def _markdown_bindings(root: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    """Each binding of the example, in order, with its file's document and its headings."""
    found = []
    folder = root / "manuscript"
    for path in (folder / "main.md", folder / "supplementary" / "S1_code_lists.md"):
        text = path.read_text(encoding="utf-8")
        index = heading_index(text)
        where = "supplement" if "supplementary" in path.parts else "main"
        found += [(where, p.ref, tuple(chain_at(index, p.start))) for p in parse(text)[0]]
    return found


def _latex_bindings(root: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    found = []
    for read in views.files(root / "manuscript"):
        where = "supplement" if read.source.path.startswith("supplementary/") else "main"
        found += [(where, p.ref, tuple(views.chain(read.source, p.start)))
                  for p in read.placeholders]  # fmt: skip
    return found


def test_the_twin_binds_the_examples_keys_in_order_under_the_same_headings(
    built_example: Path, twin: Path
) -> None:
    assert _latex_bindings(twin) == _markdown_bindings(built_example)


def _numbers(root: Path):
    loaded, _ = load_project(root)
    namespace, results, literature, _ = load_namespace(loaded)
    return check_numbers(loaded, namespace, results, literature)


#: What G2 counts of a manuscript, by `Report.counts`.
_COUNTED = ("source_files", "numeric_atoms", "bindings", "atoms_term", "atoms_structural",
            "atoms_convention", "atoms_project_exempt")  # fmt: skip


def test_g2_counts_and_judges_the_twin_as_it_does_the_example(
    project: Path, built_example: Path, tmp_path: Path
) -> None:
    example = _numbers(project)
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = _numbers(root)
    assert {key: latex.counts[key] for key in _COUNTED} == {
        key: example.counts[key] for key in _COUNTED
    }
    # The one finding G2 has of the twin alone: it does not read LaTeX's pointers yet.
    found = Counter((f.code, f.severity) for f in latex.findings if f.code != "not-read-in-latex")
    assert found == Counter((f.code, f.severity) for f in example.findings)
    assert [f.message for f in latex.findings if f.code == "not-read-in-latex"] == [
        "G2 does not read pointers to tables and figures in LaTeX yet, so it did not check them "
        "here"
    ]
