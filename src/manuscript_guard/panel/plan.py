"""Which calls a run would make, built exactly as they would be sent.

A plan is made before anything leaves the machine, and it is the whole of what would: every
request body, for every reviewer and model. The dry run prints it and writes the bodies to
`build/`, a run shows the same statement and asks, and both build the plan with this one
function, so what the author agreed to and what is sent cannot differ.

By default every configured model reads every reviewer's remit, because the point of several
models is that one's blind spot is another's finding. `one_each` is the cheaper mode: one
model per reviewer, dealt across the list in turn.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.review import (
    panel_path,
    panels,
    reading_path,
    reading_slug,
)
from manuscript_guard.panel.client import ANTHROPIC_DEFAULT_MAX_TOKENS, build_body
from manuscript_guard.panel.prompt import (
    FROM_PAPER,
    NOT_SENT,
    Material,
    PromptError,
    gather,
    system_text,
)
from manuscript_guard.panel.providers import (
    ANTHROPIC,
    ConfigError,
    Model,
    configured_models,
    key_is_set,
    read_key,
)

DRY_RUN_DIR = ("review", "dry-run")
AS_TEXT = "as-text.txt"
RULE = "=" * 12
CHARS_PER_TOKEN = 4
#: How a model a server on this machine passes on is named. Ollama serves its cloud models
#: through the same local API as the ones it runs, and sends their requests to its own
#: servers; it names them with a `-cloud` suffix or a `cloud` tag.
PASSED_ON = ("-cloud", ":cloud")

#: Used when a round has no panel file, so that a first run needs nothing but the list of
#: models. Written for any empirical paper: no field, design or journal is assumed, and each
#: `why` says so. A panel fitted to the paper is better, and the file is there to be edited.
STARTER_PANELS: dict[int, tuple[dict, ...]] = {
    1: (
        {
            "id": "design-methods",
            "role": "Methodologist for this kind of study",
            "remit": "Whether the design can answer the question the paper asks. How the "
            "units studied, the comparison and the outcome are defined; the sources of bias "
            "and the alternative explanations the design leaves open; and whether the "
            "Methods say enough for someone else to repeat the work.",
            "why": "A conclusion can be no stronger than the design that produced it.",
        },
        {
            "id": "statistics",
            "role": "Statistician",
            "remit": "Whether the analysis fits the design and is stated fully enough to "
            "reproduce. Estimators and their intervals, small samples, multiple "
            "comparisons, missing data, and whether each reported number can be "
            "reconstructed from what the paper reports.",
            "why": "The results are numbers, and somebody has to check that they follow "
            "from the analysis the paper describes.",
        },
        {
            "id": "reporting-auditor",
            "role": "Reporting-guideline auditor",
            "remit": "Whether each item of the declared reporting guideline is addressed in "
            "the text, in the place a reader would look for it. Where no guideline is "
            "declared, whether a reader could tell what was done, to what, and how many "
            "were lost at each step.",
            "why": "Journals ask for the completed checklist at submission, and an item "
            "answered afterwards is an item nobody checked.",
        },
        {
            "id": "adversarial",
            "role": "Reviewer looking for the reason to reject",
            "remit": "The weakest link between the data and the central claim. Where the "
            "title, the abstract or the conclusion says more than the results support, and "
            "the single objection the authors would find hardest to answer.",
            "why": "The others each check that their own part holds. Somebody has to look "
            "for the reason the whole does not.",
        },
    ),
    # Deliberately nobody from round one: a second pass by the same remits mostly confirms
    # itself. These two meet the paper as its readers will.
    2: (
        {
            "id": "desk-editor",
            "role": "Journal editor deciding whether to send the paper to review",
            "remit": "Whether this would survive triage at the target journal: scope, "
            "whether the abstract claims what the paper shows, length and structure against "
            "the journal's requirements, and whether the required statements are present "
            "and say something.",
            "why": "Rejection without review is the most common outcome and the cheapest "
            "to avoid.",
        },
        {
            "id": "subject-reader",
            "role": "Specialist reader in the paper's field",
            "remit": "What a reader in the field would take away, and whether that is what "
            "the data support. Missing context, over-reading of the main result, and "
            "whether the limitations are stated where a hurried reader will meet them.",
            "why": "The paper will be read by people in its field, who will act on what "
            "they take from it.",
        },
    ),
}

EXAMPLE = "review:\n  models: [openai/<model>, mistral/<model>, moonshot/<model>]"


class PlanError(Exception):
    """No plan can be made, and the reason is in the message."""


@dataclass(frozen=True)
class Call:
    reviewer: str
    model: Model
    #: The request body as it is sent. It never holds a key.
    body: bytes

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def filename(self) -> str:
        """The stem a reading by this model of this remit is filed under."""
        return f"{self.reviewer}.{reading_slug(self.model.reader)}"


@dataclass(frozen=True)
class Plan:
    round: int
    panel: Path
    panel_exists: bool
    reviewers: tuple[dict, ...]
    models: tuple[Model, ...]
    one_each: bool
    #: Every reviewer and reader this round is read by, as (reviewer id, reader), whether
    #: the reading is still to be asked for or already on file.
    pairs: tuple[tuple[str, str], ...]
    #: The pairs still to be asked for.
    calls: tuple[Call, ...]
    #: Pairs left out because their reading is already on file.
    already_filed: int
    max_output_tokens: int | None
    material: Material


def starter_panel(round_number: int) -> tuple[dict, ...]:
    """The reviewers a run asks when the round has no panel file. Rounds 1 and 2 only."""
    return tuple(dict(reviewer) for reviewer in STARTER_PANELS.get(round_number, ()))


def _reviewers_of(path: Path) -> list[dict]:
    try:
        document = read_structured(path)
    except ContractError as exc:
        raise PlanError(str(exc)) from None
    report = validate(document, "panel", path)
    if not report.ok or not isinstance(document, dict):
        said = "; ".join(finding.message for finding in report.findings[:3])
        raise PlanError(f"{path.name} is not a valid panel, so nothing is sent: {said}")
    ids = [reviewer["id"] for reviewer in document["reviewers"]]
    repeated = sorted({name for name in ids if ids.count(name) > 1})
    if repeated:
        # G11 reports this as `duplicate-reviewer`. Here it would be two calls whose replies
        # are filed under one name, the second refused after it had been paid for.
        raise PlanError(
            f"{path.name} lists {', '.join(repeated)} twice, so nothing is sent: give each "
            "reviewer an id of its own"
        )
    return list(document["reviewers"])


def _read_in_full(project: Project, number: int, reviewer: dict) -> bool:
    """Whether a remit has every reading its panel asks for, as G11 counts them: one from
    each reader it names, or the reviewer's plain record when it names none."""
    readers = reviewer.get("readers")
    if not readers:
        return reading_path(project, number, reviewer["id"]).exists()
    return all(
        reading_path(project, number, reviewer["id"], str(reader)).exists()
        for reader in readers
    )


