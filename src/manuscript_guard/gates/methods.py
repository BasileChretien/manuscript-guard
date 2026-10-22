"""G9 — does the Methods section still describe what the code does?

Methods sections go stale in a particular way. The analysis is written, the Methods are
written to match, and then the analysis changes: a filter is added, a model is swapped, a
threshold moves. Nothing forces the prose to follow, and nobody re-reads their own Methods
once they are written. The result is a paper that describes an analysis nobody ran.

No checker can read code and prose and decide whether they agree. What it can do is notice
that the code changed after the prose was last reconciled with it, and refuse to let that
pass silently. So this gate is a **reconciliation ledger**: `methods.lock` records the
analysis files as they stood when someone last read the Methods against them, and the gate
compares.

That makes the claim modest and true. It does not verify that the Methods are correct. It
verifies that somebody looked, and that nothing has changed since they did.

A whole file is a coarse thing to have looked at, so the reading can also be kept pair by
pair. The analysis marks a step of its code (`with em.step("ci"):`), and the Methods end the
text that describes it with an anchor that prints nothing, `{{method.ci}}`. What the anchor
claims is the text before it, back to the anchor before it or the start of its paragraph:
its extent is where the author put the anchors, and nothing guesses where a sentence ends.
The lock then records each step and its claim as a pair, with a digest of the step's code
read as code and the claim as written, and the report names the pair whose code or whose
text changed since it was read. An anchor in a paragraph that names no step the run recorded
fails, which is how a claim about a branch the analysis never took is caught. One on a
heading's line is in no paragraph and is not judged.

The Methods are the main text's and the supplement's, one ledger. In the supplement, the own
text of a section whose heading holds "methods", "Supplementary methods" or "eMethods 1.
Data source", and of a section under it that names a method too, is read with the main
text's Methods for the parameters below. Its paragraphs that point at no step are listed
where G2 reads them as the Methods, under a supplement's name of them ("Supplementary
methods", "eMethods 1", not "Detailed methods"); an anchor is read wherever it stands.

Two additions make the prompt useful rather than annoying. The report names *which* files
changed, so the reconciliation is targeted. And a handful of parameters that must agree —
the significance threshold, the software versions — are extracted from both sides and
compared directly, because those are checkable and they are what reviewers query.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.classify import METHODS_SECTIONS, is_methods, names_methods_place
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results, Step
from manuscript_guard.contracts.values import Value
from manuscript_guard.emit import sha256_of
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, source_files
from manuscript_guard.paths import SOURCE_SUFFIXES
from manuscript_guard.text.masking import blank_comments
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.section_names import methods_sections
from manuscript_guard.text.sections import (
    chains_at,
    footnote_index,
    heading_index,
    split_sections,
)

GATE = "G9"
LOCK = "methods.lock"
#: The lock `methods --reconcile` writes: read against the Methods of the main text and of
#: the supplement.
SCHEMA = "manuscript-guard/methods-lock/2"
#: A lock written before G9 read the supplement's Methods. Valid, and said of once where the
#: supplement has Methods (`methods-supplement-unreconciled`).
SCHEMA_MAIN_TEXT_ONLY = "manuscript-guard/methods-lock/1"



@dataclass(frozen=True)
class Drift:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def describe(self) -> str:
        parts = []
        for label, names in (
            ("changed", self.changed),
            ("added", self.added),
            ("removed", self.removed),
        ):
            if names:
                shown = ", ".join(sorted(names)[:4])
                more = f" (+{len(names) - 4} more)" if len(names) > 4 else ""
                parts.append(f"{label}: {shown}{more}")
        return "; ".join(parts)


@dataclass(frozen=True)
class Claim:
    """The text one run of anchors claims: what stands before them, back to the anchor before
    them or the start of their paragraph, its spaces and line breaks each read as one space.
    Several anchors side by side claim the same text."""

    steps: tuple[str, ...]
    text: str
    path: Path
    #: Where the claim starts, and where its anchors stand.
    line: int
    anchor_line: int


@dataclass(frozen=True)
class Paragraph:
    """A paragraph with no anchor in it: in the Methods, text that points at no step."""

    text: str
    path: Path
    line: int


Span = tuple[int, int]

#: A line that ends a paragraph and starts no claim: blank, or an ATX heading.
_HEADING = re.compile(r"[ ]{0,3}#{1,6}(?:[ \t]|$)")


def _paragraphs(
    text: str, cuts: tuple[Span, ...] = (), typed: str | None = None
) -> list[Span]:
    """Where each paragraph of `text` starts and ends, by its lines: a blank line ends one,
    and a heading is a line of its own. Read on the text as written, so a comment on a line of
    its own inside a paragraph, which pandoc keeps in the paragraph, does not end it.

    A LaTeX file's view is `text` and the file as typed is `typed`, whose empty lines alone end
    a paragraph, as TeX reads it: a line of a comment or of a `\\label` alone, spaces in the
    view, ends none. Each paragraph starts at its first character the view prints. `cuts` are
    the spans of its headings' commands and of its tables set apart, which end a paragraph
    where they stand and are part of none (`_cuts`, step 8)."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    at = 0
    # A line ends at a line feed and nowhere else, as `placeholders.parse` counts lines.
    for line in re.findall(r"[^\n]*\n|[^\n]+\Z", text if typed is None else typed):
        bare = line.rstrip("\r\n")
        if not bare.strip() or (typed is None and _HEADING.match(bare)):
            if start is not None:
                spans.append((start, at))
                start = None
        elif start is None:
            start = at
        at += len(line)
    if start is not None:
        spans.append((start, at))
    if typed is not None:
        spans = [part for first, last in spans for part in _printed_from(text, first, last)]
    for cut in cuts:
        spans = [piece for span in spans for piece in _cut(text, span, cut)]
    return spans


