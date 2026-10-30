"""`manuscript-guard search`: works a claim could cite, asked of open registries.

Three registries are searched, each with the query as typed and the filters in its own
terms: PubMed (ESearch, then ESummary for the PMIDs it found) and Europe PMC for biomedical
work, OpenAlex for every field. Then two smaller questions, about the works found: OpenAlex,
by DOI, about the ones it did not return, for whether each is retracted, how often it is
cited and where an open copy is; Crossref, about each preprint, for the published version it
became. Crossref's own search is not used: it matches citation strings, and a topic finds
little there.

Nothing here writes a file or decides anything. Each registry's answer ends `found`,
`absent` or `unresolvable`, as the lookup reads a reference's, or `not asked` where the
filters name a kind of work the registry does not type. The shapes were read from the
services' documentation and from live answers on 2026-10-20 (DESIGN.md, "A reference is
proposed from a registry, and chosen by the author").
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from manuscript_guard.lookup import sources
from manuscript_guard.lookup.http import Request
from manuscript_guard.lookup.run import Credentials
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
    _year,
    unresolvable,
)

NOT_ASKED = "not asked"
REGISTRIES = ("pubmed", "europepmc", "openalex")
NAMES = {"pubmed": "PubMed", "europepmc": "Europe PMC", "openalex": "OpenAlex",
         "crossref": "Crossref"}  # fmt: skip
#: The most a registry is asked for: a search past that many is a reading list, not a
#: proposal for one claim.
MAX_LIMIT = 50

#: The kinds of work a search can be narrowed to, and how each registry is asked for them.
#: OpenAlex types a review and a preprint and nothing finer; "cohort" is MeSH's Cohort
#: Studies, an indexing term and not a publication type.
TYPES = ("review", "systematic-review", "meta-analysis", "guideline", "rct", "cohort",
         "preprint")  # fmt: skip
TYPE_NAMES = {
    "review": "review",
    "systematic-review": "systematic review",
    "meta-analysis": "meta-analysis",
    "guideline": "guideline",
    "rct": "randomized controlled trial",
    "cohort": "cohort study",
    "preprint": "preprint",
}
PUBMED_TYPES = {
    "review": "review[pt]",
    "systematic-review": "systematic review[pt]",
    "meta-analysis": "meta-analysis[pt]",
    "guideline": "guideline[pt] OR practice guideline[pt]",
    "rct": "randomized controlled trial[pt]",
    "cohort": "cohort studies[mh]",
    "preprint": "preprint[pt]",
}
EUROPEPMC_TYPES = {
    "review": 'PUB_TYPE:"review"',
    "systematic-review": 'PUB_TYPE:"systematic review"',
    "meta-analysis": 'PUB_TYPE:"meta-analysis"',
    "guideline": 'PUB_TYPE:"guideline" OR PUB_TYPE:"practice guideline"',
    "rct": 'PUB_TYPE:"randomized controlled trial"',
    "cohort": 'MESH:"Cohort Studies"',
    "preprint": "SRC:PPR",
}
OPENALEX_TYPES = {"review": "review", "preprint": "preprint"}

#: ISO 639-1, as OpenAlex writes a language, and the MEDLINE code PubMed and Europe PMC
#: write for it.
LANGUAGES = {
    "ar": "ara", "cs": "cze", "da": "dan", "de": "ger", "el": "gre", "en": "eng",
    "es": "spa", "fi": "fin", "fr": "fre", "he": "heb", "hu": "hun", "it": "ita",
    "ja": "jpn", "ko": "kor", "nl": "dut", "no": "nor", "pl": "pol", "pt": "por",
    "ru": "rus", "sv": "swe", "tr": "tur", "zh": "chi",
}  # fmt: skip

#: What a registry calls a kind of work, folded, and the one word it is shown as. A type
#: not here ("Journal Article", "research-article", "Research Support, ...") says nothing
#: of the evidence and is not shown.
KINDS = {
    "guideline": "guideline",
    "practice guideline": "guideline",
    "consensus development conference": "consensus statement",
    "systematic review": "systematic review",
    "meta analysis": "meta-analysis",
    "network meta analysis": "meta-analysis",
    "review": "review",
    "review article": "review",
    "randomized controlled trial": "randomized controlled trial",
    "clinical trial": "clinical trial",
    "observational study": "observational study",
    "case reports": "case report",
    "preprint": "preprint",
    "editorial": "editorial",
    "comment": "comment",
    "letter": "letter",
    "published erratum": "erratum",
    "erratum": "erratum",
    "retraction of publication": "retraction notice",
    "retraction": "retraction notice",
    "expression of concern": "notice of concern",
    "book": "book",
    "book chapter": "book chapter",
    "dataset": "dataset",
    "dissertation": "dissertation",
    "report": "report",
}
ORDER = tuple(dict.fromkeys(KINDS.values()))

PUBMED_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{}/"
EUROPEPMC_URL = "https://europepmc.org/article/PMC/{}"
OPENALEX_SELECT = (
    "id,doi,title,display_name,publication_year,type,language,is_retracted,cited_by_count,"
    "open_access,primary_location,ids,authorships"
)
#: An open copy Europe PMC lists: open access, or free to read.
OPEN = frozenset({"OA", "F"})


@dataclass(frozen=True)
class Filters:
    since: int | None = None
    types: tuple[str, ...] = ()
    #: ISO 639-1.
    language: str | None = None
    limit: int = 10


@dataclass(frozen=True)
class Services:
    """Where each is asked. The tests point every one at a loopback server."""

    esearch: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    esummary: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    europepmc: str = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    openalex: str = "https://api.openalex.org/works"
    crossref: str = "https://api.crossref.org/works/"


@dataclass(frozen=True)
class Hit:
    """One work as one registry gave it. `rank` is its place in that registry's answer to
    the search, and 0 for a work asked about by its DOI after the search."""

    registry: str
    rank: int
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    title: str | None = None
    year: int | None = None
    journal: str | None = None
    first_author: str | None = None
    authors: int = 0
    kinds: tuple[str, ...] = ()
    language: str | None = None
    #: None where the registry says nothing of it.
    retracted: bool | None = None
    concern: bool = False
    #: A later version the registry links: {"pmid" or "doi", "reference"}.
    later: tuple[dict[str, str], ...] = ()
    open_copy: str | None = None
    cited_by: int | None = None


@dataclass(frozen=True)
class Answer:
    status: str
    hits: tuple[Hit, ...] = ()
    #: How many works the registry matched, of which `hits` are the first.
    count: int | None = None
    why: str = ""
    #: Words of the query the registry did not use, where it says so.
    dropped: tuple[str, ...] = ()


def _unresolvable(why: str) -> Answer:
    return Answer(UNRESOLVABLE, why=why)


def _said(answer: Any) -> Answer | None:
    """The answer that a failed request or a status alone gives, or None to read further."""
    if isinstance(answer, dict):
        return _unresolvable(answer["why"])
    said = _status_only(answer)
    return _unresolvable(said["why"]) if said else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _clean(value: Any) -> str | None:
    """A title or a name without the markup a registry leaves in it."""
    text = _text(value)
    return _text(html.unescape(re.sub(r"<[^>]+>", "", text))) if text else None


def _kinds(words: Any) -> tuple[str, ...]:
    found = set()
    for word in words if isinstance(words, list) else [words]:
        if isinstance(word, str):
            folded = " ".join(word.casefold().replace("-", " ").split(",")[0].split())
            if folded in KINDS:
                found.add(KINDS[folded])
    return tuple(k for k in ORDER if k in found)


def _doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    doi = re.sub(r"^\s*(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I)
    return doi.lower() if doi.startswith("10.") else None


def _digits(value: Any) -> str | None:
    """A PMID: digits, from a number, a string or the end of a PubMed URL."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    found = re.search(r"(\d+)/?\s*$", value)
    return found.group(1) if found else None


