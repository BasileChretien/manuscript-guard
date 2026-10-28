"""Whose name a decision is recorded under.

Decisions are kept by person and item, so two people must never share a name in the record.
Each author is recorded under their name as `authors.yaml` gives it, and where two authors share
a full name, under the name and their ORCID iD, "Wei Zhang <0000-0002-1825-0097>", or, for one of
them with no iD, the name and their place among the namesakes, "Wei Zhang (2)". Two namesakes
with no iD between them cannot be told apart by anything a page carries, so no page is built for
them until one is added.

Names are compared in Unicode's composed form and without case, so a name typed with a
combining accent is the name `authors.yaml` spells with a precomposed one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: A name and the ORCID iD it was recorded with, as `record_name` writes one that a file gave
#: against the iD authors.yaml holds.
_WITH_ORCID = re.compile(r"^(?P<name>.+?) <(?P<orcid>[^<>]+)>$")


class Namesakes(Exception):
    """Two authors share a full name and neither has an ORCID iD to tell them apart."""


def fold(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).split()).casefold()


def _authors(project) -> list[dict]:
    from manuscript_guard.approvals import authors_of

    return authors_of(project) if project is not None else []


def keyed(project) -> list[tuple[dict, str]]:
    """Every author with the name their decisions are recorded under, in `authors.yaml`'s order.
    Raises `Namesakes` where two who share a full name have no ORCID iD between them."""
    from manuscript_guard.approvals import name_of

    authors = _authors(project)
    groups: dict[str, list[dict]] = {}
    for author in authors:
        groups.setdefault(fold(name_of(author)), []).append(author)
    keys = []
    for author in authors:
        same = groups[fold(name_of(author))]
        name, orcid = name_of(author), str(author.get("orcid") or "").strip()
        if len(same) == 1:
            keys.append((author, name))
            continue
        if sum(1 for a in same if not str(a.get("orcid") or "").strip()) > 1:
            raise Namesakes(
                f"{len(same)} authors in authors.yaml are called {name}, and more than one of "
                f"them has no ORCID iD: their answers could not be told apart. Add each one's "
                f"ORCID iD to authors.yaml."
            )
        index = next(i for i, a in enumerate(same, 1) if a is author)
        keys.append((author, f"{name} <{orcid}>" if orcid else f"{name} ({index})"))
    return keys


@dataclass(frozen=True)
class Resolved:
    """Who a name and an ORCID iD in an answers file are, as far as authors.yaml says."""

    by: str
    author: dict | None
    #: The name is an author's and the iD is not theirs, or the iD is an author's and the name
    #: another's.
    orcid_differs: bool = False


def resolve(project, said: str, orcid: str) -> Resolved:
    """The author a file names, by the name it records them under, their ORCID iD, their full
    name or their family name. Raises `AmbiguousAuthor` for a name two authors share that no
    iD settles, and `Namesakes` as `keyed` does."""
    from manuscript_guard.approvals import AmbiguousAuthor, name_of

    orcid = orcid.strip()
    pairs = keyed(project)
    wanted = fold(said)
    by_key = [a for a, key in pairs if fold(key) == wanted]
    by_orcid = [a for a, _ in pairs if orcid and str(a.get("orcid") or "").strip() == orcid]
    by_name = by_key or [a for a, _ in pairs if fold(name_of(a)) == wanted] or [
        a for a, _ in pairs if fold(str(a.get("family") or "")) == wanted]  # fmt: skip
    key = dict((id(a), k) for a, k in pairs)
    if by_orcid:
        (author,) = by_orcid
        if not by_name or any(a is author for a in by_name):
            return Resolved(key[id(author)], author)
        return Resolved(f"{said} <{orcid}>", None, orcid_differs=True)
    if not by_name:
        return Resolved(said, None)
    if len(by_name) > 1:
        raise AmbiguousAuthor(f"{said!r} names {len(by_name)} authors; give the ORCID iD")
    (author,) = by_name
    held = str(author.get("orcid") or "").strip()
    if orcid and held and orcid != held:
        return Resolved(f"{said} <{orcid}>", None, orcid_differs=True)
    return Resolved(key[id(author)], author)


def standing_of(project, recorded: str) -> str | None:
    """What `status` says of a name in the record: None for an author, or why it is not one."""
    from manuscript_guard.approvals import name_of

    pairs = keyed(project)
    if any(fold(key) == fold(recorded) for _, key in pairs):
        return None
    found = _WITH_ORCID.match(recorded)
    if found and any(fold(name_of(a)) == fold(found["name"]) for a, _ in pairs):
        return "ORCID differs from authors.yaml"
    return "not an author in authors.yaml"
