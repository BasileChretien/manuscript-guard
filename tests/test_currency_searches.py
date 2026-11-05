"""`references --search` and `--replay`: the fixed searches for one claim, run and recorded,
and the works store filled for the cited work and every candidate.

No test opens a connection to a registry. Most answer from `Registry`, a transport that
answers each service in the shapes the services gave on 2026-11-05 for fictional works; the
real transport is run against a server on a loopback port that stands in for all of them.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, unquote_plus, urlsplit

import currency_records as case
import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.currency import command, records, searching, works
from manuscript_guard.gates.identifiers import doi_of
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.literature.lookups import SCHEMA, answers_digest, entry_digest, write_record
from manuscript_guard.lookup import registries as trials
from manuscript_guard.lookup import search
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport
from manuscript_guard.lookup.run import Credentials, Pacer
from manuscript_guard.lookup.search import Filters

TODAY = date(2026, 11, 5)
NCBI = "ncbi-key-0123456789abcdefSECRET"
TERMS = "drug class hepatic injury"
AGAINST = "drug class no hepatic injury"
CITED_DOI = case.CITED.removeprefix("doi:")
CITED_PMID = "31000900"
UPDATE, COMMENT, ERRATUM = "31000901", "31000902", "31000903"
REVIEW_OA = "10.5555/oa.review.2024"
SR_DOI, SR_PMID = "10.5555/sr.2022", "31000910"
TRIAL_DOI, TRIAL_PMID = "10.5555/trial.2023", "31000920"
NEW_DOI = "10.5555/trial.2026"
NCT = "NCT01234567"
BASE = "https://registry.test"
SERVICES = searching.Services(
    registries=search.Services(
        esearch=f"{BASE}/eutils/esearch.fcgi", esummary=f"{BASE}/eutils/esummary.fcgi",
        europepmc=f"{BASE}/europepmc/search", openalex=f"{BASE}/openalex/works",
        crossref=f"{BASE}/crossref/works/"),
    clinicaltrials=f"{BASE}/ctgov/api/v2/studies/",
)  # fmt: skip


def _json(status: int, data: object) -> Response:
    return Response(status, {}, json.dumps(data).encode())


def _summary(uid: str, doi: str | None, title: str, pubtypes: list[str],
             references: list[dict] | None = None) -> dict:  # fmt: skip
    ids = [{"idtype": "pubmed", "value": uid}] + ([{"idtype": "doi", "value": doi}] if doi else [])
    return {"uid": uid, "title": title, "sortpubdate": "2023/06/01 00:00", "pubtype": pubtypes,
            "articleids": ids, "authors": [{"name": "Example A", "authtype": "Author"}],
            "references": references or []}  # fmt: skip


class Registry:
    """Every registry, answering from what it holds, and keeping what it was sent. `down`
    names services that answer HTTP 503; `retracted_by` names the source that says the trial
    is retracted."""

    def __init__(self) -> None:
        self.sent: list[Request] = []
        self.down: set[str] = set()
        self.retracted_by: str | None = None
        self.newer = False
        #: PMID: (DOI, title, PubMed types)
        self.pubmed = {
            CITED_PMID: (CITED_DOI, "A disproportionality signal", ["Journal Article"]),
            UPDATE: (None, "An update of the signal", ["Journal Article"]),
            COMMENT: (None, "A comment on the signal", ["Comment"]),
            SR_PMID: (SR_DOI, "Hepatic injury: a systematic review", ["Systematic Review"]),
            TRIAL_PMID: (TRIAL_DOI, "Hepatic injury: a randomized trial",
                         ["Randomized Controlled Trial"]),
        }  # fmt: skip

    # -- what each service says ---------------------------------------------------------

    def service(self, request: Request) -> str:
        path = urlsplit(request.base).path
        for name in ("crossref", "europepmc", "openalex", "ctgov"):
            if path.startswith(f"/{name}/"):
                return name
        return path.rsplit("/", 1)[1].split(".")[0]

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append(request)
        name = self.service(request)
        if name in self.down:
            return _json(503, {})
        return getattr(self, f"_{name}")(request, request.params)

    def _esearch(self, request: Request, params: dict) -> Response:
        term = params["term"]
        ids = ([SR_PMID] if "systematic review[pt]" in term
               else [TRIAL_PMID] if params.get("mindate") else [])  # fmt: skip
        return _json(200, {"esearchresult": {"count": str(len(ids) + 30), "idlist": ids}})

    def _esummary(self, request: Request, params: dict) -> Response:
        result: dict = {"uids": []}
        for uid in params["id"].split(","):
            if uid not in self.pubmed:
                result[uid] = {"uid": uid, "error": "cannot get document summary"}
                continue
            doi, title, types = self.pubmed[uid]
            links = ([{"reftype": "Retraction in", "pmid": 39999999, "refsource": "x"}]
                     if uid == TRIAL_PMID and self.retracted_by == "pubmed" else [])
            result[uid] = _summary(uid, doi, title, types, links)
        return _json(200, {"result": result})

    def _europepmc(self, request: Request, params: dict) -> Response:
        query = params["query"]
        if params.get("pageSize") == "1" and (query.startswith("EXT_ID:")
                                              or query.startswith("DOI:")):  # fmt: skip
            return _json(200, {"hitCount": 1, "resultList": {"result": self._epmc_work(query)}})
        if 'PUB_TYPE:"systematic review"' in query:
            items = [self._epmc_item(SR_PMID)]
        elif "FIRST_PDATE" in query:
            items = [self._epmc_item(TRIAL_PMID), {"id": "PPR1", "source": "PPR",
                                                   "title": "No identifier at all"}]
        else:
            items = []
        return _json(200, {"hitCount": len(items) + 5, "resultList": {"result": items}})

    def _epmc_item(self, pmid: str, **extra) -> dict:
        doi, title, types = self.pubmed[pmid]
        item = {"id": pmid, "source": "MED", "pmid": pmid, "title": title,
                "pubYear": "2023", "pubTypeList": {"pubType": types}, **extra}  # fmt: skip
        if doi:
            item["doi"] = doi
        return item

    def _epmc_work(self, query: str) -> list[dict]:
        pmid = query.split("EXT_ID:", 1)[1].split()[0] if query.startswith("EXT_ID:") else None
        doi = query.removeprefix('DOI:"').rstrip('"') if pmid is None else None
        found = pmid or next((uid for uid, held in self.pubmed.items() if held[0] == doi), None)
        if found is None:
            if doi == REVIEW_OA:
                return [{"id": "R1", "source": "MED", "doi": REVIEW_OA, "title": "A review",
                         "abstractText": "<h4>Background</h4>A review of the class.",
                         "firstPublicationDate": "2024-02-01",
                         "pubTypeList": {"pubType": ["Review"]}}]  # fmt: skip
            if doi == NEW_DOI:
                return [{"id": "N1", "source": "MED", "doi": NEW_DOI, "title": "A newer trial",
                         "abstractText": "A newer trial.", "firstPublicationDate": "2026-05-01"}]
            return []
        extra = {"abstractText": f"The abstract of {self.pubmed[found][1]}.",
                 "firstPublicationDate": "2023-06-01"}
        if found == TRIAL_PMID and self.retracted_by == "europepmc":
            extra["commentCorrectionList"] = {"commentCorrection": [
                {"type": "Retraction in", "source": "MED", "id": "39999999"}]}
        return [self._epmc_item(found, **extra)]

    def _openalex(self, request: Request, params: dict) -> Response:
        flt = params.get("filter", "")
        if flt.startswith("doi:"):
            items = [{"id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/{doi}",
                      "is_retracted": doi == TRIAL_DOI and self.retracted_by == "openalex"}
                     for n, doi in enumerate(flt.removeprefix("doi:").split("|"), 100)]
            return _json(200, {"meta": {"count": len(items)}, "results": items})
        if flt.startswith("cites:"):
            items = [{"id": "https://openalex.org/W200", "doi": f"https://doi.org/{REVIEW_OA}",
                      "type": "review", "title": "A review citing the signal"}]
            return _json(200, {"meta": {"count": 54}, "results": items})
        items = [{"id": "https://openalex.org/W300", "doi": f"https://doi.org/{TRIAL_DOI}",
                  "type": "article", "title": "Hepatic injury: a randomized trial"}]
        if self.newer:
            items.append({"id": "https://openalex.org/W301", "doi": f"https://doi.org/{NEW_DOI}",
                          "type": "article", "title": "A newer trial"})
        return _json(200, {"meta": {"count": 12}, "results": items})

    def _crossref(self, request: Request, params: dict) -> Response:
        doi = unquote(request.base).split("/works/", 1)[1]
        notices = ([{"type": "retraction", "DOI": "10.5555/notice"}]
                   if doi == TRIAL_DOI and self.retracted_by == "crossref" else [])
        message = {"DOI": doi, "type": "journal-article", "title": [f"The work {doi}"],
                   "issued": {"date-parts": [[2019, 3]] if doi == CITED_DOI else [[2023, 6, 1]]},
                   "updated-by": notices}  # fmt: skip
        return _json(200, {"status": "ok", "message-type": "work", "message": message})

    def _ctgov(self, request: Request, params: dict) -> Response:
        studies = [{"protocolSection": {"identificationModule": {"nctId": NCT, "briefTitle": "x"},
                                        "statusModule": {"overallStatus": "RECRUITING"}}}]
        return _json(200, {"totalCount": 1, "studies": studies})

    # -- what was asked -------------------------------------------------------------------

    def asked(self, service: str) -> list[Request]:
        return [request for request in self.sent if self.service(request) == service]


def _lookup(root: Path, **sources: dict) -> None:
    """The cited work's lookup record, current: looked up by its DOI, PubMed's PMID for it
    kept with an update, a comment and an erratum."""
    loaded = load_project(root)[0]
    fields = read_entries(root / "literature" / "references.bib")[case.CITED_KEY]
    record = {
        "schema": SCHEMA, "citekey": case.CITED_KEY, "looked_up_on": "2026-10-30",
        "entry_sha256": entry_digest(fields), "identifiers": {"doi": doi_of(fields)},
        "sources": sources or {
            "crossref": {"status": "found", "doi": CITED_DOI, "title": "A signal"},
            "openalex": {"status": "found", "is_retracted": False},
            "pubmed_by_doi": {"status": "found", "pmid": CITED_PMID, "links": [
                {"type": "Update in", "pmid": UPDATE}, {"type": "Comment in", "pmid": COMMENT},
                {"type": "Erratum in", "pmid": ERRATUM}]},
        },
    }  # fmt: skip
    write_record(loaded, {**record, "answers_sha256": answers_digest(record)})


@pytest.fixture
def marked(project: Path) -> Path:
    """The example with its claim marked as c1, its cited work given a DOI, and a current
    lookup record of it."""
    case.given_a_doi(project)
    command.mark(load_project(project)[0], case.MARKED, "@" + case.CITED_KEY, "Ada Example")
    _lookup(project)
    return project


def _search(root: Path, registry: Registry, **kwargs) -> searching.Run:
    return searching.run_search(
        load_project(root)[0], "c1", terms_text=kwargs.pop("terms", TERMS),
        by=kwargs.pop("by", "Ada Example"), transport=registry, services=SERVICES,
        credentials=Credentials(ncbi_key=NCBI), pacer=Pacer(sleep=lambda s: None),
        today=kwargs.pop("today", TODAY), **kwargs)  # fmt: skip


def _records(root: Path) -> list[dict]:
    found = [read.record for read in records.read_searches(load_project(root)[0])]
    return sorted(found, key=lambda one: one["number"])


def _by(found: list[dict]) -> dict[tuple, dict]:
    return {(one["step"], one.get("as_step"), one["source"]): one for one in found}


# ------------------------------------------------------------------------------ the search


def test_every_step_is_run_at_every_source_and_recorded(marked: Path) -> None:
    registry = Registry()
    run = _search(marked, registry)
    assert run.whole, run.lines
    found = _records(marked)
    assert [one["number"] for one in found] == list(range(1, 10))
    assert all(read.problem is None for read in records.read_searches(load_project(marked)[0]))
    by = _by(found)
    assert set(by) == {("S1", None, "pubmed"), ("S1", None, "openalex"),
                       *{(s, None, r) for s in ("S2", "S3") for r in search.REGISTRIES},
                       ("S4", None, "clinicaltrials")}  # fmt: skip
    # S1: PubMed's forward links read from the lookup record, and not asked again; the
    # erratum is no later work on the question.
    links = by[("S1", None, "pubmed")]
    assert links["candidates"] == [f"pmid:{UPDATE}", f"pmid:{COMMENT}"]
    assert links["from_lookup"]["looked_up_on"] == links["searched_on"] == "2026-10-30"
    assert not any("links" in r.params.get("term", "") for r in registry.asked("esearch"))
    citing = by[("S1", None, "openalex")]
    assert citing["filters"] == {"type": "review", "sort": "newest", "limit": 10,
                                 "cites": "W100"}  # fmt: skip
    assert (citing["hits"], citing["candidates"]) == (54, [f"doi:{REVIEW_OA}"])
    # S2: syntheses, at PubMed and Europe PMC; OpenAlex types none and is not asked.
    assert by[("S2", None, "pubmed")]["candidates"] == [f"doi:{SR_DOI}"]
    assert "systematic review[pt]" in unquote_plus(by[("S2", None, "pubmed")]["sent"])
    assert by[("S2", None, "openalex")]["status"] == "not asked"
    assert "systematic review" in by[("S2", None, "openalex")]["why"]
    # S3: from the cited work's publication date, as its works record gives it.
    for source in search.REGISTRIES:
        assert by[("S3", None, source)]["cutoff"]["date"] == "2019-03"
    assert by[("S3", None, "europepmc")]["unidentified"] == 1
    # S4: pending, never candidates.
    trials_record = by[("S4", None, "clinicaltrials")]
    assert (trials_record["status"], trials_record["trials"], trials_record["candidates"]) == (
        "pending", [NCT], [])
    # The terms as sent, who wrote them, and no key in any record.
    assert {one["query"] for one in found if one["step"] in ("S2", "S3", "S4")} == {TERMS}
    assert {one["terms_by"] for one in found} == {"Ada Example"}
    assert not any(NCBI in json.dumps(one) for one in found)


def test_each_registry_is_asked_from_the_cutoff_by_its_finest_date_filter() -> None:
    filters = Filters(from_date="2019-03", limit=5)
    services = search.Services()
    pubmed = search.pubmed_search(TERMS, filters, Credentials(), services).params
    assert (pubmed["datetype"], pubmed["mindate"], pubmed["maxdate"]) == ("pdat", "2019/03/01",
                                                                          "3000")
    assert "FIRST_PDATE:[2019-03-01 TO 3000-12-31]" in search.europepmc_query(TERMS, filters)
    assert search.openalex_filter(filters) == "from_publication_date:2019-03-01"
    assert search.first_day("2020") == "2020-01-01"
    assert search.first_day("2020-02-29") == "2020-02-29"


def test_the_works_store_holds_the_cited_work_and_every_candidate(marked: Path) -> None:
    _search(marked, Registry())
    loaded = load_project(marked)[0]
    held = {path.stem for path in records.works_folder(loaded).glob("*.yaml")}
    wanted = {case.CITED, f"pmid:{UPDATE}", f"pmid:{COMMENT}", f"doi:{REVIEW_OA}",
              f"doi:{SR_DOI}", f"doi:{TRIAL_DOI}"}  # fmt: skip
    assert held == {records.safe_name(work) for work in wanted}
    cited = records.read_work(loaded, case.CITED).record
    # Crossref's date where there is a DOI; PubMed's types by the PMID PubMed gives the DOI,
    # which is not written among the cited work's identifiers.
    assert (cited["published"], cited["publication_types"]) == ("2019-03", ["Journal Article"])
    assert cited["identifiers"] == {"doi": CITED_DOI}
    trial = records.read_work(loaded, f"doi:{TRIAL_DOI}").record
    assert trial["identifiers"] == {"doi": TRIAL_DOI, "pmid": TRIAL_PMID}
    assert trial["publication_types"] == ["Randomized Controlled Trial"]
    assert trial["abstract"].startswith("The abstract of Hepatic injury")
    assert trial["sources"] == ["europepmc", "crossref", "pubmed", "openalex"]
    assert trial["integrity"] == {"retracted": False, "withdrawn": False, "under_concern": False}
    # No PMID: Europe PMC's types and first publication date.
    review = records.read_work(loaded, f"doi:{REVIEW_OA}").record
    assert (review["publication_types"], review["abstract"]) == (["Review"],
                                                                "Background A review of the class.")
    comment = records.read_work(loaded, f"pmid:{COMMENT}").record
    assert (comment["published"], comment["sources"]) == ("2023-06-01", ["europepmc", "pubmed"])
    assert (records.works_folder(loaded) / ".gitignore").is_file()


@pytest.mark.parametrize("source", ["crossref", "pubmed", "europepmc", "openalex"])
def test_a_work_any_source_says_is_retracted_is_retracted(marked: Path, source: str) -> None:
    registry = Registry()
    registry.retracted_by = source
    _search(marked, registry)
    trial = records.read_work(load_project(marked)[0], f"doi:{TRIAL_DOI}").record
    assert trial["integrity"]["retracted"] is True


def test_a_works_record_is_written_only_where_every_source_answered(marked: Path) -> None:
    _search(marked, Registry())
    loaded = load_project(marked)[0]
    before = records.work_path(loaded, f"doi:{TRIAL_DOI}").read_bytes()
    registry = Registry()
    registry.retracted_by = "pubmed"
    registry.down = {"crossref"}
    run = _search(marked, registry, today=date(2026, 11, 20))
    assert not run.whole
    assert any("Crossref" in line and "did not answer" in line for line in run.lines)
    # The trial is not written as "not retracted" on PubMed's word alone, nor kept from it:
    # its record stays as it was.
    assert records.work_path(loaded, f"doi:{TRIAL_DOI}").read_bytes() == before


def test_a_source_that_does_not_answer_is_not_recorded(marked: Path) -> None:
    registry = Registry()
    registry.down = {"ctgov", "esearch"}
    run = _search(marked, registry)
    assert not run.whole
    sources = {(one["step"], one["source"]) for one in _records(marked)}
    assert ("S4", "clinicaltrials") not in sources and ("S2", "pubmed") not in sources
    assert ("S2", "europepmc") in sources
    assert any(line.startswith("S4 ClinicalTrials.gov: did not answer") for line in run.lines)


def test_a_search_run_again_is_further_records_and_never_written_over(marked: Path) -> None:
    _search(marked, Registry())
    first = {one["number"]: one["answers_sha256"] for one in _records(marked)}
    _search(marked, Registry(), today=date(2026, 11, 6))
    found = _records(marked)
    assert len(found) == 2 * len(first)
    assert {one["number"]: one["answers_sha256"] for one in found if one["number"] in first} \
        == first  # fmt: skip
    # A number taken is never written over, even by a writer that names it.
    loaded = load_project(marked)[0]
    path = records.search_path(loaded, "c1", 1)
    before = path.read_bytes()
    new = records.file_search(loaded, {**found[0], "number": 1})
    assert path.read_bytes() == before and new.name == f"c1-{len(found) + 1}.yaml"


def test_against_is_run_as_s2_and_as_s3(marked: Path) -> None:
    registry = Registry()
    _search(marked, registry, against_text=AGAINST)
    by = _by(_records(marked))
    assert {key for key in by if key[0] == "S8"} == {
        ("S8", step, source) for step in ("S2", "S3") for source in search.REGISTRIES}
    assert by[("S8", "S2", "pubmed")]["query"] == AGAINST
    assert "systematic review[pt]" in unquote_plus(by[("S8", "S2", "pubmed")]["sent"])
    assert by[("S8", "S3", "openalex")]["cutoff"]["date"] == "2019-03"
    assert ("S8", None, "clinicaltrials") not in by


def test_the_cutoff_is_a_synthesis_search_end_a_reading_gives_where_later(marked: Path) -> None:
    _search(marked, Registry())
    loaded = load_project(marked)[0]
    reading = case.reading("Ada Example", candidate=f"doi:{SR_DOI}")
    reading["candidates"][0]["search_end"] = {"value": "2021-06", "quote": "searched to June"}
    records.file_reading(loaded, reading, "2026-11-05")
    cut = searching.cutoff(loaded, searching._claim(loaded, "c1"))
    assert cut["date"] == "2021-06" and f"doi:{SR_DOI}" in cut["from"]
    registry = Registry()
    _search(marked, registry, today=date(2026, 11, 6))
    assert {r.params.get("mindate") for r in registry.asked("esearch")} >= {"2021/06/01"}
    # A search end before the cited work's publication leaves the publication date.
    earlier = case.reading("Bea Example", candidate=f"doi:{SR_DOI}")
    earlier["candidates"][0]["search_end"] = {"value": "2018", "quote": "searched to 2018"}
    records.file_reading(loaded, earlier, "2026-11-05")
    assert searching.cutoff(loaded, searching._claim(loaded, "c1"))["date"] == "2021-06"


def test_a_replay_runs_each_recorded_search_as_recorded(marked: Path) -> None:
    _search(marked, Registry(), against_text=AGAINST)
    before = _records(marked)
    registry = Registry()
    registry.newer = True
    run = searching.replay(load_project(marked)[0], "c1", transport=registry,
                           services=SERVICES, credentials=Credentials(),
                           pacer=Pacer(sleep=lambda s: None), today=date(2027, 1, 2))
    assert run.whole, run.lines
    again = [one for one in _records(marked) if one.get("replay_of")]
    asked = [one for one in before if one.get("status", "run") != "not asked"]
    assert len(again) == len(asked)
    for one in again:
        was = next(old for old in before if old["number"] == one["replay_of"])
        for key in ("step", "as_step", "source", "query", "filters", "cutoff", "terms_by"):
            assert one.get(key) == was.get(key), key
    # OpenAlex is asked for the citing works by the id recorded, and by the DOI only for
    # the cited work's works record.
    assert sum(r.params.get("filter", "") == f"doi:{CITED_DOI}"
               for r in registry.asked("openalex")) == 1
    assert f"new since the last run: doi:{NEW_DOI}" in run.lines
    assert records.read_work(load_project(marked)[0], f"doi:{NEW_DOI}").record is not None


def test_a_replay_with_nothing_recorded_is_refused(marked: Path) -> None:
    with pytest.raises(command.Refused, match="no recorded search"):
        searching.replay(load_project(marked)[0], "c1", transport=Registry())


@pytest.mark.parametrize("replaying", [False, True])
def test_a_dry_run_sends_nothing_and_writes_nothing(marked: Path, replaying: bool) -> None:
    if replaying:
        _search(marked, Registry())
    snapshot = sorted((path, path.read_bytes()) for path in marked.rglob("*") if path.is_file())
    registry = Registry()
    loaded = load_project(marked)[0]
    if replaying:
        run = searching.replay(loaded, "c1", dry_run=True, transport=registry, services=SERVICES)
    else:
        run = searching.run_search(loaded, "c1", terms_text=TERMS, by="Ada", dry_run=True,
                                   question="Does the class cause hepatic injury?",
                                   transport=registry, services=SERVICES)  # fmt: skip
    assert registry.sent == []
    assert sorted((p, p.read_bytes()) for p in marked.rglob("*") if p.is_file()) == snapshot
    said = "\n".join(run.lines)
    assert "nothing was sent" in said and "S4 ClinicalTrials.gov: would ask" in said
    assert "hepatic injury?" not in said


@pytest.mark.parametrize(
    ("kwargs", "said"),
    [({"terms": "  "}, "the query is empty"),
     ({"terms": "x" * 301}, "not a passage of the manuscript"),
     ({"against_text": "y" * 301}, "--against"),
     ({"by": " "}, "--as names who wrote the terms")],
)  # fmt: skip
def test_terms_are_held_to_the_rule_of_search_and_signed(marked: Path, kwargs, said) -> None:
    registry = Registry()
    with pytest.raises(command.Refused, match=said):
        _search(marked, registry, **kwargs)
    assert registry.sent == []


def test_a_claim_whose_cited_work_has_no_current_lookup_record_is_refused(marked: Path) -> None:
    loaded = load_project(marked)[0]
    (marked / "literature" / "lookups" / f"{case.CITED_KEY}.yaml").unlink()
    with pytest.raises(command.Refused, match="run `manuscript-guard lookup` first"):
        _search(marked, Registry())
    assert records.read_searches(loaded) == []


def test_a_cited_work_pubmed_does_not_hold_is_not_asked_there(marked: Path) -> None:
    _lookup(marked, crossref={"status": "found", "doi": CITED_DOI},
            pubmed_by_doi={"status": "absent", "count": 0})  # fmt: skip
    _search(marked, Registry())
    links = _by(_records(marked))[("S1", None, "pubmed")]
    assert links["status"] == "not asked" and "2026-10-30" in links["why"]


def test_the_question_is_written_and_never_sent(marked: Path) -> None:
    registry = Registry()
    question = "In adults, does the drug class cause hepatic injury?"
    _search(marked, registry, question=question)
    document = yaml.safe_load((marked / "literature" / "currency.yaml").read_text("utf-8"))
    assert document["entries"][0]["question"] == question
    assert not any("adults, does" in request.url for request in registry.sent)
    # Searched for it, the entry is not framed again by the command.
    with pytest.raises(command.Refused, match="does not frame it again"):
        _search(marked, Registry(), question="Another question?")
    _search(marked, Registry(), question=question)  # the same question is no change


def test_a_question_is_written_when_a_claim_is_marked(project: Path) -> None:
    case.given_a_doi(project)
    assert main(["references", str(project), "--mark", case.MARKED, "@" + case.CITED_KEY,
                 "--question", "Does the class cause  hepatic injury?"]) == 0
    document = yaml.safe_load((project / "literature" / "currency.yaml").read_text("utf-8"))
    assert document["entries"][0]["question"] == "Does the class cause hepatic injury?"


def test_the_project_sets_how_many_works_are_kept(marked: Path) -> None:
    paper = marked / "paper.yaml"
    paper.write_text(paper.read_text("utf-8") + "\nreferences:\n  search_limit: 3\n", "utf-8")
    registry = Registry()
    _search(marked, registry)
    assert {r.params["retmax"] for r in registry.asked("esearch")} == {"3"}
    assert {r.params["pageSize"] for r in registry.asked("ctgov")} == {"3"}
    paper.write_text(paper.read_text("utf-8").replace("search_limit: 3", "search_limit: 51"),
                     "utf-8")  # fmt: skip
    report = load_project(marked)[1]
    assert any("search_limit" in finding.message for finding in report.failures)


def test_explain_says_each_search_and_the_gate_reads_their_dates(marked: Path,
                                                                   monkeypatch) -> None:
    from manuscript_guard.gates import currency as gate

    _search(marked, Registry())
    loaded = load_project(marked)[0]
    said = command.explain(loaded, "c1")
    assert f"(S2, openalex, {TODAY}): {TERMS!r} by Ada Example, not asked:" in said
    assert f"(S4, clinicaltrials, {TODAY}): {TERMS!r} by Ada Example, 1 ongoing, pending: " \
        f"{NCT}" in said  # fmt: skip
    monkeypatch.setattr(gate, "today", lambda: date(2027, 6, 1))
    stale = [f for f in gate.check_currency(loaded).findings if f.code == "currency-record-stale"]
    assert stale and str(TODAY) in stale[0].message


# ----------------------------------------------------------------------------- the clients


def test_clinicaltrials_is_asked_for_ongoing_studies_and_read_to_their_numbers() -> None:
    sent: list[Request] = []

    def ask(answer: Response):
        return lambda request: (sent.append(request), answer)[1]

    good = Registry()._ctgov(Request(""), {})
    said = trials.clinicaltrials_search(TERMS, 5, ask(good), "https://x.test/api/v2/studies/")
    assert said == {"status": "found", "count": 1, "trials": [NCT]}
    params = sent[0].params
    assert sent[0].base == "https://x.test/api/v2/studies" and params["query.term"] == TERMS
    assert params["filter.overallStatus"].split("|") == list(trials.ONGOING)
    assert (params["pageSize"], params["countTotal"]) == ("5", "true")
    none = _json(200, {"totalCount": 0, "studies": []})
    assert trials.clinicaltrials_search(TERMS, 5, ask(none), "https://x.test/s")["status"] \
        == "absent"  # fmt: skip
    for wrong in (_json(200, {"studies": []}), _json(200, {"totalCount": 1, "studies": [{}]}),
                  _json(500, {}), Response(200, {}, b"<html>")):  # fmt: skip
        assert trials.clinicaltrials_search(TERMS, 5, ask(wrong), "https://x.test/s")[
            "status"] == "unresolvable"  # fmt: skip


def test_europe_pmc_facts_carry_types_dates_integrity_and_a_published_version() -> None:
    item = {"id": "PPR9", "source": "PPR", "doi": "10.5555/pre", "title": "A preprint",
            "firstPublicationDate": "2024-01-31", "abstractText": "Text.",
            "pubTypeList": {"pubType": ["Preprint"]},
            "commentCorrectionList": {"commentCorrection": [
                {"type": "Preprint of", "source": "MED", "id": "31000930"},
                {"type": "Expression of concern in", "source": "MED", "id": "31000931"}]}}
    answer = _json(200, {"hitCount": 1, "resultList": {"result": [item]}})
    said = search.europepmc_facts("10.5555/pre", None, lambda r: answer, search.Services())
    assert said == {"status": "found", "abstract": "Text.", "title": "A preprint",
                    "doi": "10.5555/pre", "pubtypes": ["Preprint"],
                    "first_published": "2024-01-31", "retracted": False,
                    "under_concern": True, "published_as": ["pmid:31000930"]}  # fmt: skip
    # Another work's record, asked by a DOI, is none.
    other = _json(200, {"hitCount": 1, "resultList": {"result": [{**item, "doi": "10.5/o"}]}})
    assert search.europepmc_facts("10.5555/pre", None, lambda r: other,
                                  search.Services()) == {"status": "absent"}


def test_openalex_is_asked_for_the_reviews_citing_a_work_newest_first() -> None:
    request = search.openalex_citing_search("W100", 7, Credentials(openalex_key="k" * 12),
                                            search.Services())  # fmt: skip
    assert request.params["filter"] == "cites:W100,type:review"
    assert (request.params["sort"], request.params["per_page"]) == ("publication_date:desc", "7")
    assert "k" * 12 not in request.shown
    hit = search._openalex_hit(1, {"id": "https://openalex.org/W2741809807"})
    assert hit.openalex_id == "W2741809807"


def test_the_query_rule_is_one_for_search_and_references() -> None:
    assert search.folded_query("  a \n b ") == ("a b", None)
    assert search.folded_query("")[1] == "nothing to search for: the query is empty"
    assert "300" in search.folded_query("x" * 301)[1]


def test_composed_works_record_reads_withdrawal_and_concern_from_crossref() -> None:
    one = works.wanted("doi:10.5/x")
    record = works.composed(one, {"crossref": {"updated_by": [
        {"type": "withdrawal"}, {"type": "expression_of_concern"}],
        "preprint_of": ["10.5/Y"], "dates": {"online": "2020-01"}}}, TODAY)  # fmt: skip
    assert record["integrity"] == {"retracted": False, "withdrawn": True, "under_concern": True,
                                   "published_as": ["doi:10.5/y"]}  # fmt: skip
    assert record["published"] == "2020-01" and record["sources"] == ["crossref"]


# ----------------------------------------------------------------------------- the command


def test_the_command_searches_and_exits_by_whether_every_source_answered(
    marked: Path, monkeypatch, capsys
) -> None:
    registry = Registry()
    monkeypatch.setattr(searching, "default_transport", registry)
    monkeypatch.setattr(searching, "Services", lambda: SERVICES)
    monkeypatch.setattr(searching, "Pacer", lambda **kw: Pacer(sleep=lambda s: None, **kw))
    monkeypatch.setenv("NCBI_API_KEY", NCBI)
    argv = ["references", str(marked), "--search", "c1", "--terms", TERMS, "--as", "Ada"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "c1-1 S1 PubMed: 2 matched, 2 kept (from the lookup of 2026-10-30)" in out
    assert NCBI not in out
    registry.down = {"europepmc"}
    assert main(argv) == 1
    assert main(["references", str(marked), "--replay", "c1"]) == 1
    registry.down = set()
    assert main(["references", str(marked), "--replay", "c1", "--dry-run"]) == 0
    assert "nothing was sent" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "said"),
    [(["--search", "c1", "--as", "Ada"], "--terms names the terms"),
     (["--search", "c1", "--terms", TERMS], "--as names who wrote the terms"),
     (["--search", "c9", "--terms", TERMS, "--as", "Ada"], "no entry c9"),
     (["--terms", TERMS], "go with --search or --replay"),
     (["--explain", "c1", "--dry-run"], "go with --search or --replay"),
     (["--replay", "c1", "--terms", TERMS], "takes no --terms")],
)  # fmt: skip
def test_the_command_refuses_what_it_cannot_run(marked: Path, monkeypatch, capsys, argv,
                                               said) -> None:  # fmt: skip
    def refused(request, timeout):
        raise AssertionError("a request was sent")

    monkeypatch.setattr(searching, "default_transport", refused)
    assert main(["references", str(marked), *argv]) == 2
    assert said in capsys.readouterr().err


# ------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        parts = urlsplit(self.path)
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        answer = self.server.registry(Request(BASE + parts.path, params), 5.0)
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer.body)))
        self.end_headers()
        self.wfile.write(answer.body)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


def test_the_real_transport_runs_every_search_on_loopback(marked: Path) -> None:
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.registry = Registry()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        try:
            default_transport(Request(url + "/eutils/probe.fcgi"), 5)
        except NoAnswer as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"loopback connections are not allowed here: {exc}")
        httpd.registry.sent.clear()
        services = searching.Services(
            registries=search.Services(
                esearch=f"{url}/eutils/esearch.fcgi", esummary=f"{url}/eutils/esummary.fcgi",
                europepmc=f"{url}/europepmc/search", openalex=f"{url}/openalex/works",
                crossref=f"{url}/crossref/works/"),
            clinicaltrials=f"{url}/ctgov/api/v2/studies")  # fmt: skip
        run = searching.run_search(load_project(marked)[0], "c1", terms_text=TERMS, by="Ada",
                                   services=services, credentials=Credentials(ncbi_key=NCBI),
                                   pacer=Pacer(sleep=lambda s: None), today=TODAY)  # fmt: skip
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert run.whole, run.lines
    by = _by(_records(marked))
    assert by[("S4", None, "clinicaltrials")]["trials"] == [NCT]
    assert by[("S1", None, "openalex")]["candidates"] == [f"doi:{REVIEW_OA}"]
    assert records.read_work(load_project(marked)[0], f"doi:{TRIAL_DOI}").record["abstract"]
    assert any(r.params.get("api_key") == NCBI for r in httpd.registry.sent)


def test_a_filed_search_record_edited_by_hand_is_caught(marked: Path) -> None:
    from manuscript_guard.gates.currency import check_currency

    _search(marked, Registry())
    loaded = load_project(marked)[0]
    path = records.search_path(loaded, "c1", 3)
    text = path.read_text(encoding="utf-8")
    assert f"doi:{SR_DOI}" in text
    path.write_text(text.replace(f"doi:{SR_DOI}", "doi:10.5555/another"), encoding="utf-8")
    codes = {f.code for f in check_currency(loaded).findings}
    assert "currency-record-edited" in codes
