"""G8: a number the Abstract or a conclusion gives that the paper reports nowhere else.

An abstract summarises the paper, and a conclusion what it found: neither introduces data. A
results key bound in one of them, and bound nowhere in the Methods or the Results, nor
printed in a table or drawn in a figure the manuscript places, is a number a reader of the
paper cannot find in it. Nothing said so: G2 holds a binding to the analysis wherever it
stands, and G8's other check compares the results with themselves.

So each key the Abstract or a conclusion binds is looked for where the paper reports:

- bound in a section the gates read as the Methods (`methods_sections`), whose summary the
  abstract's own Methods are, or in one whose heading opens with "Results" or "Findings";
- or a key declared the same quantity (`same_as`, either way) bound there;
- or bound anywhere in the supplement, which reports what the paper has no room for;
- or its display printed in a table, or in the text of a figure, that a manuscript file
  places.

A box the journal's profile asks for (`boxes:`, highlights or key points) is read as a
summary too: under its heading, and in LaTeX in its environment (`text/boxes.py`).

Where none holds, a warning names the key and the heading it was given under. The last
route matches a display and not a key, so a coincidence can keep the warning back; DESIGN.md's
Known gaps carries that and the rest.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

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
    names_results,
    plain,
)
from manuscript_guard.text.sections import Section, scannable, split_sections, subsections

GATE = "G8"
CODE = "summary-not-reported"

#: Where a section's keys are reported, as against summarised or neither.
REPORTED = object()
#: The opening of a paper. A heading over one of these or over the Methods is the paper's
#: title written as a heading over the whole paper, and names no part of it. Not over the
#: abstract: where the profile calls it "Summary", a "Summary" under the Results is one.
_OPENING = re.compile(r"(?:introduction|background)\W*$", re.IGNORECASE)


@dataclass(frozen=True)
class Given:
    """A results key bound in a summary: the Abstract or a conclusion, under `heading`."""

    key: str
    heading: str
    line: int
    #: Where in the text read the binding starts, which places a LaTeX finding at its `.tex`
    #: line and is no part of what was given.
    start: int = field(default=0, compare=False)


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

    def read(self, text: str) -> tuple[list[Given], set[str]]:
        """The results keys `text` binds in a summary, and those it binds where the paper
        reports them."""
        place_of = self.placing(
            [section for section in split_sections(scannable(text)) if section.level])
        given: list[Given] = []
        reported: set[str] = set()
        for placeholder in parse(text)[0]:
            if placeholder.namespace != "results":
                continue
            boxed = self.boxed(placeholder.start) if self.boxed is not None else None
            if boxed is not None:
                given.append(Given(placeholder.key, boxed, placeholder.line, placeholder.start))
                continue
            place = place_of(placeholder.line)
            if place is REPORTED:
                reported.add(placeholder.key)
            elif place is not None:
                given.append(Given(placeholder.key, place, placeholder.line, placeholder.start))
        return given, reported

    def placing(self, sections: list[Section]) -> Callable[[int], object]:
        """Where each line of one file stands, given its headings in order, each with its
        level and its line: the title of the summary it is in, REPORTED, or None for
        neither. What `read` places a binding by, and the audit's Abstract against Results
        a number by, its sections read from a Word document's heading styles or a LaTeX
        document's printed view as well as from Markdown (`auditing.abstract`)."""
        self.kept += sections
        self._name(sections)
        starts, places = [0], [self._place()]
        for section in sections:
            while self.chain and self.chain[-1].level >= section.level:
                self.chain.pop()
            self.chain.append(section)
            starts.append(section.line)
            places.append(self._place())
        return lambda line: places[bisect_right(starts, line) - 1]

    def _name(self, sections: list[Section]) -> None:
        """Which sections of one file report and which summarise. A Results or a conclusion
        heading over the opening of the paper is the paper's title, and is neither."""
        methods = {id(section) for section in methods_sections(sections, self.named)}
        self.reports |= methods
        for index, section in enumerate(sections):
            below = subsections(sections, index)[1:]
            if any(self._opens(other, methods) for other in below):
                continue
            if box_of(section.title, self.boxes) is not None:
                self.summaries.add(id(section))
            elif names_results(section.title):
                self.reports.add(id(section))
            elif names_conclusion(section.title):
                self.summaries.add(id(section))

    def _opens(self, section: Section, methods: set[int]) -> bool:
        return bool(_OPENING.match(plain(section.title))) or id(section) in methods

    def _place(self) -> object:
        """What the text under the current headings is: the title of the summary it is in,
        REPORTED, or None. The outermost heading that names a part decides: the abstract's
        own "Results" summarise, and a "Summary" under the Results is theirs, even where the
        profile calls the abstract "Summary"."""
        for section in self.chain:
            if section.names_abstract(self.named) or id(section) in self.summaries:
                return section.title
            if id(section) in self.reports:
                return REPORTED
        return None


