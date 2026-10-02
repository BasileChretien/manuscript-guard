"""Copying the skills to a folder an agent tool reads, and saying when the copy is stale.

Claude Code and Codex install the skills as a plugin. Gemini CLI, Mistral Vibe and Kimi Code
CLI have no such route here and read a folder of skills: `.agents/skills`, in a project or in
the user's home. `manuscript-guard install-skills` copies the skills there.

Three things have to hold, and each has a test that fails if it stops holding:

* the copy is the skills as the plugin has them, byte for byte, from one source;
* nothing that this tool did not write is ever written over or removed;
* a copy from another release is named by `check` and `build`, and changes nothing else.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from manuscript_guard import __version__, skillcopy
from manuscript_guard.cli import main

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "plugin" / "skills"


def tree(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def skills_in(folder: Path) -> dict[str, bytes]:
    """What a folder holds, without the stamp."""
    return {name: body for name, body in tree(folder).items() if name != skillcopy.STAMP}


def stamp_of(folder: Path) -> dict:
    return json.loads((folder / skillcopy.STAMP).read_text(encoding="utf-8"))


@pytest.fixture
def older(tmp_path: Path, monkeypatch) -> Path:
    """A source as an earlier release shipped it: one skill worded differently, and one that
    has since been dropped."""
    source = tmp_path / "older-release"
    shutil.copytree(SOURCE, source)
    setup = source / "project-setup" / "SKILL.md"
    setup.write_bytes(setup.read_bytes() + b"\nAn older sentence.\n")
    dropped = source / "since-dropped"
    dropped.mkdir()
    (dropped / "SKILL.md").write_bytes(b"---\nname: since-dropped\ndescription: Use never.\n---\n")
    return source


def install_from(source: Path, version: str, folder: Path, monkeypatch) -> skillcopy.Copied:
    with monkeypatch.context() as patch:
        patch.setattr(skillcopy, "shipped", lambda: source)
        patch.setattr(skillcopy, "__version__", version)
        return skillcopy.install(folder)


# ---------------------------------------------------------------- one source


def test_the_skills_a_checkout_copies_are_the_plugins_own() -> None:
    """In a checkout there is one copy of the skills, and it is the plugin's."""
    assert skillcopy.shipped().resolve() == SOURCE.resolve()


