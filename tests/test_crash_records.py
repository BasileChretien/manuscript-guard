"""The record of a failure the tool did not expect (`diagnostics.crashes`, `diagnostics.scrub`).

The suite records nothing (conftest); each test here turns recording on in a folder of its own.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
from pathlib import Path

import pytest

from manuscript_guard import cli, hooks
from manuscript_guard.diagnostics import crashes
from manuscript_guard.diagnostics.scrub import scrub

DIAGNOSTICS = Path(crashes.__file__).resolve().parent


@pytest.fixture
def kept(tmp_path, monkeypatch) -> Path:
    """Recording on, into a folder of this test's, with no CI and no debugging; and no
    command's folder left by an earlier test's `main`, which a record would take for the
    project's (a `check` of a project run before in the same process failed two tests)."""
    folder = tmp_path / "reports"
    monkeypatch.setattr(crashes, "_invocation",
                        {"command": None, "flags": [], "words": 0, "start": None})
    monkeypatch.delenv(crashes.OFF, raising=False)
    monkeypatch.delenv(crashes.DEBUG, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv(crashes.FOLDER, str(folder))
    return folder


def _records(folder: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))
            if p.name != "hooks-said.json"]  # fmt: skip


def _broken(message: str = "nothing here"):
    def command(_args) -> int:
        raise KeyError(message)

    return command


def test_a_command_that_fails_says_one_sentence_records_it_and_exits_two(kept, monkeypatch,
                                                                         capsys) -> None:
    monkeypatch.setattr(cli, "cmd_stages", _broken())
    assert cli.main(["stages"]) == 2
    said = capsys.readouterr().err
    assert "stages stopped on an error in manuscript-guard itself" in said
    assert "KeyError" in said and "Traceback" not in said
    assert "nothing was sent" in said
    (found,) = _records(kept)
    assert found["kind"] == "command" and found["command"] == "stages"
    assert found["exception"] == "KeyError"
    assert found["count"] == 1 and len(found["fingerprint"]) == 12
    assert any(frame.get("file") == "manuscript_guard/cli.py" for frame in found["frames"])


def test_the_same_fault_again_raises_its_count_and_keeps_one_file(kept, monkeypatch) -> None:
    monkeypatch.setattr(cli, "cmd_stages", _broken())
    cli.main(["stages"])
    cli.main(["stages"])
    (found,) = _records(kept)
    assert found["count"] == 2 and found["first_seen"] <= found["last_seen"]


def test_flag_values_and_positional_words_are_never_kept() -> None:
    crashes.invoked("check", ["check", "--stage", "submission", "C:/Users/someone/secret-study",
                              "--json", "--lookup-cache=private-folder"])  # fmt: skip
    try:
        assert crashes._invocation["flags"] == ["--stage", "--json", "--lookup-cache"]
        assert crashes._invocation["words"] == 2
        kept = json.dumps(crashes._invocation)
        assert "submission" not in kept and "secret-study" not in kept
        assert "private-folder" not in kept
    finally:
        crashes.invoked(None, [])


def test_a_debugging_developer_gets_the_traceback(kept, monkeypatch) -> None:
    monkeypatch.setattr(cli, "cmd_stages", _broken())
    monkeypatch.setenv(crashes.DEBUG, "1")
    with pytest.raises(KeyError):
        cli.main(["stages"])
    assert _records(kept) == []


def test_on_a_ci_runner_the_traceback_is_printed_and_nothing_recorded(kept, monkeypatch,
                                                                      capsys) -> None:
    monkeypatch.setattr(cli, "cmd_stages", _broken())
    monkeypatch.setenv("CI", "true")
    assert cli.main(["stages"]) == 2
    said = capsys.readouterr().err
    assert "Traceback" in said and "stopped on an error in manuscript-guard itself" in said
    assert not kept.exists()


def test_recording_turned_off_records_nothing_and_says_so(kept, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "cmd_stages", _broken())
    monkeypatch.setenv(crashes.OFF, "1")
    assert cli.main(["stages"]) == 2
    assert "It was not recorded" in capsys.readouterr().err
    assert not kept.exists()


def test_a_reader_that_stopped_reading_is_not_a_fault(kept, monkeypatch) -> None:
    def closed(_args) -> int:
        raise BrokenPipeError

    monkeypatch.setattr(cli, "cmd_stages", closed)
    with pytest.raises(BrokenPipeError):
        cli.main(["stages"])
    assert not kept.exists()


