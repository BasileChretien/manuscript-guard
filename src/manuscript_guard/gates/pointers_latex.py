"""G2's pointers to tables and figures in a LaTeX manuscript (step 13).

LaTeX numbers a table or a figure where a float's `\\caption` steps its counter, and prints the
number a cross-reference to its `\\label` asks for; the compile itself says when a `\\ref`
names a label nobody defined. A pointer typed as text, "Table 4", is held here as
`pointers.py` holds one in a Markdown manuscript: it names a table or a figure the document
numbers, and the main text cites each of its own in the order ICMJE asks for, a
cross-reference to one's label counting as its citation, as a ref binding does in Markdown.

The document is read in the view `printed(..., pointing=True)` writes, the files the build
prints in their order: each caption a float numbers is a mark with its kind and the labels
after it, and each cross-reference one with its labels, so that displays, pointers and
cross-references come in the order LaTeX prints them, and each is placed back at its
`.tex` file and line.

**Only where the count is known.** A kind of one document is counted where every display of
it is numbered by a float's `\\caption` the view reads. A float with no caption the view
reads, a `\\captionof`, a `longtable`'s caption or a page `\\includepdf` takes in leaves the
kind uncounted, and one note says so, as `pointers.py` does of a table placed by hand. A
`\\mg{table.key}` outside a float is a table LaTeX does not number. A table or a figure sent
to the journal as a file of its own is declared in paper.yaml (`displays:`), as for Markdown.

**The appendix is the supplement's.** A table or a figure the main document prints after
`\\appendix` or in the appendix package's `appendices`, or under a heading that names a
supplement, an appendix or supporting information, to the next heading of its level, is not
held to ICMJE's order or to being cited, as a supplement's is not. A pointer typed to it is
held to its place among the document's tables or figures, counted on from the main text's,
which is the number LaTeX prints unless the class or the author numbers the appendix apart
(Known gaps) (Basile, 2026-10-23, after an Elsevier paper cited its "Supplementary Table"
first and was told it was out of order).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding, Report
from manuscript_guard.gates.pointers import (
    _DASHES,
    AS_FILES,
    FIGURE,
    TABLE,
    Pointer,
    _in_order,
    pointers_at,
)
from manuscript_guard.text.blocks import find_headings

GATE = "G2"
#: A heading that names the main document's supplement, its whole title or before a label,
#: a colon or a stop: "Supplementary materials", "Supplementary Table S1", "Supplement 2",
#: "Appendix A: Proofs", "Appendices", "Supporting information", "S1 Appendix", "Electronic
#: supplementary material", "Additional file 1", "Web appendix", "Data supplement",
#: "eMethods"; "Supplementary tables and figures", "Supplementary material for the online
#: version", and a label's title after it, "Appendix A Proofs", "Appendix 1 — Search" (fix
#: round). Not one the word only describes, "Supplementary analyses", "Supplementary data
#: sources", "Supplemental oxygen", "Appendix diameter", "Supplement-related events" or
#: "Supplement A arm": a title goes on after an appendix's label only, and a hyphen parts it
#: only with a space on each side (rounds 1 and 2, and the fix rounds).
_SUPPLEMENT_HEADING = re.compile(
    r"\s*(?:[A-Z]?\d+(?:\.\d+)*[.):]?\s+)?(?:"
    r"(?:(?:e|web\s+)?appendi(?:x|ces)|S\d+\s+appendix)"
    r"(?:\s+(?:S?\d+[A-Z]?|[A-Z](?:\.\d+)?)(?:\s+.*)?)?"
    r"|(?:(?:online\s+|electronic\s+)?(?:supplementary|supplemental)(?:\s+(?:materials?\s+and"
    r"\s+methods|(?:tables?|figures?)(?:\s+and\s+(?:tables?|figures?))?|materials?|information"
    r"|data|files?|appendi(?:x|ces)|text|content|methods|notes)(?:\s+(?:for|to)\s.*)?)?"
    r"|(?:online\s+|data\s+)?supplement|supporting\s+information|S\d+\s+(?:text|file)"
    r"|additional\s+files?|e(?:methods|tables?|figures?))"
    r"(?:\s+(?:S?\d+[A-Z]?|[A-Z](?:\.\d+)?))?)"
    r"(?:(?:\s*[.:\N{EN DASH}\N{EM DASH}]|\s+-\s).*)?\s*$",
    re.IGNORECASE,
)
#: The cross-references that cite what they point at: not a page's, which `\\pageref` prints.
_PAGES = frozenset({"pageref", "cpageref", "cpagerefrange", "Cpagerefrange"})
#: cleveref's ranges, `\\crefrange{a}{b}`, which cite what LaTeX numbers from a to b.
_RANGES = frozenset({"crefrange", "Crefrange"})
#: What joins two cross-references into a range in the view, `\\ref{a}--\\ref{b}`: a dash,
#: with spaces or a line's end around it, as a typed range's in `pointers.py`.
_RANGE_DASH = re.compile(r"[^\S\n]*\n?[^\S\n]*[" + _DASHES + r"][^\S\n]*\n?[^\S\n]*")
#: How far apart a range's ends may be, as `pointers.py` reads one typed.
_RANGE = 50


@dataclass(frozen=True)
class _Numbered:
    """A display LaTeX numbers: its kind, its document, and its number there."""

    kind: str
    supplementary: bool
    number: int


def check_pointers_latex(project: Project) -> Report:
    """G2's pointers, as the module says, of a LaTeX manuscript."""
    from manuscript_guard.text.latex.structure import read_document

    folder = project.path("manuscript")
    declared = project.setting("displays") or {}
    as_files = {key: int(declared.get(name) or 0) for key, name in AS_FILES.items()}
    documents = {
        supplementary: [source for source in read_document(folder, supplementary=supplementary)
                        .sources if not source.loose
                        and not source.path.lower().endswith(".sty")]
        for supplementary in (False, True)
    }  # fmt: skip
    return pointers_in_documents(documents, folder, as_files)


