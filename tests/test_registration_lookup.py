"""`lookup --registrations`: each registration asked of its registry once, and the answer kept.

No test opens a connection to a registry. Most answer from a table; the real transport is run
against a server on a loopback port. The answers are written here in the shapes each service
documents, or for the EU PAS register in the shape its pages had on 2026-10-21, with
fictional studies.
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts.project import load_project
from manuscript_guard.lookup import eupas, registries
from manuscript_guard.lookup import registrations as lookup
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport
from manuscript_guard.lookup.sources import ABSENT, FOUND, UNRESOLVABLE
from manuscript_guard.registrations import (
    answers_digest,
    digest_holds,
    identify,
    read_record,
    record_path,
)

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "example"
TODAY = date(2026, 10, 21)
NCT = "NCT01234567"


def _json(status: int, data: object, headers: dict | None = None) -> Response:
    return Response(status, headers or {}, json.dumps(data).encode())


def _text(status: int, body: str, headers: dict | None = None) -> Response:
    return Response(status, headers or {}, body.encode())


class Table:
    """A transport that answers from a function of the path and query, and keeps what it
    was sent."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.sent: list[Request] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append(request)
        return self.answer(urlsplit(request.base).path, request)


def _ask(table: Table):
    return lambda request: table(request, 1.0)


# ---------------------------------------------------------------------- ClinicalTrials.gov


def _study(nct: str = NCT, **status) -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": "A fictional study",
                                     "officialTitle": "Hepatic injury with example-drug"},
            "statusModule": {
                "studyFirstSubmitDate": "2025-01-10",
                "startDateStruct": {"date": "2025-02", "type": "ACTUAL"},
                "lastUpdateSubmitDate": "2026-03-03",
                **status,
            },
            "designModule": {"studyType": "OBSERVATIONAL",
                             "designInfo": {"observationalModel": "COHORT"}},
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Hepatic injury",
                                     "description": "Reported as a\r\nserious event",
                                     "timeFrame": "One year"}],
                "secondaryOutcomes": [{"measure": "Death"}],
                "otherOutcomes": [{"measure": "Hospital stay", "timeFrame": "One year"}],
            },
            "conditionsModule": {"conditions": ["Hepatic injury"]},
            "eligibilityModule": {"studyPopulation": "Adults dispensed example-drug"},
        }
    }  # fmt: skip


def _ctgov(answer: Response) -> dict:
    table = Table(lambda path, request: answer)
    found = registries.clinicaltrials(NCT, _ask(table), "https://registry.test/studies/")
    sent = table.sent[0]
    assert sent.base == f"https://registry.test/studies/{NCT}"
    assert sent.params == {"fields": "protocolSection", "format": "json", "markupFormat": "legacy"}
    return found


def test_a_study_clinicaltrials_knows_is_read_with_its_outcomes_apart() -> None:
    found = _ctgov(_json(200, _study()))
    assert found["status"] == FOUND
    assert found["dates"] == {"registered": "2025-01-10", "study_start": "2025-02",
                              "updated": "2026-03-03"}  # fmt: skip
    assert found["study_type"] == "observational"
    roles = [(s["label"], s.get("role")) for s in found["sections"]][:3]
    assert roles == [("Primary outcome 1", "primary"), ("Secondary outcome 1", "secondary"),
                     ("Other pre-specified outcome 1", "other")]  # fmt: skip
    assert found["sections"][0]["text"] == "Hepatic injury\nReported as a serious event\nOne year"


def test_an_estimated_start_is_not_kept() -> None:
    estimated = {"startDateStruct": {"date": "2025-02-01", "type": "ESTIMATED"}}
    assert "study_start" not in _ctgov(_json(200, _study(**estimated)))["dates"]


@pytest.mark.parametrize(
    "answer, status",
    [
        (_text(404, f"NCT number {NCT} not found"), ABSENT),
        # It pads a short number and answers for that study: another study is no answer.
        (_json(200, _study("NCT00001234")), UNRESOLVABLE),
        (_text(301, "", {"Location": "/api/v2/studies/NCT07654321"}), UNRESOLVABLE),
        (_json(429, {}), UNRESOLVABLE),
        (_json(200, {"protocolSection": {"identificationModule": {"nctId": NCT}}}), UNRESOLVABLE),
        (_text(200, "<html>maintenance</html>"), UNRESOLVABLE),
        (_text(404, "<html>Not Found</html>"), UNRESOLVABLE),
    ],
)
def test_only_clinicaltrials_documented_answers_are_found_or_absent(answer, status) -> None:
    assert _ctgov(answer)["status"] == status


