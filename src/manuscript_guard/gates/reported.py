"""G8: a number the Abstract or a conclusion gives that the paper reports nowhere else.

An abstract summarises the paper, and a conclusion what it found: neither introduces data. A
results key bound in one of them, and bound nowhere in the Methods or the Results, nor
printed in a table or drawn in a figure the manuscript places, is a number a reader of the
paper cannot find in it. Nothing said so: G2 holds a binding to the analysis wherever it
stands, and G8's other check compares the results with themselves.

So each key the Abstract or a conclusion binds is looked for where the paper reports:

- bound in a section the gates read as the Methods (`methods_sections`), whose summary the
  abstract's own Methods are, or in one whose heading opens with "Results" or "Findings";
- or, where the paper has no such Results heading, as a narrative review or a case report
  has none, bound in a section that names no part of the paper that does not report: not
  the abstract or a box, the Introduction or Background, the Discussion, a conclusion, a
  limitation, a statement of the back matter or the reference list;
- or a key declared the same quantity (`same_as`, either way) bound there;
- or bound anywhere in the supplement, which reports what the paper has no room for;
- or its display printed in a table, or in the text of a figure, that a manuscript file
  places.

A box the journal's profile asks for (`boxes:`, highlights or key points) is read as a
summary too: under its heading, and in LaTeX in its environment (`text/boxes.py`).

Where none holds, a warning names the key and the heading it was given under. The last
route matches a display and not a key, so a coincidence can keep the warning back; DESIGN.md's
Known gaps carries that and the rest.

A summary can also give the number and claim more than the Results do: drop their "may",
say "increased" where they said "associated with". So each sentence of a summary that binds
a key is held to the sentences of a Results section, of the main text or of the supplement,
that bind it or a key declared the same quantity (`summary-claim-stronger`, a warning): the
words that set how strongly a sentence claims are compared as `communicate check` compares a
post with the paper (`claims.compare_pair`). The warning is given only where the summary
claims more than every one of them (Basile, D3.2 of 2026-11-06), a negation gone or new
counted as claiming more, as `communicate check` counts it. A Results sentence that holds no
word of the claim lists states its number and leaves the claim to the sentences round it, so
it is not compared; a summary sentence that holds none is held only to the hedges and limits
it dropped, since a negation it leaves out does not turn the claim round ("no association
(HR 1.02)" against "HR 1.02"; Basile, 2026-11-07), and a word of the ladder takes its claim
with it. A sentence binding several keys is held to the Results sentences of all of them
together. Against a Results sentence that also gives a result the summary sentence does not,
only a word of the ladder the summary moves up is read: its hedges, limits and negations may
be about that other result ("associated with A but not with B" against "associated with A";
Basile, 2026-11-07). A key the Results bind in no sentence, given only in the Methods, a table
or a figure, is compared with nothing.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard import claims
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.text.boxes import box_of, environment_spans
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.section_names import (
    methods_sections,
    names_conclusion,
    names_discussion,
    names_introduction,
    names_methods,
    names_results,
    names_statement,
    plain,
)
from manuscript_guard.text.sections import Section, scannable, split_sections, subsections

GATE = "G8"
CODE = "summary-not-reported"
CLAIM_CODE = "summary-claim-stronger"
#: What `claims.compare_pair` may say of a summary sentence that holds a word of the claim
#: lists against a Results sentence for it to claim more (`_more_than`).
_MORE = frozenset({claims.STRONGER, claims.NEGATION})
#: A heading of the supplement over its Results: "Results" or "Findings" as the main text's
#: are read (`names_results`), after a label of the supplement's own, "S3.", "Appendix 2:",
#: Wiley's "Appendix S1:", JAMA's "Supplement 1." or "eResults", "Supplementary",
#: "Additional".
_SUPPLEMENT_RESULTS = re.compile(
    r"(?:(?:e?appendix|supplement|s)\s*s?\d+[a-z]?\s*[.:]?\s*)?"
    r"(?:(?:supplementa(?:ry|l)|additional)\s+|e(?=results?\b|findings\b))?"
    r"(?:results?|findings)\b",
    re.IGNORECASE,
)

#: Where a section's keys are reported, as against summarised or neither.
REPORTED = object()
#: Where a section's keys are reported if the paper has no Results: under headings that name
#: no part of it, as a narrative review's "Regulatory responses" or a case report's "Case
#: presentation".
TOPICAL = object()
#: The opening of a paper. A heading over one of these or over the Methods is the paper's
#: title written as a heading over the whole paper, and names no part of it. Not over the
#: abstract: where the profile calls it "Summary", a "Summary" under the Results is one.
_OPENING = re.compile(r"(?:introduction|background)\W*$", re.IGNORECASE)


#: Where a key was looked for, as the warning says it, with a Results section and without.
_NOWHERE = "reported nowhere in the Methods, the Results, a table or a figure"
_NOWHERE_WITHOUT_RESULTS = (
    "bound in no section that reports, nor shown in a table or a figure: with no Results "
    "section, every section reports but the abstract, a box, the Introduction, the "
    "Discussion, a conclusion and the back matter"
)


@dataclass(frozen=True)
class Given:
    """A results key bound in a summary: the Abstract or a conclusion, under `heading`."""

    key: str
    heading: str
    line: int
    #: Where in the text read the binding starts, which places a LaTeX finding at its `.tex`
    #: line and is no part of what was given.
    start: int = field(default=0, compare=False)
    #: The sentence the binding stands in, as typed, and where it starts in the text read,
    #: which tells the bindings of one sentence from those of the next: what is held to the
    #: Results sentences that bind the same key (`summary-claim-stronger`).
    sentence: str = field(default="", compare=False)
    opens: int = field(default=-1, compare=False)


@dataclass(frozen=True)
class Stated:
    """A results key bound in a sentence of a Results section: the sentence as typed, and the
    line and the offset in the text read where the binding stands."""

    key: str
    sentence: str
    line: int
    start: int = field(default=0, compare=False)


def _sentences_of(text: str) -> Callable[[int], tuple[int, str]]:
    """Where the sentence an offset of `text` stands in starts, and the sentence as typed, as
    `claims` cuts a manuscript's sentences; (-1, "") for an offset in none, as a binding on a
    line with no word. The text is cut once, when the first offset is asked for: a file that
    binds no result is not cut."""
    cut: list[list] = []

    def sentence(offset: int) -> tuple[int, str]:
        if not cut:
            found = claims.sentence_spans(text)
            cut.extend((found, [start for start, _first, _end in found]))
        spans, starts = cut
        index = bisect_right(starts, offset) - 1
        if index < 0 or offset >= spans[index][2]:
            return -1, ""
        _start, first, end = spans[index]
        return first, text[first:end].strip()

    return sentence


def supplement_stated(text: str) -> list[Stated]:
    """The results keys one file of the supplement binds in its Results, each with its
    sentence: under a heading `_SUPPLEMENT_RESULTS` reads, "Supplementary results",
    "eResults 2", the innermost heading that names the Methods or the Results deciding, since
    a supplement often has "Supplementary methods" over all of it, its results among them."""
    sections = [section for section in split_sections(scannable(text)) if section.level]
    starts, inside = [0], [False]
    chain: list[Section] = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        chain.append(section)
        starts.append(section.line)
        named = next((one for one in reversed(chain)
                      if names_methods(one.title) or _names_supplement_results(one.title)),
                     None)  # fmt: skip
        inside.append(named is not None and _names_supplement_results(named.title))
    sentence_at = _sentences_of(text)
    found = []
    for placeholder in parse(text)[0]:
        if placeholder.namespace != "results":
            continue
        if not inside[bisect_right(starts, placeholder.line) - 1]:
            continue
        _opens, sentence = sentence_at(placeholder.start)
        found.append(Stated(placeholder.key, sentence, placeholder.line, placeholder.start))
    return found


def _names_supplement_results(title: str) -> bool:
    return _SUPPLEMENT_RESULTS.match(plain(title)) is not None


@dataclass
class Walk:
    """The headings a reader is under, carried from one file of the paper into the next as
    G14 carries them, and which of the sections met so far report and which summarise.

    `named` is what the journal's profile calls the abstract where it is not "Abstract";
    `boxes` the boxes it asks for, whose headings summarise; and `boxed`, where it is given,
    the title of the box an offset of the text is in, or None, for a box a heading does not
    open (a LaTeX environment)."""

    named: str | None = None
    boxes: list = field(default_factory=list)
    boxed: Callable[[int], str | None] | None = None
    chain: list[Section] = field(default_factory=list)
    reports: set[int] = field(default_factory=set)
    summaries: set[int] = field(default_factory=set)
    #: Every section met, kept so that the identity `reports` and `summaries` hold for each
    #: is not given to a section of a later file once the first is freed (round 1 of #272).
    kept: list[Section] = field(default_factory=list)
    #: The sections named the Results, of `reports`; whether one of them was met where the
    #: paper reports, outside the abstract and every box; the sections that name a part of the
    #: paper that reports nothing; those over the abstract, the opening or the Methods, which
    #: are the paper's title written as a heading and name no part; and the keys bound under
    #: headings that name no part (TOPICAL).
    results: set[int] = field(default_factory=set)
    has_results: bool = False
    elsewhere: set[int] = field(default_factory=set)
    titles: set[int] = field(default_factory=set)
    topical: set[str] = field(default_factory=set)
    #: Each results key bound in a Results section of the files read so far, with its
    #: sentence, in the order read.
    stated: list[Stated] = field(default_factory=list)

    def read(self, text: str) -> tuple[list[Given], set[str]]:
        """The results keys `text` binds in a summary, and those it binds where the paper
        reports them. Those it binds in a Results section are kept in `stated`, with their
        sentences, as each summary's binding is kept with its sentence."""
        starts, places, results = self._placed(
            [section for section in split_sections(scannable(text)) if section.level])
        sentence_at = _sentences_of(text)
        given: list[Given] = []
        reported: set[str] = set()
        for placeholder in parse(text)[0]:
            if placeholder.namespace != "results":
                continue
            opens, sentence = sentence_at(placeholder.start)
            boxed = self.boxed(placeholder.start) if self.boxed is not None else None
            if boxed is not None:
                given.append(Given(placeholder.key, boxed, placeholder.line, placeholder.start,
                                   sentence, opens))  # fmt: skip
                continue
            at = bisect_right(starts, placeholder.line) - 1
            place = places[at]
            if place is REPORTED:
                reported.add(placeholder.key)
                if results[at]:
                    self.stated.append(Stated(placeholder.key, sentence, placeholder.line,
                                              placeholder.start))  # fmt: skip
            elif place is TOPICAL:
                self.topical.add(placeholder.key)
            elif place is not None:
                given.append(Given(placeholder.key, place, placeholder.line, placeholder.start,
                                   sentence, opens))  # fmt: skip
        return given, reported

    def reported_without_results(self) -> set[str]:
        """The keys bound under headings that name no part of the paper, read as reported
        where the paper has no Results: none once a Results heading has been met where the
        paper reports, in this file or an earlier one. Asked once every file is read."""
        return set() if self.has_results else set(self.topical)

    def placing(self, sections: list[Section]) -> Callable[[int], object]:
        """Where each line of one file stands, given its headings in order, each with its
        level and its line: the title of the summary it is in, REPORTED, TOPICAL, or None
        for none of these. What `read` places a binding by, and the audit's Abstract against Results
        a number by, its sections read from a Word document's heading styles or a LaTeX
        document's printed view as well as from Markdown (`auditing.abstract`)."""
        starts, places, _results = self._placed(sections)
        return lambda line: places[bisect_right(starts, line) - 1]

    def _placed(self, sections: list[Section]) -> tuple[list[int], list[object], list[bool]]:
        """The line each heading of one file starts on, the place the text under it has, and
        whether that text is in a Results section: one the paper's Results heading decides."""
        self.kept += sections
        self._name(sections)
        starts, places, results = [0], [self._place()], [self._in_results()]
        for section in sections:
            while self.chain and self.chain[-1].level >= section.level:
                self.chain.pop()
            self.chain.append(section)
            starts.append(section.line)
            places.append(self._place())
            results.append(self._in_results())
            if id(section) in self.results and places[-1] is REPORTED:
                self.has_results = True
        return starts, places, results

    def _name(self, sections: list[Section]) -> None:
        """Which sections of one file report and which summarise. A Results or a conclusion
        heading over the opening of the paper is the paper's title, and is neither."""
        methods = {id(section) for section in methods_sections(sections, self.named)}
        self.reports |= methods
        for index, section in enumerate(sections):
            below = subsections(sections, index)[1:]
            # Over an "Abstract", the paper's title names no part either; not over the title
            # a profile gives the abstract, where a "Summary" may be a section's own.
            if any(other.names_abstract(None) for other in below):
                self.titles.add(id(section))
            if any(self._opens(other, methods) for other in below):
                self.titles.add(id(section))
                continue
            if box_of(section.title, self.boxes) is not None:
                self.summaries.add(id(section))
            elif names_results(section.title):
                self.reports.add(id(section))
                self.results.add(id(section))
            elif names_conclusion(section.title):
                self.summaries.add(id(section))
            elif id(section) not in methods | self.titles and self._reports_nothing(section):
                self.elsewhere.add(id(section))

    def _opens(self, section: Section, methods: set[int]) -> bool:
        return bool(_OPENING.match(plain(section.title))) or id(section) in methods

    def _reports_nothing(self, section: Section) -> bool:
        """Whether a heading names a part of the paper that reports nothing, by the names
        the other gates read them by: the abstract, the Introduction or Background (G7's),
        the Discussion, a section G2 and G9 rule out as the Methods ("Limitations",
        "Interpretation"), a statement of the back matter (G7's) or the reference list."""
        from manuscript_guard.classify import rules_out_methods

        title = section.title
        return (section.names_abstract(self.named) or names_introduction(title)
                or names_discussion(title) or rules_out_methods(title)
                or names_statement(title) or section.is_references)  # fmt: skip

    def _place(self) -> object:
        """What the text under the current headings is: the title of the summary it is in,
        REPORTED, TOPICAL or None. The outermost heading that names a part decides: the
        abstract's own "Results" summarise, and a "Summary" under the Results is theirs, even
        where the profile calls the abstract "Summary". Text under headings none of which
        names a part, the paper's title apart, is TOPICAL: a review's own sections, which
        report where the paper has no Results; under the Discussion, say, it is None."""
        for section in self.chain:
            if section.names_abstract(self.named) or id(section) in self.summaries:
                return section.title
            if id(section) in self.reports:
                return REPORTED
        named = [section for section in self.chain if id(section) not in self.titles]
        if named and not any(id(section) in self.elsewhere for section in named):
            return TOPICAL
        return None

    def _in_results(self) -> bool:
        """Whether the text under the current headings is the Results': the heading that
        decides its place, as `_place` finds it, names them. Not the Methods', nor a Results
        heading's under the Methods, where the Methods decide."""
        for section in self.chain:
            if section.names_abstract(self.named) or id(section) in self.summaries:
                return False
            if id(section) in self.reports:
                return id(section) in self.results
        return False


