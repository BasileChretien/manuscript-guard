"""G7: text the manuscript repeats from its authors' earlier papers, judged as the norms for
text recycling judge it, before the journal's similarity check finds it.

A journal puts each submission through a similarity check (Crossref Similarity Check, which
is iThenticate), whose report shows every run of words the manuscript shares with a published
paper, its authors' own included. Reuse of an author's own words in a new paper is text
recycling (Text Recycling Research Project, "Text recycling: best practices for researchers",
V1.1, 2021). The norms say where it may stand: a standard description of a method may be
reused in the Methods where the earlier paper is cited, and overlap in the results,
discussion or conclusions is unlikely to be acceptable (COPE and BioMed Central, "Text
recycling guidelines for editors"); the journal's policy decides.

So each earlier output that `literature/related.yaml` lists as sharing authors with this
paper (`shares: [authors]`, the list G8 holds the paper's numbers to) is read from its stored
copy, `literature/sources/<citekey>.*`, on this machine and nowhere else, and the manuscript
is compared with it as runs of words. A word is a run of letters and digits, in
lower case; a hyphen or an apostrophe inside it, or a hyphen where a line breaks, joins its
parts ("drug-\\ninduced" is "druginduced", as "drug-induced" is); and a number is no word,
so that a binding, a reference's number and a figure updated since are no difference. Each
run of eight words the earlier paper has in the same order marks its words shared; shared
words next to each other are one passage, and so are two runs a few words apart that are a
few words apart in the earlier paper too, so that a word changed here and there does not
hide the sentence it is in. A passage of twelve shared words or more is reported, with its
lines, its section and where the earlier paper has it.

Not compared: the front matter, the headings, listings, tables and the reference list. Words
in quotation marks are quoted, not recycled: a passage that is mostly quoted is shown apart.
The statements a journal asks for (funding, competing interests, ethics, data availability
and their like) are the same from one paper to the next: they are compared, and a passage in
one is a note.

What a passage is, by where it stands:

* `recycled-methods-cited` (note): in the Methods, with the earlier paper cited in the same
  paragraph. Never more than a note.
* `recycled-text` (a note while drafting, a warning from internal-review): anywhere else, or
  in the Methods with no citation of the earlier paper beside it. Never a failure.
* `recycled-quotation` (note): a passage in quotation marks.
* `recycled-statement` (note): a passage under a heading whose whole title names a statement
  a journal asks for, outside the Results.
* `recycled-earlier-version` (note): one for each preprint, abstract or protocol of this
  same study (`kind: preprint`, `abstract` or `protocol`, `shares: [study, ...]`) the
  manuscript repeats, however much it repeats. Reuse of one's own preprint is commonly
  accepted where it is disclosed, and a results paper is expected to repeat its protocol's
  methods.
* `earlier-output-not-compared` (note): an earlier output with no citation key, or no stored
  copy that can be read.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.gates.quotations import _KEY, _QUOTED
from manuscript_guard.literature.related import Output, load_related
from manuscript_guard.literature.sources import (
    PDF_SUFFIXES,
    UnreadableSource,
    read_in_reading_order,
    stored_files,
)
from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, stage_index
from manuscript_guard.text.blocks import find_headings
from manuscript_guard.text.latex.printed import QUOTE_CLOSE, QUOTE_OPEN
from manuscript_guard.text.masking import blank_comments, fenced_blocks, front_matter_end, mask
from manuscript_guard.text.reader import LATEX, manuscript_format
from manuscript_guard.text.section_names import (
    methods_sections,
    names_abstract,
    names_conclusion,
    names_results,
    plain,
)
from manuscript_guard.text.sections import split_sections

GATE = "G7"
#: The run of words, in the same order, that marks words as shared.
SHINGLE = 8
#: The fewest shared words a passage holds for it to be reported.
SHARED = 12
#: The most words a passage may differ by, here or in the earlier paper, between two runs.
GAP = 3

#: What joins two parts of one word: a hyphen, also where a line breaks after it (a PDF
#: hyphenates), a soft hyphen, an en dash, and an apostrophe, straight or curly.
_JOINERS = "-\N{SOFT HYPHEN}\N{HYPHEN}\N{NON-BREAKING HYPHEN}\N{EN DASH}"
_APOSTROPHES = "'\N{RIGHT SINGLE QUOTATION MARK}"
_WORD = re.compile(
    rf"[^\W_]+(?:(?:[{_JOINERS}][ \t]*\r?\n[ \t]*|[{_JOINERS}{_APOSTROPHES}])[^\W_]+)*"
)
_JOINS = re.compile(rf"[{_JOINERS}{_APOSTROPHES}\s]")
#: Where no passage may run across, and whose words are not compared.
_APART = "\x01"
#: A line of a table: pipes, or a grid table's rule.
_TABLE_LINE = re.compile(r"^[ \t]*(?:\||\+[-=:+]+)[^\n]*", re.MULTILINE)
#: A line of a block quotation.
_BLOCK_QUOTE = re.compile(r"^[ \t]{0,3}>[^\n]*", re.MULTILINE)
#: Where a LaTeX document's view opens or closes a quotation marked with a command.
_MARKED = re.compile(f"[{QUOTE_OPEN}{QUOTE_CLOSE}]")


def _marked(seen: str) -> list[tuple[int, int]]:
    """Each outermost quotation a LaTeX document marks with a command, as its view writes it:
    one inside another is the outer's (round 2 of step 13)."""
    spans, depth, opened = [], 0, 0
    for found in _MARKED.finditer(seen):
        if found.group() == QUOTE_OPEN:
            opened = found.start() if depth == 0 else opened
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                spans.append((opened, found.end()))
    return spans