def test_a_study_with_nothing_listed_is_found_with_no_sections() -> None:
    """Round 1 of #390: a found record with no section lost the key the schema asks for, and
    writing it stopped the command."""
    study = _study()
    study["protocolSection"]["outcomesModule"] = {}
    study["protocolSection"]["conditionsModule"] = {}
    study["protocolSection"]["eligibilityModule"] = {}
    found = _ctgov(_json(200, study))
    assert found["status"] == FOUND and found["sections"] == []


def test_an_alias_names_the_study_it_stands_for() -> None:
    said = _ctgov(_text(301, "", {"Location": "/api/v2/studies/NCT07654321"}))
    assert "NCT07654321" in said["why"]


def test_an_outcome_with_no_measure_is_no_answer() -> None:
    study = _study()
    study["protocolSection"]["outcomesModule"]["primaryOutcomes"] = [{"description": "x"}]
    assert _ctgov(_json(200, study))["status"] == UNRESOLVABLE


# -------------------------------------------------------------------------------------- OSF

_OSF = "https://registry.test/osf/"


def _registration(original: str = "r1", latest: str = "r1", **attributes) -> dict:
    return {
        "data": {
            "id": "abcde",
            "type": "registrations",
            "attributes": {
                "title": "A fictional preregistration",
                "date_registered": "2025-01-10T09:30:00.000000",
                "registration_supplement": "OSF Preregistration",
                "withdrawn": False,
                "registration_responses": {"q1": "Does it?", "q2": "Hepatic injury",
                                           "q3": ["one", "two"]},
                **attributes,
            },
            "relationships": {
                "registration_schema": {"data": {"id": "s1", "type": "registration-schemas"}},
                "original_response": {"data": {"id": original, "type": "schema_responses"}},
                "latest_response": {"data": {"id": latest, "type": "schema_responses"}},
            },
        }
    }  # fmt: skip


def _block(kind: str, text: str = "", key: str | None = None) -> dict:
    return {"attributes": {"block_type": kind, "display_text": text,
                           "registration_response_key": key}}  # fmt: skip


_BLOCKS = {
    "data": [
        _block("page-heading", "Study information"),
        _block("question-label", "Research question"), _block("long-text-input", key="q1"),
        _block("question-label", "Outcome(s)"), _block("long-text-input", key="q2"),
        _block("question-label", "Arms"), _block("multi-select-input", key="q3"),
    ],
    "links": {"meta": {"total": 7, "per_page": 1000}},
}  # fmt: skip


def _osf_answers(registration: Response, **more: Response) -> Table:
    def answer(path: str, request: Request) -> Response:
        if path.endswith("/registrations/abcde/"):
            return registration
        if path.endswith("/schema_blocks/"):
            return more.get("blocks", _json(200, _BLOCKS))
        name = path.rstrip("/").rsplit("/", 1)[-1]
        return more[name]

    return Table(answer)


def test_an_osf_registration_is_read_with_each_question_s_words() -> None:
    table = _osf_answers(_json(200, _registration()))
    found = registries.osf("osf.io/abcde", _ask(table), _OSF)
    assert found["status"] == FOUND and found["dates"] == {"registered": "2025-01-10"}
    assert found["sections"] == [
        {"label": "Research question", "text": "Does it?"},
        {"label": "Outcome(s)", "text": "Hepatic injury", "role": "outcomes"},
        {"label": "Arms", "text": "one; two"},
    ]
    assert "first_version" not in found


def test_an_updated_osf_registration_keeps_what_it_said_first() -> None:
    first = _json(200, {"data": {"attributes": {"revision_responses": {"q2": "Death"}}}})
    said = {"date_submitted": "2025-06-01T00:00:00", "revision_justification": "added one"}
    later = _json(200, {"data": {"attributes": said}})
    table = _osf_answers(_json(200, _registration("r1", "r2")), r1=first, r2=later)
    found = registries.osf("osf.io/abcde", _ask(table), _OSF)
    assert found["first_version"] == {
        "updated": "2025-06-01", "reason": "added one",
        "sections": [{"label": "Outcome(s)", "text": "Death", "role": "outcomes"}],
    }  # fmt: skip
    assert found["dates"]["updated"] == "2025-06-01"


