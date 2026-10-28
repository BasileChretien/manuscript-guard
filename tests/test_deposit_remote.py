"""`deposit --reserve-doi`, `--stage` and `--publish`, against hosts this machine stands up.

No test opens a connection to Zenodo or OSF. A server on a loopback port answers as their
APIs are documented to (`FakeHosts`), and the real transport talks to it, token and all; a
few tests hand the client a transport that answers from a table instead. What is held:

- the token goes in the Authorization header and nowhere else, and no message, receipt or
  history holds it, nor a part of it a host echoed;
- a redirect is refused, a link to another host is not followed, a host that does not answer
  is said in our words;
- an md5 that is not the bytes sent stops the staging, with nothing after it sent;
- a draft is published only when the bundle is the one staged and the DOI is typed at a
  terminal, which `--yes` does not answer;
- a test DOI is never written into paper.yaml, and a release's real one is, its comments kept;
- OSF stages a private project and refuses a DOI and a publication.

Skipped where a loopback connection is not allowed, as in some sandboxes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import yaml
from test_deposit import deposit, unfrozen
from test_package import ready

from manuscript_guard.cli import main
from manuscript_guard.deposit.remote import command, osf, receipts, zenodo
from manuscript_guard.deposit.remote.http import (
    Client,
    NoAnswer,
    RemoteError,
    Request,
    Response,
    default_transport,
)

PANDOC = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
TOKEN = "zt-0123456789abcdefSECRETtoken"
SANDBOX = "10.5072/zenodo.101"
REAL = "10.5281/zenodo.101"


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _answer(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.seen.append((self.command, self.path, dict(self.headers.items()), body))
        status, payload, headers = self.server.hosts.answer(self.command, self.path, body)
        data = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    do_GET = do_POST = do_PUT = _answer  # noqa: N815 - the names http.server looks for

    def log_message(self, *args) -> None:
        pass


class FakeHosts:
    """Zenodo's deposition API and OSF's, as documented, holding what is sent to them."""

    def __init__(self, url: str, doi: str = SANDBOX) -> None:
        self.url, self.doi = url, doi
        self.files: dict[str, bytes] = {}
        self.metadata: dict | None = None
        self.published = False
        #: The name of a file whose md5 is answered wrong, as a host that kept other bytes.
        self.corrupt: str | None = None
        #: A file the draft holds that nobody sent.
        self.extra: str | None = None
        self.bucket = f"{url}/api/files/bucket-101"
        self.override: tuple | None = None
        #: What a publication is answered with, where not the record as documented.
        self.publish_answer: dict | None = None
        self.osf_public = False

    def _deposition(self) -> dict:
        return {"id": 101, "metadata": {"prereserve_doi": {"doi": self.doi, "recid": 101}},
                "links": {"bucket": self.bucket, "html": f"{self.url}/deposit/101"}}

    def answer(self, method: str, path: str, body: bytes) -> tuple[int, object, dict]:
        if self.override is not None:
            return self.override
        parts = urlsplit(path)
        if method == "POST" and parts.path == "/api/deposit/depositions":
            return 201, self._deposition(), {}
        if method == "PUT" and parts.path.startswith("/api/files/bucket-101/"):
            name = unquote(parts.path.rsplit("/", 1)[1])
            self.files[name] = body
            said = "0" * 32 if name == self.corrupt else md5(body)
            return 201, {"key": name, "checksum": f"md5:{said}"}, {}
        if method == "GET" and parts.path == "/api/deposit/depositions/101":
            held = [{"filename": name, "checksum": md5(data)} for name, data in self.files.items()]
            if self.extra:
                held.append({"filename": self.extra, "checksum": "1" * 32})
            return 200, {**self._deposition(), "files": held}, {}
        if method == "PUT" and parts.path == "/api/deposit/depositions/101":
            self.metadata = json.loads(body)["metadata"]
            return 200, {**self._deposition(), "metadata": {
                **self.metadata, "prereserve_doi": {"doi": self.doi}}}, {}  # fmt: skip
        if method == "POST" and parts.path == "/api/deposit/depositions/101/actions/publish":
            self.published = True
            if self.publish_answer is not None:
                return 202, self.publish_answer, {}
            page = f"{self.url}/records/101"
            return 202, {"id": 101, "doi": self.doi, "links": {"html": page}}, {}
        if method == "POST" and parts.path == "/v2/nodes/":
            return 201, {"data": {"id": "ab1cd", "attributes": {"public": self.osf_public},
                                  "links": {"html": f"{self.url}/ab1cd/"}}}, {}  # fmt: skip
        if method == "PUT" and parts.path == "/v1/resources/ab1cd/providers/osfstorage/":
            name = parse_qs(parts.query)["name"][0]
            self.files[name] = body
            said = "0" * 32 if name == self.corrupt else md5(body)
            return 201, {"data": {"attributes": {"name": name, "extra": {
                "hashes": {"md5": said, "sha256": hashlib.sha256(body).hexdigest()}}}}}, {}
        return 404, {"message": f"no route for {method} {parts.path}"}, {}


@pytest.fixture
def hosts(monkeypatch):
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.seen, httpd.hosts = [], FakeHosts(url)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        default_transport(Request("GET", url + "/probe"), 5)
    except NoAnswer as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    for target in ("zenodo", "zenodo-sandbox"):
        monkeypatch.setitem(zenodo.HOSTS, target, url)
    monkeypatch.setitem(osf.HOSTS, "api", url)
    monkeypatch.setitem(osf.HOSTS, "files", url)
    for name in ("ZENODO_TOKEN", "ZENODO_SANDBOX_TOKEN", "OSF_TOKEN"):
        monkeypatch.setenv(name, TOKEN)
    # Nobody at a terminal unless a test says what they type.
    monkeypatch.setattr(command, "ask_at_terminal", lambda _prompt: None)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def typed(monkeypatch, answer: str | None) -> list[str]:
    asked: list[str] = []

    def ask(prompt: str) -> str | None:
        asked.append(prompt)
        return answer

    monkeypatch.setattr(command, "ask_at_terminal", ask)
    return asked


def receipt(root: Path, name: str) -> dict:
    return yaml.safe_load((root / "deposit" / "receipts" / f"{name}.yaml").read_text("utf-8"))


def nowhere_but_the_header(root: Path, hosts, *said: str) -> None:
    """The token, or any four characters of it, is in no URL, body, file or message; and it
    is in every request's Authorization header."""
    for _method, path, headers, body in hosts.seen:
        assert headers.get("Authorization") == f"Bearer {TOKEN}"
        assert TOKEN not in path and TOKEN.encode() not in body
    written = [path.read_text("utf-8") for path in (root / "deposit").rglob("*.yaml")]
    for text in (*written, *said):
        assert TOKEN not in text and "SECRET" not in text, text


