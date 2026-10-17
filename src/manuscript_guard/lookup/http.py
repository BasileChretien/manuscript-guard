"""One GET, and its answer as it came: what `lookup` asks the registries with.

What this is careful about:

* **A key or an address travels and is never kept.** NCBI's key, OpenAlex's key and the
  contact address Crossref and NCBI ask for go in the query string. The request keeps them
  apart from the URL that is printed or recorded (`Request.shown`), and no message built here
  quotes the URL that was sent.
* **Redirects are not followed.** One would carry the key to a host nobody chose; the 3xx
  comes back as the answer, and an answer of that kind is no answer.
* **https only,** except to this machine, which is how the tests answer: a loopback server
  stands in for every registry, and no test opens a connection to one.

The transport is an argument, so a test can answer from a table or from a server on a
loopback port.
"""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

from manuscript_guard import __version__

TIMEOUT_SECONDS = 30.0
MAX_BYTES = 4 * 1024 * 1024
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class Request:
    """A GET: the URL without its query, the query's open part, and its secret part."""

    base: str
    params: Mapping[str, str] = field(default_factory=dict)
    #: The key and the contact address: sent, never printed, never recorded.
    secret: Mapping[str, str] = field(default_factory=dict, repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    @property
    def url(self) -> str:
        query = {**self.params, **{k: v for k, v in self.secret.items() if v}}
        return f"{self.base}?{urlencode(query)}" if query else self.base

    @property
    def shown(self) -> str:
        """What may be printed of it: the URL and its open part only."""
        return f"{self.base}?{urlencode(self.params)}" if self.params else self.base


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


class NoAnswer(Exception):
    """No answer came back. The message is ours, and quotes no URL."""


Transport = Callable[[Request, float], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def user_agent(contact: str | None) -> str:
    """Crossref asks for a contact in the User-Agent as well as in `mailto`."""
    agent = f"manuscript-guard/{__version__}"
    return f"{agent} (mailto:{contact})" if contact else agent


def default_transport(request: Request, timeout: float) -> Response:
    """Send one GET with `urllib`. A status that is not 2xx is an answer, not an error."""
    parts = urlsplit(request.base)
    local = parts.hostname in LOOPBACK
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise NoAnswer(f"refused to send a request to {parts.scheme}://{parts.hostname}")
    handlers: list = [_NoRedirect]
    if local:
        # The proxy that `http_proxy` names is not asked for this machine.
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    outgoing = urllib.request.Request(request.url, headers=dict(request.headers), method="GET")
    try:
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
        raise NoAnswer("the request could not be made as written") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise NoAnswer(f"no answer within {timeout:g} s") from None
        raise NoAnswer(f"no connection to {parts.hostname}") from None


__all__ = ["NoAnswer", "Request", "Response", "Transport", "default_transport", "user_agent"]