@pytest.mark.parametrize(
    "answer, status",
    [
        (_json(404, {"errors": [{"detail": "Not found."}]}), ABSENT),
        (_json(410, {"errors": [{"detail": "Gone"}]}), ABSENT),
        (_json(403, {"errors": [{"detail": "Forbidden"}]}), UNRESOLVABLE),
        (_json(200, {"data": {"type": "nodes", "attributes": {}}}), UNRESOLVABLE),
        (_json(200, {"errors": []}), UNRESOLVABLE),
    ],
)
def test_only_osf_documented_answers_are_found_or_absent(answer, status) -> None:
    table = _osf_answers(answer)
    assert registries.osf("osf.io/abcde", _ask(table), _OSF)["status"] == status


def test_a_template_longer_than_one_page_is_no_answer() -> None:
    blocks = _json(200, {**_BLOCKS, "links": {"meta": {"total": 2000}}})
    table = _osf_answers(_json(200, _registration()), blocks=blocks)
    assert registries.osf("osf.io/abcde", _ask(table), _OSF)["status"] == UNRESOLVABLE


def test_an_osf_registration_with_no_answer_is_found_with_no_sections() -> None:
    table = _osf_answers(_json(200, _registration(registration_responses={}, withdrawn=True)))
    found = registries.osf("osf.io/abcde", _ask(table), _OSF)
    assert found["status"] == FOUND and found["sections"] == [] and found["withdrawn"] is True


def test_a_withdrawn_osf_registration_says_so() -> None:
    table = _osf_answers(_json(200, _registration(withdrawn=True)))
    assert registries.osf("osf.io/abcde", _ask(table), _OSF)["withdrawn"] is True


# ----------------------------------------------------------------------------------- ISRCTN

_ISRCTN = "https://registry.test/isrctn/query"


def _trials(*numbers: str, doctype: str = "") -> bytes:
    trials = "".join(
        f"""<fullTrial><trial lastUpdated="2026-01-02T10:00:00Z" version="3">
        <isrctn dateAssigned="2025-01-10T13:32:42.080Z">{number}</isrctn>
        <trialDescription><title>A fictional trial</title>
        <primaryOutcome>1. Hepatic injury at one year</primaryOutcome>
        <secondaryOutcome>There are no secondary outcome measures</secondaryOutcome>
        </trialDescription>
        <conditions><condition><description>Hepatic injury</description></condition></conditions>
        <interventions><intervention><description>Example-drug</description></intervention>
        </interventions>
        <participants><recruitmentStart>2025-02-01T00:00:00.000Z</recruitmentStart></participants>
        <design><primaryStudyDesign>Interventional</primaryStudyDesign></design>
        </trial></fullTrial>"""
        for number in numbers
    )
    head = f'{doctype}<allTrials totalCount="{len(numbers)}" xmlns="http://www.67bricks.com/isrctn">'
    return (head + trials + "</allTrials>").encode()


def _isrctn(body: bytes, status: int = 200) -> dict:
    table = Table(lambda path, request: Response(status, {}, body))
    found = registries.isrctn("ISRCTN12345678", _ask(table), _ISRCTN)
    assert table.sent[0].params == {"q": "ISRCTN12345678", "limit": "10"}
    return found


def test_an_isrctn_trial_is_read_by_its_number_among_what_the_query_found() -> None:
    found = _isrctn(_trials("87654321", "12345678"))
    assert found["status"] == FOUND
    assert found["dates"] == {"registered": "2025-01-10", "study_start": "2025-02-01",
                              "updated": "2026-01-02"}  # fmt: skip
    assert found["study_type"] == "interventional"
    sections = {s["label"]: s for s in found["sections"]}
    assert sections["Primary outcome measure"]["role"] == "primary"
    assert sections["Intervention"]["text"] == "Example-drug", "not the condition's description"


