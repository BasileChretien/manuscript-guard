"""G4: the statements every paper makes, and no heading with nothing under it.

A paper written for BMJ Open (2026-11-26) built with four headings and nothing under them:
"Data availability statement", "Ethics statements", "Disclaimer" and "Contributors, funding and
competing interests" each held only an HTML comment saying what was still to be written, which
the build does not print. `check` passed at the drafting stage. G4 asked only for the
statements a journal's profile lists, and an empty heading is a match for its pattern. So two
findings, each a note before the drafting stage, a warning while the paper is drafted and a
failure from internal review on (the author's rule, 2026-11-26):

- `section-empty`: a heading of the main text or the supplement under which nothing is
  printed before the next heading of its level or above: no text, or only HTML comments and
  white space. A heading whose subsections print something is not empty; each empty
  subsection is said on its own. The reference list's heading is passed over, since the build
  puts the bibliography under it, and so is a heading with no title.
- `declaration-missing`: the main text has no statement of one of the kinds every paper
  makes, where no journal's profile says which statements the journal asks for: data
  availability, ethics, funding, competing interests, author contributions, and AI use where
  a record shows a model at work or `authors.yaml` declares a tool under `ai_use`
  (`gates/ai_use.wanted`). A statement is a heading or a paragraph's label of its kind with
  something printed under it: the headings of `data/disclosures.yaml` for funding, interests,
  ethics and contributions, as G4 reads the declarations, the Acknowledgements among the
  funding statement's; the Data availability statement's (`data_statement.HEADING`, or the
  profile's own); the AI-use statement's (`ai_use.default_places`). An ethics statement may
  also be a sentence of the Methods that holds the words of its heading, or a sentence
  anywhere in the main text that says no approval was needed (`no_approval`, as G4 reads a
  denial); and any of them a sentence of a Declarations section that holds the words of its
  kind's heading.

A kind whose only heading is empty is said once, by `section-empty`. Where the target
journal's profile lists required statements, they are the journal's, read from its page, and
`missing-required-statement` asks for them: this check then asks for none of its own, so that
a kind is never asked for twice, nor asked for against the journal's own list. Its empty
headings are still said.

English only, as the declarations are read. A LaTeX manuscript's statements are read in its
printed view; its headings are not checked for emptiness (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.text.blocks import find_headings, scannable
from manuscript_guard.text.masking import blank, front_matter_end, html_comments, metadata_blocks
from manuscript_guard.text.sections import Section, split_sections

GATE = "G4"
EMPTY = "section-empty"
MISSING = "declaration-missing"

DATA, ETHICS, FUNDING, INTERESTS, CONTRIBUTIONS, AI_USE = (
    "data", "ethics", "funding", "interests", "contributions", "ai_use")  # fmt: skip
#: The kinds of statement every paper makes, in the order they are said.
KINDS = (DATA, ETHICS, FUNDING, INTERESTS, CONTRIBUTIONS, AI_USE)
#: What each is called in a finding.
NAMES = {
    DATA: "data availability statement",
    ETHICS: "ethics statement",
    FUNDING: "funding statement",
    INTERESTS: "competing interests statement",
    CONTRIBUTIONS: "author contributions statement",
    AI_USE: "AI-use statement",
}
#: The usual heading of each kind, as a finding suggests it.
USUAL = {
    DATA: "Data availability",
    ETHICS: "Ethics",
    FUNDING: "Funding",
    INTERESTS: "Competing interests",
    CONTRIBUTIONS: "Author contributions",
    AI_USE: "Use of AI",
}
#: What to write, for each kind.
WRITE = {
    DATA: "say where the data and the code can be had, or why they cannot be shared",
    ETHICS: "name the committee that approved the study and its reference, or say why no "
    "approval was needed",
    FUNDING: "name each funder and grant, or say that the work received no funding",
    INTERESTS: "declare each author's competing interests, or say that there are none",
    CONTRIBUTIONS: "say what each author did, in CRediT's roles where the journal uses them",
    AI_USE: "name each AI tool and what it did; `manuscript-guard review --ai-use` lists what "
    "the records show",
}

#: The words of the Data availability statement's heading in a sentence: "Data sharing is not
#: allowed", "the availability of the data".
_DATA_WORDS = re.compile(
    r"\b(?:data (?:and code |and materials )?availability|availability of (?:the )?data"
    r"|data sharing)\b", re.IGNORECASE)
#: The kinds G4's reading of the declarations knows by their headings and labels.
_DISCLOSED = (FUNDING, INTERESTS, ETHICS, CONTRIBUTIONS)
STATED, HEADED_EMPTY = "stated", "empty"


# ----------------------------------------------------------------------- empty headings


@dataclass(frozen=True)
class EmptyHeading:
    """A heading with nothing printed under it, at its line of the text it was read in."""

    title: str
    level: int
    line: int
    offset: int


def _shown(text: str) -> str:
    """`text` with what the build does not print blanked, offsets kept: the front matter, the
    YAML blocks of the body and the HTML comments. Fenced listings are printed, and kept."""
    spans = [(0, front_matter_end(text)), *metadata_blocks(text), *html_comments(text)]
    return blank(text, spans)


def _opens(text: str, start: int, setext: bool) -> int:
    """Where a heading's own text starts: past its line, and past its underline."""
    body = text.find("\n", start)
    if body != -1 and setext:
        body = text.find("\n", body + 1)
    return len(text) if body == -1 else body


