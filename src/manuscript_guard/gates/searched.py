"""G7, for a reference with neither a DOI nor a PMID: whether a registry has the work.

An invented reference usually carries no identifier, and until 2026-10-20 such a reference
was never asked of anyone. Now `manuscript-guard lookup` searches PubMed and Crossref for it
by its title, and OpenAlex while its free allowance lasts, and keeps in the record each work
of their answers that holds half the cited title's words or more. This reads the record and
asks nobody. It goes by rules, never by a registry's score of relevance (paper-preflight,
`docs/adr/0003-identifier-first-routing.md`; `ATTRIBUTION.md`):

* **A work is the one cited** when its title holds 85% of the cited title's words or more
  (the rule G7 holds an identifier's work to) and the cited title holds 85% of the words of
  its title before any subtitle, one of its years is within one of the cited year, and the
  first person it lists is the cited first author, by family name (`gates/authors`; where
  either side names no person, the authors are not compared). The rule is held both ways
  here because a search, unlike an identifier, finds every longer title that repeats the
  cited words: for "Dexamethasone in Hospitalized Patients with Covid-19", Crossref has
  "Faculty Opinions recommendation of Dexamethasone in Hospitalized Patients with Covid-19"
  and PubMed a dozen trials of tocilizumab with dexamethasone in their titles.
  A notice, a comment or a reply that repeats the title is never the work, nor is a peer
  review, a grant or a part of a work; nor a DOI under a prefix of fabricated copies,
  which Crossref's search puts first once the authors' names are in the query.
* **Found** (`reference-found`, a note): the work's DOI and PMID are offered, to be added
  in Zotero; nothing is written into the .bib. The authors are compared, and a retraction
  of the work is said as for a reference with an identifier.
* **A work of the title and the year by other people**: none of the cited people on the
  lists PubMed and Crossref keep for it fails from internal-review
  (`reference-authors-disjoint`), the shape of an invented reference; some of them is a
  warning (`reference-authors-differ`). A list only OpenAlex keeps never fails: its
  records can carry another work's details.
* **Not found** (`reference-not-found`, fails from internal-review): PubMed and Crossref
  were asked and answered, and OpenAlex too where it was asked, and none of them has a work
  of the title and the year. Said only of a journal article from 1966, when MEDLINE begins,
  to the year it was looked up: a book, a report, a thesis, a web page or a conference
  abstract may be real and in no registry. A source that did not answer leaves the
  question open: an outage is never a negative.
* **Cannot be determined** (`reference-unchecked`, one note for all of them): the reason
  for each, a book, a work older than MEDLINE, a title in another script, a title too
  short to search for, or `lookup.not_indexed` in paper.yaml, where the author says why a
  real work is in no registry.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.findings import FAIL, INFO, Finding
from manuscript_guard.gates import authors, lookups
from manuscript_guard.literature import names
from manuscript_guard.literature.names import Authors, Name

#: The kinds of entry G7 says no registry has: a journal article.
JUDGED_KINDS = frozenset({"article"})
#: MEDLINE indexes from 1966. An older work may be real and in no registry.
FIRST_JUDGED_YEAR = 1966
#: DOI prefixes of fabricated copies of famous papers, registered as posted content
#: (paper-preflight's denylist; seen again on 2026-10-20: five copies of "Attention is all
#: you need" under 10.65215 ahead of the paper in Crossref's search with its authors).
DENIED_PREFIXES = ("10.65215/",)
#: Crossref types that are no work of their own.
NOT_WORKS = lookups.SERIES | lookups.VOLUMES | frozenset({"component", "peer-review", "grant"})
#: A first word of a registered title that marks a notice about the work or an answer to
#: it, "Correction: <the title>", "Comment on <the title>", "Re: <the title>": such a title
#: holds every word of the cited one, by other people, in the same year.
NOTICE_WORDS = frozenset({
    "erratum", "corrigendum", "correction", "corrections", "retraction", "comment",
    "comments", "commentary", "reply", "response", "re", "letter", "editorial", "notice",
    "expression", "addendum", "withdrawal", "withdrawn",
})  # fmt: skip
#: Words a search leaves out: they find nothing the title's other words do not.
STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "for", "and", "or", "with", "to", "by", "at", "from",
    "as", "is", "are", "be", "was", "were", "its", "it", "this", "that", "these", "those",
    "not", "no", "than", "into", "between", "after", "before", "during", "among", "versus",
    "vs", "via", "do", "does", "can", "how", "what", "why", "who", "which", "when",
})  # fmt: skip
MIN_SEARCH_WORDS = 3
MAX_SEARCH_WORDS = 12
#: What a search keeps of its answers: works that hold this much of the cited title.
KEPT = 0.5
SOURCES = {"pubmed_search": "PubMed", "crossref_search": "Crossref",
           "openalex_search": "OpenAlex"}  # fmt: skip


# -------------------------------------------------------------------- what is searched


def search_words(title: str) -> list[str]:
    """The words a registry is searched for: TeX and markup out, case and accents folded,
    each word once, the short and the common left out. A British spelling stays as it is,
    since the journal may have printed it so; a word in another script than Latin is left
    out."""
    text = lookups._TAGS.sub("", title)
    text = lookups._MATHS.sub("", lookups._SIGN.sub("", lookups._COMMAND.sub(lookups._untex, text)))
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = [w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 1 and w not in STOPWORDS]
    return list(dict.fromkeys(words))[:MAX_SEARCH_WORDS]


def unsearchable(fields: dict[str, str]) -> str:
    """Why a reference with no identifier cannot be searched for, or "" where it can."""
    title = fields.get("title", "")
    if not title.strip():
        return "it has no title to search for"
    if lookups.title_words(title) is None:
        return "its title is mostly in another script than Latin"
    if len(search_words(title)) < MIN_SEARCH_WORDS:
        return "its title has too few words to search for"
    return ""


def first_family(cited: Authors) -> str:
    """The cited first person's family name, for a search; "" where the first is a group or
    the entry names no one."""
    first = cited.names[0] if cited.names else None
    return first.family if first is not None and not first.group else ""


# ------------------------------------------------------------------ the works found


@dataclass(frozen=True)
class Work:
    """One work a search found, in the terms G7 compares."""

    source: str
    title: str
    titles: tuple[str, ...]
    years: tuple[int, ...]
    people: tuple[Name, ...]
    doi: str | None
    pmid: str | None
    answer: dict[str, Any]
    notice: bool = False

    @property
    def named(self) -> str:
        return _named([self])


def _pubmed(item: dict[str, Any]) -> Work:
    return Work(
        "PubMed", item.get("title", ""), (item.get("title", ""),),
        tuple(y for y in (item.get("year"),) if y), names.recorded(item.get("authors", [])),
        item.get("doi"), item["pmid"], item,
        notice=bool(lookups.PUBMED_NOTICES & set(item.get("pubtypes", []))),
    )  # fmt: skip


def _crossref(item: dict[str, Any]) -> Work:
    whole = ": ".join(filter(None, (item.get("title"), item.get("subtitle"))))
    notices = [n for n in item.get("update_to", []) if n["type"] in lookups.NOTICES]
    return Work(
        "Crossref", item.get("title", ""), (whole, item.get("original_title", "")),
        tuple(item.get("years", {}).values()), names.recorded(item.get("authors", [])),
        item["doi"], None, item,
        notice=bool(notices) or item.get("type") in NOT_WORKS
        or item["doi"].startswith(DENIED_PREFIXES),
    )  # fmt: skip


def _openalex(item: dict[str, Any]) -> Work:
    return Work(
        "OpenAlex", item.get("title", ""), (item.get("title", ""),),
        tuple(y for y in (item.get("year"),) if y), names.recorded(item.get("authors", [])),
        item.get("doi"), item.get("pmid"), item,
        notice=bool(item.get("doi", "").startswith(DENIED_PREFIXES)),
    )  # fmt: skip


_READERS = {"pubmed_search": _pubmed, "crossref_search": _crossref,
            "openalex_search": _openalex}  # fmt: skip


def works(record: dict[str, Any]) -> list[Work]:
    """Every work the record's searches kept, in the order the registries gave them."""
    found = []
    for name, read in _READERS.items():
        answer = record["sources"].get(name) or {}
        found += [read(item) for item in answer.get("candidates", [])]
    return found