@pytest.mark.parametrize(
    "body, status",
    [
        (_trials(), ABSENT),
        (_trials("87654321"), ABSENT),
        (_trials("12345678", doctype='<!DOCTYPE x [<!ENTITY a "b">]>'), UNRESOLVABLE),
        (b"<html>maintenance</html>", UNRESOLVABLE),
    ],
)
def test_only_isrctn_documented_answers_are_found_or_absent(body, status) -> None:
    assert _isrctn(body)["status"] == status


def test_a_trial_isrctn_may_not_have_given_is_not_absent() -> None:
    """Round 1 of #390: more trials found than the answer held was read as none of them
    being the one asked, and the registration failed as unknown."""
    body = _trials("87654321").replace(b'totalCount="1"', b'totalCount="40"')
    assert _isrctn(body)["status"] == UNRESOLVABLE


# ------------------------------------------------------------------------- the EU PAS register

_EMA = "https://catalogues.test"


def _administrative(number: str = "EUPAS1000000999", *, published: str = "14/04/2025") -> bytes:
    return f"""<html><body>
    <h1 class="content-banner-title mb-0 card-title">Hepatic injury with example-drug</h1>
    <div class="js-form-item form-item form-item-published-date-field">
      <label class="form-label">First published</label>
      <span class="field-content">{published}</span></div>
    <div class="js-form-item form-item form-item-update-date-field">
      <label class="form-label">Last updated</label>
      <span class="field-content">02/05/2025</span></div>
    <div class="darwin-study__field-darwin-eu-pas-number d-flex">
      <div class="field__label">EU PAS number:</div><div class="field__item">{number}</div></div>
    <dd><div><div class="darwin-study__status">Ongoing</div></div></dd>
    <p class="label">Study start date</p><div class="darwin-study__field-darwin-data-col-start-act">
      <div class="field__label">Actual:</div><div class="field__item">
      <time datetime="2025-03-01T12:00:00Z">01/03/2025</time></div></div>
    <div class="darwin-study__field-darwin-data-ana-start-plan">
      <div class="field__item"><time datetime="2025-06-01T12:00:00Z">01/06/2025</time></div></div>
    <div class="field__label">First published:</div><div class="field__item">
      <time datetime="2016-10-19T12:00:00Z">19/10/2016</time></div>
    <script>var x = "<h1 class='content-banner-title'>not this</h1>";</script>
    </body></html>""".encode()


def _methodological() -> bytes:
    def item(label: str, words: str) -> str:
        return (f'<dl class="description-list-item row"><div><dt><div><p class="label">{label}'
                f"</p></div></dt></div><div><dd><div>{words}</div></dd></div></dl>")

    return ("<html><body>" + item("Study type", "Non-interventional study")
            + item("Non-interventional study design", '<div class="field__item">Cohort</div>')
            + item("Outcomes", "Primary outcome: hepatic injury.<br />\n<br />\nSecondary "
                   "outcome: death.")
            + item("Data analysis plan", "A Cox model &amp; its &lt;assumptions&gt;.")
            + "</body></html>").encode()  # fmt: skip


def _catalogue(pages: dict[str, Response]) -> Table:
    def answer(path: str, request: Request) -> Response:
        key = path + ("?" + request.params["search_api_fulltext"] if request.params else "")
        return pages.get(key, _text(404, "<html>Page not found</html>"))

    return Table(answer)


def _found_at(node: str = "4318") -> Response:
    return _text(302, "", {"Location": f"/node/{node}/administrative-details"})


def test_a_study_of_the_catalogue_s_own_scheme_is_read_from_its_two_pages() -> None:
    table = _catalogue({
        "/study/1000000999": _found_at(),
        "/node/4318/administrative-details": Response(200, {}, _administrative()),
        "/node/4318/methodological-aspects": Response(200, {}, _methodological()),
    })  # fmt: skip
    found = eupas.eu_pas("EUPAS1000000999", _ask(table), _EMA)
    assert found["status"] == FOUND and found["title"] == "Hepatic injury with example-drug"
    # The study's own date, not an institution's further down the page; a planned start of
    # analysis is not a start.
    assert found["dates"] == {"registered": "2025-04-14", "study_start": "2025-03-01",
                              "updated": "2025-05-02"}  # fmt: skip
    assert found["study_type"] == "observational" and found["design"] == "Cohort"
    outcomes = [s for s in found["sections"] if s.get("role")]
    assert outcomes == [{"label": "Outcomes", "role": "outcomes",
                         "text": "Primary outcome: hepatic injury.\nSecondary outcome: death."}]
    plan = next(s for s in found["sections"] if s["label"] == "Data analysis plan")
    assert plan["text"] == "A Cox model & its <assumptions>."


