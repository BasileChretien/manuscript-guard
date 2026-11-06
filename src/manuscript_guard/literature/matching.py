"""Whether a PDF is the cited work: its DOI or its title where a work's own are printed.

A file kept under a citation key is what G7 holds every quote of that work to, and what a
co-author is shown as the work. A publisher's landing page saved as the PDF, a preview of the
first page, a supplement, a correction notice, or another paper filed under the key would then
pass for the source, and a quote checked against it would prove nothing. So a PDF fetched from
the web, or found in a folder of downloads, is kept only where it shows it is the work, and
where the evidence is not exact it is refused rather than guessed at (round 1 of #565):

* **its DOI** is on its first two pages, or in its metadata (XMP's `prism:doi`, the Info
  dictionary's `/doi`, `dc:identifier`); or
* **its title,** as `references.bib` gives it, makes up whole lines near the top of one of its
  first two pages, compared on letters and digits only, so that the line breaks, hyphens,
  capitals and accents of a typeset title do not matter. A title running on in a sentence is
  not a title: a paper whose abstract uses a cited review's title as a phrase was filed as the
  review. A title shorter than twenty letters and digits ("Editorial") is no evidence.

And it is refused, whatever it shows, where

* **its metadata names another DOI,** or its first page prints one: it is another work, which
  names this one, or several;
* **its head says it is about the work rather than the work:** a supplement ("Supplementary
  Appendix", "Supplement to:", "Supporting Information"), a correction ("Correction to:",
  "Erratum", "Corrigendum", "Retraction"), a reply or a comment ("In reply", "Reply to",
  "Response to", "Comment on"), unless the cited work's own title says so;
* **it is a preview:** fewer than half the pages `references.bib` gives the work (`preview`).

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
#: How far down a page its title is looked for, in lines: below that is the running text.
TITLE_LINES = 40
#: How many lines a typeset title is set over, at most.
TITLE_SPAN = 6
#: Where a head saying what kind of document it is stands when no title is found: the top.
HEAD_LINES = 12
PDF_HEADER = b"%PDF-"

#: A DOI where the XMP packet says which work a PDF is, mostly written uncompressed: an
#: element's text or an attribute's value, which ends at `<` or a quote. Its brackets are
#: kept: a Lancet DOI holds "(20)" (round 1 of #565: it was cut at the first one).
_XMP_DOI = re.compile(
    rb"(?i)(?:prism:doi|pdfx:doi|crossmark:doi|dc:identifier)"
    rb"[\s>\"'=]{0,8}(?:<rdf:li>)?\s*(?:doi:|https?://(?:dx\.)?doi\.org/)?"
    rb"(10\.\d{4,9}/[^\s<>\"']+)"
)
#: Where the Info dictionary gives a DOI: its `/doi` key, then a literal string, read by
#: `_literal` to the bracket that closes it (round 2 of #565: Nature, BMC and Elsevier write
#: `/doi(...)/Author(...)` with nothing between, and the DOI ran on into the next key).
_INFO_DOI = re.compile(rb"(?i)/doi\s*\(")
_A_DOI = re.compile(r"(?i)^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)$")
#: A DOI printed on a page.
_PAGE_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>\]\[]+")
_LATEX = re.compile(r"\\[A-Za-z]+\s*")
#: The heads of a document about a work rather than the work, each with what it is called.
_KINDS = (
    (re.compile(r"(?i)^\W*(?:supplement(?:ary|al)?\b|supporting information\b)"),
     "a supplement"),
    (re.compile(r"(?i)^\W*(?:correction\b|erratum\b|corrigendum\b|retraction\b"
                r"|expression of concern\b)"), "a correction or a retraction"),
    (re.compile(r"(?i)^\W*(?:in reply\b|reply\b|response to\b|author'?s'? reply\b"
                r"|comment on\b)"), "a reply or a comment"),
)  # fmt: skip


@dataclass(frozen=True)
class Shown:
    """How a PDF showed it is the work, or why it did not."""

    by: str | None
    why: str = ""
    #: Refused, though it showed the work's DOI or title: a document about the work, or one
    #: that names others too. The inbox says so of the work, where it says nothing of a PDF
    #: that showed no cited work.
    near: bool = False


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
    """The text of a PDF's first pages, each ended by a form feed, or None where nothing on
    this computer can read it.

    `pdftotext` first, with its encoding stated (`literature/sources._pdftotext` says why),
    then pypdf; neither is a dependency. Laid out as the page is: in reading order pdftotext
    runs the lines of a block into one, the journal's name, the title and the authors, and a
    title is known by the lines it makes up (`title_at`)."""
    if shutil.which("pdftotext"):
        try:
            finished = subprocess.run(
                ["pdftotext", "-layout", "-f", "1", "-l", str(pages), "-enc", "UTF-8",
                 str(path), "-"],
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
        return "".join((page.extract_text() or "") + "\f" for page in reader.pages[:pages])
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


def preview(path: Path, expected: int | None) -> str | None:
    """Why a PDF is a preview of a work of `expected` pages, or None: fewer than half of them.
    A first-page preview shows the DOI and the title, and passes every other test."""
    if not expected:
        return None
    counted = page_count(path)
    if counted is None or counted * 2 >= expected:
        return None
    return (f"has {counted} page{'' if counted == 1 else 's'} where references.bib gives the "
            f"work {expected}: a preview, most likely")  # fmt: skip


def _whole(doi: str) -> str:
    """A DOI as read, less a closing stop and a closing bracket it does not open."""
    doi = doi.replace("\\(", "(").replace("\\)", ")").rstrip(".,;:")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(".,;:")
    return doi.lower()


def _literal(raw: bytes, start: int) -> bytes | None:
    """A PDF literal string from just after its opening bracket: to the bracket that balances
    it, a bracket escaped with a backslash being a character of the string; None where it is
    not closed within a DOI's length."""
    depth, out, at = 1, bytearray(), start
    while at < len(raw) and at - start < 512:
        byte = raw[at]
        if byte == 0x5C and at + 1 < len(raw):  # a backslash escapes the next byte
            out.append(raw[at + 1])
            at += 2
            continue
        if byte == 0x28:
            depth += 1
        elif byte == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out)
        out.append(byte)
        at += 1
    return None


