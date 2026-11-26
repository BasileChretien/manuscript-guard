"""A package given to `audit --package`, opened without trusting it: a .zip is read member by
member before anything is written, and refused whole where one member could land outside the
folder it is unpacked into, or the archive is past the limits; a folder is read where it is,
and refused where it holds a link, which could lead outside it.

What a .zip is refused for, on every system: a member named from the root or a drive (`/x`,
`C:x`, `\\x`), a name with `..`, an empty or a `.` part, a backslash, a NUL or a line break
(any `str.splitlines()` ends a line at, so that no name splits a line of SHA256SUMS), a name that is
both a file and a folder of other members, a symbolic link, an encrypted member, two members
whose names differ only in case, more than `MAX_MEMBERS` members, or more than `MAX_BYTES`
once unpacked. On Windows also a name its file system cannot hold: a colon, a control
character, one of `<>"|?*`, a part ending in a stop or a space, a part kept for a device
(`CON`, `NUL`, `COM1`, `COM¹` and their like, spaces before the stop as well). A member that
cannot be written all the same, on any system, refuses the package with a sentence. The
members are written into a new temporary folder, each no larger than the archive says it is,
and the folder is removed when the audit ends. Nothing in the package is run.

A paper's project, a .zip or a .tar.gz, the audit page unpacks the same way
(`unpack_archive`) into a folder of its own, which it audits: a tar's members are held to the
same checks, and a member that is neither a file nor a folder (a link, a device) refuses it.
"""

from __future__ import annotations

import gzip
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

#: The most members a package's .zip may hold, and the most bytes they may hold unpacked.
MAX_MEMBERS = 50_000
MAX_BYTES = 16 << 30
#: The name of a package's manifest, at its top or in its one folder (`deposit/write.py`).
MANIFEST = "MANIFEST.yaml"
#: The names Windows keeps for devices, whatever follows a stop or spaces before one: as
#: Python's own check of a reserved name (`os.path.isreserved`), the superscript digits too.
_DIGITS = [str(n) for n in range(1, 10)] + [chr(0xB9), chr(0xB2), chr(0xB3)]
_DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                      *(f"COM{n}" for n in _DIGITS), *(f"LPT{n}" for n in _DIGITS)})  # fmt: skip
#: Characters no Windows file name holds; a control character neither.
_NOT_IN_A_NAME = frozenset('<>:"|?*')
#: Each character `str.splitlines()` ends a line at, which no member's name may hold, so that
#: no name can split a line of SHA256SUMS.
_LINE_BREAKS = frozenset(chr(code) for code in (10, 11, 12, 13, 0x1C, 0x1D, 0x1E, 0x85, 0x2028,
                                                0x2029))  # fmt: skip
_CHUNK = 1 << 20


class Refused(Exception):
    """The package is not read: the message says why. Nothing was unpacked."""


def _unsafe(name: str) -> str:
    """Why a member's name is refused, or "". On every system: a name from the root or a
    drive, a backslash (a separator to Windows, and to `package`'s own reading of a path on
    any system, so one name would be two paths), a NUL, `..`, an empty or a `.` part. Only on
    Windows, where the file system cannot hold them (round 2 of #487: a Linux project's
    `analysis/aux.R` packages, and was refused on Linux too): a colon, `<>"|?*`, a control
    character, a part ending in a stop or a space, and a device's name. Elsewhere a name the
    file system cannot hold refuses the package when it is written."""
    if not name or name.startswith(("/", "\\")):
        return "is named from the root"
    if PureWindowsPath(name).drive:
        return "names a Windows drive, which Windows writes outside the folder"
    if any(char in _LINE_BREAKS for char in name):
        return "holds a line break in its name"
    if "\\" in name or "\0" in name:
        return "has a backslash or a NUL in its name, which Windows reads otherwise"
    parts = name.removesuffix("/").split("/")
    if ".." in parts:
        return "has .. among its parts, which leads out of the folder"
    if any(part in ("", ".") for part in parts):
        return "has an empty part or a . part, which names another member's place"
    return _windows_cannot_hold(parts) if windows() else ""


