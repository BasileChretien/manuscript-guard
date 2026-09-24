"""Deciding what a returned document changed, and applying it to the source in one pass.

`import` used to decide and apply as it went: it reordered the file, then spliced each
reworded paragraph in at the offset it had recorded *before* the reorder. A move and a
rewording in the same document therefore landed a rewording in the wrong place. What came
out was `{{lit.agency.withdrawnWhether the signal extends...`: a binding cut in half, a
sentence gone, the co-author's edit lost, and `check` passing it. The design had said a move
and a rewording were orthogonal; they were, until both were applied.

So the plan is built first, from one reading of each document, and applied in one pass
from one snapshot of the offsets: each paragraph slot in a file receives the paragraph that
now belongs there, in its reworded form if it has one.

The plan also refuses the edits a paragraph identifier cannot vouch for. The identifier is a
bookmark at the start of a paragraph, so it says which paragraph *starts* here and nothing
about where it ends:

- Split in two, the first half keeps the identifier, and merging it replaced the whole
  source paragraph with its first half.
- Joined, the first paragraph absorbed the second and was merged with both texts, while the
  second was reported deleted and left in place - so its text was in the source twice.

Both are refused, and named, rather than guessed at.
"""

from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.docxtext import Block
from manuscript_guard.roundtrip import Alignment, align, moves


@dataclass(frozen=True)
class Refusal:
    """One paragraph whose edit is not applied, with what came back and why not."""

    name: str
    text: str
    why: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """What a returned document changed, decided before anything is written."""

    #: Identifiers that reached the document the co-author was sent.
    reached: frozenset[str]
    #: Identifiers in the order the returned document has them.
    order: tuple[str, ...]
    #: Identifier -> the source paragraph rebuilt with the co-author's wording.
    merged: dict[str, str] = field(default_factory=dict)
    refused: tuple[Refusal, ...] = ()
    #: Deleted in Word - outright or as a tracked change. Left in place in the source.
    gone: tuple[str, ...] = ()
    #: Groups of identifiers that came back as one paragraph.
    joined: tuple[tuple[str, ...], ...] = ()
    moved: tuple[tuple[str, int, int], ...] = ()
    #: Moved among a different file's paragraphs; not applied.
    crossed: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (
            self.merged or self.refused or self.gone or self.joined or self.moved or self.crossed
        )


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def _beside_new_text(sent: list[Block], returned: list[Block]) -> set[str]:
    """Identifiers whose paragraph came back directly beside text the document did not have.

    A split leaves the second half as a paragraph with no identifier next to the first, and
    that is the only trace it leaves: the first half is merely a shorter paragraph. So any
    untagged paragraph whose text was not in the document as sent is new, and a tagged
    paragraph touching one - across nothing but empty paragraphs - may have been split.
    Compared by text rather than by position, because a move changes every neighbour and
    creates no text at all. An edited heading is new text too, which costs a refusal of the
    paragraph beside it when both were edited; the alternative is a split that truncates.
    """
    unchanged = Counter(b.text for b in sent if not b.table and not b.names and b.text)
    new: set[int] = set()
    for index, block in enumerate(returned):
        if block.table or block.names or not block.text:
            continue
        if unchanged[block.text]:
            unchanged[block.text] -= 1
        else:
            new.add(index)

    def touches(indices: range) -> bool:
        for i in indices:
            block = returned[i]
            if block.table or block.names:
                return False
            if i in new:
                return True
            if block.text:
                return False
        return False

    found: set[str] = set()
    for index, block in enumerate(returned):
        if block.names and not block.table and (
            touches(range(index - 1, -1, -1)) or touches(range(index + 1, len(returned)))
        ):
            found.update(block.names)
    return found


def crossed_files(known: dict, order: list[str]) -> list[str]:
    """Identifiers that came back sitting among a different file's paragraphs.

    Reordering is per file, so a paragraph cut from one file and pasted into another was
    once silently repositioned inside the file it came from and never applied to the file
    it went to. It is left where it is and reported.
    """
    present = [name for name in order if name in known]
    crossed = []
    for position, name in enumerate(present):
        home = known[name][0]
        neighbours = [
            known[other][0]
            for other in present[max(0, position - 1) : position + 2]
            if other != name
        ]
        if neighbours and home not in neighbours:
            crossed.append(name)
    return crossed


