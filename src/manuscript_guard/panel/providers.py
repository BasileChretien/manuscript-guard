"""Where a review can be sent: the built-in providers, and any the author adds by URL.

One client speaks to all of them, because all but one offer the same chat API. A preset is
therefore four facts and no code: the base URL, the name of the environment variable that
holds the key, which of the two API shapes it speaks, and how it spells an output cap.

Every preset was read from the vendor's own documentation on 2026-10-02, and
`tests/test_review_providers.py` holds the table. **No preset names a model.** Model names
change faster than this toolkit is released, so the author supplies them: `openai/<model>`.

A key is read from the environment at the moment of a call and goes into one request header.
It is never written to a file, a record, a log or a message; the functions here only say
whether a variable is set.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

OPENAI = "openai"
ANTHROPIC = "anthropic"
APIS = (OPENAI, ANTHROPIC)

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})

NAME = re.compile(r"[a-z][a-z0-9-]*")
#: Environment variables are upper case by convention, and a key is not. Holding `key_env` to
#: the convention is what stops a key pasted there from being accepted as a variable's name,
#: committed with paper.yaml, and printed by the message that says the variable is unset.
KEY_ENV = re.compile(r"[A-Z][A-Z0-9_]*")
#: Visible ASCII and nothing else: what an address or a key is made of.
PRINTABLE = re.compile("[!-~]+")
#: A host name as it is connected to: no percent sign, which urllib would decode.
HOSTNAME = re.compile("[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9.])?")


class ConfigError(Exception):
    """`review.models` or `review.providers` cannot be used as written."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    #: The variable holding the key, or None for a provider that takes none.
    key_env: str | None
    api: str = OPENAI
    #: Whether the vendor documents `response_format: {"type": "json_object"}`.
    json_mode: bool = False
    #: The request field that caps the output, where the vendor documents one.
    max_tokens_field: str | None = "max_tokens"
    builtin: bool = False

    @property
    def host(self) -> str:
        """What the author is shown before anything is sent: the host, with its port."""
        return urlsplit(self.base_url).netloc

    @property
    def local(self) -> bool:
        """Whether a call stays on this machine."""
        return urlsplit(self.base_url).hostname in LOOPBACK


@dataclass(frozen=True)
class Model:
    provider: Provider
    name: str

    @property
    def reader(self) -> str:
        """The name a reading by this model is filed under: `provider/model`."""
        return f"{self.provider.name}/{self.name}"


def _preset(name: str, base_url: str, key_env: str | None, **facts) -> Provider:
    return Provider(name=name, base_url=base_url, key_env=key_env, builtin=True, **facts)


_MOONSHOT = {"json_mode": True, "max_tokens_field": "max_completion_tokens"}

