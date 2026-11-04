"""A citation typed as text, read where G2 finds its year unbound, so the hint can name the key.

A co-author who types "(Fictional, 2018)" in Word leaves a year that `import` merges as
text, and G2 then fails it as a number nobody bound. The generic hint told the author to bind
it with `{{results.<key>}}` or to declare it a convention, and the fix they needed was
`[@fictionalCohort2018]`. What fails does not change here: the year is still unbound and G2
still fails it. Only the hint does: it says the year is a citation's, and names the key
`references.bib` holds for that first author and year, where it holds one.

The forms read are the author-year ones: "(Name, 2018)", "(Name 2018)", "(Name et al.,
2018)", "(Name & Other, 2018)", "(Name and Other, 2018)", each part of a group "(Name, 2018;
Other, 2019)", and the narrative "Name (2018)", "Name et al. (2018)", "Name and Other (2018)".
A name is a word that opens with a capital; a month is not one, so "(March, 2018)" is a date.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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
    """A family name's last word as two are compared: its letters, accents and case folded,
    so "Müller" is `M\\"uller` as a `.bib` file writes it."""
    words = name.split() or [""]
    decomposed = unicodedata.normalize("NFKD", words[-1])
    return "".join(c for c in decomposed if c.isalpha() and not unicodedata.combining(c)).casefold()


def _first_family(authors: str) -> str:
    """The first author's family name in a `.bib` author field: before the comma, or the last
    word."""
    first = authors.split(" and ")[0].strip()
    return first.split(",")[0] if "," in first else first


def works_by(path: Path) -> dict[tuple[str, str], list[str]]:
    """The keys of `references.bib` by first author and year, as `_fold` and four digits.
    An unreadable file holds none: the hint then says to cite the work by its key."""
    from manuscript_guard.literature.bibfile import read_entries

    try:
        entries = read_entries(path) if path.is_file() else {}
    except (OSError, ValueError):
        return {}
    found: dict[tuple[str, str], list[str]] = {}
    for key, fields in entries.items():
        year = re.search(r"\d{4}", fields.get("year") or fields.get("date") or "")
        family = _fold(_first_family(fields.get("author") or fields.get("editor") or ""))
        if year and family:
            found.setdefault((family, year.group()), []).append(key)
    return {where: sorted(keys) for where, keys in found.items()}


def keys_for(typed: Typed, known: dict[tuple[str, str], list[str]]) -> list[str]:
    """The keys of the works `typed` can be: its first author's last name and its year."""
    return known.get((_fold(typed.name), typed.year), [])


def hint(typed: Typed, keys: list[str], *, latex: bool, otherwise: str) -> str:
    """What G2 says of the year of a citation typed as text: that it is one, and the key. With
    no work of that author and year in `references.bib` it may be no citation ("Japan
    (2018)"), so the hint says what to do if it is one, and `otherwise` after it."""

    def cite(key: str) -> str:
        return f"\\cite{{{key}}}" if latex else f"[@{key}]"

    if len(keys) == 1:
        return (
            f"this is a citation typed as text, \"{typed.shown}\", and references.bib holds the "
            f"work: cite it with its key, {cite(keys[0])}, in place of the typed text"
        )
    if keys:
        listed = ", ".join(cite(key) for key in keys[:-1]) + f" or {cite(keys[-1])}"
        return (
            f"this is a citation typed as text, \"{typed.shown}\", and references.bib holds "
            f"{len(keys)} works by {typed.name} from {typed.year}: cite the one meant with its "
            f"key, {listed}, in place of the typed text"
        )
    return (
        f"if this is a citation typed as text, \"{typed.shown}\", cite the work with its key, "
        f"{cite('key')}, in place of the typed text; references.bib holds no work by "
        f"{typed.name} from {typed.year}, so add it there first (sync-bib reads it from "
        f"Zotero). Otherwise, {otherwise}"
    )
