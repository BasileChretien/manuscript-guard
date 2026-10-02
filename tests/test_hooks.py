"""The hooks.

Three properties matter more than any individual behaviour, and each has a test that would
fail loudly if it stopped holding:

* a hook never breaks the session, whatever it is handed;
* a hook blocks only what is unambiguous;
* the fast paths stay fast, because they fire on every edit and every shell command.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
from pathlib import Path

import pytest

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
    shutil.rmtree(project / "review")
    result = run(
        "guard-submission",
        {"tool_input": {"command": "manuscript-guard submit"}, "cwd": str(project)},
        capsys,
    )
    assert decision(result) == "deny"
    assert "submission check" in reason(result)
    assert "check --stage submission" in reason(result)


def _named_commands(text: str) -> list[str]:
    """Each `manuscript-guard` command a message tells its reader to run."""
    return re.findall(r"`(manuscript-guard\s[^`]*)`", text)


def _refused(project: Path, capsys) -> str:
    """What the guard says of a submission from `project`, which it has to refuse."""
    result = run(
        "guard-submission",
        {"tool_input": {"command": "manuscript-guard submit"}, "cwd": str(project)},
        capsys,
    )
    assert decision(result) == "deny"
    return reason(result)


def _without_a_review(project: Path) -> None:
    shutil.rmtree(project / "review")


# Each way the submission guard refuses, by what is done to the project to bring it about. A
# refusal added to the guard is added here, so that the command it names is held to the rule.
REFUSALS = {"a failing check": _without_a_review}


@pytest.mark.parametrize("spoil", REFUSALS.values(), ids=REFUSALS.keys())
def test_a_refusal_names_a_command_the_guard_lets_through(spoil, project: Path, capsys) -> None:
    """The refusal ended "Run `manuscript-guard check --submission` for the full list", and
    `--submission` is one of the guard's own markers. An agent that did as it was told was
    refused again with the same lines, and could never see the list."""
    spoil(project)
    named = _named_commands(_refused(project, capsys))
    assert named, "a refusal says what to run next"
    for command in named:
        event = {"tool_input": {"command": command}, "cwd": str(project)}
        assert run("guard-submission", event, capsys) is None, command
        # An agent in the folder above writes it this way, which no prefix rule sees through.
        assert SUBMISSION_MARKERS.search(f"cd example && {command}") is None, command


def test_the_command_a_refusal_names_lists_every_failure(
    project: Path, capsys, monkeypatch
) -> None:
    """The refusal shows eight failures and says where the rest are. Plain `check` is let
    through as well, but at the stage this project declares it reports none of what the guard
    refused for: the command named has to be the submission check."""
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.cli import main as cli

    _without_a_review(project)
    path = project / "manuscript" / "main.md"
    loose = ", ".join(str(number) for number in range(4321, 4331))
    path.write_text(path.read_text(encoding="utf-8") + f"\n\nUnbound: {loose}.\n", encoding="utf-8")
    report, *_ = _run_gates(project, submission=True)

    refusal = _refused(project, capsys)
    hidden = [failure for failure in report.failures if failure.message not in refusal]
    assert hidden, "more failures than the refusal shows"

    (command,) = _named_commands(refusal)
    monkeypatch.chdir(project)
    assert cli(shlex.split(command)[1:]) == 1
    listed = capsys.readouterr().out
    assert [failure.message for failure in report.failures if failure.message not in listed] == []
    # Below submission a finding that does not bind yet is still printed, as a note. The
    # count is what tells the submission check from a check at the stage the project is at.
    assert f"\n{len(report.failures)} failing, " in listed


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
