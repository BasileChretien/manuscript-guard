"""The journal's citation style, stored in the project: what `manuscript-guard style` wrote,
read offline by the build and by G4.

A journal profile names its style as the CSL style repository and Zotero name it
(`references: {csl: the-lancet}`). A live build hands that name to Zotero; an offline build,
which is what CI and co-authors get, formatted in pandoc's default style unless `--csl` was
passed by hand. `style` fetches the file once and keeps it here, under
`profiles/journals/styles/`:

* `<name>.csl`, the style as the repository serves it;
* for a dependent style, which only names the style it formats like
  (`<link rel="independent-parent">`), that parent too, as `<parent>.csl` beside it: pandoc
  looks for it by that name before it would fetch it, so an offline build never does;
* `<name>.yaml`, the record: where each file came from, its digest, the day, the licence it
  names, and the style's citation format.

The files are the repository's, under the licence they name (CC BY-SA 3.0), and live in the
author's project, never in this package. Nothing here opens a connection.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.safexml import UnsafeDocument, parse_xml

SCHEMA = "manuscript-guard/csl-style/1"
SCHEMA_NAME = "csl-style"
FOLDER = ("profiles", "journals", "styles")
CSL = "{http://purl.org/net/xbiblio/csl}"
#: Where Zotero, and a dependent style's link to its parent, name a style of the repository.
ZOTERO_STYLES = ("http://www.zotero.org/styles/", "https://www.zotero.org/styles/")
#: A style's name in the repository: lower case, digits and single hyphens or dots.
_NAME = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
#: Citation formats, from the CSL specification, that print a number in the text.
NUMERIC = "numeric"
FORMATS = ("author-date", "author", "numeric", "label", "note")


class NotAStyle(Exception):
    """A file that is no CSL style, or not the kind it was asked for. The message is ours."""


@dataclass(frozen=True)
class Parsed:
    """What a style file says of itself."""

    title: str
    parent: str | None  # the independent parent's name, for a dependent style
    citation_format: str | None
    licence: str | None


@dataclass(frozen=True)
class Stored:
    """A style the project holds and the build may use: its file, and its parent's."""

    name: str
    path: Path
    parent: Path | None
    citation_format: str | None


def folder(project: Project) -> Path:
    return project.root.joinpath(*FOLDER)


def style_name(named: str) -> str | None:
    """The repository's name for what a profile's `references.csl` says: the name itself, or
    the name at the end of a zotero.org/styles URL. None for anything else, which `style`
    cannot fetch: a name with a slash, `..` or a capital, or another site's URL."""
    named = named.strip()
    for prefix in ZOTERO_STYLES:
        if named.startswith(prefix):
            named = named[len(prefix) :]
            break
    return named if _NAME.fullmatch(named) else None


def profile_style(document: dict) -> str:
    """What the profile's `references.csl` says, stripped; empty where it names none."""
    references = document.get("references") if isinstance(document, dict) else None
    return str((references or {}).get("csl") or "").strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse(data: bytes, what: str) -> Parsed:
    """Read a style's own description of itself. Raises NotAStyle for a file that is not a
    CSL style, or that carries a DTD (`safexml`)."""
    try:
        root = parse_xml(data, what=what)
    except UnsafeDocument as exc:
        raise NotAStyle(str(exc)) from None
    if root.tag != f"{CSL}style":
        raise NotAStyle(f"{what} is not a CSL style: its root element is not <style>")
    info = root.find(f"{CSL}info")
    if info is None:
        raise NotAStyle(f"{what} is not a CSL style: it has no <info>")
    title = (info.findtext(f"{CSL}title") or "").strip()
    parent = None
    for link in info.findall(f"{CSL}link"):
        if link.get("rel") == "independent-parent":
            # By the last part of the link, as pandoc looks for the parent on its resource
            # path before it would fetch it: `.../styles/the-lancet` is `the-lancet.csl`.
            parent = (link.get("href") or "").rstrip("/").rpartition("/")[2]
            if not _NAME.fullmatch(parent):
                raise NotAStyle(f"{what} is a dependent style whose parent link names no style")
    formats = [c.get("citation-format") for c in info.findall(f"{CSL}category")]
    found = next((f for f in formats if f), None)
    rights = info.find(f"{CSL}rights")
    licence = rights.get("license") if rights is not None else None
    if parent is None and root.find(f"{CSL}citation") is None:
        raise NotAStyle(f"{what} is an independent style with no <citation>")
    return Parsed(title=title, parent=parent, citation_format=found, licence=licence)


def record_path(project: Project, name: str) -> Path:
    return folder(project) / f"{name}.yaml"


def read_record(project: Project, name: str) -> dict[str, Any] | None:
    """The record of a stored style, or None where there is none or it is not one."""
    path = record_path(project, name)
    try:
        document = read_structured(path)
    except ContractError:
        return None
    if not isinstance(document, dict) or not validate(document, SCHEMA_NAME, path).ok:
        return None
    return document if document.get("style") == name else None


def write_record(project: Project, record: dict[str, Any]) -> Path:
    """Write the record, after holding it to its schema."""
    path = record_path(project, record["style"])
    report = validate(record, SCHEMA_NAME, path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record of the style {record['style']} is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


def changed(project: Project, record: dict[str, Any]) -> list[str]:
    """The stored files that are missing or not what the record says was fetched, by name."""
    wrong = []
    entries = [record] + ([record["parent"]] if record.get("parent") else [])
    for entry in entries:
        path = folder(project) / entry["file"]
        try:
            data = path.read_bytes()
        except OSError:
            wrong.append(f"{entry['file']} (missing)")
            continue
        if digest(data) != entry["sha256"]:
            wrong.append(entry["file"])
    return wrong


def stored(project: Project, named: str) -> Stored | None:
    """The style a profile names, where the project holds it as fetched: the file the build
    passes to pandoc, and its parent beside it. None where it is not stored, or a file has
    changed since."""
    name = style_name(named)
    record = read_record(project, name) if name else None
    if record is None or changed(project, record):
        return None
    parent = record.get("parent")
    return Stored(
        name=name,
        path=folder(project) / record["file"],
        parent=folder(project) / parent["file"] if parent else None,
        citation_format=record.get("citation_format"),
    )


__all__ = [
    "FORMATS",
    "NUMERIC",
    "SCHEMA",
    "NotAStyle",
    "Parsed",
    "Stored",
    "changed",
    "digest",
    "folder",
    "parse",
    "profile_style",
    "read_record",
    "record_path",
    "stored",
    "style_name",
    "write_record",
]
