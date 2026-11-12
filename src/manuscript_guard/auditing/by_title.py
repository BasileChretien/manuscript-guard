"""The audit's entries with no DOI and no PMID: sorted by their shape, and the articles and
books looked up in Crossref by their title (the author's decision of 2026-11-12, which
replaced his choice of 2026-11-11 to make no title search).

**Sorting** reads an entry's text, in this order, and the first rule that holds sorts it:

* a chapter of a book: "In:" after its title, or "In" and its editors, "(Eds.)";
* a journal article: a year then a volume, "2019;393:100-10", a volume and its issue before
  its pages, "12(3):45" or "12(3), 45-67", a volume and pages after a comma, ", 12, 45-67.",
  "vol. 12", or "in press";
* a legal or official text: one that opens with a legal act's word ("Arrêté", "Décret",
  "Loi", "Directive", "Regulation" and others), or that names an official journal or a
  register of law (`_LEGAL_NAMED`);
* a web page: one that says when it was accessed or cited, is marked "[Internet]", or says
  where it is available;
* a book: a place and a publisher before a year, "London: Example Press; 2019", an edition,
  an ISBN, a city in the United States, "Englewood Cliffs, NJ", a publisher named, or its
  editors;
* a web page again: one that gives a web address and nothing a journal or a publisher adds;
* anything else is not sorted, and is to be checked by hand.

The article comes before the web page, so that an article that also gives its address is an
article; the web page's own marks come before the book's, so that a page "[Internet].
Geneva: Example Agency; 2020" is a page.

**What an article or a book is looked up by** is read from it (`cited`): its title, its
first author's family name and its year. The title is the part after the authors, which end
at the first full stop not inside a run of initials ("Ross K. L."), or, after "(2019)." in
an author-year entry, the part after the year; a title in quotes is the quoted part. The
year is the one in brackets after the authors, or else the first year after the title, an
access date and a web address left out.

**A match is near-exact** (`near_exact`): the work's title, or its title and subtitle, the
same as the entry's once case, punctuation and accents are folded (`fold`); the work's first
author's family name the first word or words of the entry, folded the same way; and, where
the entry gives a year, one of the work's years that year. Crossref's search keeps no
notice, review or part of a work (`gates.searched._a_work`). Two works that match, with two
DOIs, are neither taken: the entry is then for a person to check.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

ARTICLE = "article"
BOOK = "book"
CHAPTER = "chapter"
WEB = "web page"
LEGAL = "legal text"
OTHER = "not sorted"
#: The kinds looked up by their title, and those no DOI is expected of.
SEARCHED = frozenset({ARTICLE, BOOK, CHAPTER})
NO_DOI_EXPECTED = frozenset({WEB, LEGAL})
#: Each kind as the report names it.
NOUN = {ARTICLE: "an article", BOOK: "a book", CHAPTER: "a chapter of a book",
        WEB: "a web page", LEGAL: "a legal or official text"}  # fmt: skip

#: What a search came to, by what the report says of it.
FOUND = "found"
TO_CHECK = "to check by hand"
EXPECTED = "no DOI expected"
PENDING = "not yet looked up"
#: Why an entry is to be checked by hand, each as the summary says it (`reason`).
NOT_FOUND = "none found by its title"
AMBIGUOUS = "more than one work of its title found"
UNANSWERED = "Crossref did not answer"
UNSEARCHED = "its title too short to look up, or not read"
UNSORTED = "not sorted"
REASONS = (NOT_FOUND, AMBIGUOUS, UNANSWERED, UNSEARCHED, UNSORTED)
#: The code of the note on an entry to check by hand, by why.
CODES = {NOT_FOUND: "not-found-by-title", AMBIGUOUS: "found-twice-by-title",
         UNANSWERED: "title-search-unanswered", UNSEARCHED: "title-not-searchable",
         UNSORTED: "reference-not-sorted"}  # fmt: skip

_URL = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)
_YEAR = r"(?:1[5-9]\d{2}|20\d{2})"

_CHAPTER = re.compile(
    r"\bIn:\s*\S|\bIn\s+[^()]{1,200}?\((?:Eds?|eds?)\.?\)|\bIn\s+[^()]{1,200}?,\s*(?:editors?|eds?\.)"
)
_ARTICLE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("it gives a year, then a volume", re.compile(
        rf"(?<!\d){_YEAR}[a-z]?(?:\s+[A-Z][a-z]{{2,8}}\.?(?:\s+\d{{1,2}})?"
        r"(?:\s*[-\u2013]\s*[A-Z]?[a-z]{0,8}\.?\s*\d{0,2})?)?\s*;\s*\(?\d")),
    ("it gives a volume and its issue before its pages", re.compile(
        r"(?<![\w/])\d{1,4}\s*\(\s*[\w./\u2013-]{1,15}\s*\)\s*[:,]\s*(?:pp?\.\s*)?[eE]?\d")),
    ("it gives a volume and pages", re.compile(
        r",\s*\d{1,4}\s*,\s*(?:pp?\.\s*)?[eE]?\d{1,6}(?:\s*[-\u2013]\s*\d{1,6})?\s*(?:\.|$)")),
    ("it gives a volume", re.compile(r"\bvol\.?\s*\d+", re.IGNORECASE)),
    ("it is in press", re.compile(r"\bin press\b", re.IGNORECASE)),
)  # fmt: skip
_LEGAL_OPENING = re.compile(
    r"^(arr[\u00eae]t[\u00e9e]|d[\u00e9e]cret|loi|ordonnance|circulaire|directive|"
    r"r[\u00e8e]glement|regulation|gesetz|verordnung|decreto|ley)(?![\w-])"
    # Not a person of that name, "Ley J." or "Loi, K.": a law's word is followed by none; nor
    # a name it begins, "Ley-Cooper A." (round 1 of #650).
    r"(?-i:(?!\s+(?:[A-Z]\.?-?){1,4}[,.\s]))(?!,)",
    re.IGNORECASE,
)
_LEGAL_NAMED = re.compile(
    r"\b(journal officiel|JORF|official journal of the european (?:union|communities)|"
    r"federal register|bundesgesetzblatt|bolet[\u00edi]n oficial|gazzetta ufficiale|"
    r"l[\u00e9e]gifrance|eur-lex|legislation\.gov\.uk|code de la sant[\u00e9e] publique|"
    r"code de l'[\u00e9e]ducation|public law \d+|U\.S\.C\.|act(?: of)? (?:1[89]|20)\d{2})(?!\w)",
    re.IGNORECASE,
)
_WEB: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("it says when it was accessed", re.compile(
        r"\[cited\b|\b(?:date\s+)?(?:last\s+)?accessed\b|\bconsult[\u00e9e]e?\s+le\b|"
        r"\bretrieved\b", re.IGNORECASE)),
    ("it is marked as on the Internet", re.compile(
        r"\[(?:internet|online|en ligne|web ?page|homepage)\]", re.IGNORECASE)),
    ("it says where it is available", re.compile(
        r"\bavailable (?:from|at|online)\b|\bdisponible (?:sur|en ligne)\b", re.IGNORECASE)),
)  # fmt: skip
_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|"
    "NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
_BOOK: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("it gives a place and a publisher before its year", re.compile(
        rf"[A-Z][^.;:]{{1,60}}:\s*[^.;:]{{2,80}};\s*(?:c\s*)?{_YEAR}")),
    ("it gives an edition", re.compile(
        r"\b\d+(?:st|nd|rd|th|e)\s+(?:ed|edn|edition|\u00e9d)\b", re.IGNORECASE)),
    ("it gives an ISBN", re.compile(r"\bISBN\b")),
    ("it gives a place in the United States", re.compile(
        rf"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s(?:{_STATES})(?=\s*[.:;,]|\s*$)")),
    ("it names a publisher", re.compile(
        r"\b(?:Press|Publishers?|Publishing|Verlag|Prentice[- ]Hall|Wiley|Springer|Elsevier|"
        r"Routledge|SAGE|McGraw[- ]Hill|Pearson|Lippincott|Saunders|Mosby|Dunod|Masson|"
        r"Hachette|Guilford|Basic Books|Norton)\b")),
    ("it names its editors", re.compile(r"\((?:Eds?|eds?)\.?\)|\beditors?\b")),
)  # fmt: skip


@dataclass(frozen=True)
class Sorted:
    """What kind of work an entry is, by its shape, and what in it says so."""

    kind: str
    why: str = ""


def sort(text: str) -> Sorted:
    """The kind of the entry `text`, typed with no number before it (`_text`)."""
    if _CHAPTER.search(text):
        return Sorted(CHAPTER, 'it is "In" a book')
    for why, pattern in _ARTICLE:
        if pattern.search(text):
            return Sorted(ARTICLE, why)
    opening = _LEGAL_OPENING.match(text)
    if opening:
        return Sorted(LEGAL, f'it opens with "{opening.group(1)}"')
    # A page's and a law's marks outside the title first, then a book's, then theirs inside
    # it: "How patients accessed care. London: Example Press; 2019." and "The Data
    # Protection Act 2018 explained. ..." are books (round 1 of #650), and "Commission
    # notice. Official Journal of the European Union. ..." is read with the journal as its
    # title.
    outside = _outside_title(text)
    found = _legal_or_web(outside)
    if found is not None:
        return found
    # A book's marks are read after the authors, whose initials "MA" or "PA" are no state.
    after = _URL.sub(" ", text[_authors_end(text):])
    for why, pattern in _BOOK:
        if pattern.search(after):
            return Sorted(BOOK, why)
    found = _legal_or_web(text)
    if found is not None:
        return found
    if _URL.search(text):
        return Sorted(WEB, "it gives a web address and nothing a journal or a publisher adds")
    return Sorted(OTHER)


def _legal_or_web(text: str) -> Sorted | None:
    """A legal text by the official journal or the register `text` names, or a web page by
    its own marks, or None."""
    named = _LEGAL_NAMED.search(text)
    if named:
        return Sorted(LEGAL, f'it names "{named.group(1)}"')
    for why, pattern in _WEB:
        if pattern.search(text):
            return Sorted(WEB, why)
    return None


def _outside_title(text: str) -> str:
    """`text` with the title `cited` reads in it blanked, or all of it where none is read."""
    said = cited(text)
    if said is None:
        return text
    at = text.find(said.title, _authors_end(text))
    if at < 0:
        at = text.find(said.title)
    if at < 0:
        return text
    return text[:at] + " " + text[at + len(said.title):]


# ------------------------------------------------------------------ what it is cited by


@dataclass(frozen=True)
class Cited:
    """What an entry is looked up by: its title, its first author's family name and its
    year, and each longer title its title may be, read on past a full stop the title holds
    ("U.S. FDA"), up to three parts of the entry in all."""

    title: str
    family: str = ""
    year: int | None = None
    titles: tuple[str, ...] = ()
    #: The whole entry, folded (`fold`): what a search's answer is not compared with, since
    #: an entry may open with a given name (round 1 of #650), and what the property that
    #: says so breaks the rule back to.
    opening: str = field(default="", compare=False)


#: A full stop, a question mark or an exclamation mark that ends a part of the entry.
_STOP = re.compile(r"[.?!](?=\s|$)")
#: A run of dotted letters before a stop, "U.S" or "e.g", and words a stop follows that end
#: no part.
_DOTTED = re.compile(r"(?:^|[\s(])(?:[A-Za-z]\.)+[A-Za-z]$")
_SHORT = frozenset({"vs", "st", "dr", "no", "vol", "ed", "eds", "pp", "p"})
#: An initial, "K" or "K." or "KL", which a stop after it may sit inside a run of.
_INITIAL = re.compile(r"(?:[A-Z]\.?-?){1,4}")
#: An entry that opens with a given name's initials, "K. L. Ross", "K.L. Ross" or "K. A. van
#: der Berg", as BibTeX's plain style, IEEE's and abbrv print it.
_GIVEN_FIRST = re.compile(
    r"(?:[A-Z]\.[\s-]*){1,4}(?:[a-z]{1,3}\s+){0,3}[A-ZÀ-ÖØ-Þ][a-z'’ß-ÿ]"
)
#: The year in brackets after an author-year entry's authors, "(2019)." or "(2019, March).".
_BRACKET_YEAR = re.compile(rf"\(({_YEAR})[a-z]?(?:,[^)]{{0,30}})?\)[.,]?\s+")
_PARTICLES = frozenset({"van", "von", "de", "der", "den", "da", "di", "du", "des", "le", "la",
                        "del", "dos", "ter", "ten", "et", "al", "al.", "and", "&",
                        "y"})  # fmt: skip
_QUOTES = {"'": "'", "\u2018": "\u2019", '"': '"', "\u201c": "\u201d"}
#: What an access date and a citation date say, which give no year of the work.
_ACCESS = re.compile(
    r"\[cited[^\]]*\]|\b(?:last\s+)?accessed\b[^.;\]]*|\bconsult[\u00e9e]e?\s+le\b[^.;\]]*|"
    r"\bretrieved\b[^.;\]]*",
    re.IGNORECASE,
)
_A_YEAR = re.compile(rf"(?<![\w/.-])({_YEAR})[a-z]?(?![\w/])")


def _stops(text: str) -> list[int]:
    """Where each part of `text` ends: at a stop that is neither inside a run of initials,
    "Ross K. L.", nor after a dotted abbreviation, "U.S.", nor after a short word that takes
    one, "vs."."""
    ends = []
    for stop in _STOP.finditer(text):
        at = stop.start()
        before = text[:at]
        word = before.split()[-1] if before.split() else ""
        if text[at] == "." and (_abbreviated(before) or word.casefold() in _SHORT):
            continue
        after = text[stop.end():].lstrip()
        if text[at] == "." and _INITIAL.fullmatch(word) and re.match(r"[A-Z]\.", after):
            continue
        ends.append(stop.end())
    return ends


def _abbreviated(before: str) -> bool:
    """Whether `before` ends in a dotted abbreviation, "U.S" or "e.g", rather than in a
    person's dotted initials after their name, "Ross K.L", whose stop ends the authors."""
    dotted = _DOTTED.search(before)
    if dotted is None:
        return False
    run = dotted.group(0).strip(" (")
    words = before[: dotted.start() + 1].split()
    named = bool(words) and words[-1][:1].isupper() and run.replace(".", "").isupper()
    return not named