def test_an_error_raised_on_purpose_is_said_and_never_recorded(kept, monkeypatch,
                                                               capsys) -> None:
    from manuscript_guard.contracts import ContractError

    def refused(_args) -> int:
        raise ContractError("paper.yaml does not read")

    monkeypatch.setattr(cli, "cmd_stages", refused)
    assert cli.main(["stages"]) == 2
    assert capsys.readouterr().err.strip() == "manuscript-guard: paper.yaml does not read"
    assert crashes.record(ContractError("x"), kind=crashes.COMMAND) is None
    assert not kept.exists()


def test_a_gate_that_fails_is_still_a_finding_and_is_recorded(kept) -> None:
    def gate():
        raise ValueError("unexpected shape")

    report = cli._guarded("G7", gate)
    (finding,) = report.findings
    assert finding.code == "gate-errored" and "ValueError" in finding.message
    (found,) = _records(kept)
    assert found["kind"] == "gate" and found["name"] == "G7"


def test_a_gate_that_cannot_read_the_authors_file_is_not_recorded(kept) -> None:
    from manuscript_guard.contracts import ContractError

    def gate():
        raise ContractError("authors.yaml: not a mapping")

    assert cli._guarded("G4", gate).findings[0].code == "gate-errored"
    assert not kept.exists()


def test_audits_writing_gates_that_fail_are_noted_and_recorded(kept, tmp_path,
                                                               monkeypatch) -> None:
    from manuscript_guard.auditing.gates import run_gates
    from manuscript_guard.gates import writing

    def broken(*_args, **_kwargs):
        raise IndexError("list index out of range")

    monkeypatch.setattr(writing, "check_writing", broken)
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nThe rate was 12%.\n", encoding="utf-8")
    run = run_gates(paper)
    assert "G6 and G14 could not run" in run.note
    (found,) = _records(kept)
    assert found["kind"] == "gate" and found["name"] == "G6 and G14"


def test_next_that_cannot_run_the_gates_still_decides_and_records(kept, tmp_path,
                                                                  monkeypatch) -> None:
    from manuscript_guard.guide.reading import inspect

    (tmp_path / "paper.yaml").write_text("schema: manuscript-guard/paper/1\n", encoding="utf-8")

    def broken(*_args, **_kwargs):
        raise AttributeError("'NoneType' object has no attribute 'findings'")

    monkeypatch.setattr(cli, "_gate_run", broken)
    state = inspect(tmp_path)
    assert "the gates could not be run" in state.error
    (found,) = _records(kept)
    assert found["kind"] == "command" and found["name"] == "the gates' findings"


def test_a_hook_that_fails_lets_the_call_go_ahead_and_is_recorded(kept, monkeypatch,
                                                                  capsys) -> None:
    def broken(_payload) -> int:
        raise TypeError("expected str, got NoneType")

    monkeypatch.setitem(hooks.HANDLERS, "stop", broken)
    assert hooks.dispatch("stop", {}) == 0
    assert capsys.readouterr().out == ""
    (found,) = _records(kept)
    assert found["kind"] == "hook" and found["name"] == "stop"


def test_the_next_session_start_says_once_that_a_hook_failed(kept, tmp_path, monkeypatch,
                                                             capsys) -> None:
    def broken(_payload) -> int:
        raise TypeError("expected str, got NoneType")

    monkeypatch.setitem(hooks.HANDLERS, "guard-write", broken)
    hooks.dispatch("guard-write", {})
    monkeypatch.chdir(tmp_path)
    started = {"source": "startup", "cwd": str(tmp_path), "session_id": "s"}
    hooks.session_start(started)
    first = json.loads(capsys.readouterr().out)
    assert "hooks failed on errors of one kind" in first["systemMessage"]
    assert "nothing was sent" in first["hookSpecificOutput"]["additionalContext"]
    hooks.session_start(started)
    assert "hooks failed" not in capsys.readouterr().out


