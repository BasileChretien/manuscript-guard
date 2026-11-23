"""The entries of `references.bib` a manuscript cites only as text typed by hand.

`init --from` makes a typed group of citations keys only if each of its parts names an entry,
so one work the list lacks leaves the rest typed, and G7 said of each that nothing cites it
(the real-paper corpus, 24 false findings in 8 papers against 4 true). What is true of such
an entry is narrower: it is cited, and no key points to it, so `sync-bib`, which writes the
file from the keys, would drop it (Basile, 2026-11-23). The import does not change.

A typed citation counts for an entry by the rule the import makes a key by, all the
citation's names and its year: one author by name, two by both joined with "&" or "and",
three or more by every name or by the first and "et al.", and the year's letter as the typed
list prints it. A name is compared as the import compares it, as the list writes it, so
"Berg" is not "van der Berg" and "Xu" is not "Xue": G7's folding for the registries
(`gates.authors.name_words`) makes those two one. Only the first name's first letter may be
a capital the entry's lacks, as at the start of a sentence. Initials typed before the first
name must be the entry's. A capitalised word just before the names may be one of them
("Garcia Lopez", "Professor Lopez"), so it leaves the entry a warning unless it is among the
words that open a sentence (`_OPENERS`).

Read beyond what the import makes a key: each part of a group on its own, so an unknown
neighbour does not hide it; a page after the year ("Smith, 2020, p. 4"); several years
("Smith 2019, 2020", "Smith (2019, 2020)"); words in lower case before the name ("e.g.,");
"and colleagues", as "et al." is read; and a possessive ("Smith and Jones's (2020)").

A citation that may be two works counts for neither: two entries by those names and that
year; an entry the typed list holds by those names and that year and `references.bib` does
not, told apart by its initials and title; an entry of the list the import could not read
that holds the year and opens on the first author's name; or a work of that year whose name
holds TeX that cannot be read. With no typed list a year's letter is not known: a key's last
letter is no printed one, since Better BibTeX and the import key a first and a second work
`smith2020` and `smith2020a`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from manuscript_guard.gates.authors import PARTICLES, name_words
from manuscript_guard.gates.typed_citations import Works, _is_name, works_by
from manuscript_guard.literature.names import Authors, Name
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import NUL, mask
from manuscript_guard.text.reference_lists import reference_lists
from manuscript_guard.typed_references import read as read_typed
from manuscript_guard.typed_references.citations import _CITED_BEFORE, _PREFIX
from manuscript_guard.typed_references.entries import YEAR, Entry

#: A pair of brackets within a paragraph, with no bracket inside.
_GROUP = re.compile(r"\((?P<inside>[^()]{1,400})\)")
_YEARS = rf"(?P<years>{YEAR}(?:,\s*{YEAR})*)"
#: A page or a range of them after the year. Anything else there is not read.
_PAGE = r"(?:,\s*pp?\.\s*[A-Za-z]?\d+(?:\s*[-\N{EN DASH}]\s*[A-Za-z]?\d+)?)?"
#: A part of a bracket: names, perhaps a comma, the year or years, perhaps a page.
_PART = re.compile(rf"(?P<head>.+?),?\s+{_YEARS}{_PAGE}")
#: The bracket of a citation in the sentence: the year or years, perhaps a page.
_IN_SENTENCE = re.compile(rf"{_YEARS}{_PAGE}")
_ONE_YEAR = re.compile(YEAR)
#: What ends a citation's names and stands for those it leaves out.
_MORE = re.compile(r"(?:,?\s+et\s+al\b\.?|\s+and\s+colleagues)$")
_POSSESSIVE = re.compile("(?:'|\N{RIGHT SINGLE QUOTATION MARK})s$")
#: Between two names: a comma, "&" or "and", the last two perhaps with a comma before.
_JOIN = re.compile(r",\s*(?:&|and)\s+|\s+(?:&|and)\s+|,\s+")
_JOINS_LAST = re.compile(r"&|and")
_INITIAL = re.compile(r"[A-Z\N{LATIN CAPITAL LETTER A WITH GRAVE}-\N{LATIN CAPITAL LETTER THORN}]"
                      r"[a-z]?\.(?:-[A-Z][a-z]?\.)?")  # fmt: skip
_LETTERS = re.compile(r"[^\W\d_]+")
_TITLE_WORD = re.compile(r"[^\W_]+")
#: A key that ends in a letter after its year, which says nothing of a printed year's letter.
_KEY_LETTER = re.compile(r"\d{4}([a-z])$")
#: How far back a citation's names are looked for in its sentence.
_BACK = 200
#: The words that open a sentence and are no one's name: "Recently, Smith (2020)", "As Smith
#: (2020)". Any other capitalised word before a name may be part of it, "Garcia Lopez (2019)",
#: or a first author, "Brown, Lee (2018)".
_OPENERS = frozenset({
    "additionally", "also", "although", "and", "as", "because", "both", "but", "by",
    "conversely", "consequently", "finally", "first", "firstly", "following", "for", "from",
    "furthermore", "hence", "here", "however", "if", "importantly", "in", "indeed", "instead",
    "lastly", "later", "likewise", "moreover", "nevertheless", "nonetheless", "notably", "on",
    "overall", "previously", "recently", "second", "secondly", "similarly", "since",
    "specifically", "subsequently", "that", "then", "therefore", "third", "thirdly", "though",
    "thus", "to", "ultimately", "unlike", "when", "whereas", "while", "with", "yet",
})  # fmt: skip


@dataclass(frozen=True)
class _Head:
    """The words a citation's names are read from, cut at what joins two names."""

    text: str
    #: Where each name's words start and end in `text`, and what joins it to the next.
    spans: tuple[tuple[int, int], ...]
    joins: tuple[str, ...]
    #: It ends in "et al." or "and colleagues".
    more: bool


