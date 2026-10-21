"""The lookup record: one file per cited reference, committed, read offline.

`literature/lookups/<citekey>.yaml` holds what the registries said of the reference's DOI
and PMID on the day they were asked, and the digest of the `references.bib` entry that was
looked up. It is the cache: `check` reads it and never asks anyone, and `lookup` asks again
only for an entry with no record, an entry changed since, or an answer that did not come.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project

SCHEMA = "manuscript-guard/lookup/2"
FOLDER = "lookups"
_SAFE = re.compile(r"[A-Za-z0-9._-]")


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def entry_digest(fields: dict[str, str]) -> str:
    """The SHA-256 of a .bib entry's fields as the file writes them, in a fixed order, so
    that `sync-bib` writing the same fields in another order changes nothing."""
    return _digest(fields)


#: What `answers_sha256` digests: everything in a record but the digest itself.
ANSWERED = ("schema", "citekey", "looked_up_on", "entry_sha256", "identifiers", "sources")


def answers_digest(record: dict[str, Any]) -> str:
    """The SHA-256 of what a record says. Kept in the record, so it catches an edit made
    without care, and not one made by someone who runs the digest again (DESIGN.md, Known
    gaps)."""
    return _digest({key: record.get(key) for key in ANSWERED})


def file_name(citekey: str) -> str:
    """A citekey as a file name on every system: each character that is not a letter, a
    digit, `.`, `_` or `-` is written as `%` and its code point in hex (`:` is `%3a`)."""
    return "".join(c if _SAFE.fullmatch(c) else f"%{ord(c):x}" for c in citekey) + ".yaml"


def folder(project: Project) -> Path:
    return project.path("literature") / FOLDER


def record_path(project: Project, citekey: str) -> Path:
    return folder(project) / file_name(citekey)


def read_record(project: Project, citekey: str) -> dict[str, Any] | None:
    """The record for a citekey, or None where there is none or it cannot be read as one."""
    path = record_path(project, citekey)
    try:
        document = read_structured(path)
    except ContractError:
        return None
    if not isinstance(document, dict) or not validate(document, "lookup", path).ok:
        return None
    return document if document.get("citekey") == citekey else None


def write_record(project: Project, record: dict[str, Any]) -> Path:
    """Write one record, after holding it to its schema: a record the gate would refuse is
    never written."""
    path = record_path(project, record["citekey"])
    report = validate(record, "lookup", path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record for @{record['citekey']} is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    # Bytes, so the file has the same line endings on every system.
    path.write_bytes(text.encode("utf-8"))
    return path


__all__ = [
    "ANSWERED",
    "FOLDER",
    "SCHEMA",
    "answers_digest",
    "entry_digest",
    "file_name",
    "folder",
    "read_record",
    "record_path",
    "write_record",
]
