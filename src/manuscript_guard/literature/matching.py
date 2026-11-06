"""Whether a PDF is the cited work: its DOI or its title on its first pages.

A file kept under a citation key is what G7 holds every quote of that work to, and what a
co-author is shown as the work. A publisher's landing page saved as the PDF, a preview of the
first page, or another paper filed under the key would then pass for the source, and a quote
checked against it would prove nothing. So a PDF fetched from the web, or found in a folder of
downloads, is kept only where it shows it is the work:

* **its DOI** is on its first two pages, or in its metadata (XMP's `prism:doi`, the Info
  dictionary's `/doi`, `dc:identifier`), and its metadata names no other DOI; or
* **its title,** as `references.bib` gives it, is on its first two pages, compared on letters
  and digits only, so that the line breaks, hyphens, capitals and accents of a typeset title
  do not matter. A title shorter than twenty letters and digits ("Editorial", "Erratum") is no
  evidence: too many papers would show it.

Only the first two pages are read. A paper's reference list, which names other works' DOIs
and titles, comes at its end; a cover page a repository adds before the article names the
article too.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

#: How many pages are read for the evidence.
PAGES = 2
#: The fewest letters and digits a title is held as evidence with.
SHORTEST_TITLE = 20
PDF_HEADER = b"%PDF-"

#: A DOI where a PDF's metadata says which work it is, in the XMP packet or the Info
#: dictionary, both of which are mostly written uncompressed.
_META_DOI = re.compile(
    rb"(?i)(?:prism:doi|pdfx:doi|crossmark:doi|dc:identifier|/doi)"
    rb"[\s>(\"'=]{0,8}(?:<rdf:li>)?\s*(?:doi:|https?://(?:dx\.)?doi\.org/)?"
    rb"(10\.\d{4,9}/[^\s<>()\"'\]\[]+)"
)
_LATEX = re.compile(r"\\[A-Za-z]+\s*")


@dataclass(frozen=True)
class Shown:
    """How a PDF showed it is the work, or why it did not."""

    by: str | None
    why: str = ""


def key_of(text: str) -> str:
    """Letters and digits only, accents taken off, in lower case."""
    folded = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in folded.lower() if ch.isascii() and ch.isalnum())


def title_key(title: str | None) -> str | None:
    """A BibTeX title as letters and digits, its commands and braces taken off; None where it
    is too short to be evidence."""
    if not title:
        return None
    key = key_of(_LATEX.sub("", title).replace("{", "").replace("}", ""))
    return key if len(key) >= SHORTEST_TITLE else None


def begins_as_pdf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(PDF_HEADER)) == PDF_HEADER


def first_pages(path: Path, pages: int = PAGES) -> str | None:
    """The text of a PDF's first pages, or None where nothing on this computer can read it.

    `pdftotext` first, with its encoding stated (`literature/sources._pdftotext` says why),
    then pypdf; neither is a dependency."""
    if shutil.which("pdftotext"):
        try:
            finished = subprocess.run(
                ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(path), "-"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60, check=False,
            )  # fmt: skip
            if finished.returncode == 0 and (finished.stdout or "").strip():
                return finished.stdout
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import pypdf
    except ImportError:
        return None
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:pages])
    except Exception:  # noqa: BLE001 - pypdf raises a wide variety; the file is then unread
        return None


def page_count(path: Path) -> int | None:
    """How many pages a PDF has, or None where it cannot be told."""
    try:
        import pypdf
    except ImportError:
        return None
    try:
        return len(pypdf.PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return None


def metadata_dois(raw: bytes) -> set[str]:
    """The DOIs a PDF's metadata names, in lower case and without a closing stop."""
    found = set()
    for match in _META_DOI.finditer(raw):
        doi = match.group(1).decode("latin-1").lower().rstrip(".,;")
        found.add(doi)
    return found


def doi_in(text: str, doi: str) -> bool:
    """Whether a DOI is in a page's text, line breaks inside it allowed, and not as the start
    of a longer one (10.1/abc.1 is not in 10.1/abc.12). Where it ends at a line break or a
    space, a digit after that is another line's: a page listing two DOIs, one under the
    other, gives both."""
    kept = [(at, ch) for at, ch in enumerate(text.lower()) if not ch.isspace()]
    flat = "".join(ch for _, ch in kept)
    for found in re.finditer(re.escape(doi.lower()), flat):
        end = found.end()
        if end == len(flat) or not flat[end].isdigit():
            return True
        if kept[end][0] != kept[end - 1][0] + 1:
            return True
    return False


def shows(path: Path, doi: str | None, title: str | None, text: str | None = None) -> Shown:
    """Whether the PDF at `path` shows it is the work of `doi` and `title`. `text` is its
    first pages' text where the caller read it already."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return Shown(None, f"it could not be read ({exc.strerror or exc})")
    if not raw.startswith(PDF_HEADER):
        return Shown(None, "it is not a PDF (it does not begin with %PDF-)")
    if text is None:
        text = first_pages(path)
    return judged(raw, text, doi, title)


def judged(raw: bytes, text: str | None, doi: str | None, title: str | None) -> Shown:
    """`shows`, on bytes and text already read."""
    meta = metadata_dois(raw)
    doi = doi.lower() if doi else None
    by_doi = bool(doi) and (doi in meta or (text is not None and doi_in(text, doi)))
    wanted = title_key(title)
    by_title = bool(wanted) and text is not None and wanted in key_of(text)
    if by_doi and (not meta or doi in meta):
        return Shown("doi")
    if by_title:
        return Shown("title")
    if text is None and not meta:
        return Shown(None, "nothing on this computer reads a PDF's text (install poppler's "
                           "pdftotext, or pypdf), and its metadata names no DOI")  # fmt: skip
    if by_doi:
        others = ", ".join(sorted(meta))
        return Shown(None, f"its metadata names another DOI ({others}), and its first pages "
                           "do not give the work's title")  # fmt: skip
    if doi and wanted:
        return Shown(None, "its first pages give neither the work's DOI nor its title")
    if doi:
        return Shown(None, "its first pages do not give the work's DOI, and its title is "
                           "too short to know it by")  # fmt: skip
    if wanted:
        return Shown(None, "its first pages do not give the work's title")
    return Shown(None, "the work has no DOI, and its title is too short to know it by")


__all__ = [
    "PAGES",
    "SHORTEST_TITLE",
    "Shown",
    "begins_as_pdf",
    "doi_in",
    "first_pages",
    "judged",
    "key_of",
    "metadata_dois",
    "page_count",
    "shows",
    "title_key",
]
