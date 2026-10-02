"""Running the panel: the calls are made, and what comes back is filed or refused.

Everything a run does that the dry run does not: it asks, it sends, and it writes records.
Each of those can go wrong in a way that matters. A manuscript sent without a yes cannot be
unsent. A reply filed without being validated is a review nobody wrote. A round in which one
provider failed must not look complete.

No test here opens a connection: the transport is replaced by one that answers from what
each test sets up, and that records what it was sent.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.gates import check_review
from manuscript_guard.gates.review import file_digests, manuscript_digest
from manuscript_guard.panel import client, commands
from manuscript_guard.panel.client import HttpResponse, TransportError

KEY_A = "sk-test-openai-0123456789SECRETA"
KEY_B = "test-mistral-0123456789SECRETB"
MODEL_A = "openai/model-a"
MODEL_B = "mistral/model-b"


def loaded(root: Path):
    return load_project(root)[0]


def reply_text(verdict: str = "minor-revision", findings: list | None = None) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "summary": "The estimator is stated; the abstract is a little ahead of the data.",
            "rejection_tests": [
                {
                    "test": "The estimate cannot be reconstructed from what is reported.",
                    "holds": False,
                    "evidence": "The two-by-two table is in the Results.",
                }
            ],
            "findings": [{"severity": "minor", "where": "Abstract", "finding": "Say synthetic."}]
            if findings is None
            else findings,
        }
    )


def answer(text: str, finish: str = "stop") -> HttpResponse:
    body = {
        "id": "chatcmpl-777",
        "model": "model-as-served",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 4321, "completion_tokens": 321},
    }
    return HttpResponse(200, {}, json.dumps(body).encode())


class Providers:
    """A transport that answers by host, and remembers every request."""

    def __init__(self) -> None:
        self.requests: list = []
        self.by_host: dict = {}
        self.default = lambda request: answer(reply_text())

    def host(self, name: str, respond) -> None:
        self.by_host[name] = respond

    def __call__(self, request, timeout):
        self.requests.append(request)
        for name, respond in self.by_host.items():
            if name in request.url:
                found = respond(request)
                if isinstance(found, Exception):
                    raise found
                return found
        return self.default(request)

    def to(self, name: str) -> list:
        return [request for request in self.requests if name in request.url]


@pytest.fixture
def providers(monkeypatch) -> Providers:
    transport = Providers()
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", KEY_A)
    monkeypatch.setenv("MISTRAL_API_KEY", KEY_B)
    return transport


def configure(root: Path, *models: str) -> Path:
    path = root / "paper.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\nreview:\n  models: [{', '.join(models)}]\n",
        encoding="utf-8",
        newline="\n",
    )
    return root


@pytest.fixture
def unreviewed(project: Path) -> Path:
    """The example with no review at all, to be read by two models from two providers."""
    shutil.rmtree(project / "review")
    return configure(project, MODEL_A, MODEL_B)


def run(root: Path, *flags: str) -> int:
    return main(["review", str(root), "--run", *flags])


def readings(root: Path, number: int = 1) -> list[Path]:
    return sorted((root / "review" / f"round-{number}").glob("*.*.yaml"))


def everything_under(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ------------------------------------------------------------------------- a run that works


def test_a_run_files_a_reading_for_every_reviewer_and_model(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    assert run(unreviewed, "--yes") == 0
    out = capsys.readouterr().out
    assert "4 reviewers x 2 models = 8 calls" in out
    assert len(providers.requests) == 8

    filed = readings(unreviewed)
    assert [path.name for path in filed] == sorted(
        f"{reviewer}.{model}.yaml"
        for reviewer in ("adversarial", "design-methods", "reporting-auditor", "statistics")
        for model in ("mistral-model-b", "openai-model-a")
    )
    for path in filed:
        document = read_structured(path)
        assert validate(document, "review", path).ok, path.name
        assert document["round"] == 1
        assert document["reviewer"] == path.name.split(".")[0]
        assert document["reader"] in (MODEL_A, MODEL_B)
        assert document["reviewed_by"] == document["reader"]


def test_the_record_says_what_the_model_said_and_nothing_else(
    unreviewed: Path, providers: Providers
) -> None:
    said = json.loads(reply_text())
    assert run(unreviewed, "--yes") == 0
    document = read_structured(readings(unreviewed)[0])
    assert document["verdict"] == said["verdict"]
    assert document["summary"] == said["summary"]
    assert document["rejection_tests"] == said["rejection_tests"]
    assert [
        {key: finding[key] for key in ("severity", "where", "finding")}
        for finding in document["findings"]
    ] == said["findings"]
    for finding in document["findings"]:
        assert set(finding) == {"id", "severity", "where", "finding"}, "no answer is written"


def test_the_record_carries_the_digests_of_what_was_sent(
    unreviewed: Path, providers: Providers
) -> None:
    assert run(unreviewed, "--yes") == 0
    project = loaded(unreviewed)
    for path in readings(unreviewed):
        document = read_structured(path)
        assert document["manuscript_sha256"] == manuscript_digest(project)
        assert document["file_sha256"] == file_digests(project)


def test_the_record_can_be_traced_to_the_request_and_the_response(
    unreviewed: Path, providers: Providers
) -> None:
    assert run(unreviewed, "--yes") == 0
    sent = {hashlib.sha256(request.body).hexdigest(): request for request in providers.requests}
    assert len(sent) == 8
    for path in readings(unreviewed):
        provenance = read_structured(path)["provenance"]
        request = sent.pop(provenance["prompt_sha256"])
        assert provenance["host"] in request.url
        assert provenance["provider"] in ("openai", "mistral")
        assert provenance["model"] in ("model-a", "model-b")
        assert provenance["model_reported"] == "model-as-served"
        assert provenance["response_id"] == "chatcmpl-777"
        assert provenance["finish"] == "stop"
        assert (provenance["input_tokens"], provenance["output_tokens"]) == (4321, 321)
        assert provenance["tool_version"]
    assert not sent, "every request is accounted for by one record"


def test_findings_are_numbered_within_the_record(unreviewed: Path, providers: Providers) -> None:
    three = [{"severity": "comment", "finding": f"Point {n}."} for n in range(3)]
    providers.default = lambda request: answer(reply_text(findings=three))
    assert run(unreviewed, "--yes") == 0
    ids = [finding["id"] for finding in read_structured(readings(unreviewed)[0])["findings"]]
    assert ids == ["r1-01", "r1-02", "r1-03"]


def test_the_panel_is_written_with_the_readers_it_was_asked_of(
    unreviewed: Path, providers: Providers
) -> None:
    assert run(unreviewed, "--yes") == 0
    path = unreviewed / "review" / "panel-1.yaml"
    panel = read_structured(path)
    assert validate(panel, "panel", path).ok
    assert panel["blinded"] is False
    assert "starter panel" in panel["rationale"].lower()
    assert [reviewer["id"] for reviewer in panel["reviewers"]] == [
        "design-methods",
        "statistics",
        "reporting-auditor",
        "adversarial",
    ]
    for reviewer in panel["reviewers"]:
        assert reviewer["readers"] == [MODEL_A, MODEL_B]

    report = check_review(loaded(unreviewed), submission=True)
    assert report.counts["review_rounds_complete"] == 1
    assert report.counts["review_readings"] == 8
    assert "reading-missing" not in {finding.code for finding in report.findings}


def test_one_each_names_one_reader_for_each_reviewer(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    assert run(unreviewed, "--yes", "--one-each") == 0
    assert "4 reviewers, one model each = 4 calls" in capsys.readouterr().out
    assert len(providers.requests) == 4
    panel = read_structured(unreviewed / "review" / "panel-1.yaml")
    assert [reviewer["readers"] for reviewer in panel["reviewers"]] == [
        [MODEL_A],
        [MODEL_B],
        [MODEL_A],
        [MODEL_B],
    ]
    assert check_review(loaded(unreviewed)).counts["review_rounds_complete"] == 1


def test_a_major_finding_from_a_model_blocks_until_it_is_answered(
    unreviewed: Path, providers: Providers
) -> None:
    major = [{"severity": "major", "where": "Methods", "finding": "No case definition."}]
    providers.host("api.mistral.ai", lambda request: answer(reply_text("reject", major)))
    assert run(unreviewed, "--yes") == 0
    report = check_review(loaded(unreviewed), submission=True)
    blocking = [f for f in report.failures if f.code == "open-major-finding"]
    assert len(blocking) == 4
    assert all(MODEL_B in finding.message for finding in blocking)


def test_the_second_round_is_a_different_panel_and_is_blinded(
    unreviewed: Path, providers: Providers
) -> None:
    assert run(unreviewed, "--yes") == 0
    for path in readings(unreviewed):
        path.write_text(
            path.read_text(encoding="utf-8").replace("Say synthetic.", "ZZ-ROUND-ONE-ZZ"),
            encoding="utf-8",
            newline="\n",
        )
    providers.requests.clear()

    assert run(unreviewed, "--yes") == 0, "with round one read, a run goes on to round two"
    panel = read_structured(unreviewed / "review" / "panel-2.yaml")
    assert panel["blinded"] is True
    assert [reviewer["id"] for reviewer in panel["reviewers"]] == ["desk-editor", "subject-reader"]
    assert len(providers.requests) == 4
    for request in providers.requests:
        assert b"ZZ-ROUND-ONE-ZZ" not in request.body

    report = check_review(loaded(unreviewed), submission=True)
    assert report.ok, report.render(unreviewed)
    assert report.counts["review_rounds_complete"] == 2


def test_an_existing_panel_gains_its_readers_and_loses_nothing(
    project: Path, providers: Providers
) -> None:
    """The example's second round was read by hand. Models read it too, beside those
    records, and the panel's own words are kept."""
    configure(project, MODEL_A, MODEL_B)
    before = read_structured(project / "review" / "panel-2.yaml")
    by_hand = {
        path.name: path.read_bytes() for path in (project / "review" / "round-2").glob("*.yaml")
    }

    assert run(project, "--yes", "--round", "2") == 0
    after = read_structured(project / "review" / "panel-2.yaml")
    assert {key: after[key] for key in before if key != "reviewers"} == {
        key: before[key] for key in before if key != "reviewers"
    }
    for was, now in zip(before["reviewers"], after["reviewers"], strict=True):
        assert {key: now[key] for key in was} == was
        assert now["readers"] == [MODEL_A, MODEL_B]
    for name, content in by_hand.items():
        assert (project / "review" / "round-2" / name).read_bytes() == content
    assert len(readings(project, 2)) == 4

    report = check_review(loaded(project), submission=True)
    assert report.ok, report.render(project)
    assert report.counts["review_readings"] == 9


