"""A paper's sentences as the reader options read them, each with the part of the paper it
stands in and the citations it carries.

Two options read sentences: `--design observational`, for causal words where an observational
study's paper sums up (`auditing.causal`), and `--cited`, each citation beside its sentence
(`auditing.cited`). Both read a file as the audit reads its numbers (`audit._read_sources`):
a Markdown paper as pandoc prints it (`claims.readable`), a Word document a paragraph a line
(`text.docx`), and a LaTeX file through its tree, what it prints at the `.tex` offsets
(`auditing.latex`), a heading's command and the end of its title cutting a sentence. Each
file is placed by its own headings, as the Abstract against Results places it, a Word
document's by their styles and a LaTeX document's by the headings its printed view shows: a
file with no heading is placed nowhere.

A sentence is cut as `claims` cuts one. A citation stands in the sentence it is typed in,
and one that opens a sentence, typed right after the stop of the sentence before, on its
line or the next with no blank line between ("X. [3] Y"), and in a Word document in its
paragraph, is that sentence's: so is one standing alone between two sentences. A heading
has no stop, so a citation opening the paragraph under it is its paragraph's. The
citations are a numbered
marker held to the reference list (`references.marker_spans`), a LaTeX `\\cite` and its kin
(`text.latex`), a pandoc citation, `[@key]` or `@key`, and a citation by author and year in
brackets, "(Smith et al., 2019)", as the earlier-papers check reads one
(`gates.recycling`). The cited-sentences table lists the first two kinds; the causal words
read every kind as a sentence that cites.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from manuscript_guard.text.section_names import (
    methods_sections,
    names_conclusion,
    names_discussion,
    names_results,
    plain,
)
from manuscript_guard.text.sections import Section, subsections

ABSTRACT = "Abstract"
METHODS = "Methods"
RESULTS = "Results"
DISCUSSION = "Discussion"
CONCLUSION = "Conclusion"
NUL = "\x00"
#: A blank of what a reading leaves unread.
_BLANK = " \t\n" + NUL
#: The opening of a paper, as G8 reads it: a heading over one of these names no part.
_OPENING = re.compile(r"(?:introduction|background)\W*$", re.IGNORECASE)
#: A "Summary" alone, which the Lancet titles its abstract, and the headings of a structured
#: abstract under it that make it one.
_SUMMARY = re.compile(r"summary\W*$", re.IGNORECASE)
_ABSTRACT_HEADING = re.compile(
    r"(?:background|introduction|objectives?|aims?|purpose|context|methods?|design"
    r"|setting|participants|results?|findings|interpretation|conclusions?)\W*$",
    re.IGNORECASE,
)
#: A pandoc citation key, as the mask blanks one (`text.masking`): `[@smith2019]`, `@smith`.
_PANDOC = re.compile(r"(?<![\w`])-?@[A-Za-z][\w:.#$%&+?<>~/-]*")
#: A sentence's stop at its end, and what may close after it, as `claims` cuts a sentence.
_STOPPED = re.compile(
    r"[.!?][)\]\"'*_\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]*\Z"
)
#: A blank line, which parts two paragraphs.
_BLANK_LINE = re.compile(r"\n[ \t\x00]*\n")
#: A letter, which a sentence holds.
_LETTER = re.compile(r"[^\W_]")


@dataclass(frozen=True)
class Place:
    """Where a line stands: the part of the paper its headings name, the outermost that
    names one deciding (`ABSTRACT` ... `CONCLUSION`, or None), and the title of the heading
    it is directly under, "" under none."""

    part: str | None = None
    title: str = ""


def placing(sections: list[Section]) -> Callable[[int], Place]:
    """Where each line of one file stands, given its headings in order, each with its level
    and its line. A heading that names the Abstract always names it, and every heading under
    it is the Abstract's, its Background, Methods, Results and Conclusions among them, as G8's
    `Walk` reads it; so is a "Summary" over the headings of a structured abstract, as the
    Lancet titles its abstract (round 1 of #482). Another heading over the opening of the
    paper (an Introduction, a Background, the Methods or the Abstract under it) is the
    paper's title, and names no part."""
    methods = {id(section) for section in methods_sections(sections)}
    named: dict[int, str] = {}
    for index, section in enumerate(sections):
        below = subsections(sections, index)[1:]
        if _summarises(section, below, methods):
            named[id(section)] = ABSTRACT
            continue
        if any(other.is_abstract or _OPENING.match(plain(other.title)) or id(other) in methods
               for other in below):  # fmt: skip
            continue
        part = _part(section, methods)
        if part is not None:
            named[id(section)] = part
    starts, places = [0], [Place()]
    chain: list[Section] = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        chain.append(section)
        part = next((named[id(one)] for one in chain if id(one) in named), None)
        starts.append(section.line)
        places.append(Place(part, plain(section.title)))
    return lambda line: places[bisect_right(starts, line) - 1]


def _summarises(section: Section, below: list[Section], methods: set[int]) -> bool:
    """Whether a heading is the Abstract, whatever stands under it: one that names it, or a
    "Summary" with a heading of a structured abstract under it."""
    if section.is_abstract:
        return True
    return bool(_SUMMARY.match(plain(section.title))) and any(
        _ABSTRACT_HEADING.match(plain(other.title)) for other in below)


def _part(section: Section, methods: set[int]) -> str | None:
    if section.is_abstract:
        return ABSTRACT
    if id(section) in methods:
        return METHODS
    if names_discussion(section.title):
        return DISCUSSION
    if names_results(section.title):
        return RESULTS
    if names_conclusion(section.title):
        return CONCLUSION
    return None


@dataclass(frozen=True)
class Cite:
    """One citation where it stands in a file: its offsets, what is written, and what it
    names: the numbers of a numbered marker, or a LaTeX key; `kind` is "numbered", "latex",
    "pandoc" or "author-year"."""

    start: int
    end: int
    written: str
    kind: str
    numbers: tuple[int, ...] = ()
    key: str = ""


@dataclass(frozen=True)
class Sentence:
    """One sentence of a file: where it stands, its first line, what it says as typed, and
    where that line stands."""

    start: int
    first: int
    end: int
    line: int
    text: str
    place: Place


@dataclass(frozen=True)
class View:
    """One file as its sentences are read: `text` is what a sentence is quoted from, `read`
    the same at its offsets with what prints no prose blanked; `place` where each line stands
    (None for a file with no heading); `cuts` more places a sentence ends; `cites` each
    citation in it."""

    path: Path
    text: str
    read: str
    lines: bool = False
    place: Callable[[int], Place] | None = None
    cuts: tuple[int, ...] = ()
    cites: tuple[Cite, ...] = field(default=())
    #: Lines before `text`'s first in the file: a front matter's abstract is read as a text of
    #: its own, at its key's line.
    line_offset: int = 0
    #: What of the file was not read, each a sentence.
    notes: tuple[str, ...] = ()

    @cached_property
    def sentences(self) -> list[Sentence]:
        """Each sentence, a citation that opens it after the stop of the one before taken
        off its start (`_after_a_stop`)."""
        from manuscript_guard.claims import sentence_pieces

        breaks = [found.start() for found in re.finditer("\n", self.text)]
        pieces = sentence_pieces(self.text, self.read, self.lines,
                                 (*self.cuts, *self._stop_cuts()))  # fmt: skip
        starts = sorted(cite.start for cite in self.cites)
        ends = {cite.start: cite.end for cite in self.cites}
        found = []
        for index, (start, first, end) in enumerate(pieces):
            if index:
                first = self._after_a_stop(pieces[index - 1], first, end, starts, ends)
            if not _LETTER.search(self.read, first, end):
                continue
            line = bisect_right(breaks, first - 1) + 1 + self.line_offset
            place =self.place(line) if self.place is not None else Place()
            found.append(Sentence(start, first, end, line, quoted(self.text, self.read,
                                                                   first, end), place))
        return found

    def _stop_cuts(self) -> tuple[int, ...]:
        """Where a sentence ends at a citation typed directly after its stop, with no space
        between: `.[3]`, `.[3-5]`, `.\\cite{a}`, and `.~\\cite{a}` as LaTeX's view blanks
        the tie (round 1 of #482). `claims` ends a sentence at a stop followed by a space, and
        read on past `.[3]` into the next; here the sentence ends after the citation, or
        after the last of several typed together, `.[3][4]`, unless the next word goes on in
        lower case, as after "e.g.[3]"."""
        read = self.read
        cuts: dict[int, int] = {}
        for cite in sorted(self.cites, key=lambda one: one.start):
            back = cite.start
            while back > 0 and read[back - 1] in NUL + "~[":
                back -= 1
            if back == 0:
                continue
            after = back in cuts.values()
            if read[back - 1] not in ".!?" and not after:
                continue
            end = cite.end
            while end < len(read) and read[end] in "])":
                end += 1
            follows = re.match(r"[ \t\n\x00]*(\S)", read[end : end + 200])
            if follows is not None and follows.group(1).islower():
                continue
            if after:
                cuts = {start: stop for start, stop in cuts.items() if stop != back}
            cuts[cite.start] = end
        return tuple(cuts.values())

    def _after_a_stop(self, before: tuple[int, int, int], first: int, end: int,
                      starts: list[int], ends: dict[int, int]) -> int:  # fmt: skip
        """Where a sentence starts once each citation that opens it is taken off: one typed
        right after the stop of the sentence before, on its line or the next, with no blank
        line between, and in a Word document in its paragraph, is that sentence's."""
        stop = before[2]
        while stop > before[1] and self.read[stop - 1] in _BLANK:
            stop -= 1
        if not _STOPPED.search(self.read, before[1], stop):
            return first
        while True:
            at = bisect_right(starts, first) - 1
            # A citation that starts at `first`, or one opened by a bracket there.
            cite = next((s for s in starts[max(at, 0) : at + 2] if first <= s < end
                         and not self.read[first:s].strip(_BLANK + "[(")), None)  # fmt: skip
            if cite is None:
                return first
            gap = self.read[stop:cite]
            if ("\n" in gap) if self.lines else _BLANK_LINE.search(gap):
                return first
            first = ends[cite]
            while first < end and self.read[first] in _BLANK + "])":
                first += 1

    def owner(self, at: int) -> int | None:
        """The index of the sentence a citation starting at `at` belongs to: the one it is
        typed in, or the one before where it opens none, typed after that one's stop
        (`sentences`) or standing alone between two."""
        index = bisect_right(self._firsts, at) - 1
        if index < 0:
            return 0 if self.sentences else None
        return index

    @cached_property
    def _firsts(self) -> list[int]:
        return [one.first for one in self.sentences]


def place_tex_lines(view, place: Callable[[int], Place]) -> dict[str, dict[int, Place]]:
    """Each line of a LaTeX document's files, by the file's path, placed as the printed
    view's line it was printed from is (`Printed.place_line`), as the Abstract against
    Results places them (`abstract.place_lines`): where several lines of the view share one
    `.tex` line, a place in a part of the paper is kept over one in none, so that the
    Abstract's last sentence, on the line of `\\end{abstract}`, stays the Abstract's."""
    lines = view.text.split("\n")
    found: dict[str, dict[int, Place]] = {}
    for number, printed in enumerate(lines, 1):
        if not printed.replace(NUL, " ").strip():
            continue
        where = view.place_line(number)
        if where is None:
            continue
        mine = found.setdefault(where[0].path, {})
        kept = mine.get(where[1])
        if kept is not None and kept.part is not None:
            continue
        mine[where[1]] = place(number)
    return found


def quoted(text: str, read: str, first: int, end: int) -> str:
    """A sentence as typed, its runs of space made one, and the blanks at its end left out."""
    stop = end
    while stop > first and read[stop - 1] in _BLANK:
        stop -= 1
    return " ".join(text[first:stop].split())


def cites_in_text(text: str, hidden: str, intervals: list[tuple[int, int]]) -> list[Cite]:
    """The citations of a Markdown or a Word document's text: each numbered marker, read in
    `hidden` as G7's census reads one; each pandoc citation and each by author and year,
    read in `text`."""
    from manuscript_guard.auditing.references import marker_spans

    found = [Cite(start, end, written, "numbered", tuple(numbers))
             for start, end, written, numbers in marker_spans(hidden, intervals)]  # fmt: skip
    found += [Cite(m.start(), m.end(), m.group(), "pandoc", key=m.group().lstrip("-@"))
              for m in _PANDOC.finditer(text)]  # fmt: skip
    return sorted(found + author_year(text), key=lambda cite: cite.start)


def author_year(text: str) -> list[Cite]:
    """Each citation by author and year in brackets, "(Smith et al., 2019)", as the
    earlier-papers check reads one (`gates.recycling`)."""
    from manuscript_guard.gates.recycling import _AUTHOR_YEAR, _is_author_year

    return [Cite(m.start(), m.end(), m.group(), "author-year")
            for m in _AUTHOR_YEAR.finditer(text) if _is_author_year(m.group())]  # fmt: skip


def latex_cites(source) -> list[Cite]:
    """Each key a LaTeX file's citation commands name (`text.latex`), where its command
    stands, with the command as typed; and each citation by author and year typed as text."""
    found = [Cite(cited.start, cited.end, " ".join(source.text[cited.start : cited.end].split()),
                  "latex", key=cited.key) for cited in source.reading.cited]  # fmt: skip
    return sorted(found + author_year(source.text), key=lambda cite: cite.start)


def latex_cuts(source) -> tuple[int, ...]:
    """Where a LaTeX file's headings and abstracts end a sentence: each heading's command
    and the end of its title, and each abstract's start and end."""
    cuts: list[int] = []
    for heading in source.reading.headings:
        cuts.append(heading.start)
        if heading.end >= 0:
            cuts.append(heading.end + 1)
    for start, end in source.reading.abstracts:
        cuts += [start, end]
    return tuple(cuts)


__all__ = [
    "ABSTRACT",
    "CONCLUSION",
    "DISCUSSION",
    "METHODS",
    "RESULTS",
    "Cite",
    "Place",
    "Sentence",
    "View",
    "author_year",
    "cites_in_text",
    "latex_cites",
    "latex_cuts",
    "place_tex_lines",
    "placing",
    "quoted",
]