def _cited_doi(reference: str) -> str | None:
    """The DOI at the end of a reference as NLM writes one: "... doi: 10.1/x."."""
    found = re.search(r"doi:\s*(10\.\S+?)\.?\s*$", reference, flags=re.I)
    return found.group(1).lower() if found else None


def _later(pmid: Any, reference: Any) -> dict[str, str] | None:
    pmid = _digits(pmid)
    text = _text(reference) or ""
    doi = _cited_doi(text)
    if not pmid and not doi:
        return None
    return {k: v for k, v in (("pmid", pmid), ("doi", doi), ("reference", text)) if v}


# -------------------------------------------------------------------------------- PubMed


def pubmed_term(query: str, filters: Filters) -> str:
    parts = [f"({query})"]
    if filters.types:
        parts.append("(" + " OR ".join(PUBMED_TYPES[t] for t in filters.types) + ")")
    if filters.language:
        parts.append(f"{LANGUAGES[filters.language]}[la]")
    return " AND ".join(parts)


def _eutils(base: str, params: dict[str, str], credentials: Credentials) -> Request:
    return Request(
        base,
        params={"db": "pubmed", **params, "retmode": "json", "tool": "manuscript-guard"},
        secret={"email": credentials.contact or "", "api_key": credentials.ncbi_key or ""},
    )


