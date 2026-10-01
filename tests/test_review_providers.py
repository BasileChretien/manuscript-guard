"""The provider layer: where a review can be sent, and the one client that sends it.

A review panel drawn from one model shares that model's blind spots, so the panel can be read
by several. Nothing here is a gate, and no gate imports it: a provider's reply is untrusted
input that becomes a review record only after it has been validated, and G11 reads records.

No test in this file opens a connection. The client takes its transport as an argument, and
the tests hand it one that answers from a list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.contracts._schema import validate
from manuscript_guard.panel import client, providers
from manuscript_guard.panel.client import CallFailed, HttpResponse, TransportError
from manuscript_guard.panel.providers import ConfigError
from manuscript_guard.panel.reply import ReplyRefused, parse_reply

KEY = "sk-test-0123456789abcdefSECRET"


def paper(**review) -> dict:
    return {
        "schema": "manuscript-guard/paper/1",
        "title": "A paper",
        "english_variant": "en-GB",
        "review": review,
    }


def model(name: str, **review):
    return providers.configured_models(paper(models=[name], **review))[0]


# ------------------------------------------------------------------------------- presets


@pytest.mark.parametrize(
    "name, base_url, key_env, api",
    [
        ("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "openai"),
        ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "openai"),
        ("moonshot", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", "openai"),
        ("moonshot-cn", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY", "openai"),
        ("deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "openai"),
        ("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai"),
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "GEMINI_API_KEY",
            "openai",
        ),
        ("ollama", "http://localhost:11434/v1", None, "openai"),
        ("anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "anthropic"),
    ],
)
def test_a_preset_carries_what_its_vendor_documents(name, base_url, key_env, api) -> None:
    """Each row was read from the vendor's own documentation on 2026-10-02. The table is here
    so that a careless edit of a preset shows up as a failing test with the old value in it."""
    preset = providers.PRESETS[name]
    assert (preset.base_url, preset.key_env, preset.api) == (base_url, key_env, api)


def test_kimi_is_another_name_for_moonshot() -> None:
    assert providers.PRESETS["kimi"].base_url == providers.PRESETS["moonshot"].base_url
    assert providers.PRESETS["kimi"].key_env == "MOONSHOT_API_KEY"


def test_no_preset_names_a_model() -> None:
    """Model names change faster than this toolkit is released; the author supplies them."""
    for preset in providers.PRESETS.values():
        assert not hasattr(preset, "model")
        assert not hasattr(preset, "default_model")


# --------------------------------------------------------------------------- configuration


def test_a_model_is_named_provider_slash_model() -> None:
    found = providers.configured_models(paper(models=["mistral/some-model"]))
    assert [(m.provider.name, m.name, m.reader) for m in found] == [
        ("mistral", "some-model", "mistral/some-model")
    ]


def test_only_the_first_slash_separates_the_provider() -> None:
    """OpenRouter's own model names hold a slash."""
    found = model("openrouter/vendor/some-model")
    assert (found.provider.name, found.name) == ("openrouter", "vendor/some-model")


def test_no_models_is_an_empty_list_not_an_error() -> None:
    assert providers.configured_models(paper()) == ()
    assert providers.configured_models({"title": "no review block"}) == ()


def test_an_unknown_provider_is_refused_and_the_known_ones_named() -> None:
    with pytest.raises(ConfigError) as refused:
        providers.configured_models(paper(models=["nosuch/model"]))
    assert "nosuch" in str(refused.value)
    assert "openai" in str(refused.value) and "review.providers" in str(refused.value)


@pytest.mark.parametrize("entry", ["justamodel", "/model", "openai/", "openai/ "])
def test_an_entry_without_both_halves_is_refused(entry: str) -> None:
    with pytest.raises(ConfigError):
        providers.configured_models(paper(models=[entry]))


def test_the_same_model_twice_is_refused() -> None:
    """Two readings by one model are one reading paid for twice."""
    with pytest.raises(ConfigError, match="twice"):
        providers.configured_models(paper(models=["openai/m", "openai/m"]))


