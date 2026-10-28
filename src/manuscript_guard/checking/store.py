"""The record of who checked what, and the reading of a co-author's answers.

One append-only CSV, `checks/decisions.csv`, holding every decision anyone has made. Append-only
because the question "was this checked, and by whom, and when" is asked months later by a person
answering a reviewer, and a file that is rewritten cannot answer it. The latest decision by one
person for one item is the one that counts; the earlier ones stay, and say what changed.

A decision carries the digest of the item as its maker saw it. An answer whose digest no longer
matches the project is not counted as agreement: the sentence or the value moved after they
looked, so their yes is about text nobody has now, and the item is outstanding again. That is
the whole reason the digest exists. Such an answer is still written down, with the digest they
saw, because the note in it may be the one thing that says what is wrong.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from manuscript_guard.checking.answers import (
    ANSWERS_SCHEMA,
    Answers,
    AnswersError,
    Refused,
    read_answers,
)
from manuscript_guard.checking.items import Items

__all__ = ["ANSWERS_SCHEMA", "Answers", "AnswersError", "Refused", "read_answers"]

DECISIONS = "checks/decisions.csv"
FIELDS = ["when", "by", "id", "group", "title", "status", "note", "digest", "bundle"]
#: What a person may answer. "unsure" is not a failure of the checker; it is the honest answer
#: when a document is ambiguous, and it keeps the item outstanding for someone else.
STATUSES = ("ok", "wrong", "unsure")


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
    #: The decisions that count: each about an item as the project has it now.
    recorded: tuple[Decision, ...]
    #: Recorded with the digest the person saw, and counting for nothing: (what to call the
    #: item, why). The note is kept with it.
    stale: tuple[tuple[str, str], ...]
    #: Recorded, and counting for nothing: what to call each item this project does not have.
    unknown: tuple[str, ...]
    #: Not recorded at all: an answer that is none of `STATUSES`, (what to call it, why).
    refused: tuple[tuple[str, str], ...] = ()
    #: Answers identical to the person's latest decision on the item, so not written again.
    skipped: int = 0
    #: The file names no page this project registered: the name is the file's word.
    claimed: bool = True
    #: Whether `authors.yaml` lists them; None where no project was given to look in.
    author: bool | None = None
    #: The stale and unknown decisions as written, which count for nothing.
    kept: tuple[Decision, ...] = ()


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


def import_answers(project_root: Path, answers_file: Path, items: Items, *,
                   project=None) -> Imported:  # fmt: skip
    """Read one co-author's answers file, hold it to the register, and record it."""
    answers = read_answers(answers_file, project_root=project_root, project=project)
    return record(project_root, answers, items)


def _same(one: Decision, other: Decision | None) -> bool:
    """Whether a new decision says nothing the latest one did not: the same answer, note and
    digest, from the same page. When it was given is not compared: an answer with no time of
    its own takes the time of the import."""
    return other is not None and (one.status, one.note, one.digest, one.bundle) == (
        other.status, other.note, other.digest, other.bundle)  # fmt: skip