def test_an_older_number_is_found_by_the_catalogue_s_search() -> None:
    search = '<a href="/study/23396">Hepatic injury</a> <a href="/study/23396">again</a>'
    table = _catalogue({
        "/search?EUPAS11379": _text(200, f"<html>1 results {search}</html>"),
        "/study/23396": _found_at("1617"),
        "/node/1617/administrative-details": Response(200, {}, _administrative("EUPAS11379")),
        "/node/1617/methodological-aspects": Response(200, {}, _methodological()),
    })  # fmt: skip
    found = eupas.eu_pas("EUPAS11379", _ask(table), _EMA)
    assert found["status"] == FOUND
    asked = [request.base.removeprefix(_EMA) for request in table.sent]
    assert asked.count("/study/23396") == 1, "a study the search links twice is read once"


def test_a_page_that_gives_another_number_is_not_the_study() -> None:
    table = _catalogue({
        "/study/1000000999": _found_at(),
        "/node/4318/administrative-details": Response(200, {}, _administrative("EUPAS1000000123")),
    })  # fmt: skip
    assert eupas.eu_pas("EUPAS1000000999", _ask(table), _EMA)["status"] == ABSENT


@pytest.mark.parametrize(
    "pages, status",
    [
        ({}, ABSENT),
        ({"/study/1000000999": _found_at(),
          "/node/4318/administrative-details": _text(200, "<html><h1>Maintenance</h1></html>")},
         UNRESOLVABLE),
        ({"/study/1000000999": _text(302, "", {"Location": "https://elsewhere.test/node/1/x"})},
         UNRESOLVABLE),
        ({"/study/1000000999": _text(302, "", {"Location": "/user/login"})}, UNRESOLVABLE),
        ({"/study/1000000999": _text(503, "")}, UNRESOLVABLE),
    ],
)  # fmt: skip
def test_only_pages_of_the_shape_read_are_found_or_absent(pages, status) -> None:
    assert eupas.eu_pas("EUPAS1000000999", _ask(_catalogue(pages)), _EMA)["status"] == status


def test_a_search_that_links_more_studies_than_are_read_is_not_absent() -> None:
    links = " ".join(f'<a href="/study/{n}">x</a>' for n in range(30001, 30009))
    pages = {"/search?EUPAS11379": _text(200, f"<html>8 results {links}</html>")}
    for n in range(30001, 30009):
        pages[f"/study/{n}"] = _found_at(str(n))
        pages[f"/node/{n}/administrative-details"] = Response(
            200, {}, _administrative("EUPAS99999"))
    found = eupas.eu_pas("EUPAS11379", _ask(_catalogue(pages)), _EMA)
    assert found["status"] == UNRESOLVABLE


def test_an_older_number_the_search_does_not_find_is_absent() -> None:
    table = _catalogue({"/search?EUPAS11379": _text(200, "<html>0 results. No results found."
                                                         "</html>")})  # fmt: skip
    assert eupas.eu_pas("EUPAS11379", _ask(table), _EMA)["status"] == ABSENT


# ------------------------------------------------------------------------------ identifiers


@pytest.mark.parametrize(
    "written, registry, kept",
    [
        ("NCT01234567", "clinicaltrials.gov", "NCT01234567"),
        ("nct01234567", "clinicaltrials.gov", "NCT01234567"),
        ("EUPAS1000000417", "eu-pas", "EUPAS1000000417"),
        ("EU PAS 11379", "eu-pas", "EUPAS11379"),
        ("ISRCTN17072692", "isrctn", "ISRCTN17072692"),
        ("https://osf.io/ABCDE/", "osf", "osf.io/abcde"),
        ("10.17605/OSF.IO/ABCDE", "osf", "osf.io/abcde"),
        ("CRD42020182366", "prospero", "CRD42020182366"),
        ("NCT123", None, None),
        ("ABC-123", None, None),
    ],
)
def test_an_identifier_names_its_registry_by_its_shape(written, registry, kept) -> None:
    assert identify(written) == (registry, kept)


