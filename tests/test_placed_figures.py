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


# ----------------------------------------------------------- round 1 of #630's review


def _link(link: Path, target: Path) -> None:
    """A link to a folder: a junction on Windows, which needs no privilege, else a symlink
    (`tests/test_vault.py`, #409)."""
    import os

    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_a_definitions_body_places_no_picture(tmp_path: Path) -> None:
    """Round 1 of #630: a picture in a macro the paper never uses is not printed, and was
    asked for a review. A definition's body places nothing (Known gaps: nor where it is
    used)."""
    root = tmp_path / "p"
    manuscript = _latex_project(root, "\\newcommand{\\logo}{\\includegraphics{logo}}\nText.\n")
    _touch(manuscript / "figs" / "logo.pdf")
    assert placed_files(load_project(root)[0]) == []


def test_a_figure_through_a_link_out_of_the_project_is_checked_and_named(
    tmp_path: Path,
) -> None:
    """Round 1 of #630: a figure in a shared folder the manuscript reaches through a link was
    dropped without a word, though pandoc and TeX find it. It is checked where the link
    leads, known by its path through the link, and named in a note."""
    from manuscript_guard.gates.placed_figures import check_placed

    shared = tmp_path / "shared"
    _touch(shared / "chart.pdf")
    root = tmp_path / "p"
    _latex_project(root, "\\includegraphics{../linked/chart}\n")
    try:
        _link(root / "linked", shared)
    except OSError:
        pytest.skip("could not make a link to a folder here")
    project = load_project(root)[0]
    [placed] = placed_files(project)
    assert placed.name == "linked/chart.pdf" and placed.outside
    said = {f.code: f for f in check_placed(project).findings}
    assert said["figure-outside-project"].severity == "info"
    assert "linked/chart.pdf" in said["figure-outside-project"].message


def test_a_figures_files_are_found_whatever_the_case_of_their_suffix(tmp_path: Path) -> None:
    """Round 1 of #630: files were looked up by lower-case suffixes, so on Linux `Chart.PDF`
    was never found and its colours passed unread."""
    from manuscript_guard.gates.figure_files import _files_of

    _touch(tmp_path / "Chart.PDF")
    _touch(tmp_path / "Chart.png", b"\x89PNG\r\n\x1a\n")
    _touch(tmp_path / "Chart.guard.yaml", b"alt: x\n")
    assert [path.name for path in _files_of(tmp_path, "Chart")] == ["Chart.png", "Chart.PDF"]


def test_a_placed_webp_is_said_to_be_unread_for_its_colours(tmp_path: Path) -> None:
    """A `.webp` is a raster no journal's artwork rules name: its review and its text are
    asked for, and its colours are said to be unread, as a PNG's are."""
    from manuscript_guard.cli import main as cli
    from manuscript_guard.gates.figure_colours import check_figure_colours

    root = tmp_path / "p"
    assert cli(["init", str(root)]) == 0
    main = root / "manuscript" / "main.md"
    main.write_text("# Results\n\n![A chart.](manuscript/figs/chart.webp)\n", encoding="utf-8")
    _touch(root / "manuscript" / "figs" / "chart.webp", b"RIFF\x00\x00\x00\x00WEBP")
    said = [(f.code, f.severity) for f in check_figure_colours(load_project(root)[0]).findings]
    assert said == [("figure-colours-unread", "info")]


def test_record_figure_takes_an_emitted_figure_in_a_folder_by_its_name_there(
    tmp_path: Path,
) -> None:
    """Round 1 of #630, a regression: `--record-figure km/curve` for `figures/km/curve.svg`
    worked on main, and was read as a path from the project's root. An emitted figure is
    matched as main matched it first; a bare name both an emitted and a placed figure have
    names both."""
    from manuscript_guard.record import RecordError, write_figure_review

    root = tmp_path / "p"
    manuscript = _latex_project(root, "\\includegraphics{curve}\n")
    _touch(root / "figures" / "km" / "curve.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    _touch(manuscript / "figs" / "curve.pdf")
    project = load_project(root)[0]
    with pytest.raises(RecordError, match="2 figures are called 'curve'"):
        write_figure_review(project, "curve", verdict="pass", reviewed_by="A. Reader")
    written = write_figure_review(project, "km/curve", verdict="pass", reviewed_by="A. Reader")
    assert written.path == root / "figures" / "km" / "curve.review.yaml"
    written = write_figure_review(project, "manuscript/figs/curve.pdf", verdict="pass",
                                  reviewed_by="A. Reader")  # fmt: skip
    assert written.path == manuscript / "figs" / "curve.review.yaml"


def _markdown_placing(project: Path, alt: str | None) -> None:
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace("{{figure.forest}}\n", "{{figure.forest}}\n\n"
                                 "![Counts by year.](manuscript/figs/chart.svg)\n", 1),
                    encoding="utf-8")  # fmt: skip
    _touch(project / "manuscript" / "figs" / "chart.svg",
           b"<svg xmlns='http://www.w3.org/2000/svg'/>")  # fmt: skip
    guard = project / "manuscript" / "figs" / "chart.guard.yaml"
    if alt is None:
        guard.unlink(missing_ok=True)
    else:
        guard.write_text(f"alt: {alt}\n", encoding="utf-8")


