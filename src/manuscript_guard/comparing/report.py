"""The comparison of two versions, run and reported, as text and as JSON.

v2 is audited as `audit` audits a paper with no outputs (`audit.audit`, G6 and G14 through
`auditing.gates.run_gates`), and so is v1, the same way. Each finding of v2's audit is marked
"stood in v1" where v1's audit gave a finding of the same gate and code that says the same,
word for word and number for number (v1's file name read as v2's), and "new in v2" where it
gave none: a finding on a line nobody touched can come from a change elsewhere, a number of
the Abstract that the Results no longer hold. Two alike in v2 and one in v1 are one of each.

The JSON is the audit's: `ok`, `counts`, and `findings`, each in the shape `check --json` gives
one, with its section and its mark. Nothing here is counted by `--strict` (decision 8 of the
editor and referee layer), so `ok` is true wherever the comparison ran.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.auditing.report import Item
from manuscript_guard.comparing import differences, letters
from manuscript_guard.comparing.differences import GATE
from manuscript_guard.comparing.versions import Version, read_version
from manuscript_guard.findings import INFO

VERSIONS = "Versions"
AUDITED = "v2 audited"
ORDER = (
    VERSIONS, differences.SECTIONS, differences.TABLES, differences.FIGURES,
    differences.NUMBERS, differences.CLAIMS, AUDITED, letters.LETTER, letters.COMMENTS,
)  # fmt: skip
NEW_IN_V2 = "new in v2"
STOOD_IN_V1 = "stood in v1"


@dataclass
class Comparison:
    old: Version
    new: Version
    #: Each item, with its mark where it is a finding of v2's audit.
    items: list[tuple[Item, str]] = field(default_factory=list)
    letter: Path | None = None
    comments: Path | None = None


def compare(old: Path, new: Path, letter: Path | None = None,
            comments: Path | None = None) -> Comparison:  # fmt: skip
    """The two versions read and set side by side, v2 audited, and the letter and the
    referee's comments held to them. Raises `versions.Unreadable`."""
    was, now = read_version(old), read_version(new)
    letter_text = letters.read_text_of(letter, "the letter") if letter else None
    mine = letters.read_text_of(comments, "the comments file") if comments else None
    found = Comparison(was, now, letter=letter, comments=comments)
    unmarked = [*_read(was, now, letter, comments),
                *differences.sections(was, now), *differences.tables(was, now),
                *differences.figures(was, now), *differences.numbers(was, now),
                *differences.claim_moves(was, now)]  # fmt: skip
    found.items = [(item, "") for item in unmarked] + audited(was, now)
    if letter_text is not None:
        found.items += [(item, "") for item in letters.letter_items(letter, letter_text, was,
                                                                    now, mine)]  # fmt: skip
    if mine is not None:
        found.items += [(item, "") for item in letters.comment_items(comments, mine, was, now)]
    return found


def _read(old: Version, new: Version, letter: Path | None, comments: Path | None) -> list[Item]:
    def said(version: Version) -> str:
        return (f"read as {version.kind}: "
                f"{sum(1 for h in version.sections if h.level)} section(s), "
                f"{len(version.tables)} table(s), {len(version.figures)} figure(s) by their "
                "captions")  # fmt: skip

    found = [Item(VERSIONS, GATE, "version-read", said(version), INFO, False, version.path)
             for version in (old, new)]
    found += [Item(VERSIONS, GATE, "file-read", f"read as the {what}", INFO, False, path)
              for what, path in (("response letter", letter), ("referee's comments", comments))
              if path]  # fmt: skip
    return found


# ------------------------------------------------------------------------ v2 audited


def _audit(version: Version) -> list[Item]:
    """A version's audit as `audit` runs it with no outputs, G6 and G14 with it."""
    from manuscript_guard.audit import audit
    from manuscript_guard.auditing.gates import run_gates
    from manuscript_guard.auditing.report import items

    report = audit([version.path], None)
    if version.kind == "LaTeX":
        report.gates = [run_gates(tree.entry, tree) for tree in report.trees]
    elif version.path in set(report.papers):
        report.gates = [run_gates(version.path)]
    return items(report)


