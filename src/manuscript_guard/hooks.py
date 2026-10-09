"""Hook handlers, reached through `manuscript-guard hook <event>`.

Routed through the CLI rather than shell scripts for two reasons. The console script is on
PATH on every platform once the package is installed, which shell scripts and `python3` are
not; and a handler that is ordinary Python is a handler that can be tested.

Three rules govern everything here.

**A hook must never break the session.** Any unexpected error exits 0 in silence. A guard
that crashes when a project is half-configured is worse than no guard, because the author
removes it and loses the guard that worked. One error is expected and is passed on: a file of
the project's own that cannot be parsed, which `check` reports in a sentence written for the
author. The submission guard refuses with that sentence and the session start says it.

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
    (
        # The one file, named. A prefix of `checks/` with a suffix of `.csv` refused a project's
        # own `checks/evidence/table3.csv` — in the folder the checking skill tells a project to
        # keep its evidence in — with a sentence about the record of who checked what, which was
        # false of it. Everything else under `checks/` is the project's to write.
        "checks/decisions.csv",
        "",
        "the record of who checked what is appended to by `manuscript-guard checker import`; "
        "a decision nobody made cannot be written into it by hand",
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
#
# The command, under each name it is installed or run by: `mguard` is its second name, both
# end in `.exe` on Windows, and `python -m manuscript_guard.cli` runs it with no script at
# all. A quote may close the name, as in PowerShell's `& "C:\Tools\mguard.exe" submit`.
# tests/test_hooks.py holds the names to the ones `pyproject.toml` installs.
_TOOL = r"\b(?:(?:manuscript-guard|mguard)(?:\.exe)?|manuscript_guard\.cli)[\"']?\s+"
# What follows a subcommand and may belong to it: up to a `;`, `&` or `|`, in quotes or not,
# and up to the end of the line unless it ends in `\` or a backtick, which is how bash and
# PowerShell continue one. The guard does not know which shell runs the command, so it
# reads on after either, and a PowerShell line that ends in a folder's backslash is read
# with the next. It stops in every case at the next invocation, a name of the command and
# a subcommand after it: a stage belongs to the nearest invocation before it. Without that,
# a build with no stage took the stage of the check a refusal names, later on the line,
# and a line that named the command n times cost n times its length.
_SAME_COMMAND = rf"(?:(?!{_TOOL}[A-Za-z])(?:[^\n;&|]|[\\`]\r?\n))*?"
SUBMISSION_MARKERS = re.compile(
    # The unambiguous ones: asking for a submission pack, for a build at the submission
    # stage, or for submission standards. `--stage submission` is a marker after `build`
    # only: after `check` it is the command a refusal tells its reader to run.
    _TOOL + r"(?:submit\b|build\b" + _SAME_COMMAND + r"--stage[\s=]+[\"']?submission\b)|"
    r"--submission\b|"
    # Moving a submission somewhere: an action verb near the pack or a built document.
    r"\b(?:zip|tar|scp|rsync|cp|copy|mv|move|curl|wget|mail|sendmail|git\s+push|"
    # The same verbs as PowerShell and Windows spell them, since on Windows an agent's shell
    # is PowerShell. `Copy-Item` and `Move-Item` are held by `copy` and `move` above. Not
    # `irm`, the short name of `Invoke-RestMethod`: it is also the French for MRI, and stands
    # in file names.
    r"compress-archive|send-mailmessage|invoke-webrequest|invoke-restmethod|iwr|"
    r"start-bitstransfer|robocopy|xcopy)\b"
    r"[^\n]{0,120}?(?:\bsubmission\b|\.docx\b)",
    re.IGNORECASE,
)

# What a refusal tells its reader to run. Spelled with `--stage`, because `--submission` is
# one of the markers above: told to run `check --submission`, an agent was refused again with
# the same lines and never saw the list. Both spellings give one verdict, and after `check`
# the stage is no marker, which is what lets this command through.
#
# A refusal says to run it on its own, and that is part of the advice. The command ends in
# the word `submission`, so after `cp`, `git push` or a folder named `Copy` on the same line
# the third alternative above matches it, and no spelling the documents give avoids the
# word.
FULL_CHECK = "manuscript-guard check --stage submission"


def _event_text() -> str:
    """The event, as the agent tool wrote it on standard input.

    Read as bytes and decoded as UTF-8, because that is what the tools write: Claude Code and
    Codex both send a name outside ASCII as its own bytes, with no escape. Left to Python,
    standard input is decoded in the ANSI code page on Windows, where `méthodes.md` arrived
    as `mÃ©thodes.md`, a file that does not exist, and a project kept under an accented
    folder was never found, so that no hook said or refused anything there.

    Bytes that are not UTF-8 are read in the encoding standard input was opened with, as they
    were before, and a byte that encoding cannot read is replaced, so that the event is kept:
    a letter lost from a file's own name leaves the folder and the extension by which the
    write guard knows a generated file.
    """
    stream = sys.stdin
    if stream is None:  # started with no standard input at all
        return ""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:  # replaced by something that holds text, as a test does
        return stream.read()
    raw = buffer.read()
    try:
        return raw.decode("utf-8-sig")  # without the mark Windows PowerShell puts first
    except UnicodeDecodeError:
        return raw.decode(getattr(stream, "encoding", None) or "utf-8", errors="replace")


def _read_event() -> dict:
    try:
        return json.loads(_event_text() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}


def _emit(payload: dict) -> int:
    # `json.dumps` escapes everything outside ASCII, and that is what keeps the answer whole:
    # standard output is in the code page on Windows too, and the tool reads it as UTF-8.
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
_PATCH_EOF = "*** End of File"
_HEREDOC_OPENERS = ("<<EOF", "<<'EOF'", '<<"EOF"')


def _patch_hunks(patch: str) -> list[tuple[str, str | None]]:
    """Each file an `apply_patch` envelope writes, and where it is moved to if it is.

    Read as Codex's own parser reads the envelope, because a looser reading refuses an edit
    to a manuscript that merely quotes a patch, and a stricter one misses a write Codex goes
    on to make:

    - nothing counts before `*** Begin Patch`, or after `*** End Patch`;
    - a header is a whole line of the envelope. Inside an update, where a line of the file's
      text begins with a space, `+` or `-`, only a marker at the very start of the line is
      one; elsewhere space around it is allowed;
    - `*** Move to:` is read once, and only before the first change to the file it moves,
      which an `*** End of File` line there is not;
    - the here-document some models wrap a patch in is taken off first.

    A deleted file is not written, so it is not here.
    """
    lines = [line.removesuffix("\r") for line in patch.strip().split("\n")]
    if len(lines) >= 4 and lines[0] in _HEREDOC_OPENERS and lines[-1].endswith("EOF"):
        lines = lines[1:-1]
    if lines[0].strip() != _PATCH_BEGIN:
        return []

    hunks: list[tuple[str, str | None]] = []
    updating = False
    may_move = False
    for line in lines[1:]:
        header = line.rstrip() if updating else line.strip()
        moves, may_move = may_move, may_move and header == _PATCH_EOF
        if header == _PATCH_END:
            break
        if header.startswith(_PATCH_ADD):
            hunks.append((header[len(_PATCH_ADD) :], None))
            updating = False
        elif header.startswith(_PATCH_DELETE):
            updating = False
        elif header.startswith(_PATCH_UPDATE):
            hunks.append((header[len(_PATCH_UPDATE) :], None))
            updating = may_move = True
        elif moves and header.startswith(_PATCH_MOVE):
            hunks[-1] = (hunks[-1][0], header[len(_PATCH_MOVE) :])
    return hunks


def patch_paths(patch: str, *, after: bool = False) -> list[str]:
    """The files an `apply_patch` envelope writes, each once, in the patch's order.

    Before the patch is applied, a moved file counts at both ends: its text changes where it
    is, and it lands where it goes. With `after`, it counts only where it now is.
    """
    names = [
        name
        for file, moved in _patch_hunks(patch)
        for name in ((moved or file,) if after else (file, moved))
        if name
    ]
    return list(dict.fromkeys(names))


def _edited_paths(payload: dict, *, after: bool = False) -> list[Path]:
    """The files a write is about to touch or, with `after`, has just touched.

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
    return [base / name for name in patch_paths(command, after=after)]