def _parts(text: str) -> list[tuple[int, int]]:
    """The parts of `text`, between its stops, each as where it starts and ends."""
    parts, start = [], 0
    for end in [*_stops(text), len(text)]:
        piece = text[start:end]
        if piece.strip():
            lead = len(piece) - len(piece.lstrip())
            parts.append((start + lead, end))
        start = end
    return parts


def _authors_end(text: str) -> int:
    """Where an entry's authors end: after the year in brackets of an author-year entry
    whose authors are only names, or else at its first stop."""
    bracketed = _bracket_year(text)
    if bracketed is not None:
        return bracketed.end()
    return _authors_stop(text) or 0


def _authors_stop(text: str) -> int | None:
    """Where an entry with no year in brackets ends its authors: at its first stop, or, where
    it opens with an initial, as a BibTeX style prints a given name first ("K. L. Ross.
    Ghosts ..."), at the first stop after a word that is no initial."""
    stops = _stops(text)
    if not stops:
        return None
    if _GIVEN_FIRST.match(text):
        for end in stops:
            words = text[:end].rstrip(".?! ").split()
            if words and not _INITIAL.fullmatch(words[-1].rstrip(".")):
                return end
    return stops[0]


def _bracket_year(text: str) -> re.Match[str] | None:
    """The year in brackets after an author-year entry's authors, where all before it are
    names: capitalised words, initials, particles and "&" (`_PARTICLES`)."""
    found = _BRACKET_YEAR.search(text, 0, 300)
    if found is None:
        return None
    words = re.findall(r"[^\s,;]+", text[: found.start()])
    named = all(w[0].isupper() or w.casefold() in _PARTICLES or w == "..." for w in words)
    return found if words and named else None