#: A quotation in single curly marks; a closing mark before a letter is an apostrophe.
_SINGLE_QUOTED = re.compile(
    "\N{LEFT SINGLE QUOTATION MARK}"
    r"(?:[^\N{RIGHT SINGLE QUOTATION MARK}\n]|\N{RIGHT SINGLE QUOTATION MARK}(?=[^\W_])"
    r"|\n(?![ \t]*\n))+?\N{RIGHT SINGLE QUOTATION MARK}(?![^\W_])"
)
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")

_INTRODUCTION = re.compile(r"(?:introduction|background|rationale)\b", re.IGNORECASE)
_DISCUSSION = re.compile(r"(?:discussion|interpretation|comment)\b", re.IGNORECASE)
#: The names of the statements a journal asks for, and of the lists, that are the same from
#: paper to paper.
_STATEMENT_NAMES = (
    r"(?:"
    r"funding(?:\s+(?:sources?|information))?|sources?\s+of\s+funding|(?:financial\s+)?support"
    r"|financial\s+disclosures?|sponsors?(?:hip)?"
    r"|role\s+of\s+the\s+(?:funders?|sponsors?|funding\s+sources?)"
    r"|(?:declarations?\s+of\s+)?(?:competing|conflicting)\s+interests?"
    r"|(?:potential\s+)?conflicts?\s+of\s+interests?|declarations?(?:\s+of\s+interests?)?"
    r"|declarations?\s+of\s+(?:the\s+use\s+of\s+)?generative\s+ai\b[\w\s-]*"
    r"|disclosures?(?:\s+of\s+interests?)?|acknowledge?ments?"
    r"|data\s+(?:availability|sharing|access)"
    r"|availability\s+of\s+(?:data(?:\s+and\s+materials?)?|materials?)"
    r"|(?:code|software|materials?)\s+availability"
    r"|ethics(?:\s+(?:committee\s+)?approval)?"
    r"|ethical(?:\s+(?:approval|considerations|standards|aspects))?"
    r"|(?:informed\s+|patient\s+)?consent(?:\s+(?:for|to)\s+(?:publication|participate))?"
    r"|patient\s+and\s+public\s+involvement|provenance\s+and\s+peer\s+review"
    r"|authors?['\N{RIGHT SINGLE QUOTATION MARK}]?\s+contributions?|contributors(?:hip)?"
    r"|credit(?:\s+author(?:ship)?)?(?:\s+contributions?)?|transparency"
    r"|(?:list\s+of\s+)?abbreviations|statements?\s+and\s+declarations?"
    r"|additional\s+contributions|article\s+information"
    r")(?:\s+(?:statements?|declarations?|disclosures?|section))?"
)
#: A statement's heading: its whole title names one or several, "Funding", "Data
#: availability statement", "Ethics approval and consent to participate", "Funding/Support",
#: "CRediT author statement". A title that only opens with such a word is the paper's own
#: matter: "Funding sources of the included trials", "Data sharing in pharmacovigilance".
_STATEMENTS = re.compile(
    rf"(?:the\s+)?{_STATEMENT_NAMES}"
    rf"(?:\s*(?:,\s*(?:and\b)?|;|&|/|\band\b)\s*{_STATEMENT_NAMES})*\W*$",
    re.IGNORECASE,
)
#: The reference list, which a similarity check is asked to leave out, and this check does.
_REFERENCES = re.compile(r"(?:references|bibliography|(?:literature|works)\s+cited)\W*$",
                         re.IGNORECASE)  # fmt: skip
