"""G7's comparison of the people a reference names with those a registry lists for the work.

The rules are Basile's (2026-10-20), and the folding of a family name is paper-preflight's
surname key (`ATTRIBUTION.md`):

* **Every person the entry names** must be somewhere on the registry's list, and the first
  of them first on it. A name the registry lists and the entry does not is never said: a
  list cut at six, "and others" and "et al." leave names out on purpose.
* **None of them on the list** is the shape of an invented reference, a real title with
  names made up, and fails from internal-review (`reference-authors-disjoint`). The first
  author not first, or some of the others not on the list, is a warning
  (`reference-authors-differ`): registries' lists have errors of their own.
* **A group is never compared**, on either side. A list that holds only a group, as
  Crossref's of a RECOVERY trial does where PubMed lists the people, says nothing of them.
* **Family names only, folded leniently.** TeX, accents, case and apostrophes go; ü and ue,
  ö and oe, ä and ae, ß and ss are one; two names agree when their last words do or when
  the words of one, its particles aside, are all in the other: "van der Berg" is "Berg",
  "García Márquez" is "García", "O'Brien" is "OBrien". Given names are not compared.

Where a work has several records, PubMed's and Crossref's, a person counts as listed when
any of them lists them, and as first when any of them puts them first. A list on which no
cited person is found is read once more with family and given names the other way round:
some records file "Li Wang" as family name "Li".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import WARN, Finding
from manuscript_guard.gates import lookups
from manuscript_guard.literature.names import INITIALS, SUFFIXES, Authors, Name

#: Words a family name may start with that say nothing of whose it is.
PARTICLES = frozenset({
    "van", "von", "der", "den", "de", "del", "della", "dei", "di", "da", "du", "des", "la",
    "le", "les", "lo", "dos", "das", "do", "ter", "ten", "te", "bin", "ibn", "ben", "al",
    "el", "st", "y", "e", "zu", "af", "av",
})  # fmt: skip
#: Two spellings of one letter (Müller, Mueller; Reiß, Reiss), read as the shorter.
_TRANSCRIPTIONS = (("ae", "a"), ("oe", "o"), ("ue", "u"), ("ss", "s"))
#: An umlaut is its transcription first, as German writes it: "Süe" and "Suee" are one
#: name, and with the dots only taken off they were "sue" and "suee" (the generated cases
#: of 2026-10-20). TeX's `\"u` is one too.
_UMLAUTS = str.maketrans({"\N{LATIN SMALL LETTER A WITH DIAERESIS}": "ae",
                          "\N{LATIN SMALL LETTER O WITH DIAERESIS}": "oe",
                          "\N{LATIN SMALL LETTER U WITH DIAERESIS}": "ue"})  # fmt: skip
_TEX_UMLAUT = re.compile(r'\\"\s*([aouAOU])')
#: Letters NFKD leaves whole, written as the TeX of a .bib writes them (`{\o}` is "o").
_LETTERS = str.maketrans({"\N{LATIN SMALL LETTER O WITH STROKE}": "o",
                          "\N{LATIN SMALL LETTER AE}": "ae",
                          "\N{LATIN SMALL LIGATURE OE}": "oe",
                          "\N{LATIN SMALL LETTER D WITH STROKE}": "d",
                          "\N{LATIN SMALL LETTER ETH}": "d",
                          "\N{LATIN SMALL LETTER L WITH STROKE}": "l",
                          "\N{LATIN SMALL LETTER DOTLESS I}": "i",
                          "\N{LATIN SMALL LETTER THORN}": "th"})  # fmt: skip
_APOSTROPHES = re.compile("['`\N{RIGHT SINGLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}"
                          "\N{MODIFIER LETTER APOSTROPHE}\N{ACUTE ACCENT}]")  # fmt: skip


def name_words(family: str) -> tuple[str, ...]:
    """A family name's words, as two are compared."""
    text = _TEX_UMLAUT.sub(lambda m: m.group(1) + "e", family.replace("{", "").replace("}", ""))
    text = lookups._MATHS.sub("", lookups._SIGN.sub("", lookups._COMMAND.sub(lookups._untex, text)))
    text = unicodedata.normalize("NFKC", text).casefold().translate(_UMLAUTS)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).translate(_LETTERS)
    words = re.findall(r"[^\W\d_]+", _APOSTROPHES.sub("", text))
    while len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    for written, read in _TRANSCRIPTIONS:
        words = [w.replace(written, read) for w in words]
    return tuple(words)


def same(cited: str, registered: str, given: str = "") -> bool:
    """Whether two family names are one person's, by the lenient folding. `given` is the
    registered person's given names: a registry can file the first part of a double surname
    among them (Crossref's given "George Davey", family "Smith", for an entry's "Davey Smith,
    G" or "Davey, SG"), so the cited family name's words may be found there too, where the
    given names are two words or more and not initials."""
    mine, theirs = name_words(cited), name_words(registered)
    if not mine or not theirs:
        return False
    if mine[-1] == theirs[-1]:
        return True
    small, large = (mine, theirs) if len(mine) <= len(theirs) else (theirs, mine)
    core = [w for w in small if w not in PARTICLES]
    if core and set(core) <= set(large):
        return True
    names = [w for w in name_words(given) if len(w) > 1] if given else []
    core = [w for w in mine if w not in PARTICLES]
    return len(names) >= 2 and bool(core) and set(core) <= {*names, *theirs}