def _cut(text: str, span: Span, cut: Span) -> list[Span]:
    """What of `span` is outside `cut` and holds more than spaces, each part from its first
    character that is not one."""
    start, end = span
    if cut[1] <= start or end <= cut[0]:
        return [span]
    return [part for first, last in ((start, cut[0]), (cut[1], end))
            for part in _printed_from(text, first, last)]  # fmt: skip


def _printed_from(text: str, first: int, last: int) -> list[Span]:
    """`first` to `last` from its first character that is not a space, or nothing."""
    first += len(text[first:last]) - len(text[first:last].lstrip())
    return [(first, last)] if first < last else []


def _inside(above: str | None, below: str | None) -> bool:
    """Whether a line between `above` and `below` is inside a paragraph as written: under a
    line of the paragraph, which a blank line or a heading is not, and over any line."""
    return bool(above and above.strip() and not _HEADING.match(above) and below and below.strip())


def anchor_lines(text: str) -> list[int]:
    """The first line, counted from 1, of each run of lines that hold nothing but anchors and
    spaces inside a paragraph.

    An anchor prints nothing and its line stays, so such a line prints as an empty line and
    the document ends the paragraph there, where the source has none. What stands under it
    then starts a block of its own: a sentence a paragraph, `- ...` a list, `## ...` a
    heading. Which of those the author meant cannot be told, so each is warned of. A line
    with a quotation's or a list's mark on it holds more than anchors, and the first and last
    lines of a paragraph end nothing it does not end already: anchors one to a line at the
    end of a paragraph, which is how two steps' anchors are written in the skill's style, are
    a run whose line below is blank. A run is warned of once, at its first line, which is
    where the paragraph ends.
    """
    lines = text.split("\n")
    found = []
    for first, last in _runs(_lines_of_anchors(text, lines)):
        above = lines[first - 2] if first > 1 else None
        below = lines[last] if last < len(lines) else None
        if _inside(above, below):
            found.append(first)
    return found


def _lines_of_anchors(text: str, lines: list[str]) -> list[int]:
    """The lines, counted from 1, that hold nothing but anchors and spaces."""
    anchors = [found for found in parse(text)[0] if found.is_anchor]
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    on: dict[int, list] = {}
    for anchor in anchors:
        on.setdefault(anchor.line, []).append(anchor)
    found = []
    for number, here in sorted(on.items()):
        start, end = starts[number - 1], starts[number - 1] + len(lines[number - 1])
        if any(anchor.end > end for anchor in here):
            continue  # braces typed over several lines
        bounds = zip([start, *(a.end for a in here)], [*(a.start for a in here), end], strict=True)
        if not "".join(text[a:b] for a, b in bounds).strip(" \t\r"):
            found.append(number)
    return found


def _runs(numbers: list[int]) -> list[tuple[int, int]]:
    """`numbers`, in order, as runs of consecutive ones: the first and last of each."""
    runs: list[tuple[int, int]] = []
    for number in numbers:
        if runs and runs[-1][1] == number - 1:
            runs[-1] = (runs[-1][0], number)
        else:
            runs.append((number, number))
    return runs


#: A paragraph that says nothing a step could back: a table or figure placed by its binding,
#: a fenced listing, a pipe table, a fenced div.
_NOT_PROSE = re.compile(r"\{\{[^}]*\}\}$|```|~~~|\||:::")


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def claims_in(
    text: str, cuts: tuple[Span, ...] = (), typed: str | None = None
) -> tuple[list[tuple[tuple[str, ...], int, int, int]], list[Span]]:
    """The claims of one file, and its paragraphs that hold no anchor.

    Each claim is its steps, where its text starts and ends, and where its anchors start.
    The text is read with comments blanked, so a comment inside a claim is not part of it,
    and the claim is empty where its anchors open their paragraph.
    """
    anchors = [found for found in parse(text)[0] if found.is_anchor]
    shown = blank_comments(text) if "<!--" in text else text
    claims, bare = [], []
    for start, end in _paragraphs(text, cuts, typed):
        inside = [a for a in anchors if start <= a.start < end]
        if not inside:
            bare.append((start, end))
            continue
        runs: list[list] = []
        for anchor in inside:
            if runs and not shown[runs[-1][-1].end : anchor.start].strip():
                runs[-1].append(anchor)
            else:
                runs.append([anchor])
        before = start
        for run in runs:
            claims.append((tuple(a.key for a in run), before, run[0].start, run[0].start))
            before = run[-1].end
    return claims, bare


