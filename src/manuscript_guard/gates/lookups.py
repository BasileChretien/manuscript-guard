"""G7, from the lookup records: a cited work still stands, and is the work the entry names.

`manuscript-guard lookup` asks the registries and writes what they said to
`literature/lookups/<citekey>.yaml`. This reads those records and asks nobody, so it says the
same in CI as on the author's machine. What it fails on:

* a cited work the record shows retracted or withdrawn (from drafting), unless the paper
  says why it cites it anyway (`lookup.cited_as_retracted` in paper.yaml);
* a DOI no registry has, a DOI or PMID whose work has another title or another year, a
  DOI that is a notice, a journal or a series rather than the work, and a work none of
  whose authors is among those the entry names (from internal-review);
* a reference with neither a DOI nor a PMID that no registry has, searched for by its
  title (from internal-review; `gates/searched`).

And what it warns of: a preprint published since or withdrawn, a later version of the work,
an expression of concern, a number of the literature ledger quoted from a work PubMed types
only as an editorial or a comment (a review among them gives a note; a letter, nothing), a
volume or first page that differs,
authors of whom only some are on the work's record or the first not first, a placeholder
for the pages, an entry changed since its lookup, and references never looked up or looked
up too long ago. A lookup that got no answer is a note: a registry that did not answer said
nothing, and nothing fails on it. So is a correction of the work, a reference with no
identifier found by its title, with the identifier it can be given, and one that could be
neither found nor said to be missing, with the reason.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.identifiers import doi_of, pmid_of
from manuscript_guard.gates.spelling import _variants
from manuscript_guard.literature import names
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.literature.lookups import answers_digest, entry_digest, record_path

GATE = "G7"
BIB_FILE = "references.bib"
#: How much of the cited title the registered one must hold. A subtitle the entry left out
#: is no difference; a title that shares a few words of a field is another paper.
TITLE_HELD = 0.85
#: A year cited one off the print, online or issued year is the same work.
YEAR_SLACK = 1
MAX_AGE_DAYS = 365
RETRACTING = frozenset({"retraction", "withdrawal", "removal"})
CONCERNING = frozenset({"expression_of_concern", "partial_retraction"})
#: The kinds of update a notice makes. A DOI that updates another with one of these is the
#: notice, not the work; one that is a new version or a new edition of another is a work.
NOTICES = RETRACTING | CONCERNING | frozenset(
    {"correction", "corrigendum", "erratum", "addendum", "clarification", "reinstatement"}
)
#: Crossref types that are never one work: a journal, a series.
SERIES = frozenset({"journal", "book-series", "book-set", "proceedings-series", "report-series"})
#: Types that hold works, which an entry citing a whole volume or issue may resolve to.
VOLUMES = frozenset({"journal-issue", "journal-volume", "proceedings"})
CITES_A_VOLUME = frozenset(
    {"proceedings", "mvproceedings", "periodical", "collection", "mvcollection", "book"}
)
#: Crossref's kinds of update, as its Crossmark documentation lists the twelve its schema
#: accepts ("Participating in Crossmark", crossref.org/documentation/crossmark/participating-
#: in-crossmark/, read 2026-11-04: addendum, clarification, correction, corrigendum, erratum,
#: expression_of_concern, new_edition, new_version, partial_retraction, removal, retraction,
#: withdrawal), as the record writes them (`lookup/sources._update`). A notice in a work's
#: `updated_by` of one of the first set is a later version of it; of the second, a
#: correction of it. Retractions and concerns have their own findings above.
UPDATING = frozenset({"new_version", "new_edition"})
CORRECTING = frozenset({"correction", "corrigendum", "erratum", "addendum", "clarification"})
#: PubMed's publication types for a notice rather than the work it is about.
PUBMED_NOTICES = frozenset({"Retraction of Publication", "Published Erratum"})
#: PubMed's publication types, from NLM's list (nlm.nih.gov/mesh/pubtypes.html, last
#: reviewed 2026-07-01), read for `number-from-secondary-source` exactly, GENERIC set aside:
#: it says nothing of the kind of work, since every article is a Journal Article and who
#: paid for it is no design. A work whose other types are all OPINION (an editorial, a
#: comment) reports what others measured: a warning. One whose other types are all
#: REVIEWED, Review among them, is a note: PubMed typed a systematic review as a Review
#: before it had a type for one. Any other type beside them (a letter, which may report data
#: of its own; a guideline; a systematic review, a meta-analysis or a study of any design)
#: says nothing (round 1 of #493).
OPINION = frozenset({"Editorial", "Comment"})
REVIEWED = OPINION | {"Review"}
GENERIC = frozenset({
    "Journal Article", "English Abstract", "Introductory Journal Article",
    "Research Support, American Recovery and Reinvestment Act",
    "Research Support, N.I.H., Extramural", "Research Support, N.I.H., Intramural",
    "Research Support, Non-U.S. Gov't", "Research Support, U.S. Gov't, Non-P.H.S.",
    "Research Support, U.S. Gov't, P.H.S.", "Research Support, U.S. Government",
    "Support of Research",
})  # fmt: skip
_PLACEHOLDER_PAGES = re.compile(
    r"\s*(?:e?0+(?:\s*-+\s*e?0+)?|in\s+press|forthcoming|[x?]+(?:\s*-+\s*[x?]+)?|n/?a|tb[ad])"
    r"\s*\.?\s*",
    re.IGNORECASE,
)
#: An HTML or MathML tag in a registered title. Taken out with nothing in its place: a tag
#: marks part of a word ("PM<sub>2.5</sub>", "<sup>18</sup>F-FDG"), and a space there
#: split it in two.
_TAGS = re.compile(r"<[^<>]*>")
#: A TeX command in a .bib title, read with its braces already gone (`literature/bibfile`):
#: `\c{c}` arrives as `\cc`, `PM\textsubscript{2.5}` as `PM\textsubscript2.5`.
_COMMAND = re.compile(r"\\([A-Za-z]+)\*?(\s?)")
#: An accent or a mark made of one sign (`\'e`, `\"u`, `\^o`): the letter after it stays.
_SIGN = re.compile(r"\\[^A-Za-z\s]")
#: Commands that are a letter of their own.
_LETTERS = {"ss": "ss", "o": "o", "O": "o", "i": "i", "j": "j", "l": "l", "L": "l",
            "aa": "a", "AA": "a", "ae": "ae", "AE": "ae", "oe": "oe", "OE": "oe"}  # fmt: skip
#: Commands named by one letter that put an accent on the letter after them; with the braces
#: gone that letter runs on in the command's name.
_ACCENTS = frozenset("cvuHkrdbt")
#: Commands that wrap text and leave it as it is.
_WRAPPERS = frozenset({
    "textsubscript", "textsuperscript", "emph", "textit", "textbf", "textsc", "textrm",
    "textsf", "texttt", "textup", "textnormal", "mathrm", "mathit", "mathbf", "mathsf",
    "mathcal", "mbox", "text", "it", "bf", "sc", "em", "rm", "nocase", "NoCaseChange",
})  # fmt: skip
#: What TeX maths writes around and inside a title's formula: `$^{18}$F` is "18F".
_MATHS = re.compile(r"[$^_]")


#: Greek letters by their command, as a registry prints them: `$\\beta$-lactam` is
#: "β-lactam". Read as an accent and the letters after it, `\\beta` was "eta". (Unicode
#: spells lambda without its b.)
_GREEK = {
    name: unicodedata.lookup(f"GREEK {'CAPITAL' if name[0].isupper() else 'SMALL'} LETTER "
                             f"{name.upper().replace('LAMBDA', 'LAMDA')}")
    for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota",
                 "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "tau", "upsilon",
                 "phi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi",
                 "Sigma", "Upsilon", "Phi", "Psi", "Omega")
} | {"varepsilon": "\N{GREEK SMALL LETTER EPSILON}", "vartheta": "\N{GREEK SMALL LETTER THETA}",
     "varphi": "\N{GREEK SMALL LETTER PHI}", "varrho": "\N{GREEK SMALL LETTER RHO}",
     "varsigma": "\N{GREEK SMALL LETTER SIGMA}"}  # fmt: skip
#: The commands known by name, longest first, so that `\\emph` is not read as `\\em`.
_KNOWN = sorted([*_WRAPPERS, *_LETTERS, *_GREEK], key=len, reverse=True)


def _untex(found: re.Match) -> str:
    """What a command leaves of the title. With the braces gone, the letters a command was
    given run on in its name (`\\ccaise`, `\\textsubscriptab`): a known name is read off
    the front and what follows it stays, and a one-letter accent leaves the letters after
    it. TeX takes the space after a command's name as part of it; where letters ran on,
    the space after them is the word's own and stays."""
    name, space = found.group(1), found.group(2)
    known = next((k for k in _KNOWN if name.startswith(k)), None)
    if known is not None:
        rest = _LETTERS.get(known, "") + _GREEK.get(known, "") + name[len(known) :]
    elif name[0] in _ACCENTS:
        rest = name[1:]
    else:
        return ""
    return rest + (space if name != known and len(name) > 1 else "")