PRESETS: dict[str, Provider] = {
    preset.name: preset
    for preset in (
        _preset(
            "openai",
            "https://api.openai.com/v1",
            "OPENAI_API_KEY",
            json_mode=True,
            max_tokens_field="max_completion_tokens",
        ),
        _preset("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", json_mode=True),
        # Kimi is Moonshot AI's model family. The platform has two hosts with separate
        # accounts and keys: `.ai` outside mainland China and `.cn` inside it.
        _preset("moonshot", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", **_MOONSHOT),
        _preset("kimi", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", **_MOONSHOT),
        _preset("moonshot-cn", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY", **_MOONSHOT),
        _preset("deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", json_mode=True),
        # OpenRouter passes `response_format` on only to the models that take it, so the
        # prompt alone asks for JSON there.
        _preset("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        # Google documents neither JSON mode nor an output cap for this endpoint, and says
        # it ignores what it does not list.
        _preset(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
            max_tokens_field=None,
        ),
        # A model run on this machine: no key, and the manuscript goes nowhere.
        _preset("ollama", "http://localhost:11434/v1", None, json_mode=True),
        _preset("anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", api=ANTHROPIC),
    )
}


def _review(paper: Mapping) -> Mapping:
    review = paper.get("review") if isinstance(paper, Mapping) else None
    return review if isinstance(review, Mapping) else {}


def _checked_url(name: str, url: object) -> str:
    """A URL a key and a manuscript may be sent to, without its trailing slash."""
    if not isinstance(url, str) or not url.strip():
        raise ConfigError(f"review.providers.{name} needs a base_url")
    if not PRINTABLE.fullmatch(url):
        raise ConfigError(
            f"review.providers.{name}: base_url holds a space, a line break or a character "
            "outside ASCII; write the address as plain characters"
        )
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        # `http://[::1:11434/v1`, with its bracket missing, or a port that is not a number.
        raise ConfigError(
            f"review.providers.{name}: base_url cannot be read as an address ({exc})"
        ) from None
    if not parts.hostname:
        raise ConfigError(f"review.providers.{name}: base_url names no host")
    if parts.username or parts.password:
        raise ConfigError(
            f"review.providers.{name}: base_url carries a user name or password; the key "
            "comes from the environment variable named in key_env"
        )
    # The authority has to be one host and at most a port, and nothing else. What decides
    # whether a call stays on this machine is the host, and `http://[::1].evil.example` and
    # `http://@localhost` each have a host that is not what the address appears to say.
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if parts.netloc.lower() != host + (f":{port}" if port is not None else ""):
        raise ConfigError(
            f"review.providers.{name}: base_url must name one host, with a port if it needs "
            "one, and nothing else before the path"
        )
    # And the host has to be written as the host that is connected to. urllib decodes a
    # percent-encoded host before it connects, so `api.openai.com%2e%65%76%69%6c.example`
    # was shown to the author as written and reached `api.openai.com.evil.example`.
    if ":" in parts.hostname:
        try:
            ipaddress.IPv6Address(parts.hostname)
        except ValueError:
            written = False
        else:
            written = True
    else:
        written = HOSTNAME.fullmatch(parts.hostname) is not None
    if not written:
        raise ConfigError(
            f"review.providers.{name}: the host in base_url must be written in letters, "
            "digits, dots and hyphens, or as a bracketed address, with nothing encoded"
        )
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise ConfigError(
            f"review.providers.{name}: base_url carries a query string; give the address "
            "the chat endpoint sits under and nothing more"
        )
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK):
        raise ConfigError(
            f"review.providers.{name}: base_url must be https. Plain http is taken only for "
            "this machine (localhost), because a key and an unpublished manuscript would "
            "otherwise cross the network unencrypted"
        )
    return url.rstrip("/")


def _custom(name: str, entry: object) -> Provider:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ConfigError(
            "a name under review.providers is lower-case letters, digits and hyphens, "
            "starting with a letter"
        )
    if name in PRESETS:
        raise ConfigError(
            f"review.providers.{name}: {name!r} is built in and cannot be pointed somewhere "
            "else; give your endpoint a name of its own"
        )
    if not isinstance(entry, Mapping):
        raise ConfigError(f"review.providers.{name} needs a base_url")

    key_env = entry.get("key_env")
    if key_env is not None and not (isinstance(key_env, str) and KEY_ENV.fullmatch(key_env)):
        # The value is not repeated: if it is not a variable's name, it may be a key.
        raise ConfigError(
            f"review.providers.{name}: key_env is the NAME of the environment variable that "
            "holds the key (upper-case letters, digits and underscores), never the key"
        )
    taken = sorted(preset.name for preset in PRESETS.values() if preset.key_env == key_env)
    if key_env is not None and taken:
        # The other half of not letting a built-in name be pointed elsewhere: a paper.yaml
        # somebody else wrote could name the reader's OpenAI key under a provider of its own
        # and have it sent to its host.
        raise ConfigError(
            f"review.providers.{name}: {key_env} is the key of the built-in provider "
            f"{taken[0]}, and is sent only there. Give this provider a variable of its own"
        )
    api = entry.get("api", OPENAI)
    if api not in APIS:
        raise ConfigError(f"review.providers.{name}: api is one of {', '.join(APIS)}")
    return Provider(name, _checked_url(name, entry.get("base_url")), key_env, api=api)


def known_providers(paper: Mapping) -> dict[str, Provider]:
    """The presets, and whatever the project adds under `review.providers`."""
    extra = _review(paper).get("providers") or {}
    if not isinstance(extra, Mapping):
        raise ConfigError(
            "review.providers holds one entry for each provider that is not built in: its "
            "name, and under it a base_url"
        )
    return {**PRESETS, **{name: _custom(name, entry) for name, entry in extra.items()}}


def configured_models(paper: Mapping) -> tuple[Model, ...]:
    """The models `review.models` lists, in the order written. Empty when it lists none."""
    listed = _review(paper).get("models")
    known = known_providers(paper)
    if listed is None:
        return ()
    if not isinstance(listed, list):
        raise ConfigError("review.models is a list: [provider/model, provider/model]")

    found: list[Model] = []
    for entry in listed:
        provider, slash, name = entry.partition("/") if isinstance(entry, str) else ("", "", "")
        if not slash or not provider or not name.strip() or name != name.strip():
            raise ConfigError(
                f"review.models: {entry!r} is not provider/model, for example openai/<model>"
            )
        if provider not in known:
            raise ConfigError(
                f"review.models: no provider called {provider!r}. Built in: "
                f"{', '.join(sorted(PRESETS))}. Any other is added under review.providers "
                "with its base_url"
            )
        model = Model(known[provider], name)
        if model in found:
            raise ConfigError(
                f"review.models lists {entry} twice; a second reading by the same model is "
                "the same reading paid for again"
            )
        found.append(model)
    return tuple(found)


def key_is_set(provider: Provider, environ: Mapping[str, str] | None = None) -> bool | None:
    """Whether the provider's key is in the environment. None when it takes no key.

    The answer is all that leaves this function: not the key, its length or any part of it.
    """
    if provider.key_env is None:
        return None
    environ = os.environ if environ is None else environ
    return bool(environ.get(provider.key_env, "").strip())


def read_key(provider: Provider, environ: Mapping[str, str] | None = None) -> str | None:
    """The key itself, for the one header it goes into. None when unset or not needed.

    A key that holds a space, a line break or a character outside ASCII is refused here, by
    the variable's name. No provider issues one, so it is a variable set wrongly, and it
    must not reach a header: `http.client` refuses such a header with a message that quotes
    it, key and all.
    """
    if provider.key_env is None:
        return None
    environ = os.environ if environ is None else environ
    key = environ.get(provider.key_env, "").strip()
    if key and not usable_key(key):
        raise ConfigError(
            f"the key in {provider.key_env} holds a space, a line break or a character "
            "outside ASCII, which no key has. Check how the variable was set; nothing was sent"
        )
    return key or None


def usable_key(key: str) -> bool:
    """Whether a key can go into a request header as it is."""
    return PRINTABLE.fullmatch(key) is not None


def slug(reader: str) -> str:
    """A reader's name as part of a file name: `openai/gpt-x.1` becomes `openai-gpt-x-1`."""
    return re.sub(r"[^a-z0-9]+", "-", reader.lower()).strip("-")


__all__ = [
    "ANTHROPIC",
    "OPENAI",
    "PRESETS",
    "ConfigError",
    "Model",
    "Provider",
    "configured_models",
    "key_is_set",
    "known_providers",
    "read_key",
    "slug",
    "usable_key",
]