#: A footnote's mark in a heading, which is no part of its title.
_FOOTNOTE_MARK = re.compile(r"\[\^[^\]\n]*\]")
#: A supplement's heading that names a part and nothing else: "Supplementary discussion",
#: "Online methods", JAMA's "eResults", whose "e" is a small letter before a capital. The
#: whole title, so that "Online discussion forums" or "eConsent" names no part (round 8 of
#: the review: a prefix taken off any heading read "Online discussion forums" under the
#: Methods as the Discussion).
_SUPPLEMENT_PART = re.compile(
    r"(?:(?i:supplement(?:ary|al)|online)\s+|e(?=[A-Z]))(?P<part>(?i:introduction|background"
    r"|rationale|methods|results(?:\s+and\s+discussion)?|findings|interpretation"
    r"|discussion(?:\s+and\s+conclusions?)?|conclusions?|concluding\s+remarks))"
    r"(?:\s+[0-9]+[A-Za-z]?)?\W*$"  # JAMA numbers them: "eResults 1" (round 9)
)

METHODS = "methods"
INTRODUCTION = "introduction"
RESULTS = "results"
DISCUSSION = "discussion"
CONCLUSION = "conclusion"
ABSTRACT = "abstract"
#: A statement a journal asks for: compared, and reported as a note.
STATEMENT = "statement"
#: A part of the paper no heading names.
UNNAMED = ""
#: The reference list: not compared.
SET_APART = "set apart"
#: Parts counted as another when a heading over several is taken for a title over the
#: paper: the conclusions are the Discussion's (round 4 of the review).
_COUNTED_AS = {CONCLUSION: DISCUSSION}

_SHOWN = {
    METHODS: "the Methods",
    INTRODUCTION: "the Introduction",
    RESULTS: "the Results",
    DISCUSSION: "the Discussion",
    CONCLUSION: "the Conclusions",
    ABSTRACT: "the abstract",
    UNNAMED: "a part of the paper no heading names",
}


@dataclass(frozen=True)
class Word:
    """A word as compared, and where it stands in the text it was read from."""

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Passage:
    """Words of the manuscript the earlier paper has in the same order."""

    #: The shared words, first to last, as the manuscript has them.
    shared: tuple[Word, ...]
    #: Where the earlier paper has the first of them.
    source_at: int


@dataclass(frozen=True)
class Recycled:
    """A passage the gate reports, and what it knows of where it stands."""

    first_line: int
    last_line: int
    #: Where the passage starts and ends in the manuscript file, as characters.
    start: int
    end: int
    shared: int
    quoted: int
    kind: str
    cited: bool
    source_at: int
    excerpt: str


def words(text: str) -> list[Word]:
    """The words of `text` as they are compared: in lower case, their joints taken out, and
    no number among them, nor a number's digits at a word's end, which is where a PDF puts a
    reference's number, "risk12" or "risk\N{SUPERSCRIPT TWO}"; "COVID-19" is "covid" on
    both sides, which compares the same."""
    found = []
    for match in _WORD.finditer(text):
        word = _JOINS.sub("", match.group()).casefold()
        while word and word[-1].isdigit():
            word = word[:-1]
        if word:
            found.append(Word(word, match.start(), match.end()))
    return found