def test_the_newest_twenty_are_kept_and_no_other_file_is_touched(kept) -> None:
    kept.mkdir(parents=True)
    theirs = kept / "notes.txt"
    theirs.write_text("mine", encoding="utf-8")
    look_alike = kept / "0123456789ab.json"
    look_alike.write_text('{"not": "a record"}', encoding="utf-8")
    for number in range(25):
        try:
            raise RuntimeError(number)
        except RuntimeError as exc:
            assert crashes.record(exc, kind=crashes.GATE, name=f"G{number}") is not None
    assert len(_records(kept)) == 20 + 1  # the look-alike is read but never deleted
    assert theirs.read_text(encoding="utf-8") == "mine"
    assert look_alike.exists()
    assert any(r.get("name") == "G24" for r in _records(kept))


def test_the_message_is_kept_with_the_project_and_home_taken_out(kept, tmp_path,
                                                                 monkeypatch) -> None:
    project = tmp_path / "study"
    project.mkdir()
    (project / "paper.yaml").write_text("schema: manuscript-guard/paper/1\n", encoding="utf-8")
    monkeypatch.chdir(project)
    try:
        raise FileNotFoundError(f"{project / 'data' / 'cohort.csv'} is not there")
    except FileNotFoundError as exc:
        path = crashes.record(exc, kind=crashes.COMMAND)
    found = json.loads(path.read_text(encoding="utf-8"))
    assert str(project) not in found["message"]
    assert found["message"].startswith("<PROJECT>")


def test_a_path_in_an_error_as_python_shows_it_is_taken_out(kept, tmp_path,
                                                            monkeypatch) -> None:
    """Python shows a path in an OSError's message through repr(), with each backslash
    doubled on Windows."""
    project = tmp_path / "study"
    project.mkdir()
    (project / "paper.yaml").write_text("schema: manuscript-guard/paper/1\n", encoding="utf-8")
    monkeypatch.chdir(project)
    try:
        open(project / "data" / "cohort.csv", encoding="utf-8")  # noqa: SIM115 - it raises
    except FileNotFoundError as exc:
        path = crashes.record(exc, kind=crashes.COMMAND)
    message = json.loads(path.read_text(encoding="utf-8"))["message"]
    assert "<PROJECT>" in message
    assert tmp_path.name not in message


