"""ORCID, read only: whether the paper's DOI is on each author's public record.

`communicate orcid` asks ORCID's public API (`https://pub.orcid.org/v3.0/<iD>/works`) for the
works of each author `authors.yaml` gives an ORCID iD for, and says whether the paper's DOI,
`publication.doi`, is among them. It asks for nothing else, sends no credential, and writes
nothing, here or at ORCID: adding a work to a record is the author's, on their own page.

A DOI not found is not proof that the record lacks it: a work the author keeps private, or
shares with trusted parties only, is not in the public record, so its absence may be the
author's choice of who sees it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.communicate.adapters.net import Api, RemoteError, default_transport

API = "https://pub.orcid.org"
ORCID_ID = re.compile(r"\A\d{4}-\d{4}-\d{4}-\d{3}[\dX]\Z")
#: The transport the client is given; a test puts its own in its place.
TRANSPORT = default_transport

ON_RECORD = "on the record"
NOT_FOUND = "not on the public record"
UNREAD = "not read"


def valid(orcid: str) -> bool:
    """An ORCID iD as written, its last character the check of the rest (ISO 7064 11-2)."""
    if ORCID_ID.fullmatch(orcid) is None:
        return False
    total = 0
    for digit in orcid.replace("-", "")[:-1]:
        total = (total + int(digit)) * 2
    check = (12 - total % 11) % 11
    return orcid[-1] == ("X" if check == 10 else str(check))


def bare(orcid: str) -> str:
    """An iD as authors.yaml may write it, with or without `https://orcid.org/`."""
    return re.sub(r"\A(?:https?://)?(?:www\.)?orcid\.org/", "", orcid.strip(), flags=re.I)


def dois(document: dict) -> set[str]:
    """Every DOI the works of a record name, in small letters."""
    found = set()
    for group in document.get("group") or ():
        ids = ((group or {}).get("external-ids") or {}).get("external-id") or ()
        for one in ids:
            if isinstance(one, dict) and str(one.get("external-id-type", "")).lower() == "doi":
                value = str(one.get("external-id-value") or "").strip().lower()
                found.add(re.sub(r"\A(?:https?://)?(?:dx\.)?doi\.org/", "", value))
    return found


@dataclass(frozen=True)
class Asked:
    author: str
    orcid: str
    state: str
    why: str = ""


def client() -> Api:
    return Api("ORCID", API, "no credential (its public API asks for none)",
               transport=TRANSPORT)  # fmt: skip


def ask(authors: list[tuple[str, str]], doi: str, api: Api | None = None) -> list[Asked]:
    """For each author and iD, whether `doi` is on the public record."""
    api = api or client()
    wanted = doi.strip().lower()
    out = []
    for name, orcid in authors:
        if not valid(orcid):
            out.append(Asked(name, orcid, UNREAD, "it is no ORCID iD"))
            continue
        try:
            said = api.call("GET", f"/v3.0/{orcid}/works")
        except RemoteError as exc:
            out.append(Asked(name, orcid, UNREAD, str(exc)))
            continue
        out.append(Asked(name, orcid, ON_RECORD if wanted in dois(said) else NOT_FOUND))
    return out


def render(asked: list[Asked], doi: str) -> str:
    lines = [f"Is {doi} on each author's public ORCID record? (Read only: nothing is written.)"]
    for one in asked:
        lines.append(f"  {one.author} ({one.orcid}): {one.state}"
                     + (f": {one.why}" if one.why else ""))  # fmt: skip
    if any(one.state == NOT_FOUND for one in asked):
        lines += ["", "A DOI not found may be on the record and kept private, or shared with "
                  "trusted parties only: its absence from the public record may be the "
                  "author's setting. Adding it is the author's, on their own ORCID page."]
    return "\n".join(lines) + "\n"
