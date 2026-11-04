"""A citation typed as text, read where G2 finds its year unbound, so the hint can name the key.

A co-author who types "(Fictional, 2018)" in Word leaves a year that `import` merges as
text, and G2 then fails it as a number nobody bound. The generic hint told the author to bind
it with `{{results.<key>}}` or to declare it a convention, and the fix they needed was
`[@fictionalCohort2018]`. What fails does not change here: the year is still unbound and G2
still fails it. Only the hint does: it says the year may be a citation's, and names the key
of each work `references.bib` holds by that first author's family name from that year, as a
work the author may mean and not as the one they meant: neither the year's letter ("2021b")
nor a given name is compared. The hint G2 gave before follows it.

A name in `references.bib` is read as a reader sees it, TeX and accents folded as G7 folds
the names it compares (`gates.authors.name_words`): `{\\AA}ngstr{\\"o}m` is "Ångström" and
"Angstrom", `L{\\o}kke` is "Løkke" and "Lokke". A name holding TeX that reading does not know
is not said to be missing: the hint names its entry to look at before adding the work.
Where nothing matches, the hint never says the work is missing either, since a name can be
missed: it says to cite the work by its key, adding it to `references.bib` if it is not there.

The forms read are the author-year ones: "(Name, 2018)", "(Name 2018)", "(Name et al.,
2018)", "(Name & Other, 2018)", "(Name and Other, 2018)", each part of a group "(Name, 2018;
Other, 2019)", and the narrative "Name (2018)", "Name et al. (2018)", "Name and Other (2018)".
A name is a word that opens with a capital; a month is not one, so "(March, 2018)" is a date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: A year a citation gives: four digits from 1800 to 2099, with a letter after where an
#: author has two works in one year.
_YEAR = re.compile(r"(?:18|19|20)\d\d[a-z]?")
_MONTHS = frozenset((
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec",
))  # fmt: skip
#: How far back a citation's names are looked for.
_BACK = 200
_AND = frozenset({"and", "&"})


@dataclass(frozen=True)
class Typed:
    """A citation typed as text: the first author's name as written, the year, and the words
    as they stand in the manuscript."""

    name: str
    year: str
    shown: str


def _flat(text: str) -> str:
    return " ".join(text.split())


def _is_name(word: str) -> bool:
    """A family name's word: letters, a hyphen or an apostrophe inside, opening with a capital,
    and no month."""
    letters = word.replace("-", "").replace("'", "").replace("\N{RIGHT SINGLE QUOTATION MARK}", "")
    return (
        bool(letters)
        and letters.isalpha()
        and word[0].isupper()
        and word.rstrip(".").lower() not in _MONTHS
    )


def _narrated(words: list[str]) -> str | None:
    """The first author's name in the words before "(2018)": the word before "et al.", the
    first of "Name and Other", "Name & Other" or "Name, Other and Third", else the last word."""
    if words[-2:] in (["et", "al."], ["et", "al"]):
        words = words[:-2]
    else:
        # "and" one or two words before the bracket, a second author's name after it.
        ands = [at for at in range(max(1, len(words) - 3), len(words) - 1) if words[at] in _AND]
        if ands and _is_name(words[ands[-1] - 1].rstrip(",")):
            words = words[: ands[-1]]
            while len(words) > 1 and words[-2].endswith(",") and _is_name(words[-2][:-1]):
                words = words[:-1]
    name = words[-1].rstrip(",") if words else ""
    return name if _is_name(name) else None


def _bracketed(part: str) -> str | None:
    """The first author's name in a citation's part of a bracket: the last word before its
    first comma, "&", "and" or "et al.", so "see Fictional" is Fictional and "Van der Berg"
    is Berg, as a family name is compared."""
    first = re.split(r",|\s&\s|\sand\s|\set\s+al\b", f" {part} ")[0].split()
    return first[-1] if first and _is_name(first[-1]) else None


def typed_citation(text: str, start: int, end: int) -> Typed | None:
    """The citation typed as text whose year is `text[start:end]`, or None where the number is
    not one. Only the year's own part of a group is read, so each year of "(Fictional, 2018;
    Other, 2019)" names its own author."""
    year = text[start:end]
    if not _YEAR.fullmatch(year):
        return None
    before = _flat(text[max(0, start - _BACK) : start].replace("\x00", " "))
    after = text[end : end + 3].lstrip()
    if before.endswith("(") and after.startswith(")"):
        # Narrative: Name (2018).
        words = before[:-1].split()[-6:]
        name = _narrated(words) if words else None
        if name is None:
            return None
        at = before.rfind(name, 0, len(before) - 1)
        return Typed(name, year[:4], f"{before[at:]}{year})")
    opened, closed = before.rfind("("), before.rfind(")")
    if opened <= closed or after[:1] not in (")", ";"):
        return None
    part = before[max(opened, before.rfind(";")) + 1 :].strip()
    name = _bracketed(part)
    if name is None:
        return None
    return Typed(name, year[:4], f"{part} {year}")