def test_the_wheel_carries_the_plugins_skills_and_no_copy_is_kept_in_the_package() -> None:
    """The wheel takes `plugin/skills` as `manuscript_guard/skills` when it is built. A copy
    kept under `src/` instead would be a second source, free to drift from the first."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    heading = "[tool.hatch.build.targets.wheel.force-include]"
    assert heading in pyproject
    section = pyproject.split(heading, 1)[1].split("\n[", 1)[0]
    forced = re.findall(r'^"([^"]+)"\s*=\s*"([^"]+)"', section, re.MULTILINE)
    assert forced == [("plugin/skills", "manuscript_guard/skills")]
    assert not (REPO / "src" / "manuscript_guard" / "skills").exists()


def test_a_built_wheel_holds_every_skill_file_as_the_plugin_has_it(tmp_path: Path) -> None:
    import zipfile

    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-q", "-w", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert built.returncode == 0, built.stdout + built.stderr
    (wheel,) = tmp_path.glob("*.whl")
    prefix = "manuscript_guard/skills/"
    with zipfile.ZipFile(wheel) as archive:
        carried = {
            name[len(prefix) :]: archive.read(name)
            for name in archive.namelist()
            if name.startswith(prefix) and not name.endswith("/")
        }
    assert carried == tree(SOURCE)


# ---------------------------------------------------------------- the copy


def test_the_copy_is_the_skills_byte_for_byte_with_a_stamp(tmp_path: Path) -> None:
    folder = tmp_path / ".agents" / "skills"
    done = skillcopy.install(folder)

    assert skills_in(folder) == tree(SOURCE)
    names = sorted(path.parent.name for path in SOURCE.glob("*/SKILL.md"))
    assert list(done.written) == names and not done.left and not done.removed

    stamp = stamp_of(folder)
    assert stamp["schema"] == skillcopy.SCHEMA
    assert stamp["version"] == __version__
    assert sorted(stamp["skills"]) == names
    body = (folder / "project-setup" / "SKILL.md").read_bytes()
    assert stamp["skills"]["project-setup"] == {"SKILL.md": hashlib.sha256(body).hexdigest()}


def test_copying_twice_changes_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    before = tree(folder)
    again = skillcopy.install(folder)
    assert tree(folder) == before
    assert not again.left and not again.removed


def test_a_newer_release_replaces_what_an_older_one_copied(
    tmp_path: Path, older: Path, monkeypatch
) -> None:
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)
    assert b"An older sentence." in (folder / "project-setup" / "SKILL.md").read_bytes()
    assert (folder / "since-dropped" / "SKILL.md").is_file()
    assert stamp_of(folder)["version"] == "0.0.1"

    done = skillcopy.install(folder)
    assert skills_in(folder) == tree(SOURCE), "the dropped skill is gone, the reworded one new"
    assert done.removed == ("since-dropped",) and not done.left
    assert stamp_of(folder)["version"] == __version__
    assert "since-dropped" not in stamp_of(folder)["skills"]


# ---------------------------------------------------------------- never over what is not ours


def test_a_folder_of_the_same_name_that_is_someone_elses_is_left(tmp_path: Path) -> None:
    """`~/.agents/skills` is shared with every other skill the user has. One of theirs that
    happens to be called `review-panel` is theirs."""
    folder = tmp_path / "skills"
    theirs = folder / "review-panel" / "SKILL.md"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"---\nname: review-panel\ndescription: Use for mine.\n---\nMine.\n")
    (folder / "another-skill").mkdir()
    (folder / "another-skill" / "SKILL.md").write_bytes(b"not ours either\n")

    done = skillcopy.install(folder)
    assert theirs.read_bytes().endswith(b"Mine.\n")
    assert (folder / "another-skill" / "SKILL.md").read_bytes() == b"not ours either\n"
    assert [name for name, _why in done.left] == ["review-panel"]
    assert "review-panel" not in stamp_of(folder)["skills"]
    assert "review-panel" not in done.written and "project-setup" in done.written


def test_a_copy_edited_since_is_left_and_stays_recorded(tmp_path: Path, monkeypatch) -> None:
    """Someone adapted a skill in place. Writing the new release over it would lose that."""
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    edited = folder / "figure-review" / "SKILL.md"
    edited.write_bytes(edited.read_bytes() + b"\nOur lab's own rule.\n")
    extra = folder / "methods-writer" / "notes.md"
    extra.write_bytes(b"a file added beside a skill\n")

    with monkeypatch.context() as patch:
        patch.setattr(skillcopy, "__version__", "99.0.0")
        done = skillcopy.install(folder)
    assert edited.read_bytes().endswith(b"Our lab's own rule.\n")
    assert extra.read_bytes() == b"a file added beside a skill\n"
    assert sorted(name for name, _why in done.left) == ["figure-review", "methods-writer"]
    # Still on record as this tool's, so a later copy says the same and does not adopt it.
    assert {"figure-review", "methods-writer"} <= set(stamp_of(folder)["skills"])
    assert skillcopy.install(folder).left == done.left


def test_a_dropped_skill_that_was_edited_is_left_too(
    tmp_path: Path, older: Path, monkeypatch
) -> None:
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)
    kept = folder / "since-dropped" / "SKILL.md"
    kept.write_bytes(kept.read_bytes() + b"edited\n")
    done = skillcopy.install(folder)
    assert kept.read_bytes().endswith(b"edited\n")
    assert not done.removed and [name for name, _why in done.left] == ["since-dropped"]


@pytest.mark.parametrize("body", ["", "{", "[]", '{"schema": "something/else"}', '{"skills": 3}'])
def test_a_stamp_that_cannot_be_read_gives_this_tool_nothing(tmp_path: Path, body: str) -> None:
    """Without a stamp it can read, no folder there is known to be this tool's."""
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    (folder / skillcopy.STAMP).write_text(body, encoding="utf-8")
    before = skills_in(folder)
    done = skillcopy.install(folder)
    assert skills_in(folder) == before
    assert not done.written and len(done.left) == len(before)


# ---------------------------------------------------------------- the command


