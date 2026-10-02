"""The one HTTP client: a request in the provider's shape, and its answer read back.

Two shapes cover every provider. Most speak the chat API OpenAI defined
(`POST <base>/chat/completions`, `Authorization: Bearer`); Anthropic speaks its own
(`POST <base>/messages`, `x-api-key`). Built on `urllib`, so the package gains no dependency.

What this module is careful about:

* **The key** goes into one header and nowhere else. It is not in the body, so the body can
  be printed by the dry run and digested into the record. Every message built from something
  a provider said is scrubbed of it, and a rejected key gets a message of our own, because a
  provider's message for a bad key can quote part of it.
* **Redirects are not followed.** One would carry the key and the manuscript to a host the
  author never agreed to.
* **Nothing is asked twice without a reason.** A rate limit or an overloaded server is
  retried, because no reply was produced. A timeout is not: the provider may have run the
  request and billed for it.
* **Only a finished reply is a reply.** One cut short by a token limit, refused, or stopped
  for any reason other than having finished is a failure, even when its text happens to
  parse.

The transport is an argument, so the tests answer from a list and never open a connection.
"""

from __future__ import annotations

import http.client
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from manuscript_guard import __version__
from manuscript_guard.panel.providers import ANTHROPIC, LOOPBACK, OPENAI, Model, usable_key

ANTHROPIC_VERSION = "2023-06-01"
#: Anthropic's API requires a cap. This one leaves room for a long review and is within what
#: its current models allow; `review.max_output_tokens` in paper.yaml replaces it.
ANTHROPIC_DEFAULT_MAX_TOKENS = 8192

#: A review of a whole manuscript by a model that reasons first can take minutes.
TIMEOUT_SECONDS = 600
RETRIES = 2
DEFAULT_WAIT_SECONDS = 10.0
MAX_WAIT_SECONDS = 60.0
#: No rate limit is worth waiting on for longer; the author can run the command again.
BUSY = frozenset({429, 503, 529})
MAX_BYTES = 8 * 1024 * 1024
SHOWN = 300
#: As few characters of a key in a row as are taken out of anything printed. A
#: provider's message for a bad key can quote its first and last few.
KEY_PART = 4


@dataclass(frozen=True)
class HttpRequest:
    url: str
    #: Holds the key, so it is left out of the request's printed form.
    headers: dict[str, str] = field(repr=False)
    body: bytes = field(repr=False, default=b"")


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[HttpRequest, float], HttpResponse]