def _printed(headings: list, bodies: list[str]) -> list[bool]:
    """For each heading, whether anything is printed under it: in its own text, or under a
    heading below it, to the next of its level or above. One pass, a stack of the headings
    still open."""
    printed = [bool(body.strip()) for body in bodies]
    open_: list[int] = []
    for index, heading in enumerate([*headings, None]):
        while open_ and (heading is None or headings[open_[-1]].level >= heading.level):
            closed = open_.pop()
            if open_ and printed[closed]:
                printed[open_[-1]] = True
        if heading is not None:
            open_.append(index)
    return printed


def _passed_over(title: str, level: int) -> bool:
    """A heading never said to be empty: one with no title, and the reference list's, which
    the build fills with the bibliography."""
    return not title or Section(title=title, level=level, body="", line=0).is_references


def empty_headings(text: str) -> list[EmptyHeading]:
    """Each heading of `text` under which nothing is printed, in order: its own text and that
    of every heading below it, to the next of its level or above, blank once the comments
    are. Headings are found as the gates find them (`scannable`), so a `#` line in a listing
    is none."""
    headings = find_headings(scannable(text))
    shown = _shown(text)
    bodies = [
        shown[_opens(text, heading.start, heading.setext):(
            headings[index + 1].start if index + 1 < len(headings) else len(text))]
        for index, heading in enumerate(headings)
    ]  # fmt: skip
    breaks = [at for at, char in enumerate(text) if char == "\n"]
    return [
        EmptyHeading(heading.title.strip(), heading.level,
                     bisect_left(breaks, heading.start) + 1, heading.start)
        for heading, printed in zip(headings, _printed(headings, bodies), strict=True)
        if not printed and not _passed_over(heading.title.strip(), heading.level)
    ]  # fmt: skip


# ----------------------------------------------------------------------- the statements


def _data_kind(title: str, heading: str | None) -> bool:
    from manuscript_guard.gates.data_statement import HEADING

    try:
        return bool(re.search(heading or HEADING, title, re.IGNORECASE))
    except re.error:
        return bool(re.search(HEADING, title))


def _ai_kind(title: str) -> bool:
    from manuscript_guard.gates.ai_use import _STATEMENT, _TOOL

    return bool(_TOOL.search(title) and _STATEMENT.search(title))


def kinds_of(title: str, data_heading: str | None = None) -> list[str]:
    """The standard kinds a heading or a label names: "Contributors, funding and competing
    interests" names three. A Declarations section is `declarations`, read for its words."""
    from manuscript_guard.gates.disclosures import DECLARATIONS, _heading_kinds

    found = [kind for kind in _heading_kinds(title) if kind in (*_DISCLOSED, DECLARATIONS)]
    if _data_kind(title, data_heading):
        found.append(DATA)
    if _ai_kind(title):
        found.append(AI_USE)
    return found


