"""`communicate approve` and `communicate publish`: an approval bound to the text, and a post
sent only when the text is checked, approved and past the embargo.

Every request goes to a server on a loopback port that answers as Bluesky and Mastodon do,
or to a table; none reaches a service. The suite sets MANUSCRIPT_GUARD_NO_NETWORK, so the
default transport sends nothing, and each loopback test gives the one that sends.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.communicate import approval, lifecycle, publish
from manuscript_guard.communicate import brief as brief_module
from manuscript_guard.communicate.adapters import bluesky, mastodon, net, orcid
from manuscript_guard.contracts import load_project
from manuscript_guard.deposit.remote import http
from manuscript_guard.deposit.remote.http import NoAnswer, Request, Response
from manuscript_guard.emit import write_digest

PASSWORD = "app-pass-SECRET-7f3k"
HANDLE = "ada.example.invalid"
ACCESS = "access-jwt-SECRET-q9w8e7"
REFRESH = "refresh-jwt-SECRET-z1x2c3"
TOKEN = "mastodon-token-SECRET-m4n5b6"
DID = "did:plc:examplexyz"
LIMITATION = "Several limitations follow from the design."
CLEAN = ("The reporting odds ratio was {{results.ror.point}} (95% CI {{results.ror.ci_low}} "
         "to {{results.ror.ci_high}}) [](#brief:findings.2).")  # fmt: skip
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
#: A thread of two posts: the finding, then a link after a word with an accent and a
#: Japanese one, so that the facet's bytes are not its characters.
THREAD = f"{CLEAN}\n\n---\n\nRésumé, 要旨: https://example.org/paper.\n"
SECRETS = (PASSWORD, ACCESS, REFRESH, TOKEN)


def append(root: Path, text: str) -> None:
    with (root / "paper.yaml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _primary_and_limitation(document: dict) -> None:
    for finding in document["findings"]:
        finding["primary"] = finding["id"] == "findings.2"
    document["limitations"] = [{"id": "limitations.1", "text": LIMITATION,
                                "from": {"file": "manuscript/main.md", "quote": LIMITATION}}]


@pytest.fixture
def ready(project: Path) -> Path:
    append(project, "\ncommunication:\n  enabled: true\n")
    assert main(["communicate", "brief", str(project)]) == 0
    path = project / "communication" / "brief.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    _primary_and_limitation(document)
    path.write_bytes(brief_module.dump(document).encode("utf-8"))
    return project


def text(root: Path, channel: str, body: str = THREAD, *, image: bool = True,
         alt: str = "A forest plot of the reporting odds ratio.") -> Path:  # fmt: skip
    front = {"channel": channel}
    if image:
        (root / "communication" / "figure.png").write_bytes(PNG)
        front |= {"attachments": ["figure.png"], "alt": {"figure.png": alt}}
    path = root / "communication" / f"{channel}.md"
    path.write_text("---\n" + yaml.safe_dump(front, allow_unicode=True) + "---\n" + body,
                    encoding="utf-8", newline="\n")  # fmt: skip
    return path


def run(*words: str) -> int:
    return main(["communicate", *words])


def approve(root: Path, channel: str) -> int:
    return run("approve", channel, str(root), "--as", "Ada Example")


def nowhere(root: Path, *said: str) -> None:
    """No secret, whole, is in any file under communication/ or anything printed."""
    written = [path.read_text("utf-8") for path in (root / "communication").rglob("*")
               if path.is_file() and path.suffix in (".yaml", ".json", ".html", ".md")]  # fmt: skip
    for one in (*written, *said):
        for secret in (*SECRETS, HANDLE):
            assert secret not in one, (secret, one[:300])


# --------------------------------------------------------------------------- the adapters


def test_a_link_is_marked_at_its_utf8_bytes_and_ends_before_its_stop() -> None:
    said = "Café ☕ 要旨 (see https://example.org/a_(b)) and https://doi.org/10.1/x."
    marked = bluesky.facets(said)
    data = said.encode("utf-8")
    links = [data[one["index"]["byteStart"]:one["index"]["byteEnd"]].decode("utf-8")
             for one in marked]  # fmt: skip
    assert links == ["https://example.org/a_(b)", "https://doi.org/10.1/x"]
    assert [one["features"][0]["uri"] for one in marked] == links
    assert marked[0]["index"]["byteStart"] != said.index("https")  # bytes, not characters
    assert bluesky.facets("no link here, http:// alone") == []


def test_a_record_key_is_thirteen_letters_that_sort_as_their_moments() -> None:
    first = bluesky.tid(datetime(2026, 10, 29, 12, tzinfo=timezone.utc))
    later = bluesky.tid(datetime(2026, 10, 29, 12, 0, 1, tzinfo=timezone.utc))
    assert len(first) == 13 and first < later
    assert set(first) <= set("234567abcdefghijklmnopqrstuvwxyz")
    assert bluesky.stamp(datetime(2026, 10, 29, 12, 0, 0, 5000, tzinfo=timezone.utc)) == \
        "2026-10-29T12:00:00.005Z"


def test_record_keys_rise_within_a_run_though_the_clock_stands_still() -> None:
    """Windows' clock can answer the same moment twice: two posts never share a key."""
    moment = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    first, made = bluesky.next_tid(moment, -1)
    second, later = bluesky.next_tid(moment, made)
    assert first == bluesky.tid(moment) and first < second and later == made + 1
    assert bluesky.micros_of(first) == made and bluesky.micros_of(second) == later
    assert bluesky.micros_of("not-a-tid") is None and bluesky.micros_of(None) is None
    # A TID's first bit is naught: its first letter is one of the first sixteen.
    assert first[0] in "234567abcdefghij" and len(second) == 13


@pytest.mark.parametrize("said", ["nan", "NaN", "inf", "-inf"])
def test_a_retry_after_that_is_no_number_of_seconds_is_read_as_none(said: str) -> None:
    answers = [Response(429, {"Retry-After": said}, b""), Response(200, {}, b'{"ok": 1}')]
    waited: list[float] = []
    api = net.Api("S", "https://s.example", "S_TOKEN", transport=lambda _r, _t: answers.pop(0),
                  sleep=waited.append)  # fmt: skip
    assert api.call("GET", "/x") == {"ok": 1} and waited == [net.RETRY_AFTER_DEFAULT]


def test_a_handle_is_public_and_an_e_mail_given_for_it_is_kept_secret(monkeypatch) -> None:
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("BLUESKY_HANDLE", "alice.example.com")
    assert bluesky.client().secrets == (PASSWORD,)
    monkeypatch.setenv("BLUESKY_HANDLE", "ada@example.org")
    assert set(bluesky.client().secrets) == {PASSWORD, "ada@example.org"}


