"""Whose name a decision is recorded under, and the authors checker cannot tell apart.

A decision is recorded under the author's name as `authors.yaml` writes it, as on every page
built before. Decisions are kept by person and item, so two people must never share a name in
the record, and two authors whose full names are one name in Unicode's composed form and
without case would. They are refused, at build and at import: a key that told them apart by
something `authors.yaml` says of them (an ORCID iD, their place in the list) would change when
the file did, and move their decisions in a record that is never rewritten. Every other author
keeps working.

Names are compared in Unicode's composed form and without case, so a name typed with a
combining accent is the name `authors.yaml` spells with a precomposed one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: A name and the ORCID iD a file gave with it, recorded apart from the author whose name it
#: is when the iD is not theirs.
_WITH_ORCID = re.compile(r"^(?P<name>.+?) <(?P<orcid>[^<>]+)>$")


class Namesakes(Exception):
    """Two authors share a full name, so their answers could not be kept apart."""


class SharedOrcid(Exception):
    """`authors.yaml` gives one ORCID iD to two authors."""


def fold(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).split()).casefold()


def _authors(project) -> list[dict]:
    from manuscript_guard.approvals import authors_of

    return authors_of(project) if project is not None else []


def _orcid(author: dict) -> str:
    return str(author.get("orcid") or "").strip()


def namesakes_message(name: str) -> str:
    return (
        f"two authors are named {name}; checker cannot keep their answers apart; write one of "
        f"the names in a form of its own in authors.yaml (a middle initial, say)"
    )


def namesakes(project) -> dict[str, list[dict]]:
    """The authors who share a full name, by the folded name."""
    from manuscript_guard.approvals import name_of

    groups: dict[str, list[dict]] = {}
    for author in _authors(project):
        groups.setdefault(fold(name_of(author)), []).append(author)
    return {name: group for name, group in groups.items() if len(group) > 1}


def refuse_shared_orcids(project) -> None:
    """Raise `SharedOrcid` where two authors are given one iD: neither can be found by it."""
    from manuscript_guard.approvals import name_of

    held: dict[str, dict] = {}
    for author in _authors(project):
        orcid = _orcid(author)
        if orcid and orcid in held:
            raise SharedOrcid(
                f"authors.yaml gives the ORCID iD {orcid} to two authors, "
                f"{name_of(held[orcid])} and {name_of(author)}; put it right before a round"
            )
        held.setdefault(orcid, author)


@dataclass(frozen=True)
class Resolved:
    """Who a name and an ORCID iD in an answers file are, as far as authors.yaml says."""

    by: str
    author: dict | None
    #: The name is an author's and the iD is not theirs, or the iD is an author's and the name
    #: another's.
    orcid_differs: bool = False


def resolve(project, said: str, orcid: str) -> Resolved:
    """The author a file or `--for` names: by ORCID iD, full name, e-mail address or family
    name. Raises
    `AmbiguousAuthor` for a family name two authors share, `Namesakes` for a name two authors
    share whole, and `SharedOrcid` as `refuse_shared_orcids` does."""
    from manuscript_guard.approvals import AmbiguousAuthor, name_of

    refuse_shared_orcids(project)
    orcid = orcid.strip()
    authors = _authors(project)
    shared = namesakes(project)
    wanted = fold(said)
    if wanted in shared:
        raise Namesakes(namesakes_message(name_of(shared[wanted][0])))
    by_orcid = [a for a in authors if orcid and _orcid(a) == orcid]
    by_name = [a for a in authors if fold(name_of(a)) == wanted] or [
        a for a in authors if fold(str(a.get("email") or "")) == wanted] or [
        a for a in authors if fold(str(a.get("family") or "")) == wanted]  # fmt: skip
    if by_orcid:
        (author,) = by_orcid
        if fold(name_of(author)) in shared:
            raise Namesakes(namesakes_message(name_of(author)))
        if not by_name or any(a is author for a in by_name):
            return Resolved(name_of(author), author)
        return Resolved(f"{said} <{orcid}>", None, orcid_differs=True)
    if not by_name:
        return Resolved(said, None)
    if len(by_name) > 1:
        raise AmbiguousAuthor(f"{said!r} names {len(by_name)} authors; give the ORCID iD")
    (author,) = by_name
    held = _orcid(author)
    if orcid and held and orcid != held:
        return Resolved(f"{said} <{orcid}>", None, orcid_differs=True)
    return Resolved(name_of(author), author)


def standing_of(project, recorded: str) -> str | None:
    """What `status` says of a name in the record: None for an author, or why it is not one."""
    from manuscript_guard.approvals import name_of

    names = {fold(name_of(a)) for a in _authors(project)}
    if fold(recorded) in names:
        return None
    found = _WITH_ORCID.match(recorded)
    if found and fold(found["name"]) in names:
        return "ORCID differs from authors.yaml"
    return "not an author in authors.yaml"
