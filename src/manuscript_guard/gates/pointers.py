"""A pointer to a table or a figure names one the document carries, and in order.

"As Table 4 shows" is a number like any other, and G2 lets it through as a cross-reference:
the rule reads the word and the digits after it. So "Table 4000" passed, and so did a
pointer to a table the document does not have. The example's own text called its first
table "Table 2" and its second "Table 3", after a third had moved to the supplement. LaTeX
refuses a `\\ref` to a label nobody defined; this is the same refusal for a pointer typed as
text.

What the document carries is counted where the build prints it: each table placed by
`{{table.<key>}}` or written by hand as a pipe table, and each figure placed by
`{{figure.<key>}}` or as an image, in the order the files print, the main text and the
supplement apart. Table 1 is the first table the main text places; Table S1, or
Supplementary Table 1, the first the supplement places.

The main text's tables and figures are also held to the order ICMJE asks for: each cited at
least once, and numbered in the order they are first cited ("Number tables consecutively in
the order of their first citation in the text", icmje.org, Preparing for Submission, read
2026-10-14). The supplement has no such rule there, and none is applied to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.text.blocks import find_headings, scannable
from manuscript_guard.text.masking import without_front_matter

GATE = "G2"
TABLE = "table"
FIGURE = "figure"

_GAP = r"[^\S\n]*(?:\n[^\S\n]*)?"
#: What joins the numbers of one pointer: "Tables 1 and 2", "Tables 1, 3", "Figures 2-4".
#: A word or a comma joins only after a plural: "Table 2 and 3 patients" is one pointer.
_DASHES = "-\N{EN DASH}\N{EM DASH}"
_JOIN = r"[^\S\n]*(?:,|and|&|to|[" + _DASHES + r"])[^\S\n]*"
_POINTER = re.compile(
    r"(?<![\w.])(?P<supp>(?:supplementary|suppl\.)" + _GAP + r")?"
    r"(?P<kind>tables?|figures?|figs?\.?)" + _GAP
    + r"(?P<s0>S)?(?P<n0>\d+)[A-Za-z]?\b"
    + r"(?P<rest>(?:" + _JOIN + r"S?\d+[A-Za-z]?\b)*)",
    re.IGNORECASE,
)
_REST = re.compile(r"(?P<join>" + _JOIN + r")(?P<s>S)?(?P<n>\d+)[A-Za-z]?\b", re.IGNORECASE)
_PLURAL = re.compile(r"(?:tables|figures|figs\.?)$", re.IGNORECASE)
_PLACED = re.compile(r"\{\{\s*(?P<kind>table|figure)\.[A-Za-z0-9_.]+\s*\}\}")
_IMAGE = re.compile(r"^[^\S\n]*!\[[^\]\n]*\]\([^)\n]*\)", re.MULTILINE)
#: A pipe table's rule under its header row: the line that makes the rows above a table.
_TABLE_RULE = re.compile(
    r"^[^\S\n]*\|?[^\S\n]*:?-{3,}:?[^\S\n]*(?:\|[^\S\n]*:?-{3,}:?[^\S\n]*)+\|?[^\S\n]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Pointer:
    kind: str
    supplementary: bool
    number: int
    path: Path
    line: int
    shown: str
    in_heading: bool


def _kind(word: str) -> str:
    return TABLE if word.lower().startswith("table") else FIGURE


def _numbers(found: re.Match) -> list[tuple[bool, int]]:
    """Each number one pointer names, a range read as every number in it."""
    out = [(bool(found["s0"]), int(found["n0"]))]
    plural = bool(_PLURAL.match(found["kind"]))
    for part in _REST.finditer(found["rest"]):
        number, joined = int(part["n"]), part["join"].strip().lower()
        ranged = joined in ("to", *_DASHES)
        if not plural and joined != "-" and joined not in _DASHES:
            break
        start = out[-1][1]
        if ranged and start < number <= start + 50:
            out.extend((bool(part["s"]), between) for between in range(start + 1, number))
        out.append((bool(part["s"]), number))
    return out


def pointers_in(text: str, path: Path) -> list[Pointer]:
    """Every table and figure a file points at, in the order it does."""
    shown = scannable(without_front_matter_kept(text))
    heads = {shown.count("\n", 0, heading.start) + 1 for heading in find_headings(text)}
    found = []
    for match in _POINTER.finditer(shown):
        line = shown.count("\n", 0, match.start()) + 1
        for s, number in _numbers(match):
            found.append(
                Pointer(
                    kind=_kind(match["kind"]),
                    supplementary=bool(match["supp"]) or s,
                    number=number,
                    path=path,
                    line=line,
                    shown=" ".join(match.group().split()),
                    in_heading=line in heads,
                )
            )
    return found


def without_front_matter_kept(text: str) -> str:
    """The text with its front matter blanked to spaces, so that offsets and lines stay."""
    body = without_front_matter(text)
    head = len(text) - len(body)
    return re.sub(r"[^\n]", " ", text[:head]) + body


def placed_in(text: str) -> list[str]:
    """What a file places, table or figure, in the order it does."""
    shown = scannable(without_front_matter_kept(text))
    places = [(m.start(), m["kind"]) for m in _PLACED.finditer(shown)]
    places += [(m.start(), FIGURE) for m in _IMAGE.finditer(shown)]
    places += [(m.start(), TABLE) for m in _TABLE_RULE.finditer(shown)]
    return [kind for _start, kind in sorted(places)]


def check_pointers(project: Project) -> Report:
    root = project.path("manuscript")
    sources = source_files(root)
    main = [path for path in sources if not is_supplementary(root, path)]
    supplement = [path for path in sources if is_supplementary(root, path)]
    documents = {
        False: printed_order(main, supplementary=False),
        True: printed_order(supplement, supplementary=True),
    }
    carried: dict[tuple[bool, str], int] = {}
    pointers: list[Pointer] = []
    for supplementary, paths in documents.items():
        for path in paths:
            text = read_text(path)
            for kind in placed_in(text):
                carried[supplementary, kind] = carried.get((supplementary, kind), 0) + 1
            pointers += pointers_in(text, path)

    report = Report()
    for pointer in pointers:
        count = carried.get((pointer.supplementary, pointer.kind), 0)
        if 1 <= pointer.number <= count:
            continue
        where = "the supplement" if pointer.supplementary else "the main text"
        plural = "" if count == 1 else "s"
        has = f"{count} {pointer.kind}{plural}" if count else f"no {pointer.kind}"
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pointer-to-nothing",
                severity=WARN,
                message=f"{pointer.shown!r} points at {pointer.kind} "
                f"{'S' if pointer.supplementary else ''}{pointer.number}, and {where} "
                f"places {has}",
                path=pointer.path,
                line=pointer.line,
                hint="number tables and figures as the document places them; a table or figure "
                "moved to the supplement is Table S1 or Figure S1 there",
            )
        )
    report = report.merge(_in_order(pointers, carried, root))
    return report.with_counts(
        pointers=len(pointers),
        tables_placed=carried.get((False, TABLE), 0),
        figures_placed=carried.get((False, FIGURE), 0),
    )


def _in_order(
    pointers: list[Pointer], carried: dict[tuple[bool, str], int], root: Path
) -> Report:
    """Each of the main text's tables and figures cited, and first cited in order."""
    report = Report()
    for kind in (TABLE, FIGURE):
        count = carried.get((False, kind), 0)
        cited = [
            p
            for p in pointers
            if p.kind == kind and not p.supplementary and not p.in_heading
            and 1 <= p.number <= count
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
                        severity=WARN,
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
                        severity=WARN,
                        message=f"{kind.capitalize()} {number} is placed in the main text and "
                        "cited nowhere",
                        path=root,
                        hint=f"ICMJE: each {kind} is cited in the text",
                    )
                )
    return report


__all__ = ["check_pointers", "placed_in", "pointers_in"]
