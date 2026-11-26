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


def test_a_declaration_without_a_reason_is_ignored(tmp_path: Path) -> None:
    """`why` was optional in the code and mandatory in every message this gate prints.

    So a bare `- value: '1'` exempted a number with no argument recorded anywhere, which is
    the shape of allowlist the whole design is written against.
    """
    script = tmp_path / "fig.py"
    script.write_text('ax.set_title("ROR 3.84")\n', encoding="utf-8")

    (tmp_path / "fig.guard.yaml").write_text("allow_source:\n  - value: '3.84'\n", encoding="utf-8")
    assert not check_figure_source(script, Classifier.load()).ok, "no reason, no exemption"

    (tmp_path / "fig.guard.yaml").write_text(
        "allow_source:\n  - value: '3.84'\n    why: the fixed reference value from the protocol\n",
        encoding="utf-8",
    )
    assert check_figure_source(script, Classifier.load()).ok


def test_a_script_in_a_language_with_no_lexer_says_it_was_not_read(tmp_path: Path) -> None:
    """An empty report reads as "checked and clean". `.jl` was getting one."""
    script = tmp_path / "fig.jl"
    script.write_text('annotate!("ROR 3.84")\n', encoding="utf-8")
    report = check_figure_source(script, Classifier.load())
    assert "figure-source-unread" in {f.code for f in report.findings}


def test_a_vector_figure_with_no_text_layer_fails(project: Path) -> None:
    """matplotlib's default `svg.fonttype` is 'path', which draws every label as outlines.

    An SVG full of annotations then reads as empty: `figures_checked` counted it, and a
    figure nobody had read looked read. It defeated both halves of G3 at once, because a
    figure yielding no atoms is also not "drawing numbers", so its script's results check
    dropped from a failure to a warning.
    """
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.gates import check_figures

    (project / "figures" / "forest.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M 0 0 L 1 1"/></svg>',
        encoding="utf-8",
    )
    loaded, _ = load_project(project)
    _ns, results, _lit, _r = load_namespace(loaded)
    report = check_figures(loaded, results)
    assert "figure-no-text-layer" in {f.code for f in report.failures}


def test_a_raster_is_only_skipped_when_the_pairing_is_recorded(project: Path) -> None:
    """Re-render only the PNG from somewhere else and the retouched figure ships.

    Verified end to end during an adversarial review: the PNG embedded in the .docx had the
    retouched digest while the SVG that G3 inspected still showed the correct value. The
    sibling rule was an assumption about filenames.
    """
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.gates import check_figures

    png = project / "figures" / "forest.png"
    png.write_bytes(png.read_bytes() + b"retouched")

    loaded, _ = load_project(project)
    _ns, results, _lit, _r = load_namespace(loaded)
    codes_found = {f.code for f in check_figures(loaded, results).findings}
    assert "figure-render-unproven" in codes_found


def test_the_review_digest_covers_every_format_of_the_figure(project: Path) -> None:
    """G10 digested the vector, because that is the file it can read.

    The .docx embeds the raster, so the picture that actually ships was under no review
    currency at all: replace the PNG and the review stayed green. Reviewing one file and
    shipping another is the whole of that gap.
    """
    from manuscript_guard.gates.figures import content_digest

    figures = project / "figures"
    before = content_digest(figures / "forest.svg")
    png = figures / "forest.png"
    png.write_bytes(png.read_bytes() + b"retouched")
    assert content_digest(figures / "forest.svg") != before


def test_a_stale_manifest_after_the_script_changed_is_refused(project: Path) -> None:
    """One of the three things the manifest genuinely catches. See render.same_render."""
    from manuscript_guard.render import same_render

    script = project / "figures" / "forest.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    figures = project / "figures"
    assert not same_render(figures / "forest.png", figures / "forest.svg")


