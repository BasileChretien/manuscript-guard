"""The journal shortlist and what the registries said of each journal on it.

`journals/shortlist.yaml` is written with the author, by the journal-profile skill: the
criteria the author states first, the journals considered with a source and a date for each
claim made of them, the ranking, the decision and who made it, and what came of earlier
choices. `journals/lookups/<issn>.yaml` is what `manuscript-guard lookup --journals` heard
from the NLM Catalog (is the journal currently indexed for MEDLINE) and from DOAJ (is it
listed) for one ISSN, on one day. G4 reads both offline; nothing here opens a connection.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project

SHORTLIST = ("journals", "shortlist.yaml")
LOOKUPS = ("journals", "lookups")
SCHEMA = "manuscript-guard/journal-lookup/1"
#: What `answers_sha256` digests: everything in a record but the digest itself.
ANSWERED = ("schema", "issn", "looked_up_on", "sources")


def shortlist_path(project: Project) -> Path:
    return project.root.joinpath(*SHORTLIST)


def issns(shortlist: dict[str, Any]) -> list[str]:
    """Every ISSN the shortlist gives, in its order, once."""
    seen: dict[str, None] = {}
    for candidate in shortlist.get("candidates") or []:
        for issn in candidate.get("issn") or []:
            seen.setdefault(issn.upper(), None)
    return list(seen)


def answers_digest(record: dict[str, Any]) -> str:
    """The SHA-256 of what a record says, kept in it: it catches an edit made without care,
    not one made by someone who runs the digest again."""
    value = {key: record.get(key) for key in ANSWERED}
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_path(project: Project, issn: str) -> Path:
    return project.root.joinpath(*LOOKUPS) / f"{issn.upper()}.yaml"


def read_record(project: Project, issn: str) -> dict[str, Any] | None:
    """The record for an ISSN, or None where there is none, it is not one, or what it says
    is not what its digest says it was."""
    path = record_path(project, issn)
    try:
        document = read_structured(path)
    except ContractError:
        return None
    if not isinstance(document, dict) or not validate(document, "journal-lookup", path).ok:
        return None
    if document.get("issn") != issn.upper():
        return None
    return document if document["answers_sha256"] == answers_digest(document) else None


def write_record(project: Project, record: dict[str, Any]) -> Path:
    """Write one record, after holding it to its schema."""
    path = record_path(project, record["issn"])
    report = validate(record, "journal-lookup", path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record for ISSN {record['issn']} is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


__all__ = [
    "ANSWERED",
    "LOOKUPS",
    "SCHEMA",
    "SHORTLIST",
    "answers_digest",
    "issns",
    "read_record",
    "record_path",
    "shortlist_path",
    "write_record",
]
