"""The hooks.

Three properties matter more than any individual behaviour, and each has a test that would
fail loudly if it stopped holding:

* a hook never breaks the session, whatever it is handed;
* a hook blocks only what is unambiguous;
* the fast paths stay fast, because they fire on every edit and every shell command.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import manuscript_guard
from manuscript_guard import hooks
from manuscript_guard.hooks import HANDLERS, SUBMISSION_MARKERS, dispatch, main


def run(handler: str, payload: dict, capsys) -> dict | None:
    assert dispatch(handler, payload) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def decision(result: dict | None) -> str | None:
    if not result:
        return None
    return result.get("hookSpecificOutput", {}).get("permissionDecision")


def context(result: dict | None) -> str:
    if not result:
        return ""
    return result.get("hookSpecificOutput", {}).get("additionalContext", "")


def reason(result: dict | None) -> str:
    if not result:
        return ""
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


# ---------------------------------------------------------------- never breaks


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_input": {}},
        {"tool_input": {"file_path": ""}},
        {"tool_input": {"file_path": "/nowhere/at/all/x.md"}},
        {"tool_input": {"file_path": None}},
        {"tool_input": "not a mapping"},
        {"cwd": "/does/not/exist"},
    ],
)
@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_no_input_breaks_a_hook(handler: str, payload: dict, capsys) -> None:
    """A hook that raises in a half-configured project teaches the author to remove it."""
    assert dispatch(handler, payload) == 0


def test_an_unknown_event_is_ignored() -> None:
    assert dispatch("not-an-event", {}) == 0
    assert main(["not-an-event"]) == 0
    assert main([]) == 0


# ---------------------------------------------------------------- the event as it arrives
#
# An agent tool starts the hook as a process of its own and writes the event on its standard
# input as UTF-8, a name outside ASCII as its own bytes and not as an escape: captured from
# Claude Code on 2026-10-02, and read in Codex's source. On Windows Python reads standard
# input in the ANSI code page unless told otherwise, so the handlers above, which are handed a
# dict, never saw what these do.

#: Either would have Python read standard input as UTF-8 for the hook. An agent tool sets
#: neither, so the hook is started with neither.
ENCODING_SWITCHES = ("PYTHONUTF8", "PYTHONIOENCODING")

#: How standard input is read where nobody says: as the platform decides, which on Windows is
#: the code page, and in a code page on every platform, so that the tests fail everywhere and
#: not only on Windows if the event is decoded as anything but UTF-8 again.
READINGS = pytest.mark.parametrize(
    "environment", [{}, {"PYTHONIOENCODING": "cp1252"}], ids=["platform", "code-page"]
)


def as_sent(payload: dict) -> bytes:
    """The event as an agent tool writes it: UTF-8, nothing escaped that need not be."""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def run_installed(
    handler: str, event: bytes, environment: dict[str, str], cwd: Path | None = None
) -> dict | None:
    """Run the entry point as an agent tool does, and read back what it printed.

    The process is given the source these tests import, so that in a git worktree it is the
    worktree's hooks that run and not an installed copy's.
    """
    env = {key: value for key, value in os.environ.items() if key not in ENCODING_SWITCHES}
    source = str(Path(manuscript_guard.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [source, env.get("PYTHONPATH")]))
    env.update(environment)
    finished = subprocess.run(
        [sys.executable, "-m", "manuscript_guard.hooks", handler],
        input=event,
        capture_output=True,
        env=env,
        cwd=cwd,
        timeout=120,
    )
    assert finished.returncode == 0, finished.stderr
    assert finished.stderr == b"", "a hook has nothing to say on standard error"
    # Printed in ASCII, so whatever reads the answer reads the same in any encoding.
    assert finished.stdout.isascii(), finished.stdout
    out = finished.stdout.strip()
    return json.loads(out) if out else None


def standard_input(raw: bytes, encoding: str) -> io.TextIOWrapper:
    """A standard input holding what a tool wrote, in the encoding Python opened it with."""
    return io.TextIOWrapper(io.BytesIO(raw), encoding=encoding)


@pytest.fixture
def under_an_accent(project: Path, tmp_path: Path) -> Path:
    """The example under a folder named `thèse`: the commonest shape of a name outside ASCII.

    Nothing in the project is accented, the folder it sits in is. A home folder named after
    its owner is enough, and then every path and the `cwd` of every event carry the name.
    """
    home = tmp_path / "thèse"
    home.mkdir()
    return project.rename(home / "paper")


@READINGS
def test_a_results_file_with_an_accented_name_is_refused_under_its_name(
    project: Path, environment: dict[str, str]
) -> None:
    target = project / "results" / "données.json"
    target.touch()
    event = as_sent({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
    assert "é".encode() in event, "the name goes as its own bytes, as the tools send it"

    result = run_installed("guard-write", event, environment)
    assert decision(result) == "deny"
    assert "results/données.json is generated" in reason(result)


@READINGS
def test_an_accented_manuscript_file_gets_its_note_after_an_edit(
    project: Path, environment: dict[str, str]
) -> None:
    path = project / "manuscript" / "méthodes.md"
    path.write_text("It was 3.84.\n", encoding="utf-8")
    event = as_sent({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})

    result = run_installed("after-edit", event, environment)
    assert "manuscript/méthodes.md has 1 number(s) bound to nothing" in context(result)
    assert "'3.84'" in context(result)


@READINGS
def test_a_results_directory_relocated_to_an_accented_name_is_still_guarded(
    project: Path, environment: dict[str, str]
) -> None:
    import yaml

    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["paths"] = {"results": "résultats"}
    paper.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    target = project / "résultats" / "01_disproportionality.json"
    target.parent.mkdir()
    target.touch()
    event = as_sent({"tool_name": "Write", "tool_input": {"file_path": str(target)}})

    result = run_installed("guard-write", event, environment)
    assert decision(result) == "deny"
    assert "machine-written" in reason(result)


@READINGS
def test_a_project_under_an_accented_folder_is_guarded_and_gets_its_status_line(
    under_an_accent: Path, environment: dict[str, str]
) -> None:
    target = under_an_accent / "results" / "01_disproportionality.json"
    event = as_sent({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
    assert decision(run_installed("guard-write", event, environment)) == "deny"

    started = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(under_an_accent)}
    assert "manuscript-guard: paper at stage" in context(
        run_installed("session-start", as_sent(started), environment)
    )


@READINGS
def test_a_submission_from_a_project_under_an_accented_folder_is_held(
    under_an_accent: Path, environment: dict[str, str]
) -> None:
    """The submission guard reads `cwd` from the event too, and its miss costs the most."""
    import shutil

    shutil.rmtree(under_an_accent / "review")
    command = {"command": "manuscript-guard submit"}
    event = as_sent({"tool_name": "Bash", "tool_input": command, "cwd": str(under_an_accent)})

    result = run_installed("guard-submission", event, environment)
    assert decision(result) == "deny"
    assert "submission check(s) failing in paper" in reason(result)


def test_a_byte_order_mark_before_the_event_is_not_part_of_it(project: Path) -> None:
    """Windows PowerShell puts one in front of what it pipes to a program as UTF-8."""
    target = project / "results" / "hand.json"
    event = as_sent({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
    assert decision(run_installed("guard-write", b"\xef\xbb\xbf" + event, {})) == "deny"


def test_an_event_that_is_not_utf8_still_guards_by_what_can_be_read(project: Path) -> None:
    """A wrapper that hands the event on in the code page, which is how main read it.

    Reading nothing from it would switch the guard off for that file. Where the code page is
    the one standard input has, the name is read whole, as it was before. Elsewhere the letter
    is lost, and the folder and the extension still say that the file is generated.
    """
    target = project / "results" / "données.json"
    target.touch()
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
    event = json.dumps(payload, ensure_ascii=False).encode("cp1252")

    result = run_installed("guard-write", event, {"PYTHONIOENCODING": "cp1252"})
    assert decision(result) == "deny"
    assert "results/données.json is generated" in reason(result)

    result = run_installed("guard-write", event, {"PYTHONIOENCODING": "utf-8"})
    assert decision(result) == "deny"
    assert "results/donn" in reason(result)
    assert "es.json is generated" in reason(result)


#: Bytes that are no event: nothing, no JSON, a code page, no text in any encoding, UTF-8 cut
#: in the middle of a letter, and JSON that is not an object.
NO_EVENT = {
    "empty": b"",
    "not-json": b"not json",
    "code-page": b'{"tool_input": {"file_path": "results/donn\xe9es.json"}}',
    "no-text": b"\xff\xfe\x00\x81",
    "cut-short": b'{"tool_input": {"file_path": "m\xc3',
    "a-list": b"[]",
    "a-string": b'"\xc3\xa9"',
}


@pytest.mark.parametrize("handler", sorted(HANDLERS))
@pytest.mark.parametrize("encoding", ["cp1252", "utf-8"])
@pytest.mark.parametrize("event", list(NO_EVENT.values()), ids=list(NO_EVENT))
def test_no_bytes_break_a_hook(
    handler: str, encoding: str, event: bytes, tmp_path: Path, monkeypatch, capsys
) -> None:
    """Whatever arrives, in whatever encoding, the hook ends with 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", standard_input(event, encoding))
    assert main([handler]) == 0


