"""G7, offline: each reference's identifiers are well formed, and its fields are there.

What can be known of `references.bib` without asking anyone: whether a DOI has the shape of
one, a PMID is digits, a PMCID is "PMC" and digits, an ISBN's check digit is right, an arXiv
identifier has one of its two forms, and whether an entry has the fields its type needs to be
printed (an article its journal, a thesis its school), or takes them from the entry its
`crossref` names. It runs in CI, needs no network and reads the committed file, so it means
the same on every machine.

Whether a well-formed DOI is registered, names the work the entry describes, or has been
retracted is another question, for a lookup that records what it found.
"""

from __future__ import annotations

import re

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import Finding, Report
from manuscript_guard.literature.bibfile import read_entries

GATE = "G7"
BIB_FILE = "references.bib"

#: A DOI as Crossref and DataCite issue them: the directory "10.", a registrant code of
#: four to nine digits (dotted subcodes allowed), a slash, and a suffix with no space.
_DOI = re.compile(r"10\.\d{4,9}(?:\.\d+)*/\S+")
#: What a DOI is often written with: a scheme, with its colon or a space after it, a
#: resolver, with its scheme or without and with `www.` or `dx.` (round 1 of #249), a
#: trailing stop. The resolver is tried first, so that the "doi" of "doi.org/" is not taken
#: for the scheme; "doi10." has lost its colon and is left as it is (round 1 of #345).
_DOI_DRESSING = re.compile(
    r"^(?:(?:https?://)?(?:www\.|dx\.)?doi\.org/|doi(?:\s*:\s*|\s+))", re.IGNORECASE
)
_PMID = re.compile(r"\d{1,9}")
_PMCID = re.compile(r"PMC\d{1,9}", re.IGNORECASE)
#: arXiv's two forms: "2101.01234v2" since 2007, "hep-th/9901001" before.
_ARXIV = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?")

#: The fields an entry of each type needs in both formats a `.bib` file is written in: what
#: BibTeX's standard styles require (btxdoc, "Entry Types") and BibLaTeX's also require (its
#: manual, section 2.1.1), under either's name. `sync-bib` writes BibLaTeX, and BibLaTeX asks
#: no publisher of a book or a collection's chapter and no note of an unpublished work, so
#: those are not required here. Each tuple is one field, any of whose names will do. A book
#: or a part of one with editors and no author passes, as BibTeX has it, though BibLaTeX asks
#: for an author (round 2 of #249).
REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    "article": (("author",), ("title",), ("journal", "journaltitle"), ("year", "date")),
    "book": (("author", "editor"), ("title",), ("year", "date")),
    "inbook": (("author", "editor"), ("title",), ("year", "date")),
    "incollection": (("author",), ("title",), ("booktitle",), ("year", "date")),
    "inproceedings": (("author",), ("title",), ("booktitle",), ("year", "date")),
    "conference": (("author",), ("title",), ("booktitle",), ("year", "date")),
    "mastersthesis": (("author",), ("title",), ("school", "institution"), ("year", "date")),
    "phdthesis": (("author",), ("title",), ("school", "institution"), ("year", "date")),
    "techreport": (("author",), ("title",), ("institution",), ("year", "date")),
    "proceedings": (("title",), ("year", "date")),
    "manual": (("title",),),
    "booklet": (("title",),),
    "unpublished": (("author",), ("title",)),
}  # fmt: skip


def normal_doi(written: str) -> str:
    """A DOI without the scheme, the resolver or the stop it is often written with."""
    return _DOI_DRESSING.sub("", written.strip()).rstrip(".").strip()


def isbn_valid(written: str) -> bool:
    """Whether an ISBN-10 or ISBN-13, hyphens and spaces aside, has the right check digit."""
    digits = re.sub(r"[\s-]", "", written).upper()
    if re.fullmatch(r"\d{9}[\dX]", digits):
        total = sum((10 - at) * (10 if d == "X" else int(d)) for at, d in enumerate(digits))
        return total % 11 == 0
    if re.fullmatch(r"\d{13}", digits):
        total = sum(int(d) * (1 if at % 2 == 0 else 3) for at, d in enumerate(digits))
        return total % 10 == 0
    return False


