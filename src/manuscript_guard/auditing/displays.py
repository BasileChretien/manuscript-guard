"""G2's tables and figures in a paper written outside manuscript-guard: each cited, numbered
in the order of its first citation, and no pointer to one the paper does not have.

`check` counts a project's tables and figures by the bindings that place them
(`gates.pointers`), and a paper audited has none. Here a kind is counted by its legends alone
(Basile, 2026-11-27, wave B): where the legends of a kind read "Table 1" to "Table n" (or
"Figure 1" to "Figure n"), each once, the paper has n of them; any other numbering, or none,
leaves the kind uncounted, and one note says so. Nothing else is counted: G2's first version
counted the tables and pictures it read as well, and failed correct papers by every way of
writing one it missed.

- **A legend** is the first pointer of a line that opens its paragraph, after nothing but
  the marks of emphasis or the `![` of a picture, set off from its title by a stop, a colon,
  a dash no number follows or the end of the marks, as G2 tells a caption from a citation,
  by a space and a capital, as BMC and Springer set one ("Table 1 Baseline
  characteristics"), or alone on its line, the end of a picture's or a link's text and its
  target standing between. Every other pointer is a citation ("as Table 2 shows", "Figures
  1-3 show", a Word cross-reference's link opening a sentence).
- **The main text's kinds** are held to ICMJE ("Number tables consecutively in the order of
  their first citation in the text"): each cited (`display-not-cited`), the first citations
  in the order of their numbers (`cited-out-of-order`), and none to a number past the last
  legend (`pointer-to-nothing`). The codes are G2's.
- **A pointer to the supplement**, "Table S1", "Supplementary Figure 2", "eTable 3", is held
  to the supplement's legends, read in every paper the audit is given, the main text's file
  among them, and only where some are: they are then counted as the main text's are.
- **A LaTeX paper** numbers its own floats, and is held by G2's own reader of one
  (`gates.pointers_latex`), as `check` holds a LaTeX project, with the audit's notes and
  hints rather than a project's.
- **A PDF** is read where its lines were rebuilt into paragraphs (`auditing.pdf`), each
  display a block opening with its legend; where they were not, a legend cannot be told from a
  line of prose, and a note says the PDF was not checked.

Each finding warns, until its code is measured on the corpus of real papers and its severity
follows that (`auditing.measured`, Basile's choice of 2026-11-27).
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.findings import INFO, WARN, Finding

GATE = "G2"
#: What `audit` says of a kind it did not count, and of a PDF it did not read for this.
NOT_COUNTED = "displays-not-counted"
#: A legend's line, as the paper sets it: its pointer opens the line, after a Word
#: bookmark, the `![` of a picture or the `[` of a link, and the marks of emphasis, and is
#: set off from its title (see the module's text). A link's or a picture's text may end
#: there, its target after it, and the set-off then follows that. A dash sets a title off
#: where no number or link follows it, as one follows a range's ("Figures 1–3 show",
#: "[Figure 1](#_Ref1)–[Figure 3](#_Ref3) show"), and a panel's letter with a dash and a
#: letter after it opens a range too ("Figures 1A–C show") (rounds 1 and 2 of #837). Any
#: space but a line's end, Word's no-break space among them, stands where a space does.
_LEGEND = re.compile(
    r"[^\S\n]*(?:\[\]\{[^}\n]*\}[^\S\n]*)*(?:!?\[)?(?:\[\]\{[^}\n]*\}[^\S\n]*)*(?:\*\*\*|\*\*|__|\*|_)?[^\S\n]*"
    r"(?i:(?:supplementary|supplemental)[^\S\n]+|e|s)?"
    r"(?i:tables?|figures?|figs?\.?)[^\S\n]*S?\d+"
    r"(?:[A-Za-z](?![\N{EN DASH}\N{EM DASH}-][A-Za-z](?![A-Za-z])))?(?:\*\*\*|\*\*|__|\*|_)?"
    r"(?:[^\S\n]*\](?:\([^)\n]*\))?(?:\{[^}\n]*\})?)?"
    r"(?:[^\S\n]*[.:|]|[^\S\n]*[\N{EN DASH}\N{EM DASH}-](?![^\S\n]*[\d\[])|[^\S\n]+(?=[A-Z])"
    r"|[^\S\n]*$)"
)
#: A picture, as pandoc writes one: what a figure the file holds may be.
_PICTURE = re.compile(r"!\[[^\]\n]*\]\(")
#: A PDF whose lines could not be rebuilt into paragraphs.
UNREBUILT = ("its lines were not rebuilt into paragraphs, so a table's or a figure's legend "
             "cannot be told from a line of prose, and its tables and figures were not "
             "checked")  # fmt: skip


@dataclass(frozen=True)
class Displays:
    """What one paper gives the check: its findings on the main text's kinds (or a LaTeX
    paper's, all of G2's), its notes, and for the supplement, the numbers its legends give by
    kind and each pointer to the supplement with the finding it would be."""

    findings: tuple[Finding, ...] = ()
    notes: tuple[Finding, ...] = ()
    supplement: dict[str, tuple[int, ...]] = field(default_factory=dict)
    to_supplement: tuple[tuple[str, int, Finding], ...] = ()
    #: How many kinds of the main text were counted, tables and figures of each file: what
    #: says the check ran where it found nothing.
    counted: int = 0

    def mapped(self, back) -> Displays:
        """The same, each finding put back at the paper's own path and line by `back`."""
        return replace(self, findings=tuple(back(f) for f in self.findings),
                       notes=tuple(back(f) for f in self.notes),
                       to_supplement=tuple((kind, number, back(f))
                                           for kind, number, f in self.to_supplement))  # fmt: skip