def _segments(prepared: str) -> list[list[Word]]:
    """The words of a prepared text in runs that nothing set apart stands inside."""
    runs: list[list[Word]] = [[]]
    for word in words(prepared):
        if runs[-1] and _APART in prepared[runs[-1][-1].end : word.start]:
            runs.append([])
        runs[-1].append(word)
    return [run for run in runs if run]


def shared_passages(segments: Sequence[Sequence[Word]], source: Sequence[Word]) -> list[Passage]:
    """Every passage of `segments` that `source` has too, however short."""
    texts = [word.text for word in source]
    index: dict[tuple[str, ...], int] = {}
    for at in range(len(texts) - SHINGLE + 1):
        index.setdefault(tuple(texts[at : at + SHINGLE]), at)
    found: list[Passage] = []
    for segment in segments:
        said = [word.text for word in segment]
        aligned: dict[int, int] = {}
        for at in range(len(said) - SHINGLE + 1):
            there = index.get(tuple(said[at : at + SHINGLE]))
            if there is not None:
                for step in range(SHINGLE):
                    aligned.setdefault(at + step, there + step)
        found.extend(_joined(segment, aligned, source))
    return found


def _joined(
    segment: Sequence[Word], aligned: dict[int, int], source: Sequence[Word]
) -> list[Passage]:
    """Shared words next to each other as one passage, and two runs apart by at most `GAP`
    words here and by at most `GAP` more there as one too."""
    runs: list[list[int]] = []
    for at in sorted(aligned):
        if runs:
            last = runs[-1][-1]
            skipped, moved = at - last - 1, aligned[at] - aligned[last]
            if skipped == 0 or (skipped <= GAP and 1 <= moved <= GAP + 1):
                runs[-1].append(at)
                continue
        runs.append([at])
    return [
        Passage(tuple(segment[at] for at in run), source[aligned[run[0]]].start) for run in runs
    ]


def _kind_of(title: str, is_methods: bool, abstract_title: str | None) -> str | None:
    """The part of the paper a heading names, where it names one, a supplement's as the
    main text's: "Supplementary discussion" and "eResults" name the Discussion and the
    Results (round 7 of the review: they named none, and a passage there was given the
    advice for text under no heading)."""
    shown = _FOOTNOTE_MARK.sub("", plain(title)).strip()
    supplement = _SUPPLEMENT_PART.match(shown)
    if supplement:
        shown = supplement["part"]
    if names_abstract(shown, abstract_title):
        return ABSTRACT
    if names_results(shown):
        return RESULTS
    if names_conclusion(shown):
        return CONCLUSION
    if _DISCUSSION.match(shown):
        return DISCUSSION
    if _INTRODUCTION.match(shown):
        return INTRODUCTION
    if _REFERENCES.match(shown):
        return SET_APART
    if _STATEMENTS.match(shown):
        return STATEMENT
    return METHODS if is_methods else None


def _part_of(chain: Sequence[str | None]) -> str:
    """The part of the paper under a chain of headings, outermost first: the reference
    list's, set apart; a statement's where one of them names a statement and the outermost
    that names a part is not the Results, "Ethics approval" under the Methods as much as
    "Funding" at the end or under the Discussion, whose theme headings "Data sharing" or
    "Consent" are the Results' own; otherwise the one the outermost that names a part names.

    A statement's text is compared and reported as a note, never set apart (Basile,
    2026-10-21, after four rounds of the review found headings read wrong both ways: each
    one set apart by mistake hid recycled text). A heading read wrong now turns a warning
    into a note at worst."""
    if SET_APART in chain:
        return SET_APART
    named = [part for part in chain if part is not None]
    outermost = next((part for part in named if part != STATEMENT), None)
    if STATEMENT in named and outermost != RESULTS:
        return STATEMENT
    return outermost or UNNAMED


