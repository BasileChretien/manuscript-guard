"""The records of reference currency, and how each is read and written.

- `literature/currency.yaml` (the tool and people): one entry per citing sentence and work,
  with its decision and the answer to a proposed change.
- `literature/currency/searches/<id>-<n>.yaml` (the tool): one search as it was sent and what
  came back, sealed by `answers_sha256`.
- `literature/currency/works/<doi-or-pmid>.yaml` (the tool): what the registries said of a
  work, its abstract among it, sealed by `answers_sha256`. The folder holds a `.gitignore`
  that keeps the rest of it out of git: an abstract is the publisher's text.
- `literature/currency/readings/<id>.<reader>.<n>.yaml`: a reading, written once and sealed
  by `reading_sha256`, as a panel's reading is.

A sealed record's digest catches an edit made without care, and not one made by somebody who
runs the digest again (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import rules
from manuscript_guard.findings import Finding, Report

CURRENCY_FILE = "currency.yaml"
SCHEMA = "manuscript-guard/currency/1"
WORK_SCHEMA = "manuscript-guard/currency-work/1"
SEARCH_SCHEMA = "manuscript-guard/currency-search/1"
READING_SCHEMA = "manuscript-guard/currency-reading/1"
FOLDER = "currency"
WORKS, SEARCHES, READINGS = "works", "searches", "readings"
#: What `references` writes in the works store, so that git leaves it out.
GITIGNORE = (
    "# Written by `manuscript-guard references`. The works store holds the abstracts of\n"
    "# the works it read, which are their publishers' text: it stays out of git unless\n"
    "# you take this file away.\n"
    "*\n"
    "!.gitignore\n"
)
HEADER = (
    "# Whether each cited work is still the one to cite (`manuscript-guard references`).\n"
    "# The rules' decisions are written here by `references --reading`; a person's decision\n"
    "# carries their name and why, and a proposed change is answered by a person.\n"
)
_SAFE = re.compile(r"[A-Za-z0-9_-]")
_ENTRY_ID = re.compile(r"c([1-9][0-9]*)")
#: A reading's file name: the entry, the reader as `safe_name` writes it, the number.
_READING_NAME = re.compile(r"(c[1-9][0-9]*)\.([^.]+)\.([1-9][0-9]*)\.yaml")
#: The fields of a candidate's reading, in the order they are shown.
FIELDS = ("level", "population", "exposure", "outcome", "stance", "search_end")


def fold_work(work: str) -> str:
    """A work's id as the store keys it: a DOI in lower case, as a DOI is matched without
    regard to case; a PMID as it is."""
    return work.lower() if work.lower().startswith("doi:") else work


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sealed_digest(record: dict[str, Any], seal: str) -> str:
    """The SHA-256 of what a record says, the seal itself left out."""
    return _digest({key: value for key, value in record.items() if key != seal})


def safe_name(text: str) -> str:
    """A name as a file name on every system: each character that is not a letter, a digit,
    `_` or `-` written as `%` and its code point in hex. A point is written so too, so that
    the parts of a reading's file name stay apart."""
    return "".join(c if _SAFE.fullmatch(c) else f"%{ord(c):x}" for c in text)


def folder(project: Project) -> Path:
    return project.path("literature") / FOLDER


def currency_path(project: Project) -> Path:
    return project.path("literature") / CURRENCY_FILE


# --------------------------------------------------------------------- literature/currency.yaml


@dataclass(frozen=True)
class Entry:
    """One entry of `currency.yaml`, as the file gives it."""

    id: str
    sentence: str
    citekey: str
    question: str | None = None
    marked_by: str | None = None
    decision: dict | None = None
    answer: dict | None = None

    @property
    def number(self) -> int:
        return int(self.id[1:])

    @property
    def named(self) -> str:
        opening = " ".join(self.sentence.split())
        opening = opening if len(opening) <= 60 else opening[:57] + "..."
        return f"{self.id} (@{self.citekey}, {opening!r})"


