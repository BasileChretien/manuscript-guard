"""G4: the boxes the journal prints beside the abstract are there, and within its limits.

A journal that asks for highlights, key points or a research-in-context panel says how many
items, how long each may be and how many words the box may hold, and some say which headings
it carries (Question, Findings, Meaning). The profile records each box it asks for under
`boxes:`, quoted from the page as every rule is (`boxes.<id>`), and this check holds the
manuscript's main text to it (`text/boxes.py` reads a box in Markdown and in LaTeX):

* `box-missing`: no heading or environment of the main text is the box's. A box written only
  in the supplement is not the box: a journal reads its boxes with the paper.
* `box-items`: fewer items than `items_min`, or more than `items_max`.
* `box-item-long`: an item over `item_max_chars` characters, spaces included, or over
  `item_max_words` words, as printed: a binding is its value's display.
* `box-over-limit`: the box over `max_words` words.
* `box-headings-missing`: a heading of `headings` that the box does not carry.
* `box-heading-invalid`: a box's `heading` that is no regular expression (a failure from
  internal review, as a profile's other errors are).

Each is a warning until submission, and fails at submission where the profile says the box
is required (`required: true`), as the author decided (2026-10-28).

And a graphical abstract the profile says is required (`graphical_abstract.required`) is
noted while `communication/graphical-abstract/` does not exist: what it is held to is the
`communicate` group's, which reads that folder.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from manuscript_guard.contracts._schema import Unreadable, read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.text.boxes import (
    BoxRule,
    Found,
    box_rules,
    latex_boxes,
    markdown_boxes,
    words,
)

GATE = "G4"
#: Where the graphical abstract is made, once the `communicate` group makes it.
GRAPHICAL_ABSTRACT = Path("communication") / "graphical-abstract"


def check_boxes(project: Project, namespace: dict[str, Any], stage: str) -> Report:
    """Each box the target journal's profile asks for, held to its rules; and a note of a
    required graphical abstract that has not been made."""
    from manuscript_guard.gates.journal import _profile, profile_path
    from manuscript_guard.policy import SUBMISSION

    document = _profile(project)
    if document is None:
        return Report()  # G4's check of the profile says why
    path = profile_path(project, project.target_journal)
    findings: list[Finding] = list(_graphical_abstract(project, document, path))
    rules, invalid = box_rules(document)
    findings += [_invalid(entry, path) for entry in invalid]
    entries = {str(entry["id"]): entry for entry in document.get("boxes") or ()
               if isinstance(entry, dict) and entry.get("id")}  # fmt: skip
    if not rules:
        return Report(tuple(findings))
    main, supplement = read_boxes(project, rules, namespace)
    for rule in rules:
        entry = entries[rule.id]
        severity = FAIL if entry.get("required") and stage == SUBMISSION else WARN
        written = [(where, one) for where, one in main if one.id == rule.id]
        if not written:
            elsewhere = [where for where, one in supplement if one.id == rule.id]
            findings.append(_missing(entry, rule, severity, path, elsewhere, project))
            continue
        for where, one in written:
            findings += held(entry, one, where, severity)
    return Report(tuple(findings))


def read_boxes(project: Project, rules: list[BoxRule], namespace: dict[str, Any]
               ) -> tuple[list[tuple[Path, Found]], list[tuple[Path, Found]]]:  # fmt: skip
    """The boxes the main text writes, and those the supplement does, each with its file."""
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.structure import read_document

        read: list[list[tuple[Path, Found]]] = []
        for supplementary in (False, True):
            sources = [source for source in read_document(folder, supplementary=supplementary)
                       .sources if not source.loose and not source.path.lower().endswith(".sty")]
            read.append([(folder / source.path, one) for source in sources
                         for one in latex_boxes(source, rules, namespace)])  # fmt: skip
        return read[0], read[1]
    main: list[tuple[Path, Found]] = []
    supplement: list[tuple[Path, Found]] = []
    sources = source_files(folder)
    paper = printed_order([p for p in sources if not is_supplementary(folder, p)],
                          supplementary=False)  # fmt: skip
    for path in [*paper, *(p for p in sources if is_supplementary(folder, p))]:
        try:
            text = read_text(path)
        except Unreadable:
            continue  # said once, before the gates run
        into = supplement if is_supplementary(folder, path) else main
        into += [(path, one) for one in markdown_boxes(text, rules, namespace)]
    return main, supplement


def held(entry: dict, box: Found, where: Path, severity: str) -> list[Finding]:
    """What of the profile's rules for a box the box written at `where` does not meet."""
    found: list[Finding] = []
    name = _name(entry)
    count = len(box.items)
    least, most = entry.get("items_min"), entry.get("items_max")
    if (least is not None and count < least) or (most is not None and count > most):
        wanted = _between(least, most)
        found.append(_at("box-items", severity, f"{name} has {count} item(s); the journal asks "
                         f"for {wanted}", where, box.line,
                         "an item is a line of the box's list, or, where it has none, a "
                         "paragraph"))  # fmt: skip
    chars, item_words = entry.get("item_max_chars"), entry.get("item_max_words")
    for number, item in enumerate(box.items, 1):
        over = []
        if chars is not None and len(item) > chars:
            over.append(f"{len(item)} characters, limit {chars}")
        if item_words is not None and words(item) > item_words:
            over.append(f"{words(item)} words, limit {item_words}")
        if over:
            found.append(_at("box-item-long", severity, f"item {number} of {name} is "
                             f"{' and '.join(over)}: \"{_short(item)}\"", where, box.line,
                             "counted as printed, spaces included and each binding as its "
                             "value's display"))  # fmt: skip
    limit = entry.get("max_words")
    if limit is not None and words(box.text) > limit:
        found.append(_at("box-over-limit", severity, f"{name}: {words(box.text)} words, limit "
                         f"{limit}", where, box.line,
                         f"{words(box.text) - limit} words over"))  # fmt: skip
    wanted_headings = [str(h) for h in entry.get("headings") or ()]
    missing = [h for h in wanted_headings if not carries(box.written, h)]
    if missing:
        found.append(_at("box-headings-missing", severity, f"{name} is missing: "
                         f"{', '.join(missing)}", where, box.line,
                         "the journal specifies " + ", ".join(wanted_headings)))  # fmt: skip
    return found