@pytest.mark.parametrize("name", ["not-json", "no-text", "cut-short", "a-list"])
def test_bytes_that_are_no_event_end_in_silence(name: str, tmp_path: Path) -> None:
    """The same for the process an agent tool starts: 0, and not a word on either stream."""
    assert run_installed("guard-write", NO_EVENT[name], {}, cwd=tmp_path) is None


@pytest.mark.parametrize("encoding", ["cp1252", "utf-8", "ascii", "cp932"])
def test_the_event_is_read_as_utf8_whatever_encoding_standard_input_has(
    encoding: str, monkeypatch
) -> None:
    payload = {"cwd": "C:\\Users\\Zoé\\thèse", "tool_input": {"file_path": "méthodes 日本語.md"}}
    monkeypatch.setattr(sys, "stdin", standard_input(as_sent(payload), encoding))
    assert hooks._read_event() == payload


def test_a_standard_input_with_no_bytes_under_it_is_read_as_text(monkeypatch) -> None:
    """What a test, or a program that calls `dispatch` itself, puts in its place."""
    payload = {"tool_input": {"file_path": "méthodes.md"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False)))
    assert hooks._read_event() == payload


def test_no_standard_input_at_all_is_an_empty_event(monkeypatch) -> None:
    """Started with none, as `pythonw` starts a program, there is no event and no error."""
    monkeypatch.setattr(sys, "stdin", None)
    assert hooks._read_event() == {}


# ---------------------------------------------------------------- the write guard


@pytest.mark.parametrize(
    ("relative", "fragment"),
    [
        ("results/01_disproportionality.json", "machine-written"),
        ("results/01_disproportionality.json.sha256", "digest"),
        ("build/manuscript.docx", "regenerated"),
        ("profiles/reporting/STROBE.yaml", "transcribed"),
    ],
)
def test_generated_files_cannot_be_edited(
    project: Path, relative: str, fragment: str, capsys
) -> None:
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    result = run("guard-write", {"tool_input": {"file_path": str(target)}}, capsys)
    assert decision(result) == "deny"
    assert fragment in reason(result)
    assert relative in reason(result)


@pytest.mark.parametrize(
    "relative",
    [
        "manuscript/main.md",
        "analysis/01_disproportionality.py",
        "paper.yaml",
        "literature/ledger.yaml",
        "review/panel-1.yaml",
        "methods.lock",
        "figures/forest.py",
    ],
)
def test_files_a_person_writes_are_allowed(project: Path, relative: str, capsys) -> None:
    """Only generated files are blocked. Everything an author edits stays editable."""
    result = run("guard-write", {"tool_input": {"file_path": str(project / relative)}}, capsys)
    assert result is None


def test_a_file_outside_any_project_is_ignored(tmp_path: Path, capsys) -> None:
    loose = tmp_path / "notes.json"
    loose.touch()
    assert run("guard-write", {"tool_input": {"file_path": str(loose)}}, capsys) is None


def test_a_recipe_stays_editable(project: Path, capsys) -> None:
    """The denial message for a transcribed profile says to edit the recipe and re-run.

    The rule that produced that message denied `profiles/reporting/**.yaml` — which includes
    `profiles/reporting/recipes/*.recipe.yaml`, the exact file it was sending you to.
    """
    recipe = project / "profiles" / "reporting" / "recipes" / "LOCAL.recipe.yaml"
    recipe.parent.mkdir(parents=True, exist_ok=True)
    recipe.touch()
    assert run("guard-write", {"tool_input": {"file_path": str(recipe)}}, capsys) is None