# ------------------------------------------------------------------ Zenodo


def test_a_sandbox_doi_is_reserved_recorded_and_never_written(project: Path, hosts, capsys,
                                                               monkeypatch) -> None:  # fmt: skip
    before = (project / "paper.yaml").read_bytes()
    typed(monkeypatch, "yes")
    assert deposit(project, "zenodo-sandbox", "release", "--reserve-doi", "--yes") == 0
    out = capsys.readouterr().out
    assert SANDBOX in out and "never written into paper.yaml" in out
    assert (project / "paper.yaml").read_bytes() == before
    held = receipt(project, "zenodo-sandbox-release")
    assert (held["id"], held["doi"], held["bucket"]) == (101, SANDBOX, hosts.hosts.bucket)
    assert held["reserved_on"].endswith("Z")
    history = yaml.safe_load((project / "deposit" / "history.yaml").read_text("utf-8"))
    assert [entry["action"] for entry in history] == ["reserved"]
    [(method, path, _headers, body)] = hosts.seen
    assert (method, path) == ("POST", "/api/deposit/depositions")
    assert json.loads(body) == {"metadata": {"prereserve_doi": True}}
    nowhere_but_the_header(project, hosts, out)


def test_a_test_doi_from_zenodo_itself_is_never_written(project: Path, hosts, capsys) -> None:
    """The DOI is held to its prefix as well as to the target."""
    before = (project / "paper.yaml").read_bytes()
    assert deposit(project, "zenodo", "release", "--reserve-doi", "--yes") == 0
    assert (project / "paper.yaml").read_bytes() == before
    assert "never written" in capsys.readouterr().out