def _first_family(authors: str) -> str:
    """The first author's family name: the first author's words before their initials,
    "Ross KL" or "Ross, K. L.", or "" where the entry opens with none."""
    first = re.split(r"[,;]|\s&\s|\sand\s", authors.strip(" ."), maxsplit=1)[0].strip()
    words = first.split()
    while len(words) > 1 and _INITIAL.fullmatch(words[-1]):
        words.pop()
    while len(words) > 1 and _INITIAL.fullmatch(words[0]):
        words.pop(0)
    family = " ".join(words).strip(" .")
    return "" if not family or _INITIAL.fullmatch(family) else family


def _closing(text: str) -> int:
    """Where the quote that `text` opens with closes, or 0 where it opens with none: the
    first closing quote not inside a word, so that "'Children's falls'" closes after
    "falls"."""
    if text[:1] not in _QUOTES:
        return 0
    found = re.search(f"{re.escape(_QUOTES[text[0]])}(?![^\\W\\d_])", text[1:])
    return found.start() + 1 if found else 0


def _without_marks(title: str) -> str:
    """A title without its quotes and without a medium in brackets after it."""
    title = re.sub(r"\s*\[[^\]]*\]\s*$", "", title.strip().rstrip(" ,.")).strip()
    close = _closing(title)
    if close:
        return title[1:close].strip(" ,.")
    return title.rstrip(" ,.")