def pubmed_search(query: str, filters: Filters, credentials: Credentials,
                  services: Services) -> Request:  # fmt: skip
    params = {"term": pubmed_term(query, filters), "retmax": str(filters.limit),
              "sort": "relevance"}  # fmt: skip
    if filters.since:
        params.update(datetype="pdat", mindate=str(filters.since), maxdate="3000")
    return _eutils(services.esearch, params, credentials)


def esearch(request: Request, ask: Ask) -> tuple[list[str], int, tuple[str, ...]] | Answer:
    """ESearch's answer: the PMIDs, how many works matched in all, and the words PubMed did
    not find, which it says only in `errorlist.phrasesnotfound`. It answers an error with a
    200: `ERROR` in the result, or `error` beside it. Also what `lookup` searches a reference
    with no identifier by (`lookup/unidentified`)."""
    answer = _ask(ask, request)
    said = _said(answer)
    if said:
        return said
    data = _json(answer)
    result = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(result, dict) or "ERROR" in result or "error" in data:
        return _unresolvable(SHAPE if not isinstance(result, dict) else "the service said: error")
    ids, count = result.get("idlist"), result.get("count")
    if not (
        isinstance(ids, list)
        and all(isinstance(i, str) and i.isdigit() for i in ids)
        and isinstance(count, str)
        and count.isdigit()
    ):
        return _unresolvable(SHAPE)
    errors = result.get("errorlist") if isinstance(result.get("errorlist"), dict) else {}
    dropped = tuple(
        p for p in errors.get("phrasesnotfound") or [] if isinstance(p, str) and p.strip()
    )
    return ids, int(count), dropped


def pubmed(query: str, filters: Filters, ask: Ask, services: Services,
           credentials: Credentials) -> Answer:  # fmt: skip
    """ESearch for the PMIDs, by PubMed's relevance, then ESummary for what each is. Both
    answer an error with a 200: `ERROR` in the search's result, `error` beside it."""
    read = esearch(pubmed_search(query, filters, credentials, services), ask)
    if isinstance(read, Answer):
        return read
    ids, count, dropped = read
    ids = ids[: filters.limit]
    if not ids:
        return Answer(ABSENT, count=0, dropped=dropped)
    answer = _ask(ask, _eutils(services.esummary, {"id": ",".join(ids)}, credentials))
    said = _said(answer)
    if said:
        return said
    data = _json(answer)
    summary = data.get("result") if isinstance(data, dict) else None
    if not isinstance(summary, dict) or "error" in data:
        return _unresolvable(SHAPE)
    hits = []
    for rank, uid in enumerate(ids, 1):
        item = summary.get(uid)
        if not isinstance(item, dict) or "error" in item:
            continue  # a PMID ESearch gave and ESummary does not know: not a work to offer
        if item.get("uid") != uid or not isinstance(item.get("title"), str):
            return _unresolvable(SHAPE)
        hits.append(_pubmed_hit(rank, item))
    return Answer(FOUND, tuple(hits), int(count), dropped=dropped)


def _pubmed_hit(rank: int, item: dict[str, Any]) -> Hit:
    ids = [i for i in item.get("articleids") or [] if isinstance(i, dict)]
    value = {i.get("idtype"): i.get("value") for i in ids if isinstance(i.get("value"), str)}
    pmcid = value.get("pmc") if re.fullmatch(r"PMC\d+", value.get("pmc") or "") else None
    # A PMC copy under embargo is not yet open: ESummary says so in the `pmcid` entry.
    embargoed = "embargo" in (value.get("pmcid") or "").casefold()
    references = [r for r in item.get("references") or [] if isinstance(r, dict)]
    said = {str(r.get("reftype", "")).casefold() for r in references}
    pubtypes = item.get("pubtype") if isinstance(item.get("pubtype"), list) else []
    authors = [a for a in item.get("authors") or []
               if isinstance(a, dict) and a.get("authtype", "Author") == "Author"]  # fmt: skip
    languages = item.get("lang") if isinstance(item.get("lang"), list) else []
    later = [_later(r.get("pmid"), r.get("refsource")) for r in references
             if str(r.get("reftype", "")).casefold() == "update in"]  # fmt: skip
    return Hit(
        registry="pubmed",
        rank=rank,
        doi=_doi(value.get("doi")),
        pmid=item["uid"],
        pmcid=pmcid,
        title=_clean(item["title"]),
        year=_year(item.get("sortpubdate")) or _year(item.get("pubdate")),
        journal=_clean(item.get("fulljournalname")) or _clean(item.get("source")),
        first_author=_clean(authors[0].get("name")) if authors else None,
        authors=len(authors),
        kinds=_kinds(pubtypes),
        language=_text(languages),
        retracted="Retracted Publication" in pubtypes or "retraction in" in said,
        concern="expression of concern in" in said,
        later=tuple(v for v in later if v),
        open_copy=PUBMED_URL.format(pmcid) if pmcid and not embargoed else None,
    )