def _fold(name: str) -> str:
    """A family name's last word as two are compared, read as G7 reads the names it compares
    (`gates.authors.name_words`): TeX read as the letters it prints, then accents, case and
    the letters of their own folded to what a reader types, "Løkke" as "lokke"."""
    from manuscript_guard.gates.authors import name_words

    words = name_words(name)
    return words[-1] if words else ""


def _unread(family: str) -> bool:
    """Whether a `.bib` family name holds TeX that `_fold` does not read, which it would leave
    out: a command that is neither a letter, an accent nor a wrapper it knows (`{\\IJ}ssel`),
    or a backslash left over."""
    from manuscript_guard.gates import lookups

    text = family.replace("{", "").replace("}", "")
    for found in lookups._COMMAND.finditer(text):
        name = found.group(1)
        if name[0] not in lookups._ACCENTS and not any(map(name.startswith, lookups._KNOWN)):
            return True
    return "\\" in lookups._SIGN.sub("", lookups._COMMAND.sub("", text))


@dataclass(frozen=True)
class Works:
    """`references.bib`'s keys by first author and year, as `_fold` and four digits, and by
    year the keys of the works whose first author's name holds TeX `_fold` does not read."""

    keys: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    unread: dict[str, list[str]] = field(default_factory=dict)


def works_by(path: Path) -> Works:
    """The works of `references.bib` as the hint looks for them, its first author's name read
    as `literature.names` reads an author field. An unreadable file holds none: the hint then
    says to cite the work by its key."""
    from manuscript_guard.literature.bibfile import read_entries
    from manuscript_guard.literature.names import cited

    try:
        entries = read_entries(path, braces=True) if path.is_file() else {}
    except (OSError, ValueError):
        return Works()
    found: dict[tuple[str, str], list[str]] = {}
    unread: dict[str, list[str]] = {}
    for key, fields in entries.items():
        year = re.search(r"\d{4}", fields.get("year") or fields.get("date") or "")
        people = cited(fields.get("author") or fields.get("editor") or "").names
        if not year or not people or not people[0].family:
            continue
        if _unread(people[0].family):
            unread.setdefault(year.group(), []).append(key)
        elif family := _fold(people[0].family):
            found.setdefault((family, year.group()), []).append(key)
    return Works({where: sorted(keys) for where, keys in found.items()},
                 {year: sorted(keys) for year, keys in unread.items()})  # fmt: skip


def keys_for(typed: Typed, works: Works) -> list[str]:
    """The keys of the works `typed` may be: its first author's family name and its year."""
    return works.keys.get((_fold(typed.name), typed.year), [])


def hint(typed: Typed, works: Works, *, latex: bool, otherwise: str) -> str:
    """What G2 says of the year of a citation typed as text: that it may be one, and the key
    of each work in `references.bib` by that family name from that year, which the author may
    mean, not the one they meant. A capitalised word before a year need not be an author
    ("Japan (2018)"), so `otherwise`, the hint G2 gave before, follows in every case."""

    def cite(key: str) -> str:
        return f"\\cite{{{key}}}" if latex else f"[@{key}]"

    def listed(keys: list[str]) -> str:
        return ", ".join(cite(key) for key in keys[:-1]) + f" and {cite(keys[-1])}" \
            if len(keys) > 1 else cite(keys[0])

    typed_as = f"if this is a citation typed as text, \"{typed.shown}\", "
    keys = keys_for(typed, works)
    if len(keys) == 1:
        return (
            f"{typed_as}references.bib holds a work by {typed.name} from {typed.year}: if it "
            f"is the one meant, cite it with its key, {cite(keys[0])}, in place of the typed "
            f"text. Otherwise, {otherwise}"
        )
    if keys:
        return (
            f"{typed_as}references.bib holds {len(keys)} works by {typed.name} from "
            f"{typed.year}, {listed(keys)}: if one of them is the work meant, cite it with its "
            f"key in place of the typed text. Otherwise, {otherwise}"
        )
    unread = works.unread.get(typed.year, [])
    if unread:
        return (
            f"{typed_as}cite the work with its key, {cite('key')}, in place of the typed text; "
            f"the name of {listed(unread)}, from {typed.year}, holds TeX this check does not "
            f"read, so look there before adding the work to references.bib. Otherwise, "
            f"{otherwise}"
        )
    return (
        f"{typed_as}cite it with its key from references.bib, {cite('key')}, in place of the "
        f"typed text, adding the work there first if it is not yet in it (sync-bib reads it "
        f"from Zotero). Otherwise, {otherwise}"
    )
