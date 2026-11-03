"""`vault init` and `vault check`: the data registered outside the project, and whether this
session can read them.

What the hooks make of a vault, the session's line and the shell guard, is in
`tests/test_hooks.py`; what the shell guard reads of a command, over generated commands, in
`tests/test_properties.py`.
"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts._schema import validate
from manuscript_guard.vault import agent_rules, probe

MINIMUM = "\ncustodian:\n  minimum_cell_count: 5\n"


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.fsmonitor=false", *arguments], cwd=root,
                          capture_output=True, text=True, check=False)  # fmt: skip


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    """A new project in a git repository, whose paper.yaml declares the custodian's minimum."""
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    with (root / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write(MINIMUM)
    if shutil.which("git"):
        _git(root, "init", "-q")
    return root


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """The vault's folder, beside the project: two extracts and a note nobody registers."""
    folder = tmp_path / "data held"
    (folder / "extract").mkdir(parents=True)
    (folder / "cohort.csv").write_bytes(b"id,age\r\n1,40\r\n")
    (folder / "extract" / "visits.csv").write_bytes(b"id,date\n1,2020-01-01\n")
    (folder / "notes.txt").write_bytes(b"not data\n")
    return folder


def vault(paper: Path, *words: str) -> int:
    return main(["vault", *words, "--path", str(paper)])


def registry(paper: Path) -> dict:
    return yaml.safe_load((paper / "design" / "vault.yaml").read_text(encoding="utf-8"))


def local(paper: Path) -> dict:
    file = paper / ".manuscript-guard" / "vault.local.yaml"
    return yaml.safe_load(file.read_text(encoding="utf-8"))


def nothing_written(paper: Path) -> bool:
    return not (paper / "design" / "vault.yaml").exists() and not (
        paper / ".manuscript-guard").exists()


# ---------------------------------------------------------------------------- what is written


def test_init_writes_the_registry_and_the_local_file_and_ignores_the_local_one(
    paper: Path, data: Path, capsys
) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "extract/*.csv", "--as", "Ada") == 0
    said = capsys.readouterr().out
    found = registry(paper)
    assert validate(found, "vault", paper / "design" / "vault.yaml").ok
    assert [entry["label"] for entry in found["files"]] == ["cohort.csv", "extract/visits.csv"]
    cohort = found["files"][0]
    from manuscript_guard.emit import input_digest, sha256_of

    assert cohort["sha256"] == input_digest(data / "cohort.csv")
    assert cohort["raw_sha256"] == sha256_of(data / "cohort.csv")
    # The line endings of a CSV are formatting to the first, and bytes to the second.
    assert cohort["sha256"] != cohort["raw_sha256"]
    assert cohort["bytes"] == 14 and cohort["registered_by"] == "Ada" and cohort["registered_on"]
    # Neither the folder's path nor any row is in the committed file.
    text = (paper / "design" / "vault.yaml").read_text(encoding="utf-8")
    assert str(data) not in text and data.name not in text and "id,age" not in text
    kept = local(paper)
    assert validate(kept, "vault-local", paper / "x").ok
    assert Path(kept["folder"]) == data.resolve()
    assert ".manuscript-guard/" in (paper / ".gitignore").read_text(encoding="utf-8").splitlines()
    if shutil.which("git"):
        ignored = _git(paper, "check-ignore", "-q", ".manuscript-guard/vault.local.yaml")
        assert ignored.returncode == 0
    assert "added .manuscript-guard/ to .gitignore" in said
    # The note in the folder was not named, and is not registered.
    assert "notes.txt" not in text
    # The agent tool's rules are printed for the folder.
    assert f"Read({agent_rules.rule_path(data.resolve())}/**)" in said


def test_a_gitignore_that_already_ignores_the_folder_is_left_as_it_is(
    paper: Path, data: Path
) -> None:
    ignore = paper / ".gitignore"
    ignore.write_bytes(b"build/\r\n/.manuscript-guard\r\n")
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    assert ignore.read_bytes() == b"build/\r\n/.manuscript-guard\r\n"


