"""`lookup`: each cited DOI and PMID asked of the registries once, and the answer kept.

No test opens a connection to a registry. Most answer from a table; the real transport is run
against a server on a loopback port that stands in for all five. The answers are written
here in the shapes the services document, with fictional works.
"""

from __future__ import annotations

import ast
import json
import shutil
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts.project import load_project
from manuscript_guard.literature.lookups import entry_digest, file_name, read_record, record_path
from manuscript_guard.lookup import run as lookup
from manuscript_guard.lookup import sources
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "example"
TODAY = date(2026, 10, 15)
CONTACT = "author@example.org"
NCBI = "ncbi-key-0123456789abcdefSECRET"
OPENALEX = "openalex-key-0123456789SECRET"

DOI = "10.5555/fictional.2021.001"
PMID = "31000001"


def _json(status: int, data: object, headers: dict | None = None) -> Response:
    return Response(status, headers or {}, json.dumps(data).encode())


def _crossref_work(doi: str = DOI, **extra) -> dict:
    return {
        "status": "ok",
        "message-type": "work",
        "message": {
            "DOI": doi,
            "type": "journal-article",
            "title": ["Hepatic injury in a fictional cohort"],
            "container-title": ["Journal of Examples"],
            "issued": {"date-parts": [[2021, 3]]},
            "published-print": {"date-parts": [[2021, 4, 1]]},
            "published-online": {"date-parts": [[2021, 3, 2]]},
            "volume": "12",
            "page": "101-109",
            **extra,
        },
    }


_OPENALEX = {"id": "https://openalex.org/W1", "is_retracted": False, "title": "Hepatic injury",
             "type": "article", "publication_year": 2021}  # fmt: skip
_DATACITE = {"data": {"attributes": {"titles": [{"title": "A fictional dataset"}],
             "types": {"resourceTypeGeneral": "Dataset"}, "publicationYear": 2020}}}  # fmt: skip
_PUBMED = {
    "header": {"type": "esummary"},
    "result": {
        "uids": [PMID],
        PMID: {
            "uid": PMID,
            "title": "Hepatic injury in a fictional cohort.",
            "sortpubdate": "2021/04/01 00:00",
            "pubtype": ["Journal Article"],
            "articleids": [{"idtype": "pubmed", "value": PMID}, {"idtype": "doi", "value": DOI}],
            "volume": "12",
            "pages": "101-9",
        },
    },
}


