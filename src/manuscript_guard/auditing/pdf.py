"""A PDF manuscript read as text, for `audit` and `compare` (DESIGN.md, "A PDF manuscript").

A referee is mostly sent a PDF. Its text is read as `proof` reads a proof
(`proof.reading`): by `pdftotext`, in UTF-8, with what every page repeats taken out (the
running head and foot, the page's number, and the line numbers a manuscript prints in its
margin). `pdftotext` reads a page in two orders, the order of its layout and the order the
PDF draws its text in (`-raw`), and one is kept: the one in which the line numbers the PDF
prints in its margin are read, then the one that gives more lines, then the layout order.
Xpdf's layout order gives a paragraph a line, and its drawing order a line a line; poppler's
layout order sets the margin's numbers apart as a column, which is dropped, and its drawing
order keeps each in front of its line. Without `pdftotext` a PDF is not read: pypdf is no
dependency of the tool, and a PDF read some other way would not be read as described here.

What is kept is the text, a line of the PDF to a line, and where each line stands: its page,
its line counted down that page's text as read (the running head and the page's number left
out), and the number the PDF prints beside it, where it prints one. Every place the audit
and `compare` give in a PDF is that page and line.

A PDF marks no heading. A line is read as one only where it holds a section's name and
nothing else, numbered or not ("Methods", "2. Results", "REFERENCES"), from the closed list
`HEADINGS`, its first letter a capital. Where one name stands on two such lines, a structured
abstract's own headings set on lines of their own perhaps, which section is the paper's is
not read, and the PDF's sections are not used to place its lines (`Sections.placed`); the
reference list is still found by its heading.

A PDF's tables are lines of text, not rows of cells: their numbers are read as the text's,
and no table is read as one. What a PDF keeps besides its text is not a Word file's: the
Author field of its Info dictionary is read through `pdfinfo` where it is installed
(`author`), and nothing else (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SUFFIX = ".pdf"
#: The longest `pdfinfo` is waited for.
PDFINFO_SECONDS = 30

#: The names a line of a PDF is read as a heading by, standing alone, in any case.
HEADINGS = frozenset({
    "abstract", "summary", "structured abstract", "introduction", "background",
    "methods", "method", "methodology", "materials and methods", "material and methods",
    "methods and materials", "patients and methods", "subjects and methods",
    "participants and methods", "results", "findings", "results and discussion",
    "discussion", "general discussion", "discussion and conclusions", "conclusion",
    "conclusions", "limitations", "strengths and limitations", "references", "bibliography",
    "literature cited", "works cited", "acknowledgements", "acknowledgments",
    "acknowledgement", "acknowledgment", "funding", "conflicts of interest",
    "conflict of interest", "competing interests", "declaration of competing interest",
    "author contributions", "data availability", "data availability statement", "ethics",
    "ethics statement", "ethical approval", "abbreviations", "appendix",
    "supplementary material", "supplementary materials", "tables", "figures",
    "figure legends", "figure captions",
})  # fmt: skip
#: A section's number in front of its name: "2 ", "2. ", "2.1 ", "II. ".
_NUMBER = re.compile(r"(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,5}\.)\s+")

#: What is said where a PDF cannot be read here.
NO_PDFTOTEXT = (
    "{name} is a PDF, and a PDF is read by pdftotext, which is not installed here: install "
    "poppler's (or Xpdf's) pdftotext, or ask for the manuscript's source, a .docx, .md or .tex"
)


class UnreadablePdf(ValueError):
    """A PDF that cannot be read here, or holds no text. The message says why."""


@dataclass(frozen=True)
class Place:
    """Where a line of a PDF's text stands: its page, from 1; its line counted down that
    page's text as read, from 1; and the number the PDF prints beside it, where it prints
    one."""

    page: int
    line: int
    printed: int | None = None

    def said(self) -> str:
        """"page 3, line 12", and "(numbered 145)" where the PDF numbers the line."""
        numbered = f" (numbered {self.printed})" if self.printed is not None else ""
        return f"page {self.page}, line {self.line}{numbered}"

    def as_dict(self) -> dict:
        return {"page": self.page, "line": self.line, "printed_line": self.printed}


@dataclass(frozen=True)
class PdfText:
    """One PDF read: who read it, how many pages, its text a line of the PDF to a line, where
    each of those lines stands, and its headings, each `(line, title)`, lines from 1."""

    path: Path
    reader: str
    pages: int
    text: str
    places: tuple[Place, ...]
    headings: tuple[tuple[int, str], ...] = ()
    #: What was taken out as what every page repeats.
    furniture: tuple[str, ...] = ()
    #: Whether the PDF prints line numbers that were read.
    numbered: bool = False

    def place(self, line: int | None) -> Place | None:
        """Where line `line` of the text stands, None for no line or one not in it."""
        if line is None or not 0 < line <= len(self.places):
            return None
        return self.places[line - 1]

    def said(self, line: int | None) -> str:
        """Where line `line` stands, in words; "line N" where it is not a line of the text."""
        place = self.place(line)
        return place.said() if place is not None else f"line {line}"

    def stretch(self, first: int, last: int) -> str:
        """Lines `first` to `last` of the text, in words: "page 5, line 3 to page 6, line 9"."""
        start, end = self.place(first), self.place(last)
        if start is None or end is None:
            return f"lines {first}-{last}"
        if (start.page, start.line) == (end.page, end.line):
            return f"page {start.page}, line {start.line}"
        if start.page == end.page:
            return f"page {start.page}, lines {start.line}-{end.line}"
        return f"page {start.page}, line {start.line} to page {end.page}, line {end.line}"

    @property
    def heading_lines(self) -> frozenset[int]:
        """The lines of its headings, from 0, as `audit.bibliography_spans` takes them."""
        return frozenset(line - 1 for line, _title in self.headings)

    @property
    def repeated(self) -> tuple[str, ...]:
        """The section names that stand on two heading lines or more."""
        seen: dict[str, int] = {}
        for _line, title in self.headings:
            key = _key(title)
            seen[key] = seen.get(key, 0) + 1
        return tuple(name for name, count in seen.items() if count > 1)

    def described(self) -> str:
        """What read it and how its places are given, for the report's notes."""
        pages = f"{self.pages} page{'s' if self.pages != 1 else ''}"
        numbers = (" and, where the PDF numbers its lines, that number" if self.numbered
                   else "")  # fmt: skip
        return (f"{self.path.name}: read by {self.reader}, {pages}; each place is a page and a "
                "line counted down that page's text as read, its running head and page number "
                f"left out{numbers}")


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == SUFFIX


