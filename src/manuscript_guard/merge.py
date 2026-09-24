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
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.docxtext import Block, spaced
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
    #: Moved into a different section or file; not applied.
    misplaced: tuple[str, ...] = ()
    #: Identifier -> (file, section): the stretch between headings, tables and figures that
    #: the paragraph belongs to, which is what a move is applied within.
    sections: dict[str, tuple[Path, int]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (
            self.merged
            or self.refused
            or self.gone
            or self.joined
            or self.moved
            or self.misplaced
        )


def _same(a: str, b: str) -> bool:
    """Word's text against Word's text, a no-break space compared as itself: split on every
    kind of space, a paragraph whose only change was one the co-author typed read as untouched,
    and the change was dropped with nothing reported."""
    return spaced(a).strip() == spaced(b).strip()


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


def _sections(known: dict) -> dict[str, tuple[Path, int]]:
    """Which section of its file each paragraph is in: how many headings, tables or figures
    come before it there.

    Import fills paragraph slots, and a heading is not a slot: it cannot change how many
    paragraphs a section holds. It used to fill slots per file, so a paragraph moved from the
    Discussion to the Introduction pushed one paragraph out of every section in between. A
    section is therefore the unit a move is applied within.
    """
    out: dict[str, tuple[Path, int]] = {}
    texts: dict[Path, str] = {}
    section: dict[Path, int] = {}
    end: dict[Path, int] = {}
    for name, (path, para, start) in sorted(
        known.items(), key=lambda item: (str(item[1][0]), item[1][2])
    ):
        if path not in texts:
            texts[path] = path.read_text(encoding="utf-8")
            section[path] = 0
        elif texts[path][end[path] : start].strip():
            section[path] += 1
        out[name] = (path, section[path])
        end[path] = start + len(para)
    return out


def _boundaries(reference: list[Block], rank) -> dict[tuple, deque]:
    """The headings, tables and figures of the document as sent, each ranked as the opening
    of the section after it, keyed by what they say (a table by its position among tables).

    Only what stands between two sections counts. Pandoc can render an untagged paragraph
    inside a section - display maths, say - and ranked as a boundary it would make every
    untouched document look as if a paragraph had crossed it.
    """
    found: dict[tuple, deque] = {}
    pending: list[tuple] = []
    tables = 0
    previous: tuple | None = None
    for block in reference:
        if block.names and not block.table:
            here = rank(block.names[0])
            if previous is None or previous[:2] != here[:2]:
                for key in pending:
                    found.setdefault(key, deque()).append((*here[:2], 0))
            pending, previous = [], here
        elif block.table:
            pending.append(("table", tables))
            tables += 1
        elif block.text:
            pending.append(("text", block.text))
    for key in pending:
        found.setdefault(key, deque()).append((float("inf"),))
    return found


def _misplaced(
    reference: list[Block], returned: list[Block], order: list[str], moved: set[str], rank
) -> list[str]:
    """Paragraphs that came back outside their own section or file.

    Every paragraph is judged, not only those the order diff calls moved: a paragraph dragged
    from the end of one section to just below the next heading keeps its place among the
    paragraphs, so the diff saw nothing and the move was dropped with "nothing came back".
    The largest set of paragraphs whose sections read in order - with the headings, tables and
    figures as sent held fixed - is kept, and whatever falls outside it is out of place. The
    order diff only breaks ties, so the paragraph that crossed the heading is the one named,
    not a neighbour the diff happened to prefer. A file holding a single paragraph, which the
    first version of this check reported as moved when nothing had moved, reads in order.
    """
    boundaries = _boundaries(reference, rank)
    same_tables = sum(b.table for b in reference) == sum(b.table for b in returned)
    ordered = set(order)
    sequence: list[tuple[str | None, tuple]] = []
    tables = 0
    for block in returned:
        if block.table:
            key = ("table", tables)
            tables += 1
            if same_tables and boundaries.get(key):
                sequence.append((None, boundaries[key].popleft()))
        elif block.names:
            sequence += [(name, rank(name)) for name in block.names if name in ordered]
        elif block.text and boundaries.get(("text", block.text)):
            sequence.append((None, boundaries[("text", block.text)].popleft()))

    # The heaviest subsequence whose ranks never decrease. A heading outweighs every
    # paragraph together, and a paragraph the diff did not call moved outweighs one it did.
    anchor = 2 * len(sequence) + 1
    weight = [anchor if n is None else (1 if n in moved else 2) for n, _r in sequence]
    best, back = list(weight), [-1] * len(sequence)
    for j in range(len(sequence)):
        for i in range(j):
            if sequence[i][1] <= sequence[j][1] and best[i] + weight[j] > best[j]:
                best[j], back[j] = best[i] + weight[j], i
    kept: set[int] = set()
    at = max(range(len(sequence)), key=best.__getitem__, default=-1)
    while at >= 0:
        kept.add(at)
        at = back[at]
    return [n for i, (n, _r) in enumerate(sequence) if n is not None and i not in kept]


def _in_parts(reference: list[Block], sections: dict) -> set[str]:
    """Paragraphs that reach Word as more than one paragraph.

    Display maths splits one: pandoc renders "Before $$y = z$$ after." as three Word
    paragraphs, and only the first carries the identifier. Merging a rewording of that first
    part replaced the whole source paragraph with it, deleting the equation and everything
    after. Within a section nothing stands between two paragraphs, so anything untagged
    between them in the document as sent is part of the one before.
    """
    found: set[str] = set()
    last: str | None = None
    between = False
    for block in reference:
        if block.names and not block.table:
            name = block.names[0]
            if last and between and sections.get(last, 0) == sections.get(name, 1):
                found.add(last)
            last, between = name, False
        else:
            between = True
    return found


def _took_in(name: str, now: str, was: str, reference: list[Block], missing: Counter) -> str:
    """The heading or caption beside this paragraph that it absorbed, if it absorbed one.

    Delete at the end of a heading makes a run-in heading: one paragraph, carrying the
    paragraph's identifier, reading "MethodsWe analysed...". It merged as prose, and the
    heading stayed in the file above it. The heading has no identifier to be joined by, so
    it is recognised by having vanished while its text turned up in its neighbour - counted,
    not merely found, because a paragraph often opens by naming its heading ("Statistical
    analysis used..."), and requiring the text to be new let that join through as
    "Statistical analysisStatistical analysis used...".
    """
    at = next(i for i, b in enumerate(reference) if b.names and b.names[0] == name)
    squashed_now, squashed_was = " ".join(now.split()), " ".join(was.split())
    for step in (-1, 1):
        i = at + step
        while 0 <= i < len(reference) and not (
            reference[i].names or reference[i].table or reference[i].text
        ):
            i += step
        if not 0 <= i < len(reference) or reference[i].names or reference[i].table:
            continue
        text = " ".join(reference[i].text.split())
        if missing[reference[i].text] and squashed_now.count(text) > squashed_was.count(text):
            return reference[i].text
    return ""


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

    sections = _sections(known)
    in_parts = _in_parts(reference, sections)
    beside_new = _beside_new_text(reference, returned)
    untagged = Counter(b.text for b in reference if not b.names and not b.table and b.text)
    untagged.subtract(b.text for b in returned if not b.names and not b.table and b.text)
    missing = +untagged
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
        elif not was.strip():
            refused.append(Refusal(name, now, (_HIDDEN,)))
        elif name in in_parts:
            refused.append(Refusal(name, now, (_IN_PARTS,)))
        elif took := _took_in(name, now, was, reference, missing):
            refused.append(Refusal(name, now, (_TOOK_IN.format(text=took[:60]),)))
        elif name in beside_new:
            refused.append(Refusal(name, now, (_SPLIT,)))
        else:
            aligned = align(source, was, now)
            if aligned.rebuilt:
                merged[name] = aligned.rebuilt
            else:
                refused.append(Refusal(name, now, why(aligned)))

    files: dict[Path, int] = {}
    for name in rendered:
        files.setdefault(known[name][0], len(files))

    def rank(name: str) -> tuple:
        path, section = sections[name]
        return (files[path], section, 1)

    moved = moves([n for n in rendered if n in set(order)], order)
    misplaced = _misplaced(reference, returned, order, {m[0] for m in moved}, rank)
    moved = [entry for entry in moved if entry[0] not in set(misplaced)]
    return Plan(
        reached=frozenset(rendered),
        order=tuple(order),
        merged=merged,
        refused=tuple(refused),
        gone=tuple(gone),
        joined=tuple(joined),
        moved=tuple(moved),
        misplaced=tuple(misplaced),
        sections=sections,
    )


_SPLIT = (
    "it came back with a new paragraph beside it: split in two in Word, or new text written "
    "next to it. Merging it would replace the whole source paragraph with only part of it. "
    "Make the split or the addition in the .md."
)
_HIDDEN = (
    "text was typed where this paragraph renders nothing - an HTML comment, or markup that "
    "prints no text. Merging it would replace what is hidden there. Add the text in the .md."
)
_IN_PARTS = (
    "it reaches Word as more than one paragraph - display maths, or markup pandoc sets apart "
    "- and only its first part carries its identifier. Merging would replace the whole "
    "paragraph with that part. Make the edit in the .md."
)
_TOOK_IN = (
    "it came back joined with the heading or caption beside it ('{text}'). Merging it would "
    "copy that text into the paragraph while the heading stays where it is. Undo the join, or "
    "make the edit in the .md."
)
_TWICE = (
    "its identifier appears {n} times in the returned document, so which copy is the "
    "paragraph cannot be told. Make the edit in the .md."
)


def why(aligned: Alignment) -> tuple[str, ...]:
    """The reason a reworded paragraph was not merged, in the author's terms."""
    if aligned.markup:
        named = aligned.markup
        listed = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
        return (
            f"the edited text carries {listed}, which Word's plain text cannot bring back: "
            f"merging it would lose {'it' if len(named) == 1 else 'them'}. "
            f"Make the edit in the .md.",
        )
    if aligned.misread:
        return (
            "merged, it would not read as the text that came back: something in the new "
            "wording would be read as Markdown, or would change markup beside it. "
            "Make the edit in the .md.",
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
        "it could not be lined up with its own source, so its numbers, citations and markup "
        "cannot be told apart from its prose. Make the edit in the .md.",
    )


def _arranged(slots: list[str], order: dict[str, int], fixed: set[str]) -> dict[str, str]:
    """Which paragraph each slot of one section receives: slot -> paragraph.

    A paragraph with no place of its own in the returned document - deleted in Word, moved
    somewhere it cannot go, absorbed by a join that lost its bookmark, or present twice -
    travels with the paragraph it followed in the section, or stays first if it was first.
    It used to keep its slot while the others moved around it, so a move could land between
    the two halves of a join; and anchoring across a heading carried it into the section
    before.
    """
    placed = [n for n in slots if n in order and n not in fixed]
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
    return dict(zip(slots, sequence, strict=True))


def apply_plan(known: dict, plan: Plan) -> list[Path]:
    """Write the moves and the rewordings, together, from one snapshot of the offsets.

    Per section of each file, every slot a paragraph occupied receives the paragraph that now
    belongs there, in its reworded form if it has one. Returns the files that changed.
    """
    order = {name: position for position, name in enumerate(plan.order)}
    fixed = set(plan.misplaced)
    by_section: dict[tuple[Path, int], list[str]] = {}
    for name, (path, _text, _start) in known.items():
        if name in plan.reached:
            where = plan.sections.get(name, (path, 0))
            by_section.setdefault(where, []).append(name)

    occupant: dict[str, str] = {}
    by_file: dict[Path, list[str]] = {}
    for (path, _section), slots in by_section.items():
        occupant.update(_arranged(slots, order, fixed))
        by_file.setdefault(path, []).extend(slots)

    written = []
    for path, slots in by_file.items():
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