def of_files(files: dict[str, str], folder: Path) -> Displays:
    """The tables and figures of a paper whose text is `files`, by their names under
    `folder`, read as Markdown (a Word paper converted, a Markdown one, a PDF's rebuilt
    lines), each file a paper of its own."""
    found: list[Finding] = []
    notes: list[Finding] = []
    supplement: dict[str, list[int]] = {}
    to_supplement: list[tuple[str, int, Finding]] = []
    counted = 0
    for name, text in files.items():
        legends, cited = _read(text, folder / name)
        # The tables and pictures the main text holds stand before the supplement's first
        # legend: those after it are the supplement's, and its legends listed alone at the
        # end stand for none (rounds 1 and 2 of #837).
        cut = min((p.line for p in legends if p.supplementary), default=0)
        held = _held("\n".join(text.split("\n")[:cut - 1]) if cut else text)
        for kind in ("table", "figure"):
            main = [p for p in legends if p.kind == kind and not p.supplementary]
            pointed = [p for p in cited if p.kind == kind and not p.supplementary]
            got, said = _counted(kind, main, pointed, folder / name, held[kind], bool(cut))
            found += got
            notes += said
            counted += bool(main) and not said
            supplement.setdefault(kind, []).extend(
                p.number for p in legends if p.kind == kind and p.supplementary)
            to_supplement += [(kind, p.number, _to_nothing(p, "the supplement", folder / name))
                              for p in cited if p.kind == kind and p.supplementary]  # fmt: skip
    return Displays(tuple(found), tuple(notes),
                    {kind: tuple(numbers) for kind, numbers in supplement.items() if numbers},
                    tuple(to_supplement), counted)  # fmt: skip


def of_latex(project) -> Displays:
    """A LaTeX paper's tables and figures, as G2 holds a LaTeX project's: the floats its
    captions number, and its pointers typed and cross-referenced (`gates.pointers_latex`).
    G2's notes and its hint on a pointer to nothing are a project's, which declares in
    paper.yaml what goes to the journal as files; the audit says its own, under the notes on
    what it read (round 1 of #837), and counts the main text's kinds G2 counted."""
    from manuscript_guard.gates.pointers_latex import read_pointers_latex
    from manuscript_guard.text.latex.structure import ENTRY

    read = read_pointers_latex(project)
    # Each warns, as a paper's of another format does, where G2 fails a project.
    found = tuple(replace(f, severity=WARN, **({"hint": _LATEX_TO_NOTHING}
                                               if f.code == "pointer-to-nothing" else {}))
                  for f in read.report.findings if f.severity != INFO)  # fmt: skip
    notes: list[Finding] = []
    counted = 0
    for supplementary in (False, True):
        for kind in ("table", "figure"):
            key = (supplementary, kind)
            if read.total[key] and key not in read.uncounted:
                counted += not supplementary
                continue
            pointed = any((p.supplementary, p.kind) == key for p in read.pointers)
            # A supplement with no float at all was not given, and says nothing, as in a
            # paper of another format.
            if pointed and (key in read.uncounted or not supplementary):
                notes.append(_latex_note(kind, supplementary, key in read.uncounted,
                                         project.path("manuscript") / ENTRY))  # fmt: skip
    return Displays(found, tuple(notes), counted=counted)


