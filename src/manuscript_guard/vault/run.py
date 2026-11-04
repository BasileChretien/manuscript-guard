"""`vault run`: the analysis run on the data held in the vault, in a copy of the project
inside the vault's folder.

The person runs it at a terminal; the plugin's hook refuses it to an agent. It lists the
analysis scripts changed since the run released last, with the `git diff` to read them, and
asks. It then copies the project into `<vault>/.runs/<run>/`, not the system's temporary
folder, so that the copy shares the data's protection, and runs the scripts there in order
with MANUSCRIPT_GUARD_VAULT naming the vault's folder (`em.vault_input` reads it). What they
print goes to the person's terminal and to `<vault>/.runs/<run>/log.txt`. What they wrote is
moved into `<vault>/outbox/<run>/`, where it waits for a person's release (`release.py`).

Nothing is written to the project but the summary the agent reads,
`.manuscript-guard/vault/last-run.json` (`summary.py`): each script's exit code, and of one
that failed, the class of the exception, the frames of its traceback in the project's own
files and the column a KeyError names where the released profile or the dictionary holds
it; no message and no value.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from manuscript_guard.vault import RUN_VARIABLE, VARIABLE

#: Inside the vault's folder: the runs, each a copy of the project and its log, and the
#: outbox, what each run wrote, waiting for a person's release.
RUNS = ".runs"
OUTBOX = "outbox"
LOG = "log.txt"
MANIFEST = "run.json"
MANIFEST_SCHEMA = "manuscript-guard/vault-run-record/1"
#: A run's id, as `new_run` makes one; nothing else names a folder of the vault.
RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}(?:-[0-9]+)?")
#: Inside a run's folder: the copy of the project, in a folder of its own whatever the
#: project's is called, and the versions the run released last ran (fix round 3 of #490).
COPY = "copy"
RELEASED = "released"
#: A commit as a release records it: git's id, SHA-1 or SHA-256.
_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
#: What a run leaves in the copy that is no output of it: Python's compiled files.
_LEFT = frozenset({"__pycache__"})
#: What a run can execute or source, by suffix: the runners' and the analysis sources', and
#: the shells' and the like (round 1 of #490).
SCRIPT_SUFFIXES = frozenset({".r", ".rmd", ".qmd", ".py", ".ipynb", ".sql", ".jl", ".do",
                             ".sas", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".pl",
                             ".m", ".stan", ".c", ".cc", ".cpp", ".h", ".hpp",
                             ".lua"})  # fmt: skip
#: Folders of the project that hold no script the run executes: at its root the results,
#: the data, the build and the records, and anywhere the libraries of others' code.
_NOT_SCRIPTS_AT_ROOT = frozenset({"results", "data", "build", "approvals", "profiles"})
_LIBRARIES = frozenset({"node_modules", "renv", "venv", "site-packages"})
#: How much of a script's standard error is kept, in this process only, for R's `Calls:`.
TAIL = 1 << 16
#: How long git may take to say which commit the project is at.
GIT_SECONDS = 10

#: The Python a `.py` script is run through, in place of `python script.py`, written into the
#: run's folder in the vault: the script runs as `__main__`, with its own folder first on the
#: path, and where it raises, the exception's class, its module, and the frames of its
#: traceback are written to the file named first, inside the vault, before the traceback is
#: printed. `summary.py` keeps of them only what the project's code already shows, and a
#: class only where it is a built-in exception. No message and no value is written.
WRAPPER = """
import builtins, json, os, runpy, sys, traceback
summary, copy, script = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [script]
sys.path[0] = os.path.dirname(os.path.abspath(script))
inside = os.path.join(os.path.normcase(os.path.realpath(copy)), "")
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit:
    raise
except BaseException as exc:
    kind = type(exc)
    module = sys.modules.get(kind.__module__)
    where = getattr(module, "__file__", None)
    held = module is not None and getattr(module, kind.__name__, None) is kind
    outside = isinstance(where, str) and not os.path.normcase(
        os.path.realpath(where)).startswith(inside)
    named = held and (module is builtins or outside)
    key = exc.args[0] if (isinstance(exc, KeyError) and len(exc.args) == 1
                          and isinstance(exc.args[0], str)) else None
    record = {"class": kind.__name__ if named else None,
              "module": kind.__module__ if named else None,
              "frames": [[f.filename, f.lineno, f.name]
                         for f in traceback.extract_tb(exc.__traceback__)],
              "key": key}
    try:
        with open(summary, "w", encoding="utf-8") as out:
            json.dump(record, out)
    except Exception:
        pass
    traceback.print_exc()
    sys.exit(1)
