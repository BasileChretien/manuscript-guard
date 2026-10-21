"""A pointer to a table or a figure names one the document carries, and in order.

"As Table 4 shows" is a number like any other, and G2 lets it through as a cross-reference:
the rule reads the word and the digits after it. So "Table 4000" passed, and so did a
pointer to a table the document does not have. The example's own text called its first
table "Table 2" and its second "Table 3", after a third had moved to the supplement. LaTeX
refuses a `\\ref` to a label nobody defined; this is the same refusal for a pointer typed as
text.

**Only where the count is known.** A kind, tables or figures, of one document, the main
text or the supplement, is checked only where every one of them is placed by its binding,
`{{table.<key>}}` or `{{figure.<key>}}`, in the order the files print: Table 1 is the first
table the main text places, Table S1 the first the supplement places. Where a document
places one by hand (a pipe, grid or simple table, an image, raw HTML), or places none
because its figures go to the journal as files of their own and `paper.yaml` does not
declare them under `displays`, what its pointers name cannot be counted, and one note
says so. The first version counted tables and images written by
hand as well, and review found correct papers failed by every way of writing one it missed.

The main text's tables and figures are also held to the order ICMJE asks for: each cited at
least once, and numbered in the order they are first cited ("Number tables consecutively in
the order of their first citation in the text", icmje.org, Preparing for Submission, read
2026-10-14). The supplement has no such rule there, and none is applied to it.

Each finding fails from the internal-review stage, Basile's choice on 2026-10-14: while the
draft is written its tables move and are numbered again, and a failure then is noise.

A pointer the build numbers, `{{ref.table.<key>}}` or `{{num.table.<key>}}` (`crossref.py`),
is read here as what it prints, so it is cited where it stands and in its order like a typed
one, and never points at nothing. What can go wrong with one is said instead: a key nothing
places (`unresolved-binding`), a number the count cannot give (`ref-number-unknown`), and
words around it that point at another kind or the other document ("Figures
{{num.table.a}}", `pointer-word-mismatch`).
"""

from __future__ import annotations

import bisect
import functools
import re
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.crossref import NUM, NUMBER, Display, Numbers, Refused, project_forms
from manuscript_guard.findings import INFO, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.text.blocks import find_headings, scannable
from manuscript_guard.text.masking import without_front_matter
from manuscript_guard.text.placeholders import Placeholder, parse

GATE = "G2"
TABLE = "table"
FIGURE = "figure"