def record(project_root: Path, answers: Answers, items: Items) -> Imported:
    """Record one answers file, already read and held to the register.

    An answer about an item that has changed since it was answered is recorded with the digest
    its maker saw, and so is one about an item this project no longer has: both count for
    nothing (`status` holds every decision to the item as it is now), and the note in each is
    kept. An answer identical to that person's latest decision on the item is not written again,
    so importing one file twice adds nothing.
    """
    by = answers.by
    known = {str(item["id"]): item for item in items.items}
    when = datetime.now().astimezone().isoformat(timespec="seconds")
    latest = {(d.by, d.id): d for d in read_decisions(project_root)}
    written: list[Decision] = []
    recorded: list[Decision] = []
    kept: list[Decision] = []
    stale: list[tuple[str, str]] = []
    unknown: list[str] = []
    refused: list[tuple[str, str]] = []
    skipped = 0

    for answer in answers.document.get("answers") or ():
        if not isinstance(answer, dict):
            refused.append((str(answer)[:40], "it is not an answer"))
            continue
        identifier = str(answer.get("id") or "")
        item = known.get(identifier)
        # By the title, not the twelve hex characters of the id: the person reading this has to
        # find the thing and ask somebody about it again. For an item the project no longer has,
        # by the title the page sent with the answer: a cited sentence edited since the page was
        # built is a new item with a new id.
        called = str((item or answer).get("title") or identifier)
        status = str(answer.get("status") or "").strip()
        if not identifier or status not in STATUSES:
            refused.append((called, f"answered {status!r}, which is not one of {STATUSES}"))
            continue
        seen = str(answer.get("digest") or "")
        decision = Decision(
            when=str(answer.get("at") or when),
            by=by,
            id=identifier,
            group=str((item or {}).get("group") or ""),
            title=called,
            status=status,
            note=str(answer.get("note") or "").strip(),
            digest=seen,
            bundle=answers.bundle,
        )
        if _same(decision, latest.get((by, identifier))):
            skipped += 1
            continue
        latest[(by, identifier)] = decision
        written.append(decision)
        if item is None:
            unknown.append(called)
            kept.append(decision)
        elif seen != item["digest"]:
            stale.append(
                (
                    called,
                    "the item changed after it was checked, so the answer is about text this "
                    "project no longer has",
                )
            )
            kept.append(decision)
        else:
            recorded.append(decision)

    if written:
        _append(project_root, written)
    return Imported(
        by=by, recorded=tuple(recorded), stale=tuple(stale), unknown=tuple(unknown),
        refused=tuple(refused), skipped=skipped, claimed=answers.claimed,
        author=answers.author, kept=tuple(kept),
    )  # fmt: skip


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
    #: The decision that counts, for each person and item they answered as it is now.
    counting: tuple[Decision, ...] = ()

    @property
    def unanswered(self) -> int:
        return self.outstanding


def _latest(decisions: list[Decision], now: dict[str, str]) -> dict[tuple[str, str], Decision]:
    """Each person's decision on each item: the latest about the item as it is now, where they
    gave one, and otherwise the latest of all. An answer about an earlier version of an item,
    imported after one about this version, says nothing about this version, so it cannot take
    the place of the answer that does: an old round's file imported late would otherwise have
    put back in the queue every item it named."""
    latest: dict[tuple[str, str], Decision] = {}
    for decision in decisions:
        key = (decision.by, decision.id)
        held = latest.get(key)
        current = decision.digest == now.get(decision.id)
        if held is None or current or held.digest != now.get(held.id):
            latest[key] = decision
    return latest


def status(project_root: Path, items: Items) -> Standing:
    """Who has answered what, where two people disagree, and what nobody has answered.

    Only the latest decision per person per item counts (`_latest`); the superseded ones stay in
    the file.

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
    latest = _latest(read_decisions(project_root), now)

    answered: dict[str, set[str]] = {}
    by_person: dict[str, dict[str, int]] = {}
    stale: list[Decision] = []
    orphaned: list[Decision] = []
    counting: list[Decision] = []
    for (person, identifier), decision in sorted(latest.items()):
        held = now.get(identifier)
        if held is None:
            orphaned.append(decision)
            continue
        # A decision with no digest is about nothing anyone can name, and so not about this.
        if decision.digest != held:
            stale.append(decision)
            continue
        counting.append(decision)
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
    return Standing(
        people=tuple(sorted(by_person)),
        by_person=by_person,
        answered=answered,
        wrong=tuple(d for d in counting if d.status in ("wrong", "unsure")),
        disagreements=tuple(disagreements),
        outstanding=len(outstanding),
        already=len(items.items) - len(items.outstanding),
        stale=tuple(stale),
        orphaned=tuple(orphaned),
        counting=tuple(counting),
    )
