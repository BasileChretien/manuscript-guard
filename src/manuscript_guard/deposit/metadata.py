""".zenodo.json, the metadata a Zenodo record of the package is made from, and the copies of it
and of CITATION.cff an author may keep at the project's root.

Like the rest of the package it is made from the records alone: the authors from
`authors.yaml` with their ORCID iDs and affiliations and never an address, the keywords and
the licence from `paper.yaml`, and as related works only the DOIs a record holds, those of
the data sources `design/data_sources.yaml` chose. Its description is a fixed sentence about
the package, with the paper's title in it: what the paper found is the paper's to say.

A file at the root is written only where none is: one the author keeps is theirs, and the
fields where it differs from the package's are named, and nothing is changed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project

from .plan import Entry, settings

ZENODO = ".zenodo.json"
CITATION = "CITATION.cff"
#: What the deposit is, as Zenodo's legacy deposition API names its kinds of upload, and as
#: CITATION.cff calls it (`type: software`): code with the results it wrote.
UPLOAD_TYPE = "software"
DESCRIPTION = (
    "The analysis code of the paper \"{title}\", the results it wrote, what they were written "
    "with, and how to run it again. README.md in the package says how, and what is not in it "
    "and why."
)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


@dataclass(frozen=True)
class Person:
    """An author as the package names them: no address."""

    given: str
    family: str
    orcid: str | None
    affiliations: tuple[tuple[str, str], ...]  # (id, text)

    @property
    def name(self) -> str:
        return " ".join(part for part in (self.given, self.family) if part)


def people(project: Project) -> list[Person]:
    """The authors in the order `authors.yaml` lists them, each with their ORCID iD and the
    affiliations it names that it describes."""
    authors = project.authors or {}
    places = {str(a.get("id")): str(a.get("text")) for a in authors.get("affiliations") or []
              if a.get("id") is not None and a.get("text")}  # fmt: skip
    found = []
    for author in authors.get("authors") or []:
        named = tuple((str(a), places[str(a)]) for a in author.get("affiliations") or []
                      if str(a) in places)  # fmt: skip
        orcid = str(author["orcid"]) if author.get("orcid") else None
        found.append(Person(str(author.get("given") or ""), str(author.get("family") or ""),
                            orcid, named))  # fmt: skip
    return found


def title(project: Project) -> str:
    return f"Code and results for \"{project.paper.get('title', '')}\""


def description(project: Project) -> str:
    return DESCRIPTION.format(title=project.paper.get("title", ""))


def keywords(project: Project) -> list[str]:
    said = project.paper.get("keywords")
    return [str(word) for word in said] if isinstance(said, list) else []


def data_dois(project: Project) -> list[str]:
    """The DOIs of the data sources the decision in `design/data_sources.yaml` chose, in its
    order; none where the record cannot be read, which its own gate reports."""
    from manuscript_guard.data_sources import chosen, record_path

    try:
        document = yaml.safe_load(record_path(project).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return []
    if not isinstance(document, dict):
        return []
    found: list[str] = []
    try:
        sources = chosen(document)
    except (KeyError, TypeError, AttributeError):
        return []
    for source in sources:
        listed = source.get("identifiers") if isinstance(source, dict) else None
        for identifier in listed if isinstance(listed, list) else []:
            if not isinstance(identifier, dict) or identifier.get("scheme") != "doi":
                continue
            doi = str(identifier.get("id") or "").strip()
            doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", doi, flags=re.I)
            if _DOI.match(doi) and doi not in found:
                found.append(doi)
    return found


def zenodo(project: Project) -> str:
    """.zenodo.json: what Zenodo's record of the package is made from, keys in order."""
    from .texts import licences

    record: dict = {
        "title": title(project),
        "upload_type": UPLOAD_TYPE,
        "description": description(project),
        "creators": [_creator(person) for person in people(project)]
        or [{"name": "The authors of the paper"}],
    }
    words = keywords(project)
    if words:
        record["keywords"] = words
    found = licences(project)
    if len(found) == 1:
        # Zenodo's licences are named by their SPDX identifiers in small letters.
        record["license"] = found[0].lower()
    package = settings(project)
    if package.get("doi"):
        record["doi"] = str(package["doi"])
    if package.get("date"):
        record["publication_date"] = str(package["date"])
    related = [{"identifier": doi, "relation": "isDerivedFrom", "resource_type": "dataset",
                "scheme": "doi"} for doi in data_dois(project)]  # fmt: skip
    if related:
        record["related_identifiers"] = related
    return json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _creator(person: Person) -> dict:
    name = ", ".join(part for part in (person.family, person.given) if part)
    creator: dict = {"name": name or "An author of the paper"}
    if person.orcid:
        creator["orcid"] = person.orcid
    if person.affiliations:
        creator["affiliation"] = "; ".join(text for _id, text in person.affiliations)
    return creator


def licence_note(project: Project) -> str | None:
    """Why .zenodo.json names no licence, where `package.licence` names several."""
    from .texts import licences

    found = licences(project)
    if len(found) > 1:
        return (f"package.licence names {len(found)} licences, and a Zenodo record takes one: "
                ".zenodo.json names none, so choose it on the record's form")  # fmt: skip
    return None


# ------------------------------------------------------------------ the copies at the root


def _parsed(name: str, data: bytes) -> object:
    text = data.decode("utf-8")
    return json.loads(text) if name == ZENODO else yaml.safe_load(text)


def differing(name: str, kept: bytes, written: bytes) -> list[str] | None:
    """The top-level fields where the file at the root differs from the package's, in
    order, or None where the one at the root cannot be read."""
    try:
        old = _parsed(name, kept)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None
    new = _parsed(name, written)
    if not isinstance(old, dict) or not isinstance(new, dict):
        return None
    return sorted(str(key) for key in set(old) | set(new) if old.get(key) != new.get(key))


def root_citation(project: Project, entries: tuple[Entry, ...], *, dry_run: bool) -> list[str]:
    """Write CITATION.cff and .zenodo.json at the project's root where none is, as the
    package holds them, and say of each what was done. One already there is never written
    over: the fields where it differs are named."""
    said = []
    for name in (CITATION, ZENODO):
        entry = next((e for e in entries if e.path == name), None)
        if entry is None or entry.data is None:
            continue
        target: Path = project.root / name
        if target.exists() or target.is_symlink():
            try:
                kept = target.read_bytes()
            except OSError:
                said.append(f"{name} at the root is kept; it could not be read")
                continue
            fields = differing(name, kept, entry.data)
            if fields is None:
                said.append(f"{name} at the root is kept; it could not be read as "
                            f"{'JSON' if name == ZENODO else 'YAML'}")  # fmt: skip
            elif fields:
                said.append(f"{name} at the root is kept; it differs from the package's in "
                            + ", ".join(fields))  # fmt: skip
            else:
                said.append(f"{name} at the root is kept; it says what the package's says")
        elif dry_run:
            said.append(f"{name} would be written at the root")
        else:
            target.write_bytes(entry.data)
            said.append(f"{name} written at the root")
    return said


__all__ = ["CITATION", "ZENODO", "Person", "data_dois", "description", "differing",
           "keywords", "licence_note", "people", "root_citation", "title", "zenodo"]  # fmt: skip