def today() -> date:
    return date.today()


# --------------------------------------------------------------------------- the title


def _latin(character: str) -> bool:
    return unicodedata.name(character, "").startswith("LATIN")


def title_words(title: str) -> list[str] | None:
    """A title's words as they are compared: markup and TeX taken out, case and accents
    folded, British spellings read as American, no word dropped however short ("CT", "B").
    None for a title mostly in another script than Latin, which is not compared."""
    text = _MATHS.sub("", _SIGN.sub("", _COMMAND.sub(_untex, _TAGS.sub("", title))))
    text = unicodedata.normalize("NFKC", text)
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(map(_latin, letters)) * 2 < len(letters):
        return None
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    )
    variants, _ise = _variants()
    words = []
    for word in re.findall(r"[^\W_]+", folded):
        kind, instead = variants.get(word, ("", ""))
        words.append(instead.split("/")[0] if kind in ("gb", "ise") else word)
    return words


def title_held(cited: str, registered: str) -> float | None:
    """How much of the cited title the registered one holds, word for word. None where
    either is not compared."""
    mine, theirs = title_words(cited), title_words(registered)
    if not mine or theirs is None:
        return None
    return sum((Counter(mine) & Counter(theirs)).values()) / len(mine)


def _best(cited: str, candidates: list[str]) -> tuple[float, str] | None:
    """The registered title that holds most of the cited one, and how much."""
    scored = [(title_held(cited, c), c) for c in candidates if c]
    scored = [(held, c) for held, c in scored if held is not None]
    return max(scored) if scored else None