_GAP = r"[^\S\n]*(?:\n[^\S\n]*)?"
#: What joins the numbers of one pointer: "Tables 1 and 2", "Tables 1, 3", "Figures 2-4",
#: and the serial comma, "Tables 1, 2, and 3".
#: A word or a comma joins only after a plural: "Table 2 and 3 patients" is one pointer.
_DASHES = "-\N{EN DASH}\N{EM DASH}"
_JOIN = r"[^\S\n]*(?:,[^\S\n]*(?:and|&)|,|and|&|to|[" + _DASHES + r"])[^\S\n]*"
#: The words that put a table or a figure in the supplement, whatever a journal calls it:
#: "Supplementary", "Supplemental", "Extended Data", "Appendix", "Online", and JAMA's
#: "eTable" and "eFigure".
_ELSEWHERE = (
    r"(?:supplementary|supplemental|suppl\.|extended" + _GAP + r"data|appendix|online"
    r"(?:" + _GAP + r"supplementary)?)"
)
_POINTER = re.compile(
    r"(?<![\w.])(?P<supp>" + _ELSEWHERE + _GAP + r")?(?P<e>e)?"
    r"(?P<kind>tables?|figures?|figs?\.?)" + _GAP
    + r"(?P<s0>S)?(?P<n0>\d+)[A-Za-z]?\b"
    + r"(?P<rest>(?:" + _JOIN + r"S?\d+[A-Za-z]?\b)*)"
    + r"(?P<after>" + _GAP + r"(?:in|of)" + _GAP + r"the" + _GAP + r"(?:online" + _GAP
    + r")?(?:supplement|supplementary|appendix)\b)?",
    re.IGNORECASE,
)
_REST = re.compile(r"(?P<join>" + _JOIN + r")(?P<s>S)?(?P<n>\d+)[A-Za-z]?\b", re.IGNORECASE)
_PLURAL = re.compile(r"(?:tables|figures|figs\.?)$", re.IGNORECASE)
#: What may stand before a caption's pointer on its line: nothing, or the marks of bold.
_CAPTION = re.compile(r"[^\S\n]*(?:\*\*|__)?")
#: What may stand before a pointer that opens its line as a caption or a heading does.
_OPENING = re.compile(r"[^\S\n]*(?:#{1,6}[^\S\n]+)?(?:\*\*|__)?")
_PLACED = re.compile(r"\{\{\s*(?P<kind>table|figure)\.(?P<key>[A-Za-z0-9_.]+)\s*\}\}")
#: What says a document places a table by hand, in any of the forms pandoc reads: a pipe
#: table's rule, a grid table's border, a simple table's dashes, a multiline table's rule, a
#: caption line, raw HTML. Read wrongly, one only leaves the tables unchecked.
_BY_HAND = {
    TABLE: re.compile(
        r"^[^\S\n]*\|?[^\S\n]*:?-+:?[^\S\n]*(?:\|[^\S\n]*:?-+:?[^\S\n]*)+\|?[^\S\n]*$"
        r"|^[^\S\n]*\+[-=:+]+\+[^\S\n]*$"
        r"|^[^\S\n]*-{2,}(?:[^\S\n]+-{2,})+[^\S\n]*$"
        r"|^[^\S\n]*-{10,}[^\S\n]*$"
        r"|^[^\S\n]*Table:"
        r"|<table\b",
        re.MULTILINE | re.IGNORECASE,
    ),
    FIGURE: re.compile(r"!\[[^\]\n]*\]\(|<img\b|<figure\b|\\includegraphics\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class Pointer:
    kind: str
    supplementary: bool
    number: int
    path: Path
    line: int
    shown: str
    #: In a heading or a caption: a pointer, and no citation.
    cites: bool
    #: The ref or num binding that printed the number, where one did.
    binding: Placeholder | None = None
    #: The pointer opens its line, after a heading's hashes or the marks of bold at most.
    opens: bool = False


def _kind(word: str) -> str:
    return TABLE if word.lower().startswith("table") else FIGURE


def _numbers(found: re.Match) -> list[tuple[bool, int, int | None]]:
    """Each number one pointer names, a range read as every number in it, with where its
    digits start in the text read, or None for one a range names without writing it. An `S`
    before the first number of a range holds for the rest: "Tables S1-3" is S1, S2 and S3."""
    out: list[tuple[bool, int, int | None]] = [
        (bool(found["s0"]), int(found["n0"]), found.start("n0"))
    ]
    plural = bool(_PLURAL.match(found["kind"]))
    ended = False
    rest = found.start("rest")
    for part in _REST.finditer(found["rest"]):
        number, joined = int(part["n"]), part["join"].strip().lower().lstrip(", ") or ","
        ranged = joined in ("to", *_DASHES)
        # After "and" the list has ended: "In Tables 1 and 2, 30 patients" counts 30.
        if (not plural and joined != "-" and joined not in _DASHES) or (ended and joined == ","):
            break
        ended = ended or joined in ("and", "&")
        start, s = out[-1][1], bool(part["s"]) or (ranged and out[-1][0])
        if ranged and start < number <= start + 50:
            out.extend((s, between, None) for between in range(start + 1, number))
        out.append((s, number, rest + part.start("n")))
    return out


@dataclass(frozen=True)
class _Printed:
    """A file's text as G2 reads it, each ref and num binding put in as the build prints it.

    `spans` holds, for each binding put in, where its print starts and ends in `text`, where
    the binding started and ended in the file, and the binding, in order: lines are counted
    in the file, so that a finding names the line the author wrote.
    """

    text: str
    spans: tuple[tuple[int, int, int, int, Placeholder], ...]

    @functools.cached_property
    def _starts(self) -> list[int]:
        return [span[0] for span in self.spans]

    def _at(self, at: int) -> int:
        return bisect.bisect_right(self._starts, at) - 1

    def origin(self, at: int) -> int:
        """Where an offset of `text` stood in the file."""
        index = self._at(at)
        if index < 0:
            return at
        start, end, was, was_end, _binding = self.spans[index]
        return was if at < end else at + was_end - end

    def binding_at(self, at: int | None) -> Placeholder | None:
        index = -1 if at is None else self._at(at)
        if index < 0 or at is None or at >= self.spans[index][1]:
            return None
        return self.spans[index][4]


def _printed(text: str, shown: str, numbers: Numbers | None) -> _Printed:
    """`shown` with every ref and num binding that prints a number put in as that number.
    One `shown` does not show, in code, a comment or the front matter, stays out."""
    if numbers is None:
        return _Printed(shown, ())
    pieces: list[str] = []
    spans: list[tuple[int, int, int, int, Placeholder]] = []
    cursor = length = 0
    for binding in parse(text)[0]:
        if not binding.is_ref or shown[binding.start : binding.end] != binding.raw:
            continue
        printed = numbers.printed(binding)
        if printed is None:
            continue
        pieces.append(shown[cursor : binding.start])
        length += binding.start - cursor
        spans.append((length, length + len(printed), binding.start, binding.end, binding))
        pieces.append(printed)
        length += len(printed)
        cursor = binding.end
    pieces.append(shown[cursor:])
    return _Printed("".join(pieces), tuple(spans))


def pointers_in(text: str, path: Path, numbers: Numbers | None = None) -> list[Pointer]:
    """Every table and figure a file points at, in the order it does: typed, and, given the
    document's `numbers`, printed by a ref or num binding."""
    read = _printed(text, _scanned(text), numbers)
    shown = read.text
    starts = [0, *(found.end() for found in re.finditer("\n", text))]
    heads = {bisect.bisect_right(starts, heading.start) for heading in find_headings(text)}
    found = []
    for match in _POINTER.finditer(shown):
        line = bisect.bisect_right(starts, read.origin(match.start()))
        caption = _is_caption(shown, match)
        elsewhere = bool(match["supp"] or match["e"] or match["after"])
        opening = shown[shown.rfind("\n", 0, match.start()) + 1 : match.start()]
        opens = _OPENING.fullmatch(opening) is not None
        for s, number, at in _numbers(match):
            found.append(
                Pointer(
                    kind=_kind(match["kind"]),
                    supplementary=elsewhere or s,
                    number=number,
                    path=path,
                    line=line,
                    shown=" ".join(match.group().split()),
                    cites=line not in heads and not caption,
                    binding=read.binding_at(at),
                    opens=opens,
                )
            )
    return found


def _is_caption(shown: str, match: re.Match) -> bool:
    """A pointer that opens its paragraph and is followed by a stop or a colon is a caption a
    writer typed above the table, not a citation of it. One that opens a line in the middle
    of a wrapped paragraph ends a sentence ("shown in\nTable 1.")."""
    if shown[match.end() : match.end() + 1] not in (".", ":"):
        return False
    start = shown.rfind("\n", 0, match.start()) + 1
    if not _CAPTION.fullmatch(shown[start : match.start()]):
        return False
    if start == 0:
        return True
    above = shown.rfind("\n", 0, start - 1) + 1
    return not shown[above : start - 1].strip()


def without_front_matter_kept(text: str) -> str:
    """The text with its front matter blanked to spaces, so that offsets and lines stay."""
    body = without_front_matter(text)
    head = len(text) - len(body)
    return re.sub(r"[^\n]", " ", text[:head]) + body


@functools.lru_cache(maxsize=4)
def _scanned(text: str) -> str:
    """The text as G2 reads a file's pointers: its front matter, fenced listings and comments
    blanked. Kept for the last few files, since each is read for what it places, for its
    pointers and for its ref and num bindings."""
    return scannable(without_front_matter_kept(text))


@dataclass(frozen=True)
class Placed:
    """What a file places by binding, `(kind, key)` in order, and which kinds it places by
    hand too."""

    bound: tuple[tuple[str, str], ...]
    by_hand: frozenset[str]


def placed_in(text: str) -> Placed:
    shown = _scanned(text)
    return Placed(
        tuple((m["kind"], m["key"]) for m in _PLACED.finditer(shown)),
        frozenset(kind for kind, form in _BY_HAND.items() if form.search(shown)),
    )


#: The paper.yaml keys that declare the displays sent as files, by document and kind.
AS_FILES = {
    (False, FIGURE): "figures_as_files",
    (False, TABLE): "tables_as_files",
    (True, FIGURE): "supplementary_figures_as_files",
    (True, TABLE): "supplementary_tables_as_files",
}


def _count(project: Project) -> tuple[Numbers, list[tuple[Path, str]]]:
    """What each document places, numbered in the order its files print, and each file's
    text in that order: the main text's, then the supplement's."""
    root = project.path("manuscript")
    declared = project.setting("displays") or {}
    sources = source_files(root)
    documents = {
        supplementary: printed_order(
            [path for path in sources if is_supplementary(root, path) == supplementary],
            supplementary=supplementary,
        )
        for supplementary in (False, True)
    }
    files: list[tuple[Path, str]] = []
    placed: dict[tuple[str, str], list[Display]] = {}
    bound: dict[tuple[bool, str], int] = {}
    by_hand: set[tuple[bool, str]] = set()
    for supplementary, paths in documents.items():
        for path in paths:
            text = read_text(path)
            files.append((path, text))
            found = placed_in(text)
            for kind, key in found.bound:
                number = bound[supplementary, kind] = bound.get((supplementary, kind), 0) + 1
                placed.setdefault((kind, key), []).append(
                    Display(kind, key, supplementary, number)
                )
            by_hand |= {(supplementary, kind) for kind in found.by_hand}
    numbers = Numbers(
        placed={where: tuple(found) for where, found in placed.items()},
        bound=bound,
        by_hand=frozenset(by_hand),
        as_files={key: int(declared.get(name) or 0) for key, name in AS_FILES.items()},
        forms=project_forms(project),
    )
    return numbers, files


def display_numbers(project: Project) -> Numbers:
    """The number each table and figure placed by its binding has in its document, which
    `{{ref.table.<key>}}` prints (`crossref.py`), and the tables a caption is typed beside,
    whose emitted caption the build leaves unnumbered (`caption_label`)."""
    numbers, files = _count(project)
    return replace(numbers, captioned=captioned(files, numbers))


def check_pointers(project: Project, results=None) -> Report:
    """G2's pointers, as the module says. Given the `results`, an emitted table's caption that
    opens with a pointer is held to the table's number too."""
    root = project.path("manuscript")
    numbers, files = _count(project)
    as_files = numbers.as_files
    bound = numbers.bound
    by_hand = set(numbers.by_hand)
    report = _unread_forms(numbers, _profile_path(project))
    pointers: list[Pointer] = []
    for path, text in files:
        found = pointers_in(text, path, numbers)
        report = report.merge(_bound(text, path, numbers, found))
        report = report.merge(_captions(text, path, numbers, found, results))
        # A binding read with words that point elsewhere is said above, and cites nothing.
        pointers += [pointer for pointer in found if _reads_as_named(pointer, numbers)]

    # What each document carries of each kind: what it places by binding, and what paper.yaml
    # says goes to the journal as files of their own.
    total = {key: bound.get(key, 0) + as_files[key] for key in AS_FILES}

    def counted(key: tuple[bool, str]) -> bool:
        return total[key] > 0 and key not in by_hand

    for pointer in pointers:
        key = (pointer.supplementary, pointer.kind)
        count = total[key]
        if not counted(key) or 1 <= pointer.number <= count:
            continue
        where = "the supplement" if pointer.supplementary else "the main text"
        plural = "" if bound.get(key, 0) == 1 else "s"
        files_too = f" and {as_files[key]} sent as files" if as_files[key] else ""
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pointer-to-nothing",
                message=f"{pointer.shown!r} points at {pointer.kind} "
                f"{'S' if pointer.supplementary else ''}{pointer.number}, and {where} "
                f"places {bound.get(key, 0)} {pointer.kind}{plural}{files_too}",
                path=pointer.path,
                line=pointer.line,
                hint="number tables and figures as the document places them, or name one by "
                "its key, `{{ref.table.<key>}}`, and the build prints its number; a table or "
                "figure moved to the supplement is Table S1 or Figure S1 there; one sent to "
                f"the journal as a file of its own is declared in paper.yaml, `displays: "
                f"{{{AS_FILES[key]}: 1}}`",
            )
        )
    report = report.merge(_unchecked(pointers, total, by_hand, root))
    report = report.merge(_in_order(pointers, total, by_hand, root))
    return report.with_counts(
        pointers=len(pointers),
        pointers_checked=sum(counted((p.supplementary, p.kind)) for p in pointers),
        tables_placed=bound.get((False, TABLE), 0),
        figures_placed=bound.get((False, FIGURE), 0),
    )


