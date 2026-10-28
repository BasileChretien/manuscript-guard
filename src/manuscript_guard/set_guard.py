"""Which `manuscript-guard set` an agent is not to run without the author.

Three changes `set` makes can turn a failing check into a passing one with nothing fixed,
and the submission guard puts each to the author (Basile, 2026-10-28: "moving back is
allowed, with the hook asking first"):

- `set stage` to an earlier stage: what starts to fail after it, up to the stage left, is
  listed as not due;
- `set reporting_guideline` without a guideline the paper declares now: its checklist is no
  longer asked for, and its findings go;
- `set target_journal` to another journal than the one declared: the old journal's limits
  and required statements are no longer held.

The guard reads a shell command as text, and two rounds of review each found another way of
writing one that it misread. So it asks by default. A command that names the tool, the word
`set` and one of those three keys anywhere, inside quotation marks too, is asked, unless the
guard reads it exactly: plain `cd <folder>` steps joined by `&&` or `;`, then the tool, `set`,
the key, plain values and at most one `--path`, then nothing but redirections of its output.
Only then is the project read, and the command let through where it moves the stage on,
adds guidelines, or sets a first journal or the same journal. Everything else is asked:
another shell started with the command (`bash -c`, `powershell -Command`), `xargs`, `eval`, a
subshell, an alias, a substitution, a quotation mark, `--`, a variable, a backslash outside a
folder, any value it cannot read.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: The keys whose change may be the author's to decide.
WATCHED = ("stage", "reporting_guideline", "target_journal")

#: What makes a command one the guard looks at: a word naming the tool, the word `set`, and
#: a watched key, anywhere in it.
_NAMES_TOOL = re.compile(r"(?i)manuscript[-_]guard|mguard")
_NAMES_SET = re.compile(r"(?i)(?<![\w])set(?![\w])")
_NAMES_KEY = re.compile(r"(?i)(?<![\w])(?:" + "|".join(WATCHED) + r")(?![\w])")

#: A word the guard reads exactly: no quotation mark, no backslash, no sign a shell expands
#: or treats specially.
_PLAIN = r"[A-Za-z0-9._/:+-]+"
#: A folder, which on Windows may hold a backslash, its separator there; to a POSIX shell it
#: is an escape, so elsewhere it may not (DESIGN.md, Known gaps). A folder never begins
#: with `-` or `+`: `cd -`, `cd -P` and `pushd +1` are no folder the guard can follow.
_FOLDER = r"(?![-+])" + (r"[A-Za-z0-9._/:+\\-]+" if os.name == "nt" else _PLAIN)
_TOOL = (
    rf"(?:(?:{_FOLDER}[/\\])?(?:manuscript-guard|mguard)(?:\.exe)?"
    rf"|(?:{_FOLDER}[/\\])?(?:python3?|py)(?:\.exe)?[ \t]+-m[ \t]+manuscript_guard\.cli)"
)
_CD = re.compile(rf"(?i)[ \t]*(?:cd|chdir|pushd|set-location|sl)[ \t]+({_FOLDER})[ \t]*")
#: Where the output goes: any descriptor's number before `>` or `>>`, then a plain file;
#: or the errors sent where the output goes.
_REDIRECTION = re.compile(rf"[0-9]*>>?[ \t]*({_PLAIN})|2>&1")
_INVOCATION = re.compile(
    rf"[ \t]*{_TOOL}[ \t]+set[ \t]+(?P<key>{_PLAIN})(?P<rest>(?:[ \t]+{_PLAIN})*?)"
    rf"(?P<path>[ \t]+--path(?:[ \t]+|=)(?P<folder>{_FOLDER}))?"
    rf"(?P<redirected>(?:[ \t]*(?:{_REDIRECTION.pattern}))*)[ \t]*"
)
#: Files the tool reads, which a redirection must not write.
_READ_BY_THE_TOOL = ("paper.yaml", "authors.yaml")
#: How the steps before the invocation are joined; `||` runs the next only where one fails.
_JOINED = re.compile(r"[ \t]*(&&|;)[ \t]*")

_DECIDES = (
    "Whether the paper is back at that stage, without that guideline or for another journal "
    "is the author's decision."
)


def _looked_at(command: str) -> bool:
    return bool(
        _NAMES_TOOL.search(command) and _NAMES_SET.search(command) and _NAMES_KEY.search(command)
    )


def _read(
    command: str, cwd: Path
) -> tuple[list[tuple[Path, bool]], str, list[str], str | None] | None:
    """The folders the `set` may run in, each with whether it is one only a `cd` that
    failed leaves it in, then its key, its values and its `--path`, where the command is one
    the guard reads exactly; None where it is not."""
    text = command.strip()
    if re.search(r"\\[ \t]", text):
        return None  # a POSIX shell joins the words on either side into one
    folders = [(cwd, False)]
    at = 0
    while True:
        step = _CD.match(text, at)
        joined = _JOINED.match(text, step.end()) if step else None
        if not step or not joined:
            break
        # Where `cd` fails, a `;` runs the rest in the folder it was in, and a `&&` nothing.
        moved = [(folder / step[1], failed) for folder, failed in folders]
        stayed = [(folder, True) for folder, _failed in folders] if joined[1] == ";" else []
        folders = moved + stayed
        at = joined.end()
    found = _INVOCATION.fullmatch(text, at)
    if found is None:
        return None
    values = found["rest"].split()
    if any(value.startswith("-") for value in values) or found["key"].startswith("-"):
        return None  # an option the guard does not read: `--`, `--help`, another
    for target in _REDIRECTION.finditer(found["redirected"]):
        if target[1] and re.split(r"[/\\]", target[1])[-1].lower() in _READ_BY_THE_TOOL:
            return None  # the output written over a file the tool reads
    return list(dict.fromkeys(folders)), found["key"], values, found["folder"]


def _paper(here: Path) -> tuple[Path, dict] | None:
    """The project `set` would find from `here`, as `find_root` does, and its settings;
    None where there is none or it cannot be read."""
    import yaml

    for up in (here, *here.parents):
        if (up / "paper.yaml").exists():
            try:
                paper = yaml.safe_load((up / "paper.yaml").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - whatever stops the reading
                return None
            if paper is None:
                return up, {}
            return (up, paper) if isinstance(paper, dict) else None
    return None


def _free(key: str, values: list[str], paper: dict) -> bool:
    """Whether setting `key` to `values` only adds to what is checked: the stage moved on
    or kept, guidelines added, a first journal chosen or the same one."""
    from manuscript_guard.policy import DRAFTING, STAGES

    if key == "stage":
        declared = paper.get("stage", DRAFTING)
        return (
            len(values) == 1
            and values[0] in STAGES
            and declared in STAGES
            and STAGES.index(values[0]) >= STAGES.index(declared)
        )
    if key == "reporting_guideline":
        declared = paper.get("reporting_guideline")
        if declared is None:
            return True
        return isinstance(declared, list) and all(name in values for name in declared)
    declared = paper.get("target_journal")
    return len(values) == 1 and (declared in (None, "") or values == [declared])


def asks(command: str, cwd: Path | None) -> str | None:
    """Why a `set` in `command` is put to the author, or None where none is. `cwd` is None
    where the folder the command was sent from cannot be had."""
    if not _looked_at(command):
        return None
    if cwd is None:
        return f"the folder this `manuscript-guard set` runs in cannot be read. {_DECIDES}"
    try:
        read = _read(command, cwd)
        if read is None:
            return (
                "this command names `manuscript-guard set` and a setting the author decides "
                f"in a form the guard does not read exactly. {_DECIDES}"
            )
        folders, key, values, folder = read
        if key not in WATCHED:
            return None
        asked = "`" + " ".join(["manuscript-guard set", key, *values]) + "`"
        for here, failed in folders:
            found = _paper(here / folder if folder else here)
            if found is None and failed:
                # Only a `cd` that failed leaves the shell here, and `set` finds no project
                # in it: it refuses, and changes nothing.
                continue
            if found is None:
                return (
                    f"no paper.yaml that can be read was found where {asked} looks, so what "
                    f"it changes cannot be read. {_DECIDES}"
                )
            root, paper = found
            if not _free(key, values, paper):
                return (
                    f"{asked} moves the stage of {root.name} back, takes a guideline away or "
                    "replaces its journal, or sets a value the guard cannot read: the check "
                    f"may then pass with nothing fixed. {_DECIDES}"
                )
    except Exception:  # noqa: BLE001 - unsure is asked, never let through
        return f"what this `manuscript-guard set` changes cannot be read. {_DECIDES}"
    return None


__all__ = ["WATCHED", "asks"]