class Table:
    """A transport that answers from a function of the path, and keeps what it was sent."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.sent: list[Request] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append(request)
        return self.answer(urlsplit(request.base).path, request)


def _registries(crossref=None, openalex=None, datacite=None, doi_org=None, pubmed=None):
    """Answers by service; each default is the work found."""
    defaults = {
        "crossref": crossref or _json(200, _crossref_work()),
        "openalex": openalex or _json(200, _OPENALEX),
        "datacite": datacite or _json(404, {"errors": [{"status": "404"}]}),
        "doi_org": doi_org or _json(200, {"responseCode": 1, "handle": DOI, "values": []}),
        "pubmed": pubmed or _json(200, _PUBMED),
    }

    def answer(path: str, request: Request) -> Response:
        name = path.strip("/").split("/")[0]
        return defaults[name]

    return Table(answer)


SERVICES = lookup.Services(
    crossref="https://registry.test/crossref/",
    openalex="https://registry.test/openalex/doi:",
    datacite="https://registry.test/datacite/",
    doi_org="https://registry.test/doi_org/",
    pubmed="https://registry.test/pubmed/esummary.fcgi",
    esearch="https://registry.test/esearch/esearch.fcgi",
    crossref_search="https://registry.test/crossref_search",
    openalex_search="https://registry.test/openalex_search",
)


def _ask(table: Table):
    return lambda request: table(request, 1.0)


# ------------------------------------------------------------------- what each one answers


def test_a_value_the_record_cannot_hold_is_not_kept() -> None:
    """Round 1 of #253: an empty publication type, a notice of no kind, a year of five
    digits. Kept, they made `lookup` stop on a record its schema refuses."""
    pubmed = {**_PUBMED["result"][PMID], "pubtype": ["", "Journal Article", " "]}
    answer = _json(200, {"header": {}, "result": {"uids": [PMID], PMID: pubmed}})
    found = sources.pubmed(PMID, _ask(_registries(pubmed=answer)), SERVICES.pubmed, None, None)
    assert found["pubtypes"] == ["Journal Article"]
    notices = [{"type": " ", "DOI": "10.5/a"},
               {"type": "retraction", "updated": {"date-parts": [[20231]]}}]  # fmt: skip
    work = _crossref_work(**{"updated-by": notices})
    ask = _ask(_registries(crossref=_json(200, work)))
    found = sources.crossref(DOI, ask, SERVICES.crossref, None)
    assert found["updated_by"] == [{"type": "retraction"}]


def test_a_work_crossref_knows_is_read_with_its_years_and_pages() -> None:
    found = sources.crossref(DOI, _ask(_registries()), SERVICES.crossref, None)
    assert found["status"] == sources.FOUND
    assert found["title"] == "Hepatic injury in a fictional cohort"
    assert found["years"] == {"print": 2021, "online": 2021, "issued": 2021}
    assert (found["volume"], found["page"]) == ("12", "101-109")


def test_a_retraction_is_read_from_updated_by_whoever_files_it() -> None:
    """Crossmark writes `expression_of_concern`, the Retraction Watch data
    `expression-of-concern`: the record has one kind for both."""
    notices = [
        {"DOI": "10.5555/NOTICE.1", "type": "retraction", "source": "retraction-watch",
         "updated": {"date-parts": [[2023, 2, 6]]}, "record-id": 1},
        {"DOI": "10.5555/notice.2", "type": "expression-of-concern", "source": "publisher",
         "updated": {"date-parts": [[2022, 5]]}},
    ]  # fmt: skip
    table = _registries(crossref=_json(200, _crossref_work(**{"updated-by": notices})))
    found = sources.crossref(DOI, _ask(table), SERVICES.crossref, None)
    assert found["updated_by"] == [
        {"type": "retraction", "doi": "10.5555/notice.1", "date": "2023-02-06",
         "source": "retraction-watch"},
        {"type": "expression_of_concern", "doi": "10.5555/notice.2", "date": "2022-05",
         "source": "publisher"},
    ]  # fmt: skip


def test_a_notice_is_read_from_update_to_and_a_preprint_from_its_relation() -> None:
    notice = _crossref_work(
        **{"update-to": [{"DOI": DOI, "type": "retraction", "updated": {"date-parts": [[2023]]}}]}
    )
    ask = _ask(_registries(crossref=_json(200, notice)))
    found = sources.crossref(DOI, ask, SERVICES.crossref, None)
    assert found["update_to"] == [{"type": "retraction", "doi": DOI, "date": "2023"}]
    preprint = _crossref_work(
        type="posted-content",
        subtype="preprint",
        posted={"date-parts": [[2020, 9, 1]]},
        relation={"is-preprint-of": [{"id-type": "doi", "id": "10.5555/Published"}]},
    )
    ask = _ask(_registries(crossref=_json(200, preprint)))
    found = sources.crossref(DOI, ask, SERVICES.crossref, None)
    assert (found["type"], found["subtype"]) == ("posted-content", "preprint")
    assert found["preprint_of"] == ["10.5555/published"]
    assert found["years"]["posted"] == 2020


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (Response(404, {}, b"Resource not found."), sources.ABSENT),
        (Response(429, {}, b""), sources.UNRESOLVABLE),
        (Response(500, {}, b""), sources.UNRESOLVABLE),
        (Response(301, {"Location": "https://elsewhere.test/"}, b""), sources.UNRESOLVABLE),
        # A 200 is not a work: an error in the body, another kind of message, no JSON.
        (_json(200, {"status": "failed", "message": "boom"}), sources.UNRESOLVABLE),
        (_json(200, {"status": "ok", "message-type": "work-list", "message": {}}),
         sources.UNRESOLVABLE),
        (Response(200, {}, b"<html>busy</html>"), sources.UNRESOLVABLE),
    ],
)  # fmt: skip
def test_only_crossref_s_documented_answers_are_found_or_absent(answer, status) -> None:
    found = sources.crossref(DOI, _ask(_registries(crossref=answer)), SERVICES.crossref, None)
    assert found["status"] == status
    if status == sources.UNRESOLVABLE:
        assert found["why"] and "registry.test" not in found["why"]


def test_a_transport_that_gets_no_answer_is_unresolvable() -> None:
    def broken(request: Request, timeout: float) -> Response:
        raise NoAnswer("no answer within 30 s")

    found = sources.crossref(DOI, lambda r: broken(r, 1.0), SERVICES.crossref, None)
    assert found == {"status": sources.UNRESOLVABLE, "why": "no answer within 30 s"}


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (_json(200, {**_OPENALEX, "is_retracted": True}), sources.FOUND),
        (Response(404, {}, b""), sources.ABSENT),
        (_json(200, {"id": "https://openalex.org/W1"}), sources.UNRESOLVABLE),
        (_json(200, {"error": "Invalid query", "message": "x"}), sources.UNRESOLVABLE),
        (Response(429, {}, b""), sources.UNRESOLVABLE),
    ],
)
def test_openalex_says_retracted_only_in_its_own_shape(answer, status) -> None:
    found = sources.openalex(DOI, _ask(_registries(openalex=answer)), SERVICES.openalex, None)
    assert found["status"] == status
    if status == sources.FOUND:
        assert found["is_retracted"] is True


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (_json(200, _DATACITE), sources.FOUND),
        (_json(404, {"errors": [{"status": "404"}]}), sources.ABSENT),
        (_json(200, {"data": []}), sources.UNRESOLVABLE),
    ],
)
def test_datacite_answers_for_a_dataset(answer, status) -> None:
    found = sources.datacite(DOI, _ask(_registries(datacite=answer)), SERVICES.datacite)
    assert found["status"] == status
    if status == sources.FOUND:
        assert (found["title"], found["type"], found["year"]) == (
            "A fictional dataset", "Dataset", 2020
        )  # fmt: skip


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (_json(200, {"responseCode": 1, "handle": DOI, "values": []}), sources.FOUND),
        (_json(200, {"responseCode": 200, "handle": DOI}), sources.FOUND),
        (_json(404, {"responseCode": 100, "handle": DOI}), sources.ABSENT),
        # A 404 that is not the handle server's "not found" is not proof of anything.
        (Response(404, {}, b"<html>not here</html>"), sources.UNRESOLVABLE),
        (_json(500, {"responseCode": 2, "handle": DOI}), sources.UNRESOLVABLE),
        (_json(200, {"responseCode": 2, "handle": DOI}), sources.UNRESOLVABLE),
    ],
)
def test_doi_org_says_registered_or_not_only_by_its_response_code(answer, status) -> None:
    found = sources.doi_org(DOI, _ask(_registries(doi_org=answer)), SERVICES.doi_org)
    assert found["status"] == status


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (_json(200, _PUBMED), sources.FOUND),
        (_json(200, {"header": {}, "result": {"uids": [PMID], PMID: {
            "uid": PMID, "error": "cannot get document summary"}}}), sources.ABSENT),
        # E-utilities answers an error with a 200.
        (_json(200, {"error": "API key invalid", "api-key": "x"}), sources.UNRESOLVABLE),
        (_json(200, {"header": {}, "result": {"uids": []}}), sources.UNRESOLVABLE),
        (Response(429, {}, b""), sources.UNRESOLVABLE),
    ],
)  # fmt: skip
def test_pubmed_is_found_or_absent_only_in_its_own_shape(answer, status) -> None:
    found = sources.pubmed(PMID, _ask(_registries(pubmed=answer)), SERVICES.pubmed, None, None)
    assert found["status"] == status
    if status == sources.FOUND:
        assert (found["doi"], found["year"], found["pubtypes"]) == (DOI, 2021, ["Journal Article"])


# ------------------------------------------------------------------------- the project


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The example, its first reference given a DOI and a PMID, its second a DOI."""
    root = tmp_path / "paper"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build", ".git"))
    _identify(root, "fictionalHepaticCohort2021", doi=f"https://doi.org/{DOI.upper()}", pmid=PMID)
    _identify(root, "fictionalClassSignal2019", doi="10.5555/fictional.2019.002")
    return root


