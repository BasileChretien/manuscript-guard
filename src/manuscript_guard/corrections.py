"""What a reading would change in a manuscript's text, exactly, at every place it would.

Most of what G14 reports is the author's to judge. Some of it has one answer once the
reading has chosen the manuscript's own form: a British word in a paper declared American
English and listed with one American spelling; a sign after P or n spaced unlike the rest;
two bounds joined unlike the rest; a per cent sign set apart unlike the rest; a number run
into its unit or into the word after it. A finding names the first place only. An `Edit`
is one change at one place, every place. The audit writes the edits into a copy of the
paper as tracked changes, which the author accepts or rejects in Word (the author's audit,
2026-11-11).

**Where the manuscript is in doubt, nothing is edited.** Two forms used as often, a paper
mostly in the other English, a list that gives two spellings: the finding stays, and no
edit is offered.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the readings that make edits import this module
    from manuscript_guard.gates.vocabulary import Passage


@dataclass(frozen=True)
class Edit:
    """One change a reading would make to a passage's text: `text[start:end]` becomes
    `new`. `within` is the stretch it belongs to, the use it is part of ("P=0.03" for the
    space after the P): what a reader is shown changed, and what finds it in a document."""

    code: str
    passage: Passage
    start: int
    end: int
    new: str
    within: tuple[int, int]


@dataclass(frozen=True)
class Correction:
    """The words at `offset` of a passage, `old`, as the readings would write them, `new`:
    the edits of one stretch, or of several stretches that overlap, made together. `codes`
    are the findings they correct; `line` and `context` place it as a finding's do."""

    codes: tuple[str, ...]
    path: Path
    line: int
    offset: int
    old: str
    new: str
    context: str


def corrections(edits: Iterable[Edit]) -> list[Correction]:
    """The edits gathered by stretch, in the order of the passages and the text: edits
    whose stretches overlap are one correction, over their union. Two edits of the same
    characters, or two insertions at one place, that say different things are both
    refused: no reading decides what another's edit becomes."""
    # By file and text, not by passage: the spelling is read in a passage of its own, the
    # same text with other sections hidden, and its edits stand among the notation's.
    by_passage: dict[tuple[Path, str], tuple[Passage, list[Edit]]] = {}
    for edit in edits:
        key = (edit.passage.path, edit.passage.text)
        by_passage.setdefault(key, (edit.passage, []))[1].append(edit)
    out: list[Correction] = []
    for passage, found in by_passage.values():
        # One edit said by two readings is one: a passage is no key, so its edits are
        # told apart by the rest.
        unique = {(e.start, e.end, e.new, e.code, e.within): e for e in found}
        for group in _overlapping(sorted(unique.values(), key=_order)):
            kept = _agreed(group)
            if kept:
                out.append(_correction(passage, kept))
    return out


def _order(edit: Edit) -> tuple[int, int, int, str, str]:
    return (edit.within[0], edit.start, edit.end, edit.new, edit.code)


def _overlapping(edits: list[Edit]) -> list[list[Edit]]:
    """The edits in groups whose stretches overlap, a stretch touching the next at its end
    being apart from it."""
    groups: list[list[Edit]] = []
    end = -1
    for edit in edits:
        if groups and edit.within[0] < end:
            groups[-1].append(edit)
            end = max(end, edit.within[1])
        else:
            groups.append([edit])
            end = edit.within[1]
    return groups


def _agreed(group: list[Edit]) -> list[Edit]:
    """The group's edits less any two that change the same characters, or insert at one
    place, differently."""
    clashing: set[int] = set()
    for index, one in enumerate(group):
        for later, other in enumerate(group[index + 1 :], start=index + 1):
            if one.new == other.new and (one.start, one.end) == (other.start, other.end):
                continue
            same_place = one.start == one.end == other.start == other.end
            if same_place or (one.start < other.end and other.start < one.end):
                clashing |= {index, later}
    return [edit for index, edit in enumerate(group) if index not in clashing]


def _correction(passage: Passage, edits: list[Edit]) -> Correction:
    from manuscript_guard.gates.vocabulary import context

    start = min(edit.within[0] for edit in edits)
    end = max(edit.within[1] for edit in edits)
    text = passage.text
    new, at = [], start
    for edit in sorted({(e.start, e.end, e.new) for e in edits}):
        new.append(text[at : edit[0]] + edit[2])
        at = edit[1]
    new.append(text[at:end])
    return Correction(
        codes=tuple(dict.fromkeys(edit.code for edit in edits)),
        path=passage.path,
        line=passage.line_of(start),
        offset=start,
        old=text[start:end],
        new="".join(new),
        context=context(text, start, end - start),
    )


def applied(text: str, found: Iterable[Correction]) -> str:
    """`text` with each correction made, as `old` at `offset` becoming `new`."""
    out, at = [], 0
    for correction in sorted(found, key=lambda one: one.offset):
        out.append(text[at : correction.offset] + correction.new)
        at = correction.offset + len(correction.old)
    out.append(text[at:])
    return "".join(out)


__all__ = ["Correction", "Edit", "applied", "corrections"]
