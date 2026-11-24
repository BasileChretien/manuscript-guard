"""The entries of `references.bib` a manuscript cites only as text typed in brackets.

`init --from` makes a typed group of citations keys only if each of its parts names an entry,
so one work the list lacks leaves the rest typed, and G7 said of each that nothing cites it
(the real-paper corpus, 24 false findings in 8 papers against 4 true). What is true of such
an entry is narrower: it is cited, and no key points to it, so `sync-bib`, which writes the
file from the keys, would drop it (Basile, 2026-11-23). The import does not change.

Only a citation in brackets is read (Basile, 2026-11-24, "Brackets only"). A part is what a
bracket holds, or one `;`-separated piece of it where every piece of that bracket is names
and a year: "(Silva; Souza, 2020)", as ABNT parts two authors, is no citation of Souza. A part
counts for an entry where it is exactly the entry's names, a comma and the year, with
nothing before or between them:
"Smith", "Smith & Jones" or "Smith and Jones", every name or "Smith et al." for three or
more, as the import renders them (`typed_references.citations.renderings`). After the year
it may hold a page ("p. 5", "pp. 5-7") or further years, and nothing else. A citation in the
sentence, "Smith (2020) showed", is not read: what stands before the bracket cannot be told
from a longer name ("Garcia Smith", "zur Smith"), so the entry keeps its warning.

Names are compared as the import compares them, as the list writes them: "Xu" is not "Xue",
which G7's folding for the registries (`gates.authors.name_words`) makes one. The import does
not read TeX, so an entry with TeX in any of its names is not named by a typed citation.

A citation that may be two works counts for neither: two entries by those names and that
year; one of that year with TeX in any of its names, whose first author may be that name; an
entry the typed list holds by those
names and that year that is not the file's, told apart by its initials and title; an entry
of the list the import could not read, or could not key, that holds the year and opens on
the first author's name; or a work of that year whose name holds TeX that cannot be read. A
year's letter is the one the typed list prints. With no list it is not known, since Better
BibTeX and the import key a first and a second work `smith2020` and `smith2020a`, so a key
ending in a letter is never counted. Whatever is in doubt stays a warning.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from manuscript_guard.gates.authors import name_words
from manuscript_guard.gates.typed_citations import _MONTHS, Works, works_by
from manuscript_guard.literature.names import Authors
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import NUL, mask
from manuscript_guard.text.reference_lists import reference_lists
from manuscript_guard.typed_references import read as read_typed
from manuscript_guard.typed_references.citations import renderings
from manuscript_guard.typed_references.entries import YEAR, Entry, Unread

#: A pair of brackets within a paragraph, with no bracket inside.
_GROUP = re.compile(r"\((?P<inside>[^()]{1,400})\)")
#: A page or a range of them after the year.
_PAGE = r"(?:, pp?\. ?[A-Za-z]?\d+(?:[-\N{EN DASH}][A-Za-z]?\d+)?)?"
#: A part of a bracket, its spaces made one: names, a comma, the years, perhaps a page.
_PART = re.compile(rf"(?P<names>.+?), (?P<years>{YEAR}(?:, {YEAR})*){_PAGE}")
_ONE_YEAR = re.compile(YEAR)
_LETTERS = re.compile(r"[^\W\d_]+")
_TITLE_WORD = re.compile(r"[^\W_]+")
#: A key that ends in a letter after its year, which says nothing of a printed year's letter.
_KEY_LETTER = re.compile(r"\d{4}([a-z])$")
#: What says that a family name, as `literature.names` reads it, holds TeX.
_TEX_SIGNS = '\\{}"'
#: A quotation mark no backslash stands before: babel's shorthand for an accent.
_BABEL = re.compile(r'(?<!\\)"')


def _in_tex(people: Authors) -> bool:
    """Whether a name of the entry holds TeX, which the import does not read. Reading a name
    takes its braces off, so babel's `M{"u}ller` is `M"uller` here, and a quotation mark,
    which no family name holds, says it too."""
    return any(sign in one.family for one in people.names for sign in _TEX_SIGNS)


def _first_words(people: Authors) -> tuple[str, ...]:
    """The first author's name as G7 folds it, babel's `"u` read as TeX's `\\"u`."""
    return name_words(_BABEL.sub(r'\\"', people.names[0].family))