def _identify(root: Path, key: str, **fields: str) -> None:
    bib = root / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    opening = f"@article{{{key},\n"
    added = "".join(f"  {name} = {{{value}}},\n" for name, value in fields.items())
    assert text.count(opening) == 1
    bib.write_text(text.replace(opening, opening + added), encoding="utf-8")


def _loaded(root: Path):
    return load_project(root)[0]


def _run(root: Path, table: Table, *, again: bool = False, credentials=None) -> list:
    project = _loaded(root)
    return lookup.run(
        project,
        lookup.plan(project, again=again),
        transport=table,
        services=SERVICES,
        credentials=credentials or lookup.Credentials(),
        pacer=lookup.Pacer(sleep=lambda s: None),
        today=TODAY,
        said=lambda line: None,
    )


def test_each_cited_reference_is_looked_up_and_its_record_written(project: Path) -> None:
    written = _run(project, _registries())
    assert [one.citekey for one, _r, _p in written] == [
        "fictionalHepaticCohort2021", "fictionalClassSignal2019"
    ]  # fmt: skip
    record = read_record(_loaded(project), "fictionalHepaticCohort2021")
    assert record["identifiers"] == {"doi": DOI, "pmid": PMID}
    assert record["looked_up_on"] == "2026-10-15"
    assert set(record["sources"]) == {"crossref", "openalex", "pubmed"}
    assert record["sources"]["pubmed"]["doi"] == DOI


