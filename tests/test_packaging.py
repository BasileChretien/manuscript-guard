"""The package as pip delivers it, not as an editable install shows it.

An editable install reads `src/` where it stands, so a file that git ignores works for
whoever wrote it and is missing for everyone else. That already happened once: `.gitignore`
matched `build/` at any depth and dropped `src/manuscript_guard/build/` from the repository,
and every check passed locally. `pip install git+https://...` builds from a clone, which
holds only what git tracks, so a file in the package that git ignores is a file no user has.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "manuscript_guard"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def ignored_by_git(root: Path, files: list[Path]) -> list[str]:
    """The files, relative to `root`, that the repository's ignore rules would drop."""
    listed = "\n".join(path.relative_to(root).as_posix() for path in files)
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=root,
        input=listed,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # 0: some are ignored, 1: none are. Anything else is git failing, not an answer.
    assert result.returncode in (0, 1), result.stderr
    return result.stdout.split()


def shipped_files() -> list[Path]:
    return [
        path
        for path in sorted(PACKAGE.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


@needs_git
def test_no_file_the_package_ships_is_ignored_by_git():
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    files = shipped_files()
    assert any(path.suffix == ".yaml" for path in files), "the package data has moved"
    assert ignored_by_git(REPO, files) == []


@needs_git
def test_the_check_catches_a_directory_an_ignore_rule_swallows(tmp_path: Path):
    """A bare `build/` in .gitignore matches `pkg/build/` too, which is how the package lost
    its own build module without a local test noticing."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    kept = tmp_path / "pkg" / "__init__.py"
    lost = tmp_path / "pkg" / "build" / "document.py"
    for path in (kept, lost):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    assert ignored_by_git(tmp_path, [kept, lost]) == ["pkg/build/document.py"]