def pointers_in_documents(documents: dict, folder: Path, as_files: dict) -> Report:
    """G2's pointers of the main text's sources and the supplement's, `documents` by whether
    each is the supplement, each list in the include tree's order; `as_files` what paper.yaml
    declares sent as files, by document and kind."""
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import ENTRY

    views = {part: printed(sources, pointing=True) for part, sources in documents.items()}
    bound, labels, uncounted, apart = _numbered(views)
    pointers, typed = _cited(views, labels, folder)
    total = {key: bound[key] + as_files[key] for key in AS_FILES}
    report = _to_nothing(typed, total, bound, as_files, uncounted)
    report = report.merge(_unchecked(pointers, total, uncounted, folder / ENTRY))
    report = report.merge(_in_order(pointers, total, uncounted, folder / ENTRY, apart))
    return report.with_counts(
        pointers=len(pointers),
        pointers_checked=sum(
            total[p.supplementary, p.kind] > 0 and (p.supplementary, p.kind) not in uncounted
            for p in pointers
        ),
        tables_placed=bound[False, TABLE],
        figures_placed=bound[False, FIGURE],
    )


def _marks():
    """A display's, a cross-reference's or the appendix's mark in the view: its kind, and what
    it holds."""
    from manuscript_guard.text.latex.printed import APPENDIX, DISPLAY, MARK_END, REFERENCE

    return re.compile(f"([{DISPLAY}{REFERENCE}{APPENDIX}])([^{MARK_END}]*){MARK_END}")


