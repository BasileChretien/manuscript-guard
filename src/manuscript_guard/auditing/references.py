"""G7 for a paper that has no `references.bib`: its reference list counted, its numbered
citations held to the list, and, only when asked, each DOI and PMID looked up.

The list is the one `audit` cuts from the text (`audit.bibliography_spans`), or in LaTeX the
`thebibliography` the reader finds. What is counted: its entries, and the DOIs and PMIDs
typed in them. Where the entries carry their numbers, "1." or "[1]", a bracketed citation in
the text, `[3]`, `[3, 5]`, `[3-5]`, is held to the list: a number the list does not hold is
reported, and so is an entry no citation names; with no such citation, every entry is,
only where a Word or Markdown paper's text cites nothing by number (`cites_by_number`,
`numbered_link`) and no author of the list with a year (`cites_by_author`). In Markdown a list
numbered "1." or "1)" is numbered as pandoc prints it, from its first number up, so a list
typed "1." on every entry is 1, 2, 3; a number pandoc escaped, `1\\.`, is typed text and
printed as typed. A .docx whose list Word numbers itself prints no number in its text, so
there an entry's number is its place in Word's count: only where every entry is numbered by
one Word numbering that counts in Arabic numerals from 1, a count no paragraph with words
above the list is in (`text.word_numbering`). A bracket after a value that encloses it,
`64 [55-72]`, is an interval and no citation (`audit._intervals`). In LaTeX each `\\cite`
key is held to the `\\bibitem` keys, and a `\\nocite{*}` cites them all; an entry is
reported in the file that holds it.

Looking up sends each DOI to Crossref and OpenAlex, and to DataCite where Crossref does not
know it and then to doi.org where DataCite does not either, and each PMID to PubMed, through
the transport `lookup` uses; nothing is sent without `--lookup`. What they answer is read as
G7 reads a record (`gates.lookups._standing`): retracted, withdrawn, under concern, published
since, and a DOI or a PMID no registry knows. An entry with neither is sorted, and an article
or a book among them is looked up in Crossref by its title (`auditing.by_title`); the DOI of a
near-exact match is then asked about as an entry's own (`by_title.look_up_all`). A record is
kept only in the folder `--lookup-cache` names, and read from there the next time instead of
asking again.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from manuscript_guard.findings import INFO, WARN
from manuscript_guard.gates.identifiers import normal_doi
from manuscript_guard.keys import placed

NUMBERED = "numbered"
#: A .docx list whose numbers Word prints: an entry's number is its place in the count.
BY_PLACE = "numbered by place"
KEYED = "keyed"
UNNUMBERED = "not numbered"
#: A PDF's list whose entries are not told apart (`census_of_printed`).
UNTOLD = "its entries not told apart"

#: An entry that carries its number: "12." / "12)" / "[12]", or as pandoc writes one it
#: escapes, which prints as typed: "12\." / "12\)" / "\[12\]". Groups: the bracketed number,
#: the number, its escape, its stop.
_NUMBERED_ENTRY = re.compile(r"\s*(?:\\?\[(\d{1,3})\\?\]|(\d{1,3})(\\?)([.)]))(?=\s)")
#: A bracketed citation of numbers, as the marker rule reads one (`audit._WHOLE_MARKER`),
#: or as pandoc escapes one, `\\[3\\]` (round 2 of #463):
#: "[3]", "[3, 5]", "[3-5]", "[3–5, 8]". Not a link's text, `[3](url)`.
_MARKER = re.compile(
    r"\\?\[\s*(\d{1,3}(?:\s*[-\u2013\u2014]\s*\d{1,3})?"
    r"(?:\s*[,;]\s*\d{1,3}(?:\s*[-\u2013\u2014]\s*\d{1,3})?)*)\s*\\?\](?!\()"
)
_PART = re.compile(r"(\d{1,3})(?:\s*[-\u2013\u2014]\s*(\d{1,3}))?")
#: What in a text may be a citation by number written other than in brackets, each by its
#: name: where a text holds none of these, no bracketed citation and no author of the list
#: cited with a year (`cites_by_author`), a numbered list's entries are each reported as
#: never cited (Basile, 2026-11-25, "Strict rule", then "Drop run-on digits"). Each reads
#: widely, a unit squared and "(1) the first" among what they find; digits run straight on
#: into letters, "VGG16", "COVID-19", "disease12", are none.
#: A superscript digit, as Unicode writes one.
_SUPERSCRIPT_DIGIT = re.compile("[\u00b9\u00b2\u00b3\u2070\u2074-\u2079]")
#: A superscript holding a digit, as pandoc writes one, `^3^`, `^1,2^`.
_CARETS = re.compile(r"\^[^\s^]*\d[^\s^]*\^")
#: HTML's superscript holding a digit, `<sup>3</sup>`.
_SUP = re.compile(r"<sup\b[^>]*>[^<]*\d", re.IGNORECASE)
#: A number in parentheses, or a list or a range of them, with a hyphen or a dash, or with
#: "and" before the last, after "ref." or "refs" or not: "(3)", "(3, 5)", "(3-5)",
#: "(2,4-6)", "(1 and 2)", "(1, 2 and 5)", "(ref. 3)", "(refs 1-3)", "(refs. 1, 2)". Of up to
#: three digits, as a bracketed citation's are, so that a year, "Smith (2019)", is read as an
#: author's (`cites_by_author`).
_NUMBER = r"\d{1,3}(?:\s*[-–—]\s*\d{1,3})?"
_PARENTHESISED = re.compile(
    rf"\(\s*(?:[Rr]efs?\.?\s*)?{_NUMBER}(?:(?:\s*[,;]\s*|\s*,?\s+and\s+){_NUMBER})*\s*\)"
)
#: Digits right after a word's closing stop, with no space: "disease.12", "trials,3-5",
#: "x);4"; not a decimal, "2.5", whose stop follows a digit, nor a hyphen, "COVID-19".
_AFTER_A_STOP = re.compile(r"[^\W\d_][.,);:]+\d")
#: Each, by the name a stand-in that forgets it is known by.
CITED_BY_NUMBER = {
    "superscript digit": _SUPERSCRIPT_DIGIT, "carets": _CARETS, "sup": _SUP,
    "parenthesised": _PARENTHESISED, "after a stop": _AFTER_A_STOP,
}  # fmt: skip
#: A Markdown link whose text is a citation's numbers, as typed: "[1](#B1)", "[2, 3](#B2)",
#: "[1-3](https://...)", and each of "[[2](#B2), [3](#B3)]", as a conversion from PMC writes
#: them; not an image, "![1](img1.png)". The mask blanks a link's target from its "]", so it
#: is read in the text as typed (`numbered_link`).
_NUMBERED_LINK = re.compile(rf"(?<!!)\[\s*{_NUMBER}(?:\s*[,;]\s*{_NUMBER})*\s*\]\(")
#: The apostrophes a name is typed with, each read as "'" when names are compared.
_APOSTROPHES = "'\N{RIGHT SINGLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}" \
    "\N{MODIFIER LETTER APOSTROPHE}"
_FOLDED = str.maketrans({mark: "'" for mark in _APOSTROPHES[1:]})
#: A word of an entry, a name among them: letters, with an apostrophe or a hyphen inside.
_WORD = re.compile(rf"[^\W\d_][\w{_APOSTROPHES}-]*")
#: A surname as a citation gives it: two letters or more, an apostrophe or a hyphen inside,
#: after particles in small letters, "van der Berg", "de la Cruz"; its last word is the name.
_PARTICLES = r"(?:(?:van|von|der|den|de|del|della|di|da|du|la|le|dos|das|ter|ten|zu)\s+)*"
_SURNAME = rf"[^\W\d_](?:[^\W\d_]|[{_APOSTROPHES}-](?=[^\W\d_]))+"
#: The authors a citation gives: a surname, then "et al.", a comma before it or not, or
#: "and" or "&" and another.
_AUTHORS = (rf"(?P<first>{_PARTICLES}{_SURNAME})"
            rf"(?:,?\s+et\s+al\.?|\s+(?:and|&)\s+(?P<second>{_PARTICLES}{_SURNAME}))?")
#: A year as an author-and-year citation gives one: four digits, a letter after or not.
_YEAR = r"\d{4}[a-z]?"
#: What may follow a citation's year, which closes it: a ")" or "]" (a part's end), a ";"
#: or a ",", or a page, after a ":" or "p." or "pp.".
_CLOSED = r"(?=\s*(?:[)\];,:]|pp?\.|\Z))"
#: An author-and-year citation in a group: its authors, a comma or a space, and its year.
_IN_A_GROUP = re.compile(rf"(?<![^\W\d_]){_AUTHORS},?\s+{_YEAR}{_CLOSED}")
#: A group in parentheses or in square brackets, with none inside, on one line or over two,
#: as Markdown wraps a paragraph's lines.
_GROUP = re.compile(r"[(\[]([^()\[\]\n]*(?:\n[^()\[\]\n]*)?)[)\]]")
#: An author-and-year citation in a sentence, its year in parentheses or in square brackets
#: and closing its part: "Smith (2019)", "Smith et al.'s (2019a)", "Smith and Lee (2019,
#: p. 4)".
_NARRATIVE = re.compile(
    rf"(?<![^\W\d_]){_AUTHORS}(?:[{_APOSTROPHES}]s)?\s*[(\[]\s*{_YEAR}{_CLOSED}"
)
#: A Markdown link whose text is an author-and-year citation, as typed, as a conversion from
#: PMC writes one: "([Smith et al., 2019](#B12); [Lee, 2020](#B2))".
_AUTHOR_LINK = re.compile(rf"(?<!!)\[\s*{_AUTHORS},?\s+{_YEAR}\s*\]\(")
#: The widest range read as a run of citations, `[3-12]`: a wider one is not expanded.
MAX_RANGE = 100
#: A DOI, which ends at a space, a quote or a brace, and before `](`, where a Markdown link's
#: text ends and its target starts. A `<` stands in it only as a SICI DOI's pair, which holds
#: a `::` and no `/`, with more of the DOI after the `>`:
#: `10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E` (round 2 of #463).
#: A tag after a DOI, `10.1000/xyz</span>`, `<br>`, `<br/>PMID` or `<i>J</i>`, is none of it.
_DOI = re.compile(
    r"\b10\.\d{4,9}(?:\.\d+)*/"
    r"(?:(?!\]\()(?:[^\s\"{}<]|<[^\s\"{}<>/]*::[^\s\"{}<>/]*>"
    r"(?=[^\s\"{}<.,;:'*_`)\]>])))+"
)
#: What a DOI written in a sentence ends with that is not the DOI's: a stop, an emphasis or a
#: code mark, `*doi:10.1000/xyz*`, and a closing bracket the DOI did not open, the `>` of
#: `<https://doi.org/...>` among them.
_DOI_STOPS = ".,;:'*_`"
_CLOSING = {")": "(", "]": "[", ">": "<"}
_PMID = re.compile(r"\bPMID\s*:?\s*(\d{1,9})\b", re.IGNORECASE)
_BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")


@dataclass(frozen=True)
class Entry:
    """One entry of a reference list: how the report names it, the line it starts on, its
    number or its key, the DOIs and PMIDs typed in it, and the file it is in where that is
    not the paper's own: a LaTeX paper's `thebibliography` in a file it inputs."""

    label: str
    line: int
    number: int | None = None
    key: str | None = None
    dois: tuple[str, ...] = ()
    pmids: tuple[str, ...] = ()
    path: Path | None = None
    #: The entry as typed, its lines joined: what the cited-sentences table shows of it.
    text: str = field(default="", compare=False)
    #: In a PDF's list whose entries are not told apart, whether its one identifier ends a
    #: line with more of the list after it, where it may run on (`census_of_printed`).
    ends_line: bool = field(default=False, compare=False)
    #: In a PDF's list told apart, whether an identifier of the entry was held back as one
    #: that may run on, or was cut short (`Census.unsent`): it is no entry with none.
    held_back: bool = field(default=False, compare=False)


def without_identifier(entry: Entry) -> bool:
    """Whether a look-up had nothing to ask of `entry`: no DOI and no PMID read, and none
    held back as not sent, which the report says apart (review of #632)."""
    return not entry.dois and not entry.pmids and not entry.held_back


@dataclass(frozen=True)
class Problem:
    """Something G7 reports of the list or of a citation, where it stands."""

    code: str
    message: str
    line: int | None = None
    path: Path | None = None
    #: What its key in `--json` names (`keys`): the entry's label, or the citation as typed,
    #: and for a citation the digest of the sentence it is typed in.
    subject: str | None = None
    sentence: str | None = None
    #: What an audit gives it: a warning, or a note for a check right too seldom on published
    #: papers to warn (`_title_differs`).
    severity: str = WARN
    #: What an audit says under it, where the check's record on published papers is shown.
    hint: str | None = None


@dataclass
class Census:
    """What a paper's reference list holds, and what is wrong between it and the text."""

    path: Path
    entries: tuple[Entry, ...] = ()
    style: str = UNNUMBERED
    markers: int = 0
    problems: list[Problem] = field(default_factory=list)
    note: str = ""
    #: In a PDF's list, each DOI or PMID that ends a line the entry goes on after, `(line,
    #: identifier as read)`: it may go on on the next line, and is not looked up.
    unsent: list[tuple[int, str]] = field(default_factory=list)
    #: In a PDF's list, why its entries are not told apart, where they are not (`UNTOLD`).
    untold: str = ""
    #: Whether its text holds a bracketed citation or what a citation by number may be
    #: (`cites_by_number`, `numbered_link`), and the names it cites with a year, folded
    #: (`cited_names`): what the other files of an audit are held to (`held_across`).
    cites: bool = False
    named: frozenset[str] = frozenset()
    #: Whether its entries are each reported as never cited because its text cites nothing
    #: (`_held_to_numbers`).
    uncited: bool = False

    @property
    def dois(self) -> int:
        return sum(1 for entry in self.entries if entry.dois)

    @property
    def pmids(self) -> int:
        return sum(1 for entry in self.entries if entry.pmids)


def identifiers(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The DOIs and the PMIDs typed in `text`, each once, in order."""
    dois = [_trimmed(normal_doi(found.group(0))).lower() for found in _DOI.finditer(text)]
    pmids = [found.group(1) for found in _PMID.finditer(text)]
    return tuple(dict.fromkeys(dois)), tuple(dict.fromkeys(pmids))


def _trimmed(doi: str) -> str:
    """`doi` without the stops and the closing brackets after it that are the sentence's: a
    bracket the DOI opened is its own, `10.1016/S0140-6736(19)30000-0`, and stays."""
    while doi and (doi[-1] in _DOI_STOPS or _unopened(doi)):
        doi = doi[:-1]
    return doi


def _unopened(doi: str) -> bool:
    """Whether `doi` ends with a closing bracket it did not open."""
    last = doi[-1]
    return last in _CLOSING and doi.count(last) > doi.count(_CLOSING[last])


def _entries_of(lines: list[str], spans: list[tuple[int, int]], paragraphs: bool) -> list[Entry]:
    """The entries under each list's heading: a paragraph each in a .docx, and in Markdown
    a block, or a line that starts with its number."""
    found: list[tuple[int, list[str], int]] = []
    for list_at, (start, end) in enumerate(spans):
        current: list[str] | None = None
        for index in range(start + 1, min(end, len(lines))):
            line = lines[index]
            if not line.strip():
                current = None
                continue
            if paragraphs or current is None or _NUMBERED_ENTRY.match(line):
                current = [line]
                found.append((index + 1, current, list_at))
            else:
                current.append(line)
    entries = []
    # A Markdown list, "1." or "1)" and not escaped: pandoc prints it from its first number
    # up, whatever the others are typed as. Its stop and its list, while it lasts.
    run: tuple[int, str, int] | None = None
    counted = 0
    for place, (line, parts, list_at) in enumerate(found, start=1):
        text = " ".join(parts)
        numbered = _NUMBERED_ENTRY.match(text)
        number = int(numbered.group(1) or numbered.group(2)) if numbered else None
        if paragraphs or not _is_list_item(numbered):
            run = None
        elif run is not None and _same_list(run, numbered.group(4), list_at):
            counted += 1
            number = run[0] + counted
        else:
            run, counted = (number, numbered.group(4), list_at), 0
        dois, pmids = identifiers(text)
        label = f"entry {number}" if number is not None else f"entry {place} of the list"
        entries.append(Entry(label, line, number=number, dois=dois, pmids=pmids,
                             text=" ".join(text.split())))  # fmt: skip
    return entries


def _is_list_item(numbered: re.Match[str] | None) -> bool:
    """Whether an entry's number makes it an item of a Markdown ordered list: "1." or "1)",
    not escaped, `1\\.`, which pandoc writes for a number it means as typed text."""
    return numbered is not None and numbered.group(2) is not None and not numbered.group(3)


def _same_list(run: tuple[int, str, int], stop: str, list_at: int) -> bool:
    """Whether an item goes on the list `run` began, its first number, its stop and the
    reference list it is in: a list ends where the stop changes, as in pandoc and
    CommonMark, and at the end of its reference list."""
    return run[1:] == (stop, list_at)


def markers_in(hidden: str, intervals: list[tuple[int, int]]) -> list[tuple[int, str, list[int]]]:
    """Each bracketed citation of numbers in `hidden`, the text as the audit reads it, with
    the line it is on and the numbers it cites. One inside an interval's span, which runs
    from the value it follows to its closing bracket, is none (`audit._intervals`)."""
    return [(hidden.count("\n", 0, start) + 1, written, numbers)
            for start, _end, written, numbers in marker_spans(hidden, intervals)]  # fmt: skip


def marker_spans(
    hidden: str, intervals: list[tuple[int, int]]
) -> list[tuple[int, int, str, list[int]]]:
    """`markers_in`, each marker with where it starts and ends in `hidden` instead of its
    line: what the cited-sentences table finds a marker's sentence by."""
    found = []
    for marker in _MARKER.finditer(hidden):
        if any(start <= marker.start() < end for start, end in intervals):
            continue
        numbers: list[int] = []
        for part in _PART.finditer(marker.group(1)):
            low = int(part.group(1))
            high = int(part.group(2)) if part.group(2) else low
            if low <= high <= low + MAX_RANGE:
                numbers += range(low, high + 1)
            else:
                numbers += [low, high]
        found.append((marker.start(), marker.end(), marker.group(0), numbers))
    return found


def census_of_text(
    path: Path,
    original: str,
    spans: list[tuple[int, int]],
    hidden: str,
    intervals: list[tuple[int, int]],
    *,
    docx: bool,
    numbering: Mapping[int, tuple[str, bool, int]] | None = None,
    raised: Collection[int] = (),
    fields: bool = False,
    typed: str | None = None,
) -> Census:
    """A Markdown, text or .docx paper's census: its lists are `spans` of `original`, its
    citations are read in `hidden`, where the lists are blanked. `numbering` is a .docx's
    Word numbering, by the line it numbers (`text.docx.DocxText.numbering`); `raised`, the
    0-based lines of `hidden` where a .docx raises a digit as superscript
    (`text.docx.DocxText.raised`), and `fields`, whether it holds a citation field
    (`DocxText.cited_by_field`); `typed`, the text `hidden` masks, at the same offsets,
    where a link's target is read (`numbered_link`). Where no bracketed citation is read, the
    entries are
    reported as never cited only if the text cites nothing by number (`cites_by_number`,
    `numbered_link`) and no author of the list with a year (`cites_by_author`), nor does any
    other file of the audit (`held_across`)."""
    markers = markers_in(hidden, intervals)
    typed = hidden if typed is None else typed
    said = {"markers": len(markers), "named": cited_names(hidden, typed),
            "cites": bool(markers) or cites_by_number(hidden, spans, raised, fields)
            or numbered_link(typed, hidden)}  # fmt: skip
    if not spans:
        return Census(path, note="no reference list was found under a heading, so none was "
                      "counted", **said)  # fmt: skip
    entries = _entries_of(original.split("\n"), spans, paragraphs=docx)
    census = Census(path, tuple(entries), **said)
    if entries and all(entry.number is not None for entry in entries):
        census.style = NUMBERED
    elif docx and _numbered_by_word(entries, numbering or {}):
        census.style = BY_PLACE
        # The number Word prints: the entry's place in its count, where an empty numbered
        # paragraph takes one too (round 2 of #463).
        places = [numbering[entry.line][2] for entry in entries]
        entries = [
            Entry(f"entry {place}", entry.line, number=place, dois=entry.dois, pmids=entry.pmids,
                  text=entry.text)
            for place, entry in zip(places, entries, strict=True)
        ]
        census.entries = tuple(entries)
    else:
        return census
    census.uncited = not census.cites and not _listed(census.named, entries)
    census.problems = _held_to_numbers(path, entries, markers, _sentences(hidden, intervals),
                                       uncited=census.uncited)  # fmt: skip
    return census


def cites_by_number(
    hidden: str, spans: list[tuple[int, int]], raised: Collection[int] = (), fields: bool = False
) -> bool:
    """Whether a text whose reference lists are blanked, `hidden`, may cite by number other
    than in brackets: a digit raised as superscript, as typed text writes one or, in a .docx,
    on a line of `raised` outside the lists' `spans`, a note's mark among them; a number in
    parentheses, with words or not (`_PARENTHESISED`); digits right after a word's stop; or
    a citation field (`fields`). A Markdown link whose text is a number is read apart, in
    the text as typed (`numbered_link`). Where none is there and no
    bracketed citation either, the text cites nothing by number, and a numbered list's every
    entry is never cited, unless the text cites an author of the list with a year
    (`cites_by_author`; Basile, 2026-11-25, "Strict rule", then "Drop run-on digits").
    Digits typed straight onto a word, "disease12", are not read as a citation. A PDF's text
    is never asked: its superscripts are set as plain digits, so any number after a word may
    be one (`census_of_printed`)."""
    if fields or _raised_outside(raised, spans):
        return True
    return any(pattern.search(hidden) for pattern in CITED_BY_NUMBER.values())


def _raised_outside(raised: Collection[int], spans: list[tuple[int, int]]) -> bool:
    """Whether a line of `raised` is outside the reference lists' `spans`, which are
    `[start, end)` 0-based lines, as `hidden` blanks them."""
    return any(not any(start <= line < end for start, end in spans) for line in raised)


def numbered_link(typed: str, hidden: str) -> bool:
    """Whether `typed`, a text as typed, holds a Markdown link whose text is a citation's
    numbers (`_NUMBERED_LINK`) where `hidden`, its mask at the same offsets, has not masked
    its opening bracket: a link in a comment or a listing is none. Read in the text as typed,
    since the mask blanks the link's target from its "]"."""
    return any(hidden[link.start()] == "[" for link in _NUMBERED_LINK.finditer(typed))


def cites_by_author(hidden: str, entries: Collection[Entry], typed: str | None = None) -> bool:
    """Whether `hidden`, a text whose reference lists are blanked, cites with a year an
    author whose name is a word of an entry, in either's case and whatever apostrophes each
    is typed with: an author-and-year paper whose list is numbered cites its entries by
    name, and none is reported as never cited (Basile, 2026-11-25). The names are the
    surnames a citation's shape gives (`AUTHOR_YEAR`); `typed` is the text as typed, where a
    link is read (`hidden` where it is not given)."""
    return _listed(cited_names(hidden, hidden if typed is None else typed), entries)


def cited_names(hidden: str, typed: str) -> frozenset[str]:
    """The surnames `hidden` cites with a year (`AUTHOR_YEAR`), folded (`_folded`)."""
    return frozenset(_folded(name) for read in AUTHOR_YEAR.values()
                     for name in read(hidden, typed))  # fmt: skip


def _listed(named: Collection[str], entries: Collection[Entry]) -> bool:
    """Whether a name of `named`, folded, is a word of an entry of `entries`, folded."""
    return bool(named) and any(_folded(word) in named for entry in entries
                               for word in _WORD.findall(entry.text))  # fmt: skip


def _folded(name: str) -> str:
    """`name` as names are compared: its apostrophes read as "'", in no case."""
    return name.translate(_FOLDED).casefold()


def _surnames(cited: re.Match[str]) -> set[str]:
    """The surnames an author-and-year citation gives: the last word of each, capitalised,
    after its particles, and without a possessive "'s"."""
    return {re.sub(rf"[{_APOSTROPHES}]s\Z", "", said.split()[-1])
            for said in (cited.group("first"), cited.group("second"))
            if said and said.split()[-1][0].isupper()}  # fmt: skip


def _named_in_a_group(hidden: str, _typed: str) -> set[str]:
    """The surnames an author-and-year citation in parentheses or in square brackets gives,
    "(Smith et al., 2020)", "[Smith and Lee 2020; Brown, 2019a]", "(Smith, et al., 2019: 45)",
    a group over two lines among them: in each part of a group, between its semicolons, a
    citation's shape (`_IN_A_GROUP`). Not a capitalised word before a year in any other
    shape, "(N = 1998)", "(The 2019 cohort)"."""
    return {name for group in _GROUP.finditer(hidden) for part in group.group(1).split(";")
            for cited in _IN_A_GROUP.finditer(part) for name in _surnames(cited)}  # fmt: skip


def _named_in_a_sentence(hidden: str, _typed: str) -> set[str]:
    """The surnames an author-and-year citation in a sentence gives, its year in parentheses
    or in square brackets: "Smith (2019)", "Smith and Lee (2020)", "Smith et al.'s [2019a]"."""
    return {name for cited in _NARRATIVE.finditer(hidden) for name in _surnames(cited)}


def _named_in_a_link(hidden: str, typed: str) -> set[str]:
    """The surnames a Markdown link whose text is an author-and-year citation gives, read in
    `typed`, the text as typed, where `hidden`, its mask at the same offsets, has not masked
    its opening bracket (`_AUTHOR_LINK`): the mask blanks a link's target from its "]"."""
    return {name for cited in _AUTHOR_LINK.finditer(typed) if hidden[cited.start()] == "["
            for name in _surnames(cited)}  # fmt: skip


#: How an author is cited with a year, each by the name a stand-in that forgets it is known
#: by: in parentheses or in square brackets, in a sentence, and as a link's text.
AUTHOR_YEAR: dict[str, Callable[[str, str], set[str]]] = {
    "in a group": _named_in_a_group, "in a sentence": _named_in_a_sentence,
    "in a link": _named_in_a_link,
}  # fmt: skip


def held_across(censuses: list[Census]) -> list[Census]:
    """The censuses of the files one audit reads, each list whose entries were reported as
    never cited because its own text cites nothing (`Census.uncited`) left unreported where
    another file cites, by number (`Census.cites`) or by an author of any file's list with a
    year: a paper given as several files, its sections in some and its list alone in
    another, and a Word paper beside its supplement (round 2 of #790)."""
    named = frozenset().union(*(census.named for census in censuses))
    if not any(census.cites for census in censuses) and not any(
            _listed(named, census.entries) for census in censuses):  # fmt: skip
        return censuses
    return [replace(census, uncited=False, problems=[
        problem for problem in census.problems if problem.code != "entry-never-cited"])
        if census.uncited else census for census in censuses]  # fmt: skip


def _sentences(hidden: str, intervals: list[tuple[int, int]]) -> list[str]:
    """The digest of the sentence each marker of `markers_in` stands in, in its order
    (`keys`): each use of a citation is a finding of its own sentence."""
    return [placed(hidden, start) for start, *_rest in marker_spans(hidden, intervals)]


def census_of_printed(
    path: Path,
    text: str,
    spans: list[tuple[int, int]],
    hidden: str,
    intervals: list[tuple[int, int]],
) -> Census:
    """A PDF's census (`auditing.pdf`). Its text has no blank line between two entries, so an
    entry is told apart only by its number: the first line of the list opens one, and a line
    opens the next only where it starts with the number after the last, "2." or "[2]" after
    1, in the form the first entry's number has.

    The entries are not told apart (`UNTOLD`) where the list's first line carries no number,
    where an entry holds more than one DOI or more than one PMID, or where a line in the list's
    own form opens with a number above the next one (an entry left out, or a number carried onto
    a line of its own), and `Census.untold` says why. A line after one that ends in a hyphen or
    a dash goes on that entry ("112-" then "118. doi..." is a page range wrapped). Each
    identifier is then looked up alone, as an entry of its own, so that a retracted work among
    them is asked about, one that ends a line among them (`Entry.ends_line`); and no citation
    is held to an entry, nor to the count of entries.

    In a list whose entries are told apart, a DOI or a PMID that ends a line its entry goes on
    after may go on on the next line, cut by the wrap: it is not looked up, and is listed as
    such (`Census.unsent`), rather than sent cut and reported unregistered. So is one cut
    before its suffix, "10.1016/" or "doi:" alone at a line's end, which is never read as
    one."""
    said = {"cites": bool(markers_in(hidden, intervals)) or cites_by_number(hidden, spans),
            "named": cited_names(hidden, hidden)}  # fmt: skip
    if not spans:
        return Census(path, note="no reference list was found under a heading, so none was "
                      "counted", **said)  # fmt: skip
    lines = text.split("\n")
    found: list[tuple[int | None, list[tuple[int, str]]]] = []
    census = Census(path, **said)
    for start, end in spans:
        expected: int | None = None
        form: tuple[bool, str] | None = None
        first = True
        for index in range(start + 1, min(end, len(lines))):
            line = lines[index]
            if not line.strip():
                continue
            if not first and found[-1][1][-1][1].rstrip().endswith(_RANGE_OPEN):
                # A line that ends in a hyphen or a dash never ends an entry: "112-" then
                # "118. doi..." is a page range wrapped, neither an entry nor a skip. The line
                # before is the entry's last, with or without a blank line between.
                found[-1][1].append((index + 1, line))
                continue
            numbered = _NUMBERED_ENTRY.match(line)
            number = int(numbered.group(1) or numbered.group(2)) if numbered else None
            shape = (bool(numbered.group(1)), numbered.group(4) or "") if numbered else None
            if first or (number is not None and number == expected and shape == form):
                first = False
                found.append((number, [(index + 1, line)]))
                expected = number + 1 if number is not None else None
                form = shape
                continue
            if (number is not None and expected is not None and shape == form
                    and number > expected and not census.untold):  # fmt: skip
                census.untold = (f"its numbers go from {expected - 1} to {number}, at line "
                                 f"{index + 1}: an entry left out, or a number of the entry "
                                 "before carried onto a line of its own")  # fmt: skip
            found[-1][1].append((index + 1, line))
    if not census.untold and any(number is None for number, _parts in found):
        census.untold = "its first entry carries no number, so none is told from the next"
    entries: list[Entry] = []
    for number, parts in found:
        held = _identifiers_of(parts)
        dois = [said for _at, said, kind, _ends in held if kind == "doi"]
        pmids = [said for _at, said, kind, _ends in held if kind == "pmid"]
        if not census.untold and (len(dois) > 1 or len(pmids) > 1):
            census.untold = (f"entry {number} holds more than one "
                             f"{'DOI' if len(dois) > 1 else 'PMID'}")  # fmt: skip
        entries.append(Entry(f"entry {number}" if number is not None else "an entry",
                             parts[0][0], number=number,
                             text=" ".join(" ".join(line for _at, line in parts).split())))
    census.markers = len(markers_in(hidden, intervals))
    census.unsent = [(at, said) for _number, parts in found for at, said in _cut_short(parts)]
    if census.untold:
        # One "entry" for each identifier, at its line, so that each is asked about, the one
        # that ends a line among them.
        census.style = UNTOLD
        census.entries = tuple(
            Entry(f"the {'DOI' if kind == 'doi' else 'PMID'} {said} of the list", at,
                  dois=(said,) if kind == "doi" else (), pmids=(said,) if kind == "pmid" else (),
                  text=said, ends_line=ends)
            for _number, parts in found for at, said, kind, ends in _identifiers_of(parts))
        return census
    told = []
    for entry, (_number, parts) in zip(entries, found, strict=True):
        held = _identifiers_of(parts)
        census.unsent += [(at, said) for at, said, _kind, ends in held if ends]
        told.append(replace(entry, dois=tuple(s for _a, s, k, e in held if k == "doi" and not e),
                            pmids=tuple(s for _a, s, k, e in held if k == "pmid" and not e),
                            held_back=any(ends for *_said, ends in held)
                            or bool(_cut_short(parts))))  # fmt: skip
    census.entries = tuple(told)
    if told:
        census.style = NUMBERED
        census.problems = _held_to_numbers(path, told, markers_in(hidden, intervals),
                                           _sentences(hidden, intervals))  # fmt: skip
    return census


def _identifiers_of(parts: list[tuple[int, str]]) -> list[tuple[int, str, str, bool]]:
    """Each DOI and PMID typed in an entry's lines, `(line, identifier, kind, ends a line)`,
    once each: whether it ends a line the entry goes on after, where it may go on on the
    next."""
    found: list[tuple[int, str, str, bool]] = []
    seen: set[str] = set()
    for at, (line_at, line) in enumerate(parts):
        last = at == len(parts) - 1
        for pattern, kind in ((_DOI, "doi"), (_PMID, "pmid")):
            for match in pattern.finditer(line):
                said = (_trimmed(normal_doi(match.group(0))).lower() if kind == "doi"
                        else match.group(1))  # fmt: skip
                if not said or said in seen:
                    continue
                seen.add(said)
                ends = not last and not line[match.end():].strip(" .,;")
                found.append((line_at, said, kind, ends))
        # "PMID:" at a line's end, its digits beginning the next line of the entry.
        if not last and _PMID_AT_END.search(line):
            next_at, after = parts[at + 1]
            digits = _goes_on("pmid", after)
            if digits and digits.group(0).strip() not in seen:
                said = digits.group(0).strip()
                seen.add(said)
                ends = at + 1 < len(parts) - 1 and not after[digits.end():].strip(" .,;")
                found.append((next_at, said, "pmid", ends))
    return found


#: What a line that ends a page range ends with, which no entry ends with.
_RANGE_OPEN = ("-", "\N{EN DASH}", "\N{EM DASH}")
#: A line that ends with "PMID", its PMID on the next.
_PMID_AT_END = re.compile(r"\bPMID\s*:?\s*$", re.IGNORECASE)
#: What begins the next line where an identifier is introduced at a line's end: the DOI after
#: "doi:" or a DOI link's prefix, the digits after "PMID:".
_GOES_ON = {"doi": re.compile(r"\s*10\.\d{4,9}"), "pmid": re.compile(r"\s*\d{1,9}\b")}
#: An identifier cut before it starts: a DOI's prefix and its slash, or "doi:" or "PMID:",
#: with nothing after it on its line.
_CUT_SHORT = re.compile(
    r"(?:\b10\.\d{4,9}(?:\.\d+)*/|https?://(?:dx\.)?doi\.org/|\b(?:doi|pmid)\s*:?)\s*$",
    re.IGNORECASE,
)


def _cut_short(parts: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Each identifier an entry's line ends before its first character, `(line, as read)`:
    no DOI or PMID is read of it, and it is listed as not looked up rather than dropped. A
    "doi:", a DOI link's prefix or a "PMID:" whose identifier begins the next line of the
    entry is none: that line's identifier is read there (NLM breaks at the space in "doi:
    10...")."""
    cut = []
    for index, (at, line) in enumerate(parts):
        found = _CUT_SHORT.search(line.rstrip(" .,;"))
        if found is None:
            continue
        said = found.group(0).strip()
        kind = "pmid" if said.lower().startswith("pmid") else "doi"
        after = parts[index + 1][1] if index + 1 < len(parts) else ""
        if not said.startswith("10.") and _goes_on(kind, after):
            continue
        cut.append((at, said))
    return cut


def _goes_on(kind: str, after: str) -> re.Match[str] | None:
    """The identifier beginning `after`, the line after its "doi:" or "PMID:". An entry's own
    number ("4." in a list whose entries are not told apart) is not a PMID's digits."""
    if kind == "pmid" and _NUMBERED_ENTRY.match(after):
        return None
    return _GOES_ON[kind].match(after)


def _numbered_by_word(
    entries: list[Entry], numbering: Mapping[int, tuple[str, bool, int]]
) -> bool:
    """Whether Word numbers the list 1, 2, 3 by place: its entries, none typing a number,
    each numbered in one count that prints Arabic numerals from 1, and no paragraph with
    words above the list numbered in that count (`word_numbering`: the same abstract
    numbering and level, or the same numbering where it restarts the level). What is
    compared is the count only: a paragraph above in another count, or empty, is not looked
    at (round 2 of #463). A bracketed number in the text is no sign of it: `range [0, 100]`
    in an author-year paper made every entry "cited nowhere" (round 1 of #463)."""
    if not entries or any(entry.number is not None for entry in entries):
        return False
    keys = {numbering.get(entry.line, ("", False, 0))[:2] for entry in entries}
    if len(keys) != 1:
        return False
    ((key, from_one),) = keys
    first = entries[0].line
    return bool(key) and from_one and not any(
        line < first and numbered[0] == key for line, numbered in numbering.items()
    )


def _held_to_numbers(
    path: Path, entries: list[Entry], markers: list[tuple[int, str, list[int]]],
    sentences: list[str] | tuple = (), *, uncited: bool = False,
) -> list[Problem]:
    """What is wrong between a numbered list's `entries` and the text's bracketed citations,
    `markers`: each citation of a number the list does not hold, and, where there is a
    citation, each entry none names. With none, each entry is reported only where the text
    cites nothing by number and no author of the list with a year (`uncited`,
    `cites_by_number`, `cites_by_author`), and the message says so: its key is the one an
    entry no citation names has."""
    numbers = {entry.number for entry in entries}
    highest = max((number for number in numbers if number is not None), default=0)
    problems = []
    cited: set[int] = set()
    held = f"{len(numbers)} entr{'y' if len(numbers) == 1 else 'ies'}, the last {highest}"
    for index, (line, written, cites) in enumerate(markers):
        sentence = sentences[index] if index < len(sentences) else None
        cited.update(cites)
        missing = [number for number in dict.fromkeys(cites) if number not in numbers]
        if missing:
            which = ", ".join(map(str, missing)) if len(missing) < 4 else (
                f"{missing[0]} to {missing[-1]}")  # fmt: skip
            problems.append(Problem(
                "citation-beyond-list",
                f"{written} cites {'entry' if len(missing) == 1 else 'entries'} {which}, which "
                f"the reference list does not hold: it has {held}", line, path, written,
                sentence,
            ))  # fmt: skip
    if markers:
        seen: set[int] = set()
        for entry in entries:
            if entry.number not in cited and entry.number not in seen:
                seen.add(entry.number)
                problems.append(Problem(
                    "entry-never-cited", f"{entry.label} of the reference list is cited "
                    "nowhere in the text", entry.line, path, entry.label,
                ))  # fmt: skip
    elif uncited:
        seen = set()
        for entry in entries:
            if entry.number not in seen:
                seen.add(entry.number)
                problems.append(Problem(
                    "entry-never-cited", f"{entry.label} of the reference list is cited "
                    "nowhere in the text, which cites nothing by number: no number in "
                    "brackets, raised as a superscript or in parentheses, none after a "
                    "word's stop, no link whose text is a number, no note's mark or "
                    "citation field, and no author of the list cited with a year",
                    entry.line, path, entry.label,
                ))  # fmt: skip
    return sorted(problems, key=lambda problem: problem.line or 0)


def _typed(body: str) -> str:
    """A `\\bibitem`'s text as typed, its comments and the `\\end{thebibliography}` after the
    last entry left out, its lines joined."""
    kept = "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in body.split("\n"))
    kept = re.sub(r"\\end\s*\{thebibliography\}.*", "", kept, flags=re.DOTALL)
    return " ".join(kept.split())


def census_of_latex(path: Path, files: list[tuple[Path, Any]]) -> Census:
    """A LaTeX document's census, its files given as their paths and their `Source`s: the
    `\\bibitem`s of its `thebibliography`, held to the keys its citation commands name."""
    entries: list[Entry] = []
    cited: list[tuple[Path, int, str, str]] = []
    for where, source in files:
        text, reading = source.text, source.reading
        for start, end in reading.references:
            items = list(_BIBITEM.finditer(text, start, end))
            for index, item in enumerate(items):
                stop = items[index + 1].start() if index + 1 < len(items) else end
                body = text[item.end() : stop]
                dois, pmids = identifiers(body)
                key = item.group(1).strip()
                entries.append(Entry(
                    f"\\bibitem{{{key}}}", text.count("\n", 0, item.start()) + 1, key=key,
                    dois=dois, pmids=pmids, path=where, text=_typed(body),
                ))  # fmt: skip
        cited += [(where, text.count("\n", 0, use.offset) + 1, use.key, placed(text, use.offset))
                  for use in reading.cited]  # fmt: skip
    if not entries:
        note = ("no thebibliography was found: a list BibTeX or biber makes from a .bib is "
                "not read, so none was counted") if cited else "no reference list was found"
        return Census(path, note=note, cites=bool(cited))
    census = Census(path, tuple(entries), style=KEYED, markers=len(cited), cites=bool(cited))
    keys = {entry.key for entry in entries}
    every = any(key == "*" for _where, _line, key, _sentence in cited)
    named = {key for _where, _line, key, _sentence in cited}
    for where, line, key, sentence in cited:
        if key != "*" and key not in keys:
            census.problems.append(Problem(
                "citation-not-listed", f"\\cite{{{key}}} names no \\bibitem of the list",
                line, where, key, sentence,
            ))  # fmt: skip
    if not every:
        census.problems += [
            Problem("entry-never-cited", f"{entry.label} is cited nowhere in the text",
                    entry.line, entry.path or path, entry.label)
            for entry in entries if entry.key not in named
        ]  # fmt: skip
    return census


# ----------------------------------------------------------------------------- looking up


@dataclass(frozen=True)
class Looked:
    """What was asked of the registries for one entry, or would be, and what they said;
    `path` is the census's, and the entry's own file is `entry.path` where it has one."""

    path: Path
    entry: Entry
    asked: str
    problems: tuple[Problem, ...] = ()
    #: Where the record came from: "asked", "kept" (the cache), or "" for a dry run.
    came: str = ""
    #: Whether a registry asked knows the work: one found its DOI or its PMID.
    known: bool = False
    #: What each registry answered, by its name (`lookup.run.look_up`'s `sources`): the
    #: title, the year, the authors and the journal the cited-sentences table and the
    #: self-citation count read. Empty for a dry run.
    answers: Mapping[str, Any] = field(default_factory=dict, compare=False)
    #: Whether the entry gave no DOI, and Crossref's search by its title found the one asked
    #: about (`auditing.by_title`).
    by_title: bool = False


#: Who is asked of a DOI, in turn: DataCite only where Crossref does not know it, and doi.org
#: only where DataCite does not either (`lookup.run.look_up`).
DOI_REGISTRIES = "Crossref and OpenAlex, then DataCite and doi.org where Crossref has no record,"
#: The codes of a DOI or a PMID no registry knows, as `check`'s G7 gives them.
UNKNOWN = ("doi-unregistered", "pmid-unknown")


def _asked(entry: Entry) -> str:
    parts = []
    if entry.dois:
        parts.append(f"{DOI_REGISTRIES} for doi:{entry.dois[0]}")
    if entry.pmids:
        parts.append(f"PubMed for PMID {entry.pmids[0]}")
    return "; ".join(parts)


#: Under this share of the searched words of the title an entry gives, its DOI's record is
#: another work's (Basile, 2026-11-26, item 7b: "warn on few shared words").
TITLE_SHARE = 0.5
#: The fewest searched words a title is compared by, as few as a title is searched by
#: (`by_title`): fewer say too little of a work to tell it from another.
TITLE_WORDS = 3
#: A "title" that is no title but a citation's tail read wrong: one holding a link or a DOI,
#: or a year in brackets with a volume and pages, "J Exp Med (1996) 184:1845-56". On 100 PMC
#: papers (2026-11-27) the entry's reader took such a tail for the title of 10 entries.
_NO_TITLE = re.compile(
    r"(?i)https?://|\bdoi\b|\b10\.\d{4,9}/|\(\d{4}\)\s*\d+\s*(?:\(\d+\)\s*)?[:,]\s*\d+"
)
#: A tag of a registry's title, "<i>", taken out as a space: Crossref keeps
#: "Recombinant<i>Mycobacterium", whose words ran together with the tags taken out.
_TAG = re.compile(r"<[^<>]{1,40}>")
#: The languages an entry says its title was translated from, as PubMed marks it, "[Article
#: in Spanish]", or as a list does, "(in Japanese with English abstract)".
LANGUAGES = ("Afrikaans", "Albanian", "Arabic", "Armenian", "Basque", "Belarusian", "Bengali",
             "Bosnian", "Bulgarian", "Catalan", "Chinese", "Croatian", "Czech", "Danish",
             "Dutch", "Estonian", "Farsi", "Finnish", "French", "Galician", "Georgian",
             "German", "Greek", "Hebrew", "Hindi", "Hungarian", "Icelandic", "Indonesian",
             "Irish", "Italian", "Japanese", "Kazakh", "Korean", "Latvian", "Lithuanian",
             "Macedonian", "Malay", "Mongolian", "Norwegian", "Persian", "Polish",
             "Portuguese", "Romanian", "Russian", "Serbian", "Slovak", "Slovenian", "Spanish",
             "Swahili", "Swedish", "Tamil", "Thai", "Turkish", "Ukrainian", "Urdu",
             "Vietnamese", "Welsh")  # fmt: skip
_LANGUAGE = "(?:" + "|".join(LANGUAGES) + ")"
_OR_ENGLISH = "(?:" + "|".join((*LANGUAGES, "English")) + ")"
_JOINED = r"(?:,| and| or) "
#: An entry that says its title is a translation: the registry holds the title in the
#: language the work was written in, which shares no words with it. One work may be in two,
#: "[Article in German, French]" (round 1 of #846), English among them where another is
#: named, "[Article in English, Portuguese]" (round 2).
_TRANSLATED = re.compile(
    rf"(?i)[\[(](?:article |text )?in (?:{_OR_ENGLISH}{_JOINED})*{_LANGUAGE}"
    rf"(?:{_JOINED}{_OR_ENGLISH})*(?:,? with (?:an )?English abstract)?[\])]"
)
#: What the check was worth on 100 PMC papers (2026-11-27): 1 of the 6 notes judged by two
#: readers was right; the others gave a work's title in translation. A note, then, and never
#: a warning (Basile, 2026-11-27: under half right, "a note, with that record shown").
TITLE_RECORD = ("On 100 published papers, 1 of the 6 such notes judged was right; most of the "
                "others gave the title in translation, which this check cannot tell from "
                "another work's.")


def _worded(title: str) -> list[str]:
    """A title's searched words with a letter in them: a volume and pages read as a title,
    "184:1845-56", is three searched words and no word at all (2026-11-27)."""
    from manuscript_guard.gates.searched import search_words

    return [word for word in search_words(title) if any(c.isalpha() for c in word)]


def _found_at(words: list[str], part: list[str]) -> int | None:
    """Where `part` stands in `words`, word for word, or None."""
    return next((at for at in range(len(words) - len(part) + 1)
                 if words[at:at + len(part)] == part), None)  # fmt: skip


def _gives_record_title(text: str, title: str, records: list[str]) -> bool:
    """Whether an entry holds a record's title, with its subtitle, word for word, folded as a
    title search folds them, outside the `title` its reader took it to give: it names that
    work where its reader took another part of it for the title. In a list that puts the
    title between commas, "Z.C. Dong, Y. Chen, Transcriptomics: advances and approaches,
    Sci. China Life Sci. 56 (2013)", the reader took "China Life Sci" for its title
    (2026-11-27). Within the title read it is never looked for: a title that holds the
    record's and words of another work is held to the record like any other (round 1 of
    #846). A record's title of too few words to tell a work by is never looked for."""
    from manuscript_guard.gates.searched import folded_words

    read = folded_words(title)
    outside, rest = [], folded_words(text)
    # Each place the title read stands is cut out, should the entry give it twice (round 2).
    while read and (at := _found_at(rest, read)) is not None:
        outside.append(rest[:at])
        rest = rest[at + len(read):]
    outside.append(rest)
    for record in records:
        if len(_worded(record)) < TITLE_WORDS:
            continue
        words = folded_words(record)
        if any(_found_at(part, words) is not None for part in outside):
            return True
    return False


def _with_subtitle(title: str, records: list[str]) -> bool:
    """Whether the title read is one of `records`, a colon and words the record does not
    hold: "Statin therapy and fracture risk: a cohort of older women", whose record is
    "Statin therapy and fracture risk" (round 2 of #846). `_title_differs` gives each record's
    title alone and with its subtitle, so that the words after the colon may be the record's
    subtitle given otherwise, or none it holds (round 5). Each colon is tried, for a
    record whose own title holds one, "COVID-19: lessons learned" (round 3). A record's title
    of too few words to tell a work by is never taken for it."""
    from manuscript_guard.gates.searched import folded_words

    mains = [folded_words(title[:at]) for at, sign in enumerate(title) if sign == ":"]
    return any(len(_worded(record)) >= TITLE_WORDS and folded_words(record) in mains
               for record in records)  # fmt: skip


def _title_differs(
    entry: Entry, answers: dict[str, Any], path: Path | None, style: str
) -> list[Problem]:
    """A real DOI with another work's title, the commonest fabricated citation: each record
    Crossref and OpenAlex hold for the entry's DOI is of a work whose title, with its
    subtitle, holds under half the searched words (`gates.searched.search_words`) of the
    title the entry gives, read as a title search reads it (`by_title.cited`), and none is
    it exactly (`by_title._same_title`). Its first reading must have enough words to tell a
    work by; each longer one, read on past a full stop, is tried too, against each record
    alone, and the reading and the record that share the most are said, so that a longer
    reading can only clear an entry: one that runs on into the journal's name never makes a
    finding of its own. Nor does an entry that holds a record's title word for word outside
    the title read, gives a record's title with a subtitle it does not hold, or says its
    title is a translation. A note (`TITLE_RECORD`)."""
    from manuscript_guard.auditing.by_title import _same_title, _text, cited
    from manuscript_guard.gates.searched import search_words
    from manuscript_guard.lookup.sources import FOUND

    records = [answers[name] for name in ("crossref", "openalex")
               if isinstance(answers.get(name), dict) and answers[name].get("status") == FOUND
               and answers[name].get("title")]  # fmt: skip
    # Read as a title search reads an entry: its number, its emphasis and its TeX off. A
    # list whose entries cannot be told apart has no title to read (`UNTOLD`).
    text = _text(entry, style) if entry.dois and entry.text and style != UNTOLD else None
    said = cited(text) if text is not None else None
    if not records or said is None or any(_same_title(said, record) for record in records):
        return []
    if (len(_worded(said.title)) < TITLE_WORDS or _NO_TITLE.search(said.title)
            or _TRANSLATED.search(text)):  # fmt: skip
        return []
    whole = [_TAG.sub(" ", ": ".join(str(t) for t in (record.get("title"), record.get("subtitle"))
                                      if t)) for record in records]  # fmt: skip
    titles = [_TAG.sub(" ", str(record["title"])) for record in records]
    # The title alone and with its subtitle: Crossref keeps "COVID-19" and "lessons learned"
    # apart (round 4 of #846).
    if _gives_record_title(text, said.title, whole) or _with_subtitle(said.title, titles + whole):
        return []
    # Each record alone, so that the title the finding quotes is the one its words were
    # counted in (round 1 of #846: counted in both, one quoted, the count was not its own).
    best: tuple[int, int, str, str] | None = None
    for record in whole:
        held = set(search_words(record))
        for title in dict.fromkeys((said.title, *said.titles)):
            words = _worded(title)
            if len(words) < TITLE_WORDS:
                continue
            shared = sum(word in held for word in words)
            if best is None or shared * best[1] > best[0] * len(words):
                best = (shared, len(words), title, record)
    if best is None or best[0] >= TITLE_SHARE * best[1]:
        return []
    shared, total, title, record = best
    return [Problem(
        "reference-title-differs",
        f'{entry.label}: its DOI {entry.dois[0]} is of a work titled "{record}", which has '
        f'{shared} of the {total} searched words of the title given, "{title}"',
        entry.line, path, entry.label, severity=INFO, hint=TITLE_RECORD,
    )]  # fmt: skip


def _unknown(entry: Entry, answers: dict[str, Any], path: Path | None) -> list[Problem]:
    """A DOI every registry asked of it says it does not hold, and a PMID PubMed does not:
    a typo, most often, and no check of the work at all (`gates.lookups._identity`)."""
    from manuscript_guard.lookup.sources import ABSENT

    said = {name: answer.get("status") for name, answer in answers.items()
            if isinstance(answer, dict)}  # fmt: skip
    problems = []
    if entry.ends_line:
        # Perhaps cut by the wrap: not found as printed is all that can be said.
        if "crossref" in said and all(said.get(name) == ABSENT
                                      for name in ("crossref", "datacite", "doi_org")):  # fmt: skip
            problems.append(Problem("not-found-as-printed", f"{entry.label}: no registry has "
                                    f"the DOI {entry.dois[0]} as printed{_may_run_on(entry)}",
                                    entry.line, path, f"{entry.label} doi"))  # fmt: skip
        if said.get("pubmed") == ABSENT:
            problems.append(Problem("not-found-as-printed", f"{entry.label}: PubMed has no PMID "
                                    f"{entry.pmids[0]} as printed{_may_run_on(entry)}",
                                    entry.line, path, f"{entry.label} pmid"))  # fmt: skip
        return problems
    if "crossref" in said and all(said.get(name) == ABSENT
                                  for name in ("crossref", "datacite", "doi_org")):  # fmt: skip
        problems.append(Problem(
            "doi-unregistered", f"{entry.label}: no registry has the DOI {entry.dois[0]}: not "
            "Crossref, not DataCite, not doi.org, so nothing was checked of the work",
            entry.line, path, entry.label,
        ))  # fmt: skip
    if said.get("pubmed") == ABSENT:
        problems.append(Problem(
            "pmid-unknown", f"{entry.label}: PubMed has no PMID {entry.pmids[0]}, so nothing "
            "was checked of the work", entry.line, path, entry.label,
        ))  # fmt: skip
    return problems


def _may_run_on(entry: Entry) -> str:
    """What is said with each answer about an identifier that ends a line with more of its
    list after it, where it may run on to the next."""
    if not entry.ends_line:
        return ""
    return ("; it ends a line, with more of the list after it, and may run on to the next, so "
            "the registry may have been asked about part of it")


def _kept_name(entry: Entry) -> str:
    named = [f"doi_{entry.dois[0]}"] if entry.dois else []
    named += [f"pmid_{entry.pmids[0]}"] if entry.pmids else []
    return re.sub(r"[^A-Za-z0-9._-]", "_", "__".join(named)) + ".json"


def _read_kept(path: Path, wanted: dict[str, str]) -> dict[str, Any] | None:
    """A record kept before for the same identifiers, or None."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("identifiers") != wanted:
        return None
    return record if isinstance(record.get("sources"), dict) else None


def look_up(
    censuses: list[Census],
    *,
    dry_run: bool = False,
    cache: Path | None = None,
    transport: Callable | None = None,
    services: Any = None,
    credentials: Any = None,
    today: date | None = None,
    pacer: Any = None,
) -> list[Looked]:
    """Each entry with a DOI or a PMID, asked of the registries, or with `dry_run` only what
    would be asked. A record is written into `cache` and read from it, never elsewhere."""
    from manuscript_guard.auditing.progress import step
    from manuscript_guard.lookup import run
    from manuscript_guard.lookup.http import default_transport

    services = services or run.Services()
    credentials = credentials or run.Credentials.from_environment(None)
    ask = run._asker(transport or default_transport, pacer or run.Pacer(), credentials)
    asking = _Asking(ask, services, credentials, today or date.today(), cache, dry_run)
    wanted = [(census.path, entry, census.style) for census in censuses
              for entry in census.entries if entry.dois or entry.pmids]  # fmt: skip
    looked: list[Looked] = []
    for path, entry, style in wanted:
        # How many of the entries looked up are done, for a reader who waits (`progress`).
        step("lookup", len(looked), len(wanted))
        looked.append(_looked_up(path, entry, asking, style=style))
    return looked


@dataclass(frozen=True)
class _Asking:
    """What every entry is asked with: the transport that paces, where, the credentials,
    the day, the folder kept, and whether only what would be asked is said."""

    ask: Callable
    services: Any
    credentials: Any
    today: date
    cache: Path | None
    dry_run: bool


def _looked_up(path: Path, entry: Entry, asking: _Asking, *, asked: str = "",
               by_title: bool = False, style: str | None = None) -> Looked:  # fmt: skip
    """One entry with a DOI or a PMID, asked of the registries; `asked` what is said before
    the registries, for a DOI found by the entry's title. `style` is its list's, by which its
    title is read for `_title_differs`; given none, the title is not compared."""
    from manuscript_guard.gates.lookups import _standing
    from manuscript_guard.lookup import run

    asked = asked + _asked(entry)
    if asking.dry_run:
        return Looked(path, entry, asked, by_title=by_title)
    wanted = {k: v for k, v in (("doi", entry.dois[:1]), ("pmid", entry.pmids[:1])) if v}
    wanted = {k: v[0] for k, v in wanted.items()}
    cache = asking.cache
    kept = cache / _kept_name(entry) if cache is not None else None
    record = _read_kept(kept, wanted) if kept is not None and kept.exists() else None
    came = "kept"
    if record is None:
        came = "asked"
        planned = run.Planned(entry.label, doi=wanted.get("doi"), pmid=wanted.get("pmid"))
        record = run.look_up(planned, asking.ask, asking.services, asking.credentials,
                             asking.today, by_doi=False)  # fmt: skip
        run._never_kept(record, asking.credentials)
        # An answer that did not come is asked for again, never kept as one.
        if kept is not None and not _unanswered(record):
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text(json.dumps(record, indent=2, ensure_ascii=True) + "\n",
                            encoding="utf-8")  # fmt: skip
    answers = record.get("sources", {})
    where = entry.path or path
    found = _standing(entry.label, {}, answers, where, None)
    problems = tuple(
        Problem(f.code, f.message.removeprefix("@") + _may_run_on(entry), entry.line, where,
                entry.label)
        for f in found
    ) + tuple(_unknown(entry, answers, where)) + tuple(
        () if by_title or style is None else _title_differs(entry, answers, where, style)
    ) + tuple(
        Problem("lookup-unanswered", f"{entry.label}: {name} did not answer ({why})",
                entry.line, where, f"{entry.label} {name}")
        for name, why in _unanswered(record)
    )  # fmt: skip
    known = any(isinstance(answer, dict) and answer.get("status") == "found"
                for answer in answers.values())  # fmt: skip
    return Looked(path, entry, asked, problems, came, known, answers, by_title)


def _unanswered(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Each registry that gave no answer, and why: a check that did not happen is said."""
    from manuscript_guard.lookup.sources import UNRESOLVABLE

    return [
        (name, str(answer.get("why", "no reason given")))
        for name, answer in record.get("sources", {}).items()
        if isinstance(answer, dict) and answer.get("status") == UNRESOLVABLE
    ]