# ---------------------------------------------------------------------------- Europe PMC


def europepmc_query(query: str, filters: Filters) -> str:
    parts = [f"({query})"]
    if filters.types:
        parts.append("(" + " OR ".join(EUROPEPMC_TYPES[t] for t in filters.types) + ")")
    if filters.language:
        parts.append(f'LANG:"{LANGUAGES[filters.language]}"')
    if filters.since:
        parts.append(f"PUB_YEAR:[{filters.since} TO 3000]")
    return " AND ".join(parts)


def europepmc_search(query: str, filters: Filters, services: Services) -> Request:
    return Request(services.europepmc, params={
        "query": europepmc_query(query, filters), "format": "json", "resultType": "core",
        "pageSize": str(filters.limit)})  # fmt: skip


def europepmc(query: str, filters: Filters, ask: Ask, services: Services) -> Answer:
    """The search, by Europe PMC's relevance, with each work's core record. A query it
    cannot read is answered with no work, not with an error."""
    answer = _ask(ask, europepmc_search(query, filters, services))
    said = _said(answer)
    if said:
        return said
    data = _json(answer)
    count = data.get("hitCount") if isinstance(data, dict) else None
    listed = data.get("resultList") if isinstance(data, dict) else None
    results = listed.get("result") if isinstance(listed, dict) else None
    if isinstance(count, bool) or not isinstance(count, int) or not isinstance(results, list):
        return _unresolvable(SHAPE)
    hits = []
    for rank, item in enumerate(results[: filters.limit], 1):
        if not isinstance(item, dict) or not _text(item.get("id")):
            return _unresolvable(SHAPE)
        hits.append(_europepmc_hit(rank, item))
    return Answer(FOUND if hits else ABSENT, tuple(hits), count)


def europepmc_work_search(doi: str | None, pmid: str | None, services: Services) -> Request:
    """The request for one work's core record, by its PMID where it has one, else its DOI:
    the identifier is all that is sent."""
    query = f"EXT_ID:{pmid} AND SRC:MED" if pmid else f'DOI:"{doi}"'
    return Request(services.europepmc, params={"query": query, "format": "json",
                                               "resultType": "core", "pageSize": "1"})


def europepmc_work(doi: str | None, pmid: str | None, ask: Ask,
                   services: Services) -> dict[str, Any]:  # fmt: skip
    """What Europe PMC holds of one work asked by its PMID or DOI, as a lookup record keeps a
    registry's answer: `found` with its abstract and title where it gives them, `absent`
    where no work it holds has that identifier, `unresolvable` where no answer of its shape
    came. A work it returns under another identifier is none (`absent`): asked by a DOI,
    a search can match more than the DOI's own work."""
    answer = _ask(ask, europepmc_work_search(doi, pmid, services))
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    listed = data.get("resultList") if isinstance(data, dict) else None
    results = listed.get("result") if isinstance(listed, dict) else None
    if not isinstance(results, list):
        return unresolvable(SHAPE)
    if not results:
        return {"status": ABSENT}
    item = results[0]
    if not isinstance(item, dict) or not _text(item.get("id")):
        return unresolvable(SHAPE)
    same = (_digits(item.get("pmid")) == pmid) if pmid else (_doi(item.get("doi")) == doi)
    if not same:
        return {"status": ABSENT}
    found = {"abstract": _abstract(item.get("abstractText")), "title": _clean(item.get("title")),
             "year": _year(item.get("pubYear"))}  # fmt: skip
    return {"status": FOUND, **{k: v for k, v in found.items() if v not in (None, "")}}


