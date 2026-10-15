"""Each author's approval, tied to the manuscript they approved.

"All authors approved the final manuscript" is a sentence of the covering letter, typed, and
true or not. So an author's approval is recorded where it can be held to something:
`manuscript-guard approve --as <author>` writes `approvals/<author>.yaml`, one file per
author, with the digest of what decides the built document, the prose and the results, as
`check` reads it to say a build is current (`gates.review.document_digest`). An approval is a
person's statement, so the hooks put to the person an agent's attempt to write one.

`submit` then says which authors have not approved, and which approved a manuscript that has
changed since. It warns and does not refuse: whether to send without an approval is the
corresponding author's decision, and an approval given by e-mail is still one.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report

DIRECTORY = "approvals"
SCHEMA = "manuscript-guard/approval/1"


class NoSuchAuthor(Exception):
    """`--as` names nobody `authors.yaml` lists, or more than one of them."""


def authors_of(project: Project) -> list[dict]:
    listed = (project.authors or {}).get("authors") if isinstance(project.authors, dict) else []
    return [a for a in listed or [] if isinstance(a, dict)]


def name_of(author: dict) -> str:
    return " ".join(str(author.get(part) or "").strip() for part in ("given", "family")).strip()


def slug_of(author: dict) -> str:
    """The file an author's approval is kept in: their name, folded to plain letters."""
    plain = unicodedata.normalize("NFKD", name_of(author)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "author"


def find_author(project: Project, said: str) -> dict:
    """The author `said` names: by ORCID iD, e-mail address, full name or family name."""
    wanted = " ".join(said.split()).casefold()
    authors = authors_of(project)
    for field in ("orcid", "email"):
        found = [a for a in authors if str(a.get(field) or "").casefold() == wanted]
        if found:
            return found[0]
    for test in (
        lambda a: name_of(a).casefold() == wanted,
        lambda a: str(a.get("family") or "").strip().casefold() == wanted,
    ):
        found = [a for a in authors if test(a)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise NoSuchAuthor(f"{said!r} names {len(found)} authors; give the ORCID iD")
    names = ", ".join(name_of(a) for a in authors) or "none"
    raise NoSuchAuthor(f"{said!r} is not an author in authors.yaml (they are: {names})")


def approve(project: Project, author: dict, note: str | None = None) -> Path:
    """Write the author's approval of the manuscript as it stands."""
    from manuscript_guard.gates.review import document_digest

    record = {
        "schema": SCHEMA,
        "author": name_of(author),
        "approved_on": date.today().isoformat(),
        "document_sha256": document_digest(project),
    }
    if author.get("orcid"):
        record["orcid"] = str(author["orcid"])
    if note:
        record["note"] = note
    path = project.root / DIRECTORY / f"{slug_of(author)}.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        "# Written by `manuscript-guard approve`: this author's approval of the manuscript,\n"
        "# bound to what it said. Approve again after a change; never edit by hand.\n"
        + yaml.safe_dump(record, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return path


def check_approvals(project: Project) -> Report:
    """A warning for each author with no approval, or one given to an earlier manuscript."""
    from manuscript_guard.gates.review import document_digest

    current = document_digest(project)
    report = Report()
    for author in authors_of(project):
        path = project.root / DIRECTORY / f"{slug_of(author)}.yaml"
        if not path.is_file():
            report = report.with_findings(
                _finding("approval-missing", f"{name_of(author)} has not approved the "
                         "manuscript", path, "they run `manuscript-guard approve --as "
                         f"\"{name_of(author)}\"` once they have read it")  # fmt: skip
            )
            continue
        document = read_structured(path)
        checked = validate(document, "approval", path)
        if not checked.ok:
            report = report.merge(checked)
            continue
        if document["document_sha256"] != current:
            report = report.with_findings(
                _finding("approval-stale", f"{name_of(author)} approved the manuscript on "
                         f"{document['approved_on']}, and it has changed since", path,
                         "they read it again and approve it as it stands")  # fmt: skip
            )
    return report


def _finding(code: str, message: str, path: Path, hint: str) -> Finding:
    return Finding(gate="BUILD", code=code, severity=WARN, message=message, path=path, hint=hint)