def test_a_notebook_edit_is_guarded_too(project: Path, capsys) -> None:
    """hooks.json registers NotebookEdit, and that tool sends `notebook_path`.

    The handler read only `file_path`, so it returned None every time and the matcher was
    dead: a notebook could write straight into results/.
    """
    target = project / "results" / "hand.json"
    target.touch()
    result = run("guard-write", {"tool_input": {"notebook_path": str(target)}}, capsys)
    assert decision(result) == "deny"


def test_the_guard_follows_a_relocated_results_directory(project: Path, capsys) -> None:
    """`paths:` in paper.yaml can move results/, and the guard read the literal name."""
    import yaml

    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["paths"] = {"results": "outputs"}
    paper.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (project / "outputs").mkdir(exist_ok=True)
    target = project / "outputs" / "01_disproportionality.json"
    target.touch()

    result = run("guard-write", {"tool_input": {"file_path": str(target)}}, capsys)
    assert decision(result) == "deny"
    assert "machine-written" in reason(result)


# ---------------------------------------------------------------- after an edit


def test_unbound_numbers_are_reported_the_moment_they_are_written(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text("# Results\n\nThe odds ratio was 3.84 in 77 cases.\n", encoding="utf-8")
    result = run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys)
    text = context(result)
    assert "2 number(s) bound to nothing" in text
    assert "'3.84'" in text
    assert "{{results." in text, "the message says what to do about it"


def test_a_clean_manuscript_says_nothing(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    assert run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys) is None


def test_editing_an_analysis_file_warns_that_results_are_stale(project: Path, capsys) -> None:
    path = project / "analysis" / "01_disproportionality.py"
    result = run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys)
    assert "stale until it is re-run" in context(result)
    assert "methods" in context(result)


def test_markdown_outside_the_manuscript_is_left_alone(project: Path, capsys) -> None:
    path = project / "design" / "plan.md"
    assert run("after-edit", {"tool_input": {"file_path": str(path)}}, capsys) is None


# ---------------------------------------------------------------- the submission guard


@pytest.mark.parametrize(
    "command",
    [
        "manuscript-guard submit",
        "cd example && manuscript-guard submit --offline",
        "FOO=1 manuscript-guard check --submission",
        "zip -r out.zip build/submission",
        "scp build/manuscript.docx server:/tmp",
    ],
)
def test_submission_shaped_commands_are_recognised(command: str) -> None:
    """Matched against the whole string: a leading assignment or `cd x &&` defeats a
    prefix rule, which is exactly how a submission slipped past the predecessor's guard."""
    assert SUBMISSION_MARKERS.search(command)


@pytest.mark.parametrize(
    "command",
    ["ls -la", "git status", "pytest -q", "python analysis/01_model.py", "manuscript-guard check"],
)
def test_ordinary_commands_are_not_touched(command: str, capsys) -> None:
    assert SUBMISSION_MARKERS.search(command) is None
    assert run("guard-submission", {"tool_input": {"command": command}}, capsys) is None


def test_a_failing_submission_blocks_the_command(project: Path, capsys) -> None:
    import shutil

    shutil.rmtree(project / "review")
    result = run(
        "guard-submission",
        {"tool_input": {"command": "manuscript-guard submit"}, "cwd": str(project)},
        capsys,
    )
    assert decision(result) == "deny"
    assert "submission check" in reason(result)
    assert "check --submission" in reason(result)


def test_a_passing_submission_is_not_blocked(project: Path, capsys) -> None:
    result = run(
        "guard-submission",
        {"tool_input": {"command": "manuscript-guard submit"}, "cwd": str(project)},
        capsys,
    )
    assert result is None


# ---------------------------------------------------------------- session start


def test_session_start_reports_the_stage_and_the_count(project: Path, capsys) -> None:
    text = context(run("session-start", {"cwd": str(project)}, capsys))
    assert "stage 'drafting'" in text
    assert "0 failing" in text


def test_session_start_names_what_becomes_due_next(tmp_path: Path, capsys) -> None:
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="Something new")
    (root / "paper.yaml").write_text(
        (root / "paper.yaml").read_text(encoding="utf-8") + "stage: design\n", encoding="utf-8"
    )
    text = context(run("session-start", {"cwd": str(root)}, capsys))
    assert "become due at 'drafting'" in text


# ---------------------------------------------------------------- a project that cannot be read
#
# `check` stops on a file of the project's own that it cannot use, before there is one
# finding, and says which file in a sentence written for the author. The hooks took that for
# an unexpected failure and ended in silence, so a submission from such a project went through
# with nothing checked. They are started here as a tool starts them.

SUBMIT = {"tool_name": "Bash", "tool_input": {"command": "manuscript-guard submit"}}

#: One file of each kind that is read before any gate runs, left as an author can leave it: a
#: results file made by hand and never filled, and YAML with a bracket still open. Then the
#: files that parse and still cannot be used, or cannot be read as text at all: `check` ended
#: in a traceback on each, so the guard was silent after it had learned to refuse the first
#: four. With each, what `check` says of it after the name of the file.
UNREADABLE = {
    "results": ("results/hand.json", b"", "cannot parse"),
    "paper": ("paper.yaml", b"title: [unclosed\n", "cannot parse"),
    "authors": ("authors.yaml", b"authors: [unclosed\n", "cannot parse"),
    "ledger": ("literature/ledger.yaml", b"entries: [unclosed\n", "cannot parse"),
    "utf-16": ("results/hand.json", b"\xff\xfe\x7b", "cannot read as UTF-8: the file is UTF-16"),
    "code page": (
        "authors.yaml",
        b"authors:\n  - name: Ren\xe9e\n",
        "cannot read as UTF-8: the byte 0xe9 on line 2",
    ),
    "list": ("paper.yaml", b"- a\n- b\n", "holds a list where"),
    "folders": ("paper.yaml", b"paths: [results]\n", "`paths` holds a list where"),
    "date": (
        "literature/ledger.yaml",
        b"entries:\n  - verified_on: 2026-09-31\n",
        "cannot parse: ",
    ),
}


@pytest.fixture(params=list(UNREADABLE))
def unreadable(request, project: Path) -> tuple[Path, str]:
    """The example with one file `check` cannot use, and how its sentence about it begins."""
    relative, content, said = UNREADABLE[request.param]
    (project / relative).write_bytes(content)
    return project, f"{Path(relative).name}: {said}"