def anchored(project: Project) -> tuple[list[Claim], list[Paragraph]]:
    """Every claim in the manuscript, and every Methods paragraph that points at no step."""
    claims: list[Claim] = []
    open_: list[Paragraph] = []
    for read in _anchor_texts(project):
        found, bare = _anchored_in(read)
        claims += found
        open_ += bare
    return claims, open_


@dataclass(frozen=True)
class _Read:
    """A manuscript file as its anchors are read. A Markdown file is read as typed, under its
    own headings (`chains` None). A LaTeX file is read as Markdown writes it
    (`views.markdown_view`), `\\mg{method.step}` as `{{method.step}}` at its offsets, under the
    headings the include tree gives at each place, its paragraphs ended where it is typed with
    an empty line (`typed`), each heading's command and each table set apart cut out of them
    (`_cuts`), as a Markdown heading is a line of its own and a pipe table is no prose, and
    each float blanked (`_unprinted`), which TeX moves out of its paragraph (step 8)."""

    path: Path
    text: str
    chains: Callable[[int], list] | None = None
    cuts: tuple[Span, ...] = ()
    typed: str | None = None


def _anchor_texts(project: Project) -> list[_Read]:
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return [_Read(path, read_text(path)) for path in source_files(folder)]
    from manuscript_guard.text.latex.views import files

    return [_latex_read(found.path, found.source, found.view) for found in files(folder)]


def _latex_read(path: Path, source, view: str) -> _Read:
    """A LaTeX file as G9 reads it: its Markdown view, under the headings the include tree
    gives at each place."""
    from manuscript_guard.text.latex.views import chain

    shown = _blanked(view, _unprinted(source, view))
    return _Read(path, shown, lambda at: [chain(source, at)], _cuts(source, view), source.text)


def _cuts(source, view: str) -> tuple[Span, ...]:
    """What of a LaTeX file ends a paragraph: each heading's command, to its title's end, and
    each table typed outside a float, which a `longtable` or a `center` sets apart, each part
    of none; and either end of a float or such a table that holds an anchor, which is a
    paragraph of its own, as a pipe table is in Markdown, its words before the anchor the
    claim (rounds 1 and 3 of step 8). A `tabular` typed within a sentence ends it too."""
    reading = source.reading
    anchors = _anchors_at(view)
    headings = [(h.start, h.end) for h in reading.headings if h.end > h.start]
    apart = [span for span in reading.tables if not _within(span, reading.floats)]
    ends = [(edge, edge) for span in (*reading.floats, *apart) if _holds(span, anchors)
            for edge in span]  # fmt: skip
    return (*headings, *(span for span in apart if not _holds(span, anchors)), *ends)


def _unprinted(source, view: str) -> tuple[Span, ...]:
    """What of a LaTeX file's paragraphs G9 reads no word of, and that ends none: each float
    that holds no anchor, which TeX moves out of its paragraph, and the paragraph goes on
    round it (round 2 of step 8); and each table inside a float that holds no anchor, so that
    a float's claim is its caption's words (round 3)."""
    reading = source.reading
    anchors = _anchors_at(view)
    inside = [span for span in reading.tables if _within(span, reading.floats)]
    return tuple(span for span in (*reading.floats, *inside) if not _holds(span, anchors))


def _anchors_at(view: str) -> list[int]:
    return [found.start for found in parse(view)[0] if found.is_anchor]


def _holds(span: Span, anchors: list[int]) -> bool:
    return any(span[0] <= at < span[1] for at in anchors)


def _within(span: Span, spans) -> bool:
    """Whether `span` is inside one of `spans` other than itself."""
    return any(start <= span[0] and span[1] <= end and (start, end) != span
               for start, end in spans)  # fmt: skip


def _blanked(text: str, spans: tuple[Span, ...]) -> str:
    """`text` with each of `spans` spaces, its line breaks kept."""
    out = list(text)
    for start, end in spans:
        for index in range(start, end):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


#: The view pads a binding inside its braces to the command's width (`{{ results.n}}`); the
#: claim reads it as Markdown writes it.
_PADDED = re.compile(r"\{\{ +")


