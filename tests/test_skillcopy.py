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
import os
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
    """A source as an earlier release shipped it: one skill worded differently and holding a
    file it no longer has, and one skill that has since been dropped."""
    source = tmp_path / "older-release"
    shutil.copytree(SOURCE, source)
    setup = source / "project-setup" / "SKILL.md"
    setup.write_bytes(setup.read_bytes() + b"\nAn older sentence.\n")
    (source / "project-setup" / "reference.md").write_bytes(b"a file a later release dropped\n")
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
    """Built with the hatchling that is installed, so the test needs no network. It is among
    the development dependencies for this; without it the test is skipped, and CI's wheel job
    makes the same comparison on an installed wheel."""
    import zipfile

    pytest.importorskip("hatchling")
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "--no-build-isolation",
         "-q", "-w", str(tmp_path)],
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
    # Still on record, or the next copy would take it for someone else's.
    assert "since-dropped" in stamp_of(folder)["skills"]


def rewrite_stamp(folder: Path, change) -> None:
    stamp = stamp_of(folder)
    change(stamp)
    (folder / skillcopy.STAMP).write_text(json.dumps(stamp), encoding="utf-8")


UNREADABLE = {
    "empty": lambda text: "",
    "cut short": lambda text: text[: len(text) // 2],
    "a list": lambda text: "[]",
    "another schema": lambda text: text.replace(skillcopy.SCHEMA, "manuscript-guard/skills/2"),
    "no version": lambda text: text.replace('"version"', '"release"'),
    "skills not a mapping": lambda text: json.dumps({**json.loads(text), "skills": 3}),
    "a digest that is not text": lambda text: json.dumps(
        {**json.loads(text), "skills": {"review-panel": {"SKILL.md": 3}}}
    ),
    "a byte order mark": lambda text: "\N{ZERO WIDTH NO-BREAK SPACE}" + text,
}


@pytest.mark.parametrize("kind", sorted(UNREADABLE))
def test_a_stamp_that_cannot_be_read_stops_the_copy_and_is_left(tmp_path: Path, kind: str) -> None:
    """A stamp this release cannot read may be a later release's. Writing a new one over it
    would lose the record of what is the tool's, for that release and every one after: the
    folders would be someone else's for good. So nothing is written, the stamp included."""
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    stamp = folder / skillcopy.STAMP
    stamp.write_text(UNREADABLE[kind](stamp.read_text(encoding="utf-8")), encoding="utf-8")
    before = tree(folder)
    with pytest.raises(skillcopy.StampUnreadable):
        skillcopy.install(folder)
    assert tree(folder) == before


@pytest.mark.parametrize(
    "name", ["../../outside", "sub/outside", "<absolute>", "", ".", "REVIEW-PANEL", "Outside"]
)
def test_a_stamp_is_never_obeyed_for_a_name_that_is_not_a_skills(tmp_path: Path, name: str) -> None:
    """The stamp says which folders may be removed, and a name in it was used as a path. One
    written by hand, or arriving with a cloned project, could name a folder anywhere, with
    the digests of what is in it. A name that is not one lower-case folder name makes the
    whole stamp unreadable."""
    folder = tmp_path / "a" / "skills"
    skillcopy.install(folder)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_bytes(b"precious")
    (folder / "Outside").mkdir()
    (folder / "Outside" / "precious.txt").write_bytes(b"precious")
    listed = str(outside) if name == "<absolute>" else name
    digests = {"precious.txt": hashlib.sha256(b"precious").hexdigest()}
    if name == "REVIEW-PANEL":
        digests = stamp_of(folder)["skills"]["review-panel"]

    def forge(stamp: dict) -> None:
        stamp["version"] = "0.0.1"
        stamp["skills"][listed] = digests

    rewrite_stamp(folder, forge)
    before = tree(tmp_path)
    with pytest.raises(skillcopy.StampUnreadable):
        skillcopy.install(folder)
    assert tree(tmp_path) == before


def test_a_copy_that_stopped_half_way_is_finished_by_the_next(
    tmp_path: Path, older: Path, monkeypatch
) -> None:
    """The stamp is written when the copy is done. A copy that stops before that (a file held
    open, a synced folder, an interrupt) leaves new skills under an old stamp, and they read
    as changed since they were copied: left, for good. What is already in a folder is what
    would be written there, so writing it loses nothing."""
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)

    real = shutil.copytree
    calls: list[object] = []

    def held_open(source, target, *arguments, **named):
        calls.append(target)
        if len(calls) == 1:
            real(source, target, *arguments, **named)
            (Path(target) / "SKILL.md").write_bytes(b"half of a skill")
            raise PermissionError("the file is open in another program")
        return real(source, target, *arguments, **named)

    with monkeypatch.context() as patch:
        patch.setattr(skillcopy.shutil, "copytree", held_open)
        with pytest.raises(PermissionError):
            skillcopy.install(folder)
    assert stamp_of(folder)["version"] == "0.0.1", "the stamp is as the last whole copy left it"

    done = skillcopy.install(folder)
    assert not done.left, done.left
    assert tree(folder).keys() - {skillcopy.STAMP} == tree(SOURCE).keys(), "and nothing half-made"
    assert skills_in(folder) == tree(SOURCE)
    assert stamp_of(folder)["version"] == __version__