def read_document(project: Project) -> tuple[dict | None, Report]:
    """`currency.yaml` as it is, held to its schema, and what stopped it being read. No file
    is no entries and no finding."""
    path = currency_path(project)
    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, Report((Finding(gate="G0", code="schema-violation", message=str(exc),
                                     path=path, hint="see the currency schema"),))  # fmt: skip
    if document is None:
        return None, Report()
    report = validate(document, "currency", path)
    if report.ok:
        ids = [entry["id"] for entry in document.get("entries") or []]
        twice = sorted({one for one in ids if ids.count(one) > 1})
        if twice:
            report = Report((Finding(
                gate="G0", code="schema-violation", path=path,
                message=f"entries: the id {', '.join(twice)} is given to more than one entry",
                hint="give each entry an id of its own; an id never changes once given",
            ),))  # fmt: skip
    if not report.ok or not isinstance(document, dict):
        return None, report
    return document, report


def read_entries(project: Project) -> tuple[tuple[Entry, ...], Report]:
    """The entries of `currency.yaml`, and what stopped them being read."""
    document, report = read_document(project)
    if document is None:
        return (), report
    return tuple(_entry(raw) for raw in document.get("entries") or []), report


def _entry(raw: dict) -> Entry:
    return Entry(
        id=str(raw["id"]),
        sentence=str(raw["sentence"]),
        citekey=str(raw["citekey"]).strip(),
        question=raw.get("question"),
        marked_by=raw.get("marked_by"),
        decision=raw.get("decision"),
        answer=raw.get("answer"),
    )


def next_id(document: dict | None) -> str:
    """The id a new entry is given: one past the highest given yet."""
    numbers = [int(found[1]) for entry in (document or {}).get("entries") or []
               if (found := _ENTRY_ID.fullmatch(str(entry.get("id"))))]  # fmt: skip
    return f"c{max(numbers, default=0) + 1}"


def write_document(project: Project, document: dict) -> Path:
    """Write `currency.yaml` whole, after holding it to its schema: a file the gate would
    refuse is never written."""
    path = currency_path(project)
    report = validate(document, "currency", path)
    if not report.ok:
        problems = "; ".join(finding.message for finding in report.failures)
        raise ContractError(f"{path}: the entries would not be valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = HEADER + "\n" + yaml.safe_dump(document, sort_keys=False, allow_unicode=True,
                                          width=100)  # fmt: skip
    path.write_bytes(text.encode("utf-8"))
    return path


# ---------------------------------------------------------------------------- the works store


def work_id(fields: dict[str, str] | None) -> str | None:
    """The works store's id for a `references.bib` entry: its DOI, else its PMID, as G7 reads
    them; None where it has neither."""
    from manuscript_guard.gates.identifiers import doi_of, pmid_of

    if not fields:
        return None
    doi = doi_of(fields)
    if doi:
        return f"doi:{doi}"
    pmid = pmid_of(fields)
    return f"pmid:{pmid}" if pmid else None


def is_work(fields: dict[str, str] | None, work: str) -> bool:
    """Whether a `references.bib` entry is the work `work` names: a `doi:` id by the entry's
    DOI, a `pmid:` id by its PMID, each as G7 reads them. An entry with both is either
    work (round 2 of #499: `work_id` gives the DOI first, and a candidate filed by its PMID
    was never the entry's)."""
    from manuscript_guard.gates.identifiers import doi_of, pmid_of

    if not fields:
        return False
    work = fold_work(work)
    if work.startswith("doi:"):
        return doi_of(fields) == work.removeprefix("doi:")
    if work.startswith("pmid:"):
        return pmid_of(fields) == work.removeprefix("pmid:")
    return False


def works_folder(project: Project) -> Path:
    return folder(project) / WORKS


def work_path(project: Project, work: str) -> Path:
    return works_folder(project) / (safe_name(work) + ".yaml")


def store_here(project: Project) -> bool:
    """Whether this checkout holds the works store: a record of at least one work. In a
    clone it is absent, since git leaves it out."""
    found = works_folder(project)
    return found.is_dir() and any(found.glob("*.yaml"))


def ensure_gitignore(project: Project) -> Path:
    """Write the works store's `.gitignore` where it is not there yet."""
    path = works_folder(project) / ".gitignore"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(GITIGNORE.encode("utf-8"))
    return path