def test_a_release_doi_is_written_into_paper_yaml_with_its_comments(project: Path, hosts,
                                                                    capsys) -> None:  # fmt: skip
    hosts.hosts.doi = REAL
    text = (project / "paper.yaml").read_text(encoding="utf-8")
    assert deposit(project, "zenodo", "release", "--reserve-doi", "--yes") == 0
    now = (project / "paper.yaml").read_text(encoding="utf-8")
    assert now == text.replace("package:\n", f"package:\n  doi: '{REAL}'\n", 1)
    assert yaml.safe_load(now)["package"]["doi"] == REAL
    # A second reservation would reserve a second DOI.
    assert deposit(project, "zenodo", "release", "--reserve-doi") == 1
    assert "a second would reserve a second DOI" in capsys.readouterr().err


def test_a_release_doi_is_not_written_unless_the_author_says_yes(project: Path, hosts, capsys,
                                                                 monkeypatch) -> None:  # fmt: skip
    hosts.hosts.doi = REAL
    before = (project / "paper.yaml").read_bytes()
    asked = typed(monkeypatch, "no")
    assert deposit(project, "zenodo", "release", "--reserve-doi") == 0
    assert asked and (project / "paper.yaml").read_bytes() == before
    assert f"doi: {REAL}" in capsys.readouterr().out


def test_a_plans_doi_is_not_the_packages(project: Path, hosts, capsys) -> None:
    hosts.hosts.doi = REAL
    before = (project / "paper.yaml").read_bytes()
    assert deposit(unfrozen(project), "zenodo", "preregistration", "--reserve-doi",
                   "--yes") == 0  # fmt: skip
    assert (project / "paper.yaml").read_bytes() == before
    assert "the release's" in capsys.readouterr().out


def _staged(project: Path, hosts) -> None:
    assert deposit(unfrozen(project), "zenodo-sandbox", "preregistration", "--reserve-doi",
                   "--stage") == 0  # fmt: skip


def test_staging_sends_each_file_checks_its_md5_and_describes_the_draft(
    project: Path, hosts, capsys
) -> None:
    _staged(project, hosts)
    out = capsys.readouterr().out
    folder = project / "build" / "deposit" / "zenodo-sandbox-preregistration"
    top = sorted(path.name for path in folder.iterdir() if path.is_file())
    assert sorted(hosts.hosts.files) == sorted(["zenodo-sandbox-preregistration.zip", *top])
    assert hosts.hosts.files["README.md"] == (folder / "README.md").read_bytes()
    wanted = json.loads((folder / ".zenodo.json").read_text(encoding="utf-8"))
    assert hosts.hosts.metadata == {**wanted, "prereserve_doi": True}
    held = receipt(project, "zenodo-sandbox-preregistration")
    assert held["files"]["README.md"]["md5"] == md5((folder / "README.md").read_bytes())
    assert len(held["bundle_sha256"]) == 64 and held["staged_on"]
    assert not hosts.hosts.published and "nothing is published" in out
    nowhere_but_the_header(project, hosts, out)


def test_a_file_the_host_holds_as_other_bytes_stops_the_staging(project: Path, hosts,
                                                                capsys) -> None:  # fmt: skip
    hosts.hosts.corrupt = "CITATION.cff"
    assert deposit(unfrozen(project), "zenodo-sandbox", "preregistration", "--reserve-doi",
                   "--stage") == 1  # fmt: skip
    said = capsys.readouterr().err
    assert "CITATION.cff as other bytes than were sent" in said and "stopped" in said
    # Nothing after it was sent, the draft was not described, and nothing is recorded staged.
    puts = [path for method, path, _h, _b in hosts.seen if method == "PUT"]
    assert puts[-1].endswith("/CITATION.cff") and hosts.hosts.metadata is None
    assert "staged_on" not in receipt(project, "zenodo-sandbox-preregistration")


def test_staging_without_a_draft_is_refused(project: Path, hosts, capsys) -> None:
    assert deposit(unfrozen(project), "zenodo-sandbox", "preregistration", "--stage") == 1
    assert "reserve its DOI first" in capsys.readouterr().err
    assert hosts.seen == []


