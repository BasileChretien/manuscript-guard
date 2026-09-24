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
from dataclasses import dataclass, field, replace
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
    #: Gone from its place, with its words back elsewhere, as (identifier, Word's text): moved
    #: where Word did not record the move, and reworded or reading like another paragraph, so
    #: the copy cannot be matched to it for certain. Left in place in the source.
    displaced: tuple[tuple[str, str], ...] = ()
    #: Groups of identifiers that came back as one paragraph.
    joined: tuple[tuple[str, ...], ...] = ()
    moved: tuple[tuple[str, int, int], ...] = ()
    #: Moved into a different section or file; not applied.
    misplaced: tuple[str, ...] = ()
    #: Moved within their section, and not applied: the section also gained text the
    #: document as sent did not have, or holds an identifier on text not its own, so where
    #: its paragraphs now stand cannot be read with certainty.
    withheld: tuple[str, ...] = ()
    #: Identifier -> (file, section): the stretch between headings, tables and figures that
    #: the paragraph belongs to, which is what a move is applied within.
    sections: dict[str, tuple[Path, int]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (
            self.merged
            or self.refused
            or self.gone
            or self.displaced
            or self.joined
            or self.moved
            or self.misplaced
            or self.withheld
        )


def _squashed(text: str) -> str:
    return spaced(text).strip()


def _same(a: str, b: str) -> bool:
    """Word's text against Word's text, a no-break space compared as itself: split on every
    kind of space, a paragraph whose only change was one the co-author typed read as untouched,
    and the change was dropped with nothing reported."""
    return _squashed(a) == _squashed(b)


def _unidentified(reference: list[Block]) -> Counter:
    """What the document as sent held without an identifier - headings, captions - by text."""
    return Counter(_squashed(b.text) for b in reference if not b.names and not b.table and b.text)


def _off_headings(
    rendered: dict[str, str], returned: list[Block], expected: Counter
) -> list[Block]:
    """Identifiers taken off a heading or caption they slid onto.

    Deleted or cut without Track Changes, the last paragraph of a section leaves its
    identifier on the heading after it. Read as the paragraph's text, the heading was merged
    into it wherever the paragraph named the heading - "Methods", bindings intact. A block
    that reads exactly as a heading or caption of the document as sent is that heading, and
    an identifier on it names a paragraph that is no longer there.
    """
    out = []
    for block in returned:
        text = _squashed(block.text)
        if (
            block.names
            and not block.table
            and expected[text]
            and not any(_squashed(rendered.get(name, "")) == text for name in block.names)
        ):
            block = replace(block, names=())
        out.append(block)
    return out


def _given_back(
    rendered: dict[str, str], returned: list[Block], expected: Counter
) -> list[Block]:
    """Identifiers left on an empty line by Enter pressed at the start of their paragraph.

    An identifier is an empty bookmark at the start of its paragraph, and Enter pressed there
    puts the new line in front of the paragraph's text and behind its bookmark. Without Track
    Changes nothing in the markup says so, and the paragraph was reported deleted, with the
    advice to delete a paragraph nobody deleted. Given back only from a line with no text, to
    the next paragraph when it reads exactly as the identified one was sent.

    Not from text: a paste or a new paragraph typed there reads the same way as a paragraph
    rewritten with a copy of its old text pasted after it, and a first version that gave
    identifiers back from pasted text was beaten three times in review. Those are refused.
    """
    out = list(returned)
    for index, block in enumerate(out):
        if block.table or not block.names or block.text:
            continue
        after = index + 1
        while after < len(out) and not (out[after].table or out[after].names or out[after].text):
            after += 1
        if after == len(out) or out[after].table or out[after].names:
            continue
        text = _squashed(out[after].text)
        theirs = [n for n in block.names if n in rendered and _squashed(rendered[n]) == text]
        if len(theirs) != 1 or expected[text]:
            continue
        out[after] = replace(out[after], names=block.names)
        out[index] = replace(block, names=())
    return out


def _recovered(
    rendered: dict[str, str], reference: list[Block], returned: list[Block]
) -> list[Block]:
    """The returned document with identifiers put back where only exact text can say.
    `docxtext` has already put them back where the tracked changes say."""
    expected = _unidentified(reference)
    return _given_back(rendered, _off_headings(rendered, returned, expected), expected)


def _pieces(reference: list[Block], name: str) -> list[str]:
    """The untagged paragraphs Word shows after this one's first part, as sent."""
    at = next(i for i, b in enumerate(reference) if b.names and b.names[0] == name)
    pieces = []
    for block in reference[at + 1 :]:
        if block.names or block.table:
            break
        if block.text:
            pieces.append(block.text)
    return pieces


def _between_parts(
    returned: list[Block], parts: dict[str, list[str]], expected: Counter
) -> dict[str, set[str]]:
    """Paragraphs that came back between one paragraph and another part of it.

    Display maths reaches Word as three paragraphs. A paragraph moved between the parts is
    inside the paragraph, a place the source does not have: reordered to after the whole of
    it, the split the co-author made was dropped without a word. Only within a section: a
    heading or caption ends the search. Returns, for each paragraph with something inside it,
    what is. (A paragraph split in Word leaves new text in its section, and `_unsettled`
    holds that section's moves.)
    """
    found: dict[str, set[str]] = {}
    for index, block in enumerate(returned):
        owner = next((name for name in block.names if parts.get(name)), None)
        if owner is None:
            continue
        wanted = [_squashed(text) for text in parts[owner]]
        passed: list[str] = []
        for later in returned[index + 1 :]:
            text = _squashed(later.text)
            if not wanted or later.table:
                break
            if later.names:
                passed += later.names
            elif text in wanted:
                wanted.remove(text)
                if passed:
                    found.setdefault(owner, set()).update(passed)
            elif expected[text]:
                break
    return found


def _not_its_own(
    rendered: dict[str, str], texts: dict[str, str], returned: list[Block], expected: Counter
) -> set[str]:
    """Identifiers that came back on text that is not their paragraph's.

    Their paragraph's own text came back as a paragraph with no identifier, or what they are
    on reads word for word as another paragraph, a heading or a caption did. That is text
    pasted or typed in front of them without Track Changes, where nothing in the markup says
    so. Merged, the paste replaced the paragraph - a heading's text, or another paragraph with
    its numbers typed in, under "bindings intact". It asks only whether the text an
    identifier is on reads as something else's; an identifier on text that is new is left to
    the split check, which refuses it beside the text that came back without one.
    """
    loose = Counter(_squashed(b.text) for b in returned if not b.table and not b.names and b.text)
    readings = Counter(_squashed(text) for text in rendered.values())
    found: set[str] = set()
    for name, now in texts.items():
        was = rendered[name]
        if _same(was, now) or not was.strip():
            continue
        own, here = _squashed(was), _squashed(now)
        if (loose[own] and not expected[own]) or (here and (readings[here] or expected[here])):
            found.add(name)
    return found


def _swallowed(name: str, was: str, now: str, rendered: dict[str, str]) -> str:
    """The whole of another paragraph, now inside this one and not before.

    A join that lost the second paragraph's bookmark, or a paragraph pasted into another,
    and not beside it: the paragraph came back holding the other's text, and merged, the
    other's text was in the source twice. Only a paragraph of five words or more, so that a
    short one ("None declared.") quoted in a rewording does not refuse it.
    """
    here, before = _squashed(now), _squashed(was)
    for other, text in rendered.items():
        whole = _squashed(text)
        if other != name and len(whole.split()) >= 5 and whole in here and whole not in before:
            return text
    return ""


def _unsettled(
    returned: list[Block], sections: dict, expected: Counter, suspects: set[str]
) -> set:
    """Sections whose paragraphs cannot be placed with certainty.

    One gained text the document as sent did not have - a split's second half, a paragraph
    typed there - or holds an identifier on text not its own. A move there was reordered
    among paragraphs import cannot see: a paragraph moved between the halves of a split went
    to after the whole of it. The sections either side of the new text count, since which of
    them it belongs to is not written anywhere.
    """
    found = {sections[name] for name in suspects if name in sections}
    unchanged = Counter(expected)
    for index, block in enumerate(returned):
        if block.table or block.names or not block.text:
            continue
        key = _squashed(block.text)
        if unchanged[key]:
            unchanged[key] -= 1
            continue
        for step in (-1, 1):
            i = index + step
            while 0 <= i < len(returned) and not (returned[i].names or returned[i].table):
                i += step
            if 0 <= i < len(returned):
                found.update(sections[n] for n in returned[i].names if n in sections)
    return found


def _kept_in_place(
    order: list[str], rendered: dict[str, str], sections: dict, unsettled: set
) -> list[str]:
    """The returned order, with the paragraphs of each unsettled section in their sent order:
    `apply_plan` sorts a section's slots by it, and those are not reordered."""
    sent = {name: i for i, name in enumerate(rendered)}
    held = [i for i, name in enumerate(order) if sections.get(name) in unsettled]
    out = list(order)
    for i, name in zip(held, sorted((order[i] for i in held), key=sent.__getitem__), strict=True):
        out[i] = name
    return out


#: Most of the words, in order: a judgement, used only to choose the words of a refusal.
_ALIKE = 0.6


def _alike(a: str, b: str) -> bool:
    return difflib.SequenceMatcher(a=a.split(), b=b.split(), autojunk=False).ratio() >= _ALIKE


def _displaced(
    gone: list[str], rendered: dict[str, str], reference: list[Block], returned: list[Block]
) -> dict[str, str]:
    """Paragraphs reported gone whose words came back elsewhere: moved where Word did not
    record the move, and then reworded, or reading like another paragraph as well.

    The text is new, with no identifier, or it sits on a paragraph whose identifier it does
    not resemble - the one a paste landed in front of, when nothing gave that one back. Not
    applied: nothing says which paragraph the text is, which is what the identifier is for.
    But not reported as a deletion either. That advice was to delete the paragraph in the
    .md, leaving Word's copy - numbers where the source has bindings - as the only one.
    A judgement, and it only chooses the words of a refusal. Returns each with the text it most
    resembles, for the author to port the rewording from.
    """
    expected = _unidentified(reference)
    elsewhere = [
        block.text
        for block in returned
        if not block.table
        and block.text
        and (
            not any(_alike(rendered[n], block.text) for n in block.names if n in rendered)
            if block.names
            else not expected[_squashed(block.text)]
        )
    ]
    found: dict[str, str] = {}
    for name in gone:
        words = rendered[name].split()
        scored = [
            (difflib.SequenceMatcher(a=words, b=text.split(), autojunk=False).ratio(), text)
            for text in elsewhere
        ]
        best = max(scored, default=(0.0, ""))
        if best[0] >= _ALIKE:
            found[name] = best[1]
    return found


def _beside_new_text(sent: list[Block], returned: list[Block]) -> set[str]:
    """Identifiers whose paragraph came back directly beside text the document did not have.

    A split leaves the second half as a paragraph with no identifier next to the first, and
    that is the only trace it leaves: the first half is merely a shorter paragraph. So any
    untagged paragraph whose text was not in the document as sent is new, and a tagged
    paragraph touching one - across nothing but empty paragraphs - may have been split. So
    may one touching a paragraph that arrived with Track Changes on, identifier or not.
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
            # A paragraph moved here, identifier and all, is no neighbour to vouch for: it
            # stood where the second half of a split had, and the split merged as the whole.
            if block.arrived and block.text:
                return True
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
    returned = _recovered(rendered, reference, returned)
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
    expected = _unidentified(reference)
    not_its_own = _not_its_own(rendered, texts, returned, expected)
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
        elif name in not_its_own:
            opening = _squashed(source)[:60]
            refused.append(Refusal(name, now or "", (_NOT_ITS_OWN.format(opening=opening),)))
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
        elif other := _swallowed(name, was, now, rendered):
            refused.append(Refusal(name, now, (_SWALLOWED.format(text=_squashed(other)[:60]),)))
        else:
            aligned = align(source, was, now)
            if aligned.rebuilt == source:
                # Only pandoc's typesetting was undone in Word - a no-break space it put after
                # "e.g." taken out again - and the next build puts it back. Nothing to merge.
                continue
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
    # A paragraph that came back inside another, and the one it is inside: which of the two
    # the order says moved is a tie the diff breaks either way.
    parts = {name: _pieces(reference, name) for name in in_parts}
    inside = _between_parts(returned, parts, expected)
    involved = set(inside).union(*inside.values())
    shifted = {entry[0] for entry in moved}
    misplaced += [n for n in rendered if n in shifted & involved and n not in misplaced]
    moved = [entry for entry in moved if entry[0] not in set(misplaced)]
    unsettled = _unsettled(returned, sections, expected, not_its_own)
    withheld = [entry[0] for entry in moved if sections[entry[0]] in unsettled]
    moved = [entry for entry in moved if entry[0] not in set(withheld)]
    order = _kept_in_place(order, rendered, sections, unsettled)
    displaced = _displaced(gone, rendered, reference, returned)
    return Plan(
        reached=frozenset(rendered),
        order=tuple(order),
        merged=merged,
        refused=tuple(refused),
        gone=tuple(name for name in gone if name not in displaced),
        displaced=tuple((name, displaced[name]) for name in gone if name in displaced),
        joined=tuple(joined),
        moved=tuple(moved),
        misplaced=tuple(misplaced),
        withheld=tuple(withheld),
        sections=sections,
    )


_SPLIT = (
    "it came back with a new paragraph beside it: split in two in Word, or new text written "
    "next to it. Merging it would replace the whole source paragraph with only part of it. "
    "Make the split or the addition in the .md. If the text shown is a paragraph moved "
    "from elsewhere, move that paragraph in the .md rather than retyping it."
)
_HIDDEN = (
    "text was typed where this paragraph renders nothing - an HTML comment, or markup that "
    "prints no text. Merging it would replace what is hidden there. Add the text in the .md; "
    "if it is a paragraph moved from elsewhere, move that paragraph rather than retyping it."
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
_NOT_ITS_OWN = (
    "the paragraph opening '{opening}' came back with its identifier on other text (shown): "
    "text pasted or typed in front of it took the identifier, and its own text came back "
    "without one, or the text shown reads exactly as another paragraph or a heading. Nothing "
    "is merged into it, and nothing in its section is reordered. Make the edits in the .md; "
    "if a paragraph was moved, move it there rather than retyping it."
)
_SWALLOWED = (
    "it came back holding the whole of another paragraph ('{text}'): joined to it, or "
    "pasted into it, in Word. Merging would put that paragraph's text in the source a second "
    "time. Make the edit in the .md."
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
    if aligned.touching:
        return (
            "the text between two of its numbers or citations was deleted, so they would "
            "touch: one could turn the other into a link, and the paragraph could not be "
            "lined up with its source again. Make the edit in the .md, keeping at least a "
            "space between them.",
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
