"""The figure files a paper places the ordinary way (`gates/placed_figures.py`): found as
LaTeX's graphicx and pandoc find them, and recorded beside the file.

The real case is arXiv 2409.10841, a LaTeX paper whose four results figures are placed with
`\\includegraphics` of names with no extension, which no figure check read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.gates.placed_figures import (
    graphics_folders,
    images,
    placed_files,
    resolve_graphic,
)


def _touch(path: Path, data: bytes = b"%PDF-1.4\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_a_name_with_no_extension_takes_the_first_extension_graphicx_tries(
    tmp_path: Path,
) -> None:
    """pdfTeX's graphicx tries `.pdf` before `.png`, each in every folder before the next."""
    png = _touch(tmp_path / "figs" / "chart.png")
    pdf = _touch(tmp_path / "figs" / "chart.pdf")
    here = _touch(tmp_path / "chart.pdf")
    for found in (here, pdf, png):
        assert resolve_graphic(tmp_path, "main.tex", "", ["figs/"], "chart") == found
        found.unlink()
    assert resolve_graphic(tmp_path, "main.tex", "", ["figs/"], "chart") is None


def test_a_path_is_found_through_graphicspath_and_from_the_supplements_folder(
    tmp_path: Path,
) -> None:
    hit = _touch(tmp_path / "supplementary" / "plots" / "s1.pdf")
    assert resolve_graphic(tmp_path, "supplementary/main.tex", "", ["plots/"], "s1") == hit
    assert resolve_graphic(tmp_path, "main.tex", "", ["plots/"], "s1") is None
    assert resolve_graphic(tmp_path, "main.tex", "", [], "nothing.pdf") is None


def test_graphicspath_is_read_in_order_and_a_commented_one_is_not() -> None:
    texts = ["\\graphicspath{{figs/}{img/}}\n% \\graphicspath{{old/}}\n",
             "\\graphicspath{ {img/} {more/} }"]  # fmt: skip
    assert graphics_folders(texts) == ["figs/", "img/", "more/"]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("![A chart.](figs/a.svg)\n", ["figs/a.svg"]),
        ('![](<figs/a b.png> "title"){width=50%}\n', ["figs/a b.png"]),
        ("![](figs/a%20b.png)\n", ["figs/a b.png"]),
        ("![A link](https://example.org/a.png)\n", []),
        ("`![](figs/a.svg)`\n", []),
        ("<!-- ![](figs/a.svg) -->\n", []),
        ("```\n![](figs/a.svg)\n```\n", []),
        ("[a link](figs/a.svg)\n", []),
    ],
    ids=["plain", "angled", "escaped", "web", "code", "comment", "fence", "link"],
)
def test_a_markdown_image_is_read_where_pandoc_prints_it(text: str, found: list[str]) -> None:
    assert images(text) == found


def _latex_project(root: Path, body: str) -> Path:
    from manuscript_guard.cli import main

    assert main(["init", str(root), "--latex"]) == 0
    manuscript = root / "manuscript"
    (manuscript / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{graphicx}\n\\graphicspath{{figs/}}\n"
        f"\\begin{{document}}\n{body}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    return manuscript


def test_what_tex_does_not_print_places_no_figure(tmp_path: Path) -> None:
    root = tmp_path / "p"
    manuscript = _latex_project(
        root,
        "\\includegraphics{shown}\n% \\includegraphics{commented}\n"
        "\\iffalse\n\\includegraphics{skipped}\n\\fi\n"
        "\\newcommand{\\fig}[1]{\\includegraphics{#1}}\n",
    )
    for name in ("shown", "commented", "skipped"):
        _touch(manuscript / "figs" / f"{name}.pdf")
    project = load_project(root)[0]
    assert [placed.name for placed in placed_files(project)] == ["manuscript/figs/shown.pdf"]


def test_a_figure_placed_in_two_formats_is_one_figure(tmp_path: Path) -> None:
    root = tmp_path / "p"
    manuscript = _latex_project(root, "\\includegraphics{a.pdf}\n\\includegraphics{a.png}\n")
    _touch(manuscript / "figs" / "a.pdf")
    _touch(manuscript / "figs" / "a.png", b"\x89PNG\r\n\x1a\n")
    project = load_project(root)[0]
    assert [placed.name for placed in placed_files(project)] == ["manuscript/figs/a.pdf"]


def test_record_figure_takes_a_placed_figures_path_or_its_name(tmp_path: Path) -> None:
    from manuscript_guard.record import RecordError, write_figure_review

    root = tmp_path / "p"
    manuscript = _latex_project(root, "\\includegraphics{a}\n\\includegraphics{other/a}\n")
    _touch(manuscript / "figs" / "a.pdf")
    _touch(manuscript / "figs" / "other" / "a.pdf")
    project = load_project(root)[0]
    with pytest.raises(RecordError, match="2 figures are called 'a'"):
        write_figure_review(project, "a", verdict="pass", reviewed_by="A. Reader")
    written = write_figure_review(project, "manuscript/figs/other/a.pdf", verdict="pass",
                                  reviewed_by="A. Reader")  # fmt: skip
    assert written.path == manuscript / "figs" / "other" / "a.review.yaml"
    with pytest.raises(RecordError, match="no reviewable figure called 'b'"):
        write_figure_review(project, "b", verdict="pass", reviewed_by="A. Reader")