@pytest.mark.parametrize("written, registry", [("EU-PAS 12345", "eu-pas"),
                                               ("ISRCTN 17072692", "ISRCTN"),
                                               ("12345678", "clinicaltrials.gov")])  # fmt: skip
def test_a_registry_with_a_shape_holds_a_named_identifier_to_it(written, registry) -> None:
    """Round 1 of #390: naming the registry let any text through, which the EU PAS lookup
    then failed to read as a number."""
    assert identify(written, registry) == (None, None)


def test_an_identifier_of_another_registry_needs_its_name() -> None:
    assert identify("ACTRN12625000123456", "ANZCTR") == ("anzctr", "ACTRN12625000123456")
    assert identify("../x", "anzctr") == (None, None), "no path is made of an identifier"


# ------------------------------------------------------------------------------ the project


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build", ".git"))
    return root


def _declare(root: Path, *entries: dict) -> None:
    paper = root / "paper.yaml"
    text = paper.read_text(encoding="utf-8").rstrip("\n")
    block = yaml.safe_dump({"registration": list(entries)}, sort_keys=False)
    paper.write_text(f"{text}\n\n{block}", encoding="utf-8")


def _everywhere() -> Table:
    """Every registry finding what it is asked about."""

    def answer(path: str, request: Request) -> Response:
        if "/studies/" in path:
            return _json(200, _study(path.rsplit("/", 1)[-1]))
        return _text(404, "")

    return Table(answer)


SERVICES = registries.Services(
    clinicaltrials="https://registry.test/studies/",
    osf=_OSF,
    isrctn=_ISRCTN,
    eu_pas=_EMA,
)


def _run(root: Path, table: Table, *, again: bool = False) -> list:
    project = load_project(root)[0]
    return lookup.run(project, lookup.plan(project, again=again), transport=table,
                      services=SERVICES, pacer=lookup.Pacer(sleep=lambda s: None), today=TODAY,
                      said=lambda line: None)  # fmt: skip


def test_each_registration_is_asked_and_its_record_written(project: Path) -> None:
    _declare(project, {"id": NCT})
    written = _run(project, _everywhere())
    assert len(written) == 1
    record = read_record(record_path(load_project(project)[0], NCT))
    assert record["status"] == FOUND and record["asked_on"] == "2026-10-21"
    assert record["answers_sha256"] == answers_digest(record) and digest_holds(record)


def test_a_record_that_stands_is_not_asked_again_and_one_that_did_not_come_is(
    project: Path,
) -> None:
    _declare(project, {"id": NCT})
    _run(project, _everywhere())
    table = _everywhere()
    assert _run(project, table) == [] and table.sent == []
    path = record_path(load_project(project)[0], NCT)
    _run(project, Table(lambda path, request: _json(503, {})), again=True)
    assert read_record(path)["status"] == UNRESOLVABLE
    assert len(_run(project, _everywhere())) == 1


def test_an_edited_record_is_asked_again(project: Path) -> None:
    _declare(project, {"id": NCT})
    _run(project, _everywhere())
    path = record_path(load_project(project)[0], NCT)
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record["sections"][0]["text"] = "Anything"
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    [planned] = lookup.plan(load_project(project)[0])
    assert planned.why == "its record was edited"


def test_a_registry_that_is_not_asked_and_a_record_copied_by_hand_are_left_alone(
    project: Path,
) -> None:
    _declare(project, {"id": "CRD42020182366"}, {"id": "ACTRN12625000123456", "registry": "anzctr"},
             {"id": NCT}, {"id": "ABC-123"}, {"id": "ISRCTN 17072692", "registry": "ISRCTN"},
             {"id": "https://x.org/ACTRN1", "registry": "anzctr"})  # fmt: skip
    path = record_path(load_project(project)[0], NCT)
    path.parent.mkdir(parents=True)
    by_hand = {"schema": "manuscript-guard/registration/1", "id": NCT,
               "registry": "clinicaltrials.gov", "source": "by-hand", "status": "found",
               "copied_on": "2026-10-01", "copied_by": "A. Author",
               "dates": {"registered": "2025-01-10"}, "sections": []}  # fmt: skip
    path.write_text(yaml.safe_dump(by_hand), encoding="utf-8")
    planned = lookup.plan(load_project(project)[0])
    said = {p.written: p.skipped for p in planned}
    assert "PROSPERO is not asked" in said["CRD42020182366"]
    assert "design/registrations/CRD42020182366.yaml" in said["CRD42020182366"]
    assert "anzctr is not asked" in said["ACTRN12625000123456"]
    assert said[NCT] == lookup.BY_HAND
    assert "names no registry" in said["ABC-123"]
    assert said["ISRCTN 17072692"].endswith("is not written as ISRCTN writes its identifiers")
    assert "holds a character a file name cannot" in said["https://x.org/ACTRN1"]
    table = _everywhere()
    assert _run(project, table) == [] and table.sent == []


