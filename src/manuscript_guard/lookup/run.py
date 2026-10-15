"""`manuscript-guard lookup`: each cited reference's DOI and PMID asked of the registries
once, and what they said written down.

Which registries, and in what order:

* Crossref for a DOI, for the work's title, type, years, pages, and the notices that update
  it: retractions, corrections, expressions of concern, from the publisher and from the
  Retraction Watch data Crossref carries.
* OpenAlex for the same DOI, for its `is_retracted`.
* DataCite where Crossref does not know the DOI: datasets are registered there, not there.
* doi.org's handle API where neither knows it, for the other agencies (JaLC for Japanese
  papers, mEDRA, KISTI): whether the DOI is registered at all, and nothing more.
* PubMed's ESummary for a PMID, separately from the DOI, with the DOI PubMed holds for it.

Nothing here decides anything about the reference. G7 reads the record, offline.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.identifiers import doi_of, pmid_of
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.literature.lookups import (
    SCHEMA,
    answers_digest,
    entry_digest,
    read_record,
    record_path,
    write_record,
)
from manuscript_guard.lookup import sources
from manuscript_guard.lookup.http import (
    TIMEOUT_SECONDS,
    Request,
    Response,
    Transport,
    default_transport,
    user_agent,
)
from manuscript_guard.zotero import find_citations

BIB_FILE = "references.bib"
#: Read from the environment only, so that no key is ever written into the project.
NCBI_KEY = "NCBI_API_KEY"
OPENALEX_KEY = "OPENALEX_API_KEY"
#: The contact address Crossref's polite pool and NCBI ask for, where paper.yaml has none.
CONTACT = "MANUSCRIPT_GUARD_CONTACT"
#: The longest wait a 429's `Retry-After` is obeyed for, once, before the answer is kept as
#: unresolvable.
MAX_WAIT_SECONDS = 30.0


@dataclass(frozen=True)
class Services:
    """Where each registry is asked. The tests point every one at a loopback server."""

    crossref: str = "https://api.crossref.org/works/"
    openalex: str = "https://api.openalex.org/works/doi:"
    datacite: str = "https://api.datacite.org/dois/"
    doi_org: str = "https://doi.org/api/handles/"
    pubmed: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@dataclass(frozen=True)
class Credentials:
    """What travels with a request and is never kept: the contact address and the keys."""

    contact: str | None = None
    ncbi_key: str | None = None
    openalex_key: str | None = None

    @classmethod
    def from_environment(cls, project: Project) -> Credentials:
        settings = project.setting("lookup") or {}
        contact = os.environ.get(CONTACT, "").strip() or settings.get("contact")
        return cls(
            contact=contact or None,
            ncbi_key=os.environ.get(NCBI_KEY, "").strip() or None,
            openalex_key=os.environ.get(OPENALEX_KEY, "").strip() or None,
        )

    @property
    def secrets(self) -> tuple[str, ...]:
        """The values a record must not hold. One shorter than eight characters is no key
        a registry issues, and looked for it would be found in a page number."""
        values = (self.contact, self.ncbi_key, self.openalex_key)
        return tuple(s for s in values if s and len(s) >= 8)


@dataclass
class Pacer:
    """At most one request to a host in each `interval` seconds: NCBI allows three a second
    without a key, the others more, and none is asked faster than five."""

    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    intervals: dict[str, float] = field(
        default_factory=lambda: {"eutils.ncbi.nlm.nih.gov": 0.34}
    )
    default: float = 0.2
    _last: dict[str, float] = field(default_factory=dict)

    def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            pause = self.intervals.get(host, self.default) - (self.clock() - last)
            if pause > 0:
                self.sleep(pause)
        self._last[host] = self.clock()


@dataclass(frozen=True)
class Planned:
    """One cited reference and what is to be done with it."""

    citekey: str
    doi: str | None = None
    pmid: str | None = None
    digest: str = ""
    #: Why it is not looked up, where it is not.
    skipped: str = ""
    #: Why it is looked up again, where it has a record.
    again: str = ""


def cited_keys(project: Project) -> list[str]:
    """Every citekey the manuscript cites, in order of first use."""
    seen: dict[str, None] = {}
    for path in source_files(project.path("manuscript")):
        for use in find_citations(read_text(path), path):
            seen.setdefault(use.citekey, None)
    return list(seen)


def _stale(record: dict[str, Any] | None, planned: Planned) -> str:
    """Why a record no longer answers for the entry, or "" where it does."""
    if record is None:
        return "no record"
    if record["entry_sha256"] != planned.digest:
        return "the entry changed since it was looked up"
    wanted = {k: v for k, v in (("doi", planned.doi), ("pmid", planned.pmid)) if v}
    if record["identifiers"] != wanted:
        return "its identifiers changed"
    if any(s.get("status") == sources.UNRESOLVABLE for s in record["sources"].values()):
        return "an answer did not come last time"
    return ""


def plan(project: Project, *, again: bool = False) -> list[Planned]:
    """What `lookup` would do with each cited reference."""
    entries = read_entries(project.path("literature") / BIB_FILE)
    planned: list[Planned] = []
    files: dict[str, str] = {}
    for citekey in cited_keys(project):
        fields = entries.get(citekey)
        if fields is None:
            planned.append(Planned(citekey, skipped="not in references.bib"))
            continue
        clash = files.setdefault(record_path(project, citekey).name.casefold(), citekey)
        if clash != citekey:
            planned.append(
                Planned(
                    citekey,
                    skipped=f"its record would share a file with @{clash} on a system that "
                    "does not tell upper from lower case; rename one",
                )
            )
            continue
        doi, pmid = doi_of(fields), pmid_of(fields)
        if not doi and not pmid:
            written = fields.get("doi") or fields.get("pmid")
            planned.append(
                Planned(
                    citekey,
                    skipped="its identifier is malformed (G7 says how)"
                    if written
                    else "it has no DOI and no PMID",
                )
            )
            continue
        one = Planned(citekey, doi=doi, pmid=pmid, digest=entry_digest(fields))
        why = "looked up again, as asked" if again else _stale(read_record(project, citekey), one)
        planned.append(
            Planned(citekey, doi, pmid, one.digest, skipped="" if why else "up to date", again=why)
        )
    return planned


def _asker(transport: Transport, pacer: Pacer, credentials: Credentials) -> sources.Ask:
    """A transport that waits its turn per host, sends the User-Agent, and obeys one 429's
    `Retry-After` when it is short."""

    def ask(request: Request) -> Response:
        host = urlsplit(request.base).hostname or ""
        # The contact address is in the User-Agent only where a source puts it there.
        headers = {"User-Agent": user_agent(None), "Accept": "application/json",
                   **request.headers}  # fmt: skip
        sent = Request(request.base, request.params, request.secret, headers)
        pacer.wait(host)
        response = transport(sent, TIMEOUT_SECONDS)
        if response.status == 429:
            wait = response.headers.get("Retry-After", "")
            if wait.isdigit() and int(wait) <= MAX_WAIT_SECONDS:
                pacer.sleep(float(wait))
                pacer.wait(host)
                response = transport(sent, TIMEOUT_SECONDS)
        return response

    return ask


def look_up(
    planned: Planned,
    ask: sources.Ask,
    services: Services,
    credentials: Credentials,
    today: date,
) -> dict[str, Any]:
    """The record for one reference: each registry asked in turn."""
    found: dict[str, Any] = {}
    if planned.doi:
        doi = planned.doi
        found["crossref"] = sources.crossref(doi, ask, services.crossref, credentials.contact)
        found["openalex"] = sources.openalex(
            doi, ask, services.openalex, credentials.openalex_key
        )
        if found["crossref"]["status"] != sources.FOUND:
            found["datacite"] = sources.datacite(doi, ask, services.datacite)
            if found["datacite"]["status"] != sources.FOUND:
                found["doi_org"] = sources.doi_org(doi, ask, services.doi_org)
    if planned.pmid:
        found["pubmed"] = sources.pubmed(
            planned.pmid, ask, services.pubmed, credentials.contact, credentials.ncbi_key
        )
    identifiers = {k: v for k, v in (("doi", planned.doi), ("pmid", planned.pmid)) if v}
    record = {
        "schema": SCHEMA,
        "citekey": planned.citekey,
        "looked_up_on": today.isoformat(),
        "entry_sha256": planned.digest,
        "identifiers": identifiers,
        "sources": found,
    }
    return {**record, "answers_sha256": answers_digest(record)}


def run(
    project: Project,
    planned: list[Planned],
    *,
    transport: Transport | None = None,
    services: Services | None = None,
    credentials: Credentials | None = None,
    pacer: Pacer | None = None,
    today: date | None = None,
    said: Callable[[str], None] = print,
) -> list[tuple[Planned, dict[str, Any], Path]]:
    """Look up each planned reference that is due, write its record, and say what came."""
    services = services or Services()
    credentials = credentials or Credentials()
    ask = _asker(transport or default_transport, pacer or Pacer(), credentials)
    written = []
    for one in planned:
        if one.skipped:
            continue
        record = look_up(one, ask, services, credentials, today or date.today())
        _never_kept(record, credentials)
        path = write_record(project, record)
        said(f"@{one.citekey}: " + summary(record))
        written.append((one, record, path))
    return written


def _never_kept(record: dict[str, Any], credentials: Credentials) -> None:
    """A key or the contact address in a record is refused before it is written. Nothing
    puts one there; this holds that true of whatever is added later."""
    text = repr(record)
    if any(secret in text for secret in credentials.secrets):
        raise RuntimeError("a lookup record would have held a key or the contact address")


def summary(record: dict[str, Any]) -> str:
    """One line: what each registry answered."""
    names = {
        "crossref": "Crossref",
        "openalex": "OpenAlex",
        "datacite": "DataCite",
        "doi_org": "doi.org",
        "pubmed": "PubMed",
    }
    parts = []
    for name, answer in record["sources"].items():
        said = answer["status"]
        if said == sources.UNRESOLVABLE:
            said += f" ({answer['why']})"
        elif name == "openalex" and answer.get("is_retracted"):
            said += ", retracted"
        parts.append(f"{names[name]} {said}")
    return "; ".join(parts)


__all__ = [
    "CONTACT",
    "NCBI_KEY",
    "OPENALEX_KEY",
    "Credentials",
    "Pacer",
    "Planned",
    "Services",
    "cited_keys",
    "look_up",
    "plan",
    "run",
    "summary",
]
