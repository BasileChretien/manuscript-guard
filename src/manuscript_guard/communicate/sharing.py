"""What a text may share of the paper, held to the journal's sharing policy.

A text says in its front matter which version of the paper it shares (`version_shared`:
`preprint`, `accepted`, `published` or `none`) and what it uploads (`attachments`). A
document among the attachments, a PDF or a Word file, is an **upload** of that version, to
the place its channel puts it (`where` in `data/channels.yaml`: ResearchGate is an
`academic-network`, a blog a `personal-site`). An image, the graphical abstract or the
overview slide, is no version of the paper.

Each upload is held to the profile's `sharing` block (`profiles/journals/<journal>.yaml`):

- the version recorded there, and the channel's place among its `where`, else
  `comm-sharing-not-allowed`;
- its `embargo_months` past since `publication.published_on`, else `comm-sharing-not-allowed`;
- where the profile records no sharing policy, or nothing of that version, or the version
  or the place cannot be told, `comm-sharing-unknown`.

A link to the paper's DOI is no upload, and is allowed with a policy or without one: the
author decided on 2026-10-28 that, with no `sharing` block, the DOI is linked and nothing is
uploaded. A link to a copy elsewhere is not read as sharing it (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path, PurePosixPath

from manuscript_guard.communicate import GATE
from manuscript_guard.communicate.status import publication
from manuscript_guard.findings import FAIL, Finding

VERSIONS = ("preprint", "accepted", "published")
#: What an upload of the paper is written as.
DOCUMENTS = frozenset({".pdf", ".docx", ".doc", ".odt", ".rtf", ".epub", ".tex"})


#: The keys of a text's front matter that list files or links: one written alone is a list
#: of one, and any other shape than a list of them is refused (`comm-front-matter`).
LISTED = ("attachments", "links")


def listed(front: dict, key: str) -> list[str] | None:
    """What a text's front matter lists under `key`: a string read as a list of one, nothing
    as none, and None where it is neither nor a list of strings, which is refused."""
    said = front.get(key)
    if said is None:
        return []
    if isinstance(said, str):
        return [said]
    if isinstance(said, list) and all(isinstance(one, str) for one in said):
        return list(said)
    return None


def shape_findings(path: Path, front: dict) -> list[Finding]:
    """`comm-front-matter` for each of `LISTED` that is neither a string nor a list of them:
    what it uploads could not be held to the sharing policy."""
    return [Finding(GATE, "comm-front-matter",
                    f"{path.name}: its front matter's `{key}` is neither a name nor a list of "
                    "them, so what it shares cannot be read", FAIL, path, 1,
                    hint=f"write `{key}: [paper.pdf]`, a list of names")
            for key in LISTED if listed(front, key) is None]  # fmt: skip


def uploads(front: dict) -> list[str]:
    """The attachments of a text that are a document, a version of the paper."""
    return [one for one in listed(front, "attachments") or ()
            if PurePosixPath(one).suffix.lower() in DOCUMENTS]  # fmt: skip


def _policy(project) -> dict | None:
    from manuscript_guard.gates.journal import _profile

    document = _profile(project)
    block = (document or {}).get("sharing")
    return block if isinstance(block, dict) else None


def _plus_months(day: date, months: int) -> date:
    year, month = divmod(day.month - 1 + months, 12)
    year += day.year
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _day(said: object) -> date | None:
    if isinstance(said, date):
        return said
    try:
        return date.fromisoformat(str(said)) if said else None
    except ValueError:
        return None


def sharing_findings(project, path: Path, front: dict, channel: str, rules: dict,
                     today: date) -> list[Finding]:  # fmt: skip
    """`comm-sharing-not-allowed` and `comm-sharing-unknown` for each upload of a text."""
    files = uploads(front)
    if not files:
        return []
    names = ", ".join(files)

    def unknown(why: str, hint: str) -> list[Finding]:
        return [Finding(GATE, "comm-sharing-unknown", f"it uploads {names}, and {why}", FAIL,
                        path, 1, hint=hint)]  # fmt: skip

    def refused(why: str, hint: str) -> list[Finding]:
        return [Finding(GATE, "comm-sharing-not-allowed", f"it uploads {names}, and {why}",
                        FAIL, path, 1, hint=hint)]  # fmt: skip

    link = "link the paper's DOI instead, which every policy allows"
    version = front.get("version_shared")
    if version not in VERSIONS:
        return unknown("its front matter does not say which version of the paper that is",
                       "write `version_shared: preprint`, `accepted` or `published`")
    where = rules.get("where")
    if not isinstance(where, str):
        return unknown(f"a {channel or 'text with no channel'} puts it at no place a journal's "
                       "sharing policy names", link)  # fmt: skip
    policy = _policy(project)
    if policy is None:
        return unknown(
            "the journal's profile records no sharing policy: without one, a link to the "
            "DOI is shared and nothing is uploaded",
            f"{link}; or record the journal's sharing policy in its profile, quoted from the "
            "journal's own page (the journal-profile skill)",
        )
    entry = policy.get(version)
    if not isinstance(entry, dict):
        return unknown(f"the journal's sharing policy records nothing of the {version} version",
                       f"{link}; or record what the policy says of it, quoted")  # fmt: skip
    allowed = entry.get("where") or []
    if where not in allowed:
        places = ", ".join(allowed) if allowed else "nowhere"
        return refused(f"the journal lets the {version} version be shared at {places}, and a "
                       f"{channel} is {where}", link)  # fmt: skip
    months = entry.get("embargo_months")
    if isinstance(months, int) and not isinstance(months, bool) and months > 0:
        published_on = _day(publication(project).get("published_on"))
        if published_on is None:
            return unknown(f"the journal lets the {version} version be shared {months} months "
                           "after publication, and paper.yaml gives no "
                           "publication.published_on",
                           "write the day the paper was published in paper.yaml")  # fmt: skip
        lifts = _plus_months(published_on, months)
        if today < lifts:
            return refused(f"the journal lets the {version} version be shared from "
                           f"{lifts.isoformat()}, {months} months after publication",
                           f"{link} until then")  # fmt: skip
    return []
