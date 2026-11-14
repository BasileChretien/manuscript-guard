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
`HEADINGS`, its first letter a capital. A structured abstract's own headings set on lines
of their own are its, up to an Introduction or to where the order of its parts starts
again (`text.section_names.section_levels`). Where one name stands on two such lines otherwise,
which section is the paper's is not read, and the PDF's sections are not used to place its
lines (`PdfText.placed`); the reference list is still found by its heading.

Two lines are headings besides, each only where the names read nothing (Basile, 2026-11-15,
decisions 22 and 23, after the real-paper corpus; round 1 of #686). Where no line names the
Abstract, the first line before the first heading that opens on the Abstract's run-in label
and goes on, "Abstract: The second generation...", as MDPI's layout sets it, and not on a
count of words, "Abstract: 248 words": the label is the Abstract's heading and the rest of
the line its first text, and it runs to the next heading as an Abstract read from its lines
does (`section_levels`), as a Word paper's run-in label does (`text.docx_abstract`). And
where the names cannot be placed alone, a line after the Abstract that opens on a study's
number and a colon, "Experiment 1: Modulating prior knowledge", "Study II: A replication"
(`study_title`), with a name after it before the next: a multi-study paper's heading over
the sections each study repeats, one level above the names after it, up to the next such
line or to the end of the paper.

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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.text.section_names import (
    ABSTRACT_PARTS,
    SECTION_NAMES,
    abstract_end,
    names_abstract,
    run_in_abstract,
    section_levels,
    section_name_alone,
)

SUFFIX = ".pdf"
#: The longest `pdfinfo` is waited for.
PDFINFO_SECONDS = 30

#: The names a line of a PDF is read as a heading by, standing alone, in any case: the same
#: as a Word paragraph wholly in bold is read by in a document with no heading style.
HEADINGS = SECTION_NAMES

#: What is said where a PDF cannot be read here.
NO_PDFTOTEXT = (
    "{name} is a PDF, and a PDF is read by pdftotext, which is not installed here: install "
    "poppler's (or Xpdf's) pdftotext, or ask for the manuscript's source, a .docx, .md or .tex"
)


class UnreadablePdf(ValueError):
    """A PDF that cannot be read here, or holds no text. The message says why."""


#: What is said where a PDF's headings cannot be placed (`PdfText.placed`).
UNPLACED = ("a section's name stands alone on two lines or more, or a structured abstract's "
            "headings stand on lines of their own with no Introduction after them and their "
            "order never starting again, so which section is the paper's is not read")


@dataclass(frozen=True)
class Place:
    """Where a line of a PDF's text stands: its page, from 1; its line counted down that
    page's text as read, from 1; and the number the PDF prints in front of it, where it prints
    one there (a number counted on between two the PDF prints is not given)."""

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
    #: Each running head and foot taken out, `(page, "head" or "foot", text)`: the blinding
    #: check reads them (`auditing.journal._pdf_places`).
    running: tuple[tuple[int, str, str], ...] = ()
    #: The lines, from 1, of the headings that are the Abstract's run-in label, the rest of
    #: the line its first text (`headings_of`).
    run_in: frozenset[int] = frozenset()

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
    def placed(self) -> tuple[tuple[int, str, int], ...] | None:
        """Each heading `(line, title, level)`, where the headings can be placed exactly; else
        None (`UNPLACED`). A structured abstract's headings, on lines of their own, are the
        Abstract's, level 2, where the heading after the Abstract's is one of
        `ABSTRACT_PARTS`: they run to an Introduction, or to where the order of its parts
        starts again, an "Abbreviations" among them (DESIGN.md, Known gaps). With neither
        after them, where they end is not read, unless words stand under the Abstract's own
        heading: then it is one paragraph or more, and the heading after it the main text's. A
        name on two lines among the rest is not placed either
        (`text.section_names.section_levels`, which reads a Word document's bold titles the
        same way)."""
        worded = _worded(self.text.split("\n"), self.headings, self.run_in)
        levels = _levels([title for _line, title in self.headings], worded)
        if levels is None:
            return None
        placed = zip(self.headings, levels, strict=True)
        return tuple((line, title, level) for (line, title), level in placed)

    def described(self) -> str:
        """What read it and how its places are given, for the report's notes."""
        pages = f"{self.pages} page{'s' if self.pages != 1 else ''}"
        numbers = (" and, where the PDF prints a line's number, that number" if self.numbered
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
    and its first letter is a capital (`text.section_names.section_name_alone`)."""
    return section_name_alone(line)


#: A line that opens on a study's number, Arabic or Roman, and a colon: "Experiment 1:
#: Modulating prior knowledge", "Study II: A replication", "EXPERIMENT 3:" (Basile,
#: 2026-11-15, decision 23, after pdf-psych-A2 of the real-paper corpus, whose four
#: experiments each have a "Method" and a "Results and Discussion"). Not "Experiment 3 (n =
#: 99) confirmed this", nor "Experiment 1. In addition", which are its prose.
_STUDY = re.compile(r"(?:Experiment|EXPERIMENT|Study|STUDY) (?:\d{1,2}|[IVX]{1,5}):")


def study_title(line: str) -> str | None:
    """The line, its spaces as one, where it opens on a study's number and a colon
    (`_STUDY`): a multi-study paper's heading over its study's sections; else None."""
    text = " ".join(line.split())
    return text if _STUDY.match(text) else None


#: What a title page writes after "Abstract:": its count of words, "248 words", "250-word",
#: which titles no Abstract (round 1 of #686).
_WORD_COUNT = re.compile(r"\d[\d,]*\s*-?\s*words?\b", re.IGNORECASE)


def headings_of(texts: Sequence[str]) -> tuple[tuple[tuple[int, str], ...], frozenset[int]]:
    """The headings of a PDF's lines, each `(line, title)`, lines from 1, and the lines of
    those that are a run-in label: each line that holds a section's name alone
    (`heading_title`); the Abstract's run-in label, where none of them names the Abstract
    (`_run_in`); and the studies' own headings, where the paper's names cannot be placed
    without them (`_studies`). Each new shape is read only where the names read nothing, as
    a Word paper's run-in label is read where no heading names the Abstract (Basile,
    2026-11-15, decisions 22 and 23, after the real-paper corpus; round 1 of #686)."""
    named = [(at, title) for at, text in enumerate(texts, 1)
             if (title := heading_title(text)) is not None]  # fmt: skip
    label = _run_in(texts, named)
    run_in = frozenset({label[0]} if label is not None else ())
    if label is not None:
        named = sorted([*named, label])
    return tuple(_studies(texts, named, run_in)), run_in


def _run_in(texts: Sequence[str], named: list[tuple[int, str]]) -> tuple[int, str] | None:
    """The first line before the first heading that opens on the Abstract's run-in label and
    goes on (`text.section_names.run_in_abstract`), with its label less the colon or the stop
    as its title, the rest of the line the Abstract's (decision 22, after pdf-socio-B1). Not
    where a heading names the Abstract, nor where the rest of the line is a count of words, a
    title page's "Abstract: 248 words"; nor after the first heading, where a reference or a
    quotation opens so."""
    if any(names_abstract(title) for _at, title in named):
        return None
    first = named[0][0] if named else len(texts) + 1
    for at, text in enumerate(texts[: first - 1], 1):
        label = run_in_abstract(text)
        if label is not None and not _WORD_COUNT.match(after_label(text)):
            return at, label.rstrip(" :.")
    return None


def _studies(texts: Sequence[str], named: list[tuple[int, str]],
             run_in: frozenset[int]) -> list[tuple[int, str]]:  # fmt: skip
    """`named` with the lines that open on a study's number and a colon (`study_title`)
    among them, where the names cannot be placed without them and can with them (decision
    23, after pdf-psych-A2): each after the Abstract's end, with a name after it before the
    next such line. Else `named`, so a paper the names place is placed as they place it, and
    a study listed in its Abstract or a summary row is no heading (round 1 of #686)."""
    lines = [(at, title) for at, text in enumerate(texts, 1)
             if (title := study_title(text)) is not None]  # fmt: skip
    if not lines:
        return named
    titles = [title for _at, title in named]
    worded = _worded(list(texts), named, run_in)
    if section_levels(titles, worded) is not None:
        return named
    after = _abstract_ends(named, worded)
    if after is None:
        return named
    nexts = [at for at, _title in lines[1:]] + [len(texts) + 1]
    kept = [(at, title) for (at, title), until in zip(lines, nexts, strict=True)
            if at > after and any(at < line < until for line, _name in named)]  # fmt: skip
    if not kept:
        return named
    found = sorted([*named, *kept])
    if _levels([title for _at, title in found], _worded(list(texts), found, run_in)) is None:
        return named
    return found


def _abstract_ends(named: list[tuple[int, str]], worded: list[bool]) -> int | None:
    """The line of the first heading after the Abstract's that is no part of it, 0 where no
    heading names the Abstract; None where it ends is not read, or it runs to the end."""
    first = next((at for at, (_line, title) in enumerate(named) if names_abstract(title)), None)
    if first is None:
        return 0
    end = abstract_end([title for _line, title in named[first:]], worded[first:])
    if end is None or first + end >= len(named):
        return None
    return named[first + end][0]


def _worded(lines: list[str], headings: Sequence[tuple[int, str]],
            run_in: frozenset[int]) -> list[bool]:  # fmt: skip
    """For each heading, whether words stand under it before the next: a run-in label has
    them on its own line."""
    starts = [line for line, _title in headings]
    # With no heading read there is none to place (corpus run of 2026-11-11, 2509.01351).
    ends = [*starts[1:], len(lines) + 1] if starts else []
    return [start in run_in or any(lines[k].strip() for k in range(start, end - 1))
            for start, end in zip(starts, ends, strict=True)]  # fmt: skip


def after_label(line: str) -> str:
    """The rest of a line that opens on the Abstract's run-in label, the Abstract's first
    text (`headings_of`); the line as it is where it opens on none."""
    label = run_in_abstract(line)
    return line if label is None else line.lstrip()[len(label):].lstrip()


def _levels(titles: list[str], worded: list[bool]) -> tuple[int, ...] | None:
    """Each title's level, as `PdfText.placed` gives it: the titles before the first study's
    (`study_title`) as `section_levels` places them; each study's at level 1, and the names
    after it at level 2, up to the next study's or the end, none of them twice under it."""
    studies = [at for at, title in enumerate(titles) if study_title(title) is not None]
    first = studies[0] if studies else len(titles)
    levels = section_levels(titles[:first], worded[:first])
    if levels is None:
        return None
    bounds = [*studies, len(titles)]
    for start, end in zip(bounds, bounds[1:], strict=False):
        names = [" ".join(title.casefold().split()) for title in titles[start + 1 : end]]
        if len(names) != len(set(names)):
            return None
        levels = (*levels, 1, *([2] * len(names)))
    return levels


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


def _pdftotext(path: Path, extra: list[str]) -> tuple[str | None, str]:
    """What `pdftotext` reads in one order, in UTF-8 and read as UTF-8, and "", or None and
    why it read nothing: it did not answer in time, or failed; an empty reading is "" and
    ""."""
    from manuscript_guard.proof.reading import PDFTOTEXT_SECONDS

    try:
        done = subprocess.run(
            ["pdftotext", *extra, "-enc", "UTF-8", str(path), "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PDFTOTEXT_SECONDS, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return None, f"pdftotext did not answer within {PDFTOTEXT_SECONDS} seconds"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"pdftotext could not be run ({exc})"
    if done.returncode != 0:
        said = " ".join((done.stderr or "").split())[:200]
        return None, f"pdftotext failed on it (exit {done.returncode}{': ' + said if said else ''})"
    return done.stdout or "", ""


def _read(path: Path) -> PdfText:
    from manuscript_guard.proof import reading

    if not can_read():
        raise UnreadablePdf(NO_PDFTOTEXT.format(name=path.name))
    name = reading._pdftotext_name()
    found, failed = [], []
    for order, extra in (("layout order", []), ("drawing order", ["-raw"])):
        text, why = _pdftotext(path, extra)
        if text is None:
            failed.append(why)
            continue
        paged = reading._paged(f"{name}, {order}", text.split("\f"))
        if paged.lines:
            found.append((paged, text))
    if not found and failed:
        raise UnreadablePdf(f"{path.name} could not be read: {failed[0]}")
    if not found:
        raise UnreadablePdf(f"{path.name} holds no text pdftotext can read: a PDF that is a "
                            "scanned image cannot be audited")  # fmt: skip
    # The margin's numbers read first, then more lines, then the layout order: `max` keeps
    # the first of those that tie.
    kept, text = max(found, key=lambda one: (one[0].numbered, len(one[0].lines)))
    return _text_of(path, kept, text)


def _text_of(path: Path, kept, raw: str) -> PdfText:
    """The text of the reading kept, each line placed. `raw` is what `pdftotext` gave, read
    again for two things `proof.reading` does not keep: whether the PDF printed a line's
    number in front of it (a number counted on between two printed ones is not shown as the
    PDF's), and on which page and at which edge each running head and foot stood."""
    from manuscript_guard.proof.reading import _lines

    pages = [_lines(page) for page in raw.split("\f")]
    places: list[Place] = []
    counted: dict[int, int] = {}
    for line in kept.lines:
        page = line.page or 1
        counted[page] = counted.get(page, 0) + 1
        typed = pages[page - 1] if page <= len(pages) else []
        printed = (line.number if kept.numbered and line.number is not None
                   and f"{line.number} {line.text}" in typed else None)  # fmt: skip
        places.append(Place(page, counted[page], printed))
    texts = [line.text for line in kept.lines]
    headings, run_in = headings_of(texts)
    taken = set(kept.furniture)
    running = tuple((index, "head" if at < len(lines) / 2 else "foot", text)
                    for index, lines in enumerate(pages, 1)
                    for at, text in enumerate(lines) if text in taken)  # fmt: skip
    return PdfText(path, kept.reader, kept.pages, "\n".join(texts), tuple(places), headings,
                   kept.furniture, kept.numbered, running, run_in)  # fmt: skip


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
    "ABSTRACT_PARTS",
    "AUTHOR_FIELD",
    "HEADINGS",
    "NO_PDFTOTEXT",
    "UNPLACED",
    "PdfText",
    "Place",
    "UnreadablePdf",
    "after_label",
    "author",
    "can_read",
    "heading_title",
    "headings_of",
    "is_pdf",
    "read_pdf",
    "study_title",
]