def _or_nothing(reader, path: Path) -> str | None:
    """What `reader` says of one file, or None where it cannot be read.

    A patch names several files. One of them that cannot be read must not cost the others
    what the hook has to say about them.
    """
    try:
        return reader(path)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return None


def _relocated(root: Path) -> dict[str, str]:
    """Where `paths:` in paper.yaml puts `results/` and `build/`, for each one it moves.

    `results/` and `build/` are the defaults, but `paths:` can move either, and a guard that
    reads the literal names silently stops guarding when it does. G1 still catches the edit
    afterwards; preventing it is the write guard's whole job.

    A project that cannot be read moves nothing, and the guard stands on the default names:
    a `paper.yaml` saved in another encoding is the half-configured project a hook has to
    survive, and must not be what switches the guard off.
    """
    from manuscript_guard.contracts import ContractError, load_project

    try:
        project, _report = load_project(root)
    except (ContractError, ValueError, OSError):
        # `ContractError` is what such a file raises now, in a sentence for `check` to print.
        # It was `UnicodeDecodeError`, a `ValueError`, and a paper.yaml that does not parse
        # had always raised this one: there the guard was switched off.
        return {}
    moved: dict[str, str] = {}
    for name in ("results", "build"):
        try:
            configured = str(project.path(name).relative_to(root)).replace("\\", "/")
        except (ValueError, OSError):
            continue
        if configured and configured != name:
            moved[name] = configured
    return moved


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


