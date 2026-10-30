"""`vault init`: register the folder where the data are held, and which files they are.

Two files are written. `design/vault.yaml` is committed: each file by its label (its name
inside the folder, never the absolute path), its digests as the emitter takes an input's
(`emit.input_digest`, `emit.sha256_of`), its size, and who registered it and when. No row
count: a count is a result, and a result leaves the vault only through a person's release.
`.manuscript-guard/vault.local.yaml` is this machine's, and git-ignored: the folder's absolute
path, which the hooks need. The path is no secret: where the operating system keeps the
agent out, knowing it gives no access.

Refused, with nothing written: a folder inside the project or holding it, links followed; a
project whose `paper.yaml` declares no `custodian.minimum_cell_count` (1 where the custodian
has no rule, said on purpose); a name or a glob that matches no file in the folder, or a file
whose link leads out of it; and a local file git would track.
"""

from __future__ import annotations

import glob
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from manuscript_guard.vault import LOCAL, LOCAL_FOLDER, LOCAL_SCHEMA, REGISTRY, REGISTRY_SCHEMA
from manuscript_guard.vault.probe import local_file, local_folder, registered, registry_file

#: The lines of `.gitignore` that already keep `.manuscript-guard/` out, as written.
_IGNORED = (".manuscript-guard/", ".manuscript-guard", "/.manuscript-guard/",
            "/.manuscript-guard")  # fmt: skip
_HEADER = (
    "# The files of the vault, registered by `manuscript-guard vault init`: each by its name\n"
    "# inside the vault's folder and its digests, never its contents or where it is.\n"
    "# Where the folder is on this machine is in .manuscript-guard/vault.local.yaml, which\n"
    "# git does not track.\n"
)


class Refused(Exception):
    """Why nothing was registered, in a sentence for the person at the terminal."""


@dataclass
class Registered:
    """What `init` or `refresh` did."""

    folder: Path
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    #: Said beside it: the line added to `.gitignore`, git not asked.
    notes: list[str] = field(default_factory=list)


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def _folder(given: Path, root: Path) -> Path:
    try:
        folder = given.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Refused(f"{given}: no such folder ({exc})") from exc
    if not folder.is_dir():
        raise Refused(f"{given} is not a folder")
    project = root.resolve()
    if _inside(folder, project):
        raise Refused(
            f"{given} is inside the project ({project}). An agent works in the project's "
            "folder, so the vault is kept outside it: move the data to a folder of their own, "
            "outside the project, and register that."
        )
    if _inside(project, folder):
        raise Refused(
            f"the project ({project}) is inside {given}: an agent working in the project "
            "would be working in the vault. Keep the data in a folder of their own, outside "
            "the project."
        )
    return folder


def _minimum(root: Path) -> int:
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.custodian import minimum_cell_count

    project, _report = load_project(root)
    minimum = minimum_cell_count(project)
    if minimum is None:
        raise Refused(
            "paper.yaml declares no `custodian: {minimum_cell_count: N}`. Every later check "
            "of what leaves the vault holds counts to it, and custodians differ (5, 10, 11): "
            "write the custodian's, or 1 where there is no rule, and run this again."
        )
    return minimum


def _files(folder: Path, patterns: list[str]) -> list[str]:
    """Each file the names and globs match in the folder, as its label, once, sorted."""
    if not patterns:
        raise Refused(
            "name the files to register, or globs for them, after the folder: only files "
            "named are registered, so that a whole folder is not taken in by mistake"
        )
    labels: set[str] = set()
    for pattern in patterns:
        relative = pattern
        if Path(pattern).is_absolute():
            try:
                relative = str(Path(pattern).resolve().relative_to(folder))
            except (ValueError, OSError) as exc:
                raise Refused(f"{pattern} is not in the vault's folder, {folder}") from exc
        matched = [match for match in glob.glob(relative, root_dir=folder, recursive=True)
                   if (folder / match).is_file()]  # fmt: skip
        if not matched:
            raise Refused(f"{pattern} matches no file in {folder}")
        for match in matched:
            real = (folder / match).resolve()
            if not _inside(real, folder):
                raise Refused(f"{match} leads out of the vault's folder, to {real}")
            labels.add(Path(os.path.normpath(match)).as_posix())
    return sorted(labels)


def _digests(folder: Path, label: str) -> dict:
    from manuscript_guard.emit import input_digest, sha256_of

    path = folder.joinpath(*label.split("/"))
    try:
        return {"sha256": input_digest(path), "raw_sha256": sha256_of(path),
                "bytes": path.stat().st_size}  # fmt: skip
    except OSError as exc:
        raise Refused(f"{label} cannot be read here: {exc}") from exc


