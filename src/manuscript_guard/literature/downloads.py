"""`sync-sources --from <folder>`: the PDFs a downloader saved, filed by the DOI they carry.

A tool that fetches papers through the author's own access (an open copy first, then a
publisher's text-and-data-mining service, then the author's own signed-in browser) saves each
under its DOI. auto-paper-harvester (github.com/jxtse/auto-paper-harvester, read at commit
4bcb9b5) writes `<folder>/<name>/<name>.pdf` for a paper it got from an open copy or a
publisher's service, and `<folder>/_browser_fallback/<name>.pdf` for one it got through a
browser; a folder of `<name>.pdf` saved by hand or by another tool is read the same way.
manuscript-guard drives no browser and fetches nothing here: it reads the folder.

Each PDF is filed under the citation key of the cited work whose DOI its name spells, the DOI
of the work's entry in `literature/references.bib` as G7 reads it (`doi_of`: undressed, in
lower case). A file name cannot hold every character a DOI can, and the harvester writes the
others as `_` in three ways (`names`); each is tried, without regard to case, as a DOI is
matched. What is not a PDF, a sign-in or paywall page saved under a `.pdf` name, is refused
and said. A file whose name spells two cited DOIs is copied for neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.identifiers import BIB_FILE, doi_of
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.literature.copies import FROM_FOLDER, Candidate, digest
from manuscript_guard.literature.sources import filed_name

#: Where auto-paper-harvester saves what its browser passes fetched.
BROWSER = "_browser_fallback"
#: What an older auto-paper-harvester called the PDF in a DOI's folder; it renames the file
#: to `<name>.pdf` when it next sees it.
LEGACY = "article.pdf"
#: How every PDF begins. A page saved under a `.pdf` name begins otherwise.
PDF_HEADER = b"%PDF-"

_RUN = re.compile(r"[^0-9A-Za-z._-]+")
_ONE = re.compile(r"[^0-9A-Za-z._-]")


class FolderUnreadable(Exception):
    """The folder named with `--from` is not one, or cannot be listed."""


@dataclass(frozen=True)
class Found:
    """A PDF at a place where a DOI names it: the name, in lower case, and the file."""

    name: str
    path: Path
    shown: str


@dataclass(frozen=True)
class Offer:
    """What the folder holds for each cited work, why a work was given nothing, and how many
    of the folder's PDFs no cited DOI names."""

    chosen: dict[str, list[Candidate]]
    why: dict[str, list[str]]
    pdfs: int
    unmatched: int

    def candidates(self, key: str) -> tuple[list[Candidate], list[str]]:
        return self.chosen.get(key, []), self.why.get(key, [])


def names(doi: str) -> set[str]:
    """The names, less `.pdf` and in lower case, that auto-paper-harvester gives a DOI's PDF.

    `clients._safe_identifier`, for an open copy or a publisher's service: each run of other
    characters than letters, digits, `.`, `_` and `-` made one `_`, `.` and `_` taken off the
    ends, and cut at 150 characters. `browser_fallback._doi_to_pdf_path`, for its own browser:
    each run made one `_`, and `_` taken off the ends. `real_browser._slug`, for the author's
    Chrome: each such character made `_`, and nothing taken off.
    """
    doi = doi.lower()
    return {
        _RUN.sub("_", doi).strip("._")[:150],
        _RUN.sub("_", doi).strip("_"),
        _ONE.sub("_", doi),
    }


def _is_pdf_name(path: Path) -> bool:
    return path.suffix.lower() == ".pdf" and path.is_file()


def found_in(folder: Path) -> list[Found]:
    """The PDFs of a folder at the places a DOI names them: `<name>.pdf` in it or in its
    `_browser_fallback`, and `<name>/<name>.pdf` or `<name>/article.pdf` in it. The other
    files of a DOI's folder, its supplements, are not the work's."""
    found: list[Found] = []
    for entry in sorted(folder.iterdir()):
        if _is_pdf_name(entry):
            found.append(Found(entry.stem.lower(), entry, entry.name))
        elif entry.is_dir() and entry.name == BROWSER:
            found.extend(
                Found(inner.stem.lower(), inner, f"{BROWSER}/{inner.name}")
                for inner in sorted(entry.iterdir())
                if _is_pdf_name(inner)
            )
        elif entry.is_dir():
            found.extend(
                Found(entry.name.lower(), inner, f"{entry.name}/{inner.name}")
                for inner in sorted(entry.iterdir())
                if _is_pdf_name(inner)
                and inner.name.lower() in {f"{entry.name.lower()}.pdf", LEGACY}
            )
    return found


def _begins_as_pdf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(PDF_HEADER)) == PDF_HEADER