def _forms(people: Authors) -> tuple[str, ...]:
    """Every way a citation's whole names may be the entry's, as the import renders them."""
    families = tuple(" ".join(one.family.split()) for one in people.names)
    if not families or not all(families) or _in_tex(people):
        return ()
    return (f"{families[0]} et al.",) if people.truncated else renderings(families)


def _names_it(names: str, people: Authors) -> bool:
    return names in _forms(people)


def _initials(given: str) -> tuple[str, ...]:
    return tuple(word[0].casefold() for word in _LETTERS.findall(given))


def _title_words(title: str) -> tuple[str, ...]:
    return tuple(_TITLE_WORD.findall(title.casefold()))


def _same_work(entry: Entry, key: str, year: str, works: Works) -> bool:
    """Whether a typed list's `entry` is the work `references.bib` holds as `key`, from `year`:
    every family name as written, the initials of each, and the title. The import keys an
    entry by its name and year alone, so a key the list and the file share does not say it."""
    people = works.people[key].names
    return (
        entry.year[:4] == year
        and len(people) == len(entry.families)
        and all(one.family == family and _initials(one.given) == _initials(given)
                for one, family, given in zip(people, entry.families, entry.initials,
                                              strict=True))  # fmt: skip
        and _title_words(works.titles.get(key, "")) == _title_words(dict(entry.fields).get(
            "title") or "")
    )  # fmt: skip


@dataclass(frozen=True)
class _NotRead:
    """An entry of a typed list the import could not read, as a citation may still be of it:
    the years it holds and the words of its first author, those before its first comma or
    bracket. A second author's name does not make it the work: "(Lee et al., 2019)" is not
    "Smith, A., Lee, B., ... (2019)"."""

    years: frozenset[str]
    first: frozenset[str]

    @classmethod
    def of(cls, text: str) -> _NotRead:
        years = frozenset(year[:4] for year in re.findall(rf"(?<!\d){YEAR}", text))
        return cls(years, frozenset(name_words(re.split(r"[,(]", text, maxsplit=1)[0])))

    def may_be(self, year: str, family: str) -> bool:
        return year[:4] in self.years and set(name_words(family)) <= self.first


def _as_typed(lines: list[str], entry: Unread) -> str:
    """The line of the text an entry not read stands on: of one the import could not key, it
    keeps the name alone, without the year."""
    return lines[entry.line - 1] if 0 < entry.line <= len(lines) else entry.text


@dataclass(frozen=True)
class _Listing:
    """What the manuscript's typed reference lists add to `references.bib`: the entries read
    from them, and those not read."""

    entries: tuple[Entry, ...]
    unknown: tuple[_NotRead, ...]

    @classmethod
    def of(cls, texts: Iterable[str]) -> _Listing:
        entries: list[Entry] = []
        unknown: list[_NotRead] = []
        for text in texts:
            typed = read_typed(text)
            lines = text.split("\n")
            entries += [entry for _key, entry in typed.entries]
            unknown += [_NotRead.of(_as_typed(lines, entry)) for entry in typed.unread]
        return cls(tuple(entries), tuple(unknown))

    def letter(self, key: str, year: str, works: Works) -> str | None:
        """The letter the list prints after the year of the work `key`, "" for none, or None
        where that is not known: the list does not hold the work and the key ends in a
        letter, which says only that it was the second of its name and year."""
        printed = {entry.year[4:] for entry in self.entries if _same_work(entry, key, year, works)}
        if printed:
            return printed.pop() if len(printed) == 1 else None
        return None if _KEY_LETTER.search(key) else ""

    def holds_another(self, names: str, year: str, key: str, works: Works) -> bool:
        """Whether the list holds a work other than `key` that the citation names."""
        return any(
            entry.year == year
            and names in renderings(entry.families)
            and not _same_work(entry, key, year[:4], works)
            for entry in self.entries
        )