def test_init_again_keeps_who_registered_a_file_that_did_not_change(
    paper: Path, data: Path, capsys
) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    first = registry(paper)["files"][0]
    assert vault(paper, "init", str(data), "cohort.csv", "extract/visits.csv", "--as", "Bo") == 0
    said = capsys.readouterr().out
    files = {entry["label"]: entry for entry in registry(paper)["files"]}
    assert files["cohort.csv"] == first
    assert files["extract/visits.csv"]["registered_by"] == "Bo"
    assert "registered: extract/visits.csv" in said and "unchanged: cohort.csv" in said


def test_refresh_says_which_labels_changed(paper: Path, data: Path, capsys) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "extract/visits.csv", "--as", "Ada") == 0
    capsys.readouterr()
    (data / "extract" / "visits.csv").write_bytes(b"id,date\n1,2020-01-02\n")
    assert vault(paper, "init", "--refresh", "--as", "Bo") == 0
    said = capsys.readouterr().out
    assert "changed since registered: extract/visits.csv" in said
    assert "cohort.csv" not in said.split("changed since registered:")[1].splitlines()[0]
    files = {entry["label"]: entry for entry in registry(paper)["files"]}
    assert files["extract/visits.csv"]["registered_by"] == "Bo"
    assert files["cohort.csv"]["registered_by"] == "Ada"
    assert vault(paper, "init", "--refresh", "--as", "Bo") == 0
    assert "no registered file changed" in capsys.readouterr().out


def test_a_line_ending_changed_by_git_is_no_change(paper: Path, data: Path, capsys) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    (data / "cohort.csv").write_bytes(b"id,age\n1,40\n")
    assert vault(paper, "init", "--refresh", "--as", "Bo") == 0
    assert "changed since registered: cohort.csv" in capsys.readouterr().out
    # The raw digest moved, the content's did not: it is a change of the file, said as one,
    # and its content digest is the one the emitter will compare.
    entry = registry(paper)["files"][0]
    from manuscript_guard.emit import input_digest

    assert entry["sha256"] == input_digest(data / "cohort.csv")


# ---------------------------------------------------------------------------- refused


def _refused(paper: Path, capsys, *words: str) -> str:
    assert vault(paper, *words) == 2
    said = capsys.readouterr().err
    assert "refused, nothing written" in said, said
    assert nothing_written(paper)
    return said


def test_a_folder_inside_the_project_is_refused(paper: Path, capsys) -> None:
    inside = paper / "data"
    inside.mkdir()
    (inside / "cohort.csv").write_text("x\n", encoding="utf-8")
    assert "inside the project" in _refused(paper, capsys, "init", str(inside), "cohort.csv",
                                            "--as", "Ada")  # fmt: skip


def test_a_project_inside_the_folder_is_refused(paper: Path, capsys) -> None:
    (paper.parent / "cohort.csv").write_text("x\n", encoding="utf-8")
    said = _refused(paper, capsys, "init", str(paper.parent), "cohort.csv", "--as", "Ada")
    assert "is inside" in said


