"""`lookup` for a reference with neither a DOI nor a PMID: its title searched for.

Each registry is searched in its own terms, and each answer is kept whole enough for G7 to
judge it offline (`gates/searched`); nothing here decides whether a work is the one cited,
beyond whether a second, wider question is worth asking.

* **PubMed**, ESearch then ESummary. First every searched word of the title in the title
  field, `word[ti] AND ...`, which finds the work and little else. Not the title as a
  quoted phrase: PubMed holds only short phrases in its index, and a quoted title answers
  "No items found" with the phrase under `quotedphrasesnotfound` (seen 2026-10-20). Nor the
  words untagged: they are mapped to MeSH and searched everywhere, and the work is lost
  among 65. Where no work of the first answer is the cited one, the first author in the
  first author's field and the cited year with one either side, `family[1au] AND
  y0:y1[dp] AND (word[ti] OR ...)`: a title cited with one word wrong finds nothing the
  first way, since a word PubMed does not know makes the whole search empty.
* **Crossref**, `query.bibliographic` with the title, the first author's family name and
  the year, and a filter to the cited year with one either side. Crossref's score is not a
  confidence (paper-preflight's ADR-0003), and with the authors in the query it ranks
  fabricated copies of a famous paper first (five under 10.65215 for "Attention is all you
  need" on 2026-10-20); the filter keeps those out where the year is cited, and G7 never
  takes one. A search is answered from Crossref's list pool, one request a second.
* **OpenAlex**, its `search` of the title, with a key, or without one while its free daily
  allowance has three searches' worth left: a search costs a thousandth of a dollar, and
  the allowance is ten cents a day for everyone behind one address (`X-RateLimit-
  Remaining-USD`, read from each answer).

Each search keeps the works of its first ten answers that hold half the cited title's words
or more, with what G7 compares: title, years, authors, DOI and PMID, type, and the notices
a work carries. The terms sent are kept too (`asked`), so that a "not found" can be read
against what was asked.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from manuscript_guard.gates import lookups as g7
from manuscript_guard.gates import searched
from manuscript_guard.gates.authors import LETTERS
from manuscript_guard.literature import names
from manuscript_guard.literature.names import Authors
from manuscript_guard.lookup import search, sources
from manuscript_guard.lookup.http import Request, Response, user_agent
from manuscript_guard.lookup.run import Credentials
from manuscript_guard.lookup.sources import ABSENT, FOUND, SHAPE, UNRESOLVABLE, Ask

#: How many works of each answer are read.
ROWS = 10
#: Crossref's fields for a work, as its search route lets them be chosen: `subtype` is not
#: one (its 400 lists those that are, 2026-10-20).
CROSSREF_SELECT = (
    "DOI,title,subtitle,original-title,type,author,issued,published-print,published-online,"
    "posted,container-title,volume,page,article-number,update-to,updated-by,relation"
)
#: Searches' worth of OpenAlex's allowance that must be left for one to be made.
OPENALEX_RESERVE = 3


@dataclass(frozen=True)
class Query:
    """What a reference is searched by."""

    title: str
    words: tuple[str, ...]
    cited: Authors
    year: int | None

    @property
    def family(self) -> str:
        """The first author's family name as PubMed's author field takes it: accents and
        case folded, or "" where it cannot be written in plain letters."""
        family = searched.first_family(self.cited)
        # "Jørgensen" is "jorgensen": NFKD keeps ø, æ and ł whole (the measurement of
        # 2026-10-21 lost a first author's search to it).
        folded = unicodedata.normalize("NFKD", plain(family).casefold()).translate(LETTERS)
        folded = " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())
        return folded if folded.isascii() and re.fullmatch(r"[a-z' -]+", folded) else ""


def plain(text: str) -> str:
    """A name or a title with its TeX taken out, as G7 reads one."""
    text = text.replace("{", "").replace("}", "")
    return g7._MATHS.sub("", g7._SIGN.sub("", g7._COMMAND.sub(g7._untex, text)))


def query(fields: dict[str, str], raw: dict[str, str]) -> Query:
    """The search for one entry; `raw` is the entry read with its braces."""
    return Query(
        title=fields.get("title", ""),
        words=tuple(searched.search_words(fields.get("title", ""))),
        cited=names.cited(raw.get("author", "")),
        year=g7._cited_year(fields),
    )


@dataclass
class Allowance:
    """What OpenAlex's last answer said is left of the free daily allowance."""

    remaining: float | None = None
    cost: float = 0.001

    def heard(self, response: Response) -> None:
        headers = {k.lower(): v for k, v in response.headers.items()}
        for name, set_to in (("x-ratelimit-remaining-usd", "remaining"),
                             ("x-ratelimit-cost-usd", "cost")):  # fmt: skip
            try:
                setattr(self, set_to, float(headers[name]))
            except (KeyError, ValueError):
                continue

    def lets(self, keyed: bool) -> bool:
        return keyed or self.remaining is None or self.remaining >= OPENALEX_RESERVE * self.cost