def cited(text: str) -> Cited | None:
    """What the entry `text` is looked up by, or None where it has no title to read."""
    bracketed = _bracket_year(text)
    if bracketed is not None:
        authors, start, year = text[: bracketed.start()], bracketed.end(), int(bracketed.group(1))
    else:
        end = _authors_stop(text)
        if end is None:
            return None
        authors, start, year = text[:end], end, None
    parts = [(max(s, start), e) for s, e in _parts(text) if e > start]
    parts = [(s + len(text[s:e]) - len(text[s:e].lstrip()), e) for s, e in parts
             if text[s:e].strip()]  # fmt: skip
    if not parts:
        return None
    rest = text[parts[0][0]:]
    close = _closing(rest)
    if close:
        title = rest[1:close].strip(" ,.")
        after = parts[0][0] + close + 1
    else:
        title = _without_marks(text[parts[0][0]:parts[0][1]])
        after = parts[0][1]
    if not title:
        return None
    titles = tuple(dict.fromkeys(
        [title] + [_without_marks(text[parts[0][0]:parts[j][1]])
                   for j in range(1, min(3, len(parts)))]
    ))  # fmt: skip
    if year is None:
        later = _ACCESS.sub(" ", _URL.sub(" ", text[after:]))
        found = _A_YEAR.search(later)
        year = int(found.group(1)) if found else None
    return Cited(title, _first_family(authors), year, titles, fold(text))