def _project_root(payload: dict) -> Path | None:
    """The project the event was sent from, or None where there is none.

    Asked before the gates are run, because the gates raise one error for two things: no
    `paper.yaml` above this folder, and a project with a file that cannot be parsed. The
    first is no business of a hook. The second is said, in `_cannot_check`.

    The folder is the one the event names, and the search goes upwards from it only. A
    command sent from above a project that enters it, `cd paper && manuscript-guard submit`,
    finds none here. The submission guard then looks at what the command names
    (`_named_projects`); the session start says nothing.
    """
    from manuscript_guard.contracts import ContractError, find_root

    try:
        return find_root(Path(payload.get("cwd") or Path.cwd()))
    except (ContractError, OSError):
        return None


def _cannot_check(error: Exception) -> str:
    """The project's own account of why it cannot be read, set in from the margin.

    It is written for the author and names the file: `check` prints the same sentence and
    exits 2. A YAML error runs over several lines, so each is set in.
    """
    return "\n".join(f"  {line}" for line in str(error).splitlines())


# The words of a shell command, for the one thing asked of each below: whether it is a path.
# A string in quotes is one word, whatever it holds. Outside quotes a word ends at white space
# and at what a shell or PowerShell puts between two commands, around a value or between the
# items of a list. Nothing is run and nothing expanded: this is not how a shell reads a
# command, only enough to find the paths written out in one.
#
# One kind of word is read as a shell reads it: a word with an escaped space, `\ `, in which
# every backslash stands before a space or one of the characters a shell escapes, which
# are a few of ASCII (`_SHELL_ESCAPES`). Git Bash writes `paper (1).docx` as
# `paper\ \(1\).docx`, and there every backslash makes the character after it part of the
# name, a bracket or an `&` included, so the word does not end at them. A backslash before
# anything else is where Windows ends a folder's name, `.\paper\build`, and a word that
# holds one is read as it always was, by the last pattern: it ends at a bracket, escaped or
# not. That is a letter or a digit, of any script, and a mark no shell escapes: taken the
# other way round, as every character but a letter of English, then as every character
# but a letter, `.\études\ ` and `.\【投稿】論文\ ` were a shell's word and the folder was not
# found. What is left is a folder that begins with one of the escaped characters, `#1`,
# `~old`, `(old)`: the word does not say which shell wrote it (Known gaps). The first look
# ahead finds the escaped space without trying the word's every split.
_SHELL_ESCAPES = r""" !"#$&'()*,:;<=>?@\[\\\]^`{|}~"""
_ESCAPED = rf"""\\[{_SHELL_ESCAPES}]|[^\s\\;&|()<>=,{{}}`"']"""
_SHELL_WORD = (
    r"""(?=(?:\\[^ \n]|[^\s\\;&|()<>=,{}`"'])*\\ )"""
    rf"""((?:{_ESCAPED})+)(?![^\s;&|()<>=,{{}}`"'])"""
)
_WORDS = re.compile(
    r""""([^"]*)"|'([^']*)'|""" + _SHELL_WORD + r"""|((?:\\ |[^\s;&|()<>=,{}`"'])+)"""
)
_ESCAPE = re.compile(r"\\(.)")

