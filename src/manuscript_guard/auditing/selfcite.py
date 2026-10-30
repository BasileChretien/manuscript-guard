"""Self-citation, for an editor: the references whose registry record lists an author of the
paper, and those the journal itself published.

With `--authors` and `--lookup`, each author of the paper is looked for in the author list
each registry asked keeps for each reference (Crossref's, PubMed's): a person of the same
family name, folded as G7 folds one when it compares a reference's authors with a registry's
(`gates.authors.same`: accents, case, apostrophes and particles), and the same first initial.
With `--journal` and `--lookup`, each record's journal (Crossref's `container`, PubMed's full
journal name) is compared with the profile's `name`, both folded: case, punctuation and a
leading "The".

Counts and the list of entries, and never a ratio or a verdict (Basile, 2026-10-29): how much
self-citation is too much is the editor's call, and a namesake counts as much as the author.
The reference text is not read for names: without `--lookup` nothing is counted, and the
report says so. Nothing here is counted by `--strict`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: What the report says where nothing was counted for want of the registries' lists.
NOT_LOOKED_UP = ("not counted: the registries' author lists are needed (--lookup); the "
                 "reference text is not read for names")  # fmt: skip
DRY_RUN = "not counted: --dry-run sent nothing, so no registry's author list was read"
NO_AUTHORS = "authors not counted: --authors names them"


@dataclass(frozen=True)
class Author:
    """One author of the paper, as `--authors` gives them."""

    given: str
    family: str

    @property
    def shown(self) -> str:
        return f"{self.given} {self.family}"


@dataclass
class SelfCitation:
    """What was counted: for each author, the entries whose record lists them; for the
    journal, the entries it published; how many entries were looked up, and how many of
    them no registry gave an author list or a journal for; or why nothing was counted."""

    authors: list[tuple[Author, list]] = field(default_factory=list)
    journal: str | None = None
    in_journal: list = field(default_factory=list)
    looked: int = 0
    no_people: int = 0
    no_journal: int = 0
    unlooked: int = 0
    note: str = ""
    authors_note: str = ""


def _initial(given: str) -> str:
    """A given name's first letter, folded as a family name is."""
    from manuscript_guard.gates.authors import name_words

    words = name_words(given)
    return words[0][0] if words else ""


def _people(answers: dict) -> list:
    """The persons of a record's author lists, Crossref's and PubMed's."""
    from manuscript_guard.literature.names import recorded

    found = []
    for name in ("crossref", "pubmed"):
        answer = answers.get(name)
        if isinstance(answer, dict) and isinstance(answer.get("authors"), list):
            found += [p for p in recorded(answer["authors"]) if p.family and not p.group]
    return found


def lists_author(answers: dict, author: Author) -> bool:
    """Whether a record lists a person of the author's family name and first initial."""
    from manuscript_guard.gates.authors import same

    initial = _initial(author.given)
    return bool(initial) and any(
        same(author.family, person.family) and _initial(person.given) == initial
        for person in _people(answers)
    )


def folded_title(title: str) -> str:
    """A journal's name as two are compared: accents, case and punctuation gone, its spaces
    made one, and a leading "The" left out."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold().replace("&",
                                                                                     " and ")
    text = " ".join(re.findall(r"[^\W_]+", text))
    return text.removeprefix("the ").strip()


def _journals(answers: dict) -> list[str]:
    found = []
    for name, key in (("crossref", "container"), ("pubmed", "journal")):
        answer = answers.get(name)
        if isinstance(answer, dict) and isinstance(answer.get(key), str):
            found.append(answer[key])
    return found


def count(looked: list | None, census_entries: int, authors: dict | None,
          journal: str | None, dry_run: bool) -> SelfCitation:  # fmt: skip
    """The count, from what `references.look_up` asked (`looked`, None without --lookup),
    the number of entries the lists hold, the `--authors` document and the profile's name."""
    said = SelfCitation(journal=journal)
    if authors is None:
        said.authors_note = NO_AUTHORS
    if looked is None:
        said.note = NOT_LOOKED_UP
        return said
    if dry_run:
        said.note = DRY_RUN
        return said
    people = [Author(str(p.get("given") or "").strip(), str(p.get("family") or "").strip())
              for p in (authors or {}).get("authors") or [] if isinstance(p, dict)]  # fmt: skip
    asked = [one for one in looked if one.came]
    said.looked = len(asked)
    said.unlooked = max(0, census_entries - len(asked))
    said.no_people = sum(1 for one in asked if not _people(one.answers))
    said.no_journal = sum(1 for one in asked if not _journals(one.answers))
    if authors is not None:
        said.authors = [(author, [one for one in asked if lists_author(one.answers, author)])
                        for author in people]  # fmt: skip
    if journal:
        mine = folded_title(journal)
        said.in_journal = [one for one in asked
                           if any(folded_title(t) == mine for t in _journals(one.answers))]
    return said


__all__ = ["DRY_RUN", "NOT_LOOKED_UP", "NO_AUTHORS", "Author", "SelfCitation", "count",
           "folded_title", "lists_author"]  # fmt: skip