def doi_of(fields: dict[str, str]) -> str | None:
    """An entry's DOI as it is looked up: well formed, undressed, in lower case (a DOI is
    matched without regard to case). None where it has none, or one G7 says is malformed."""
    doi = normal_doi(fields.get("doi", ""))
    return doi.lower() if doi and _DOI.fullmatch(doi) else None


def pmid_of(fields: dict[str, str]) -> str | None:
    """An entry's PMID, where it has a well-formed one, in either place it is written."""
    eprinttype = (fields.get("eprinttype") or fields.get("archiveprefix") or "").lower()
    pmid = fields.get("pmid", "").strip() or (
        fields.get("eprint", "").strip() if eprinttype == "pubmed" else ""
    )
    return pmid if pmid and _PMID.fullmatch(pmid) else None


#: What an ISBN field holds beside its numbers: a label, "ISBN-13", "ISBN 13:", "e-ISBN" or
#: "eISBN"; a qualifier in brackets; and the qualifiers written without them, "pbk." (round 2
#: of #249: each stuck to the ISBN beside it). A "10" or "13" after the label is the label's
#: only where no digit follows it, so an ISBN-10 that opens "13" keeps them.
_ISBN_ASIDE = re.compile(
    r"\b(?:e-?)?ISBN(?:[-\s]?1[03](?!\d))?\s*:?|\([^()]*\)"
    r"|\b(?:pbk|hbk|paperback|hardback|hardcover|softcover|cloth|print|online|electronic"
    r"|e-?book)\b\.?",
    re.IGNORECASE,
)


def _isbn_length(written: str) -> int:
    return len(re.sub(r"[\s-]", "", written))


def _isbns(field: str) -> list[str]:
    """The ISBNs of one field, which may hold several: parted by commas, semicolons or
    slashes, or by spaces, which can also part the groups of one ISBN ("978 0 306 40615
    7"). Words are joined until they make ten or thirteen characters. Ten is an ISBN-10
    unless the run opens as an ISBN-13 does, with 978 or 979, and enough follows to make
    thirteen: an ISBN-13 is not cut after its tenth character."""
    found: list[str] = []
    for part in re.split(r"[,;/]", _ISBN_ASIDE.sub(" ", field)):
        words = part.split()
        run: list[str] = []
        for at, word in enumerate(words):
            run.append(word)
            compact = re.sub(r"[\s-]", "", "".join(run))
            longer = _isbn_length("".join(run + words[at + 1 :]))
            thirteen_to_come = compact[:3] in ("978", "979") and longer >= 13
            if len(compact) == 13 or (len(compact) == 10 and not thirteen_to_come):
                found.append(" ".join(run))
                run = []
        if run:
            found.append(" ".join(run))
    return found