def check_reported(project: Project, results: Results) -> Report:
    """A warning for each results key a summary gives that the paper reports nowhere else,
    and for each sentence of a summary that claims more than the Results sentences that bind
    its keys."""
    from manuscript_guard.gates.journal import abstract_title, box_rules_of
    from manuscript_guard.text.reader import LATEX, manuscript_format

    root = project.path("manuscript")
    walk = Walk(abstract_title(project), box_rules_of(project))
    if manuscript_format(root) == LATEX:
        given, reported, placed, stated = _latex_read(root, walk)
    else:
        given, reported, placed, stated = _markdown_read(root, walk)
    reported |= walk.reported_without_results()
    same = _same_quantity(results)
    claimed = _claimed(root, given, stated, same)
    reported_as = {same(key) for key in reported}
    missing = [(path, one) for path, one in given if same(one.key) not in reported_as]
    report = Report()
    if not missing:
        return report.with_findings(*claimed)
    shown = _printed(project, results, placed)
    seen: set[tuple[Path, str, str]] = set()
    for path, one in missing:
        value = results.values.get(one.key)
        if value is None or (path, one.key, one.heading) in seen or _shows(shown, value.display):
            continue  # G2 says a key the analysis did not emit
        seen.add((path, one.key, one.heading))
        report = report.with_findings(
            Finding(
                gate=GATE,
                code=CODE,
                severity=WARN,
                message=f"results.{one.key} is given under {plain(one.heading)!r} and "
                + (_NOWHERE if walk.has_results else _NOWHERE_WITHOUT_RESULTS),
                path=path,
                line=one.line,
                hint="report the number where the paper reports its results, a table or a "
                "figure included, and let the summary restate it; a coarser form for the "
                "summary is a second key emitted with same_as",
            )
        )
    return report.with_findings(*claimed)