# ------------------------------------------------------------------------- the match


def fold(text: str) -> str:
    """`text` with its tags, case, accents and punctuation folded away, each run of what is
    not a letter or a digit one space: "Børte" and "borte" are one, and so are "Children's"
    and "Children’s", both "children s"."""
    from manuscript_guard.gates.authors import LETTERS
    from manuscript_guard.gates.lookups import _TAGS

    text = html.unescape(_TAGS.sub(" ", text))
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    text = "".join(c for c in text.translate(LETTERS) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", text))


def near_exact(said: Cited, work: dict[str, Any]) -> bool:
    """Whether Crossref's `work` is the entry read as `said`: the same title, the same first
    author's family name, and the same year where the entry gives one."""
    return (_same_title(said, work) and _same_first_author(said, work)
            and _same_year(said, work))  # fmt: skip


def _same_title(said: Cited, work: dict[str, Any]) -> bool:
    """The work's title, or its title and subtitle, one of the entry's, folded, without the
    flag a registry puts before a retracted or withdrawn work's title, "RETRACTED:", as
    `gates.searched` takes it off (round 1 of #650): the works most worth finding."""
    from manuscript_guard.gates.searched import _FLAG

    wanted = {fold(title) for title in said.titles} - {""}
    whole = ": ".join(t for t in (work.get("title"), work.get("subtitle")) if t)
    titles = {fold(_FLAG.sub("", t)) for t in (whole, work.get("title"),
                                               work.get("original_title")) if t}  # fmt: skip
    return bool(wanted & titles)


def _same_first_author(said: Cited, work: dict[str, Any]) -> bool:
    """The family name of the first person the work lists the first author's the entry is
    read to give (`cited`), folded: where the entry opens with a given name, "K. L. Ross.",
    its opening is no family name (round 1 of #650). A work that lists a group first, or no
    one, is none, and so is an entry whose first author was not read."""
    people = [p for p in work.get("authors") or [] if isinstance(p, dict)]
    family = fold(people[0].get("family", "")) if people else ""
    return bool(family) and family == fold(said.family)


def _same_year(said: Cited, work: dict[str, Any]) -> bool:
    """One of the work's years the entry's, where the entry gives one."""
    return said.year is None or said.year in set((work.get("years") or {}).values())


def matches(said: Cited, answer: dict[str, Any]) -> tuple[str, ...]:
    """The DOI of each work of Crossref's search `answer` that is the entry's, each once."""
    from manuscript_guard.gates import searched

    found = []
    for item in answer.get("candidates") or []:
        if not isinstance(item, dict) or not isinstance(item.get("doi"), str):
            continue
        if searched._a_work(searched._crossref(item), said.title) and near_exact(said, item):
            found.append(item["doi"])
    return tuple(dict.fromkeys(found))


# ------------------------------------------------------------------------ the search


@dataclass(frozen=True)
class Searched:
    """One entry with no DOI and no PMID: its kind, what it is looked up by, and what came
    of it; `path` is the census's."""

    path: Path
    entry: Any
    sorted: Sorted
    cited: Cited | None = None
    #: What was asked of Crossref, or would be; "" where nothing was to be.
    asked: str = ""
    #: "asked", "kept" (the cache), or "" where nothing was sent.
    came: str = ""
    #: The DOI of each near-exact work Crossref has.
    dois: tuple[str, ...] = ()
    #: Why an article or a book was not looked up, where it was not.
    unsearched: str = ""
    #: Why Crossref gave no answer, where it gave none.
    unanswered: str = ""

    @property
    def doi(self) -> str | None:
        return self.dois[0] if len(self.dois) == 1 else None


def _text(entry: Any, style: str) -> str:
    """An entry as it is sorted: its number, its marks of emphasis and its TeX off."""
    from manuscript_guard.auditing.reader import excerpt
    from manuscript_guard.auditing.references import BY_PLACE, KEYED
    from manuscript_guard.lookup.unidentified import plain

    text = " ".join(entry.text.split())
    if entry.number is not None and style != BY_PLACE:
        text = re.sub(r"^\\?[\[(]?\d{1,4}\\?[\].)]\s+", "", text, count=1)
    if style == KEYED:
        # A tie is a space, and "--" a dash, as TeX prints them.
        text = plain(re.sub(r"\\newblock\b", " ", text)).replace("~", " ").replace("--", "-")
    return " ".join(excerpt(text).split())


def unasked(census: Any) -> list[Searched]:
    """Each entry of `census` with no DOI and no PMID, sorted and read, nothing asked. A list
    whose entries are not told apart has none: each of its "entries" is an identifier."""
    from manuscript_guard.auditing.references import UNTOLD, without_identifier
    from manuscript_guard.gates.searched import unsearchable

    if getattr(census, "note", "") or census.style == UNTOLD:
        # No list was read, or its "entries" are identifiers.
        return []
    found = []
    for entry in census.entries:
        if not without_identifier(entry):
            continue
        text = _text(entry, census.style)
        kind = sort(text)
        said = cited(text) if kind.kind in SEARCHED else None
        why = ""
        if kind.kind in SEARCHED:
            why = "its title could not be read" if said is None else unsearchable(
                {"title": said.title})  # fmt: skip
        found.append(Searched(census.path, entry, kind, said, unsearched=why))
    return found


def _wanted(said: Cited) -> dict[str, Any]:
    return {"title": said.title, "family": said.family, "year": said.year}


def _kept_name(said: Cited) -> str:
    digest = hashlib.sha256(json.dumps(_wanted(said), sort_keys=True).encode()).hexdigest()
    return f"title_{digest[:24]}.json"


def asked_said(said: Cited) -> str:
    """What is asked of Crossref for an entry, as the report says it."""
    by = f", first author {said.family}" if said.family else ""
    return f'Crossref for the title "{said.title}"{by}' + (f", {said.year}" if said.year else "")


def search(
    censuses: list[Any], ask: Any, where: Any, *, cache: Path | None, dry_run: bool,
    credentials: Any,
) -> list[Searched]:  # fmt: skip
    """Each entry with no DOI and no PMID, sorted, and each article and book looked up in
    Crossref by its title (`lookup.unidentified.crossref`), or with `dry_run` only what
    would be asked. A record is read from and written to `cache` only."""
    from manuscript_guard.auditing.references import _read_kept
    from manuscript_guard.gates.searched import search_words
    from manuscript_guard.literature.names import Authors, Name
    from manuscript_guard.lookup import run, unidentified
    from manuscript_guard.lookup.sources import UNRESOLVABLE

    found: list[Searched] = []
    for census in censuses:
        for one in unasked(census):
            said = one.cited
            if one.sorted.kind not in SEARCHED or said is None or one.unsearched:
                found.append(one)
                continue
            one = replace(one, asked=asked_said(said))
            if dry_run:
                found.append(one)
                continue
            wanted = _wanted(said)
            kept = cache / _kept_name(said) if cache is not None else None
            record = _read_kept(kept, wanted) if kept is not None and kept.exists() else None
            came = "kept"
            if record is None:
                came = "asked"
                query = unidentified.Query(
                    said.title, tuple(search_words(said.title)),
                    Authors((Name(family=said.family),) if said.family else ()), said.year,
                )  # fmt: skip
                record = {"identifiers": wanted,
                          "sources": {"crossref_search": unidentified.crossref(query, ask, where)}}
                run._never_kept(record, credentials)
                answer = record["sources"]["crossref_search"]
                if kept is not None and answer.get("status") != UNRESOLVABLE:
                    kept.parent.mkdir(parents=True, exist_ok=True)
                    kept.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n",
                                    encoding="utf-8")  # fmt: skip
            answer = record["sources"].get("crossref_search") or {}
            if answer.get("status") == UNRESOLVABLE:
                found.append(replace(one, came=came,
                                     unanswered=str(answer.get("why") or "no reason given")))
                continue
            found.append(replace(one, came=came, dois=matches(said, answer)))
    return found


