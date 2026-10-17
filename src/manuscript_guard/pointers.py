"""An input kept out of the repository, by Git LFS or git-annex, and the pointer left in it.

A data custodian may forbid the data leaving their hands, and G1 fails while git tracks a
restricted input (`restricted-input-tracked`). A project then keeps its data in Git LFS or
git-annex (DataLad uses it), which commit a small pointer naming the content in place of the
file. Where the content is not fetched, which is what CI and a co-author's clone have, the
pointer is what sits at the input's path, and G1 hashed the pointer: `input-changed` for an
input nobody touched, or `input-missing` for an annexed one, whose link points at nothing.

What a pointer looks like, read from each tool's own documentation (DESIGN.md, "An input
can stay out of the repository"):

* Git LFS: a text file under 1024 bytes, `version https://git-lfs.github.com/spec/v1` first,
  then `oid sha256:<hex>` and `size <bytes>`, one `key value` a line. With an extension
  (`ext-<n>-<name>` lines) the oid names the content after the extension, not the file.
* git-annex: a key, `<BACKEND>-s<bytes>[-<field>...]--<name>`. SHA256E, the default, writes
  `SHA256E-s<bytes>--<hex><.ext>`, SHA256 the hex alone; DataLad's default is MD5E. A locked
  file is a symbolic link whose target ends in the key; an unlocked one, or a link checked out
  where links are not made, is a small file holding `/annex/objects/<key>` or the link's
  target.

Nothing here decides anything: `pointer_at` says what a pointer names, and G1 compares it with
what the emitter recorded.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

#: Past this size a file is the data, not a pointer to it (Git LFS's own limit).
MOST_BYTES = 1024
LFS = "Git LFS"
ANNEX = "git-annex"
_LFS_VERSIONS = (b"version https://git-lfs.github.com/spec/v1\n",
                 b"version https://hawser.github.com/spec/v1\n")  # fmt: skip
_HEX64 = re.compile(r"[0-9a-f]{64}")
#: A git-annex key: the backend, its fields (`-s<size>`, `-m<mtime>`, `-S<n>-C<n>`), `--`,
#: then the name the backend makes. Uppercase backends, as git-annex names them.
_KEY = re.compile(r"(?P<backend>[A-Z0-9_]+)(?P<fields>(?:-[a-zA-Z]\d+)*)--(?P<name>[^/\\\s]+)")
_ANNEXED = re.compile(r"(?:^|[/\\])annex[/\\]objects[/\\](?:[^\s]*[/\\])?(?P<key>[^/\\\s]+)\s*$")


@dataclass(frozen=True)
class Pointer:
    """What a pointer at an input's path names: the tool, the SHA-256 of the content where the
    pointer gives it, the size where it gives it, and how it names the content otherwise."""

    tool: str
    sha256: str | None
    size: int | None
    named_by: str


def _lfs(data: bytes) -> Pointer | None:
    if not data.startswith(_LFS_VERSIONS):
        return None
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    fields = dict(line.split(" ", 1) for line in lines[1:] if " " in line)
    oid, size = fields.get("oid", ""), fields.get("size", "")
    method, _, digest = oid.partition(":")
    if not size.isdigit() or not digest:
        return None
    extended = any(key.startswith("ext-") for key in fields)
    sha = digest if method == "sha256" and _HEX64.fullmatch(digest) and not extended else None
    # With an extension the size and the oid are of the content after it, not of the file.
    return Pointer(LFS, sha, None if extended else int(size),
                   "an extension" if extended else method)  # fmt: skip


def annex_key(key: str) -> Pointer | None:
    """What a git-annex key names. None for a string that is no key."""
    found = _KEY.fullmatch(key)
    if found is None:
        return None
    sizes = re.findall(r"-s(\d+)", found.group("fields"))
    backend, name = found.group("backend"), found.group("name")
    hexed = name[:64]
    sha = None
    if backend == "SHA256" and _HEX64.fullmatch(name):
        sha = name
    elif backend == "SHA256E" and _HEX64.fullmatch(hexed) and (len(name) == 64 or name[64] == "."):
        sha = hexed
    # A chunked key (`-S`, `-C`) names a part of the content; its size is the part's.
    chunked = re.search(r"-[SC]\d+", found.group("fields")) is not None
    size = int(sizes[0]) if sizes and not chunked else None
    return Pointer(ANNEX, sha, size, backend)


def pointer_at(path: Path) -> Pointer | None:
    """The pointer at an input's path, or None where the path holds the content itself (or
    nothing). A link whose target exists is the content, read through the link."""
    if path.is_symlink() and not path.exists():
        target = os.readlink(path)
        return annex_key(re.split(r"[/\\]", target.rstrip("/\\"))[-1])
    try:
        if not path.is_file() or path.stat().st_size > MOST_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    found = _lfs(data)
    if found is not None:
        return found
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    annexed = _ANNEXED.search(text.strip()) if text.count("\n") <= 1 else None
    return annex_key(annexed.group("key")) if annexed else None


__all__ = ["ANNEX", "LFS", "MOST_BYTES", "Pointer", "annex_key", "pointer_at"]