def _reads_as_named(pointer: Pointer, numbers: Numbers) -> bool:
    """Whether a pointer points where its binding does: a typed one always does."""
    if pointer.binding is None:
        return True
    display = numbers.display(pointer.binding)
    return not isinstance(display, Refused) and (display.kind, display.supplementary) == (
        pointer.kind,
        pointer.supplementary,
    )


def _bound(text: str, path: Path, numbers: Numbers, found: list[Pointer]) -> Report:
    """What is wrong with each ref and num binding of a file the build prints: a key nothing
    places, a number the count cannot give, and words around it that point elsewhere."""
    report = Report()
    shown = _scanned(text)
    read: dict[int, list[Pointer]] = {}
    for pointer in found:
        if pointer.binding is not None:
            read.setdefault(pointer.binding.start, []).append(pointer)
    for binding in parse(text)[0]:
        if not binding.is_ref or shown[binding.start : binding.end] != binding.raw:
            continue
        display = numbers.display(binding)
        if isinstance(display, Refused):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code=display.code,
                    message=display.why,
                    path=path,
                    line=binding.line,
                    col=binding.col,
                    hint=display.hint,
                )
            )
            continue
        readings = read.get(binding.start, [])
        named = (display.kind, display.supplementary)
        wrong = [p for p in readings if (p.kind, p.supplementary) != named]
        if readings and not wrong:
            continue
        printed = numbers.printed(binding)
        whole = numbers.forms[display.supplementary, display.kind].replace(
            NUMBER, str(display.number)
        )
        said = (
            f"read with the words around it as {wrong[0].shown!r}, a {wrong[0].kind} of "
            f"{_where(wrong[0].supplementary)}"
            if wrong
            else "with no word before it that points at a table or a figure"
        )
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pointer-word-mismatch",
                message=f"{binding.raw} prints {printed!r}, {said}; {display.binding} is "
                f"{whole} in {_where(display.supplementary)}",
                path=path,
                line=binding.line,
                col=binding.col,
                hint=f"write {{{{ref.{display.kind}.{display.key}}}}}, which prints {whole!r} "
                f"whole, or put {{{{{NUM}.{display.kind}.{display.key}}}}} after the words "
                f"that name a {display.kind} of {_where(display.supplementary)}",
            )
        )
    return report


