"""When the paper may be shared, and what is due: the embargo, the triggers and `communicate
status`.

paper.yaml says when each text is due:

    communication:
      enabled: true
      channels: [bluesky-thread, mastodon-thread, press-release]
      triggers:
        accepted: [press-release, pitch]
        published: [bluesky-thread, mastodon-thread]
        followups:
          - {after_days: 30, channels: [bluesky]}

A trigger is read against `publication:` (`status.py`): `accepted` from the paper's
acceptance on, `published` once it is online, and a follow-up a number of days after
`publication.published_on`. Without `triggers`, every channel of `channels` is due once the
paper is online. `communicate status` says what is due, what is written and what waits;
`--prepare` writes what is due and not yet written. Nothing runs in the background: the
author asks, and the answer is for the day asked.

The embargo (`publication.embargo_until`) holds every text: before it lifts, `communicate
check` fails each one (`comm-embargo`). A time written with no zone is read where the day
comes last, twelve hours behind UTC, so that it has lifted everywhere when it is read as
lifted; a date alone lifts at the start of that day there. One that cannot be read is held
as not lifted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from manuscript_guard.communicate import GATE, folder
from manuscript_guard.communicate.status import OUT, publication
from manuscript_guard.findings import FAIL, Finding

#: Where a time with no zone is reached last: an embargo read in it has lifted everywhere.
LATEST_ZONE = timezone(timedelta(hours=-12))
_WHEN = re.compile(
    r"\A(?P<day>\d{4}-\d{2}-\d{2})"
    r"(?:[T ](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.\d+)?)?"
    r"[ \t]*(?P<zone>Z|UTC|GMT|[+-]\d{2}(?::?\d{2})?)?)?\Z",
    re.IGNORECASE,
)
ACCEPTED = frozenset({"accepted", *OUT})


def now() -> datetime:
    """This moment, in UTC: what an embargo and a follow-up are read against. A test sets it."""
    return datetime.now(timezone.utc)


def _zone(written: str | None) -> timezone:
    if not written:
        return LATEST_ZONE
    if written.upper() in ("Z", "UTC", "GMT"):
        return timezone.utc
    sign = -1 if written[0] == "-" else 1
    digits = written[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:4] or 0)
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def lifted_at(said: object) -> datetime | None:
    """When an embargo written `said` lifts, as an aware moment; None where it cannot be read.
    `2026-12-01T00:01Z` and `2026-12-01T09:01+09:00` are that moment; `2026-12-01T00:01` and
    `2026-12-01` are read twelve hours behind UTC, where the time comes last."""
    if isinstance(said, datetime):
        return said if said.tzinfo else said.replace(tzinfo=LATEST_ZONE)
    if isinstance(said, date):
        return datetime.combine(said, time(), LATEST_ZONE)
    found = _WHEN.match(str(said).strip())
    if found is None:
        return None
    try:
        day = date.fromisoformat(found["day"])
        at = time(int(found["hour"] or 0), int(found["minute"] or 0), int(found["second"] or 0))
        return datetime.combine(day, at, _zone(found["zone"]))
    except ValueError:
        return None


def embargo_findings(project, path: Path) -> list[Finding]:
    """`comm-embargo` for a text while the journal's embargo holds, or where its time cannot
    be read."""
    said = publication(project).get("embargo_until")
    if said is None or said == "":
        return []
    lifts = lifted_at(said)
    if lifts is None:
        return [Finding(
            GATE, "comm-embargo",
            f"paper.yaml's publication.embargo_until, {str(said)!r}, is no date and time this "
            "can read, so the embargo is held as not lifted",
            FAIL, path, hint="write it as the journal gives it, in ISO 8601 with its zone: "
            "2026-12-01T00:01Z, or 2026-12-01T00:01+01:00",
        )]  # fmt: skip
    if now() >= lifts:
        return []
    return [Finding(
        GATE, "comm-embargo",
        f"the journal's embargo holds until {shown(lifts)}, and nothing of the paper is shared "
        "before it lifts",
        FAIL, path, hint="hold the text until then; `communicate status` says what is due",
    )]  # fmt: skip


def shown(moment: datetime) -> str:
    """A moment as written in a finding: in UTC, to the minute."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------- what is due

TO_WRITE = "to write"
WRITTEN = "written"
BEFORE_OUT = "written before the paper was online"
WAITS = "waits"


@dataclass(frozen=True)
class Due:
    """One channel a trigger names, and where it stands today."""

    channel: str
    #: What makes it due: "accepted", "published", or a number of days after publication.
    when: str
    state: str
    why: str