def audited(old: Version, new: Version) -> list[tuple[Item, str]]:
    """v2's audit, each finding with its mark: whether v1's audit gave the same finding."""
    stood = Counter((item.gate, item.code, item.message.replace(old.path.name, new.path.name))
                    for item in _audit(old))  # fmt: skip
    found = []
    for item in _audit(new):
        key = (item.gate, item.code, item.message)
        mark = STOOD_IN_V1 if stood[key] > 0 else NEW_IN_V2
        stood[key] -= 1 if stood[key] > 0 else 0
        found.append((Item(AUDITED, item.gate, item.code, f"{item.section}: {item.message}",
                           item.severity, False, item.path, item.line, item.context, item.hint),
                      mark))  # fmt: skip
    return found


# ------------------------------------------------------------------------------ output


def _where(found: Comparison, item: Item, root: Path | None) -> str:
    names = {found.old.path: "v1", found.new.path: "v2"}
    for name, version in (("v1", found.old), ("v2", found.new)):
        names.update({path: f"{name} {_shown(path, root)}" for path in version.files
                      if path != version.path})  # fmt: skip
    names.update({path: name for name, path in (("letter", found.letter),
                                                ("comments", found.comments)) if path})
    if item.path is None:
        return ""
    shown = names.get(item.path, _shown(item.path, root))
    return f"{shown} line {item.line}" if item.line else shown


def _shown(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            pass
    return path.name


def render(found: Comparison, root: Path | None = None) -> str:
    """The comparison as text, a section at a time, in `ORDER`."""
    lines = [f"Compared {_shown(found.old.path, root)} (v1) with {_shown(found.new.path, root)} "
             "(v2). Each line is a fact with its place; none says whether a change answers "
             "a comment."]  # fmt: skip
    for section in ORDER:
        mine = [(item, mark) for item, mark in found.items if item.section == section]
        if not mine:
            continue
        lines += ["", section + (" (each finding new in v2 or standing in v1)"
                                 if section == AUDITED else "")]  # fmt: skip
        for item, mark in mine:
            where = _where(found, item, root)
            tag = f"[{mark}] " if mark else ""
            lines.append(f"  {where + ': ' if where else ''}{tag}{item.message}")
            if item.context:
                lines.append(f"      {item.context}")
    return "\n".join(lines)


def counts(found: Comparison) -> dict[str, int]:
    codes = Counter(item.code for item, _mark in found.items if item.gate == GATE)
    marks = Counter(mark for _item, mark in found.items if mark)
    return {
        "sections_v1": sum(1 for h in found.old.sections if h.level),
        "sections_v2": sum(1 for h in found.new.sections if h.level),
        "tables_v1": len(found.old.tables), "tables_v2": len(found.new.tables),
        "figures_v1": len(found.old.figures), "figures_v2": len(found.new.figures),
        "facts_changed": codes["fact-changed"], "facts_gone": codes["fact-gone"],
        "facts_new": codes["fact-new"],
        "claims_moved": sum(1 for item, _m in found.items if item.section == differences.CLAIMS),
        "v2_findings": sum(1 for item, _m in found.items if item.section == AUDITED),
        "v2_findings_new": marks[NEW_IN_V2], "v2_findings_stood": marks[STOOD_IN_V1],
        "letter_quotations": sum(codes[code] for code in letters.SAID),
        "comments_not_matched": codes["comment-not-matched"],
    }  # fmt: skip


def as_json(found: Comparison) -> str:
    return json.dumps(
        {
            "ok": True,
            "old": str(found.old.path),
            "new": str(found.new.path),
            "letter": None if found.letter is None else str(found.letter),
            "comments": None if found.comments is None else str(found.comments),
            "counts": counts(found),
            "findings": [item.as_dict() | {"mark": mark or None} for item, mark in found.items],
        },
        indent=2,
        ensure_ascii=True,
    )
