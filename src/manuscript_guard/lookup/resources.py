"""`manuscript-guard lookup --resources`: each RRID the manuscript types, asked of the RRID
resolver once, a cell line of Cellosaurus too, and what they said written down.

The shapes were read from live answers on 2026-11-12 (DESIGN.md, "A typed RRID is looked up
once, and the answer kept"):

* The resolver, `https://scicrunch.org/resolver/RRID:<accession>.json`, needs no key. It
  answers an RRID it knows with HTTP 200 and `{"hits": {"total": n, "hits": [...]},
  "resolver": {...}}`, `total` a number, each hit's `_source` with `item.name`,
  `item.types` (a list of `{"name": ..., "curie": ..., "type": ...}`, some with no name)
  and `rrid` (`curie`, `properCitation`, `is_unique`). There can be several hits:
  RRID:AB_2298772 gave two, one for each vendor's catalogue entry; RRID:CVCL_0030 thirty.
  One it does not know is HTTP 404.
* Cellosaurus, `https://api.cellosaurus.org/cell-line/<CVCL_xxxx>?format=json&fields=ac,id,cc`,
  needs no key; its data are CC BY 4.0. It answers `{"Cellosaurus": {"cell-line-list":
  [...]}}`, each line with `accession-list` and `name-list` (`{"type", "value"}`, the
  primary accession's type `primary`, the name's `identifier`) and `comment-list`
  (`{"category", "value"}`). A line it marks problematic has a comment of category
  "Problematic cell line", whose value opens with "Contaminated.", "Misidentified." and so
  on (CVCL_0372, KB: "Contaminated. Shown to be a HeLa derivative ..."). An accession it
  does not have is HTTP 404.

Anything else, an outage, a timeout, a 429, an answer of another shape, records nothing for
that RRID, and the command says so: it is never written down as unknown. Nothing of the
manuscript is sent, and nothing of the user: the RRID is the whole of each request, with a
User-Agent of "manuscript-guard/<version>". At most one request a second to each host.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.contracts.project import Project
from manuscript_guard.lookup.http import Request, Transport, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer, _asker
from manuscript_guard.lookup.sources import SHAPE, Ask, _ask, _json, _status_only
from manuscript_guard.rrids import (
    ABSENT,
    CELLOSAURUS_LICENCE,
    FOUND,
    SCHEMA,
    accession,
    answers_digest,
    digest_holds,
    first_places,
    is_cell_line,
    read_record,
    record_path,
    typed,
    write_record,
)

#: One request a second to each host, as the brief for this lookup asks.
INTERVALS = {"scicrunch.org": 1.0, "api.cellosaurus.org": 1.0}
#: The records of one RRID kept, at most: HeLa's RRID gives thirty, one for each vendor.
MOST_HITS = 50
PROBLEMATIC = "Problematic cell line"
UNREADABLE = "its record cannot be read, and is not written over: put it right or delete it"


@dataclass(frozen=True)
class Services:
    """Where each service is asked. The tests point both at a loopback server."""

    resolver: str = "https://scicrunch.org/resolver/"
    cellosaurus: str = "https://api.cellosaurus.org/cell-line/"


@dataclass(frozen=True)
class Planned:
    """One RRID and what is to be done with it."""

    rrid: str
    #: Why it is not asked, where it is not.
    skipped: str = ""
    #: Why it is asked, where it is.
    why: str = ""


class NoAnswer(Exception):
    """A service did not answer in the shape it documents: nothing is recorded."""


def _why_asked(path: Path, rrid: str) -> str:
    """Why an RRID with this record path is asked, or "" where its record stands. Raises
    ContractError where the record cannot be read: it is not written over."""
    if not path.is_file():
        return "no record"
    record = read_record(path)
    if record["rrid"] != rrid:
        return f"its record is the record of {record['rrid']}"
    if not digest_holds(record):
        return "its record was edited"
    return ""


def plan(project: Project, *, again: bool = False) -> list[Planned]:
    """What `lookup --resources` would do with each RRID the manuscript types."""
    out = []
    for rrid in first_places(typed(project)):
        path = record_path(project, rrid)
        try:
            why = _why_asked(path, rrid)
        except ContractError:
            out.append(Planned(rrid, skipped=UNREADABLE))
            continue
        why = "asked again, as asked" if again else why
        out.append(Planned(rrid, skipped="" if why else "up to date", why=why))
    return out


def _types(item: dict[str, Any]) -> list[str]:
    """The names of a record's types; a type with no name, as `{"type": "supercategory"}`,
    is passed over."""
    listed = item.get("types")
    if not isinstance(listed, list):
        return []
    return [one["name"].strip() for one in listed
            if isinstance(one, dict) and isinstance(one.get("name"), str)
            and one["name"].strip()]  # fmt: skip


def _hit(hit: Any) -> dict[str, Any] | None:
    """One record of the resolver's, in the record's terms; None where it is of no shape."""
    source = hit.get("_source") if isinstance(hit, dict) else None
    if not isinstance(source, dict):
        return None
    item = source.get("item") if isinstance(source.get("item"), dict) else {}
    rrid = source.get("rrid") if isinstance(source.get("rrid"), dict) else {}
    out = {
        "curie": rrid.get("curie"),
        "name": item.get("name"),
        "types": _types(item),
        "citation": rrid.get("properCitation"),
    }
    kept = {key: (" ".join(value.split()) if isinstance(value, str) else
                  value if key == "types" else None)
            for key, value in out.items()}  # fmt: skip
    kept = {key: value for key, value in kept.items() if value not in (None, "", [])}
    if not (isinstance(kept.get("curie"), str) or isinstance(kept.get("name"), str)):
        return None
    return kept


def resolver(rrid: str, ask: Ask, base: str) -> dict[str, Any]:
    """What the resolver said of one RRID. Raises NoAnswer where it said nothing usable."""
    answer = _ask(ask, Request(base + quote(rrid, safe=":") + ".json"))
    if isinstance(answer, dict):
        raise NoAnswer(answer["why"])
    if answer.status == 404:
        return {"status": ABSENT, "total": 0, "hits": []}
    said = _status_only(answer)
    if said is not None:
        raise NoAnswer(said["why"])
    data = _json(answer)
    hits = data.get("hits") if isinstance(data, dict) else None
    total = hits.get("total") if isinstance(hits, dict) else None
    listed = hits.get("hits") if isinstance(hits, dict) else None
    if isinstance(total, bool) or not isinstance(total, int) or not isinstance(listed, list):
        raise NoAnswer(f"the resolver gave {SHAPE}")
    kept = [one for one in map(_hit, listed) if one is not None]
    if total < 0 or (total and not kept) or len(kept) < len(listed):
        raise NoAnswer(f"the resolver gave {SHAPE}")
    if not total:
        return {"status": ABSENT, "total": 0, "hits": []}
    return {"status": FOUND, "total": total, "hits": kept[:MOST_HITS]}


def _values(entries: Any, kind: str) -> list[str]:
    return [e["value"] for e in entries if isinstance(e, dict) and e.get("type") == kind
            and isinstance(e.get("value"), str)] if isinstance(entries, list) else []  # fmt: skip


def cellosaurus(rrid: str, ask: Ask, base: str) -> dict[str, Any]:
    """What Cellosaurus says of a cell line. Raises NoAnswer where it said nothing usable."""
    asked = accession(rrid).upper()
    params = {"format": "json", "fields": "ac,id,cc"}
    answer = _ask(ask, Request(base + quote(asked, safe=""), params=params))
    if isinstance(answer, dict):
        raise NoAnswer(answer["why"])
    if answer.status == 404:
        return {"status": ABSENT, "licence": CELLOSAURUS_LICENCE}
    said = _status_only(answer)
    if said is not None:
        raise NoAnswer(said["why"])
    data = _json(answer)
    root = data.get("Cellosaurus") if isinstance(data, dict) else None
    lines = root.get("cell-line-list") if isinstance(root, dict) else None
    if not isinstance(lines, list):
        raise NoAnswer(f"Cellosaurus gave {SHAPE}")
    for line in lines:
        if not isinstance(line, dict):
            raise NoAnswer(f"Cellosaurus gave {SHAPE}")
        accessions = line.get("accession-list")
        written = [e.get("value", "").upper() for e in accessions or [] if isinstance(e, dict)
                   and isinstance(e.get("value"), str)]  # fmt: skip
        if asked not in written:
            continue
        comments = line.get("comment-list") or []
        if not isinstance(comments, list):
            raise NoAnswer(f"Cellosaurus gave {SHAPE}")
        problems = [" ".join(c["value"].split()) for c in comments if isinstance(c, dict)
                    and c.get("category") == PROBLEMATIC and isinstance(c.get("value"), str)
                    and c["value"].strip()]  # fmt: skip
        out = {"status": FOUND, "accession": next(iter(_values(accessions, "primary")), None),
               "name": next(iter(_values(line.get("name-list"), "identifier")), None),
               "problems": problems, "licence": CELLOSAURUS_LICENCE}  # fmt: skip
        return {key: value for key, value in out.items() if value not in (None, [])}
    raise NoAnswer(f"Cellosaurus gave no line {asked} in its answer")


def look_up(rrid: str, ask: Ask, services: Services, today: date) -> dict[str, Any]:
    """The record for one RRID. Raises NoAnswer where either service did not answer."""
    record: dict[str, Any] = {"schema": SCHEMA, "rrid": rrid, "asked_on": today.isoformat(),
                              **resolver(rrid, ask, services.resolver)}  # fmt: skip
    if is_cell_line(rrid):
        record["cellosaurus"] = cellosaurus(rrid, ask, services.cellosaurus)
    return {**record, "answers_sha256": answers_digest(record)}


def run(
    project: Project,
    planned: list[Planned],
    *,
    transport: Transport | None = None,
    services: Services | None = None,
    pacer: Pacer | None = None,
    today: date | None = None,
    said: Callable[[str], None] = print,
) -> tuple[list[tuple[Planned, dict[str, Any], Path]], list[tuple[Planned, str]]]:
    """Ask about each RRID that is due and write its record; what was written, and each
    RRID whose answer did not come, with why. Nothing is written for that one."""
    services = services or Services()
    ask = _asker(transport or default_transport, pacer or Pacer(intervals=dict(INTERVALS)),
                 Credentials())  # fmt: skip
    written, late = [], []
    for one in planned:
        if one.skipped:
            continue
        try:
            record = look_up(one.rrid, ask, services, today or date.today())
        except NoAnswer as exc:
            said(f"{one.rrid}: no answer ({exc}); nothing recorded, asked again next time")
            late.append((one, str(exc)))
            continue
        path = write_record(project, record)
        said(f"{one.rrid}: " + summary(record))
        written.append((one, record, path))
    return written, late


def summary(record: dict[str, Any]) -> str:
    """One line: what the resolver, and Cellosaurus, answered."""
    if record["status"] == ABSENT:
        said = "the resolver does not know it"
    else:
        first = record["hits"][0]
        kinds = ", ".join(first.get("types", [])[:2])
        said = first.get("name", first.get("curie", "")) + (f" ({kinds})" if kinds else "")
        if record["total"] > 1:
            said += f", and {record['total'] - 1} other record(s)"
    line = record.get("cellosaurus")
    if line is not None:
        if line["status"] == ABSENT:
            said += "; Cellosaurus does not have it"
        elif line.get("problems"):
            said += "; Cellosaurus marks it problematic"
    return said


__all__ = ["INTERVALS", "NoAnswer", "Planned", "Services", "cellosaurus", "look_up", "plan",
           "resolver", "run", "summary"]  # fmt: skip