def _head(words: str) -> _Head:
    text = _POSSESSIVE.sub("", " ".join(words.split()))
    ending = _MORE.search(text)
    names = text[: ending.start()] if ending else text
    spans, joins, at = [], [], 0
    for join in _JOIN.finditer(names):
        spans.append((at, join.start()))
        joins.append(join.group())
        at = join.end()
    spans.append((at, len(names)))
    return _Head(names, tuple(spans), tuple(joins), ending is not None)


def _initials(given: str) -> tuple[str, ...]:
    return tuple(word[0].casefold() for word in _LETTERS.findall(given))


def _lead_fits(lead: str, *, bracketed: bool) -> bool:
    """Whether the words before a citation's names leave them all its names."""
    lead = lead.strip()
    if bracketed:
        return not lead or _PREFIX.fullmatch(lead) is not None
    words = lead.split()
    if not words:
        return True
    last = words[-1]
    if last.endswith(";") or _CITED_BEFORE.search(last):
        return True
    if last in ("and", "&"):
        # Between two citations, "Smith (2019) and Lee (2018)"; else the names go on before it.
        return len(words) > 1 and _CITED_BEFORE.search(words[-2]) is not None
    word = last.rstrip(",")
    if word.endswith(")"):
        return False  # "Brown (ed.) Lee (2018)": what the bracket follows may be a name.
    return _is_no_name(word)


def _is_no_name(word: str) -> bool:
    """Whether a word before a citation's names is none of them: in lower case throughout
    ("al-Rashid" is not), a number, or a word that opens a sentence."""
    return word.islower() or word.isdigit() or word.casefold() in _OPENERS


def _same_name(typed: str, family: str, *, opens: bool = False) -> bool:
    """Whether a name typed is the family name as the list writes it, as the import compares
    them. With `opens`, where it opens the citation, it may have a capital the entry lacks:
    "Van der Berg" for "van der Berg" at the start of a sentence."""
    written = " ".join(family.split())
    return typed == written or (
        opens and written[:1].islower() and typed == written[0].upper() + written[1:]
    )


def _first_name_fits(head: _Head, at: int, family: str, given: str, *,
                     bracketed: bool) -> int | None:  # fmt: skip
    """Where the citation's names start, if the name at `head.spans[at]` ends with `family`,
    after any initials the entry has too, and the words before it leave it the first of the
    citation's names."""
    start, end = head.spans[at]
    found = list(re.finditer(r"\S+", head.text[start:end]))
    words = [word.group() for word in found]
    taken = len(family.split())
    if not taken or len(words) < taken or not _is_name(words[-1]):
        return None
    if not _same_name(" ".join(words[-taken:]), family, opens=True):
        return None
    before = words[:-taken]
    typed: list[str] = []
    while before and _INITIAL.fullmatch(before[-1]):
        typed[:0] = [letters[0].casefold() for letters in _LETTERS.findall(before.pop())]
    if typed and tuple(typed) != _initials(given):
        return None
    if before and before[-1].casefold() in PARTICLES:
        return None
    lead = " ".join((head.text[:start] + " ".join(before)).split())
    if not _lead_fits(lead, bracketed=bracketed):
        return None
    return start + found[len(before)].start()


def _names_it(head: _Head, people: Authors, *, bracketed: bool) -> int | None:
    """Where the citation's names start if they are the entry's by the import's rule, or None
    where the citation is not of it."""
    if not people.names or any(not one.family for one in people.names):
        return None
    if head.more:
        if len(people.names) < 3 and not people.truncated:
            return None
        wanted = people.names[:1]
    elif people.truncated:
        return None
    else:
        wanted = people.names
    count = len(wanted)
    if len(head.spans) < count:
        return None
    joins = head.joins[len(head.joins) - (count - 1) :] if count > 1 else ()
    if joins and (not _JOINS_LAST.search(joins[-1])
                  or any(_JOINS_LAST.search(join) for join in joins[:-1])):  # fmt: skip
        return None
    at = len(head.spans) - count
    for offset, person in enumerate(wanted[1:], start=at + 1):
        start, end = head.spans[offset]
        if not _same_name(head.text[start:end], person.family):
            return None
    return _first_name_fits(head, at, wanted[0].family, wanted[0].given, bracketed=bracketed)


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


