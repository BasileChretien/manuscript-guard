"""The summary of a run on the data held in the vault that the agent reads, data-free by
construction: `.manuscript-guard/vault/last-run.json` in the project.

It holds each script's exit code and, of the script that failed: for Python, the class of the
exception and the frames of its traceback that fall in the project's own files (path, line,
function); for R, the function names of its `Calls:` line; and the key of a KeyError where it
is exactly a column name the released profile or the data dictionary already holds. No
message and no value goes in. Every name kept is one the project's code, a library or a
released file already shows, the code read as the copy held it before the run: a function
whose name is not a word of those scripts, a frame in a file the run wrote or outside the
copy, a line past the end of its file, a class that is no built-in exception, or a key no
released file names, is left out.
The exit code and a line number still carry a few bits a script could choose (DESIGN.md,
Known gaps; Basile's decision 9a).

What the wrapper of a Python script wrote, and what R printed, are read as untrusted: the
script could have written either.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from manuscript_guard.vault import SUMMARY, SUMMARY_SCHEMA

#: A word of a script: a name as Python or R spells one.
_WORD = re.compile(r"[A-Za-z_.][A-Za-z0-9_.]*")
_R_NAME = re.compile(r"[A-Za-z.][A-Za-z0-9._]*")
#: The names Python gives code that has none of its own.
_ANGLED = frozenset({"<module>", "<lambda>", "<listcomp>", "<dictcomp>", "<setcomp>",
                     "<genexpr>"})  # fmt: skip
#: How many frames are kept, the last ones, nearest the fault.
FRAMES = 20
#: The most of what the wrapper wrote that is read: ample for a class, a module, the frames
#: and a key; anything larger, or too deep for the reader, is no name (fix round 3 of #490).
SUMMARY_BYTES = 64 * 1024


def _words(text: str) -> set[str]:
    found = set(_WORD.findall(text))
    return found | {part for word in found for part in word.split(".") if part}


def code_words(texts: dict[str, str]) -> set[str]:
    """Every word of the project's scripts as the copy held them before anything ran in it
    (`run.source_texts`): never of what the run wrote (round 1 of #490)."""
    words: set[str] = set()
    for text in texts.values():
        words |= _words(text)
    return words


def known_columns(project) -> frozenset[str]:
    """The column names already in the project: the data dictionary's variables, and the
    columns of each profile released into `profiles/data/`."""
    from manuscript_guard.contracts import ContractError
    from manuscript_guard.contracts.dictionary import load_dictionary

    names: set[str] = set()
    try:
        dictionary, _report = load_dictionary(project)
    except (ContractError, OSError, ValueError):
        dictionary = None
    if dictionary is not None:
        names |= set(dictionary.names())
    folder = Path(project.root) / "profiles" / "data"
    for path in sorted(folder.glob("*.profile.json")) if folder.is_dir() else ():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        columns = document.get("columns") if isinstance(document, dict) else None
        for column in columns if isinstance(columns, list) else ():
            if isinstance(column, dict) and isinstance(column.get("name"), str):
                names.add(column["name"])
    return frozenset(names)


def _relative(path: str, work: Path) -> str | None:
    """The path from the copy's root of a file a frame names, or None outside the copy."""
    try:
        real = Path(os.path.realpath(path))
        return real.relative_to(Path(os.path.realpath(work))).as_posix()
    except (ValueError, OSError, TypeError):
        return None


def _identifier(name: object) -> bool:
    return isinstance(name, str) and name.isascii() and name.isidentifier()


def _frames(given: object, work: Path, texts: dict[str, str]) -> list[dict]:
    """The frames in a script of the project as it stood before the run: its file among
    them, its line within that file, its function `<module>` or the like or a word of it."""
    kept = []
    for frame in given if isinstance(given, list) else ():
        if not (isinstance(frame, list) and len(frame) == 3):
            continue
        filename, line, name = frame
        relative = _relative(filename, work) if isinstance(filename, str) else None
        text = texts.get(relative) if relative is not None else None
        if text is None or not isinstance(line, int) or isinstance(line, bool):
            continue
        if not 1 <= line <= text.count("\n") + 1:
            continue
        if not (isinstance(name, str)
                and (name in _ANGLED or (_identifier(name) and name in _words(text)))):
            continue
        kept.append({"path": relative, "line": line, "function": name})
    return kept[-FRAMES:]


#: The built-in exceptions, computed here: a closed set the script cannot add to.
BUILTIN_EXCEPTIONS = frozenset(
    name for name, found in vars(__import__("builtins")).items()
    if isinstance(found, type) and issubclass(found, BaseException)
)  # fmt: skip
#: What the summary says of any other exception: its name is withheld.
NOT_BUILTIN = "not a builtin"


def _kind(record: dict) -> str | None:
    """The exception's class name where it is a built-in exception, of the set this process
    computes; None for any other. All the wrapper wrote is the script's to forge, since the
    script ran in the wrapper's process, and nothing it names is looked for or imported here:
    importing a module a run names runs that module's code in the tool (the fix round of
    #490)."""
    name, module = record.get("class"), record.get("module")
    # By type first: a name of another type is no name, never an error (fix round 2).
    if not (isinstance(name, str) and isinstance(module, str)):
        return None
    return name if module == "builtins" and name in BUILTIN_EXCEPTIONS else None


def python_failure(project, texts: dict[str, str], work: Path, script: str, code: int,
                   summary: Path) -> dict:  # fmt: skip
    """What the summary says of a Python script that failed, from what its wrapper wrote."""
    failed: dict = {"path": script, "exit_code": code}
    try:
        with summary.open("rb") as file:
            data = file.read(SUMMARY_BYTES + 1)
    except OSError:
        return failed  # nothing was raised: the script ended with an exit code of its own
    try:
        record = json.loads(data.decode("utf-8")) if len(data) <= SUMMARY_BYTES else None
    except (UnicodeDecodeError, ValueError, RecursionError):
        record = None
    if not isinstance(record, dict):
        # A summary that cannot be read says nothing: the path and the exit code alone, as a
        # script that raised nothing (fix round 4 of #490).
        return failed
    kind = _kind(record)
    if kind is not None:
        failed["class"] = kind
    else:
        failed["exception"] = NOT_BUILTIN
    frames = _frames(record.get("frames"), work, texts)
    if frames:
        failed["frames"] = frames
    key = record.get("key")
    if isinstance(key, str) and key in known_columns(project):
        failed["column"] = key
    return failed


def r_failure(texts: dict[str, str], script: str, code: int, tail: bytes) -> dict:
    """What the summary says of an R script that failed: the function names of the last
    `Calls:` line it printed that are words of the project's scripts before the run."""
    failed: dict = {"path": script, "exit_code": code}
    lines = [line for line in tail.decode("utf-8", "replace").splitlines()
             if line.startswith("Calls: ")]  # fmt: skip
    if not lines:
        return failed
    words = code_words(texts)
    calls = [part.strip() for part in lines[-1][len("Calls: "):].split("->")]
    kept = [part for part in calls if _R_NAME.fullmatch(part) and part in words]
    if kept:
        # As many as a Python traceback's frames, the last ones, nearest the fault.
        failed["calls"] = kept[-FRAMES:]
    return failed


def write_summary(root: Path, run: str, ran_at: str, scripts: list[tuple[str, int | None]],
                  failed: dict | None, *, outbox: bool, stopped: bool = False) -> Path:  # fmt: skip
    """Write the summary into the project, checked against its schema first. A run stopped
    before its end says so, the script it stopped in with no exit code."""
    from manuscript_guard.contracts._schema import validate

    document = {"schema": SUMMARY_SCHEMA, "run": run, "ran_at": ran_at,
                "scripts": [{"path": path, "exit_code": code} for path, code in scripts],
                "failed": failed, "outbox": outbox,
                **({"stopped": True} if stopped else {})}  # fmt: skip
    path = root.joinpath(*SUMMARY.parts)
    checked = validate(document, "vault-run", path)
    if not checked.ok:
        # Never written in a shape the schema does not hold: what is kept is said in it.
        document["failed"] = None if failed is None else {
            "path": failed["path"], "exit_code": failed["exit_code"]}  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


__all__ = ["code_words", "known_columns", "python_failure", "r_failure", "write_summary"]
