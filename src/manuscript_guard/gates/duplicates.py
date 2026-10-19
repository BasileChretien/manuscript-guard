"""G7: one work is cited under one key.

Two cited entries of `references.bib` with the same DOI, PMID, PMCID or ISBN are one work,
and the reference list prints it twice, numbered twice. Nothing caught it: G7 knew a key
that resolves to several items in Zotero, not two keys that resolve to one work. Read from
the committed file, so it means the same in CI as with Zotero open.

Each identifier is compared as it names the work, not as it is written: a DOI undressed and
in lower case, a PMID without leading noughts, a PMCID in capitals, an ISBN-10 as the
ISBN-13 it is. Two entries with the same title and no identifier in common may be one work
too, or a correction and the paper it corrects, so that is a warning.

An ISBN names a book, and a chapter or a conference paper can carry the book's ISBN or its
DOI: two chapters of one book are two works. So a part of a book is compared by its title
alone, and an ISBN is read only where the entry is a whole book, with its volume.
"""

from __future__ import annotations

import re
import unicodedata

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.identifiers import _DOI, _PMCID, _PMID, _isbns, isbn_valid, normal_doi
from manuscript_guard.literature.bibfile import read_entries

GATE = "G7"
BIB_FILE = "references.bib"
#: A title shorter than this, "Editorial" or "Correction", is shared by works that differ.
TITLE_WORDS = 4
#: Entry types that are part of a book: what they carry can name the book.
PARTS = frozenset(
    {"bookinbook", "conference", "inbook", "incollection", "inproceedings", "inreference",
     "suppbook", "suppcollection"}
)  # fmt: skip
#: Entry types that are a whole book, the only ones whose ISBN names what is cited.
BOOKS = frozenset(
    {"book", "booklet", "collection", "manual", "mastersthesis", "mvbook", "mvcollection",
     "mvproceedings", "mvreference", "phdthesis", "proceedings", "reference", "report",
     "techreport", "thesis"}
)  # fmt: skip


def isbn_13(written: str) -> str:
    """An ISBN as the thirteen digits that name its book: an ISBN-10 is the ISBN-13 that
    opens with 978, with the check digit worked out again."""
    digits = re.sub(r"[\s-]", "", written).upper()
    if len(digits) == 13:
        return digits
    body = "978" + digits[:9]
    check = (10 - sum(int(d) * (1 if at % 2 == 0 else 3) for at, d in enumerate(body)) % 10) % 10
    return body + str(check)


def identifiers_of(fields: dict[str, str]) -> set[tuple[str, str]]:
    """Each identifier an entry names its work by, as the work is named. None for a part of
    a book, and an ISBN only for a whole book, with the volume where it gives one."""
    found: set[tuple[str, str]] = set()
    kind = fields.get("type", "").lower()
    if kind in PARTS:
        return found
    doi = normal_doi(fields.get("doi", ""))
    if doi and _DOI.fullmatch(doi):
        found.add(("DOI", doi.lower()))
    eprinttype = (fields.get("eprinttype") or fields.get("archiveprefix") or "").lower()
    pmid = fields.get("pmid", "").strip() or (
        fields.get("eprint", "").strip() if eprinttype == "pubmed" else ""
    )
    if pmid and _PMID.fullmatch(pmid):
        found.add(("PMID", str(int(pmid))))
    pmcid = fields.get("pmcid", "").strip() or (
        fields.get("eprint", "").strip() if eprinttype == "pmc" else ""
    )
    if pmcid and _PMCID.fullmatch(pmcid):
        found.add(("PMCID", "PMC" + str(int(pmcid[3:]))))
    volume = _volume(fields.get("volume", ""))
    for isbn in _isbns(fields.get("isbn", "") if kind in BOOKS else ""):
        if isbn_valid(isbn):
            found.add(("ISBN", isbn_13(isbn) + (f", volume {volume}" if volume else "")))
    return found


#: The word a volume is often written with: "Vol. 1", "Volume 1", "v. 1".
_VOLUME_WORD = re.compile(r"^(?:vol(?:ume)?\.?|v\.)\s*", re.IGNORECASE)


def _volume(written: str) -> str:
    """A volume as it names a book's part: without the word it is written with, so that "1"
    and "Vol. 1" are one volume (round 2 of #261: they were two, and one book cited twice
    was not found)."""
    return _VOLUME_WORD.sub("", " ".join(written.split())).casefold()


def title_of(fields: dict[str, str]) -> str | None:
    """A title as it is compared: case, accents and punctuation folded. None for one too
    short to say two entries are one work."""
    folded = "".join(
        c
        for c in unicodedata.normalize("NFKD", fields.get("title", "").casefold())
        if not unicodedata.combining(c)
    )
    words = re.findall(r"[^\W_]+", folded)
    return " ".join(words) if len(words) >= TITLE_WORDS else None


def _keys(keys: list[str]) -> str:
    return " and ".join(f"@{key}" for key in keys)


def check_duplicates(project: Project, cited: set[str]) -> Report:
    """Cited entries that are one work: by an identifier, a failure; by title alone, a
    warning."""
    path = project.path("literature") / BIB_FILE
    if not path.is_file() or not cited:
        return Report()
    entries = {key: fields for key, fields in read_entries(path).items() if key in cited}
    by_identifier: dict[tuple[str, str], list[str]] = {}
    by_title: dict[str, list[str]] = {}
    for key, fields in sorted(entries.items()):
        for named in identifiers_of(fields):
            by_identifier.setdefault(named, []).append(key)
        title = title_of(fields)
        if title:
            by_title.setdefault(title, []).append(key)
    report = Report()
    same_work: set[frozenset[str]] = set()
    for (kind, value), keys in sorted(by_identifier.items()):
        if len(keys) < 2 or frozenset(keys) in same_work:
            continue
        same_work.add(frozenset(keys))
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="reference-duplicate",
                message=f"{_keys(keys)} are one work, by the same {kind} ({value}), and the "
                "reference list prints it once for each",
                path=path,
                hint="keep one item in Zotero and cite it by its key alone (Zotero's "
                "Duplicate Items merges them), then `manuscript-guard sync-bib`",
            )
        )
    for _title, keys in sorted(by_title.items()):
        if len(keys) < 2 or any(set(keys) <= work for work in same_work):
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="reference-title-duplicate",
                severity=WARN,
                message=f"{_keys(keys)} have the same title, and may be one work",
                path=path,
                hint="where they are, keep one in Zotero; a correction and the paper it "
                "corrects can share a title and are two works",
            )
        )
    return report


__all__ = ["check_duplicates", "identifiers_of", "isbn_13", "title_of"]
