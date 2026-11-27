"""The paper's own registration numbers under `audit --lookup` (Basile, 2026-11-26): each
NCT, ISRCTN, EU PAS or PROSPERO number the paper names outside its reference list, its record
asked of ClinicalTrials.gov or ISRCTN, what the registry holds shown for the editor to
compare, and a registration after the study's start flagged from the registry's own dates
alone. Every answer comes from a table the test gives as the transport: no test opens a
connection to a registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.auditing import editor
from manuscript_guard.cli import main
from manuscript_guard.lookup import http
from manuscript_guard.lookup import run as lookup
from manuscript_guard.lookup.http import Response

PAPER = (
    "# A trial of a drug\n\n## Abstract\n\nTrial registration: ClinicalTrials.gov "
    "NCT04446611.\n\n## Methods\n\nThe trial was registered before it began (NCT04446611).\n\n"
    "## Results\n\nOf the 120 patients, 30 (25.0%) died.\n\n## References\n\n"
    "1. Smith A. Another trial. Lancet. 2019;393:1-2. NCT01111111\n"
)


def _study(nct: str, registered: str, start: str | None, start_type: str = "ACTUAL",
           primary: tuple[str, ...] = ("Death at 28 days",)) -> dict:
    status = {"studyFirstSubmitDate": registered, "lastUpdateSubmitDate": "2021-01-04"}
    if start is not None:
        status["startDateStruct"] = {"date": start, "type": start_type}
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "officialTitle": "A trial of a drug in adults"},
        "statusModule": status,
        "designModule": {"studyType": "INTERVENTIONAL"},
        "outcomesModule": {"primaryOutcomes": [{"measure": m, "timeFrame": "28 days"}
                                               for m in primary]},
    }}  # fmt: skip


ISRCTN_XML = (
    '<allTrials xmlns="http://www.67bricks.com/isrctn" totalCount="1"><fullTrial>'
    '<trial lastUpdated="2021-01-01T00:00:00Z">'
    '<isrctn dateAssigned="{assigned}T00:00:00Z">24952438</isrctn>'
    "<trialDescription><scientificTitle>A trial of exercise</scientificTitle>"
    "<primaryOutcome>Pain at 6 weeks</primaryOutcome></trialDescription>"
    "<participants><recruitmentStart>{start}T00:00:00Z</recruitmentStart></participants>"
    "</trial></fullTrial></allTrials>"
)


class Registries:
    """ClinicalTrials.gov answering for the studies in `studies`, 404 for any other, and
    ISRCTN for its one trial; every request seen."""

    def __init__(self) -> None:
        self.studies: dict[str, dict] = {}
        self.isrctn: tuple[str, str] = ("2019-05-01", "2019-03-01")
        self.seen: list[str] = []

    def __call__(self, request, timeout):  # noqa: ARG002 - the transport's signature
        self.seen.append(request.url)
        if "clinicaltrials.gov" in request.base:
            nct = request.base.rsplit("/", 1)[1]
            if nct in self.studies:
                return Response(200, {"Content-Type": "application/json"},
                                json.dumps(self.studies[nct]).encode())  # fmt: skip
            return Response(404, {}, b'{"message": "Study not found"}')
        if "isrctn.com" in request.base:
            assigned, start = self.isrctn
            return Response(200, {"Content-Type": "application/xml"},
                            ISRCTN_XML.format(assigned=assigned, start=start).encode())
        return Response(404, {}, b"{}")

    @property
    def asked(self) -> list[str]:
        return [url for url in self.seen if "clinicaltrials.gov" in url or "isrctn.com" in url]


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch) -> Registries:
    table = Registries()
    monkeypatch.setattr(http, "default_transport", table)
    monkeypatch.setattr(lookup, "Pacer", lambda: lookup_pacer())
    return table


def lookup_pacer():
    return _PACER(sleep=lambda seconds: None)


_PACER = lookup.Pacer


def _audit(tmp_path: Path, capsys, text: str = PAPER, *flags: str) -> tuple[int, str, dict]:
    paper = tmp_path / "paper.md"
    paper.write_text(text, encoding="utf-8")
    code = main(["audit", str(paper), *flags])
    out = capsys.readouterr().out
    main(["audit", str(paper), "--json", *flags])
    data = json.loads(capsys.readouterr().out)
    return code, out, data


def _registration(data: dict) -> list[dict]:
    return [f for f in data["findings"] if f["gate"] == "G12"]


def test_a_number_named_in_the_text_is_asked_once_and_one_in_the_reference_list_never(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """The Abstract and the Methods name the same trial: it is asked once. A trial cited in
    the reference list is another study's, and is not asked."""
    registries.studies["NCT04446611"] = _study("NCT04446611", "2020-06-20", "2020-07")
    _audit(tmp_path, capsys, PAPER, "--lookup")
    asked = [url for url in registries.asked if "NCT" in url]
    assert all("NCT04446611" in url for url in asked), asked
    assert not any("NCT01111111" in url for url in registries.seen)