def _read_returned(
    returned: list[Block], rendered: dict[str, str]
) -> tuple[dict[str, str], list[tuple[str, ...]], set[str]]:
    """Each identifier's text, the groups that were joined, and identifiers that slid.

    When a paragraph is deleted in Word its bookmark can survive, pushed to the start of the
    next paragraph. A block carrying two identifiers whose text is exactly one of them
    unchanged is that, not a join.
    """
    texts: dict[str, str] = {}
    joined: list[tuple[str, ...]] = []
    slid: set[str] = set()
    for block in returned:
        names = [name for name in block.names if name in rendered]
        if block.table or not names:
            continue
        if len(names) == 1:
            texts.setdefault(names[0], block.text)
            continue
        kept = [name for name in names if _same(rendered[name], block.text)]
        if len(kept) == 1:
            texts.setdefault(kept[0], block.text)
            slid.update(name for name in names if name != kept[0])
        else:
            joined.append(tuple(names))
    return texts, joined, slid


def _absorbed(now: str, other: str, was: str) -> bool:
    """Whether this paragraph reads more like itself followed by `other` than like itself.

    A join made by selecting across the boundary and retyping deletes the second paragraph's
    bookmark with the selection, so the second paragraph looks deleted and the first merely
    longer. Two explanations fit a paragraph that changed beside one that vanished - reworded
    while its neighbour was deleted, or joined with its neighbour - and the one whose text
    the returned paragraph resembles more is taken, a tie counting as the join.

    Two earlier versions looked for the neighbour's words instead, and each was defeated in
    a round of review: one unbroken run of six words was split by a single edited word, and
    "the words it gained" lost the absorbed paragraph's common words to the old text as soon
    as the transition was retyped too. Both left the neighbour's text in the source twice.
    """
    theirs, mine, before = other.split(), now.split(), was.split()
    if not theirs or not mine:
        return False
    alone = difflib.SequenceMatcher(a=before, b=mine, autojunk=False).ratio()
    together = difflib.SequenceMatcher(a=before + theirs, b=mine, autojunk=False).ratio()
    return together >= alone


def _joined_without_bookmark(
    rendered: dict[str, str], texts: dict[str, str], in_join: set[str]
) -> list[tuple[str, str]]:
    """Pairs whose second paragraph vanished into the first; see `_absorbed`."""
    found = []
    sequence = list(rendered)
    for position, name in enumerate(sequence[1:], start=1):
        before = sequence[position - 1]
        now = texts.get(before)
        if (
            name not in texts
            and now
            and not {name, before} & in_join
            and not _same(rendered[before], now)
            and _absorbed(now, rendered[name], rendered[before])
        ):
            found.append((before, name))
            in_join.update((before, name))
    return found


def plan_import(known: dict, reference: list[Block], returned: list[Block]) -> Plan:
    """Compare the document as sent with the document as returned, paragraph by paragraph."""
    rendered = {b.names[0]: b.text for b in reference if b.names and not b.table}
    texts, joined, slid = _read_returned(returned, rendered)
    in_join = {name for group in joined for name in group}
    joined += _joined_without_bookmark(rendered, texts, in_join)
    counts = Counter(n for b in returned if not b.table for n in b.names if n in rendered)
    # A paragraph that came back twice has no one position, so it keeps the one it had:
    # left in, its first copy decided where it went, wherever that copy had been pasted.
    order = [
        name
        for name in dict.fromkeys(
            n for b in returned if not b.table for n in b.names if n in rendered
        )
        if name not in slid and counts[name] == 1
    ]

    beside_new = _beside_new_text(reference, returned)
    merged: dict[str, str] = {}
    refused: list[Refusal] = []
    gone: list[str] = []
    for name, (_path, source, _start) in known.items():
        if name not in rendered or name in in_join:
            continue
        was, now = rendered[name], texts.get(name)
        if counts[name] > 1:
            refused.append(Refusal(name, now or "", (_TWICE.format(n=counts[name]),)))
        elif now is None or (not now.strip() and was.strip()):
            gone.append(name)
        elif _same(was, now):
            continue
        elif name in beside_new:
            refused.append(Refusal(name, now, (_SPLIT,)))
        else:
            aligned = align(source, was, now)
            if aligned.rebuilt:
                merged[name] = aligned.rebuilt
            else:
                refused.append(Refusal(name, now, why(aligned)))

    crossed = crossed_files(known, order)
    moved = [
        entry
        for entry in moves([n for n in rendered if n in set(order)], order)
        if entry[0] not in set(crossed)
    ]
    return Plan(
        reached=frozenset(rendered),
        order=tuple(order),
        merged=merged,
        refused=tuple(refused),
        gone=tuple(gone),
        joined=tuple(joined),
        moved=tuple(moved),
        crossed=tuple(crossed),
    )