def _parts(text: str, abstract_title: str | None) -> list[tuple[int, int, str]]:
    """Each heading's start, the end of its line, and the part of the paper under it: the
    one the outermost heading over it names, as "Methods" over "Statistical analysis". A
    heading over headings that name two parts or more is a title over the paper, and names
    none: "# Background rates of liver injury" over its Methods and its Results. A
    statement's heading is not counted as a part: "Methods" over "Statistical methods" and
    "Ethics approval" is the Methods (round 2 of the review); and conclusions are counted with
    the Discussion: "Discussion" over "Interpretation" and "Conclusions" is the Discussion
    (round 4)."""
    methods = {section.line for section in methods_sections(split_sections(text), abstract_title)}
    headings = find_headings(text)
    named = [
        _kind_of(h.title, text.count("\n", 0, h.start) + 1 in methods, abstract_title)
        for h in headings
    ]
    for index, heading in enumerate(headings):
        under = set()
        for later, kind in zip(headings[index + 1 :], named[index + 1 :], strict=True):
            if later.level <= heading.level:
                break
            under.add(_COUNTED_AS.get(kind, kind))
        if len(under - {None, SET_APART, STATEMENT}) >= 2:
            named[index] = None
    parts: list[tuple[int, int, str]] = []
    chain: list[tuple[int, str | None]] = []
    for heading, own in zip(headings, named, strict=True):
        while chain and chain[-1][0] >= heading.level:
            chain.pop()
        chain.append((heading.level, own))
        kind = _part_of([part for _level, part in chain])
        ends = text.find("\n", heading.start)
        if ends != -1 and heading.setext:
            ends = text.find("\n", ends + 1)
        parts.append((heading.start, len(text) if ends == -1 else ends, kind))
    return parts


def _prepared(text: str, parts: list[tuple[int, int, str]]) -> str:
    """`text` as it is compared: what `mask` hides gone, and set apart what no passage may
    run across and whose words are not compared."""
    shown = list(mask(text))
    apart = [(0, front_matter_end(text))]
    apart += [(fence.start, fence.end) for fence in fenced_blocks(text)]
    apart += [(match.start(), match.end()) for match in _TABLE_LINE.finditer(text)]
    for index, (start, ends, kind) in enumerate(parts):
        apart.append((start, ends))
        if kind == SET_APART:
            following = parts[index + 1][0] if index + 1 < len(parts) else len(text)
            apart.append((start, following))
    for start, end in apart:
        shown[start:end] = _APART * (end - start)
    return "".join(shown)


def _quoted_spans(seen: str) -> list[tuple[int, int]]:
    """Where the manuscript quotes, as spans none of which overlaps another: in double
    marks, straight or curly, in single curly marks, and in a block quotation; in a LaTeX
    document's view, also where LaTeX marks a quotation with a command (round 1 of step
    13)."""
    spans = sorted(
        [
            *((m.start(), m.end())
              for pattern in (_QUOTED, _SINGLE_QUOTED, _BLOCK_QUOTE)
              for m in pattern.finditer(seen)),
            *_marked(seen),
        ]
    )  # fmt: skip
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _inside(spans: list[tuple[int, int]], offset: int) -> bool:
    at = bisect_right(spans, (offset, len(spans) + 2**62)) - 1
    return at >= 0 and spans[at][0] <= offset < spans[at][1]


def _cites(seen: str, key: str, first: int, last: int) -> bool:
    """Whether the paragraphs a passage stands in cite `key`."""
    breaks = [0, *(m.end() for m in _PARAGRAPH_BREAK.finditer(seen)), len(seen)]
    start = breaks[max(0, bisect_right(breaks, first) - 1)]
    end = breaks[min(len(breaks) - 1, bisect_right(breaks, last))]
    return key in _KEY.findall(seen[start:end])


@dataclass(frozen=True)
class _Manuscript:
    """A manuscript file as it is compared, read once for every copy it is compared with."""

    text: str
    parts: list[tuple[int, int, str]]
    #: The text with its comments blanked, where quotations and citations are read.
    seen: str
    quotes: list[tuple[int, int]]
    segments: list[list[Word]]