# --------------------------------------------------------------------------- the gate


def _finding(code: str, message: str, path: Path, hint: str, severity: str | None = None):
    extra = {"severity": severity} if severity else {}
    return Finding(gate=GATE, code=code, message=message, path=path, hint=hint, **extra)


def _read(project: Project, citekey: str) -> tuple[dict[str, Any] | None, Report]:
    path = record_path(project, citekey)
    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, Report((_finding("lookup-record-unreadable", str(exc), path, _REDO),))
    report = validate(document, "lookup", path, gate=GATE)
    if not report.ok:
        return None, report
    if document["citekey"] != citekey:
        message = f"the record for @{citekey} is the record of @{document['citekey']}"
        return None, Report((_finding("lookup-record-misfiled", message, path, _REDO),))
    try:
        date.fromisoformat(document["looked_up_on"])
    except ValueError:
        message = f"@{citekey}: the lookup date {document['looked_up_on']!r} is no date"
        return None, Report((_finding("lookup-record-unreadable", message, path, _REDO),))
    return document, Report()


_REDO = "run `manuscript-guard lookup --again` to write the record again"
#: Answers read for a work's types and links only, never for what is known of it, by the
#: words a message names them with.
_SIDE_ANSWERS = {"pubmed_by_doi": "PubMed by the DOI"}  # as `lookup` names it (run.py)


def check_lookups(project: Project, cited: list[str], literature: Any = None) -> Report:
    """Every cited reference, against its record; and, given the literature ledger, each
    value quoted from a work PubMed types only as an editorial or a comment, or as a review
    among those (a note); a letter is not judged."""
    from manuscript_guard.gates import searched

    bib = project.path("literature") / BIB_FILE
    entries = read_entries(bib) if bib.is_file() else {}
    raw = read_entries(bib, braces=True) if bib.is_file() else {}
    settings = project.setting("lookup") or {}
    excused: dict[str, str] = settings.get("cited_as_retracted") or {}
    not_indexed: dict[str, str] = settings.get("not_indexed") or {}
    max_age = settings.get("max_age_days") or MAX_AGE_DAYS
    report, missing, stale, looked = Report(), [], [], 0
    unchecked: list[str] = []
    for citekey in cited:
        fields = entries.get(citekey)
        if fields is None:
            continue  # `citation-unresolved` says so
        report = report.merge(_pages(citekey, fields, bib))
        identified = bool(doi_of(fields) or pmid_of(fields))
        if not identified:
            if fields.get("doi") or fields.get("pmid"):
                continue  # `identifier-malformed` says so
            why = (f"paper.yaml: {not_indexed[citekey]}" if citekey in not_indexed
                   else searched.unsearchable(fields))  # fmt: skip
            if why:
                unchecked.append(f"@{citekey} ({why})")
                continue
        if not record_path(project, citekey).exists():
            missing.append(citekey)
            continue
        record, problems = _read(project, citekey)
        report = report.merge(problems)
        if record is None:
            continue
        looked += 1
        if (today() - date.fromisoformat(record["looked_up_on"])).days > max_age:
            stale.append(citekey)
        cited_by = names.cited(raw.get(citekey, {}).get("author", ""))
        judged, why = _judge(project, citekey, fields, record, excused.get(citekey), cited_by)
        report = report.merge(judged)
        if why:
            unchecked.append(f"@{citekey} ({why})")
    report = report.merge(_unlooked(missing, stale, max_age, project))
    report = report.merge(_unchecked(unchecked, project))
    if literature is not None:
        report = report.merge(_secondary_sources(project, literature, entries))
    return report.with_counts(references_looked_up=looked)


def _unchecked(unchecked: list[str], project: Project) -> Report:
    if not unchecked:
        return Report()
    return Report((_finding(
        "reference-unchecked",
        f"{len(unchecked)} cited reference(s) with no DOI and no PMID could not be checked "
        "against a registry: " + ", ".join(unchecked),
        project.path("literature") / BIB_FILE,
        "give each an identifier in Zotero where it has one, or check it by hand",
        INFO,
    ),))  # fmt: skip