def _gitignored(root: Path) -> list[str]:
    """Add `.manuscript-guard/` to `.gitignore` where no line of it does, and refuse where git
    would track the local file all the same. What was done or could not be asked is said."""
    from manuscript_guard.gates.custodian import _git

    notes = []
    ignore = root / ".gitignore"
    data = ignore.read_bytes() if ignore.exists() else b""
    lines = {line.strip() for line in data.decode("utf-8", "replace").splitlines()}
    if not lines & set(_IGNORED):
        ending = b"\r\n" if b"\r\n" in data else b"\n"
        gap = b"" if not data or data.endswith(b"\n") else ending
        ignore.write_bytes(data + gap + f"{LOCAL_FOLDER}/".encode() + ending)
        notes.append(f"added {LOCAL_FOLDER}/ to .gitignore")
    local = LOCAL.as_posix()
    try:
        tracked = _git(root, "ls-files", "--error-unmatch", "--", local)
        ignored = _git(root, "check-ignore", "-q", "--", local)
    except (OSError, subprocess.SubprocessError) as exc:  # git missing, or it took too long
        return [*notes, f"git could not be asked whether it tracks {local} ({exc})"]
    if "not a git repository" in (tracked.stderr + ignored.stderr).lower():
        return notes
    if tracked.returncode == 0:
        raise Refused(f"git tracks {local}: `git rm --cached {local}`, then run this again")
    if ignored.returncode == 1:
        raise Refused(
            f"git would track {local}: a rule of .gitignore takes it back in. Make git ignore "
            f"{LOCAL_FOLDER}/, then run this again"
        )
    if ignored.returncode != 0:
        return [*notes, f"git could not say whether it ignores {local}: "
                        f"{ignored.stderr.strip()}"]  # fmt: skip
    return notes


def _write_yaml(path: Path, document: dict, header: str = "") -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    text = header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    path.write_bytes(text.encode("utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entries(folder: Path, labels: list[str], before: dict[str, dict], by: str) -> tuple[
        list[dict], Registered]:  # fmt: skip
    done = Registered(folder)
    entries = []
    for label in labels:
        digests = _digests(folder, label)
        old = before.get(label)
        if old is not None and all(old.get(key) == digests[key] for key in digests):
            entries.append(old)
            done.unchanged.append(label)
            continue
        (done.changed if old is not None else done.added).append(label)
        entries.append({"label": label, **digests, "registered_by": by, "registered_on": _now()})
    done.removed = sorted(set(before) - set(labels))
    return entries, done


def _record(root: Path, folder: Path, entries: list[dict]) -> None:
    _write_yaml(registry_file(root), {"schema": REGISTRY_SCHEMA, "files": entries}, _HEADER)
    _write_yaml(local_file(root), {"schema": LOCAL_SCHEMA, "folder": str(folder)},
                "# This machine's: where the vault's folder is. Not for git.\n")  # fmt: skip


def init(root: Path, given: Path, patterns: list[str], by: str) -> Registered:
    """Register the files the names and globs match in the folder. Over an earlier
    registration, a file whose digests are the same keeps who registered it and when."""
    if not by.strip():
        raise Refused("--as names who registers the files")
    folder = _folder(given, root)
    _minimum(root)
    labels = _files(folder, patterns)
    before = {entry["label"]: entry for entry in registered(root)}
    entries, done = _entries(folder, labels, before, by.strip())
    done.notes = _gitignored(root)
    _record(root, folder, entries)
    return done


def refresh(root: Path, by: str) -> Registered:
    """Digest the registered files again, after a new extract, and say which changed."""
    if not by.strip():
        raise Refused("--as names who registers the files")
    folder = local_folder(root)
    before = {entry["label"]: entry for entry in registered(root)}
    if folder is None or not before:
        raise Refused(
            f"no vault is registered on this machine ({LOCAL} and {REGISTRY} are both needed): "
            "run `manuscript-guard vault init <folder> <files>`"
        )
    folder = _folder(folder, root)
    _minimum(root)
    missing = [label for label in before if not folder.joinpath(*label.split("/")).is_file()]
    if missing:
        raise Refused(
            f"not in {folder}: {', '.join(missing)}. Run `vault init` with the files the vault "
            "now holds"
        )
    entries, done = _entries(folder, list(before), before, by.strip())
    done.notes = _gitignored(root)
    _record(root, folder, entries)
    return done
