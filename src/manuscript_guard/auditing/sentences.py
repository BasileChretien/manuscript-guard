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
#: An abbreviation's stop at the end of a text, which ends no sentence before a citation:
#: "Smith et al. [3] showed", "e.g. [4]", "cf. [5]", "Fig. [6]" (round 2
#: of #482); "ca." in lower case only, as "Ca." is calcium.
_ABBREVIATED = re.compile(
    r"(?<![^\W_])(?:et\s+al|e\.\s?g|i\.\s?e|cf|vs|viz|figs?|refs?|eqs?|approx|(?-i:ca)|suppl)"
    r"\.\Z",
    re.IGNORECASE,
)
#: What may stand between two citations typed together, `[3] [4]`, `[3]~[4]`, `[3], [4]`.
_BETWEEN = " \t~,;[]()" + NUL


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
        summary = _summarises(section, below, methods)
        if summary is not None:
            named[id(section)] = ABSTRACT if summary or not _after_the_opening(
                sections, index, methods) else CONCLUSION
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


def _summarises(section: Section, below: list[Section], methods: set[int]) -> bool | None:
    """Whether a heading is the Abstract, whatever stands under it: True for one that names
    it, False for a "Summary" with a heading of a structured abstract under it, which is the
    Abstract only before the paper's opening (`_after_the_opening`), and None for any
    other."""
    if section.is_abstract:
        return True
    if _SUMMARY.match(plain(section.title)) and any(
            _ABSTRACT_HEADING.match(plain(other.title)) for other in below):  # fmt: skip
        return False
    return None


def _after_the_opening(sections: list[Section], index: int, methods: set[int]) -> bool:
    """Whether a heading comes after the paper's opening, an Introduction, a Background or
    the Methods outside an Abstract: a "Summary" there is the paper's last section, read as
    its conclusion, and not its abstract (round 2 of #482)."""
    chain: list[Section] = []
    for section in sections[:index]:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        chain.append(section)
        if any(one.is_abstract for one in chain[:-1]):
            continue
        if _OPENING.match(plain(section.title)) or id(section) in methods:
            return True
    return False


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

    @property
    def prints(self) -> bool:
        """Whether it prints a citation in the sentence: `\\nocite` prints none."""
        return not (self.kind == "latex"
                    and self.written.lstrip("\\").lower().startswith("nocite"))


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
    #: Where each heading stands, from its first character to its end: a heading is no
    #: sentence of its part (round 2 of #482).
    headings: tuple[tuple[int, int], ...] = ()

    @cached_property
    def sentences(self) -> list[Sentence]:
        """Each sentence, a citation that opens it after the stop of the one before taken
        off its start (`_after_a_stop`)."""
        from manuscript_guard.claims import sentence_pieces

        breaks = [found.start() for found in re.finditer("\n", self.text)]
        heads = sorted(self.headings)
        pieces: list[tuple[int, int, int]] = []
        for piece in sentence_pieces(self.text, self.read, self.lines,
                                     (*self.cuts, *self._stop_cuts(),
                                      *(at for span in self.headings for at in span))):  # fmt: skip
            # A heading is a piece of its own: the line under it is never joined to it, nor
            # does it give the heading a citation it opens with (round 3 of #482).
            if pieces and not _within(heads, pieces[-1][1]) \
                    and self._continues(pieces[-1], piece):  # fmt: skip
                pieces[-1] = (pieces[-1][0], pieces[-1][1], piece[2])
            else:
                pieces.append(piece)
        found = []
        for index, (start, first, end) in enumerate(pieces):
            if index and not _within(heads, pieces[index - 1][1]):
                first = self._after_a_stop(pieces[index - 1], start, first, end)
            if not _LETTER.search(self.read, first, end) or _within(heads, first):
                continue
            line = bisect_right(breaks, first - 1) + 1 + self.line_offset
            place =self.place(line) if self.place is not None else Place()
            found.append(Sentence(start, first, end, line, quoted(self.text, self.read,
                                                                   first, end), place))
        return found

    @cached_property
    def _runs(self) -> list[tuple[int, int]]:
        """Each run of citations typed together, `[3] [4]` or `[3]~[4]`, on one line with
        nothing but spaces, ties and punctuation between: where its first starts and its
        last ends."""
        runs: list[tuple[int, int]] = []
        for cite in sorted(self.cites, key=lambda one: one.start):
            if runs and runs[-1][1] <= cite.start and not self.read[
                    runs[-1][1] : cite.start].strip(_BETWEEN):  # fmt: skip
                runs[-1] = (runs[-1][0], max(runs[-1][1], cite.end))
            else:
                runs.append((cite.start, cite.end))
        return runs

    def _opening_run(self, first: int, end: int) -> tuple[int, int] | None:
        """The run of citations that opens the piece `[first, end)`, or None. `first` is the
        piece's start: in LaTeX's view a citation is blanked, and a piece's first word
        stands after it."""
        runs = self._runs
        at = bisect_right([start for start, _end in runs], first) - 1
        return next((run for run in runs[max(at, 0) : at + 2] if first <= run[0] < end
                     and not self.read[first : run[0]].strip(_BLANK + "[(")), None)  # fmt: skip

    def _past(self, at: int) -> int:
        """Past the brackets that close a citation ending at `at`."""
        while at < len(self.read) and self.read[at] in "])":
            at += 1
        return at

    def _stop_cuts(self) -> tuple[int, ...]:
        """Where a sentence ends at a citation typed directly after its stop, with no space
        between: `.[3]`, `.[3-5]`, `.\\cite{a}`, and `.~\\cite{a}` as LaTeX's view blanks
        the tie (round 1 of #482). `claims` ends a sentence at a stop followed by a space, and
        read on past `.[3]` into the next; here the sentence ends after the citation, or
        after the last of a run typed together, `.[3] [4]`, unless the stop is an
        abbreviation's, "et al.[3]", or the word after the run goes on in lower case."""
        read = self.read
        cuts = []
        for start, end in self._runs:
            back = start
            while back > 0 and read[back - 1] in NUL + "~[":
                back -= 1
            if back == 0 or read[back - 1] not in ".!?" or _abbreviated(read, back):
                continue
            end = self._past(end)
            if _begins(read, end):
                cuts.append(end)
        return tuple(cuts)

    def _continues(self, before: tuple[int, int, int], piece: tuple[int, int, int]) -> bool:
        """Whether a piece goes on the sentence before it: one that ends at an abbreviation's
        stop, "Smith et al.", and a piece that opens with a citation, "[3] showed that",
        which `claims` cut at the stop (round 2 of #482)."""
        stop = _trimmed(self.read, before[1], before[2])
        return _abbreviated(self.read, stop) and self._opening_run(piece[0], piece[2]) is not None

    def _after_a_stop(self, before: tuple[int, int, int], start: int, first: int,
                      end: int) -> int:  # fmt: skip
        """Where a sentence starts once the run of citations that opens it is taken off: one
        typed right after the stop of the sentence before, on its line or the next, with no
        blank line between, and in a Word document in its paragraph, is that sentence's,
        where the word after the run begins a sentence, in a capital or a figure."""
        stop = _trimmed(self.read, before[1], before[2])
        if not _STOPPED.search(self.read, before[1], stop) or _abbreviated(self.read, stop):
            return first
        run = self._opening_run(start, end)
        if run is None:
            return first
        gap = self.read[stop : run[0]]
        if ("\n" in gap) if self.lines else _BLANK_LINE.search(gap):
            return first
        after = self._past(run[1])
        if not _begins(self.read, after):
            return first
        while after < end and self.read[after] in _BLANK:
            after += 1
        return after

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


