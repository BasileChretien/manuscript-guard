"""Which `manuscript-guard set` an agent is not to run without the author.

Three changes `set` makes can turn a failing check into a passing one with nothing fixed,
and the submission guard puts each to the author (Basile, 2026-10-28: "moving back is
allowed, with the hook asking first"):

- `set stage` to an earlier stage: what starts to fail after it, up to the stage left, is
  listed as not due;
- `set reporting_guideline` without a guideline the paper declares now: its checklist is no
  longer asked for, and its findings go;
- `set target_journal` to another journal than the one declared: the old journal's limits
  and required statements are no longer held. Choosing the first journal adds rules, and is
  not asked; nor is moving the stage on, or adding a guideline.

The guard reads the command as text and cannot always know what it does, and where it
cannot, it asks: no project where the command would find one, a `paper.yaml` it cannot
read, a change of folder before the `set` it does not follow, a value held in a variable.
A guard that let a change through whenever it was unsure would be one an agent could step
round by writing the command another way.
"""

from __future__ import annotations

import contextlib
import re
import shlex
from pathlib import Path

#: The keys whose change may be the author's to decide.
WATCHED = ("stage", "reporting_guideline", "target_journal")
#: Commands that change the folder the next one runs in.
_CHANGES_FOLDER = ("cd", "chdir", "pushd", "popd", "set-location", "push-location",
                   "pop-location", "sl")  # fmt: skip
_A_CHANGE = re.compile(
    r"(?i)(?<![\w.-])(?:" + "|".join(map(re.escape, _CHANGES_FOLDER)) + r")(?![\w.-])"
)
#: Where one command of a line ends and the next begins.
_BETWEEN = re.compile(r"&&|\|\||[;&|\r\n]")
#: What the shell expands before the command sees it: a variable, a substitution, a home
#: folder, a pattern.
_EXPANDED = re.compile(r"[$`%~*?]")
#: What a `set` invocation sets when the guard cannot say.
_UNSURE = "unsure"


def _readings(text: str) -> list[list[str]]:
    """The words of `text` as a POSIX shell gives them, and as PowerShell and cmd do, with
    the quotation marks around a word taken off. Each once."""
    readings = []
    with contextlib.suppress(ValueError):  # a quotation mark left open
        readings.append(shlex.split(text, posix=True))
    try:
        words = shlex.split(text, posix=False)
    except ValueError:
        words = text.split()
    readings.append(
        [
            word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "\"'" else word
            for word in words
        ]  # fmt: skip
    )
    return [list(words) for words in dict.fromkeys(tuple(words) for words in readings)]


def _folders(before: str, cwd: Path) -> list[Path] | None:
    """Each folder the commands before a `set` leave the shell in, from `cwd`; None where
    one of them changes the folder in a way the guard does not follow."""
    folders = [cwd]
    for command in _BETWEEN.split(before):
        command = command.strip().lstrip("({& ").strip()
        if not _A_CHANGE.search(command):
            continue
        moved: list[Path] = []
        for words in _readings(command):
            if not words or words[0].lower() not in _CHANGES_FOLDER:
                return None  # a change of folder further into the command
            if words[0].lower() in ("popd", "pop-location"):
                return None
            given = [word for word in words[1:] if word.lower() not in ("-path", "-literalpath")]
            if len(given) != 1 or given[0].startswith("-") or _EXPANDED.search(given[0]):
                return None
            moved += [folder / given[0] for folder in folders]
        folders = list(dict.fromkeys(moved))
    return folders


def _asked(words: list[str]) -> tuple[str, list[str], str | None] | None:
    """The key a `set` invocation's words write, its values and the folder `--path` names,
    as argparse reads them; None where it writes a key the guard does not watch."""
    positional: list[str] = []
    folder = None
    given = iter(words)
    for word in given:
        if word == "--":
            positional += list(given)
        elif word == "--path":
            folder = next(given, None)
        elif word.startswith("--path="):
            folder = word.partition("=")[2]
        elif not word.startswith("-"):
            positional.append(word)
    if not positional:
        return None
    key, values = positional[0], positional[1:]
    if _EXPANDED.search(key):
        return _UNSURE, values, folder
    return (key, values, folder) if key in WATCHED else None


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


def _why(key: str, values: list[str], root: Path, paper: dict) -> str | None:
    """Why setting `key` to `values` in this project is the author's to decide, or None."""
    from manuscript_guard.policy import DRAFTING, STAGES

    asked = "`" + " ".join(["manuscript-guard set", key, *values]) + "`"
    if key == "stage":
        declared = paper.get("stage", DRAFTING)
        new = values[0] if len(values) == 1 else None
        if new not in STAGES:
            return None  # `set` refuses it
        if declared not in STAGES:
            return f"{asked} sets the stage of {root.name}, whose stage cannot be read."
        if STAGES.index(new) >= STAGES.index(declared):
            return None
        return (
            f"{asked} moves {root.name} back from {declared}, and every finding that starts "
            f"to fail after {new}, up to {declared}, is then listed as not due: the check "
            "passes with nothing fixed."
        )
    if key == "reporting_guideline":
        declared = paper.get("reporting_guideline")
        if declared is None:
            return None
        if not isinstance(declared, list):
            return f"{asked} replaces what {root.name} declares, which cannot be read as a list."
        dropped = [str(name) for name in declared if name not in values]
        if not dropped:
            return None
        return (
            f"{asked} takes {', '.join(dropped)} from {root.name}'s guidelines, and the "
            "checklist of each is then no longer asked for: its findings go with nothing "
            "done."
        )
    declared = paper.get("target_journal")
    if declared in (None, "") or values == [declared]:
        return None
    return (
        f"{asked} moves {root.name} from {declared}, whose limits and required statements "
        "are then no longer held."
    )


def _invocation(words: list[str], folders: list[Path] | None) -> str | None:
    asked = _asked(words)
    if asked is None:
        return None
    key, values, folder = asked
    if key == _UNSURE or any(_EXPANDED.search(word) for word in [*values, folder or ""]):
        return "this `manuscript-guard set` names its setting or its value through the shell."
    if folders is None:
        return (
            f"the folder this `manuscript-guard set {key}` runs in is changed before it in a "
            "way the guard does not follow, so what it changes cannot be read."
        )
    for here in folders:
        found = _paper(here / folder if folder else here)
        if found is None:
            return (
                f"no paper.yaml that can be read was found where this `manuscript-guard set "
                f"{key}` looks, so what it changes cannot be read."
            )
        why = _why(key, values, *found)
        if why:
            return why
    return None


def asks(command: str, cwd: Path, tool: str, ends: re.Pattern[str]) -> str | None:
    """Why a `set` in `command` is put to the author, or None where none is. `tool` is the
    pattern of the command's name, `ends` where one invocation ends."""
    joined = re.sub(r"[\\`]\r?\n", " ", command)
    found_any = False
    try:
        for found in re.finditer(tool + r"set\b", joined, re.IGNORECASE):
            found_any = True
            rest = joined[found.end() :]
            end = ends.search(rest)
            folders = _folders(joined[: found.start()], cwd)
            for words in _readings(rest[: end.start() if end else len(rest)]):
                why = _invocation(words, folders)
                if why:
                    return f"{why} {_DECIDES}"
    except Exception:  # noqa: BLE001 - unsure is asked, never let through
        if found_any:
            return f"what this `manuscript-guard set` changes cannot be read. {_DECIDES}"
    return None


_DECIDES = (
    "Whether the paper is back at that stage, without that guideline or for another journal "
    "is the author's decision."
)


__all__ = ["WATCHED", "asks"]
