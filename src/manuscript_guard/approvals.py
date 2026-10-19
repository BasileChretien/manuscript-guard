"""Each author's approval, tied to the manuscript they approved.

"All authors approved the final manuscript" is a sentence of the covering letter, typed, and
true or not. So an author's approval is recorded where it can be held to something:
`manuscript-guard approve --as <author>` writes `approvals/<author>.yaml`, one file per
author, with the digest of what decides the built document, the prose and the results, as
`check` reads it to say a build is current (`gates.review.document_digest`), and the digest of
the title page the authors put their names to (`front_digest`). An approval is a person's
statement, so the hooks put to the person an agent's attempt to write one.

`submit` then says which authors have not approved, and which approved a manuscript that has
changed since. It warns and does not refuse: whether to send without an approval is the
corresponding author's decision, and an approval given by e-mail is still one.
"""

from __future__ import annotations

import hashlib
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


def front_digest(project: Project) -> str:
    """The title page as the authors approve it, as `submit` prints it but for its word
    counts, which the manuscript decides (round 1 of #284: a new title, or an author added,
    left every approval of the old one standing). What it does not print, a role, the
    CRediT roles, the funding, stales nothing (round 1 of #355). A title page that cannot be
    built, with no `authors.yaml` or one the schema refuses, is the same empty page."""
    from manuscript_guard.build.submission import SubmissionError, printed_front

    try:
        printed = printed_front(project)
    except (SubmissionError, KeyError, TypeError, AttributeError, IndexError):
        printed = ""
    return hashlib.sha256(printed.encode("utf-8")).hexdigest()


class NoSuchAuthor(Exception):
    """`--as` names nobody `authors.yaml` lists, or more than one of them."""


def authors_of(project: Project) -> list[dict]:
    listed = (project.authors or {}).get("authors") if isinstance(project.authors, dict) else []
    return [a for a in listed or [] if isinstance(a, dict)]


def name_of(author: dict) -> str:
    return " ".join(str(author.get(part) or "").strip() for part in ("given", "family")).strip()


def slug_of(author: dict) -> str:
    """The file an author's approval is kept in: by the ORCID iD where there is one, then the
    e-mail address, then the name with its own letters kept. Two authors named alike, or two
    names an ASCII fold empties, shared one file before (round 1 of #284)."""
    for field in ("orcid", "email"):
        value = str(author.get(field) or "").strip()
        if value:
            return re.sub(r"[^\w.@-]+", "-", value.lower()).strip("-")
    named = unicodedata.normalize("NFKC", name_of(author)).casefold()
    return re.sub(r"[^\w]+", "-", named).strip("-") or "author"


def _names(document: dict, author: dict) -> bool:
    """Whether an approval record is this author's: by name, and by ORCID iD where both
    give one."""
    if str(document.get("author") or "").strip() != name_of(author):
        return False
    orcid, recorded = str(author.get("orcid") or ""), str(document.get("orcid") or "")
    return not (orcid and recorded and orcid != recorded)


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
        "front_sha256": front_digest(project),
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

    current, front = document_digest(project), front_digest(project)
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
        if not _names(document, author):
            report = report.with_findings(
                _finding("approval-missing", f"{name_of(author)} has not approved the "
                         f"manuscript: {path.name} is {document['author']}'s", path,
                         "they run `manuscript-guard approve` as themselves")  # fmt: skip
            )
            continue
        # An approval written before the title page was held to has no `front_sha256`, and is
        # judged by the manuscript alone, as it was given.
        recorded = document.get("front_sha256")
        changed = ("it" if document["document_sha256"] != current else
                   "its title page" if recorded and recorded != front else None)  # fmt: skip
        if changed:
            report = report.with_findings(
                _finding("approval-stale", f"{name_of(author)} approved the manuscript on "
                         f"{document['approved_on']}, and {changed} has changed since", path,
                         "they read it again and approve it as it stands")  # fmt: skip
            )
    return report


def _finding(code: str, message: str, path: Path, hint: str) -> Finding:
    return Finding(gate="BUILD", code=code, severity=WARN, message=message, path=path, hint=hint)
