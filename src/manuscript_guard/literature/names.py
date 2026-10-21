"""The people and the groups in an author list: a `.bib` entry's, and each registry's.

A name is read into its family name and its given names, as written, TeX and accents kept;
G7 folds them when it compares (`gates/authors`). A group, a consortium or an agency, is
kept apart: G7 never compares one (Basile, 2026-10-20).

A `.bib` entry's `author` field is read with its braces (`bibfile.read_entries(braces=True)`),
in BibTeX's three forms, `First von Last`, `von Last, First` and `von Last, Jr, First`, and
in biblatex's extended one (`family=Berg, given=Anna, prefix=van der`). A name braced whole,
`{World Health Organization}`, is a group's, and so is one that holds a word only a group's
name has ("Collaborative Group", "Consortium"). `others` or "et al." at the end says that the
list is cut short. A name written the way PubMed prints it, family name first and initials
after with no comma (`Naranjo CA`), which BibTeX reads as given name "Naranjo" and family
name "CA", is read the other way round.

The registries: Crossref gives `family` and `given`, or `name` for a group; PubMed writes
`Naranjo CA`, family name then initials, and types a group as `CollectiveName`; OpenAlex
gives one display name, `C. A. Naranjo`, whose last word is taken for the family name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words of a group's name and of no person's. "Force" alone is a family name.
GROUP_WORDS = frozenset({
    "group", "groups", "consortium", "collaboration", "collaborative", "collaborators",
    "committee", "team", "investigators", "investigator", "trialists", "network", "society",
    "association", "organization", "organisation", "agency", "council", "initiative",
    "taskforce", "foundation", "institute", "commission", "administration", "board",
    "alliance", "program", "programme", "centre", "center", "department", "ministry",
    "federation", "academy", "college", "union", "partnership", "registry", "authors",
    "office", "panel", "services", "working", "party", "behalf",
})  # fmt: skip
#: A suffix after a family name, which is no part of it.
SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "2nd", "3rd"})
_AND = re.compile(r"\s+and\s+", re.IGNORECASE)
_ET_AL = re.compile(r",?\s*\bet\.?\s+al\.?\s*$", re.IGNORECASE)
#: Initials as PubMed prints them after a family name, "CA", or as a .bib may, "C.A.".
INITIALS = re.compile(r"(?:[A-Z]\.?){1,4}")


@dataclass(frozen=True)
class Name:
    """One person, by family and given names as written, or one group, by its name."""

    family: str = ""
    given: str = ""
    group: str = ""

    def record(self) -> dict[str, str]:
        """As a lookup record keeps it: what was given, and nothing empty."""
        if self.group:
            return {"group": self.group}
        return {k: v for k, v in (("family", self.family), ("given", self.given)) if v}


@dataclass(frozen=True)
class Authors:
    names: tuple[Name, ...] = ()
    #: The list ends with `others` or "et al.": the work has more authors than it names.
    truncated: bool = False


def _depth_zero(text: str, sign: re.Pattern[str] | str) -> list[str]:
    """`text` cut at each `sign` outside every brace."""
    pattern = re.compile(sign) if isinstance(sign, str) else sign
    pieces, start, depth, index = [], 0, 0, 0
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0:
            found = pattern.match(text, index)
            if found and found.end() > index:
                pieces.append(text[start:index])
                start = index = found.end()
                continue
        index += 1
    pieces.append(text[start:])
    return [p.strip() for p in pieces]


def _braced_whole(text: str) -> bool:
    if not (text.startswith("{") and text.endswith("}")):
        return False
    depth = 0
    for index, char in enumerate(text):
        depth += {"{": 1, "}": -1}.get(char, 0)
        if depth == 0 and index < len(text) - 1:
            return False
    return True


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", text.casefold())


def _is_group(text: str) -> bool:
    return bool(set(_words(text)) & GROUP_WORDS)


def _plain(text: str) -> str:
    return " ".join(text.replace("{", "").replace("}", "").split())


def _lower(word: str) -> bool:
    """A particle, `von` or `de`: its first letter in lower case, TeX taken off."""
    letters = re.sub(r"^[{\\'`^\"~=.]+(?:[A-Za-z](?=\{))?", "", word).lstrip("{")
    return bool(letters) and letters[0].islower()


def _extended(text: str) -> Name:
    """biblatex's extended form: `family=Berg, given=Anna, prefix=van der`."""
    parts = {}
    for piece in _depth_zero(text, ","):
        key, _, value = piece.partition("=")
        parts[key.strip().lower()] = _plain(value)
    family = " ".join(p for p in (parts.get("prefix", ""), parts.get("family", "")) if p)
    return Name(family=family, given=parts.get("given", ""))