def _supplement_parts(text: str) -> list[tuple[int, int]]:
    """Where each heading that names a supplement runs in the view, to the next heading of
    its level or above, or to the reference list, past which a paper may place its floats
    (round 2)."""
    from manuscript_guard.text.latex.printed import APPENDIX, MARK_END

    headings = find_headings(text)
    lists = [found.start() for found in re.finditer(f"{APPENDIX}references{MARK_END}", text)]
    parts = []
    for index, heading in enumerate(headings):
        if _SUPPLEMENT_HEADING.match(heading.title):
            ends = [later.start for later in headings[index + 1 :] if later.level <= heading.level]
            ends += [at for at in lists if at > heading.start]
            parts.append((heading.start, min(ends, default=len(text))))
    return parts


def _numbered(views: dict):
    """How many tables and figures each document numbers, the display each label names, the
    kinds a document numbers in a way the view cannot count, and the numbers of the main
    document's displays that are its supplement's, in its appendix or under a heading that
    names one."""
    from manuscript_guard.text.latex.printed import APPENDIX, DISPLAY

    labels: dict[tuple[bool, str], _Numbered] = {}
    bound: dict[tuple[bool, str], int] = {key: 0 for key in AS_FILES}
    uncounted: set[tuple[bool, str]] = set()
    apart: dict[tuple[bool, str], set[int]] = {key: set() for key in AS_FILES}
    for supplementary, view in views.items():
        parts = _supplement_parts(view.text)
        # `\\appendix` holds to the end; an environment to where it ends (round 2).
        command = environment = False
        for found in _marks().finditer(view.text):
            if found[1] == APPENDIX:
                command = command or found[2] == ""
                environment = {"environment": True, "end": False}.get(found[2], environment)
            if found[1] != DISPLAY:
                continue
            appendix = command or environment
            code, named = found[2][:1], found[2][1:]
            kind = TABLE if code.lower() == "t" else FIGURE
            if code.isupper():
                uncounted.add((supplementary, kind))
                continue
            bound[supplementary, kind] += 1
            display = _Numbered(kind, supplementary, bound[supplementary, kind])
            if appendix or any(low <= found.start() < high for low, high in parts):
                apart[supplementary, kind].add(display.number)
            for label in filter(None, named.split(",")):
                labels.setdefault((supplementary, label), display)
    return bound, labels, uncounted, apart


def _cited(views: dict, labels: dict, folder: Path) -> tuple[list[Pointer], list[Pointer]]:
    """Every pointer and cross-reference to a display, in the order each document prints them,
    each at its `.tex` file and line; and the pointers typed among them."""
    from manuscript_guard.text.latex.printed import REFERENCE
    from manuscript_guard.text.latex.structure import ENTRY

    pointers: list[Pointer] = []
    typed: list[Pointer] = []
    for supplementary, view in views.items():
        heads = {view.text.count("\n", 0, h.start) + 1 for h in find_headings(view.text)}
        found: list[tuple[int, Pointer]] = []
        # A mark's labels are no words of the text: `fig1` is no pointer to Figure 1.
        scanned = _marks().sub(lambda mark: mark[1] + " " * len(mark[2]) + mark[0][-1], view.text)
        for at, pointer in pointers_at(scanned, folder / ENTRY):
            placed = _placed(view, at, folder, pointer)
            if placed is not None:
                found.append((at, placed))
                typed.append(placed)
        last: tuple[int, _Numbered | None] = (-1, None)
        for mark in _marks().finditer(view.text):
            command, _colon, named = mark[2].partition(":")
            if mark[1] != REFERENCE or command in _PAGES:
                continue
            line = view.text.count("\n", 0, mark.start()) + 1
            shown = [(label, labels.get((supplementary, label))
                      or labels.get((not supplementary, label)))
                     for label in filter(None, named.split(","))]  # fmt: skip
            # A typed range, `\\ref{a}--\\ref{b}`, cites what LaTeX numbers between the two,
            # as "Figures 2-4" does in Markdown (corpus round, 2026-10-23).
            after, before = last
            if shown and after >= 0 and _RANGE_DASH.fullmatch(view.text, after, mark.start()):
                shown[:0] = _between(before, shown[0][1])
            if command in _RANGES and len(shown) == 2:
                shown[1:1] = _between(shown[0][1], shown[1][1])
            last = (mark.end(), shown[-1][1] if shown else None)
            for label, display in shown:
                if display is None:
                    continue
                reference = Pointer(
                    kind=display.kind, supplementary=display.supplementary,
                    number=display.number, path=folder / ENTRY, line=line,
                    shown=f"\\{command}{{{label}}}", cites=line not in heads,
                )  # fmt: skip
                placed = _placed(view, mark.start(), folder, reference)
                if placed is not None:
                    found.append((mark.start(), placed))
        pointers += [pointer for _at, pointer in sorted(found, key=lambda pair: pair[0])]
    return pointers, typed