def _blocks(shown: str) -> list[tuple[int, int]]:
    """Each run of lines that are not blank, as its first and last line, counted from 1."""
    blocks: list[tuple[int, int]] = []
    first = None
    lines = shown.split("\n")
    for number, line in enumerate(lines, 1):
        if line.strip() and first is None:
            first = number
        elif not line.strip() and first is not None:
            blocks.append((first, number - 1))
            first = None
    if first is not None:
        blocks.append((first, len(lines)))
    return blocks


#: What may stand before the number an emitted caption opens with: spaces, and the marks of
#: bold or italics.
_CAPTION_MARKS = re.compile(r"[\s*_]*")


def opening_pointer(caption: str) -> re.Match | None:
    """The pointer an emitted caption opens with, however it is set off: "Table 2." in
    "Table 2. Baseline characteristics", and "Table 2 Baseline characteristics", "Table 2 -
    Baseline" and "**Table 2.** Baseline" alike (round 1 of #381: only a stop or a colon was
    read, and the others got a second number). The build prints such a caption as it is, and
    numbers any other."""
    found = _POINTER.match(caption, _CAPTION_MARKS.match(caption).end())
    return found if found is not None and not found["rest"] else None


#: Where a caption stands beside each kind, in blocks from its binding: a figure's under it, a
#: table's under it or above it.
_BESIDE = {FIGURE: (1,), TABLE: (1, -1)}
#: A caption between two tables is the caption of either: it has to name one of them.
_NAMES_ONE = any