def test_a_provider_that_is_not_built_in_is_given_by_its_url() -> None:
    found = model(
        "lab/some-model",
        providers={"lab": {"base_url": "https://llm.example.org/v1", "key_env": "LAB_KEY"}},
    )
    assert found.provider.base_url == "https://llm.example.org/v1"
    assert found.provider.key_env == "LAB_KEY"
    assert found.provider.api == "openai"
    assert not found.provider.builtin


def test_a_trailing_slash_on_the_url_changes_nothing() -> None:
    found = model("lab/m", providers={"lab": {"base_url": "https://llm.example.org/v1/"}})
    assert found.provider.base_url == "https://llm.example.org/v1"


def test_a_built_in_name_cannot_be_pointed_somewhere_else() -> None:
    """`openai` in a project somebody else wrote must mean OpenAI: a paper.yaml that moved it
    would send the reader's OpenAI key, and their manuscript, to a host of its choosing."""
    with pytest.raises(ConfigError, match="built in"):
        providers.configured_models(
            paper(
                models=["openai/m"],
                providers={"openai": {"base_url": "https://elsewhere.example/v1"}},
            )
        )


@pytest.mark.parametrize(
    "url, why",
    [
        ("http://llm.example.org/v1", "https"),
        ("ftp://llm.example.org/v1", "https"),
        ("https://user:pass@llm.example.org/v1", "user"),
        ("https://llm.example.org/v1?key=abc", "query"),
        ("https:///v1", "host"),
    ],
)
def test_a_url_a_key_should_not_travel_to_is_refused(url: str, why: str) -> None:
    with pytest.raises(ConfigError, match=why):
        providers.configured_models(
            paper(models=["lab/m"], providers={"lab": {"base_url": url}})
        )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_plain_http_is_allowed_to_this_machine_only(host: str) -> None:
    found = model("local/m", providers={"local": {"base_url": f"http://{host}:8080/v1"}})
    assert found.provider.local


def test_a_remote_provider_is_not_local() -> None:
    assert not providers.PRESETS["openai"].local
    assert providers.PRESETS["ollama"].local


def test_the_host_is_what_the_author_is_shown() -> None:
    assert providers.PRESETS["openrouter"].host == "openrouter.ai"
    assert providers.PRESETS["ollama"].host == "localhost:11434"


# ------------------------------------------------------------------------------ the schema


def test_paper_yaml_takes_the_list_and_the_extra_provider(tmp_path: Path) -> None:
    document = paper(
        rounds_required=2,
        models=["openai/a", "mistral/b"],
        providers={"lab": {"base_url": "https://llm.example.org/v1", "key_env": "LAB_KEY"}},
        max_output_tokens=4000,
    )
    assert validate(document, "paper", tmp_path / "paper.yaml").ok


@pytest.mark.parametrize(
    "review",
    [
        {"models": ["no-slash"]},
        {"models": ["openai/a", "openai/a"]},
        {"models": "openai/a"},
        {"providers": {"lab": {"key_env": "LAB_KEY"}}},
        {"providers": {"lab": {"base_url": "https://x.example", "api": "gemini"}}},
        {"providers": {"lab": {"base_url": "https://x.example", "api_key": "abc"}}},
        {"providers": {"Lab": {"base_url": "https://x.example"}}},
        {"api_key": "abc"},
    ],
)
def test_paper_yaml_refuses_what_the_tool_would_not_understand(review, tmp_path: Path) -> None:
    assert not validate(paper(**review), "paper", tmp_path / "paper.yaml").ok


def test_a_key_pasted_where_the_variable_name_goes_is_refused(tmp_path: Path) -> None:
    """`key_env` names a variable. A key written there would sit in a committed file, and the
    message saying the variable is unset would print it. Variable names are upper case."""
    document = paper(providers={"lab": {"base_url": "https://x.example", "key_env": KEY}})
    assert not validate(document, "paper", tmp_path / "paper.yaml").ok
    with pytest.raises(ConfigError) as refused:
        providers.configured_models(
            paper(models=["lab/m"], providers=document["review"]["providers"])
        )
    assert KEY not in str(refused.value)