@dataclass(frozen=True)
class Where:
    """The services a search asks, and what travels with it."""

    esearch: str
    esummary: str
    crossref: str
    openalex: str
    credentials: Credentials = field(default_factory=Credentials)
    allowance: Allowance = field(default_factory=Allowance)


# --------------------------------------------------------------------------------- PubMed


def pubmed_terms(q: Query) -> list[str]:
    """The title's words in the title field; then the first author, the years and any of
    the words, where there is a first author and a year to ask by."""
    terms = [" AND ".join(f"{w}[ti]" for w in q.words)]
    if q.family and q.year:
        anyword = " OR ".join(f"{w}[ti]" for w in q.words)
        terms.append(f"{q.family}[1au] AND {q.year - 1}:{q.year + 1}[dp] AND ({anyword})")
    return terms


def _kept(q: Query, *titles: str | None) -> bool:
    """A work alike enough to the cited one to keep (`gates/searched.alike`)."""
    return searched.alike(q.title, [t for t in titles if t]) >= searched.KEPT


def _is_it(q: Query, item: dict[str, Any]) -> bool:
    """Whether PubMed's work is, by G7's rules, the one cited: the second search is not
    worth asking then."""
    work = searched._pubmed(item)
    return (
        searched.held(q.title, work) >= g7.TITLE_HELD
        and searched._dated(work, q.year)
        and searched._leads(q.cited, work)
    )


def pubmed(q: Query, ask: Ask, where: Where) -> dict[str, Any]:
    asked: list[str] = []
    kept: dict[str, dict[str, Any]] = {}
    matched = False
    for term in pubmed_terms(q):
        if any(_is_it(q, item) for item in kept.values()):
            break
        asked.append(term)
        request = search._eutils(
            where.esearch, {"term": term, "retmax": str(ROWS), "sort": "relevance"},
            where.credentials,
        )  # fmt: skip
        read = search.esearch(request, ask)
        if isinstance(read, search.Answer):
            return {"status": UNRESOLVABLE, "why": read.why or SHAPE, "asked": asked}
        ids = [i for i in read[0][:ROWS] if i not in kept]
        matched = matched or bool(read[0])
        if not ids:
            continue
        credentials = where.credentials
        said = sources.summaries(ids, ask, where.esummary, credentials.contact,
                                 credentials.ncbi_key)  # fmt: skip
        if "status" in said:
            return {**said, "asked": asked}
        for pmid in ids:
            answer = said[pmid]
            if answer["status"] == FOUND and _kept(q, answer.get("title")):
                kept[pmid] = {"pmid": pmid, **{k: v for k, v in answer.items() if k != "status"}}
    return {"status": FOUND if matched else ABSENT, "asked": asked,
            **({"candidates": list(kept.values())} if kept else {})}  # fmt: skip


# ------------------------------------------------------------------------------- Crossref


def crossref_text(q: Query) -> str:
    """The whole title's words, the first author's family name and the year: Crossref
    ranks by all of them, and a long title cut to PubMed's twelve words lost the Lancet's
    NOR-SWITCH trial among abstracts of the same words (the measurement of 2026-10-21)."""
    family = plain(searched.first_family(q.cited))
    words = " ".join(re.findall(r"[^\W_]+", plain(g7._TAGS.sub("", q.title))))
    return " ".join(p for p in (words, family, str(q.year or "")) if p)


