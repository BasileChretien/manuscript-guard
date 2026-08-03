"""Figure source checking and figure review.

The first test is the important one. Before the source check existed, a figure script that
read the results *and also* typed one annotation passed everything: the output check
compared the drawn number against results and it matched, because at that moment it was
still the right number. This is the recorded gap from the first build, and it must stay
closed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from manuscript_guard.classify import Classifier
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.findings import merge_all
from manuscript_guard.gates import (
    check_figure_reviews,
    check_figure_source,
    check_figures,
    content_digest,
    review_path,
)
from manuscript_guard.text.code import PYTHON, R, numbers_in

FOREST = Path("figures") / "forest.py"


def figure_report(root: Path):
    project, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(project)
    return merge_all(
        [check_figures(project, results), check_figure_reviews(project, content_digest)]
    )


def codes(report) -> set[str]:
    return {f.code for f in report.failures}


def refresh_review(root: Path) -> None:
    """Re-stamp the example's review for the figure as it now stands."""
    svg = root / "figures" / "forest.svg"
    path = review_path(svg)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["content_sha256"] = content_digest(svg)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- the closed gap


def test_hardcoded_annotation_is_caught_even_though_the_script_reads_results(
    project: Path,
) -> None:
    script = project / FOREST
    text = script.read_text(encoding="utf-8")
    # Replace the results-derived label with the value it currently holds. The script still
    # reads the results file for the marker position, so the old script-level check passes.
    corrupted = text.replace(
        'label = f"{point[\'display\']} (95% CI {low[\'display\']} to {high[\'display\']})"',
        'label = "3.84 (95% CI 2.89 to 5.12)"',
    )
    assert corrupted != text, "the fixture's label line changed; update this test"
    script.write_text(corrupted, encoding="utf-8")

    report = figure_report(project)
    assert "figure-source-text-number" in codes(report)


def test_data_typed_into_a_figure_script_is_caught(project: Path) -> None:
    script = project / FOREST
    script.write_text(
        script.read_text(encoding="utf-8")
        + "\n\nBASELINE = data.frame(x=[1, 2, 3], y=[0.2, 0.5, 0.9])\n",
        encoding="utf-8",
    )
    report = figure_report(project)
    assert "figure-source-hardcoded-data" in codes(report)


def test_a_stray_constant_in_a_figure_script_is_caught(project: Path) -> None:
    script = project / FOREST
    script.write_text(
        script.read_text(encoding="utf-8") + "\n\nEXCESS_RISK = 3.84 * 1.15\n", encoding="utf-8"
    )
    report = figure_report(project)
    assert "figure-source-unclassified-number" in codes(report)


# ---------------------------------------------------------------- what must stay quiet


def test_the_example_figure_script_is_clean(project: Path) -> None:
    report = check_figure_source(project / FOREST, Classifier.load())
    assert report.ok, report.render(project)
    assert report.counts["figure_source_numbers"] > 20, "the fixture must be real plotting code"
    assert report.counts["figure_source_presentation"] > 15


@pytest.mark.parametrize(
    "snippet",
    [
        'ax.errorbar([1], [0], capsize=4, markersize=6)',
        'ax.axvline(1, linestyle="--", linewidth=0.8)',
        'fig, ax = plt.subplots(figsize=(6.5, 2.2))',
        'ax.set_xticks([0.5, 1, 2, 5, 10])',
        'ax.set_xticklabels(["0.5", "1", "2", "5", "10"])',
        'fig.savefig(OUT, format="png", dpi=300)',
        'data = path.read_text(encoding="utf-8")',
        'ax.annotate(label, xytext=(8, 4), textcoords="offset points", fontsize=9)',
    ],
)
def test_ordinary_plotting_code_is_not_reported(tmp_path: Path, snippet: str) -> None:
    """A checker that reports `dpi=300` gets switched off, and then guards nothing."""
    script = tmp_path / "fig.py"
    script.write_text(snippet + "\n", encoding="utf-8")
    assert check_figure_source(script, Classifier.load()).ok, snippet


@pytest.mark.parametrize(
    "snippet",
    [
        'ax.annotate("ROR 3.84", xy=(1, 0))',
        'ax.set_title("Hepatic injury in 77 reports")',
        'plt.text(1, 1, "12.4% were serious")',
    ],
)
def test_numbers_written_into_drawn_text_are_reported(tmp_path: Path, snippet: str) -> None:
    script = tmp_path / "fig.py"
    script.write_text(snippet + "\n", encoding="utf-8")
    report = check_figure_source(script, Classifier.load())
    assert not report.ok, snippet
    assert "figure-source-text-number" in {f.code for f in report.failures}


