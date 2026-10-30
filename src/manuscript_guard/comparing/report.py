"""The comparison of two versions, run and reported, as text and as JSON.

v2 is audited as `audit` audits a paper with no outputs (`audit.audit`, G6 and G14 through
`auditing.gates.run_gates`), and each finding that has a line is marked by its sentence: "new
in v2" where that sentence is in no reading of v1, "stood in v1" where it is. The sentence is
read in the text the finding's line belongs to: the paper as `audit` reads it, the Markdown
pandoc makes of a .docx for G6 and G14, or the `.tex` file a LaTeX finding names; v1's
readings are its text, its `.tex` files, and the Markdown pandoc makes of it where it is a
.docx and a finding needs it. A finding with no line is not marked.

The JSON is the audit's: `ok`, `counts`, and `findings`, each in the shape `check --json` gives
one, with its section and its mark. Nothing here is counted by `--strict` (decision 8 of the
editor and referee layer), so `ok` is true wherever the comparison ran.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard import claims
from manuscript_guard.auditing.report import LANGUAGE, WRITING, Item
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


def audited(old: Version, new: Version) -> list[tuple[Item, str]]:
    """v2's audit, each finding with its mark."""
    from manuscript_guard.audit import audit
    from manuscript_guard.auditing.gates import run_gates
    from manuscript_guard.auditing.report import items

    report = audit([new.path], None)
    if new.kind == "LaTeX":
        report.gates = [run_gates(tree.entry, tree) for tree in report.trees]
    elif new.path in set(report.papers):
        report.gates = [run_gates(new.path)]
    marker = _Marker(old, new)
    return [(Item(AUDITED, item.gate, item.code, f"{item.section}: {item.message}",
                  item.severity, False, item.path, item.line, item.context, item.hint),
             marker.mark(item)) for item in items(report)]  # fmt: skip


class _Marker:
    """Whether a finding's sentence is in v1."""

    def __init__(self, old: Version, new: Version) -> None:
        self.old, self.new = old, new
        self.converted: dict[Path, str | None] = {}
        self.texts: dict[Path, str] = {}
        self.held: list[str] | None = None

    def _converted(self, path: Path) -> str | None:
        """The Markdown pandoc makes of a .docx, as G6 and G14 read it."""
        if path not in self.converted:
            from manuscript_guard.auditing.gates import _stage

            try:
                self.converted[path] = _stage(path).files["main.md"]
            except ValueError:
                self.converted[path] = None
        return self.converted[path]

    def _text(self, path: Path) -> str | None:
        if path not in self.texts:
            from manuscript_guard.audit import UnreadableText, read_text

            try:
                self.texts[path] = read_text(path).replace("\r\n", "\n")
            except (OSError, UnreadableText):
                return None
        return self.texts[path]

    def _v1(self, converted: bool) -> list[str]:
        """Every reading of v1 a sentence is looked for in."""
        if self.held is None:
            self.held = [letters.folded(self.old.text)]
            for path in self.old.files:
                text = self._text(path)
                self.held += [letters.folded(text)] if text else []
        if converted and self.old.kind == "Word":
            text = self._converted(self.old.path)
            if text is not None and letters.folded(text) not in self.held:
                self.held.append(letters.folded(text))
        return self.held

    def mark(self, item: Item) -> str:
        if item.path is None or item.line is None:
            return ""
        converted = self.new.kind == "Word" and item.section in (WRITING, LANGUAGE)
        line = item.line
        if converted:
            text = self._converted(self.new.path)
        elif self.new.kind == "LaTeX":
            text = self._text(item.path)
        elif item.path == self.new.path:
            text, line = self.new.text, item.line
            if self.new.kind == "Word":
                text, line = differences.prose(self.new, apart=False)[0], 2 * item.line - 1
        else:
            text = None
        if text is None:
            return ""
        said = [letters.folded(one)
                for one in _sentences_at(text, line, item.context, item.message.split(" ")[0])]
        said = [one for one in said if one]
        if not said:
            return ""
        held = self._v1(converted)
        stood = all(any(one in reading for reading in held) for one in said)
        return STOOD_IN_V1 if stood else NEW_IN_V2


def _sentences_at(text: str, line: int, context: str | None, needle: str = "") -> list[str]:
    """The sentences that stand on `line` of `text`, from 1: the one that holds `context`
    where one does; else the one sentence that holds `needle`, the finding's first word, a
    number or a term, where one alone does; else all of them; the line itself where no
    sentence does."""
    starts = [0] + [at + 1 for at, char in enumerate(text) if char == "\n"]
    if line < 1 or line > len(starts):
        return []
    low = starts[line - 1]
    high = starts[line] - 1 if line < len(starts) else len(text)
    touching = [text[first:end] for _start, first, end in claims.sentence_spans(text)
                if first < max(high, low + 1) and end > low]  # fmt: skip
    if context and context.strip():
        holding = [one for one in touching if letters.folded(context) in letters.folded(one)]
        if holding:
            return holding[:1]
    if needle and len(touching) > 1:
        pattern = re.compile(r"(?<![\w.])" + re.escape(needle) + r"(?![\w])")
        holding = [one for one in touching if pattern.search(one)]
        if len(holding) == 1:
            return holding
    return touching or [text[low:high]]


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
