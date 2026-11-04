"""The summary of a run on the data held in the vault that the agent reads, data-free by
construction: `.manuscript-guard/vault/last-run.json` in the project.

It holds each script's exit code and, of the script that failed: for Python, the class of the
exception and the frames of its traceback that fall in the project's own files (path, line,
function); for R, the function names of its `Calls:` line; and the key of a KeyError where it
is exactly a column name the released profile or the data dictionary already holds. No
message and no value goes in. Every name kept is one the project's code, a library or a
released file already shows, the code read as the copy held it before the run: a function
whose name is not a word of those scripts, a frame in a file the run wrote or outside the
copy, a line past the end of its file, a class the wrapper did not find under its name in a
built-in module or a module outside the copy, or a key no released file names, is left out.
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
        if not (name in _ANGLED or (_identifier(name) and name in _words(text))):
            continue
        kept.append({"path": relative, "line": line, "function": name})
    return kept[-FRAMES:]


def _kind(record: dict, work: Path) -> str | None:
    """The exception's class name, where the wrapper found the class under that name in its
    module, and the module a built-in one or one whose file is outside the copy; and that
    file, read here, holds the name. Anything else is an exception of the script's own."""
    import builtins

    name, module = record.get("class"), record.get("module")
    if not _identifier(name):
        return None
    if module == "builtins":
        found = getattr(builtins, name, None)
        return name if isinstance(found, type) and issubclass(found, BaseException) else None
    where = record.get("module_file")
    if not (isinstance(module, str) and module != "__main__" and isinstance(where, str)
            and _relative(where, work) is None and Path(where).is_file()):  # fmt: skip
        return None
    try:
        held = Path(where).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return name if name in _words(held) else None


def python_failure(project, texts: dict[str, str], work: Path, script: str, code: int,
                   summary: Path) -> dict:  # fmt: skip
    """What the summary says of a Python script that failed, from what its wrapper wrote."""
    failed: dict = {"path": script, "exit_code": code}
    try:
        record = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return failed
    if not isinstance(record, dict):
        return failed
    kind = _kind(record, work)
    if kind is not None:
        failed["class"] = kind
    else:
        failed["own_exception"] = True
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
        failed["calls"] = kept
    return failed


def write_summary(root: Path, run: str, ran_at: str, scripts: list[tuple[str, int]],
                  failed: dict | None, *, outbox: bool) -> Path:  # fmt: skip
    """Write the summary into the project, checked against its schema first."""
    from manuscript_guard.contracts._schema import validate

    document = {"schema": SUMMARY_SCHEMA, "run": run, "ran_at": ran_at,
                "scripts": [{"path": path, "exit_code": code} for path, code in scripts],
                "failed": failed, "outbox": outbox}  # fmt: skip
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