def _only(keys: list[str]) -> str | None:
    return keys[0] if len(keys) == 1 else None


def _the_work(names: str, year: str, works: Works, by_year: dict[str, list[str]],
              listing: _Listing) -> str | None:  # fmt: skip
    """The one key the citation `names`, `year` can mean, or None where it names none or may
    be of two works: among them an entry of that year with TeX in any of its names, whose
    first author, folded, is the first author of the entry named."""
    four, letter = year[:4], year[4:]
    if names.rstrip(".").casefold() in _MONTHS or works.unread.get(four):
        return None
    keys = by_year.get(four, ())
    named = [key for key in keys if _names_it(names, works.people[key])]
    letters = {key: listing.letter(key, four, works) for key in named}
    key = _only([one for one, printed in letters.items() if printed == letter])
    if key is None or None in letters.values():
        return None
    family = _first_words(works.people[key])
    if any(_in_tex(works.people[other]) and _first_words(works.people[other]) == family
           for other in keys):  # fmt: skip
        return None
    first = works.people[key].names[0].family
    if any(entry.may_be(year, first) for entry in listing.unknown):
        return None
    return None if listing.holds_another(names, year, key, works) else key


def _every_piece_cites(read: list[re.Match[str] | None]) -> bool:
    """Whether every `;`-separated piece of a bracket is names and a year of its own."""
    return all(piece is not None for piece in read)


def _parts(text: str) -> Iterable[tuple[str, tuple[str, ...], str]]:
    """Each part of a bracket of `text`, a masked text, whose every piece is names and years:
    the names, the years and the part as typed. What is masked stays in it as NUL, which is
    no name's and no year's, so a part with code or a comment in it is read as no citation."""
    for found in _GROUP.finditer(text):
        inside = found.group("inside")
        if "\n\n" in inside:
            continue
        pieces = [" ".join(part.split()) for part in inside.split(";")]
        read = [_PART.fullmatch(piece) for piece in pieces]
        if not _every_piece_cites(read):
            continue
        for piece, one in zip(pieces, read, strict=True):
            if one is not None:
                yield one.group("names"), tuple(_ONE_YEAR.findall(one.group("years"))), piece


def cited_as_typed(texts: Sequence[str], works: Works) -> dict[str, str]:
    """Each key of `works` a citation typed in brackets in `texts` names, with the words of
    the first."""
    listing = _Listing.of(texts)
    by_year: dict[str, list[str]] = {}
    for (_family, year), keys in works.keys.items():
        by_year.setdefault(year, []).extend(key for key in keys if key in works.people)
    found: dict[str, str] = {}
    for text in texts:
        masked = mask(text)
        chars = list(masked)
        for start, end in (*reference_lists(text), *code_spans(masked)):
            chars[start:end] = NUL * (end - start)
        for names, years, shown in _parts("".join(chars)):
            for year in years:
                key = _the_work(names, year, works, by_year, listing)
                if key is not None:
                    found.setdefault(key, shown)
    return found


def typed_only(project, uncited: Sequence[str]) -> dict[str, str]:
    """Of the keys `uncited`, those a Markdown manuscript cites as typed text in brackets,
    with the words of the citation. A LaTeX manuscript cites by command, and is not read."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.citations import BIB_FILE
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if not uncited or manuscript_format(folder) == LATEX:
        return {}
    works = works_by(project.path("literature") / BIB_FILE)
    found = cited_as_typed([read_text(path) for path in source_files(folder)], works)
    return {key: found[key] for key in uncited if key in found}