def test_a_submission_from_a_project_that_cannot_be_read_is_refused(
    unreadable: tuple[Path, str],
) -> None:
    project, said = unreadable
    event = as_sent({**SUBMIT, "cwd": str(project)})

    result = run_installed("guard-submission", event, {})
    assert decision(result) == "deny"
    assert f"cannot check {project.name}" in reason(result)
    assert said in reason(result), "the project's own sentence, file named"
    assert f"`{hooks.FULL_CHECK}`" in reason(result)


def test_the_refusal_names_a_command_the_guard_lets_through(project: Path, capsys) -> None:
    """`--submission` is one of the guard's own markers. A refusal that said to run
    `check --submission` sent an agent back into the same refusal, in a project it had just
    repaired as much as in the broken one.

    The command it names instead ends in the word `submission`, which the guard matches
    after `cp` or `git push` on the same line. So the refusal says to run it on its own.
    """
    (project / "results" / "hand.json").write_bytes(b"")
    refused = run("guard-submission", {**SUBMIT, "cwd": str(project)}, capsys)
    named = re.findall(r"`(manuscript-guard\s[^`]*)`", reason(refused))
    assert named, "the refusal says what to run next"

    (project / "results" / "hand.json").unlink()
    shutil.rmtree(project / "review")  # readable again, and failing at submission
    for command in named:
        event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(project)}
        assert run("guard-submission", event, capsys) is None, command
        assert SUBMISSION_MARKERS.search(f"cd paper && {command}") is None, command
        assert f"`{command}` on its own" in reason(refused)
        assert SUBMISSION_MARKERS.search(f"git push && {command}"), "why it has to be alone"


def test_it_is_refused_from_a_folder_inside_the_project_as_well(project: Path) -> None:
    (project / "results" / "hand.json").write_bytes(b"")
    event = as_sent({**SUBMIT, "cwd": str(project / "manuscript")})

    result = run_installed("guard-submission", event, {})
    assert decision(result) == "deny"
    assert "hand.json: cannot parse" in reason(result)


@READINGS
def test_the_sentence_names_a_file_under_an_accented_folder_whole(
    under_an_accent: Path, environment: dict[str, str]
) -> None:
    """The sentence carries the path of the file, and the path the name of the folder."""
    (under_an_accent / "results" / "hand.json").write_bytes(b"")
    event = as_sent({**SUBMIT, "cwd": str(under_an_accent)})

    result = run_installed("guard-submission", event, environment)
    assert decision(result) == "deny"
    assert str(Path("thèse") / "paper" / "results" / "hand.json") in reason(result)


@pytest.mark.parametrize("command", ["manuscript-guard submit", "cp ~/Downloads/letter.docx ."])
def test_a_submission_shaped_command_outside_any_project_is_left_alone(
    command: str, tmp_path: Path
) -> None:
    """No project is the same error as a project that cannot be read, and is not refused.

    `find_root` raises it wherever there is no `paper.yaml` above. A guard that refused on it
    would refuse every command naming a `.docx` on the whole machine.
    """
    bash = {"tool_name": "Bash", "tool_input": {"command": command}}
    for cwd in (tmp_path, tmp_path / "removed-since"):
        event = as_sent({**bash, "cwd": str(cwd)})
        assert run_installed("guard-submission", event, {}) is None
    # No `cwd` in the event: the folder the hook was started in.
    assert run_installed("guard-submission", as_sent(bash), {}, cwd=tmp_path) is None


def test_session_start_says_why_a_project_cannot_be_checked(
    unreadable: tuple[Path, str],
) -> None:
    project, said = unreadable
    started = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(project)}

    result = run_installed("session-start", as_sent(started), {})
    assert f"manuscript-guard: {project.name} cannot be checked" in context(result)
    assert said in context(result)
    assert "`manuscript-guard check`" in context(result)
    assert decision(result) is None, "it is said, and nothing is blocked"
    assert "systemMessage" not in result


def test_a_results_file_is_still_guarded_in_a_project_that_cannot_be_read(
    unreadable: tuple[Path, str], capsys
) -> None:
    """The write guard asks `paper.yaml` where the results are kept, and with no answer keeps
    to the folder's usual name.

    It caught the error a file that is not UTF-8 used to raise, and went on. That file now
    raises the project's own error, which it did not catch: the guard ended in silence and
    the edit went through. A `paper.yaml` that does not parse had always ended it so.
    """
    project, _said = unreadable
    edit = {"tool_input": {"file_path": str(project / "results" / "x.json")}, "cwd": str(project)}

    result = run("guard-write", edit, capsys)
    assert decision(result) == "deny"
    assert "results/x.json is generated, not written" in reason(result)


def test_a_failure_that_is_not_the_projects_own_still_ends_in_silence(
    project: Path, monkeypatch, capsys
) -> None:
    """Only an error the project words for its author is passed on.

    Anything else is a fault of the tool. Refusing on it would stop every command that names
    a `.docx` in a project whose author can do nothing about it.
    """

    def broken(*_args, **_kwargs):
        raise RuntimeError("anything at all")

    monkeypatch.setattr("manuscript_guard.cli._run_gates", broken)
    assert run("guard-submission", {**SUBMIT, "cwd": str(project)}, capsys) is None
    assert run("session-start", {"cwd": str(project), "source": "startup"}, capsys) is None


# ---------------------------------------------------------------- a CLI older than its plugin

UPGRADE_PIP = "pip install --upgrade git+https://github.com/BasileChretien/manuscript-guard"
UPGRADE_PIPX = "pipx install --force git+https://github.com/BasileChretien/manuscript-guard"