def _abstract(value: Any) -> str | None:
    """An abstract without the markup Europe PMC leaves in it, each tag a space: its section
    headings are tags, `<h4>Background</h4>Text`."""
    text = _text(value)
    return _text(html.unescape(re.sub(r"<[^>]+>", " ", text))) if text else None


def _listed(item: dict[str, Any], outer: str, inner: str) -> list:
    held = item.get(outer)
    value = held.get(inner) if isinstance(held, dict) else None
    return value if isinstance(value, list) else [value] if value is not None else []


def _europepmc_hit(rank: int, item: dict[str, Any]) -> Hit:
    pubtypes = [str(p).casefold() for p in _listed(item, "pubTypeList", "pubType")]
    notes = [c for c in _listed(item, "commentCorrectionList", "commentCorrection")
             if isinstance(c, dict)]  # fmt: skip
    said = {str(c.get("type", "")).casefold() for c in notes}
    later = [
        _later(c.get("id") if c.get("source") == "MED" else None, c.get("reference"))
        for c in notes
        if str(c.get("type", "")).casefold() in ("preprint of", "update in")
    ]
    journal = _dict(_dict(item.get("journalInfo")).get("journal"))
    publisher = _dict(item.get("bookOrReportDetails")).get("publisher")
    authors = [a for a in _listed(item, "authorList", "author") if isinstance(a, dict)]
    written = [a.strip() for a in str(item.get("authorString") or "").split(",") if a.strip()]
    first = (authors[0].get("fullName") or authors[0].get("collectiveName") if authors
             else written[0].rstrip(".") if written else None)  # fmt: skip
    pmcid = item.get("pmcid") if re.fullmatch(r"PMC\d+", str(item.get("pmcid") or "")) else None
    copies = [u for u in _listed(item, "fullTextUrlList", "fullTextUrl")
              if isinstance(u, dict) and u.get("availabilityCode") in OPEN]  # fmt: skip
    open_copy = (
        EUROPEPMC_URL.format(pmcid) if pmcid and item.get("isOpenAccess") == "Y"
        else _text(copies[0].get("url")) if copies else None
    )  # fmt: skip
    return Hit(
        registry="europepmc",
        rank=rank,
        doi=_doi(item.get("doi")),
        pmid=_digits(item.get("pmid")),
        pmcid=pmcid,
        title=_clean(item.get("title")),
        year=_year(item.get("pubYear")),
        journal=_clean(journal.get("title")) or _clean(publisher),
        first_author=_clean(first),
        authors=len(authors) or len(written),
        kinds=_kinds(pubtypes),
        language=_text(item.get("language")),
        retracted="retracted publication" in pubtypes or "retraction in" in said,
        concern="expression of concern in" in said,
        later=tuple(v for v in later if v),
        open_copy=open_copy,
        cited_by=_count(item.get("citedByCount")),
    )


# ------------------------------------------------------------------------------ OpenAlex


def openalex_filter(filters: Filters) -> str:
    parts = []
    if filters.since:
        parts.append(f"from_publication_date:{filters.since}-01-01")
    if filters.types:
        parts.append("type:" + "|".join(OPENALEX_TYPES[t] for t in filters.types))
    if filters.language:
        parts.append(f"language:{filters.language}")
    return ",".join(parts)


def openalex_search(query: str, filters: Filters, credentials: Credentials,
                    services: Services) -> Request:  # fmt: skip
    params = {"search": query, "per_page": str(filters.limit), "select": OPENALEX_SELECT}
    if openalex_filter(filters):
        params["filter"] = openalex_filter(filters)
    return Request(services.openalex, params=params,
                   secret={"api_key": credentials.openalex_key or ""})  # fmt: skip


def _openalex_results(answer: Any, limit: int) -> tuple[list[dict], int] | Answer:
    said = _said(answer)
    if said:
        return said
    data = _json(answer)
    meta = data.get("meta") if isinstance(data, dict) else None
    count = meta.get("count") if isinstance(meta, dict) else None
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(count, bool) or not isinstance(count, int) or not isinstance(results, list):
        return _unresolvable(SHAPE)
    if not all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in results):
        return _unresolvable(SHAPE)
    return results[:limit], count


def openalex(query: str, filters: Filters, ask: Ask, services: Services,
             credentials: Credentials) -> Answer:  # fmt: skip
    """`/works?search=`, by OpenAlex's relevance. A filter it does not know is a 400."""
    read = _openalex_results(_ask(ask, openalex_search(query, filters, credentials, services)),
                             filters.limit)  # fmt: skip
    if isinstance(read, Answer):
        return read
    results, count = read
    hits = tuple(_openalex_hit(rank, r) for rank, r in enumerate(results, 1))
    return Answer(FOUND if hits else ABSENT, hits, count)