def look_up_all(
    censuses: list[Any],
    *,
    dry_run: bool = False,
    cache: Path | None = None,
    transport: Any = None,
    services: Any = None,
    credentials: Any = None,
    today: Any = None,
    pacer: Any = None,
) -> tuple[list[Any], list[Searched]]:
    """What `--lookup` asks: each entry with a DOI or a PMID (`references.look_up`), and each
    article or book with neither looked up in Crossref by its title (`search`), the DOI of a
    near-exact match then asked about as an entry's own, through one transport and one
    pace. Returns what was asked of the registries, in the lists' order, the entries found
    by their title among it; and each entry with no DOI and no PMID, sorted."""
    from datetime import date

    from manuscript_guard.auditing import references
    from manuscript_guard.lookup import run, unidentified
    from manuscript_guard.lookup.http import default_transport

    services = services or run.Services()
    credentials = credentials or run.Credentials.from_environment(None)
    pacer = pacer or run.Pacer()
    looked = references.look_up(censuses, dry_run=dry_run, cache=cache, transport=transport,
                                services=services, credentials=credentials, today=today,
                                pacer=pacer)  # fmt: skip
    ask = run._asker(transport or default_transport, pacer, credentials)
    where = unidentified.Where(
        esearch=services.esearch, esummary=services.pubmed, crossref=services.crossref_search,
        openalex=services.openalex_search, credentials=credentials,
    )  # fmt: skip
    titles = search(censuses, ask, where, cache=cache, dry_run=dry_run, credentials=credentials)
    asking = references._Asking(ask, services, credentials, today or date.today(), cache,
                                dry_run)  # fmt: skip
    for one in titles:
        if one.doi:
            entry = replace(one.entry, dois=(one.doi,))
            looked.append(references._looked_up(
                one.path, entry, asking, by_title=True,
                asked=f"Crossref for its title, which gave doi:{one.doi}; then "))  # fmt: skip
    # In the lists' order: a LaTeX paper's entries stand in several files, whose lines are
    # not one count.
    order = {(census.path, entry.path, entry.line, entry.label): (at, place)
             for at, census in enumerate(censuses)
             for place, entry in enumerate(census.entries)}  # fmt: skip
    looked.sort(key=lambda one: order.get((one.path, one.entry.path, one.entry.line,
                                           one.entry.label), (len(censuses), 0)))  # fmt: skip
    return looked, titles