def test_datacite_is_asked_only_where_crossref_does_not_know_the_doi(project: Path) -> None:
    """A dataset's DOI: Crossref answers 404, DataCite knows it, doi.org is not asked."""
    table = _registries(crossref=Response(404, {}, b"Resource not found."),
                        datacite=_json(200, _DATACITE))  # fmt: skip
    _run(project, table)
    record = read_record(_loaded(project), "fictionalClassSignal2019")
    assert record["sources"]["crossref"]["status"] == sources.ABSENT
    assert record["sources"]["datacite"]["status"] == sources.FOUND
    assert "doi_org" not in record["sources"]
    asked = [urlsplit(r.base).path.split("/")[1] for r in table.sent]
    assert "doi_org" not in asked


def test_doi_org_is_asked_where_neither_crossref_nor_datacite_knows_it(project: Path) -> None:
    table = _registries(crossref=Response(404, {}, b""))
    _run(project, table)
    record = read_record(_loaded(project), "fictionalClassSignal2019")
    assert record["sources"]["datacite"]["status"] == sources.ABSENT
    assert record["sources"]["doi_org"]["status"] == sources.FOUND


def test_a_record_that_answers_for_its_entry_is_not_looked_up_again(project: Path) -> None:
    _run(project, _registries())
    table = _registries()
    assert _run(project, table) == [] and table.sent == []
    assert {p.skipped for p in lookup.plan(_loaded(project))} == {"up to date"}
    assert len(_run(project, table, again=True)) == 2


def test_an_entry_changed_since_its_lookup_is_looked_up_again(project: Path) -> None:
    _run(project, _registries())
    _identify(project, "fictionalClassSignal2019", number="3")
    planned = {p.citekey: p for p in lookup.plan(_loaded(project))}
    assert planned["fictionalClassSignal2019"].again == "the entry changed since it was looked up"
    assert planned["fictionalHepaticCohort2021"].skipped == "up to date"


def test_an_answer_that_did_not_come_is_asked_for_again(project: Path) -> None:
    _run(project, _registries(openalex=Response(429, {}, b"")))
    planned = lookup.plan(_loaded(project))
    assert {p.again for p in planned} == {"an answer did not come last time"}


def test_a_short_retry_after_is_obeyed_once(project: Path) -> None:
    answers = [Response(429, {"Retry-After": "2"}, b""), _json(200, _crossref_work())]
    waited: list[float] = []

    def answer(path: str, request: Request) -> Response:
        if path.startswith("/crossref/") and answers:
            return answers.pop(0)
        return _registries().answer(path, request)

    project_ = _loaded(project)
    lookup.run(
        project_,
        lookup.plan(project_)[:1],
        transport=Table(answer),
        services=SERVICES,
        pacer=lookup.Pacer(sleep=waited.append),
        today=TODAY,
        said=lambda line: None,
    )
    record = read_record(project_, "fictionalHepaticCohort2021")
    assert record["sources"]["crossref"]["status"] == sources.FOUND
    assert 2.0 in waited


def test_what_is_not_looked_up_says_why(project: Path) -> None:
    """The example says in paper.yaml that its two references are in no registry."""
    bib = project / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    bib.write_text(
        text.replace(f"https://doi.org/{DOI.upper()}", "1016/no-prefix").replace(
            f"  pmid = {{{PMID}}},\n", ""
        ).replace("  doi = {10.5555/fictional.2019.002},\n", ""),
        encoding="utf-8",
    )
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text(encoding="utf-8") + "\nSee [@nowhere2020].\n", "utf-8")
    planned = {p.citekey: p.skipped for p in lookup.plan(_loaded(project))}
    assert planned == {
        "fictionalHepaticCohort2021": "its identifier is malformed (G7 says how)",
        "fictionalClassSignal2019": "it has no DOI and no PMID, and paper.yaml says no registry "
        "has it: invented for this worked example; no registry has it",
        "nowhere2020": "not in references.bib",
    }


def test_a_citekey_is_a_file_name_on_every_system() -> None:
    assert file_name("smith:2020/a") == "smith%3a2020%2fa.yaml"
    assert file_name("Smith_2020-b.x") == "Smith_2020-b.x.yaml"


def test_two_citekeys_one_file_where_case_is_not_told_apart(project: Path) -> None:
    bib = project / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8")
        + "\n@article{FICTIONALCLASSSIGNAL2019,\n  doi = {10.5555/other},\n  title = {T},\n}\n",
        encoding="utf-8",
    )
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(
        main_md.read_text(encoding="utf-8") + "\nSee [@FICTIONALCLASSSIGNAL2019].\n", "utf-8"
    )
    planned = {p.citekey: p.skipped for p in lookup.plan(_loaded(project))}
    assert "share a file with @fictionalClassSignal2019" in planned["FICTIONALCLASSSIGNAL2019"]