"""


class RunRefused(Exception):
    """Why nothing was run, in a sentence for the person at the terminal."""


@dataclass(frozen=True)
class Change:
    """An analysis script changed since the run released last: why it is listed, and how to
    read what changed."""

    path: str
    said: str
    read: str


@dataclass
class Ran:
    """What one run did."""

    run: str
    folder: Path
    scripts: list[tuple[str, int]] = field(default_factory=list)
    failed: str | None = None
    #: The script running, until it ends.
    running: str | None = None
    moved: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def log(self) -> Path:
        return self.folder / RUNS / self.run / LOG

    @property
    def outbox(self) -> Path:
        return self.folder / OUTBOX / self.run


# ---------------------------------------------------------------------------- the scripts


def _reparse(entry: os.DirEntry) -> bool:
    """Whether a folder's entry is a link: a symbolic link, or on Windows a junction or any
    other reparse point, which a walk must not go through (round 1 of #490)."""
    if entry.is_symlink():
        return True
    try:
        attributes = entry.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _walk(top: Path, skip=lambda _relative: False, left: frozenset[str] = _LEFT):
    """Each file under `top`, by its path from it, and each link, neither followed; with a
    flag saying which is a link. A folder `skip` names, by its path, is not entered, nor one
    named in `left` (Python's compiled files)."""
    pending = [top]
    while pending:
        folder = pending.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda one: one.name)
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(top).as_posix()
            if _reparse(entry):
                yield relative, path, True
            elif entry.is_dir(follow_symlinks=False):
                if entry.name not in left and not skip(relative):
                    pending.append(path)
            else:
                yield relative, path, False


#: What the copy leaves out, by name at any depth: `verify._skip`'s and compiled Python. The
#: copy and the listing of both sides read the project by this one rule (fix round 2 of #490).
_NOT_COPIED = frozenset({"build", ".git", *_LEFT})


def _not_copied(relative: str) -> bool:
    return relative.rsplit("/", 1)[-1] in _NOT_COPIED


def _copied_path(root: Path, relative: str) -> bool:
    """Whether the copy holds this path: no part of it a name the copy leaves out, and no
    folder on the way a link or a junction, which the copy does not go through."""
    from manuscript_guard.verify import _is_junction

    parts = relative.split("/")
    if any(part in _NOT_COPIED for part in parts):
        return False
    here = root
    for part in parts[:-1]:
        here = here / part
        if here.is_symlink() or _is_junction(str(here)):
            return False
    return True


def _not_scripts(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1]
    return name.startswith(".") or name in _LIBRARIES or _not_copied(relative) or (
        "/" not in relative and name in _NOT_SCRIPTS_AT_ROOT)  # fmt: skip


#: Files a runner reads before the script where they are there, wherever a run is: R's
#: profile and environment, read by a run that is not `--vanilla`, Quarto's project file and
#: renv's start; and every file of Quarto's extensions (the fix round of #490).
RUNNER_FILES = (".Rprofile", ".Renviron", "_quarto.yml", "_quarto.yaml", "renv/activate.R")
#: Read by Quarto in any folder of the project.
RUNNER_NAMES = frozenset({"_metadata.yml", "_metadata.yaml"})
RUNNER_FOLDERS = ("_extensions",)
#: Compiled code a run can load in place of a script: listed and recorded by digest.
COMPILED_SUFFIXES = frozenset({".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib"})