def openalex_by_doi(dois: list[str], ask: Ask, services: Services,
                    credentials: Credentials) -> Answer:  # fmt: skip
    """What OpenAlex holds of works found elsewhere, asked by DOI in one request. A DOI with
    `|` or `,` in it cannot be written in the filter and is not asked about."""
    wanted = [d for d in dict.fromkeys(dois) if not set(d) & {"|", ","}][:MAX_LIMIT]
    if not wanted:
        return Answer(NOT_ASKED, why="no DOI to ask about")
    request = Request(services.openalex, params={
        "filter": "doi:" + "|".join(wanted), "per_page": str(MAX_LIMIT),
        "select": OPENALEX_SELECT}, secret={"api_key": credentials.openalex_key or ""})  # fmt: skip
    read = _openalex_results(_ask(ask, request), MAX_LIMIT)
    if isinstance(read, Answer):
        return read
    results, count = read
    hits = tuple(_openalex_hit(0, r) for r in results)
    return Answer(FOUND if hits else ABSENT, hits, count)


def _openalex_hit(rank: int, item: dict[str, Any]) -> Hit:
    ids = _dict(item.get("ids"))
    source = _dict(_dict(item.get("primary_location")).get("source"))
    authors = [a for a in item.get("authorships") or [] if isinstance(a, dict)]
    author = _dict(authors[0].get("author")) if authors else {}
    oa = _dict(item.get("open_access"))
    retracted = item.get("is_retracted")
    return Hit(
        registry="openalex",
        rank=rank,
        doi=_doi(item.get("doi")),
        pmid=_digits(ids.get("pmid")),
        pmcid=_text(re.findall(r"PMC\d+", str(ids.get("pmcid") or ""))),
        title=_clean(item.get("title")) or _clean(item.get("display_name")),
        year=_year(item.get("publication_year")),
        journal=_clean(source.get("display_name")),
        first_author=_clean(author.get("display_name")),
        authors=len(authors),
        kinds=_kinds(item.get("type")),
        language=_text(item.get("language")),
        retracted=retracted if isinstance(retracted, bool) else None,
        open_copy=_text(oa.get("oa_url")) if oa.get("is_oa") is True else None,
        cited_by=_count(item.get("cited_by_count")),
    )


# ------------------------------------------------------------------------------ Crossref


def crossref(doi: str, ask: Ask, services: Services,
             credentials: Credentials) -> Hit | Answer | None:  # fmt: skip
    """What Crossref says of a preprint: the published version it links, and a retraction.
    None where it does not know the DOI, since a preprint server's DOI may be DataCite's;
    an unresolvable Answer where no answer came, which is not the same (round 1 of #369)."""
    said = sources.crossref(doi, ask, services.crossref, credentials.contact)
    if said["status"] == UNRESOLVABLE:
        return _unresolvable(said["why"])
    if said["status"] != FOUND:
        return None
    retracting = {"retraction", "withdrawal", "removal"}
    return Hit(
        registry="crossref",
        rank=0,
        doi=said["doi"],
        retracted=any(u["type"] in retracting for u in said.get("updated_by", [])),
        later=tuple({"doi": d} for d in said.get("preprint_of", [])),
    )


def asks(filters: Filters) -> dict[str, str]:
    """Why each registry is not asked, for the filters given: "" for one that is."""
    unsupported = [t for t in filters.types if t not in OPENALEX_TYPES]
    why = ""
    if unsupported:
        named = " or ".join(TYPE_NAMES[t] for t in unsupported)
        why = f"it types a review and a preprint, and not a {named}"
    return {"pubmed": "", "europepmc": "", "openalex": why}


__all__ = [
    "LANGUAGES",
    "MAX_LIMIT",
    "NAMES",
    "NOT_ASKED",
    "REGISTRIES",
    "TYPES",
    "Answer",
    "Filters",
    "Hit",
    "Services",
    "asks",
    "crossref",
    "esearch",
    "europepmc",
    "europepmc_search",
    "europepmc_work",
    "europepmc_work_search",
    "openalex",
    "openalex_by_doi",
    "openalex_search",
    "pubmed",
    "pubmed_search",
    "UNRESOLVABLE",
]
