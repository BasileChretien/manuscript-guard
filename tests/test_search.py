"""`search`: works a claim could cite, asked of PubMed, Europe PMC and OpenAlex, merged into
one list, and said. It proposes; the author chooses, and nothing is written.

No test opens a connection to a registry. Most answer from a table; the real transport is run
against a server on a loopback port that stands in for all of them. The answers are written
here in the shapes the services answered on 2026-10-20, for fictional works.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from manuscript_guard.cli import main
from manuscript_guard.lookup import proposals
from manuscript_guard.lookup import search as registries
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer
from manuscript_guard.lookup.search import Filters, Hit

CONTACT = "author@example.org"
NCBI = "ncbi-key-0123456789abcdefSECRET"
OPENALEX = "openalex-key-0123456789SECRET"
QUERY = "hepatic injury in a fictional cohort"

REVIEW, META = "10.5555/demo.review.2024", "10.5555/demo.meta.2023"
TRIAL = "10.5555/demo.trial.2020"
PREPRINT, PUBLISHED = "10.5555/demo.preprint.2025", "10.5555/demo.published.2026"
OTHER = "10.5555/demo.other.2022"
SERVICES = registries.Services(
    esearch="https://registry.test/eutils/esearch.fcgi",
    esummary="https://registry.test/eutils/esummary.fcgi",
    europepmc="https://registry.test/europepmc/search",
    openalex="https://registry.test/openalex/works",
    crossref="https://registry.test/crossref/works/",
)


def _json(status: int, data: object) -> Response:
    return Response(status, {}, json.dumps(data).encode())


def esearch(*ids: str, dropped: tuple[str, ...] = ()) -> Response:
    result = {"count": str(len(ids) + 40), "retmax": str(len(ids)), "retstart": "0",
              "idlist": list(ids), "translationset": [], "querytranslation": QUERY}  # fmt: skip
    if dropped:
        result["errorlist"] = {"phrasesnotfound": list(dropped), "fieldsnotfound": []}
    return _json(200, {"header": {"type": "esearch", "version": "0.3"}, "esearchresult": result})


def summary(uid: str, doi: str, title: str, pubtypes: list[str], *, year: int = 2024,
            pmc: str | None = None, references: list[dict] | None = None,
            embargo: bool = False) -> dict:  # fmt: skip
    ids = [{"idtype": "pubmed", "idtypen": 1, "value": uid},
           {"idtype": "doi", "idtypen": 3, "value": doi.upper()}]  # fmt: skip
    if pmc:
        note = f"pmc-id: {pmc};" + (" embargo-date: 2099/01/01;" if embargo else "")
        ids += [{"idtype": "pmc", "idtypen": 8, "value": pmc},
                {"idtype": "pmcid", "idtypen": 5, "value": note}]  # fmt: skip
    return {
        "uid": uid, "pubdate": f"{year} Mar", "source": "J Demo Pharmacol",
        "fulljournalname": "Journal of demonstrative pharmacology", "title": title,
        "authors": [{"name": "Author A", "authtype": "Author", "clusterid": ""},
                    {"name": "Writer B", "authtype": "Author", "clusterid": ""}],
        "lang": ["eng"], "pubtype": pubtypes, "articleids": ids,
        "references": references or [], "sortpubdate": f"{year}/03/01 00:00",
    }  # fmt: skip


def esummary(*items: dict) -> Response:
    result = {"uids": [i["uid"] for i in items], **{i["uid"]: i for i in items}}
    return _json(200, {"header": {"type": "esummary", "version": "0.3"}, "result": result})


PUBMED_ITEMS = (
    summary("31000101", REVIEW, "A review of hepatic injury.", ["Journal Article", "Review"],
            pmc="PMC9000101"),  # fmt: skip
    summary("31000102", META, "Hepatic injury: a systematic review and meta-analysis.",
            ["Journal Article", "Systematic Review", "Meta-Analysis"], year=2023),
    summary("31000103", TRIAL, "A randomized trial in a fictional cohort.",
            ["Journal Article", "Randomized Controlled Trial", "Retracted Publication"],
            year=2020, references=[{"refsource": "J Demo. 2021;1:1. doi: 10.5555/retraction.",
                                    "reftype": "Retraction in", "pmid": 31000190}]),
)  # fmt: skip


def epmc_item(rank_id: str, doi: str, title: str, pubtypes: list[str], **extra) -> dict:
    return {
        "id": rank_id, "source": "MED", "pmid": rank_id, "doi": doi, "title": title,
        "authorString": "Author A, Writer B.", "pubYear": "2024",
        "journalInfo": {"journal": {"title": "Journal of demonstrative pharmacology"}},
        "pubTypeList": {"pubType": pubtypes}, "isOpenAccess": "N", "language": "eng",
        "citedByCount": 12, **extra,
    }  # fmt: skip


EPMC_PREPRINT = {
    "id": "PPR900001", "source": "PPR", "doi": PREPRINT, "title": "A fictional preprint.",
    "authorString": "Poster P.", "pubYear": "2025", "pubTypeList": {"pubType": ["Preprint"]},
    "bookOrReportDetails": {"publisher": "demoRxiv"}, "isOpenAccess": "N", "citedByCount": 0,
    "fullTextUrlList": {"fullTextUrl": [{"availability": "Free", "availabilityCode": "F",
                                         "documentStyle": "pdf", "site": "Europe_PMC",
                                         "url": "https://demorxiv.test/900001.pdf"}]},
    "commentCorrectionList": {"commentCorrection": [{"source": "MED", "id": "31000199",
        "reference": "J Demo. 2026;3:3", "type": "Preprint of", "orderIn": 10001}]},
}  # fmt: skip


def europepmc(*items: dict) -> Response:
    return _json(200, {"version": "6.9", "hitCount": len(items) + 100,
                       "request": {"queryString": QUERY},
                       "resultList": {"result": list(items)}})  # fmt: skip


def oa_item(doi: str, title: str, kind: str = "article", **extra) -> dict:
    return {
        "id": f"https://openalex.org/W{sum(map(ord, doi))}", "doi": f"https://doi.org/{doi}",
        "title": title, "display_name": title, "publication_year": 2022, "type": kind,
        "language": "en", "is_retracted": False, "cited_by_count": 7,
        "open_access": {"is_oa": False, "oa_status": "closed", "oa_url": None},
        "primary_location": {"source": {"display_name": "Demo Journal", "type": "journal"}},
        "ids": {"openalex": "https://openalex.org/W1", "doi": f"https://doi.org/{doi}"},
        "authorships": [{"author": {"display_name": "Ada Author"}}], **extra,
    }  # fmt: skip


def openalex(*items: dict) -> Response:
    return _json(200, {"meta": {"count": len(items) + 300, "page": 1, "per_page": 10},
                       "results": list(items)})  # fmt: skip


def crossref_preprint(doi: str = PREPRINT, published: str = PUBLISHED, **extra) -> Response:
    relation = {"is-preprint-of": [{"id-type": "doi", "id": published}]}
    message = {"DOI": doi, "type": "posted-content", "subtype": "preprint",
               "title": ["A fictional preprint"], "posted": {"date-parts": [[2025, 1, 2]]},
               "relation": relation, **extra}  # fmt: skip
    return _json(200, {"status": "ok", "message-type": "work", "message": message})


class Table:
    """A transport that answers by service, and keeps what it was sent."""

    def __init__(self, **answers: Response) -> None:
        self.answers = {
            "esearch": esearch("31000101", "31000102", "31000103"),
            "esummary": esummary(*PUBMED_ITEMS),
            "europepmc": europepmc(EPMC_PREPRINT, epmc_item("31000101", REVIEW, "A review.",
                                                            ["Review", "Journal Article"])),
            "openalex": openalex(oa_item(OTHER, "Another fictional study"),
                                 oa_item(REVIEW, "A review of hepatic injury", "review")),
            "by_doi": openalex(oa_item(META, "Hepatic injury: a meta-analysis",
                                       cited_by_count=40)),
            "crossref": crossref_preprint(),
            **answers,
        }  # fmt: skip
        self.sent: list[Request] = []

    def name(self, request: Request) -> str:
        path = urlsplit(request.base).path
        if path.startswith("/crossref/"):
            return "crossref"
        if path.startswith("/openalex/"):
            return "by_doi" if request.params.get("filter", "").startswith("doi:") else "openalex"
        if path.startswith("/europepmc/"):
            return "europepmc"
        return path.rsplit("/", 1)[1].split(".")[0]

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append(request)
        return self.answers.get(self.name(request), _json(404, {}))

    def asked(self) -> list[str]:
        return [self.name(r) for r in self.sent]


def _ask(table: Table):
    return lambda request: table(request, 1.0)


def _run(table: Table, filters: Filters | None = None, **kwargs) -> proposals.Result:
    return proposals.run(QUERY, filters or Filters(), transport=table, services=SERVICES,
                         pacer=Pacer(sleep=lambda s: None), **kwargs)  # fmt: skip


# ----------------------------------------------------------------------- what each one says


def test_pubmed_is_searched_and_each_pmid_read() -> None:
    table = Table()
    answer = registries.pubmed(QUERY, Filters(), _ask(table), SERVICES, Credentials())
    assert answer.status == "found" and answer.count == 43
    review, meta, trial = answer.hits
    assert (review.rank, review.doi, review.pmid, review.pmcid) == (1, REVIEW, "31000101",
                                                                    "PMC9000101")  # fmt: skip
    assert review.kinds == ("review",) and review.retracted is False
    assert review.open_copy == "https://pmc.ncbi.nlm.nih.gov/articles/PMC9000101/"
    assert (review.first_author, review.authors, review.year) == ("Author A", 2, 2024)
    assert meta.kinds == ("systematic review", "meta-analysis")
    assert trial.retracted is True and trial.kinds == ("randomized controlled trial",)
    assert table.asked() == ["esearch", "esummary"]
    sent = parse_qs(urlsplit(table.sent[0].url).query)
    assert sent["term"] == [f"({QUERY})"] and sent["sort"] == ["relevance"]


def test_pubmed_is_asked_in_its_own_terms() -> None:
    table = Table()
    filters = Filters(since=2020, types=("systematic-review", "guideline"), language="fr", limit=5)
    registries.pubmed(QUERY, filters, _ask(table), SERVICES, Credentials())
    sent = parse_qs(urlsplit(table.sent[0].url).query)
    assert sent["term"] == [f"({QUERY}) AND (systematic review[pt] OR guideline[pt] OR "
                            "practice guideline[pt]) AND fre[la]"]  # fmt: skip
    assert (sent["mindate"], sent["datetype"], sent["retmax"]) == (["2020"], ["pdat"], ["5"])


def test_a_preprint_pubmed_links_to_a_later_version_says_so() -> None:
    cited = "J Demo. 2026;3:3. doi: 10.5555/Demo.Published.2026."
    update = {"refsource": cited, "reftype": "Update in", "pmid": 31000199}
    item = summary("31000104", PREPRINT, "A preprint.", ["Preprint"], references=[update],
                   pmc="PMC9000104", embargo=True)  # fmt: skip
    table = Table(esearch=esearch("31000104"), esummary=esummary(item))
    [hit] = registries.pubmed(QUERY, Filters(), _ask(table), SERVICES, Credentials()).hits
    assert hit.later == ({"pmid": "31000199", "doi": PUBLISHED, "reference": cited},)
    assert hit.kinds == ("preprint",)
    # A PMC copy still under embargo is not offered as open.
    assert hit.open_copy is None


@pytest.mark.parametrize(
    ("answers", "status", "why"),
    [
        ({"esearch": esearch()}, "absent", ""),
        ({"esearch": _json(200, {"esearchresult": {"ERROR": "Empty Term"}})}, "unresolvable",
         "the service said: error"),
        ({"esearch": _json(429, {})}, "unresolvable", "throttled"),
        ({"esearch": _json(200, {"esearchresult": {"idlist": ["1"]}})}, "unresolvable", "shape"),
        ({"esummary": _json(200, {"error": "boom"})}, "unresolvable", "shape"),
        ({"esummary": Response(200, {}, b"<html>")}, "unresolvable", "shape"),
    ],
)  # fmt: skip
def test_pubmed_that_says_nothing_readable_is_not_read_as_nothing_found(
    answers, status, why
) -> None:
    answer = registries.pubmed(QUERY, Filters(), _ask(Table(**answers)), SERVICES, Credentials())
    assert answer.status == status and why in answer.why and not answer.hits


def test_a_word_pubmed_left_out_of_the_search_is_said() -> None:
    """PubMed searches the rest of a query when a word of it matches nothing, and says so
    only in `errorlist` (2026-10-20): the search was not the one asked for."""
    table = Table(esearch=esearch("31000101", dropped=("hepatotoxicityy",)))
    answer = registries.pubmed(QUERY, Filters(), _ask(table), SERVICES, Credentials())
    assert answer.dropped == ("hepatotoxicityy",)
    table = Table(esearch=esearch(dropped=("hepatotoxicityy",)))
    result = _run(table)
    assert "PubMed: nothing found; it left out 'hepatotoxicityy'" in proposals.render(result)


def test_europepmc_is_read_with_a_preprint_and_its_published_version() -> None:
    table = Table()
    filters = Filters(since=2021, types=("preprint", "meta-analysis"), language="en")
    answer = registries.europepmc(QUERY, filters, _ask(table), SERVICES)
    preprint, review = answer.hits
    assert (preprint.doi, preprint.pmid, preprint.kinds) == (PREPRINT, None, ("preprint",))
    assert preprint.later == ({"pmid": "31000199", "reference": "J Demo. 2026;3:3"},)
    assert preprint.journal == "demoRxiv" and preprint.first_author == "Poster P"
    assert preprint.open_copy == "https://demorxiv.test/900001.pdf"
    assert (review.pmid, review.cited_by, review.retracted) == ("31000101", 12, False)
    assert parse_qs(urlsplit(table.sent[0].url).query)["query"] == [
        f'({QUERY}) AND (SRC:PPR OR PUB_TYPE:"meta-analysis") AND LANG:"eng" AND '
        "PUB_YEAR:[2021 TO 3000]"
    ]


def test_europepmc_reads_a_retraction_and_an_open_copy_in_europe_pmc() -> None:
    notes = {"commentCorrection": {"source": "MED", "id": "31000190", "type": "Retraction in",
                                   "reference": "J Demo. 2021;1:1"}}  # fmt: skip
    item = epmc_item("31000103", TRIAL, "A trial.", "Journal Article", pmcid="PMC9000103",
                     isOpenAccess="Y", commentCorrectionList=notes)  # fmt: skip
    [hit] = registries.europepmc(QUERY, Filters(), _ask(Table(europepmc=europepmc(item))),
                                 SERVICES).hits  # fmt: skip
    assert hit.retracted is True
    assert hit.open_copy == "https://europepmc.org/article/PMC/PMC9000103"


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (europepmc(), "absent"),
        (_json(200, {"hitCount": "many", "resultList": {"result": []}}), "unresolvable"),
        (_json(200, {"hitCount": 1, "resultList": {"result": [{"title": "no id"}]}}),
         "unresolvable"),
        (_json(503, {}), "unresolvable"),
    ],
)  # fmt: skip
def test_europepmc_that_says_nothing_readable(answer, status) -> None:
    assert registries.europepmc(QUERY, Filters(), _ask(Table(europepmc=answer)),
                                SERVICES).status == status  # fmt: skip


def test_openalex_is_read_and_asked_with_its_key() -> None:
    table = Table(openalex=openalex(oa_item(OTHER, "A <i>fictional</i> study", is_retracted=True,
        open_access={"is_oa": True, "oa_url": "https://repository.test/1.pdf"},
        ids={"pmid": "https://pubmed.ncbi.nlm.nih.gov/31000105",
             "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9000105"})))  # fmt: skip
    filters = Filters(since=2019, types=("review", "preprint"), language="en")
    [hit] = registries.openalex(QUERY, filters, _ask(table), SERVICES,
                                Credentials(openalex_key=OPENALEX)).hits  # fmt: skip
    assert (hit.doi, hit.pmid, hit.pmcid, hit.title) == (OTHER, "31000105", "PMC9000105",
                                                         "A fictional study")  # fmt: skip
    assert hit.retracted is True and hit.open_copy == "https://repository.test/1.pdf"
    [sent] = table.sent
    assert sent.params["filter"] == (
        "from_publication_date:2019-01-01,type:review|preprint,language:en"
    )
    assert OPENALEX in sent.url and OPENALEX not in sent.shown


def test_openalex_answering_a_filter_it_does_not_know_is_unresolvable() -> None:
    table = Table(openalex=_json(400, {"error": "Invalid query parameters error."}))
    answer = registries.openalex(QUERY, Filters(), _ask(table), SERVICES, Credentials())
    assert (answer.status, answer.why) == ("unresolvable", "HTTP 400")


def test_openalex_is_not_asked_for_a_kind_it_does_not_type() -> None:
    assert registries.asks(Filters(types=("review", "preprint")))["openalex"] == ""
    why = registries.asks(Filters(types=("review", "rct")))["openalex"]
    assert why == "it types a review and a preprint, and not a randomized controlled trial"
    table = Table()
    result = _run(table, Filters(types=("meta-analysis",)))
    assert "openalex" not in table.asked() and result.answers["openalex"].status == "not asked"
    # OpenAlex is still asked about the works the others found, by their DOIs.
    assert "by_doi" in table.asked()


def test_openalex_is_asked_by_doi_about_the_works_it_did_not_return() -> None:
    table = Table()
    answer = registries.openalex_by_doi([META, "10.5555/a|b", META], _ask(table), SERVICES,
                                        Credentials())  # fmt: skip
    assert table.sent[0].params["filter"] == f"doi:{META}"
    assert answer.hits[0].rank == 0 and answer.hits[0].cited_by == 40


def test_crossref_says_what_a_preprint_became_and_whether_it_was_retracted() -> None:
    notice = [{"DOI": "10.5555/notice", "type": "withdrawal", "updated": {"date-parts": [[2025]]}}]
    table = Table(crossref=crossref_preprint(**{"updated-by": notice}))
    hit = registries.crossref(PREPRINT, _ask(table), SERVICES, Credentials())
    assert hit.later == ({"doi": PUBLISHED},) and hit.retracted is True
    assert unquote(table.sent[0].base).endswith(f"/crossref/works/{PREPRINT}")
    assert registries.crossref(PREPRINT, _ask(Table(crossref=Response(404, {}, b""))),
                               SERVICES, Credentials()) is None  # fmt: skip


# ---------------------------------------------------------------- one list of candidates


def _hit(registry: str, rank: int, **fields) -> Hit:
    return Hit(registry=registry, rank=rank, **fields)


def test_one_work_found_twice_is_one_candidate_above_a_work_found_once() -> None:
    hits = [_hit("pubmed", 1, doi="10.5/a", pmid="1"), _hit("pubmed", 2, doi="10.5/b"),
            _hit("europepmc", 1, doi="10.5/b", pmid="2"),
            _hit("openalex", 1, doi="10.5/b")]  # fmt: skip
    ranked = proposals.ranked([proposals.candidate(g) for g in proposals.merge(hits)],
                              "relevance")  # fmt: skip
    assert [c.doi for c in ranked] == ["10.5/b", "10.5/a"]
    assert ranked[0].found_by == {"pubmed": 2, "europepmc": 1, "openalex": 1}
    assert ranked[0].pmid == "2"


def test_a_pmid_joins_two_answers_only_where_no_doi_tells_them_apart() -> None:
    hits = [_hit("pubmed", 1, pmid="7"), _hit("europepmc", 1, doi="10.5/a", pmid="7"),
            _hit("openalex", 1, doi="10.5/other", pmid="7")]  # fmt: skip
    groups = proposals.merge(hits)
    assert [[h.registry for h in g] for g in groups] == [["pubmed", "europepmc"], ["openalex"]]


def test_a_work_asked_about_after_the_search_never_becomes_a_candidate() -> None:
    hits = [_hit("pubmed", 1, doi="10.5/a"), _hit("openalex", 0, doi="10.5/unseen",
                                                  retracted=True)]  # fmt: skip
    [group] = proposals.merge(hits)
    assert [h.doi for h in group] == ["10.5/a"]


def test_a_retraction_any_registry_reports_stands() -> None:
    group = [_hit("pubmed", 1, doi="10.5/a", retracted=False),
             _hit("openalex", 0, doi="10.5/a", retracted=True)]  # fmt: skip
    one = proposals.candidate(group)
    assert (one.retracted, one.retracted_per, one.retraction_checked_by) == (
        True, ("openalex",), ("pubmed", "openalex"))  # fmt: skip
    assert proposals.candidate([_hit("europepmc", 1, doi="10.5/b")]).retracted is None


def test_the_other_orders_are_by_year_and_by_citations() -> None:
    pool = [proposals.candidate([_hit("pubmed", 1, doi="10.5/old", year=2010, cited_by=900)]),
            proposals.candidate([_hit("pubmed", 2, doi="10.5/new", year=2026, cited_by=1)]),
            proposals.candidate([_hit("pubmed", 3, doi="10.5/none")])]  # fmt: skip
    assert [c.doi for c in proposals.ranked(pool, "newest")] == ["10.5/new", "10.5/old",
                                                                 "10.5/none"]  # fmt: skip
    assert [c.doi for c in proposals.ranked(pool, "cited")] == ["10.5/old", "10.5/new",
                                                                "10.5/none"]  # fmt: skip


def test_the_search_asks_each_registry_then_about_what_they_found() -> None:
    table = Table()
    result = _run(table, credentials=Credentials(contact=CONTACT, ncbi_key=NCBI,
                                                 openalex_key=OPENALEX))  # fmt: skip
    assert table.asked() == ["esearch", "esummary", "europepmc", "openalex", "by_doi",
                             "crossref"]  # fmt: skip
    by_doi = {c.doi: c for c in result.candidates}
    assert set(by_doi) == {REVIEW, META, TRIAL, PREPRINT, OTHER}
    assert by_doi[REVIEW].found_by == {"pubmed": 1, "europepmc": 2, "openalex": 2}
    assert result.candidates[0].doi == REVIEW
    assert by_doi[META].cited_by == {"openalex": 40}
    assert by_doi[TRIAL].retracted is True
    later = {v.get("doi") or v.get("pmid") for v in by_doi[PREPRINT].later_versions}
    assert later == {"31000199", PUBLISHED}
    said = proposals.render(result) + json.dumps(proposals.as_json(result))
    assert "RETRACTED (PubMed)" in said and f"DOI {PUBLISHED} (Crossref)" in said
    # A work the author chooses goes into Zotero by its identifier, from the registry.
    assert "Zotero's Add Item by Identifier" in proposals.render(result)
    assert proposals.as_json(result)["candidates"][0]["for_zotero"] == REVIEW
    assert not any(s in said for s in (CONTACT, NCBI, OPENALEX))
    # Asked about by DOI: those OpenAlex did not return; Crossref: the preprint only.
    assert set(table.sent[4].params["filter"][4:].split("|")) == {META, TRIAL, PREPRINT}
    assert unquote(table.sent[5].base).endswith(PREPRINT)


def test_crossref_that_did_not_answer_is_not_read_as_finding_nothing() -> None:
    """Round 1 of #369: a 503 from Crossref was kept as `absent`, so a withdrawal only
    Crossref carries read as "retracted: no" and nothing said the check had failed."""
    result = _run(Table(crossref=_json(503, {})))
    assert result.answers["crossref"].status == "unresolvable"
    assert "Crossref, asked about the preprints: unresolvable (HTTP 503)" in proposals.render(
        result
    )
    [preprint] = [c for c in result.candidates if c.doi == PREPRINT]
    assert "crossref" not in preprint.retraction_checked_by
    # A DOI Crossref does not know is not a failure: a preprint server may register at
    # DataCite.
    result = _run(Table(crossref=Response(404, {}, b"Resource not found.")))
    assert result.answers["crossref"].status == "absent"


def test_one_later_version_two_registries_give_is_said_once() -> None:
    hits = [_hit("pubmed", 1, doi=PREPRINT, later=({"pmid": "9", "doi": "10.5/x"},)),
            _hit("europepmc", 1, doi=PREPRINT, later=({"pmid": "9", "reference": "J. 2026"},)),
            _hit("crossref", 0, doi=PREPRINT, later=({"doi": "10.5/x"},))]  # fmt: skip
    [one] = proposals.candidate(hits).later_versions
    assert one == {"pmid": "9", "doi": "10.5/x", "reference": "J. 2026",
                   "said_by": ["pubmed", "europepmc", "crossref"]}  # fmt: skip


def test_openalex_asked_without_a_key_is_said_when_only_asked_by_doi() -> None:
    result = _run(Table(), Filters(types=("systematic-review",)))
    assert result.answers["openalex"].status == "not asked"
    assert "OpenAlex was asked without a key" in proposals.render(result)


def test_the_limit_cuts_the_merged_list_and_says_how_many_more() -> None:
    # Each registry gives two; four works among the six, and two of them shown.
    result = _run(Table(), Filters(limit=2))
    assert len(result.candidates) == 2 and result.more == 2
    assert "2 more found" in proposals.render(result)


def test_a_search_no_registry_answered_says_so() -> None:
    down = _json(503, {})
    result = _run(Table(esearch=down, europepmc=down, openalex=down))
    assert not proposals.answered(result)
    assert "PubMed: unresolvable (HTTP 503)" in proposals.render(result)
    assert proposals.answered(_run(Table(esearch=down, europepmc=europepmc(), openalex=down)))


# ----------------------------------------------------------------------------- the command


def _refused(request: Request, timeout: float) -> Response:
    raise AssertionError("a request was sent")


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["search", "  "], "the query is empty"),
        (["search", "x" * 301], "not a passage of the manuscript"),
        (["search", QUERY, "--type", "review,case-series"], "no type 'case-series'"),
        (["search", QUERY, "--language", "english"], "give it in two letters"),
        (["search", QUERY, "--since", "20"], "--since takes a year"),
        (["search", QUERY, "--limit", "51"], "--limit takes 1 to 50"),
    ],
)
def test_a_search_that_cannot_be_asked_sends_nothing(argv, said, monkeypatch, capsys) -> None:
    monkeypatch.setattr(proposals, "default_transport", _refused)
    assert main(argv) == 2
    assert said in capsys.readouterr().err


def test_a_dry_run_says_what_it_would_ask_and_sends_nothing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(proposals, "default_transport", _refused)
    monkeypatch.setenv("NCBI_API_KEY", NCBI)
    monkeypatch.chdir(tmp_path)
    assert main(["search", QUERY, "--type", "rct", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "PubMed: would ask https://eutils.ncbi.nlm.nih.gov/" in out
    assert "Europe PMC: would ask" in out and "OpenAlex: would ask" not in out
    assert "nothing was sent" in out and NCBI not in out


def test_the_search_runs_outside_a_project_and_in_one(
    project: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    table = Table()
    monkeypatch.setattr(proposals, "default_transport", table)
    monkeypatch.setattr(proposals, "Services", lambda: SERVICES)
    monkeypatch.delenv("MANUSCRIPT_GUARD_CONTACT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["search", QUERY, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {c["doi"] for c in data["candidates"]} >= {REVIEW, META}
    assert data["registries"]["pubmed"] == {"status": "found", "count": 43}
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8") + f"\nlookup:\n  contact: {CONTACT}\n",
                     encoding="utf-8")  # fmt: skip
    table.sent.clear()
    assert main(["search", QUERY, "--root", str(project)]) == 0
    assert CONTACT not in capsys.readouterr().out
    assert parse_qs(urlsplit(table.sent[0].url).query)["email"] == [CONTACT]
    assert main(["search", QUERY, "--root", str(tmp_path)]) == 2
    assert "no paper.yaml" in capsys.readouterr().err


def test_a_search_no_registry_answered_exits_1(tmp_path: Path, monkeypatch, capsys) -> None:
    down = _json(500, {})
    monkeypatch.setattr(proposals, "default_transport",
                        Table(esearch=down, europepmc=down, openalex=down))  # fmt: skip
    monkeypatch.setattr(proposals, "Services", lambda: SERVICES)
    monkeypatch.chdir(tmp_path)
    assert main(["search", QUERY]) == 1
    assert "No work was found." in capsys.readouterr().out


# ------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        parts = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        request = Request("https://registry.test" + parts.path, params)
        answer = self.server.table(request, 5.0)
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer.body)))
        self.end_headers()
        self.wfile.write(answer.body)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


def test_the_real_transport_searches_on_loopback() -> None:
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.table = Table()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        try:
            default_transport(Request(url + "/eutils/probe.fcgi"), 5)
        except NoAnswer as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"loopback connections are not allowed here: {exc}")
        httpd.table.sent.clear()
        services = registries.Services(
            esearch=f"{url}/eutils/esearch.fcgi", esummary=f"{url}/eutils/esummary.fcgi",
            europepmc=f"{url}/europepmc/search", openalex=f"{url}/openalex/works",
            crossref=f"{url}/crossref/works/")  # fmt: skip
        result = proposals.run(QUERY, Filters(), services=services,
                               credentials=Credentials(ncbi_key=NCBI),
                               pacer=Pacer(sleep=lambda s: None))  # fmt: skip
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert {c.doi for c in result.candidates} == {REVIEW, META, TRIAL, PREPRINT, OTHER}
    assert any(r.params.get("api_key") == NCBI for r in httpd.table.sent)