def _read(text: str, abstract_title: str | None) -> _Manuscript:
    parts = _parts(text, abstract_title)
    seen = blank_comments(text)
    segments = _segments(_prepared(text, parts))
    return _Manuscript(text, parts, seen, _quoted_spans(seen), segments)


def recycled_in(
    text: str, source: str, key: str, abstract_title: str | None = None
) -> list[Recycled]:
    """The passages of a manuscript file, `text`, that an earlier paper, `source`, has too,
    each with its part of the paper and whether it is cited: those with `SHARED` words or
    more outside quotation marks, and those with as many inside them."""
    return _recycled(_read(text, abstract_title), words(source), key)


def _recycled(read: _Manuscript, source: Sequence[Word], key: str) -> list[Recycled]:
    starts = [start for start, _ends, _kind in read.parts]
    found: list[Recycled] = []
    for passage in shared_passages(read.segments, source):
        quoted = sum(_inside(read.quotes, word.start) for word in passage.shared)
        if max(quoted, len(passage.shared) - quoted) < SHARED:
            continue
        first, last = passage.shared[0], passage.shared[-1]
        at = bisect_right(starts, first.start) - 1
        found.append(
            Recycled(
                first_line=read.text.count("\n", 0, first.start) + 1,
                last_line=read.text.count("\n", 0, last.start) + 1,
                start=first.start,
                end=last.end,
                shared=len(passage.shared),
                quoted=quoted,
                kind=read.parts[at][2] if at >= 0 else UNNAMED,
                cited=_cites(read.seen, key, first.start, last.end),
                source_at=passage.source_at,
                excerpt=" ".join(
                    read.text[first.start : last.end]
                    .replace(QUOTE_OPEN, "")
                    .replace(QUOTE_CLOSE, "")
                    .split()
                ),
            )
        )
    return found


#: The kinds of earlier output that are this paper's study in an earlier form, where it
#: shares the study: the norms count reuse of one's own preprint as accepted when disclosed,
#: and a results paper repeats its protocol's methods (Basile, 2026-10-21, round 1).
EARLIER_VERSIONS = ("preprint", "abstract", "protocol")


def own_outputs(project: Project) -> tuple[Path | None, list[Output]]:
    """The earlier outputs `literature/related.yaml` lists as sharing authors with this
    paper, and where the list is. G8 says what is wrong with a list it cannot read."""
    related, _report = load_related(project)
    if related is None:
        return None, []
    return related.path, [output for output in related.outputs if "authors" in output.shares]


def earlier_version(output: Output) -> bool:
    """Whether an earlier output is this paper's study in an earlier form."""
    return output.kind in EARLIER_VERSIONS and "study" in output.shares


def check_recycling(project: Project, stage: str = DRAFTING) -> Report:
    """A finding for each passage the manuscript repeats from an earlier output of its
    authors, one for each earlier version of this paper it repeats, and a note for each
    earlier output that could not be compared."""
    from manuscript_guard.gates.journal import abstract_title, text_recycling

    listed, outputs = own_outputs(project)
    if listed is None or not outputs:
        return Report()
    stored = project.path("literature") / "sources"
    due = stage_index(stage) >= stage_index(INTERNAL_REVIEW)
    named, policy = abstract_title(project), text_recycling(project)
    folder = project.path("manuscript")
    manuscript = _manuscript(folder, named)
    report, compared, reported = Report(), 0, 0
    for output in outputs:
        key = output.citekey
        copies, unread = _copies(stored, key) if key else ([], [])
        if not copies:
            report = report.with_findings(_not_compared(listed, output, unread))
            continue
        compared += 1
        texts = dict(copies)
        read = [(copy, words(source)) for copy, source in copies]
        found = [
            _placed(folder, where, copy, passage)
            for where, prepared in manuscript
            for copy, passage in _kept(
                (copy, passage)
                for copy, source in read
                for passage in _recycled(prepared, source, key)
            )
        ]
        reported += len(found)
        if earlier_version(output):
            if found:
                report = report.with_findings(_repeats_a_version(listed, output, found, texts))
            continue
        for path, copy, passage in found:
            report = report.with_findings(
                _finding(path, key, copy, texts[copy], passage, due, policy)
            )
    return report.with_counts(earlier_outputs_compared=compared, recycled_passages=reported)