def carries(written: str, heading: str) -> bool:
    """Whether a box's text carries a heading the journal names, as words of its own, in any
    case: "meaningful" does not carry "Meaning" (round 1 of #464)."""
    pattern = r"(?<!\w)" + re.escape(heading) + r"(?!\w)"
    return re.search(pattern, written, re.IGNORECASE) is not None


def _missing(entry: dict, rule: BoxRule, severity: str, path: Path, elsewhere: list[Path],
             project: Project) -> Finding:  # fmt: skip
    asked = "requires" if entry.get("required") else "asks for"
    hint = (f"write it under a heading `{entry['heading']}` names, or in LaTeX in "
            f"\\begin{{{rule.environment}}}, in the main text")
    if elsewhere:
        shown = ", ".join(sorted({_where(p, project) for p in elsewhere}))
        hint += f"; the one in {shown} is the supplement's, which a journal does not read as it"
    return Finding(gate=GATE, code="box-missing", severity=severity,
                   message=f"the journal {asked} {_name(entry)}, and the main text has none",
                   path=path, hint=hint)  # fmt: skip


def _graphical_abstract(project: Project, document: dict, path: Path) -> list[Finding]:
    rules = document.get("graphical_abstract") or {}
    if not rules.get("required") or (project.root / GRAPHICAL_ABSTRACT).is_dir():
        return []
    return [Finding(gate=GATE, code="graphical-abstract-missing", severity=INFO,
                    message="the journal requires a graphical abstract, and "
                    f"{GRAPHICAL_ABSTRACT.as_posix()}/ does not exist",
                    path=path,
                    hint="make one there before submitting; nothing checks it yet")]  # fmt: skip


def _invalid(entry: dict, path: Path) -> Finding:
    return Finding(gate=GATE, code="box-heading-invalid", severity=FAIL,
                   message=f"the heading of box {entry.get('id')} is not a regular expression: "
                   f"{entry.get('heading')!r}",
                   path=path,
                   hint="write it as a Python regular expression, `^highlights$` say")  # fmt: skip


def _name(entry: dict) -> str:
    return f"the box {entry['id']}"


def _between(least: int | None, most: int | None) -> str:
    if least is not None and most is not None:
        return f"{least} to {most}"
    return f"at least {least}" if most is None else f"at most {most}"


def _short(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _where(path: Path, project: Project) -> str:
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return str(path)


def _at(code: str, severity: str, message: str, path: Path, line: int, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=severity, message=message, path=path,
                   line=line, hint=hint)  # fmt: skip
