"""A study's registrations, as `paper.yaml` declares them, and what each registry said.

`paper.yaml` lists the study's registrations under `registration`: the identifier, and for a
registry manuscript-guard does not ask, its name. Under each the author quotes the outcomes
the registry holds and names the planned result that reports each one.

`design/registrations/<id>.yaml` is what `manuscript-guard lookup --registrations` heard from
the registry about one identifier, on one day: the registered date, the study's own start
dates, its type, and each field of the record as the registry labels it, outcomes among them.
A registry that is not asked has a record copied by hand, which says so. G12 reads both
offline; nothing here opens a connection.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project

RECORDS = ("design", "registrations")
SCHEMA = "manuscript-guard/registration/1"
#: What `answers_sha256` digests: everything a fetched record says but the digest itself.
ANSWERED = (
    "schema", "id", "registry", "source", "asked_on", "status", "why", "title", "dates",
    "study_type", "design", "withdrawn", "sections", "first_version",
)  # fmt: skip

CLINICALTRIALS = "clinicaltrials.gov"
EU_PAS = "eu-pas"
OSF = "osf"
ISRCTN = "isrctn"
PROSPERO = "prospero"
#: The registries `lookup --registrations` asks. Any other is copied by hand.
ASKED = (CLINICALTRIALS, EU_PAS, OSF, ISRCTN)
NAMES = {
    CLINICALTRIALS: "ClinicalTrials.gov",
    EU_PAS: "the EU PAS register (HMA-EMA catalogue)",
    OSF: "OSF Registries",
    ISRCTN: "ISRCTN",
    PROSPERO: "PROSPERO",
}

# Each registry's identifier as it is written, and as it is kept. ClinicalTrials.gov pads a
# short number with zeros and answers for that study (`NCT123` is NCT00000123), so only the
# full eight digits are taken as an identifier.
_SHAPES = (
    (CLINICALTRIALS, re.compile(r"(?i)NCT(\d{8})"), "NCT{}"),
    (EU_PAS, re.compile(r"(?i)EU[ ]?PAS[ ]?(\d{3,12})"), "EUPAS{}"),
    (ISRCTN, re.compile(r"(?i)ISRCTN(\d{8})"), "ISRCTN{}"),
    (PROSPERO, re.compile(r"(?i)CRD(\d{11,12})"), "CRD{}"),
    (
        OSF,
        re.compile(
            r"(?i)(?:https?://)?(?:doi\.org/)?(?:10\.17605/)?osf\.io/([a-z0-9]{5,8})/?"
        ),
        "osf.io/{}",
    ),
)

#: What the manuscript is searched for when `paper.yaml` declares no registration: the
#: identifiers that name nothing but a registration, written as `identify` reads them. An
#: OSF link is left out, since most name a project's data or code rather than a
#: registration.
NAMED_IN_TEXT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:NCT\d{8}|ISRCTN\d{8}|EU ?PAS ?\d{3,12}|CRD\d{11,12})"
    r"(?![A-Za-z0-9])"
)


@dataclass(frozen=True)
class Outcome:
    """One registered outcome as the author quotes it: the registry's words, the role the
    registry gives it, and the planned result that reports it, if any does."""

    registered: str
    role: str
    reported_as: str | None
    index: int


@dataclass(frozen=True)
class Declared:
    """One registration `paper.yaml` lists."""

    written: str
    id: str | None
    registry: str | None
    retrospective: str | None
    outcomes: tuple[Outcome, ...]
    #: Whether `outcomes` was given at all: an empty list is an author saying none.
    outcomes_given: bool
    index: int


def identify(written: str, registry: str | None = None) -> tuple[str | None, str | None]:
    """The registry an identifier belongs to and the identifier as it is kept, or (None, None)
    where its shape names no registry and none is named."""
    text = written.strip()
    for name, shape, kept in _SHAPES:
        found = shape.fullmatch(text)
        if found:
            value = found.group(1)
            return name, kept.format(value.lower() if name == OSF else value)
    if registry and text and not any(ch in text for ch in "\\/:*?\"<>|\n"):
        return registry.strip().lower(), text
    return None, None


def _text_of(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def declared(project: Project) -> list[Declared]:
    """Every registration `paper.yaml` lists, in its order. A value of another shape than
    the schema's is the contract's to report, and is read here as nothing."""
    out = []
    for index, entry in enumerate(_listed(project.setting("registration"))):
        if not isinstance(entry, dict):
            continue
        written = str(entry.get("id") or "")
        registry, kept = identify(written, _text_of(entry.get("registry")))
        outcomes = tuple(
            Outcome(
                registered=_text_of(item.get("registered")) or "",
                role=str(item.get("role") or ""),
                reported_as=_text_of(item.get("reported_as")),
                index=number,
            )
            for number, item in enumerate(_listed(entry.get("outcomes")))
            if isinstance(item, dict)
        )
        out.append(
            Declared(
                written=written,
                id=kept,
                registry=registry,
                retrospective=_text_of(entry.get("retrospective")),
                outcomes=outcomes,
                outcomes_given="outcomes" in entry,
                index=index,
            )
        )
    return out


def file_name(identifier: str) -> str:
    """The record's file name: the identifier, with a slash, which OSF's has, made a dash."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", identifier) + ".yaml"


def record_path(project: Project, identifier: str) -> Path:
    return project.root.joinpath(*RECORDS) / file_name(identifier)


def answers_digest(record: dict[str, Any]) -> str:
    """The SHA-256 of what a record says, kept in it: it catches an edit made without care,
    not one made by someone who runs the digest again."""
    value = {key: record.get(key) for key in ANSWERED}
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_record(path: Path) -> dict[str, Any]:
    """A record as it is, held to its schema. Raises ContractError where it is not one; the
    gate says which, and whether its digest holds."""
    document = read_structured(path)
    if not isinstance(document, dict):
        raise ContractError(f"{path.name} is not a registration record")
    report = validate(document, "registration", path)
    if not report.ok:
        raise ContractError("; ".join(f.message for f in report.failures))
    return document


def digest_holds(record: dict[str, Any]) -> bool:
    """Whether a fetched record says what it said when it was written. A record copied by
    hand has no digest: it is the author's word, and the gate says so."""
    if record.get("source") == "by-hand":
        return True
    return record.get("answers_sha256") == answers_digest(record)


def write_record(project: Project, record: dict[str, Any]) -> Path:
    """Write one fetched record, after holding it to its schema."""
    path = record_path(project, record["id"])
    report = validate(record, "registration", path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record for {record['id']} is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


__all__ = [
    "ANSWERED",
    "ASKED",
    "CLINICALTRIALS",
    "EU_PAS",
    "ISRCTN",
    "NAMED_IN_TEXT",
    "NAMES",
    "OSF",
    "PROSPERO",
    "RECORDS",
    "SCHEMA",
    "Declared",
    "Outcome",
    "answers_digest",
    "declared",
    "digest_holds",
    "file_name",
    "identify",
    "read_record",
    "record_path",
    "write_record",
]