#: The hint on a LaTeX paper's pointer past what its floats number.
_LATEX_TO_NOTHING = ("point at a table or figure the paper numbers, with `\\ref` to its "
                     "`\\label`, or give the one it means a float with a `\\caption`")


def _latex_note(kind: str, supplementary: bool, uncounted: bool, path: Path) -> Finding:
    """The note on a kind of a LaTeX paper pointed at and not counted."""
    which = f"{'supplementary ' if supplementary else ''}{kind}s"
    if uncounted:
        why = (f"{'its supplement' if supplementary else 'it'} has a {kind} that no float's "
               "`\\caption` numbers")
    else:
        why = f"{kind}s are pointed at and no float's `\\caption` numbers one"
    return Finding(gate=GATE, code=NOT_COUNTED, severity=INFO, path=path, subject=which,
                   message=f"{why}, so its {which} were not counted")


def unread_pdf(path: Path) -> Displays:
    """A PDF whose lines were not rebuilt into paragraphs: its note, and nothing checked."""
    return Displays(notes=(Finding(gate=GATE, code=NOT_COUNTED, severity=INFO, path=path,
                                   message=UNREBUILT,
                                   subject="tables and figures"),))  # fmt: skip


def supplement_findings(read: list[Displays]) -> tuple[list[Finding], list[Finding]]:
    """The pointers to the supplement of every paper `read`, held to the supplement's legends
    read in all of them: findings, and notes where a kind of the supplement is pointed at and
    its legends do not number it 1 to m once each. A kind no paper gives a legend of is not
    checked, and says nothing: the supplement was not given."""
    found: list[Finding] = []
    notes: list[Finding] = []
    for kind in ("table", "figure"):
        numbers = sorted(number for one in read for number in one.supplement.get(kind, ()))
        pointers = [(number, finding) for one in read for k, number, finding in one.to_supplement
                    if k == kind]  # fmt: skip
        if not numbers or not pointers:
            continue
        if numbers != list(range(1, len(numbers) + 1)):
            where = pointers[0][1]
            notes.append(Finding(gate=GATE, code=NOT_COUNTED, severity=INFO, path=where.path,
                                 subject=f"supplementary {kind}s",
                                 message=f"the supplement's {kind} legends read "
                                 f"{_listing(numbers)}, not 1 to {len(numbers)} once each, so "
                                 f"its {kind}s were not counted"))  # fmt: skip
            continue
        found += [_counting(finding, len(numbers)) for number, finding in pointers
                  if number > len(numbers)]  # fmt: skip
    return found, notes


@dataclass(frozen=True)
class _Pointer:
    kind: str
    supplementary: bool
    number: int
    line: int
    shown: str


def _read(text: str, path: Path) -> tuple[list[_Pointer], list[_Pointer]]:
    """The legends and the citations of a text, each in the order it stands."""
    from manuscript_guard.gates.pointers import pointers_at
    from manuscript_guard.text.blocks import find_headings

    lines = text.split("\n")
    starts = [0, *(found.end() for found in re.finditer("\n", text))]
    heads = {bisect.bisect_right(starts, heading.start) for heading in find_headings(text)}
    legends: list[_Pointer] = []
    cited: list[_Pointer] = []
    seen: set[int] = set()
    for _at, pointer in pointers_at(text, path):
        one = _Pointer(pointer.kind, pointer.supplementary, pointer.number, pointer.line,
                       pointer.shown)  # fmt: skip
        first = pointer.line not in seen
        seen.add(pointer.line)
        if first and pointer.line not in heads and _a_legend(lines, pointer.line):
            legends.append(one)
            continue
        if pointer.cites:
            cited.append(one)
    return legends, cited


def _a_legend(lines: list[str], line: int) -> bool:
    """Whether line `line`, from 1, opens its paragraph with a legend."""
    if not 0 < line <= len(lines) or not _LEGEND.match(lines[line - 1]):
        return False
    return line == 1 or not lines[line - 2].strip()


def _held(text: str) -> dict[str, int]:
    """How many tables a text holds, those pandoc writes as pipe and grid tables
    (`text.captioned`), and how many pictures, either of which may be a figure."""
    from manuscript_guard.text.captioned import markdown_captioned

    return {"table": len(markdown_captioned(text)), "figure": len(_PICTURE.findall(text))}