def metadata_dois(raw: bytes) -> set[str]:
    """The DOIs a PDF's metadata names, in lower case and without a closing stop."""
    found = {_whole(one.group(1).decode("latin-1")) for one in _XMP_DOI.finditer(raw)}
    for one in _INFO_DOI.finditer(raw):
        value = _literal(raw, one.end())
        doi = _A_DOI.match(value.decode("latin-1").strip()) if value is not None else None
        if doi:
            found.add(_whole(doi.group(1)))
    return found


def doi_in(text: str, doi: str) -> bool:
    """Whether a DOI is in a page's text, line breaks inside it allowed, and not as the start
    of a longer one: 10.1/abc.1 is not in 10.1/abc.12, nor in 10.1/abc.1.s001, PLoS's name
    for a supplement (round 1 of #565). Where it ends at a line break or a space, what follows
    is another line's: a page listing two DOIs, one under the other, gives both."""
    kept = [(at, ch) for at, ch in enumerate(text.lower()) if not ch.isspace()]
    flat = "".join(ch for _, ch in kept)
    for found in re.finditer(re.escape(doi.lower()), flat):
        end = found.end()
        if end == len(flat) or kept[end][0] != kept[end - 1][0] + 1:
            return True
        after = flat[end]
        if after.isalnum():
            continue
        joined = end + 1 < len(flat) and kept[end + 1][0] == kept[end][0] + 1
        if after in "./_-;:()" and joined and flat[end + 1].isalnum():
            continue
        return True
    return False


def _lines(page: str) -> list[str]:
    return [line for line in page.splitlines() if key_of(line)][:TITLE_LINES]