class TransportError(Exception):
    """No answer came back: `kind` is "timeout" or "network"."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class CallFailed(Exception):
    """One call produced nothing that can be filed.

    `kind` says why, in a word a caller can branch on. `text` is what the model did write,
    where it wrote anything, so the author can read a reply that was refused.
    """

    def __init__(self, kind: str, message: str, text: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.text = text


@dataclass(frozen=True)
class Reply:
    text: str
    #: The provider's identifier for this response, where it gives one.
    response_id: str | None
    #: The model as the provider names it, which may be more exact than what was asked for.
    model: str | None
    finish: str
    input_tokens: int | None
    output_tokens: int | None


# ------------------------------------------------------------------------------ the request


def build_body(
    model: Model, system: str, user: str, *, max_output_tokens: int | None = None
) -> bytes:
    """The request body, as the bytes that are sent. It never holds the key.

    Nothing is set that the author did not ask for: no temperature, which some models
    refuse, and no streaming.
    """
    provider = model.provider
    if provider.api == ANTHROPIC:
        body: dict = {
            "model": model.name,
            "max_tokens": max_output_tokens or ANTHROPIC_DEFAULT_MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    else:
        body = {
            "model": model.name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if provider.json_mode:
            body["response_format"] = {"type": "json_object"}
        if max_output_tokens and provider.max_tokens_field:
            body[provider.max_tokens_field] = max_output_tokens
    return json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")


def endpoint(model: Model) -> str:
    path = "/messages" if model.provider.api == ANTHROPIC else "/chat/completions"
    return model.provider.base_url + path


def build_request(model: Model, body: bytes, *, key: str | None) -> HttpRequest:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"manuscript-guard/{__version__}",
    }
    if model.provider.api == ANTHROPIC:
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if key:
            headers["x-api-key"] = key
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    return HttpRequest(endpoint(model), headers, body)


# ---------------------------------------------------------------------------- the transport


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, so the 3xx comes back as the answer."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def _timed_out(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, TimeoutError) or "timed out" in str(reason)


def default_transport(request: HttpRequest, timeout: float) -> HttpResponse:
    """Send one request with `urllib`. A status that is not 2xx is an answer, not an error.

    A request to this machine goes to this machine: the proxy that `http_proxy` names in
    the environment is not used for it. With one set, as on many institutional networks,
    urllib handed a request for `http://localhost` to the proxy, body and all, while the
    author had been told that nothing leaves the machine.
    """
    handlers: list = [NoRedirect]
    if urlsplit(request.url).hostname in LOOPBACK:
        handlers.append(urllib.request.ProxyHandler({}))
    try:
        opener = urllib.request.build_opener(*handlers)
        outgoing = urllib.request.Request(
            request.url, data=request.body, headers=request.headers, method="POST"
        )
        try:
            with opener.open(outgoing, timeout=timeout) as response:
                body = response.read(MAX_BYTES + 1)
                # Reading a set number of bytes returns what arrived and says nothing when
                # the connection closed early, so the length the server declared is checked.
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and len(body) < min(int(declared), MAX_BYTES + 1):
                    raise TransportError("network", "the answer was cut off part way")
                return HttpResponse(response.status, dict(response.headers.items()), body)
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers.items()) if exc.headers else {}
            return HttpResponse(exc.code, headers, exc.read(MAX_BYTES + 1))
    except http.client.HTTPException as exc:
        # An answer cut off part way, or one that is not HTTP. Not an OSError.
        raise TransportError(
            "network", f"the answer could not be read ({type(exc).__name__})"
        ) from None
    except ValueError:
        # Raised while the request is built, and its words quote what it was built from:
        # for a header `http.client` will not send, the header, key and all. Never repeated.
        raise TransportError("network", "the request could not be made as written") from None
    except (urllib.error.URLError, OSError) as exc:
        if _timed_out(exc):
            raise TransportError("timeout", f"no answer within {timeout:g} s") from None
        raise TransportError("network", str(getattr(exc, "reason", exc))) from None


# ------------------------------------------------------------------------------- the answer


def without_key(text: str, key: str | None) -> str:
    """`text` with the key taken out, whole or in part.

    Any run of the key's characters, four or more in a row, becomes `[key]`: a provider's
    message for a bad key can quote the first and last few. A word that happens to share
    four characters with the key goes too, which costs a word of somebody else's message.
    """
    if not key:
        return text
    if len(key) < KEY_PART:
        return text.replace(key, "[key]")
    parts = {key[i : i + KEY_PART] for i in range(len(key) - KEY_PART + 1)}
    hidden = [False] * len(text)
    for start in range(len(text) - KEY_PART + 1):
        if text[start : start + KEY_PART] in parts:
            hidden[start : start + KEY_PART] = [True] * KEY_PART
    out: list[str] = []
    for index, char in enumerate(text):
        if not hidden[index]:
            out.append(char)
        elif index == 0 or not hidden[index - 1]:
            out.append("[key]")
    return "".join(out)


def _scrub(text: str, key: str | None) -> str:
    """Somebody else's words, fit to print: without the key or any part of it, without
    characters a terminal would act on, and not at length."""
    text = "".join(char if char.isprintable() else " " for char in without_key(text, key))
    text = " ".join(text.split())
    return text if len(text) <= SHOWN else text[:SHOWN] + "..."


def _header(response: HttpResponse, name: str) -> str | None:
    for found, value in response.headers.items():
        if found.lower() == name.lower():
            return value
    return None


def _wait(response: HttpResponse) -> float:
    try:
        asked = float(_header(response, "Retry-After") or "")
    except ValueError:
        return DEFAULT_WAIT_SECONDS
    if not math.isfinite(asked):
        return DEFAULT_WAIT_SECONDS
    return min(max(asked, 0.0), MAX_WAIT_SECONDS)


def _said(response: HttpResponse) -> str:
    """The provider's own account of an error, from wherever its body keeps one."""
    text = response.body[:4096].decode("utf-8", errors="replace")
    try:
        document = json.loads(response.body)
    except (ValueError, RecursionError):
        return text
    if isinstance(document, dict):
        error = document.get("error")
        for found in (
            error.get("message") if isinstance(error, dict) else error,
            document.get("message"),
            document.get("detail"),
        ):
            if isinstance(found, str) and found.strip():
                return found
    return text