# What a `git` command is told to record: the value of `-m` or `--message`, in quotes, or
# as the heredoc an agent writes a long one through. It is text and no command, so the
# markers do not read it: `git commit -m "copy-edit the abstract before submission"` named
# a verb and then the word. Only a value in quotes, and only git's: `python -m` names a
# module to run, and what another command takes after `-m` is not known. A quote escaped
# inside the value ends it here, and the rest is read.
_MESSAGE = re.compile(
    r"""(?<![\w-])(?:-[A-Za-z]*m|--message)\s*=?\s*(?P<said>"""
    r""""\$\(cat\s*<<-?\s*['"]?(?P<end>\w+)['"]?\n.*?\n[ \t]*(?P=end)[ \t]*\n?[ \t]*\)\""""
    r"""|"[^"]*"|'[^']*')""",
    re.DOTALL,
)
_BETWEEN_COMMANDS = re.compile(r"[;&|\n]")
# Git as the command, not as a word: the first word of its command, after any `NAME=value`.
# The letters stand in `--exclude=.git`, in `~/git/tools/send.py` and in a string that is
# searched for, and the value of those commands' `-m` is a path or a text to act on.
_GIT_COMMAND = re.compile(r"\s*(?:[A-Za-z_]\w*=\S*\s+)*git(?:\.exe)?\s", re.IGNORECASE)
_NOT_A_LINE_END = re.compile(r"[^\n]")

# `/c/Users/x`, which is how Git Bash writes `C:/Users/x`, and Claude Code runs its commands
# in Git Bash on Windows. Not `/s` with nothing after it, which is a switch: read as a drive
# it sent the hook to look at `S:`, and a drive may be a share that takes its time.
_GIT_BASH_DRIVE = re.compile(r"/([A-Za-z])(/.*)")

# No path anyone keeps a paper under is longer, and no folder deeper. A word past either is
# not walked: each step is a look on disk at a longer path, and `..` exists at every step,
# so 5000 of them in one word took 34 s.
_LONGEST_PATH = 4096
_DEEPEST_PATH = 100