def problems(
    key: str, fields: dict[str, str], parent: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """What is wrong with one entry: each as a code and a sentence. `parent` is the entry its
    `crossref` names, whose fields it takes where it gives none of its own."""
    found: list[tuple[str, str]] = []

    def malformed(kind: str, value: str, why: str) -> None:
        found.append(("identifier-malformed", f"@{key}: the {kind} {value!r} {why}"))

    doi = fields.get("doi", "").strip()
    if doi and not _DOI.fullmatch(normal_doi(doi)):
        malformed("DOI", doi, 'is not "10.", a registrant code, a slash and a suffix')
    eprinttype = (fields.get("eprinttype") or fields.get("archiveprefix") or "").lower()
    pmid = fields.get("pmid", "").strip() or (
        fields.get("eprint", "").strip() if eprinttype == "pubmed" else ""
    )
    if pmid and not _PMID.fullmatch(pmid):
        malformed("PMID", pmid, "is not a number")
    pmcid = fields.get("pmcid", "").strip() or (
        fields.get("eprint", "").strip() if eprinttype == "pmc" else ""
    )
    if pmcid and not _PMCID.fullmatch(pmcid):
        malformed("PMCID", pmcid, 'is not "PMC" and a number')
    arxiv = fields.get("eprint", "").strip() if eprinttype == "arxiv" else ""
    if arxiv and not _ARXIV.fullmatch(re.sub(r"(?i)^arxiv:", "", arxiv)):
        malformed("arXiv identifier", arxiv, 'has neither of its forms, "2101.01234" or '
                  '"hep-th/9901001"')  # fmt: skip
    isbns = _isbns(fields.get("isbn", ""))
    for isbn in isbns:
        if not isbn_valid(isbn):
            malformed("ISBN", isbn.strip(), "has a check digit that does not add up")
    # A field of labels and qualifiers alone, "online", holds none (round 1 of #345); one
    # with a digit in it may hold an ISBN set aside in brackets, and is left as it was.
    written = fields.get("isbn", "").strip()
    if written and not any(isbn.strip() for isbn in isbns) and not re.search(r"\d", written):
        malformed("ISBN", written, "holds no ISBN, only what is written beside one")

    kind = fields.get("type", "").lower()
    given = {**inherited(parent), **{name: v for name, v in fields.items() if v.strip()}}
    for names in REQUIRED.get(kind, ()):
        if not any(given.get(name, "").strip() for name in names):
            found.append(
                (
                    "reference-field-missing",
                    f"@{key}: an @{kind} entry needs its {' or '.join(names)}, and has "
                    "none",
                )
            )
    return found


#: What a part does not take from the work that holds it: the parent's title, which becomes
#: the part's `booktitle` and is not its title (round 1 of #345: a paper with no title of
#: its own took the proceedings' name for one), and what names the parent's own entry.
NOT_INHERITED = (
    "title", "subtitle", "titleaddon", "shorttitle", "type", "type_field", "crossref", "xref",
    "ids", "entryset", "label", "shorthand", "sortkey",
)  # fmt: skip


def inherited(parent: dict[str, str] | None) -> dict[str, str]:
    """What an entry takes from the one its `crossref` names: every field it lacks but the
    title, as biber inherits from a book, a collection or proceedings (BibLaTeX's manual,
    appendix B), the author of a book given to its chapter (round 2 of #345); and the
    parent's title as its `booktitle`, which BibTeX's parent writes itself (round 1 of #249:
    a hand-written `@inproceedings` was told it had no booktitle)."""
    if not parent:
        return {}
    fields = {name: value for name, value in parent.items() if name not in NOT_INHERITED}
    if parent.get("title", "").strip() and not fields.get("booktitle", "").strip():
        fields["booktitle"] = parent["title"]
    return fields


def parent_of(fields: dict[str, str], entries: dict[str, dict[str, str]]) -> dict | None:
    """The entry `fields` names in its `crossref`, matched exactly, as biber matches keys
    (round 1 of #345: a key in other capitals was taken for it, and the build does not).
    None where it names none, or one the file does not hold."""
    named = fields.get("crossref", "").strip()
    return entries.get(named) if named else None


def check_identifiers(project: Project) -> Report:
    """Every entry of the committed `references.bib`, cited or not."""
    path = project.path("literature") / BIB_FILE
    if not path.is_file():
        return Report().with_counts(references_read=0)
    entries = read_entries(path)
    report = Report()
    for key, fields in sorted(entries.items()):
        for code, message in problems(key, fields, parent_of(fields, entries)):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code=code,
                    message=message,
                    path=path,
                    hint=_HINTS[code],
                )
            )
    return report.with_counts(references_read=len(entries))


_HINTS = {
    "identifier-malformed": "correct it in Zotero, then `manuscript-guard sync-bib`; a "
    "mistyped identifier sends a reader, and any lookup, to another work or to none",
    "reference-field-missing": "fill the field in Zotero, then `manuscript-guard sync-bib`: "
    "the reference list prints the entry without it",
}


__all__ = [
    "REQUIRED",
    "check_identifiers",
    "doi_of",
    "inherited",
    "isbn_valid",
    "normal_doi",
    "parent_of",
    "pmid_of",
    "problems",
]
