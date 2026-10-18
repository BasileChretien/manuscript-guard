"""`lookup --journals`: each shortlisted journal's ISSN asked of the NLM Catalog and DOAJ once,
and the answers kept for G4 to read offline (item 49).

No test opens a connection to either. Most answer from a table; the real transport is run
against a server on a loopback port. The answers are written here in the shapes the services
document and answered on 2026-10-17, for fictional journals.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts.project import load_project
from manuscript_guard.lookup import journals
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport
from manuscript_guard.lookup.run import Credentials
from manuscript_guard.shortlist import answers_digest, read_record, record_path

TODAY = date(2026, 10, 17)
PRINT, ONLINE, OTHER = "1111-111X", "2222-2222", "3333-3333"
NAME = "Journal of Demonstrative Pharmacoepidemiology"
NCBI = "ncbi-key-0123456789abcdefSECRET"
SERVICES = journals.Services(
    esearch="https://eutils.invalid/esearch.fcgi",
    esummary="https://eutils.invalid/esummary.fcgi",
    doaj="https://doaj.invalid/api/v4/search/journals/",
)


def _json(status: int, data: object) -> Response:
    return Response(status, {}, json.dumps(data).encode())


def esearch(*ids: str) -> Response:
    return _json(200, {"header": {"type": "esearch", "version": "0.3"},
                       "esearchresult": {"count": str(len(ids)), "retmax": str(len(ids)),
                                         "retstart": "0", "idlist": list(ids)}})  # fmt: skip


def esummary(indexed: str = "Y", uid: str = "900001", issns=(PRINT, ONLINE)) -> Response:
    item = {
        "uid": uid,
        "nlmuniqueid": "9999001R",
        "titlemainlist": [{"sorttitle": "journal of demonstrative", "title": f"{NAME}."}],
        "issnlist": [{"issn": i, "validyn": "Y", "issntype": "Print"} for i in issns],
        "currentindexingstatus": indexed,
    }
    return _json(200, {"header": {"type": "esummary"}, "result": {"uids": [uid], uid: item}})


def listed(issn: str = ONLINE, total: int = 1) -> Response:
    results = [{"id": "f00dfeed", "bibjson": {"title": NAME, "eissn": issn},
                "last_updated": "2026-09-17T10:51:00Z", "admin": {"ticked": True}}]  # fmt: skip
    return _json(200, {"total": total, "page": 1, "pageSize": 10, "results": results[:total]})


class Table:
    """A transport that answers by service, and keeps what it was sent."""

    def __init__(self, **answers: Response) -> None:
        self.answers = {"esearch": esearch("900001"), "esummary": esummary(),
                        "doaj": listed(), **answers}  # fmt: skip
        self.sent: list[Request] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append(request)
        path = urlsplit(request.base).path
        name = "doaj" if "/search/journals/" in path else path.rsplit("/", 1)[1].split(".")[0]
        return self.answers[name]


def _ask(table: Table):
    return lambda request: table(request, 1.0)


# ---------------------------------------------------------------------------- what is read


@pytest.mark.parametrize(
    ("answers", "said"),
    [
        ({}, {"status": "found", "records": [{"nlm_id": "9999001R", "title": f"{NAME}.",
                                              "currently_indexed": True,
                                              "issns": [PRINT, ONLINE]}]}),
        ({"esummary": esummary("N")}, "not indexed"),
        ({"esearch": esearch()}, {"status": "absent"}),
        ({"esearch": _json(500, {})}, {"status": "unresolvable", "why": "HTTP 500"}),
        ({"esearch": _json(200, {"esearchresult": {"ERROR": "Invalid query"}})},
         {"status": "unresolvable", "why": "the service said: error"}),
        ({"esummary": _json(200, {"result": {"uids": ["900001"], "900001": {"uid": "900001"}}})},
         "shape"),
        ({"esearch": _json(429, {})}, "throttled"),
    ],
)
def test_the_nlm_catalog_is_read_into_the_record(answers, said) -> None:
    table = Table(**answers)
    got = journals.nlm_catalog(ONLINE, _ask(table), SERVICES, Credentials())
    if said == "not indexed":
        assert got["status"] == "found" and got["records"][0]["currently_indexed"] is False
    elif said == "shape":
        assert got["status"] == "unresolvable" and "shape" in got["why"]
    elif said == "throttled":
        assert got["status"] == "unresolvable" and "429" in got["why"]
    else:
        assert got == said
    first = table.sent[0]
    assert parse_qs(urlsplit(first.url).query)["term"] == [f"{ONLINE}[IS]"]
    assert parse_qs(urlsplit(first.url).query)["db"] == ["nlmcatalog"]


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (listed(), "found"),
        (listed(total=0), "absent"),
        # A search that found another journal: this ISSN is not listed.
        (listed(issn=OTHER), "absent"),
        (_json(200, {"total": "one", "results": []}), "unresolvable"),
        (_json(503, {}), "unresolvable"),
        (Response(200, {}, b"<html>maintenance</html>"), "unresolvable"),
    ],
)
def test_doaj_is_read_into_the_record(answer, said) -> None:
    table = Table(doaj=answer)
    got = journals.doaj(ONLINE, _ask(table), SERVICES)
    assert got["status"] == said
    if said == "found":
        assert got == {"status": "found", "id": "f00dfeed", "title": NAME, "issns": [ONLINE],
                       "last_updated": "2026-09-17T10:51:00Z"}  # fmt: skip
    assert unquote(table.sent[0].base).endswith(f"/search/journals/issn:{ONLINE}")


def test_a_key_travels_and_is_never_kept(project: Path) -> None:
    table = Table()
    record = journals.look_up(
        ONLINE, _ask(table), SERVICES, Credentials(contact="author@example.org", ncbi_key=NCBI),
        TODAY,
    )  # fmt: skip
    assert all(NCBI in r.url for r in table.sent if "eutils" in r.base)
    assert NCBI not in repr(record) and "author@example.org" not in repr(record)
    assert all(NCBI not in r.shown for r in table.sent)
    assert record["answers_sha256"] == answers_digest(record)


# ----------------------------------------------------------------------------- the command


def write_shortlist(root: Path, **candidate) -> None:
    shortlist = {
        "schema": "manuscript-guard/shortlist/1",
        "criteria": {"stated_by": "A. Author", "stated_on": "2026-10-17",
                     "indexing": ["MEDLINE"], "open_access": "preferred"},  # fmt: skip
        "candidates": [{"journal": NAME, "issn": [PRINT, ONLINE], "profile": "demo-journal",
                        **candidate}],  # fmt: skip
        "decision": {"journal": NAME, "decided_by": "A. Author", "decided_on": "2026-10-17"},
    }
    folder = root / "journals"
    folder.mkdir(exist_ok=True)
    (folder / "shortlist.yaml").write_text(yaml.safe_dump(shortlist, sort_keys=False),
                                           encoding="utf-8")  # fmt: skip


def look_up_journals(root: Path, table: Table | None = None) -> Table:
    """The shortlist's ISSNs looked up, as `lookup --journals` would, from the table."""
    table = table or Table()
    project, _ = load_project(root)
    journals.run(project, [PRINT, ONLINE], transport=table, services=SERVICES, today=TODAY,
                 said=lambda _: None)  # fmt: skip
    return table