def unread(project: Project, number: int) -> list[tuple[str, str]]:
    """The readers a round's panel names whose reading is not on file, as (reviewer,
    reader). Empty when the round has no panel, or one that cannot be read.

    A run asks the models listed now. The panel may name others: a model since taken out of
    `review.models`, or one that `--one-each` dealt to another reviewer this time. The
    command must not call a round read while the panel is still waiting for them.
    """
    path = panel_path(project, number)
    if not path.exists():
        return []
    try:
        reviewers = _reviewers_of(path)
    except PlanError:
        return []
    return [
        (reviewer["id"], str(reader))
        for reviewer in reviewers
        for reader in reviewer.get("readers") or ()
        if not reading_path(project, number, reviewer["id"], str(reader)).exists()
    ]


def next_round(project: Project) -> int:
    """The first round in which somebody has not reported, else the one after the last."""
    last = 0
    for number, path in panels(project):
        last = max(last, number)
        try:
            reviewers = _reviewers_of(path)
        except PlanError:
            return number
        if not all(_read_in_full(project, number, reviewer) for reviewer in reviewers):
            return number
    return last + 1


def _pairs(reviewers: tuple[dict, ...], models: tuple[Model, ...], one_each: bool):
    if one_each:
        return [(reviewer, models[i % len(models)]) for i, reviewer in enumerate(reviewers)]
    return [(reviewer, model) for reviewer in reviewers for model in models]


