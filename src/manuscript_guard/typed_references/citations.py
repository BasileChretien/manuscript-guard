"""A citation typed as text made a pandoc citation where it names exactly one entry of the
reference list, by its authors and its year.

A citation is compared with each entry as APA writes one: "Smith" for one author, "Smith &
Jones" or "Smith and Jones" for two, "Smith et al." or every name for three or more, "Smith,
Jones, & Lee" and its forms with "and" or without the last comma, and the year as the list
gives it, its letter included ("2020a"). The names must be the citation's all, so "Smith &
Jones" is not the work of Jones alone, and in the sentence nor are "Brown and Lee (2018)",
"Brown, Lee (2018)" or "Professor Lee (2018)" (`_names_alone`). A family name the list writes
in lower case, "van der Berg", is not read in capitals at the start of a sentence: citeproc
prints it in lower case, so the citation would not print as typed. Before a name in
brackets, words in lower case are the citation's prefix, "see", "e.g.,", and are kept:
`[e.g., @smith2020]`.

Read: a group in brackets, "(Smith & Jones, 2020)" or "(e.g., Smith, 2020; Lee, 2018)",
each of its parts a citation, made `[@smith2020; @lee2018]`; and the narrative "Smith et al.
(2019)", made `@smith2019`, which pandoc prints as typed.

Nothing is guessed. A citation stays as typed, and is listed with why, where it names no
entry, where it names two (two works "Smith 2020" with no letter), where an entry the list
could not read holds its year and one of its names and so may be the work, and, for a group,
where one of its parts is any of these or no citation at all: pandoc reads a group whole, so
a group is made a citation whole or not at all. A page or a second year in the brackets,
"(Smith, 2020, p. 4)" or "Smith (2020, 2021)", is not read, and is listed. So is a word in
capitals before a year in brackets that names no entry, "the UK Biobank (2020)": no rule
tells a work the list lacks from a name that is no citation's (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from manuscript_guard.typed_references.entries import YEAR, Entry, Unread

#: A pair of brackets on one line, with no bracket inside.
_GROUP = re.compile(r"\((?P<inside>[^()\n]{1,400})\)")
#: A part of a group: names, perhaps a comma, and the year.
_PART = re.compile(rf"(?P<head>.+?),? (?P<year>{YEAR})")
#: A part that opens as one does, with something after its year: "Smith, 2020, p. 4".
_OPENS = re.compile(rf"(?P<head>.+?),? (?P<year>{YEAR})(?![\w])")
_ALONE = re.compile(YEAR)
#: A year in the sentence's brackets with a page or a second year after it: "2020, p. 4".
_YEAR_FIRST = re.compile(rf"{YEAR}[,;] .+")
#: The end of a citation's year in brackets, as a word before a joining "and" or comma ends.
_CITED_BEFORE = re.compile(rf"{YEAR}\)[,;]?$")
#: The words before a name in brackets that are the citation's prefix: "see", "e.g.,".
_PREFIX = re.compile(r"[a-z][a-z.]*,?(?: [a-z][a-z.]*,?)*")
#: The ways APA joins the last of three names or more to the others.
_JOINS = (", & ", ", and ", " & ", " and ")


@dataclass(frozen=True)
class Left:
    """A citation typed as text that stays as typed: its line, its words and why."""

    line: int
    shown: str
    why: str


@dataclass(frozen=True)
class Made:
    """The text with each citation that names one entry made a pandoc citation, how many
    citations were, and those left as typed."""

    text: str
    converted: int
    left: tuple[Left, ...]


def renderings(families: tuple[str, ...]) -> tuple[str, ...]:
    """Every way APA names these authors in a citation, as the list writes the names."""
    first = families[0]
    if len(families) == 1:
        forms = [first]
    elif len(families) == 2:
        forms = [f"{first} & {families[1]}", f"{first} and {families[1]}"]
    else:
        listed = ", ".join(families[:-1])
        forms = [f"{first} et al.", *(f"{listed}{join}{families[-1]}" for join in _JOINS)]
    return tuple(forms)


def make_citations(text: str, keyed: Iterable[tuple[str, Entry]], unread: Iterable[Unread],
                   apart: list[tuple[int, int]]) -> Made:  # fmt: skip
    """`text` with each citation typed as text outside `apart` that names exactly one of the
    `keyed` entries made a pandoc citation of its key."""
    by_year: dict[str, list[tuple[str, Entry]]] = {}
    for key, entry in keyed:
        by_year.setdefault(entry.year, []).append((key, entry))
    unknown = [_Unknown.of(entry) for entry in unread]
    pieces: list[str] = []
    left: list[Left] = []
    at = converted = 0
    for found in _GROUP.finditer(text):
        if any(start <= found.start() < end for start, end in apart):
            continue
        line = text.count("\n", 0, found.start()) + 1
        inside = found.group("inside")
        if _ALONE.fullmatch(inside.strip()):
            made = _narrative(text, found, by_year, unknown)
        elif _YEAR_FIRST.fullmatch(inside.strip()):
            made = _narrative(text, found, by_year, unknown, more=True)
        else:
            made = _bracketed(inside, by_year, unknown)
        if made is None:
            continue
        if isinstance(made, str):
            left.append(Left(line, _shown(text, found), made))
            continue
        start, written, count = made
        start = found.start() if start is None else start
        pieces += [text[at:start], written]
        at, converted = found.end(), converted + count
    pieces.append(text[at:])
    return Made("".join(pieces), converted, tuple(left))


@dataclass(frozen=True)
class _Unknown:
    """An entry the list could not read, as a citation may still be of it: the years it
    holds and the words of its names, folded as G7 folds them."""

    line: int
    years: frozenset[str]
    words: frozenset[str]

    @classmethod
    def of(cls, entry: Unread) -> _Unknown:
        from manuscript_guard.gates.authors import name_words

        years = frozenset(year[:4] for year in re.findall(rf"(?<!\d){YEAR}", entry.text))
        return cls(entry.line, years, frozenset(name_words(entry.text)))

    def may_be(self, year: str, names: str) -> bool:
        from manuscript_guard.gates.authors import name_words

        return year[:4] in self.years and bool(
            (set(name_words(names)) - {"et", "al", "and"}) & self.words
        )


def _one(head: str, year: str, by_year, unknown, *, bracketed: bool):
    """The key and prefix of the one entry `head` and `year` name, or why there is none.
    In brackets, `head` is the part before the year, prefix and names; in the sentence, the
    text before the bracket, which must end with the names."""
    named = _named(head, year, by_year, bracketed=bracketed)
    if not named:
        if _named(head, year, by_year, bracketed=bracketed, capital=True):
            return ("it is typed with a capital its entry's name lacks, which the citation "
                    "pandoc makes would print in lower case")  # fmt: skip
        return "it names no entry of the reference list by its authors and year"
    if len(named) > 1:
        return (f"it names {len(named)} entries of the reference list by its authors and "
                "year")  # fmt: skip
    (key, (lead, form)), = named.items()
    for entry in unknown:
        if entry.may_be(year, form):
            return (f"the entry on line {entry.line}, which could not be read, may be the "
                    "work it names")  # fmt: skip
    return key, lead, form


def _named(head: str, year: str, by_year, *, bracketed: bool,
           capital: bool = False) -> dict[str, tuple[str, str]]:  # fmt: skip
    """The entries `head` and `year` name, each with the prefix and the names it is named
    by, the longest. With `capital`, by each form with its first letter in capitals."""
    named: dict[str, tuple[str, str]] = {}
    for key, entry in by_year.get(year, []):
        for form in renderings(entry.families):
            if capital:
                if form[:1].isupper():
                    continue
                form = form[0].upper() + form[1:]
            if not head.endswith(form):
                continue
            lead = head[: -len(form)]
            if bracketed:
                fits = not lead or (lead.endswith(" ") and _PREFIX.fullmatch(lead.rstrip()))
            else:
                fits = not (lead[-1:].isalnum() or lead[-1:] in tuple("'’-")) and _names_alone(
                    lead
                )
            if fits and len(form) > len(named.get(key, ("", ""))[1]):
                named[key] = (lead.strip() if bracketed else "", form)
    return named


def _names_alone(before: str) -> bool:
    """Whether the words before a citation's names in the sentence leave them all its names:
    they end with no "and", "&" or comma, nor with a word in capitals that does not open the
    sentence. "Brown and Lee (2018)", "Brown, Lee (2018)" and "Professor Lee (2018)" are not
    the work of Lee alone (round 1 of #638: the first was made "Brown and @lee2018"). An "and"
    or a comma after another citation's year, "Smith (2019) and Lee (2018)", joins two
    citations, and leaves each its names (round 2)."""
    words = before.split()
    if not words:
        return True
    last = words[-1]
    if _CITED_BEFORE.search(last) or (
        last in ("and", "&") and len(words) > 1 and _CITED_BEFORE.search(words[-2])
    ):
        return True
    if last in ("and", "&") or last.endswith((",", ";")):
        return False
    opens = len(words) == 1 or words[-2].endswith((".", "!", "?", ":"))
    return not (last[:1].isupper() and not opens)


def _bracketed(inside: str, by_year, unknown) -> tuple[None, str, int] | str | None:
    """A group in brackets made a citation: `(None, written, how many)`, why it is not, or
    None where it is no citation at all."""
    parts = [" ".join(part.split()) for part in inside.split(";")]
    read = [_PART.fullmatch(part) for part in parts]
    # A part that has names and a year with more after it, a page, is a citation's too.
    if not any(found is not None and _names_like(found.group("head"))
               for found in map(_OPENS.match, parts)):  # fmt: skip
        return None
    cited = []
    for part, found in zip(parts, read, strict=True):
        if found is None or not _names_like(found.group("head")):
            return f"its part {part!r} is not names and a year alone"
        one = _one(found.group("head"), found.group("year"), by_year, unknown, bracketed=True)
        if isinstance(one, str):
            return f"{one}, {part!r}" if len(parts) > 1 else one
        key, lead, _form = one
        cited.append(f"{lead} @{key}" if lead else f"@{key}")
    return None, f"[{'; '.join(cited)}]", len(cited)


def _narrative(text: str, found: re.Match, by_year, unknown, *, more: bool = False):
    """"Smith et al. (2019)" made `@smith2019`: `(start, written, 1)`, why it is not, or None
    where the words before the bracket are no names. With `more`, the brackets hold a page
    or a second year after the year, and the citation is listed. The words before it are
    read back to the paragraph's start, across a line's break inside it (round 2 of #638:
    "As Brown and" over "Lee (2018)" was made "Brown and @lee2018")."""
    paragraph = text.rfind("\n\n", 0, found.start())
    before = text[paragraph + 2 if paragraph >= 0 else 0 : found.start()]
    if not before[-1:].isspace():
        return None
    stem = before.rstrip()
    if not stem or not _names_like(stem):
        return None
    if more:
        return "a page or a second year in its brackets, after the year, is not read"
    one = _one(stem, found.group("inside").strip(), by_year, unknown, bracketed=False)
    if isinstance(one, str):
        return one
    key, _lead, form = one
    return found.start() - len(before) + len(stem) - len(form), f"@{key}", 1


def _names_like(head: str) -> bool:
    """Whether the words before a year end as names do: a word in capitals that is no month,
    or "et al."."""
    from manuscript_guard.gates.typed_citations import _MONTHS

    words = head.split()
    if not words:
        return False
    last = words[-1].rstrip(",")
    return last == "al." or (
        last[:1].isupper() and last.rstrip(".").lower() not in _MONTHS and last[:1].isalpha()
    )


def _shown(text: str, found: re.Match) -> str:
    """A citation left as typed, as the listing shows it: the bracket, with the five words
    before it in its sentence where the bracket holds the year alone."""
    inside = found.group("inside").strip()
    if _ALONE.fullmatch(inside) or _YEAR_FIRST.fullmatch(inside):
        before = text[text.rfind("\n", 0, found.start()) + 1 : found.start()]
        cut = max(before.rfind(". "), before.rfind(") "), before.rfind("; "))
        words = before[cut + 2 if cut >= 0 else 0 :].split()[-5:]
        return " ".join([*words, found.group(0)])
    return found.group(0)
