"""`manuscript-guard lookup --paper`: the paper's own DOI asked of Crossref once, and what it
said kept in `communication/lookups/crossref.yaml`.

Only the DOI is sent, paper.yaml's `publication.doi`, and only by the command that asks:
`communicate check` reads the record offline (`communicate/own_doi.py`). The transport is an
argument, as for every lookup, and the tests answer from a loopback server.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.communicate.own_doi import (
    SCHEMA,
    answers_digest,
    read_record,
    write_record,
)
from manuscript_guard.communicate.status import publication
from manuscript_guard.lookup import sources
from manuscript_guard.lookup.http import Transport, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer, Services, _asker, _never_kept

#: What of Crossref's answer is kept: enough to tell the work, nothing of its authors.
KEPT = ("doi", "title", "subtitle", "container", "type")


def doi_of(project) -> str | None:
    doi = publication(project).get("doi")
    return doi if isinstance(doi, str) and doi else None


def why_asked(project, *, again: bool = False) -> str:
    """Why the DOI is asked about, or "" where its record stands: none yet, another DOI's,
    one Crossref did not know or did not answer for, or asked again."""
    doi = doi_of(project)
    if doi is None:
        return ""
    if again:
        return "asked again, as asked"
    record = read_record(project)
    if record is None:
        return "no record"
    if str(record["doi"]).lower() != doi.lower():
        return "the record is of another DOI"
    status = record["crossref"]["status"]
    if status == sources.UNRESOLVABLE:
        return "an answer did not come last time"
    if status == sources.ABSENT:
        return "Crossref did not know it last time"
    return ""


def look_up(doi: str, ask: sources.Ask, base: str, contact: str | None,
            today: date) -> dict[str, Any]:  # fmt: skip
    answer = sources.crossref(doi, ask, base, contact)
    if answer["status"] == sources.FOUND:
        answer = {"status": sources.FOUND, **{key: answer[key] for key in KEPT if key in answer}}
    record = {"schema": SCHEMA, "doi": doi, "looked_up_on": today.isoformat(),
              "crossref": answer}  # fmt: skip
    return {**record, "answers_sha256": answers_digest(record)}


def run(
    project,
    *,
    transport: Transport | None = None,
    services: Services | None = None,
    credentials: Credentials | None = None,
    pacer: Pacer | None = None,
    today: date | None = None,
    said: Callable[[str], None] = print,
) -> tuple[dict[str, Any], Path]:
    """Ask Crossref about the paper's DOI, keep the answer, and say what came."""
    doi = doi_of(project)
    if doi is None:
        raise ValueError("paper.yaml gives no publication.doi")
    services = services or Services()
    credentials = credentials or Credentials()
    ask = _asker(transport or default_transport, pacer or Pacer(), credentials)
    record = look_up(doi, ask, services.crossref, credentials.contact, today or date.today())
    _never_kept(record, credentials)
    path = write_record(project, record)
    said(f"DOI {doi}: {summary(record)}")
    return record, path


def summary(record: dict[str, Any]) -> str:
    answer = record["crossref"]
    if answer["status"] == sources.FOUND:
        return f"Crossref found it, '{answer.get('title', '(no title)')}'"
    if answer["status"] == sources.ABSENT:
        return "Crossref does not know it"
    return f"Crossref's answer did not come ({answer['why']})"


__all__ = ["KEPT", "doi_of", "look_up", "run", "summary", "why_asked"]
