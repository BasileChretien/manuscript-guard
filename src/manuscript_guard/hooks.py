"""Hook handlers, reached through `manuscript-guard hook <event>`.

Routed through the CLI rather than shell scripts for two reasons. The console script is on
PATH on every platform once the package is installed, which shell scripts and `python3` are
not; and a handler that is ordinary Python is a handler that can be tested.

Three rules govern everything here.

**A hook must never break the session.** Any unexpected error exits 0 in silence. A guard
that crashes when a project is half-configured is worse than no guard, because the author
removes it and loses the guard that worked.

**A hook must be fast.** `guard-write` and `after-edit` fire on every edit, so neither loads
the full gate set: the first is a path check, the second classifies numbers in one file.
Only `session-start` and the submission guard run the gates, and those fire rarely.

**A hook blocks only what is unambiguous.** Writing to a machine-written results file is
always wrong. Prose that trips the AI-writing lint is not, so that is reported as context,
never denied.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Paths that no editor should write, relative to the project root. Each is generated, and
# editing one desynchronises it from whatever generates it.
FORBIDDEN = (
    ("results/", ".json", "results are machine-written; change the analysis and re-run it"),
    ("results/", ".sha256", "the digest is written with the fragment it covers"),
    ("build/", "", "everything in build/ is regenerated; edit the source instead"),
    (
        "profiles/reporting/",
        ".yaml",
        "checklist profiles are transcribed from the official document; "
        "edit the recipe and re-run `manuscript-guard transcribe`",
    ),
)

# Exempt from the rule above. Without this, the guard denies edits to
# `profiles/reporting/recipes/*.recipe.yaml` — the exact file its own denial message tells
# you to go and edit.
ALLOWED = ("profiles/reporting/recipes/",)

# Commands that mean a manuscript is about to leave the building. Matched against the whole
# command string rather than by a prefix rule: a leading env-var assignment or `cd x &&`
# defeats prefix matching, which is exactly how a submission slipped past the guard in the
# project that preceded this one.
SUBMISSION_MARKERS = re.compile(
    # The two unambiguous ones: asking for a submission pack, or asking for submission
    # standards.
    r"manuscript-guard\s+submit\b|--submission\b|"
    # Moving a submission somewhere: an action verb near the pack or a built document.
    r"\b(?:zip|tar|scp|rsync|cp|copy|mv|move|curl|wget|mail|sendmail|git\s+push)\b"
    r"[^\n]{0,120}?(?:\bsubmission\b|\.docx\b)",
    re.IGNORECASE,
)


def _read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0


def _deny(event: str, reason: str) -> int:
    return _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def _context(event: str, text: str) -> int:
    return _emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


# Codex edits files with one tool, `apply_patch`, and hands a hook the text of the patch where
# other tools hand it a path. These are the markers of that text as codex-rs spells them
# (apply-patch/src/parser.rs, read 2026-10-02).
PATCH_TOOL = "apply_patch"
_PATCH_BEGIN = "*** Begin Patch"
_PATCH_END = "*** End Patch"
_PATCH_ADD = "*** Add File: "
_PATCH_UPDATE = "*** Update File: "
_PATCH_DELETE = "*** Delete File: "
_PATCH_MOVE = "*** Move to: "
_HEREDOC_OPENERS = ("<<EOF", "<<'EOF'", '<<"EOF"')


def patch_paths(patch: str) -> list[str]:
    """The files an `apply_patch` envelope writes, read as Codex's own parser reads it.

    A file added, a file updated, and where an updated file is moved to. A deleted file is
    not written, so it is not here. The rules are the parser's, because a looser reading
    refuses an edit to a manuscript that merely quotes a patch, and a stricter one misses a
    write Codex goes on to make:

    - nothing counts before `*** Begin Patch`, or after `*** End Patch`;
    - a header is a whole line of the envelope. Inside an update, where a line of the file's
      text begins with a space, `+` or `-`, only a marker at the very start of the line is
      one; elsewhere space around it is allowed;
    - `*** Move to:` is read only on the line straight after the header of the file it moves;
    - the here-document some models wrap a patch in is taken off first.
    """
    lines = [line.removesuffix("\r") for line in patch.strip().split("\n")]
    if len(lines) >= 4 and lines[0] in _HEREDOC_OPENERS and lines[-1].endswith("EOF"):
        lines = "\n".join(lines[1:-1]).strip().split("\n")
    if lines[0].strip() != _PATCH_BEGIN:
        return []

    written: list[str] = []
    updating = False
    may_move = False
    for line in lines[1:]:
        header = line.rstrip() if updating else line.strip()
        moves, may_move = may_move, False
        if header == _PATCH_END:
            break
        if header.startswith(_PATCH_ADD):
            written.append(header[len(_PATCH_ADD) :])
            updating = False
        elif header.startswith(_PATCH_DELETE):
            updating = False
        elif header.startswith(_PATCH_UPDATE):
            written.append(header[len(_PATCH_UPDATE) :])
            updating = may_move = True
        elif moves and header.startswith(_PATCH_MOVE):
            written.append(header[len(_PATCH_MOVE) :])
    return written


def _edited_paths(payload: dict) -> list[Path]:
    """The files a write is about to touch, or has just touched.

    Most tools name one, in `file_path`. `notebook_path` is here because hooks.json registers
    NotebookEdit and that tool does not send `file_path` — so the matcher was live and the
    handler always returned None, making the notebook branch of the write guard dead.

    Codex's `apply_patch` names none: the patch's text arrives in `tool_input.command` and
    may write several files, each relative to the directory Codex is in.
    """
    tool_input = payload.get("tool_input", {})
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if target:
        return [Path(target)]
    command = tool_input.get("command")
    if payload.get("tool_name") != PATCH_TOOL or not isinstance(command, str):
        return []
    base = Path(payload.get("cwd") or Path.cwd())
    return [base / name for name in patch_paths(command) if name]


def _or_nothing(reader, path: Path) -> str | None:
    """What `reader` says of one file, or None where it cannot be read.

    A patch names several files. One of them that cannot be read must not cost the others
    what the hook has to say about them.
    """
    try:
        return reader(path)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return None


def _project_path(root: Path, name: str) -> Path:
    """Where this project keeps `name`, honouring a `paths:` override in paper.yaml."""
    from manuscript_guard.contracts import load_project

    project, _report = load_project(root)
    return project.path(name)


def _relative_to_project(path: Path) -> tuple[Path, str] | None:
    """Find the project root above `path`, and the path relative to it."""
    from manuscript_guard.contracts import ContractError, find_root

    try:
        root = find_root(path.parent if path.suffix else path)
    except (ContractError, OSError):
        return None
    try:
        return root, str(path.resolve().relative_to(root)).replace("\\", "/")
    except (ValueError, OSError):
        return None


# --------------------------------------------------------------------------- handlers


def guard_write(payload: dict) -> int:
    """Refuse edits to files that something else generates.

    A patch is applied whole, so one generated file in it refuses all of it, and the reason
    names each generated file and none of the others.
    """
    refusals = [why for path in _edited_paths(payload) if (why := _or_nothing(_refusal, path))]
    if not refusals:
        return 0
    return _deny("PreToolUse", "\n".join(refusals))


def _refusal(path: Path) -> str | None:
    """Why this file may not be written by hand, or None where it may."""
    found = _relative_to_project(path)
    if found is None:
        return None
    root, relative = found

    if any(relative.startswith(prefix) for prefix in ALLOWED):
        return None

    # `results/` and `build/` are the defaults, but `paths:` in paper.yaml can move either,
    # and a guard that reads the literal names silently stops guarding when it does. G1
    # still catches the edit afterwards; preventing it is this hook's whole job.
    for name in ("results", "build"):
        try:
            configured = str(_project_path(root, name).relative_to(root)).replace("\\", "/")
        except (ValueError, OSError):
            continue
        if configured and configured != name:
            relative = relative.replace(f"{configured}/", f"{name}/", 1)

    for prefix, suffix, why in FORBIDDEN:
        if relative.startswith(prefix) and relative.endswith(suffix):
            return f"{relative} is generated, not written. {why}."
    return None


def after_edit(payload: dict) -> int:
    """Classify the numbers in a manuscript file the moment it is saved."""
    notes = [note for path in _edited_paths(payload) if (note := _or_nothing(_note_on, path))]
    if not notes:
        return 0
    return _context("PostToolUse", "\n".join(notes))


def _note_on(path: Path) -> str | None:
    """What to say about a file that was just written, or None where there is nothing."""
    if path.suffix.lower() != ".md":
        return _analysis_note(path)
    # A patch that moves a file names it where it was, too.
    if not path.is_file():
        return None
    found = _relative_to_project(path)
    if found is None:
        return None
    root, relative = found

    from manuscript_guard.classify import UNCLASSIFIED, Classifier
    from manuscript_guard.contracts import load_project
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.tokens import find_atoms

    project, _ = load_project(root)
    manuscript = project.path("manuscript")
    try:
        path.resolve().relative_to(manuscript.resolve())
    except (ValueError, OSError):
        return None

    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    text = path.read_text(encoding="utf-8", errors="replace")
    loose = [
        (atom.line, atom.text)
        for atom in find_atoms(text, mask(text))
        if classifier.classify(atom).kind == UNCLASSIFIED
    ]
    if not loose:
        return None

    listed = "; ".join(f"line {line}: {text!r}" for line, text in loose[:6])
    more = f" (+{len(loose) - 6} more)" if len(loose) > 6 else ""
    return (
        f"{relative} has {len(loose)} number(s) bound to nothing — {listed}{more}. "
        f"Bind each with {{{{results.<key>}}}} or {{{{lit.<key>}}}}, or add it to "
        f"`conventions:` in paper.yaml with a reason."
    )


def _analysis_note(path: Path) -> str | None:
    found = _relative_to_project(path)
    if found is None:
        return None
    _root, relative = found
    if not relative.startswith("analysis/"):
        return None
    return (
        f"{relative} changed. The results it wrote are now stale until it is re-run, and "
        f"the Methods may no longer describe it (`manuscript-guard methods`)."
    )


def guard_submission(payload: dict) -> int:
    """Before anything that looks like a submission, hold the project to that standard."""
    # Codex puts the text of a patch in the field a shell command arrives in. A patch that
    # writes the word `--submission` into a file is an edit, which the write guard reads.
    if payload.get("tool_name") == PATCH_TOOL:
        return 0
    command = str(payload.get("tool_input", {}).get("command", ""))
    if not SUBMISSION_MARKERS.search(command):
        return 0

    from manuscript_guard.cli import _run_gates

    cwd = Path(payload.get("cwd") or Path.cwd())
    report, project, _stage, _deferred = _run_gates(cwd, submission=True)
    if report.ok:
        return 0

    lines = [f"  {f.code}: {f.message}" for f in report.failures[:8]]
    more = f"\n  (+{len(report.failures) - 8} more)" if len(report.failures) > 8 else ""
    return _deny(
        "PreToolUse",
        f"{len(report.failures)} submission check(s) failing in {project.root.name}:\n"
        + "\n".join(lines)
        + more
        + "\n\nRun `manuscript-guard check --submission` for the full list.",
    )


def _status_line(payload: dict) -> str:
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.policy import DESCRIPTIONS

    cwd = Path(payload.get("cwd") or Path.cwd())
    report, project, stage, deferred = _run_gates(cwd)
    failing = len(report.failures)
    warnings = len(report.warnings)

    parts = [
        f"manuscript-guard: {project.root.name} at stage '{stage}' "
        f"({DESCRIPTIONS[stage]}). {failing} failing, {warnings} warning(s)."
    ]
    if deferred:
        upcoming = min(deferred, key=lambda s: list(DESCRIPTIONS).index(s))
        parts.append(f"{sum(deferred.values())} more become due at '{upcoming}'.")
    if failing:
        parts.append("Run `manuscript-guard check`.")
    return " ".join(parts)


# `pip install --upgrade` is enough for a pip install now that the package version moves with
# the plugin. pipx is the exception: `pipx upgrade` refuses a git install ("no package index
# was checked"), so it has to be reinstalled.
UPGRADE_COMMAND = (
    "pip install --upgrade git+https://github.com/BasileChretien/manuscript-guard "
    "(with pipx: pipx install --force git+https://github.com/BasileChretien/manuscript-guard)"
)

# A clear or a compact happens inside a session that already heard it at its start.
QUIET_SOURCES = ("clear", "compact")


def _version_tuple(text: object) -> tuple[int, ...] | None:
    """`0.2.260` as (0, 2, 260); None for anything that is not plain dotted digits."""
    if not isinstance(text, str) or not re.fullmatch(r"\d+(?:\.\d+)*", text.strip()):
        return None
    try:
        return tuple(int(part) for part in text.strip().split("."))
    except ValueError:  # int() refuses a part of more than 4300 digits
        return None


def _plugin_version() -> str | None:
    """The version of the plugin this hook was started from, if Claude Code says where it is.

    `CLAUDE_PLUGIN_ROOT` names the installed copy of the plugin. Unset, as it is anywhere but
    under Claude Code, there is nothing to compare and the answer is None.
    """
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return None
    try:
        document = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    except (OSError, ValueError, RecursionError):  # the last for a file nested past the limit
        return None
    version = document.get("version") if isinstance(document, dict) else None
    return version if isinstance(version, str) else None


def stale_cli_notice() -> str | None:
    """A sentence, when the plugin is newer than this command line tool; otherwise None.

    The plugin's skills name commands and options of the release they were written against,
    and an installed copy of the plugin updates on its own schedule, not with the package. The
    two carry one version number, so older here means a skill may name something this copy
    lacks. It only says so: nothing is blocked, because a stale tool still guards.
    """
    from manuscript_guard import __version__

    plugin = _plugin_version()
    wanted = _version_tuple(plugin)
    have = _version_tuple(__version__)
    if wanted is None or have is None or have >= wanted:
        return None
    return (
        f"manuscript-guard: the plugin is at {plugin.strip()} but the installed command line "
        f"tool is at {__version__}, so a skill may name a command or option this copy lacks. "
        f"Upgrade it with: {UPGRADE_COMMAND}."
    )


def session_start(payload: dict) -> int:
    """One line on where the manuscript stands, so nobody has to remember.

    Also, once at the start of a session, the notice that the installed command line tool is
    older than the plugin. It is said here, where it is heard once, and not by the hooks that
    fire on every edit and every shell command.
    """
    # Each is guarded on its own, so that neither can cost the other: outside a project there
    # is no status line, and a manifest nobody should have written is no reason to lose it.
    source = payload.get("source") if isinstance(payload, dict) else None
    try:
        notice = None if source in QUIET_SOURCES else stale_cli_notice()
    except Exception:  # noqa: BLE001 - a hook must never break the session
        notice = None
    try:
        status = _status_line(payload)
    except Exception:  # noqa: BLE001 - outside a project there is no line, and no error
        status = None
    if status is None and notice is None:
        return 0

    output: dict = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": " ".join(part for part in (status, notice) if part),
        }
    }
    if notice:
        output["systemMessage"] = notice
    return _emit(output)


HANDLERS = {
    "guard-write": guard_write,
    "after-edit": after_edit,
    "guard-submission": guard_submission,
    "session-start": session_start,
}


def dispatch(event: str, payload: dict | None = None) -> int:
    """Run a handler, swallowing anything unexpected.

    A hook that raises in a project that is half-configured teaches the author to remove
    the hook, and they lose the ones that were working.
    """
    handler = HANDLERS.get(event)
    if handler is None:
        return 0
    try:
        return handler(payload if payload is not None else _read_event())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for `manuscript-guard-hook`.

    A separate console script from the main CLI, and this module imports nothing heavy at
    module level, because the Bash guard fires on *every* shell command. Routing it through
    the full CLI would load the gates, the build pipeline and the Zotero client before
    deciding the command has nothing to do with a submission.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in HANDLERS:
        return 0
    return dispatch(args[0])


if __name__ == "__main__":
    sys.exit(main())