def test_a_draft_holding_a_file_nobody_sent_is_refused(project: Path, hosts, capsys) -> None:
    hosts.hosts.extra = "old.zip"
    assert deposit(unfrozen(project), "zenodo-sandbox", "preregistration", "--reserve-doi",
                   "--stage") == 1  # fmt: skip
    assert "holds files the bundle does not: old.zip" in capsys.readouterr().err


def test_publishing_needs_the_doi_typed_and_yes_does_not_answer_it(
    project: Path, hosts, capsys, monkeypatch
) -> None:
    _staged(project, hosts)
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish", "--yes") == 1
    assert "there is none here: run it yourself" in capsys.readouterr().err
    typed(monkeypatch, "10.5072/zenodo.102")
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    assert "not the draft's DOI" in capsys.readouterr().err
    assert not hosts.hosts.published
    asked = typed(monkeypatch, f" {SANDBOX} ")
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 0
    assert hosts.hosts.published and SANDBOX in asked[0] and "cannot be deleted" in asked[0]
    held = receipt(project, "zenodo-sandbox-preregistration")
    assert held["published_on"] and held["page"].endswith("/records/101")
    history = yaml.safe_load((project / "deposit" / "history.yaml").read_text("utf-8"))
    assert [entry["action"] for entry in history] == ["reserved", "staged", "publish_sent",
                                                       "published"]
    # Published once, it is not published or staged again.
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    assert deposit(project, "zenodo-sandbox", "preregistration", "--stage") == 1
    nowhere_but_the_header(project, hosts, capsys.readouterr().err)


def test_a_bundle_changed_since_it_was_staged_is_not_published(project: Path, hosts, capsys,
                                                               monkeypatch) -> None:  # fmt: skip
    _staged(project, hosts)
    plan = project / "design" / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\nA sentence added after staging.\n",
                    encoding="utf-8")  # fmt: skip
    asked = typed(monkeypatch, SANDBOX)
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    assert "not the one staged" in capsys.readouterr().err
    assert not asked and not hosts.hosts.published


def test_a_draft_changed_at_the_host_is_not_published(project: Path, hosts, capsys,
                                                      monkeypatch) -> None:  # fmt: skip
    _staged(project, hosts)
    hosts.hosts.files["README.md"] = b"changed on the page"
    typed(monkeypatch, SANDBOX)
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    assert "other bytes than the bundle for README.md" in capsys.readouterr().err
    assert not hosts.hosts.published


@PANDOC
def test_a_release_is_published_only_with_every_authors_current_approval(
    project: Path, hosts, capsys, monkeypatch
) -> None:
    ready(project)
    hosts.hosts.doi = REAL
    assert deposit(project, "zenodo", "release", "--reserve-doi", "--yes") == 0
    assert yaml.safe_load((project / "paper.yaml").read_text("utf-8"))["package"]["doi"] == REAL
    # Until the statement names the DOI, the release fails the submission check, and is not
    # staged: G4 asks for it there.
    assert deposit(project, "zenodo", "release", "--stage") == 1
    out = capsys.readouterr().out
    assert f"availability statement names {REAL}" in out
    assert hosts.hosts.files == {}
    # Named, as tests/test_package.py holds G4 to: a change of the manuscript here would leave
    # the example's review rounds behind it, which the submission check holds as well.
    from manuscript_guard import cli
    from manuscript_guard.findings import Report

    monkeypatch.setattr(cli, "check_package_doi", lambda *_args, **_kwargs: Report())
    assert deposit(project, "zenodo", "release", "--stage") == 0, capsys.readouterr()
    assert "ro-crate-preview.html" in hosts.hosts.files
    capsys.readouterr()
    asked = typed(monkeypatch, REAL)
    assert deposit(project, "zenodo", "release", "--publish") == 1
    assert "Ada Example has not approved" in capsys.readouterr().err
    assert not asked and not hosts.hosts.published
    # Approved now, the release staged says otherwise in its VERIFICATION.json: it is not the
    # bundle staged, until it is staged again.
    for author in ("Ada Example", "Blaise Sample"):
        assert main(["approve", str(project), "--as", author]) == 0
    assert deposit(project, "zenodo", "release", "--publish") == 1
    assert "not the one staged" in capsys.readouterr().err
    assert deposit(project, "zenodo", "release", "--stage") == 0
    assert deposit(project, "zenodo", "release", "--publish") == 0
    assert hosts.hosts.published and len(asked) == 1