def test_a_thread_replies_to_its_root_and_to_the_post_before() -> None:
    done = [{"uri": "at://a/1", "cid": "c1"}, {"uri": "at://a/2", "cid": "c2"}]
    assert bluesky.reply_to([]) is None
    assert bluesky.reply_to(done) == {"root": {"uri": "at://a/1", "cid": "c1"},
                                      "parent": {"uri": "at://a/2", "cid": "c2"}}
    post = bluesky.record("x https://e.org", "t", langs=["en"], reply=bluesky.reply_to(done))
    assert post["$type"] == "app.bsky.feed.post" and post["reply"]["parent"]["cid"] == "c2"
    assert post["facets"][0]["index"] == {"byteStart": 2, "byteEnd": 15}


def test_a_mastodon_post_is_keyed_by_its_text_its_files_and_its_place() -> None:
    key = mastodon.idempotency_key
    assert key("a" * 64, "b" * 64, 1) == key("a" * 64, "b" * 64, 1)
    assert key("a" * 64, "b" * 64, 1) != key("a" * 64, "b" * 64, 2)
    assert key("a" * 64, "b" * 64, 1) != key("a" * 64, "c" * 64, 1)  # a corrected image
    assert key("a" * 64, "b" * 64, 1) != key("a" * 64, "b" * 64, 1, attempt=1)
    body, kind = mastodon.form(net.Image("figure.png", PNG, "image/png", "A plot."))
    assert kind.startswith("multipart/form-data; boundary=mg-")
    assert b'name="description"\r\n\r\nA plot.' in body and b'filename="figure.png"' in body
    assert mastodon.status("hi", language="en", in_reply_to_id="7") == {
        "status": "hi", "visibility": "public", "language": "en", "in_reply_to_id": "7"}


def test_the_default_transport_sends_nothing_while_the_suite_runs() -> None:
    with pytest.raises(NoAnswer) as raised:
        net.default_transport(Request("GET", "http://127.0.0.1:9/"), 1)
    assert raised.value.reached is False and net.NO_NETWORK in str(raised.value)


def test_a_service_that_asks_for_time_is_waited_for_once() -> None:
    answers = [Response(429, {"Retry-After": "2"}, b""), Response(200, {}, b'{"ok": 1}')]
    waited: list[float] = []
    api = net.Api("S", "https://s.example", "S_TOKEN", ("tok-SECRET-1234",),
                  transport=lambda _r, _t: answers.pop(0), sleep=waited.append)  # fmt: skip
    assert api.call("GET", "/x") == {"ok": 1} and waited == [2.0]
    again = net.Api("S", "https://s.example", "S_TOKEN", transport=lambda _r, _t: Response(
        429, {"Retry-After": "1"}, b""), sleep=lambda _s: None)  # fmt: skip
    with pytest.raises(net.RemoteError, match="nothing was done") as raised:
        again.call("GET", "/x")
    assert raised.value.reached is False
    long = net.Api("S", "https://s.example", "S_TOKEN", transport=lambda _r, _t: Response(
        429, {"Retry-After": "3600"}, b""))  # fmt: skip
    with pytest.raises(net.RemoteError, match="3600 seconds"):
        long.call("GET", "/x")


def test_a_refusal_is_said_without_the_secret_the_service_quoted() -> None:
    body = json.dumps({"message": f"bad password {PASSWORD}"}).encode()
    api = net.Api("S", "https://s.example", "S_TOKEN", (PASSWORD,),
                  transport=lambda _r, _t: Response(400, {}, body))  # fmt: skip
    with pytest.raises(net.Answered) as raised:
        api.call("POST", "/x")
    assert raised.value.status == 400 and PASSWORD not in str(raised.value)
    assert "SECRET" not in str(raised.value)
    refused = net.Api("S", "https://s.example", "S_TOKEN", (PASSWORD,),
                      transport=lambda _r, _t: Response(401, {}, body))  # fmt: skip
    with pytest.raises(net.RemoteError, match="refused the credentials in S_TOKEN") as raised:
        refused.call("POST", "/x")
    assert PASSWORD not in str(raised.value)
    with pytest.raises(net.RemoteError, match="must be https"):
        net.Api("S", "http://s.example", "S_TOKEN")


# ---------------------------------------------------------------------------- approving


def test_an_approval_records_who_when_and_the_digests_of_the_text(ready: Path) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    path = ready / "communication" / "approvals" / "bluesky-thread.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert record["by"] == "Ada Example" and record["check_clean"] is True
    assert {"on", "text_sha256", "attachments_sha256"} <= set(record)
    project, _ = load_project(ready)
    prepared = approval.prepare(project, "bluesky-thread")
    assert approval.current_approval(project, prepared)["by"] == "Ada Example"
    # The post as it is sent: the values printed, the anchor gone, no space before a stop.
    assert prepared.posts[0].startswith("The reporting odds ratio was ")
    assert "[](" not in prepared.posts[0] and prepared.posts[0].endswith(").")
    assert prepared.posts[1] == "Résumé, 要旨: https://example.org/paper."