def test_the_project_is_the_one_the_command_names(kept, tmp_path, monkeypatch) -> None:
    project = tmp_path / "study"
    project.mkdir()
    (project / "paper.yaml").write_text("schema: manuscript-guard/paper/1\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    crashes.invoked("check", ["check", str(project)], start=project)
    try:
        raise ValueError(f"{project / 'manuscript' / 'main.md'} line 3")
    except ValueError as exc:
        path = crashes.record(exc, kind=crashes.COMMAND)
    finally:
        crashes.invoked(None, [])
    assert json.loads(path.read_text(encoding="utf-8"))["message"].startswith("<PROJECT>")


def test_an_error_of_the_system_is_not_said_to_be_the_tools_alone(kept, monkeypatch,
                                                                  capsys) -> None:
    def held(_args) -> int:
        raise PermissionError(13, "Permission denied", "manuscript.docx")

    monkeypatch.setattr(cli, "cmd_stages", held)
    assert cli.main(["stages"]) == 2
    said = capsys.readouterr().err
    assert "not in your files" not in said
    assert "another program holds open" in said and "PermissionError" in said


def test_a_short_option_keeps_no_value_and_words_after_two_dashes_are_no_flags() -> None:
    crashes.invoked("build", ["build", "-omydraft", "--", "-secret-word"])
    try:
        assert crashes._invocation["flags"] == ["-o"]
        assert "mydraft" not in json.dumps(crashes._invocation)
        assert "secret" not in json.dumps(crashes._invocation)
    finally:
        crashes.invoked(None, [])


def test_times_are_kept_finer_than_a_second() -> None:
    assert "." in crashes._now()


def test_an_unattended_session_leaves_the_line_for_the_next_one(kept, tmp_path, monkeypatch,
                                                                capsys) -> None:
    def broken(_payload) -> int:
        raise TypeError("expected str, got NoneType")

    monkeypatch.setitem(hooks.HANDLERS, "guard-write", broken)
    hooks.dispatch("guard-write", {})
    monkeypatch.chdir(tmp_path)
    started = {"source": "startup", "cwd": str(tmp_path), "session_id": "s"}
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ATTENDED", "0")
    hooks.session_start(started)
    assert "hooks failed" not in capsys.readouterr().out
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ATTENDED", "1")
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    hooks.session_start(started)
    assert "hooks failed" in capsys.readouterr().out


def test_the_hook_line_does_not_give_the_agent_the_home_folder(kept, tmp_path, monkeypatch,
                                                               capsys) -> None:
    monkeypatch.setenv(crashes.FOLDER, str(Path.home() / ".mg-test-reports-not-made"))
    try:
        raise TypeError("x")
    except TypeError as exc:
        crashes.record(exc, kind=crashes.HOOK, name="stop")
    try:
        line = crashes.hook_failures()
    finally:
        import shutil

        shutil.rmtree(Path.home() / ".mg-test-reports-not-made", ignore_errors=True)
    assert line is not None and str(Path.home()) not in line
    assert "~" in line


def test_a_record_written_is_said_written_even_if_tidying_fails(kept, monkeypatch) -> None:
    def broken(*_args) -> None:
        raise OSError("cannot list the folder")

    monkeypatch.setattr(crashes, "_rotate", broken)
    try:
        raise RuntimeError("x")
    except RuntimeError as exc:
        assert crashes.record(exc, kind=crashes.COMMAND) is not None


def test_scrub_takes_out_each_spelling_of_the_project_folder(tmp_path) -> None:
    root = tmp_path / "Clinical Study"
    root.mkdir()
    forward = str(root).replace("\\", "/")
    back = forward.replace("/", "\\")
    said = scrub(f"a {forward}/x.md b {back}\\y.md c", root=root, environ={})
    assert forward not in said and back not in said
    assert said.count("<PROJECT>") == 2


def test_scrub_does_not_cut_a_longer_folder_name(tmp_path) -> None:
    root = tmp_path / "study"
    root.mkdir()
    longer = str(tmp_path / "study2" / "x.md")
    assert "<PROJECT>" not in scrub(longer, root=root, environ={})


def test_scrub_replaces_the_home_folder_and_the_temp_folder(tmp_path) -> None:
    home = tmp_path / "home" / "someone"
    said = scrub(f"{home}/notes and {tempfile.gettempdir()}/x", environ={"HOME": str(home),
                                                                         "USERPROFILE": str(home)})
    assert "<HOME>" in said and "<TEMP>" in said
    assert "someone" not in said


def test_scrub_replaces_a_secret_an_address_and_a_password_in_a_link() -> None:
    environ = {"ZENODO_TOKEN": "zen0d0-s3cret-value", "MY_SERVICE_API_KEY": "abcdef123456",
               "SHORT_TOKEN": "yes", "PATH": "/usr/bin"}  # fmt: skip
    text = ("token zen0d0-s3cret-value key abcdef123456 ok yes, mail ada@example.org, "
            "https://user:pass@host.example/x")
    said = scrub(text, environ=environ)
    assert "<SECRET:ZENODO_TOKEN>" in said and "<SECRET:MY_SERVICE_API_KEY>" in said
    assert "zen0d0" not in said and "abcdef123456" not in said
    assert "ok yes," in said  # a value of fewer than six characters is left
    assert "<EMAIL>" in said and "ada@example.org" not in said
    assert "user:pass" not in said and "https://host.example/x" in said


def test_scrub_replaces_the_authors_names_and_orcids(tmp_path) -> None:
    (tmp_path / "authors.yaml").write_text(
        "schema: manuscript-guard/authors/1\nauthors:\n"
        "  - given: Ada\n    family: Lovelace\n    orcid: 0000-0002-1825-0097\n",
        encoding="utf-8",
    )
    said = scrub("Ada Lovelace (0000-0002-1825-0097) wrote; Lovelace agreed; Lovelaces no; "
                 "KeyError: 'lovelace2020'.", root=tmp_path, environ={})  # fmt: skip
    assert "Lovelace " not in said and "0000-0002-1825-0097" not in said
    assert said.count("<AUTHOR-1>") == 3
    assert "Lovelaces" in said  # a name inside a longer word is left
    # A name in another case, as in a citation key, is left: Known gaps says so.
    assert "'lovelace2020'" in said


def _authors_file(folder: Path, given: str, family: str) -> Path:
    (folder / "authors.yaml").write_text(
        f'schema: manuscript-guard/authors/1\nauthors:\n  - given: "{given}"\n'
        f'    family: "{family}"\n', encoding="utf-8")  # fmt: skip
    return folder


def test_scrub_takes_an_address_out_whole_though_it_holds_a_name(tmp_path) -> None:
    root = _authors_file(tmp_path, "Ada", "Lovelace")
    said = scrub("from ada.lovelace@uni.edu and Lovelace", root=root, environ={})
    assert "uni.edu" not in said and "ada." not in said
    assert said == "from <EMAIL> and <AUTHOR-1>"


def test_scrub_leaves_the_errors_own_words_and_its_labels(tmp_path) -> None:
    text = ("line 3, column 5 in <HOME>/x and <TEMP>; may not; KeyError: 'page'; "
            "KeyError: 'page_size'; no attribute 'line_no'; '_page_count'; li_x; ma2")
    for family in ("Line", "Home", "Temp", "May", "Page", "Li", "Ma"):
        folder = tmp_path / family
        folder.mkdir()
        assert scrub(text, root=_authors_file(folder, "Ada", family), environ={}) == text


def test_scrub_matches_a_name_with_either_apostrophe(tmp_path) -> None:
    folder = tmp_path / "typographic"
    folder.mkdir()
    said = scrub("by O\N{RIGHT SINGLE QUOTATION MARK}Brien", environ={},
                 root=_authors_file(folder, "Ada", "O'Brien"))  # fmt: skip
    assert said == "by <AUTHOR-1>"


def test_the_crash_sentence_does_not_give_the_agent_the_home_folder(kept, monkeypatch,
                                                                    capsys) -> None:
    folder = Path.home() / ".mg-test-reports-said"
    monkeypatch.setenv(crashes.FOLDER, str(folder))
    monkeypatch.setattr(cli, "cmd_stages", _broken())
    try:
        cli.main(["stages"])
    finally:
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
    said = capsys.readouterr().err
    assert str(Path.home()) not in said and "~" in said


def test_the_hook_line_dates_from_the_last_notice(kept) -> None:
    try:
        raise TypeError("x")
    except TypeError as exc:
        path = crashes.record(exc, kind=crashes.HOOK, name="stop")
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**record, "first_seen": "2026-09-01T00:00:00.000000+00:00"}),
                    encoding="utf-8")  # fmt: skip
    (kept / "hooks-said.json").write_text(
        json.dumps({"schema": crashes.SCHEMA, "said": "2026-10-20T00:00:00.000000+00:00"}),
        encoding="utf-8")  # fmt: skip
    line = crashes.hook_failures()
    assert line is not None and "since 2026-10-20" in line