def script_files(root: Path, named: tuple[str, ...] = ()) -> dict[str, Path]:
    """Every file of the project that a run can execute or source, by its path from the
    root: by its suffix, anywhere but in the results, the data, the build, a hidden folder
    and the libraries of others' code, no link followed; and wherever they are, the scripts
    named to run and the files a runner reads first (round 2 of #490)."""
    suffixes = SCRIPT_SUFFIXES | COMPILED_SUFFIXES
    found = {relative: path for relative, path, link in sorted(_walk(root, _not_scripts))
             if not link and (path.suffix.lower() in suffixes or path.name in RUNNER_NAMES)}
    for folder in RUNNER_FOLDERS:
        if (root / folder).is_dir() and _copied_path(root, f"{folder}/x"):
            found.update({f"{folder}/{relative}": path
                          for relative, path, link in _walk(root / folder, _not_copied)
                          if not link})  # fmt: skip
    for relative in (*named, *RUNNER_FILES):
        path = root.joinpath(*relative.split("/"))
        if path.is_file() and not path.is_symlink() and _copied_path(root, relative):
            found.setdefault(relative, path)
    return dict(sorted(found.items()))


def analysis_sources(root: Path, named: tuple[str, ...] = ()) -> dict[str, str]:
    """Every script of the project (`script_files`), by its path from the root, with its
    digest as G1 takes a script's (`emit.source_digest`)."""
    from manuscript_guard.emit import source_digest

    return {relative: source_digest(path)
            for relative, path in script_files(root, named).items()}  # fmt: skip


def source_texts(work: Path, named: tuple[str, ...] = ()) -> dict[str, str]:
    """The text of every script of the copy as it was made, before anything ran in it: what
    the summary holds a name and a frame to."""
    texts = {}
    for relative, path in script_files(work, named).items():
        if path.suffix.lower() in COMPILED_SUFFIXES:
            continue
        try:
            texts[relative] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return texts


def default_scripts(root: Path) -> list[str]:
    """The scripts run where none is named: each file directly in `analysis/` that a runner
    here knows, in the order of their names (`00_profile.py`, `01_model.R`). A helper in a
    folder below is read by them, and not run."""
    from manuscript_guard.verify import RUNNERS

    folder = root / "analysis"
    return sorted(path.relative_to(root).as_posix() for path in folder.iterdir()
                  if path.is_file() and path.suffix.lower() in RUNNERS) if folder.is_dir() \
        else []  # fmt: skip


def scripts_to_run(root: Path, named: list[str]) -> list[str]:
    """The scripts to run, by their paths from the root, each one there with a runner here;
    refused otherwise."""
    from manuscript_guard.verify import runner_for

    chosen = []
    for given in named or default_scripts(root):
        path = Path(given)
        path = path if path.is_absolute() else root / path
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError) as exc:
            raise RunRefused(f"{given} is not a file of the project") from exc
        if not (root / relative).is_file():
            raise RunRefused(f"{given} is not there")
        if runner_for(root / relative) is None:
            raise RunRefused(f"no runner for {Path(relative).suffix} on this machine, to run "
                             f"{relative}")  # fmt: skip
        chosen.append(relative)
    if not chosen:
        raise RunRefused("no script to run: name them, or put them directly in analysis/")
    return list(dict.fromkeys(chosen))


def changes(sources: dict[str, str], last: dict | None) -> list[Change]:
    """Each script whose digest is not the one the run released last ran with."""
    if last is None:
        return [Change(path, "no run on the vault has been released yet", f"read {path} whole")
                for path in sources]  # fmt: skip
    before = {entry["path"]: entry["sha256"] for entry in last["scripts"]}
    commit = last.get("commit")
    said = f"run {last['run']}, released on {str(last['released_at'])[:10]}"
    out = []
    for path, digest in sources.items():
        if before.get(path) == digest:
            continue
        read = (f"git diff {commit} -- {path}" if commit else f"read {path} whole")
        out.append(Change(path, f"changed since {said}" if path in before else
                          f"not in {said}", read))  # fmt: skip
    return out