def _trimmed(read: str, first: int, end: int) -> int:
    """Where a piece's text ends, the blanks after it left out."""
    while end > first and read[end - 1] in _BLANK:
        end -= 1
    return end


def _abbreviated(read: str, stop: int) -> bool:
    """Whether the text ending at `stop` ends with an abbreviation's stop."""
    return bool(_ABBREVIATED.search(read, max(0, stop - 16), stop))


def _begins(read: str, at: int) -> bool:
    """Whether what follows `at` may begin a sentence: nothing, or a word not in lower
    case."""
    found = re.match(r"[ \t\n\x00]*(\S)", read[at : at + 200])
    return found is None or not found.group(1).islower()


def _within(spans: list[tuple[int, int]], at: int) -> bool:
    """Whether `at` lies in one of `spans`, sorted by their start."""
    index = bisect_right(spans, (at, 10**18)) - 1
    return index >= 0 and spans[index][0] <= at < spans[index][1]


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
    return sorted(found + author_year(text, hidden), key=lambda cite: cite.start)


def author_year(text: str, read: str) -> list[Cite]:
    """Each citation by author and year in brackets, "(Smith et al., 2019)", as the
    earlier-papers check reads one (`gates.recycling`), where `read`, the text at its
    offsets with what prints nothing blanked, prints it: not in a comment (round 2 of #482)."""
    from manuscript_guard.gates.recycling import _AUTHOR_YEAR, _is_author_year

    return [Cite(m.start(), m.end(), m.group(), "author-year")
            for m in _AUTHOR_YEAR.finditer(text)
            if _is_author_year(m.group()) and read[m.start()] != NUL]  # fmt: skip


def latex_cites(source, read: str) -> list[Cite]:
    """Each key a LaTeX file's citation commands name (`text.latex`), where its command
    stands, with the command as typed; and each citation by author and year typed as text
    where it prints, `read` being what does."""
    found = [Cite(cited.start, cited.end, " ".join(source.text[cited.start : cited.end].split()),
                  "latex", key=cited.key) for cited in source.reading.cited]  # fmt: skip
    return sorted(found + author_year(source.text, read), key=lambda cite: cite.start)


def latex_headings(source) -> tuple[tuple[int, int], ...]:
    """Where each heading of a LaTeX file stands, its command to the end of its title."""
    return tuple((heading.start, heading.end + 1) for heading in source.reading.headings
                 if heading.end >= 0)  # fmt: skip


def line_spans(text: str, lines) -> tuple[tuple[int, int], ...]:
    """Where each of `lines`, counted from 1, stands in `text`."""
    starts = [0, *(found.end() for found in re.finditer("\n", text))]
    return tuple((starts[line - 1], starts[line] if line < len(starts) else len(text))
                 for line in sorted(lines) if 0 < line <= len(starts))  # fmt: skip


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
    "latex_headings",
    "line_spans",
    "place_tex_lines",
    "placing",
    "quoted",
]
