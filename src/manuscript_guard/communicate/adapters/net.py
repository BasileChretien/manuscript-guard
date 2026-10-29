"""One request to a service, and its answer read back: what each adapter sends with.

It is `deposit/remote/http.py`'s transport, under the same rules: https only, but to this
machine; no redirect followed; a link a service gives followed nowhere. Two things are its
own:

* **No request leaves the machine while `MANUSCRIPT_GUARD_NO_NETWORK` is set.** The test
  suite sets it, so that a test that forgot to give its own transport fails rather than
  posting. A loopback test gives the sending transport itself.
* **Every secret is kept out of what is printed and written**: an app password, a token, a
  handle that may be an e-mail address, the session's own tokens. A message built from what
  a service said is scrubbed of each, whole or in part (`scrubbed`), and a service's words
  for refused credentials are replaced by ours, since they can quote them.

A service that asks to be given time (HTTP 429) is waited for once, as long as it says up to
`RETRY_AFTER_MAX` seconds, and asked again; a second 429 is the answer. Nothing it was asked
was done, so a run again later is safe.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from urllib.parse import urlencode

from manuscript_guard import __version__
from manuscript_guard.deposit.remote import http
from manuscript_guard.deposit.remote.http import (
    NoAnswer,
    RemoteError,
    Request,
    Response,
    Transport,
    allowed,
    scrubbed,
)

#: Set, to anything, no request is sent: the test suite sets it.
NO_NETWORK = "MANUSCRIPT_GUARD_NO_NETWORK"
TIMEOUT_SECONDS = 60.0
#: The longest a service's "try again after" is waited for, in seconds; longer is refused.
RETRY_AFTER_MAX = 30.0
#: How long to wait where a 429 says nothing of when to come back.
RETRY_AFTER_DEFAULT = 5.0
#: The longest value a service answered that is recorded whole, an id or a link.
MAX_KEPT = 2000
#: As many characters of a secret in a row as make a value a service returned one that is
#: recorded nowhere.
SECRET_STRETCH = 8


@dataclass(frozen=True)
class Image:
    """An image a post carries: its file's name, its bytes, its type and its alternative
    text, as printed."""

    name: str
    data: bytes = field(repr=False)
    content_type: str
    alt: str


#: The images a post can carry, by the file's suffix: what Bluesky and Mastodon both take.
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}  # fmt: skip


class Answered(RemoteError):
    """The service answered a request with a status that is not taken: `status` is it, and
    `error` the name its body gives the error (atproto's `error`, `RecordNotFound`), or None."""

    def __init__(self, message: str, *, status: int, reached: bool,
                 error: str | None = None) -> None:  # fmt: skip
        super().__init__(message, reached=reached)
        self.status = status
        self.error = error


def default_transport(request: Request, timeout: float) -> Response:
    """Send one request, unless `MANUSCRIPT_GUARD_NO_NETWORK` is set."""
    if os.environ.get(NO_NETWORK, "").strip():
        raise NoAnswer(f"{NO_NETWORK} is set, so no request leaves this machine",
                       reached=False)  # fmt: skip
    return http.default_transport(request, timeout)


def error_of(body: bytes) -> str | None:
    """The name a service's body gives an error, `{"error": "RecordNotFound"}`, or None."""
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        return None
    found = document.get("error") if isinstance(document, dict) else None
    return found if isinstance(found, str) else None


def said_of(body: bytes) -> str:
    """A service's own account of an error, from wherever its body keeps one: atproto's
    `message`, Mastodon's `error`."""
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        return body[:4096].decode("utf-8", errors="replace")
    if isinstance(document, dict):
        for key in ("message", "error_description", "error", "detail"):
            found = document.get(key)
            if isinstance(found, str) and found.strip():
                return found
    return body[:4096].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Api:
    """A service, as one origin, the secrets nothing it says may carry into a message, and
    the names of the variables its credentials are read from."""

    name: str
    origin: str
    credentials: str
    secrets: tuple[str, ...] = field(default=(), repr=False)
    transport: Transport = default_transport
    timeout: float = TIMEOUT_SECONDS
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if not allowed(self.origin):
            raise RemoteError(f"{self.name}: its address must be https (plain http only to "
                              "this machine); nothing was sent", reached=False)  # fmt: skip

    def holding(self, secret: str) -> Api:
        """The same service, with one more secret kept out of every message: a session's
        token once it is given."""
        return replace(self, secrets=(*self.secrets, secret))

    def plain(self, said: object) -> str:
        """Anything a service returned, fit for a message: no secret in it, whole or in part,
        in either case; no character a terminal acts on; not at length."""
        text = str(said)
        for secret in self.secrets:
            text = scrubbed(text, secret, folded=True)
        return scrubbed(text, None)

    def kept(self, what: str, said: object) -> str:
        """A string the service returned that is recorded whole, an id, a URI or a link;
        refused where it is none, or holds a stretch of a secret, or a character a terminal
        acts on."""
        if not isinstance(said, (str, int)) or isinstance(said, bool) or str(said) == "":
            raise RemoteError(f"{self.name} answered no {what}")
        said = str(said)
        if len(said) > MAX_KEPT or not said.isprintable():
            raise RemoteError(f"{self.name} answered a {what} that is not one")
        for secret in self.secrets:
            stretches = {secret[i : i + SECRET_STRETCH]
                         for i in range(max(len(secret) - SECRET_STRETCH + 1, 1))}  # fmt: skip
            if any(part.lower() in said.lower() for part in stretches):
                raise RemoteError(f"{self.name} answered a {what} that holds part of a secret; "
                                  "it is recorded nowhere")  # fmt: skip
        return said

    def url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        return self.origin.rstrip("/") + path + (f"?{urlencode(query)}" if query else "")

    def call(self, method: str, path: str, *, document: object = None,
             data: bytes | None = None, content_type: str | None = None,
             headers: Mapping[str, str] | None = None, bearer: str | None = None,
             query: Mapping[str, str] | None = None, expect: tuple[int, ...] = (200,),
             ) -> dict:  # fmt: skip
        """Send one request and return the JSON object it answered with; `RemoteError` where
        no answer came, the service refused, or its answer is no object. `reached` on the
        error is False where nothing can have been done: never sent, refused before it was
        acted on (a 4xx), or the credentials refused."""
        sent = {"Accept": "application/json", "User-Agent": f"manuscript-guard/{__version__}",
                **(headers or {})}  # fmt: skip
        if bearer is not None:
            sent["Authorization"] = f"Bearer {bearer}"
        body = b""
        if document is not None:
            body = json.dumps(document, ensure_ascii=False).encode("utf-8")
            sent["Content-Type"] = content_type or "application/json"
        elif data is not None:
            body = data
            sent["Content-Type"] = content_type or "application/octet-stream"
        request = Request(method, self.url(path, query), sent, body)
        answer = self._send(request)
        if answer.status == 429:
            self.sleep(self._wait(answer))
            answer = self._send(request)
        return self._read(answer, expect)

    def _send(self, request: Request) -> Response:
        try:
            return self.transport(request, self.timeout)
        except NoAnswer as exc:
            raise RemoteError(f"{self.name}: {self.plain(exc)}", reached=exc.reached) from None

    def _wait(self, answer: Response) -> float:
        said = {key.lower(): value for key, value in answer.headers.items()}.get("retry-after")
        try:
            seconds = float(said) if said is not None else RETRY_AFTER_DEFAULT
        except ValueError:
            seconds = RETRY_AFTER_DEFAULT
        if not math.isfinite(seconds):  # `nan` or `inf`: read as no header
            seconds = RETRY_AFTER_DEFAULT
        if seconds > RETRY_AFTER_MAX or seconds < 0:
            raise RemoteError(f"{self.name} asked to be given {said} seconds (HTTP 429); nothing "
                              "was done, so run it again later", reached=False)  # fmt: skip
        return seconds

    def _read(self, answer: Response, expect: tuple[int, ...]) -> dict:
        status = answer.status
        if status in (401, 403):
            # Our words, not the service's: its message for refused credentials can quote them.
            raise RemoteError(f"{self.name} refused the credentials in {self.credentials} (HTTP "
                              f"{status}): they may be wrong, expired or revoked",
                              reached=False)  # fmt: skip
        if status == 429:
            raise RemoteError(f"{self.name} asked again to be given time (HTTP 429); nothing "
                              "was done, so run it again later", reached=False)  # fmt: skip
        if 300 <= status < 400:
            raise RemoteError(f"{self.name} answered with a redirect (HTTP {status}), which is "
                              "not followed: it would carry the credentials elsewhere")
        if status not in expect:
            raise Answered(f"{self.name} answered HTTP {status}: "
                           f"{self.plain(said_of(answer.body))}", status=status,
                           reached=status >= 500, error=error_of(answer.body))  # fmt: skip
        if len(answer.body) > http.MAX_BYTES:
            raise RemoteError(f"{self.name} answered with more than {http.MAX_BYTES} bytes")
        try:
            document = json.loads(answer.body) if answer.body.strip() else {}
        except (ValueError, RecursionError):
            raise RemoteError(f"{self.name} answered, but not with JSON") from None
        if not isinstance(document, dict):
            raise RemoteError(f"{self.name} answered, but not with a JSON object")
        return document


__all__ = ["IMAGE_TYPES", "NO_NETWORK", "Answered", "Api", "Image", "RemoteError",
           "default_transport", "error_of", "said_of"]  # fmt: skip