def _anchored_in(read: _Read) -> tuple[list[Claim], list[Paragraph]]:
    """A file's claims and its Methods paragraphs that point at no step."""
    path, text, chains = read.path, read.text, read.chains
    found, bare = claims_in(text, read.cuts, read.typed)
    shown = blank_comments(text) if "<!--" in text else text

    def said(words: str) -> str:
        return _collapsed(words) if read.chains is None else _PADDED.sub("{{", _collapsed(words))

    if chains is None:
        headings, notes = heading_index(text), footnote_index(text)

        def chains(at: int):
            return chains_at(headings, notes, at)

    def methods(at: int) -> bool:
        return any(is_methods(chain) for chain in chains(at))

    def line(at: int) -> int:
        return text.count("\n", 0, at) + 1

    claims = [
        Claim(
            steps=steps,
            text=said(shown[start:end]),
            path=path,
            # Where its first word is: after the anchor before it, a line break can come first.
            line=line(start + len(shown[start:end]) - len(shown[start:end].lstrip())),
            anchor_line=line(at),
        )
        for steps, start, end, at in found
    ]
    open_ = []
    for start, end in bare:
        words = said(shown[start:end])
        if words and methods(start) and not _NOT_PROSE.match(words):
            open_.append(Paragraph(words, path, line(start)))
    return claims, open_


def analysis_digests(project: Project) -> dict[str, str]:
    directory = project.path("analysis")
    if not directory.exists():
        return {}
    out = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            out[str(path.relative_to(project.root)).replace("\\", "/")] = sha256_of(path)
    return out


def lock_path(project: Project) -> Path:
    return project.root / LOCK


def read_lock(project: Project) -> dict:
    path = lock_path(project)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compare(current: dict[str, str], recorded: dict[str, str]) -> Drift:
    return Drift(
        added=tuple(sorted(set(current) - set(recorded))),
        removed=tuple(sorted(set(recorded) - set(current))),
        changed=tuple(sorted(k for k in set(current) & set(recorded) if current[k] != recorded[k])),
    )


def methods_text(project: Project) -> str | None:
    """The Methods as G9 reads them: the main text's (`main_methods`), then each of the
    supplement's (`supplementary_methods`), one ledger. None where neither has any.

    The main text's alone, as G4 counts a required section, until 2026-10-21: a parameter
    the supplement's Methods stated was reported absent, and in a paper whose Methods are all
    in "eMethods" the lock's parameters were compared with no text."""
    return _joined(main_methods(project), supplementary_methods(project))


def _joined(main: str | None, supplement: list[tuple[Path, str]]) -> str | None:
    parts = ([main] if main is not None else []) + [text for _path, text in supplement]
    return "\n\n".join(parts) if parts else None


def main_methods(project: Project) -> str | None:
    """The main text's Methods: everything under the heading that is the paper's Methods
    (`section_names.methods_sections`), the test G4 counts a required Methods section
    present by, in the first file that has one. None where no heading is.

    The pattern this had of its own read "Methods" and "Materials and methods" and nothing
    else, so under "2. Methods" or "Patients and methods" a wrong parameter in the lock was
    compared with no text, and the gate said nothing."""
    from manuscript_guard.gates.journal import abstract_title

    named = abstract_title(project)
    folder = project.path("manuscript")
    if _latex(folder):
        # The document as Markdown would print it, its headings as `#` lines (step 8).
        from manuscript_guard.text.latex.printed import printed_document

        return methods_in(printed_document(folder, supplementary=False), named)
    for path in source_files(folder, main_text_only=True):
        found = methods_in(read_text(path), named)
        if found is not None:
            return found
    return None


def _latex(folder: Path) -> bool:
    from manuscript_guard.text.reader import LATEX, manuscript_format

    return manuscript_format(folder) == LATEX


def supplementary_methods(project: Project) -> list[tuple[Path, str]]:
    """Each file of the supplement that has Methods, with its Methods as
    `supplement_methods_in` reads them, in the order of the files."""
    from manuscript_guard.gates.journal import abstract_title

    named = abstract_title(project)
    root = project.path("manuscript")
    if _latex(root):
        from manuscript_guard.text.latex.printed import printed_document
        from manuscript_guard.text.latex.structure import SUPPLEMENT_ENTRY

        text = supplement_methods_in(printed_document(root, supplementary=True), named)
        return [] if text is None else [(root / SUPPLEMENT_ENTRY, text)]
    found = []
    for path in source_files(root):
        if is_supplementary(root, path):
            text = supplement_methods_in(read_text(path), named)
            if text is not None:
                found.append((path, text))
    return found


def methods_in(text: str, abstract_title: str | None = None) -> str | None:
    """The Methods of one file of the main text, as `main_methods` reads them, or None.
    `abstract_title` is what the journal's profile calls the abstract, as G4 has it."""
    found = methods_sections(split_sections(text), abstract_title)
    return found[0].enclosed if found else None