def caption_label(numbers: Numbers, key: str, caption: str) -> str | None:
    """What the build prints before the caption of the table placed by `{{table.<key>}}`:
    its pointer, "Table 2" or "eTable 1" (Basile's choice of 2026-10-20). None where the count
    cannot number the table; where the emitted caption opens with a pointer already, which
    is printed as it is and held to the table's number by G2; and where a caption is typed
    beside the table, as a paragraph or a heading (round 1 of #381: the number was printed
    twice, the typed caption's and the build's)."""
    displays = numbers.placed.get((TABLE, key), ())
    if len(displays) != 1 or numbers.uncounted(displays[0].supplementary, TABLE):
        return None
    if caption and opening_pointer(caption) is not None:
        return None
    if key in numbers.captioned:
        return None
    form = numbers.forms[displays[0].supplementary, TABLE]
    return form.replace(NUMBER, str(displays[0].number))


@dataclass(frozen=True)
class _Beside:
    """A caption typed beside one or two displays of its kind, and those displays."""

    caption: Pointer
    displays: tuple[Display, ...]


def _beside(text: str, numbers: Numbers, found: list[Pointer]) -> list[_Beside]:
    """Each caption of a file that stands beside a display placed by its binding: a pointer
    that opens a block and cites nothing there (a caption, or a heading), in the block
    directly under a figure or a table, or directly above a table, of its own kind. A block
    between two tables stands beside both, and is the caption of the one it names (round 1 of
    #381: it was held to each of them)."""
    shown = _scanned(text)
    blocks = _blocks(shown)
    starts = {first: index for index, (first, _last) in enumerate(blocks)}
    displays: dict[int, Display] = {}
    for placed in _PLACED.finditer(shown):
        kind, key = placed["kind"], placed["key"]
        found_here = numbers.placed.get((kind, key), ())
        if len(found_here) != 1 or numbers.uncounted(found_here[0].supplementary, kind):
            continue
        line = shown.count("\n", 0, placed.start()) + 1
        index = next(i for i, (a, b) in enumerate(blocks) if a <= line <= b)
        displays[index] = found_here[0]
    out: list[_Beside] = []
    seen: set[int] = set()
    for pointer in found:
        index = starts.get(pointer.line)
        if index is None or index in seen or not pointer.opens or pointer.cites:
            continue
        seen.add(index)
        near = tuple(
            displays[index - step]
            for step in _BESIDE[pointer.kind]
            if index - step in displays and displays[index - step].kind == pointer.kind
        )
        if near:
            out.append(_Beside(pointer, near))
    return out