def write_work(project: Project, record: dict[str, Any]) -> Path:
    """Write one works record, sealed, after holding it to its schema; and the store's
    `.gitignore` with it."""
    record = {key: value for key, value in record.items() if key != "answers_sha256"}
    record = {"schema": WORK_SCHEMA, **record, "work": fold_work(str(record["work"]))}
    record["answers_sha256"] = sealed_digest(record, "answers_sha256")
    path = work_path(project, str(record["work"]))
    report = validate(record, "currency-work", path)
    if not report.ok:
        problems = "; ".join(finding.message for finding in report.failures)
        raise ContractError(f"the record of {record['work']} is not valid: {problems}")
    ensure_gitignore(project)
    text = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    path.write_bytes(text.encode("utf-8"))
    return path


@dataclass(frozen=True)
class Read:
    """A sealed record as read: the record where it fits its schema, and what is wrong with it
    where something is (`edited` where it no longer matches its digest)."""

    path: Path
    record: dict | None
    problem: str | None = None
    edited: bool = False


def _sealed(path: Path, schema: str, seal: str) -> Read:
    try:
        record = read_structured(path)
    except ContractError as exc:
        return Read(path, None, str(exc))
    if record is None:
        return Read(path, None, "no such file")
    report = validate(record, schema, path)
    if not report.ok or not isinstance(record, dict):
        return Read(path, None, "; ".join(finding.message for finding in report.failures))
    if record.get(seal) != sealed_digest(record, seal):
        return Read(path, record, f"it no longer matches its `{seal}`", edited=True)
    return Read(path, record)


def read_work(project: Project, work: str) -> Read | None:
    """The works record of `work`, or None where the store has none."""
    path = work_path(project, work)
    if not path.is_file():
        return None
    found = _sealed(path, "currency-work", "answers_sha256")
    if found.record is not None and found.record.get("work") != work:
        return Read(path, None, f"it is the record of {found.record.get('work')}")
    return found


def as_work(record: dict | None) -> rules.Work | None:
    """A works record as the rules read it."""
    if record is None:
        return None
    integrity = record.get("integrity") or {}
    return rules.Work(
        id=str(record["work"]),
        published=record.get("published"),
        retracted=bool(integrity.get("retracted")),
        withdrawn=bool(integrity.get("withdrawn")),
        under_concern=bool(integrity.get("under_concern")),
        published_as=tuple(integrity.get("published_as") or ()),
        types=tuple(record.get("publication_types") or ()),
    )


# --------------------------------------------------------------------------------- searches


def search_path(project: Project, entry: str, number: int) -> Path:
    return folder(project) / SEARCHES / f"{entry}-{number}.yaml"


def write_search(project: Project, record: dict[str, Any]) -> Path:
    """Write one search record, sealed, after holding it to its schema. Nothing in this
    version runs a search: the recorded searches, still to come, are to write them
    (DESIGN.md, "A cited work is held to newer evidence by fixed rules")."""
    record = {key: value for key, value in record.items() if key != "answers_sha256"}
    record = {"schema": SEARCH_SCHEMA, **record}
    record["answers_sha256"] = sealed_digest(record, "answers_sha256")
    path = search_path(project, str(record["entry"]), int(record["number"]))
    report = validate(record, "currency-search", path)
    if not report.ok:
        problems = "; ".join(finding.message for finding in report.failures)
        raise ContractError(f"the search record is not valid: {problems}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(yaml.safe_dump(record, sort_keys=False, allow_unicode=True,
                                    width=100).encode("utf-8"))  # fmt: skip
    return path


def read_searches(project: Project) -> list[Read]:
    """Every search record, in the order of their names."""
    found = folder(project) / SEARCHES
    if not found.is_dir():
        return []
    return [_sealed(path, "currency-search", "answers_sha256")
            for path in sorted(found.glob("*.yaml"))]  # fmt: skip


# --------------------------------------------------------------------------------- readings


def readings_folder(project: Project) -> Path:
    return folder(project) / READINGS


def reading_path(project: Project, entry: str, reader: str, number: int) -> Path:
    return readings_folder(project) / f"{entry}.{safe_name(reader)}.{number}.yaml"


def read_readings(project: Project) -> list[Read]:
    """Every reading filed, in the order of their names. One whose name is not its entry, its
    reader and its number, as `file_reading` names it, is edited: a reading copied under
    another name keeps its seal, and would count as a second reading."""
    found = readings_folder(project)
    if not found.is_dir():
        return []
    read = []
    for path in sorted(found.glob("*.yaml")):
        one = _sealed(path, "currency-reading", "reading_sha256")
        record = one.record
        if one.problem is None and record is not None:
            named = _READING_NAME.fullmatch(path.name)
            said = (str(record.get("entry")), safe_name(str(record.get("reader"))),
                    str(record.get("number")))  # fmt: skip
            if named is None or named.groups() != said:
                one = Read(path, record, f"its name is not that of {said[0]}'s reading "
                           f"{said[2]} by {record.get('reader')}", edited=True)  # fmt: skip
        read.append(one)
    return read


