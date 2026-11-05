"""`references --search` and `--replay`: the fixed searches for one claim, run and recorded.

The reader (an agent through the `literature-currency` skill, a model, a person) writes the
claim as a question and the terms, and says who wrote them (`--as`). Nothing is derived from
the sentence, from MeSH or from a list of keywords. The tool then runs every search of the
protocol, at every source, and records each one sealed, numbered and written once
(`literature/currency/searches/<id>-<n>.yaml`):

- S1, forward from the cited work: PubMed's "Update in" and "Comment in" links, read from
  the cited work's lookup record and not asked again; and the reviews OpenAlex lists as
  citing it, newest first, by its OpenAlex id, which its DOI finds.
- S2, syntheses on the question: PubMed (`systematic review[pt]`) and Europe PMC
  (`PUB_TYPE:"systematic review"`) with the terms. OpenAlex types no systematic review, and
  is recorded as not asked, with the reason.
- S3, primary studies published from the cutoff on, at all three, by each one's finest
  date filter. The cutoff is the later of the cited work's publication date and the newest
  search end date a filed reading gives for a synthesis an S2 search found (R4); before any
  reading, the cited work's date. Syntheses are not filtered out: the rules deal with them.
- S4, ongoing trials: ClinicalTrials.gov's studies still under way for the terms, recorded
  as pending with their NCT numbers, never as candidates.
- S8, evidence against the sentence: a query of the reader's own (`--against`), run as S2
  and as S3.

The works store is then filled for the cited work and every candidate (`works.py`).
`--replay` runs each recorded search again with its query, filters and cutoff as recorded,
writes new records, refreshes the works records and lists the works new since the last run.

What leaves the machine: the terms, the identifiers of the cited work and of the works
found. The question is not sent, and no sentence of the manuscript is.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import records, works
from manuscript_guard.currency.command import Refused
from manuscript_guard.lookup import registries as trials_registry
from manuscript_guard.lookup import search, sources
from manuscript_guard.lookup.http import Transport, default_transport
from manuscript_guard.lookup.run import CROSSREF_LIST, Credentials, Pacer, _asker, _never_kept

#: How many works each source keeps at each step, unless `references.search_limit` says.
LIMIT = 10
#: The steps this version runs, in order, and the sources of each.
STEPS = {"S1": ("pubmed", "openalex"), "S2": search.REGISTRIES, "S3": search.REGISTRIES,
         "S4": ("clinicaltrials",)}  # fmt: skip
#: The kinds of work S2 asks each registry for.
SYNTHESES = ("systematic-review",)
#: PubMed's links that point forward from the cited work to a later one on it (S1).
FORWARD = ("Update in", "Comment in")
NAMES = {**search.NAMES, "clinicaltrials": "ClinicalTrials.gov"}
#: The searches a replay runs again: those that were asked.
ASKED = records.ASKED
#: Why S3 has no date to ask from, where the cited work's record could not be fetched.
UNFETCHED = ("the cited work's works record could not be fetched, so there is no date to "
             "ask from")  # fmt: skip


@dataclass(frozen=True)
class Services:
    """Where each is asked. The tests point every one at a loopback server."""

    registries: search.Services = field(default_factory=search.Services)
    clinicaltrials: str = trials_registry.Services().clinicaltrials


@dataclass(frozen=True)
class Planned:
    """One search to run: a step at a source, with its query and filters."""

    step: str
    source: str
    query: str
    filters: dict[str, Any] = field(default_factory=dict)
    as_step: str | None = None
    cutoff: dict[str, str] | None = None
    #: Why it is not asked, where it is not.
    why: str = ""
    terms_by: str | None = None
    replay_of: int | None = None
    #: Why it cannot be asked now, though it is to be: no record is written, and the run is
    #: not whole (round 1 of #530: a cited work not fetched was filed as "not asked").
    unanswered: str = ""
    #: A dry run's S3, asked from the date the cited work's fetch, run first, will give.
    dated_by_fetch: bool = False

    @property
    def shown(self) -> str:
        return f"{self.step}{f' as {self.as_step}' if self.as_step else ''} {NAMES[self.source]}"


@dataclass
class Run:
    """What one `--search` or `--replay` did, said as it is to be printed."""

    lines: list[str] = field(default_factory=list)
    #: False where a source or a work did not answer, so that the run is to be asked again.
    whole: bool = True


@dataclass(frozen=True)
class Claim:
    """The entry and its cited work, as a search needs them."""

    entry: records.Entry
    raw: dict[str, Any]
    cited: works.Wanted
    fields: dict[str, str]
    lookup: dict[str, Any] | None
    lookup_reason: str = ""


# ----------------------------------------------------------------------------- the claim


def _claim(project: Project, entry_id: str) -> Claim:
    from manuscript_guard.currency.command import _entry_of
    from manuscript_guard.gates.currency import _bib
    from manuscript_guard.gates.identifiers import doi_of, pmid_of
    from manuscript_guard.literature.lookups import read_record
    from manuscript_guard.lookup import run as lookup

    _document, raw = _entry_of(project, entry_id)
    entry = records._entry(raw)
    fields = _bib(project).get(entry.citekey)
    cited = records.work_id(fields)
    if fields is None or cited is None:
        raise Refused(f"@{entry.citekey} has no DOI and no PMID in references.bib, and the "
                      "works store keys a work by one of them")  # fmt: skip
    planned = next((one for one in lookup.plan(project) if one.citekey == entry.citekey), None)
    reason = ("the manuscript does not cite it" if planned is None
              else "" if planned.skipped == "up to date"
              else planned.again or planned.skipped)  # fmt: skip
    record = read_record(project, entry.citekey) if not reason else None
    by_doi = ((record or {}).get("sources") or {}).get("pubmed_by_doi") or {}
    wanted = works.wanted(cited, doi_of(fields), pmid_of(fields),
                          by_doi.get("pmid") if by_doi.get("status") == sources.FOUND
                          else None)  # fmt: skip
    return Claim(entry, raw, wanted, fields, record, reason)


def _refuse_unplaced(project: Project, claim: Claim) -> None:
    """Refuse to search for an entry no sentence of the manuscript reads as: its claim is
    put back on its sentence first (round 1 of #530: the refusal said to run `lookup`)."""
    from manuscript_guard.currency.survey import survey

    found, _report = survey(project)
    if claim.entry.id not in found.placed:
        key, entry = claim.entry.citekey, claim.entry.id
        raise Refused(f"{entry} is unplaced: no sentence citing @{key} reads as it does. Put "
                      f"it on its sentence first, with `manuscript-guard references --mark "
                      f"\"<words>\" @{key} --id {entry}`")  # fmt: skip


def _refuse_without_lookup(claim: Claim) -> None:
    if claim.lookup_reason:
        raise Refused(
            f"@{claim.entry.citekey}'s lookup record is not current ({claim.lookup_reason}): "
            "run `manuscript-guard lookup` first, since the search reads PubMed's links from "
            "it"
        )


def limit_of(project: Project) -> int:
    """`references.search_limit` in paper.yaml, or `LIMIT`."""
    value = (project.setting("references") or {}).get("search_limit")
    return value if isinstance(value, int) and not isinstance(value, bool) else LIMIT


def terms(text: str | None, flag: str) -> str:
    """The terms as they are sent, held to `search`'s rule for a query."""
    if text is None:
        raise Refused(f"{flag} names the terms to search for")
    query, problem = search.folded_query(text)
    if problem:
        raise Refused(f"{flag}: {problem}")
    return query


def framed(project: Project, raw: dict[str, Any], question: str | None) -> dict[str, Any]:
    """The entry with its question written (rule F1). A question already written that differs
    is replaced only while the entry has no searches and no readings: they were made for
    it, and a person who frames the claim again edits it by hand."""
    if question is None:
        return raw
    folded = " ".join(question.split())
    if not folded:
        raise Refused("--question writes the claim as a question, and it is empty")
    if raw.get("question") in (None, folded):
        return {**raw, "question": folded}
    entry = str(raw["id"])
    held = [read for read in [*records.read_searches(project), *records.read_readings(project)]
            if (read.record or {}).get("entry") == entry]  # fmt: skip
    if held:
        raise Refused(f"{entry} was searched or read for the question {raw['question']!r}: the "
                      "command does not frame it again; edit `question` in "
                      "literature/currency.yaml by hand if it is to change")  # fmt: skip
    return {**raw, "question": folded}


def _write_question(project: Project, entry_id: str, question: str | None) -> None:
    if question is None:
        return
    document, _report = records.read_document(project)
    entries = [framed(project, dict(raw), question) if raw["id"] == entry_id else dict(raw)
               for raw in (document or {}).get("entries") or []]  # fmt: skip
    records.write_document(project, {**document, "entries": entries})


# ---------------------------------------------------------------------------- the cutoff


def cutoff(project: Project, claim: Claim) -> dict[str, str] | None:
    """The date S3 asks from, and what gave it: the later of the cited work's publication
    date in its works record and the newest search end date a filed reading gives for a
    synthesis an S2 search of the entry found (R4). Dates of any precision compare as the
    first day each names, so "2021" is before "2021-03"."""
    held = records.read_work(project, claim.cited.work)
    published = (held.record or {}).get("published") if held and not held.problem else None
    best = (published, f"the cited work's publication date, in its works record of "
            f"{held.record['fetched_on']}") if published else None  # fmt: skip
    syntheses = {work for read in records.read_searches(project)
                 if read.problem is None and read.record["entry"] == claim.entry.id
                 and "S2" in (read.record["step"], read.record.get("as_step"))
                 for work in read.record["candidates"]}  # fmt: skip
    for read in records.read_readings(project):
        record = read.record
        if read.problem or not record or record["entry"] != claim.entry.id:
            continue
        for one in record.get("candidates") or []:
            end = (one.get("search_end") or {}).get("value")
            if end and one["work"] in syntheses and (best is None or _later(end, best[0])):
                best = (str(end), f"the search end date of {one['work']}, as "
                        f"{record['reader']}'s reading {record.get('number')} gives it")
    return {"date": best[0], "from": best[1]} if best else None


def _later(one: str, other: str) -> bool:
    return search.first_day(one) > search.first_day(other)


# -------------------------------------------------------------------------- the planning


def planned(claim: Claim, query: str, against: str | None, by: str, limit: int,
            cut: dict[str, str] | None, without_cut: str = "") -> list[Planned]:  # fmt: skip
    """Every search of the protocol for the claim, in order. `without_cut` says what S3 is
    where there is no cutoff: "" not asked, since the cited work's date is not known;
    `UNFETCHED` unanswered; "later" for a dry run, dated by the fetch it would run first."""
    out = [_s1_pubmed(claim, by, limit), _s1_openalex(claim, by, limit)]
    for step, words, as_step in (("S2", query, None), ("S3", query, None), ("S4", query, None),
                                 ("S8", against, "S2"), ("S8", against, "S3")):  # fmt: skip
        if words is None:
            continue
        kind = as_step or step
        for source in STEPS[kind]:
            out.append(_planned(step, source, words, by, limit, cut, as_step, without_cut))
    return out


def _planned(step: str, source: str, words: str, by: str, limit: int,
             cut: dict[str, str] | None, as_step: str | None = None,
             without_cut: str = "") -> Planned:  # fmt: skip
    kind = as_step or step
    one = Planned(step, source, words, {"limit": limit}, as_step=as_step, terms_by=by)
    if kind == "S2":
        filters = search.Filters(types=SYNTHESES, limit=limit)
        why = search.asks(filters)[source]
        return replace(one, filters={"types": list(SYNTHESES), "limit": limit}, why=why)
    if kind == "S3":
        if cut is None and without_cut == "later":
            return replace(one, dated_by_fetch=True)
        if cut is None and without_cut:
            return replace(one, unanswered=without_cut)
        if cut is None:
            return replace(one, why="the cited work's publication date is not known, so there "
                           "is no date to ask from")  # fmt: skip
        return replace(one, filters={"from": cut["date"], "limit": limit}, cutoff=cut)
    return one


def _s1_pubmed(claim: Claim, by: str, limit: int) -> Planned:
    pmid = _cited_pmid(claim)
    one = Planned("S1", "pubmed", f"links of PMID {pmid}" if pmid else claim.cited.work,
                  {"links": list(FORWARD), "limit": limit}, terms_by=by)  # fmt: skip
    if not pmid:
        return replace(one, why=f"PubMed holds no record of the cited work, by its lookup of "
                       f"{(claim.lookup or {}).get('looked_up_on')}")  # fmt: skip
    return one


def _s1_openalex(claim: Claim, by: str, limit: int) -> Planned:
    one = Planned("S1", "openalex", claim.cited.work,
                  {"type": "review", "sort": "newest", "limit": limit}, terms_by=by)
    if not claim.cited.doi:
        return replace(one, why="the cited work has no DOI, by which OpenAlex is asked for it")
    return one


def _cited_pmid(claim: Claim) -> str | None:
    said = (claim.lookup or {}).get("sources") or {}
    for name in ("pubmed", "pubmed_by_doi"):
        answer = said.get(name) or {}
        if answer.get("status") == sources.FOUND:
            return claim.cited.pmid or answer.get("pmid")
    return None


def _from_record(record: dict[str, Any]) -> Planned:
    """A recorded search, to be run again as it was."""
    return Planned(record["step"], record["source"], record["query"],
                   dict(record.get("filters") or {}), as_step=record.get("as_step"),
                   cutoff=record.get("cutoff"), terms_by=record.get("terms_by"),
                   replay_of=int(record["number"]))  # fmt: skip


# ----------------------------------------------------------------------------- the asking


@dataclass
class Asked:
    """One search's answer, as its record says it, and the works it kept with their
    identifiers; or why there was no answer."""

    planned: Planned
    record: dict[str, Any] | None = None
    found: dict[str, works.Wanted] = field(default_factory=dict)
    failed: str = ""


def _filters(one: Planned) -> search.Filters:
    return search.Filters(types=tuple(one.filters.get("types") or ()),
                          from_date=one.filters.get("from"),
                          limit=int(one.filters.get("limit") or LIMIT))  # fmt: skip


def requests(one: Planned, claim: Claim, services: Services,
             credentials: Credentials) -> list[str]:  # fmt: skip
    """What running one search would ask, in words, for a dry run."""
    registries, filters = services.registries, _filters(one)
    if one.why:
        return [f"not asked: {one.why}"]
    if one.dated_by_fetch:
        return ["would ask from the cited work's publication date, which its works record, "
                "fetched first, gives"]  # fmt: skip
    if one.step == "S1" and one.source == "pubmed" and claim.lookup is None:
        # Round 1 of #530: a replay's dry run read the record it does not have.
        return [f"would not be read: @{claim.entry.citekey}'s lookup record is not current "
                f"({claim.lookup_reason}); run `manuscript-guard lookup`"]  # fmt: skip
    if one.step == "S1" and one.source == "pubmed":
        return [f"would read the {', '.join(FORWARD)} links of literature/lookups/"
                f"{claim.entry.citekey}.yaml (looked up on {claim.lookup.get('looked_up_on')}); "
                "nothing is asked"]  # fmt: skip
    if one.step == "S1":
        if one.filters.get("cites"):
            request = search.openalex_citing_search(one.filters["cites"], filters.limit,
                                                    credentials, registries)  # fmt: skip
            return [f"would ask {request.shown}"]
        return [f"would ask OpenAlex for the cited work by its DOI, {claim.cited.doi}, then for "
                "the reviews citing it, newest first"]  # fmt: skip
    if one.source == "clinicaltrials":
        request = trials_registry.clinicaltrials_search_request(one.query, filters.limit,
                                                                services.clinicaltrials)
        return [f"would ask {request.shown}"]
    request = {
        "pubmed": lambda: search.pubmed_search(one.query, filters, credentials, registries),
        "europepmc": lambda: search.europepmc_search(one.query, filters, registries),
        "openalex": lambda: search.openalex_search(one.query, filters, credentials, registries),
    }[one.source]()
    return [f"would ask {request.shown}"]


def ask_one(one: Planned, claim: Claim, ask: sources.Ask, services: Services,
            credentials: Credentials, today: date) -> Asked:  # fmt: skip
    """Run one search and read its answer into the terms of its record."""
    base = {"step": one.step, **({"as_step": one.as_step} if one.as_step else {}),
            "source": one.source, "query": one.query,
            **({"terms_by": one.terms_by} if one.terms_by else {}),
            "filters": one.filters, **({"cutoff": one.cutoff} if one.cutoff else {}),
            **({"replay_of": one.replay_of} if one.replay_of else {}),
            "searched_on": today.isoformat()}  # fmt: skip
    if one.why:
        return Asked(one, {**base, "status": "not asked", "why": one.why, "candidates": []})
    if one.unanswered:
        return Asked(one, failed=one.unanswered)
    if one.step == "S1" and one.source == "pubmed":
        return _links(one, claim, base)
    if one.source == "clinicaltrials":
        said = trials_registry.clinicaltrials_search(one.query, _filters(one).limit, ask,
                                                     services.clinicaltrials)  # fmt: skip
        if said["status"] == sources.UNRESOLVABLE:
            return Asked(one, failed=said["why"])
        sent = trials_registry.clinicaltrials_search_request(one.query, _filters(one).limit,
                                                             services.clinicaltrials).shown
        return Asked(one, {**base, "status": "pending", "sent": sent, "hits": said["count"],
                           "candidates": [], "trials": said.get("trials", [])})  # fmt: skip
    if one.step == "S1":
        return _citing(one, claim, ask, services, credentials, base)
    filters, registries = _filters(one), services.registries
    if one.source == "pubmed":
        answer = search.pubmed(one.query, filters, ask, registries, credentials)
        sent = search.pubmed_search(one.query, filters, credentials, registries).shown
    elif one.source == "europepmc":
        answer = search.europepmc(one.query, filters, ask, registries)
        sent = search.europepmc_search(one.query, filters, registries).shown
    else:
        answer = search.openalex(one.query, filters, ask, registries, credentials)
        sent = search.openalex_search(one.query, filters, credentials, registries).shown
    return _kept(one, claim, base, answer, sent)


def _kept(one: Planned, claim: Claim, base: dict[str, Any], answer: search.Answer,
          sent: str) -> Asked:  # fmt: skip
    if answer.status == sources.UNRESOLVABLE:
        return Asked(one, failed=answer.why)
    found, unidentified = _identified(answer.hits, claim)
    record = {**base, "status": "run", "sent": sent, "hits": answer.count or 0,
              "candidates": list(found)}  # fmt: skip
    if unidentified:
        record["unidentified"] = unidentified
    return Asked(one, record, found)


def _identified(hits: tuple[search.Hit, ...] | list[search.Hit],
                claim: Claim) -> tuple[dict[str, works.Wanted], int]:  # fmt: skip
    """The works of an answer by their store ids, the cited work left out, and how many had
    no identifier a record can hold."""
    found: dict[str, works.Wanted] = {}
    unidentified = 0
    for hit in hits:
        work = (f"doi:{hit.doi}" if hit.doi else f"pmid:{hit.pmid}" if hit.pmid else None)
        if work is None or not records.WORK.fullmatch(work):
            unidentified += 1
            continue
        if _is_cited(claim, hit.doi, hit.pmid):
            continue
        held = found.get(work)
        found[work] = works.wanted(work, hit.doi or (held.doi if held else None),
                                   hit.pmid or (held.pmid if held else None))  # fmt: skip
    return found, unidentified


def _is_cited(claim: Claim, doi: str | None, pmid: str | None) -> bool:
    cited = claim.cited
    return bool((doi and doi == cited.doi) or (pmid and pmid in (cited.pmid, cited.types_pmid)))


def _links(one: Planned, claim: Claim, base: dict[str, Any]) -> Asked:
    """S1 at PubMed: the forward links the cited work's lookup record holds."""
    if claim.lookup is None:
        return Asked(one, failed=f"@{claim.entry.citekey}'s lookup record is not current "
                     f"({claim.lookup_reason}): run `manuscript-guard lookup`")  # fmt: skip
    said = claim.lookup.get("sources") or {}
    answer = next((said[name] for name in ("pubmed", "pubmed_by_doi")
                   if (said.get(name) or {}).get("status") == sources.FOUND), None)  # fmt: skip
    if answer is None:
        why = (f"PubMed holds no record of the cited work, by its lookup of "
               f"{claim.lookup.get('looked_up_on')}")  # fmt: skip
        return Asked(one, {**base, "query": claim.cited.work, "status": "not asked",
                           "why": why, "candidates": []})  # fmt: skip
    links = [link for link in answer.get("links") or []
             if link.get("type") in FORWARD and link.get("pmid")]  # fmt: skip
    hits = [search.Hit("pubmed", n, pmid=link["pmid"]) for n, link in enumerate(links, 1)]
    found, unidentified = _identified(hits, claim)
    record = {**base, "status": "run", "searched_on": claim.lookup["looked_up_on"],
              "from_lookup": {"record": f"literature/lookups/{claim.entry.citekey}.yaml",
                              "looked_up_on": claim.lookup["looked_up_on"]},
              "hits": len(links), "candidates": list(found)}  # fmt: skip
    if unidentified:
        record["unidentified"] = unidentified
    return Asked(one, record, found)


def _citing(one: Planned, claim: Claim, ask: sources.Ask, services: Services,
            credentials: Credentials, base: dict[str, Any]) -> Asked:  # fmt: skip
    """S1 at OpenAlex: the cited work's OpenAlex id by its DOI, where the record does not
    hold it yet, then the reviews citing it, newest first."""
    registries, limit = services.registries, _filters(one).limit
    work = one.filters.get("cites")
    if not work:
        answer = search.openalex_by_doi([claim.cited.doi], ask, registries, credentials)
        if answer.status == sources.UNRESOLVABLE:
            return Asked(one, failed=answer.why)
        work = next((hit.openalex_id for hit in answer.hits
                     if hit.doi == claim.cited.doi and hit.openalex_id), None)  # fmt: skip
        if work is None:
            why = f"OpenAlex holds no work with the cited work's DOI, {claim.cited.doi}"
            return Asked(one, {**base, "status": "not asked", "why": why, "candidates": []})
    filters = {**one.filters, "cites": work}
    answer = search.openalex_citing(work, limit, ask, registries, credentials)
    sent = search.openalex_citing_search(work, limit, credentials, registries).shown
    return _kept(replace(one, filters=filters), claim, {**base, "filters": filters}, answer,
                 sent)  # fmt: skip


# ------------------------------------------------------------------------------- the runs


def _asker_for(transport: Transport | None, pacer: Pacer | None,
               credentials: Credentials) -> sources.Ask:  # fmt: skip
    from manuscript_guard.lookup.registrations import INTERVALS

    pacer = pacer or Pacer(intervals={"eutils.ncbi.nlm.nih.gov": 0.34, CROSSREF_LIST: 1.0,
                                      **INTERVALS})  # fmt: skip
    return _asker(transport or default_transport, pacer, credentials)


def run_search(project: Project, entry_id: str, *, terms_text: str | None, by: str | None,
               against_text: str | None = None, question: str | None = None,
               dry_run: bool = False, transport: Transport | None = None,
               services: Services | None = None, credentials: Credentials | None = None,
               pacer: Pacer | None = None, today: date | None = None) -> Run:  # fmt: skip
    """`references --search <id>`: every search of the protocol for the entry, recorded."""
    query = terms(terms_text, "--terms")
    against = terms(against_text, "--against") if against_text is not None else None
    if by is None or not by.strip():
        raise Refused("--as names who wrote the terms: a person, or the model that wrote them")
    claim = _claim(project, entry_id)
    _refuse_unplaced(project, claim)
    _refuse_without_lookup(claim)
    framed(project, claim.raw, question)
    services = services or Services()
    credentials = credentials or Credentials.from_environment(project)
    limit, today = limit_of(project), today or date.today()
    if dry_run:
        return _dry(project, claim, planned(claim, query, against, by.strip(), limit,
                                            cutoff(project, claim), "later"),
                    services, credentials)  # fmt: skip
    _write_question(project, entry_id, question)
    ask = _asker_for(transport, pacer, credentials)
    run = Run()
    cited = works.fetch(project, [claim.cited], ask, services.registries, credentials, today)
    _said_works(run, cited, "the cited work")
    unfetched = UNFETCHED if cited[0].record is None and "not fetched" in cited[0].why else ""
    searches = planned(claim, query, against, by.strip(), limit, cutoff(project, claim),
                       unfetched)  # fmt: skip
    return _finish(project, claim, run, searches, ask, services, credentials, today, set())


def replay(project: Project, entry_id: str, *, dry_run: bool = False,
           transport: Transport | None = None, services: Services | None = None,
           credentials: Credentials | None = None, pacer: Pacer | None = None,
           today: date | None = None) -> Run:  # fmt: skip
    """`references --replay <id>`: each search last recorded for the entry, at each step and
    source, run again as it was recorded."""
    claim = _claim(project, entry_id)
    held = [read.record for read in records.read_searches(project)
            if read.problem is None and read.record["entry"] == entry_id]  # fmt: skip
    if not held:
        raise Refused(f"{entry_id} has no recorded search to run again: run "
                      f"`references --search {entry_id}` first")  # fmt: skip
    newest: dict[tuple, dict] = {}
    for record in sorted(held, key=lambda one: one["number"]):
        newest[(record["step"], record.get("as_step"), record["source"])] = record
    again = [_from_record(record) for record in newest.values()
             if record.get("status", "run") in ASKED]  # fmt: skip
    if not again:
        raise Refused(f"none of {entry_id}'s recorded searches was asked, so none is run "
                      f"again: `references --search {entry_id}` frames them afresh")
    services = services or Services()
    credentials = credentials or Credentials.from_environment(project)
    if dry_run:
        return _dry(project, claim, again, services, credentials)
    ask = _asker_for(transport, pacer, credentials)
    run = Run()
    today = today or date.today()
    cited = works.fetch(project, [claim.cited], ask, services.registries, credentials, today)
    _said_works(run, cited, "the cited work")
    seen = {work for record in held for work in record["candidates"]}
    return _finish(project, claim, run, again, ask, services, credentials, today, seen,
                   replaying=True)  # fmt: skip


def _finish(project: Project, claim: Claim, run: Run, searches: list[Planned],
            ask: sources.Ask, services: Services, credentials: Credentials, today: date,
            seen: set[str], *, replaying: bool = False) -> Run:  # fmt: skip
    found: dict[str, works.Wanted] = {}
    new: list[str] = []
    for one in searches:
        asked = ask_one(one, claim, ask, services, credentials, today)
        if asked.record is None:
            run.whole = False
            run.lines.append(f"{one.shown}: did not answer ({asked.failed}); nothing recorded, "
                             "and the search is to be run again")  # fmt: skip
            continue
        _never_kept(asked.record, credentials)
        path = records.file_search(project, {"entry": claim.entry.id, **asked.record})
        run.lines.append(f"{path.stem} {one.shown}: {_said(asked.record)}")
        for work, wanted in asked.found.items():
            held = found.get(work)
            found[work] = wanted if held is None else works.wanted(
                work, held.doi or wanted.doi, held.pmid or wanted.pmid)  # fmt: skip
            if work not in seen and work not in new:
                new.append(work)
    fetched = works.fetch(project, list(found.values()), ask, services.registries,
                          credentials, today)  # fmt: skip
    _said_works(run, fetched, "the works found")
    records.ensure_gitignore(project)
    if replaying:
        run.lines.append("new since the last run: " + (", ".join(new) if new else "none"))
    run.lines.append(
        "Read each candidate from its works record (`references --explain "
        f"{claim.entry.id}`), and file each reading with `references --reading`; the rules "
        "decide from two"
    )  # fmt: skip
    return run


def _said(record: dict[str, Any]) -> str:
    status = record.get("status", "run")
    if status == "not asked":
        return f"not asked: {record['why']}"
    if status == "pending":
        listed = ", ".join(record["trials"]) or "none"
        return f"{record['hits']} ongoing, pending: {listed}"
    said = f"{record['hits']} matched, {len(record['candidates'])} kept"
    if record.get("from_lookup"):
        said += f" (from the lookup of {record['from_lookup']['looked_up_on']})"
    if record.get("unidentified"):
        said += f", {record['unidentified']} with no DOI or PMID left out"
    return said


def _said_works(run: Run, fetched: list[works.Fetched], what: str) -> None:
    written = [one for one in fetched if one.record is not None]
    if fetched:
        run.lines.append(f"works store, {what}: {len(written)} of {len(fetched)} written")
    for one in fetched:
        if one.record is None:
            run.whole = run.whole and "not fetched" not in one.why
            run.lines.append(f"  {one.work}: {one.why}")


def _dry(project: Project, claim: Claim, searches: list[Planned], services: Services,
         credentials: Credentials) -> Run:  # fmt: skip
    run = Run()
    run.lines.append(f"works store, the cited work {claim.cited.work}: would be fetched first")
    for one in searches:
        for line in requests(one, claim, services, credentials):
            run.lines.append(f"{one.shown}: {line}")
    run.lines.append(f"then the works store, for each work found: {works.PLANNED}")
    run.lines.append("nothing was sent, and nothing written; the question is never sent")
    del project
    return run


__all__ = ["LIMIT", "Planned", "Run", "Services", "cutoff", "framed", "limit_of", "planned",
           "replay", "run_search", "terms"]