def plugin_at(root: Path, version: object) -> Path:
    """A plugin directory as Claude Code's cache holds one, at the given version."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "manuscript-guard", "version": version}), encoding="utf-8"
    )
    return root


def test_a_plugin_newer_than_the_cli_says_so_with_the_upgrade_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from manuscript_guard import __version__

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", "99.0.0")))
    result = run("session-start", {"cwd": str(tmp_path), "source": "startup"}, capsys)
    assert result is not None
    shown = result["systemMessage"]
    # Both versions and both upgrade commands: pipx has no `upgrade` for a git install.
    for needle in ("99.0.0", __version__, UPGRADE_PIP, UPGRADE_PIPX):
        assert needle in shown, needle
    assert shown in context(result), "the model is told as well as the person"
    assert decision(result) is None, "a stale CLI blocks nothing"


def test_the_notice_comes_alongside_the_status_line_in_a_project(
    project: Path, monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", "99.0.0")))
    text = context(run("session-start", {"cwd": str(project), "source": "startup"}, capsys))
    assert "stage 'drafting'" in text
    assert "99.0.0" in text


def test_the_notice_comes_alongside_the_reason_a_project_cannot_be_checked(
    project: Path, monkeypatch, tmp_path: Path, capsys
) -> None:
    (project / "results" / "hand.json").write_bytes(b"")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", "99.0.0")))
    result = run("session-start", {"cwd": str(project), "source": "startup"}, capsys)
    assert "hand.json: cannot parse" in context(result)
    assert "99.0.0" in context(result)
    assert "cannot parse" not in result["systemMessage"], "the notice alone is shown"


@pytest.mark.parametrize("version", ["0.0.1", None])
def test_a_cli_at_or_past_the_plugin_says_nothing(
    version: str | None, tmp_path: Path, monkeypatch, capsys
) -> None:
    from manuscript_guard import __version__

    shipped = __version__ if version is None else version  # None: exactly equal
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", shipped)))
    assert run("session-start", {"cwd": str(tmp_path), "source": "startup"}, capsys) is None


def test_without_a_plugin_root_it_stays_silent(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    assert run("session-start", {"cwd": str(tmp_path), "source": "startup"}, capsys) is None


@pytest.mark.parametrize(
    "broken",
    ["no-such-directory", "empty", "not-json", "list", "no-version", "number", "prerelease"],
)
def test_a_plugin_root_it_cannot_read_stays_silent(
    broken: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    root = tmp_path / "cache"
    if broken != "no-such-directory":
        (root / ".claude-plugin").mkdir(parents=True)
        body = {
            "empty": "",
            "not-json": "{",
            "list": "[]",
            "no-version": '{"name": "manuscript-guard"}',
            "number": '{"version": 99}',
            "prerelease": '{"version": "99.0.0-rc1"}',
        }[broken]
        (root / ".claude-plugin" / "plugin.json").write_text(body, encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    assert run("session-start", {"cwd": str(tmp_path), "source": "startup"}, capsys) is None


@pytest.mark.parametrize("source", ["clear", "compact"])
def test_it_is_said_once_per_session_not_again_after_a_clear_or_a_compact(
    source: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", "99.0.0")))
    assert run("session-start", {"cwd": str(tmp_path), "source": source}, capsys) is None


@pytest.mark.parametrize(
    ("plugin", "warns"),
    [
        ("0.2.99", False),  # older: 99 < 260, though "99" sorts after "260" as text
        ("0.2.9", False),
        ("0.2.260", False),
        ("0.2.259", False),
        ("0.2.261", True),
        ("0.10.0", True),  # newer: 10 > 2, though "10" sorts before "2" as text
        ("0.2.1000", True),  # newer: 1000 > 260, though "1000" sorts before "260" as text
        ("0.2.260.1", True),
        ("1.0", True),
    ],
)
def test_versions_are_compared_as_numbers_not_as_text(
    plugin: str, warns: bool, tmp_path: Path, monkeypatch, capsys
) -> None:
    """A comparison of the strings gets 0.2.99 against 0.2.260 and 0.10.0 against 0.2.260
    the wrong way round, and every other test here would still pass."""
    monkeypatch.setattr("manuscript_guard.__version__", "0.2.260")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", plugin)))
    result = run("session-start", {"cwd": str(tmp_path), "source": "startup"}, capsys)
    assert (result is not None) == warns


def test_the_notice_names_the_version_without_the_spaces_around_it(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", " 99.0.0 ")))
    result = run("session-start", {"cwd": str(tmp_path), "source": "startup"}, capsys)
    assert result is not None
    assert "at 99.0.0 but" in result["systemMessage"]


def absurd_plugin_root(kind: str, root: Path) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
    body = {
        # int() refuses more than 4300 digits, and json.loads gives up on deep nesting.
        "endless-version": json.dumps({"version": "9" * 5000}),
        "deep-nesting": "[" * 100_000 + "]" * 100_000,
    }[kind]
    (root / ".claude-plugin" / "plugin.json").write_text(body, encoding="utf-8")
    return root


@pytest.mark.parametrize("kind", ["endless-version", "deep-nesting"])
def test_an_absurd_plugin_manifest_never_costs_the_status_line(
    kind: str, project: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(absurd_plugin_root(kind, tmp_path / "cache")))
    result = run("session-start", {"cwd": str(project), "source": "startup"}, capsys)
    assert "stage 'drafting'" in context(result)
    assert "systemMessage" not in result


def test_a_failing_check_for_the_notice_never_costs_the_status_line(
    project: Path, monkeypatch, capsys
) -> None:
    """Whatever the check does, the line about the project is still said."""

    def broken() -> str:
        raise RuntimeError("anything at all")

    monkeypatch.setattr("manuscript_guard.hooks.stale_cli_notice", broken)
    result = run("session-start", {"cwd": str(project), "source": "startup"}, capsys)
    assert "stage 'drafting'" in context(result)


@pytest.mark.parametrize("handler", sorted(set(HANDLERS) - {"session-start"}))
def test_no_other_hook_repeats_it(handler: str, tmp_path: Path, monkeypatch, capsys) -> None:
    """These fire on every edit and every shell command; the notice is for the start."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_at(tmp_path / "cache", "99.0.0")))
    payload = {"cwd": str(tmp_path), "tool_input": {"command": "ls", "file_path": ""}}
    assert run(handler, payload, capsys) is None


# ---------------------------------------------------------------- Codex's input
#
# Codex runs the same hooks, with the same event names and the same output. One input differs:
# it edits files with a tool named `apply_patch`, and what the hook receives is the patch's
# text in `tool_input.command`, with no `file_path`. The files are named in the patch's
# headers, relative to `cwd`. The payloads below are shaped as Codex builds them
# (codex-rs/core/src/tools/handlers/apply_patch.rs), and the patches follow the grammar at the
# top of codex-rs/apply-patch/src/parser.rs, read on 2026-10-02.


def patch_of(*hunks: str) -> str:
    return "\n".join(["*** Begin Patch", *hunks, "*** End Patch"])