def captioned(files: list[tuple[Path, str]], numbers: Numbers) -> frozenset[str]:
    """The keys of the tables a caption is typed beside, which the build numbers no caption
    of: the typed one prints the number."""
    return frozenset(
        display.key
        for path, text in files
        for beside in _beside(text, numbers, pointers_in(text, path, numbers))
        for display in beside.displays
        if display.kind == TABLE
    )


def _captions(
    text: str, path: Path, numbers: Numbers, found: list[Pointer], results
) -> Report:
    """A caption that names another display than the one it stands beside (`_beside`): one it
    names is beside it, or it is said. A ref in a caption is read as the number it prints, so
    `{{ref.figure.flow}}.` under the forest plot is said too. Given the results, an emitted
    table's caption that opens with a pointer is held to the table's number as well."""
    report = Report()
    for beside in _beside(text, numbers, found):
        caption = beside.caption
        named = (caption.supplementary, caption.number)
        if _NAMES_ONE((d.supplementary, d.number) == named for d in beside.displays):
            continue
        display = beside.displays[0]
        form = numbers.forms[display.supplementary, display.kind]
        report = report.with_findings(
            _caption_finding(
                f"{caption.shown!r} captions {display.binding}",
                form.replace(NUMBER, str(display.number)), display, path, caption.line,
                f"write {{{{ref.{display.kind}.{display.key}}}}} for the number",
            )  # fmt: skip
        )
    if results is None:
        return report
    shown = _scanned(text)
    for placed in _PLACED.finditer(shown):
        key = placed["key"]
        emitted = results.tables.get(key) if placed["kind"] == TABLE else None
        typed = opening_pointer(emitted.caption) if emitted and emitted.caption else None
        displays = numbers.placed.get((TABLE, key), ())
        if typed is None or len(displays) != 1:
            continue
        display = displays[0]
        if numbers.uncounted(display.supplementary, TABLE):
            continue
        elsewhere = bool(typed["supp"] or typed["e"] or typed["after"] or typed["s0"])
        named = (_kind(typed["kind"]), elsewhere, int(typed["n0"]))
        if named == (TABLE, display.supplementary, display.number):
            continue
        form = numbers.forms[display.supplementary, TABLE]
        report = report.with_findings(
            _caption_finding(
                f"the caption emitted for {display.binding} opens with "
                f"{' '.join(typed.group().split())!r}",
                form.replace(NUMBER, str(display.number)), display, path,
                shown.count("\n", 0, placed.start()) + 1,
                "emit the caption without its number: the build prints the number the table "
                "has before it",
            )  # fmt: skip
        )
    return report