def _unlooked(missing: list[str], stale: list[str], max_age: int, project: Project) -> Report:
    found = []
    where = project.path("literature") / "lookups"
    if missing:
        found.append(
            _finding(
                "lookup-missing",
                f"{len(missing)} cited reference(s) were never looked up: "
                + ", ".join(f"@{k}" for k in missing),
                where,
                "run `manuscript-guard lookup` to ask the registries whether each exists, "
                "names the cited work and still stands; one with no identifier is searched "
                "for by its title",
                WARN,
            )
        )
    if stale:
        found.append(
            _finding(
                "lookup-stale",
                f"{len(stale)} reference(s) were looked up more than {max_age} days ago: "
                + ", ".join(f"@{k}" for k in stale),
                where,
                "a work can be retracted after it is cited; `manuscript-guard lookup "
                "--again` asks again",
                WARN,
            )
        )
    return Report(tuple(found))


def _pages(citekey: str, fields: dict[str, str], bib: Path) -> Report:
    pages = fields.get("pages", "")
    if not pages or not _PLACEHOLDER_PAGES.fullmatch(pages):
        return Report()
    return Report(
        (
            _finding(
                "pages-placeholder",
                f"@{citekey}: the pages are {pages!r}, which a reference list should not print",
                bib,
                "fill them in Zotero once the work is paginated, then `manuscript-guard "
                "sync-bib`",
                WARN,
            ),
        )
    )


def _judge(
    project: Project,
    citekey: str,
    fields: dict[str, str],
    record: dict[str, Any],
    excuse: str | None,
    cited: names.Authors | None = None,
) -> tuple[Report, str]:
    """What one record says of the reference it was written for, and why nothing could be
    said of a reference with no identifier, where nothing could."""
    from manuscript_guard.gates import searched

    path = record_path(project, citekey)
    cited = cited or names.Authors()
    if answers_digest(record) != record["answers_sha256"]:
        return Report(
            (
                _finding(
                    "lookup-record-edited",
                    f"@{citekey}: the record was changed after `lookup` wrote it",
                    path,
                    "what a registry said is not the author's to edit; " + _REDO,
                ),
            )
        ), ""
    found: list[Finding] = []
    looked_on = date.fromisoformat(record["looked_up_on"])
    if looked_on > today():
        found.append(
            _finding(
                "lookup-date-future",
                f"@{citekey}: looked up on {looked_on.isoformat()}, which has not come yet",
                path,
                _REDO,
            )
        )
    wanted = {k: v for k, v in (("doi", doi_of(fields)), ("pmid", pmid_of(fields))) if v}
    if entry_digest(fields) != record["entry_sha256"]:
        found.append(
            _finding(
                "lookup-entry-changed",
                f"@{citekey}: the entry changed in references.bib after it was looked up",
                path,
                "`manuscript-guard lookup` looks up a changed entry again",
                WARN,
            )
        )
        # A search was made by the entry's title, author and year: judged against the entry
        # as it is now, it would be held to words nobody searched for.
        if record["identifiers"] != wanted or not wanted:
            return Report(tuple(found)), ""
    answers = record["sources"]
    late = [name for name, answer in answers.items() if answer["status"] == "unresolvable"]
    if late:
        # Every registry silent: nothing is known of the reference, retracted or not. What
        # PubMed's search by DOI said counts for nothing here: it never says which work is
        # cited (round 1 of #493).
        asked = [name for name in answers if name not in _SIDE_ANSWERS]
        nothing = bool(asked) and all(name in late for name in asked)
        named = ", ".join(_SIDE_ANSWERS.get(name, name) for name in late)
        found.append(
            _finding(
                "lookup-unresolvable",
                f"@{citekey}: no answer from {named} when it was looked up"
                + (", so nothing is known of it" if nothing else ""),
                path,
                "`manuscript-guard lookup` asks again for an answer that did not come",
                WARN if nothing else INFO,
            )
        )
    if not wanted:
        verdict = searched.judge(citekey, fields, cited, record, path, excuse)
        return Report((*found, *verdict.findings)), verdict.unchecked
    found += _standing(citekey, fields, answers, path, excuse)
    found += _since(citekey, answers, path, record["looked_up_on"])
    found += _identity(citekey, fields, answers, path, excuse)
    # A record of version 1 kept no authors; every later one does.
    if record["schema"] != _NO_AUTHORS:
        found += _authors(citekey, fields, cited, answers, path, found)
    return Report(tuple(found)), ""


_NO_AUTHORS = "manuscript-guard/lookup/1"


