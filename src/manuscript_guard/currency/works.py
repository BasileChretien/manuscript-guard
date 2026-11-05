"""The works store filled: what the registries say of the cited work and of each candidate.

For each work, by its identifiers:

- Europe PMC's core record, by the PMID where there is one, else the DOI: the abstract, the
  publication types as it writes them, the first publication date, a retraction or an
  expression of concern it marks, and the published version of a preprint ("Preprint of").
- Crossref, where there is a DOI: the full publication date, the notices that update the
  work (a retraction, a removal, a withdrawal, an expression of concern) and
  `is-preprint-of`.
- PubMed's ESummary, where there is a PMID: the publication types, "Retracted Publication",
  and the "Retraction in" and "Expression of concern in" links.
- OpenAlex, where there is a DOI: `is_retracted`.

`publication_types` are PubMed's where it answered for a PMID, else Europe PMC's;
`published` is Crossref's date where there is a DOI, else Europe PMC's first publication
date. A work is retracted, withdrawn or under concern where any of them says so. A record is
written, sealed, only where every source asked answered and one knew the work; it is then
written whole over the last, since the facts change. Where a source did not answer, the
record the store held stays as it was: a lookup that did not work says nothing, and never
"not retracted".

The clients are `lookup`'s; nothing here reads the manuscript.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import records
from manuscript_guard.lookup import search, sources
from manuscript_guard.lookup.run import Credentials, _never_kept

#: Crossref's kinds of update (`lookup/sources._update`) that take a work out, put it under
#: concern, or withdraw it.
RETRACTED = frozenset({"retraction", "removal"})
WITHDRAWN = frozenset({"withdrawal"})
CONCERN = frozenset({"expression_of_concern", "partial_retraction"})
#: How many PMIDs one ESummary is asked about, and DOIs one OpenAlex request.
SUMMARY_BATCH = 100
OPENALEX_BATCH = search.MAX_LIMIT
NAMES = {"europepmc": "Europe PMC", "crossref": "Crossref", "pubmed": "PubMed",
         "openalex": "OpenAlex"}  # fmt: skip
#: Why a work has no record where every registry answered and none knows it.
UNKNOWN = "no registry asked knows the work"


@dataclass(frozen=True)
class Wanted:
    """A work to fetch: its store id and the identifiers it is asked by."""

    work: str
    doi: str | None = None
    pmid: str | None = None
    #: A PMID asked of PubMed for the publication types only, and not written among the
    #: work's identifiers: the cited work's `pmid_by_doi` (DESIGN.md, lookup schema 3).
    types_pmid: str | None = None

    @property
    def summary_pmid(self) -> str | None:
        return self.pmid or self.types_pmid


@dataclass(frozen=True)
class Fetched:
    """What came of one work: the record written, or why none was."""

    work: str
    record: dict[str, Any] | None = None
    why: str = ""


def wanted(work: str, doi: str | None = None, pmid: str | None = None,
           types_pmid: str | None = None) -> Wanted:  # fmt: skip
    """A work by its store id, with the identifier the id is made of among its own."""
    kind, _colon, value = work.partition(":")
    doi = doi or (value if kind == "doi" else None)
    pmid = pmid or (value if kind == "pmid" else None)
    return Wanted(records.fold_work(work), doi.lower() if doi else None, pmid,
                  None if pmid else types_pmid)  # fmt: skip


#: What fetching a work asks, in words, for a dry run.
PLANNED = ("Europe PMC by its PMID or DOI; Crossref and OpenAlex where it has a DOI; "
           "PubMed's ESummary where it has a PMID")


def fetch(project: Project, works: list[Wanted], ask: sources.Ask,
          services: search.Services, credentials: Credentials,
          today: date) -> list[Fetched]:  # fmt: skip
    """Fetch each work, write the records that can be written, and say what came of each.
    Europe PMC is asked first: the PMID it gives a work known by its DOI alone is asked of
    PubMed for its types and links (round 1 of #530), and not written among the work's
    identifiers."""
    epmc = {one.work: search.europepmc_facts(one.doi, one.pmid or None, ask, services)
            for one in works}  # fmt: skip
    works = [one if one.summary_pmid or not epmc[one.work].get("pmid")
             else replace(one, types_pmid=epmc[one.work]["pmid"]) for one in works]  # fmt: skip
    summaries = _summaries(works, ask, services, credentials)
    retracted = _openalex(works, ask, services, credentials)
    done = []
    for one in works:
        answers: dict[str, dict[str, Any]] = {"europepmc": epmc[one.work]}
        if one.doi:
            answers["crossref"] = sources.crossref(one.doi, ask, services.crossref,
                                                   credentials.contact)  # fmt: skip
            answers["openalex"] = retracted.get(one.doi, {"status": sources.ABSENT})
        if one.summary_pmid:
            answers["pubmed"] = summaries.get(one.summary_pmid, {"status": sources.ABSENT})
        done.append(_written(project, one, answers, credentials, today))
    return done


def _summaries(works: list[Wanted], ask: sources.Ask, services: search.Services,
               credentials: Credentials) -> dict[str, dict[str, Any]]:  # fmt: skip
    pmids = list(dict.fromkeys(one.summary_pmid for one in works if one.summary_pmid))
    said: dict[str, dict[str, Any]] = {}
    for start in range(0, len(pmids), SUMMARY_BATCH):
        batch = pmids[start : start + SUMMARY_BATCH]
        answer = sources.summaries(batch, ask, services.esummary, credentials.contact,
                                   credentials.ncbi_key)  # fmt: skip
        said |= {pmid: answer for pmid in batch} if "status" in answer else answer
    return said


def _openalex(works: list[Wanted], ask: sources.Ask, services: search.Services,
              credentials: Credentials) -> dict[str, dict[str, Any]]:  # fmt: skip
    """OpenAlex's `is_retracted` for each DOI, asked `OPENALEX_BATCH` at a time. A DOI the
    filter cannot hold (`|` or `,` in it) is not asked, and has no answer."""
    dois = list(dict.fromkeys(one.doi for one in works
                              if one.doi and not set(one.doi) & {"|", ","}))  # fmt: skip
    said: dict[str, dict[str, Any]] = {}
    for start in range(0, len(dois), OPENALEX_BATCH):
        batch = dois[start : start + OPENALEX_BATCH]
        answer = search.openalex_by_doi(batch, ask, services, credentials)
        if answer.status == sources.UNRESOLVABLE:
            said |= {doi: sources.unresolvable(answer.why) for doi in batch}
            continue
        held = {hit.doi: hit for hit in answer.hits if hit.doi}
        for doi in batch:
            hit = held.get(doi)
            if hit is None:
                said[doi] = {"status": sources.ABSENT}
            elif hit.retracted is None:
                # A work with no `is_retracted` is no answer, as `sources.openalex` reads it
                # (round 1 of #530).
                said[doi] = sources.unresolvable("OpenAlex said nothing of a retraction")
            else:
                said[doi] = {"status": sources.FOUND, "is_retracted": hit.retracted}
    return said


def _written(project: Project, one: Wanted, answers: dict[str, dict[str, Any]],
             credentials: Credentials, today: date) -> Fetched:  # fmt: skip
    failed = [f"{NAMES[name]} ({answer.get('why') or 'no answer'})"
              for name, answer in answers.items() if answer["status"] == sources.UNRESOLVABLE]
    if failed:
        return Fetched(one.work, why=f"not fetched: {', '.join(failed)} did not answer, and "
                       "the record held stays as it was")  # fmt: skip
    found = {name: answer for name, answer in answers.items()
             if answer["status"] == sources.FOUND}  # fmt: skip
    if not found:
        return Fetched(one.work, why=UNKNOWN)
    record = composed(one, found, today)
    _never_kept(record, credentials)
    try:
        records.write_work(project, record)
    except ContractError as exc:
        # One work's record that its schema refuses stops no other (round 1 of #530).
        return Fetched(one.work, why=f"not written: {exc}")
    return Fetched(one.work, record)


def composed(one: Wanted, found: dict[str, dict[str, Any]], today: date) -> dict[str, Any]:
    """One works record from the answers that knew the work."""
    epmc, crossref = found.get("europepmc", {}), found.get("crossref", {})
    pubmed, openalex = found.get("pubmed", {}), found.get("openalex", {})
    links = {link.get("type") for link in pubmed.get("links") or []}
    notices = {notice.get("type") for notice in crossref.get("updated_by") or []}
    pubtypes = pubmed.get("pubtypes") if pubmed else epmc.get("pubtypes")
    published = _crossref_date(crossref) if one.doi else None
    published = published or epmc.get("first_published")
    # Crossref's id may be a URL; `search._doi` reads it as the DOI, or as none.
    published_as = [f"doi:{doi}" for doi in map(search._doi, crossref.get("preprint_of") or [])
                    if doi]  # fmt: skip
    published_as += epmc.get("published_as") or []
    integrity = {
        "retracted": bool(notices & RETRACTED or "Retracted Publication" in (pubmed.get(
            "pubtypes") or []) or "Retraction in" in links or epmc.get("retracted")
            or openalex.get("is_retracted")),
        "withdrawn": bool(notices & WITHDRAWN),
        "under_concern": bool(notices & CONCERN or "Expression of concern in" in links
                              or epmc.get("under_concern")),
    }  # fmt: skip
    if published_as:
        integrity["published_as"] = list(dict.fromkeys(records.fold_work(work)
                                                       for work in published_as))
    identifiers = {key: value for key, value in (("doi", one.doi), ("pmid", one.pmid)) if value}
    record: dict[str, Any] = {
        "work": one.work,
        "identifiers": identifiers,
        "fetched_on": today.isoformat(),
        "sources": [name for name in NAMES if name in found],
    }
    title = crossref.get("title") or epmc.get("title") or pubmed.get("title")
    if title:
        record["title"] = title
    if published:
        record["published"] = published
    if pubtypes:
        record["publication_types"] = list(pubtypes)
    record["integrity"] = integrity
    if epmc.get("abstract"):
        record["abstract"] = epmc["abstract"]
    return record


def _crossref_date(crossref: dict[str, Any]) -> str | None:
    """Crossref's publication date. `issued` is the earlier of print and online, at the
    precision of the coarser: the finest of online and print that agrees with it at its own
    precision is taken, else `issued` (round 1 of #530: a print year and an online day gave
    the year). With no `issued`, online, print, or a preprint's `posted`."""
    dates = crossref.get("dates") or {}
    issued = dates.get("issued")
    if not issued:
        return next((dates[name] for name in ("online", "print", "posted") if dates.get(name)),
                    None)  # fmt: skip
    agreeing = [dates[name] for name in ("online", "print")
                if dates.get(name) and dates[name][: len(issued)] == issued]  # fmt: skip
    finest = max(map(len, agreeing), default=0)
    if finest <= len(issued):
        return issued
    # Of two as fine, the earlier, as `issued` is (round 2 of #530); Crossref's dates are
    # zero-padded, so the earlier is the lesser.
    return min(one for one in agreeing if len(one) == finest)


__all__ = ["PLANNED", "UNKNOWN", "Fetched", "Wanted", "composed", "fetch", "wanted"]