def test_conventions_still_apply_inside_figure_text(tmp_path: Path) -> None:
    """The prose rules govern figure labels too, so "95% CI" passes and a bare value does not."""
    script = tmp_path / "fig.py"
    script.write_text('ax.set_xlabel("Odds ratio (95% CI)")\n', encoding="utf-8")
    assert check_figure_source(script, Classifier.load()).ok


def test_docstrings_and_comments_are_not_figure_text(tmp_path: Path) -> None:
    script = tmp_path / "fig.py"
    script.write_text('"""Figure 1, per G3, version 2."""\n# see issue 42\n', encoding="utf-8")
    assert check_figure_source(script, Classifier.load()).ok


# ---------------------------------------------------------------- the code lexer


def test_r_named_arguments_are_understood() -> None:
    source = "ggplot(d) + geom_point(size = 7) + scale_y_log10(breaks = c(0.5, 1, 2))\n"
    found = {n.text: n.names for n in numbers_in(source, R)}
    assert "size" in found["7"]
    assert "geom_point" in found["7"]
    # Inside c(), the number inherits the outer named argument, which is what settles it.
    assert "breaks" in found["0.5"]
    assert "scale_y_log10" in found["0.5"]


def test_python_nested_calls_carry_the_outer_argument() -> None:
    found = {n.text: n.names for n in numbers_in("ax.set(xlim=(0.5, 10))\n", PYTHON)}
    assert "xlim" in found["0.5"]


def test_numbers_inside_strings_are_marked_as_such() -> None:
    found = numbers_in('label = "value 42"\nsize = 3\n', PYTHON)
    by_text = {n.text: n for n in found}
    assert by_text["42"].in_string
    assert not by_text["3"].in_string


# ---------------------------------------------------------------- the review gate


def test_an_unreviewed_figure_fails(project: Path) -> None:
    review_path(project / "figures" / "forest.svg").unlink()
    assert "figure-unreviewed" in codes(figure_report(project))


def test_a_review_of_an_older_figure_fails(project: Path) -> None:
    svg = project / "figures" / "forest.svg"
    edited = svg.read_text(encoding="utf-8").replace("</svg>", "<g/></svg>")
    svg.write_text(edited, encoding="utf-8")
    assert "figure-review-stale" in codes(figure_report(project))


def test_re_rendering_an_unchanged_figure_keeps_the_review_current(project: Path) -> None:
    """Render metadata must not invalidate a review, or the gate becomes noise."""
    import subprocess
    import sys

    before = content_digest(project / "figures" / "forest.svg")
    subprocess.run(
        [sys.executable, str(project / FOREST)], cwd=project, check=True, capture_output=True
    )
    assert content_digest(project / "figures" / "forest.svg") == before


def test_a_review_missing_required_checks_fails(project: Path) -> None:
    path = review_path(project / "figures" / "forest.svg")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["checks"] = [c for c in document["checks"] if c["id"] != "scale-not-misleading"]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = figure_report(project)
    assert "figure-review-incomplete" in codes(report)
    assert any("scale-not-misleading" in (f.context or "") for f in report.failures)


def test_a_review_raising_concerns_fails(project: Path) -> None:
    path = review_path(project / "figures" / "forest.svg")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["verdict"] = "concerns"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert "figure-review-concerns" in codes(figure_report(project))


def test_svg_and_png_of_one_figure_share_a_single_review(project: Path) -> None:
    assert (project / "figures" / "forest.png").exists()
    report = figure_report(project)
    assert report.counts["figures_reviewed"] == 1
    assert report.counts["figures_outstanding"] == 0
    assert "figure-unreviewed" not in codes(report)


def test_a_raster_with_no_vector_sibling_is_flagged(project: Path) -> None:
    (project / "figures" / "forest.svg").unlink()
    report = figure_report(project)
    assert any(f.code == "figure-not-inspectable" for f in report.warnings)


def test_review_notes_survive_a_round_trip(project: Path) -> None:
    """The example's own review must satisfy the schema it ships with."""
    report = figure_report(project)
    assert not any(f.code == "schema-violation" for f in report.findings), report.render(project)
    text = review_path(project / "figures" / "forest.svg").read_text(encoding="utf-8")
    assert re.search(r"reviewed_by:\s*\S", text)