def can_read() -> bool:
    """Whether a PDF can be read here: `pdftotext` is on PATH."""
    return shutil.which("pdftotext") is not None


def heading_title(line: str) -> str | None:
    """The section's name a line of a PDF holds alone, its number taken off, or None: the
    whole line, less a number in front and a colon or a stop after, is one of `HEADINGS`,
    and its first letter is a capital."""
    text = " ".join(line.split())
    found = _NUMBER.match(text)
    if found is not None:
        text = text[found.end() :]
    text = text.rstrip(":.").strip()
    if not text[:1].isupper() or _key(text) not in HEADINGS:
        return None
    return text


def _key(title: str) -> str:
    return " ".join(title.casefold().split())


_READ: dict[tuple[str, str], PdfText] = {}
#: How many PDFs read are kept: `compare` reads two versions, each in several places.
_KEPT = 8


def read_pdf(path: Path) -> PdfText:
    """`path` read (see the module's docstring). Raises `UnreadablePdf` with what to say. A
    file read once is not read again while it is unchanged: `audit` and `compare` read one
    version in several places, and each `pdftotext` is a process."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise UnreadablePdf(f"{path.name} cannot be read: {exc.strerror or exc}") from None
    key = (str(path.resolve()), digest)
    if key not in _READ:
        while len(_READ) >= _KEPT:
            del _READ[next(iter(_READ))]
        _READ[key] = _read(path)
    return _READ[key]


def _read(path: Path) -> PdfText:
    from manuscript_guard.proof import reading

    if not can_read():
        raise UnreadablePdf(NO_PDFTOTEXT.format(name=path.name))
    name = reading._pdftotext_name()
    found = []
    for order, extra in (("layout order", []), ("drawing order", ["-raw"])):
        text = reading._pdftotext(path, extra)
        if text is not None:
            found.append(reading._paged(f"{name}, {order}", text.split("\f")))
    found = [one for one in found if one.lines]
    if not found:
        raise UnreadablePdf(f"{path.name} holds no text pdftotext can read: a PDF that is a "
                            "scanned image cannot be audited")  # fmt: skip
    # The margin's numbers read first, then more lines, then the layout order: `max` keeps
    # the first of those that tie.
    kept = max(found, key=lambda one: (one.numbered, len(one.lines)))
    return _text_of(path, kept)


def _text_of(path: Path, kept) -> PdfText:
    places: list[Place] = []
    counted: dict[int, int] = {}
    for line in kept.lines:
        page = line.page or 1
        counted[page] = counted.get(page, 0) + 1
        places.append(Place(page, counted[page], line.number if kept.numbered else None))
    texts = [line.text for line in kept.lines]
    headings = tuple((at, title) for at, text in enumerate(texts, 1)
                     if (title := heading_title(text)) is not None)  # fmt: skip
    return PdfText(path, kept.reader, kept.pages, "\n".join(texts), tuple(places), headings,
                   kept.furniture, kept.numbered)  # fmt: skip


#: Where the name `author` gives was read.
AUTHOR_FIELD = "the PDF's author (the Author of its Info dictionary, read by pdfinfo)"


def author(path: Path) -> tuple[str | None, str]:
    """The Author field of the PDF's Info dictionary as `pdfinfo` reads it ("" where it has
    none), with "", or None with why it was not read: no `pdfinfo`, or one that failed or
    took too long."""
    if shutil.which("pdfinfo") is None:
        return None, "pdfinfo is not installed"
    try:
        done = subprocess.run(
            ["pdfinfo", "-enc", "UTF-8", str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=PDFINFO_SECONDS, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return None, f"pdfinfo took more than {PDFINFO_SECONDS} seconds"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"pdfinfo could not be run ({exc})"
    if done.returncode != 0:
        return None, "pdfinfo could not read it"
    for line in (done.stdout or "").splitlines():
        found = re.match(r"Author:[ \t]*(.*)$", line)
        if found:
            return found.group(1).strip(), ""
    return "", ""


__all__ = [
    "AUTHOR_FIELD",
    "HEADINGS",
    "NO_PDFTOTEXT",
    "PdfText",
    "Place",
    "UnreadablePdf",
    "author",
    "can_read",
    "heading_title",
    "is_pdf",
    "read_pdf",
]