def test_the_diagnostics_import_nothing_that_could_send() -> None:
    """`urllib.parse` writes an address and sends nothing; every other way out is refused,
    `webbrowser` among them, which `report-issue --open` uses from the command line instead."""
    sending = ("urllib.request", "urllib.robotparser", "http", "socket", "ssl", "subprocess",
               "requests", "smtplib", "ftplib", "webbrowser", "asyncio")  # fmt: skip
    for path in DIAGNOSTICS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name != "urllib", (path.name, name)
                assert not any(name == out or name.startswith(out + ".") for out in sending), (
                    path.name, name)


def test_the_folder_is_the_users_own_by_system(monkeypatch, tmp_path) -> None:
    environ = {"LOCALAPPDATA": str(tmp_path), "XDG_STATE_HOME": str(tmp_path)}
    where = crashes.folder(environ)
    assert where is not None and where.parts[-2:] == ("manuscript-guard", "reports")
    if os.name == "nt":
        assert where.parent.parent == tmp_path
    assert crashes.folder({**environ, crashes.OFF: "1"}) is None
    assert crashes.folder({**environ, "CI": "true"}) is None
    assert crashes.folder({crashes.FOLDER: str(tmp_path / "x")}) == tmp_path / "x"


def test_a_fingerprint_leaves_out_line_numbers() -> None:
    inner = [{"file": "manuscript_guard/gates/numbers.py", "line": 10, "function": "f"}]
    moved = [{"file": "manuscript_guard/gates/numbers.py", "line": 99, "function": "f"}]
    elsewhere = [{"file": "manuscript_guard/gates/numbers.py", "line": 10, "function": "g"}]
    one = crashes.fingerprint("gate", "G2", "KeyError", inner)
    assert one == crashes.fingerprint("gate", "G2", "KeyError", moved)
    assert one != crashes.fingerprint("gate", "G2", "KeyError", elsewhere)
    assert one != crashes.fingerprint("gate", "G2", "ValueError", inner)
