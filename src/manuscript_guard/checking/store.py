"""The record of who checked what, and the reading of a co-author's answers.

One append-only CSV, `checks/decisions.csv`, holding every decision anyone has made. Append-only
because the question "was this checked, and by whom, and when" is asked months later by a person
answering a reviewer, and a file that is rewritten cannot answer it. The latest decision by one
person for one item is the one that counts; the earlier ones stay, and say what changed.

A decision carries the digest of the item as its maker saw it. An answer whose digest no longer
matches the project is not recorded as agreement: the sentence or the value moved after they
looked, so their yes is about text nobody has now, and the item is outstanding again. That is
the whole reason the digest exists.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from manuscript_guard.checking.items import Items

ANSWERS_SCHEMA = "manuscript-guard/checking-answers/1"
DECISIONS = "checks/decisions.csv"
FIELDS = ["when", "by", "id", "group", "title", "status", "note", "digest", "bundle"]
#: What a person may answer. "unsure" is not a failure of the checker; it is the honest answer
#: when a document is ambiguous, and it keeps the item outstanding for someone else.
STATUSES = ("ok", "wrong", "unsure")


class AnswersError(Exception):
    """An answers file that cannot be read, or does not belong to this project."""


@dataclass(frozen=True)
class Decision:
    when: str
    by: str
    id: str
    group: str
    title: str
    status: str
    note: str
    digest: str
    bundle: str


@dataclass(frozen=True)
class Imported:
    """What one answers file added, and what it could not."""

    by: str
    recorded: tuple[Decision, ...]
    stale: tuple[tuple[str, str], ...]       # (what to call the item, why)
    unknown: tuple[str, ...]                 # ids this project does not have


def decisions_path(project_root: Path) -> Path:
    return project_root / DECISIONS


def read_decisions(project_root: Path) -> list[Decision]:
    path = decisions_path(project_root)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            Decision(**{field: str(row.get(field) or "") for field in FIELDS})
            for row in csv.DictReader(handle)
            if row.get("id")
        ]


def _append(project_root: Path, decisions: list[Decision]) -> None:
    path = decisions_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        if new:
            writer.writeheader()
        for decision in decisions:
            writer.writerow(decision.__dict__)


def import_answers(project_root: Path, answers_file: Path, items: Items) -> Imported:
    """Record one co-author's answers, refusing those about items that have since changed."""
    try:
        document = json.loads(answers_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnswersError(
            f"{answers_file} is not an answers file this can read ({exc}). The page writes it "
            f"with its own button; a file edited by hand afterwards may no longer be JSON."
        ) from exc
    if document.get("schema") != ANSWERS_SCHEMA:
        raise AnswersError(
            f"{answers_file}: schema is {document.get('schema')!r}, and this reads "
            f"{ANSWERS_SCHEMA!r}"
        )
    by = str(document.get("by") or "").strip()
    if not by:
        raise AnswersError(f"{answers_file} does not say who made it")

    known = {str(item["id"]): item for item in items.items}
    when = datetime.now().astimezone().isoformat(timespec="seconds")
    recorded: list[Decision] = []
    stale: list[tuple[str, str]] = []
    unknown: list[str] = []

    for answer in document.get("answers") or ():
        identifier = str(answer.get("id") or "")
        item = known.get(identifier)
        if item is None:
            unknown.append(identifier)
            continue
        # The title, not the twelve hex characters of the id: the person reading this refusal has
        # to find the thing and ask somebody about it again.
        called = str(item.get("title") or identifier)
        status = str(answer.get("status") or "").strip()
        if status not in STATUSES:
            stale.append((called, f"answered {status!r}, which is not one of {STATUSES}"))
            continue
        if str(answer.get("digest") or "") != item["digest"]:
            stale.append(
                (
                    called,
                    "the item changed after it was checked, so the answer is about text this "
                    "project no longer has",
                )
            )
            continue
        recorded.append(
            Decision(
                when=str(answer.get("at") or when),
                by=by,
                id=identifier,
                group=str(item.get("group") or ""),
                title=str(item.get("title") or ""),
                status=status,
                note=str(answer.get("note") or "").strip(),
                digest=item["digest"],
                bundle=str(document.get("bundle") or ""),
            )
        )

    if recorded:
        _append(project_root, recorded)
    return Imported(by=by, recorded=tuple(recorded), stale=tuple(stale), unknown=tuple(unknown))


@dataclass(frozen=True)
class Standing:
    """Where the checking stands, for one project."""

    people: tuple[str, ...]
    by_person: dict[str, dict[str, int]]          # person -> status -> how many
    answered: dict[str, set[str]]                 # item id -> the people who answered it
    wrong: tuple[Decision, ...]                   # anything anyone called wrong or was unsure of
    disagreements: tuple[tuple[str, tuple[Decision, ...]], ...]
    outstanding: int
    already: int
    #: Decisions whose item has changed since: the person answered about text nobody has now, so
    #: the item is outstanding again and their answer counts for nothing.
    stale: tuple[Decision, ...] = ()
    #: Decisions about an id this project no longer has at all.
    orphaned: tuple[Decision, ...] = ()

    @property
    def unanswered(self) -> int:
        return self.outstanding


def status(project_root: Path, items: Items) -> Standing:
    """Who has answered what, where two people disagree, and what nobody has answered.

    Only the latest decision per person per item counts; the superseded ones stay in the file.

    **Every decision is held against the item as it is now**, not only as it was at import. The
    first version compared the digest once, when the answers came in, and never again: a value
    edited the day after a round still read as answered by everybody, which is the opposite of
    what the digest is for. A decision whose item has changed since is `stale` — the item is
    outstanding again — and one about an id the project no longer has is `orphaned`.

    An "unsure" is not an answer. The question was put and the person could not settle it, so the
    item stays outstanding for someone else, which is what this toolkit says of it in three
    places and did not do.
    """
    now = {str(item["id"]): str(item.get("digest") or "") for item in items.items}

    latest: dict[tuple[str, str], Decision] = {}
    for decision in read_decisions(project_root):
        latest[(decision.by, decision.id)] = decision

    answered: dict[str, set[str]] = {}
    by_person: dict[str, dict[str, int]] = {}
    stale: list[Decision] = []
    orphaned: list[Decision] = []
    for (person, identifier), decision in sorted(latest.items()):
        held = now.get(identifier)
        if held is None:
            orphaned.append(decision)
            continue
        if decision.digest and held and decision.digest != held:
            stale.append(decision)
            continue
        counts = by_person.setdefault(person, {})
        counts[decision.status] = counts.get(decision.status, 0) + 1
        if decision.status != "unsure":
            answered.setdefault(identifier, set()).add(person)

    outstanding = [
        item for item in items.outstanding if not answered.get(str(item["id"]))
    ]
    disagreements = []
    for identifier, people in sorted(answered.items()):
        said = {latest[(person, identifier)].status for person in people}
        if len(said) > 1:
            disagreements.append(
                (identifier, tuple(latest[(person, identifier)] for person in sorted(people)))
            )
    counted = {(d.by, d.id) for d in stale} | {(d.by, d.id) for d in orphaned}
    return Standing(
        people=tuple(sorted(by_person)),
        by_person=by_person,
        answered=answered,
        wrong=tuple(
            d
            for (person, identifier), d in sorted(latest.items())
            if d.status in ("wrong", "unsure") and (person, identifier) not in counted
        ),
        disagreements=tuple(disagreements),
        outstanding=len(outstanding),
        already=len(items.items) - len(items.outstanding),
        stale=tuple(stale),
        orphaned=tuple(orphaned),
    )