# ------------------------------------------------------------------ OSF


def test_osf_stages_a_private_project_and_refuses_a_doi_and_publishing(project: Path, hosts,
                                                                       capsys) -> None:  # fmt: skip
    root = unfrozen(project)
    assert deposit(root, "osf", "preregistration", "--reserve-doi") == 2
    assert "mints a DOI only for a project or a registration that is public" in \
        capsys.readouterr().err  # fmt: skip
    assert deposit(root, "osf", "preregistration", "--publish") == 2
    assert "done on OSF's own page" in capsys.readouterr().err
    assert hosts.seen == []
    assert deposit(root, "osf", "preregistration", "--stage") == 0
    method, path, _headers, body = hosts.seen[0]
    assert (method, path) == ("POST", "/v2/nodes/")
    assert json.loads(body)["data"]["attributes"]["public"] is False
    assert "README.md" in hosts.hosts.files
    held = receipt(project, "osf-preregistration")
    assert held["id"] == "ab1cd" and held["doi"] is None and held["staged_on"]
    # Sent once, it is not sent again by the tool.
    assert deposit(root, "osf", "preregistration", "--stage") == 1
    nowhere_but_the_header(project, hosts, capsys.readouterr().err)


def test_osf_holding_other_bytes_stops_the_staging(project: Path, hosts, capsys) -> None:
    hosts.hosts.corrupt = "README.md"
    assert deposit(unfrozen(project), "osf", "preregistration", "--stage") == 1
    assert "README.md as other bytes" in capsys.readouterr().err
    assert "staged_on" not in receipt(project, "osf-preregistration")


# ------------------------------------------------------------------ what is refused first


@pytest.mark.parametrize(
    ("target", "bundle", "options", "said"),
    [
        ("arxiv", "preprint", ("--stage",), "takes nothing sent by the tool"),
        ("gh-pages", "release", ("--stage",), "takes nothing sent by the tool"),
        ("zenodo", "release", ("--stage", "--dry-run"), "--dry-run sends nothing"),
        ("zenodo", "release", ("--stage", "--publish"), "run on its own"),
    ],
)
def test_what_cannot_be_sent_is_refused_before_anything_is(
    project: Path, hosts, capsys, target: str, bundle: str, options: tuple, said: str
) -> None:
    assert deposit(project, target, bundle, *options) == 2
    assert said in capsys.readouterr().err
    assert hosts.seen == []


def test_a_token_not_in_the_environment_is_named_and_nothing_sent(project: Path, hosts, capsys,
                                                                  monkeypatch) -> None:  # fmt: skip
    monkeypatch.delenv("ZENODO_SANDBOX_TOKEN")
    assert deposit(project, "zenodo-sandbox", "release", "--reserve-doi") == 2
    assert "ZENODO_SANDBOX_TOKEN is not set" in capsys.readouterr().err
    assert hosts.seen == []


# ------------------------------------------------------------------ the transport


def _client(transport) -> Client:
    return Client("Zenodo", ("https://zenodo.org",), TOKEN, "ZENODO_TOKEN", transport)


def test_a_host_that_does_not_answer_is_said_in_our_words() -> None:
    def silent(_request: Request, _timeout: float) -> Response:
        raise NoAnswer("no connection to zenodo.org")

    with pytest.raises(RemoteError) as raised:
        _client(silent).call("GET", "https://zenodo.org/api/deposit/depositions/1")
    assert str(raised.value) == "Zenodo: no connection to zenodo.org"


