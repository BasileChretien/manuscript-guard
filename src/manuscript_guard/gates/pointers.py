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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.text.blocks import find_headings, scannable
from manuscript_guard.text.masking import without_front_matter

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
_PLACED = re.compile(r"\{\{\s*(?P<kind>table|figure)\.[A-Za-z0-9_.]+\s*\}\}")
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


def _kind(word: str) -> str:
    return TABLE if word.lower().startswith("table") else FIGURE


def _numbers(found: re.Match) -> list[tuple[bool, int]]:
    """Each number one pointer names, a range read as every number in it. An `S` before
    the first number of a range holds for the rest: "Tables S1-3" is S1, S2 and S3."""
    out = [(bool(found["s0"]), int(found["n0"]))]
    plural = bool(_PLURAL.match(found["kind"]))
    ended = False
    for part in _REST.finditer(found["rest"]):
        number, joined = int(part["n"]), part["join"].strip().lower().lstrip(", ") or ","
        ranged = joined in ("to", *_DASHES)
        # After "and" the list has ended: "In Tables 1 and 2, 30 patients" counts 30.
        if (not plural and joined != "-" and joined not in _DASHES) or (ended and joined == ","):
            break
        ended = ended or joined in ("and", "&")
        start, s = out[-1][1], bool(part["s"]) or (ranged and out[-1][0])
        if ranged and start < number <= start + 50:
            out.extend((s, between) for between in range(start + 1, number))
        out.append((s, number))
    return out


def pointers_in(text: str, path: Path) -> list[Pointer]:
    """Every table and figure a file points at, in the order it does."""
    shown = scannable(without_front_matter_kept(text))
    heads = {shown.count("\n", 0, heading.start) + 1 for heading in find_headings(text)}
    found = []
    for match in _POINTER.finditer(shown):
        line = shown.count("\n", 0, match.start()) + 1
        caption = _is_caption(shown, match)
        elsewhere = bool(match["supp"] or match["e"] or match["after"])
        for s, number in _numbers(match):
            found.append(
                Pointer(
                    kind=_kind(match["kind"]),
                    supplementary=elsewhere or s,
                    number=number,
                    path=path,
                    line=line,
                    shown=" ".join(match.group().split()),
                    cites=line not in heads and not caption,
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


@dataclass(frozen=True)
class Placed:
    """What a file places by binding, in order, and which kinds it places by hand too."""

    bound: tuple[str, ...]
    by_hand: frozenset[str]


def placed_in(text: str) -> Placed:
    shown = scannable(without_front_matter_kept(text))
    return Placed(
        tuple(m["kind"] for m in _PLACED.finditer(shown)),
        frozenset(kind for kind, form in _BY_HAND.items() if form.search(shown)),
    )


#: The paper.yaml keys that declare the displays sent as files, by document and kind.
AS_FILES = {
    (False, FIGURE): "figures_as_files",
    (False, TABLE): "tables_as_files",
    (True, FIGURE): "supplementary_figures_as_files",
    (True, TABLE): "supplementary_tables_as_files",
}


def check_pointers(project: Project) -> Report:
    root = project.path("manuscript")
    declared = project.setting("displays") or {}
    as_files = {key: int(declared.get(name) or 0) for key, name in AS_FILES.items()}
    sources = source_files(root)
    main = [path for path in sources if not is_supplementary(root, path)]
    supplement = [path for path in sources if is_supplementary(root, path)]
    documents = {
        False: printed_order(main, supplementary=False),
        True: printed_order(supplement, supplementary=True),
    }
    bound: dict[tuple[bool, str], int] = {}
    by_hand: set[tuple[bool, str]] = set()
    pointers: list[Pointer] = []
    for supplementary, paths in documents.items():
        for path in paths:
            text = read_text(path)
            placed = placed_in(text)
            for kind in placed.bound:
                bound[supplementary, kind] = bound.get((supplementary, kind), 0) + 1
            by_hand |= {(supplementary, kind) for kind in placed.by_hand}
            pointers += pointers_in(text, path)

    # What each document carries of each kind: what it places by binding, and what paper.yaml
    # says goes to the journal as files of their own.
    total = {key: bound.get(key, 0) + as_files[key] for key in AS_FILES}

    def counted(key: tuple[bool, str]) -> bool:
        return total[key] > 0 and key not in by_hand

    report = Report()
    for pointer in pointers:
        key = (pointer.supplementary, pointer.kind)
        count = total[key]
        if not counted(key) or 1 <= pointer.number <= count:
            continue
        where = "the supplement" if pointer.supplementary else "the main text"
        plural = "" if bound.get(key, 0) == 1 else "s"
        files = f" and {as_files[key]} sent as files" if as_files[key] else ""
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pointer-to-nothing",
                message=f"{pointer.shown!r} points at {pointer.kind} "
                f"{'S' if pointer.supplementary else ''}{pointer.number}, and {where} "
                f"places {bound.get(key, 0)} {pointer.kind}{plural}{files}",
                path=pointer.path,
                line=pointer.line,
                hint="number tables and figures as the document places them; a table or figure "
                "moved to the supplement is Table S1 or Figure S1 there; one sent to the journal "
                f"as a file of its own is declared in paper.yaml, `displays: "
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


__all__ = ["Placed", "check_pointers", "placed_in", "pointers_in"]