def _authors(citekey, fields, cited, answers, path, found: list[Finding]) -> list[Finding]:
    """The cited people against the lists Crossref and PubMed keep for the identifiers' work.
    Not where the identifier names another work: its people are another work's."""
    from manuscript_guard.gates import authors

    if {f.code for f in found} & {"reference-title-mismatch", "pmid-names-another-work",
                                   "reference-not-the-work"}:  # fmt: skip
        return []
    lists = [(label, names.recorded(_found(answers, name).get("authors", [])))
             for name, label in (("crossref", "Crossref"), ("pubmed", "PubMed"))
             if _found(answers, name)]  # fmt: skip
    which = " and ".join(f"{k} {v}" for k, v in (("DOI", doi_of(fields)),
                                                 ("PMID", pmid_of(fields))) if v)  # fmt: skip
    return authors.judged(citekey, cited, lists, path, f"the work of its {which}")


def _found(answers: dict[str, Any], name: str) -> dict[str, Any]:
    answer = answers.get(name) or {}
    return answer if answer.get("status") == "found" else {}


# ------------------------------------------------------- what PubMed links the work to


def _retracted_in(pubmed: dict[str, Any]) -> bool:
    """PubMed says the work is retracted: by its type, or by its link to the notice."""
    return "Retracted Publication" in pubmed.get("pubtypes", []) or any(
        link["type"] == "Retraction in" for link in pubmed.get("links", [])
    )


def _links(answers: dict[str, Any], kind: str) -> list[tuple[str, dict[str, str]]]:
    """PubMed's links of one kind from the work, each with where it was read: the record of
    the entry's PMID, or of the PMID PubMed gives its DOI."""
    by_doi = _found(answers, "pubmed_by_doi")
    read = [("PubMed's `references`", _found(answers, "pubmed")),
            (f"PubMed's `references` for PMID {by_doi.get('pmid')}, found by the DOI", by_doi)]
    return [(label, link) for label, said in read for link in said.get("links", [])
            if link["type"] == kind]  # fmt: skip


def _pointed(link: dict[str, str]) -> str:
    """Where a link points: " PMID 123 (N Engl J Med. 2021 ...)"."""
    pmid = f" PMID {link['pmid']}" if link.get("pmid") else ""
    return pmid + (f" ({link['reference']})" if link.get("reference") else "")


def _a(kind: str) -> str:
    """A kind of notice with its article, chosen by its first letter, which suits every one
    of Crossref's kinds: "an erratum", "an addendum", "a correction" (round 1 of #493)."""
    return ("an " if kind[:1].lower() in "aeiou" else "a ") + kind


def _since(citekey: str, answers: dict[str, Any], path: Path, looked_on: str) -> list[Finding]:
    """What came after the work: a later version or edition of it (a warning, as a preprint
    published since is), a correction of it (a note). Read from Crossref's `updated_by`
    only: a DOI whose `update_to` names another is itself the notice, and that is
    `reference-not-the-work`. Each says the registry, the field and the day it was read."""
    notices = _found(answers, "crossref").get("updated_by", [])
    found = []
    for code, kinds, kind, severity, said, hint in (
        ("reference-updated", UPDATING, "Update in", WARN, "has a later version",
         "cite the latest version, and check that what is cited from it is still in it"),
        ("reference-corrected", CORRECTING, "Erratum in", INFO, "has been corrected",
         "read the correction, and check that what is cited is not what it corrects"),
    ):  # fmt: skip
        where = [
            f"Crossref's `updated-by` lists {_a(n['type'].replace('_', ' '))}"
            + (f" (doi:{n['doi']}{', ' + n['date'] if n.get('date') else ''})"
               if n.get("doi") else "")
            for n in notices if n["type"] in kinds
        ]  # fmt: skip
        where += [f'{label} lists "{kind}"{_pointed(link)}' for label, link in
                  _links(answers, kind)]  # fmt: skip
        if where:
            found.append(_finding(
                code, f"@{citekey} {said}: {'; '.join(where)}; looked up on {looked_on}",
                path, hint, severity,
            ))  # fmt: skip
    return found


# ------------------------------------------------------- the kind of work cited


def _types_of(record: dict[str, Any]) -> tuple[tuple[str, ...], str, bool] | None:
    """The work's PubMed publication types, the PMID whose record gives them, and whether
    that PMID is the one PubMed gives the DOI rather than the entry's own."""
    answers = record.get("sources") or {}
    for name in ("pubmed", "pubmed_by_doi"):
        said = _found(answers, name)
        if said.get("pubtypes"):
            pmid = said.get("pmid") or record.get("identifiers", {}).get("pmid", "")
            return tuple(said["pubtypes"]), pmid, name == "pubmed_by_doi"
    return None


def publication_types(record: dict[str, Any]) -> tuple[str, ...] | None:
    """PubMed's publication types for the work a lookup record is of: from the record of
    the entry's PMID, else from that of the PMID PubMed gives the entry's DOI
    (`pubmed_by_doi`). None where PubMed was not asked, did not find it, or lists no type.
    The record is taken as read: whether it is sealed and still the entry's is the
    caller's to hold."""
    typed = _types_of(record)
    return typed[0] if typed else None


