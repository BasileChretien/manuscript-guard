"""The manuscript's format and its files (`text/reader.py`): the seam the gates are taught
LaTeX through, one at a time (DESIGN.md, "LaTeX manuscripts")."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts.project import load_project
from manuscript_guard.gates.review import file_digests
from manuscript_guard.text.reader import LATEX, MARKDOWN, Reader, manuscript_format


def _write(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (("main.md",), MARKDOWN),
        (("main.tex",), LATEX),
        (("main.tex", "methods.tex"), LATEX),
        # Both: Markdown, as every project was, and G0 refuses the folder (`two-formats`).
        (("main.md", "main.tex"), MARKDOWN),
        # No entry file: Markdown, so a folder of `.md` files reads as it always has.
        (("intro.md",), MARKDOWN),
        (("intro.tex",), MARKDOWN),
        ((), MARKDOWN),
    ],
)
def test_the_format_is_read_from_the_entry_file(
    tmp_path: Path, names: tuple[str, ...], expected: str
) -> None:
    _write(tmp_path, *names)
    assert manuscript_format(tmp_path) == expected


def test_a_latex_manuscript_lists_its_tex_files_as_a_markdown_one_lists_its_md(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "main.tex", "results.tex", "notes.md", "_drafts/old.tex", ".hidden/x.tex",
        "supplementary/main.tex", "supplementary/s1.tex",
    )  # fmt: skip
    reader = Reader(tmp_path, LATEX)
    names = [p.relative_to(tmp_path).as_posix() for p in reader.files()]
    assert names == ["main.tex", "results.tex", "supplementary/main.tex", "supplementary/s1.tex"]
    main_text = [p.relative_to(tmp_path).as_posix() for p in reader.files(main_text_only=True)]
    assert main_text == ["main.tex", "results.tex"]
    ordered = reader.printed_order([tmp_path / "results.tex", tmp_path / "main.tex"],
                                   supplementary=False)  # fmt: skip
    assert [p.name for p in ordered] == ["main.tex", "results.tex"]


def test_a_review_of_a_latex_manuscript_is_tied_to_its_tex_files(project: Path) -> None:
    folder = project / "manuscript"
    for path in folder.rglob("*.md"):
        path.unlink()
    _write(folder, "main.tex", "supplementary/s1.tex")
    loaded, _ = load_project(project)
    assert sorted(file_digests(loaded)) == ["main.tex", "supplementary/s1.tex"]
