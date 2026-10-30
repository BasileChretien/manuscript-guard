"""`manuscript-guard vault init` and `vault check`.

`init` is the person's: it registers the data and prints the agent tool's deny rules, and
with `--agent-settings` writes them, once the person says yes at a terminal. `check` may be
run by anyone, the agent included: it reads nothing of the data, and says whether this session
can.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manuscript_guard.vault import DOC, LOCAL, REGISTRY, VARIABLE
from manuscript_guard.vault.probe import (
    EXIT,
    READABLE,
    UNREGISTERED,
    Probe,
    VaultFileError,
    local_folder,
    registered,
    state,
)

_PREFIX = "manuscript-guard: vault"


def _root(args: argparse.Namespace) -> Path:
    from manuscript_guard.contracts import find_root

    return find_root(Path(args.path))


def cmd_vault(args: argparse.Namespace) -> int:
    try:
        if args.verb == "check":
            return _check(args)
        return _init(args)
    except VaultFileError as exc:
        print(f"{_PREFIX}: {exc}", file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------- check


def _tried(found: Probe) -> str:
    parts = []
    if found.opened:
        parts.append(f"{len(found.opened)} of {len(found.opened) + len(found.refused)} "
                     "registered files opened for reading (nothing was read)")  # fmt: skip
    if found.refused:
        parts.append("refused or not there: " + ", ".join(
            f"{label} ({why})" for label, why in found.refused))  # fmt: skip
    parts.append("the folder was listed" if found.listed else "the folder could not be listed")
    return "; ".join(parts)


def _check(args: argparse.Namespace) -> int:
    root = _root(args)
    said, found = state(root)
    if said == UNREGISTERED:
        files = registered(root)
        if files:
            print(f"{_PREFIX}: not registered here. {REGISTRY} registers {len(files)} file(s), "
                  f"but this machine has no {LOCAL} saying where they are: run `manuscript-guard "
                  "vault init <folder> <files>` here.")  # fmt: skip
        else:
            print(f"{_PREFIX}: not registered here: no {LOCAL} in {root}.")
        return EXIT[UNREGISTERED]
    assert found is not None
    if said == READABLE:
        print(f"{_PREFIX}: readable from this session. {found.folder}: {_tried(found)}.")
        print("The separation the vault relies on is not in place for this account: an agent "
              f"run as it can read the data. {DOC} gives the setups that keep them apart.")
    else:
        print(f"{_PREFIX}: not reachable from this session. {found.folder}: {_tried(found)}.")
    return EXIT[said]


# ---------------------------------------------------------------------------- init


def _init(args: argparse.Namespace) -> int:
    from manuscript_guard.vault import register

    root = _root(args)
    words = list(args.words)
    try:
        if args.refresh:
            if words:
                raise register.Refused("--refresh takes no folder and no files: it digests "
                                       "the files registered again")  # fmt: skip
            done = register.refresh(root, args.as_ or "")
        elif not words and args.agent_settings:
            folder = local_folder(root)
            if folder is None:
                raise register.Refused(f"no vault is registered on this machine (no {LOCAL})")
            return _agent_rules(root, folder, write=True)
        else:
            if not words:
                raise register.Refused("name the vault's folder, then its files or globs")
            done = register.init(root, Path(words[0]), words[1:], args.as_ or "")
    except register.Refused as exc:
        print(f"{_PREFIX} init: refused, nothing written: {exc}", file=sys.stderr)
        return 2
    _said(done, refreshing=args.refresh)
    return _agent_rules(root, done.folder, write=args.agent_settings)


def _said(done, *, refreshing: bool) -> None:
    for note in done.notes:
        print(f"{_PREFIX}: {note}")
    if refreshing:
        changed = done.changed
        print(f"{_PREFIX}: changed since registered: {', '.join(changed)}" if changed else
              f"{_PREFIX}: no registered file changed")  # fmt: skip
        return
    for word, labels in (("registered", done.added), ("changed", done.changed),
                         ("unchanged", done.unchanged), ("no longer registered", done.removed)):
        if labels:
            print(f"{_PREFIX}: {word}: {', '.join(labels)}")
    print(f"{_PREFIX}: {REGISTRY} holds their digests, for git; {LOCAL} holds where the folder "
          f"is, for this machine only. `manuscript-guard vault check` says whether this session "
          f"can read them; {DOC} says how to make sure it cannot.")  # fmt: skip


def _agent_rules(root: Path, folder: Path, *, write: bool) -> int:
    """Print Claude Code's deny rules for the folder; with `write`, put them in its local
    settings once the person at the terminal says yes."""
    from manuscript_guard.deposit.remote.command import ask_at_terminal
    from manuscript_guard.vault import agent_rules

    try:
        rules = agent_rules.rules(folder)
    except agent_rules.Unspellable as exc:
        print(f"{_PREFIX}: no deny rules for Claude Code: {exc}. Rename the folder, or keep "
              f"the agent out by the operating system alone ({DOC}).")  # fmt: skip
        return 2 if write else 0
    print(f"{_PREFIX}: Claude Code's own deny rules keep its file tools, and the file commands "
          f"it recognises in a shell, out of the folder; not a script that opens a file itself "
          f"({DOC}). For .claude/settings.local.json, under permissions.deny:")  # fmt: skip
    for rule in rules:
        print(f"  {rule}")
    print(f"A shell command that names the folder or {VARIABLE} is refused by the plugin's "
          "hook while this session can read the folder.")  # fmt: skip
    if not write:
        print("`manuscript-guard vault init --agent-settings` writes them there, after asking "
              "you.")
        return 0
    settings = root / agent_rules.SETTINGS
    try:
        document, missing = agent_rules.merged(settings, rules)
    except ValueError as exc:
        print(f"{_PREFIX}: --agent-settings: {exc}; nothing written", file=sys.stderr)
        return 2
    if not missing:
        print(f"{_PREFIX}: {settings} already holds them")
        return 0
    answer = ask_at_terminal(f"Add these {len(missing)} deny rule(s) to {settings}? [y/N] ")
    if answer is None:
        print(f"{_PREFIX}: --agent-settings asks at a terminal, and there is none here: "
              "nothing written. Run it yourself, or add the rules by hand.", file=sys.stderr)
        return 2
    if answer.strip().lower() not in ("y", "yes"):
        print(f"{_PREFIX}: nothing written to {settings}")
        return 0
    agent_rules.write(settings, document)
    print(f"{_PREFIX}: written to {settings}. Claude Code reads it in a session started in "
          f"{root}.")  # fmt: skip
    return 0

