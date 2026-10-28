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
        # `creators_note` refuses the package where there is no one to name.
        "creators": [_creator(person) for person in people(project) if person.name],
    }
    words = keywords(project)
    if words:
        record["keywords"] = words
    found = licences(project)
    if len(found) == 1:
        # Zenodo's licences are named by their SPDX identifiers in small letters.
        record["license"] = found[0].lower()
    # Never `package.doi`: it is the package's own DOI, and the legacy API reads `doi` as one
    # a publisher assigned already, which a GitHub release read from the root would take.
    package = settings(project)
    if package.get("date"):
        record["publication_date"] = str(package["date"])
    related = [{"identifier": doi, "relation": "isDerivedFrom", "resource_type": "dataset",
                "scheme": "doi"} for doi in data_dois(project)]  # fmt: skip
    if related:
        record["related_identifiers"] = related
    return json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _creator(person: Person) -> dict:
    name = ", ".join(part for part in (person.family, person.given) if part)
    creator: dict = {"name": name}
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


def creators_note(project: Project) -> str | None:
    """Why the citation files cannot be written: Zenodo requires each record's creators, and
    `authors.yaml` names none, or lists an author with no name."""
    found = people(project)
    if not found:
        return "authors.yaml lists no author, and a Zenodo record has to name its creators"
    nameless = sum(not person.name for person in found)
    if nameless:
        return (f"authors.yaml lists {nameless} author(s) with neither a given nor a family "
                "name, and a Zenodo record names each of its creators")  # fmt: skip
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
            said.append(_kept(name, target, entry.data))
        elif dry_run:
            said.append(f"{name} would be written at the root")
        else:
            said.append(_created(name, target, entry.data))
    return said


def _created(name: str, target: Path, data: bytes) -> str:
    """Write `data` at `target` only if nothing is there as it is opened: a file made since
    it was looked for is kept, and a write the system refuses is said, not raised."""
    try:
        handle = open(target, "xb")  # noqa: SIM115 -- the file it made is removed on failure
    except FileExistsError:
        return _kept(name, target, data)
    except OSError as exc:
        return f"{name} could not be written at the root ({exc.strerror or exc})"
    try:
        with handle:
            handle.write(data)
    except OSError as exc:
        # The file is the one this call made: what it holds is not the package's.
        target.unlink(missing_ok=True)
        return f"{name} could not be written at the root ({exc.strerror or exc})"
    return f"{name} written at the root"


def _kept(name: str, target: Path, data: bytes) -> str:
    try:
        kept = target.read_bytes()
    except OSError:
        return f"{name} at the root is kept; it could not be read"
    fields = differing(name, kept, data)
    if fields is None:
        return (f"{name} at the root is kept; it could not be read as "
                f"{'JSON' if name == ZENODO else 'YAML'}")  # fmt: skip
    if fields:
        return f"{name} at the root is kept; it differs from the package's in " + ", ".join(fields)
    return f"{name} at the root is kept; it says what the package's says"


__all__ = ["CITATION", "ZENODO", "Person", "creators_note", "data_dois", "description",
           "differing", "keywords", "licence_note", "people", "root_citation", "title",
           "zenodo"]  # fmt: skip