def supplement_methods_in(text: str, abstract_title: str | None = None) -> str | None:
    """The Methods of one file of the supplement, or None where they hold no text: the own
    text of every section that the main text's Methods would be found as
    (`methods_sections`), and of each section under one read that names a method too
    (`classify.names_methods_place`: "Statistical analysis", "eMethods 2"), in the order
    they stand. Every one, not the first: a supplement numbers its Methods, "eMethods 1" to
    "eMethods 4", with its tables between them.

    Not everything under such a heading, as the main text's Methods are read: a supplement
    often has "Supplementary methods" over all of it, its tables and its results among them,
    and a locked parameter matched by a number of theirs would be no check (round 1 of
    #395). Under one of the main text's names (`classify.METHODS_SECTIONS`, "Statistical
    analysis") everything is read, as G2 holds it. G2 and G15 read those names wherever they
    stand, and G9 only under a section it reads (Known gaps)."""
    sections = split_sections(text)
    found = {id(section) for section in methods_sections(sections, abstract_title)}
    read: list[str] = []
    #: Each open section's level, whether it is read, and whether all under it is.
    open_: list[tuple[int, bool, bool]] = []
    for section in sections:
        while open_ and open_[-1][0] >= section.level:
            open_.pop()
        _level, under_read, under_all = open_[-1] if open_ else (0, False, False)
        reading = id(section) in found or (
            under_read and (under_all or names_methods_place(section.title))
        )
        whole = reading and (under_all or METHODS_SECTIONS.match(section.title) is not None)
        open_.append((section.level, reading, whole))
        if reading:
            read.append(section.body)
    return "\n\n".join(read) if any(part.strip() for part in read) else None


def _no_methods(project: Project) -> Report:
    """Said where the manuscript has text and no heading names the Methods: a LaTeX one has
    its entry file (round 1 of step 8)."""
    folder = project.path("manuscript")
    if not _latex(folder) and not source_files(folder, main_text_only=True):
        return Report()
    return Report(
        (
            Finding(
                gate=GATE,
                code="methods-not-found",
                severity=WARN,
                message="no heading in the main text or the supplement names the Methods, so "
                "the parameters in methods.lock were compared with no text",
                path=project.path("manuscript"),
                hint='a heading whose title holds "methods" is the Methods, outside the '
                'abstract and under no Introduction, Results or Discussion: "Methods", '
                '"2. Methods", "Patients and methods", "Statistical methods" in the main text, '
                '"Supplementary methods" or "eMethods 1" in the supplement',
            ),
        )
    )


def _supplement_unreconciled(
    project: Project, lock: dict, supplement: list[tuple[Path, str]]
) -> Report:
    """A lock written before G9 read the supplement's Methods, in a project whose supplement
    has some: said once, and nothing else changes. Its files and its pairs are held as they
    always were, and `methods --reconcile` writes the lock that clears it."""
    # A `schema:` left empty is no schema, as one left out is.
    if not supplement or (lock.get("schema") or SCHEMA_MAIN_TEXT_ONLY) != SCHEMA_MAIN_TEXT_ONLY:
        return Report()

    def shown(path: Path) -> str:
        try:
            return path.relative_to(project.root).as_posix()
        except ValueError:  # a manuscript folder outside the project
            return path.as_posix()

    return Report(
        (
            Finding(
                gate=GATE,
                code="methods-supplement-unreconciled",
                severity=WARN,
                message="methods.lock was written when G9 read only the main text's Methods, "
                "so the supplement's Methods may never have been read against the code",
                path=lock_path(project),
                context=", ".join(shown(path) for path, _ in supplement),
                hint="read the supplement's Methods against the analysis, then "
                "`manuscript-guard methods --reconcile`",
            ),
        )
    )


def check_methods(
    project: Project,
    namespace: dict[str, Value] | None = None,
    results: Results | None = None,
) -> Report:
    if namespace is None or results is None:
        from manuscript_guard.contracts import load_namespace

        loaded = load_namespace(project)
        namespace = namespace if namespace is not None else loaded[0]
        results = results if results is not None else loaded[1]
    current = analysis_digests(project)
    lock = read_lock(project)
    pairs = _pairs(project, results, lock if current and _reconciled(lock) else None)
    if not current:
        return pairs.with_counts(analysis_files=0)

    supplement = supplementary_methods(project)
    prose = _joined(main_methods(project), supplement)
    if prose is None:
        pairs = pairs.merge(_no_methods(project))
    recorded = lock.get("analysis", {})

    if not recorded:
        return pairs.with_findings(
            Finding(
                gate=GATE,
                code="methods-never-reconciled",
                severity=WARN,
                message=f"the Methods have never been read against the {len(current)} "
                f"analysis file(s)",
                path=lock_path(project),
                hint="read the Methods against the code, then run "
                "`manuscript-guard methods --reconcile`",
            ),
        ).with_counts(analysis_files=len(current))

    drift = compare(current, recorded)
    report = pairs.merge(_supplement_unreconciled(project, lock, supplement))
    if drift.any:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="methods-drift",
                message="the analysis changed after the Methods were last reconciled with it",
                path=lock_path(project),
                context=drift.describe(),
                hint="re-read the Methods against those files, then "
                "`manuscript-guard methods --reconcile`",
            )
        )

    report = report.merge(_compare_parameters(project, lock, namespace, prose))
    return report.with_counts(
        analysis_files=len(current),
        analysis_changed=len(drift.changed) + len(drift.added) + len(drift.removed),
    )