# ------------------------------------------------------------------------------- the keys


def test_a_key_is_set_unset_or_not_needed() -> None:
    openai = providers.PRESETS["openai"]
    assert providers.key_is_set(openai, {"OPENAI_API_KEY": KEY}) is True
    assert providers.key_is_set(openai, {}) is False
    assert providers.key_is_set(openai, {"OPENAI_API_KEY": "  "}) is False
    assert providers.key_is_set(providers.PRESETS["ollama"], {}) is None


def test_listing_the_providers_never_prints_a_key(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    assert main(["review", str(tmp_path), "--providers"]) == 0
    out = capsys.readouterr().out
    assert KEY not in out and KEY[-6:] not in out
    lines = {line.split()[0]: line for line in out.splitlines() if line.strip()}
    assert "OPENAI_API_KEY" in lines["openai"] and "set" in lines["openai"].split()
    assert "MISTRAL_API_KEY" in lines["mistral"] and "unset" in lines["mistral"].split()
    assert "localhost:11434" in lines["ollama"]


def test_listing_says_which_configured_models_are_ready(
    monkeypatch, capsys, project: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    path = project / "paper.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nreview:\n  models: [openai/model-a, mistral/model-b]\n",
        encoding="utf-8",
    )
    assert main(["review", str(project), "--providers"]) == 0
    out = capsys.readouterr().out
    assert KEY not in out
    ready = next(line for line in out.splitlines() if "openai/model-a" in line)
    waiting = next(line for line in out.splitlines() if "mistral/model-b" in line)
    assert "ready" in ready
    assert "MISTRAL_API_KEY" in waiting and "not set" in waiting


def test_listing_reports_a_paper_yaml_it_cannot_read(capsys, tmp_path: Path) -> None:
    """Not the same as no project: showing the presets alone would hide the broken file."""
    (tmp_path / "paper.yaml").write_text("title: [unclosed\n", encoding="utf-8")
    assert main(["review", str(tmp_path), "--providers"]) == 2
    assert "paper.yaml" in capsys.readouterr().err


def test_listing_reports_a_bad_list_rather_than_crashing(capsys, project: Path) -> None:
    path = project / "paper.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nreview:\n  models: [nosuch/model]\n",
        encoding="utf-8",
    )
    assert main(["review", str(project), "--providers"]) == 2
    assert "nosuch" in capsys.readouterr().err


# ---------------------------------------------------------------------------- the request


def test_an_openai_style_request(monkeypatch) -> None:
    found = model("mistral/some-model")
    body = client.build_body(found, "the system text", "the user text")
    request = client.build_request(found, body, key=KEY)
    assert request.url == "https://api.mistral.ai/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.headers["Content-Type"] == "application/json"
    sent = json.loads(request.body)
    assert sent["model"] == "some-model"
    assert sent["messages"] == [
        {"role": "system", "content": "the system text"},
        {"role": "user", "content": "the user text"},
    ]
    assert sent["response_format"] == {"type": "json_object"}
    assert "stream" not in sent and "temperature" not in sent


def test_an_anthropic_request() -> None:
    found = model("anthropic/some-model")
    body = client.build_body(found, "the system text", "the user text")
    request = client.build_request(found, body, key=KEY)
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == KEY
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in request.headers
    sent = json.loads(request.body)
    assert sent["model"] == "some-model"
    assert sent["system"] == "the system text"
    assert sent["messages"] == [{"role": "user", "content": "the user text"}]
    assert sent["max_tokens"] == client.ANTHROPIC_DEFAULT_MAX_TOKENS


def test_the_key_is_in_a_header_and_nowhere_in_the_body() -> None:
    """The body is what the dry run prints and what the record's digest is taken over."""
    for name in ("openai/m", "anthropic/m", "ollama/m"):
        found = model(name)
        assert KEY.encode() not in client.build_body(found, "s", "u")


def test_a_provider_with_no_key_sends_no_authorization() -> None:
    found = model("ollama/some-model")
    request = client.build_request(found, client.build_body(found, "s", "u"), key=None)
    assert "Authorization" not in request.headers