def _authors_of(entry: Entry) -> Authors:
    return Authors(tuple(Name(family=family, given=given) for family, given
                         in zip(entry.families, entry.initials, strict=True)))  # fmt: skip


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
            entries += [entry for _key, entry in typed.entries]
            unknown += [_NotRead.of(entry.text) for entry in typed.unread]
        return cls(tuple(entries), tuple(unknown))

    def letter(self, key: str, year: str, works: Works) -> str | None:
        """The letter the list prints after the year of the work `key`, "" for none, or None
        where that is not known: the list does not hold the work and the key ends in a
        letter, which says only that it was the second of its name and year."""
        printed = {entry.year[4:] for entry in self.entries if _same_work(entry, key, year, works)}
        if printed:
            return printed.pop() if len(printed) == 1 else None
        return None if _KEY_LETTER.search(key) else ""

    def holds_another(self, head: _Head, year: str, key: str, works: Works, *,
                      bracketed: bool) -> bool:  # fmt: skip
        """Whether the list holds a work other than `key` that the citation names."""
        return any(
            entry.year == year
            and not _same_work(entry, key, year[:4], works)
            and _names_it(head, _authors_of(entry), bracketed=bracketed) is not None
            for entry in self.entries
        )


def _the_work(head: _Head, year: str, works: Works, by_year: dict[str, list[str]],
              listing: _Listing, *, bracketed: bool) -> tuple[str, int] | None:  # fmt: skip
    """The one key the citation `head`, `year` names and where its names start, or None
    where it names none or may be of two works."""
    four, letter = year[:4], year[4:]
    if works.unread.get(four):
        return None
    fits = ((key, _names_it(head, works.people[key], bracketed=bracketed))
            for key in by_year.get(four, ()))  # fmt: skip
    named = {key: at for key, at in fits if at is not None}
    letters = {key: listing.letter(key, four, works) for key in named}
    same = [key for key, printed in letters.items() if printed == letter]
    if len(same) != 1 or None in letters.values():
        return None
    family = works.people[same[0]].names[0].family
    if any(entry.may_be(year, family) for entry in listing.unknown):
        return None
    if listing.holds_another(head, year, same[0], works, bracketed=bracketed):
        return None
    return same[0], named[same[0]]


@dataclass(frozen=True)
class _Typed:
    """A citation typed in the text: the words its names are read from, its years, and the
    bracket it has in the sentence, or None where it is a part of a bracket."""

    words: str
    years: tuple[str, ...]
    bracket: str | None


def _citations(text: str) -> Iterable[_Typed]:
    """Each citation typed in `text`, a masked text."""
    for found in _GROUP.finditer(text):
        inside = found.group("inside")
        if "\n\n" in inside:
            continue
        alone = _IN_SENTENCE.fullmatch(inside.strip())
        if alone is not None:
            floor = max(0, found.start() - _BACK)
            paragraph = text.rfind("\n\n", floor, found.start())
            before = text[paragraph + 2 if paragraph >= 0 else floor : found.start()]
            if before[-1:].isspace():
                years = tuple(_ONE_YEAR.findall(alone.group("years")))
                yield _Typed(" ".join(before.replace(NUL, " ").split()), years,
                             " ".join(inside.split()))  # fmt: skip
            continue
        for part in inside.split(";"):
            flat = " ".join(part.replace(NUL, " ").split())
            read = _PART.fullmatch(flat)
            if read is not None:
                yield _Typed(flat, tuple(_ONE_YEAR.findall(read.group("years"))), None)


def _shown(typed: _Typed, at: int) -> str:
    """The citation as the manuscript types it: its part of the bracket, or in the sentence
    its names, from the first, and its bracket."""
    if typed.bracket is None:
        return typed.words
    return f"{typed.words[at:]} ({typed.bracket})"


def _names_of(part: str) -> str:
    """The words before the year of a part of a bracket."""
    read = _PART.fullmatch(part)
    return read.group("head") if read is not None else part


def cited_as_typed(texts: Sequence[str], works: Works) -> dict[str, str]:
    """Each key of `works` a citation typed in `texts` names, with the words of the first."""
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
        for typed in _citations("".join(chars)):
            bracketed = typed.bracket is None
            head = _head(_names_of(typed.words) if bracketed else typed.words)
            for year in typed.years:
                read = _the_work(head, year, works, by_year, listing, bracketed=bracketed)
                if read is not None:
                    found.setdefault(read[0], _shown(typed, read[1]))
    return found


def typed_only(project, uncited: Sequence[str]) -> dict[str, str]:
    """Of the keys `uncited`, those a Markdown manuscript cites as typed text, with the words
    of the citation. A LaTeX manuscript cites by command, and is not read here."""
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