def test_an_approval_is_refused_to_somebody_who_is_no_author_and_without_as(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert run("approve", "bluesky-thread", str(ready), "--as", "Nobody Here") == 2
    assert "not an author" in capsys.readouterr().err
    assert run("approve", "bluesky-thread", str(ready)) == 2
    assert "takes --as" in capsys.readouterr().err
    assert run("check", str(ready), "--post") == 2
    assert not (ready / "communication" / "approvals").exists()


@pytest.mark.parametrize(("body", "alt", "said"), [
    (THREAD.replace("{{results.ror.point}}", "3.84"), "A plot.", "comm-number-unbound"),
    (THREAD, "A plot of 3.84.", "comm-number-unbound"),
    (THREAD + "\n<!-- write: a closing line -->\n", "A plot.", "a slot is still to write"),
    (THREAD, "", "has no alternative text"),
])  # fmt: skip
def test_a_text_the_check_fails_or_that_cannot_be_posted_is_not_approved(
    ready: Path, body: str, alt: str, said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread", body, alt=alt)
    assert approve(ready, "bluesky-thread") == 2
    assert said in capsys.readouterr().err
    assert not (ready / "communication" / "approvals").exists()


@pytest.mark.parametrize(("files", "said"), [
    ({"figure.bmp": b"BM" + b"\x00" * 30}, "only a PNG, JPEG, WebP or GIF"),
    ({f"figure-{n}.png": PNG for n in range(5)}, "5 images, and a post carries 4 at most"),
    ({"figure.png": PNG + b"\x00" * 1_000_000}, "Bluesky takes an image of 1000000 at most"),
])  # fmt: skip
def test_an_image_a_post_cannot_carry_is_refused(
    ready: Path, files: dict, said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = ready / "communication"
    for name, data in files.items():
        (root / name).write_bytes(data)
    front = {"channel": "bluesky-thread", "attachments": list(files),
             "alt": {name: "A forest plot." for name in files}}  # fmt: skip
    (root / "bluesky-thread.md").write_text("---\n" + yaml.safe_dump(front) + "---\n" + THREAD,
                                            encoding="utf-8", newline="\n")  # fmt: skip
    assert approve(ready, "bluesky-thread") == 2
    assert said in capsys.readouterr().err
    assert not (root / "approvals").exists()


def _approved(root: Path) -> Path:
    text(root, "bluesky-thread")
    assert approve(root, "bluesky-thread") == 0
    return root / "communication" / "approvals" / "bluesky-thread.yaml"


def test_an_approval_by_an_author_no_longer_listed_is_refused(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _approved(ready)
    authors = ready / "authors.yaml"
    authors.write_text(authors.read_text("utf-8").replace("given: Ada", "given: Adele", 1),
                       encoding="utf-8")  # fmt: skip
    capsys.readouterr()
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "whom authors.yaml does not list" in capsys.readouterr().err


@pytest.mark.parametrize("written", [
    "schema: [\n",
    "schema: manuscript-guard/communication-approval/0\nby: Ada Example\n",
    "- a list\n",
])  # fmt: skip
def test_an_approval_that_cannot_be_read_is_refused(
    ready: Path, written: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _approved(ready).write_text(written, encoding="utf-8")
    capsys.readouterr()
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "is no approval this can read" in capsys.readouterr().err


def test_an_approval_that_does_not_say_the_check_passed_is_refused(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _approved(ready)
    path.write_text(path.read_text("utf-8").replace("check_clean: true", "check_clean: false"),
                    encoding="utf-8")  # fmt: skip
    capsys.readouterr()
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "does not say the check passed" in capsys.readouterr().err


def test_resume_without_post_and_as_on_a_post_are_refused(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert run("publish", "bluesky-thread", str(ready), "--resume") == 2
    assert "--resume goes with --post" in capsys.readouterr().err
    assert run("publish", "bluesky-thread", str(ready), "--as", "Example") == 2
    assert "--as goes with `communicate approve`" in capsys.readouterr().err
    assert not (ready / "communication" / "outbox").exists()


def test_a_text_is_approved_while_the_embargo_holds(ready: Path, monkeypatch) -> None:
    append(ready, "publication:\n  embargo_until: 2026-12-01T00:01Z\n")
    monkeypatch.setattr(lifecycle, "now", lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0


def _ror_display(root: Path, shown: str) -> None:
    fragment = next((root / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"] |= {"value": float(shown), "display": shown}
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


@pytest.mark.parametrize("edit", ["text", "attachment", "alt", "bound value"])
def test_an_edit_of_what_was_approved_makes_the_approval_stale(
    ready: Path, edit: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    if edit == "text":
        path.write_text(path.read_text("utf-8").replace("Résumé", "Summary"), encoding="utf-8")
    elif edit == "attachment":
        (ready / "communication" / "figure.png").write_bytes(PNG + b"\x01")
    elif edit == "alt":
        text(ready, "bluesky-thread", alt="Another description of the plot.")
    else:
        _ror_display(ready, "3.85")
    capsys.readouterr()
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "the approval is stale" in capsys.readouterr().err


# ------------------------------------------------------------------- without --post


def test_without_post_the_requests_are_written_and_nothing_is_sent(
    ready: Path, services, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    text(ready, "mastodon-thread")
    for channel in ("bluesky-thread", "mastodon-thread"):
        assert run("publish", channel, str(ready)) == 0
    said = capsys.readouterr().out
    assert services.seen == []
    assert "nothing was sent" in said and "--post would be refused: nobody has approved" in said
    sky = json.loads((ready / "communication" / "outbox" / "bluesky-thread.json")
                     .read_text("utf-8"))  # fmt: skip
    urls = [one["url"].rsplit("/", 1)[1] for one in sky["requests"]]
    assert urls == ["com.atproto.server.createSession", "com.atproto.repo.uploadBlob",
                    "com.atproto.repo.createRecord", "com.atproto.repo.createRecord"]
    second = sky["requests"][3]["body"]["record"]
    assert second["reply"]["root"]["uri"] == "<post 1's uri>"
    assert second["facets"][0]["features"][0]["uri"] == "https://example.org/paper"
    assert sky["requests"][2]["body"]["record"]["embed"]["images"][0]["alt"].startswith("A forest")
    toot = json.loads((ready / "communication" / "outbox" / "mastodon-thread.json")
                      .read_text("utf-8"))  # fmt: skip
    assert toot["requests"][0]["body"]["description"].startswith("A forest")
    assert toot["requests"][2]["body"]["in_reply_to_id"] == "<post 1's id>"
    assert (ready / "communication" / "preview.html").is_file()
    nowhere(ready, said)
    before = (ready / "communication" / "outbox" / "bluesky-thread.json").read_bytes()
    assert run("publish", "bluesky-thread", str(ready)) == 0
    assert (ready / "communication" / "outbox" / "bluesky-thread.json").read_bytes() == before


@pytest.mark.parametrize("channel", ["pitch", "press-release", "newsletter"])
def test_an_e_mail_is_a_draft_and_nothing_sends_it(
    ready: Path, channel: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (ready / "communication" / f"{channel}.md").write_text(f"---\nchannel: {channel}\n---\nHi.\n",
                                                          encoding="utf-8")  # fmt: skip
    assert run("publish", channel, str(ready), "--post") == 2
    assert "nothing sends an e-mail" in capsys.readouterr().err


def test_linkedin_is_printed_to_paste_and_researchgate_is_by_hand(
    ready: Path, services, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "linkedin", CLEAN + "\n", image=False)
    assert run("publish", "linkedin", str(ready), "--post") == 0
    said = capsys.readouterr().out
    assert "https://www.linkedin.com/feed/" in said and "Nothing was posted" in said
    assert "The reporting odds ratio was " in said and "{{" not in said
    assert run("publish", "researchgate", str(ready)) == 0
    assert "by hand" in capsys.readouterr().out
    assert not (ready / "communication" / "published").exists()
    # With no text, there is nothing the steps were taken with.
    assert run("publish", "researchgate", str(ready), "--done", "--as", "Example") == 2
    assert "researchgate.md does not exist" in capsys.readouterr().err
    assert not (ready / "communication" / "published").exists()
    text(ready, "researchgate", CLEAN + "\n", image=False)
    assert run("publish", "researchgate", str(ready), "--done", "--as", "Example") == 0
    record = yaml.safe_load((ready / "communication" / "published" / "researchgate.yaml")
                            .read_text("utf-8"))  # fmt: skip
    assert record["publications"][0]["by"] == "Ada Example"
    assert services.seen == []
    assert run("publish", "bluesky-thread", str(ready), "--done") == 2


# ------------------------------------------------------------------ the loopback services


class Services:
    """Bluesky's and Mastodon's answers, kept with every request."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.seen: list[tuple[str, str, dict, bytes]] = []
        self.records: dict[str, dict] = {}
        self.statuses: dict[str, dict] = {}
        self.media_asked = 0
        #: The number of the createRecord or status request to fail, and how: "500" (not
        #: made), "lost" (made, and its answer lost), "401".
        self.fail_at: int | None = None
        self.how = "500"
        self.throttle = 0
        self.creates = 0
        self.works: list[str] = []
        self.did, self.handle = DID, HANDLE
        #: What getRecord answers for a key it does not hold, and whether createRecord refuses
        #: every record (a 400), as a server does a record it will not take.
        self.not_found: tuple[int, dict] = (400, {"error": "RecordNotFound",
                                                  "message": "Could not locate record"})
        self.refuse_create = False
        #: Mastodon: each status by its id, and the id each key it keeps was answered with.
        self.keys: dict[str, str] = {}
        self.account = "9"

    def answer(self, method: str, path: str, headers: dict, body: bytes):
        parts = urlsplit(path)
        if self.throttle:
            self.throttle -= 1
            return 429, {"error": "RateLimitExceeded"}, {"Retry-After": "0"}
        route = parts.path
        if route == "/xrpc/com.atproto.server.createSession":
            sent = json.loads(body)
            if sent != {"identifier": self.handle, "password": PASSWORD}:
                return 401, {"message": f"wrong {sent.get('password')}"}, {}
            return 200, {"accessJwt": ACCESS, "refreshJwt": REFRESH, "did": self.did,
                         "handle": self.handle}, {}  # fmt: skip
        if route.startswith("/xrpc/") and headers.get("Authorization") != f"Bearer {ACCESS}":
            return 401, {"message": "no"}, {}
        if route == "/xrpc/com.atproto.repo.uploadBlob":
            return 200, {"blob": {"$type": "blob", "ref": {"$link": "bafyimage"},
                                  "mimeType": headers.get("Content-Type"),
                                  "size": len(body)}}, {}  # fmt: skip
        if route == "/xrpc/com.atproto.repo.createRecord":
            return self._create(json.loads(body))
        if route == "/xrpc/com.atproto.repo.getRecord":
            rkey = parse_qs(parts.query)["rkey"][0]
            if rkey not in self.records:
                return self.not_found[0], self.not_found[1], {}
            return 200, self.records[rkey]["answer"], {}
        if route.startswith("/api/") and headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {"error": "The access token is invalid"}, {}
        if route == "/api/v2/media":
            return 202, {"id": "301", "url": None, "description": "kept"}, {}
        if route == "/api/v1/media/301":
            self.media_asked += 1
            return 200, {"id": "301", "url": f"{self.url}/media/301.png"}, {}
        if route == "/api/v1/statuses":
            return self._status(headers.get("Idempotency-Key", ""), json.loads(body))
        if route == "/api/v1/accounts/verify_credentials":
            return 200, {"id": self.account, "acct": "ada"}, {}
        if route.startswith("/api/v1/statuses/") and method == "GET":
            found = self.statuses.get(route.rsplit("/", 1)[1])
            return (200, found["answer"], {}) if found else (404, {"error": "Record not found"}, {})
        if route.startswith("/v3.0/"):
            ids = [{"external-id-type": "doi", "external-id-value": one} for one in self.works]
            return 200, {"group": [{"external-ids": {"external-id": ids}}]}, {}
        return 404, {"error": f"no route for {method} {route}"}, {}

    def _failing(self) -> tuple | None:
        self.creates += 1
        if self.fail_at != self.creates:
            return None
        if self.how == "401":
            return 401, {"message": "token expired"}, {}
        return 500, {"message": "Internal Server Error"}, {}

    def _create(self, sent: dict):
        rkey = sent["rkey"]
        if rkey in self.records or self.refuse_create:
            # A server holds one record under a key, and refuses a second.
            return 400, {"error": "InvalidRequest", "message": "Record already exists"}, {}
        answer = {"uri": f"at://{self.did}/app.bsky.feed.post/{rkey}", "cid": f"cid-{rkey}"}
        failing = self._failing()
        if failing is not None and self.how != "lost":
            return failing
        self.records[rkey] = {"sent": sent, "answer": answer}
        return failing or (200, answer, {})

    def _status(self, key: str, sent: dict):
        if key in self.keys:  # Mastodon answers a key it keeps with the status it made then
            return 200, self.statuses[self.keys[key]]["answer"], {}
        failing = self._failing()
        if failing is not None and self.how != "lost":
            return failing
        number = str(100 + len(self.statuses))
        answer = {"id": number, "url": f"{self.url}/@ada/{number}",
                  "account": {"id": self.account},
                  "in_reply_to_id": sent.get("in_reply_to_id"), "reblog": None,
                  "created_at": bluesky.stamp(datetime.now(timezone.utc))}  # fmt: skip
        self.statuses[number] = {"sent": sent, "answer": answer, "key": key}
        self.keys[key] = number
        return failing or (200, answer, {})

    def forget_keys(self) -> None:
        """What an hour does: Mastodon no longer keeps the keys; the statuses stay."""
        self.keys.clear()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _any(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = dict(self.headers.items())
        self.server.seen.append((self.command, self.path, headers, body))
        status, document, extra = self.server.services.answer(self.command, self.path, headers,
                                                              body)  # fmt: skip
        data = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    do_GET = do_POST = _any  # noqa: N815 - the names http.server looks for

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def services(monkeypatch):
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.seen = []
    httpd.services = Services(url)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        http.default_transport(Request("GET", url + "/probe"), 5)
    except NoAnswer as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    # The transport that sends, to this machine only: the default refuses in the suite.
    for module in (bluesky, mastodon, orcid):
        monkeypatch.setattr(module, "TRANSPORT", http.default_transport)
    monkeypatch.setattr(mastodon, "READY_WAIT", 0.0)
    monkeypatch.setattr(orcid, "API", url)
    httpd.services.seen = httpd.seen
    yield httpd.services
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def credentials(services, monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", HANDLE)
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", PASSWORD)
    monkeypatch.setenv("BLUESKY_SERVICE", services.url)
    monkeypatch.setenv("MASTODON_BASE_URL", services.url)
    monkeypatch.setenv("MASTODON_TOKEN", TOKEN)
    return services


def published(root: Path, channel: str) -> dict:
    return yaml.safe_load((root / "communication" / "published" / f"{channel}.yaml")
                          .read_text("utf-8"))  # fmt: skip


def only_where_they_belong(services: Services) -> None:
    """The app password in the session's body only, the tokens in a header only, and none
    in any URL."""
    for _method, path, headers, body in services.seen:
        for secret in SECRETS:
            assert secret not in path
        if path.endswith("createSession"):
            assert PASSWORD.encode() in body and "Authorization" not in headers
        else:
            held = ACCESS if path.startswith("/xrpc/") else TOKEN
            assert headers.get("Authorization") == f"Bearer {held}", path
            assert PASSWORD.encode() not in body and ACCESS.encode() not in body
            assert TOKEN.encode() not in body


# ------------------------------------------------------------------------ posting: Bluesky


def test_a_thread_is_posted_to_bluesky_each_post_a_reply_and_each_recorded(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    said = capsys.readouterr().out
    first, second = (one["sent"]["record"] for one in credentials.records.values())
    assert first["embed"]["images"][0] == {"alt": "A forest plot of the reporting odds ratio.",
                                           "image": {"$type": "blob",
                                                     "ref": {"$link": "bafyimage"},
                                                     "mimeType": "image/png", "size": len(PNG)}}
    assert "reply" not in first and first["langs"] == ["en"]
    root = next(iter(credentials.records.values()))["answer"]
    assert second["reply"] == {"root": root, "parent": root}
    data = second["text"].encode("utf-8")
    facet = second["facets"][0]["index"]
    assert data[facet["byteStart"]:facet["byteEnd"]] == b"https://example.org/paper"
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["complete"] is True and [one["index"] for one in record["posts"]] == [1, 2]
    assert record["posts"][0]["url"].startswith(f"{bluesky.APP}/profile/{DID}/post/")
    assert record["account"] == DID and "pending" not in record
    assert "posted 2 of 2" in said
    only_where_they_belong(credentials)
    nowhere(ready, said)


def test_the_same_text_is_not_posted_twice(ready: Path, credentials,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    made = len(credentials.records)
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "is not posted twice" in capsys.readouterr().err
    assert len(credentials.records) == made


def test_a_thread_that_stops_part_way_is_resumed_from_its_last_post(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at = 2
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    said = capsys.readouterr().out
    assert "1 of the 2 posts were posted" in said and "--resume" in said
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["complete"] is False and len(record["posts"]) == 1
    assert "HTTP 500" in record["failure"]
    # Posting it again whole is refused; resuming posts the rest, replying to the first.
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "not posted again whole" in capsys.readouterr().err
    credentials.fail_at = None
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 0
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["complete"] is True and len(record["posts"]) == 2
    second = credentials.records[record["posts"][1]["rkey"]]["sent"]["record"]
    first = {"uri": record["posts"][0]["uri"], "cid": record["posts"][0]["cid"]}
    assert second["reply"] == {"root": first, "parent": first}
    assert "embed" not in second
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 2


def test_a_post_whose_answer_was_lost_is_asked_for_and_not_made_twice(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at, credentials.how = 2, "lost"
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    assert "no answer came back" in capsys.readouterr().out
    assert published(ready, "bluesky-thread")["publications"][0]["pending"]["index"] == 2
    made = credentials.creates
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 0
    assert credentials.creates == made and len(credentials.records) == 2
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["complete"] is True and len(record["posts"]) == 2


def test_a_lookup_refused_is_not_read_as_no_post(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only `RecordNotFound` says Bluesky holds no post under a key: any other refusal of the
    lookup leaves the key, and nothing is sent again."""
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at = 2
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    pending = published(ready, "bluesky-thread")["publications"][0]["pending"]
    credentials.not_found = (400, {"error": "InvalidRequest", "message": "Could not find repo"})
    made = credentials.creates
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 1
    assert credentials.creates == made and len(credentials.records) == 1
    assert published(ready, "bluesky-thread")["publications"][0]["pending"] == pending


def test_a_post_refused_after_its_lookup_keeps_its_key(ready: Path, credentials) -> None:
    """Bluesky said it holds no post under the key, and then refused the post: the key is
    kept, so that the next run asks again rather than making a post under a new one."""
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at = 2
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    pending = published(ready, "bluesky-thread")["publications"][0]["pending"]
    credentials.refuse_create = True
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 1
    assert published(ready, "bluesky-thread")["publications"][0]["pending"] == pending
    credentials.refuse_create = False
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 0
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["complete"] is True and record["posts"][1]["rkey"] == pending["rkey"]


def test_a_did_web_account_whose_did_holds_its_handle_is_posted_from(
    ready: Path, credentials, monkeypatch
) -> None:
    credentials.did, credentials.handle = "did:web:alice.example.com", "alice.example.com"
    monkeypatch.setenv("BLUESKY_HANDLE", "alice.example.com")
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["account"] == "did:web:alice.example.com" and record["complete"] is True


def test_the_same_posts_are_not_posted_twice_after_an_edit_of_the_file_only(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    """A comment added to the file changes its digest and not one word posted."""
    path = text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    made = len(credentials.records)
    path.write_text(path.read_text("utf-8") + "\n<!-- posted on the day it came out -->\n",
                    encoding="utf-8", newline="\n")  # fmt: skip
    assert approve(ready, "bluesky-thread") == 0
    capsys.readouterr()
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "as printed, with the same files attached, were posted" in capsys.readouterr().err
    assert len(credentials.records) == made
    assert published(ready, "bluesky-thread")["publications"][0]["printed_sha256"]


def test_an_edited_thread_is_not_posted_beside_the_one_that_stopped(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    path = text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at = 2
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    path.write_text(path.read_text("utf-8").replace("Résumé", "Summary"), encoding="utf-8")
    assert approve(ready, "bluesky-thread") == 0
    capsys.readouterr()
    made = len(credentials.records)
    for words in (["--post"], ["--post", "--resume"]):
        assert run("publish", "bluesky-thread", str(ready), *words) == 2
        said = capsys.readouterr().err
        assert "stopped part-way, 1 of its posts posted" in said and "--abandon" in said
    assert len(credentials.records) == made
    assert run("publish", "bluesky-thread", str(ready), "--abandon") == 0
    assert "left as it is" in capsys.readouterr().out
    assert published(ready, "bluesky-thread")["publications"][0]["abandoned_on"]
    credentials.fail_at = None
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    assert len(credentials.records) == made + 2
    assert run("publish", "bluesky-thread", str(ready), "--abandon") == 2
    assert "nothing to abandon" in capsys.readouterr().err
    assert run("publish", "bluesky-thread", str(ready), "--abandon", "--post") == 2


def test_refused_credentials_post_nothing_and_are_named_not_quoted(
    ready: Path, credentials, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", PASSWORD + "-wrong")
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    said = capsys.readouterr().out
    assert "nothing was posted" in said and "BLUESKY_APP_PASSWORD" in said
    assert PASSWORD not in said
    assert not (ready / "communication" / "published").exists()


def test_a_service_that_asks_for_time_is_asked_again(ready: Path, credentials) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    credentials.throttle = 1
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    assert published(ready, "bluesky-thread")["publications"][0]["complete"] is True


# ----------------------------------------------------------------------- posting: Mastodon


def test_a_thread_is_posted_to_mastodon_with_its_image_described_and_its_keys(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "mastodon-thread")
    assert approve(ready, "mastodon-thread") == 0
    assert run("publish", "mastodon-thread", str(ready), "--post") == 0
    said = capsys.readouterr().out
    media = next(body for _m, path, _h, body in credentials.seen if path == "/api/v2/media")
    assert b"A forest plot of the reporting odds ratio." in media and PNG in media
    assert credentials.media_asked == 1  # 202, then asked until it was ready
    first, second = (one["sent"] for one in credentials.statuses.values())
    assert first["media_ids"] == ["301"] and first["visibility"] == "public"
    assert second["in_reply_to_id"] == "100" and "media_ids" not in second
    keys = list(credentials.keys)
    assert len(set(keys)) == 2 and all(len(key) == 40 for key in keys)
    record = published(ready, "mastodon-thread")["publications"][0]
    assert [one["id"] for one in record["posts"]] == ["100", "101"]
    assert record["posts"][1]["url"].endswith("/@ada/101")
    only_where_they_belong(credentials)
    nowhere(ready, said)


def test_a_mastodon_thread_resumed_replies_to_the_last_post_and_sends_its_key_again(
    ready: Path, credentials
) -> None:
    text(ready, "mastodon-thread", f"{CLEAN}\n\n---\n\nOne.\n\n---\n\nTwo.\n", image=False)
    assert approve(ready, "mastodon-thread") == 0
    credentials.fail_at, credentials.how = 3, "lost"
    assert run("publish", "mastodon-thread", str(ready), "--post") == 1
    pending = published(ready, "mastodon-thread")["publications"][0]["pending"]
    assert pending["index"] == 3
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume") == 0
    assert len(credentials.statuses) == 3  # the key sent again was the same status
    third = credentials.statuses[credentials.keys[pending["idempotency_key"]]]["sent"]
    assert third["in_reply_to_id"] == "101"
    assert published(ready, "mastodon-thread")["publications"][0]["complete"] is True


def test_a_corrected_image_under_the_same_name_is_another_status(ready: Path,
                                                                 credentials) -> None:  # fmt: skip
    """The key is of the files attached too: a corrected image approved again is posted, not
    answered with the status made with the first one."""
    text(ready, "mastodon-thread")
    assert approve(ready, "mastodon-thread") == 0
    assert run("publish", "mastodon-thread", str(ready), "--post") == 0
    (ready / "communication" / "figure.png").write_bytes(PNG + b"corrected")
    assert approve(ready, "mastodon-thread") == 0
    assert run("publish", "mastodon-thread", str(ready), "--post") == 0
    assert len(credentials.statuses) == 4
    first, second = published(ready, "mastodon-thread")["publications"]
    assert first["posts"][0]["id"] != second["posts"][0]["id"]


def test_a_resume_refused_keeps_the_record_of_a_post_that_may_be_up(
    ready: Path, credentials, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Post 1 was sent and its answer lost; the resume is refused before it is acted on. Post
    1 may be up, so its record stays, and a plain --post is still refused."""
    text(ready, "mastodon-thread", f"{CLEAN}\n\n---\n\nOne.\n", image=False)
    assert approve(ready, "mastodon-thread") == 0
    credentials.fail_at, credentials.how = 1, "lost"
    assert run("publish", "mastodon-thread", str(ready), "--post") == 1
    pending = published(ready, "mastodon-thread")["publications"][0]["pending"]
    monkeypatch.setenv("MASTODON_TOKEN", TOKEN + "-revoked")
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume") == 1
    record = published(ready, "mastodon-thread")["publications"]
    assert len(record) == 1 and record[0]["pending"] == pending and record[0]["posts"] == []
    capsys.readouterr()
    assert run("publish", "mastodon-thread", str(ready), "--post") == 2
    assert "not posted again whole" in capsys.readouterr().err


def _second_lost(root: Path, services: Services, how: str) -> dict:
    """A Mastodon thread of two posts whose second was sent and heard nothing of: made, its
    answer lost (`lost`), or not made (`500`). Its pending entry."""
    text(root, "mastodon-thread", f"{CLEAN}\n\n---\n\nOne.\n", image=False)
    assert approve(root, "mastodon-thread") == 0
    services.fail_at, services.how = 2, how
    assert run("publish", "mastodon-thread", str(root), "--post") == 1
    pending = published(root, "mastodon-thread")["publications"][0]["pending"]
    assert pending["index"] == 2 and pending["pending_at"].endswith("Z")
    services.fail_at = None
    return pending


def _an_hour_later(monkeypatch, services: Services) -> None:
    moment = datetime.now(timezone.utc) + mastodon.KEY_LIFETIME + timedelta(minutes=1)
    monkeypatch.setattr(lifecycle, "now", lambda: moment)
    services.forget_keys()


def test_a_late_resume_on_mastodon_is_refused_and_was_posted_records_the_post(
    ready: Path, credentials, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pending = _second_lost(ready, credentials, "lost")
    _an_hour_later(monkeypatch, credentials)
    seen = len(credentials.seen)
    capsys.readouterr()
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume") == 2
    said = capsys.readouterr().err
    assert "post 2 of mastodon-thread.md" in said and pending["pending_at"] in said
    assert credentials.url in said and "--was-posted" in said and "--not-posted" in said
    assert len(credentials.seen) == seen  # nothing was sent
    # The account's post 1 is not post 2: it replies to nothing.
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume",
               "--was-posted", "100") == 2  # fmt: skip
    assert "is not post 2" in capsys.readouterr().err
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume",
               "--was-posted", f"{credentials.url}/@ada/101") == 0  # fmt: skip
    assert len(credentials.statuses) == 2
    record = published(ready, "mastodon-thread")["publications"][0]
    assert record["complete"] is True and "pending" not in record
    assert record["posts"][1] == {"index": 2, "id": "101", "url": f"{credentials.url}/@ada/101",
                                  "posted_on": pending["pending_at"], "recorded": "--was-posted"}


def test_a_late_resume_on_mastodon_not_posted_sends_it_under_a_new_key(
    ready: Path, credentials, monkeypatch
) -> None:
    pending = _second_lost(ready, credentials, "500")
    _an_hour_later(monkeypatch, credentials)
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume",
               "--not-posted") == 0  # fmt: skip
    assert len(credentials.statuses) == 2
    second = credentials.statuses["101"]
    assert second["key"] != pending["idempotency_key"]
    assert second["sent"]["in_reply_to_id"] == "100"
    record = published(ready, "mastodon-thread")["publications"][0]
    assert record["complete"] is True and [one["id"] for one in record["posts"]] == ["100", "101"]


def _account_status(services: Services, number: str, **said) -> None:
    """A status of the account the instance holds, made by hand, not by a key."""
    services.statuses[number] = {"sent": {}, "key": None, "answer": {
        "id": number, "url": f"{services.url}/@ada/{number}", "account": {"id": services.account},
        "in_reply_to_id": None, "reblog": None,
        "created_at": bluesky.stamp(datetime.now(timezone.utc)), **said}}


def test_was_posted_for_post_1_is_not_a_boost_nor_a_post_made_at_another_time(
    ready: Path, credentials, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A thread's first post replies to nothing, as an older paper's post and a boost do: the
    status named is held to have been made when the post was sent, and to be no boost."""
    text(ready, "mastodon-thread", f"{CLEAN}\n\n---\n\nOne.\n", image=False)
    assert approve(ready, "mastodon-thread") == 0
    credentials.fail_at, credentials.how = 1, "lost"
    assert run("publish", "mastodon-thread", str(ready), "--post") == 1
    pending = published(ready, "mastodon-thread")["publications"][0]["pending"]
    credentials.fail_at = None
    _an_hour_later(monkeypatch, credentials)
    _account_status(credentials, "500", reblog={"id": "77", "account": {"id": "12"}})
    _account_status(credentials, "501", created_at="2026-01-05T09:00:00.000Z")
    sent = mastodon.sent_at(pending)
    late = sent + timedelta(minutes=61)  # the fifty minutes, the ten of the margin, and one
    _account_status(credentials, "502", created_at=bluesky.stamp(late))
    _account_status(credentials, "503", created_at=bluesky.stamp(sent - timedelta(minutes=6)))
    capsys.readouterr()
    for number, said in (("500", "is a boost"), ("501", "it is another post"),
                         ("502", "it is another post"), ("503", "it is another post")):
        assert run("publish", "mastodon-thread", str(ready), "--post", "--resume",
                   "--was-posted", number) == 2, number  # fmt: skip
        assert said in capsys.readouterr().err, number
        assert published(ready, "mastodon-thread")["publications"][0]["pending"] == pending
    # Within the margins, with the instance's offset written out, it is the post.
    within = (sent + timedelta(minutes=55)).astimezone(timezone(timedelta(hours=9)))
    _account_status(credentials, "504", created_at=within.isoformat(timespec="milliseconds"))
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume",
               "--was-posted", "504") == 0  # fmt: skip
    record = published(ready, "mastodon-thread")["publications"][0]
    assert record["complete"] is True and record["posts"][0]["id"] == "504"
    second = credentials.statuses[record["posts"][1]["id"]]["sent"]
    assert second["in_reply_to_id"] == "504"


@pytest.mark.parametrize("origin", ["https://example.social", "https://example.social:443"])
def test_a_link_with_its_scheme_s_default_port_written_is_on_the_instance(origin: str) -> None:
    api = net.Api("Mastodon", origin, "MASTODON_BASE_URL and MASTODON_TOKEN")
    for link in ("https://example.social/@me/1", "https://Example.social:443/@me/1"):
        assert mastodon.status_id(api, link) == "1"
    for link in ("https://example.social:8443/@me/1", "http://example.social/@me/1",
                 "https://example.social:x/@me/1"):
        with pytest.raises(publish.Refused):
            mastodon.status_id(api, link)


def test_a_failed_lookup_of_was_posted_past_the_hour_says_what_is_true(
    ready: Path, credentials, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The key's fifty minutes have passed: the message does not offer them again."""
    pending = _second_lost(ready, credentials, "lost")
    _an_hour_later(monkeypatch, credentials)
    capsys.readouterr()
    assert run("publish", "mastodon-thread", str(ready), "--post", "--resume",
               "--was-posted", "999") == 1  # fmt: skip
    said = capsys.readouterr().out
    assert "within 50 minutes" not in said and "same Idempotency-Key" not in said
    assert "more than 50 minutes ago" in said and pending["pending_at"] in said
    assert "--was-posted <its link or id>" in said and "--not-posted" in said
    assert published(ready, "mastodon-thread")["publications"][0]["pending"] == pending


@pytest.mark.parametrize("channel", ["bluesky-thread", "mastodon-thread"])
def test_the_posts_of_an_abandoned_thread_are_not_posted_again(
    ready: Path, credentials, channel: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Its posts are up: the same text posted again would stand beside them (Bluesky), or be
    answered with them by the keys the instance still keeps (Mastodon)."""
    path = text(ready, channel, image=False)
    assert approve(ready, channel) == 0
    credentials.fail_at = 2
    assert run("publish", channel, str(ready), "--post") == 1
    credentials.fail_at = None
    assert run("publish", channel, str(ready), "--abandon") == 0
    made = (len(credentials.records), len(credentials.statuses))
    capsys.readouterr()
    assert run("publish", channel, str(ready), "--post") == 2
    said = capsys.readouterr().err
    assert "left part-way" in said and "Change the text" in said
    assert (len(credentials.records), len(credentials.statuses)) == made
    assert len(published(ready, channel)["publications"]) == 1
    path.write_text(path.read_text("utf-8").replace("Résumé", "Summary"), encoding="utf-8")
    assert approve(ready, channel) == 0
    assert run("publish", channel, str(ready), "--post") == 0
    assert len(published(ready, channel)["publications"]) == 2


def test_the_same_words_in_another_language_are_other_posts(ready: Path) -> None:
    path = text(ready, "mastodon-thread", image=False)
    first = approval.prepare(load_project(ready)[0], "mastodon-thread")
    path.write_text(path.read_text("utf-8").replace("---\n", "---\nlanguage: fr\n", 1),
                    encoding="utf-8", newline="\n")  # fmt: skip
    second = approval.prepare(load_project(ready)[0], "mastodon-thread")
    assert second.language == "fr" and second.posts == first.posts
    assert second.printed_sha256 != first.printed_sha256


@pytest.mark.parametrize("at", ["stopped", "complete"])
def test_a_record_that_cannot_be_written_says_posts_may_have_been_made(
    ready: Path, credentials, monkeypatch, at: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The write of a stopped thread's failure, or of a whole one's `complete`, fails: the
    author is told the posts may be up, and the record stays as it was written last."""
    text(ready, "bluesky-thread", image=False)
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at = 2 if at == "stopped" else None
    real = publish.write_published

    def failing(project, channel: str, document: dict):
        entry = document["publications"][-1]
        if "failure" in entry or entry.get("complete") is True:
            raise PermissionError(13, "Permission denied")
        return real(project, channel, document)

    monkeypatch.setattr(publish, "write_published", failing)
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    assert "MAY HAVE BEEN MADE" in capsys.readouterr().out
    record = published(ready, "bluesky-thread")["publications"][0]
    assert record["complete"] is False and "failure" not in record
    assert len(record["posts"]) == (1 if at == "stopped" else 2)


def test_a_record_not_written_after_nothing_was_posted_says_nothing_was_posted(
    ready: Path, credentials, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first post refused, and the record then not written again: the author is told
    nothing was posted and why, not that posts may be up."""
    text(ready, "bluesky-thread", image=False)
    assert approve(ready, "bluesky-thread") == 0
    credentials.fail_at, credentials.how = 1, "401"
    real = publish.write_published

    def failing(project, channel: str, document: dict):
        if document["publications"] == []:  # the entry taken out, nothing having been posted
            raise PermissionError(13, "Permission denied")
        return real(project, channel, document)

    monkeypatch.setattr(publish, "write_published", failing)
    assert run("publish", "bluesky-thread", str(ready), "--post") == 1
    said = capsys.readouterr().out
    assert "nothing was posted:" in said and "could not be written again" in said
    assert "MAY HAVE BEEN MADE" not in said and "--post --resume" in said
    # The way the message gives sends the thread from its first post, once.
    monkeypatch.setattr(publish, "write_published", real)
    credentials.fail_at = None
    assert run("publish", "bluesky-thread", str(ready), "--post", "--resume") == 0
    [record] = published(ready, "bluesky-thread")["publications"]
    assert record["complete"] is True and record["posts"][0]["index"] == 1


def test_a_time_with_an_offset_of_a_day_is_no_time() -> None:
    assert mastodon.created("2026-10-29T10:00:00.000+24:00") is None
    assert mastodon.created("2026-10-29T10:00:00+23:59") is not None


@pytest.mark.parametrize(("channel", "words", "said"), [
    ("mastodon-thread", ["--post", "--was-posted", "101"], "go with --post --resume"),
    ("mastodon-thread", ["--post", "--resume", "--was-posted", "101", "--not-posted"],
     "say opposite things"),
    ("bluesky-thread", ["--post", "--resume", "--not-posted"], "are Mastodon's"),
])  # fmt: skip
def test_what_became_of_a_lost_post_is_said_only_where_it_means_something(
    ready: Path, channel: str, words: list[str], said: str,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    text(ready, channel)
    assert run("publish", channel, str(ready), *words) == 2
    assert said in capsys.readouterr().err


# --------------------------------------------------------------------- without credentials


def test_with_no_credentials_it_says_what_to_paste_where_and_posts_nothing(
    ready: Path, services, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    said = capsys.readouterr().out
    assert "--- post 2 ---" in said and "Résumé, 要旨: https://example.org/paper." in said
    assert "BLUESKY_HANDLE and BLUESKY_APP_PASSWORD are not set" in said
    assert "Attach figure.png to post 1" in said
    assert services.seen == [] and not (ready / "communication" / "published").exists()


def test_the_embargo_holds_a_post_that_is_approved(ready: Path, credentials, monkeypatch,
                                                   capsys: pytest.CaptureFixture[str]
                                                   ) -> None:  # fmt: skip
    append(ready, "publication:\n  embargo_until: 2026-12-01T00:01Z\n")
    monkeypatch.setattr(lifecycle, "now", lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "embargo holds until 2026-12-01 00:01 UTC" in capsys.readouterr().err
    assert credentials.seen == []
    monkeypatch.setattr(lifecycle, "now", lambda: datetime(2026, 12, 2, tzinfo=timezone.utc))
    assert run("publish", "bluesky-thread", str(ready), "--post") == 0
    # The clock stood still for both posts of the thread, and each has a key of its own.
    keys = [one["rkey"] for one in published(ready, "bluesky-thread")["publications"][0]["posts"]]
    assert len(keys) == 2 and keys[0] < keys[1] and set(keys) == set(credentials.records)


def test_a_record_of_what_was_posted_that_cannot_be_read_stops_the_post(
    ready: Path, credentials, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "bluesky-thread")
    assert approve(ready, "bluesky-thread") == 0
    record = ready / "communication" / "published" / "bluesky-thread.yaml"
    record.parent.mkdir()
    record.write_text("publications: {", encoding="utf-8")
    assert run("publish", "bluesky-thread", str(ready), "--post") == 2
    assert "cannot be read" in capsys.readouterr().err
    assert credentials.seen == []


# ---------------------------------------------------------------------------------- ORCID


def test_orcid_says_whether_the_doi_is_on_each_public_record_and_writes_nothing(
    ready: Path, services, capsys: pytest.CaptureFixture[str]
) -> None:
    append(ready, "publication:\n  status: published-online\n  doi: 10.1234/demo.5678\n")
    before = sorted(path for path in ready.rglob("*") if path.is_file())
    services.works = ["https://doi.org/10.1234/DEMO.5678"]
    assert run("orcid", str(ready)) == 0
    assert "Ada Example (0000-0002-1825-0097): on the record" in capsys.readouterr().out
    services.works = ["10.9999/other"]
    assert run("orcid", str(ready)) == 0
    said = capsys.readouterr().out
    assert "not on the public record" in said and "privacy" not in said
    assert "kept private" in said
    asked = [path for _m, path, _h, _b in services.seen]
    assert asked.count("/v3.0/0000-0002-1825-0097/works") == 2
    assert all(path.startswith("/v3.0/") and path.endswith("/works") for path in asked)
    assert all(method == "GET" for method, _p, _h, _b in services.seen)
    assert sorted(path for path in ready.rglob("*") if path.is_file()) == before


def test_orcid_reads_nothing_while_the_suite_runs(ready: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    append(ready, "publication:\n  doi: 10.1234/demo.5678\n")
    assert run("orcid", str(ready)) == 0
    assert "not read" in capsys.readouterr().out
    assert orcid.valid("0000-0002-1825-0097") and not orcid.valid("0000-0002-1825-0098")


def test_publish_refuses_while_the_group_is_off(project: Path) -> None:
    assert run("publish", "bluesky-thread", str(project)) == 2
    assert run("approve", "bluesky-thread", str(project), "--as", "Example") == 2
    assert publish.BY_HAND