def _words(command: str) -> list[str]:
    """Each thing in a command that may be a path, once, in the order written.

    A word is read as it stands, and where it was written in a way that hides a path, as
    that path too:

    - in quotes, `=` is not a separator, so `"--files-from=paper/list.txt"` is also read
      from after its last `=`;
    - curl writes a file to upload after an `@`, `file=@paper/build/manuscript.docx`, so a
      word is also read from after its last `@`.

    Outside quotes a backslash and a space are a space in a name, `my\\ paper`, as a shell
    reads them, and that is the only reading. To PowerShell a backslash ends a folder's
    name, so `.\\paper\\ D:\\sent` is two paths, and it is not found. Reading the pieces as
    well found it, and twice took a piece of a file's name for the project beside it:
    `paper` in `cp paper\\ draft.docx`, then in `cp Edited\\ paper\\ \\(JD\\).docx`.

    A word with an escaped space, in which every backslash stands before a space or a
    character a shell escapes, is a shell's throughout (`_SHELL_WORD`): each backslash in
    it is taken off and the character after it kept, so `paper\\ \\(1\\).docx` is the one
    name `paper (1).docx`. It ended at the bracket, and Windows drops the space then left
    at the end of `paper `, which named the folder `paper` beside the file.
    """
    words: list[str] = []
    for double, single, shell, bare in _WORDS.findall(command):
        quoted = double or single
        if quoted:
            words += [quoted, quoted.rpartition("=")[2]]
        else:
            words.append(_ESCAPE.sub(r"\1", shell) if shell else bare.replace("\\ ", " "))
    read = (reading for word in words for reading in (word, word.rpartition("@")[2]))
    return list(dict.fromkeys(reading for reading in read if reading))


def _without_messages(command: str) -> str:
    """The command with what each `git` command in it is told to record blanked out.

    Blanked, not taken out: the markers count the characters between a verb and the word on
    one line, so a message leaves its own length in spaces and its line ends behind, and
    what stands on either side of it is as far apart as it was. Taken out, a rename before
    a commit and the check a refusal names after it came together and read as a submission.

    A message is git's where `git` is the command it belongs to: the first word after the
    start of the line or the last `;`, `&` or `|` before the option. A message blanked
    earlier on the line is not searched for those, so a second `-m` after a message with an
    `&` in it is still git's. The command is read once, from left to right.
    """
    if "git" not in command:
        return command
    pieces: list[str] = []
    at = start = searched = 0
    for found in _MESSAGE.finditer(command):
        for between in _BETWEEN_COMMANDS.finditer(command, searched, found.start()):
            start = between.end()
        if _GIT_COMMAND.match(command, start):
            pieces += [command[at : found.start("said")], _NOT_A_LINE_END.sub(" ", found["said"])]
            at = searched = found.end()
        else:
            searched = found.start("said")  # not a message: what it holds is read as before
    return "".join(pieces) + command[at:]


def _spelt(word: str, cwd: Path) -> Path | None:
    """Where a word points if it is a path, as far along it as there is anything on disk.

    None for an option, for a word too long or too deep to be a path, and for a folder on
    another machine: asking Windows whether `//host/share` exists waits for the host, and a
    hook that fires on a shell command cannot wait.
    """
    if word.startswith("-") or len(word) > _LONGEST_PATH:
        return None
    if word.startswith("~"):
        word = os.path.expanduser(word)
    elif os.name == "nt" and (drive := _GIT_BASH_DRIVE.fullmatch(word)):
        word = f"{drive[1]}:{drive[2]}"
    path = Path(word)
    if path.drive.startswith(("\\\\", "//")) or len(path.parts) > _DEEPEST_PATH:
        return None
    # Downwards from the folder the command was sent from, or from the root the word names,
    # and no further than what exists: a word that is no path costs one look.
    here, parts = cwd, path.parts
    if path.anchor:
        path = cwd / path  # on Windows a root with no drive is the root of this drive
        here, parts = Path(path.anchor), path.parts[1:]
    for part in parts:
        if not (here / part).exists():
            break
        here = here / part
    return here