def check_reported(project: Project, results: Results) -> Report:
    """A warning for each results key a summary gives that the paper reports nowhere else."""
    from manuscript_guard.gates.journal import abstract_title, box_rules_of
    from manuscript_guard.text.reader import LATEX, manuscript_format

    root = project.path("manuscript")
    walk = Walk(abstract_title(project), box_rules_of(project))
    if manuscript_format(root) == LATEX:
        given, reported, placed = _latex_read(root, walk)
    else:
        given, reported, placed = _markdown_read(root, walk)
    same = _same_quantity(results)
    reported_as = {same(key) for key in reported}
    missing = [(path, one) for path, one in given if same(one.key) not in reported_as]
    report = Report()
    if not missing:
        return report
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
                message=f"results.{one.key} is given under {plain(one.heading)!r} and reported "
                "nowhere in the Methods, the Results, a table or a figure",
                path=path,
                line=one.line,
                hint="report the number where the paper reports its results, a table or a "
                "figure included, and let the summary restate it; a coarser form for the "
                "summary is a second key emitted with same_as",
            )
        )
    return report


def _latex_read(root: Path, walk: Walk) -> tuple[list[tuple[Path, Given]], set[str], dict]:
    """A LaTeX manuscript's summaries and reports, read in each document's printed view
    (`text/latex/printed.py`), where a binding is `{{results.key}}` under the headings LaTeX
    prints it under; each summary's binding named at its `.tex` file and line (step 8). Its
    files nothing inputs are not printed, and report nothing."""
    from dataclasses import replace

    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import ENTRY, read_document

    given: list[tuple[Path, Given]] = []
    reported: set[str] = set()
    placed: dict[str, set[str]] = {"table": set(), "figure": set()}
    for supplementary in (False, True):
        sources = [source for source in read_document(root, supplementary=supplementary).sources
                   if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
        view = printed(sources)
        placeholders = parse(view.text)[0]
        for placeholder in placeholders:
            if placeholder.namespace in placed:
                placed[placeholder.namespace].add(placeholder.key)
        if supplementary:
            reported |= {p.key for p in placeholders if p.namespace == "results"}
            continue
        walk.boxed = _boxed_in(view, sources, walk.boxes)
        found, binds = walk.read(view.text)
        for one in found:
            where = view.place(one.start)
            path, line = (where[0].path, where[1]) if where else (ENTRY, one.line)
            given.append((root / path, replace(one, line=line)))
        reported |= binds
    return given, reported, placed


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


def _markdown_read(root: Path, walk: Walk) -> tuple[list[tuple[Path, Given]], set[str], dict]:
    """A Markdown manuscript's summaries and reports: the paper's files in printed order, the
    headings carried from one into the next, and the supplement's bindings, each reported."""
    sources = source_files(root)
    given: list[tuple[Path, Given]] = []
    reported: set[str] = set()
    placed: dict[str, set[str]] = {"table": set(), "figure": set()}
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
            continue
        found, binds = walk.read(text)
        given += [(path, one) for one in found]
        reported |= binds
    return given, reported, placed


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
