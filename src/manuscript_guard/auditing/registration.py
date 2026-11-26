"""The paper's own registration under `audit --lookup` (Basile, 2026-11-26, item 7a of the
editor's list): each NCT, ISRCTN, EU PAS or PROSPERO number the paper names outside its
reference list, asked of its registry, and what the registry holds shown for an editor to set
beside the paper.

Nothing here reads the paper's outcomes or dates: the registry's primary outcome, its title
and its dates are shown, and whether the paper reports that outcome is the editor's to judge.
What is judged is only what the registry's own dates show: a study registered after its
actual start, compared as far as the less precise of the two dates goes, as G12 compares them
for a project (`gates.registration._after`), and a start after the day the registry was asked
taken for a plan. A number in the reference list is another study's and is not asked; one
named in the text is asked as written, whoever's it is (DESIGN.md, Known gaps).

ClinicalTrials.gov and ISRCTN are asked through their APIs (`lookup.registries`), sending the
number and nothing else. EU PAS and PROSPERO are not asked: their records are read on their
pages, by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.registrations import (
    CLINICALTRIALS,
    EU_PAS,
    ISRCTN,
    NAMED_IN_TEXT,
    NAMES,
    PROSPERO,
    identify,
)

#: The section of the report the findings stand in.
SECTION = "Registration (G12)"
#: The registries the audit asks, by their APIs.
ASKED = (CLINICALTRIALS, ISRCTN)
#: Where each registry the audit does not ask is read by hand.
BY_HAND = {
    EU_PAS: "https://catalogues.ema.europa.eu",
    PROSPERO: "https://www.crd.york.ac.uk/prospero/",
}
#: How much of a registered outcome the record's finding quotes.
QUOTED = 240


@dataclass(frozen=True)
class Named:
    """A registration number the paper names: as the registry keeps it, its registry, where
    it is first named, and how many times it is named."""

    identifier: str
    registry: str
    path: Path
    line: int
    context: str
    times: int = 1


@dataclass(frozen=True)
class Asked:
    """What came of one number: the registry's record or why there is none (`record`), and
    whether it was asked, read from the records kept, not asked (a dry run), or left to be
    read by hand (`came`: "asked", "kept", "", "manual")."""

    named: Named
    record: dict = field(default_factory=dict)
    came: str = ""


@dataclass(frozen=True)
class RegistrationRun:
    asked: tuple[Asked, ...] = ()
    dry_run: bool = False


def named_in(path: Path, hidden: str, text: str) -> list[Named]:
    """Each registration number in a paper's text, with its reference lists blanked (as the
    audit reads it), found in `hidden`, the text with its comments masked at the same
    offsets, so that a number in a comment is not taken; its line and context from `text`."""
    lines = text.split("\n")
    found = []
    for match in NAMED_IN_TEXT.finditer(hidden):
        registry, identifier = identify(match.group(0))
        if registry is None or identifier is None:
            continue
        line = hidden.count("\n", 0, match.start()) + 1
        found.append(Named(identifier, registry, path, line, lines[line - 1].strip()[:200]))
    return found


def gathered(named: list[Named]) -> list[Named]:
    """Each number once, at the first place it is named, with how many times it is."""
    out: dict[str, Named] = {}
    times: dict[str, int] = {}
    for one in named:
        times[one.identifier] = times.get(one.identifier, 0) + 1
        out.setdefault(one.identifier, one)
    return [Named(one.identifier, one.registry, one.path, one.line, one.context,
                  times[one.identifier]) for one in out.values()]  # fmt: skip


def asked_at() -> tuple[str, ...]:
    """Where the registries the audit asks are asked: the audit page's policy names each
    host (tests/test_web.py)."""
    from manuscript_guard.lookup.registries import Services

    services = Services()
    return (services.clinicaltrials, services.isrctn)


def _kept_path(cache: Path, identifier: str) -> Path:
    return cache / f"registration-{identifier}.json"


def look_up(
    named: list[Named],
    *,
    dry_run: bool = False,
    cache: Path | None = None,
    transport: Any = None,
    pacer: Any = None,
    credentials: Any = None,
) -> RegistrationRun:
    """Each number asked of its registry once, through one paced transport, or with
    `dry_run` only what would be asked. A record is read from and written to `cache` only,
    an answer that could not be read never kept."""
    from manuscript_guard.lookup import http, registries
    from manuscript_guard.lookup import run as lookup
    from manuscript_guard.lookup.sources import UNRESOLVABLE

    services = registries.Services()
    ask = None
    out = []
    for one in gathered(named):
        if one.registry not in ASKED:
            out.append(Asked(one, came="manual"))
            continue
        if dry_run:
            out.append(Asked(one))
            continue
        kept = _kept_path(cache, one.identifier) if cache is not None else None
        if kept is not None and kept.exists():
            try:
                out.append(Asked(one, json.loads(kept.read_text(encoding="utf-8")), "kept"))
                continue
            except (OSError, ValueError):
                pass  # a record that cannot be read is asked again
        if ask is None:
            credentials = credentials or lookup.Credentials.from_environment(None)
            ask = lookup._asker(transport or http.default_transport, pacer or lookup.Pacer(),
                                credentials)  # fmt: skip
        if one.registry == CLINICALTRIALS:
            record = registries.clinicaltrials(one.identifier, ask, services.clinicaltrials)
        else:
            record = registries.isrctn(one.identifier, ask, services.isrctn)
        record = {**record, "asked_on": date.today().isoformat()}
        if kept is not None and record.get("status") != UNRESOLVABLE:
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes((json.dumps(record, indent=2, ensure_ascii=True) + "\n").encode())
        out.append(Asked(one, record, "asked"))
    return RegistrationRun(tuple(out), dry_run)


def late(record: dict) -> str | None:
    """The study's actual start, where the registry's own dates show it registered after it
    (`gates.registration._after`): a start after the day the registry was asked is a plan,
    not a start, and is never one."""
    from manuscript_guard.gates.registration import _after

    dates = record.get("dates") or {}
    registered, start = dates.get("registered"), dates.get("study_start")
    asked = record.get("asked_on") or date.today().isoformat()
    if not registered or not start or start[:10] > asked:
        return None
    return start if _after(registered, start) else None


def _primary(record: dict) -> str:
    listed = [section for section in record.get("sections") or []
              if section.get("role") == "primary" and section.get("text")]  # fmt: skip
    if not listed:
        return "it lists no primary outcome"
    # Its measure, description and time frame, one to a line in the record.
    first = "; ".join(" ".join(part.split()) for part in str(listed[0]["text"]).splitlines()
                      if part.strip())
    if len(first) > QUOTED:
        first = first[:QUOTED].rsplit(" ", 1)[0] + "…"
    more = f" (and {len(listed) - 1} more)" if len(listed) > 1 else ""
    return f"its primary outcome: {first}{more}"


def record_said(one: Asked) -> str:
    """What the registry holds, as the record's finding says it."""
    record, named = one.record, one.named
    dates = record.get("dates") or {}
    title = f' as "{record["title"]}"' if record.get("title") else ""
    start = f"; its study started {dates['study_start']}" if dates.get("study_start") else ""
    times = f" (named {named.times} times)" if named.times > 1 else ""
    return (f"{named.identifier}{times}: {NAMES[named.registry]} holds it{title}, registered "
            f"{dates.get('registered', 'on a date not given')}{start}; {_primary(record)}")