def test_skills_already_there_as_they_would_be_written_are_taken_without_a_stamp(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    (folder / skillcopy.STAMP).unlink()
    done = skillcopy.install(folder)
    assert not done.left and not done.written
    assert sorted(stamp_of(folder)["skills"]) == sorted(done.unchanged)


def with_crlf(body: bytes) -> bytes:
    return body.replace(b"\n", b"\r\n")


def test_a_copy_checked_out_with_other_line_endings_is_still_the_tools(
    tmp_path: Path, older: Path, monkeypatch
) -> None:
    """A copy committed with a project and checked out by git on Windows comes back with
    CRLF. Digests over the bytes as they are called all fourteen changed, for good."""
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)
    for path in folder.rglob("*.md"):
        path.write_bytes(with_crlf(path.read_bytes()))
    done = skillcopy.install(folder)
    assert not done.left, done.left
    assert done.written == ("project-setup",) and done.removed == ("since-dropped",)
    # The skill that changed is the new release's. The others hold the same text, and are
    # left with the line endings git gave them: rewriting them would show every file as
    # modified, with nothing in the diff.
    expected = {
        name: body if name.startswith("project-setup/") else with_crlf(body)
        for name, body in tree(SOURCE).items()
    }
    assert skills_in(folder) == expected


def forbid(*_arguments, **_named):
    raise AssertionError("nothing was to be copied or removed")


def test_a_run_with_nothing_to_change_writes_no_skill(tmp_path: Path, monkeypatch) -> None:
    """Every skill was removed and written again on each run, changed or not: a folder of
    the user's own that held the same text was written over, and one in use was emptied."""
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    theirs = folder / "review-panel"
    (theirs / "an empty folder of the user's").mkdir()
    (theirs / "SKILL.md").write_bytes(with_crlf((theirs / "SKILL.md").read_bytes()))
    before = tree(folder)

    with monkeypatch.context() as patch:
        patch.setattr(skillcopy.shutil, "copytree", forbid)
        patch.setattr(skillcopy.shutil, "rmtree", forbid)
        done = skillcopy.install(folder)
    assert tree(folder) == before
    assert (theirs / "an empty folder of the user's").is_dir()
    assert not done.written and not done.left and not done.removed
    assert len(done.unchanged) == len(list(SOURCE.glob("*/SKILL.md")))