def make_plan(
    project: Project, *, round_number: int | None = None, one_each: bool = False
) -> Plan:
    """Every call a run of this round would make. Nothing is written and nothing is sent."""
    try:
        models = configured_models(project.paper)
    except ConfigError as exc:
        raise PlanError(str(exc)) from None
    if not models:
        raise PlanError(
            "paper.yaml lists no models to read the panel. Add, for example:\n\n"
            f"{EXAMPLE}\n\n`manuscript-guard review --providers` lists the providers"
        )
    names: dict[str, str] = {}
    for model in models:
        clash = names.setdefault(reading_slug(model.reader), model.reader)
        if clash != model.reader:
            raise PlanError(
                f"{clash} and {model.reader} would be filed under one file name "
                f"({reading_slug(model.reader)}); list one of them"
            )

    number = next_round(project) if round_number is None else round_number
    if number < 1:
        raise PlanError("rounds are numbered from 1")
    path = panel_path(project, number)
    exists = path.exists()
    reviewers = tuple(_reviewers_of(path)) if exists else starter_panel(number)
    if not reviewers:
        raise PlanError(
            f"round {number} has no panel, and only rounds 1 and 2 have a starter. Say who "
            f"reads the manuscript in this round by writing review/{path.name}; the "
            "reviewers of an earlier panel can be copied into it"
        )

    try:
        material = gather(project)
    except PromptError as exc:
        raise PlanError(str(exc)) from None

    review = project.paper.get("review")
    cap = review.get("max_output_tokens") if isinstance(review, dict) else None
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
        raise PlanError(
            "review.max_output_tokens in paper.yaml is a whole number of tokens; "
            f"{cap!r} is not one"
        )
    paired = _pairs(reviewers, models, one_each)
    calls: list[Call] = []
    filed = 0
    for reviewer, model in paired:
        if reading_path(project, number, reviewer["id"], model.reader).exists():
            filed += 1
            continue
        body = build_body(model, system_text(reviewer), material.user, max_output_tokens=cap)
        calls.append(Call(reviewer["id"], model, body))

    return Plan(
        round=number,
        panel=path,
        panel_exists=exists,
        reviewers=reviewers,
        models=models,
        one_each=one_each,
        pairs=tuple((reviewer["id"], model.reader) for reviewer, model in paired),
        calls=tuple(calls),
        already_filed=filed,
        max_output_tokens=cap,
        material=material,
    )


# ------------------------------------------------------------------------- saying what it is


def passed_on(model: Model) -> bool:
    """Whether a model served on this machine is known to be sent on from there.

    The address cannot say: an Ollama cloud model is reached at `localhost:11434` like a
    model Ollama runs, and the statement said "this machine; nothing leaves it" of a
    manuscript about to go to Ollama's servers. The name can, for Ollama's cloud models.
    """
    return model.provider.local and model.name.lower().endswith(PASSED_ON)


