"""Making the calls of a plan, and filing or refusing what comes back.

By the time anything here runs, the author has been shown the plan and has said yes. What
is left to get right is what is written down:

* **A reading is filed whole or not at all.** A reply becomes a record only after it has
  come back finished, parsed as one JSON object, fitted the reply schema, and the record
  built from it has fitted the review schema. The record is written to a temporary file and
  moved into place, so an interrupted run leaves no half-written record for G11 to read.
* **Nothing of the review is written by this tool.** The verdict, the summary, the tests and
  the findings are the model's words. The tool adds what the model cannot know: who read,
  when, which version of the manuscript, and how the reading can be traced. It numbers the
  findings. It writes no `resolution`: answering a finding is the author's.
* **A reply that is refused is kept to read, and counted nowhere.** It goes under
  `refused/` as text, where no gate looks. The author paid for it and may want to see what
  the model said; it is not a review record and cannot become one.
* **One provider failing does not undo the others.** Their readings are filed. The panel
  names every reader that was asked, so G11 reports the round as incomplete until the rest
  report, and running the command again asks only for what is missing.
* **A record is never overwritten**, by a run any more than by hand.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard import __version__
from manuscript_guard.contracts._schema import validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.review import reading_path, reading_slug, round_dir
from manuscript_guard.panel import client
from manuscript_guard.panel.client import CallFailed, Reply, Transport
from manuscript_guard.panel.plan import Call, Plan
from manuscript_guard.panel.providers import Provider, key_is_set, read_key
from manuscript_guard.panel.reply import ReplyRefused, parse_reply
from manuscript_guard.record import panel_lock

REFUSED_DIR = "refused"
#: The longest thing a provider says of itself that is filed.
MAX_SAID = 200
#: How many characters of a key, in a row, a record is refused for.
KEY_RUN = 8

STARTER_RATIONALE = (
    "Starter panel, written by manuscript-guard because this round had none. It assumes "
    "nothing about the paper: the remits are those any empirical paper needs somebody to "
    "hold. Edit the reviewers to fit this paper and this journal, and say why here."
)


@dataclass(frozen=True)
class Outcome:
    call: Call
    #: The record, when the reading was filed.
    path: Path | None = None
    verdict: str = ""
    findings: int = 0
    major: int = 0
    #: Why the reading was not filed, in words.
    failure: str = ""
    #: Where the refused reply was kept, when there was text to keep.
    kept: Path | None = None

    @property
    def filed(self) -> bool:
        return self.path is not None


def providers_of(plan: Plan) -> list[Provider]:
    """The providers this plan's calls go to, in the order the models are listed."""
    return list(dict.fromkeys(call.model.provider for call in plan.calls))


def missing_keys(plan: Plan, environ: Mapping[str, str] | None = None) -> list[Provider]:
    """The providers whose key is not set. Checked before anything is sent or written."""
    return [p for p in providers_of(plan) if key_is_set(p, environ) is False]


def _dump(document: dict) -> str:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=88)


def _write_new(path: Path, text: str) -> None:
    """Write a file that must not exist yet, whole: to a temporary name, then linked into
    place. A link refuses a name that is taken, where a move would replace what is there,
    and somebody can file a record between a look for one and the move."""
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_bytes(data)
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(path) from None
        except OSError:
            # A file system with no hard links. Exclusive create refuses a taken name as
            # well; what it cannot promise is that a write cut short leaves nothing behind.
            try:
                with open(path, "xb") as handle:
                    handle.write(data)
            except FileExistsError:
                raise FileExistsError(path) from None
    finally:
        temporary.unlink(missing_ok=True)


# -------------------------------------------------------------------------------- the panel


def _readers_asked(plan: Plan) -> dict[str, list[str]]:
    asked: dict[str, list[str]] = {}
    for reviewer, reader in plan.pairs:
        asked.setdefault(reviewer, []).append(reader)
    return asked


def write_panel(project: Project, plan: Plan, today: date | None = None) -> Path:
    """Record who was asked to read each remit, before any call is made.

    A round with no panel gets the starter panel the author was shown. An existing panel
    keeps every word of its own and gains, for each reviewer, the readers this run asks. It
    is written first so that a run which is interrupted, or in which a provider fails,
    leaves a round G11 can see is incomplete.

    The panel is held while it is read and written, as `review --record` holds it: a
    reading filed by hand at the same moment adds its reader to the same file. Raises
    `RecordError` when somebody else holds it for too long.
    """
    today = today or date.today()
    with panel_lock(plan.panel):
        return _write_panel(project, plan, today)