def test_an_output_cap_goes_in_the_field_the_vendor_names() -> None:
    def body(name: str) -> dict:
        return json.loads(client.build_body(model(name), "s", "u", max_output_tokens=4000))

    assert body("openai/m")["max_completion_tokens"] == 4000
    assert body("moonshot/m")["max_completion_tokens"] == 4000
    assert body("mistral/m")["max_tokens"] == 4000
    assert body("anthropic/m")["max_tokens"] == 4000


def test_without_a_cap_an_openai_style_request_sends_none() -> None:
    """A reasoning model spends its cap on thinking first, so a default cap would truncate
    replies the author never asked to limit. Anthropic's API requires one."""
    sent = json.loads(client.build_body(model("openai/m"), "s", "u"))
    assert not {"max_tokens", "max_completion_tokens"} & set(sent)


def test_the_body_is_the_same_bytes_every_time() -> None:
    found = model("openai/m")
    assert client.build_body(found, "s", "ü") == client.build_body(found, "s", "ü")
    assert "ü".encode() in client.build_body(found, "s", "ü")


# ------------------------------------------------------------------------------- the call


class Answers:
    """A transport that answers from a list and remembers what it was asked."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def openai_answer(content='{"ok": true}', finish="stop", status=200, **message) -> HttpResponse:
    body = {
        "id": "chatcmpl-123",
        "model": "some-model-2026-01-01",
        "choices": [
            {"message": {"role": "assistant", "content": content, **message},
             "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 340, "total_tokens": 1540},
    }
    return HttpResponse(status, {}, json.dumps(body).encode())


def anthropic_answer(text='{"ok": true}', stop="end_turn") -> HttpResponse:
    body = {
        "id": "msg_123",
        "model": "some-model-2026-01-01",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "usage": {"input_tokens": 1200, "output_tokens": 340},
    }
    return HttpResponse(200, {}, json.dumps(body).encode())


def error(status: int, message: str = "no", headers: dict | None = None) -> HttpResponse:
    return HttpResponse(
        status, headers or {}, json.dumps({"error": {"message": message}}).encode()
    )


def ask(name: str, transport, **kwargs):
    found = model(name)
    naps: list[float] = []
    reply = client.call(
        found,
        client.build_body(found, "s", "u"),
        key=KEY,
        transport=transport,
        sleep=naps.append,
        **kwargs,
    )
    return reply, naps


def test_an_openai_style_reply_is_read() -> None:
    reply, _ = ask("openai/some-model", Answers(openai_answer()))
    assert reply.text == '{"ok": true}'
    assert reply.response_id == "chatcmpl-123"
    assert reply.model == "some-model-2026-01-01"
    assert reply.finish == "stop"
    assert (reply.input_tokens, reply.output_tokens) == (1200, 340)


def test_an_anthropic_reply_is_read() -> None:
    reply, _ = ask("anthropic/some-model", Answers(anthropic_answer()))
    assert reply.text == '{"ok": true}'
    assert reply.response_id == "msg_123"
    assert reply.finish == "end_turn"
    assert (reply.input_tokens, reply.output_tokens) == (1200, 340)


def test_content_given_as_parts_is_the_text_parts_joined() -> None:
    """Mistral's reasoning models answer with a list: their thinking, then the text."""
    parts = [
        {"type": "thinking", "thinking": [{"type": "text", "text": "hm"}]},
        {"type": "text", "text": '{"ok": '},
        {"type": "text", "text": "true}"},
    ]
    reply, _ = ask("mistral/m", Answers(openai_answer(content=parts)))
    assert reply.text == '{"ok": true}'


@pytest.mark.parametrize(
    "name, answer",
    [
        ("openai/m", openai_answer(finish="length")),
        ("anthropic/m", anthropic_answer(stop="max_tokens")),
        ("anthropic/m", anthropic_answer(stop="model_context_window_exceeded")),
    ],
)
def test_a_reply_cut_short_is_refused_even_if_it_parses(name: str, answer) -> None:
    with pytest.raises(CallFailed) as failed:
        ask(name, Answers(answer))
    assert failed.value.kind == "truncated"
    assert failed.value.text == '{"ok": true}'


