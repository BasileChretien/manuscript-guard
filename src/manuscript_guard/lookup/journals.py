"""`manuscript-guard lookup --journals`: each shortlisted journal's ISSN asked of the NLM
Catalog and DOAJ once, and what they said written down.

* The NLM Catalog, through E-utilities: ESearch finds the catalogue records of the ISSN
  (`<issn>[IS]`), and ESummary says of each whether the journal is currently indexed for
  MEDLINE (`currentindexingstatus`, "Y" or "N").
* DOAJ, through its search API (version 4): whether a journal with the ISSN is listed.

Nothing of the manuscript is sent: an ISSN is all either is asked. Each answer is `found`,
`absent` or `unresolvable`, as `lookup.sources` reads a reference's. The shapes were read
from the services' documentation and from live answers on 2026-10-17 (DESIGN.md, "The
journal shortlist is a record").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from manuscript_guard.contracts.project import Project
from manuscript_guard.lookup.http import Request, Transport, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer, _asker, _never_kept
from manuscript_guard.lookup.sources import (
    ABSENT,
    FOUND,
    SHAPE,
    UNRESOLVABLE,
    Ask,
    _ask,
    _json,
    _status_only,
    _text,
    unresolvable,
)
from manuscript_guard.shortlist import SCHEMA, answers_digest, read_record, write_record

#: Search results past this many are not read: an ISSN names one serial, or a few records
#: of it (a title that changed, a print and an online edition).
MAX_RECORDS = 20


@dataclass(frozen=True)
class Services:
    """Where each is asked. The tests point both at a loopback server."""

    esearch: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    esummary: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    doaj: str = "https://doaj.org/api/v4/search/journals/"


def _eutils(base: str, params: dict[str, str], credentials: Credentials) -> Request:
    return Request(
        base,
        params={**params, "db": "nlmcatalog", "retmode": "json", "tool": "manuscript-guard"},
        secret={"email": credentials.contact or "", "api_key": credentials.ncbi_key or ""},
    )


def _issns(listed: Any) -> list[str]:
    out = []
    for item in listed if isinstance(listed, list) else []:
        value = item.get("issn") if isinstance(item, dict) else None
        if isinstance(value, str) and len(value.strip()) == 9:
            out.append(value.strip().upper())
    return out


def nlm_catalog(
    issn: str, ask: Ask, services: Services, credentials: Credentials
) -> dict[str, Any]:
    """The catalogue's records of the ISSN, and whether each is currently indexed for
    MEDLINE. E-utilities answers an error with a 200 that holds `error`."""
    term = {"term": f"{issn}[IS]", "retmax": str(MAX_RECORDS)}
    answer = _ask(ask, _eutils(services.esearch, term, credentials))
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    result = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(result, dict) or "ERROR" in result or "error" in data:
        return unresolvable(SHAPE if not isinstance(result, dict) else "the service said: error")
    ids = result.get("idlist")
    if not isinstance(ids, list) or not all(isinstance(i, str) and i.isdigit() for i in ids):
        return unresolvable(SHAPE)
    if not ids:
        return {"status": ABSENT}
    answer = _ask(ask, _eutils(services.esummary, {"id": ",".join(ids)}, credentials))
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    summary = data.get("result") if isinstance(data, dict) else None
    if not isinstance(summary, dict) or "error" in data:
        return unresolvable(SHAPE)
    records = []
    for uid in ids:
        item = summary.get(uid)
        status = item.get("currentindexingstatus") if isinstance(item, dict) else None
        if status not in ("Y", "N") or not _text(item.get("nlmuniqueid")):
            return unresolvable(SHAPE)
        titles = item.get("titlemainlist")
        title = titles[0].get("title") if isinstance(titles, list) and titles and isinstance(
            titles[0], dict) else None  # fmt: skip
        record = {
            "nlm_id": _text(item["nlmuniqueid"]),
            "title": _text(title),
            "currently_indexed": status == "Y",
            "issns": _issns(item.get("issnlist")),
        }
        records.append({k: v for k, v in record.items() if v not in (None, [])})
    return {"status": FOUND, "records": records}


def doaj(issn: str, ask: Ask, services: Services) -> dict[str, Any]:
    """DOAJ's journal search for the ISSN: listed, with its DOAJ id, or not."""
    answer = _ask(ask, Request(services.doaj + quote(f"issn:{issn}", safe=":")))
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    total = data.get("total") if isinstance(data, dict) else None
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(total, bool) or not isinstance(total, int) or not isinstance(results, list):
        return unresolvable(SHAPE)
    for item in results:
        bibjson = item.get("bibjson") if isinstance(item, dict) else None
        if not isinstance(bibjson, dict) or not _text(item.get("id")):
            return unresolvable(SHAPE)
        listed = [str(bibjson.get(k) or "").upper() for k in ("pissn", "eissn")]
        if issn.upper() in listed:
            found = {
                "status": FOUND,
                "id": _text(item["id"]),
                "title": _text(bibjson.get("title")),
                "issns": [i for i in listed if len(i) == 9],
                "last_updated": _text(item.get("last_updated")),
            }
            return {k: v for k, v in found.items() if v not in (None, [])}
    # A search that matched other journals, or none: this ISSN is not listed.
    return {"status": ABSENT}