def _manuscript(folder: Path, named: str | None) -> list[tuple[object, _Manuscript]]:
    """Each manuscript file, read for the passages it repeats. A LaTeX manuscript's documents
    are read as they print (`printed_of`), the main text and the supplement, with its
    headings as Markdown's and a citation `[@key]`; a passage is placed back at its `.tex`
    file by `_placed` (step 13)."""
    if manuscript_format(folder) != LATEX:
        return [(path, _read(read_text(path), named)) for path in source_files(folder)]
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import read_document

    views = []
    for part in (False, True):
        sources = [source for source in read_document(folder, supplementary=part).sources
                   if not source.path.lower().endswith(".sty")]  # fmt: skip
        # A file nothing inputs is compared on its own, as G2 reads it (round 1 of step 13):
        # a supplement with no `main.tex` is all such files.
        views.append(printed([s for s in sources if not s.loose], compared=True))
        views += [printed([source], compared=True) for source in sources if source.loose]
    return [(view, _read(view.text, named)) for view in views if view.text.strip()]


def _placed(
    folder: Path, where: object, copy: Path, passage: Recycled
) -> tuple[Path, Path, Recycled]:
    """A passage with the file and the lines it is typed on: a Markdown file's own, or, for
    a LaTeX document's printed view, the `.tex` file its first word is typed in, and the
    lines there of its first word and, in that file, its last (step 13)."""
    if isinstance(where, Path):
        return where, copy, passage
    first = where.place(passage.start)
    if first is None:
        from manuscript_guard.text.latex.structure import ENTRY

        return folder / ENTRY, copy, passage
    source, line = first
    last = where.place(max(passage.end - 1, passage.start))
    end = last[1] if last is not None and last[0] is source else line
    return folder / source.path, copy, replace(passage, first_line=line, last_line=end)


def _copies(stored: Path, key: str) -> tuple[list[tuple[Path, str]], list[str]]:
    """Every stored copy of an earlier output that can be read, with its text, and why each
    other could not be."""
    copies, unread = [], []
    for path in stored_files(stored, key):
        try:
            copies.append((path, read_in_reading_order(path)))
        except (UnreadableSource, OSError) as exc:
            unread.append(str(exc))
    return copies, unread


def _kept(found) -> list[tuple[Path, Recycled]]:
    """One passage for each place in the manuscript, where several copies of one output
    hold it: the one that shares the most words. Places are compared by their characters,
    so that two passages on one line are two (round 1 of the review: by lines, a quotation
    and a recycled sentence after it on the same line were one)."""
    kept: list[tuple[Path, Recycled]] = []
    for copy, passage in sorted(found, key=lambda pair: -pair[1].shared):
        if not any(
            passage.start < other.end and other.start < passage.end for _copy, other in kept
        ):
            kept.append((copy, passage))
    return sorted(kept, key=lambda pair: (pair[1].start, pair[1].end))


def _where(copy: Path, source: str, at: int) -> str:
    """Where a copy has a passage: its page for a PDF, which is the PDF's own count and not
    the number printed on the page, and its line otherwise."""
    if copy.suffix.lower() in PDF_SUFFIXES:
        return f"page {source.count(chr(12), 0, at) + 1} of {copy.name}"
    return f"line {source.count(chr(10), 0, at) + 1} of {copy.name}"