@dataclass(frozen=True)
class Pair:
    """One step and one claim pointing at it, and how they stand against the lock."""

    step: str
    claim: Claim
    found: Step | None
    #: unknown, unread, code, claim or read; see `_judged`.
    standing: str
    read_on: str | None = None
    was: str | None = None


def _locked(lock: dict) -> list[dict]:
    pairs = lock.get("pairs") or []
    return [pair for pair in pairs if isinstance(pair, dict)]


def _reconciled(lock: dict) -> bool:
    """Whether `lock` is one the pairs are held to: it records the files, or a pair.

    It was the files alone. `methods --reconcile <step>` run before any `methods --reconcile`
    writes a lock with that pair and no file, which then counted as no lock: every pair was
    passed over, the one just read with them, and its step could change unreported.
    """
    return bool(lock.get("analysis") or _locked(lock))


def _judged(claims: list[Claim], steps: dict[str, Step], locked: list[dict] | None) -> list[Pair]:
    """Every pair of a step and a claim pointing at it, in the order of the claims, and where
    each stands: its step never ran (`unknown`); never read (`unread`); its code (`code`) or
    its text (`claim`) changed since it was read; or `read`, as it was.

    A pair is the lock's when its step and its text are the lock's. A text is a changed one
    only where it is all that is left: one text of the step that the lock does not hold, and
    one text the lock holds that no claim does now. A second text pointing at a step is a new
    pair, never read, rather than the first one changed.
    """
    pairs = [(step, claim) for claim in claims for step in claim.steps]
    if locked is None:
        return [
            Pair(step, claim, steps.get(step), "unread" if step in steps else "unknown")
            for step, claim in pairs
        ]
    now = {(step, claim.text) for step, claim in pairs}
    left: dict[str, list[dict]] = {}
    for entry in locked:
        if (entry.get("step"), entry.get("claim")) not in now:
            left.setdefault(entry.get("step"), []).append(entry)
    new: dict[str, set[str]] = {}
    held = {(entry.get("step"), entry.get("claim")): entry for entry in locked}
    for step, claim in pairs:
        if (step, claim.text) not in held:
            new.setdefault(step, set()).add(claim.text)
    out = []
    for step, claim in pairs:
        found = steps.get(step)
        if found is None:
            out.append(Pair(step, claim, found, "unknown"))
            continue
        entry = held.get((step, claim.text))
        if entry is not None:
            standing = "read" if entry.get("code") == found.digest else "code"
            out.append(Pair(step, claim, found, standing, entry.get("read_on")))
        elif len(new[step]) == 1 and len(left.get(step, ())) == 1:
            was = left[step][0]
            standing = "claim" if was.get("code") == found.digest else "unread"
            out.append(Pair(step, claim, found, standing, was.get("read_on"), was.get("claim")))
        else:
            out.append(Pair(step, claim, found, "unread"))
    return out


def pairs_of(project: Project, results: Results, lock: dict | None) -> list[Pair]:
    """Every step and claim pointing at it, in the order the manuscript has them."""
    claims, _open = anchored(project)
    return _judged(claims, results.steps, _locked(lock) if lock is not None else None)


def _excerpt(text: str, width: int = 90) -> str:
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def _pairs(project: Project, results: Results, lock: dict | None) -> Report:
    """The anchors and the steps, and each pair against the lock where there is one.

    Nothing at all, not even a count, for a project with neither: it reads as it did before
    there were steps.
    """
    claims, open_ = anchored(project)
    if not claims and not results.steps:
        return Report()
    findings = []
    locked = _locked(lock) if lock is not None else None
    for claim in claims:
        if not claim.text:
            findings.append(
                Finding(
                    gate=GATE,
                    code="method-claim-empty",
                    message=f"{_anchors(claim.steps)} claims no text: nothing stands before it "
                    f"in its paragraph",
                    hint="put the anchor at the end of the text that describes the step",
                    path=claim.path,
                    line=claim.anchor_line,
                )
            )
    findings += _anchor_line_findings(project)
    pairs = _judged(claims, results.steps, locked)
    described = {pair.step for pair in pairs}
    stale = 0
    for pair in pairs:
        # Without a lock every pair is unread, and `methods-never-reconciled` says so once.
        if locked is None and pair.found is not None:
            continue
        finding = _pair_finding(pair, {"path": pair.claim.path, "line": pair.claim.anchor_line})
        if finding is not None:
            stale += pair.standing in ("code", "claim", "unread")
            findings.append(finding)
    for name, step in sorted(results.steps.items()):
        if name in described:
            continue
        findings.append(
            Finding(
                gate=GATE,
                code="method-step-undescribed",
                severity=WARN,
                message=f"step {name!r} ran, and no text in the manuscript points at it",
                path=project.root / step.script,
                line=step.lines[0] if step.lines else None,
                hint=f"end the Methods text that describes it with {{{{method.{name}}}}}, or "
                "take the mark off the code",
            )
        )
    return Report(tuple(findings)).with_counts(
        method_steps=len(results.steps),
        method_claims=len(claims),
        method_pairs_stale=stale,
        methods_open=len(open_),
    )