def test_a_local_model_needs_no_key(project: Path, providers: Providers, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("MISTRAL_API_KEY")
    shutil.rmtree(project / "review")
    configure(project, "ollama/model-l")
    assert run(project, "--yes") == 0
    assert len(providers.to("localhost:11434")) == 4
    assert all("Authorization" not in request.headers for request in providers.requests)


# -------------------------------------------------------------------------------- the keys


def test_each_key_goes_to_its_own_provider_and_nowhere_else(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    assert run(unreviewed, "--yes") == 0
    for request in providers.to("api.openai.com"):
        assert request.headers["Authorization"] == f"Bearer {KEY_A}"
        assert KEY_B.encode() not in request.body and KEY_A.encode() not in request.body
    for request in providers.to("api.mistral.ai"):
        assert request.headers["Authorization"] == f"Bearer {KEY_B}"
    assert len(providers.to("api.openai.com")) == len(providers.to("api.mistral.ai")) == 4

    printed = capsys.readouterr()
    for key in (KEY_A, KEY_B):
        assert key not in printed.out and key not in printed.err
        for name, content in everything_under(unreviewed).items():
            assert key.encode() not in content, name


def test_a_key_a_provider_echoes_is_not_printed_or_kept(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    providers.host(
        "api.mistral.ai",
        lambda request: HttpResponse(
            400, {}, json.dumps({"error": {"message": f"bad key {KEY_B} given"}}).encode()
        ),
    )
    providers.host("api.openai.com", lambda request: answer(f"I was given {KEY_A}. No review."))
    assert run(unreviewed, "--yes") == 1
    printed = capsys.readouterr()
    for key in (KEY_A, KEY_B):
        assert key not in printed.out and key not in printed.err
        for name, content in everything_under(unreviewed).items():
            assert key.encode() not in content, name


def test_a_missing_key_stops_the_run_before_anything_is_sent_or_written(
    unreviewed: Path, providers: Providers, monkeypatch, capsys
) -> None:
    """Sending half a panel for a reason known in advance would file a round to finish."""
    monkeypatch.delenv("MISTRAL_API_KEY")
    before = everything_under(unreviewed)
    assert run(unreviewed, "--yes") == 2
    assert "MISTRAL_API_KEY" in capsys.readouterr().err
    assert providers.requests == []
    assert everything_under(unreviewed) == before


# ------------------------------------------------------------------------------ the consent


def test_without_a_yes_nothing_is_sent_and_nothing_is_written(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    """Under a test, or in a script, nobody is there to answer."""
    before = everything_under(unreviewed)
    assert run(unreviewed) == 2
    printed = capsys.readouterr()
    assert "4 reviewers x 2 models = 8 calls" in printed.out, "the statement is still shown"
    assert "--yes" in printed.err
    assert providers.requests == []
    assert everything_under(unreviewed) == before


@pytest.mark.parametrize("typed", ["n", "", "no", "maybe", "y ", "Yes please"])
def test_anything_but_a_yes_at_the_prompt_sends_nothing(
    unreviewed: Path, providers: Providers, monkeypatch, typed: str
) -> None:
    monkeypatch.setattr(commands, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)
    before = everything_under(unreviewed)
    assert run(unreviewed) == 2
    assert providers.requests == []
    assert everything_under(unreviewed) == before


@pytest.mark.parametrize("typed", ["yes", "YES", " yes "])
def test_a_yes_at_the_prompt_sends(
    unreviewed: Path, providers: Providers, monkeypatch, typed: str
) -> None:
    asked: list[str] = []

    def answer_it(prompt: str = "") -> str:
        asked.append(prompt)
        return typed

    monkeypatch.setattr(commands, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", answer_it)
    assert run(unreviewed) == 0
    assert len(asked) == 1 and "8 calls" in asked[0] and "yes" in asked[0]
    assert len(providers.requests) == 8


def test_a_prompt_that_is_closed_sends_nothing(
    unreviewed: Path, providers: Providers, monkeypatch
) -> None:
    def closed(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr(commands, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", closed)
    assert run(unreviewed) == 2
    assert providers.requests == []


def test_a_dry_run_still_sends_nothing_even_with_a_yes(
    unreviewed: Path, providers: Providers
) -> None:
    assert run(unreviewed, "--dry-run", "--yes") == 0
    assert providers.requests == []
    assert not (unreviewed / "review").exists()


# ------------------------------------------------------------------------------- failures


def test_one_provider_failing_files_the_rest_and_leaves_the_round_incomplete(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    providers.host(
        "api.mistral.ai",
        lambda request: HttpResponse(500, {}, b'{"message": "internal error"}'),
    )
    assert run(unreviewed, "--yes") == 1
    out = capsys.readouterr().out
    assert [path.name.split(".")[1] for path in readings(unreviewed)] == ["openai-model-a"] * 4
    assert "4 of 8" in out and MODEL_B in out and "internal error" in out

    report = check_review(loaded(unreviewed), submission=True)
    missing = [f for f in report.failures if f.code == "reading-missing"]
    assert len(missing) == 4 and all(MODEL_B in finding.message for finding in missing)
    assert report.counts["review_rounds_complete"] == 0


def test_running_again_asks_only_for_what_is_missing(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    providers.host(
        "api.mistral.ai", lambda request: TransportError("timeout", "no answer within 600 s")
    )
    assert run(unreviewed, "--yes") == 1
    assert len(providers.to("api.mistral.ai")) == 4, "a timeout is not retried"
    first = {path.name: path.read_bytes() for path in readings(unreviewed)}

    providers.by_host.clear()
    providers.requests.clear()
    assert run(unreviewed, "--yes") == 0, "the same round, not the next one"
    out = capsys.readouterr().out
    assert "4 readings already on file" in out
    assert len(providers.requests) == len(providers.to("api.mistral.ai")) == 4
    assert len(readings(unreviewed)) == 8
    for name, content in first.items():
        assert (unreviewed / "review" / "round-1" / name).read_bytes() == content
    assert check_review(loaded(unreviewed)).counts["review_rounds_complete"] == 1


@pytest.mark.parametrize(
    "text, finish, said",
    [
        ("Here is my review: the paper is fine.", "stop", "not one JSON object"),
        (reply_text("accept"), "stop", "verdict"),
        (reply_text()[:-30], "stop", "not one JSON object"),
        (reply_text(), "length", "output limit"),
        (reply_text(), "content_filter", "declined"),
        ("", "stop", "no text"),
    ],
    ids=["prose", "a verdict outside the vocabulary", "cut JSON", "truncated", "refused", "empty"],
)
def test_a_reply_that_cannot_be_filed_is_refused_not_repaired(
    unreviewed: Path, providers: Providers, capsys, text: str, finish: str, said: str
) -> None:
    providers.host("api.mistral.ai", lambda request: answer(text, finish))
    assert run(unreviewed, "--yes") == 1
    out = capsys.readouterr().out
    assert said in out
    assert len(readings(unreviewed)) == 4, "the other provider's readings are filed"
    assert not any("mistral" in path.name for path in readings(unreviewed))
    assert len(providers.to("api.mistral.ai")) == 4, "and it is not asked again"


def test_a_refused_reply_is_kept_to_read_and_counted_nowhere(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    providers.host(
        "api.mistral.ai", lambda request: answer("Here is my review: the paper is fine.")
    )
    assert run(unreviewed, "--yes") == 1
    kept = sorted((unreviewed / "review" / "round-1" / "refused").glob("*"))
    assert [path.name for path in kept] == [
        f"{reviewer}.mistral-model-b.txt"
        for reviewer in ("adversarial", "design-methods", "reporting-auditor", "statistics")
    ]
    text = kept[0].read_text(encoding="utf-8")
    assert "Here is my review: the paper is fine." in text
    assert MODEL_B in text and "not a review record" in text
    assert "refused/" in capsys.readouterr().out

    report = check_review(loaded(unreviewed), submission=True)
    assert report.counts["review_readings"] == 4
    assert not [f for f in report.findings if f.path and f.path.parent.name == "refused"]


def test_a_reply_kept_from_an_earlier_run_goes_when_the_reading_is_filed(
    unreviewed: Path, providers: Providers
) -> None:
    providers.host("api.mistral.ai", lambda request: answer("Not a review."))
    assert run(unreviewed, "--yes") == 1
    providers.by_host.clear()
    assert run(unreviewed, "--yes") == 0
    assert not (unreviewed / "review" / "round-1" / "refused").exists()


def test_a_reading_that_appears_meanwhile_is_not_overwritten(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    """A record cannot be re-stamped, by a run any more than by hand."""
    target = unreviewed / "review" / "round-1" / "statistics.openai-model-a.yaml"

    def file_it_first(request):
        if b"Statistician" in request.body and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("filed by somebody else\n", encoding="utf-8")
        return answer(reply_text())

    providers.host("api.openai.com", file_it_first)
    assert run(unreviewed, "--yes") == 1
    assert target.read_text(encoding="utf-8") == "filed by somebody else\n"
    assert "already exists" in capsys.readouterr().out


def test_a_manuscript_edited_during_the_run_makes_the_reading_stale_not_wrong(
    unreviewed: Path, providers: Providers
) -> None:
    """The record names the version that was sent, whatever the file says by then."""
    sent_digest = manuscript_digest(loaded(unreviewed))
    path = unreviewed / "manuscript" / "main.md"

    def edit_then_answer(request):
        if "Edited meanwhile" not in path.read_text(encoding="utf-8"):
            path.write_text(
                path.read_text(encoding="utf-8") + "\n\nEdited meanwhile.\n", encoding="utf-8"
            )
        return answer(reply_text())

    providers.default = edit_then_answer
    assert run(unreviewed, "--yes") == 0
    for filed in readings(unreviewed):
        assert read_structured(filed)["manuscript_sha256"] == sent_digest
    report = check_review(loaded(unreviewed))
    assert len([f for f in report.findings if f.code == "review-stale"]) == 8


def test_no_half_written_file_is_left_in_the_round(
    unreviewed: Path, providers: Providers
) -> None:
    assert run(unreviewed, "--yes") == 0
    names = [path.name for path in (unreviewed / "review" / "round-1").iterdir()]
    assert all(name.endswith(".yaml") for name in names), names
    for path in readings(unreviewed):
        assert b"\r\n" not in path.read_bytes()
        assert yaml.safe_load(path.read_text(encoding="utf-8"))


def test_when_everything_is_on_file_nothing_is_asked_or_sent(
    project: Path, providers: Providers, capsys
) -> None:
    configure(project, MODEL_A)
    assert run(project, "--yes", "--round", "2") == 0
    providers.requests.clear()
    assert run(project, "--round", "2") == 0, "no yes is needed to send nothing"
    assert providers.requests == []
    assert "nothing to send" in capsys.readouterr().out


def test_a_key_that_is_not_a_key_stops_the_run_before_anything_is_sent(
    unreviewed: Path, providers: Providers, monkeypatch, capsys
) -> None:
    """A variable set to two lines, or to a sentence. Nothing may be sent to the other
    provider either: half a panel sent for a reason known in advance is a round to finish."""
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-FIRSTHALF\nSECONDHALF")
    before = everything_under(unreviewed)
    assert run(unreviewed, "--yes") == 2
    printed = capsys.readouterr()
    assert "MISTRAL_API_KEY" in printed.err
    assert "FIRSTHALF" not in printed.err + printed.out
    assert "SECONDHALF" not in printed.err + printed.out
    assert providers.requests == []
    assert everything_under(unreviewed) == before


def test_part_of_a_key_in_a_reply_is_not_kept_either(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    providers.host(
        "api.openai.com",
        lambda request: answer(f"Your key {KEY_A[:10]}...{KEY_A[-6:]} looks wrong. No review."),
    )
    assert run(unreviewed, "--yes") == 1
    printed = capsys.readouterr()
    parts = (KEY_A[:10].encode(), KEY_A[-6:].encode())
    for name, content in everything_under(unreviewed).items():
        assert not any(part in content for part in parts), name
    assert not any(part in (printed.out + printed.err).encode() for part in parts)


def test_a_finding_whose_place_is_null_is_filed_without_one(
    unreviewed: Path, providers: Providers
) -> None:
    findings = [{"severity": "minor", "where": None, "finding": "Say synthetic."}]
    providers.default = lambda request: answer(reply_text(findings=findings))
    assert run(unreviewed, "--yes") == 0
    document = read_structured(readings(unreviewed)[0])
    assert document["findings"] == [
        {"id": "r1-01", "severity": "minor", "finding": "Say synthetic."}
    ]


# ------------------------------------------------------------- what the provider says of itself


def served(text: str, **said) -> HttpResponse:
    """An answer whose envelope the test words: the id, the model, the usage."""
    body = {
        "id": "chatcmpl-777",
        "model": "model-as-served",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4321, "completion_tokens": 321},
    }
    body.update(said)
    return HttpResponse(200, {}, json.dumps(body).encode())


@pytest.mark.parametrize(
    "field, value",
    [
        ("id", f"chatcmpl-{KEY_A}"),
        ("id", f"chatcmpl-{KEY_A[8:20]}"),
        ("model", f"model for {KEY_A}"),
        ("id", "chatcmpl-777" + chr(27) + "[2J"),
        ("model", "model" + chr(10) + "verdict: accept"),
        ("id", "x" * 5000),
        ("model", "served " + chr(0xD800)),
    ],
    ids=[
        "the key in the id",
        "part of the key in the id",
        "the key in the model",
        "an escape sequence",
        "a line break",
        "five thousand characters",
        "half a character",
    ],
)
def test_what_a_provider_says_of_itself_is_filed_only_when_it_is_plain(
    unreviewed: Path, providers: Providers, capsys, field: str, value: str
) -> None:
    """The response id and the model's served name are the provider's words, and they go
    into a record that is committed. One that is not a short plain line is left out, and the
    reading is filed without it: the review is the model's and loses nothing."""
    providers.host("api.openai.com", lambda request: served(reply_text(), **{field: value}))
    assert run(unreviewed, "--yes") == 0, capsys.readouterr().out
    kept = {"id": "response_id", "model": "model_reported"}[field]
    other = ({"response_id", "model_reported"} - {kept}).pop()
    for path in readings(unreviewed):
        if "openai" not in path.name:
            continue
        document = read_structured(path)
        assert validate(document, "review", path).ok
        assert kept not in document["provenance"]
        assert other in document["provenance"], "the field that is plain is still filed"
    for name, content in everything_under(unreviewed).items():
        assert KEY_A.encode() not in content and KEY_A[8:20].encode() not in content, name


@pytest.mark.parametrize("usage", [{"prompt_tokens": -5, "completion_tokens": 321}, "many", None])
def test_a_token_count_that_is_not_a_count_does_not_cost_the_reading(
    unreviewed: Path, providers: Providers, usage
) -> None:
    providers.host("api.openai.com", lambda request: served(reply_text(), usage=usage))
    assert run(unreviewed, "--yes") == 0
    for path in readings(unreviewed):
        if "openai" in path.name:
            provenance = read_structured(path)["provenance"]
            assert "input_tokens" not in provenance
            assert provenance.get("output_tokens") in (None, 321)


def test_a_review_that_repeats_the_key_is_not_filed(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    """A model is never sent the key, so it cannot repeat it; a gateway between could put it
    there. The reply fits the schema in every other way, and a record is committed."""
    said = json.loads(reply_text())
    said["summary"] = f"The estimator is stated. Called with {KEY_A}."
    providers.host("api.openai.com", lambda request: answer(json.dumps(said)))
    assert run(unreviewed, "--yes") == 1
    printed = capsys.readouterr()
    assert "repeats the key" in printed.out
    assert not any("openai" in path.name for path in readings(unreviewed))
    assert len(readings(unreviewed)) == 4, "the other provider's readings are filed"
    for name, content in everything_under(unreviewed).items():
        assert KEY_A.encode() not in content, name
    assert KEY_A not in printed.out + printed.err


def test_a_reply_with_half_a_character_in_it_is_refused_and_the_run_goes_on(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    """JSON can spell half of a surrogate pair, which no file can hold. The reply is refused
    and what can be kept of it is kept; the run ended in a traceback there."""
    said = json.loads(reply_text())
    said["summary"] = "The estimator is stated " + chr(0xD83D) + "."
    providers.host("api.mistral.ai", lambda request: answer(json.dumps(said, ensure_ascii=False)))
    assert run(unreviewed, "--yes") == 1
    out = capsys.readouterr().out
    assert "4 of 8" in out
    assert len(readings(unreviewed)) == 4
    kept = sorted((unreviewed / "review" / "round-1" / "refused").glob("*"))
    assert len(kept) == 4
    assert "The estimator is stated" in kept[0].read_text(encoding="utf-8")


# ------------------------------------------------------------------- two writers at one time


def test_a_panel_somebody_else_is_writing_stops_the_run_before_anything_is_sent(
    unreviewed: Path, providers: Providers, monkeypatch, capsys
) -> None:
    from manuscript_guard import record

    monkeypatch.setattr(record, "LOCK_WAIT_SECONDS", 0.3)
    lock = unreviewed / "review" / "panel-1.yaml.lock"
    lock.parent.mkdir()
    lock.write_bytes(b"")
    before = everything_under(unreviewed)
    assert run(unreviewed, "--yes") == 2
    printed = capsys.readouterr()
    assert "nothing was sent" in printed.err.lower() and lock.name in printed.err
    assert providers.requests == []
    assert everything_under(unreviewed) == before


def test_a_run_leaves_no_lock_behind(unreviewed: Path, providers: Providers) -> None:
    assert run(unreviewed, "--yes") == 0
    assert not list((unreviewed / "review").glob("*.lock"))


def test_a_reader_the_panel_already_names_in_other_letters_is_not_named_twice(
    project: Path, providers: Providers
) -> None:
    """The panel was written by hand as `OpenAI/Model-A`. That is the reader this run asks,
    filed under the same name, and a second entry would be two readers for one file."""
    configure(project, MODEL_A)
    panel = project / "review" / "panel-2.yaml"
    document = read_structured(panel)
    for reviewer in document["reviewers"]:
        reviewer["readers"] = ["OpenAI/Model-A"]
    panel.write_bytes(yaml.safe_dump(document, sort_keys=False).encode("utf-8"))

    assert run(project, "--yes", "--round", "2") == 0
    for reviewer in read_structured(panel)["reviewers"]:
        assert reviewer["readers"] == ["OpenAI/Model-A"]
    report = check_review(loaded(project), submission=True)
    assert report.ok, report.render(project)
    assert "duplicate-reader" not in {finding.code for finding in report.findings}


def test_a_record_is_not_replaced_even_when_the_look_for_it_came_too_early(
    tmp_path: Path, monkeypatch
) -> None:
    """Between looking for a record and putting one there, somebody else can file theirs.
    The move itself has to refuse."""
    from manuscript_guard.panel import run as running

    target = tmp_path / "statistics.openai-model-a.yaml"
    target.write_bytes(b"theirs")
    real = Path.exists
    monkeypatch.setattr(
        Path, "exists", lambda self, **how: False if self == target else real(self, **how)
    )
    with pytest.raises(FileExistsError):
        running._write_new(target, "ours")
    monkeypatch.undo()
    assert target.read_bytes() == b"theirs"
    assert [path.name for path in tmp_path.iterdir()] == [target.name]


def test_a_file_system_with_no_hard_links_still_gets_its_record(
    tmp_path: Path, monkeypatch
) -> None:
    from manuscript_guard.panel import run as running

    def no_links(source, target, **how):
        raise OSError("hard links are not supported here")

    monkeypatch.setattr(running.os, "link", no_links)
    target = tmp_path / "statistics.openai-model-a.yaml"
    running._write_new(target, "ours")
    assert target.read_bytes() == b"ours"
    with pytest.raises(FileExistsError):
        running._write_new(target, "again")
    assert target.read_bytes() == b"ours"
    assert [path.name for path in tmp_path.iterdir()] == [target.name]


def test_part_of_the_key_in_a_review_is_not_filed_either(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    said = json.loads(reply_text())
    said["findings"] = [{"severity": "minor", "finding": f"Called as {KEY_A[6:18]}, it seems."}]
    providers.host("api.openai.com", lambda request: answer(json.dumps(said)))
    assert run(unreviewed, "--yes") == 1
    assert "repeats the key" in capsys.readouterr().out
    assert not any("openai" in path.name for path in readings(unreviewed))
    for name, content in everything_under(unreviewed).items():
        assert KEY_A[6:18].encode() not in content, name


def test_a_review_is_not_refused_for_a_word_the_key_begins_with(
    unreviewed: Path, providers: Providers, monkeypatch
) -> None:
    """A key begins with its vendor's prefix. Refusing a review for four of a key's
    characters in a row refused every review that said `project`."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-0123456789abcdefSECRET")
    said = json.loads(reply_text())
    said["summary"] = "The project reports a disproportionality signal; the task is stated."
    providers.default = lambda request: answer(json.dumps(said))
    assert run(unreviewed, "--yes") == 0
    assert len(readings(unreviewed)) == 8


def test_a_fault_nobody_foresaw_in_one_reading_does_not_lose_the_others(
    unreviewed: Path, providers: Providers, capsys
) -> None:
    def broken(request):
        raise RuntimeError("something nobody foresaw")

    providers.host("api.mistral.ai", broken)
    assert run(unreviewed, "--yes") == 1
    out = capsys.readouterr().out
    assert "4 of 8" in out and "RuntimeError" in out
    assert len(readings(unreviewed)) == 4
