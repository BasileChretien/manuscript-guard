"""`manuscript-guard vault run` and `vault release`: the person's, at a terminal.

Both refuse where standard input is not a terminal, before anything of the vault is read:
a script's or an agent's input answers nothing here. The plugin's hook refuses both to an
agent, as it refuses `deposit --publish`. An agent can start a pseudo-terminal; the hook's
refusal is the other half (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manuscript_guard.vault import DOC, LOCAL, REGISTRY, SUMMARY
from manuscript_guard.vault.probe import READABLE, local_folder, registered, state
from manuscript_guard.vault.run import RUN_ID

_PREFIX = "manuscript-guard: vault"


def _at_terminal() -> bool:
    """Whether a person is there to answer: standard input is a terminal."""
    stream = sys.stdin
    return stream is not None and stream.isatty()


def _ask(prompt: str) -> str | None:
    from manuscript_guard.deposit.remote.command import ask_at_terminal

    return ask_at_terminal(prompt)


def _yes(answer: str | None) -> bool:
    return answer is not None and answer.strip().lower() in ("y", "yes")


def _refused(verb: str, why: str) -> int:
    print(f"{_PREFIX} {verb}: refused, nothing done: {why}", file=sys.stderr)
    return 2


def _no_terminal(verb: str) -> int:
    return _refused(verb, f"`vault {verb}` is run by a person at a terminal, and standard input "
                    "here is not one. Run it yourself, in a terminal the agent tool cannot "
                    f"read ({DOC})")  # fmt: skip


def _vault(verb: str, root: Path) -> Path | int:
    folder = local_folder(root)
    if folder is None:
        return _refused(verb, f"no vault is registered on this machine (no {LOCAL}): run "
                        "`manuscript-guard vault init <folder> <files>`")  # fmt: skip
    if not registered(root):
        return _refused(verb, f"{REGISTRY} registers no file")
    return folder


# ---------------------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    from manuscript_guard.contracts import find_root, load_project
    from manuscript_guard.vault import run as running
    from manuscript_guard.vault.records import last_release

    root = find_root(Path(args.path))
    if not _at_terminal():
        return _no_terminal("run")
    folder = _vault("run", root)
    if isinstance(folder, int):
        return folder
    project, _report = load_project(root)
    try:
        scripts = running.scripts_to_run(root, list(args.words))
    except running.RunRefused as exc:
        return _refused("run", str(exc))
    said, _found = state(root)
    if said != READABLE:
        return _refused("run", f"the vault's folder, {folder}, cannot be read from here: "
                        "`manuscript-guard vault check` says why")  # fmt: skip
    changed = running.changes(running.analysis_sources(root), last_release(root))
    print(f"{_PREFIX} run: the scripts to run on the data held in {folder}, in this order:")
    for script in scripts:
        print(f"  {script}")
    if changed:
        print("The analysis scripts that changed since the run released last, by digest; "
              "read each before you answer:")  # fmt: skip
        for change in changed:
            print(f"  {change.path}: {change.said}; {change.read}")
    else:
        print("No analysis script changed since the run released last.")
    print("They were written with an agent: what they print or write can hold any value of "
          "the data. What they write waits in the vault's outbox until you release it.")
    answer = _ask("Run them on the data held in the vault? [y/N] ")
    if answer is None:
        return _no_terminal("run")
    if not _yes(answer):
        print(f"{_PREFIX} run: nothing run")
        return 0
    run_id = running.new_run(folder)
    done = running.run(project, folder, scripts, run_id)
    for note in done.notes:
        print(f"{_PREFIX} run: {note}")
    print(f"{_PREFIX} run {run_id}: what the scripts printed is in {done.log}.")
    if done.failed is not None:
        code = dict(done.scripts)[done.failed]
        print(f"{_PREFIX} run {run_id}: {done.failed} exited {code}; the scripts after it were "
              "not run, and nothing was put in the outbox. The agent is told the exit code, "
              f"and where the code failed but not why, in {SUMMARY}.")  # fmt: skip
        return 1
    for left in done.left:
        print(f"{_PREFIX} run {run_id}: {left} is a link the run made, and is left out")
    print(f"{_PREFIX} run {run_id}: {len(done.moved)} file(s) wait in {done.outbox}. Read "
          f"them, then `manuscript-guard vault release {run_id} --as <you>`.")  # fmt: skip
    return 0


# ---------------------------------------------------------------------------- release


def _show(findings) -> None:
    for finding in findings:
        print(f"  {finding.message}" + (f"\n    {finding.hint}" if finding.hint else ""))


def _signed(project, signable, settled) -> bool:
    """Say whether the signable stands signed off; print its findings where it does not."""
    from manuscript_guard.vault.release import _standing

    ok, found = _standing(project, signable)
    if ok:
        for finding in found:
            print(f"{_PREFIX} release: {finding.message}")
        settled.append(signable.id)
        return True
    _show(found)
    return False


def _named(unread: list[str]) -> list[str] | None:
    """The files no check reads that the person names, one by one; None where nobody is
    there to answer."""
    if not unread:
        return []
    print("No check reads these files: a figure can draw a real person's values, and a file "
          "can hold anything. Each is released only where you type its path.")  # fmt: skip
    named = []
    for relative in unread:
        answer = _ask(f"  {relative}: type its path to release it, or press Enter to keep "
                      "it in the vault: ")  # fmt: skip
        if answer is None:
            return None
        if answer.strip() == relative:
            named.append(relative)
    return named


def cmd_release(args: argparse.Namespace) -> int:
    from manuscript_guard.contracts import find_root, load_project
    from manuscript_guard.vault import release as releasing
    from manuscript_guard.vault.records import release_file

    root = find_root(Path(args.path))
    if not _at_terminal():
        return _no_terminal("release")
    words = list(args.words)
    if len(words) != 1:
        return _refused("release", "name the run to release, as `vault run` printed it")
    run_id = words[0]
    if not RUN_ID.fullmatch(run_id):
        return _refused("release", f"{run_id!r} is no run's id: `vault run` prints one, as "
                        "20261104-093012")  # fmt: skip
    folder = _vault("release", root)
    if isinstance(folder, int):
        return folder
    project, _report = load_project(root)
    if release_file(root, run_id).exists():
        return _refused("release", f"run {run_id} was released already "
                        f"({release_file(root, run_id).relative_to(root).as_posix()})")
    try:
        who = releasing.releaser(project, args.as_ or "")
        box = releasing.open_outbox(project, folder, run_id)
    except releasing.Refused as exc:
        return _refused("release", str(exc))
    print(f"{_PREFIX} release: {releasing.SENT}")
    found, inputs = releasing.read_outbox(project, box)
    if found.refused:
        print(f"{_PREFIX} release: refused, nothing released: the outbox of run {run_id} holds "
              "what the data custodian forbids, or what cannot be read:", file=sys.stderr)
        for said in found.refused:
            print(f"  {said}", file=sys.stderr)
        return 1
    signed: list[str] = []
    agent = releasing.agent_signable(project)
    if agent is not None and not _signed(project, agent, signed):
        print(f"{_PREFIX} release: refused, nothing released, until the data custodian signs "
              f"off that the agent's provider may read what is released.", file=sys.stderr)
        return 1
    small = releasing.small_signable(project, run_id, found.small)
    if small is not None and not _signed(project, small, signed):
        print(f"{_PREFIX} release: refused, nothing released: counts below the data "
              "custodian's minimum, as they stand:", file=sys.stderr)  # fmt: skip
        for one in found.small:
            print(f"  {one.fragment}: {one.where} is {one.count}", file=sys.stderr)
        return 1
    for warning in found.warnings:
        print(f"{_PREFIX} release: warning: {warning}")
    named = _named(box.unread)
    if named is None:
        return _no_terminal("release")
    going = [*box.fragments, *(one for one, _entry in box.harvested), *box.plan, *named]
    if not going:
        print(f"{_PREFIX} release: nothing to release; the outbox is left as it is")
        return 0
    print(f"{_PREFIX} release: into {root}:")
    for relative in going:
        print(f"  {relative}")
    if not _yes(_ask(f"Release these {len(going)} file(s) into the project? [y/N] ")):
        print(f"{_PREFIX} release: nothing released")
        return 0
    path = releasing.write_release(project, box, named, who, inputs, found.warnings, signed)
    print(f"{_PREFIX} release: {len(going)} file(s) released, recorded in "
          f"{path.relative_to(root).as_posix()}. {releasing.SENT}")  # fmt: skip
    return 0
