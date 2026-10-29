"""The paper's own DOI, as Crossref answered for it: kept, and read offline.

`manuscript-guard lookup --paper` asks Crossref about paper.yaml's `publication.doi` once
and keeps the answer in `communication/lookups/crossref.yaml`
(`manuscript_guard.lookup.paper_doi`). `communicate check` reads that record and asks
nothing:

- `comm-doi-unknown`, a warning: Crossref answered that it does not know the DOI. A DOI is
  often registered only when the paper is published, so the hint says to ask again then.
- `comm-doi-title-differs`, a warning: Crossref's title for it is not paper.yaml's `title`,
  compared with the case, the markup Crossref keeps (`<i>`), the marks and the spacing
  folded, and a subtitle Crossref keeps apart joined on: a DOI typed one digit wrong is
  another paper's.
- `comm-doi-not-looked-up`, a note: no record answers for this DOI, it was edited, or the
  answer did not come.

A record holds the digest of what it says (`answers_sha256`), as the other lookups' do: one
edited by hand answers for nothing.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.communicate import GATE, folder
from manuscript_guard.communicate.status import OUT, publication
from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.findings import INFO, WARN, Finding

SCHEMA = "manuscript-guard/communication-lookup/1"
LOOKUPS = "lookups"
RECORD = "crossref.yaml"
#: What `answers_sha256` digests: everything in a record but the digest itself.
ANSWERED = ("schema", "doi", "looked_up_on", "crossref")
_TAG = re.compile(r"<[^<>]{0,200}>")


def record_path(project) -> Path:
    return folder(project) / LOOKUPS / RECORD


def answers_digest(record: dict[str, Any]) -> str:
    value = {key: record.get(key) for key in ANSWERED}
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_record(project) -> dict[str, Any] | None:
    """The record, or None where there is none, it is not one, or it says other than its
    digest says it did."""
    path = record_path(project)
    try:
        document = read_structured(path)
    except ContractError:
        return None
    if not isinstance(document, dict) or not validate(document, "communication-lookup",
                                                      path).ok:  # fmt: skip
        return None
    return document if document["answers_sha256"] == answers_digest(document) else None


def write_record(project, record: dict[str, Any]) -> Path:
    path = record_path(project)
    report = validate(record, "communication-lookup", path)
    if not report.ok:
        problems = "; ".join(f.message for f in report.failures)
        raise ContractError(f"the record of the paper's DOI is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


def fold_title(title: str) -> str:
    """A title as two are compared: its markup and entities off, its letters in one case and
    decomposed with their accents off, and every run of marks and spaces one space."""
    plain = html.unescape(_TAG.sub("", title))
    plain = "".join(char for char in unicodedata.normalize("NFKD", plain)
                    if not unicodedata.combining(char))  # fmt: skip
    return " ".join(re.sub(r"[\W_]+", " ", plain.casefold()).split())


def same_title(ours: str, answer: dict[str, Any]) -> bool:
    """Whether Crossref's title for the DOI is paper.yaml's: its title alone, or its title and
    its subtitle."""
    mine = fold_title(ours)
    title = str(answer.get("title") or "")
    subtitle = str(answer.get("subtitle") or "")
    return mine in {fold_title(title), fold_title(f"{title} {subtitle}")} if title else False


def findings(project) -> list[Finding]:
    """What the kept answer says of paper.yaml's `publication.doi`, read offline."""
    doi = publication(project).get("doi")
    if not isinstance(doi, str) or not doi:
        return []
    path = record_path(project)
    record = read_record(project)
    asked = "`manuscript-guard lookup --paper` asks Crossref and keeps the answer"
    if record is None or str(record["doi"]).lower() != doi.lower():
        return [Finding(GATE, "comm-doi-not-looked-up",
                        f"paper.yaml's DOI, {doi}, has not been asked of Crossref",
                        INFO, path, hint=asked)]  # fmt: skip
    answer = record["crossref"]
    if answer["status"] == "unresolvable":
        return [Finding(GATE, "comm-doi-not-looked-up",
                        f"Crossref's answer for {doi} did not come on {record['looked_up_on']}: "
                        f"{answer['why']}", INFO, path, hint=asked)]  # fmt: skip
    if answer["status"] == "absent":
        later = ("" if publication(project).get("status") in OUT else "; a publisher often "
                 "registers the DOI when the paper is published, so ask again then")
        return [Finding(GATE, "comm-doi-unknown",
                        f"Crossref did not know {doi} on {record['looked_up_on']}: a link to "
                        "it may lead nowhere", WARN, path,
                        hint="check the DOI in paper.yaml against the publisher's page, and "
                        f"ask again with `manuscript-guard lookup --paper`{later}")]  # fmt: skip
    title = project.paper.get("title")
    if isinstance(title, str) and title.strip() and not same_title(title, answer):
        return [Finding(GATE, "comm-doi-title-differs",
                        f"Crossref's title for {doi} is '{answer.get('title', '')}', and "
                        "paper.yaml's title is not that one: the DOI may be another paper's",
                        WARN, path, context=title[:160],
                        hint="check the DOI against the publisher's page; where the title "
                        "changed at the journal, write its title in paper.yaml")]  # fmt: skip
    return []