def secondary(types: tuple[str, ...] | list[str]) -> str | None:
    """How a number quoted from a work of these PubMed types is said, from the types beside
    the generic ones: `WARN` where all are an editorial or a comment (`OPINION`), `INFO`
    where all are a review, an editorial or a comment and one is a review (`REVIEWED`), and
    None for anything else, a letter included."""
    kinds = set(types) - GENERIC
    if kinds and kinds <= OPINION:
        return WARN
    if "Review" in kinds and kinds <= REVIEWED:
        return INFO
    return None


def _sealed(project: Project, citekey: str, fields: dict[str, str] | None) -> dict | None:
    """A citekey's record where it can be read, is as `lookup` wrote it, and was looked up
    by the identifiers the entry has now; None otherwise, and whatever stands in the way
    is said where the reference is cited."""
    if fields is None or not record_path(project, citekey).exists():
        return None
    record, _problems = _read(project, citekey)
    if record is None or answers_digest(record) != record["answers_sha256"]:
        return None
    wanted = {k: v for k, v in (("doi", doi_of(fields)), ("pmid", pmid_of(fields))) if v}
    return record if wanted and record["identifiers"] == wanted else None


def currency_facts(project: Project, citekey: str, fields: dict[str, str] | None) -> list[str]:
    """What the lookup record of `citekey` says has come after the work, in words: what
    gives `reference-updated` (a later version or edition at Crossref, an "Update in" at
    PubMed) or `preprint-published`. Its citations are then in the scope of reference
    currency (`gates/currency.py`). Nothing where the record is not sealed as `lookup` wrote
    it or not of the identifiers the entry has now, as `number-from-secondary-source` reads
    one."""
    record = _sealed(project, citekey, fields)
    if record is None:
        return []
    answers = record.get("sources") or {}
    crossref = _found(answers, "crossref")
    said = []
    if any(n["type"] in UPDATING for n in crossref.get("updated_by", [])) \
            or _links(answers, "Update in"):  # fmt: skip
        said.append(f"has a later version (looked up on {record['looked_up_on']})")
    if crossref.get("type") == "posted-content" and crossref.get("preprint_of"):
        published = ", ".join(f"doi:{d}" for d in crossref["preprint_of"])
        said.append(f"is a preprint published since as {published} (looked up on "
                    f"{record['looked_up_on']})")  # fmt: skip
    return said


def values_quoted_from(literature: Any) -> dict[str, list[Any]]:
    """The values of the literature ledger and of attested.yaml, by the citekey of the work
    each is quoted from, in the order of their keys. Read so for `number-from-secondary-
    source` and for reference currency's K5 (`gates/currency.py`)."""
    by_work: dict[str, list[Any]] = {}
    for _key, value in sorted(literature.values.items()):
        citekey = str((value.detail or {}).get("citekey") or "").strip()
        if citekey:
            by_work.setdefault(citekey, []).append(value)
    return by_work


def _secondary_sources(project: Project, literature: Any,
                       entries: dict[str, dict[str, str]]) -> Report:  # fmt: skip
    """`number-from-secondary-source`: a value of the literature ledger, or of attested.yaml,
    quoted from a work PubMed types only as an editorial or a comment (a warning) or as a
    review (a note; `secondary`), one finding per work. A work with no type known says
    nothing."""
    by_work = values_quoted_from(literature)
    found = []
    for citekey, values in by_work.items():
        record = _sealed(project, citekey, entries.get(citekey))
        typed = _types_of(record) if record else None
        severity = secondary(typed[0]) if typed else None
        if severity is None:
            continue
        types, pmid, by_doi = typed
        shown = ", ".join(t for t in types if t not in GENERIC)
        whose = f"PMID {pmid}" + (", which PubMed gives its DOI" if by_doi else "")
        keys = ", ".join(f"lit.{v.key}" for v in values)
        said = ("a work that reports what other studies measured" if severity == WARN else
                "most such works report what other studies measured, though a work typed "
                "only as a review may be a systematic review indexed before PubMed had a "
                "type for one")  # fmt: skip
        found.append(Finding(
            gate=GATE, code="number-from-secondary-source", severity=severity,
            message=f"{keys}: quoted from @{citekey}, which PubMed types as {shown} "
            f"(`pubtype` of {whose}, looked up on {record['looked_up_on']}): {said}",
            path=values[0].source,
            hint="quote the value from the study that measured it, or from a systematic "
            "review or meta-analysis, and cite that work; PubMed's types are its "
            "indexers'",
        ))  # fmt: skip
    return Report(tuple(found))