def test_a_record_is_held_to_its_entry_by_digest(project: Path) -> None:
    _run(project, _registries())
    project_ = _loaded(project)
    record = read_record(project_, "fictionalClassSignal2019")
    from manuscript_guard.literature.bibfile import read_entries

    fields = read_entries(project / "literature" / "references.bib")["fictionalClassSignal2019"]
    assert record["entry_sha256"] == entry_digest(fields)
    assert entry_digest(dict(reversed(fields.items()))) == entry_digest(fields)


# ----------------------------------------------------------------------- what is not kept


def test_no_key_and_no_contact_address_is_kept(project: Path) -> None:
    """They travel in the query string, where the registries ask for them, and nowhere is
    a request's URL written down."""
    table = _registries()
    credentials = lookup.Credentials(contact=CONTACT, ncbi_key=NCBI, openalex_key=OPENALEX)
    _run(project, table, credentials=credentials)
    sent = " ".join(unquote(r.url) for r in table.sent)
    assert CONTACT in sent and NCBI in sent and OPENALEX in sent
    assert not any(s in r.shown for r in table.sent for s in (CONTACT, NCBI, OPENALEX))
    for path in (project / "literature" / "lookups").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        for secret in (CONTACT, NCBI, OPENALEX, "registry.test", "mailto", "api_key"):
            assert secret not in text, (path.name, secret)


def test_a_record_that_would_hold_a_key_is_refused(project: Path, monkeypatch) -> None:
    def leaky(*args, **kwargs):
        return {"status": sources.UNRESOLVABLE, "why": f"refused {NCBI}"}

    monkeypatch.setattr(sources, "pubmed", leaky)
    with pytest.raises(RuntimeError, match="key or the contact"):
        _run(project, _registries(), credentials=lookup.Credentials(ncbi_key=NCBI))
    assert not record_path(_loaded(project), "fictionalHepaticCohort2021").exists()


def test_the_contact_address_can_come_from_paper_yaml(project: Path, monkeypatch) -> None:
    monkeypatch.delenv(lookup.CONTACT, raising=False)
    paper = project / "paper.yaml"
    paper.write_text(
        paper.read_text(encoding="utf-8") + f"\nlookup:\n  contact: {CONTACT}\n", "utf-8"
    )
    assert lookup.Credentials.from_environment(_loaded(project)).contact == CONTACT
    monkeypatch.setenv(lookup.CONTACT, "other@example.org")
    assert lookup.Credentials.from_environment(_loaded(project)).contact == "other@example.org"