def test_a_skill_folder_in_use_is_left_whole(tmp_path: Path, older: Path, monkeypatch) -> None:
    """On Windows a folder that is some program's working directory cannot be moved or
    removed. The old skill was emptied before that was found out, and then read as changed
    for good. It is now moved aside whole, which either happens or does not."""
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)
    before = tree(folder)
    real = os.replace

    def in_use(source, target):
        if Path(source) == folder / "project-setup":
            raise PermissionError(32, "The process cannot access the file", str(source))
        return real(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(skillcopy.os, "replace", in_use)
        with pytest.raises(PermissionError):
            skillcopy.install(folder)
    assert tree(folder) == before, "the old skill is whole, and nothing half-made is left"
    assert sorted(p.name for p in folder.iterdir()) == sorted({n.split("/")[0] for n in before})

    done = skillcopy.install(folder)
    assert not done.left
    assert skills_in(folder) == tree(SOURCE)


def test_a_copy_that_cannot_be_moved_in_puts_the_old_skill_back(
    tmp_path: Path, older: Path, monkeypatch
) -> None:
    """By then the old skill has been moved aside, and the staging folder it sits in is
    removed on the way out. Without the move back the skill was gone from the folder."""
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)
    before = tree(folder)
    real = os.replace

    def no_way_in(source, target):
        if Path(source).name == "new" and Path(target) == folder / "project-setup":
            raise PermissionError(5, "Access is denied", str(target))
        return real(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(skillcopy.os, "replace", no_way_in)
        with pytest.raises(PermissionError):
            skillcopy.install(folder)
    assert tree(folder) == before, "the old skill is back whole, and nothing half-made is left"
    assert sorted(p.name for p in folder.iterdir()) == sorted({n.split("/")[0] for n in before})

    done = skillcopy.install(folder)
    assert done.written == ("project-setup",) and not done.left
    assert skills_in(folder) == tree(SOURCE)


def test_nothing_the_copy_did_not_make_is_removed_to_make_room(
    tmp_path: Path, older: Path, monkeypatch
) -> None:
    """A skill was staged under a fixed name beside its place, and whatever had that name
    was removed first."""
    folder = tmp_path / "skills"
    install_from(older, "0.0.1", folder, monkeypatch)
    theirs = folder / ".project-setup.partial"
    theirs.mkdir()
    (theirs / "precious.txt").write_bytes(b"precious")
    done = skillcopy.install(folder)
    assert done.written == ("project-setup",)
    assert (theirs / "precious.txt").read_bytes() == b"precious"


def make_link(link: Path, target: Path) -> bool:
    """A link to a folder, of whatever kind this system lets an ordinary user make."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        pass
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return True
    except (ImportError, OSError, AttributeError):
        return False


def test_a_file_or_a_link_where_a_skill_goes_is_left(tmp_path: Path, monkeypatch) -> None:
    """Even one the stamp lists, with the very content that was copied: a link leads out of
    the folder, and what is at its other end is not this tool's to remove."""
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    elsewhere = tmp_path / "elsewhere" / "figure-review"
    shutil.copytree(folder / "figure-review", elsewhere)
    shutil.rmtree(folder / "figure-review")
    linked = make_link(folder / "figure-review", elsewhere)
    shutil.rmtree(folder / "review-panel")
    (folder / "review-panel").write_bytes(b"a file where a folder was\n")

    with monkeypatch.context() as patch:
        patch.setattr(skillcopy, "__version__", "99.0.0")
        done = skillcopy.install(folder)
    left = [name for name, _why in done.left]
    assert "review-panel" in left
    assert (folder / "review-panel").read_bytes() == b"a file where a folder was\n"
    if not linked:
        pytest.skip("this system lets an ordinary user make no link to a folder")
    assert "figure-review" in left
    assert tree(elsewhere) == tree(SOURCE / "figure-review")


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


def test_the_command_fails_and_names_what_it_left(tmp_path: Path, monkeypatch, capsys) -> None:
    folder = tmp_path / "skills"
    (folder / "review-panel").mkdir(parents=True)
    (folder / "review-panel" / "SKILL.md").write_bytes(b"theirs\n")
    monkeypatch.setenv(skillcopy.USER_FOLDER_VARIABLE, str(folder))
    assert main(["install-skills"]) == 1
    captured = capsys.readouterr()
    assert "review-panel" in captured.err and "not from manuscript-guard" in captured.err
    assert "`--project` copies" in captured.err, "the message says what can be done about it"
    assert (folder / "project-setup" / "SKILL.md").is_file(), "the rest was still copied"


@pytest.mark.parametrize("form", ["--project", "--dir"])
def test_the_way_forward_is_not_the_option_already_given(
    form: str, project: Path, monkeypatch, capsys
) -> None:
    """In the project's own folder, a skill that is someone else's is not helped by being
    told to use `--project`."""
    folder = project / ".agents" / "skills"
    (folder / "review-panel").mkdir(parents=True)
    (folder / "review-panel" / "SKILL.md").write_bytes(b"theirs\n")
    monkeypatch.chdir(project)
    arguments = ["--project"] if form == "--project" else ["--dir", str(folder)]
    assert main(["install-skills", *arguments]) == 1
    said = capsys.readouterr().err
    assert "review-panel" in said and "not from manuscript-guard" in said
    assert "`--project` copies" not in said
    assert "move it away" in said


def test_the_command_says_how_to_take_the_new_release_of_a_changed_skill(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    edited = folder / "figure-review" / "SKILL.md"
    edited.write_bytes(edited.read_bytes() + b"\nOur own rule.\n")
    monkeypatch.setattr(skillcopy, "__version__", "99.0.0")
    assert main(["install-skills", "--dir", str(folder)]) == 1
    said = capsys.readouterr().err
    assert "figure-review" in said and "was changed" in said
    assert "delete the folder and run the command again" in said


def test_the_command_stops_at_a_stamp_it_cannot_read(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "skills"
    skillcopy.install(folder)
    (folder / skillcopy.STAMP).write_text("{", encoding="utf-8")
    before = tree(folder)
    assert main(["install-skills", "--dir", str(folder)]) == 2
    assert tree(folder) == before
    said = capsys.readouterr().err
    assert skillcopy.STAMP in said and "nothing" in said


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


@pytest.mark.parametrize(
    ("copy", "renews"),
    [
        ("0.2.99", True),  # older: 99 < 400, though "99" sorts after "400" as text
        ("0.2.399", True),
        ("0.2.400", None),
        ("0.2.1000", False),  # newer: 1000 > 400, though "1000" sorts before "400" as text
        ("0.10.0", False),
    ],
)
def test_releases_are_compared_as_numbers_not_as_text(
    project: Path, no_user_copy: Path, copy: str, renews: bool | None, monkeypatch, capsys
) -> None:
    install_from(SOURCE, copy, project / ".agents" / "skills", monkeypatch)
    monkeypatch.setattr(skillcopy, "__version__", "0.2.400")
    _code, _out, said = check(project, capsys)
    if renews is None:
        assert said == ""
    else:
        assert ("install-skills --project" in said) == renews, said
        assert ("pip install --upgrade" in said) != renews, said


def test_with_nowhere_to_say_it_the_notice_is_not_said(
    project: Path, no_user_copy: Path, older: Path, monkeypatch, capsys
) -> None:
    """A process started with its error stream closed has none, and `print` then writes to
    standard output: the notice landed after the JSON of `check --json`."""
    code, out, _err = check(project, capsys, "--json")
    install_from(older, "0.0.1", project / ".agents" / "skills", monkeypatch)
    capsys.readouterr()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stderr", None)
        again = main(["check", str(project), "--json"])
    assert (again, capsys.readouterr().out) == (code, out)


def test_a_stamp_that_cannot_be_read_in_one_place_does_not_cost_the_other_its_line(
    project: Path, no_user_copy: Path, older: Path, monkeypatch, capsys
) -> None:
    install_from(older, "0.0.1", no_user_copy, monkeypatch)
    folder = project / ".agents" / "skills"
    folder.mkdir(parents=True)
    (folder / skillcopy.STAMP).write_text("{", encoding="utf-8")
    _code, _out, said = check(project, capsys)
    assert str(no_user_copy) in said and "0.0.1" in said
    assert len(said.strip().splitlines()) == 1


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
WITH_GEMINI = "MANUSCRIPT_GUARD_WITH_GEMINI"


@pytest.mark.skipif(
    GEMINI is None or not os.environ.get(WITH_GEMINI),
    reason=f"runs only with Gemini CLI installed and {WITH_GEMINI} set",
)
def test_gemini_cli_finds_every_skill_in_the_copy(tmp_path: Path) -> None:
    """`gemini skills list` reads the folders and calls no model. It is asked for by name,
    with the variable above, because Gemini CLI reads and keeps its state in the real home of
    whoever runs it, which a test suite should not touch unasked. Passed with Gemini CLI
    0.58.0 on 2026-10-02."""
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