@pytest.mark.parametrize(
    ("status", "body", "said"),
    [
        (401, b'{"message": "token zt-0123456789abcdefSECRETtoken is not valid"}',
         "refused the token in ZENODO_TOKEN (HTTP 401)"),
        (400, b'{"message": "bad token zt-0123456789abcdefSECRETtoken given"}', "[key]"),
        (400, b'{"message": "bad token ...SECRETtok"}', "[key]"),
        (302, b"", "redirect (HTTP 302), which is not followed"),
        (200, b"not json", "not with JSON"),
    ],
)
def test_what_a_host_says_is_said_without_the_token(status: int, body: bytes, said: str) -> None:
    def answer(_request: Request, _timeout: float) -> Response:
        return Response(status, {"Location": "https://elsewhere.example/"}, body)

    with pytest.raises(RemoteError) as raised:
        _client(answer).call("GET", "https://zenodo.org/api/deposit/depositions/1")
    message = str(raised.value)
    assert said in message
    assert TOKEN not in message and "SECRET" not in message


def test_a_link_to_another_host_is_not_followed_and_the_token_not_sent() -> None:
    sent: list[Request] = []

    def answer(request: Request, _timeout: float) -> Response:
        sent.append(request)
        return Response(201, {}, b"{}")

    api = _client(answer)
    with pytest.raises(RemoteError) as raised:
        zenodo.upload(api, {"bucket": "https://elsewhere.example/files/b"}, [("a.txt", b"a")])
    assert "not its own" in str(raised.value) and sent == []
    with pytest.raises(RemoteError):
        api.call("GET", "http://zenodo.org/api")  # plain http to a host on the network
    assert sent == []


def test_a_redirect_from_a_real_server_is_not_followed(hosts) -> None:
    hosts.hosts.override = (302, b"", {"Location": "http://127.0.0.2:1/elsewhere"})
    api = Client("Zenodo", (hosts.hosts.url,), TOKEN, "ZENODO_TOKEN", default_transport, 5)
    with pytest.raises(RemoteError) as raised:
        api.call("POST", f"{hosts.hosts.url}/api/deposit/depositions", document={})
    assert "not followed" in str(raised.value)
    assert len(hosts.seen) == 1


def test_a_server_that_is_not_there_is_no_answer() -> None:
    import socket

    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    with pytest.raises(NoAnswer) as raised:
        default_transport(Request("GET", f"http://127.0.0.1:{port}/x"), 2)
    # Refused at once, or, on Windows, after the attempts to connect run out.
    assert str(raised.value) in {"no connection to 127.0.0.1", "no answer within 2 s"}
    with pytest.raises(NoAnswer):
        default_transport(Request("GET", "http://zenodo.org/api"), 2)


def test_the_receipt_and_history_are_what_was_answered(tmp_path: Path) -> None:
    from manuscript_guard.contracts.project import Project

    project = Project(tmp_path, {}, None)
    made = {"target": "zenodo", "bundle": "release", "host": "https://zenodo.org", "id": 7,
            "doi": REAL}  # fmt: skip
    receipts.write(project, made)
    receipts.append_history(project, made, "reserved", "2026-10-28T00:00:00Z")
    receipts.append_history(project, made, "staged", "2026-10-28T00:01:00Z")
    assert receipts.read(project, "zenodo", "release")["doi"] == REAL
    history = yaml.safe_load((tmp_path / receipts.HISTORY).read_text("utf-8"))
    assert [entry["action"] for entry in history] == ["reserved", "staged"]
    (tmp_path / "deposit" / "receipts" / "zenodo-release.yaml").write_text("target: osf\n",
                                                                           "utf-8")  # fmt: skip
    with pytest.raises(receipts.ReceiptError):
        receipts.read(project, "zenodo", "release")


# ------------------------------------------------------------------ package.doi in paper.yaml


@pytest.mark.parametrize(
    ("text", "written"),
    [
        ("title: X\n# a note\n", "title: X\n# a note\npackage:\n  doi: '10.5281/zenodo.9'\n"),
        ("title: X\npackage:\n  licence: MIT  # mine\nstage: drafting\n",
         "title: X\npackage:\n  doi: '10.5281/zenodo.9'\n  licence: MIT  # mine\n"
         "stage: drafting\n"),
        ("package:\n    doi: 10.5281/zenodo.1  # reserved\n",
         "package:\n    doi: '10.5281/zenodo.9'  # reserved\n"),
        ("title: X\r\npackage:\r\n  licence: MIT\r\n",
         "title: X\r\npackage:\r\n  doi: '10.5281/zenodo.9'\r\n  licence: MIT\r\n"),
    ],
)
def test_the_doi_is_written_under_package_and_nothing_else_changes(
    text: str, written: str
) -> None:
    from manuscript_guard.paper_edit import edit_package_doi

    assert edit_package_doi(text, "10.5281/zenodo.9").text == written