def _counted(kind: str, legends: list[_Pointer], cited: list[_Pointer], path: Path,
             held: int = 0, cut: bool = False) -> tuple[list[Finding], list[Finding]]:  # fmt: skip
    """The findings on one kind of a file's main text, and the note where it is not counted:
    where its legends do not number it 1 to n once each, or where the main text holds more
    of the kind than they number (`held`, counted before the supplement's first legend where
    the file gives one, `cut`), as where a legend stands in a layout table or in a picture
    the check does not read (the corpus run of ea3fc52), and its citations would point at
    nothing."""
    numbers = sorted(p.number for p in legends)
    if not numbers:
        if not cited:
            return [], []
        return [], [Finding(gate=GATE, code=NOT_COUNTED, severity=INFO, path=path,
                            subject=f"{kind}s",
                            message=f"{kind}s are pointed at and no legend numbers "
                            f"one, so its {kind}s were not counted")]  # fmt: skip
    count = len(numbers)
    if numbers == list(range(1, count + 1)) and held > count:
        what = "tables" if kind == "table" else "pictures"
        before = " before the supplement's first legend" if cut else ""
        return [], [Finding(gate=GATE, code=NOT_COUNTED, severity=INFO, path=path,
                            line=legends[0].line, subject=f"{kind}s",
                            message=f"it holds {held} {what}{before}, and its legends "
                            f"number {count} {kind}{'s' if count != 1 else ''}, so its {kind}s "
                            "were not counted")]  # fmt: skip
    if numbers != list(range(1, count + 1)):
        return [], [Finding(gate=GATE, code=NOT_COUNTED, severity=INFO, path=path,
                            line=legends[0].line, subject=f"{kind}s",
                            message=f"its {kind} legends read {_listing(numbers)}, "
                            f"not 1 to {count} once each, so its {kind}s were not counted")]
    found: list[Finding] = []
    first: dict[int, _Pointer] = {}
    for pointer in cited:
        if pointer.number <= count:
            first.setdefault(pointer.number, pointer)
        else:
            found.append(_counting(_to_nothing(pointer, "the paper", path), count))
    # Held among the numbers cited: one cited nowhere is said so below, and is not said to be
    # cited after the next (round 1 of #837).
    for expected, (number, pointer) in zip(sorted(first), first.items(), strict=True):
        if number != expected:
            found.append(Finding(gate=GATE, code="cited-out-of-order", severity=WARN, path=path,
                                 line=pointer.line, context=pointer.shown,
                                 message=f"{kind.capitalize()} {number} is first cited before "
                                 f"{kind} {expected}",
                                 hint=f"ICMJE: number {kind}s in the order of their first "
                                 "citation in the text, so that the first one cited is 1"))
            break
    by_number = {p.number: p for p in legends}
    found += [Finding(gate=GATE, code="display-not-cited", severity=WARN, path=path,
                      line=by_number[number].line, context=by_number[number].shown,
                      message=f"{kind.capitalize()} {number} has its legend in the paper and is "
                      "cited nowhere in its text",
                      hint=f"ICMJE: each {kind} is cited in the text")
              for number in range(1, count + 1) if number not in first]  # fmt: skip
    return found, []


def _to_nothing(pointer: _Pointer, where: str, path: Path) -> Finding:
    """The finding on a pointer past the last legend of its kind, to be given that count
    (`_counting`) once it is known: the supplement's is, once every paper is read."""
    kind = pointer.kind
    label = f"{'supplementary ' if pointer.supplementary else ''}{kind} {pointer.number}"
    return Finding(gate=GATE, code="pointer-to-nothing", severity=WARN, path=path,
                   line=pointer.line, context=pointer.shown,
                   message=f"{pointer.shown!r} points at {label}, and the legends of {where} "
                   f"number its {kind}s 1 to {{count}}",
                   hint=f"point at a {kind} the paper has, or give the {kind} its legend")


def _counting(finding: Finding, count: int) -> Finding:
    """A pointer's finding with the count of its kind's legends said in it."""
    return replace(finding, message=finding.message.replace("{count}", str(count)))


def _listing(numbers: list[int]) -> str:
    return ", ".join(str(number) for number in numbers)


__all__ = ["GATE", "NOT_COUNTED", "UNREBUILT", "Displays", "of_files", "of_latex",
           "supplement_findings", "unread_pdf"]  # fmt: skip