def look_up(
    issn: str, ask: Ask, services: Services, credentials: Credentials, today: date
) -> dict[str, Any]:
    record = {
        "schema": SCHEMA,
        "issn": issn.upper(),
        "looked_up_on": today.isoformat(),
        "sources": {
            "nlm_catalog": nlm_catalog(issn, ask, services, credentials),
            "doaj": doaj(issn, ask, services),
        },
    }
    return {**record, "answers_sha256": answers_digest(record)}


def due(project: Project, wanted: list[str], *, again: bool = False) -> list[str]:
    """The ISSNs to ask about: those with no record, one whose answer did not come, or all
    of them where asked again."""
    out = []
    for issn in wanted:
        record = None if again else read_record(project, issn)
        late = record is not None and any(
            s.get("status") == UNRESOLVABLE for s in record["sources"].values()
        )
        if record is None or late:
            out.append(issn)
    return out


def run(
    project: Project,
    wanted: list[str],
    *,
    transport: Transport | None = None,
    services: Services | None = None,
    credentials: Credentials | None = None,
    pacer: Pacer | None = None,
    today: date | None = None,
    said: Callable[[str], None] = print,
) -> list[tuple[dict[str, Any], Path]]:
    """Ask about each ISSN, write its record, and say what came."""
    services = services or Services()
    credentials = credentials or Credentials()
    pacer = pacer or Pacer(intervals={"eutils.ncbi.nlm.nih.gov": 0.34, "doaj.org": 0.5})
    ask = _asker(transport or default_transport, pacer, credentials)
    written = []
    for issn in wanted:
        record = look_up(issn, ask, services, credentials, today or date.today())
        _never_kept(record, credentials)
        path = write_record(project, record)
        said(f"ISSN {issn}: " + summary(record))
        written.append((record, path))
    return written


def summary(record: dict[str, Any]) -> str:
    nlm, listed = record["sources"]["nlm_catalog"], record["sources"]["doaj"]
    if nlm["status"] == FOUND:
        indexed = any(r["currently_indexed"] for r in nlm["records"])
        said = "NLM Catalog: " + ("currently indexed for MEDLINE" if indexed
                                  else "not currently indexed for MEDLINE")  # fmt: skip
    else:
        said = f"NLM Catalog: {nlm['status']}"
    said += f"; DOAJ: {'listed' if listed['status'] == FOUND else listed['status']}"
    for answer in (nlm, listed):
        if answer["status"] == UNRESOLVABLE:
            said += f" ({answer['why']})"
    return said


__all__ = ["MAX_RECORDS", "Services", "doaj", "due", "look_up", "nlm_catalog", "run", "summary"]