def _anchor_line_findings(project: Project) -> list[Finding]:
    """A warning for each line of nothing but anchors inside a paragraph (`anchor_lines`)."""
    return [
        Finding(
            gate=GATE,
            code="method-anchor-line",
            severity=WARN,
            message="this line holds nothing but anchors, and prints as an empty line, so the "
            "paragraph ends here in the document though it goes on in the source",
            hint="put the anchor at the end of the line above, or leave a blank line after it "
            "if a new paragraph or a list is meant",
            path=read.path,
            line=line,
        )
        # A line of nothing but anchors ends no paragraph in LaTeX, where only an empty line
        # does: a Markdown file's alone are read (step 8).
        for read in _anchor_texts(project)
        if read.chains is None
        for line in anchor_lines(read.text)
    ]


def _anchors(steps: tuple[str, ...]) -> str:
    return "".join(f"{{{{method.{step}}}}}" for step in steps)


def _pair_finding(pair: Pair, where: dict) -> Finding | None:
    step, claim = pair.step, pair.claim
    reconcile_hint = (
        f"read it against {pair.found.where if pair.found else ''}, then "
        f"`manuscript-guard methods --reconcile {step}`"
    )
    if pair.standing == "unknown":
        return Finding(
            gate=GATE,
            code="method-step-unknown",
            message=f"{{{{method.{step}}}}} names no step the analysis ran",
            hint=f'mark the code with `with em.step("{step}"):` (R: `em$step("{step}", {{ ... '
            "})`) and run it again; a step in a branch the run did not take is not recorded",
            **where,
        )
    if pair.standing == "unread":
        return Finding(
            gate=GATE,
            code="method-pair-unread",
            message=f"the text pointing at step {step!r} has never been read against its code",
            context=_excerpt(claim.text),
            hint=reconcile_hint,
            **where,
        )
    if pair.standing == "code":
        return Finding(
            gate=GATE,
            code="method-step-changed",
            message=f"step {step!r} changed after the text pointing at it was last read "
            f"against it",
            context=_excerpt(claim.text),
            hint="re-" + reconcile_hint,
            **where,
        )
    if pair.standing == "claim":
        return Finding(
            gate=GATE,
            code="method-claim-changed",
            message=f"the text pointing at step {step!r} changed after it was last read "
            f"against the code",
            context=f"was: {_excerpt(pair.was or '')}",
            hint="re-" + reconcile_hint,
            **where,
        )
    return None


#: What `methods --explain` calls each standing, in a column wide enough for the longest.
_SAID = {
    "read": "read",
    "code": "code changed",
    "claim": "text changed",
    "unread": "never read",
    "unknown": "no such step",
}


def explain_methods(project: Project, results: Results | None = None) -> list[str]:
    """Each claim in the manuscript with the step it points at and how the pair stands, then
    the Methods paragraphs that point at no step, then the steps no text points at. What a
    person reads to check the Methods against the code: every claim beside the lines that
    back it, and what nothing backs."""
    import textwrap

    if results is None:
        from manuscript_guard.contracts import load_namespace

        results = load_namespace(project)[1]
    lock = read_lock(project)
    claims, open_ = anchored(project)
    locked = _locked(lock) if _reconciled(lock) else None
    root = project.root

    def at(path: Path, line: int) -> str:
        return f"{path.relative_to(root).as_posix()}:{line}"

    def said(text: str) -> list[str]:
        return textwrap.wrap(text, width=88, initial_indent=" " * 14, subsequent_indent=" " * 14)

    out = ["The Methods against the code, claim by claim.", ""]
    tally: dict[str, int] = {}
    described: set[str] = set()
    judged = _judged(claims, results.steps, locked)
    for claim in claims:
        for pair in (pair for pair in judged if pair.claim is claim):
            described.add(pair.step)
            tally[pair.standing] = tally.get(pair.standing, 0) + 1
            when = f", read {pair.read_on}" if pair.read_on else ""
            where = pair.found.where if pair.found else "no step of that name ran"
            out.append(
                f"{_SAID[pair.standing]:<13} {at(claim.path, claim.line)}  step "
                f"{pair.step}  {where}{when}"
            )
            if pair.standing == "claim":
                out += said(f"was: {pair.was}")
        out += said(claim.text or "(nothing stands before the anchor)")
        out.append("")
    for paragraph in open_:
        out.append(f"{'open':<13} {at(paragraph.path, paragraph.line)}  no step points here")
        out += said(paragraph.text)
        out.append("")
    alone = [step for name, step in sorted(results.steps.items()) if name not in described]
    for step in alone:
        out.append(f"{'undescribed':<13} step {step.name}  {step.where}  no text points at it")
    if alone:
        out.append("")
    counted = ", ".join(f"{n} {_SAID[k]}" for k, n in sorted(tally.items()) if n)
    out.append(
        f"{sum(tally.values())} pair(s){': ' + counted if counted else ''}; "
        f"{len(open_)} Methods paragraph(s) point at no step; "
        f"{len(alone)} step(s) described by nothing."
    )
    return out


