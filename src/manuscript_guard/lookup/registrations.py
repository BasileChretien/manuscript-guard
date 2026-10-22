"""`manuscript-guard lookup --registrations`: each registration `paper.yaml` lists, asked of
its registry once, and what the registry said written down.

ClinicalTrials.gov, OSF and ISRCTN are asked through their APIs, the EU PAS register by its
pages (`lookup.registries`, `lookup.eupas`). A registration elsewhere, PROSPERO's among them,
is not asked: its record is copied by hand, and `lookup` says so and never writes over it.
Nothing of the manuscript is sent: the identifier is all a registry is asked.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.contracts.project import Project
from manuscript_guard.lookup import eupas, registries
from manuscript_guard.lookup.http import Transport, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer, _asker, _never_kept
from manuscript_guard.lookup.sources import FOUND, UNRESOLVABLE
from manuscript_guard.registrations import (
    ASKED,
    CLINICALTRIALS,
    EU_PAS,
    ISRCTN,
    NAMES,
    OSF,
    SCHEMA,
    answers_digest,
    declared,
    digest_holds,
    file_name,
    read_record,
    record_path,
    refused,
    write_record,
)

#: The pace for each host: the catalogue is a web site, and is asked as a person would ask it.
INTERVALS = {
    "clinicaltrials.gov": 1.2,
    "catalogues.ema.europa.eu": 1.0,
    "www.isrctn.com": 0.5,
}


UNREADABLE = "its record cannot be read, and is not written over: put it right or delete it"
BY_HAND = "its record was copied by hand, and is not written over"


@dataclass(frozen=True)
class Planned:
    """One registration and what is to be done with it."""

    written: str
    id: str | None = None
    registry: str | None = None
    #: Why it is not asked, where it is not.
    skipped: str = ""
    #: Why it is asked, where it is.
    why: str = ""


def _why_asked(path: Path) -> str:
    """Why a registration with this record path is asked, or "" where its record stands."""
    if not path.is_file():
        return "no record"
    try:
        record = read_record(path)
    except ContractError:
        return ""
    if not digest_holds(record):
        return "its record was edited"
    if record["status"] == UNRESOLVABLE:
        return "an answer did not come last time"
    return ""


def plan(project: Project, *, again: bool = False) -> list[Planned]:
    """What `lookup --registrations` would do with each registration `paper.yaml` lists."""
    out: list[Planned] = []
    seen: set[str] = set()
    for one in declared(project):
        if one.id is None:
            out.append(Planned(one.written, skipped=f"its identifier {refused(one.named)}"))
            continue
        if one.id in seen:
            continue
        seen.add(one.id)
        path = record_path(project, one.id)
        if one.registry not in ASKED:
            name = NAMES.get(one.registry, one.registry)
            out.append(Planned(one.written, one.id, one.registry,
                               skipped=f"{name} is not asked: copy its record by hand into "
                               f"design/registrations/{file_name(one.id)}"))  # fmt: skip
            continue
        try:
            by_hand = path.is_file() and read_record(path).get("source") == "by-hand"
        except ContractError:
            out.append(Planned(one.written, one.id, one.registry, skipped=UNREADABLE))
            continue
        if by_hand:
            out.append(Planned(one.written, one.id, one.registry, skipped=BY_HAND))
            continue
        why = "asked again, as asked" if again else _why_asked(path)
        out.append(Planned(one.written, one.id, one.registry, skipped="" if why else "up to date",
                           why=why))  # fmt: skip
    return out


def look_up(
    planned: Planned, ask, services: registries.Services, today: date
) -> dict[str, Any]:
    """The record for one registration."""
    asking: dict[str, Callable[..., dict[str, Any]]] = {
        CLINICALTRIALS: lambda: registries.clinicaltrials(planned.id, ask, services.clinicaltrials),
        EU_PAS: lambda: eupas.eu_pas(planned.id, ask, services.eu_pas),
        OSF: lambda: registries.osf(planned.id, ask, services.osf),
        ISRCTN: lambda: registries.isrctn(planned.id, ask, services.isrctn),
    }
    answer = asking[planned.registry]()
    record = {
        "schema": SCHEMA,
        "id": planned.id,
        "registry": planned.registry,
        "source": "registry",
        "asked_on": today.isoformat(),
        **answer,
    }
    return {**record, "answers_sha256": answers_digest(record)}


def run(
    project: Project,
    planned: list[Planned],
    *,
    transport: Transport | None = None,
    services: registries.Services | None = None,
    pacer: Pacer | None = None,
    today: date | None = None,
    said: Callable[[str], None] = print,
) -> list[tuple[Planned, dict[str, Any], Path]]:
    """Ask about each registration that is due, write its record, and say what came."""
    services = services or registries.Services()
    credentials = Credentials()
    ask = _asker(transport or default_transport, pacer or Pacer(intervals=dict(INTERVALS)),
                 credentials)  # fmt: skip
    written = []
    for one in planned:
        if one.skipped:
            continue
        record = look_up(one, ask, services, today or date.today())
        _never_kept(record, credentials)
        path = write_record(project, record)
        said(f"{one.id}: " + summary(record))
        written.append((one, record, path))
    return written


def summary(record: dict[str, Any]) -> str:
    """One line: what the registry answered."""
    name = NAMES.get(record["registry"], record["registry"])
    if record["status"] == FOUND:
        outcomes = sum(1 for s in record.get("sections", []) if s.get("role"))
        return (f"{name}: registered {record['dates']['registered']}, {outcomes} outcome "
                f"field{'' if outcomes == 1 else 's'}")  # fmt: skip
    return f"{name}: {record['status']} ({record['why']})"


__all__ = ["INTERVALS", "Planned", "look_up", "plan", "run", "summary"]