def test_rewriting_the_manifest_defeats_it_and_that_is_documented(project: Path) -> None:
    """Recorded as a test because the limit is easy to forget and easy to overclaim.

    The manifest, the figures and the script are all writable by whoever holds the checkout,
    so a determined author edits both the raster and the digest that vouches for it. This is
    a drift detector of the same strength as a `.sha256` sidecar, defeated the same way.
    `verify` answers that for results by re-running the analysis; nothing does for figures,
    because re-rendering is not reproducible across plotting-library versions.
    """
    import hashlib
    import json

    from manuscript_guard.render import same_render

    figures = project / "figures"
    png, svg = figures / "forest.png", figures / "forest.svg"
    png.write_bytes(png.read_bytes() + b"retouched")
    assert not same_render(png, svg), "the edit alone is caught"

    manifest = figures / "forest.render.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["outputs"]["forest.png"] = hashlib.sha256(png.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert same_render(png, svg), "editing the manifest too is not caught, by design"


def test_a_recorded_pairing_is_accepted(project: Path) -> None:
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.gates import check_figures

    loaded, _ = load_project(project)
    _ns, results, _lit, _r = load_namespace(loaded)
    codes_found = {f.code for f in check_figures(loaded, results).findings}
    assert "figure-render-unproven" not in codes_found, "the example records its own render"


@pytest.mark.parametrize(
    "snippet",
    [
        'ax.annotate("OR 3", xy=(1, 2))  # cf. Table 3 for the full comparison',
        'ax.set_title("77 reports")  # matches Figure 77 in the appendix',
        'plt.text(0, 0, "3.84 overall")  # grade 3.84 is not a thing, but shares digits',
    ],
)
def test_an_unrelated_digit_elsewhere_on_the_line_cannot_excuse_a_claim(
    tmp_path: Path, snippet: str
) -> None:
    """Candidates used to be matched to the literal by *text*, so any same-line atom
    sharing the digit string could clear it — a trailing `# cf. Table 3` classified as
    structural and the hardcoded `"OR 3"` beside it went unreported. Judged by position
    now, so what is in the comment cannot speak for what is in the string."""
    script = tmp_path / "fig.py"
    script.write_text(snippet + "\n", encoding="utf-8")
    report = check_figure_source(script, Classifier.load())
    assert not report.ok, snippet
    assert "figure-source-text-number" in {f.code for f in report.failures}


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


# ------------------------------------------- what an R or a Python figure script names by number


def _figure_source_numbers(tmp_path: Path, snippet: str, suffix: str) -> list[str]:
    """The numbers G3's script check reports in a script holding `snippet`, as it says them."""
    script = tmp_path / f"fig{suffix}"
    script.write_text(snippet + "\n", encoding="utf-8")
    return [f.message.split("'")[1] for f in check_figure_source(script, Classifier.load())
            .findings]  # fmt: skip


@pytest.mark.parametrize(
    ("snippet", "suffix"),
    [
        ('p <- p + geom_vline(xintercept = 1, linetype = "dashed", colour = "grey50")', ".R"),
        ('p <- p + theme(strip.background = element_rect(fill = "gray95"))', ".R"),
        ('p <- p + scale_colour_manual(values = c("red3", "steelblue4", "Grey100"))', ".R"),
        ('ax.plot(x, y, color="C0")\nax.axhline(0.5, color="C9")', ".py"),
        # Known gaps: a label that is, whole, a colour's name is taken for one.
        ('p <- p + labs(title = "red3")', ".R"),
    ],
)
def test_a_colour_named_with_digits_draws_no_number(
    tmp_path: Path, snippet: str, suffix: str
) -> None:
    """svglite's figures of the bisphosphonates paper (2026-11-26): `colour = "grey50"` and
    `fill = "grey95"` were each reported as a number the figure draws. A string that is one
    of R's colour names with digits (`grDevices::colors()`), or matplotlib's `C0` to `C9`
    in a Python script, names a colour."""
    assert _figure_source_numbers(tmp_path, snippet, suffix) == []