@pytest.mark.parametrize(
    ("text", "doi", "said"),
    [
        ("package: {licence: MIT}\n", "10.5281/zenodo.9", "not written one key to a line"),
        ("title: X\n", "10.5072/zenodo.9", "a test DOI"),
        ("title: X\n", "10.5072/ZENODO.9", "a test DOI"),
        ("title: X\n", "zenodo.9", "cannot be"),
        ("package: MIT\n", "10.5281/zenodo.9", "not a mapping"),
    ],
)
def test_a_doi_that_cannot_be_written_safely_is_refused(text: str, doi: str, said: str) -> None:
    from manuscript_guard.paper_edit import Refused, edit_package_doi

    with pytest.raises(Refused) as raised:
        edit_package_doi(text, doi)
    assert said in str(raised.value)


# ------------------------------------------------------------------ round 1 of #467


def _answering(document: object, status: int = 201):
    sent: list[Request] = []

    def answer(request: Request, _timeout: float) -> Response:
        sent.append(request)
        return Response(status, {}, json.dumps(document).encode())

    return _client(answer), sent


def _clean(message: str) -> None:
    assert TOKEN not in message and "SECRET" not in message, message
    assert chr(27) not in message, message


def _deposition(**links: str) -> dict:
    return {"id": 1, "metadata": {"prereserve_doi": {"doi": links.pop("doi", REAL)}},
            "links": {"bucket": "https://zenodo.org/api/files/b",
                      "html": "https://zenodo.org/deposit/1", **links}}  # fmt: skip


@pytest.mark.parametrize(
    "planted",
    [
        {"doi": f"10.5281/{TOKEN}"},
        {"bucket": f"https://zenodo.org/api/files/{TOKEN}"},
        {"html": f"https://zenodo.org/deposit/1?t={TOKEN}"},
        {"html": "https://zenodo.org/deposit/1" + chr(27) + "[2J"},
    ],
)
def test_a_doi_or_link_holding_the_token_is_refused_before_it_is_recorded(planted) -> None:
    """Round 1 of #467 (blocking): a DOI or a link a host returns is recorded and printed
    whole, so one that holds the token, or a character a terminal acts on, is refused."""
    api, _sent = _answering(_deposition(**planted))
    with pytest.raises(RemoteError) as raised:
        zenodo.reserve(api, "zenodo")
    _clean(str(raised.value))
    assert "recorded nowhere" in str(raised.value)


def test_every_string_a_host_returns_is_said_without_the_token() -> None:
    """Round 1 of #467 (blocking): a checksum, a file name, a DOI, OSF's md5 and the host of
    a link, each with the token planted, reach a message without it."""
    api, _sent = _answering({"checksum": f"md5:{TOKEN}" + chr(27) + "[31m"})
    with pytest.raises(RemoteError) as raised:
        zenodo.upload(api, {"bucket": "https://zenodo.org/api/files/b"}, [("a.txt", b"a")])
    _clean(str(raised.value))
    api, _sent = _answering({})
    with pytest.raises(RemoteError) as raised:
        zenodo.compare(api, {TOKEN: "0" * 32}, {})
    _clean(str(raised.value))
    api, _sent = _answering({"metadata": {"prereserve_doi": {"doi": f"10.1/{TOKEN}"}}}, 200)
    with pytest.raises(RemoteError) as raised:
        zenodo.describe(api, "zenodo", {"id": 1, "doi": REAL}, {})
    _clean(str(raised.value))
    _fields, problem = zenodo.published(api, {"id": 1, "doi": REAL}, {"doi": f"10.1/{TOKEN}"})
    _clean(str(problem))
    hashed = _answering({"data": {"attributes": {"extra": {"hashes": {"md5": TOKEN}}}}})[0]
    osf_api = Client("OSF", ("https://files.osf.io",), TOKEN, "OSF_TOKEN", hashed.transport)
    with pytest.raises(RemoteError) as raised:
        osf.upload(osf_api, "ab1cd", [("a.txt", b"a")])
    _clean(str(raised.value))
    # A host name is written in small letters, so the token planted in one is too.
    small = Client("Zenodo", ("https://zenodo.org",), "zt-0123456789abcdefsecret",
                   "ZENODO_TOKEN", api.transport)  # fmt: skip
    with pytest.raises(RemoteError) as raised:
        small.call("GET", f"https://{small.token}.example/x")
    assert "secret" not in str(raised.value) and "0123456789" not in str(raised.value)