# ------------------------------------------------------------------------ what is said


def outcome(one: Searched, looked_up: bool) -> str:
    """What the entry comes to: found, to check by hand, no DOI expected, or not yet looked
    up (no `--lookup`, or a dry run)."""
    found = reason(one, looked_up)
    return TO_CHECK if found in REASONS else found


def reason(one: Searched, looked_up: bool) -> str:
    """`outcome`, with why an entry is to be checked by hand said as it is (`REASONS`): not
    sorted, its title not looked up, Crossref not answering, more than one work of its title,
    or none (round 1 of #650: all five were "no DOI or PMID found")."""
    kind = one.sorted.kind
    if kind in NO_DOI_EXPECTED:
        return EXPECTED
    if kind not in SEARCHED:
        return UNSORTED
    if one.unsearched:
        return UNSEARCHED
    if not looked_up or not one.came:
        return PENDING
    if one.unanswered:
        return UNANSWERED
    if one.doi:
        return FOUND
    return AMBIGUOUS if one.dois else NOT_FOUND


def without_identifier(report: Any) -> list[Searched]:
    """Each entry with no DOI and no PMID of `report`'s lists: as `--lookup` left them, or,
    without it, sorted and read with nothing asked (`unasked`)."""
    if report.lookups is not None and getattr(report, "titles", None) is not None:
        return list(report.titles)
    return [one for census in report.references for one in unasked(census)]