def _words_of(kind: str, text: str) -> bool:
    """Whether `text` holds the words of `kind`'s heading: "no competing interests", "this
    work received no funding", "ethical approval", "no generative AI was used"."""
    from manuscript_guard.gates.disclosures import _data, _pattern, fold

    if kind == DATA:
        return bool(_DATA_WORDS.search(text))
    if kind == AI_USE:
        return any(_ai_kind(sentence) for sentence in re.split(r"(?<=[.!?])\s+|\n", text))
    pattern = _data()["headings"][kind]
    # The headings' patterns that hold to a whole title (`^...$`) say nothing of a sentence.
    return bool(_pattern(pattern).search(fold(text)))


def stated(text: str, *, abstract: str | None = None,
           data_heading: str | None = None) -> dict[str, str]:  # fmt: skip
    """Each standard kind the main text holds: `stated` where something is printed under a
    heading or a label of it, `empty` where its only heading has nothing printed under it;
    a kind the text does not hold is left out. Headings' own lines are no statement: the
    Methods and a Declarations section are read for their words without them."""
    from manuscript_guard.gates.disclosures import (
        DECLARATIONS,
        _data,
        _first,
        _label_kinds,
        _labelled,
        _own,
    )
    from manuscript_guard.text.section_names import methods_sections
    from manuscript_guard.text.sections import subsections

    printed = scannable(text)
    sections = split_sections(printed)
    empty = {heading.line for heading in empty_headings(text)}
    said: dict[str, str] = {}

    def found(kind: str, how: str) -> None:
        if said.get(kind) != STATED:
            said[kind] = how

    for section in sections:
        if not section.title:
            continue
        for kind in kinds_of(section.title, data_heading):
            if kind == DECLARATIONS:
                # Its own words, before a heading of its parts, which are read as headings.
                for named in KINDS:
                    if _words_of(named, section.body):
                        found(named, STATED)
            elif _own(section.enclosed, kind).strip():
                found(kind, STATED)
            elif section.line in empty:
                found(kind, HEADED_EMPTY)
    for section in methods_sections(sections, abstract):
        parts = subsections(sections, sections.index(section))
        if _words_of(ETHICS, " ".join(part.body for part in parts)):
            found(ETHICS, STATED)
    # A sentence that says no approval was needed is an ethics statement where it stands: in
    # the Data availability statement, say, as G4 reads a denial (`ethics-approval-denied`).
    if _first(_data()["no_approval"], printed):
        found(ETHICS, STATED)
    for label, rest in _labelled(printed):
        kinds = [kind for kind in _label_kinds(label) if kind in _DISCLOSED]
        kinds += [DATA] if _data_kind(label, data_heading) else []
        kinds += [AI_USE] if _ai_kind(label) else []
        for kind in kinds:
            if rest.strip():
                found(kind, STATED)
    return said


def missing(said: dict[str, str], wanted: Iterable[str] = KINDS, *,
            empty_said: bool = True) -> list[str]:  # fmt: skip
    """The kinds of `wanted` that `said`, as `stated` gives it, does not hold. One whose only
    heading is empty is left out where `empty_said`, since `section-empty` says it."""
    return [kind for kind in wanted
            if said.get(kind) != STATED and not (empty_said and said.get(kind) == HEADED_EMPTY)]


# ------------------------------------------------------------------------------ the check


@dataclass(frozen=True)
class _Source:
    """One file of a document as the gates join them: where its text starts in the whole,
    and how many lines of front matter come before it in the file."""

    path: Path
    start: int
    skipped: int


def _document(folder: Path, *, supplementary: bool) -> tuple[str, list[_Source]]:
    """A Markdown document as `journal.main_text` joins it, each file's front matter left
    out, with where each file starts."""
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files

    paths = [path for path in source_files(folder)
             if is_supplementary(folder, path) == supplementary]  # fmt: skip
    pieces, sources, at = [], [], 0
    for path in printed_order(paths, supplementary=supplementary):
        text = read_text(path)
        head = front_matter_end(text)
        if pieces:
            at += 2
        sources.append(_Source(path, at, text.count("\n", 0, head)))
        pieces.append(text[head:])
        at += len(text) - head
    return "\n\n".join(pieces), sources