def test_an_unexpected_answer_to_a_publication_is_recorded_and_never_sent_again(
    project: Path, hosts, capsys, monkeypatch
) -> None:
    """Round 1 of #467: once the publication is sent, it is recorded with the host's answer
    before anything can raise, and a run again does not send it twice."""
    _staged(project, hosts)
    hosts.hosts.publish_answer = {}
    typed(monkeypatch, SANDBOX)
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    assert "the publication was sent, and the host answered" in capsys.readouterr().err
    held = receipt(project, "zenodo-sandbox-preregistration")
    assert held["publish_sent_on"] and "published_on" not in held
    assert "the DOI None" in held["publish_answer"]
    history = yaml.safe_load((project / "deposit" / "history.yaml").read_text("utf-8"))
    assert history[-1]["action"] == "publish_sent"
    count = len(hosts.seen)
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    assert "It is not sent again" in capsys.readouterr().err
    assert len(hosts.seen) == count


def test_a_publication_the_host_refuses_is_recorded_too(
    project: Path, hosts, capsys, monkeypatch
) -> None:
    _staged(project, hosts)
    typed(monkeypatch, SANDBOX)
    original = hosts.hosts.answer

    def refusing(method: str, path: str, body: bytes):
        if path.endswith("/actions/publish"):
            return 500, {"message": "the server tripped"}, {}
        return original(method, path, body)

    hosts.hosts.answer = refusing
    assert deposit(project, "zenodo-sandbox", "preregistration", "--publish") == 1
    held = receipt(project, "zenodo-sandbox-preregistration")
    assert "HTTP 500: the server tripped" in held["publish_answer"]
    assert held["publish_sent_on"] and "published_on" not in held


@pytest.mark.parametrize("written", [None, "{not json", "[1, 2]"])
def test_a_zenodo_json_that_cannot_describe_the_draft_stops_before_anything_is_sent(
    project: Path, hosts, capsys, monkeypatch, written: str | None
) -> None:
    """Round 1 of #467: `.zenodo.json` is read before any file is sent, and refused (exit 2)
    where it is missing, not JSON, or not an object."""
    from manuscript_guard.deposit import command as local

    real = local.written

    def spoiled(project_, made, every):
        staged = real(project_, made, every)
        path = staged.directory / ".zenodo.json"
        if written is None:
            path.unlink()
        else:
            path.write_text(written, encoding="utf-8")
        return staged

    monkeypatch.setattr(local, "written", spoiled)
    root = unfrozen(project)
    assert deposit(root, "zenodo-sandbox", "preregistration", "--reserve-doi") == 0
    assert deposit(root, "zenodo-sandbox", "preregistration", "--stage") == 2
    assert ".zenodo.json" in capsys.readouterr().err
    assert not [path for method, path, _h, _b in hosts.seen if method == "PUT"]


def test_an_osf_project_not_answered_private_is_recorded_and_gets_nothing(
    project: Path, hosts, capsys
) -> None:
    """Round 1 of #467: the project's id is recorded before its answer is judged, so a run
    again makes no second project, and one not answered private gets nothing, ever."""
    hosts.hosts.osf_public = True
    root = unfrozen(project)
    assert deposit(root, "osf", "preregistration", "--stage") == 1
    assert "did not answer that it is private" in capsys.readouterr().err
    held = receipt(project, "osf-preregistration")
    assert held["id"] == "ab1cd" and held["private"] is False and "staged_on" not in held
    assert hosts.hosts.files == {}
    assert deposit(root, "osf", "preregistration", "--stage") == 1
    assert "did not answer that it is private" in capsys.readouterr().err
    assert [method for method, *_rest in hosts.seen] == ["POST"]