def windows() -> bool:
    """Whether the package is unpacked on Windows, whose file system holds fewer names."""
    return os.name == "nt"


def _windows_cannot_hold(parts: list[str]) -> str:
    if any(char in _NOT_IN_A_NAME or ord(char) < 32 for part in parts for char in part):
        return ("has a colon, a control character or one of < > \" | ? * in its name, which "
                "Windows cannot hold")  # fmt: skip
    if any(part.endswith((".", " ")) for part in parts):
        return "has a part ending in a stop or a space, which Windows drops"
    if any(part.split(".")[0].rstrip(" ").upper() in _DEVICES for part in parts):
        return "has a part Windows keeps for a device"
    return ""


def _checked(shown: str, entries: list[tuple[str, int, object]],
             refused: Callable[[object], str], max_members: int | None,
             max_bytes: int | None) -> None:  # fmt: skip
    """`Refused` where one of an archive's members, each its name (a folder's ending in
    "/"), its size and what the archive keeps of it, or the whole, is not safe to unpack:
    a name `_unsafe` refuses or one `refused` says why of, two names in one case, a name both
    a file and a folder, more members or bytes than the limits (`MAX_MEMBERS`, `MAX_BYTES`
    where none is given)."""
    max_members = MAX_MEMBERS if max_members is None else max_members
    max_bytes = MAX_BYTES if max_bytes is None else max_bytes
    if len(entries) > max_members:
        raise Refused(f"{shown} holds {len(entries)} members, more than the "
                      f"{max_members} the audit unpacks")  # fmt: skip
    seen: dict[str, str] = {}
    folders: set[str] = set()
    total = 0
    for name, size, kept in entries:
        why = _unsafe(name) or refused(kept)
        if why:
            raise Refused(f"{shown}: the member {name!r} {why}; nothing was unpacked")
        key = name.rstrip("/").casefold()
        if key in seen:
            raise Refused(f"{shown}: the members {seen[key]!r} and {name!r} are one name "
                          "on a system that ignores case; nothing was unpacked")  # fmt: skip
        seen[key] = name
        parts = key.split("/")
        folders.update("/".join(parts[:end]) for end in range(1, len(parts)))
        total += size
    both = sorted(key for key, name in seen.items() if not name.endswith("/") and key in folders)
    if both:
        raise Refused(f"{shown}: the member {seen[both[0]]!r} is both a file and a folder "
                      "of other members; nothing was unpacked")  # fmt: skip
    if total > max_bytes:
        raise Refused(f"{shown} unpacks to {total} bytes, more than the {max_bytes} the "
                      "audit unpacks")  # fmt: skip


def _zip_refused(info: zipfile.ZipInfo) -> str:
    if stat.S_ISLNK(info.external_attr >> 16):
        return "is a link"
    if info.flag_bits & 0x1:
        return "is encrypted"
    return ""


def members(archive: Path, *, max_members: int | None = None,
            max_bytes: int | None = None) -> list[zipfile.ZipInfo]:  # fmt: skip
    """The members of a .zip, each checked; `Refused` where one, or the whole, is not safe
    to unpack."""
    try:
        with zipfile.ZipFile(archive) as opened:
            infos = opened.infolist()
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as exc:
        raise Refused(f"{archive.name} is not a .zip the audit can read ({exc})") from None
    _checked(archive.name, [(info.filename, info.file_size, info) for info in infos],
             _zip_refused, max_members, max_bytes)  # fmt: skip
    return infos