def _where(plan: Plan, provider) -> str:
    """Where a provider's calls go, as far as this tool can know it."""
    if not provider.local:
        return "a third party"
    sent_on = [
        model.name for model in plan.models if model.provider == provider and passed_on(model)
    ]
    if sent_on:
        return (
            f"this machine, whose Ollama server passes {', '.join(sent_on)} on to Ollama's "
            "servers: that leaves this machine"
        )
    return "this machine; nothing leaves it unless the server there passes it on"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _columns(rows: Sequence[tuple[str, ...]], indent: str = "  ") -> list[str]:
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return [
        indent
        + "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]


def _headline(plan: Plan) -> str:
    reviewers = _plural(len(plan.reviewers), "reviewer")
    calls = _plural(len(plan.calls), "call")
    if plan.one_each:
        return f"Round {plan.round}: {reviewers}, one model each = {calls}"
    return f"Round {plan.round}: {reviewers} x {_plural(len(plan.models), 'model')} = {calls}"


def describe(plan: Plan, project: Project, environ: Mapping[str, str] | None = None) -> str:
    """What a run of this plan would send, to whom, in words an author can agree to."""
    lines = [_headline(plan)]
    if plan.already_filed:
        lines.append(
            f"  ({_plural(plan.already_filed, 'reading')} already on file and not asked for "
            "again)"
        )
    if not plan.one_each and len(plan.models) > 1:
        lines.append(
            f"  (--one-each would make {len(plan.reviewers)}: one model per reviewer, dealt "
            "in turn)"
        )

    lines.append("")
    panel = plan.panel.relative_to(project.root).as_posix()
    if plan.panel_exists:
        lines.append(f"The panel is {panel}:")
    else:
        lines.append(
            f"There is no {panel}. A run writes this starter panel there, for you to edit:"
        )
    lines += _columns(
        [(reviewer["id"], str(reviewer.get("role") or "")) for reviewer in plan.reviewers]
    )

    size = max((len(call.body) for call in plan.calls), default=0)
    lines += [
        "",
        f"Each call sends about {size:,} bytes, roughly {size // CHARS_PER_TOKEN:,} tokens "
        f"at {CHARS_PER_TOKEN} characters a token. That is an estimate, and no price is "
        "built in:",
    ]
    lines += _columns([(sent.label, sent.note) for sent in plan.material.sent])
    lines.append(f"  from paper.yaml: {FROM_PAPER}")
    lines.append("  the reviewer's own role, remit and reason, from the panel")
    if plan.material.unrendered:
        count = plan.material.unrendered
        lines.append(
            f"  ({_plural(count, 'binding')} {'has' if count == 1 else 'have'} no value yet "
            "and would be sent as written)"
        )
    lines += ["", f"Not sent: {', '.join(NOT_SENT)}.", "", "Where it goes:"]

    rows = []
    for provider in dict.fromkeys(model.provider for model in plan.models):
        count = sum(1 for call in plan.calls if call.model.provider == provider)
        state = key_is_set(provider, environ)
        if state is None:
            key = "no key"
        elif state and not _usable(provider, environ):
            key = f"key in {provider.key_env}: set, but not a key"
        else:
            key = f"key in {provider.key_env}: {'set' if state else 'unset'}"
        where = _where(plan, provider)
        rows.append((provider.name, provider.host, _plural(count, "call"), key, where))
    lines += _columns(rows)

    lines.append("")
    if plan.max_output_tokens:
        uncapped = [
            m.reader
            for m in plan.models
            if m.provider.api != ANTHROPIC and not m.provider.max_tokens_field
        ]
        lines.append(
            f"Each reply is capped at {plan.max_output_tokens:,} tokens"
            + (
                f", except {', '.join(uncapped)}, which gets no cap: its endpoint documents "
                "no way to set one."
                if uncapped
                else "."
            )
        )
    else:
        capped = [m.reader for m in plan.models if m.provider.api == ANTHROPIC]
        lines.append(
            "No cap is set on a reply (review.max_output_tokens in paper.yaml sets one)"
            + (
                f", except {', '.join(capped)}: {ANTHROPIC_DEFAULT_MAX_TOKENS:,} tokens, "
                "because that API requires one."
                if capped
                else "."
            )
        )
    return "\n".join(lines)


def _usable(provider, environ: Mapping[str, str] | None) -> bool:
    """Whether the key that is set could be sent: a run refuses one that could not."""
    try:
        read_key(provider, environ)
    except ConfigError:
        return False
    return True


def dry_run_dir(plan: Plan, project: Project) -> Path:
    return project.path("build") / DRY_RUN_DIR[0] / f"round-{plan.round}" / DRY_RUN_DIR[1]


def write_dry_run(plan: Plan, project: Project) -> list[Path]:
    """Write each request body where the author can read it. Under `build/` and nowhere else.

    Bodies from an earlier dry run are removed first: left behind, they would read as part
    of this plan.
    """
    directory = dry_run_dir(plan, project)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in (*directory.glob("*.json"), directory / AS_TEXT):
        stale.unlink(missing_ok=True)
    written = []
    for call in plan.calls:
        path = directory / f"{call.filename}.json"
        path.write_bytes(call.body)
        written.append(path)
    (directory / AS_TEXT).write_text(as_text(plan), encoding="utf-8", newline="\n")
    return written


def as_text(plan: Plan) -> str:
    """The same messages the bodies carry, laid out to be read rather than sent.

    A body is JSON, with every line break written as an escape. This is what it says: each
    reviewer's instructions, then the one message every reviewer and model is given.
    """
    parts = [
        f"What round {plan.round} of the panel would be sent. The files beside this one "
        "are the request bodies, byte for byte; this is their text, for reading.",
    ]
    asked = {call.reviewer for call in plan.calls}
    for reviewer in plan.reviewers:
        if reviewer["id"] in asked:
            parts += [f"{RULE} instructions to {reviewer['id']}", system_text(reviewer).rstrip()]
    parts += [f"{RULE} the message every reviewer is given", plan.material.user.rstrip()]
    return "\n\n".join(parts) + "\n"


__all__ = [
    "AS_TEXT",
    "Call",
    "Plan",
    "PlanError",
    "as_text",
    "describe",
    "dry_run_dir",
    "make_plan",
    "next_round",
    "starter_panel",
    "unread",
    "write_dry_run",
]