def _finding(
    path: Path,
    key: str,
    copy: Path,
    source: str,
    passage: Recycled,
    due: bool,
    policy: str | None,
) -> Finding:
    lines = (
        f"line {passage.first_line}"
        if passage.first_line == passage.last_line
        else f"lines {passage.first_line}-{passage.last_line}"
    )
    where = _where(copy, source, passage.source_at)
    said = f"{lines} repeat {passage.shared} words of @{key} ({where})"
    shown = _shown(passage.excerpt)
    journal = f" The journal's policy: {_shown(policy)}." if policy else ""
    unquoted = passage.shared - passage.quoted
    if unquoted < SHARED:
        return Finding(
            gate=GATE,
            code="recycled-quotation",
            severity=INFO,
            message=f"{said}, in quotation marks: {shown}",
            path=path,
            line=passage.first_line,
            hint="a quotation is not recycled text; a similarity check still shows it, so "
            f"cite @{key} where it is quoted",
        )
    if passage.kind == METHODS and passage.cited:
        return Finding(
            gate=GATE,
            code="recycled-methods-cited",
            severity=INFO,
            message=f"{said}, in the Methods, which cite it there: {shown}",
            path=path,
            line=passage.first_line,
            hint="a standard description may be reused in the Methods when the earlier paper is "
            "cited (TRRP 2021; COPE); say so in the covering letter, since the journal's "
            "similarity check will show it." + journal,
        )
    if passage.kind == STATEMENT:
        return Finding(
            gate=GATE,
            code="recycled-statement",
            severity=INFO,
            message=f"{said}, in a statement the journal asks for: {shown}",
            path=path,
            line=passage.first_line,
            hint="a funding, ethics or competing-interests statement is often the same from one "
            "paper to the next, and the journal's similarity check will show it; keep it if it "
            "is still true of this paper",
        )
    return Finding(
        gate=GATE,
        code="recycled-text",
        severity=WARN if due else INFO,
        message=f"{said}, in {_SHOWN.get(passage.kind, _SHOWN[UNNAMED])}: {shown}",
        path=path,
        line=passage.first_line,
        hint=_advice(passage, key) + journal + ("" if due else " A warning from internal-review."),
    )


def _advice(passage: Recycled, key: str) -> str:
    """What the norms say of a passage, by where it stands."""
    if passage.kind == METHODS:
        return (
            f"a standard description may be reused in the Methods when the earlier paper is "
            f"cited (TRRP 2021; COPE): cite @{key} in this paragraph and say so in the "
            f"covering letter, or write it afresh"
        )
    if passage.kind in (RESULTS, DISCUSSION, CONCLUSION, ABSTRACT):
        return (
            "overlap with an earlier paper in the results, discussion or conclusions is "
            "unlikely to be acceptable (COPE), and the abstract is this paper's own: write it "
            "afresh"
        )
    return (
        f"whether background may be reused is the journal's to say (TRRP 2021): write it "
        f"afresh, or cite @{key} and say so in the covering letter"
    )


def _repeats_a_version(
    listed: Path, output: Output, found: list[tuple[Path, Path, Recycled]], texts: dict
) -> Finding:
    """One note for an earlier version of this paper, however much of it is repeated."""
    path, copy, first = found[0]
    shared = sum(passage.shared for _path, _copy, passage in found)
    passages = "1 passage" if len(found) == 1 else f"{len(found)} passages"
    return Finding(
        gate=GATE,
        code="recycled-earlier-version",
        severity=INFO,
        message=f"{passages}, {shared} words in all, repeat the {output.kind} @{output.citekey}, "
        f"an earlier output of this study: the first at {path.name}:{first.first_line} "
        f"({_where(copy, texts[copy], first.source_at)})",
        path=listed,
        line=output.line,
        hint="a paper may repeat its own study's preprint, abstract or protocol where it says "
        "so (TRRP 2021): cite it, name it in the covering letter, and read the journal's "
        "policy on preprints",
    )


def _not_compared(listed: Path, output: Output, unread: list[str]) -> Finding:
    key = output.citekey
    if key is None:
        why = "it has no citation key to name its stored copy by"
        hint = "give it its citekey from references.bib, and store your own copy under it"
    else:
        why = "; ".join(unread) if unread else f"no copy is stored as literature/sources/{key}.*"
        hint = (
            f"store your own copy as literature/sources/{key}.pdf (or .txt, .html): it is "
            "read on this machine and sent nowhere"
        )
    return Finding(
        gate=GATE,
        code="earlier-output-not-compared",
        severity=INFO,
        message=f"the earlier output {output.name} was not compared with the manuscript's "
        f"text: {why}",
        path=listed,
        line=output.line,
        hint=hint,
    )


def _shown(text: str) -> str:
    return repr(text if len(text) <= 80 else text[:77] + "...")