def said(one: Searched, looked_up: bool) -> str:
    """What the report says of one entry with no DOI and no PMID, plainly."""
    kind = one.sorted.kind
    noun = NOUN.get(kind, "")
    if kind in NO_DOI_EXPECTED:
        return f"no DOI expected: {noun} ({one.sorted.why})"
    if kind not in SEARCHED:
        return ("not sorted: neither an article, a book, a web page nor a legal text by its "
                "shape, so not looked up: check it by hand")  # fmt: skip
    if one.unsearched:
        return f"{noun} with no DOI given, not looked up by its title, as {one.unsearched}: " \
               "check it by hand"
    if not looked_up:
        return (f"{noun}: looked up in Crossref by its title only when the references are "
                "looked up (--lookup)")  # fmt: skip
    if not one.came:
        return f"{noun}: would ask {one.asked}"
    if one.unanswered:
        return (f"{noun} with no DOI given; Crossref did not answer ({one.unanswered}), so it "
                "was not looked up by its title: check it by hand")  # fmt: skip
    if one.doi:
        return f"{noun}, found by its title: DOI {one.doi}, then looked up as the others"
    if one.dois:
        return (f"{noun} with no DOI given; Crossref has {len(one.dois)} works of its title, "
                f"first author and year ({', '.join('doi:' + d for d in one.dois)}): check it "
                "by hand")  # fmt: skip
    return f"{noun} with no DOI given, and none found by its title: check it by hand"


__all__ = ["AMBIGUOUS", "ARTICLE", "BOOK", "CHAPTER", "CODES", "EXPECTED", "FOUND", "LEGAL",
           "NOT_FOUND", "NO_DOI_EXPECTED", "OTHER", "PENDING", "REASONS", "SEARCHED", "TO_CHECK",
           "UNANSWERED", "UNSEARCHED", "UNSORTED", "WEB", "Cited", "Searched", "Sorted", "cited",
           "fold", "look_up_all", "matches", "near_exact", "outcome", "reason", "said", "search",
           "sort", "unasked", "without_identifier"]  # fmt: skip
