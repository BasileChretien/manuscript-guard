"""A stored copy kept out of git and not on this computer, as CI and a fresh clone have it.

A new project ignores `literature/sources/*` and commits `literature/sources.yaml`. A copy
counts as kept out of git only where the record lists it, it is absent, and git says its path
is ignored (Basile, 2026-11-05), so `keep_away` makes the project a git repository with that
line in its `.gitignore`, records the copy and deletes it.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.literature import copies

IGNORED = "literature/sources/*"


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-c", "user.name=Test", "-c",
         "user.email=test@example.org", *arguments],
        cwd=root, capture_output=True, text=True, timeout=60, check=True,
    )  # fmt: skip


def a_repository(root: Path, *, ignore: bool = True) -> None:
    """`root` as a git repository, ignoring the copies where `ignore`."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    if not (root / ".git").exists():
        git(root, "init", "-q")
    if ignore:
        gitignore = root / ".gitignore"
        held = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if IGNORED not in held.splitlines():
            gitignore.write_text(held + ("" if not held or held.endswith("\n") else "\n")
                                 + IGNORED + "\n", encoding="utf-8")  # fmt: skip


def record(root: Path, name: str, key: str) -> None:
    """Enter literature/sources/<name> in the record as the author's, as it is now."""
    project = load_project(root)[0]
    files = copies.read_record(project)
    source = root / "literature" / "sources" / name
    data = source.read_bytes() if source.exists() else b""
    files[name] = {"key": key, "sha256": hashlib.sha256(data).hexdigest(),
                   "bytes": len(data), "from": "author", "copied": "2026-11-05"}  # fmt: skip
    copies.write_record(project, files)


def keep_away(root: Path, name: str, key: str, *, ignore: bool = True,
              repository: bool = True) -> None:  # fmt: skip
    """Record literature/sources/<name> as a copy of `key`, then delete it: kept out of git
    where `repository` and `ignore`."""
    if repository:
        a_repository(root, ignore=ignore)
    record(root, name, key)
    (root / "literature" / "sources" / name).unlink(missing_ok=True)