def test_alt_text_md_does_not_say_the_document_carries_a_placed_figures_text(
    project: Path,
) -> None:
    """Round 1 of #630: `alt-text.md` said the document carries each figure's text in its
    picture, and a placed figure's is not written there: pandoc writes the image's own
    description, or nothing."""
    from manuscript_guard.build.submission import alt_texts

    _markdown_placing(project, "Two lines, one rising.")
    written = alt_texts(load_project(project)[0])
    head, _, placed = written.partition("## manuscript/figs/chart.svg")
    assert "Two lines, one rising." in placed
    assert "not in the document" in " ".join(placed.split())
    assert "carries the same text in each picture placed by its binding" in " ".join(
        head.split()
    )


def test_a_placed_figures_alternative_text_leaves_the_manuscript_digest_alone(
    project: Path,
) -> None:
    """Round 1 of #630: the digest a sealed review is held to took in a placed figure's
    guard-file text, which the build writes into no picture, so writing it made a sealed
    review stale with the document unchanged."""
    from manuscript_guard.gates.review import document_digest

    _markdown_placing(project, None)
    before = document_digest(load_project(project)[0])
    (project / "manuscript" / "figs" / "chart.guard.yaml").write_text(
        "alt: Two lines, one rising.\n", encoding="utf-8"
    )
    assert document_digest(load_project(project)[0]) == before


# --------------------------------------------------- the fix-only round of #630's review


@pytest.mark.parametrize("how", ["absolute", "climbing"])
def test_a_figure_written_outside_the_project_is_named_by_its_file_alone(
    project: Path, tmp_path: Path, how: str
) -> None:
    """The fix-only round of #630: a figure path written outside the project, absolutely or
    with "..", was written into `alt-text.md` and the note as a path that climbs out of the
    project, the author's own folders with it. Such a file is named by its file name."""
    from manuscript_guard.build.submission import alt_texts
    from manuscript_guard.gates.placed_figures import check_placed

    shared = tmp_path / "someone_private_home" / "shared"
    _touch(shared / "x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    (shared / "x.guard.yaml").write_text("alt: Two lines.\n", encoding="utf-8")
    target = shared.joinpath("x.svg").as_posix() if how == "absolute" else (
        Path("..") / "someone_private_home" / "shared" / "x.svg").as_posix()
    if how == "climbing":
        assert (project / target).resolve() == (shared / "x.svg").resolve(), target
    main = project / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8").replace(
        "{{figure.forest}}\n", f"{{{{figure.forest}}}}\n\n![Two lines.](<{target}>)\n", 1),
        encoding="utf-8")  # fmt: skip
    loaded = load_project(project)[0]
    [placed] = [found for found in placed_files(loaded) if found.path.stem == "x"]
    assert placed.name == "x.svg" and placed.outside
    written = alt_texts(loaded)
    assert "## x.svg" in written and "someone_private_home" not in written, written
    [note] = [f for f in check_placed(loaded).findings if f.code == "figure-outside-project"]
    assert "someone_private_home" not in note.message
    assert "written or linked outside the project" in note.message


def test_a_picture_added_after_a_check_is_found_by_the_next(tmp_path: Path) -> None:
    """The fix-only round of #630: what the manuscript names is read once per content of its
    sources, and the files it names are found again on each call, so a PDF saved beside the
    PNG after one check is the picture the next one finds."""
    root = tmp_path / "p"
    manuscript = _latex_project(root, "\\includegraphics{chart}\n")
    _touch(manuscript / "figs" / "chart.png", b"\x89PNG\r\n\x1a\n")
    project = load_project(root)[0]
    assert [placed.name for placed in placed_files(project)] == ["manuscript/figs/chart.png"]
    _touch(manuscript / "figs" / "chart.pdf")
    assert [placed.name for placed in placed_files(project)] == ["manuscript/figs/chart.pdf"]