def commit_of(root: Path) -> str | None:
    """The project's git commit, or None where git cannot say."""
    try:
        said = subprocess.run(["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
                              cwd=root, capture_output=True, text=True, check=False,
                              timeout=GIT_SECONDS)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    sha = said.stdout.strip()
    return sha if said.returncode == 0 and len(sha) >= 40 else None


# ---------------------------------------------------------------------------- the run


def run_key(run: str) -> tuple[str, int]:
    """A run's id as it is ordered: its time, then its number, `-10` after `-9`."""
    parts = run.split("-")
    base = "-".join(parts[:2])
    number = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    return base, number


def new_run(folder: Path) -> str:
    """A run's id: when it started, in UTC, with a number after it where that is taken."""
    base = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run, number = base, 1
    while (folder / RUNS / run).exists() or (folder / OUTBOX / run).exists():
        number += 1
        run = f"{base}-{number}"
    return run


def _linked_results(root: Path) -> str | None:
    """Why the project's `results/`, which the copy empties, cannot be emptied safely: it, or
    something in it, is a link or a junction (round 2 of #490)."""
    from manuscript_guard.verify import _is_junction

    results = root / "results"
    if results.is_symlink() or _is_junction(str(results)):
        return "results/ is a link or a junction: make it a folder of the project's own"
    links = [relative for relative, _path, link in _walk(results, left=frozenset()) if link] \
        if results.is_dir() else []  # fmt: skip
    if links:
        return f"results/ holds a link or a junction: {', '.join(links)}"
    return None


def stage(root: Path, work: Path) -> None:
    """The project copied to `work`, as `verify` copies it, its results emptied, so that what
    is in them after the run is what the run wrote. Refused, before anything is copied, where
    the project's results are, or hold, a link."""
    from manuscript_guard.verify import _skip

    if why := _linked_results(root):
        raise RunRefused(why)

    def ignored(directory: str, names: list[str]) -> set[str]:
        # `_NOT_COPIED`, the rule the listing reads the project by; no compiled Python, so
        # that none stands in for a script listed; and every junction.
        return _skip(directory, names) | (_NOT_COPIED & set(names))

    try:
        shutil.copytree(root, work, symlinks=True, ignore=ignored)
    except (OSError, shutil.Error) as exc:
        raise RunRefused(f"could not copy the project into the vault: {exc}") from exc
    results = work / "results"
    if results.is_dir():
        # Wholly, `__pycache__` too (the fix round of #490).
        found = list(_walk(results, left=frozenset()))
        if any(link for _relative, _path, link in found):
            raise RunRefused("the copy's results/ holds a link or a junction")
        for _relative, path, _link in found:
            path.unlink()
        for folder in sorted((one for one in results.rglob("*") if one.is_dir()),
                             reverse=True):  # fmt: skip
            folder.rmdir()


def snapshot(work: Path) -> dict[str, tuple[int, int, bool]]:
    """Each file of the copy, by its path, with its size, when it was written and whether it
    is a link; nothing reached through a link or a junction (round 1 of #490)."""
    found = {}
    for relative, path, link in _walk(work):
        try:
            held = path.lstat()
        except OSError:
            continue
        found[relative] = (held.st_size, held.st_mtime_ns, link)
    return found


def command_for(script: Path, summary: Path, wrapper: Path, work: Path) -> list[str]:
    from manuscript_guard.verify import runner_for

    runner = runner_for(script)
    assert runner is not None  # `scripts_to_run` refused a script with none
    if script.suffix.lower() == ".py":
        # `-B`: no compiled file is written beside the copy's scripts.
        return [runner[0], "-B", *runner[1:], str(wrapper), str(summary), str(work),
                str(script)]
    return [*runner, str(script)]


def _pump(pipe, terminal, log, lock: threading.Lock, tail: bytearray | None) -> None:
    """Copy what a script prints to the person's terminal and to the log, as it comes."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    while chunk := pipe.read1(1 << 16):
        with lock:
            log.write(chunk)
            log.flush()
            _show(terminal, chunk, decoder)
            if tail is not None:
                tail.extend(chunk)
                del tail[:-TAIL]


def _show(terminal, chunk: bytes, decoder) -> None:
    buffer = getattr(terminal, "buffer", None)
    if buffer is not None:
        terminal.flush()
        buffer.write(chunk)
        buffer.flush()
    else:
        terminal.write(decoder.decode(chunk))
        terminal.flush()


def execute(command: list[str], cwd: Path, env: dict[str, str], log) -> tuple[int, bytes]:
    """Run one script, its output streamed to the terminal and the log; its exit code and the
    end of its standard error, kept here for R's `Calls:` line."""
    from manuscript_guard.verify import _kill_tree

    group: dict = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                   if sys.platform == "win32" else {"start_new_session": True})  # fmt: skip
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group)  # fmt: skip
    lock, tail = threading.Lock(), bytearray()
    pumps = [threading.Thread(target=_pump, args=(process.stdout, sys.stdout, log, lock, None)),
             threading.Thread(target=_pump, args=(process.stderr, sys.stderr, log, lock, tail))]
    for pump in pumps:
        pump.start()
    try:
        code = process.wait()
    except KeyboardInterrupt:
        _kill_tree(process)
        code = process.wait()
    for pump in pumps:
        pump.join()
    return code, bytes(tail)