def _named_projects(command: str, cwd: Path) -> list[Path]:
    """The projects a command names: each one that a word of the command is a path into.

    Where no project is at the folder the command was sent from, this is all the guard has:
    an agent started at the root of a repository stands there, with the paper in a folder
    below. `cd paper && manuscript-guard submit`, `manuscript-guard submit paper` and
    `scp paper/build/manuscript.docx host:` each name it; a file that is not written yet
    names the project its folder is in. From inside a project it finds a second one, and
    the project the command was sent from among them where a path leads back into it.

    A project the command does not name is not looked for. The same folder is where every
    other command of the repository is sent from, and a paper somewhere below that fails
    must not stop a copy of an unrelated `.docx`. So a path held in a variable, a glob for
    the folder itself, or a command inside a quoted string names nothing (Known gaps).

    The folder itself and the ones above it are left out: `_project_root` looked there.
    """
    from manuscript_guard.contracts import ContractError, find_root

    cwd = cwd.resolve()
    looked_in = {cwd, *cwd.parents}
    roots: list[Path] = []
    for word in _words(command):
        try:
            found = _spelt(word, cwd)
            if found is None or found.resolve() in looked_in:
                continue
            roots.append(find_root(found if found.is_dir() else found.parent))
        except (ContractError, OSError, ValueError):
            continue  # a word that is no path, or a path with no project above it
    return list(dict.fromkeys(roots))


# --------------------------------------------------------------------------- handlers


def guard_write(payload: dict) -> int:
    """Refuse edits to files that something else generates.

    A patch is applied whole, so one generated file in it refuses all of it, and the reason
    names each generated file and none of the others.
    """
    # A patch may write many files of one project, and where that project keeps `results/`
    # is asked of it once.
    projects: dict[Path, dict[str, str]] = {}
    refusals = [
        why
        for path in _edited_paths(payload)
        if (why := _or_nothing(lambda file: _refusal(file, projects), path))
    ]
    if not refusals:
        return 0
    return _deny("PreToolUse", "\n".join(refusals))


def _refusal(path: Path, projects: dict[Path, dict[str, str]]) -> str | None:
    """Why this file may not be written by hand, or None where it may."""
    found = _relative_to_project(path)
    if found is None:
        return None
    root, relative = found

    if any(relative.startswith(prefix) for prefix in ALLOWED):
        return None

    if root not in projects:
        projects[root] = _relocated(root)
    for name, configured in projects[root].items():
        relative = relative.replace(f"{configured}/", f"{name}/", 1)

    for prefix, suffix, why in FORBIDDEN:
        if relative.startswith(prefix) and relative.endswith(suffix):
            return f"{relative} is generated, not written. {why}."
    return None


def after_edit(payload: dict) -> int:
    """Classify the numbers in a manuscript file the moment it is saved."""
    notes = [
        note
        for path in _edited_paths(payload, after=True)
        if (note := _or_nothing(_note_on, path))
    ]
    if not notes:
        return 0
    return _context("PostToolUse", "\n".join(notes))


def _note_on(path: Path) -> str | None:
    """What to say about a file that was just written, or None where there is nothing."""
    if path.suffix.lower() != ".md":
        return _analysis_note(path)
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
    """Before anything that looks like a submission, hold the project to that standard.

    The project is the one at the folder the command was sent from, where there is one, and
    each other project the command names.
    """
    # Codex puts the text of a patch in the field a shell command arrives in. A patch that
    # writes the word `--submission` into a file is an edit, which the write guard reads.
    if payload.get("tool_name") == PATCH_TOOL:
        return 0
    # What a commit is told to say is no command and names no file: it is left out before
    # the markers are asked, and before the words are read for a project.
    command = _without_messages(str(payload.get("tool_input", {}).get("command", "")))
    if not SUBMISSION_MARKERS.search(command):
        return 0

    root = _project_root(payload)
    refusals = [_submission_refusal(root)] if root is not None else []
    # Then the projects the command names, which from a project's own folder is how a second
    # one is reached: `cd ../second && manuscript-guard submit`. The search for them must not
    # cost the project the command was sent from its refusal, and one named project that the
    # tool itself fails on must not cost the others theirs.
    try:
        cwd = Path(payload.get("cwd") or Path.cwd()).resolve()
        others = [named for named in _named_projects(command, cwd) if named != root]
    except Exception:  # noqa: BLE001 - a hook must never break the session
        others = []
    refusals += [
        _or_nothing(lambda named: _submission_refusal(named, named_from=cwd), named)
        for named in others
    ]
    refusals = [refusal for refusal in refusals if refusal]
    if not refusals:
        return 0
    return _deny("PreToolUse", "\n\n".join(refusals))