def _people(names: Sequence[Name]) -> list[Name]:
    """The persons of a list whose family names are written in Latin letters: a name in
    another script, as Crossref keeps a Russian or a Chinese journal's authors, is never
    found in a romanised entry, and is not compared (round 1 of #379), as a title mostly
    in another script is not."""
    return [n for n in names if n.family and not n.group and _latin(n.family)]


def _latin(family: str) -> bool:
    letters = [c for c in family if c.isalpha()]
    return bool(letters) and sum(map(lookups._latin, letters)) * 2 >= len(letters)


def _swapped(people: list[Name]) -> list[Name]:
    """The list read with family and given names the other way round, where the given name
    is a word and not initials."""
    return [
        Name(family=p.given, given=p.family)
        if p.given and not INITIALS.fullmatch(p.given.replace(" ", "")) else p
        for p in people
    ]  # fmt: skip


def _paired(cited: list[Name], people: list[Name]) -> set[int]:
    """Which cited people are on the list, each listed person taken once."""
    taken: set[int] = set()
    found: set[int] = set()
    for index, person in enumerate(cited):
        hit = next((j for j, other in enumerate(people)
                    if j not in taken and same(person.family, other.family, other.given)),
                   None)  # fmt: skip
        if hit is not None:
            taken.add(hit)
            found.add(index)
    return found


@dataclass(frozen=True)
class Compared:
    """What the comparison found. `compared` is False where either side names no person."""

    compared: bool
    disjoint: bool = False
    first: bool = True
    #: The cited people no list holds, as the entry writes them.
    missing: tuple[str, ...] = ()
    #: The first person of the list the comparison was made with, and its people.
    listed: tuple[str, ...] = ()


def compare(
    cited: Authors, lists: Sequence[Sequence[Name]], complete: Sequence[bool] = ()
) -> Compared:
    """The entry's people against one work's lists, one per registry that has the work.
    `complete` says of each list whether its registry lists every author (PubMed's does)."""
    mine = _people(cited.names)
    flags = [*complete, *[False] * len(lists)][: len(lists)]
    kept = [(p, c) for p, c in zip(map(_people, lists), flags, strict=True) if p]
    if not mine or not kept:
        return Compared(compared=False)
    found: set[int] = set()
    first, short = False, False
    for people, whole in kept:
        here = _paired(mine, people)
        if not here and _paired(mine, _swapped(people)):
            people = _swapped(people)
            here = _paired(mine, people)
        found |= here
        first = first or same(mine[0].family, people[0].family, people[0].given)
        # A list each of whose people the entry names, and shorter than the entry's, stops
        # short: Crossref lists one author of a paper of three (the measurement of
        # 2026-10-20). Not where a complete list was kept, which says who is missing.
        short = short or (not whole and len(here) == len(people) < len(mine))
    listed = tuple(p.family for p in kept[0][0])
    if not found:
        return Compared(compared=True, disjoint=True, first=False, listed=listed)
    missing = tuple(p.family for i, p in enumerate(mine) if i not in found)
    if short and first and not any(whole for _people, whole in kept):
        missing = ()
    return Compared(compared=True, first=first, missing=missing, listed=listed)


def shown(families: Sequence[str], most: int = 6) -> str:
    """A list of family names as a message gives it."""
    names = ", ".join(families[:most])
    return names + (f" and {len(families) - most} more" if len(families) > most else "")


_HINT = "correct the authors in Zotero, then `manuscript-guard sync-bib`"


def _joined(words: list[str]) -> str:
    words = list(dict.fromkeys(words))
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)


def judged(
    citekey: str,
    cited: Authors,
    lists: Sequence[tuple[str, Sequence[Name]]],
    path: Path,
    about: str,
    *,
    may_fail: bool = True,
) -> list[Finding]:
    """What G7 says of the cited people against one work's lists, each named by the
    registry that keeps it. `about` says which work: "the DOI's work". Where `may_fail` is
    False, none of them on a list is a warning: a list only OpenAlex keeps can be wrong."""
    said = compare(cited, [names for _source, names in lists],
                   [source == "PubMed" for source, _names in lists])  # fmt: skip
    if not said.compared:
        return []
    keeping = _joined([source for source, names in lists if _people(names)])
    if said.disjoint:
        mine = shown([p.family for p in _people(cited.names)])
        message = (
            f"@{citekey}: none of the cited authors ({mine}) is among those {keeping} list "
            f"for {about}: {shown(said.listed)}"
        )
        if may_fail:
            return [lookups._finding("reference-authors-disjoint", message, path,
                                     "the entry names other people than the work it "
                                     "describes: " + _HINT)]  # fmt: skip
        return [lookups._finding("reference-authors-differ", message, path, _HINT, WARN)]
    parts = []
    if not said.first:
        parts.append(
            f"the cited first author, {_people(cited.names)[0].family}, is not first on the "
            f"list {keeping} keep for {about}, which begins with {said.listed[0]}"
        )
    if said.missing:
        verb = "is" if len(said.missing) == 1 else "are"
        parts.append(f"{shown(said.missing)} {verb} on no list of its authors")
    if not parts:
        return []
    message = f"@{citekey}: " + "; ".join(parts)
    return [lookups._finding("reference-authors-differ", message, path, _HINT, WARN)]


__all__ = ["PARTICLES", "Compared", "compare", "judged", "name_words", "same", "shown"]