def _read(files: list[Found]) -> tuple[list[tuple[Found, str, int]], list[str]]:
    """The files that are PDFs, with their digests, and why each other one is not taken."""
    read: list[tuple[Found, str, int]] = []
    why: list[str] = []
    for one in files:
        try:
            if not _begins_as_pdf(one.path):
                why.append(
                    f"the folder's {one.shown} does not begin with %PDF-, so it is not a PDF "
                    "(a sign-in or paywall page saved under that name, most likely)"
                )
                continue
            sha, size = digest(one.path)
        except OSError as exc:
            why.append(f"the folder's {one.shown} could not be read ({exc.strerror or exc})")
            continue
        read.append((one, sha, size))
    return read, why


def _cited_dois(project: Project, keys: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Each cited key's DOI, and why each key without one has none."""
    bib = project.path("literature") / BIB_FILE
    entries = read_entries(bib) if bib.is_file() else {}
    dois: dict[str, str] = {}
    why: dict[str, list[str]] = {}
    for key in keys:
        fields = entries.get(key)
        doi = doi_of(fields) if fields is not None else None
        if doi:
            dois[key] = doi
        elif fields is None:
            why[key] = [f"not in {BIB_FILE}, so there is no DOI to find its file by"]
        elif fields.get("doi", "").strip():
            why[key] = [f"its DOI in {BIB_FILE} is malformed (G7 says how)"]
        else:
            why[key] = [f"no DOI in {BIB_FILE}, so there is no name to find its file by"]
    return dois, why


def _match(found: list[Found], dois: set[str]) -> tuple[dict[str, list[Found]],
                                                        dict[str, list[str]], int]:  # fmt: skip
    """The files each DOI names, why a DOI's file was not taken as its own because another
    cited DOI names it too, and how many files no cited DOI names."""
    spelt: dict[str, set[str]] = {}
    for doi in dois:
        for name in names(doi):
            spelt.setdefault(name, set()).add(doi)
    files: dict[str, list[Found]] = {}
    doubt: dict[str, list[str]] = {}
    unmatched = 0
    for one in found:
        named = sorted(spelt.get(one.name, ()))
        if not named:
            unmatched += 1
        elif len(named) > 1:
            for doi in named:
                doubt.setdefault(doi, []).append(
                    f"the folder's {one.shown} could be the PDF of any of {', '.join(named)}, "
                    "and which is not guessed"
                )
        else:
            files.setdefault(named[0], []).append(one)
    return files, doubt, unmatched


def _choose(
    doi: str, files: list[Found], doubt: list[str]
) -> tuple[tuple[Found, str, int] | None, list[str]]:
    """The one PDF of a DOI, as (file, SHA-256, size), or None, and why each other file
    was not taken. Two PDFs that differ are neither taken."""
    read, why = _read(files)
    versions: dict[str, tuple[Found, str, int]] = {}
    for one, sha, size in read:
        versions.setdefault(sha, (one, sha, size))
    why = doubt + why
    if len(versions) > 1:
        shown = ", ".join(one.shown for one, _, _ in read)
        why.append(
            f"{len(versions)} PDFs of its DOI that differ ({shown}), and which is the work's "
            "is not guessed"
        )
        return None, why
    if not versions and not why:
        why.append(f"the folder has no PDF named for its DOI, {doi}")
    return next(iter(versions.values()), None), why


def offer(project: Project, folder: Path) -> Offer:
    """What the folder holds for each work the manuscript cites."""
    from manuscript_guard.lookup.run import cited_keys

    try:
        if not folder.is_dir():
            raise FolderUnreadable(f"{folder} is not a folder")
        found = found_in(folder)
    except OSError as exc:
        raise FolderUnreadable(f"{folder} could not be read ({exc.strerror or exc})") from exc
    dois, why = _cited_dois(project, cited_keys(project))
    files, doubt, unmatched = _match(found, set(dois.values()))
    chosen: dict[str, list[Candidate]] = {}
    for doi in sorted(set(dois.values())):
        pdf, reasons = _choose(doi, files.get(doi, []), doubt.get(doi, []))
        for key in (key for key, its in dois.items() if its == doi):
            if pdf is not None:
                one, sha, size = pdf
                name = filed_name(key, ".pdf")
                chosen[key] = [Candidate(name, one.path, FROM_FOLDER, None, sha, size,
                                         about="from the folder", doi=doi)]  # fmt: skip
            if reasons:
                why[key] = reasons
    return Offer(chosen, why, len(found), unmatched)


__all__ = ["BROWSER", "FolderUnreadable", "Found", "Offer", "found_in", "names", "offer"]