def collect(work: Path, before: dict[str, tuple[int, int, bool]], outbox: Path) -> tuple[
        list[str], list[str]]:  # fmt: skip
    """Move each file the run wrote or changed in the copy into the outbox, at its path; and
    say which it left, a link it made, or a junction, being no file of its own."""
    moved, left = [], []
    for relative, held in sorted(snapshot(work).items()):
        if before.get(relative) == held or relative.endswith(".pyc"):
            continue
        source = work / relative
        if held[2]:
            left.append(relative)
            continue
        target = outbox / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(relative)
    return moved, left


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Staged:
    """A copy of the project made in the vault for a run, before anything runs in it: its
    scripts by digest, which the person is shown, and their texts, which the summary holds
    names to. What is listed is what runs (round 2 of #490)."""

    run: str
    folder: Path
    here: Path
    work: Path
    scripts: list[str]
    sources: dict[str, str]
    texts: dict[str, str]
    record: dict


def prepare(project, folder: Path, scripts: list[str]) -> Staged:
    """Copy the project into the vault for a run of `scripts`, and read its scripts there.
    Refused, with nothing in the vault, where the copy cannot be made safely."""
    root = Path(project.root)
    if why := _linked_results(root):
        raise RunRefused(why)
    run_id = new_run(folder)
    here = folder / RUNS / run_id
    work = here / COPY / root.name
    here.mkdir(parents=True)
    named = tuple(scripts)
    try:
        stage(root, work)
        sources = analysis_sources(work, named)
        texts = source_texts(work, named)
    except BaseException as exc:
        # A copy that could not be made whole, or one stopped while it was made, is not left
        # in the vault (the fix rounds of #490).
        shutil.rmtree(here, ignore_errors=True)
        with contextlib.suppress(OSError):
            here.parent.rmdir()
        if isinstance(exc, OSError):
            raise RunRefused(f"could not copy the project into the vault: {exc}") from exc
        raise
    record = {"schema": MANIFEST_SCHEMA, "run": run_id, "ran_at": _now(),
              "commit": commit_of(root),
              "scripts": [{"path": path, "sha256": digest} for path, digest in sources.items()],
              "ran": list(scripts)}  # fmt: skip
    return Staged(run_id, folder, here, work, list(scripts), sources, texts, record)


def differs(project, staged: Staged) -> list[str]:
    """The scripts listed whose file in the project is no longer the copy's: changed, gone or
    new since the copy was made. Asked at the yes, so that what the person read in the project
    is what the copy runs (the fix round of #490)."""
    now = analysis_sources(Path(project.root), tuple(staged.scripts))
    return sorted(path for path in set(now) | set(staged.sources)
                  if now.get(path) != staged.sources.get(path))


def discard(staged: Staged) -> None:
    """Remove a copy the person chose not to run, and the folder of runs where it was the
    only one."""
    shutil.rmtree(staged.here, ignore_errors=True)
    with contextlib.suppress(OSError):
        staged.here.parent.rmdir()


