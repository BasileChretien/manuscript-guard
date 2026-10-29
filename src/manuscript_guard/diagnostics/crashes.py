"""A record of each failure the tool did not expect, kept on this machine.

A traceback printed to a terminal is read once and lost, and the person who met it rarely
knows what to send. So when a command, a gate or a hook fails on an error the toolkit did not
raise on purpose, what is needed to find the fault is kept in a file of its own in a folder
of the user's: the tool's version, Python's, the system's name, the command and the names of
the flags given (never their values, which are paths, phrases, titles and DOIs), the error's
type, the frames inside the toolkit by file, line and function, and the error's message with
the paths, addresses, secrets and authors' names taken out (`scrub`). No frame's variables,
no file's contents and no environment. One file per fault, found again by its fingerprint,
with how often and when it was met; the newest twenty are kept.

Nothing is sent. `MANUSCRIPT_GUARD_NO_REPORTS=1` records nothing, `MANUSCRIPT_GUARD_REPORTS`
names another folder, and on a CI runner (`CI` set) nothing is recorded, since the runner's
log is where that run is read. `MANUSCRIPT_GUARD_DEBUG=1` lets the error through as a
traceback, for whoever is fixing it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import traceback
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "manuscript-guard/crash/1"
#: How many faults are kept; the ones met longest ago go first.
KEPT = 20
OFF = "MANUSCRIPT_GUARD_NO_REPORTS"
FOLDER = "MANUSCRIPT_GUARD_REPORTS"
DEBUG = "MANUSCRIPT_GUARD_DEBUG"
#: A message longer than this is cut: a message that quotes a whole file is not kept whole.
LONGEST_MESSAGE = 2000
COMMAND, GATE, HOOK = "command", "gate", "hook"

#: The errors the toolkit raises on purpose, each a sentence about the author's files rather
#: than a fault of its own. They are said to the author and never recorded.
_ON_PURPOSE = frozenset({"ContractError", "BuildError", "RoundTripError"})
_RECORD_NAME = re.compile(r"^[0-9a-f]{12}\.json$")
_FLAG = re.compile(r"^--?[A-Za-z][A-Za-z0-9-]*$")
#: When the session-start line last said which hooks failed (`hook_failures`).
_SAID = "hooks-said.json"
_TRUE = frozenset({"1", "true", "yes", "on"})

#: What `main` was asked: the command, the flags' names, and the folder or file it names,
#: which says which project's folder and authors to take out of a record. Set once per
#: invocation.
_invocation: dict = {"command": None, "flags": [], "words": 0, "start": None}


def invoked(command: str | None, argv: Sequence[str], start: Path | str | None = None) -> None:
    """Keep the command and the names of the flags given; their values are counted, not kept.

    A short option is kept as its two characters, since its value may follow with no space
    (`-omydraft`), and every word after `--` is an argument, however it begins."""
    flags: list[str] = []
    words = 0
    tokens = list(argv)
    ends = tokens.index("--") if "--" in tokens else len(tokens)
    for token in tokens[:ends]:
        name = token.split("=", 1)[0]
        if _FLAG.match(name):
            name = name if name.startswith("--") else name[:2]
            if name not in flags:
                flags.append(name)
        else:
            words += 1
    words += len(tokens[ends + 1:])
    _invocation.update(command=command, flags=flags, words=max(words - 1, 0),
                       start=Path(start) if start else None)  # fmt: skip


def _set(environ: Mapping[str, str], name: str) -> bool:
    return environ.get(name, "").strip().lower() in _TRUE


def debugging(environ: Mapping[str, str] | None = None) -> bool:
    return _set(os.environ if environ is None else environ, DEBUG)


def under_ci(environ: Mapping[str, str] | None = None) -> bool:
    return _set(os.environ if environ is None else environ, "CI")


def folder(environ: Mapping[str, str] | None = None) -> Path | None:
    """Where records are kept, or None where recording is off or on a CI runner."""
    environ = os.environ if environ is None else environ
    if _set(environ, OFF) or under_ci(environ):
        return None
    if environ.get(FOLDER):
        return Path(environ[FOLDER])
    if os.name == "nt":
        base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "manuscript-guard" / "reports"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "manuscript-guard" / "reports"
    state = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "manuscript-guard" / "reports"


def on_purpose(exc: BaseException) -> bool:
    """Whether `exc` is one of the toolkit's own sentences rather than a fault."""
    return any(
        cls.__name__ in _ON_PURPOSE and cls.__module__.startswith("manuscript_guard")
        for cls in type(exc).__mro__
    )


