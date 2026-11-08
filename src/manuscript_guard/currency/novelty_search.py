"""`references --search` and `--replay` for a claim of novelty, and `--hand-search`.

A claim that something is first, or that no study has looked at it, is held to a recorded
search for the earlier study (DESIGN.md, "A claim to be first, or that nothing is known, rests
on a recorded search"). The reader writes the terms and says who wrote them (`--as`); nothing
is derived from the sentence. Two steps, each recorded as currency's searches are, sealed,
numbered and written once:

- N1, the earlier study: the terms at PubMed, Europe PMC and OpenAlex, with no limit of date or
  of publication type.
- N2, forward from the nearest: OpenAlex's works of every type that cite a work the reader
  names (`--forward`), newest first. The work is asked of OpenAlex by its DOI, else its PMID.

Each record holds the years searched (no lower limit, to the day it ran) and, in the reader's
words, what the search did not reach (`not_searched`, D4.4). The works kept go into the works
store, for the reader to read. A search a person ran by hand in a database the tool cannot
reach is filed from a file with `--hand-search`, signed by that person: it adds to the record
and never counts as a step.

What leaves the machine: the terms, the seed's DOI or PMID, and the identifiers of the works
found. No sentence of the manuscript is sent.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import novelty, records, works
from manuscript_guard.currency.command import Refused
from manuscript_guard.currency.searching import (
    ASKED,
    Run,
    Services,
    _asker_for,
    _said,
    _said_works,
    _write_question,
    framed,
    limit_of,
    terms,
)
from manuscript_guard.lookup import search, sources
from manuscript_guard.lookup.http import Transport
from manuscript_guard.lookup.run import Credentials, Pacer, _never_kept

#: The step of the search for the earlier study, and of the look forward from the nearest.
EARLIER, FORWARD = "N1", "N2"
STEPS = {EARLIER: search.REGISTRIES, FORWARD: ("openalex",)}
#: The fields a search by hand is filed with, beside who ran it.
HAND_FIELDS = frozenset({"step", "source", "query", "sent", "searched_on", "hits", "years",
                         "not_searched", "candidates", "seed"})  # fmt: skip


def _entry(project: Project, entry_id: str) -> tuple[records.Entry, dict]:
    from manuscript_guard.currency.command import _entry_of

    _document, raw = _entry_of(project, entry_id)
    entry = records._entry(raw)
    if not entry.novelty:
        raise Refused(f"{entry_id} is not a claim of novelty")
    return entry, raw


def _refuse_unplaced(project: Project, entry: records.Entry) -> None:
    from manuscript_guard.literature.passages import statement_words

    have = {claim.folded for claim in novelty.claims(project)}
    if not any(statement_words(one) in have for one in entry.sentences):
        raise Refused(f"{entry.id} is unplaced: no claim of the manuscript reads as it does. "
                      "Mark the claim as the manuscript now has it first, with "
                      f"`manuscript-guard references --novelty \"<words>\" --id {entry.id}`")


def not_searched_of(text: str | None) -> str:
    """`--not-searched` as it is recorded, or why it cannot be (D4.4)."""
    problem = novelty.not_searched_problem(text)
    if problem:
        raise Refused(f"--not-searched: {problem}")
    return " ".join(str(text).split())


def seed_of(project: Project, text: str) -> works.Wanted:
    """The work `--forward` names: `@key` (its DOI and PMID in references.bib), a DOI with
    or without `doi:` or `https://doi.org/`, or a PMID with or without `pmid:`."""
    from manuscript_guard.gates.currency import _bib
    from manuscript_guard.gates.identifiers import doi_of, pmid_of

    given = text.strip()
    if given.startswith("@"):
        fields = _bib(project).get(given[1:])
        work = records.work_id(fields)
        if fields is None or work is None:
            raise Refused(f"--forward {given}: references.bib gives it no DOI and no PMID")
        return works.wanted(work, doi_of(fields), pmid_of(fields))
    lowered = given.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        lowered = lowered.removeprefix(prefix)
    if lowered.startswith("10."):
        work = f"doi:{lowered}"
    else:
        number = lowered.removeprefix("pmid:")
        work = f"pmid:{number}" if number.isdigit() and not number.startswith("0") else ""
    if not records.WORK.fullmatch(work):
        raise Refused(f"--forward {given}: name the work by its DOI, its PMID or @key")
    return works.wanted(work)


# ----------------------------------------------------------------------------- the runs


def run(project: Project, entry_id: str, *, terms_text: str | None, forward: str | None,
        not_searched: str | None, by: str | None, question: str | None = None,
        dry_run: bool = False, transport: Transport | None = None,
        services: Services | None = None, credentials: Credentials | None = None,
        pacer: Pacer | None = None, today: date | None = None) -> Run:  # fmt: skip
    """`references --search ID` for a claim of novelty: N1 with `--terms`, N2 with
    `--forward`."""
    entry, raw = _entry(project, entry_id)
    if (terms_text is None) == (forward is None):
        raise Refused("a claim of novelty is searched with --terms (N1, the earlier study) or "
                      "with --forward (N2, the works citing the nearest one), one at a time")
    note = not_searched_of(not_searched)
    if by is None or not by.strip():
        raise Refused("--as names who wrote the terms: a person, or the model that wrote them")
    query = terms(terms_text, "--terms") if terms_text is not None else None
    seed = seed_of(project, forward) if forward is not None else None
    _refuse_unplaced(project, entry)
    framed(project, raw, question)
    services = services or Services()
    credentials = credentials or Credentials.from_environment(project)
    today, limit = today or date.today(), limit_of(project)
    step = EARLIER if seed is None else FORWARD
    planned = [_base(step, source, query or (seed.work if seed else ""), by.strip(), note,
                     limit, today, seed) for source in STEPS[step]]  # fmt: skip
    if dry_run:
        return _dry(planned, seed, services, credentials)
    _write_question(project, entry_id, question)
    return _finish(project, entry, planned, seed, _asker_for(transport, pacer, credentials),
                   services, credentials, today, set())  # fmt: skip


def replay(project: Project, entry_id: str, *, dry_run: bool = False,
           transport: Transport | None = None, services: Services | None = None,
           credentials: Credentials | None = None, pacer: Pacer | None = None,
           today: date | None = None) -> Run:  # fmt: skip
    """`references --replay ID` for a claim of novelty: the newest N1 the tool ran at each
    source and the newest N2, run again as recorded, to the day of the replay. The records are
    chosen among those the tool ran and that were asked, and the newest taken from those, so
    a later search by hand or a later `not asked` hides no run."""
    entry, _raw = _entry(project, entry_id)
    held = [read.record for read in records.read_searches(project)
            if read.problem is None and read.record["entry"] == entry_id]  # fmt: skip
    ran = [one for one in held if one.get("status", "run") in ASKED]
    newest: dict[tuple, dict] = {}
    for record in sorted(ran, key=lambda one: one["number"]):
        newest[(record["step"], record["source"])] = record
    if not newest:
        raise Refused(f"none of {entry_id}'s searches was run by the tool and answered, so "
                      f"none is run again: `references --search {entry_id}` runs them")
    services = services or Services()
    credentials = credentials or Credentials.from_environment(project)
    today = today or date.today()
    planned = [{**_base(one["step"], one["source"], one["query"], str(one.get("terms_by") or ""),
                        str(one["not_searched"]), limit_of(project), today, None),
                "filters": dict(one.get("filters") or {}), "replay_of": int(one["number"]),
                **({"seed": one["seed"]} if one.get("seed") else {})}
               for one in newest.values()]  # fmt: skip
    if dry_run:
        return _dry(planned, None, services, credentials)
    seen = {work for record in held for work in record.get("candidates") or []}
    return _finish(project, entry, planned, None, _asker_for(transport, pacer, credentials),
                   services, credentials, today, seen, replaying=True)  # fmt: skip


def _base(step: str, source: str, query: str, by: str, note: str, limit: int, today: date,
          seed: works.Wanted | None) -> dict[str, Any]:  # fmt: skip
    record: dict[str, Any] = {"step": step, "source": source, "query": query,
                              "filters": {"limit": limit},
                              "searched_on": today.isoformat(),
                              "years": {"from": None, "to": today.isoformat()},
                              "not_searched": note}  # fmt: skip
    if by:
        record["terms_by"] = by
    if seed is not None:
        record["seed"] = seed.work
    return record


def _filters(record: dict[str, Any]) -> search.Filters:
    return search.Filters(limit=int((record.get("filters") or {}).get("limit") or 10))


def _shown(record: dict[str, Any]) -> str:
    return f"{record['step']} {search.NAMES[record['source']]}"


def _ask(record: dict[str, Any], seed: works.Wanted | None, ask: sources.Ask,
         services: Services, credentials: Credentials
         ) -> tuple[dict[str, Any] | None, dict[str, works.Wanted], str]:  # fmt: skip
    """Run one search: its record, the works it kept, or why there was no answer."""
    registries, filters = services.registries, _filters(record)
    if record["step"] == FORWARD:
        return _forward(record, seed, ask, services, credentials)
    query = record["query"]
    if record["source"] == "pubmed":
        answer = search.pubmed(query, filters, ask, registries, credentials)
        sent = search.pubmed_search(query, filters, credentials, registries).shown
    elif record["source"] == "europepmc":
        answer = search.europepmc(query, filters, ask, registries)
        sent = search.europepmc_search(query, filters, registries).shown
    else:
        answer = search.openalex(query, filters, ask, registries, credentials)
        sent = search.openalex_search(query, filters, credentials, registries).shown
    return _kept(record, answer, sent)


def _forward(record: dict[str, Any], seed: works.Wanted | None, ask: sources.Ask,
             services: Services, credentials: Credentials
             ) -> tuple[dict[str, Any] | None, dict[str, works.Wanted], str]:  # fmt: skip
    """N2: the seed's OpenAlex id, where the record does not hold it yet, then the works of
    every type that cite it, newest first."""
    registries, limit = services.registries, _filters(record).limit
    work = (record.get("filters") or {}).get("cites")
    if not work:
        seed = seed or works.wanted(str(record["seed"]))
        answer = search.openalex_work(seed.doi, seed.pmid, ask, registries, credentials)
        if answer.status == sources.UNRESOLVABLE:
            return None, {}, answer.why
        work = next((hit.openalex_id for hit in answer.hits if hit.openalex_id), None)
        if work is None:
            why = f"OpenAlex holds no work {seed.work}"
            return {**record, "status": "not asked", "why": why, "candidates": []}, {}, ""
    record = {**record, "filters": {**(record.get("filters") or {}), "cites": work}}
    answer = search.openalex_citing(work, limit, ask, registries, credentials, reviews=False)
    sent = search.openalex_citing_search(work, limit, credentials, registries,
                                         reviews=False).shown  # fmt: skip
    return _kept(record, answer, sent)


def _kept(record: dict[str, Any], answer: search.Answer, sent: str
          ) -> tuple[dict[str, Any] | None, dict[str, works.Wanted], str]:  # fmt: skip
    if answer.status == sources.UNRESOLVABLE:
        return None, {}, answer.why
    found: dict[str, works.Wanted] = {}
    unidentified = 0
    for hit in answer.hits:
        work = f"doi:{hit.doi}" if hit.doi else f"pmid:{hit.pmid}" if hit.pmid else ""
        if not records.WORK.fullmatch(work):
            unidentified += 1
            continue
        held = found.get(work)
        found[work] = works.wanted(work, hit.doi or (held.doi if held else None),
                                   hit.pmid or (held.pmid if held else None))  # fmt: skip
    kept = {**record, "status": "run", "sent": sent, "hits": answer.count or 0,
            "candidates": list(found)}  # fmt: skip
    if unidentified:
        kept["unidentified"] = unidentified
    return kept, found, ""


def _finish(project: Project, entry: records.Entry, planned: list[dict[str, Any]],
            seed: works.Wanted | None, ask: sources.Ask, services: Services,
            credentials: Credentials, today: date, seen: set[str], *,
            replaying: bool = False) -> Run:  # fmt: skip
    run_ = Run()
    found: dict[str, works.Wanted] = {}
    new: list[str] = []
    kept_works = False
    for one in planned:
        record, kept, failed = _ask(one, seed, ask, services, credentials)
        if record is None:
            run_.whole = False
            run_.lines.append(f"{_shown(one)}: did not answer ({failed}); nothing recorded, "
                              "and the search is to be run again")  # fmt: skip
            continue
        _never_kept(record, credentials)
        path = records.file_search(project, {"entry": entry.id, **record})
        run_.lines.append(f"{path.stem} {_shown(one)}: {_said(record)}")
        kept_works = kept_works or (one["step"] == EARLIER and bool(record["candidates"]))
        for work, wanted in kept.items():
            found.setdefault(work, wanted)
            if work not in seen and work not in new:
                new.append(work)
    fetched = works.fetch(project, list(found.values()), ask, services.registries, credentials,
                          today)  # fmt: skip
    _said_works(run_, fetched, "the works found")
    records.ensure_gitignore(project)
    if replaying:
        run_.lines.append("new since the last run: " + (", ".join(new) if new else "none"))
    run_.lines.append(
        f"Read each work kept from its works record (`references --explain {entry.id}`); "
        "where one did what the sentence says none did, tell the author, who rewords the "
        "claim. A search by hand in a database the tool cannot reach is filed by the person "
        "who ran it, with `references --hand-search`."
    )  # fmt: skip
    if kept_works:
        run_.lines.append(
            f"N1 kept works: follow the nearest forward, `references --search {entry.id} "
            "--forward <its DOI, PMID or @key> --not-searched \"...\" --as <who>`")
    return run_


def _dry(planned: list[dict[str, Any]], seed: works.Wanted | None, services: Services,
         credentials: Credentials) -> Run:  # fmt: skip
    run_ = Run()
    registries = services.registries
    for one in planned:
        filters = _filters(one)
        if one["step"] == FORWARD:
            cites = (one.get("filters") or {}).get("cites")
            if cites:
                request = search.openalex_citing_search(cites, filters.limit, credentials,
                                                        registries, reviews=False)  # fmt: skip
                said = f"would ask {request.shown}"
            else:
                said = (f"would ask OpenAlex for {seed.work if seed else one['seed']}, then "
                        "for the works of every type citing it, newest first")  # fmt: skip
        elif one["source"] == "pubmed":
            said = f"would ask {search.pubmed_search(one['query'], filters, credentials, registries).shown}"  # noqa: E501
        elif one["source"] == "europepmc":
            said = f"would ask {search.europepmc_search(one['query'], filters, registries).shown}"
        else:
            said = f"would ask {search.openalex_search(one['query'], filters, credentials, registries).shown}"  # noqa: E501
        run_.lines.append(f"{_shown(one)}: {said}")
    run_.lines.append(f"then the works store, for each work found: {works.PLANNED}")
    run_.lines.append("nothing was sent, and nothing written; no sentence is ever sent")
    return run_


# ----------------------------------------------------------------------- a search by hand


def hand_search(project: Project, entry_id: str, path: Path, by: str | None) -> str:
    """`references --hand-search ID FILE --as PERSON`: file a search a person ran by hand, in
    a database the tool cannot reach, as a record of its own, sealed. It adds to the record
    and never counts as N1 or N2."""
    from manuscript_guard.gates.literature import _MODEL_NAME

    entry, _raw = _entry(project, entry_id)
    if by is None or not by.strip():
        raise Refused("--as names the person who ran the search")
    if _MODEL_NAME.search(by):
        raise Refused(f"{by!r} cannot file a search by hand: it is a person's word for what "
                      "they searched, and a model's search is run by the tool")
    try:
        given = read_structured(path)
    except ContractError as exc:
        raise Refused(str(exc)) from exc
    if not isinstance(given, dict):
        raise Refused(f"{path.name}: a search by hand is a mapping of its fields")
    unknown = sorted(set(given) - HAND_FIELDS)
    if unknown:
        raise Refused(f"{path.name}: {', '.join(unknown)} is no field of a search by hand; it "
                      f"holds {', '.join(sorted(HAND_FIELDS))}")
    record = {key: given[key] for key in sorted(given)}
    record["not_searched"] = not_searched_of(record.get("not_searched"))
    searched_on = str(record.get("searched_on") or "")
    try:
        if date.fromisoformat(searched_on) > date.today():
            raise Refused(f"{path.name}: searched_on {searched_on} is after today")
    except ValueError as exc:
        raise Refused(f"{path.name}: searched_on is the day it ran, as YYYY-MM-DD") from exc
    years = record.get("years") if isinstance(record.get("years"), dict) else {}
    record["years"] = {"from": None if years.get("from") is None else str(years["from"]),
                       "to": str(years.get("to") or searched_on)}  # fmt: skip
    record["candidates"] = [records.fold_work(str(one)) for one in record.get("candidates") or []]
    if record.get("seed"):
        record["seed"] = records.fold_work(str(record["seed"]))
    record = {**record, "status": "by hand", "terms_by": by.strip(), "searched_on": searched_on}
    try:
        written = records.file_search(project, {"entry": entry.id, **record})
    except ContractError as exc:
        raise Refused(str(exc)) from exc
    return (f"filed {written.stem}: a search by hand of {record.get('source')}, by "
            f"{by.strip()}. It adds to the record and never counts as {EARLIER} or "
            f"{FORWARD}, which the tool runs")


__all__ = ["EARLIER", "FORWARD", "hand_search", "not_searched_of", "replay", "run", "seed_of"]