def _caption_finding(
    said: str, named: str, display: Display, path: Path, line: int, hint: str
) -> Finding:
    return Finding(
        gate=GATE,
        code="caption-names-another",
        message=f"{said}, which is {named} in {_where(display.supplementary)}",
        path=path,
        line=line,
        hint=hint,
    )


def _where(supplementary: bool) -> str:
    return "the supplement" if supplementary else "the main text"


def _profile_path(project: Project) -> Path | None:
    from manuscript_guard.gates.journal import profile_path

    slug = project.target_journal
    return profile_path(project, slug) if slug else None


def _unread_forms(numbers: Numbers, profile: Path | None) -> Report:
    """A form of the journal profile's `pointers:` that G2 does not read back, whole, as a
    pointer to that kind of that document. A ref printed in it would be a pointer G2 could
    not hold to anything, or would hold to the other document."""
    report = Report()
    for (supplementary, kind), form in numbers.forms.items():
        written = form.replace(NUMBER, "1")
        read = next(
            (m for m in _POINTER.finditer(f"As {written} shows") if m.group() == written), None
        )
        if (
            read is not None
            and not read["rest"]
            and _kind(read["kind"]) == kind
            and bool(read["supp"] or read["e"] or read["after"] or read["s0"]) == supplementary
        ):
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pointer-form-unread",
                message=f"the journal profile writes a pointer to a {kind} of "
                f"{_where(supplementary)} {form!r}, which G2 does not read as one",
                path=profile or Path("profiles") / "journals",
                hint="a form is the word and {n}, as the journal writes it: \"Table {n}\", "
                "\"Fig. {n}\", \"Table S{n}\", \"Supplementary Table {n}\", \"eTable {n}\", "
                "\"Extended Data Fig. {n}\", \"Table {n} in the Supplement\"",
            )
        )
    return report