def record(
    exc: BaseException,
    *,
    kind: str,
    name: str | None = None,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Record `exc` and return the file, or None where nothing was written.

    Never raises: a record that cannot be written costs the command nothing.
    """
    try:
        where = folder(environ)
        if where is None or on_purpose(exc):
            return None
        root = root if root is not None else project_root()
        found = _entry(exc, kind, name, root, environ)
        where.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = where / f"{found['fingerprint']}.json"
        _write(path, _merged(path, found))
    except Exception:  # noqa: BLE001 - a record must never cost the command its message
        return None
    with contextlib.suppress(Exception):  # the record is written; tidying is not its part
        _rotate(where, path)
    return path


def records(environ: Mapping[str, str] | None = None) -> list[dict]:
    """Every record kept, the one met last first."""
    where = folder(environ)
    if where is None or not where.is_dir():
        return []
    return sorted(_read_all(where).values(), key=lambda r: r["last_seen"], reverse=True)


def said(path: Path | None) -> str:
    """The line after the error's own: where it was recorded, and that nothing was sent."""
    if path is None:
        return (f"It was not recorded ({OFF} is set, or the folder could not be written); "
                f"{DEBUG}=1 shows where it happened.")  # fmt: skip
    return (f"It is recorded on this machine in {_shown(path.parent)}, as {path.name}; nothing "
            f"was sent. {DEBUG}=1 shows the traceback.")  # fmt: skip


def hook_failures(environ: Mapping[str, str] | None = None) -> str | None:
    """Once, at a session's start, the hooks' failures since this was last said: a hook that
    fails keeps out of the agent's way, so a guard it holds may not have run."""
    try:
        where = folder(environ)
        if where is None or not where.is_dir():
            return None
        since = _said_at(where)
        failed = [r for r in _read_all(where).values()
                  if r["kind"] == HOOK and r["last_seen"] > since]  # fmt: skip
        if not failed:
            return None
        _write(where / _SAID, {"schema": SCHEMA, "said": _now()})
        # Since the last notice where there was one: a fault met before it was said then.
        first = max(min(r["first_seen"] for r in failed), since)[:10]
        kinds = "one kind" if len(failed) == 1 else f"{len(failed)} kinds"
        return (f"manuscript-guard's hooks failed on errors of {kinds} since {first}, and kept "
                f"out of the way, so a check they hold may not have run. The records are in "
                f"{_shown(where)}; nothing was sent.")  # fmt: skip
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return None


def _shown(where: Path) -> str:
    """`where` with the home folder written `~`: the line goes into the agent's context, and
    the home folder's name is the user's."""
    try:
        return str(Path("~") / where.resolve().relative_to(Path.home().resolve()))
    except (ValueError, OSError, RuntimeError):
        return str(where)


def project_root() -> Path | None:
    """The project of the folder or file the command names, or of the working folder."""
    try:
        from manuscript_guard.contracts.project import find_root

        return find_root(_invocation.get("start") or Path.cwd())
    except Exception:  # noqa: BLE001 - no project is an answer
        try:
            from manuscript_guard.contracts.project import find_root

            return find_root(Path.cwd())
        except Exception:  # noqa: BLE001 - no project is an answer
            return None


def _entry(exc, kind: str, name: str | None, root: Path | None, environ) -> dict:
    from manuscript_guard import __version__
    from manuscript_guard.diagnostics.scrub import scrub

    frames = _frames(exc)
    exception = _qualified(type(exc))
    message = scrub(str(exc), root=root, environ=environ)[:LONGEST_MESSAGE]
    now = _now()
    return {
        "schema": SCHEMA,
        "fingerprint": fingerprint(kind, name or _invocation["command"], exception, frames),
        "kind": kind,
        "command": _invocation["command"],
        "name": name,
        "version": __version__,
        "python": python_version(),
        "system": system_name(),
        "flags": list(_invocation["flags"]),
        "other_words": _invocation["words"],
        "exception": exception,
        "frames": frames,
        "message": message,
        "first_seen": now,
        "last_seen": now,
        "count": 1,
    }


def fingerprint(kind: str, name: str | None, exception: str, frames: list[dict]) -> str:
    """Twelve hex digits of the fault: what failed, the error's type and the innermost frame
    inside the toolkit by file and function. Line numbers are left out, so that one fault
    keeps its fingerprint across small edits."""
    inner = next((f"{f['file']}:{f['function']}" for f in reversed(frames) if "file" in f), "")
    text = "|".join((kind, name or "", exception, inner))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _frames(exc: BaseException) -> list[dict]:
    """The frames inside the toolkit by package-relative file, line and function; any other by
    its module's name only, one entry for a run of them."""
    package = Path(__file__).resolve().parent.parent
    frames: list[dict] = []
    for frame, line in traceback.walk_tb(exc.__traceback__):
        try:
            inside = Path(frame.f_code.co_filename).resolve().relative_to(package)
        except (ValueError, OSError):
            module = str(frame.f_globals.get("__name__", "?"))
            if not frames or frames[-1].get("module") != module:
                frames.append({"module": module})
            continue
        frames.append({"file": f"manuscript_guard/{inside.as_posix()}", "line": line,
                       "function": frame.f_code.co_name})  # fmt: skip
    return frames


def python_version() -> str:
    return ".".join(str(part) for part in sys.version_info[:3])


def system_name() -> str:
    """The system's name and release, read without starting a program: `platform.release`
    may run `ver` on Windows, with no limit on how long it takes."""
    if os.name == "nt":
        version = sys.getwindowsversion()
        return f"Windows {version.major}.{version.minor}.{version.build}"
    try:
        named = os.uname()
    except AttributeError:
        return sys.platform
    return f"{named.sysname} {named.release}"


def _qualified(cls: type) -> str:
    module = cls.__module__
    return cls.__qualname__ if module == "builtins" else f"{module}.{cls.__qualname__}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _merged(path: Path, found: dict) -> dict:
    """`found`, keeping when the fault was first met and how often, where it was met before."""
    before = _read(path)
    if before is not None:
        found = {**found, "first_seen": before["first_seen"], "count": before["count"] + 1}
    return found


def _read(path: Path) -> dict | None:
    """A record this module wrote, or None: a file of any other shape is not one of ours."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or "fingerprint" not in data:
        return None
    return data


def _read_all(where: Path) -> dict[Path, dict]:
    found = {}
    for path in where.iterdir():
        if _RECORD_NAME.match(path.name):
            data = _read(path)
            if data is not None:
                found[path] = data
    return found


def _write(path: Path, data: dict) -> None:
    """Written whole or not at all: another process reading the folder never sees half."""
    partial = path.with_name(f".{path.name}.{os.getpid()}.part")
    partial.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(partial, path)


def _rotate(where: Path, current: Path) -> None:
    """Keep the `KEPT` records met last, `current` always among them. Only this module's
    records are ever deleted: the folder may be one the user named, with files of their own."""
    others = [(path, data) for path, data in _read_all(where).items() if path != current]
    others.sort(key=lambda item: item[1]["last_seen"], reverse=True)
    for path, _data in others[KEPT - 1:]:
        path.unlink(missing_ok=True)


def _said_at(where: Path) -> str:
    try:
        data = json.loads((where / _SAID).read_text(encoding="utf-8"))
        return str(data.get("said", ""))
    except (OSError, ValueError, AttributeError):
        return ""