def test_lookup_journals_keeps_a_record_per_issn_and_asks_once(
    project: Path, monkeypatch, capsys
) -> None:
    write_shortlist(project)
    table = Table()
    monkeypatch.setattr(journals, "default_transport", table)
    monkeypatch.setattr(journals, "Services", lambda: SERVICES)
    assert main(["lookup", str(project), "--journals", "--dry-run"]) == 0
    assert table.sent == [] and "nothing was sent" in capsys.readouterr().out
    assert main(["lookup", str(project), "--journals"]) == 0
    out = capsys.readouterr().out
    assert f"ISSN {ONLINE}: NLM Catalog: currently indexed for MEDLINE; DOAJ: listed" in out, out
    assert f"ISSN {PRINT}: NLM Catalog: currently indexed for MEDLINE; DOAJ: absent" in out, out
    assert "2 looked up" in out, out
    loaded, _ = load_project(project)
    for issn in (PRINT, ONLINE):
        assert read_record(loaded, issn) is not None
    asked = len(table.sent)
    assert main(["lookup", str(project), "--journals"]) == 0
    assert len(table.sent) == asked and "0 looked up, 2 up to date" in capsys.readouterr().out
    assert main(["lookup", str(project), "--journals", "--again"]) == 0
    assert len(table.sent) == 2 * asked


def test_lookup_journals_asks_again_where_an_answer_did_not_come(
    project: Path, monkeypatch, capsys
) -> None:
    write_shortlist(project)
    table = Table(doaj=_json(503, {}))
    monkeypatch.setattr(journals, "default_transport", table)
    monkeypatch.setattr(journals, "Services", lambda: SERVICES)
    assert main(["lookup", str(project), "--journals"]) == 1
    assert "asks again" in capsys.readouterr().out
    table.answers["doaj"] = listed()
    assert main(["lookup", str(project), "--journals"]) == 0
    assert "2 looked up" in capsys.readouterr().out


def test_lookup_journals_without_a_shortlist_says_why(project: Path, capsys) -> None:
    assert main(["lookup", str(project), "--journals"]) == 2
    assert "there is no journals/shortlist.yaml" in capsys.readouterr().err


def test_an_edited_record_is_not_read(project: Path) -> None:
    write_shortlist(project)
    look_up_journals(project)
    loaded, _ = load_project(project)
    path = record_path(loaded, ONLINE)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["sources"]["nlm_catalog"]["records"][0]["currently_indexed"] = False
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert read_record(loaded, ONLINE) is None


# ------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        path = urlsplit(self.path).path
        name = "doaj" if "/search/journals/" in path else path.rsplit("/", 1)[1].split(".")[0]
        answer = Table().answers.get(name, _json(404, {}))
        self.server.seen.append(self.path)
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer.body)))
        self.end_headers()
        self.wfile.write(answer.body)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


def test_the_real_transport_asks_both_on_loopback(project: Path) -> None:
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        try:
            default_transport(Request(url + "/probe"), 5)
        except NoAnswer as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"loopback connections are not allowed here: {exc}")
        services = journals.Services(esearch=f"{url}/esearch.fcgi",
                                     esummary=f"{url}/esummary.fcgi",
                                     doaj=f"{url}/api/v4/search/journals/")  # fmt: skip
        write_shortlist(project)
        loaded, _ = load_project(project)
        [(record, _path)] = journals.run(loaded, [ONLINE], services=services, today=TODAY,
                                         said=lambda _: None)  # fmt: skip
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert record["sources"]["nlm_catalog"]["status"] == "found"
    assert record["sources"]["doaj"]["status"] == "found"


def test_the_skills_example_shortlist_is_one() -> None:
    """The journal-profile skill shows the record it asks the agent to write."""
    import re

    from manuscript_guard.contracts._schema import _plain, validate

    skill = Path(__file__).resolve().parents[1] / "plugin" / "skills" / "journal-profile"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    [block] = [b for b in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL) if "shortlist/1" in b]
    report = validate(_plain(yaml.safe_load(block)), "shortlist", skill / "SKILL.md")
    assert report.ok, report.render()