def _standing(citekey, fields, answers, path, excuse) -> list[Finding]:
    """Retracted, withdrawn, under concern, published since."""
    crossref, openalex, pubmed = (_found(answers, n) for n in ("crossref", "openalex", "pubmed"))
    preprint = crossref.get("type") == "posted-content"
    notices = crossref.get("updated_by", [])
    retracting = [n for n in notices if n["type"] in RETRACTING]
    withdrawn_preprint = bool(
        preprint and retracting and all(n["type"] == "withdrawal" for n in retracting)
    )
    by_doi = _found(answers, "pubmed_by_doi")
    said_by = [
        *(["Crossref"] if retracting and not withdrawn_preprint else []),
        *(["OpenAlex"] if openalex.get("is_retracted") is True else []),
        *(["PubMed"] if _retracted_in(pubmed) else []),
        *([f"PubMed (PMID {by_doi.get('pmid')}, found by the DOI)"]
          if _retracted_in(by_doi) else []),
    ]  # fmt: skip
    found = []
    if said_by:
        notice = next((n for n in retracting if n.get("doi")), None)
        detail = ""
        if notice:
            dated = f", {notice['date']}" if notice.get("date") else ""
            detail = f" (notice doi:{notice['doi']}{dated})"
        if excuse:
            found.append(_finding(
                "reference-retracted-cited",
                f"@{citekey} is retracted{detail}, and cited knowingly: {excuse}",
                path, "paper.yaml, `lookup.cited_as_retracted`", INFO,
            ))  # fmt: skip
        else:
            found.append(_finding(
                "reference-retracted",
                f"@{citekey} is retracted, by what {' and '.join(said_by)} say{detail}",
                path,
                "cite other evidence; where the paper discusses the retracted work itself, "
                f"say why under `lookup.cited_as_retracted` in paper.yaml ({citekey}: <why>)",
            ))  # fmt: skip
    if withdrawn_preprint:
        found.append(_finding(
            "preprint-withdrawn", f"@{citekey} is a preprint its server has withdrawn",
            path, "cite the published version if there is one, or other evidence", WARN,
        ))  # fmt: skip
    concerns = sorted({n["type"].replace("_", " ") for n in notices if n["type"] in CONCERNING})
    # PubMed's own link to an expression of concern, said with where it was read.
    linked = [f"PubMed's \"Expression of concern in\"{_pointed(link)}"
              for _label, link in _links(answers, "Expression of concern in")]  # fmt: skip
    if concerns or linked:
        found.append(_finding(
            "reference-under-concern",
            f"@{citekey} carries a notice: {', '.join([*concerns, *linked])}",
            path, "read the notice before relying on the work", WARN,
        ))  # fmt: skip
    if preprint and crossref.get("preprint_of"):
        published = ", ".join(f"doi:{d}" for d in crossref["preprint_of"])
        found.append(_finding(
            "preprint-published",
            f"@{citekey} is a preprint, published since as {published}",
            path, "cite the published version, and check that what is cited is still in it",
            WARN,
        ))  # fmt: skip
    return found


def _identity(citekey, fields, answers, path, excuse) -> list[Finding]:
    """Whether the identifiers name the work the entry describes."""
    crossref, datacite, pubmed = (_found(answers, n) for n in ("crossref", "datacite", "pubmed"))
    found: list[Finding] = []
    absent = [answers.get(n, {}).get("status") == "absent" for n in ("crossref", "datacite",
                                                                      "doi_org")]  # fmt: skip
    if "crossref" in answers and all(absent):
        found.append(_finding(
            "doi-unregistered",
            f"@{citekey}: no registry has the DOI {doi_of(fields)}: not Crossref, not "
            "DataCite, not doi.org",
            path, "correct the DOI in Zotero, then `manuscript-guard sync-bib`",
        ))  # fmt: skip
    if answers.get("pubmed", {}).get("status") == "absent":
        found.append(_finding(
            "pmid-unknown",
            f"@{citekey}: PubMed has no PMID {pmid_of(fields)}",
            path, "correct the PMID in Zotero, then `manuscript-guard sync-bib`",
        ))  # fmt: skip
    not_the_work = _not_the_work(fields, crossref, pubmed)
    if not_the_work and not excuse:
        found.append(_finding(
            "reference-not-the-work", f"@{citekey}: {not_the_work}", path,
            "cite the work itself; where the paper means to cite the notice, say why under "
            "`lookup.cited_as_retracted` in paper.yaml",
        ))  # fmt: skip
    title = fields.get("title", "")
    registered = crossref or datacite or (pubmed if not doi_of(fields) else {})
    candidates = [
        " ".join(filter(None, (registered.get("title"), registered.get("subtitle")))),
        registered.get("original_title", ""),
    ]
    # PubMed's title of the same work, where PubMed gives it the entry's own DOI: the English
    # title of a paper Crossref registered in another language (round 1 of #253: PubMed was
    # no candidate where Crossref had answered).
    if registered is not pubmed and pubmed.get("doi") and pubmed.get("doi") == doi_of(fields):
        candidates.append(pubmed.get("title", ""))
    best = _best(title, candidates) if title and registered else None
    # A guideline cited with its task force in its title, which the registries leave out,
    # is the registered title still (Basile, 2026-10-21; `gates/searched`).
    from manuscript_guard.gates.searched import subtitle_left_out

    if best and best[0] < TITLE_HELD and not any(
        subtitle_left_out(title, c) for c in candidates if c
    ):
        found.append(_finding(
            "reference-title-mismatch",
            f"@{citekey}: the identifier names {best[1]!r}, which holds {best[0]:.0%} of the "
            f"cited title's words",
            path, "the identifier or the title is another work's: correct the entry in Zotero",
        ))  # fmt: skip
    if pubmed and doi_of(fields):
        found += _pmid_and_doi(citekey, fields, pubmed, path)
    found += _year(citekey, fields, crossref, datacite, pubmed, path)
    found += _details(citekey, fields, crossref, path)
    return found