@dataclass(frozen=True)
class Standing:
    status: str
    due: tuple[Due, ...]
    #: When the embargo lifts, where it has not; "" where there is none or it has.
    embargo: str


def _day(said: object) -> date | None:
    if isinstance(said, date):
        return said
    try:
        return date.fromisoformat(str(said)) if said else None
    except ValueError:
        return None


def triggers(project) -> dict:
    """paper.yaml's triggers, or the default: every channel listed, once the paper is out."""
    setting = project.setting("communication") or {}
    said = setting.get("triggers") if isinstance(setting, dict) else None
    if isinstance(said, dict):
        return said
    channels = setting.get("channels") if isinstance(setting, dict) else None
    return {"published": list(channels or [])}


def _written(project, channel: str) -> dict | None:
    """The front matter of the channel's text, where one is written."""
    from manuscript_guard.communicate.texts import front_matter
    from manuscript_guard.contracts._schema import read_text

    path = folder(project) / f"{channel}.md"
    if not path.is_file():
        return None
    front, _error = front_matter(read_text(path).replace("\r\n", "\n"))
    return front


def standing(project) -> Standing:
    """Each channel a trigger names, and whether it is due, written or waiting, today."""
    said = publication(project)
    status = said.get("status") or "not given"
    published_on = _day(said.get("published_on"))
    today = now().date()
    rules = triggers(project)
    out: list[Due] = []
    seen: set[tuple[str, str]] = set()

    def add(channel: str, when: str, due: bool, why: str, links: bool) -> None:
        if not isinstance(channel, str) or (channel, when) in seen:
            return
        seen.add((channel, when))
        front = _written(project, channel)
        if not due:
            state = WAITS
        elif front is None:
            state = TO_WRITE
        elif links and status in OUT and front.get("version_shared") != "published":
            state = BEFORE_OUT
        else:
            state = WRITTEN
        out.append(Due(channel, when, state, why))

    for channel in rules.get("accepted") or ():
        add(channel, "accepted", status in ACCEPTED,
            "from the paper's acceptance" if status in ACCEPTED else "until the paper is "
            "accepted", False)  # fmt: skip
    for channel in rules.get("published") or ():
        add(channel, "published", status in OUT,
            "once the paper is online" if status in OUT else "until the paper is online",
            True)  # fmt: skip
    for followup in rules.get("followups") or ():
        if not isinstance(followup, dict) or not isinstance(followup.get("after_days"), int):
            continue
        days = followup["after_days"]
        when = f"{days} days after publication"
        if status not in OUT or published_on is None:
            why = ("until the paper is online and paper.yaml gives publication.published_on"
                   if published_on is None else "until the paper is online")  # fmt: skip
            due = False
        else:
            on = published_on + timedelta(days=days)
            due = today >= on
            why = f"from {on.isoformat()}" if due else f"until {on.isoformat()}"
        for channel in followup.get("channels") or ():
            add(channel, when, due, why, True)
    embargo = ""
    lifts = lifted_at(said["embargo_until"]) if said.get("embargo_until") else None
    if said.get("embargo_until") and (lifts is None or now() < lifts):
        embargo = shown(lifts) if lifts else f"{said['embargo_until']} (not read as a time)"
    return Standing(status, tuple(out), embargo)


def render(held: Standing) -> str:
    lines = [f"publication status: {held.status}"]
    if held.embargo:
        lines.append(f"embargo: until {held.embargo}; nothing is shared before it lifts")
    if not held.due:
        lines.append("no channel is named: list them under communication.channels, or "
                     "communication.triggers, in paper.yaml")  # fmt: skip
    for state in (TO_WRITE, BEFORE_OUT, WRITTEN, WAITS):
        mine = [one for one in held.due if one.state == state]
        if not mine:
            continue
        lines += ["", f"{state}:"]
        lines += [f"  {one.channel} ({one.when}, {one.why})" for one in mine]
    if any(one.state == TO_WRITE for one in held.due):
        lines += ["", "`communicate status --prepare` writes what is due and not yet written"]
    if any(one.state == BEFORE_OUT for one in held.due):
        lines += ["", "a text written before the paper was online does not link it: "
                  "`communicate build --channels <name> --force` writes it again"]
    return "\n".join(lines) + "\n"


def to_prepare(held: Standing) -> list[str]:
    return list(dict.fromkeys(one.channel for one in held.due if one.state == TO_WRITE))
