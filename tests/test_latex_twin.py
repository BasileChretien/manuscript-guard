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


def _cited(root: Path) -> list[tuple[str, str, bool]]:
    """Each citation, in the order the files print them and each file writes them: its file,
    its key, and whether it is narrative."""
    from manuscript_guard.text.reader import citation_uses

    uses = citation_uses(load_project(root)[0])
    files = list(dict.fromkeys(use.path for use in uses))
    written = sorted(uses, key=lambda use: (files.index(use.path), use.start))
    return [(use.path.name, use.citekey, use.narrative) for use in written]


def test_the_twin_cites_the_examples_keys_in_order_as_the_example_does(
    built_example: Path, twin: Path
) -> None:
    """Step 5: the citations join the comparison when the citation reader does."""
    twin_cited = [(key, narrative) for _name, key, narrative in _cited(twin)]
    example = [(key, narrative) for _name, key, narrative in _cited(built_example)]
    assert twin_cited == example and example


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
    # G2 reads the twin's pointers to tables and figures too, from step 13, and finds what it
    # finds in the example's.
    found = Counter((f.code, f.severity) for f in latex.findings)
    assert found == Counter((f.code, f.severity) for f in example.findings)


def test_g4_counts_the_twins_words_sections_and_display_items_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 6: the journal's limits, its required sections and its statements read the twin
    as Markdown would print it, and find what they find in the example."""
    from manuscript_guard.gates import check_journal

    example = check_journal(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_journal(load_project(root)[0])
    counted = ("abstract_words", "main_text_words", "display_items")
    assert {key: latex.counts[key] for key in counted} == {
        key: example.counts[key] for key in counted
    }
    assert example.counts["main_text_words"] > 0 and example.counts["display_items"] > 0
    assert Counter((f.code, f.severity) for f in latex.findings) == Counter(
        (f.code, f.severity) for f in example.findings
    )


def test_g14_reads_the_twins_words_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 7: the abbreviations, terms, spelling and notation of the twin are read as the
    example's are, a bound value in an interval or a percentage among them, and G14 says of
    it what it says of the example."""
    from manuscript_guard.gates import check_language

    example = check_language(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_language(load_project(root)[0])
    assert latex.counts == example.counts
    assert example.counts["notation_intervals"] > 0 and example.counts["notation_percents"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g6_reads_the_twins_prose_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 7: G6 counts the twin's words, phrases, artefacts and vague attributions as the
    example's, and says of it what it says of the example."""
    from manuscript_guard.gates import check_writing

    example = check_writing(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_writing(load_project(root)[0])
    assert latex.counts == example.counts and example.counts["prose_words"] > 1000
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g8_reads_the_twins_summaries_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 8: the numbers the twin's Abstract and conclusions give are looked for where the
    paper reports, as the example's are."""
    from manuscript_guard.gates.reported import check_reported

    projekt = load_project(project)[0]
    example = check_reported(projekt, load_namespace(projekt)[1])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_reported(twin, load_namespace(twin)[1])
    assert latex.counts == example.counts
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g9_reads_the_twins_claims_and_methods_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 8: the twin's claims are the example's, word for word, so the example's lock
    holds them, and its Methods have as many paragraphs that point at no step: a heading or a
    typed table is no paragraph of them."""
    from manuscript_guard.gates.methods import anchored, check_methods

    projekt = load_project(project)[0]
    example = check_methods(projekt, *load_namespace(projekt)[:2])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_methods(twin, *load_namespace(twin)[:2])
    assert latex.counts == example.counts and example.counts["method_claims"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]
    said = [(claim.steps, claim.text) for claim in anchored(twin)[0]]
    assert said == [(claim.steps, claim.text) for claim in anchored(projekt)[0]]


def test_g15_reads_the_twins_models_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 8: the models the twin's Methods name, and the bindings it holds, are the
    example's."""
    from manuscript_guard.gates.models import check_models

    projekt = load_project(project)[0]
    example = check_models(projekt, load_namespace(projekt)[1])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_models(twin, load_namespace(twin)[1])
    assert latex.counts == example.counts and example.counts["models"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g8r_reads_the_twins_checklist_answers_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 8: the twin's claims of a guideline, and the headings the checklist's answers
    point at, are the example's."""
    from manuscript_guard.gates import check_reporting

    example = check_reporting(load_project(project)[0])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    latex = check_reporting(load_project(root)[0])
    assert latex.counts == example.counts
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]


def test_g7_reads_the_twins_quotations_and_cited_statements_as_the_examples(
    project: Path, tmp_path: Path
) -> None:
    """Step 8: the twin's cited statements, and the passages they are held to, are the
    example's, each at its `.tex` line."""
    from manuscript_guard.gates import check_passages, check_prose_quotations

    projekt = load_project(project)[0]
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    for check in (check_prose_quotations, check_passages):
        example, latex = check(projekt), check(twin)
        assert latex.counts == example.counts, check.__name__
        assert [(f.code, f.message) for f in latex.findings] == [
            (f.code, f.message) for f in example.findings
        ]
    assert check_passages(twin).counts["cited_statements"] == 3


def test_g8_recomputes_the_twins_statistics_as_the_examples(project: Path, tmp_path: Path) -> None:
    """Step 8: each P and interval the twin prints, its values put in, is read as the
    example's is."""
    from manuscript_guard.gates.recomputed import check_recomputed

    projekt = load_project(project)[0]
    example = check_recomputed(projekt, *load_namespace(projekt)[:2])
    root = tmp_path / "twin"
    shutil.copytree(project, root)
    shutil.rmtree(root / "manuscript")
    shutil.copytree(TWIN, root / "manuscript")
    twin = load_project(root)[0]
    latex = check_recomputed(twin, *load_namespace(twin)[:2])
    assert latex.counts == example.counts and example.counts["printed_intervals_read"] > 0
    assert [(f.code, f.message) for f in latex.findings] == [
        (f.code, f.message) for f in example.findings
    ]