def _first_word(title: str) -> str:
    words = lookups.title_words(title) or []
    return words[0] if words else ""


def _a_work(work: Work, cited_title: str) -> bool:
    """Not a notice, a comment or a reply that repeats the cited title."""
    first = _first_word(work.title)
    return not work.notice and not (first in NOTICE_WORDS and first != _first_word(cited_title))


#: Where a title's subtitle starts, after its main title: a colon, a question or an
#: exclamation mark, or a dash, with a space after it ("X: a cohort study", "Is X safe? A
#: cohort study", "X - a review"). Not a full stop: "Complementary Use of U.S. FDA's
#: Adverse Event Reporting System ..." is one title (the measurement of 2026-10-20).
_SUBTITLE = re.compile(r"(?<=\S)(?:[:?!]|\s[-\u2013\u2014])\s")
#: The flag a registry puts in front of a retracted work's title.
_FLAG = re.compile(r"^\s*(?:retracted|withdrawn)\s*:\s*", re.IGNORECASE)


def main_title(title: str) -> str:
    """A registered title before its subtitle, without the flag a registry puts in front."""
    title = _FLAG.sub("", title)
    return _SUBTITLE.split(title, maxsplit=1)[0]


#: The fewest words a cited main title has for a registered title that holds only it to be
#: taken for the cited one.
_MAIN_WORDS = 4