def file_reading(project: Project, document: dict[str, Any], filed_on: str) -> Path:
    """File one reading: numbered as its reader's next of the entry, sealed, and written once.
    A name already taken is never written over."""
    document = folded_reading({key: value for key, value in document.items()
                               if key not in ("number", "filed_on", "reading_sha256")})
    entry, reader = str(document.get("entry")), str(document.get("reader"))
    if not _ENTRY_ID.fullmatch(entry):
        raise ContractError(f"{entry!r} is not the id of an entry of literature/currency.yaml")
    number = 1
    while reading_path(project, entry, reader, number).exists():
        number += 1
    record = {**document, "number": number, "filed_on": filed_on}
    record["reading_sha256"] = sealed_digest(record, "reading_sha256")
    path = reading_path(project, entry, reader, number)
    report = validate(record, "currency-reading", path)
    if not report.ok:
        problems = "; ".join(finding.message for finding in report.failures)
        raise ContractError(f"the reading is not valid: {problems}")
    text = ("# Filed by `manuscript-guard references --reading`. Sealed by `reading_sha256`:\n"
            "# a second reading is filed as a further one, never written over this.\n"
            + yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100))  # fmt: skip
    _write_new(path, text)
    return path


def folded_reading(record: dict) -> dict:
    """A reading with each work it names folded as the store keys it (`fold_work`)."""
    record = dict(record)
    if isinstance(record.get("cited"), dict) and isinstance(record["cited"].get("work"), str):
        record["cited"] = {**record["cited"], "work": fold_work(record["cited"]["work"])}
    if isinstance(record.get("candidates"), list):
        record["candidates"] = [
            {**one, "work": fold_work(one["work"])}
            if isinstance(one, dict) and isinstance(one.get("work"), str) else one
            for one in record["candidates"]
        ]  # fmt: skip
    return record


def as_reading(record: dict) -> rules.Reading:
    """A reading as the rules read it."""
    candidates = {}
    for one in record.get("candidates") or []:
        candidates[str(one["work"])] = rules.Fields(
            level=one["level"]["value"],
            population=one["population"]["value"],
            exposure=one["exposure"]["value"],
            outcome=one["outcome"]["value"],
            stance=one["stance"]["value"],
            search_end=(one.get("search_end") or {}).get("value"),
        )
    return rules.Reading(
        reader=str(record["reader"]),
        hierarchy=str(record["hierarchy"]),
        scale=str(record["scale"]),
        cited_level=int(record["cited"]["level"]["value"]),
        candidates=candidates,
        number=int(record.get("number") or 1),
    )


def quotes_of(record: dict) -> list[tuple[str, str, str]]:
    """Each quote of a reading, as the work it is of, the field and the words."""
    quoted = [(str(record["cited"]["work"]), "level", str(record["cited"]["level"]["quote"]))]
    for one in record.get("candidates") or []:
        for name in FIELDS:
            if one.get(name):
                quoted.append((str(one["work"]), name, str(one[name]["quote"])))
    return quoted


def _write_new(path: Path, text: str) -> None:
    """Write a file that must not exist yet, whole: to a temporary name, then linked into
    place, as a panel's reading is filed (`panel/run.py`, which nothing a gate reads may
    import). A link refuses a name that is taken, where a move would replace it."""
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_bytes(data)
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(path) from None
        except OSError:
            try:
                with open(path, "xb") as handle:
                    handle.write(data)
            except FileExistsError:
                raise FileExistsError(path) from None
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


__all__ = ["CURRENCY_FILE", "Entry", "Read", "as_reading", "as_work", "currency_path",
           "ensure_gitignore", "file_reading", "folder", "next_id", "quotes_of",
           "read_document", "read_entries", "read_readings", "read_searches", "read_work",
           "reading_path", "safe_name", "sealed_digest", "store_here", "work_id",
           "work_path", "write_document", "write_search", "write_work"]