def _write_panel(project: Project, plan: Plan, today: date) -> Path:
    asked = _readers_asked(plan)
    path = plan.panel
    if path.exists():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        changed = False
        for reviewer in document["reviewers"]:
            readers = list(reviewer.get("readers") or [])
            # A reader is known by the name of its file, as the gate knows it: the panel's
            # `OpenAI/Model-A` is the reader this run asks as `openai/model-a`.
            named = {reading_slug(str(reader)) for reader in readers}
            added = [
                name
                for name in asked.get(reviewer["id"], [])
                if reading_slug(name) not in named
            ]
            if added:
                reviewer["readers"] = readers + added
                changed = True
        if changed:
            path.write_bytes(_dump(document).encode("utf-8"))
        return path

    document = {
        "schema": "manuscript-guard/panel/1",
        "round": plan.round,
        "opened_on": today.isoformat(),
        "manuscript_sha256": plan.material.manuscript_sha256,
        # A model's request carries nothing from an earlier round: it is built from a fixed
        # list of inputs, and the records are not on it.
        "blinded": plan.round > 1,
        "rationale": STARTER_RATIONALE,
        "reviewers": [
            {**reviewer, "readers": asked[reviewer["id"]]} for reviewer in plan.reviewers
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    round_dir(project, plan.round).mkdir(parents=True, exist_ok=True)
    _write_new(path, _dump(document))
    return path


# ------------------------------------------------------------------------------ one reading


def _plain(said: str | None, keys: Sequence[str]) -> str | None:
    """What a provider says of itself, when it is fit to commit: one short line of printable
    characters with nothing of a key in it. Otherwise nothing, and the record does without.

    The response id and the served model's name are the provider's words, not checked
    against any schema of ours, and they go into a file that is committed and shown.
    """
    if not said or len(said) > MAX_SAID or not said.isprintable():
        return None
    if any(client.without_key(said, key) != said for key in keys):
        return None
    return said


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for name, inner in value.items():
            yield from _strings(name)
            yield from _strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner)


def _repeats_a_key(document: dict, keys: Sequence[str]) -> bool:
    """Whether a record holds a key of this run, or `KEY_RUN` characters of one in a row.

    A model is never sent the key, so it cannot repeat one; a gateway between could put it
    in the reply. A shorter run is not looked for: the first letters of a key are a
    vendor's prefix and a common word, and every review that said `project` was refused.
    """
    for key in keys:
        parts = {key} if len(key) <= KEY_RUN else {
            key[start : start + KEY_RUN] for start in range(len(key) - KEY_RUN + 1)
        }
        for text in _strings(document):
            if any(part in text for part in parts):
                return True
    return False


def _record(
    plan: Plan, call: Call, reply: Reply, parsed: dict, today: date, keys: Sequence[str] = ()
) -> dict:
    """The review record for one reply. Every word of the review is the model's."""
    provider = call.model.provider
    provenance = {
        "provider": provider.name,
        "model": call.model.name,
        "model_reported": _plain(reply.model, keys),
        "host": provider.host,
        "prompt_sha256": call.prompt_sha256,
        "response_id": _plain(reply.response_id, keys),
        # One of the endings the client takes for a finished reply, so not free text.
        "finish": reply.finish,
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "tool_version": __version__,
    }
    return {
        "schema": "manuscript-guard/review/1",
        "round": plan.round,
        "reviewer": call.reviewer,
        "reader": call.model.reader,
        "reviewed_by": call.model.reader,
        "reviewed_on": today.isoformat(),
        "manuscript_sha256": plan.material.manuscript_sha256,
        "file_sha256": dict(sorted(plan.material.file_sha256.items())),
        "verdict": parsed["verdict"],
        "summary": parsed["summary"],
        "rejection_tests": parsed["rejection_tests"],
        "findings": [
            {"id": f"r{plan.round}-{index:02d}", **finding}
            for index, finding in enumerate(parsed["findings"], start=1)
        ],
        "provenance": {key: value for key, value in provenance.items() if value is not None},
    }


HEADER = (
    "# Filed by `manuscript-guard review --run` from the reply of the reader named below.\n"
    "# Answer each major finding by adding `resolution:` (what was done) or `overridden:`\n"
    "# (why it was not) to it. Nothing else here is yours to edit: the digests say which\n"
    "# version was read, and a second reading is a further round.\n"
)


def file_reading(
    project: Project,
    plan: Plan,
    call: Call,
    reply: Reply,
    parsed: dict,
    today: date,
    keys: Sequence[str] = (),
) -> Path:
    """Write the record for one validated reply. Raises `ReplyRefused` rather than file a
    record the review schema does not accept or one that repeats a key, and
    `FileExistsError` rather than replace one."""
    path = reading_path(project, plan.round, call.reviewer, call.model.reader)
    document = _record(plan, call, reply, parsed, today, keys)
    report = validate(document, "review", path)
    if not report.ok:
        said = "; ".join(finding.message for finding in report.findings[:3])
        raise ReplyRefused(f"the record built from the reply does not fit the schema: {said}")
    if _repeats_a_key(document, keys):
        raise ReplyRefused(
            "the reply repeats the key it was called with, or part of it; a record is "
            "committed, so this one is not filed"
        )
    _write_new(path, HEADER + _dump(document))
    return path


def refused_path(project: Project, plan: Plan, call: Call) -> Path:
    return round_dir(project, plan.round) / REFUSED_DIR / f"{call.filename}.txt"


def _keep(project: Project, plan: Plan, call: Call, why: str, text: str, today: date) -> Path:
    """Keep a refused reply where the author can read it and no gate will."""
    path = refused_path(project, plan, call)
    path.parent.mkdir(parents=True, exist_ok=True)
    note = (
        f"This is not a review record. It is the reply {call.model.reader} gave when asked "
        f"to read {call.reviewer}'s remit\nin round {plan.round} on {today.isoformat()}, "
        f"kept so that it can be read. It was not filed: {why}\n"
        "Nothing here is counted by any check. Delete it when you have read it.\n"
        f"{'-' * 72}\n{text}\n"
    )
    # A reply can hold half of a surrogate pair, which no file can: it is kept as `?`.
    path.write_bytes(note.encode("utf-8", errors="replace"))
    return path


def _forget(project: Project, plan: Plan, call: Call) -> None:
    """A reading that is now filed has no refused reply worth keeping."""
    path = refused_path(project, plan, call)
    path.unlink(missing_ok=True)
    if path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()


def _clean(text: str, keys: list[str]) -> str:
    """`text` without any key of this run, whole or in part: a reply or an error
    that repeats one is still printed and kept."""
    for key in keys:
        text = client.without_key(text, key)
    return text


def _one(
    project: Project,
    plan: Plan,
    call: Call,
    key: str | None,
    keys: list[str],
    transport: Transport | None,
    today: date,
) -> Outcome:
    """Make one call and file its reading, or say why not. Never raises."""
    why, text = "", ""
    try:
        reply = client.call(call.model, call.body, key=key, transport=transport)
        text = reply.text
        parsed = parse_reply(reply.text)
        path = file_reading(project, plan, call, reply, parsed, today, keys)
    except CallFailed as exc:
        why, text = str(exc), exc.text
    except ReplyRefused as exc:
        why = str(exc)
    except FileExistsError:
        name = reading_path(project, plan.round, call.reviewer, call.model.reader).name
        why = f"{name} already exists, and a record is not replaced; the reply was not filed"
    except Exception as exc:  # noqa: BLE001 - one reading failing must not lose the others
        why = f"{type(exc).__name__}: {exc}"
    else:
        with contextlib.suppress(OSError):
            _forget(project, plan, call)
        majors = sum(1 for finding in parsed["findings"] if finding["severity"] == "major")
        return Outcome(call, path, parsed["verdict"], len(parsed["findings"]), majors)

    # Printed, so nothing in it that a terminal would act on or could not show.
    why = "".join(char if char.isprintable() else " " for char in _clean(why, keys))
    kept = None
    if text.strip():
        try:
            kept = _keep(project, plan, call, why, _clean(text, keys), today)
        except OSError as exc:
            why += f" (and the reply could not be kept to read: {type(exc).__name__})"
    return Outcome(call, failure=why, kept=kept)


def run_plan(
    project: Project,
    plan: Plan,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    today: date | None = None,
    say: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    """Make every call of the plan. Providers are asked side by side, each one call at a
    time, so one slow provider does not hold the others and none is flooded."""
    today = today or date.today()
    held = {provider: read_key(provider, environ) for provider in providers_of(plan)}
    keys = [key for key in held.values() if key]
    told = threading.Lock()

    def ask(provider: Provider) -> list[Outcome]:
        outcomes = []
        for call in plan.calls:
            if call.model.provider != provider:
                continue
            outcome = _one(project, plan, call, held[provider], keys, transport, today)
            outcomes.append(outcome)
            if say is not None:
                with told:
                    say(outcome)
        return outcomes

    with ThreadPoolExecutor(max_workers=max(1, len(held))) as pool:
        done = [outcome for outcomes in pool.map(ask, list(held)) for outcome in outcomes]
    order = {id(call): index for index, call in enumerate(plan.calls)}
    return sorted(done, key=lambda outcome: order[id(outcome.call)])


__all__ = [
    "REFUSED_DIR",
    "Outcome",
    "file_reading",
    "missing_keys",
    "providers_of",
    "run_plan",
    "write_panel",
]
