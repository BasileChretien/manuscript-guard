"""`manuscript-guard sync-sources`: each cited work's own copy, taken from Zotero.

A co-author asked whether a cited paper says what a sentence says needs the paper, and G7
needs its text to hold a quote to it. The author mostly has both already: Zotero keeps the
PDF or the saved page of the items it holds, saved from the author's browser by the Zotero
Connector or fetched by "Find Available PDF", from an open copy or through the library's
proxy. So this copies, for each work the manuscript cites, what Zotero holds into
`literature/sources/<key>.<suffix>`, the name G7 reads, and lists the works it could not.

What it takes, for each attachment Better BibTeX lists for the key:

* the file, where it is on this computer and is a PDF, a saved page or plain text;
* else Zotero's text of it, `.zotero-ft-cache` in the attachment's folder, which Zotero keeps
  for a file it indexed, whether the file is not downloaded here or is of another kind (an
  EPUB), filed as `<key>.txt`;
* else nothing, and the reason is said.

The other kinds G7 reads, a table or a citation file, are not taken: attached to an item in
Zotero they are a supplement's data or the item's own reference, not the work's text. Two
different files that would take one name are neither of them copied: which is the article and
which the supplement is not a thing to guess. A file under `literature/sources/` that this
command did not write, or that was changed since it wrote it, is never written over; one it
wrote, and that is as it wrote it, is replaced when Zotero's copy has changed. A file found in
place with Zotero's bytes is left out of the record, so it stays the author's (round 1 of
#361). Nothing is deleted. What it wrote is recorded in `literature/sources.yaml`: each file's
name, the work, the SHA-256 and size of what was written, and whether it is the file or
Zotero's text. The record holds no path on anyone's computer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.literature.sources import (
    HTML_SUFFIXES,
    PDF_SUFFIXES,
    filed_name,
    stored_files,
)
from manuscript_guard.zotero import Attachment, client

SCHEMA = "manuscript-guard/sources/1"
#: Under `literature/`, beside `sources/` rather than in it, so that it can be kept in git
#: where the sources are not.
RECORD = "sources.yaml"
FOLDER = "sources"
#: The text Zotero keeps of a file it indexed, in the attachment's own folder.
ZOTERO_TEXT = ".zotero-ft-cache"
#: The kinds taken as the work's own text: G7 reads more (`TEXT_SUFFIXES`), but a table or a
#: citation file attached in Zotero is not the work (round 1 of #361).
TAKEN = frozenset(PDF_SUFFIXES | HTML_SUFFIXES | {".txt"})
#: The kinds on this computer whose Zotero text is taken in their place: a book's text, and
#: not a table's or a citation file's, which Zotero may index too (round 2 of #361).
TEXT_IN_PLACE_OF = frozenset({".epub"})

COPIED = "copied"
UPDATED = "updated"
UNCHANGED = "unchanged"
KEPT = "kept"
STORED = "stored"
NO_COPY = "no copy"

HEADER = (
    "# Written by `manuscript-guard sync-sources`: the files it copied from Zotero into\n"
    "# literature/sources/. A file listed here is one the command may replace when Zotero's\n"
    "# copy changes, and only while it is as the command wrote it. Not edited by hand.\n"
)


class NothingToCopy(Exception):
    """The manuscript cites nothing."""


@dataclass(frozen=True)
class Candidate:
    """A file Zotero holds for a work, and the name it is filed under."""

    name: str
    origin: Path
    kind: str
    attachment: str | None
    sha256: str
    size: int
    #: What the copy is, as the command says it: "from Zotero", or which file Zotero's text is of.
    about: str = "from Zotero"


@dataclass(frozen=True)
class Outcome:
    """What became of one file of a cited work, or of the work where nothing was copied."""

    key: str
    status: str
    said: str
    name: str | None = None


def record_path(project: Project) -> Path:
    return project.path("literature") / RECORD


def read_record(project: Project) -> dict[str, dict[str, Any]]:
    """The files the command wrote, by name. A record it cannot use stops it: without it, it
    cannot tell its own files from the author's."""
    path = record_path(project)
    document = read_structured(path)
    if document is None:
        return {}
    report = validate(document, "sources", path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(
            f"{path}: not a record sync-sources can use ({problems}). Put it right, or delete "
            "it: the files it listed are then treated as put there by hand, and kept"
        )
    return dict(document["files"])


def write_record(project: Project, files: dict[str, dict[str, Any]]) -> Path:
    path = record_path(project)
    document = {"schema": SCHEMA, "files": {name: files[name] for name in sorted(files)}}
    report = validate(document, "sources", path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record of copied sources is not valid: {problems}")
    text = HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


def digest(path: Path) -> tuple[str, int]:
    """The SHA-256 of a file's bytes, and how many there are."""
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
            size += len(block)
    return sha.hexdigest(), size


def candidates(key: str, held: list[Attachment]) -> tuple[list[Candidate], list[str]]:
    """The files to copy for a work, and why each attachment that gave none gave none."""
    found: dict[str, dict[str, Candidate]] = {}
    why: list[str] = []
    for one in held:
        if one.path is None:
            why.append("only a link, or an attachment with no file")
            continue
        path = Path(one.path)
        suffix = path.suffix.lower()
        here = path.is_file()
        text = path.parent / ZOTERO_TEXT
        about = "from Zotero"
        if here and suffix in TAKEN:
            origin, kind, name = path, "zotero", filed_name(key, suffix)
        elif (not here or suffix in TEXT_IN_PLACE_OF) and text.is_file():
            origin, kind, name = text, "zotero-text", filed_name(key, ".txt")
            about = (
                f"Zotero's text of a {suffix} file"
                if here
                else "Zotero's text of a file that is not on this computer"
            )
        elif here:
            why.append(f"a {suffix or 'suffixless'} file, not taken as the work's text")
            continue
        else:
            why.append(f"its {suffix} file is not on this computer, nor Zotero's text of it")
            continue
        try:
            sha, size = digest(origin)
        except OSError as exc:
            why.append(f"its file could not be read ({exc.strerror or exc})")
            continue
        found.setdefault(name, {}).setdefault(
            sha, Candidate(name, origin, kind, one.item, sha, size, about)
        )
    chosen = []
    for name, versions in found.items():
        if len(versions) == 1:
            chosen.extend(versions.values())
        else:
            why.append(
                f"{len(versions)} {Path(name).suffix} files that differ, and which is the "
                f"work's is not guessed: save it as literature/sources/{name}"
            )
    return chosen, why


def _decide(dest: Path, candidate: Candidate, ours: dict[str, Any] | None) -> str:
    if not dest.exists():
        return COPIED
    if not dest.is_file():
        return KEPT
    current, _ = digest(dest)
    if current == candidate.sha256:
        return UNCHANGED
    if ours is not None and ours.get("sha256") == current:
        return UPDATED
    return KEPT


def _write(origin: Path, dest: Path) -> tuple[str, int]:
    """Copy through a file beside the destination, so that a copy cut short leaves the old
    file whole; returns the digest of what was written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=dest.parent, prefix=".sync-sources-")
    os.close(handle)
    try:
        shutil.copyfile(origin, temporary)
        written = digest(Path(temporary))
        os.replace(temporary, dest)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return written


def _entry(key: str, candidate: Candidate, written: tuple[str, int], today: date) -> dict:
    entry: dict[str, Any] = {"key": key, "sha256": written[0], "bytes": written[1]}
    entry["from"] = candidate.kind
    if candidate.attachment:
        entry["attachment"] = candidate.attachment
    entry["copied"] = today.isoformat()
    return entry


def _size(size: int) -> str:
    for unit, step in (("MB", 1 << 20), ("KB", 1 << 10)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{size} bytes"


def _said(status: str, candidate: Candidate, dry_run: bool) -> str:
    where = f"literature/sources/{candidate.name}"
    what = candidate.about
    if status == COPIED:
        return f"{'would copy' if dry_run else 'copied'} {where} ({what}, {_size(candidate.size)})"
    if status == UPDATED:
        verb = "would replace" if dry_run else "replaced"
        return f"{verb} {where} with Zotero's newer copy ({what}, {_size(candidate.size)})"
    if status == UNCHANGED:
        return f"{where} is Zotero's copy already"
    return (
        f"{where} is not the file Zotero holds, and is not as sync-sources wrote it: left as "
        "it is. Move it away to take Zotero's."
    )


def _without_copy(folder: Path, key: str, why: list[str]) -> Outcome:
    reasons = "; ".join(why) or "no attachment"
    stored = [p.name for p in stored_files(folder, key)]
    if stored:
        return Outcome(key, STORED, f"nothing to copy from Zotero ({reasons}); "
                       f"{', '.join(stored)} is stored already")  # fmt: skip
    return Outcome(key, NO_COPY, f"no copy: {reasons}")


def sync(
    project: Project,
    *,
    dry_run: bool = False,
    today: date | None = None,
    fetch: Callable[[str], list[Attachment] | None] | None = None,
) -> list[Outcome]:
    """Copy each cited work's files from Zotero, record them, and say what became of each."""
    from manuscript_guard.lookup.run import cited_keys

    keys = cited_keys(project)
    if not keys:
        raise NothingToCopy("the manuscript cites nothing, so there is no source to copy")
    fetch = fetch or client.attachments
    folder = project.path("literature") / FOLDER
    on_disk = read_record(project)
    # An entry whose file is gone says nothing of a file saved under that name later: kept, it
    # made the author's copy the command's (round 2 of #361).
    recorded = {name: entry for name, entry in on_disk.items() if (folder / name).is_file()}
    files = dict(recorded)
    outcomes: list[Outcome] = []
    try:
        for key in keys:
            held = fetch(key)
            if held is None:
                outcomes.append(_without_copy(folder, key, ["not in Zotero"]))
                continue
            chosen, why = candidates(key, held)
            if not chosen:
                outcomes.append(_without_copy(folder, key, why))
                continue
            for candidate in chosen:
                outcomes.append(
                    _file(key, candidate, folder, recorded, files, dry_run, today or date.today())
                )
    finally:
        # Zotero stopping halfway leaves the files copied so far recorded as the command's.
        if not dry_run and files != on_disk:
            write_record(project, files)
    return outcomes


def _file(
    key: str,
    candidate: Candidate,
    folder: Path,
    recorded: dict[str, dict[str, Any]],
    files: dict[str, dict[str, Any]],
    dry_run: bool,
    today: date,
) -> Outcome:
    """Copy one file where it is due, and enter it in `files`. Only a file the command writes
    is entered: one found in place with Zotero's bytes stays the author's (round 1 of #361)."""
    dest = folder / candidate.name
    where = f"literature/sources/{candidate.name}"
    try:
        status = _decide(dest, candidate, recorded.get(candidate.name))
    except OSError as exc:
        said = f"{where} could not be read ({exc.strerror or exc}): left as it is"
        return Outcome(key, KEPT, said, candidate.name)
    if not dry_run and status in (COPIED, UPDATED):
        try:
            written = _write(candidate.origin, dest)
        except OSError as exc:
            said = f"{where} could not be written ({exc.strerror or exc}): left as it was"
            return Outcome(key, KEPT, said, candidate.name)
        files[candidate.name] = _entry(key, candidate, written, today)
    return Outcome(key, status, _said(status, candidate, dry_run), candidate.name)


def report(outcomes: list[Outcome], *, dry_run: bool = False) -> list[str]:
    """What `sync-sources` prints: a line for each file, a count, and the works with no copy."""
    lines = [f"@{one.key}: {one.said}" for one in outcomes]
    counts = Counter(one.status for one in outcomes)
    parts = [
        f"{counts[status]} {label}"
        for status, label in (
            (COPIED, "to copy" if dry_run else "copied"),
            (UPDATED, "to replace" if dry_run else "replaced"),
            (UNCHANGED, "unchanged"),
            (KEPT, "kept as they are"),
            (STORED, "works stored by hand"),
        )
        if counts[status]
    ]
    works = len({one.key for one in outcomes})
    counted = ", ".join(parts) or "nothing copied"
    lines.append(f"{works} cited work{'' if works == 1 else 's'}: {counted}")
    missing = [one for one in outcomes if one.status == NO_COPY]
    if missing:
        lines.append(f"No copy for {len(missing)} cited work{'' if len(missing) == 1 else 's'}:")
        lines.extend(f"  @{one.key}: {one.said.removeprefix('no copy: ')}" for one in missing)
        lines.append(
            "  For each: in Zotero, save it from the publisher's page with the Zotero Connector, "
            "or use Find Available PDF, or open its attachment once so that the file is "
            "downloaded here; then run this again. Or save the file as "
            "literature/sources/<key>.pdf yourself."
        )
    return lines


__all__ = [
    "COPIED",
    "KEPT",
    "NO_COPY",
    "RECORD",
    "SCHEMA",
    "STORED",
    "UNCHANGED",
    "UPDATED",
    "Candidate",
    "NothingToCopy",
    "Outcome",
    "candidates",
    "read_record",
    "report",
    "sync",
    "write_record",
]