def test_no_gate_imports_the_lookup() -> None:
    """The gates read the records; they never ask a registry."""
    for path in sorted((REPO / "src" / "manuscript_guard" / "gates").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("manuscript_guard.lookup"), path
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
                assert not any(n.startswith("manuscript_guard.lookup") for n in names), path


# ---------------------------------------------------------------------------- the command


def test_the_example_has_nothing_to_look_up_and_sends_nothing(tmp_path, capsys, monkeypatch):
    root = tmp_path / "paper"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build", ".git"))
    monkeypatch.setattr(lookup, "default_transport", _refused)
    assert main(["lookup", str(root)]) == 0
    out = capsys.readouterr().out
    said = "@fictionalHepaticCohort2021: not looked up: it has no DOI and no PMID, and paper.yaml"
    assert said in out
    assert not (root / "literature" / "lookups").exists()


def _refused(request: Request, timeout: float) -> Response:
    raise AssertionError("a request was sent")


def test_a_dry_run_says_what_it_would_look_up_and_sends_nothing(project, capsys, monkeypatch):
    monkeypatch.setattr(lookup, "default_transport", _refused)
    assert main(["lookup", str(project), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"@fictionalHepaticCohort2021: would look up DOI {DOI}, PMID {PMID} (no record)" in out
    assert "nothing was sent" in out
    assert not (project / "literature" / "lookups").exists()


# ------------------------------------------------------- a reference with no identifier

#: The example's first reference, as the registries would hold it: answers in the shapes
#: probed on 2026-10-20 (DESIGN.md, "A reference is looked up once, and the answer is kept").
_TITLE = "Hepatic injury in a fictional national cohort, 2010-2019"
_ESUMMARY = {
    "header": {"type": "esummary"},
    "result": {
        "uids": [PMID],
        PMID: {
            "uid": PMID,
            "title": _TITLE + ".",
            "sortpubdate": "2021/04/01 00:00",
            "pubtype": ["Journal Article"],
            "articleids": [{"idtype": "pubmed", "value": PMID}, {"idtype": "doi", "value": DOI}],
            "authors": [{"name": "Fictional A", "authtype": "Author", "clusterid": ""},
                        {"name": "Fictional B", "authtype": "Author", "clusterid": ""},
                        {"name": "Fictional Study Group", "authtype": "CollectiveName"}],
        },
    },
}  # fmt: skip


def _esearch(*ids: str) -> Response:
    return _json(200, {"header": {"type": "esearch"}, "esearchresult": {
        "count": str(len(ids)), "retmax": str(len(ids)), "retstart": "0", "idlist": list(ids)}})


def _work_list(*items: dict) -> Response:
    return _json(200, {"status": "ok", "message-type": "work-list", "message": {
        "total-results": 5000000, "items": list(items), "items-per-page": 10, "query": {}}})


_CROSSREF_ITEM = {
    "DOI": DOI.upper(),
    "type": "journal-article",
    "title": [_TITLE],
    "issued": {"date-parts": [[2021, 3]]},
    "author": [{"given": "Anne", "family": "Fictional", "sequence": "first"},
               {"given": "Bernard", "family": "Fictional", "sequence": "additional"},
               {"name": "The Fictional Study Group", "sequence": "additional"}],
}  # fmt: skip
_OPENALEX_RESULT = {
    "id": "https://openalex.org/W1", "doi": f"https://doi.org/{DOI}", "title": _TITLE,
    "publication_year": 2021, "type": "article", "is_retracted": False,
    "ids": {"pmid": f"https://pubmed.ncbi.nlm.nih.gov/{PMID}"},
    "authorships": [{"author": {"display_name": "Anne Fictional"}}],
}  # fmt: skip


def _searches(esearch=None, esummary=None, crossref=None, openalex=None, headers=None):
    """Answers to the searches by service; each default finds the cited work."""
    found = {
        "esearch": esearch or (lambda request: _esearch(PMID)),
        "pubmed": esummary or (lambda request: _json(200, _ESUMMARY)),
        "crossref_search": crossref or (lambda request: _work_list(_CROSSREF_ITEM)),
        "openalex_search": openalex or (lambda request: _json(
            200, {"meta": {"count": 1}, "results": [_OPENALEX_RESULT]}, headers)),
    }

    def answer(path: str, request: Request) -> Response:
        return found[path.strip("/").split("/")[0]](request)

    return Table(answer)


@pytest.fixture
def searched(tmp_path: Path) -> Path:
    """The example, its two references without the paper.yaml that says no registry has
    them: each is searched for by its title."""
    root = tmp_path / "paper"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build", ".git"))
    paper = root / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    paper.write_text(text[: text.index("lookup:\n")] + text[text.index("\n# Abbreviations"):],
                     encoding="utf-8")  # fmt: skip
    return root


def test_a_reference_with_no_identifier_is_searched_by_its_title(searched: Path) -> None:
    table = _searches()
    written = _run(searched, table)
    assert len(written) == 2
    record = read_record(_loaded(searched), "fictionalHepaticCohort2021")
    assert record["schema"] == "manuscript-guard/lookup/2" and record["identifiers"] == {}
    assert set(record["sources"]) == {"pubmed_search", "crossref_search", "openalex_search"}
    pubmed = record["sources"]["pubmed_search"]
    assert pubmed["asked"] == ["hepatic[ti] AND injury[ti] AND fictional[ti] AND national[ti] "
                               "AND cohort[ti] AND 2010[ti] AND 2019[ti]"]  # fmt: skip
    assert pubmed["candidates"][0]["pmid"] == PMID
    assert pubmed["candidates"][0]["authors"] == [
        {"family": "Fictional", "given": "A"}, {"family": "Fictional", "given": "B"},
        {"group": "Fictional Study Group"}]  # fmt: skip
    crossref = record["sources"]["crossref_search"]["candidates"][0]
    assert crossref["doi"] == DOI and crossref["authors"][2] == {
        "group": "The Fictional Study Group"}  # fmt: skip
    alex = record["sources"]["openalex_search"]["candidates"][0]
    assert alex["pmid"] == PMID and alex["authors"] == [{"family": "Fictional", "given": "Anne"}]
    # A quoted title is "No items found" in PubMed, whatever it holds (2026-10-20).
    assert not any('"' in v for r in table.sent for v in r.params.values())


def test_pubmed_is_asked_by_the_first_author_only_where_the_title_found_no_work(
    searched: Path,
) -> None:
    """A title cited with one word wrong finds nothing in PubMed's title field, since an
    unknown word empties the whole search: the first author and the years find it."""
    terms: list[str] = []

    def esearch(request: Request) -> Response:
        terms.append(request.params["term"])
        return _esearch(PMID) if "[1au]" in request.params["term"] else _esearch()

    _run(searched, _searches(esearch=esearch))
    record = read_record(_loaded(searched), "fictionalHepaticCohort2021")
    asked = record["sources"]["pubmed_search"]["asked"]
    assert len(asked) == 2 and asked[1].startswith("fictional[1au] AND 2020:2022[dp] AND (")
    assert "hepatic[ti] OR injury[ti]" in asked[1]
    assert record["sources"]["pubmed_search"]["candidates"][0]["pmid"] == PMID
    terms.clear()
    _run(searched, _searches(esearch=lambda r: (terms.append(r.params["term"]), _esearch(PMID))[1]),
         again=True)  # fmt: skip
    first = [term for term in terms if "hepatic" in term]
    assert first and not any("[1au]" in term for term in first), "the title found it"


def test_crossref_s_search_keeps_to_the_cited_years(searched: Path) -> None:
    """Fabricated copies of a famous paper, posted years later, rank first once the authors
    are in the query (five under 10.65215 for "Attention is all you need", 2026-10-20)."""
    table = _searches()
    _run(searched, table)
    sent = [r for r in table.sent if r.base.endswith("crossref_search")]
    assert sent[0].params["filter"] == "from-pub-date:2020,until-pub-date:2022"
    assert sent[0].params["query.bibliographic"].endswith("Fictional 2021")


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (_work_list(_CROSSREF_ITEM), sources.FOUND),
        (_work_list(), sources.ABSENT),
        (_json(200, {"status": "failed", "message-type": "validation-failure", "message": []}),
         sources.UNRESOLVABLE),
        (_json(200, {"status": "ok", "message-type": "work", "message": {"DOI": DOI}}),
         sources.UNRESOLVABLE),
        (_work_list({"title": ["no DOI"]}), sources.UNRESOLVABLE),
        (Response(429, {}, b""), sources.UNRESOLVABLE),
    ],
)  # fmt: skip
def test_crossref_s_search_is_found_or_absent_only_in_its_own_shape(
    searched: Path, answer: Response, status: str
) -> None:
    _run(searched, _searches(crossref=lambda request: answer))
    record = read_record(_loaded(searched), "fictionalHepaticCohort2021")
    assert record["sources"]["crossref_search"]["status"] == status


def test_a_work_too_unlike_the_cited_one_is_not_kept(searched: Path) -> None:
    other = {**_CROSSREF_ITEM, "DOI": "10.5555/other", "title": ["Renal outcomes of statins"]}
    _run(searched, _searches(crossref=lambda request: _work_list(other, _CROSSREF_ITEM)))
    record = read_record(_loaded(searched), "fictionalHepaticCohort2021")
    kept = record["sources"]["crossref_search"]["candidates"]
    assert [c["doi"] for c in kept] == [DOI]


def test_openalex_is_searched_only_while_its_allowance_lasts(searched: Path) -> None:
    """A search costs a thousandth of a dollar, and the free allowance is ten cents a day
    for everyone behind one address: with three searches' worth left, no more is asked."""
    nearly = {"X-RateLimit-Remaining-USD": "0.002", "X-RateLimit-Cost-USD": "0.001"}
    _run(searched, _searches(headers=nearly))
    keys = ("fictionalHepaticCohort2021", "fictionalClassSignal2019")
    first, second = (read_record(_loaded(searched), k) for k in keys)
    assert "openalex_search" in first["sources"] and "openalex_search" not in second["sources"]
    _run(searched, _searches(headers=nearly), again=True,
         credentials=lookup.Credentials(openalex_key=OPENALEX))  # fmt: skip
    second = read_record(_loaded(searched), "fictionalClassSignal2019")
    assert "openalex_search" in second["sources"], "with a key, the allowance is its own"


def test_crossref_s_searches_are_paced_from_their_own_pool() -> None:
    """A search is answered from Crossref's list pool at one a second, and a DOI from the
    single-record pool at five: one does not hold the other up."""
    clock = [0.0]
    waited: list[float] = []
    pacer = lookup.Pacer(clock=lambda: clock[0], sleep=waited.append)
    ask = lookup._asker(lambda request, timeout: _json(200, {}), pacer, lookup.Credentials())
    ask(Request("https://api.crossref.org/works", params={"query.bibliographic": "x"}))
    ask(Request("https://api.crossref.org/works/10.5555/x"))
    ask(Request("https://api.crossref.org/works", params={"query.bibliographic": "y"}))
    assert waited == [1.0]


def test_a_record_kept_before_the_authors_is_looked_up_again(project: Path) -> None:
    _run(project, _registries())
    path = record_path(_loaded(project), "fictionalClassSignal2019")
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["schema"] = "manuscript-guard/lookup/1"
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    planned = {p.citekey: p for p in lookup.plan(_loaded(project))}
    assert planned["fictionalClassSignal2019"].again == (
        "it was looked up before the authors were kept")  # fmt: skip
    assert planned["fictionalHepaticCohort2021"].skipped == "up to date"


def test_crossref_and_pubmed_keep_each_work_s_authors() -> None:
    people = [{"given": "Anne", "family": "Fictional"},
              {"name": "The RECOVERY Collaborative Group"},
              {"given": "RECOVERY", "family": "Collaborative Group"},
              {"given": "Only"}]  # fmt: skip
    found = sources.crossref(DOI, _ask(_registries(crossref=_json(200, _crossref_work(
        author=people)))), SERVICES.crossref, None)  # fmt: skip
    assert found["authors"] == [
        {"family": "Fictional", "given": "Anne"},
        {"group": "The RECOVERY Collaborative Group"},
        {"group": "RECOVERY Collaborative Group"},
        {"family": "Only"},
    ]  # fmt: skip
    pubmed = sources.pubmed(PMID, _ask(_registries(pubmed=_json(200, _ESUMMARY))),
                            SERVICES.pubmed, None, None)  # fmt: skip
    assert pubmed["authors"][0] == {"family": "Fictional", "given": "A"}
    assert pubmed["authors"][2] == {"group": "Fictional Study Group"}


def test_a_dry_run_says_a_reference_with_no_identifier_would_be_searched(
    searched, capsys, monkeypatch
):
    monkeypatch.setattr(lookup, "default_transport", _refused)
    assert main(["lookup", str(searched), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert ("@fictionalHepaticCohort2021: would search PubMed, Crossref and OpenAlex for its "
            "title (no record)") in out  # fmt: skip


# ------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        self.server.seen.append(self.path)
        self.server.agents.append((self.path, self.headers.get("User-Agent", "")))
        status, payload = self.server.respond(self.path)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if status in (301, 302):
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []
    httpd.agents = []
    answers = {
        "crossref": (200, _crossref_work()),
        "openalex": (200, {**_OPENALEX, "is_retracted": True}),
        "datacite": (404, {"errors": []}),
        "doi_org": (200, {"responseCode": 1}),
        "pubmed": (200, _PUBMED),
    }

    def respond(path: str) -> tuple[int, bytes]:
        status, data = answers.get(path.strip("/").split("/")[0], (404, {}))
        return status, json.dumps(data).encode()

    httpd.respond = respond
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        default_transport(Request(httpd.url + "/probe"), 5)
    except NoAnswer as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_the_real_transport_looks_up_and_keeps_no_key(project: Path, server) -> None:
    services = lookup.Services(
        crossref=f"{server.url}/crossref/",
        openalex=f"{server.url}/openalex/doi:",
        datacite=f"{server.url}/datacite/",
        doi_org=f"{server.url}/doi_org/",
        pubmed=f"{server.url}/pubmed/esummary.fcgi",
    )
    project_ = _loaded(project)
    lookup.run(
        project_,
        lookup.plan(project_),
        services=services,
        credentials=lookup.Credentials(contact=CONTACT, ncbi_key=NCBI, openalex_key=OPENALEX),
        pacer=lookup.Pacer(sleep=lambda s: None),
        today=TODAY,
        said=lambda line: None,
    )
    record = read_record(project_, "fictionalHepaticCohort2021")
    assert record["sources"]["openalex"]["is_retracted"] is True
    assert record["sources"]["pubmed"]["status"] == sources.FOUND
    queries = [parse_qs(urlsplit(path).query) for path in server.seen]
    assert any(q.get("api_key") == [NCBI] and q.get("email") == [CONTACT] for q in queries)
    assert any(q.get("api_key") == [OPENALEX] for q in queries)
    assert any(q.get("mailto") == [CONTACT] for q in queries)
    # Round 1 of #253: the contact address is in the User-Agent of Crossref's requests only.
    for path, agent in server.agents:
        assert (CONTACT in agent) is path.startswith("/crossref/"), (path, agent)
    for path in (project / "literature" / "lookups").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        assert not any(s in text for s in (CONTACT, NCBI, OPENALEX, "127.0.0.1"))
        assert yaml.safe_load(text)["schema"] == "manuscript-guard/lookup/2"


def test_the_real_transport_follows_no_redirect(server) -> None:
    server.respond = lambda path: (302, b"")
    answer = default_transport(Request(server.url + "/crossref/x", secret={"api_key": NCBI}), 5)
    assert answer.status == 302
    assert server.seen == ["/crossref/x?api_key=" + NCBI]


def test_the_real_transport_sends_nothing_unencrypted_off_this_machine() -> None:
    with pytest.raises(NoAnswer, match="refused"):
        default_transport(Request("http://registry.test/works/x"), 5)
