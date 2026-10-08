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


# ---------------------------------------------------------------- when a push is a release
#
# `.github/scripts/release_decision.py` is what publish.yml asks before it builds. PyPI
# keeps a version for good and refuses a number twice, so what is published, and when, is
# held here, where each case can be seen.


def load_release_decision():
    import importlib.util

    path = REPO / ".github" / "scripts" / "release_decision.py"
    spec = importlib.util.spec_from_file_location("release_decision", path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def never_asked(version: str) -> bool:
    raise AssertionError(f"PyPI was asked about {version}, and need not have been")


def test_a_push_that_raises_the_version_to_one_pypi_lacks_is_a_release():
    decision = load_release_decision()
    publish, why = decision.decide("0.2.431", "0.2.430", lambda version: False)
    assert publish and "0.2.430 to 0.2.431" in why


def test_a_push_that_leaves_the_version_alone_releases_nothing_and_asks_nobody():
    """The code between a merge and its bump carries the old number: it is not that release,
    whether or not the number reached PyPI."""
    decision = load_release_decision()
    publish, why = decision.decide("0.2.430", "0.2.430", never_asked)
    assert not publish and "left the version at 0.2.430" in why


def test_a_version_pypi_already_has_is_not_released_again():
    decision = load_release_decision()
    publish, why = decision.decide("0.2.431", "0.2.430", lambda version: True)
    assert not publish and "already on PyPI" in why


def test_a_push_whose_commit_before_cannot_be_read_releases_nothing_and_fails():
    """As after a forced push, the one case with no commit to compare with. Nothing then
    says that this push is the one that raised the number, and PyPI's lacking it is no proof
    of that. So PyPI is not asked, and the run fails, where somebody sees it."""
    decision = load_release_decision()
    with pytest.raises(SystemExit, match="cannot be read"):
        decision.decide("0.2.431", None, never_asked)


@pytest.mark.parametrize(
    ("now", "before"),
    [
        ("0.2.430", "0.2.431"),  # a bump taken back
        ("0.2.9", "0.2.10"),  # below as numbers, above as text
        ("0.1.999", "0.2.0"),
        ("0.2", "0.2.0"),  # the same version written short, and long
        ("0.2.431.0", "0.2.431"),
    ],
)
def test_a_version_that_did_not_rise_is_not_released_and_pypi_is_not_asked(now: str, before: str):
    """A number that went down is one PyPI lacks only by chance, or has already: before the
    first release every number was one it lacked, so a bump taken back was a release."""
    decision = load_release_decision()
    publish, why = decision.decide(now, before, never_asked)
    assert not publish and "not above" in why


def test_a_version_is_compared_as_numbers():
    decision = load_release_decision()
    assert decision.decide("0.2.10", "0.2.9", lambda version: False)[0]
    assert decision.decide("0.3", "0.2.999", lambda version: False)[0]
    assert decision.decide("1.0.0", "0.99", lambda version: False)[0]


@pytest.mark.parametrize(("code", "there"), [(200, True), (404, False)])
def test_pypi_s_yes_and_no_are_read_as_such(code: int, there: bool):
    decision = load_release_decision()
    asked = []

    def status(url: str) -> int:
        asked.append(url)
        return code

    assert decision.on_pypi("0.2.431", status) is there
    assert asked == ["https://pypi.org/pypi/manuscript-guard/0.2.431/json"]


@pytest.mark.parametrize("code", [500, 503, 429, 301])
def test_an_answer_that_is_neither_stops_the_release(code: int):
    decision = load_release_decision()
    with pytest.raises(SystemExit, match="nothing is published"):
        decision.on_pypi("0.2.431", lambda url: code)


def test_the_version_is_the_one_line_of_digits_and_dots():
    decision = load_release_decision()
    assert decision.version_in((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert decision.version_in('[project]\nversion = "1.2.3"\n') == "1.2.3"
    for unreadable in (
        "[project]\nname = 'x'\n",
        '[project]\nversion = "1.2.3"\n[tool.x]\nversion = "9.9"\n',
        '[project]\nversion = "1.2.3-rc1"\n',
        '[project]\nversion = "1.2.3\nextra"\n',
    ):
        with pytest.raises(SystemExit):
            decision.version_in(unreadable)


@needs_git
def test_the_commit_before_is_read_from_git_and_no_commit_reads_as_none():
    decision = load_release_decision()
    assert decision.version_at("0" * 40, REPO) is None
    assert decision.version_at("", REPO) is None
    assert decision.version_at("not-a-commit", REPO) is None
    assert decision.version_at("HEAD", REPO) == decision.version_in(
        subprocess.run(
            ["git", "show", "HEAD:pyproject.toml"],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    )


def test_the_script_prints_the_two_lines_the_workflow_reads(monkeypatch, capsys):
    decision = load_release_decision()
    monkeypatch.setattr(decision, "on_pypi", lambda version: False)
    monkeypatch.setattr(decision, "version_at", lambda commit, checkout: "0.0.1")
    assert decision.main(["release_decision.py", "--before", "abc", "--checkout", str(REPO)]) == 0
    printed = capsys.readouterr()
    version = decision.version_in((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert printed.out.splitlines() == ["publish=true", f"version={version}"]
    assert "releasing it" in printed.err


def test_with_no_commit_before_the_script_prints_nothing_for_the_workflow(monkeypatch, capsys):
    """What the script prints goes into the workflow's outputs, so a run that cannot decide
    must leave them empty: the jobs after it then have nothing to build or to upload."""
    decision = load_release_decision()
    monkeypatch.setattr(decision, "on_pypi", never_asked)
    with pytest.raises(SystemExit) as stopped:
        decision.main(["release_decision.py", "--before", "", "--checkout", str(REPO)])
    assert stopped.value.code not in (0, None)
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------- where the release may run
#
# The upload and the tag are what the workflow file allows, and nothing runs it before a
# real release, so its shape is held here: when it starts, in which repository, and which
# job may do what.


def release_workflow() -> dict:
    import yaml

    path = REPO / ".github" / "workflows" / "publish.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_release_starts_on_a_push_to_main_of_this_repository_and_on_nothing_else():
    """Not by hand: a run by hand builds whatever main holds at that moment. Not in a fork:
    one with Actions on would tag itself and make its own release before PyPI, which trusts
    this repository alone, refused the upload."""
    import re

    workflow = release_workflow()
    # YAML 1.1 reads the key `on` as true.
    assert workflow[True] == {"push": {"branches": ["main"], "paths": ["pyproject.toml"]}}

    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    here = re.search(r'^Homepage = "https://github\.com/([^"]+)"$', pyproject, re.MULTILINE)
    first = workflow["jobs"]["decide"]
    assert f"github.repository == '{here.group(1)}'" in first["if"]
    assert "github.ref == 'refs/heads/main'" in first["if"]
    assert "||" not in first["if"], "either condition alone would let a run start"

    # Every other job waits for the one that decides, so none starts where it did not.
    for name, job in workflow["jobs"].items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert name == "decide" or "decide" in needs, name


def test_only_the_upload_asks_for_an_identity_and_only_the_release_job_may_write():
    workflow = release_workflow()
    assert workflow["permissions"] == {}, "a job is given what it needs, and no more"
    granted = {name: job.get("permissions", {}) for name, job in workflow["jobs"].items()}
    assert [name for name, given in granted.items() if "id-token" in given] == ["publish"]
    assert [name for name, given in granted.items() if "write" in given.values()] == [
        "release",
        "publish",
    ]
    assert granted["release"] == {"contents": "write"}
    assert granted["publish"] == {"id-token": "write"}