def _unpack(archive: Path, into: Path, *, max_members: int | None = None,
            max_bytes: int | None = None) -> None:  # fmt: skip
    infos = members(archive, max_members=max_members, max_bytes=max_bytes)
    with zipfile.ZipFile(archive) as opened:
        for info in infos:
            target = into.joinpath(*PurePosixPath(info.filename).parts)
            written = 0
            try:
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with opened.open(info) as source, target.open("xb") as out:
                    for block in iter(lambda: source.read(_CHUNK), b""):  # noqa: B023
                        written += len(block)
                        if written > info.file_size:
                            raise Refused(f"{archive.name}: the member {info.filename!r} is "
                                          "larger than the archive says")  # fmt: skip
                        out.write(block)
            except (zipfile.BadZipFile, EOFError, ValueError, NotImplementedError) as exc:
                raise Refused(f"{archive.name}: the member {info.filename!r} cannot be read "
                              f"({exc})") from None  # fmt: skip
            except OSError as exc:
                raise Refused(f"{archive.name}: the member {info.filename!r} cannot be written "
                              f"here ({exc.strerror or exc}); nothing in it is read") from None


#: What an archive of a paper's project is named: a .zip, as Overleaf downloads one, or a
#: .tar.gz, as arXiv gives a paper's source. The audit page unpacks one into a folder of its
#: own and audits the folder (`unpack_archive`, docs/audit-page.md).
ARCHIVES = (".zip", ".tar.gz", ".tgz")


def archive_stem(name: str) -> str:
    """The archive's name without its suffix, the folder it is unpacked into: "project" of
    "project.zip" and of "project.tar.gz"; "" for a name that is no archive's."""
    lowered = name.lower()
    for suffix in ARCHIVES:
        if lowered.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return ""


def _tar_refused(info: tarfile.TarInfo) -> str:
    if info.issym() or info.islnk():
        return "is a link"
    if not (info.isreg() or info.isdir()):
        return "is neither a file nor a folder"
    return ""


def _tar_entries(infos: list[tarfile.TarInfo]) -> list[tuple[str, int, tarfile.TarInfo]]:
    """Each member of a tar as `_checked` takes it: its name without the "./" a tar made of
    a folder's contents puts before each, a folder's ending in "/", and the folder "."
    itself left out, which is the folder it is unpacked into."""
    entries = []
    for info in infos:
        name = info.name
        while name.startswith("./"):
            name = name[2:]
        if info.isdir():
            if name.rstrip("/") in ("", "."):
                continue
            name = name.rstrip("/") + "/"
        entries.append((name, info.size if info.isreg() else 0, info))
    return entries


def _copied(source, target: Path, size: int, shown: str, name: str) -> None:
    """A member's bytes written to `target`, which must not be there, and no more than the
    archive says it holds."""
    written = 0
    with source, target.open("xb") as out:
        for block in iter(lambda: source.read(_CHUNK), b""):  # noqa: B023
            written += len(block)
            if written > size:
                raise Refused(f"{shown}: the member {name!r} is larger than the archive says")
            out.write(block)


def _untar(archive: Path, into: Path, max_members: int | None, max_bytes: int | None) -> None:
    """A .tar.gz unpacked into `into`, every member checked before any is written; one
    gzipped file that is no tar, as arXiv gives a paper of one file, written as its own
    `.tex`."""
    try:
        opened = tarfile.open(archive, "r:gz")  # noqa: SIM115 - closed below
    except tarfile.ReadError:
        _ungzip(archive, into, MAX_BYTES if max_bytes is None else max_bytes)
        return
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        raise Refused(f"{archive.name} is not a .tar.gz the audit can read ({exc})") from None
    with opened:
        try:
            entries = _tar_entries(opened.getmembers())
        except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
            raise Refused(f"{archive.name} is not a .tar.gz the audit can read ({exc})") from None
        _checked(archive.name, entries, _tar_refused, max_members, max_bytes)
        for name, size, info in entries:
            target = into.joinpath(*PurePosixPath(name).parts)
            try:
                if info.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                _copied(opened.extractfile(info), target, size, archive.name, name)
            except (tarfile.TarError, EOFError, zlib.error) as exc:
                raise Refused(f"{archive.name}: the member {name!r} cannot be read "
                              f"({exc})") from None  # fmt: skip
            except OSError as exc:
                raise Refused(f"{archive.name}: the member {name!r} cannot be written here "
                              f"({exc.strerror or exc}); nothing in it is read") from None