def _refuse_status(model: Model, response: HttpResponse, key: str | None) -> CallFailed:
    provider = model.provider
    status = response.status
    if status in (401, 403):
        # Our words, not the provider's: its message for a bad key can quote part of the key.
        held = (
            f"the key in {provider.key_env}" if provider.key_env else "a request with no key"
        )
        return CallFailed(
            "auth", f"{provider.name} refused {held} (HTTP {status}) for {model.name}"
        )
    if 300 <= status < 400:
        return CallFailed(
            "rejected",
            f"{provider.host} answered with a redirect (HTTP {status}), which is not "
            "followed: it would carry the key and the manuscript to another host",
        )
    return CallFailed(
        "rejected", f"{provider.name} answered HTTP {status}: {_scrub(_said(response), key)}"
    )


def _count(usage: object, name: str) -> int | None:
    value = usage.get(name) if isinstance(usage, dict) else None
    # A count below zero is not a count, and the record's schema would refuse the reading.
    counted = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return value if counted else None


def _text_parts(content: object) -> str | None:
    """A reply's text, whether given as a string or as typed parts. None when it is neither.

    Parts that are not text (a reasoning model's thinking) are not the reply.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(part, dict) for part in content):
        parts = [part.get("text") for part in content if part.get("type") == "text"]
        texts = [part for part in parts if isinstance(part, str)]
        if len(texts) == len(parts):
            return "".join(texts)
    return None


def _unreadable(model: Model, why: str) -> CallFailed:
    return CallFailed(
        "unreadable", f"{model.provider.name} answered, but not in the documented shape: {why}"
    )


def _read_openai(model: Model, document: dict) -> tuple[str, str | None, str | None, object]:
    """The text, how the reply ended, a refusal if there was one, and the usage."""
    choices = document.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(choice, dict) or not isinstance(message, dict):
        raise _unreadable(model, "no choices[0].message")
    content = message.get("content")
    text = "" if content is None else _text_parts(content)
    if text is None:
        raise _unreadable(model, "choices[0].message.content is neither text nor text parts")
    refusal = message.get("refusal")
    finish = choice.get("finish_reason")
    return (
        text,
        finish if isinstance(finish, str) else None,
        refusal if isinstance(refusal, str) and refusal.strip() else None,
        document.get("usage"),
    )


def _read_anthropic(model: Model, document: dict) -> tuple[str, str | None, str | None, object]:
    content = document.get("content")
    text = _text_parts(content) if isinstance(content, list) else None
    if text is None:
        raise _unreadable(model, "no content blocks")
    stop = document.get("stop_reason")
    return text, stop if isinstance(stop, str) else None, None, document.get("usage")


#: How each API says a reply finished, was cut short, or was refused. Anything else (a tool
#: call, an abort, a reason this code has not met) is not a finished reply.
_ENDINGS = {
    OPENAI: ({"stop"}, {"length"}, {"content_filter"}, ("prompt_tokens", "completion_tokens")),
    ANTHROPIC: (
        {"end_turn"},
        {"max_tokens", "model_context_window_exceeded"},
        {"refusal"},
        ("input_tokens", "output_tokens"),
    ),
}


def read_reply(model: Model, response: HttpResponse, key: str | None = None) -> Reply:
    """Turn a 2xx answer into a `Reply`, or say why it is not one."""
    if len(response.body) > MAX_BYTES:
        raise _unreadable(model, f"more than {MAX_BYTES} bytes")
    try:
        document = json.loads(response.body)
    except (ValueError, RecursionError):
        raise _unreadable(model, "the body is not JSON") from None
    if not isinstance(document, dict):
        raise _unreadable(model, "the body is not an object")

    anthropic = model.provider.api == ANTHROPIC
    read = _read_anthropic if anthropic else _read_openai
    text, finish, refusal, usage = read(model, document)
    finished, cut, refused, (tokens_in, tokens_out) = _ENDINGS[ANTHROPIC if anthropic else OPENAI]

    who = model.reader
    if refusal or finish in refused:
        said = f": {_scrub(refusal, key)}" if refusal else ""
        raise CallFailed("refused", f"{who} declined to answer{said}", text)
    if finish in cut:
        raise CallFailed(
            "truncated",
            f"{who} stopped at its output limit ({finish}); a reply cut short is not filed. "
            "Raise review.max_output_tokens in paper.yaml, or use a model with more room",
            text,
        )
    if finish not in finished:
        raise CallFailed(
            "incomplete",
            f"{who} did not finish its reply (it stopped with "
            f"{_scrub(str(finish), key)[:80]!r})",
            text,
        )
    if not text.strip():
        raise CallFailed("empty", f"{who} answered with no text")

    response_id = document.get("id")
    named = document.get("model")
    return Reply(
        text=text,
        response_id=response_id if isinstance(response_id, str) else None,
        model=named if isinstance(named, str) else None,
        finish=finish,
        input_tokens=_count(usage, tokens_in),
        output_tokens=_count(usage, tokens_out),
    )


# --------------------------------------------------------------------------------- the call


def call(
    model: Model,
    body: bytes,
    *,
    key: str | None,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = RETRIES,
    timeout: float = TIMEOUT_SECONDS,
) -> Reply:
    """Send one request and return its finished reply, or raise `CallFailed`."""
    provider = model.provider
    if provider.key_env and not key:
        # The caller checks this before a run. Here it is the last place to stop a request
        # that would disclose the manuscript and be refused.
        raise CallFailed(
            "auth", f"{provider.key_env} is not set, so {provider.name} was not asked"
        )
    if key and not usable_key(key):
        held = f"the key in {provider.key_env}" if provider.key_env else "the key given"
        raise CallFailed(
            "auth",
            f"{held} holds a space, a line break or a character outside ASCII, which no "
            f"key has; {provider.name} was not asked",
        )
    send = transport or default_transport
    request = build_request(model, body, key=key)
    for attempt in range(retries + 1):
        try:
            response = send(request, timeout)
        except TransportError as exc:
            where = f"{model.provider.name} ({model.provider.host})"
            if exc.kind == "timeout":
                raise CallFailed(
                    "timeout",
                    f"{where}: {_scrub(str(exc), key)}. Not asked again: the request may "
                    "have run and been billed",
                ) from None
            raise CallFailed(
                "network", f"could not reach {where}: {_scrub(str(exc), key)}"
            ) from None

        if response.status in BUSY:
            if attempt < retries:
                sleep(_wait(response))
                continue
            raise CallFailed(
                "busy",
                f"{model.provider.name} was rate-limited or overloaded (HTTP "
                f"{response.status}) on {retries + 1} attempts",
            )
        if not 200 <= response.status < 300:
            raise _refuse_status(model, response, key)
        return read_reply(model, response, key)
    raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover


__all__ = [
    "ANTHROPIC_DEFAULT_MAX_TOKENS",
    "ANTHROPIC_VERSION",
    "DEFAULT_WAIT_SECONDS",
    "MAX_WAIT_SECONDS",
    "CallFailed",
    "HttpRequest",
    "HttpResponse",
    "NoRedirect",
    "Reply",
    "TransportError",
    "build_body",
    "build_request",
    "call",
    "default_transport",
    "endpoint",
    "read_reply",
    "without_key",
]
