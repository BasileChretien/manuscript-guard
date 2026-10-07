"""What `tests/test_differential.py` compares with: a reader for one source, the base
branch's source exported from git, and the changes a pull request says it means.

See that file for why each is the way it is.
"""

from __future__ import annotations

import filecmp
import io
import json
import os
import queue
import subprocess
import sys
import tarfile
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
WORKER = Path(__file__).with_name("readings.py")
EXPECTED = Path(__file__).with_name("data") / "differential_expected.yaml"

#: The commit to compare with, where the run is told one.
BASE = "MANUSCRIPT_GUARD_BASE"
#: How long one answer may take, in seconds. Most answers take milliseconds and `check` on
#: a new project under a second. A session of the round trip, which builds three documents,
#: took three seconds on a quiet machine and fourteen on a busy one. This is for a reading
#: that never comes back.
ANSWER_WITHIN = 120
#: How long a reader may take to say it is there. It is not an answer's limit, however
#: short that is set: this is Python starting and importing the package, which takes a
#: second on a quiet machine and several on a busy one.
START_WITHIN = 120


class Lost(Exception):
    """The reader did not start, read another source than it was given, stopped answering
    or died. Nothing is known about the input it was asked."""


class Reader:
    """One source's package in a process of its own, asked one input at a time.

    `source` is the folder that holds `manuscript_guard`. It is the only place the process
    is told to look, and the process says where it found the package: a reader that found
    it anywhere else is refused, because Python falls back to whatever copy is installed.
    """

    def __init__(
        self,
        source: Path,
        *,
        hash_seed: str = "0",
        worker: Path = WORKER,
        within: int = ANSWER_WITHIN,
    ) -> None:
        self.source = source.resolve()
        self.within = within
        self.lost: str | None = None
        env = dict(os.environ)
        env.update(PYTHONPATH=str(self.source), PYTHONHASHSEED=hash_seed, PYTHONIOENCODING="utf-8")
        # What the process complains of goes to a file, not a pipe: nothing reads a pipe
        # until the process is lost, and a full one would stop it.
        self._complaints = tempfile.TemporaryFile()  # noqa: SIM115 - closed in `close`
        self.process = subprocess.Popen(
            [sys.executable, str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._complaints,
            env=env,
            cwd=tempfile.gettempdir(),
        )
        self._answers: queue.Queue[bytes | None] = queue.Queue()
        threading.Thread(target=self._listen, daemon=True).start()
        try:
            first = self._next("to start", within=max(within, START_WITHIN))
            found = Path(first["package"]).resolve()
            if found != self.source / "manuscript_guard":
                self._end(f"it read {found}, which is not the source it was given")
        except Lost as lost:
            self.close()
            raise Lost(f"the reader for {self.source} could not be started: {lost}") from None
        self.package = found
        #: The readings this source has no door for, each with what looking for it raised.
        self.absent: dict[str, str] = first["absent"]
        #: The readings this source has and could not be asked for, each with why: not
        #: the same as having none, and never passed over (`readings.why_not`).
        self.broken: dict[str, str] = first.get("broken", {})

    def _listen(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._answers.put(line)
        self._answers.put(None)

    def _end(self, why: str) -> None:
        """Stop the process and remember why, so that every later question says the same."""
        self.process.kill()
        self.process.wait()
        self._complaints.seek(0)
        printed = self._complaints.read().decode("utf-8", errors="replace").strip()
        self.lost = why + (f"; it printed:\n{printed[-2000:]}" if printed else "")
        raise Lost(self.lost)

    def _next(self, what: str, *, within: int | None = None) -> dict[str, Any]:
        within = self.within if within is None else within
        try:
            line = self._answers.get(timeout=within)
        except queue.Empty:
            self._end(f"no answer within {within} seconds {what}")
        if line is None:
            self._end(f"it ended {what}")
        return json.loads(line)

    def ask(self, reading: str, given: Any) -> dict[str, Any]:
        """What this source's `reading` makes of `given`: `answer`, `raised` or `absent`."""
        if self.lost is not None:
            raise Lost(self.lost)
        assert self.process.stdin is not None
        asked = json.dumps({"reading": reading, "given": given}, ensure_ascii=True)
        try:
            self.process.stdin.write(asked.encode("ascii") + b"\n")
            self.process.stdin.flush()
        except OSError:
            self._end(f"it was gone before {reading!r} could be asked of {given!r}")
        return self._next(f"when {reading!r} was asked of {given!r}")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe is not None:
                pipe.close()
        self._complaints.close()

    def __enter__(self) -> Reader:
        return self

    def __exit__(self, *raised: object) -> None:
        self.close()


#: How much of a value is quoted where two answers part.
SHOWN = 160


def _shown(value: Any) -> str:
    quoted = repr(value)
    return quoted if len(quoted) <= SHOWN else f"{quoted[:SHOWN]}... ({len(quoted)} characters)"


def first_difference(first: Any, second: Any, at: str = "") -> str | None:
    """Where two answers part, in words, or None where they are one answer."""
    if first == second:
        return None
    if isinstance(first, dict) and isinstance(second, dict):
        if set(first) == set(second):
            for key in sorted(first):
                inner = f"{at}.{key}" if at else str(key)
                found = first_difference(first[key], second[key], inner)
                if found is not None:
                    return found
        elif not at:
            # The whole answer: one side answered, and the other raised or has no such reading.
            (one,), (other,) = first, second
            told = {
                "answer": "answered",
                "absent": "has no such reading",
                "broken": "cannot make the reading",
            }
            said = [
                f"raised {side[key]}" if key == "raised" else told[key]
                for side, key in ((first, one), (second, other))
            ]
            return f"the first {said[0]} and the second {said[1]}"
        else:
            only = [
                f"only the {side} has {', '.join(map(repr, sorted(has - lacks)))}"
                for side, has, lacks in (
                    ("first", set(first), set(second)),
                    ("second", set(second), set(first)),
                )
                if has - lacks
            ]
            return f"{at}: {' and '.join(only)}"
    if isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            return (
                f"{at}: {len(first)} in the first, {len(second)} in the second; "
                f"{_shown(first)} and {_shown(second)}"
            )
        for index, (one, other) in enumerate(zip(first, second, strict=True)):
            found = first_difference(one, other, f"{at}[{index}]")
            if found is not None:
                return found
    return f"{at}: {_shown(first)} in the first, {_shown(second)} in the second"


def summarised(found: list[tuple[Any, str]]) -> str:
    """The differences of one reading by kind, for whoever reads a change that was meant:
    how many inputs part at each place in the answer, and the shortest input that does.
    Two differences are of one kind where they part at the same place, whichever finding
    of the list it is in."""
    kinds: dict[str, list[tuple[Any, str]]] = {}
    for given, where in found:
        place = where.split(": ", 1)[0]
        kind = "".join("#" if character.isdigit() else character for character in place)
        kinds.setdefault(kind, []).append((given, where))
    lines = []
    for kind, members in sorted(kinds.items(), key=lambda item: (-len(item[1]), item[0])):
        given, where = min(members, key=lambda member: len(repr(member[0])))
        lines.append(f"{len(members)} at {kind}, the shortest of them {given!r}")
        lines.append(f"      {where}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- the base


def _git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(REPO), *arguments], capture_output=True, timeout=300)


def base_commit() -> str | None:
    """The commit to compare with: the one `MANUSCRIPT_GUARD_BASE` names, which has to be
    here, or else where this branch left `origin/main`, or None where that cannot be told.

    Set and empty is not "not set". It is what a workflow's expression leaves when it
    found no commit to name, and a run that was told to compare must not skip for it."""
    named = os.environ.get(BASE)
    if named is not None and not named.strip():
        raise LookupError(
            f"{BASE} is set and names no commit; name the commit to compare with, or unset "
            "the variable to compare with where this branch left origin/main"
        )
    named = (named or "").strip()
    if named:
        found = _git("rev-parse", "--verify", "--quiet", f"{named}^{{commit}}")
        if found.returncode != 0:
            raise LookupError(
                f"{BASE}={named} names no commit in this repository; fetch it, or unset "
                "the variable to compare with where this branch left origin/main"
            )
        return found.stdout.decode("ascii").strip()
    found = _git("merge-base", "HEAD", "origin/main")
    return found.stdout.decode("ascii").strip() if found.returncode == 0 else None


def exported(commit: str, to: Path) -> Path:
    """`src/manuscript_guard` as `commit` has it, written under `to`; the folder to give a
    `Reader`. The files git tracks, and so the lists and schemas the package reads."""
    archive = _git("archive", "--format=tar", commit, "src/manuscript_guard")
    if archive.returncode != 0:
        raise LookupError(
            f"git could not export {commit}: {archive.stderr.decode('utf-8', 'replace').strip()}"
        )
    to.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        # Extraction filters came to 3.10 in 3.10.12, and CI's Windows and macOS jobs run
        # 3.10.11. Without one nothing is lost here: the archive is git's own, of a folder
        # it tracks.
        if hasattr(tarfile, "data_filter"):
            tar.extractall(to, filter="data")
        else:
            tar.extractall(to)
    return to / "src"


def same_source(one: Path, other: Path) -> bool:
    """Whether two sources hold the same package, file for file, compiled files apart."""

    def alike(compared: filecmp.dircmp[str]) -> bool:
        if compared.left_only or compared.right_only or compared.funny_files:
            return False
        _same, differ, errors = filecmp.cmpfiles(
            compared.left, compared.right, compared.common_files, shallow=False
        )
        return not differ and not errors and all(map(alike, compared.subdirs.values()))

    return alike(
        filecmp.dircmp(one / "manuscript_guard", other / "manuscript_guard", ignore=["__pycache__"])
    )


# ----------------------------------------------------------------- a change that is meant


@dataclass(frozen=True)
class Expected:
    reading: str
    why: str


def declared(written: str) -> list[Expected]:
    """The entries of `differential_expected.yaml`, each a reading and why it will differ."""

    def refused(what: str) -> ValueError:
        return ValueError(f"{EXPECTED.name}: {what}")

    document = yaml.safe_load(written) or {}
    entries = document.get("expected", []) if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise refused("`expected:` is a list of entries, each a `reading:` and a `why:`")
    found: list[Expected] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"reading", "why"}:
            raise refused(f"an entry is a `reading:` and a `why:` and nothing else, not {entry!r}")
        reading, why = entry["reading"], entry["why"]
        if not isinstance(reading, str) or not isinstance(why, str) or not why.split():
            raise refused(f"{reading!r} does not say in words why it will differ")
        if any(reading == other.reading for other in found):
            raise refused(f"{reading!r} is entered twice; one entry says all that is meant")
        found.append(Expected(reading, " ".join(why.split())))
    return found


def new_entries(here: list[Expected], at_base: list[Expected]) -> dict[str, str]:
    """The readings this pull request says will differ, each with why: the entries the
    base does not have. One the base has was another pull request's, and is spent."""
    return {entry.reading: entry.why for entry in here if entry not in at_base}