def _ungzip(archive: Path, into: Path, max_bytes: int) -> None:
    """One gzipped file, written as `<the archive's stem>.tex`, and no more of it than
    `max_bytes`."""
    name = f"{archive_stem(archive.name)}.tex"
    why = _unsafe(name)
    if why:
        raise Refused(f"{archive.name}: the file it holds would be named {name!r}, which {why}")
    written = 0
    try:
        with gzip.open(archive) as source, (into / name).open("xb") as out:
            for block in iter(lambda: source.read(_CHUNK), b""):  # noqa: B023
                written += len(block)
                if written > max_bytes:
                    raise Refused(f"{archive.name} unpacks to more than the {max_bytes} bytes "
                                  "the audit unpacks")  # fmt: skip
                out.write(block)
    except (OSError, EOFError, zlib.error) as exc:
        raise Refused(f"{archive.name} is not a .tar.gz the audit can read ({exc})") from None


def unpack_archive(archive: Path, into: Path, *, max_members: int | None = None,
                   max_bytes: int | None = None) -> None:  # fmt: skip
    """The .zip or .tar.gz `archive` of a paper's project unpacked into the new folder
    `into`, with the checks a package's .zip is held to (`members`), and in a tar no member
    but a file or a folder; `Refused`, and the folder removed, where it cannot be."""
    if into.exists():
        raise Refused(f"{archive.name}: the folder {into.name} is there already")
    into.mkdir(parents=True)
    try:
        if archive.name.lower().endswith(".zip"):
            _unpack(archive, into, max_members=max_members, max_bytes=max_bytes)
        else:
            _untar(archive, into, max_members, max_bytes)
    except BaseException:
        shutil.rmtree(into, ignore_errors=True)
        raise


def _links(folder: Path) -> list[str]:
    found = []
    # A Windows junction is no link to `islink`; Python 3.12 can tell one.
    junction = getattr(os.path, "isjunction", lambda _path: False)
    for top, dirs, files in os.walk(folder, followlinks=False):
        for name in [*dirs, *files]:
            if os.path.islink(os.path.join(top, name)) or junction(os.path.join(top, name)):
                found.append(Path(top, name).relative_to(folder).as_posix())
    return found


def root_of(base: Path, shown: str) -> Path:
    """Where the package's manifest is: at the top of `base`, or in its one folder, as
    `package` writes its .zip."""
    if (base / MANIFEST).is_file():
        return base
    inside = [child for child in base.iterdir()] if base.is_dir() else []
    if len(inside) == 1 and inside[0].is_dir() and (inside[0] / MANIFEST).is_file():
        return inside[0]
    raise Refused(f"{shown} has no {MANIFEST} at its top, nor in a single folder there: it is "
                  "not a package `manuscript-guard package` wrote")  # fmt: skip


@contextmanager
def opened(given: Path) -> Iterator[Path]:
    """The package's root folder, for as long as the audit reads it: a folder where it is, a
    .zip unpacked into a temporary folder removed afterwards. `Refused` where it cannot be."""
    if given.is_dir():
        links = _links(given)
        if links:
            raise Refused(f"{given.name} holds a link, which could lead out of the package: "
                          f"{links[0]}")  # fmt: skip
        yield root_of(given, given.name)
        return
    if given.suffix.lower() != ".zip":
        raise Refused(f"{given.name}: --package reads a .zip or a folder")
    folder = Path(tempfile.mkdtemp(prefix="mg-package-"))
    try:
        _unpack(given, folder)
        yield root_of(folder, given.name)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


__all__ = ["ARCHIVES", "MANIFEST", "MAX_BYTES", "MAX_MEMBERS", "Refused", "archive_stem",
           "members", "opened", "root_of", "unpack_archive"]  # fmt: skip
