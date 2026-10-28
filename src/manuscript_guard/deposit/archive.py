"""Writing a planned bundle: `build/deposit/<target>-<bundle>/`, its SHA256SUMS, and one
archive of it that is the same bytes from the same files, wherever and whenever it is made.

The .zip is `package`'s (`write._zip`): every entry dated 1980-01-01, in order, as from a
Unix system. The .tar.gz, which arXiv reads, is made the same way: its members in order,
each a plain file dated 0 and owned by user and group 0 with no names, mode 644, in the POSIX
format, and the gzip stream dated 0 with no file name in it. A file whose digest is not the
plan's once copied stops the bundle, and the folder and the archive are removed.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project

from .plan import Entry, generated
from .write import SUMS, _place, _zip

#: Where the bundles are written, in the project's build folder.
HOME = "deposit"
#: The archive formats, by the suffix each is written with.
ZIP, TAR = ".zip", ".tar.gz"


@dataclass(frozen=True)
class Staged:
    directory: Path
    archive: Path


def sums(entries: tuple[Entry, ...]) -> Entry:
    """SHA256SUMS of every other file of the bundle, for `sha256sum -c`."""
    text = "".join(f"{entry.sha256}  {entry.path}\n"
                   for entry in sorted(entries, key=lambda e: e.path))  # fmt: skip
    return generated(SUMS, text, "the SHA-256 of every other file")


def tar_bytes(members: list[tuple[str, bytes]]) -> bytes:
    """A .tar.gz of the members, by name and bytes, at its top level and in order."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as out:
        for name, data in sorted(members):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            out.addfile(info, io.BytesIO(data))
    zipped = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=zipped, mtime=0,
                       compresslevel=9) as stream:  # fmt: skip
        stream.write(raw.getvalue())
    return zipped.getvalue()


def entry_bytes(entry: Entry) -> bytes:
    return entry.data if entry.data is not None else Path(entry.source).read_bytes()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage(project: Project, name: str, entries: tuple[Entry, ...], *,
          tarred: tuple[str, ...] | None = None) -> Staged:  # fmt: skip
    """Write the bundle into build/deposit/<name>/, replacing the one there, and its archive
    beside it: a .tar.gz of the files `tarred` names, or a .zip of the whole folder."""
    home = project.path("build") / HOME
    directory = home / name
    archive = home / f"{name}{TAR if tarred is not None else ZIP}"
    if directory.exists():
        shutil.rmtree(directory)
    for old in (home / f"{name}{ZIP}", home / f"{name}{TAR}"):
        old.unlink(missing_ok=True)
    directory.mkdir(parents=True)
    try:
        for entry in entries:
            _place(directory, entry)
        if tarred is not None:
            archive.write_bytes(tar_bytes([(name, (directory / name).read_bytes())
                                           for name in tarred]))  # fmt: skip
        else:
            _zip(directory, archive)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise
    return Staged(directory, archive)


__all__ = ["HOME", "TAR", "ZIP", "Staged", "entry_bytes", "stage", "sums", "tar_bytes"]
