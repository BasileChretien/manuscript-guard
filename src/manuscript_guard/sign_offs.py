"""Findings a named person signs off, each sign-off bound to what was signed.

Some findings are not the author's to close. A warning about a model the analysis fitted is
for the statistician to judge, an exception to the rule on small cells for the data
custodian. `authors.yaml` names these people under `roles:`, and a gate that raises such a
finding hands it here as a `Signable`: the role that may sign it, an id, and the digest of
what is signed. `manuscript-guard sign --as <person> --finding <id>` writes that digest to
`approvals/sign-offs/`, in a file named by the id (`path_of`). The gate then reports the
finding as information that says who signed it and when. A sign-off by someone who no longer
holds the role counts for nothing, and so does one of something that has changed since it
was signed. The finding then stands, with a hint that names who signs it.

A sign-off is a person's statement, as an author's approval is (`approvals.py`): the hooks
put to the person an agent's `sign` and an agent's edit of a file under `approvals/`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.approvals import DIRECTORY as APPROVALS
from manuscript_guard.approvals import NoSuchAuthor, find_author, name_of
from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding

DIRECTORY = f"{APPROVALS}/sign-offs"
SCHEMA = "manuscript-guard/sign-off/1"

#: The roles `authors.yaml` may name under `roles:`, each as a finding's hint calls it. The
#: corresponding author is not among them: `corresponding: true` on an author names them.
ROLES = {
    "statistician": "the statistician",
    "data_custodian": "the data custodian",
    "ethics_lead": "the person responsible for ethics approval",
}

#: How long the readable part of a sign-off's file name may be.
_SLUG = 60


@dataclass(frozen=True)
class Holder:
    """The person named for a role: an author, or someone the project names beside them."""

    name: str
    orcid: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Signable:
    """Findings one person may sign off together: the role, the id the hint names, the
    digest of what is signed, and the findings themselves."""

    role: str
    id: str
    digest: str
    findings: tuple[Finding, ...]


def digest_of(*parts: object) -> str:
    """The digest of what is signed, from parts that JSON can write."""
    text = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def holder(project: Project, role: str) -> Holder | None:
    """The person `authors.yaml` names for the role, or None where it names nobody.

    Raises NoSuchAuthor where the role names an author `authors.yaml` does not list."""
    roles = project.authors.get("roles") if isinstance(project.authors, dict) else None
    said = (roles or {}).get(role) if isinstance(roles, dict) else None
    if isinstance(said, str):
        said = {"author": said}
    if not isinstance(said, dict):
        return None
    if said.get("author"):
        author = find_author(project, str(said["author"]))
        return Holder(name_of(author), author.get("orcid"), author.get("email"))
    if said.get("name"):
        return Holder(str(said["name"]).strip(), said.get("orcid"), said.get("email"))
    return None


def is_holder(project: Project, person: Holder, said: str) -> bool:
    """Whether `said`, as `--as` gives it, names the person: as an author is found, by ORCID
    iD, e-mail address, full name or family name, or for someone who is not an author by
    ORCID iD, e-mail address or full name."""
    try:
        author = find_author(project, said)
    except NoSuchAuthor:
        wanted = " ".join(said.split()).casefold()
        return wanted in {
            str(value).casefold() for value in (person.name, person.orcid, person.email) if value
        }
    return name_of(author) == person.name and author.get("orcid") == person.orcid


def path_of(project: Project, finding_id: str) -> Path:
    """The file a sign-off of this id is kept in: its id as a file name can carry it, with
    eight characters of the id's digest so that two ids never share one."""
    slug = re.sub(r"[^\w.-]+", "-", finding_id.casefold()).strip("-.")[:_SLUG]
    tag = hashlib.sha256(finding_id.encode("utf-8")).hexdigest()[:8]
    return project.root / DIRECTORY / f"{slug}-{tag}.yaml"


def sign(project: Project, signable: Signable, person: Holder, note: str | None = None) -> Path:
    """Write the person's sign-off of what the signable holds as it stands."""
    record = {
        "schema": SCHEMA,
        "finding": signable.id,
        "role": signable.role,
        "person": person.name,
        "signed_on": date.today().isoformat(),
        "signed_sha256": signable.digest,
        "said": [finding.message for finding in signable.findings],
    }
    if person.orcid:
        record["orcid"] = str(person.orcid)
    if note:
        record["note"] = note
    path = path_of(project, signable.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Written by `manuscript-guard sign`: a named person's sign-off of a finding, bound\n"
        "# to what it said. Sign again after a change; never edit by hand.\n"
        + yaml.safe_dump(record, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return path


def settle(project: Project, signable: Signable) -> tuple[Finding, ...]:
    """The signable's findings as they stand: information naming who signed them, where the
    person the role names signed what is there now; otherwise the findings as raised, with
    a hint that says who signs them and how, and any fault in the record."""
    role = ROLES[signable.role]
    try:
        person = holder(project, signable.role)
    except NoSuchAuthor as exc:
        return _waiting(signable, f"`roles: {signable.role}` in authors.yaml: {exc}")
    if person is None:
        return _waiting(
            signable,
            f"name {role} under `roles:` in authors.yaml; if they judge it acceptable, they "
            f"sign it off with `manuscript-guard sign --as <them> --finding {signable.id}`",
        )
    command = f'`manuscript-guard sign --as "{person.name}" --finding {signable.id}`'
    path = path_of(project, signable.id)
    if not path.is_file():
        return _waiting(
            signable, f"{person.name}, {role}, signs it off with {command} if they judge it "
            "acceptable"
        )  # fmt: skip
    try:
        record = read_structured(path)
    except ContractError as exc:
        # Round 1 of #304: raised, it stopped G15, and every finding of the gate went with it.
        unread = Finding(gate="G0", code="schema-violation", message=str(exc), path=path)
        return (unread, *_waiting(signable, f"{path.name} is not a sign-off it can read"))
    checked = validate(record, "sign-off", path)
    if not checked.ok:
        return checked.findings + _waiting(signable, f"{path.name} is not a sign-off it can read")
    if record["finding"] != signable.id or record["role"] != signable.role:
        return _waiting(signable, f"{path.name} signs another finding; {person.name} runs "
                        f"{command}")  # fmt: skip
    if record["person"] != person.name or (
        person.orcid and record.get("orcid") and str(record["orcid"]) != str(person.orcid)
    ):
        return _waiting(
            signable, f"{path.name} was signed by {record['person']}, who is not {role}; "
            f"{person.name} signs it off with {command}"
        )  # fmt: skip
    if record["signed_sha256"] != signable.digest:
        return _waiting(
            signable, f"{person.name} signed it off on {record['signed_on']}, and it has "
            f"changed since; if it still stands, they sign it again with {command}"
        )  # fmt: skip
    note = record.get("note")
    return tuple(
        replace(
            finding,
            severity=INFO,
            message=f"{finding.message}; signed off by {person.name}, {role}, on "
            f"{record['signed_on']}",
            hint=f"they said: {note}" if note else None,
        )
        for finding in signable.findings
    )


def _waiting(signable: Signable, why: str) -> tuple[Finding, ...]:
    return tuple(
        replace(finding, hint=f"{finding.hint}; or {why}" if finding.hint else why)
        for finding in signable.findings
    )