@pytest.mark.parametrize(
    "name, answer",
    [
        ("openai/m", openai_answer(finish="content_filter")),
        ("openai/m", openai_answer(content=None, refusal="I cannot help with that.")),
        ("anthropic/m", anthropic_answer(stop="refusal")),
    ],
)
def test_a_refusal_is_a_failure_not_a_review(name: str, answer) -> None:
    with pytest.raises(CallFailed) as failed:
        ask(name, Answers(answer))
    assert failed.value.kind == "refused"


@pytest.mark.parametrize("finish", ["tool_calls", "insufficient_system_resource", "aborted", None])
def test_any_other_way_of_stopping_is_a_failure(finish) -> None:
    with pytest.raises(CallFailed) as failed:
        ask("deepseek/m", Answers(openai_answer(finish=finish)))
    assert failed.value.kind == "incomplete"


def test_an_empty_reply_is_a_failure() -> None:
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", Answers(openai_answer(content="  ")))
    assert failed.value.kind == "empty"


@pytest.mark.parametrize(
    "body", [b"<html>502</html>", b"[]", b'{"choices": []}', b'{"choices": [{"message": 3}]}']
)
def test_an_answer_that_is_not_the_documented_shape_is_a_failure(body: bytes) -> None:
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", Answers(HttpResponse(200, {}, body)))
    assert failed.value.kind == "unreadable"


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_names_the_variable_and_prints_nothing_of_the_key(status: int) -> None:
    """OpenAI's own message for a bad key quotes part of it."""
    answer = error(status, f"Incorrect API key provided: {KEY[:8]}****{KEY[-4:]}")
    transport = Answers(answer)
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", transport)
    assert failed.value.kind == "auth"
    assert "OPENAI_API_KEY" in str(failed.value)
    assert KEY[-4:] not in str(failed.value) and KEY[:8] not in str(failed.value)
    assert len(transport.requests) == 1


def test_a_key_echoed_in_an_error_is_taken_out() -> None:
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", Answers(error(400, f"bad request from key {KEY} today")))
    assert failed.value.kind == "rejected"
    assert KEY not in str(failed.value)
    assert "bad request from key" in str(failed.value)


def test_a_rate_limit_is_retried_after_the_wait_the_provider_asks_for() -> None:
    transport = Answers(error(429, headers={"Retry-After": "7"}), openai_answer())
    reply, naps = ask("openai/m", transport)
    assert reply.text == '{"ok": true}'
    assert naps == [7.0]
    assert len(transport.requests) == 2


def test_header_names_are_read_whatever_their_case() -> None:
    _, naps = ask("openai/m", Answers(error(429, headers={"retry-after": "3"}), openai_answer()))
    assert naps == [3.0]


def test_a_wait_is_capped_and_a_missing_one_has_a_default() -> None:
    transport = Answers(
        error(429, headers={"Retry-After": "86400"}), error(503), openai_answer()
    )
    _, naps = ask("openai/m", transport)
    assert naps == [client.MAX_WAIT_SECONDS, client.DEFAULT_WAIT_SECONDS]


@pytest.mark.parametrize("status", [429, 503, 529])
def test_two_retries_and_then_the_pair_fails(status: int) -> None:
    transport = Answers(error(status), error(status), error(status), openai_answer())
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", transport)
    assert failed.value.kind == "busy"
    assert len(transport.requests) == 3


def test_a_timeout_is_not_retried() -> None:
    """The provider may have run the request and billed for it; asking again would pay twice
    without the author having been told."""
    transport = Answers(TransportError("timeout", "timed out after 600 s"), openai_answer())
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", transport)
    assert failed.value.kind == "timeout"
    assert len(transport.requests) == 1