def alike(cited_title: str, titles: list[str]) -> float:
    """How alike the cited title is to the registered one, each way: the share of the cited
    title's words the registered title holds, and the share of the registered title's words
    the cited one holds, of its main title or of the whole, whichever is more; the lower of
    the two shares, at the registered title that best matches.

    Or the other way round, where the entry cites a subtitle the registry left out: the
    registered title wholly in the cited one, and the cited main title in the registered
    one. A guideline is printed with its task force in its title, which Crossref and PubMed
    leave out (two in the measurement of 2026-10-20)."""
    cited_main = main_title(cited_title)
    long_enough = len(lookups.title_words(cited_main) or []) >= _MAIN_WORDS
    best = 0.0
    for title in (t for t in titles if t):
        there = lookups.title_held(cited_title, title)
        whole = lookups.title_held(_FLAG.sub("", title), cited_title)
        main = lookups.title_held(main_title(title), cited_title)
        back = [b for b in (whole, main) if b is not None]
        if there is not None and back:
            best = max(best, min(there, max(back)))
        if long_enough and whole is not None:
            best = max(best, min(lookups.title_held(cited_main, title) or 0.0, whole))
    return best


def held(cited_title: str, work: Work) -> float:
    return alike(cited_title, list(work.titles))


def _dated(work: Work, year: int | None) -> bool:
    return year is None or any(abs(year - y) <= lookups.YEAR_SLACK for y in work.years)


# -------------------------------------------------------------------------- the verdict


@dataclass(frozen=True)
class Verdict:
    findings: tuple[Finding, ...] = ()
    #: Why nothing could be said of the reference, where nothing could.
    unchecked: str = ""


def judge(
    citekey: str,
    fields: dict[str, str],
    cited: Authors,
    record: dict[str, Any],
    path: Path,
    excuse: str | None,
) -> Verdict:
    """What one search record says of the reference it was written for."""
    title, year = fields.get("title", ""), lookups._cited_year(fields)
    usable = [w for w in works(record) if _a_work(w, title)]
    titled = [w for w in usable if held(title, w) >= lookups.TITLE_HELD]
    dated = [w for w in titled if _dated(w, year)]
    lead = [w for w in dated if _leads(cited, w)]
    if lead:
        return Verdict(tuple(_found(citekey, fields, cited, lead, path, excuse)))
    if dated:
        return Verdict(tuple(_by_others(citekey, title, cited, dated, path)))
    why = _open(fields, record, year)
    if why:
        return Verdict(unchecked=why)
    return Verdict((_not_found(citekey, title, record, usable, titled, path),))


def _leads(cited: Authors, work: Work) -> bool:
    """The cited first author is first on the work's list, or one side names no person."""
    said = authors.compare(cited, [work.people])
    return not said.compared or said.first