def _not_the_work(fields, crossref, pubmed) -> str:
    kind = fields.get("type", "").lower()
    notices = [n for n in crossref.get("update_to", []) if n["type"] in NOTICES]
    if notices:
        notice = notices[0]
        about = f" for doi:{notice['doi']}" if notice.get("doi") else ""
        return f"the DOI is a {notice['type'].replace('_', ' ')} notice{about}, not the work"
    registered = crossref.get("type", "")
    if registered in SERIES or registered == "component" or (
        registered in VOLUMES and kind not in CITES_A_VOLUME
    ):
        return f"the DOI is a {registered.replace('-', ' ')}, not one work in it"
    notices = sorted(PUBMED_NOTICES & set(pubmed.get("pubtypes", [])))
    if notices:
        return f"the PMID is a notice ({', '.join(notices)}), not the work"
    return ""


def _pmid_and_doi(citekey, fields, pubmed, path) -> list[Finding]:
    doi = doi_of(fields)
    if pubmed.get("doi"):
        if pubmed["doi"] == doi:
            return []
        said = f"PubMed gives PMID {pmid_of(fields)} the DOI {pubmed['doi']}, not {doi}"
    else:
        best = _best(fields.get("title", ""), [pubmed.get("title", "")])
        if not best or best[0] >= TITLE_HELD:
            return []
        said = f"the PMID names {best[1]!r}, another title than the entry's"
    return [_finding(
        "pmid-names-another-work", f"@{citekey}: {said}", path,
        "the PMID or the DOI is another work's: correct the entry in Zotero",
    )]  # fmt: skip


def _cited_year(fields: dict[str, str]) -> int | None:
    found = re.match(r"\s*(\d{4})\b", fields.get("year") or fields.get("date") or "")
    return int(found.group(1)) if found else None


def _year(citekey, fields, crossref, datacite, pubmed, path) -> list[Finding]:
    cited = _cited_year(fields)
    years = (
        list(crossref.get("years", {}).values())
        or [y for y in (datacite.get("year"),) if y]
        or [y for y in (pubmed.get("year"),) if y]
    )
    if cited is None or not years or any(abs(cited - y) <= YEAR_SLACK for y in years):
        return []
    shown = ", ".join(str(y) for y in sorted(set(years)))
    return [_finding(
        "reference-year-mismatch",
        f"@{citekey}: cited as {cited}, and the identifier's work is of {shown}",
        path, "the year or the identifier is another work's: correct the entry in Zotero",
    )]  # fmt: skip


def _first_page(pages: str) -> str:
    return re.split(r"\s*[-\u2013\u2014]+\s*", pages.strip(), maxsplit=1)[0].casefold()


def _details(citekey, fields, crossref, path) -> list[Finding]:
    """Volume and first page or article number, a warning: they are mistyped more often
    than the work is another (an article number "101880T" copied as "1018807")."""
    if not crossref:
        return []
    differ = []
    volume, registered = fields.get("volume", "").strip(), crossref.get("volume", "")
    if volume and registered and volume.casefold() != registered.strip().casefold():
        differ.append(f"volume {volume}, registered {registered}")
    cited = _first_page(fields.get("pages", "") or fields.get("eid", ""))
    known = [p for p in (_first_page(crossref.get("page", "")),
                         crossref.get("article_number", "").casefold()) if p]  # fmt: skip
    if cited and known and cited not in known:
        differ.append(f"first page or number {cited}, registered {' or '.join(known)}")
    if not differ:
        return []
    return [_finding(
        "reference-details-differ", f"@{citekey}: " + "; ".join(differ), path,
        "correct the entry in Zotero if the registry is right", WARN,
    )]  # fmt: skip


__all__ = [
    "CORRECTING",
    "GENERIC",
    "MAX_AGE_DAYS",
    "OPINION",
    "REVIEWED",
    "TITLE_HELD",
    "UPDATING",
    "check_lookups",
    "publication_types",
    "secondary",
    "title_held",
    "title_words",
    "today",
]
