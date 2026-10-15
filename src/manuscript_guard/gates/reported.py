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

Where none holds, a warning names the key and the heading it was given under. The last
route matches a display and not a key, so a coincidence can keep the warning back; DESIGN.md's
Known gaps carries that and the rest.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
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


@dataclass
class Walk:
    """The headings a reader is under, carried from one file of the paper into the next as
    G14 carries them, and which of the sections met so far report and which summarise.

    `named` is what the journal's profile calls the abstract where it is not "Abstract"."""

    named: str | None = None
    chain: list[Section] = field(default_factory=list)
    reports: set[int] = field(default_factory=set)
    summaries: set[int] = field(default_factory=set)
    #: Every section met, kept so that the identity `reports` and `summaries` hold for each
    #: is not given to a section of a later file once the first is freed (round 1 of #272).
    kept: list[Section] = field(default_factory=list)

    def read(self, text: str) -> tuple[list[Given], set[str]]:
        """The results keys `text` binds in a summary, and those it binds where the paper
        reports them."""
        sections = [section for section in split_sections(scannable(text)) if section.level]
        self.kept += sections
        self._name(sections)
        starts, places = [0], [self._place()]
        for section in sections:
            while self.chain and self.chain[-1].level >= section.level:
                self.chain.pop()
            self.chain.append(section)
            starts.append(section.line)
            places.append(self._place())
        given: list[Given] = []
        reported: set[str] = set()
        for placeholder in parse(text)[0]:
            if placeholder.namespace != "results":
                continue
            place = places[bisect_right(starts, placeholder.line) - 1]
            if place is REPORTED:
                reported.add(placeholder.key)
            elif place is not None:
                given.append(Given(placeholder.key, place, placeholder.line))
        return given, reported

    def _name(self, sections: list[Section]) -> None:
        """Which sections of one file report and which summarise. A Results or a conclusion
        heading over the opening of the paper is the paper's title, and is neither."""
        methods = {id(section) for section in methods_sections(sections, self.named)}
        self.reports |= methods
        for index, section in enumerate(sections):
            below = subsections(sections, index)[1:]
            if any(self._opens(other, methods) for other in below):
                continue
            if names_results(section.title):
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
    from manuscript_guard.gates.journal import abstract_title

    root = project.path("manuscript")
    sources = source_files(root)
    walk = Walk(abstract_title(project))
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