@pytest.mark.parametrize(
    ("snippet", "suffix", "reported"),
    [
        # Not one of R's names: grey stops at 100, a numbered colour at 4.
        ('p <- p + labs(title = "grey150")', ".R", ["150"]),
        ('p <- p + labs(title = "red5")', ".R", ["5"]),
        # A colour name inside drawn words is drawn words.
        ('p <- p + labs(title = "grey50 reports")', ".R", ["50"]),
        # matplotlib's names are not R's, nor R's matplotlib's.
        ('ax.set_title("grey50")', ".py", ["50"]),
        ('p <- p + labs(title = "C3")', ".R", ["3"]),
        # Known gaps: R reads "grey 50", and a grey level matplotlib takes as a string.
        ('p <- p + geom_line(colour = "grey 50")', ".R", ["50"]),
        ('ax.plot(x, y, color="0.5")', ".py", ["0.5"]),
    ],
)
def test_a_string_that_is_no_colour_name_is_still_read(
    tmp_path: Path, snippet: str, suffix: str, reported: list[str]
) -> None:
    assert _figure_source_numbers(tmp_path, snippet, suffix) == reported


@pytest.mark.parametrize(
    ("snippet", "suffix"),
    [
        ("first <- edges[1]", ".R"),
        ("second <- fits[[2]]", ".R"),
        ("rest <- edges[-1]", ".R"),
        ("first <- edges[1L]", ".R"),
        ("top <- sort(counts)[1]", ".R"),
        ("first = edges[0]", ".py"),
        ("last = edges[-1]", ".py"),
        ("cell = rows[0][1]", ".py"),
    ],
)
def test_a_number_that_is_a_whole_subscript_is_an_index(
    tmp_path: Path, snippet: str, suffix: str
) -> None:
    """`edges[1]` takes the first of the edges the script read: an index, not a number the
    figure draws or data typed into it."""
    assert _figure_source_numbers(tmp_path, snippet, suffix) == []


@pytest.mark.parametrize(
    ("snippet", "suffix", "reported"),
    [
        # Arithmetic in a subscript, and a subscript with two numbers, are read as before.
        ("last <- edges[length(edges) - 1]", ".R", ["1"]),
        ("cell <- d[1, 2]", ".R", ["1", "2"]),
        # Typed data is data, whatever subscripts it afterwards.
        ("edges <- c(0, 1, 3, 7)", ".R", ["0", "1", "3", "7"]),
        # A Python list of one number is a list, not a subscript.
        ("ticks = [1]", ".py", ["1"]),
        ("ticks = [[2]]", ".py", ["2"]),
        # Known gaps: a slice is read.
        ("some <- edges[1:3]", ".R", ["1", "3"]),
    ],
)
def test_a_number_beside_a_subscript_is_still_read(
    tmp_path: Path, snippet: str, suffix: str, reported: list[str]
) -> None:
    assert _figure_source_numbers(tmp_path, snippet, suffix) == reported


@pytest.mark.parametrize(
    ("snippet", "suffix"),
    [
        ('status <- system2("python", "record.py")\nif (status != 0) stop("not recorded")',
         ".R"),
        ('code <- system("make figures")\nstopifnot(code == 0L)', ".R"),
        ('status <- processx::run("python", "x.py")$status\nif (status != 0) stop()', ".R"),
        ('res <- processx::run("python", "x.py")\nif (res$status != 0) stop()', ".R"),
        ('if (system2("python", "x.py") != 0) stop()', ".R"),
        ('status <- system2("python", "x.py")\nif (0 != status) stop()', ".R"),
        ("rc = subprocess.call(['x'])\nif rc != 0:\n    raise SystemExit(rc)", ".py"),
        ("if subprocess.run(['x']).returncode != 0:\n    raise SystemExit", ".py"),
        ("proc = subprocess.run(['x'])\nif proc.returncode != 0:\n    raise SystemExit", ".py"),
        ("code = subprocess.run(['x']).returncode\nassert code == 0", ".py"),
        ("if os.system('make') != 0:\n    raise SystemExit", ".py"),
        # Known gaps: `stdout = TRUE` makes system2() return the output, taken for a status.
        ('said <- system2("git", "status", stdout = TRUE)\nif (said != 0) stop()', ".R"),
    ],
)  # fmt: skip
def test_a_zero_compared_with_an_exit_status_is_no_number(
    tmp_path: Path, snippet: str, suffix: str
) -> None:
    """The bisphosphonates paper's `tto.R` stopped when the render record's Python call
    failed, and `!= 0` on its exit status was reported as a number bound to nothing."""
    assert _figure_source_numbers(tmp_path, snippet, suffix) == []