def test_the_command_copies_to_the_users_folder(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home-skills"
    monkeypatch.setenv(skillcopy.USER_FOLDER_VARIABLE, str(home))
    assert main(["install-skills"]) == 0
    assert skills_in(home) == tree(SOURCE)
    said = capsys.readouterr().out
    assert str(home) in said and __version__ in said


def test_the_command_copies_into_a_project(project: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(project / "manuscript")
    assert main(["install-skills", "--project"]) == 0
    assert skills_in(project / ".agents" / "skills") == tree(SOURCE)


def test_the_command_copies_to_a_named_folder(tmp_path: Path, capsys) -> None:
    assert main(["install-skills", "--dir", str(tmp_path / "x" / "skills")]) == 0
    assert skills_in(tmp_path / "x" / "skills") == tree(SOURCE)


def test_outside_a_project_the_project_form_says_so(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["install-skills", "--project"]) == 2
    assert not (tmp_path / ".agents").exists()
    assert "paper.yaml" in capsys.readouterr().err


def test_the_command_fails_and_names_what_it_left(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "skills"
    (folder / "review-panel").mkdir(parents=True)
    (folder / "review-panel" / "SKILL.md").write_bytes(b"theirs\n")
    assert main(["install-skills", "--dir", str(folder)]) == 1
    captured = capsys.readouterr()
    assert "review-panel" in captured.err and "not from manuscript-guard" in captured.err
    assert (folder / "project-setup" / "SKILL.md").is_file(), "the rest was still copied"


# ---------------------------------------------------------------- a stale copy


def check(project: Path, capsys, *extra: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = main(["check", str(project), *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def no_user_copy(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "no-user-skills"
    monkeypatch.setenv(skillcopy.USER_FOLDER_VARIABLE, str(home))
    return home


def test_a_copy_from_an_older_release_is_named_by_check(
    project: Path, no_user_copy: Path, older: Path, monkeypatch, capsys
) -> None:
    code, out, err = check(project, capsys)
    assert err == ""

    install_from(older, "0.0.1", project / ".agents" / "skills", monkeypatch)
    again, out_again, said = check(project, capsys)
    assert (again, out_again) == (code, out), "the notice changes neither the result nor stdout"
    assert "0.0.1" in said and __version__ in said
    assert "manuscript-guard install-skills --project" in said
    assert len(said.strip().splitlines()) == 1


def test_the_users_copy_is_named_too_with_the_command_that_renews_it(
    project: Path, no_user_copy: Path, older: Path, monkeypatch, capsys
) -> None:
    install_from(older, "0.0.1", no_user_copy, monkeypatch)
    _code, _out, said = check(project, capsys)
    assert str(no_user_copy) in said
    assert "`manuscript-guard install-skills`" in said


def test_a_copy_from_this_release_says_nothing(project: Path, no_user_copy: Path, capsys) -> None:
    skillcopy.install(project / ".agents" / "skills")
    skillcopy.install(no_user_copy)
    _code, _out, err = check(project, capsys)
    assert err == ""


def test_a_copy_newer_than_the_tool_says_to_upgrade_the_tool(
    project: Path, no_user_copy: Path, monkeypatch, capsys
) -> None:
    install_from(SOURCE, "99.0.0", project / ".agents" / "skills", monkeypatch)
    _code, _out, said = check(project, capsys)
    assert "99.0.0" in said and "pip install --upgrade" in said
    assert "install-skills" not in said


def test_the_notice_leaves_json_as_it_was(
    project: Path, no_user_copy: Path, older: Path, monkeypatch, capsys
) -> None:
    code, out, _err = check(project, capsys, "--json")
    install_from(older, "0.0.1", project / ".agents" / "skills", monkeypatch)
    again, out_again, said = check(project, capsys, "--json")
    assert (again, out_again) == (code, out)
    json.loads(out_again)
    assert "0.0.1" in said


def test_the_copy_in_a_project_does_not_change_what_check_finds(
    project: Path, no_user_copy: Path, capsys
) -> None:
    """The skills are prose with numbers in them. They are not the manuscript."""
    code, out, _err = check(project, capsys)
    skillcopy.install(project / ".agents" / "skills")
    assert check(project, capsys)[:2] == (code, out)


@pytest.mark.parametrize("body", ["", "{", "[]", '{"schema": "manuscript-guard/skills/1"}'])
def test_a_stamp_that_cannot_be_read_never_costs_the_check(
    project: Path, no_user_copy: Path, body: str, capsys
) -> None:
    code, out, _err = check(project, capsys)
    folder = project / ".agents" / "skills"
    folder.mkdir(parents=True)
    (folder / skillcopy.STAMP).write_text(body, encoding="utf-8")
    assert check(project, capsys) == (code, out, "")


def test_build_names_a_stale_copy_as_well(
    project: Path, no_user_copy: Path, older: Path, monkeypatch, capsys
) -> None:
    install_from(older, "0.0.1", project / ".agents" / "skills", monkeypatch)
    capsys.readouterr()
    # Whether or not pandoc is there to finish the build, the notice is said.
    main(["build", str(project), "--offline"])
    assert "manuscript-guard install-skills --project" in capsys.readouterr().err


# ---------------------------------------------------------------- a tool that reads the folder

GEMINI = shutil.which("gemini")


@pytest.mark.skipif(GEMINI is None, reason="Gemini CLI is not installed")
def test_gemini_cli_finds_every_skill_in_the_copy(tmp_path: Path) -> None:
    """`gemini skills list` reads the folders and calls no model. Skipped where Gemini CLI
    is absent, which includes CI: this is the check a contributor who has it can run."""
    workspace = tmp_path / "w"
    folder = workspace / ".agents" / "skills"
    skillcopy.install(folder)
    listed = subprocess.run(
        [GEMINI, "skills", "list"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    printed = listed.stdout + listed.stderr
    assert listed.returncode == 0, printed
    for name in sorted(path.parent.name for path in SOURCE.glob("*/SKILL.md")):
        assert str(folder / name / "SKILL.md") in printed, name