def test_a_network_failure_is_reported_without_the_key() -> None:
    transport = Answers(TransportError("network", f"could not connect ({KEY})"))
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", transport)
    assert failed.value.kind == "network"
    assert KEY not in str(failed.value)


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_a_failure(status: int) -> None:
    """Following one would carry the key, and the manuscript, to a host nobody agreed to."""
    transport = Answers(HttpResponse(status, {"Location": "https://elsewhere.example/"}, b""))
    with pytest.raises(CallFailed) as failed:
        ask("openai/m", transport)
    assert failed.value.kind == "rejected"
    assert "redirect" in str(failed.value)
    assert len(transport.requests) == 1


def test_the_real_transport_does_not_follow_redirects() -> None:
    handler = client.NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://x.example/") is None


def test_the_real_transport_is_what_a_call_uses_by_default() -> None:
    assert client.call.__kwdefaults__["transport"] is None
    assert callable(client.default_transport)


# ------------------------------------------------------------------------------ the reply

GOOD = {
    "verdict": "major-revision",
    "summary": "The estimator is stated, the case definition is not.",
    "rejection_tests": [
        {
            "test": "The estimate cannot be reconstructed from what is reported.",
            "holds": False,
            "evidence": "The two-by-two table is in the Results.",
        }
    ],
    "findings": [
        {
            "severity": "major",
            "where": "Methods, Case definition",
            "finding": "No case definition is given.",
        },
        {"severity": "comment", "finding": "The limitations are stated early."},
    ],
}


def test_a_reply_that_is_one_object_of_the_right_shape_is_accepted() -> None:
    assert parse_reply(json.dumps(GOOD)) == GOOD
    assert parse_reply("\n  " + json.dumps(GOOD, indent=2) + "\n") == GOOD


def test_one_code_fence_around_the_whole_reply_is_taken_off() -> None:
    assert parse_reply("```json\n" + json.dumps(GOOD) + "\n```") == GOOD
    assert parse_reply("```\n" + json.dumps(GOOD) + "\n```\n") == GOOD


@pytest.mark.parametrize(
    "text",
    [
        "Here is my review:\n" + json.dumps(GOOD),
        json.dumps(GOOD) + "\nI hope this helps.",
        "```json\n" + json.dumps(GOOD) + "\n```\nand\n```json\n" + json.dumps(GOOD) + "\n```",
        json.dumps(GOOD) + json.dumps(GOOD),
        json.dumps([GOOD]),
        json.dumps(GOOD)[:-20],
        "",
        "null",
    ],
)
def test_anything_else_is_refused_not_repaired(text: str) -> None:
    with pytest.raises(ReplyRefused):
        parse_reply(text)


def changed(**changes) -> str:
    return json.dumps({**GOOD, **changes})


@pytest.mark.parametrize(
    "text, named",
    [
        (changed(verdict="accept"), "verdict"),
        (changed(verdict=None), "verdict"),
        (changed(summary=""), "summary"),
        (changed(rejection_tests=[]), "rejection_tests"),
        (changed(findings=[{"severity": "critical", "finding": "x"}]), "severity"),
        (changed(findings=[{"severity": "major"}]), "finding"),
        (changed(findings=[{"severity": "major", "finding": "x", "resolution": "done"}]),
         "resolution"),
        (changed(reviewed_by="somebody else"), "reviewed_by"),
        (json.dumps({k: v for k, v in GOOD.items() if k != "findings"}), "findings"),
    ],
)
def test_a_reply_of_the_wrong_shape_is_refused_and_the_message_says_where(
    text: str, named: str
) -> None:
    with pytest.raises(ReplyRefused) as refused:
        parse_reply(text)
    assert named in str(refused.value)


def test_a_key_given_twice_is_refused() -> None:
    """A parser keeps the last and says nothing; which verdict the model meant is a guess."""
    text = json.dumps(GOOD)[:-1] + ', "verdict": "pass"}'
    with pytest.raises(ReplyRefused, match="twice"):
        parse_reply(text)


def test_a_model_cannot_answer_its_own_finding() -> None:
    """`resolution` and `overridden` are the author's to write. A reply carrying one would
    file a major finding already closed."""
    for field in ("resolution", "overridden", "resolved_on", "id"):
        finding = {"severity": "major", "finding": "x", field: "2026-10-02"}
        with pytest.raises(ReplyRefused):
            parse_reply(changed(findings=[finding]))
