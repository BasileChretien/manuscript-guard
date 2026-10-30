"""A package given to `audit --package`, opened without trusting it: a .zip is read member by
member before anything is written, and refused whole where one member could land outside the
folder it is unpacked into, or the archive is past the limits; a folder is read where it is,
and refused where it holds a link, which could lead outside it.

What a .zip is refused for: a member named from the root (`/x`, `C:x`, `\\x`), a name with
`..` among its parts, a backslash or a colon in a name (Windows reads either as a path of its
own), a name no Windows file system holds (a control character, one of `<>"|?*`, a part ending
in a stop or a space, an empty or a `.` part), a part Windows keeps for a device (`CON`, `NUL`,
`COM1`, `COM¹` and their like, spaces before the stop as well), a name that is both a file and
a folder of other members, a symbolic link, an encrypted member, two members whose names differ
only in case, more than `MAX_MEMBERS` members, or more than `MAX_BYTES` once unpacked. A member
that cannot be written all the same refuses the package with a sentence. The members are then
written into a new temporary folder, each no larger than the archive says it is, and the
folder is removed when the audit ends. Nothing in the package is run.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

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
_CHUNK = 1 << 20


class Refused(Exception):
    """The package is not read: the message says why. Nothing was unpacked."""


def _unsafe(name: str) -> str:
    """Why a member's name is refused, or ""."""
    if not name or name.startswith(("/", "\\")):
        return "is named from the root"
    if "\\" in name or ":" in name or "\0" in name:
        return "has a backslash, a colon or a NUL in its name, which Windows reads otherwise"
    if any(char in _NOT_IN_A_NAME or ord(char) < 32 for char in name):
        return ("has a control character or one of < > \" | ? * in its name, which Windows "
                "cannot hold")  # fmt: skip
    parts = name.removesuffix("/").split("/")
    if ".." in parts:
        return "has .. among its parts, which leads out of the folder"
    if any(part in ("", ".") for part in parts):
        return "has an empty part or a . part, which names another member's place"
    if any(part.endswith((".", " ")) for part in parts):
        return "has a part ending in a stop or a space, which Windows drops"
    if any(part.split(".")[0].rstrip(" ").upper() in _DEVICES for part in parts):
        return "has a part Windows keeps for a device"
    return ""


def members(archive: Path) -> list[zipfile.ZipInfo]:
    """The members of a .zip, each checked; `Refused` where one, or the whole, is not safe
    to unpack."""
    try:
        with zipfile.ZipFile(archive) as opened:
            infos = opened.infolist()
    except (zipfile.BadZipFile, OSError, EOFError, ValueError) as exc:
        raise Refused(f"{archive.name} is not a .zip the audit can read ({exc})") from None
    if len(infos) > MAX_MEMBERS:
        raise Refused(f"{archive.name} holds {len(infos)} members, more than the "
                      f"{MAX_MEMBERS} the audit unpacks")  # fmt: skip
    seen: dict[str, str] = {}
    folders: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        why = _unsafe(name)
        if why:
            raise Refused(f"{archive.name}: the member {name!r} {why}; nothing was unpacked")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise Refused(f"{archive.name}: the member {name!r} is a link; nothing was unpacked")
        if info.flag_bits & 0x1:
            raise Refused(f"{archive.name}: the member {name!r} is encrypted; nothing was "
                          "unpacked")  # fmt: skip
        key = name.rstrip("/").casefold()
        if key in seen:
            raise Refused(f"{archive.name}: the members {seen[key]!r} and {name!r} are one name "
                          "on a system that ignores case; nothing was unpacked")  # fmt: skip
        seen[key] = name
        parts = key.split("/")
        folders.update("/".join(parts[:end]) for end in range(1, len(parts)))
        total += info.file_size
    both = sorted(key for key, name in seen.items() if not name.endswith("/") and key in folders)
    if both:
        raise Refused(f"{archive.name}: the member {seen[both[0]]!r} is both a file and a folder "
                      "of other members; nothing was unpacked")  # fmt: skip
    if total > MAX_BYTES:
        raise Refused(f"{archive.name} unpacks to {total} bytes, more than the {MAX_BYTES} the "
                      "audit unpacks")  # fmt: skip
    return infos


def _unpack(archive: Path, into: Path) -> None:
    infos = members(archive)
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


__all__ = ["MANIFEST", "MAX_BYTES", "MAX_MEMBERS", "Refused", "members", "opened", "root_of"]
