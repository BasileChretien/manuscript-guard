"""Whether the vault's data can be read from this session, found by trying.

Each registered file is opened for reading and closed without a byte read, and the folder is
listed, by the process that asks: `vault check` at a terminal, or a hook in the agent tool's
process, as the agent's account. That measures what the operating system lets this account
do, which is the separation that holds. `os.access` is not used: on Windows it reads the
read-only attribute and not the access control list, so it says "readable" of a file the
account is refused.

It sees nothing of a sandbox an agent tool applies to shell commands only: the hook runs
outside it, and an agent under the same account in such a sandbox is reported readable
(DESIGN.md, Known gaps).

Imports nothing heavy at the top: the shell guard reads `local_folder` on every command.
"""

from __future__ import annotations

import contextlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.vault import LOCAL, LOCAL_SCHEMA, REGISTRY, REGISTRY_SCHEMA

#: The three answers, and the exit code `vault check` gives each.
UNREACHABLE, READABLE, UNREGISTERED = "unreachable", "readable", "unregistered"
EXIT = {UNREACHABLE: 0, READABLE: 1, UNREGISTERED: 2}


class VaultFileError(Exception):
    """A vault file of the project that cannot be used, in a sentence that names it."""


@dataclass(frozen=True)
class Probe:
    """What this process could do in the vault's folder."""

    folder: Path
    #: Whether the folder could be listed.
    listed: bool
    #: The registered files opened for reading, by label.
    opened: tuple[str, ...]
    #: The registered files that could not be opened, each with why.
    refused: tuple[tuple[str, str], ...]
    #: Whether the folder, listed, holds anything at all.
    holds: bool = False

    @property
    def readable(self) -> bool:
        """Readable where a registered file opened, or where the folder lists and holds
        anything, the registered files moved or renamed (round 1 of #488). An empty folder,
        the mount point of a volume that is not mounted, is not reachable."""
        return bool(self.opened) or (self.listed and self.holds)


def _structured(path: Path) -> object:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError) as exc:
        raise VaultFileError(f"{path}: cannot be read: {exc}") from exc


def local_file(root: Path) -> Path:
    return root.joinpath(*LOCAL.parts)


def registry_file(root: Path) -> Path:
    return root.joinpath(*REGISTRY.parts)


def _local(root: Path) -> dict | None:
    """`.manuscript-guard/vault.local.yaml`, or None where no vault is registered here. A file
    there that does not name the folder by an absolute path is refused."""
    file = local_file(root)
    if not file.is_file():
        return None
    document = _structured(file)
    folders = [document.get(key) for key in ("folder", "resolved")] if isinstance(
        document, dict) else [None]  # fmt: skip
    if not (isinstance(document, dict) and document.get("schema") == LOCAL_SCHEMA
            and isinstance(folders[0], str) and folders[0]
            and all(one is None or (isinstance(one, str) and Path(one).is_absolute())
                    for one in folders)):  # fmt: skip
        raise VaultFileError(
            f"{file}: does not name the vault's folder as {LOCAL_SCHEMA} does: run "
            "`manuscript-guard vault init` again"
        )
    return document


def local_folder(root: Path) -> Path | None:
    """The vault's folder on this machine, as the person typed it at `vault init`, or None
    where no vault is registered here."""
    document = _local(root)
    return None if document is None else Path(document["folder"])


def local_spellings(root: Path) -> list[str]:
    """The folder as typed and as its links lead, both taken at `vault init`, so that a hook
    compares a command with them and asks nothing of the folder on disk."""
    document = _local(root)
    if document is None:
        return []
    return list(dict.fromkeys(one for one in (document["folder"], document.get("resolved"))
                              if one))  # fmt: skip


def registered(root: Path) -> list[dict]:
    """The files `design/vault.yaml` registers, each as written there; none where there is
    no such file. A file there that is not a registry is refused."""
    file = registry_file(root)
    if not file.is_file():
        return []
    document = _structured(file)
    files = document.get("files") if isinstance(document, dict) else None
    if not (isinstance(document, dict) and document.get("schema") == REGISTRY_SCHEMA
            and isinstance(files, list)
            and all(isinstance(entry, dict) and isinstance(entry.get("label"), str)
                    for entry in files)):  # fmt: skip
        raise VaultFileError(f"{file}: is not a registry of the vault's files")
    return files


def _opens(path: Path) -> str | None:
    """None where the file opens for reading, else why not. Nothing is read."""
    try:
        handle = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as exc:
        return type(exc).__name__
    os.close(handle)
    return None


def _lists(folder: Path) -> tuple[bool, bool]:
    """Whether the folder lists, and whether it holds anything."""
    try:
        with os.scandir(folder) as entries:
            return True, next(entries, None) is not None
    except OSError:
        return False, False


def probe(folder: Path, labels: list[str]) -> Probe:
    """Try each registered file, then the folder."""
    opened, refused = [], []
    for label in labels:
        why = _opens(folder.joinpath(*label.split("/")))
        if why is None:
            opened.append(label)
        else:
            refused.append((label, why))
    listed, holds = _lists(folder)
    return Probe(folder, listed, tuple(opened), tuple(refused), holds)


def state(root: Path) -> tuple[str, Probe | None]:
    """`READABLE`, `UNREACHABLE` or `UNREGISTERED`, with what was tried."""
    folder = local_folder(root)
    if folder is None:
        return UNREGISTERED, None
    found = probe(folder, [entry["label"] for entry in registered(root)])
    return (READABLE if found.readable else UNREACHABLE), found


class Pending:
    """`state(root)` asked on a thread of its own, so that a hook waits for it no longer than
    it can: a volume that is not mounted, or a share that takes its time, may not answer."""

    def __init__(self, root: Path) -> None:
        self._said: list[str] = []
        self.thread = threading.Thread(target=self._ask, args=(root,), daemon=True,
                                       name="manuscript-guard-vault")  # fmt: skip
        self.thread.start()

    def _ask(self, root: Path) -> None:
        # No answer where a vault file cannot be used: it is said as one not checked.
        with contextlib.suppress(VaultFileError, OSError, ValueError):
            self._said.append(state(root)[0])

    def answer(self, limit: float) -> str | None:
        """The answer, or None where it did not come within `limit` seconds or could not be
        had. The thread is left running where it is still asking."""
        self.thread.join(max(limit, 0.0))
        if self.thread.is_alive():
            return None
        return self._said[0] if self._said else None


def state_in_time(root: Path, limit: float) -> tuple[str | None, threading.Thread | None]:
    """`state(root)`'s answer, or None where it did not come within `limit` seconds; and the
    thread still asking, so that a hook can end without it, or None."""
    pending = Pending(root)
    said = pending.answer(limit)
    return said, (pending.thread if pending.thread.is_alive() else None)
