"""What `manuscript-guard review --providers` and `review --run` print and return.

Kept out of `cli.py`, which only parses the flags and hands over.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from manuscript_guard.contracts import ContractError, load_project
from manuscript_guard.contracts.project import find_root
from manuscript_guard.panel.providers import (
    ConfigError,
    Provider,
    configured_models,
    key_is_set,
    known_providers,
)

EXAMPLE = "review:\n  models: [openai/<model>, mistral/<model>, moonshot/<model>]"


def _key_words(provider: Provider, environ: Mapping[str, str] | None) -> tuple[str, str]:
    """The variable's name and whether it is set. Never anything of the key."""
    state = key_is_set(provider, environ)
    if state is None:
        return "(none)", "-"
    return provider.key_env or "", "set" if state else "unset"


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
        missing = key_is_set(model.provider, environ) is False
        ready.append(
            (
                f"  {model.reader}",
                f"{model.provider.key_env} is not set" if missing else "ready",
            )
        )
    print(_table(ready))
    return 0


def run_panel(
    start: Path,
    *,
    round_number: int | None,
    one_each: bool,
    dry_run: bool,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Say what a run of the panel would send, and to whom. This version sends nothing."""
    from manuscript_guard.panel.plan import (
        AS_TEXT,
        PlanError,
        describe,
        dry_run_dir,
        make_plan,
        write_dry_run,
    )

    if not dry_run:
        print(
            "manuscript-guard: this version shows what a run would send and sends nothing. "
            "Add --dry-run to see it; sending the panel to the providers comes in a later "
            "release.",
            file=sys.stderr,
        )
        return 2

    project, _ = load_project(start)
    try:
        plan = make_plan(project, round_number=round_number, one_each=one_each)
    except PlanError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2

    print(describe(plan, project, environ))
    print()
    if not plan.calls:
        print("Every reading of this round is already on file, so there is nothing to send.")
        return 0

    written = write_dry_run(plan, project)
    where = dry_run_dir(plan, project).relative_to(project.root).as_posix()
    print(
        "Dry run: nothing was sent. The request bodies, exactly as a run would send them, "
        f"are in {where}/ with the SHA-256 of each:"
    )
    by_name = {call.filename: call for call in plan.calls}
    print(_table([(f"  {path.name}", by_name[path.stem].prompt_sha256) for path in written]))
    print(f"\nTo read what they say, open {where}/{AS_TEXT}.")
    return 0


__all__ = ["list_providers", "run_panel"]