def test_the_record_is_shown_with_its_primary_outcome_and_dates_for_the_editor(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    registries.studies["NCT04446611"] = _study("NCT04446611", "2020-06-20", "2020-07")
    _code, out, data = _audit(tmp_path, capsys, PAPER, "--lookup")
    assert "=== Registration (G12)" in out
    (record,) = [f for f in _registration(data) if f["code"] == "registration-record"]
    assert record["severity"] == "info" and record["line"] == 5
    for said in ("NCT04446611", "ClinicalTrials.gov", "2020-06-20", "2020-07",
                 "Death at 28 days", "named 2 times"):
        assert said in record["message"], (said, record["message"])
    assert not [f for f in _registration(data) if f["code"] == "registration-late"]


def test_a_registration_after_the_study_s_actual_start_is_flagged(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    registries.studies["NCT04446611"] = _study("NCT04446611", "2020-08-02", "2020-07")
    _code, _out, data = _audit(tmp_path, capsys, PAPER, "--lookup")
    (late,) = [f for f in _registration(data) if f["code"] == "registration-late"]
    assert late["severity"] == "warn"
    assert "2020-08-02" in late["message"] and "2020-07" in late["message"]


@pytest.mark.parametrize(("registered", "start", "start_type"), [
    ("2020-07-15", "2020-07", "ACTUAL"),      # in the month it started: maybe before it
    ("2020-09-01", "2020-07", "ESTIMATED"),   # a start the registry only expects
    ("2020-09-01", "2999-01-01", "ACTUAL"),   # a start after the day asked is a plan
], ids=["same-month", "estimated", "future"])  # fmt: skip
def test_a_registration_not_shown_late_by_the_registry_s_own_dates_is_not_flagged(
    tmp_path: Path, capsys, registries: Registries, registered: str, start: str,
    start_type: str,
) -> None:
    registries.studies["NCT04446611"] = _study("NCT04446611", registered, start, start_type)
    _code, _out, data = _audit(tmp_path, capsys, PAPER, "--lookup")
    assert not [f for f in _registration(data) if f["code"] == "registration-late"]
    assert [f for f in _registration(data) if f["code"] == "registration-record"]


def test_a_number_its_registry_does_not_know_is_said(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    _code, _out, data = _audit(tmp_path, capsys, PAPER, "--lookup")
    (unknown,) = [f for f in _registration(data) if f["code"] == "registration-unknown"]
    assert "NCT04446611" in unknown["message"] and unknown["severity"] == "warn"


def test_an_isrctn_number_is_asked_of_isrctn_and_its_dates_shown_never_judged(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """ISRCTN gives its recruitment start with no word of whether it happened or was planned:
    registered after a start that was only planned is not late, so ISRCTN's dates are shown
    and never judged (round 1 of #827)."""
    text = PAPER.replace("ClinicalTrials.gov NCT04446611", "ISRCTN24952438").replace(
        "(NCT04446611)", "(ISRCTN24952438)")
    _code, _out, data = _audit(tmp_path, capsys, text, "--lookup")
    assert any("isrctn.com" in url and "ISRCTN24952438" in url for url in registries.asked)
    (record,) = [f for f in _registration(data) if f["code"] == "registration-record"]
    assert "recruitment start" in record["message"] and "2019-03-01" in record["message"]
    assert "study started" not in record["message"]
    assert not [f for f in _registration(data) if f["code"] == "registration-late"]


def test_a_number_after_a_comment_of_several_lines_is_said_at_its_own_line(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """A comment's line breaks are masked as no breaks at all: a number counted in the masked
    text was placed above where it stands, its context another line's (round 1 of #827)."""
    registries.studies["NCT04446611"] = _study("NCT04446611", "2020-06-20", "2020-07")
    text = PAPER.replace("Trial registration: ClinicalTrials.gov NCT04446611.\n\n", "").replace(
        "## Methods\n\n", "## Methods\n\n<!--\nnote one\nnote two\n-->\n")
    _code, _out, data = _audit(tmp_path, capsys, text, "--lookup")
    (record,) = [f for f in _registration(data) if f["code"] == "registration-record"]
    lines = text.split("\n")
    assert lines[record["line"] - 1] == "The trial was registered before it began (NCT04446611)."
    assert record["context"] == lines[record["line"] - 1]


def test_a_prospero_number_is_left_to_be_looked_up_by_hand_and_nothing_is_sent(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    text = PAPER.replace("ClinicalTrials.gov NCT04446611", "PROSPERO CRD42020123456").replace(
        "(NCT04446611)", "(CRD42020123456)")
    _code, _out, data = _audit(tmp_path, capsys, text, "--lookup")
    assert not any("CRD42020123456" in url for url in registries.seen)
    (by_hand,) = [f for f in _registration(data) if f["code"] == "registration-by-hand"]
    assert "PROSPERO" in by_hand["message"]


def test_a_dry_run_says_what_it_would_ask_and_sends_nothing(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    _code, _out, data = _audit(tmp_path, capsys, PAPER, "--lookup", "--dry-run")
    assert registries.asked == []
    (would,) = [f for f in _registration(data) if f["code"] == "registration-would-ask"]
    assert "NCT04446611" in would["message"]


def test_without_lookup_no_registry_is_asked_and_the_report_says_nothing_of_it(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    _code, out, data = _audit(tmp_path, capsys, PAPER)
    assert registries.seen == []
    assert _registration(data) == [] and "Registration (G12)" not in out


def test_the_editor_s_report_puts_the_record_and_a_late_registration_under_look(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    registries.studies["NCT04446611"] = _study("NCT04446611", "2020-08-02", "2020-07")
    _code, out, _data = _audit(tmp_path, capsys, PAPER, "--lookup", "--editor")
    look = out.split(editor.title(editor.LOOK))[1].split(editor.title(editor.ASK))[0]
    assert "NCT04446611" in look
    for code in ("registration-record", "registration-late", "registration-unknown"):
        (kind,) = [kind for kind in editor.KINDS if ("G12", code) in kind.codes]
        assert kind.part == editor.LOOK, code