def test_nothing_of_the_manuscript_is_sent(project: Path) -> None:
    _declare(project, {"id": NCT})
    table = _everywhere()
    _run(project, table)
    for request in table.sent:
        assert set(request.params) <= {"fields", "format", "markupFormat"}
        assert not request.secret


# ---------------------------------------------------------------------------- the command


def _refused(request: Request, timeout: float) -> Response:
    raise AssertionError("a request was sent")


def test_a_paper_with_no_registration_asks_nothing(project, capsys, monkeypatch) -> None:
    monkeypatch.setattr(lookup, "default_transport", _refused)
    assert main(["lookup", str(project), "--registrations"]) == 0
    assert "paper.yaml lists no registration" in capsys.readouterr().out


def test_a_dry_run_says_what_it_would_ask_and_sends_nothing(project, capsys, monkeypatch) -> None:
    monkeypatch.setattr(lookup, "default_transport", _refused)
    _declare(project, {"id": NCT}, {"id": "CRD42020182366"})
    assert main(["lookup", str(project), "--registrations", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"{NCT}: would ask ClinicalTrials.gov (no record)" in out
    assert "CRD42020182366: not looked up: PROSPERO is not asked" in out
    assert not (project / "design" / "registrations").exists()


def test_journals_and_registrations_are_not_asked_together(project, capsys) -> None:
    assert main(["lookup", str(project), "--registrations", "--journals"]) == 2


# ------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        self.server.seen.append(self.path)
        status, payload, headers = self.server.respond(self.path)
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
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

    def respond(path: str) -> tuple[int, bytes, dict]:
        if path.startswith("/studies/"):
            return 200, json.dumps(_study()).encode(), {"Content-Type": "application/json"}
        if path.startswith("/ema/study/"):
            return 302, b"", {"Location": "/node/4318/administrative-details"}
        if path.startswith("/ema/node/4318/administrative-details"):
            return 200, _administrative(), {"Content-Type": "text/html"}
        if path.startswith("/ema/node/4318/methodological-aspects"):
            return 200, _methodological(), {"Content-Type": "text/html"}
        return 404, b"", {}

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


def test_the_real_transport_looks_up_a_trial_and_a_catalogue_study(
    project: Path, server
) -> None:
    """The catalogue's redirect is read for the page it names, and never followed: the next
    request is this tool's own, to the same host."""
    _declare(project, {"id": NCT}, {"id": "EUPAS1000000999"})
    services = registries.Services(clinicaltrials=f"{server.url}/studies/", osf=_OSF,
                                   isrctn=_ISRCTN, eu_pas=f"{server.url}/ema")  # fmt: skip
    project_ = load_project(project)[0]
    pacer = lookup.Pacer(sleep=lambda s: None)
    lookup.run(project_, lookup.plan(project_), services=services, pacer=pacer, today=TODAY,
               said=lambda line: None)
    trial = read_record(record_path(project_, NCT))
    study = read_record(record_path(project_, "EUPAS1000000999"))
    assert trial["status"] == FOUND and study["status"] == FOUND
    assert [urlsplit(p).path for p in server.seen] == [
        f"/studies/{NCT}", "/ema/study/1000000999", "/ema/node/4318/administrative-details",
        "/ema/node/4318/methodological-aspects",
    ]  # fmt: skip
    assert parse_qs(urlsplit(server.seen[0]).query)["markupFormat"] == ["legacy"]
    for path in (project / "design" / "registrations").glob("*.yaml"):
        assert "127.0.0.1" not in path.read_text(encoding="utf-8")
