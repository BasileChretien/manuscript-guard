"""One file fetched from the web, following redirects over https only: what `sync-sources`
downloads a cited work's open copy, or its publisher's PDF, with.

`lookup/http.py` follows no redirect, since one would carry a registry key to a host nobody
chose. A download cannot work that way: doi.org answers every DOI with a redirect to the
publisher, and a repository's PDF link often redirects to a storage host. So this follows
them, under its own rules:

* **https only, at every hop**, but to this machine, which is how the tests answer. A
  redirect to `http://` is refused rather than followed: the bytes kept as the work's would
  otherwise be ones anybody on the network could have changed.
* **No key, no address, no cookie of the user's travels.** The request carries a
  User-Agent naming the toolkit and nothing else of the person running it. A cookie a
  publisher sets on the way through its redirects is kept in memory for that run only, as a
  browser would keep it, since some publishers send the PDF only to a client that returns the
  cookie their first redirect set; it is never written anywhere.
* **A cap on the size,** checked against `Content-Length` before reading and against what is
  read: a server that sends more is cut off and nothing is kept.
* **Nothing leaves the machine while `MANUSCRIPT_GUARD_NO_NETWORK` is set,** which the test
  suite sets, as `communicate` does: a test that forgot its own transport fails rather than
  reaching a publisher.

Nothing fetched is ever run: the bytes are only read, as a PDF's text or a page's tags, by
the caller.
"""

from __future__ import annotations

import http.client
import http.cookiejar
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from manuscript_guard import __version__
from manuscript_guard.lookup.http import LOOPBACK, NoAnswer, Request, Response, Transport

#: The largest file kept: a long article with its figures is rarely over 20 MB, and a server
#: that sends more than this is sending something else.
MAX_BYTES = 64 * 1024 * 1024
#: doi.org, then the publisher's own two or three, then its storage host: eight is more than
#: any chain seen, and a loop is cut off at it.
MAX_HOPS = 8
TIMEOUT_SECONDS = 60.0
REDIRECTS = frozenset({301, 302, 303, 307, 308})
#: Set, to anything, no request is sent: the test suite sets it.
NO_NETWORK = "MANUSCRIPT_GUARD_NO_NETWORK"
#: Who is asking, without saying who runs it: no e-mail address goes to any of these hosts.
AGENT = f"manuscript-guard/{__version__} (+https://github.com/BasileChretien/manuscript-guard)"


class Offline(NoAnswer):
    """No request may leave this machine: nothing else is worth asking either."""


@dataclass(frozen=True)
class Fetched:
    """What came back at the end of the redirects: where, its status, its type, its bytes."""

    url: str
    status: int
    content_type: str
    body: bytes


def allowed(url: str) -> bool:
    """Whether a URL may be asked: https, or http to this machine."""
    parts = urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK)


def header(response: Response, name: str) -> str:
    """A header of an answer, whatever case the server wrote its name in."""
    wanted = name.lower()
    return next((v for k, v in response.headers.items() if k.lower() == wanted), "")


def get(url: str, transport: Transport, *, accept: str = "*/*") -> Fetched:
    """GET `url`, following each redirect while it stays on https. Raises NoAnswer, with a
    reason that quotes no secret, where no answer came or a redirect was refused."""
    for _hop in range(MAX_HOPS + 1):
        if not allowed(url):
            parts = urlsplit(url)
            raise NoAnswer(f"refused to follow a link to {parts.scheme}://{parts.hostname}, "
                           "which is not https")  # fmt: skip
        response = transport(Request(url, headers={"User-Agent": AGENT, "Accept": accept}),
                             TIMEOUT_SECONDS)  # fmt: skip
        if response.status not in REDIRECTS:
            kind = header(response, "Content-Type").split(";")[0].strip().lower()
            return Fetched(url, response.status, kind, response.body)
        location = header(response, "Location").strip()
        if not location:
            raise NoAnswer(f"{urlsplit(url).hostname} redirected without saying where")
        url = urljoin(url, location)
    raise NoAnswer(f"redirected more than {MAX_HOPS} times")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """`get` follows redirects itself, so that each hop is held to https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def session() -> Transport:
    """A transport for one run: one GET at a time, a cookie jar kept in memory only."""
    jar = http.cookiejar.CookieJar()

    def send(request: Request, timeout: float) -> Response:
        return default_transport(request, timeout, jar)

    return send


def default_transport(
    request: Request, timeout: float, jar: http.cookiejar.CookieJar | None = None
) -> Response:
    """Send one GET with `urllib`, no redirect followed, at most `MAX_BYTES` read. A status
    that is not 2xx is an answer, not an error. The proxy the environment names is used, as a
    university network's may be the way to its access."""
    if os.environ.get(NO_NETWORK, "").strip():
        raise Offline(f"{NO_NETWORK} is set, so no request leaves this machine")
    url = request.url
    if not allowed(url):
        raise NoAnswer(f"refused to send a request to {urlsplit(url).scheme}://"
                       f"{urlsplit(url).hostname}")  # fmt: skip
    host = urlsplit(url).hostname
    handlers: list = [_NoRedirect, urllib.request.HTTPCookieProcessor(jar)]
    if host in LOOPBACK:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    outgoing = urllib.request.Request(url, headers=dict(request.headers), method="GET")
    try:
        try:
            with opener.open(outgoing, timeout=timeout) as answer:
                return Response(answer.status, dict(answer.headers.items()), _read(answer))
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers.items()) if exc.headers else {}
            return Response(exc.code, headers, exc.read(1 << 20))
    except http.client.HTTPException as exc:
        raise NoAnswer(f"the answer from {host} could not be read ({type(exc).__name__})") from None
    except ValueError:
        raise NoAnswer("the request could not be made as written") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise NoAnswer(f"no answer from {host} within {timeout:g} s") from None
        raise NoAnswer(f"no connection to {host}") from None


def _read(answer) -> bytes:
    """The body, refused where it says or turns out to be larger than `MAX_BYTES`, or where it
    stops short of what it said it was."""
    declared = answer.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BYTES:
        raise NoAnswer(f"the file is {int(declared) >> 20} MB, over the {MAX_BYTES >> 20} MB "
                       "kept")  # fmt: skip
    body = answer.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise NoAnswer(f"the file is over the {MAX_BYTES >> 20} MB kept")
    if declared.isdigit() and len(body) < int(declared):
        raise NoAnswer("the answer was cut off part way")
    return body


__all__ = [
    "AGENT",
    "MAX_BYTES",
    "MAX_HOPS",
    "NO_NETWORK",
    "Fetched",
    "Offline",
    "allowed",
    "default_transport",
    "get",
    "header",
    "session",
]
