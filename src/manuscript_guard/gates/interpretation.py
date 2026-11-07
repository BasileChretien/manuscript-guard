"""G8: the sentences of the Results and the Discussion that rest on neither a result nor a
citation.

A sentence that gives a result binds it, and one that reports the literature cites it: the
gates hold the first to the analysis and the second to its source and its passage. What is
left of the Results and the Discussion is the authors' interpretation, "the association
probably reflects confounding by indication", "use increases the risk in older patients". It
is the paper's argument, and much of it is right, but nothing holds it to anything, and it
is where an automated scientist was found wrong most often (DESIGN.md, "A sentence that
rests on neither a result nor a citation").

So each sentence of the Results and the Discussion, the main text's and the supplement's, that
holds a word of the claim ladder (`data/claim_strength.yaml`, read as `claims` reads it) and
neither a binding nor a citation is counted: a note for each file that has one
(`interpretation-sentences`), at every stage, and never a warning (Basile, D10.1 of
2026-11-06). `manuscript-guard explain <file>` lists those of a file, which the review-panel
skill sends to a reader with an "interpretation" remit, who says whether each follows from
the results the paper reports. The Abstract, a box and a conclusion are not read, since G8
holds them to the Results already (`summary-claim-stronger`, D10.2), nor are the headings.

A hedge, a limit or a negation alone claims nothing to count: "this cannot be excluded" has
no claim a reader could hold to the results. An anchor of the Methods (`{{method.…}}`) points
at the code and is no binding of a result. The sections are read as G8 reads them for a
summary (`reported.Walk`, `reported.supplement_parts`).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard import claims
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.gates.reported import GATE, Walk, supplement_part, supplement_parts
from manuscript_guard.text.blocks import find_headings
from manuscript_guard.text.placeholders import ANCHOR_NAMESPACE, parse
from manuscript_guard.text.sections import scannable, split_sections

CODE = "interpretation-sentences"
#: What a part of the supplement is read for: its Results and its Discussion.
_ARGUED = ("results", "discussion")
#: A stop and what may close after it, as `claims` reads the end of a sentence, at the end of
#: the text before a citation typed against it; in LaTeX, a tie may stand between.
_CLOSING = r"[)\]\"'*_\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]*"
_STOPPED = re.compile(rf"[.!?]{_CLOSING}\Z")
_STOPPED_TIED = re.compile(rf"[.!?]{_CLOSING}~?\Z")
#: What follows a citation that ends its sentence: a space and no word going on in lower
#: case, as `claims` reads what follows a stop, or the end of the text.
_ENDS = re.compile(r"\s+(?![\sa-z])|\s*\Z")


@dataclass(frozen=True)
class Argued:
    """A sentence of the Results or the Discussion that holds a word of the claim ladder: the
    file and line it starts on, its words as typed with their spaces made one, and whether it
    binds a result or cites a work."""

    path: Path
    line: int
    sentence: str
    rests: bool


#: A sentence as `sentences_in` gives it: the offset it starts at, its line, its words, and
#: whether it binds a result or cites a work.
Read = list[tuple[int, int, str, bool]]


def sentences_in(text: str, inside: Callable[[int], bool],
                 boxed: Callable[[int], object] | None = None,
                 against: Callable[[int], bool] | None = None) -> Read:  # fmt: skip
    """Each sentence of `text` on a line `inside` reads, not a heading's, that holds a word of
    the claim ladder: the offset it starts at, its line, its words, and whether it binds a
    result or cites a work. A sentence in a box (`boxed`, a LaTeX environment) is a summary's,
    and left out. `text` is a Markdown file, or a LaTeX document's printed view, where a
    binding is `{{namespace.key}}` and a citation `[@key]`, as in Markdown.

    A citation typed against the stop before it cites the sentence that stop ends, and the
    next sentence starts after it (`_trailing`; round 1 of #578). `against` says whether the
    citation that opens at an offset of `text` was typed so; in Markdown, it is read in the
    text itself."""
    text = _lined(text)
    read = claims.readable(text)
    breaks = [0, *(at + 1 for at, char in enumerate(text) if char == "\n")]
    headings = _heading_lines(text)
    cuts = [offset for line in headings for offset in _line_span(breaks, line, len(text))]
    trailing = _trailing(text, against or (lambda at: _typed_against(text, at)))
    cuts += [end for _start, end, _stop in trailing]
    rested = _carried(_grounds(text), trailing)
    found = []
    for start, first, end in claims.sentence_pieces(text, read, cuts=cuts):
        line = bisect_right(breaks, first)
        if line in headings or not inside(line):
            continue
        if boxed is not None and boxed(first) is not None:
            continue
        if not _claims(claims.claim_words(read, start, end)):
            continue
        at = bisect_left(rested, start)
        rests = at < len(rested) and rested[at] < end
        found.append((first, line, " ".join(text[first:end].split()), rests))
    return found


def _lined(text: str) -> str:
    """`text` with each line end a line feed, a carriage return alone one too, so that the
    headings and the sentences count the same lines."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _grounds(text: str) -> list[int]:
    """Where each binding of a result and each citation of `text` starts, in order: what a
    sentence rests on. Not an anchor of the Methods, which points at the code, nor a
    citation in a comment, which prints nothing."""
    from manuscript_guard.text.masking import blank_comments
    from manuscript_guard.zotero import find_citations

    bound = [one.start for one in parse(text)[0] if one.namespace != ANCHOR_NAMESPACE]
    return sorted(bound + [use.start for use in find_citations(blank_comments(text), Path())])


def _trailing(text: str, against: Callable[[int], bool]) -> list[tuple[int, int, int]]:
    """Where each citation group starts and ends that ends the sentence before it, and where
    the stop it cites up to stands: typed against its stop ("injury.[@a] We", in LaTeX
    "injury.\\cite{a} We" or "injury.~\\cite{a} We", as a superscript style has it), or after
    such a group with only spaces between ("injury.[@a] [@b] We", round 2 of #578), the last
    followed by a space and no word going on in lower case. Typed after a space, "injury.
    [@a] showed", a group opens the next sentence."""
    from manuscript_guard.text.masking import blank_comments
    from manuscript_guard.zotero.citations import bracketed

    groups = [(group.start(), group.end()) for group in bracketed(blank_comments(text))]
    found: list[tuple[int, int, int]] = []
    first = 0
    while first < len(groups):
        last = first
        while last + 1 < len(groups) and not text[groups[last][1]:groups[last + 1][0]].strip():
            last += 1
        start = groups[first][0]
        if against(start) and _ENDS.match(text, groups[last][1]):
            stop = len(text[:start].rstrip()) - 1
            found += [(begin, end, stop) for begin, end in groups[first:last + 1]]
        first = last + 1
    return found


def _typed_against(text: str, at: int) -> bool:
    """Whether the citation that opens at `at` is typed against a stop, in Markdown."""
    return _STOPPED.search(text, max(0, at - 8), at) is not None


def _carried(grounds: list[int], trailing: list[tuple[int, int, int]]) -> list[int]:
    """`grounds` with each that stands in a citation group of `trailing` moved back to the
    stop the group cites up to, which ends the sentence it cites, in order."""
    if not trailing:
        return grounds
    starts = [start for start, _end, _stop in trailing]

    def carried(at: int) -> int:
        index = bisect_right(starts, at) - 1
        if index < 0 or at >= trailing[index][1]:
            return at
        return trailing[index][2]

    return sorted(carried(at) for at in grounds)


def _claims(words: tuple[claims.Word, ...]) -> bool:
    """Whether a sentence's words of the claim lists claim something: a word of the ladder.
    A hedge, a limit or a negation alone does not."""
    return any(isinstance(kind, int) for _word, kind in words)


def _heading_lines(text: str) -> set[int]:
    """The lines a heading of `text` stands on, its underline with a setext title's."""
    found: set[int] = set()
    for heading in find_headings(scannable(text)):
        line = text.count("\n", 0, heading.start) + 1
        found.update((line, line + 1) if heading.setext else (line,))
    return found


def _line_span(breaks: list[int], line: int, length: int) -> tuple[int, int]:
    """Where `line` starts in the text and where the next one does, or the text's end."""
    return breaks[line - 1], breaks[line] if line < len(breaks) else length


def argued(project: Project) -> list[Argued]:
    """Each sentence of the Results and the Discussion that holds a word of the claim ladder,
    in the files the manuscript prints, in order, its supplement's last."""
    from manuscript_guard.gates.journal import abstract_title, box_rules_of
    from manuscript_guard.text.reader import LATEX, manuscript_format

    root = project.path("manuscript")
    walk = Walk(abstract_title(project), box_rules_of(project))
    if manuscript_format(root) == LATEX:
        return _latex_argued(root, walk)
    sources = source_files(root)
    supplement = [path for path in sources if is_supplementary(root, path)]
    paper = printed_order([path for path in sources if path not in supplement],
                          supplementary=False)  # fmt: skip
    found: list[Argued] = []
    for path in [*paper, *supplement]:
        text = read_text(path)
        read = supplement_argued(text) if path in supplement else paper_argued(text, walk)
        found += [Argued(path, line, said, rests) for _at, line, said, rests in read]
    return found


def paper_argued(text: str, walk: Walk, boxed: Callable[[int], object] | None = None,
                 against: Callable[[int], bool] | None = None) -> Read:  # fmt: skip
    """`sentences_in` of one file of the paper, under the headings `walk` carries into it
    from the files before: its Results and its Discussion."""
    text = _lined(text)
    sections = [one for one in split_sections(scannable(text)) if one.level]
    return sentences_in(text, walk.arguing(sections), boxed, against)


def supplement_argued(text: str, against: Callable[[int], bool] | None = None) -> Read:
    """`sentences_in` of one file of the supplement: its Results and its Discussion."""
    text = _lined(text)
    return sentences_in(text, _supplement_inside(text), against=against)


def _supplement_inside(text: str) -> Callable[[int], bool]:
    """Whether a line of a file of the supplement is in its Results or its Discussion: the
    innermost heading over it that names the Methods, the Results or the Discussion decides."""
    starts, parts = supplement_parts(text, supplement_part)
    return lambda line: parts[bisect_right(starts, line) - 1] in _ARGUED


def _latex_argued(root: Path, walk: Walk) -> list[Argued]:
    """`argued` of a LaTeX manuscript, read in each document's printed view, each sentence
    named at the `.tex` file and line it starts on, as G8 names a summary's."""
    from manuscript_guard.gates.reported import _boxed_in
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import ENTRY, read_document

    found: list[Argued] = []
    for supplementary in (False, True):
        sources = [source for source in read_document(root, supplementary=supplementary).sources
                   if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
        view = printed(sources)
        against = _typed_against_in(view)
        if supplementary:
            read = supplement_argued(view.text, against)
        else:
            read = paper_argued(view.text, walk, _boxed_in(view, sources, walk.boxes), against)
        for first, line, said, rests in read:
            where = view.place(first)
            path, placed = (where[0].path, where[1]) if where else (ENTRY, line)
            found.append(Argued(root / path, placed, said, rests))
    return found


def _typed_against_in(view) -> Callable[[int], bool]:
    """Whether the citation that opens at an offset of a LaTeX document's printed view was
    typed against a stop, or a stop and a tie, in its source: `before.\\cite{a}`. The view
    writes a space before every citation, so it is read in the source the view came from."""
    starts = [origin[0] for origin in view.origins]

    def against(offset: int) -> bool:
        index = bisect_right(starts, offset) - 1
        if index < 0:
            return False
        _start, source, at, linear = view.origins[index]
        return not linear and _STOPPED_TIED.search(source.text, max(0, at - 8), at) is not None

    return against


def check_interpretation(project: Project) -> Report:
    """A note for each file whose Results or Discussion hold a sentence that claims and rests
    on neither a result nor a citation, counting them."""
    every = argued(project)
    by_file: dict[Path, list[Argued]] = {}
    for one in every:
        by_file.setdefault(one.path, []).append(one)
    report = Report()
    for path, ones in by_file.items():
        bare = [one for one in ones if not one.rests]
        if not bare:
            continue
        shown = _shown(project, path)
        report = report.with_findings(Finding(
            gate=GATE, code=CODE, severity=INFO, path=path, line=bare[0].line,
            message=f"{len(bare)} of the {len(ones)} sentences of the Results and the "
            "Discussion here that hold a word of the claim ladder "
            f"{'rests' if len(bare) == 1 else 'rest'} on neither a result nor a citation: "
            "the paper's interpretation, which no gate checks",
            context=bare[0].sentence[:160],
            hint=f"`manuscript-guard explain {shown}` lists them; a reader of the review "
            "panel can be sent the list and asked whether each follows from the results the "
            "paper reports (the review-panel skill's interpretation remit). Many such "
            "sentences are right, and nothing needs changing for this note",
        ))  # fmt: skip
    return report


def listed(project: Project, file: Path) -> list[Argued]:
    """The sentences `check`'s note counts in one file of the manuscript, in order."""
    wanted = file.resolve()
    return [one for one in argued(project) if not one.rests and one.path.resolve() == wanted]


def _shown(project: Project, path: Path) -> str:
    """A file as the hint names it, from the project's folder, where `explain` is run."""
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return path.as_posix()
