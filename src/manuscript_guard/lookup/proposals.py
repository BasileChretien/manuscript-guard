"""The works the registries found, merged into one list of candidates, and said.

A work two registries found is one candidate: the same DOI is the same work, and a PMID
joins two answers only where no DOI tells them apart. The order is the registries' own
relevance, merged by reciprocal rank (each registry's rank r adds 1/(60 + r)), so a work
near the top of two answers stands above one at the top of one. Nothing here judges
whether a work supports a claim: that is the author's to decide, with the work read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from manuscript_guard.lookup import search as registries
from manuscript_guard.lookup.http import Request, Transport, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer, _asker
from manuscript_guard.lookup.search import (
    MAX_LIMIT,
    NAMES,
    NOT_ASKED,
    REGISTRIES,
    Answer,
    Filters,
    Hit,
    Services,
)
from manuscript_guard.lookup.sources import ABSENT, FOUND, UNRESOLVABLE

SORTS = ("relevance", "newest", "cited")
#: The constant of reciprocal-rank fusion, as its authors set it (Cormack, Clarke and
#: Buettcher, SIGIR 2009): large enough that the first few ranks of one list do not
#: outweigh agreement between lists.
FUSION = 60
#: Whose word is taken first for a field two registries give.
PRIORITY = ("pubmed", "europepmc", "openalex", "crossref")
#: Whose open copy is offered first: a copy in PMC or Europe PMC is the full text, free to
#: read, where a publisher's may move.
COPIES = ("europepmc", "pubmed", "openalex")
REMINDER = (
    "The order is the registries' relevance, merged; it says nothing of whether a work "
    "supports the claim. Read each work before proposing it, and cite only what the author "
    "chooses."
)
#: How a chosen work gets into the author's library: by Zotero, from the registry's record,
#: and not by this command (Basile's choice, 2026-10-20).
ZOTERO = (
    "To add a work the author chooses: Zotero's Add Item by Identifier, with its DOI, or its "
    "PMID where it has none; then `manuscript-guard sync-bib` and `lookup`."
)


@dataclass(frozen=True)
class Candidate:
    doi: str | None
    pmid: str | None
    pmcid: str | None
    title: str | None
    year: int | None
    journal: str | None
    first_author: str | None
    authors: int
    kinds: tuple[str, ...]
    language: str | None
    #: True where a registry says so, False where those asked say nothing of it, None
    #: where none was asked.
    retracted: bool | None
    retracted_per: tuple[str, ...]
    retraction_checked_by: tuple[str, ...]
    concern_per: tuple[str, ...]
    later_versions: tuple[dict[str, Any], ...]
    open_copy: str | None
    cited_by: dict[str, int] = field(default_factory=dict)
    found_by: dict[str, int] = field(default_factory=dict)
    #: Identifiers two registries gave differently, said in words.
    disagree: tuple[str, ...] = ()
    score: float = 0.0


@dataclass(frozen=True)
class Result:
    query: str
    filters: Filters
    sort: str
    answers: dict[str, Answer]
    candidates: tuple[Candidate, ...]
    #: Candidates past the limit, not shown.
    more: int = 0
    keyless: bool = False


def merge(hits: list[Hit]) -> list[list[Hit]]:
    """The hits, grouped by work. A hit with rank 0 joins a work found by the search, and
    never makes one."""
    groups: list[list[Hit]] = []
    by_doi: dict[str, int] = {}
    by_pmid: dict[str, int] = {}
    for hit in hits:
        index = by_doi.get(hit.doi) if hit.doi else None
        if index is None and hit.pmid and hit.pmid in by_pmid:
            other = by_pmid[hit.pmid]
            if not hit.doi or not any(h.doi for h in groups[other]):
                index = other
        if index is None:
            if not hit.rank:
                continue
            groups.append([])
            index = len(groups) - 1
        groups[index].append(hit)
        if hit.doi:
            by_doi.setdefault(hit.doi, index)
        if hit.pmid:
            by_pmid.setdefault(hit.pmid, index)
    return groups


def _first(hits: list[Hit], name: str) -> Any:
    return next((getattr(h, name) for h in hits if getattr(h, name)), None)


def _names(hits: list[Hit], keep: Callable[[Hit], bool]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(h.registry for h in hits if keep(h)))


def _later(hits: list[Hit]) -> tuple[dict[str, Any], ...]:
    found: dict[tuple, dict[str, Any]] = {}
    for hit in hits:
        for one in hit.later:
            key = (one.get("pmid"), one.get("doi"))
            entry = found.setdefault(key, {**one, "said_by": []})
            if hit.registry not in entry["said_by"]:
                entry["said_by"].append(hit.registry)
    return tuple(found.values())


def _disagree(hits: list[Hit], name: str, label: str) -> tuple[str, ...]:
    first = _first(hits, name)
    return tuple(
        f"{NAMES[h.registry]} gives {label} {getattr(h, name)}"
        for h in hits
        if getattr(h, name) and getattr(h, name) != first
    )


def candidate(group: list[Hit]) -> Candidate:
    hits = sorted(group, key=lambda h: PRIORITY.index(h.registry))
    copies = sorted((h for h in hits if h.open_copy), key=lambda h: COPIES.index(h.registry))
    retracted_per = _names(hits, lambda h: h.retracted is True)
    checked = _names(hits, lambda h: h.retracted is not None)
    return Candidate(
        doi=_first(hits, "doi"),
        pmid=_first(hits, "pmid"),
        pmcid=_first(hits, "pmcid"),
        title=_first(hits, "title"),
        year=_first(hits, "year"),
        journal=_first(hits, "journal"),
        first_author=_first(hits, "first_author"),
        authors=max((h.authors for h in hits), default=0),
        kinds=tuple(k for k in registries.ORDER if any(k in h.kinds for h in hits)),
        language=_first(hits, "language"),
        retracted=True if retracted_per else (False if checked else None),
        retracted_per=retracted_per,
        retraction_checked_by=checked,
        concern_per=_names(hits, lambda h: h.concern),
        later_versions=_later(hits),
        open_copy=copies[0].open_copy if copies else None,
        cited_by={h.registry: h.cited_by for h in hits if h.cited_by is not None},
        found_by={h.registry: h.rank for h in hits if h.rank},
        disagree=_disagree(hits, "pmid", "PMID") + _disagree(hits, "pmcid", "PMCID"),
        score=sum(1 / (FUSION + h.rank) for h in hits if h.rank),
    )


def ranked(candidates: list[Candidate], sort: str) -> list[Candidate]:
    def key(c: Candidate) -> tuple:
        tie = (-c.score, min(c.found_by.values(), default=0), c.doi or c.pmid or c.title or "")
        if sort == "newest":
            return (-(c.year or 0), *tie)
        if sort == "cited":
            return (-max(c.cited_by.values(), default=-1), *tie)
        return tie

    return sorted(candidates, key=key)


def planned(query: str, filters: Filters, credentials: Credentials,
            services: Services) -> list[tuple[str, Request]]:  # fmt: skip
    """The requests the search starts with, for each registry asked."""
    skipped = registries.asks(filters)
    first = {
        "pubmed": lambda: registries.pubmed_search(query, filters, credentials, services),
        "europepmc": lambda: registries.europepmc_search(query, filters, services),
        "openalex": lambda: registries.openalex_search(query, filters, credentials, services),
    }
    return [(name, first[name]()) for name in REGISTRIES if not skipped[name]]


def run(
    query: str,
    filters: Filters,
    *,
    sort: str = "relevance",
    transport: Transport | None = None,
    services: Services | None = None,
    credentials: Credentials | None = None,
    pacer: Pacer | None = None,
) -> Result:
    """Ask each registry, then ask about the works found, and merge what came."""
    services = services or Services()
    credentials = credentials or Credentials()
    ask = _asker(transport or default_transport, pacer or Pacer(), credentials)
    skipped = registries.asks(filters)
    answers: dict[str, Answer] = {}
    for name in REGISTRIES:
        if skipped[name]:
            answers[name] = Answer(NOT_ASKED, why=skipped[name])
        elif name == "europepmc":
            answers[name] = registries.europepmc(query, filters, ask, services)
        else:
            reader = registries.pubmed if name == "pubmed" else registries.openalex
            answers[name] = reader(query, filters, ask, services, credentials)
    hits = [h for name in REGISTRIES for h in answers[name].hits]
    pool = ranked([candidate(g) for g in merge(hits)], "relevance")
    unseen = [c.doi for c in pool[:MAX_LIMIT] if c.doi and "openalex" not in c.found_by]
    if unseen:
        answers["openalex_by_doi"] = registries.openalex_by_doi(unseen, ask, services,
                                                                credentials)  # fmt: skip
        hits += answers["openalex_by_doi"].hits
    pool = ranked([candidate(g) for g in merge(hits)], sort)
    preprints = [c.doi for c in pool[: filters.limit] if "preprint" in c.kinds and c.doi]
    if preprints:
        said = [registries.crossref(doi, ask, services, credentials) for doi in preprints]
        found = tuple(h for h in said if h is not None)
        answers["crossref"] = Answer(FOUND if found else ABSENT, found, len(found))
        hits += found
        pool = ranked([candidate(g) for g in merge(hits)], sort)
    return Result(query, filters, sort, answers, tuple(pool[: filters.limit]),
                  max(0, len(pool) - filters.limit),
                  keyless=not credentials.openalex_key)  # fmt: skip


def answered(result: Result) -> bool:
    """Whether any registry asked gave an answer that can be read."""
    return any(result.answers[n].status in (FOUND, ABSENT) for n in REGISTRIES)


# ------------------------------------------------------------------------------- saying it


def _filters(result: Result) -> str:
    f = result.filters
    said = []
    if f.since:
        said.append(f"since {f.since}")
    if f.types:
        said.append(" or ".join(registries.TYPE_NAMES[t] for t in f.types))
    if f.language:
        said.append(f"in {f.language}")
    return f" ({'; '.join(said)})" if said else ""


def _registry(name: str, answer: Answer) -> str:
    if answer.status == FOUND:
        said = f"{answer.count} found"
    elif answer.status == ABSENT:
        said = "nothing found"
    else:
        said = f"{answer.status} ({answer.why})"
    if answer.dropped:
        said += "; it left out " + ", ".join(repr(d) for d in answer.dropped)
    return f"{NAMES[name]}: {said}"


def _version(one: dict[str, Any]) -> str:
    ids = [f"{k.upper()} {one[k]}" for k in ("doi", "pmid") if one.get(k)]
    named = ", ".join(NAMES[n] for n in one["said_by"])
    reference = f": {one['reference']}" if one.get("reference") else ""
    return f"a later version, {' / '.join(ids)}{reference} ({named})"


def _lines(number: int, c: Candidate) -> list[str]:
    who = [f"{c.first_author}{' et al.' if c.authors > 1 else ''}"] if c.first_author else []
    lead = ", ".join([*who, *([str(c.year)] if c.year else [])])
    title = (c.title or "(no title given)").rstrip(".")
    journal = f" {c.journal.rstrip('.')}." if c.journal else ""
    lines = [f"{number:2}. {lead + '. ' if lead else ''}{title}.{journal}"]
    ids = [f"{label} {value}" for label, value in
           (("DOI", c.doi), ("PMID", c.pmid), ("PMCID", c.pmcid)) if value]  # fmt: skip
    lines.append("    " + (" · ".join(ids) or "no DOI and no PMID"))
    facts = [", ".join(c.kinds)] if c.kinds else []
    if c.retracted:
        facts.insert(0, f"RETRACTED ({', '.join(NAMES[n] for n in c.retracted_per)})")
    elif c.retracted is False:
        named = ", ".join(NAMES[n] for n in c.retraction_checked_by)
        facts.append(f"retracted: no ({named})")
    else:
        facts.append("retracted: not known")
    if c.concern_per:
        facts.append(f"expression of concern ({', '.join(NAMES[n] for n in c.concern_per)})")
    if c.cited_by:
        counts = ", ".join(f"{n} ({NAMES[r]})" for r, n in c.cited_by.items())
        facts.append(f"cited {counts}")
    lines.append("    " + " · ".join(facts))
    lines += [f"    {_version(one)}" for one in c.later_versions]
    if c.open_copy:
        lines.append(f"    open copy: {c.open_copy}")
    lines += [f"    note: {said}" for said in c.disagree]
    found = ", ".join(f"{NAMES[r]} #{n}" for r, n in c.found_by.items())
    lines.append(f"    found by {found}")
    return lines


def render(result: Result) -> str:
    out = [f"Searched for {result.query!r}{_filters(result)}, by {result.sort}."]
    out.append("; ".join(_registry(n, result.answers[n]) for n in REGISTRIES))
    for name in ("openalex_by_doi", "crossref"):
        answer = result.answers.get(name)
        if answer is not None and answer.status == UNRESOLVABLE:
            what = "the works it did not return" if name == "openalex_by_doi" else "the preprints"
            registry = "OpenAlex" if name == "openalex_by_doi" else "Crossref"
            out.append(f"{registry}, asked about {what}: unresolvable ({answer.why})")
    if result.keyless and result.answers["openalex"].status != NOT_ASKED:
        out.append("OpenAlex was asked without a key (OPENALEX_API_KEY), from the allowance "
                   "it shares between everyone at this network address.")  # fmt: skip
    out.append("")
    if not result.candidates:
        out.append("No work was found.")
    for number, one in enumerate(result.candidates, 1):
        out += _lines(number, one)
    if result.more:
        out.append(f"\n{result.more} more found; `--limit` shows more (at most {MAX_LIMIT}).")
    out.append("")
    out.append(REMINDER)
    if result.candidates:
        out.append(ZOTERO)
    return "\n".join(out)


def as_json(result: Result) -> dict[str, Any]:
    f = result.filters
    return {
        "query": result.query,
        "filters": {"since": f.since, "types": list(f.types), "language": f.language,
                    "limit": f.limit, "sort": result.sort},  # fmt: skip
        "registries": {
            name: {k: v for k, v in (("status", a.status), ("count", a.count), ("why", a.why),
                                     ("left_out", list(a.dropped))) if v not in (None, "", [])}
            for name, a in result.answers.items()
        },  # fmt: skip
        "candidates": [_candidate_json(c) for c in result.candidates],
        "more": result.more,
        "note": REMINDER,
        "zotero": ZOTERO,
    }


def _candidate_json(c: Candidate) -> dict[str, Any]:
    data = {
        "doi": c.doi, "pmid": c.pmid, "pmcid": c.pmcid, "title": c.title, "year": c.year,
        "journal": c.journal, "first_author": c.first_author, "authors": c.authors,
        "kinds": list(c.kinds), "language": c.language, "retracted": c.retracted,
        "retracted_per": list(c.retracted_per),
        "retraction_checked_by": list(c.retraction_checked_by),
        "expression_of_concern_per": list(c.concern_per),
        "later_versions": [dict(v) for v in c.later_versions], "open_copy": c.open_copy,
        "cited_by": dict(c.cited_by), "found_by": dict(c.found_by),
        "disagree": list(c.disagree),
        # What Zotero's Add Item by Identifier is given for it.
        "for_zotero": c.doi or c.pmid,
    }  # fmt: skip
    return data


__all__ = ["SORTS", "Candidate", "Result", "answered", "as_json", "candidate", "merge",
           "planned", "ranked", "render", "run"]  # fmt: skip