def run(project, staged: Staged) -> Ran:
    """Run the staged scripts on the data held in the vault, in the copy made for them, and
    move what they wrote into its outbox where every script finished; write the summary the
    agent reads in the project."""
    from manuscript_guard.vault.summary import write_summary

    root = Path(project.root)
    folder, run_id, here, work = staged.folder, staged.run, staged.here, staged.work
    record = dict(staged.record)
    done = Ran(run_id, folder)
    ran_at = record["ran_at"]
    try:
        failure = _steps(project, staged, done)
    except BaseException:
        # Stopped after it started, by a fault or a Ctrl-C: the copy goes, and the log stays
        # with a record that says the run did not finish (fix round 2 of #490); the agent is
        # told it stopped, so that it never reads the run before's summary as this one's
        # (fix round 3).
        record.update({"finished": False, "outbox": []})
        with contextlib.suppress(OSError):
            (here / MANIFEST).write_text(json.dumps(record, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")  # fmt: skip
        shutil.rmtree(work.parent, ignore_errors=True)
        stopped = [*done.scripts, *([(done.running, None)] if done.running else [])]
        with contextlib.suppress(Exception):
            write_summary(root, run_id, ran_at, stopped, None, outbox=False, stopped=True)
        raise
    record.update({"finished": done.failed is None, "outbox": done.moved})
    (here / MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8",
                                 newline="\n")  # fmt: skip
    try:
        shutil.rmtree(work.parent)
    except OSError as exc:
        done.notes.append(f"the copy of the project at {work} could not be removed ({exc}): "
                          "remove it yourself")  # fmt: skip
    write_summary(root, run_id, ran_at, done.scripts, failure, outbox=bool(done.moved))
    return done


def _steps(project, staged: Staged, done: Ran) -> dict | None:
    """Run the scripts in the copy, and move what they wrote into the outbox where every one
    finished; what the summary says of the one that failed, or None."""
    from manuscript_guard.vault.summary import python_failure, r_failure

    folder, run_id, here, work = staged.folder, staged.run, staged.here, staged.work
    scripts, texts = staged.scripts, staged.texts
    wrapper = here / "wrapper.py"
    wrapper.write_text(WRAPPER, encoding="utf-8", newline="\n")
    before = snapshot(work)
    env = {**os.environ, VARIABLE: str(folder), RUN_VARIABLE: run_id,
           "PYTHONDONTWRITEBYTECODE": "1"}
    failure = None
    with (here / LOG).open("wb") as log:
        for number, script in enumerate(scripts, 1):
            summary = here / "summary" / f"{number}.json"
            summary.parent.mkdir(exist_ok=True)
            log.write(f"== {script}\n".encode())
            log.flush()
            command = command_for(work / script, summary, wrapper, work)
            done.running = script
            code, tail = execute(command, work, env, log)
            done.running = None
            done.scripts.append((script, code))
            if code != 0:
                done.failed = script
                failure = (python_failure(project, texts, work, script, code, summary)
                           if script.lower().endswith(".py")
                           else r_failure(texts, script, code, tail))  # fmt: skip
                break
    if done.failed is None:
        done.moved, done.left = collect(work, before, done.outbox)
    return failure


def released_version(root: Path, staged: Staged, path: str, commit: str | None) -> Path | None:
    """The script as the run released last ran it, from git at that run's commit, the path
    read from the project's own folder (`./`, so that a project inside a larger repository
    gets its own file), written beside the copy under `<vault>/.runs/<run>/released/`, so that
    the person reads the copy's bytes against it; None where it had none, the record's commit
    is no commit's id, or git or the disk cannot say (fix round 3 of #490)."""
    if not (isinstance(commit, str) and _COMMIT.fullmatch(commit)):
        return None
    try:
        said = subprocess.run(["git", "-c", "core.fsmonitor=false", "show", "--end-of-options",
                               f"{commit}:./{path}"], cwd=root, capture_output=True,
                              check=False, timeout=GIT_SECONDS)  # fmt: skip
        if said.returncode != 0:
            return None
        target = staged.here.joinpath(RELEASED, *path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(said.stdout)
    except (OSError, subprocess.SubprocessError):
        return None
    return target


def read_manifest(folder: Path, run_id: str) -> dict:
    """What `vault run` recorded of a run, in the vault; refused where there is none."""
    if not RUN_ID.fullmatch(run_id):
        raise RunRefused(f"{run_id!r} is no run's id: `vault run` prints one, as "
                         "20261104-093012")  # fmt: skip
    path = folder / RUNS / run_id / MANIFEST
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RunRefused(f"no run {run_id} in the vault ({path} cannot be read: {exc})") from exc
    if not (isinstance(document, dict) and document.get("schema") == MANIFEST_SCHEMA
            and document.get("run") == run_id):  # fmt: skip
        raise RunRefused(f"{path} is not the record of run {run_id}")
    return document


__all__ = ["Change", "Ran", "RunRefused", "Staged", "analysis_sources", "changes",
           "default_scripts", "discard", "new_run", "prepare", "read_manifest", "run",
           "scripts_to_run", "differs"]