#: Read: (the summaries' bindings, the keys reported, the tables and figures placed, the
#: Results' bindings), each binding with the file it is typed in.
Read = tuple[list[tuple[Path, Given]], set[str], dict, list[tuple[Path, Stated]]]


def _latex_read(root: Path, walk: Walk) -> Read:
    """A LaTeX manuscript's summaries and reports, read in each document's printed view
    (`text/latex/printed.py`), where a binding is `{{results.key}}` under the headings LaTeX
    prints it under; each summary's binding, and each the Results bind, named at its `.tex`
    file and line (step 8). Its files nothing inputs are not printed, and report nothing."""
    from dataclasses import replace

    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import ENTRY, read_document

    given: list[tuple[Path, Given]] = []
    reported: set[str] = set()
    placed: dict[str, set[str]] = {"table": set(), "figure": set()}
    stated: list[tuple[Path, Stated]] = []
    for supplementary in (False, True):
        sources = [source for source in read_document(root, supplementary=supplementary).sources
                   if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
        view = printed(sources)
        placeholders = parse(view.text)[0]
        for placeholder in placeholders:
            if placeholder.namespace in placed:
                placed[placeholder.namespace].add(placeholder.key)

        def at(one, view=view) -> tuple[Path, int]:
            where = view.place(one.start)
            path, line = (where[0].path, where[1]) if where else (ENTRY, one.line)
            return root / path, line

        if supplementary:
            reported |= {p.key for p in placeholders if p.namespace == "results"}
            for one in supplement_stated(view.text):
                path, line = at(one)
                stated.append((path, replace(one, line=line)))
            continue
        walk.boxed = _boxed_in(view, sources, walk.boxes)
        found, binds = walk.read(view.text)
        for one in found:
            path, line = at(one)
            given.append((path, replace(one, line=line)))
        for one in walk.stated:
            path, line = at(one)
            stated.append((path, replace(one, line=line)))
        reported |= binds
    return given, reported, placed, stated


def _boxed_in(view, sources: list, rules: list) -> Callable[[int], str | None] | None:
    """The title of the box environment an offset of a LaTeX document's printed view stands
    in, read back to the file and the place it was printed from, or None. None in place of
    the function where the document writes no box in its environment."""
    spans = {source.path: environment_spans(source, rules) for source in sources}
    spans = {path: found for path, found in spans.items() if found}
    if not spans:
        return None
    starts = [origin[0] for origin in view.origins]

    def boxed(offset: int) -> str | None:
        index = bisect_right(starts, offset) - 1
        if index < 0:
            return None
        start, source, at, linear = view.origins[index]
        where = at + (offset - start) if linear else at
        return next((title for begin, end, _rule, title in spans.get(source.path, ())
                     if begin <= where < end), None)  # fmt: skip

    return boxed


def _markdown_read(root: Path, walk: Walk) -> Read:
    """A Markdown manuscript's summaries and reports: the paper's files in printed order, the
    headings carried from one into the next, and the supplement's bindings, each reported;
    and the bindings of the Results, the paper's and the supplement's."""
    sources = source_files(root)
    given: list[tuple[Path, Given]] = []
    reported: set[str] = set()
    placed: dict[str, set[str]] = {"table": set(), "figure": set()}
    stated: list[tuple[Path, Stated]] = []
    supplement = [p for p in sources if is_supplementary(root, p)]
    paper = printed_order([p for p in sources if p not in supplement], supplementary=False)
    for path in [*paper, *supplement]:
        text = read_text(path)
        placeholders = parse(text)[0]
        for placeholder in placeholders:
            if placeholder.namespace in placed:
                placed[placeholder.namespace].add(placeholder.key)
        if path in supplement:
            reported |= {p.key for p in placeholders if p.namespace == "results"}
            stated += [(path, one) for one in supplement_stated(text)]
            continue
        before = len(walk.stated)
        found, binds = walk.read(text)
        given += [(path, one) for one in found]
        stated += [(path, one) for one in walk.stated[before:]]
        reported |= binds
    return given, reported, placed, stated


def _claimed(root: Path, given: list[tuple[Path, Given]], stated: list[tuple[Path, Stated]],
             same: Callable[[str], str]) -> list[Finding]:  # fmt: skip
    """`summary-claim-stronger` for each sentence of a summary that claims more than every
    Results sentence that binds one of its keys, or a key declared the same quantity, and
    holds a word of the claim lists (`claims_more`); each Results sentence read with whether
    the summary sentence gives every result it binds."""
    by_quantity: dict[str, list[tuple[Path, Stated]]] = {}
    bound_in: dict[tuple[Path, str], set[str]] = {}
    for path, one in stated:
        if one.sentence:
            by_quantity.setdefault(same(one.key), []).append((path, one))
            bound_in.setdefault((path, one.sentence), set()).add(same(one.key))
    sentences: dict[tuple[Path, int], list[Given]] = {}
    for path, one in given:
        if one.sentence:
            sentences.setdefault((path, one.opens), []).append(one)
    found = []
    for (path, _opens), ones in sentences.items():
        gives = {same(one.key) for one in ones}
        held: dict[tuple[Path, str], tuple[Path, Stated]] = {}
        keys: list[str] = []
        for one in ones:
            worded = [(where, it) for where, it in by_quantity.get(same(one.key), ())
                      if _compared(it.sentence, bound_in[where, it.sentence] <= gives)]
            if worded and one.key not in keys:
                keys.append(one.key)
            for where, it in worded:
                held.setdefault((where, it.sentence), (where, it))
        moved = claims_more(ones[0].sentence, [
            (it.sentence, bound_in[(where, it.sentence)] <= gives) for where, it in held.values()
        ])  # fmt: skip
        if moved is None:
            continue
        found.append(Finding(
            gate=GATE, code=CLAIM_CODE, severity=WARN, path=path, line=ones[0].line,
            message=_claim_message(root, ones[0].heading, keys, list(held.values()), moved),
            context=" ".join(ones[0].sentence.split())[:160],
            hint="a summary claims what the Results claim: keep their hedges, their limits "
            "and their negations, and their word for the claim, \"associated\" where they "
            "found an association; where the summary's words are the right ones, the "
            "Results should say them too",
        ))  # fmt: skip
    return found


def holds_a_word(text: str) -> bool:
    """Whether `text` holds a word of the claim lists: a hedge, a limit, a negation or a
    word of the ladder (`data/claim_strength.yaml`)."""
    return any(sentence.words for sentence in claims.sentences(text))


def _compared(stated: str, whole: bool) -> bool:
    """Whether a Results sentence is compared with a summary sentence: where it holds a word
    of the claim lists, and, where it binds a result the summary does not give, a word of the
    ladder, all that is read of it then (`_more_than`). One that is not is left out, and keeps
    back no warning another Results sentence gives (round 3 of #573)."""
    return holds_a_word(stated) and (whole or _ladder_only(stated) is not None)


def claims_more(summary: str, stated: Sequence[tuple[str, bool]]) -> Finding | None:
    """What `claims.compare_pair` says of `summary` against the first of `stated`, where the
    summary claims more than every one of them (`_more_than`); None where it does not, or
    where none of them is compared (`_compared`), the rest being left out. Each Results
    sentence comes with whether the summary gives every result it binds."""
    worded = [(one, whole) for one, whole in dict.fromkeys(stated) if _compared(one, whole)]
    if not worded:
        return None
    first = None
    for one, whole in worded:
        moved = _more_than(summary, one, whole)
        if moved is None:
            return None
        first = first or moved
    return first


def _more_than(summary: str, stated: str, whole: bool) -> Finding | None:
    """What `claims.compare_pair` says of `summary` against one Results sentence, where the
    summary claims more than it; None where it does not.

    Where the summary gives every result the sentence binds (`whole`), a word of the claim
    lists dropped or moved up, or a negation gone or new, claims more. A summary that holds
    no such word claims more only by a hedge or a limit it dropped: a negation it leaves out
    does not turn the claim round, nor does a word of the ladder, which takes its claim with
    it ("suggests a signal" against the ratio alone; round 1 of #573). Where the sentence
    binds a result the summary does not give, its hedges, limits and negations may be about
    that one, so only a word of the ladder the summary moves up claims more (Basile,
    2026-11-07). Such a sentence that holds no word of the ladder then states its number,
    and is compared with nothing, as one that holds no word is (`_compared`, round 2 of
    #573)."""
    if not whole:
        said, held = _ladder_only(summary), _ladder_only(stated)
        if said is None or held is None:
            return None
        moved = claims.compare_pair(held, said)
        return moved if moved is not None and moved.code == claims.STRONGER else None
    moved = claims.compare_pair(stated, summary)
    if moved is None:
        return None
    if holds_a_word(summary):
        return moved if moved.code in _MORE else None
    return moved if _bare_claims_more(moved, stated) else None


def _bare_claims_more(moved: Finding, stated: str) -> bool:
    """Whether a summary that holds no word of the claim lists claims more than `stated`, as
    `compare_pair` found them to move: only by a hedge or a limit it dropped, and only where
    that reads as claiming more. Not where `stated` negates too, nor where the lowest word
    of the ladder it holds is above consistency, whose claim went with the hedge (Basile,
    2026-11-07, round 2 of #573)."""
    held = {kind for sentence in claims.sentences(stated) for _word, kind in sentence.words}
    return moved.code == claims.STRONGER and bool(held & {claims.HEDGE, claims.LIMIT})


def _ladder_only(text: str) -> str | None:
    """The words of the ladder `text` holds, as a sentence of them alone, each read as a word
    of its own: what is compared where only a move up the ladder is read. None where it holds
    none."""
    rungs = [word for sentence in claims.sentences(text) for word, kind in sentence.words
             if isinstance(kind, int)]  # fmt: skip
    return " ".join(["So", *rungs]) + "." if rungs else None


def _claim_message(root: Path, heading: str, keys: list[str],
                   held: list[tuple[Path, Stated]], moved: Finding) -> str:  # fmt: skip
    """"this sentence under 'Abstract' claims more than the Results sentence that binds
    results.hr (main.md:42): 'may' is gone", and for several Results sentences each named."""
    what = moved.message.split(": ", 1)[-1]
    places = [f"{_shown(root, where)}:{one.line}" for where, one in held]
    named = _joined([f"results.{key}" for key in keys])
    if len(held) == 1:
        return (f"this sentence under {plain(heading)!r} claims more than the Results "
                f"sentence that binds {named} ({places[0]}): {what}")  # fmt: skip
    return (f"this sentence under {plain(heading)!r} claims more than each of the "
            f"{len(held)} Results sentences that bind {named} ({_joined(places)}); against "
            f"the first, {what}")  # fmt: skip


def _shown(root: Path, path: Path) -> str:
    """A file of the manuscript as a finding names it: from the manuscript folder."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _joined(shown: Sequence[str]) -> str:
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _same_quantity(results: Results):
    """A function giving each key one name for every key declared the same quantity."""
    parent: dict[str, str] = {}

    def root(key: str) -> str:
        seen = set()
        while parent.get(key, key) != key and key not in seen:
            seen.add(key)
            key = parent[key]
        return key

    for key, value in results.values.items():
        if value.same_as:
            parent[root(key)] = root(value.same_as)
    return root


def _printed(project: Project, results: Results, placed: dict[str, set[str]]) -> str:
    """The text of every table and every figure the manuscript places."""
    from manuscript_guard.gates.figures import _extract_text

    parts: list[str] = []
    for key in sorted(placed["table"]):
        table = results.tables.get(key)
        if table is not None:
            parts += [*table.columns, *(cell for row in table.rows for cell in row)]
    for key in sorted(placed["figure"]):
        for suffix in (".svg", ".pdf"):
            path = project.path("figures") / f"{key}{suffix}"
            text = _extract_text(path) if path.is_file() else None
            if text:
                parts.append(text)
    return "\n".join(parts)


def _shows(printed: str, display: str) -> bool:
    """Whether `display` is printed whole in `printed`, with or without its commas, as G3
    reads a figure's numbers: not inside a longer number."""
    return any(
        re.search(rf"(?<![\w.]){re.escape(written)}(?!\w|\.\d)", printed)
        for written in {display, display.replace(",", "")}
        if written
    )