def codex_edit(cwd: Path, patch: str, event: str = "PreToolUse") -> dict:
    return {
        "session_id": "019a-test",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": event,
        "model": "gpt-test",
        "turn_id": "turn-1",
        "permission_mode": "default",
        "tool_name": "apply_patch",
        "tool_use_id": "call-1",
        "tool_input": {"command": patch},
    }


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (patch_of("*** Add File: a/new.md", "+one", "+two"), ["a/new.md"]),
        (patch_of("*** Update File: a/old.md", "@@", "-one", "+two"), ["a/old.md"]),
        # A file moved is written at both ends: its text changes where it was, and it lands
        # where it goes.
        (
            patch_of("*** Update File: a/old.md", "*** Move to: b/new.md", "@@", "-one", "+two"),
            ["a/old.md", "b/new.md"],
        ),
        # Deleting is not writing.
        (patch_of("*** Delete File: a/gone.md"), []),
        (
            patch_of(
                "*** Add File: one.md",
                "+x",
                "*** Delete File: two.md",
                "*** Update File: three.md",
                "@@ def f():",
                " kept",
                "+added",
                "*** End of File",
            ),
            ["one.md", "three.md"],
        ),
        # What Codex's parser lets through: space around a marker, CRLF, the here-document
        # an older model wraps the patch in.
        ("  *** Begin Patch\r\n *** Add File: a.md \r\n+x\r\n*** End Patch\r\n", ["a.md"]),
        ("<<'EOF'\n*** Begin Patch\n*** Add File: a.md\n+x\n*** End Patch\nEOF\n", ["a.md"]),
        # A header is a line of the patch, never a line of a file's text.
        (
            patch_of(
                "*** Add File: notes.md",
                "+*** Add File: results/x.json",
                "+*** Update File: results/y.json",
            ),
            ["notes.md"],
        ),
        (
            patch_of(
                "*** Update File: notes.md",
                "@@",
                " *** Add File: results/x.json",
                "-*** Update File: results/y.json",
                "+*** Move to: results/z.json",
            ),
            ["notes.md"],
        ),
        # `Move to` is read only before the first change to the file it moves.
        (
            patch_of("*** Update File: a.md", "@@", "-one", "*** Move to: results/z.json"),
            ["a.md"],
        ),
        # `*** End of File` there makes no change, so Codex still takes a move after it.
        (
            patch_of(
                "*** Update File: analysis/hand.json",
                "*** End of File",
                "*** End of File",
                "*** Move to: results/hand.json",
                "@@",
                "-a",
                "+b",
            ),
            ["analysis/hand.json", "results/hand.json"],
        ),
        # A file is moved once.
        (
            patch_of("*** Update File: a.md", "*** Move to: b.md", "*** Move to: results/c.md"),
            ["a.md", "b.md"],
        ),
        # After a file is added or deleted the next header may be indented again, which
        # inside an update it may not.
        (
            patch_of(
                "*** Update File: a.md",
                "@@",
                "+x",
                "*** Add File: b.md",
                "+y",
                " *** Add File: results/c.json",
                "+z",
            ),
            ["a.md", "b.md", "results/c.json"],
        ),
        (
            patch_of(
                "*** Update File: a.md",
                "@@",
                "+x",
                "*** Delete File: b.md",
                " *** Add File: results/c.json",
                "+z",
            ),
            ["a.md", "results/c.json"],
        ),
        # Nothing counts before `*** Begin Patch`, or after `*** End Patch`.
        ("junk\n*** Add File: results/x.json\n+x\n*** End Patch", []),
        (patch_of("*** Add File: a.md", "+x") + "\n*** Add File: results/x.json\n+x", ["a.md"]),
        # The here-document with the line endings of Windows.
        (
            "<<'EOF'\r\n*** Begin Patch\r\n*** Add File: a.md\r\n+x\r\n*** End Patch\r\nEOF\r\n",
            ["a.md"],
        ),
        # A file named by two hunks is one file.
        (
            patch_of("*** Update File: a.md", "@@", "+x", "*** Update File: a.md", "@@", "+y"),
            ["a.md"],
        ),
        ("", []),
        ("not a patch at all", []),
        ("*** Add File: results/x.json\n+x\n", []),  # no `*** Begin Patch`: Codex refuses it
    ],
)
def test_the_files_a_patch_writes_are_read_as_codex_reads_them(patch: str, expected: list) -> None:
    from manuscript_guard.hooks import patch_paths

    assert patch_paths(patch) == expected


@pytest.mark.parametrize("verb", ["Add", "Update"])
@pytest.mark.parametrize(
    ("relative", "fragment"),
    [
        ("results/01_disproportionality.json", "machine-written"),
        ("results/01_disproportionality.json.sha256", "digest"),
        ("build/manuscript.md", "regenerated"),
        ("profiles/reporting/STROBE.yaml", "transcribed"),
    ],
)
def test_a_patch_cannot_write_a_generated_file(
    project: Path, verb: str, relative: str, fragment: str, capsys
) -> None:
    body = ["+{}"] if verb == "Add" else ["@@", "-{}", '+{"edited": true}']
    patch = patch_of(f"*** {verb} File: {relative}", *body)
    result = run("guard-write", codex_edit(project, patch), capsys)
    assert decision(result) == "deny"
    assert fragment in reason(result)
    assert relative in reason(result)
    assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_a_patch_cannot_move_a_file_into_results(project: Path, capsys) -> None:
    patch = patch_of(
        "*** Update File: analysis/hand.json", "*** Move to: results/hand.json", "@@", "-a", "+b"
    )
    result = run("guard-write", codex_edit(project, patch), capsys)
    assert decision(result) == "deny"
    assert "results/hand.json" in reason(result)


def test_one_generated_file_among_several_refuses_the_patch_and_is_the_one_named(
    project: Path, capsys
) -> None:
    """A patch is applied whole, so it is refused whole. The reason names what was wrong."""
    patch = patch_of(
        "*** Update File: manuscript/main.md",
        "@@",
        "-old",
        "+new",
        "*** Add File: results/hand.json",
        "+{}",
        "*** Update File: analysis/01_disproportionality.py",
        "@@",
        "-old",
        "+new",
        "*** Add File: build/notes.md",
        "+x",
    )
    result = run("guard-write", codex_edit(project, patch), capsys)
    assert decision(result) == "deny"
    said = reason(result)
    assert "results/hand.json" in said and "build/notes.md" in said
    assert "main.md" not in said and "01_disproportionality.py" not in said