def _person(text: str) -> Name:
    pieces = _depth_zero(text, ",")
    if len(pieces) >= 2:
        family, given = pieces[0], pieces[-1]
    else:
        words = [w for w in _depth_zero(text, r"\s+") if w]
        if len(words) == 1:
            return Name(family=_plain(words[0]))
        while len(words) > 2 and words[-1].lower().rstrip(".") in SUFFIXES:
            words.pop()
        start = next((i for i, w in enumerate(words[:-1]) if _lower(w)), len(words) - 1)
        family, given = " ".join(words[start:]), " ".join(words[:start])
    family, given = _plain(family), _plain(given)
    # "Naranjo CA" with no comma: BibTeX's given name "Naranjo", family name "CA".
    one_word = bool(given) and " " not in given and not INITIALS.fullmatch(given)
    if INITIALS.fullmatch(family) and one_word:
        family, given = given, family
    return Name(family=family, given=given)


def cited(value: str) -> Authors:
    """An `author` field as `read_entries(braces=True)` gives it."""
    names: list[Name] = []
    truncated = False
    for part in _depth_zero(value or "", _AND):
        if not part:
            continue
        if part.casefold().rstrip(".") in {"others", "et al"}:
            truncated = True
            continue
        cut = _ET_AL.sub("", part)
        if cut != part:
            truncated, part = True, cut
        if _braced_whole(part):
            names.append(Name(group=_plain(part)))
        elif "family=" in part.replace(" ", "").lower():
            names.append(_extended(part))
        elif _is_group(_plain(part)):
            names.append(Name(group=_plain(part)))
        else:
            names.append(_person(part))
    return Authors(tuple(n for n in names if n.family or n.group), truncated)


def pubmed(name: str, collective: bool = False) -> Name:
    """PubMed's `Naranjo CA`: the family name, then the initials, with no comma."""
    text = " ".join(name.split())
    if collective or _is_group(text):
        return Name(group=text)
    words = text.split()
    while len(words) > 1 and words[-1].lower().rstrip(".") in SUFFIXES:
        words.pop()
    if len(words) > 1 and INITIALS.fullmatch(words[-1]):
        return Name(family=" ".join(words[:-1]), given=words[-1])
    return Name(family=" ".join(words))


def displayed(name: str) -> Name:
    """OpenAlex's display name, `C. A. Naranjo`: the last word is the family name."""
    text = " ".join(name.split())
    if _is_group(text):
        return Name(group=text)
    words = text.split()
    while len(words) > 1 and words[-1].lower().rstrip(".,") in SUFFIXES:
        words.pop()
    return Name(family=words[-1].rstrip(","), given=" ".join(words[:-1])) if words else Name()


def crossref(author: dict) -> Name:
    """One of Crossref's `author` entries: `family` and `given`, or `name` for a group."""
    family, given, group = (
        " ".join(author[k].split()) if isinstance(author.get(k), str) else ""
        for k in ("family", "given", "name")
    )
    if group and not family:
        return Name(group=group)
    # A group Crossref filed as a person: given "RECOVERY", family "Collaborative Group".
    if _is_group(f"{given} {family}"):
        return Name(group=" ".join(p for p in (given, family) if p))
    if family:
        return Name(family=family, given=given)
    # One name, filed as the given one: it is the name compared.
    return Name(family=given) if given else Name()


def recorded(entries: list[dict]) -> tuple[Name, ...]:
    """A lookup record's `authors`, read back."""
    return tuple(
        Name(family=e.get("family", ""), given=e.get("given", ""), group=e.get("group", ""))
        for e in entries
        if isinstance(e, dict)
    )


__all__ = ["GROUP_WORDS", "INITIALS", "Authors", "Name", "cited", "crossref", "displayed", "pubmed",
           "recorded"]  # fmt: skip
