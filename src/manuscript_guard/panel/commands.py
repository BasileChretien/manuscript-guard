"""What `manuscript-guard review --providers` and `review --run` print and return.

Kept out of `cli.py`, which only parses the flags and hands over.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from manuscript_guard.contracts import ContractError, load_project
from manuscript_guard.contracts.project import PAPER_FILE, find_root
from manuscript_guard.gates.review import reading_slug
from manuscript_guard.panel.providers import (
    ConfigError,
    Provider,
    configured_models,
    key_is_set,
    known_providers,
    read_key,
)

EXAMPLE = "review:\n  models: [openai/<model>, mistral/<model>, moonshot/<model>]"


def _key_words(provider: Provider, environ: Mapping[str, str] | None) -> tuple[str, str]:
    """The variable's name and whether it is set. Never anything of the key."""
    state = key_is_set(provider, environ)
    if state is None:
        return "(none)", "-"
    return provider.key_env or "", "set" if state else "unset"


def _shown(path: Path, root: Path) -> str:
    """A path as the author is shown it: relative to the project where it is inside it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _table(rows: Sequence[tuple[str, ...]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def list_providers(start: Path, environ: Mapping[str, str] | None = None) -> int:
    """List the providers, each key's variable and whether it is set.

    Works outside a project, where it shows the built-in providers only.
    """
    from manuscript_guard.panel.plan import passed_on
    try:
        find_root(start)
    except ContractError:
        project = None
    else:
        # A paper.yaml that cannot be read is an error to report, not a missing project.
        project, _ = load_project(start)
    paper = project.paper if project is not None else {}

    try:
        known = known_providers(paper)
        models = configured_models(paper)
    except ConfigError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    rows = [("provider", "key variable", "key", "host")]
    for provider in known.values():
        variable, state = _key_words(provider, environ)
        where = provider.host + ("  (this machine)" if provider.local else "")
        rows.append((provider.name, variable, state, where))
    print(_table(rows))
    print()

    if project is None:
        print("No paper.yaml here, so only the built-in providers are shown.")
        return 0
    if not models:
        print("paper.yaml lists no models. To have a panel read by several, add:\n")
        print(EXAMPLE)
        return 0

    print("review.models in paper.yaml:")
    ready = []
    for model in models:
        state = "ready"
        if key_is_set(model.provider, environ) is False:
            state = f"{model.provider.key_env} is not set"
        else:
            try:
                read_key(model.provider, environ)
            except ConfigError:
                state = f"{model.provider.key_env} is set, but to something that is not a key"
        if passed_on(model):
            state += "; leaves this machine through Ollama's servers"
        ready.append((f"  {model.reader}", state))
    print(_table(ready))
    return 0


def run_panel(
    start: Path,
    *,
    round_number: int | None,
    one_each: bool,
    dry_run: bool,
    yes: bool = False,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Have a round of the panel read by the models in `review.models`.

    The same statement is printed whether or not anything is sent: which files go to which
    host, and how many calls that is. A dry run stops there. A run then needs a yes, typed
    at a terminal or given as `--yes`, and without one sends nothing and writes nothing.
    """
    from manuscript_guard.panel.plan import PlanError, describe, make_plan, unread

    project, contract = load_project(start)
    # What a request says about the paper is read from paper.yaml, so a file its schema
    # refuses is not planned from: a keyword list written as one string was sent letter by
    # letter. `check` reports the same findings; here they stop the plan.
    broken = [
        finding
        for finding in contract.failures
        if finding.path is not None and finding.path.name == PAPER_FILE
    ]
    if broken:
        said = "; ".join(finding.message for finding in broken[:5])
        print(
            f"manuscript-guard: {PAPER_FILE} does not fit its schema, so nothing is planned "
            f"from it: {said}",
            file=sys.stderr,
        )
        return 2
    try:
        plan = make_plan(project, round_number=round_number, one_each=one_each)
    except PlanError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(describe(plan, project, environ))
    print()
    if not plan.calls:
        waiting = unread(project, plan.round)
        if waiting:
            print(
                "Every reading this run would ask for is on file, so there is nothing to "
                "send. The round is not complete:"
            )
            print(_still_waiting(waiting))
            return 1
        print("Every reading of this round is already on file, so there is nothing to send.")
        return 0
    if dry_run:
        return _dry_run(plan, project)
    return _send(plan, project, yes, environ)


def _still_waiting(waiting: Sequence[tuple[str, str]]) -> str:
    """The readers the panel names that have not reported, and the two ways out."""
    rows = _table([(f"  {reviewer}", reader) for reviewer, reader in waiting])
    return (
        "the panel names these readers, and their readings are not on file:\n"
        f"{rows}\n"
        "This run did not ask them: they are not in review.models, or --one-each dealt "
        "another model to that reviewer. A model is listed there and the command run again. "
        "A person files their own reading: `manuscript-guard review --record <reviewer> "
        "--reading <who> --verdict <verdict>`. A reader that is not going to report is "
        "taken out of its reviewer's `readers` in the panel file."
    )


def _dry_run(plan, project) -> int:
    from manuscript_guard.panel.plan import AS_TEXT, dry_run_dir, write_dry_run

    written = write_dry_run(plan, project)
    where = _shown(dry_run_dir(plan, project), project.root)
    print(
        "Dry run: nothing was sent. The request bodies, exactly as a run would send them, "
        f"are in {where}/ with the SHA-256 of each:"
    )
    by_name = {call.filename: call for call in plan.calls}
    print(_table([(f"  {path.name}", by_name[path.stem].prompt_sha256) for path in written]))
    print(f"\nTo read what they say, open {where}/{AS_TEXT}.")
    return 0