@pytest.mark.parametrize(
    "hunks",
    [
        ("*** Update File: manuscript/main.md", "@@", "-old", "+new"),
        ("*** Add File: analysis/02_model.py", "+print(1)"),
        ("*** Update File: paper.yaml", "@@", "-stage: drafting", "+stage: submission"),
        ("*** Update File: profiles/reporting/recipes/LOCAL.recipe.yaml", "@@", "-a", "+b"),
        # Removing a fragment whose script is gone is a person's decision, and `check` reports
        # every binding that pointed at it.
        ("*** Delete File: results/01_disproportionality.json",),
        # The text of a manuscript may quote a patch.
        ("*** Update File: manuscript/main.md", "@@", "+*** Add File: results/x.json"),
    ],
)
def test_a_patch_to_files_a_person_writes_is_allowed(project: Path, hunks: tuple, capsys) -> None:
    assert run("guard-write", codex_edit(project, patch_of(*hunks)), capsys) is None


def test_a_patch_is_read_from_the_directory_codex_is_in(project: Path, capsys) -> None:
    patch = patch_of("*** Add File: ../results/hand.json", "+{}")
    result = run("guard-write", codex_edit(project / "manuscript", patch), capsys)
    assert decision(result) == "deny"
    assert "results/hand.json" in reason(result)


def test_a_patch_naming_a_whole_path_is_read_too(project: Path, capsys) -> None:
    patch = patch_of(f"*** Add File: {project / 'results' / 'hand.json'}", "+{}")
    result = run("guard-write", codex_edit(project.parent, patch), capsys)
    assert decision(result) == "deny"


def test_a_patch_outside_any_project_is_ignored(tmp_path: Path, capsys) -> None:
    patch = patch_of("*** Add File: results/x.json", "+{}")
    assert run("guard-write", codex_edit(tmp_path, patch), capsys) is None


def test_a_file_that_cannot_be_read_does_not_cost_the_others_their_refusal(
    project: Path, capsys
) -> None:
    """A name no file system takes stops the reading of that one file, and only that one.

    The NUL is in a directory's name on purpose. In the file's own name it is caught where
    the path is resolved, and the test then passes whether or not one file's error is kept
    from the others."""
    patch = patch_of(
        "*** Add File: bad\x00dir/x.json", "+{}", "*** Add File: build/y.md", "+y"
    )
    result = run("guard-write", codex_edit(project, patch), capsys)
    assert decision(result) == "deny"
    assert "build/y.md" in reason(result)

    noted = patch_of(
        "*** Add File: bad\x00dir/x.py",
        "+x",
        "*** Update File: analysis/01_disproportionality.py",
        "@@",
        "+x",
    )
    text = context(run("after-edit", codex_edit(project, noted, "PostToolUse"), capsys))
    assert "analysis/01_disproportionality.py changed" in text


def test_a_generated_file_a_patch_moves_away_is_refused_where_it_is(project: Path, capsys) -> None:
    """The file is rewritten where it stands before it is moved, so the guard reads the patch
    as it will be applied, both ends of a move, and not as the project is left afterwards."""
    patch = patch_of(
        "*** Update File: results/01_disproportionality.json",
        "*** Move to: analysis/hand.json",
        "@@",
        "-a",
        "+b",
    )
    result = run("guard-write", codex_edit(project, patch), capsys)
    assert decision(result) == "deny"
    assert "results/01_disproportionality.json" in reason(result)


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("authors.yaml", "- name: Zoë\n".encode("cp1252")),
        ("paper.yaml", "title: Étude\n".encode("cp1252")),
        ("authors.yaml", "authors: []\n".encode("utf-16")),
    ],
)
@pytest.mark.parametrize("shape", ["a path", "a patch"])
def test_a_project_file_in_another_encoding_does_not_turn_the_guard_off(
    project: Path, name: str, body: bytes, shape: str, capsys
) -> None:
    """Where the project keeps `results/` is read from the project. When it cannot be read,
    `results/` is where it is by default, and the guard still stands: a file saved in the
    code page of Windows, or as UTF-16 by a shell redirect, is the half-configured project a
    hook has to survive. Asking the project once for a whole patch had moved that question
    out of the place that caught its failure."""
    (project / name).write_bytes(body)
    target = project / "results" / "01_disproportionality.json"
    if shape == "a path":
        payload = {"tool_input": {"file_path": str(target)}}
    else:
        payload = codex_edit(
            project, patch_of("*** Update File: results/01_disproportionality.json", "@@", "+x")
        )
    result = run("guard-write", payload, capsys)
    assert decision(result) == "deny"
    assert "machine-written" in reason(result)


def test_only_the_tool_that_applies_patches_has_its_input_read_as_one(
    project: Path, capsys
) -> None:
    """A shell command may hold the text of a patch, in a here-document or an `echo`. What it
    does with it is the shell's business, and the write guard does not claim to know."""
    patch = patch_of("*** Add File: results/hand.json", "+{}")
    payload = codex_edit(project, patch) | {"tool_name": "Bash"}
    assert run("guard-write", payload, capsys) is None


def test_a_file_named_twice_in_a_patch_is_refused_and_noted_once(project: Path, capsys) -> None:
    twice = ("*** Update File: {0}", "@@", "+x", "*** Update File: {0}", "@@", "+y")
    refused = patch_of(*(line.format("results/hand.json") for line in twice))
    said = reason(run("guard-write", codex_edit(project, refused), capsys))
    assert said.count("results/hand.json") == 1, said

    (project / "manuscript" / "main.md").write_text("It was 3.84.\n", encoding="utf-8")
    noted = patch_of(*(line.format("manuscript/main.md") for line in twice))
    text = context(run("after-edit", codex_edit(project, noted, "PostToolUse"), capsys))
    assert text.count("bound to nothing") == 1, text


def test_the_project_is_read_once_for_a_patch_of_many_files(
    project: Path, monkeypatch, capsys
) -> None:
    """Where `results/` and `build/` are is a question about the project, not about each
    file. Asked per file it took eight seconds for five hundred, of a fifteen-second limit."""
    import manuscript_guard.contracts as contracts

    loaded = []
    real = contracts.load_project

    def counted(*arguments, **named):
        loaded.append(arguments)
        return real(*arguments, **named)

    monkeypatch.setattr(contracts, "load_project", counted)
    hunks = [line for n in range(40) for line in (f"*** Add File: results/{n}.json", "+{}")]
    result = run("guard-write", codex_edit(project, patch_of(*hunks)), capsys)
    assert decision(result) == "deny" and reason(result).count("\n") == 39
    assert len(loaded) == 1, len(loaded)