def _check_from(cwd: Path, root: Path) -> str:
    """The submission check as a command that finds the project at `root` from `cwd`.

    The folder is written last. The guard's markers want a verb before the word
    `submission`, and `copy` is one: after the word, a folder called `paper-copy` does not
    make the command submission-shaped, and before it, as in `cd paper-copy && ...`, it does.
    """
    try:
        folder = root.relative_to(cwd)
    except ValueError:  # not below the folder the command was sent from
        folder = root
    return f'{FULL_CHECK} "{folder.as_posix()}"'


def _submission_refusal(root: Path, *, named_from: Path | None = None) -> str | None:
    """Why a submission from this project is refused, or None where its check passes.

    A project found because the command names it is said to be so, and the check the refusal
    names carries the project's folder: from `named_from`, the folder the command was sent
    from, the check alone finds no project.
    """
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.contracts import ContractError

    which = root.name if named_from is None else f"{root.name}, which this command names"
    check = FULL_CHECK if named_from is None else _check_from(named_from, root)
    try:
        report, _project, _stage, _deferred = _run_gates(root, submission=True)
    except ContractError as error:
        # Not an unexpected failure: a file of the project's own cannot be parsed, so no gate
        # ran. Left to `dispatch` this ended in silence and the command went through, from a
        # project in which `check --submission` exits 2.
        return (
            f"manuscript-guard cannot check {which}, so nothing in it has been held to "
            f"the submission standard:\n\n{_cannot_check(error)}\n\n"
            f"Fix that, then run `{check}` on its own."
        )
    if report.ok:
        return None

    lines = [f"  {f.code}: {f.message}" for f in report.failures[:8]]
    more = f"\n  (+{len(report.failures) - 8} more)" if len(report.failures) > 8 else ""
    return (
        f"{len(report.failures)} submission check(s) failing in {which}:\n"
        + "\n".join(lines)
        + more
        + f"\n\nRun `{check}` on its own for the full list."
    )


def _status_line(payload: dict) -> str | None:
    """Where the project stands, or why that cannot be said. None outside a project."""
    root = _project_root(payload)
    if root is None:
        return None

    from manuscript_guard.cli import _run_gates
    from manuscript_guard.contracts import ContractError
    from manuscript_guard.policy import DESCRIPTIONS

    try:
        report, project, stage, deferred = _run_gates(root)
    except ContractError as error:
        # Silence here read as "no project", and the author met the file at submission.
        return (
            f"manuscript-guard: {root.name} cannot be checked, and no gate has run:\n"
            f"{_cannot_check(error)}\n"
            "Fix that, then run `manuscript-guard check`."
        )
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


# Every version is released to PyPI within minutes of being raised, so the index soon has
# the number the plugin carries and `pip install --upgrade` takes it, wherever the copy
# came from. pipx is the exception: `pipx upgrade` keeps a copy that was installed from
# git on git ("no package index was checked"), so it is reinstalled, which serves a copy
# from PyPI as well.
UPGRADE_COMMAND = (
    "pip install --upgrade manuscript-guard (with pipx: pipx install --force manuscript-guard)"
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
    except Exception:  # noqa: BLE001 - a fault of the tool's own costs the line, and no more
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
    module level, because the submission guard fires on *every* shell command, whichever of
    `Bash`, `PowerShell` and `Monitor` runs it. Routing it through the full CLI would load
    the gates, the build pipeline and the Zotero client before deciding the command has
    nothing to do with a submission.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in HANDLERS:
        return 0
    return dispatch(args[0])


if __name__ == "__main__":
    sys.exit(main())