@pytest.mark.parametrize(
    ("snippet", "suffix", "reported"),
    [
        ('if (n_cases != 0) stop("no cases")', ".R", ["0"]),
        ("if count == 0:\n    raise SystemExit", ".py", ["0"]),
        # A status compared with another number than 0 is read: it is not "did it fail".
        ('status <- system2("python", "x.py")\nif (status == 2) stop()', ".R", ["2"]),
        # Named in an argument of a call, a status is no status of the script's.
        ('f(status = system2("x"))\nif (status != 0) stop()', ".R", ["0"]),
        # Known gaps: calls not known to return a status.
        ("proc = subprocess.Popen(['x'])\nif proc.wait() != 0:\n    raise SystemExit", ".py",
         ["0"]),
    ],
)
def test_a_zero_compared_with_anything_else_is_still_read(
    tmp_path: Path, snippet: str, suffix: str, reported: list[str]
) -> None:
    assert _figure_source_numbers(tmp_path, snippet, suffix) == reported


# ------------------------------------------------------- what an SVG figure draws as text

_SVGLITE_STYLE = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 720.00 360.00'>\n"
    "<defs>\n  <style type='text/css'><![CDATA[\n"
    "    line, polyline, polygon, path, rect, circle {\n"
    "      fill: none;\n      stroke: #000000;\n      stroke-linecap: round;\n"
    "      stroke-linejoin: round;\n      stroke-miterlimit: 10.00;\n    }\n"
    "  ]]></style>\n</defs>\n"
    "<script type='text/javascript'>var width = 640;</script>\n"
    "<rect width='100%' height='100%' style='stroke: none; fill: #FFFFFF;'/>\n"
    "<text x='12.50' y='30.25' style='font-size: 8.80px;'>Reports</text>\n"
    "<text x='12.50' y='60.25'>3.84</text>\n"
    "</svg>\n"
)


def test_an_svg_s_style_and_script_are_not_its_drawn_text(tmp_path: Path) -> None:
    """svglite writes `stroke: #000000; stroke-miterlimit: 10.00` in a `<style>` at the
    head of every SVG, and G3 read them as numbers drawn in the figure: the bisphosphonates
    paper allowlisted `000000` and `10.00` in its sidecar to get past them. A `<style>` and
    a `<script>` draw nothing, and an attribute's value, a coordinate or an inline style, is
    not read either: only the text of the elements that hold it."""
    from manuscript_guard.gates.figures import _extract_text

    figure = tmp_path / "forest.svg"
    figure.write_text(_SVGLITE_STYLE, encoding="utf-8")
    assert _extract_text(figure).split("\n") == ["Reports", "3.84"]


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


def test_numbered_labels_in_a_figure_are_still_numbering(project: Path) -> None:
    """A figure's text is one text element per line, not Markdown, so every line starts a
    block of its own. Read as Markdown, the lines after the first would be the wrapped lines
    of one paragraph, and "8. Hepatic" in a legend would stop counting as numbering when
    `ordered-list-marker` learned that a list cannot interrupt a paragraph."""
    svg = project / "figures" / "forest.svg"
    text = svg.read_text(encoding="utf-8")
    legend = "<text>7. Renal</text><text>8. Hepatic</text>"
    svg.write_text(text.replace("</svg>", legend + "</svg>", 1), encoding="utf-8")
    unbound = [
        f.message for f in figure_report(project).findings if f.code == "figure-number-unbound"
    ]
    assert not any("'7'" in m or "'8'" in m for m in unbound), unbound