_SPLIT = (
    "it came back with a new paragraph beside it: split in two in Word, or new text written "
    "next to it. Merging it would replace the whole source paragraph with only part of it. "
    "Make the split or the addition in the .md."
)
_TWICE = (
    "its identifier appears {n} times in the returned document, so which copy is the "
    "paragraph cannot be told. Make the edit in the .md."
)


def why(aligned: Alignment) -> tuple[str, ...]:
    """The reason a reworded paragraph was not merged, in the author's terms."""
    if aligned.markup:
        return (
            "it carries a footnote or a link, which Word's plain text cannot bring back: "
            "merging it would delete them. Make the edit in the .md.",
        )
    if aligned.changed:
        lines = []
        for shown, token in aligned.changed:
            if token.startswith("{{"):
                key = token.strip("{} ")
                lines.append(f"'{shown}' comes from {key}. Change the analysis, not the document.")
            else:
                lines.append(
                    f"'{shown}' is the citation {token}. Change the citation in the .md, "
                    f"not in Word."
                )
        return tuple(lines)
    return (
        "it could not be lined up with its own source, so its numbers and citations cannot be "
        "told apart from its prose. Make the edit in the .md.",
    )


def apply_plan(known: dict, plan: Plan) -> list[Path]:
    """Write the moves and the rewordings, together, from one snapshot of the offsets.

    Per file, every slot a paragraph occupied receives the paragraph that now belongs there,
    in its reworded form if it has one. Returns the files that changed.

    A paragraph that has no place of its own in the returned document - deleted in Word, moved
    into another file, absorbed by a join that lost its bookmark, or present twice - travels
    with the paragraph it followed in the source. It used to keep its slot while the others
    moved around it, so a move elsewhere in the file could land between the two halves of a
    join.
    """
    order = {name: position for position, name in enumerate(plan.order)}
    crossed = set(plan.crossed)
    by_file: dict[Path, list[str]] = {}
    for name, (path, _text, _start) in known.items():
        if name in plan.reached:
            by_file.setdefault(path, []).append(name)

    written = []
    for path, slots in by_file.items():
        placed = [n for n in slots if n in order and n not in crossed]
        followers: dict[str | None, list[str]] = {}
        anchor: str | None = None
        for name in slots:
            if name in placed:
                anchor = name
            else:
                followers.setdefault(anchor, []).append(name)
        sequence = list(followers.get(None, []))
        for name in sorted(placed, key=order.__getitem__):
            sequence += [name, *followers.get(name, [])]
        occupant = dict(zip(slots, sequence, strict=True))
        edits = []
        for slot in slots:
            incoming = occupant[slot]
            _p, original, start = known[slot]
            replacement = plan.merged.get(incoming, known[incoming][1])
            if replacement != original:
                edits.append((start, start + len(original), replacement))
        if not edits:
            continue
        text = path.read_text(encoding="utf-8")
        # Right to left, so an earlier splice cannot move a later one, and at the offsets
        # the identifiers carry, so a repeated paragraph cannot be confused for its twin.
        for start, end, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