def test_unbound_numbers_are_reported_after_a_patch(project: Path, capsys) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text("# Results\n\nThe odds ratio was 3.84 in 77 cases.\n", encoding="utf-8")
    patch = patch_of("*** Update File: manuscript/main.md", "@@", "+The odds ratio was 3.84.")
    result = run("after-edit", codex_edit(project, patch, "PostToolUse"), capsys)
    text = context(result)
    assert "manuscript/main.md has 2 number(s) bound to nothing" in text
    assert "'3.84'" in text
    assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_every_file_of_a_patch_gets_its_note(project: Path, capsys) -> None:
    (project / "manuscript" / "main.md").write_text("It was 3.84.\n", encoding="utf-8")
    patch = patch_of(
        "*** Update File: analysis/01_disproportionality.py",
        "@@",
        "-old",
        "+new",
        "*** Update File: manuscript/main.md",
        "@@",
        "+It was 3.84.",
        "*** Update File: paper.yaml",
        "@@",
        "-a",
        "+b",
    )
    text = context(run("after-edit", codex_edit(project, patch, "PostToolUse"), capsys))
    assert "analysis/01_disproportionality.py changed" in text
    assert "manuscript/main.md has 1 number(s) bound to nothing" in text
    assert len(text.splitlines()) == 2, "one line a file, and paper.yaml has none"


def test_a_file_a_patch_moved_is_read_where_it_went(project: Path, capsys) -> None:
    moved = project / "manuscript" / "results-section.md"
    moved.write_text("It was 3.84.\n", encoding="utf-8")
    patch = patch_of(
        "*** Update File: manuscript/draft.md",
        "*** Move to: manuscript/results-section.md",
        "@@",
        "+It was 3.84.",
    )
    text = context(run("after-edit", codex_edit(project, patch, "PostToolUse"), capsys))
    assert "manuscript/results-section.md has 1 number(s) bound to nothing" in text
    assert "draft.md" not in text


def test_an_analysis_file_a_patch_moved_is_named_where_it_went(project: Path, capsys) -> None:
    patch = patch_of(
        "*** Update File: analysis/01_disproportionality.py",
        "*** Move to: analysis/01_ror.py",
        "@@",
        "-old",
        "+new",
    )
    text = context(run("after-edit", codex_edit(project, patch, "PostToolUse"), capsys))
    assert "analysis/01_ror.py changed" in text
    assert len(text.splitlines()) == 1 and "01_disproportionality.py" not in text


def test_a_clean_patch_says_nothing(project: Path, capsys) -> None:
    patch = patch_of("*** Update File: manuscript/main.md", "@@", "-a", "+b")
    assert run("after-edit", codex_edit(project, patch, "PostToolUse"), capsys) is None


def test_the_text_of_a_patch_is_not_a_shell_command(project: Path, capsys) -> None:
    """Both tools put their input in `tool_input.command`. A patch that writes the word
    `--submission` into a file is an edit, and is not held to the submission check."""
    import shutil

    shutil.rmtree(project / "review")
    patch = patch_of(
        "*** Update File: README.md", "@@", "+Run `manuscript-guard check --submission`."
    )
    assert run("guard-submission", codex_edit(project, patch), capsys) is None


def test_a_shell_command_from_codex_is_held_to_the_submission_check(project: Path, capsys) -> None:
    import shutil

    shutil.rmtree(project / "review")
    payload = codex_edit(project, "", "PreToolUse") | {
        "tool_name": "Bash",
        "tool_input": {"command": "cd . && manuscript-guard submit --offline"},
    }
    result = run("guard-submission", payload, capsys)
    assert decision(result) == "deny"
    assert "submission check" in reason(result)


def test_session_start_reads_the_same_from_codex(project: Path, capsys) -> None:
    payload = {
        "session_id": "019a-test",
        "transcript_path": None,
        "cwd": str(project),
        "hook_event_name": "SessionStart",
        "model": "gpt-test",
        "source": "startup",
    }
    result = run("session-start", payload, capsys)
    assert "stage 'drafting'" in context(result)
    assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"


@pytest.mark.parametrize(
    "command",
    [
        None,
        5,
        ["*** Begin Patch"],
        "",
        "*** Begin Patch",
        "*** Begin Patch\n*** Add File: \n*** End Patch",
        "*** Begin Patch\n*** Add File: results/\x00.json\n+x\n*** End Patch",
        "*** Begin Patch\n*** Update File: " + "a/" * 5000 + "x.md\n*** End Patch",
        "*** Begin Patch\n*** Add File: results/<>:|?*.json\n+x\n*** End Patch",
    ],
)
@pytest.mark.parametrize("handler", sorted(set(HANDLERS) - {"session-start"}))
def test_no_patch_breaks_a_hook(handler: str, command: object, project: Path, capsys) -> None:
    payload = codex_edit(project, "") | {"tool_input": {"command": command}}
    assert dispatch(handler, payload) == 0
    capsys.readouterr()


@READINGS
def test_a_patch_naming_accented_files_is_read_as_codex_sends_it(
    project: Path, environment: dict[str, str]
) -> None:
    """Codex writes the event as UTF-8 too, and the names are in the text of the patch.

    `serde_json::to_string` escapes nothing outside ASCII, and its bytes go to the hook as they
    are (codex-rs/hooks/src/events and engine/command_runner.rs, read 2026-10-02).
    """
    written = patch_of(
        "*** Add File: results/données.json",
        "+{}",
        "*** Update File: manuscript/méthodes.md",
        "@@",
        "+It was 3.84.",
    )
    refused = run_installed("guard-write", as_sent(codex_edit(project, written)), environment)
    assert decision(refused) == "deny"
    assert "results/données.json is generated" in reason(refused)
    assert "méthodes" not in reason(refused), "only the generated file is named"

    (project / "manuscript" / "méthodes.md").write_text("It was 3.84.\n", encoding="utf-8")
    edited = patch_of("*** Update File: manuscript/méthodes.md", "@@", "+It was 3.84.")
    event = as_sent(codex_edit(project, edited, "PostToolUse"))
    noted = run_installed("after-edit", event, environment)
    assert "manuscript/méthodes.md has 1 number(s) bound to nothing" in context(noted)
