"""One request to a repository's API, and its answer read back: what `deposit` sends with.

What this module is careful about, as `lookup/http.py` and `panel/client.py` are:

* **The token goes into one header and nowhere else**: never into a URL, a file, a record or
  a message. Every message built from what a host said is scrubbed of it, whole or in part,
  and a token refused gets a message of our own, since a host's words for a bad token can
  quote it.
* **Redirects are not followed.** One would carry the token and the files to a host nobody
  chose; the 3xx comes back as the answer, and is refused.
* **A link a host gives is followed only to the host it came from.** Zenodo names the bucket
  the files go to; a bucket on any other host, scheme or port is refused before the token is
  sent there.
* **https only,** except to this machine, which is how the tests answer: a loopback server
  stands in for each host, and no test opens a connection to one.

The transport is an argument, so a test answers from a table or from a server on a loopback
port.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from manuscript_guard import __version__
from manuscript_guard.panel.client import KEY_PART, without_key
from manuscript_guard.panel.providers import usable_key

TIMEOUT_SECONDS = 120.0
MAX_BYTES = 8 * 1024 * 1024
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
#: As much of a host's own words as a message quotes.
SHOWN = 300
#: The longest DOI or link a host's answer is recorded with.
MAX_KEPT = 2000
#: As many characters of the token in a row as make a value a host returned one that is
#: refused rather than recorded: fewer, as a message is scrubbed of, would refuse a link
#: that shares four digits with a token by chance.
TOKEN_STRETCH = 8


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    #: Holds the token, so it is left out of the request's printed form.
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    body: bytes = field(default=b"", repr=False)


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


class NoAnswer(Exception):
    """No answer came back. The message is ours, and quotes no URL. `reached` is False where
    the request cannot have reached the host: refused before it was sent, or no connection."""

    def __init__(self, message: str, *, reached: bool = True) -> None:
        super().__init__(message)
        self.reached = reached


class RemoteError(Exception):
    """The host refused, or answered in a way that is not taken: a sentence for the author,
    with no token in it. `reached` is False where the request cannot have been acted on: never
    sent, no connection made, or the token refused."""

    def __init__(self, message: str, *, reached: bool = True) -> None:
        super().__init__(message)
        self.reached = reached


Transport = Callable[[Request, float], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def allowed(url: str) -> bool:
    """https, or plain http to this machine."""
    parts = urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK)


def default_transport(request: Request, timeout: float) -> Response:
    """Send one request with `urllib`. A status that is not 2xx is an answer, not an error."""
    parts = urlsplit(request.url)
    if not allowed(request.url):
        raise NoAnswer(f"refused to send a request to {parts.scheme}://{parts.hostname}",
                       reached=False)
    handlers: list = [_NoRedirect]
    if parts.hostname in LOOPBACK:
        # The proxy that `http_proxy` names is not asked for this machine.
        handlers.append(urllib.request.ProxyHandler({}))
    try:
        opener = urllib.request.build_opener(*handlers)
        outgoing = urllib.request.Request(request.url, data=request.body or None,
                                          headers=dict(request.headers),
                                          method=request.method)  # fmt: skip
        try:
            with opener.open(outgoing, timeout=timeout) as answer:
                body = answer.read(MAX_BYTES + 1)
                declared = answer.headers.get("Content-Length", "")
                if declared.isdigit() and len(body) < min(int(declared), MAX_BYTES + 1):
                    raise NoAnswer("the answer was cut off part way")
                return Response(answer.status, dict(answer.headers.items()), body)
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers.items()) if exc.headers else {}
            return Response(exc.code, headers, exc.read(MAX_BYTES + 1))
    except http.client.HTTPException as exc:
        raise NoAnswer(f"the answer could not be read ({type(exc).__name__})") from None
    except ValueError:
        # Raised while the request is built, and its words quote what it was built from: for
        # a header `http.client` will not send, the header, token and all. Never repeated.
        raise NoAnswer("the request could not be made as written", reached=False) from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise NoAnswer(f"no answer within {timeout:g} s") from None
        raise NoAnswer(f"no connection to {parts.hostname}", reached=not _before(reason)) \
            from None  # fmt: skip


def _before(reason: object) -> bool:
    """Whether a failure came before the request could be sent: a connection refused, a name
    that is no host's, a certificate that failed its check, or a TLS handshake that failed,
    each before the first byte of the request. A timeout is not among them: urllib does not
    tell one while connecting from one while sending."""
    if isinstance(reason, (ConnectionRefusedError, socket.gaierror,
                           ssl.SSLCertVerificationError)):  # fmt: skip
        return True
    said = str(reason).upper()
    return isinstance(reason, ssl.SSLError) and ("HANDSHAKE" in said
                                                 or "WRONG_VERSION_NUMBER" in said)


def token_from(name: str) -> str:
    """The token in the environment variable `name`; `RemoteError` where it is unset or could
    not go into a header as it is. The token is read from there only: never from a file."""
    token = os.environ.get(name, "")
    if not token:
        raise RemoteError(f"{name} is not set: the token is read from the environment only, "
                          "and never from a file")  # fmt: skip
    if not usable_key(token):
        raise RemoteError(f"{name} holds a space or a character a header cannot carry; set it "
                          "to the token alone")  # fmt: skip
    return token


def _without_key_folded(text: str, token: str) -> str:
    """`text` with any run of the token's characters, four or more in a row, taken out, the
    two compared in small letters; the rest of `text` as it was."""
    low, key = text.lower(), token.lower()
    if len(low) != len(text) or len(key) < KEY_PART:
        return without_key(low, key)
    parts = {key[i : i + KEY_PART] for i in range(len(key) - KEY_PART + 1)}
    hidden = [False] * len(text)
    for start in range(len(text) - KEY_PART + 1):
        if low[start : start + KEY_PART] in parts:
            hidden[start : start + KEY_PART] = [True] * KEY_PART
    return "".join(char if not hidden[index] else "[key]" if index == 0 or not hidden[index - 1]
                   else "" for index, char in enumerate(text))  # fmt: skip


def scrubbed(text: str, token: str | None, *, folded: bool = False) -> str:
    """Somebody else's words, fit to print: without the token or any part of it, without
    characters a terminal would act on, and not at length. `folded` looks for the token in
    small letters too, for what a host may have lowered, a host name."""
    kept = _without_key_folded(text, token) if folded and token else without_key(text, token)
    text = "".join(char if char.isprintable() else " " for char in kept)
    text = " ".join(text.split())
    return text if len(text) <= SHOWN else text[:SHOWN] + "..."


def _said(body: bytes) -> str:
    """A host's own account of an error, from wherever its body keeps one."""
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        return body[:4096].decode("utf-8", errors="replace")
    if isinstance(document, dict):
        for found in (document.get("message"), document.get("detail"),
                      (document.get("errors") or [{}])[0] if isinstance(
                          document.get("errors"), list) else None):  # fmt: skip
            if isinstance(found, dict):
                found = found.get("detail") or found.get("message")
            if isinstance(found, str) and found.strip():
                return found
    return body[:4096].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Client:
    """A host's API, as one origin, its token and the variable it is read from."""

    name: str
    origins: tuple[str, ...]
    token: str = field(repr=False)
    token_env: str
    transport: Transport = default_transport
    timeout: float = TIMEOUT_SECONDS

    def _same_origin(self, url: str) -> bool:
        parts = urlsplit(url)
        for origin in self.origins:
            known = urlsplit(origin)
            if (parts.scheme, parts.hostname, parts.port) == \
                    (known.scheme, known.hostname, known.port):  # fmt: skip
                return True
        return False

    def plain(self, said: object, *, folded: bool = False) -> str:
        """Anything a host returned, fit for a message: without the token or any part of it,
        without characters a terminal would act on, and not at length. `folded` for what is
        read in small letters, a host name: the token is looked for in small letters too."""
        return scrubbed(str(said), self.token, folded=folded)

    def kept(self, what: str, said: object) -> str | None:
        """A string a host returned that is to be recorded or printed whole, a DOI or a link;
        None where it gave none. Refused where it holds the token, or a stretch of it long
        enough not to be chance, or a character a terminal would act on: such a value is
        written nowhere."""
        if said is None:
            return None
        if not isinstance(said, str) or not said or len(said) > MAX_KEPT:
            raise RemoteError(f"{self.name} answered a {what} that is not one")
        stretches = {self.token[i : i + TOKEN_STRETCH]
                     for i in range(max(len(self.token) - TOKEN_STRETCH + 1, 1))}  # fmt: skip
        if any(part in said for part in stretches) or not said.isprintable():
            raise RemoteError(f"{self.name} answered a {what} that holds part of the token or a "
                              "character a terminal acts on; it is recorded nowhere, and "
                              "nothing more is done")  # fmt: skip
        return said

    def call(self, method: str, url: str, *, document: object = None, data: bytes | None = None,
             content_type: str | None = None, expect: tuple[int, ...] = (200, 201, 202),
             ) -> dict:  # fmt: skip
        """Send one request and return the JSON object it answered with; `RemoteError` where
        no answer came, the host refused, or its answer is not an object."""
        if not self._same_origin(url) or not allowed(url):
            parts = urlsplit(url)
            raise RemoteError(f"{self.name} named a place to send to that is not its own "
                              f"({self.plain(parts.scheme, folded=True)}://"
                              f"{self.plain(parts.hostname, folded=True)}); nothing was sent "
                              "there, since the token would go with it",
                              reached=False)  # fmt: skip
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json",
                   "User-Agent": f"manuscript-guard/{__version__}"}  # fmt: skip
        body = b""
        if document is not None:
            body = json.dumps(document, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = content_type or "application/json"
        elif data is not None:
            body = data
            headers["Content-Type"] = content_type or "application/octet-stream"
        try:
            answer = self.transport(Request(method, url, headers, body), self.timeout)
        except NoAnswer as exc:
            raise RemoteError(f"{self.name}: {self.plain(exc, folded=True)}",
                              reached=exc.reached) from None
        return self._read(answer, expect)

    def _read(self, answer: Response, expect: tuple[int, ...]) -> dict:
        status = answer.status
        if status in (401, 403):
            # Our words, not the host's: its message for a bad token can quote part of it.
            raise RemoteError(f"{self.name} refused the token in {self.token_env} (HTTP "
                              f"{status}): it may have expired, or lack the scope this needs",
                              reached=False)
        if 300 <= status < 400:
            raise RemoteError(f"{self.name} answered with a redirect (HTTP {status}), which is "
                              "not followed: it would carry the token and the files to "
                              "another place")  # fmt: skip
        if status not in expect:
            raise RemoteError(f"{self.name} answered HTTP {status}: "
                              f"{scrubbed(_said(answer.body), self.token)}")  # fmt: skip
        if len(answer.body) > MAX_BYTES:
            raise RemoteError(f"{self.name} answered with more than {MAX_BYTES} bytes")
        try:
            document = json.loads(answer.body) if answer.body.strip() else {}
        except (ValueError, RecursionError):
            raise RemoteError(f"{self.name} answered, but not with JSON") from None
        if not isinstance(document, dict):
            raise RemoteError(f"{self.name} answered, but not with a JSON object")
        return document


__all__ = ["Client", "NoAnswer", "RemoteError", "Request", "Response", "Transport",
           "allowed", "default_transport", "scrubbed", "token_from"]  # fmt: skip
