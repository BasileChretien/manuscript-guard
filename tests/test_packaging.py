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


# Left in a source tree by a file browser, and named in .gitignore, so the wheel build leaves
# them out too. Only names that file lists: another would hide a file that does ship.
DESKTOP_LITTER = {".DS_Store", "Thumbs.db"}


def shipped_files() -> list[Path]:
    return [
        path
        for path in sorted(PACKAGE.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and path.name not in DESKTOP_LITTER
    ]


@needs_git
def test_no_file_the_package_ships_is_ignored_by_git():
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    files = shipped_files()
    assert any(path.suffix == ".yaml" for path in files), "the package data has moved"
    assert ignored_by_git(REPO, files) == []


# ---------------------------------------------------------------- the wheel's own file list
#
# `.github/scripts/check_wheel_files.py` is what CI's wheel job runs on the built wheel. A
# fresh project reads only some of the package's data, so using the wheel notices some
# missing files and not others (ten of the 32 data files could be dropped from it and the job
# still passed). Comparing the two lists notices every one.


def load_wheel_check():
    import importlib.util

    path = REPO / ".github" / "scripts" / "check_wheel_files.py"
    spec = importlib.util.spec_from_file_location("check_wheel_files", path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_wheel(directory: Path, names: list[str]) -> Path:
    import zipfile

    path = directory / "manuscript_guard-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")
        archive.writestr("manuscript_guard-9.9.9.dist-info/METADATA", "")
    return path


TRACKED = [
    "manuscript_guard/__init__.py",
    "manuscript_guard/build/zotero_word.lua",
    "manuscript_guard/data/plot_params.yaml",
]


def test_a_wheel_holding_every_tracked_file_passes(tmp_path: Path):
    check = load_wheel_check()
    wheel = fake_wheel(tmp_path, TRACKED)
    assert check.compare(check.wheel_files(wheel), set(TRACKED)) == ([], [])


@pytest.mark.parametrize("dropped", TRACKED)
def test_a_wheel_missing_one_file_fails_and_names_it(dropped: str, tmp_path: Path, capsys):
    """Each of these was a file the fresh-project run never reads."""
    check = load_wheel_check()
    wheel = fake_wheel(tmp_path, [name for name in TRACKED if name != dropped])
    missing, unexpected = check.compare(check.wheel_files(wheel), set(TRACKED))
    assert (missing, unexpected) == ([dropped], [])
    assert check.report(missing, unexpected) != 0
    assert dropped in capsys.readouterr().out


def test_a_wheel_holding_a_file_git_does_not_track_fails_too(tmp_path: Path, capsys):
    """A generated checklist profile is such a file, and it carries text that may not be
    redistributed."""
    check = load_wheel_check()
    stray = "manuscript_guard/profiles/reporting/STROBE.yaml"
    wheel = fake_wheel(tmp_path, [*TRACKED, stray])
    missing, unexpected = check.compare(check.wheel_files(wheel), set(TRACKED))
    assert (missing, unexpected) == ([], [stray])
    assert check.report(missing, unexpected) != 0
    assert stray in capsys.readouterr().out


@needs_git
def test_the_tracked_files_are_what_git_lists_for_the_package():
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = load_wheel_check().tracked_files(REPO)
    assert "manuscript_guard/__init__.py" in tracked
    assert "manuscript_guard/build/zotero_word.lua" in tracked
    assert not any(name.startswith("src/") for name in tracked), "paths are the wheel's"
    # The skills are tracked under plugin/ and taken into the package when the wheel is built.
    assert "manuscript_guard/skills/project-setup/SKILL.md" in tracked
    assert not any(name.startswith("plugin/") for name in tracked)


def test_a_wheel_without_the_skills_fails_and_names_one(tmp_path: Path, capsys):
    """`install-skills` copies them out of the installed package, so a wheel built without
    them leaves that command with nothing to copy."""
    check = load_wheel_check()
    skill = "manuscript_guard/skills/project-setup/SKILL.md"
    assert check.in_the_wheel("plugin/skills/project-setup/SKILL.md") == skill
    assert check.in_the_wheel("src/manuscript_guard/__init__.py") == TRACKED[0]
    wheel = fake_wheel(tmp_path, TRACKED)
    missing, unexpected = check.compare(check.wheel_files(wheel), {*TRACKED, skill})
    assert (missing, unexpected) == ([skill], [])
    assert check.report(missing, unexpected) != 0
    assert skill in capsys.readouterr().out


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