def _between(first: _Numbered | None, last: _Numbered | None) -> list[tuple[str, _Numbered]]:
    """The displays a range from `first` to `last` takes in between them: of one kind and one
    document, the first numbered before the last, at most `_RANGE` apart, as `pointers.py`
    reads a typed range."""
    if (
        first is None
        or last is None
        or (first.kind, first.supplementary) != (last.kind, last.supplementary)
        or not first.number < last.number <= first.number + _RANGE
    ):
        return []
    return [("", replace(first, number=number)) for number in range(first.number + 1, last.number)]


def _to_nothing(typed, total, bound, as_files, uncounted) -> Report:
    """Each pointer typed to a table or a figure past what its document numbers."""
    report = Report()
    for pointer in typed:
        key = (pointer.supplementary, pointer.kind)
        count = total[key]
        if not count or key in uncounted or 1 <= pointer.number <= count:
            continue
        where = "the supplement" if pointer.supplementary else "the main text"
        plural = "" if bound[key] == 1 else "s"
        files_too = f" and {as_files[key]} sent as files" if as_files[key] else ""
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pointer-to-nothing",
                message=f"{pointer.shown!r} points at {pointer.kind} "
                f"{'S' if pointer.supplementary else ''}{pointer.number}, and {where} "
                f"numbers {bound[key]} {pointer.kind}{plural}{files_too}",
                path=pointer.path,
                line=pointer.line,
                hint="number tables and figures as the document captions them, or point at one "
                "with `\\ref` to its `\\label`, and LaTeX prints its number; a table or figure "
                "moved to the supplement is Table S1 or Figure S1 there; one sent to the "
                f"journal as a file of its own is declared in paper.yaml, `displays: "
                f"{{{AS_FILES[key]}: 1}}`",
            )
        )
    return report


def _placed(view, at: int, folder: Path, pointer: Pointer) -> Pointer | None:
    """`pointer` at the `.tex` file and line the view's offset `at` stands on."""
    where = view.place(at)
    if where is None:
        return None
    source, line = where
    return replace(pointer, path=folder / source.path, line=line)


def _unchecked(
    pointers: list[Pointer],
    total: dict[tuple[bool, str], int],
    uncounted: set[tuple[bool, str]],
    entry: Path,
) -> Report:
    """One note for each document and kind whose pointers could not be checked, and why."""
    report = Report()
    for supplementary in (False, True):
        for kind in (TABLE, FIGURE):
            key = (supplementary, kind)
            mine = [p for p in pointers if (p.supplementary, p.kind) == key]
            if not mine or (total[key] and key not in uncounted):
                continue
            where = "the supplement" if supplementary else "the main text"
            why = (
                f"{where} has a {kind} no `\\caption` the reader reads numbers"
                if key in uncounted
                else f"{where} numbers none with a float's `\\caption` and declares none sent "
                "as files"
            )
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="pointers-unchecked",
                    severity=INFO,
                    message=f"{len(mine)} pointer(s) to {where}'s {kind}s were not checked: "
                    f"{why}, so its {kind}s cannot be counted",
                    path=entry,
                    hint=f"put each {kind} in a float with a `\\caption`, and declare those "
                    f"sent as files of their own in paper.yaml (`displays: "
                    f"{{{AS_FILES[key]}: <how many>}}`), to have its pointers checked",
                )
            )
    return report