def crossref(q: Query, ask: Ask, where: Where) -> dict[str, Any]:
    """`/works?query.bibliographic=`. A 200 is a list only with `"status": "ok"` and
    `"message-type": "work-list"`, and each item a work with a DOI."""
    text = crossref_text(q)
    params = {"query.bibliographic": text, "rows": str(ROWS), "select": CROSSREF_SELECT}
    if q.year:
        params["filter"] = f"from-pub-date:{q.year - 1},until-pub-date:{q.year + 1}"
    contact = where.credentials.contact
    request = Request(where.crossref, params=params, secret={"mailto": contact or ""},
                      headers={"User-Agent": user_agent(contact)})  # fmt: skip
    asked = [text + (f" ({params['filter']})" if "filter" in params else "")]
    answer = sources._ask(ask, request)
    if isinstance(answer, dict):
        return {**answer, "asked": asked}
    said = sources._status_only(answer)
    if said:
        return {**said, "asked": asked}
    data = sources._json(answer)
    message = data.get("message") if isinstance(data, dict) else None
    items = message.get("items") if isinstance(message, dict) else None
    if not (
        isinstance(data, dict)
        and data.get("status") == "ok"
        and data.get("message-type") == "work-list"
        and isinstance(items, list)
        and all(isinstance(i, dict) and isinstance(i.get("DOI"), str) for i in items)
    ):
        return {**sources.unresolvable(SHAPE), "asked": asked}
    works = [sources.work(item) for item in items[:ROWS]]
    kept = [
        w for w in works
        if _kept(q, ": ".join(filter(None, (w.get("title"), w.get("subtitle")))),
                 w.get("original_title"))
    ]  # fmt: skip
    return {"status": FOUND if items else ABSENT, "asked": asked,
            **({"candidates": kept} if kept else {})}  # fmt: skip


# ------------------------------------------------------------------------------- OpenAlex


def _openalex_work(item: dict[str, Any]) -> dict[str, Any]:
    ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
    people = [a.get("author") for a in item.get("authorships") or [] if isinstance(a, dict)]
    shown = [p.get("display_name") for p in people if isinstance(p, dict)]
    retracted = item.get("is_retracted")
    return sources._kept({
        "doi": search._doi(item.get("doi")),
        "pmid": search._digits(ids.get("pmid")),
        "title": search._clean(item.get("title")) or search._clean(item.get("display_name")),
        "type": sources._text(item.get("type")),
        "year": sources._year(item.get("publication_year")),
        "is_retracted": retracted if isinstance(retracted, bool) else None,
        "authors": [names.displayed(s).record() for s in shown if isinstance(s, str) and s.strip()],
    })  # fmt: skip


def openalex(q: Query, ask: Ask, where: Where) -> dict[str, Any] | None:
    """`/works?search=`, the title. None where the allowance does not let it be asked."""
    if not where.allowance.lets(bool(where.credentials.openalex_key)):
        return None
    text = " ".join(q.words)
    request = search.openalex_search(
        text, search.Filters(limit=ROWS), where.credentials,
        search.Services(openalex=where.openalex),
    )  # fmt: skip
    answer = sources._ask(ask, request)
    if isinstance(answer, Response) and answer.status == 429:
        # OpenAlex says 429 once the allowance is spent (seen 2026-10-21, the day after a
        # measurement spent it): no search was made, which is not an answer that did not
        # come. OpenAlex may find a work and never fails one, so nothing waits on it.
        where.allowance.remaining = 0.0
        return None
    read = search._openalex_results(answer, ROWS)
    if isinstance(read, search.Answer):
        return {"status": UNRESOLVABLE, "why": read.why or SHAPE, "asked": [text]}
    results, _count = read
    kept = [w for w in map(_openalex_work, results) if _kept(q, w.get("title"))]
    return {"status": FOUND if results else ABSENT, "asked": [text],
            **({"candidates": kept} if kept else {})}  # fmt: skip


# ----------------------------------------------------------------------------- the whole


def look_up(q: Query, ask: Ask, where: Where) -> dict[str, Any]:
    """The record's `sources` for one reference with no identifier."""
    found = {"pubmed_search": pubmed(q, ask, where), "crossref_search": crossref(q, ask, where)}
    alex = openalex(q, ask, where)
    if alex is not None:
        found["openalex_search"] = alex
    return found


def listening(ask: Ask, allowance: Allowance, host: str) -> Callable[[Request], Response]:
    """`ask`, telling the allowance what each of OpenAlex's answers says of it."""

    def heard(request: Request) -> Response:
        response = ask(request)
        if urlsplit(request.base).hostname == host:
            allowance.heard(response)
        return response

    return heard


__all__ = ["Allowance", "Query", "Where", "crossref", "look_up", "openalex", "pubmed",
           "pubmed_terms", "query"]  # fmt: skip
