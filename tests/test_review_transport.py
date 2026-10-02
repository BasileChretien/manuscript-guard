"""The real transport, against a server on this machine.

Every other test of the provider layer hands the client a transport that answers from a list,
so the function that actually opens a connection, carries the key and reads the answer was
not run by any of them. Here it talks to an HTTP server started on a loopback port for the
test: nothing leaves the machine, and nothing outside it is needed.

Skipped where a loopback connection is not allowed, as in some sandboxes.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from manuscript_guard.panel import client, providers
from manuscript_guard.panel.client import CallFailed, HttpRequest, TransportError

KEY = "sk-test-0123456789abcdefSECRET"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        """urllib follows a 301, 302 or 303 to a POST with a GET, headers and all."""
        self.do_POST()

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.seen.append((self.path, dict(self.headers.items()), body))
        status, headers, payload = self.server.respond(self.path)
        try:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            if "Content-Length" not in headers:
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True
        except ConnectionError:
            pass  # the client gave up waiting, which is what the timeout test is for

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []
    httpd.respond = lambda path: (200, {}, b"{}")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        client.default_transport(HttpRequest(httpd.url + "/probe", {}, b"{}"), 5)
    except TransportError as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def local_model(server):
    paper = {
        "review": {
            "models": ["here/some-model"],
            "providers": {"here": {"base_url": server.url + "/v1", "key_env": "HERE_KEY"}},
        }
    }
    return providers.configured_models(paper)[0]


def chat(text: str = '{"ok": true}') -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-1",
            "model": "some-model",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        }
    ).encode()


def test_a_request_arrives_as_it_was_built(server) -> None:
    model = local_model(server)
    body = client.build_body(model, "the system text", "the user text")
    server.respond = lambda path: (200, {"Content-Type": "application/json"}, chat())

    reply = client.call(model, body, key=KEY)

    assert reply.text == '{"ok": true}'
    [(path, headers, received)] = server.seen
    assert path == "/v1/chat/completions"
    assert received == body
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"].startswith("manuscript-guard/")


def test_a_status_that_is_not_success_comes_back_as_an_answer(server) -> None:
    server.respond = lambda path: (429, {"Retry-After": "7"}, b'{"error": {"message": "slow"}}')
    response = client.default_transport(HttpRequest(server.url + "/v1/x", {}, b"{}"), 5)
    assert response.status == 429
    assert response.body == b'{"error": {"message": "slow"}}'
    assert client._wait(response) == 7.0


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_not_followed_and_the_key_goes_nowhere_else(server, status: int) -> None:
    """The second address is on the same server so the test can see that nothing arrived.

    Left to itself urllib answers a 301, 302 or 303 to a POST by asking the new address with
    a GET that still carries the Authorization header.
    """
    model = local_model(server)

    def respond(path: str):
        if path == "/v1/chat/completions":
            return status, {"Location": server.url + "/elsewhere"}, b""
        return 200, {}, chat()

    server.respond = respond
    with pytest.raises(CallFailed) as failed:
        client.call(model, client.build_body(model, "s", "u"), key=KEY)

    assert failed.value.kind == "rejected" and "redirect" in str(failed.value)
    assert [path for path, _headers, _body in server.seen] == ["/v1/chat/completions"]


def test_what_an_exception_says_about_a_header_it_refused_is_not_repeated(server) -> None:
    """`http.client` will not send a header holding a line break, and says which: the
    message quotes the header. A key never gets this far now; if one did, it must not be
    printed from here."""
    request = HttpRequest(
        server.url + "/v1/x", {"Authorization": "Bearer sk-FIRSTHALF\nSECONDHALF"}, b"{}"
    )
    with pytest.raises(TransportError) as failed:
        client.default_transport(request, 5)
    assert "FIRSTHALF" not in str(failed.value) and "SECONDHALF" not in str(failed.value)
    assert server.seen == []


def test_a_server_that_does_not_answer_in_time_is_a_timeout(server) -> None:
    def slow(path: str):
        time.sleep(1.5)
        return 200, {}, chat()

    server.respond = slow
    with pytest.raises(TransportError) as failed:
        client.default_transport(HttpRequest(server.url + "/v1/x", {}, b"{}"), 0.3)
    assert failed.value.kind == "timeout"


def test_nothing_listening_is_a_network_failure_not_a_traceback(server) -> None:
    port = server.server_address[1]
    server.shutdown()
    server.server_close()
    # Windows takes about two seconds to refuse a connection to a closed loopback port.
    with pytest.raises(TransportError) as failed:
        client.default_transport(HttpRequest(f"http://127.0.0.1:{port}/v1/x", {}, b"{}"), 15)
    assert failed.value.kind == "network"
    assert KEY not in str(failed.value)


def test_an_answer_too_large_to_be_a_review_is_not_read_whole(server, monkeypatch) -> None:
    monkeypatch.setattr(client, "MAX_BYTES", 64)
    server.respond = lambda path: (200, {}, b"x" * 1000)
    model = local_model(server)
    response = client.default_transport(HttpRequest(server.url + "/v1/x", {}, b"{}"), 5)
    assert len(response.body) == 65
    with pytest.raises(CallFailed) as failed:
        client.read_reply(model, response)
    assert failed.value.kind == "unreadable"


def test_an_answer_cut_off_part_way_is_a_failure_not_a_traceback(server) -> None:
    """`http.client` raises its own exception for this, which is not an OSError."""
    server.respond = lambda path: (200, {"Content-Length": "500"}, b'{"choices": [')
    model = local_model(server)
    with pytest.raises(CallFailed) as failed:
        client.call(model, client.build_body(model, "s", "u"), key=KEY)
    assert failed.value.kind == "network"
    assert len(server.seen) == 1, "and it is not asked again"


def test_a_model_on_this_machine_is_not_reached_through_a_proxy(server, monkeypatch) -> None:
    """Many institutional networks set `http_proxy`. A request for `http://localhost` then
    went to the proxy, body and all, while the statement said nothing leaves the machine.
    The proxy here is the test's own server; nothing listens on the port the model is on."""
    monkeypatch.setenv("http_proxy", server.url)
    monkeypatch.delenv("no_proxy", raising=False)
    paper = {
        "review": {
            "models": ["local/m"],
            "providers": {"local": {"base_url": "http://localhost:9/v1"}},
        }
    }
    model = providers.configured_models(paper)[0]
    assert model.provider.local
    body = client.build_body(model, "s", "THE UNPUBLISHED MANUSCRIPT")
    with pytest.raises(CallFailed):
        client.call(model, body, key=None, timeout=15)
    assert server.seen == [], "the proxy was sent the request"


def test_a_key_with_a_line_break_opens_no_connection_and_prints_nothing(
    server, monkeypatch
) -> None:
    broken = "sk-FIRSTHALF\nSECONDHALF"
    monkeypatch.setenv("HERE_KEY", broken)
    model = local_model(server)
    with pytest.raises(providers.ConfigError) as refused:
        providers.read_key(model.provider)
    assert "FIRSTHALF" not in str(refused.value) and "SECONDHALF" not in str(refused.value)
    with pytest.raises(CallFailed) as failed:
        client.call(model, client.build_body(model, "s", "u"), key=broken)
    assert "FIRSTHALF" not in str(failed.value) and "SECONDHALF" not in str(failed.value)
    assert server.seen == []