def _link(link: Path, target: Path) -> None:
    """A link to a folder: a junction on Windows, which needs no privilege, else a symlink."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_a_link_that_leads_into_the_project_is_followed_and_refused(
    paper: Path, tmp_path: Path, capsys
) -> None:
    inside = paper / "kept"
    inside.mkdir()
    (inside / "cohort.csv").write_text("x\n", encoding="utf-8")
    _link(tmp_path / "looks outside", inside)
    said = _refused(paper, capsys, "init", str(tmp_path / "looks outside"), "cohort.csv",
                    "--as", "Ada")  # fmt: skip
    assert "inside the project" in said


def test_a_project_with_no_custodian_minimum_is_refused(
    tmp_path: Path, data: Path, capsys
) -> None:
    root = tmp_path / "bare"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    said = _refused(root, capsys, "init", str(data), "cohort.csv", "--as", "Ada")
    assert "minimum_cell_count" in said and "1 where there is no rule" in said


@pytest.mark.parametrize("minimum", ["0", "-5", "true", "'5'"])
def test_a_custodian_minimum_below_one_is_refused(
    tmp_path: Path, data: Path, capsys, minimum: str
) -> None:
    """Round 1 of #488: 1 is the least a custodian's minimum can say."""
    root = tmp_path / "low"
    assert main(["init", str(root)]) == 0
    with (root / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write(f"\ncustodian:\n  minimum_cell_count: {minimum}\n")
    capsys.readouterr()
    assert "minimum_cell_count" in _refused(root, capsys, "init", str(data), "cohort.csv",
                                            "--as", "Ada")  # fmt: skip


def test_one_said_on_purpose_is_accepted(tmp_path: Path, data: Path) -> None:
    root = tmp_path / "one"
    assert main(["init", str(root)]) == 0
    with (root / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write("\ncustodian:\n  minimum_cell_count: 1\n")
    assert vault(root, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    assert main(["check", str(root)]) in (0, 1)  # paper.yaml still reads as its schema says


@pytest.mark.parametrize(
    ("words", "said"),
    [
        ((), "name the files to register"),
        (("*.parquet",), "matches no file"),
        (("extract",), "matches no file"),  # a folder is no file
        (("../elsewhere.csv",), "leads out of the vault's folder"),
    ],
)
def test_only_files_named_in_the_folder_are_registered(
    paper: Path, data: Path, capsys, words: tuple[str, ...], said: str
) -> None:
    (data.parent / "elsewhere.csv").write_text("x\n", encoding="utf-8")
    assert said in _refused(paper, capsys, "init", str(data), *words, "--as", "Ada")


def test_a_file_whose_link_leads_out_of_the_folder_is_refused(
    paper: Path, data: Path, tmp_path: Path, capsys
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "other.csv").write_text("x\n", encoding="utf-8")
    _link(data / "linked", outside)
    assert "leads out of the vault's folder" in _refused(
        paper, capsys, "init", str(data), "linked/other.csv", "--as", "Ada")  # fmt: skip


def test_who_registers_is_said(paper: Path, data: Path, capsys) -> None:
    assert "--as" in _refused(paper, capsys, "init", str(data), "cohort.csv")


def test_refresh_with_nothing_registered_is_refused(paper: Path, capsys) -> None:
    assert "no vault is registered" in _refused(paper, capsys, "init", "--refresh", "--as", "A")


def test_refresh_of_a_file_that_is_gone_is_refused(paper: Path, data: Path, capsys) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    before = (paper / "design" / "vault.yaml").read_bytes()
    (data / "cohort.csv").unlink()
    assert vault(paper, "init", "--refresh", "--as", "Bo") == 2
    assert "not in" in capsys.readouterr().err
    assert (paper / "design" / "vault.yaml").read_bytes() == before


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_local_file_git_tracks_is_refused(paper: Path, data: Path, capsys) -> None:
    kept = paper / ".manuscript-guard" / "vault.local.yaml"
    kept.parent.mkdir()
    kept.write_text("schema: x\n", encoding="utf-8")
    _git(paper, "add", "-f", ".manuscript-guard/vault.local.yaml")
    ignore = (paper / ".gitignore").read_bytes()
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 2
    assert "git tracks .manuscript-guard/vault.local.yaml" in capsys.readouterr().err
    assert kept.read_text(encoding="utf-8") == "schema: x\n"
    assert not (paper / "design" / "vault.yaml").exists()
    assert (paper / ".gitignore").read_bytes() == ignore, "a refusal changes nothing"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_gitignore_that_takes_the_local_file_back_in_is_refused(
    paper: Path, data: Path, capsys
) -> None:
    (paper / ".gitignore").write_text(".manuscript-guard/\n!.manuscript-guard/\n"
                                      "!.manuscript-guard/vault.local.yaml\n",
                                      encoding="utf-8")  # fmt: skip
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 2
    assert "git would track" in capsys.readouterr().err
    assert nothing_written(paper)


# ---------------------------------------------------------------------------- check


def test_check_with_nothing_registered_exits_2(paper: Path, capsys) -> None:
    assert vault(paper, "check") == 2
    assert "not registered here" in capsys.readouterr().out


def test_check_with_the_registry_and_no_local_file_says_to_register_here(
    paper: Path, data: Path, capsys
) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    shutil.rmtree(paper / ".manuscript-guard")
    capsys.readouterr()
    assert vault(paper, "check") == 2
    assert "this machine has no" in capsys.readouterr().out


def test_check_of_a_folder_this_account_can_read_exits_1(paper: Path, data: Path, capsys) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    capsys.readouterr()
    assert vault(paper, "check") == 1
    said = capsys.readouterr().out
    assert "readable from this session" in said and "1 of 1" in said


def test_check_of_a_folder_that_is_not_there_exits_0(paper: Path, data: Path, capsys) -> None:
    """An encrypted volume that is not mounted: the folder is not there."""
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    data.rename(data.with_name("unmounted"))
    capsys.readouterr()
    assert vault(paper, "check") == 0
    said = capsys.readouterr().out
    assert "not reachable from this session" in said and "could not be listed" in said


def test_check_of_a_folder_that_lists_without_the_files_registered_exits_1(
    paper: Path, data: Path, capsys
) -> None:
    """Round 1 of #488: the folder lists and holds something, though not the files registered
    (moved, renamed): what is in it can be read."""
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    (data / "cohort.csv").rename(data / "cohort-2026.csv")
    capsys.readouterr()
    assert vault(paper, "check") == 1
    assert "readable from this session" in capsys.readouterr().out


def test_check_of_an_empty_mount_point_exits_0(paper: Path, data: Path, capsys) -> None:
    """An encrypted volume's mount point with nothing mounted on it: the folder is there and
    empty."""
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    shutil.rmtree(data)
    data.mkdir()
    capsys.readouterr()
    assert vault(paper, "check") == 0
    assert "not reachable" in capsys.readouterr().out


def test_the_folder_is_kept_as_typed_and_as_its_links_lead(
    paper: Path, data: Path, tmp_path: Path, capsys
) -> None:
    """Round 1 of #488: a mapped drive or a link keeps the spelling the person typed, for the
    hooks and for the agent tool's rules, beside the one its links lead to."""
    typed = tmp_path / "typed here"
    _link(typed, data)
    assert vault(paper, "init", str(typed), "cohort.csv", "--as", "Ada") == 0
    said = capsys.readouterr().out
    kept = local(paper)
    assert validate(kept, "vault-local", paper / "x").ok
    assert Path(kept["folder"]) == typed.absolute()
    assert Path(kept["resolved"]) == data.resolve()
    for folder in (typed.absolute(), data.resolve()):
        assert f"Read({agent_rules.rule_path(folder)}/**)" in said


@pytest.fixture
def refused_to_this_account(data: Path):
    """The folder and its files refused to the account the tests run as: a deny ACL on
    Windows, set and taken away with icacls inside the test's folder; mode 000 elsewhere.

    Taken away in the reverse of the order set, the folder before the file in it: a file in a
    folder of mode 000 cannot be reached to change its own mode (CI on Ubuntu, 2fe9db87). And
    taken away whatever was set before a step failed."""
    targets = [data / "cohort.csv", data]
    done: list[Path] = []
    if os.name == "nt":
        if shutil.which("icacls") is None:
            pytest.skip("icacls is not on PATH")
        user = getpass.getuser()
        try:
            for target in targets:
                denied = subprocess.run(["icacls", str(target), "/deny", f"{user}:(R)"],
                                        capture_output=True, text=True, check=False)  # fmt: skip
                if denied.returncode != 0:
                    pytest.skip(f"icacls could not deny: {denied.stdout}{denied.stderr}")
                done.append(target)
            yield
        finally:
            for target in reversed(done):
                subprocess.run(["icacls", str(target), "/remove:d", user],
                               capture_output=True, check=False)  # fmt: skip
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads whatever the mode says")
    modes = {path: path.stat().st_mode for path in targets}
    try:
        for path in targets:
            path.chmod(0)
            done.append(path)
        yield
    finally:
        for path in reversed(done):
            path.chmod(modes[path])


def test_check_of_files_this_account_is_refused_exits_0(
    paper: Path, data: Path, capsys, request
) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0
    request.getfixturevalue("refused_to_this_account")
    capsys.readouterr()
    assert vault(paper, "check") == 0, capsys.readouterr().out
    said = capsys.readouterr().out
    assert "not reachable" in said and "cohort.csv (PermissionError)" in said


def test_the_probe_reads_no_byte(paper: Path, data: Path, monkeypatch) -> None:
    """It opens and closes: `os.read` is never asked for."""
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada") == 0

    def refused(*_args):
        raise AssertionError("the probe read the data")

    monkeypatch.setattr(os, "read", refused)
    assert probe.state(paper)[0] == probe.READABLE


def test_a_local_file_that_names_no_folder_is_said(paper: Path, capsys) -> None:
    kept = paper / ".manuscript-guard" / "vault.local.yaml"
    kept.parent.mkdir()
    kept.write_text("schema: manuscript-guard/vault-local/1\nfolder: relative/path\n", "utf-8")
    assert vault(paper, "check") == 2
    assert "run `manuscript-guard vault init` again" in capsys.readouterr().err


# ---------------------------------------------------------------------------- the agent's rules


@pytest.mark.parametrize(
    ("folder", "windows", "spelt"),
    [
        (PureWindowsPath(r"C:\Users\Ada\Data held"), True, "//c/Users/Ada/Data held"),
        (PureWindowsPath(r"d:\vault"), True, "//d/vault"),
        (PurePosixPath("/home/ada/data held"), False, "//home/ada/data held"),
        (PurePosixPath("/Volumes/Encrypted/extract"), False, "//Volumes/Encrypted/extract"),
    ],
)
def test_a_rule_names_the_folder_as_claude_code_spells_an_absolute_path(
    folder, windows: bool, spelt: str
) -> None:
    """`//` from the root of the file system, and on Windows the drive as `/c`, as Claude
    Code's permissions page says (read 2026-10-30)."""
    assert agent_rules.rule_path(folder, windows=windows) == spelt
    assert agent_rules.rules(folder, windows=windows) == [
        f"Read({spelt})", f"Read({spelt}/**)", f"Edit({spelt})", f"Edit({spelt}/**)"]


@pytest.mark.parametrize(
    ("folder", "windows"),
    [
        (r"\\server\share\vault", True),
        (r"C:\data [2020]", True),
        ("/home/ada/data*", False),
        ("/home/ada/data (copy)", False),
        ("relative/data", False),
    ],
)
def test_a_folder_no_rule_can_name_exactly_is_refused(folder: str, windows: bool) -> None:
    with pytest.raises(agent_rules.Unspellable):
        agent_rules.rule_path(folder, windows=windows)


def test_agent_settings_is_refused_without_a_terminal(paper: Path, data: Path, capsys) -> None:
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada", "--agent-settings") == 2
    said = capsys.readouterr().err
    assert "asks at a terminal" in said
    # Round 1 of #488: what was written is said, and what was not.
    assert "design/vault.yaml and .manuscript-guard/vault.local.yaml were written" in said
    assert "the deny rules were not" in said
    assert not (paper / ".claude").exists()
    # The registration itself stands: it was the person's to make, and it is made.
    assert registry(paper)["files"]


@pytest.mark.parametrize(("typed", "written"), [("y", True), ("yes", True), ("n", False),
                                                ("", False)])  # fmt: skip
def test_agent_settings_writes_the_rules_after_a_yes(
    paper: Path, data: Path, monkeypatch, typed: str, written: bool
) -> None:
    from manuscript_guard.deposit.remote import command

    asked: list[str] = []
    monkeypatch.setattr(command, "ask_at_terminal", lambda prompt: asked.append(prompt) or typed)
    settings = paper / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"],
                                                    "deny": ["Read(./.env)"]},
                                    "model": "x"}), encoding="utf-8")  # fmt: skip
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada", "--agent-settings") == 0
    assert asked and "[y/N]" in asked[0]
    found = json.loads(settings.read_text(encoding="utf-8"))
    rules = agent_rules.rules(data.resolve())
    if written:
        assert found == {"permissions": {"allow": ["Bash(ls)"], "deny": ["Read(./.env)", *rules]},
                         "model": "x"}  # fmt: skip
        # Asked again with the rules there, nothing is asked and nothing added.
        asked.clear()
        assert vault(paper, "init", "--agent-settings") == 0
        assert not asked
        assert json.loads(settings.read_text(encoding="utf-8")) == found
    else:
        assert found["permissions"]["deny"] == ["Read(./.env)"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_agent_settings_makes_git_ignore_the_settings_file_it_creates(
    paper: Path, data: Path, monkeypatch
) -> None:
    """Round 1 of #488: the file holds this machine's paths, as the local file does."""
    from manuscript_guard.deposit.remote import command

    monkeypatch.setattr(command, "ask_at_terminal", lambda prompt: "y")
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada", "--agent-settings") == 0
    assert (paper / ".claude" / "settings.local.json").is_file()
    lines = (paper / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".claude/settings.local.json" in lines
    assert _git(paper, "check-ignore", "-q", ".claude/settings.local.json").returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_agent_settings_refuses_a_settings_file_git_tracks_before_writing_anything(
    paper: Path, data: Path, monkeypatch, capsys
) -> None:
    from manuscript_guard.deposit.remote import command

    monkeypatch.setattr(command, "ask_at_terminal", lambda prompt: "y")
    settings = paper / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text("{}\n", encoding="utf-8")
    _git(paper, "add", "-f", ".claude/settings.local.json")
    ignore = (paper / ".gitignore").read_bytes()
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada", "--agent-settings") == 2
    assert "git tracks .claude/settings.local.json" in capsys.readouterr().err
    assert nothing_written(paper)
    assert settings.read_text(encoding="utf-8") == "{}\n"
    assert (paper / ".gitignore").read_bytes() == ignore


def test_agent_settings_refuses_a_settings_file_it_cannot_read(
    paper: Path, data: Path, monkeypatch, capsys
) -> None:
    from manuscript_guard.deposit.remote import command

    monkeypatch.setattr(command, "ask_at_terminal", lambda prompt: "y")
    settings = paper / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text("{not json", encoding="utf-8")
    assert vault(paper, "init", str(data), "cohort.csv", "--as", "Ada", "--agent-settings") == 2
    assert "cannot be read as JSON" in capsys.readouterr().err
    assert settings.read_text(encoding="utf-8") == "{not json"


def test_vault_reads_no_abbreviated_option(paper: Path) -> None:
    """Round 2 of #488: `--pa` is no `--path`, as the guard reads `vault`'s subcommand."""
    with pytest.raises(SystemExit):
        main(["vault", "check", "--pa", str(paper)])


def test_vault_offers_no_run_and_no_release_yet() -> None:
    """They read the real data and let what a run wrote into the project: a later step, and
    the shell guard refuses them to an agent already (`tests/test_hooks.py`)."""
    for verb in ("run", "release"):
        with pytest.raises(SystemExit):
            main(["vault", verb])


def test_the_vault_modules_the_hooks_read_import_nothing_heavy() -> None:
    """The shell guard reads the local file on every command in a project with a vault."""
    code = ("import sys; import manuscript_guard.vault.probe; "
            "heavy = {'yaml', 'jsonschema', 'manuscript_guard.contracts', "
            "'manuscript_guard.emit'}; "
            "print(sorted(heavy & set(sys.modules)))")  # fmt: skip
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          check=True)  # fmt: skip
    assert done.stdout.strip() == "[]"