def _compare_parameters(
    project: Project, lock: dict, namespace: dict[str, Value] | None, prose: str | None
) -> Report:
    """The few things both sides state explicitly, and where disagreement is checkable.

    Read as the Methods print: a value bound there, `{{results.param.alpha}}`, is stated in
    them, and the source alone does not hold the number. The Methods are the main text's and
    the supplement's, and a parameter either states is stated. With no Methods found, nothing
    is compared, and `methods-not-found` says so.
    """
    report = Report()
    if not prose:
        return report
    if namespace is None:
        from manuscript_guard.contracts import load_namespace

        namespace = load_namespace(project)[0]
    prose = substitute(prose, {ref: value.display for ref, value in namespace.items()})

    declared = lock.get("parameters", {})
    for name, expected in declared.items():
        if str(expected).lower() in prose.lower():
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="methods-parameter-absent",
                severity=WARN,
                message=f"the Methods do not mention {name} = {expected}",
                path=lock_path(project),
                hint="either the Methods, the main text's or the supplement's, should state "
                "it, or it should not be in the lock",
            )
        )
    return report


def reconcile(
    project: Project,
    *,
    parameters: dict | None = None,
    steps: list[str] | None = None,
    results: Results | None = None,
) -> tuple[Path, int]:
    """Record the analysis as it stands. Run after reading the Methods against the code.

    With `steps`, only the pairs of those steps are recorded, each with its claims as they
    now read and its code as it now stands: the files, and every other pair, stay as the lock
    has them, since nobody has re-read those. Where there was no lock, the one written holds
    no file and no day the files were read on, and `check` goes on saying they never were.
    """
    if results is None:
        from manuscript_guard.contracts import load_namespace

        results = load_namespace(project)[1]
    existing = read_lock(project)
    today = date.today().isoformat()
    current = [pair for pair in pairs_of(project, results, None) if pair.found is not None]
    if steps is None:
        analysis = analysis_digests(project)
        reconciled_on = today
        kept: list[dict] = []
        fresh = current
    else:
        unknown = sorted(set(steps) - {pair.step for pair in current})
        if unknown:
            raise ValueError(
                f"no text points at a step named {', '.join(map(repr, unknown))} that the "
                f"analysis ran, so there is no pair to record"
            )
        analysis = existing.get("analysis", {})
        reconciled_on = existing.get("reconciled_on")
        kept = [pair for pair in _locked(existing) if pair.get("step") not in steps]
        fresh = [pair for pair in current if pair.step in steps]
    recorded = kept + [
        {"step": pair.step, "claim": pair.claim.text, "code": pair.found.digest, "read_on": today}
        for pair in fresh
        if pair.found is not None
    ]
    # Files read against the main text's Methods alone stay so: the lock of a step's pairs
    # keeps the files, and the day, that the lock had.
    keeps_files = steps is not None and analysis
    schema = (existing.get("schema") or SCHEMA_MAIN_TEXT_ONLY) if keeps_files else SCHEMA
    document = {
        "schema": schema,
        # The day the files were read against the Methods: of a lock that holds only pairs,
        # no day. Each pair has its own, `read_on`.
        **({"reconciled_on": reconciled_on} if reconciled_on else {}),
        "parameters": parameters if parameters is not None else existing.get("parameters", {}),
        "analysis": analysis,
    }
    if recorded:
        unique = {(p["step"], p["claim"]): p for p in recorded}
        document["pairs"] = sorted(unique.values(), key=lambda p: (p["step"], p["claim"]))
    path = lock_path(project)
    header = (
        "# Records the analysis as it stood when the Methods were last read against it.\n"
        "# Written by `manuscript-guard methods --reconcile`. Re-run it after you have\n"
        "# re-read the Methods, not merely after the code changed: the point of the file\n"
        "# is that a person looked.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
        newline="\n",
    )
    return path, len(analysis) if steps is None else len(fresh)