def interactive() -> bool:
    """Whether somebody is there to be asked."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _agreed(plan, hosts: str) -> bool:
    """Ask, and take nothing but the word yes for an answer."""
    calls = f"{len(plan.calls)} call{'' if len(plan.calls) == 1 else 's'}"
    try:
        typed = input(f"Send these {calls} to {hosts}? Type yes to send: ")
    except (EOFError, KeyboardInterrupt):
        # A closed prompt, or Ctrl+C, which is how many people say no.
        return False
    return typed.strip().lower() == "yes"


def _send(plan, project, yes: bool, environ: Mapping[str, str] | None) -> int:
    from manuscript_guard.panel.plan import passed_on_calls, unread
    from manuscript_guard.panel.run import (
        REFUSED_DIR,
        missing_keys,
        providers_of,
        run_plan,
        unfileable,
        write_panel,
    )
    from manuscript_guard.record import RecordError

    # Known before anything is sent, so nothing is: half a panel sent for a reason that could
    # have been said in advance is a round to finish and a manuscript already disclosed.
    missing = missing_keys(plan, environ)
    if missing:
        names = ", ".join(f"{p.key_env} (for {p.name})" for p in missing)
        print(
            f"manuscript-guard: nothing was sent. Not set in the environment: {names}. Set "
            "it, or take that provider's models out of review.models in paper.yaml.",
            file=sys.stderr,
        )
        return 2

    for provider in providers_of(plan):
        try:
            read_key(provider, environ)
        except ConfigError as exc:
            print(f"manuscript-guard: nothing was sent. {exc}", file=sys.stderr)
            return 2

    # A record holds more than the reply, and what the tool adds has to fit its schema too.
    why = unfileable(project, plan)
    if why:
        print(
            "manuscript-guard: nothing was sent. No reply could be filed as a review record "
            f"of this manuscript as it stands: {why}",
            file=sys.stderr,
        )
        return 2

    # The line the author answers says where the manuscript goes, not only the address it
    # is handed to: an Ollama cloud model is reached at localhost and sent on from there.
    hosts = ", ".join(
        provider.host
        + (" and on to Ollama's servers" if passed_on_calls(plan, provider) else "")
        for provider in providers_of(plan)
    )
    if not yes:
        if not interactive():
            print(
                "manuscript-guard: nothing was sent. The manuscript is unpublished and this "
                f"would send it to {hosts}; that needs a yes. Run the command in a terminal "
                "to be asked, or add --yes.",
                file=sys.stderr,
            )
            return 2
        if not _agreed(plan, hosts):
            print("Nothing was sent.", file=sys.stderr)
            return 2

    try:
        panel = write_panel(project, plan)
    except RecordError as exc:
        print(f"manuscript-guard: nothing was sent. {exc}", file=sys.stderr)
        return 2
    print(f"panel: {panel.relative_to(project.root).as_posix()}")

    def say(outcome) -> None:
        who = f"  {outcome.call.reviewer}  {outcome.call.model.reader}"
        if outcome.filed:
            count = f"{outcome.findings} finding{'' if outcome.findings == 1 else 's'}"
            major = f" ({outcome.major} major)" if outcome.major else ""
            print(f"{who}  filed: {outcome.verdict}, {count}{major}", flush=True)
        else:
            print(f"{who}  not filed: {outcome.failure}", flush=True)

    def stopping() -> None:
        print(
            "Stopping: no further call is sent. Waiting for the calls already made, whose "
            "replies are filed; they cannot be recalled.",
            flush=True,
        )

    outcomes = run_plan(project, plan, environ=environ, say=say, stopping=stopping)
    filed = [outcome for outcome in outcomes if outcome.filed]
    unsent = [outcome for outcome in outcomes if not outcome.sent]
    where = f"review/round-{plan.round}"
    print(f"\nFiled {len(filed)} of {len(outcomes)} readings in {where}/.")
    if unsent:
        print(f"The run was stopped: {len(unsent)} of {len(outcomes)} calls were not sent.")
    if len(filed) < len(outcomes):
        print(
            "The round is not complete until the rest are filed: the panel names every "
            "reader that was asked. Run the command again to ask only for those."
        )
        if any(outcome.kept for outcome in outcomes):
            print(
                f"A reply that was refused is kept to read in {where}/{REFUSED_DIR}/. It is "
                "not a review record and no check counts it."
            )
    # Readers the panel names that this run did not ask. Without this the command said two
    # of two were filed, and exited 0, with the panel still waiting for two others.
    asked = {(outcome.call.reviewer, outcome.call.filename) for outcome in outcomes}
    others = [
        (reviewer, reader)
        for reviewer, reader in unread(project, plan.round)
        if (reviewer, f"{reviewer}.{reading_slug(reader)}") not in asked
    ]
    if others:
        print("The round is not complete: " + _still_waiting(others))
    print(
        "`manuscript-guard review` shows where the round stands. Answer each major finding "
        "in its record with a `resolution` or an `overridden`."
    )
    return 0 if len(filed) == len(outcomes) and not others else 1


__all__ = ["interactive", "list_providers", "run_panel"]