def findings(run: RegistrationRun) -> list:
    """The report's items, one or two for each number: what its registry holds, a
    registration after the study's start, or why nothing is held."""
    from manuscript_guard.auditing.report import Item, about
    from manuscript_guard.findings import INFO, WARN
    from manuscript_guard.lookup.sources import ABSENT, FOUND

    out = []
    for one in run.asked:
        named = one.named
        place = (named.path, named.line, named.context)
        name = NAMES[named.registry]
        if one.came == "manual":
            out.append(about(Item(SECTION, "G12", "registration-by-hand",
                                  f"{named.identifier} is in {name}, which the audit does not "
                                  f"ask: read its record at {BY_HAND[named.registry]}", INFO,
                                  False, *place), named.identifier))  # fmt: skip
            continue
        if not one.came:
            out.append(about(Item(SECTION, "G12", "registration-would-ask",
                                  f"{named.identifier}: would ask {name} for its record", INFO,
                                  False, *place), named.identifier))  # fmt: skip
            continue
        status = one.record.get("status")
        why = one.record.get("why") or "no reason given"
        if status == FOUND:
            out.append(about(Item(SECTION, "G12", "registration-record", record_said(one),
                                  INFO, False, *place), named.identifier))  # fmt: skip
            started = late(one.record)
            if started:
                registered = one.record["dates"]["registered"]
                out.append(about(Item(
                    SECTION, "G12", "registration-late",
                    f"{named.identifier} was registered on {registered}, after its study "
                    f"started ({started}), as {name} gives the dates", WARN, False, *place,
                    "a study registered after it started registered nothing in advance: the "
                    "paper says so, and why, where it was registered retrospectively",
                ), named.identifier))  # fmt: skip
        elif status == ABSENT:
            out.append(about(Item(SECTION, "G12", "registration-unknown",
                                  f"{named.identifier}: {why}", WARN, False, *place),
                             named.identifier))  # fmt: skip
        else:
            out.append(about(Item(SECTION, "G12", "registration-unanswered",
                                  f"{named.identifier}: {name} gave no record: {why}", INFO,
                                  False, *place), named.identifier))  # fmt: skip
    return out


__all__ = ["ASKED", "BY_HAND", "SECTION", "Asked", "Named", "RegistrationRun", "findings",
           "gathered", "late", "look_up", "named_in", "record_said"]