def title_at(pages: list[str], wanted: str) -> tuple[int, int] | None:
    """Where the title makes up whole lines near the top of a page, as (page, line): the
    lines' letters and digits are the title's, with at most a footnote's two digits after."""
    for number, page in enumerate(pages):
        lines = [key_of(line) for line in _lines(page)]
        for first in range(len(lines)):
            joined = ""
            for last in range(first, min(first + TITLE_SPAN, len(lines))):
                joined += lines[last]
                rest = joined[len(wanted):]
                if joined.startswith(wanted) and (not rest or (rest.isdigit() and len(rest) <= 2)):
                    return number, first
                if len(joined) >= len(wanted):
                    break
    return None


def _kind(pages: list[str], at: tuple[int, int] | None, title: str) -> str | None:
    """What a document is about the work, by its head: the lines above its title, or its top
    lines where no title was found; None for the work itself. A kind its own title names, a
    cited reply titled "In reply: ...", is the work's."""
    page, line = at if at is not None else (0, HEAD_LINES)
    if page >= len(pages):
        return None
    head = _lines(pages[page])[: line + 1]
    own = title.lower()
    for pattern, called in _KINDS:
        for one in head:
            found = pattern.match(one)
            if found and found.group().strip(" \t:.-").lower() not in own:
                return called
    return None


def _on_the_page(page: str) -> set[str]:
    return {_whole(found) for found in _PAGE_DOI.findall(page)}


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


def _own(printed: str, doi: str | None) -> bool:
    """Whether a DOI read on a page is the work's: the same, the start of it cut at a line
    break, or it with a word `-layout` set against it (round 2 of #565:
    `10.1177/25152459221106366deffner` was taken for another). `<doi>.s001`, a supplement's,
    is not."""
    if not doi:
        return False
    if printed == doi or doi.startswith(printed):
        return True
    return printed.startswith(doi) and printed[len(doi)].isalpha()


def judged(raw: bytes, text: str | None, doi: str | None, title: str | None) -> Shown:
    """`shows`, on bytes and text already read.

    Another DOI refuses only a PDF that the work's own DOI is not in: one that has it names
    others beside it, a dataset, a comment, a page shared with other articles (round 2 of
    #565: refused, 27 of 52 real PDFs were). The metadata is the PDF's word for which work it
    is, so a PDF whose metadata names another DOI and not the work's is refused even where
    the work's DOI is in its text: that is another paper citing it."""
    meta = metadata_dois(raw)
    doi = doi.lower() if doi else None
    if text is None and not meta:
        return Shown(None, "nothing on this computer reads a PDF's text (install poppler's "
                           "pdftotext, or pypdf), and its metadata names no DOI")  # fmt: skip
    pages = (text or "").split("\f")[:PAGES]
    printed = _on_the_page("\n".join(pages))
    in_text = bool(doi) and (doi_in("\n".join(pages), doi)
                             or any(_own(one, doi) for one in printed))  # fmt: skip
    wanted = title_key(title)
    at = title_at(pages, wanted) if wanted else None
    near = in_text or at is not None or bool(doi and doi in meta)
    others = sorted(meta - {doi})
    if others and not (doi and doi in meta):
        return Shown(None, f"its metadata names another DOI ({', '.join(others)}), so it is "
                           "taken for another work", near)  # fmt: skip
    by_doi = bool(doi) and (doi in meta or in_text)
    if not by_doi:
        page_one = sorted(one for one in _on_the_page(pages[0] if pages else "")
                          if not _own(one, doi))  # fmt: skip
        if page_one:
            return Shown(None, f"its first page gives another DOI ({', '.join(page_one)}) and "
                               "not the work's, so it is another work, or one about several",
                         near)  # fmt: skip
    if by_doi or at is not None:
        kind = _kind(pages, at, title or "")
        if kind:
            return Shown(None, f"its head says it is {kind}, not the work itself", near)
        return Shown("doi" if by_doi else "title")
    if doi and wanted:
        return Shown(None, "its first pages give neither the work's DOI nor its title as a "
                           "title")  # fmt: skip
    if doi:
        return Shown(None, "its first pages do not give the work's DOI, and its title is "
                           "too short to know it by")  # fmt: skip
    if wanted:
        return Shown(None, "its first pages do not give the work's title as a title")
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
    "preview",
    "shows",
    "title_at",
    "title_key",
]