def _unchecked(
    pointers: list[Pointer],
    total: dict[tuple[bool, str], int],
    by_hand: set[tuple[bool, str]],
    root: Path,
) -> Report:
    """One note for each document and kind whose pointers could not be checked, and why."""
    report = Report()
    for supplementary in (False, True):
        for kind in (TABLE, FIGURE):
            key = (supplementary, kind)
            mine = [p for p in pointers if (p.supplementary, p.kind) == key]
            if not mine or (total[key] and key not in by_hand):
                continue
            where = "the supplement" if supplementary else "the main text"
            why = (
                f"{where} places one or more by hand"
                if key in by_hand
                else f"{where} places none by {{{{{kind}.<key>}}}} and declares none sent as files"
            )
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="pointers-unchecked",
                    severity=INFO,
                    message=f"{len(mine)} pointer(s) to {where}'s {kind}s were not checked: "
                    f"{why}, so its {kind}s cannot be counted",
                    path=root,
                    hint=f"place every {kind} by {{{{{kind}.<key>}}}}, and declare those sent "
                    f"as files of their own in paper.yaml (`displays: "
                    f"{{{AS_FILES[key]}: <how many>}}`), to have its pointers checked",
                )
            )
    return report


def _in_order(
    pointers: list[Pointer],
    total: dict[tuple[bool, str], int],
    by_hand: set[tuple[bool, str]],
    root: Path,
) -> Report:
    """Each of the main text's tables and figures cited, and first cited in order: those
    sent as files are numbered with the others, so the numbers run from 1 to all of them."""
    report = Report()
    for kind in (TABLE, FIGURE):
        count = total[(False, kind)]
        if not count or (False, kind) in by_hand:
            continue
        cited = [
            p
            for p in pointers
            if p.kind == kind and not p.supplementary and p.cites and 1 <= p.number <= count
        ]
        first: dict[int, Pointer] = {}
        for pointer in cited:
            first.setdefault(pointer.number, pointer)
        expected = 1
        for number, pointer in first.items():
            if number != expected:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="cited-out-of-order",
                        message=f"{kind.capitalize()} {number} is first cited before "
                        f"{kind} {expected}",
                        path=pointer.path,
                        line=pointer.line,
                        hint=f"ICMJE: number {kind}s in the order of their first citation in "
                        "the text, so that the first one cited is 1",
                    )
                )
                break
            expected += 1
        for number in range(1, count + 1):
            if number not in first:
                report = report.with_findings(
                    Finding(
                        gate=GATE,
                        code="display-not-cited",
                        message=f"{kind.capitalize()} {number} is placed in the main text, or "
                        "sent with it as a file, and cited nowhere",
                        path=root,
                        hint=f"ICMJE: each {kind} is cited in the text",
                    )
                )
    return report


__all__ = [
    "Placed",
    "caption_label",
    "check_pointers",
    "display_numbers",
    "opening_pointer",
    "placed_in",
    "pointers_in",
]
