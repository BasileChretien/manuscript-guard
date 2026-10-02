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
    project: Path, tmp_path: Path, environment: dict[str, str]
) -> None:
    """The commonest shape: nothing in the project is accented, the folder it sits in is.

    A home folder named after its owner is enough, and then every path and the `cwd` of every
    event carry the name.
    """
    home = tmp_path / "thèse"
    home.mkdir()
    root = project.rename(home / "paper")
    target = root / "results" / "01_disproportionality.json"
    event = as_sent({"tool_name": "Write", "tool_input": {"file_path": str(target)}})
    assert decision(run_installed("guard-write", event, environment)) == "deny"

    started = as_sent({"hook_event_name": "SessionStart", "source": "startup", "cwd": str(root)})
    assert "manuscript-guard: paper at stage" in context(
        run_installed("session-start", started, environment)
    )


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