def _found(citekey, fields, cited, lead: list[Work], path, excuse) -> list[Finding]:
    # An article and its own conference abstract can share title, year and first author:
    # PubMed's article, then a journal article, is the one whose identifiers are offered.
    lead = sorted(lead, key=lambda w: (w.source != "PubMed",
                                       w.answer.get("type") not in (None, "journal-article")))
    offered = []
    for kind, value in (("DOI", next((w.doi for w in lead if w.doi), None)),
                        ("PMID", next((w.pmid for w in lead if w.pmid), None))):  # fmt: skip
        if value:
            offered.append(f"{kind} {value}")
    by = joined([w.source for w in lead])
    shown = " and ".join(offered) if offered else "no identifier"
    found = [lookups._finding(
        "reference-found",
        f"@{citekey} has no DOI and no PMID; {by} {'has' if ' and ' not in by else 'have'} "
        f"the work cited, with {shown}",
        path,
        "add it to the entry in Zotero, then `manuscript-guard sync-bib` and `manuscript-guard "
        "lookup`: G7 then checks the reference by its identifier" if offered else
        "nothing to add; the entry is checked by its title until it has an identifier",
        INFO,
    )]  # fmt: skip
    lists = [(w.source, w.people) for w in lead]
    about = f"the work of this title ({_named(lead) or 'no identifier'})"
    found += authors.judged(citekey, cited, lists, path, about)
    answers = {name: {"status": "found", **w.answer}
               for w in reversed(lead) for name in (w.source.lower(),)}  # fmt: skip
    if "openalex" in answers:
        answers["openalex"] = {"status": "found", "is_retracted": answers["openalex"].get(
            "is_retracted") is True}  # fmt: skip
    found += lookups._standing(citekey, fields, answers, path, excuse)
    return found


def _named(found: list[Work]) -> str:
    """The identifiers of the works, each once."""
    pmids = [f"PMID {w.pmid}" for w in found if w.pmid]
    dois = [f"doi:{w.doi}" for w in found if w.doi]
    return ", ".join(dict.fromkeys([*pmids, *dois]))


def joined(words: list[str]) -> str:
    """"PubMed", "PubMed and Crossref", "PubMed, Crossref and OpenAlex"."""
    words = list(dict.fromkeys(words))
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)


def _by_others(citekey, title, cited, dated: list[Work], path) -> list[Finding]:
    """A work of the cited title and year whose first author is another person."""
    lists = [(w.source, w.people) for w in dated]
    firm = [w for w in dated if w.source != "OpenAlex"]
    about = f"the work of this title ({_named(dated) or 'no identifier'})"
    return authors.judged(citekey, cited, lists, path, about, may_fail=bool(firm))


def _open(fields: dict[str, str], record: dict[str, Any], year: int | None) -> str:
    """Why "no registry has it" cannot be said, or "" where it can."""
    kind = fields.get("type", "").lower()
    if kind not in JUDGED_KINDS:
        return f"a {kind or 'reference'} entry, which may be real and in no registry"
    looked = date.fromisoformat(record["looked_up_on"]).year
    if year is not None and year < FIRST_JUDGED_YEAR:
        return f"of {year}, before MEDLINE begins in {FIRST_JUDGED_YEAR}"
    if year is not None and year > looked:
        return f"of {year}, after it was looked up"
    answers = record["sources"]
    asked = [n for n in ("pubmed_search", "crossref_search") if n in answers]
    if len(asked) < 2:
        return "PubMed and Crossref were not both asked"
    if any(a.get("status") == "unresolvable" for n, a in answers.items() if n in SOURCES):
        return "a registry did not answer"
    return ""


def _not_found(citekey, title, record, usable: list[Work], titled: list[Work], path) -> Finding:
    asked = [SOURCES[n] for n in SOURCES if n in record["sources"]]
    near = ""
    if titled:
        work = titled[0]
        near = (f"; {work.source} has a work of this title of "
                f"{', '.join(map(str, sorted(set(work.years)))) or 'no year'} ({work.named})")
    elif usable:
        work = max(usable, key=lambda w: held(title, w))
        near = (f"; the nearest, {work.named or work.source} {work.title!r}, is "
                f"{held(title, work):.0%} alike")
    return lookups._finding(
        "reference-not-found",
        f"@{citekey}: no registry has a work of this title and year: "
        f"{joined(asked)} were searched and answered{near}",
        path,
        "check that the work exists and that the title and year are written as published; a "
        "real work no registry indexes is said so under `lookup.not_indexed` in paper.yaml "
        f"({citekey}: <why>)",
        FAIL,
    )


__all__ = [
    "DENIED_PREFIXES",
    "FIRST_JUDGED_YEAR",
    "JUDGED_KINDS",
    "Verdict",
    "Work",
    "first_family",
    "judge",
    "search_words",
    "unsearchable",
    "works",
]