def _located(joined: str, sources: list[_Source], offset: int) -> tuple[Path | None, int]:
    source = next((s for s in reversed(sources) if s.start <= offset), None)
    if source is None:
        return None, joined.count("\n", 0, offset) + 1
    return source.path, source.skipped + joined.count("\n", source.start, offset) + 1


def severity_at(stage: str | None) -> str:
    """A note before the drafting stage, a warning while drafting, a failure from internal
    review on. No stage is drafting, the default."""
    from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, stage_index

    here = stage_index(stage or DRAFTING)
    if here >= stage_index(INTERNAL_REVIEW):
        return FAIL
    return WARN if here >= stage_index(DRAFTING) else INFO


def _empty_finding(heading: EmptyHeading, path: Path | None, line: int, severity: str,
                   heads: list[str]) -> Finding:  # fmt: skip
    """`heads`: the statements the manuscript has nowhere but under this heading."""
    named = [NAMES[kind] for kind in heads]
    lacking = (f", so the manuscript has no {', '.join(named[:-1])} or {named[-1]}"
               if len(named) > 1 else f", so the manuscript has no {named[0]}" if named else "")
    return Finding(
        gate=GATE, code=EMPTY, severity=severity, path=path, line=line,
        message=f"the heading {heading.title!r} has nothing under it{lacking}",
        hint="write what goes under it, or take the heading out until it is written: an HTML "
        "comment is not printed, so the built document shows the heading alone"
        + "".join(f"; {WRITE[kind]}" for kind in heads),
        subject=heading.title,
    )  # fmt: skip


def _missing_finding(kind: str, path: Path | None, severity: str) -> Finding:
    return Finding(
        gate=GATE, code=MISSING, severity=severity, path=path,
        message=f"the manuscript has no {NAMES[kind]}",
        hint=f"{WRITE[kind]}, under a heading such as \"{USUAL[kind]}\" or in a paragraph "
        f"labelled \"{USUAL[kind]}:\"; the submission-pack skill drafts the declarations from "
        "authors.yaml",
        subject=kind,
    )  # fmt: skip


def check_statements(project: Project, stage: str | None = None) -> Report:
    """G4's check of the standard statements and of empty headings, at `stage` (the module's
    docstring)."""
    from manuscript_guard.gates.ai_use import wanted
    from manuscript_guard.gates.data_statement import _profile_heading
    from manuscript_guard.gates.journal import _profile, abstract_title, main_text
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if not folder.is_dir():
        return Report()
    severity = severity_at(stage)
    markdown = manuscript_format(folder) != LATEX
    data_heading = _profile_heading(project)
    said = stated(main_text(project), abstract=abstract_title(project),
                  data_heading=data_heading)  # fmt: skip
    findings: list[Finding] = []
    if markdown:
        for supplementary in (False, True):
            joined, sources = _document(folder, supplementary=supplementary)
            for heading in empty_headings(joined):
                path, line = _located(joined, sources, heading.offset)
                named = kinds_of(heading.title, data_heading)
                heads = [] if supplementary else [
                    kind for kind in KINDS if kind in named and said.get(kind) == HEADED_EMPTY]
                findings.append(_empty_finding(heading, path, line, severity, heads))
    profile = _profile(project) or {}
    # The journal's list, where its profile has one, is `missing-required-statement`'s.
    wanted_kinds = [] if profile.get("required_statements") else [
        kind for kind in KINDS if kind != AI_USE or wanted(project)]  # fmt: skip
    where = _main_file(folder)
    findings += [_missing_finding(kind, where, severity)
                 for kind in missing(said, wanted_kinds, empty_said=markdown)]
    return Report(tuple(findings))


def _main_file(folder: Path) -> Path | None:
    """The file a statement missing from the main text is said of: `main.md`, or the main
    text's first file."""
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    glob = "*.tex" if manuscript_format(folder) == LATEX else None
    paths = [path for path in (source_files(folder, glob=glob) if glob else source_files(folder))
             if not is_supplementary(folder, path)]  # fmt: skip
    ordered = printed_order(paths, supplementary=False)
    return ordered[0] if ordered else None


__all__ = ["EMPTY", "KINDS", "MISSING", "check_statements", "empty_headings", "kinds_of",
           "missing", "severity_at", "stated"]  # fmt: skip
