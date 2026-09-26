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
import re
from collections import Counter, deque
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.docxtext import Block, spaced
from manuscript_guard.roundtrip import Alignment, align, moves, only_definitions_between


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
    #: Identifier -> (file, section): the stretch between headings, tables, figures and
    #: paragraphs held in place that the paragraph belongs to, which is what a move is applied
    #: within.
    sections: dict[str, tuple[Path, int]] = field(default_factory=dict)
    #: The kind of each table, figure or equation of the document as sent that the returned
    #: one could not be matched with: deleted, pasted twice, or changed while others of its
    #: kind were added or removed. A move past one of them cannot be seen.
    lost: tuple[str, ...] = ()
    #: Headings, tables, figures and equations that came back in another place, as (kind,
    #: text): kind is "table", "figure", "equation", or "text" for a heading or caption. None
    #: of them moves in the .md.
    strayed: tuple[tuple[str, str], ...] = ()
    #: Text of paragraphs without an identifier - a heading, a list item, a quotation, a
    #: caption, a new paragraph - that the document did not have when it was sent.
    unidentified: tuple[str, ...] = ()
    #: Text of such paragraphs of the document as sent that did not come back as they were.
    vanished: tuple[str, ...] = ()
    #: Text of such paragraphs that all came back unchanged, but out of their order.
    reordered: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (
            self.merged
            or self.refused
            or self.gone
            or self.joined
            or self.moved
            or self.misplaced
            or self.lost
            or self.strayed
            or self.unidentified
            or self.vanished
            or self.reordered
        )


def _same(a: str, b: str) -> bool:
    """Word's text against Word's text, a no-break space compared as itself: split on every
    kind of space, a paragraph whose only change was one the co-author typed read as untouched,
    and the change was dropped with nothing reported."""
    return spaced(a).strip() == spaced(b).strip()


_NBSP = chr(0xA0)


#: A no-break space an author can write: the character itself, `\ `, or an entity, named or
#: numbered, which pandoc reads with any number of leading zeros.
_WRITTEN_NBSP = re.compile(r"\\ |&nbsp;|&NonBreakingSpace;|&#0*160;|&#[xX]0*[aA]0;|" + _NBSP)


def _typeset_only(was: str, now: str, source: str) -> bool:
    """Whether Word's text differs from the text sent only where a no-break space pandoc put
    in ("e.g." then a space) was taken out again. The next build puts it back, so there is
    nothing to merge. Decided by the rewording for an ordinary paragraph, it was never asked
    for a paragraph held in place, which refused the edit instead.

    Only a source with no no-break space of its own, and no binding or citation whose value
    could hold one, can have had one put in by pandoc. Asked of any source, the question
    dropped a co-author's change to a no-break space the author had written - "Hy's`\\ `law" -
    with "nothing came back", and one inside a binding's value.
    """
    if _WRITTEN_NBSP.search(source) or "{{" in source or "@" in source:
        return False
    was, now = spaced(was).strip(), spaced(now).strip()
    return len(was) == len(now) and all(
        a == b or (a == _NBSP and b == " ") for a, b in zip(was, now, strict=True)
    )


def _beside_new_text(
    sent: list[Block], returned: list[Block], counterparts: dict[int, int] | None = None
) -> set[str]:
    """Identifiers whose paragraph came back directly beside text the document did not have.

    A split leaves the second half as a paragraph with no identifier next to the first, and
    that is the only trace it leaves: the first half is merely a shorter paragraph. So any
    untagged paragraph whose text was not in the document as sent is new, and a tagged
    paragraph touching one - across nothing but empty paragraphs - may have been split.
    Compared by text rather than by position, because a move changes every neighbour and
    creates no text at all. An edited heading is new text too, which costs a refusal of the
    paragraph beside it when both were edited; the alternative is a split that truncates.

    A table, figure or equation the document as sent did not have is new too. The search
    stopped at any block that was not prose, so a paragraph split around a pasted picture or
    a new equation was merged as its first half.
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
            if block.table:
                if counterparts is None or i not in counterparts:
                    return counterparts is not None
                # One that was there before is looked past, as an empty line is: an equation
                # moved in between the halves of a split paragraph hid the second half.
                continue
            if block.names:
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


#: A line that opens or closes something Word shows apart from the paragraph above it: a
#: `:::` or code fence, an HTML block tag, a LaTeX environment, a definition, or the
#: underline that makes the line above it a heading. Written directly under a paragraph, with
#: no blank line between, it is part of that paragraph's source but not of its Word text.
_BLOCK_LINE = re.compile(
    r"^[ \t]*(?::::|```|~~~|\\(?:begin|end)\s*\{"
    r"|</?(?:address|article|aside|blockquote|center|details|div|dl|fieldset|figure|footer"
    r"|form|h[1-6]|header|hr|nav|ol|p|pre|section|table|ul)\b)"
    r"|^[ \t]{0,3}[:~][ \t]"
    r"|^[ \t]{0,3}(?:=+|-+)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


#: What `_bare` sets aside: a backslash escape, a code span, by pandoc's rule that a run of
#: backticks is closed by a run of the same length, and a comment that closes. Nothing more.
#: Each escape is taken as a pair, so `\`` opens nothing and `\\` before a backtick leaves it
#: free to open a span. Taken for an opener, an escaped backtick began a "code span" that ran
#: to the next real one and swallowed the `$$` or the `<!--` between them; refused after any
#: backslash, the backtick after `\\` did the same from the other end. Nor may the raw text
#: before an opener stop it: a backtick there was either an escaped one, as in \``x`, or one
#: of a run that never closes, whose last backtick pandoc opens a span on, as in ``a'' `b.
#: Refused, the span's closer was taken for an opener and swallowed what followed.
_CODE_OR_COMMENT = re.compile(r"\\.|(`+)(?!`).+?(?<!`)\1(?!`)|<!--.*?-->", re.DOTALL)
_DISPLAY_MATHS = re.compile(r"(?<!\\)\$\$")


def _bare(para: str) -> tuple[str, bool]:
    """A paragraph's source with its code spans and closed comments blanked out, and whether
    what is left holds display maths, which Word sets apart as a paragraph of its own.

    Searched for as written, `$$` or `<!--` inside backticks held a paragraph that explained
    them. The rewording's own scan of inline markup was tried next, and it sets aside more
    than it should for this: taking `` `glmer` from $$..$$ `nlme`{.r} `` for one code span
    with attributes, or `~~ $$x$$ ~~` for struck-through text, it hid display maths, and a
    paragraph that was not held had its first part moved without its equation. Setting
    aside too little only holds a paragraph that could have moved - `$$` in a footnote does.
    """
    bare = _CODE_OR_COMMENT.sub(lambda match: " " * len(match.group(0)), para)
    return bare, _DISPLAY_MATHS.search(bare) is not None


def _held_in_place(
    known: dict, rendered: dict[str, str], in_parts: Collection[str] = ()
) -> dict[str, str]:
    """Paragraphs of source whose slot no move may refill, each with why.

    A move rewrites slots, and a slot is only safe to refill when what it holds is the
    paragraph Word showed, all of it and nothing more. An HTML comment with a blank line in
    it is two paragraphs of source: the first reaches Word as an empty line, and the second
    does not reach it at all. As a slot, the first half moved and the second stayed, so a
    paragraph dragged below the empty line was written inside the comment and vanished from
    the build. These are held where they are:

    - `hidden`: it never reached Word, because something opened before it holds it.
    - `runs-on`: it opens that something, or a comment it does not close. Moved, the
      opening went and the close stayed.
    - `empty`: it reaches Word as an empty line, like a comment's first line.
    - `glued`: a line opening or closing a block follows it with no blank line between,
      and went with it.
    - `in-parts`: Word shows it as more than one paragraph, and only the first moved. Found
      by untagged text before the next paragraph of its section, which misses the last
      paragraph of a section, and by display maths in its source, which does not.

    Each is a section of its own, so a move is never applied across one.
    """
    found: dict[str, str] = {}
    texts: dict[Path, str] = {}
    before: dict[Path, tuple[str, int]] = {}
    for name, (path, para, start) in sorted(
        known.items(), key=lambda item: (str(item[1][0]), item[1][2])
    ):
        if path not in texts:
            texts[path] = path.read_text(encoding="utf-8")
        if name not in rendered:
            found[name] = "hidden"
            if path in before and not texts[path][before[path][1] : start].strip():
                found.setdefault(before[path][0], "runs-on")
        elif not rendered[name].strip():
            found[name] = "empty"
        elif "<!--" in (bare := _bare(para))[0]:
            # Found by what it opens, not by what follows it: whatever the comment holds
            # after the blank line - a heading, a fence - comes before any tagged paragraph.
            # A closed comment is blanked out of `bare`, so an opening left in it is unclosed.
            found[name] = "runs-on"
        elif _BLOCK_LINE.search(para):
            found[name] = "glued"
        elif name in in_parts or bare[1]:
            found[name] = "in-parts"
        before[path] = (name, start + len(para))
    return found


def _text_counterparts(reference: list[Block], returned: list[Block]) -> dict[int, int]:
    """Which heading or caption of the document as sent each returned one is, by index.

    Matched as a sequence, so that of two headings reading "Outcome" each is paired with its
    own. Matched one text at a time, first come first served, renaming or deleting the first
    made the second stand in for it, and the second was reported as moved. A text of which the
    sequence leaves exactly one copy over on each side is paired too, which is how a heading
    dragged elsewhere is still recognised.
    """

    def texts(blocks: list[Block]) -> list[tuple[int, str]]:
        return [(i, b.text) for i, b in enumerate(blocks) if not b.names and not b.table and b.text]

    sent, back = texts(reference), texts(returned)
    matcher = difflib.SequenceMatcher(
        a=[text for _i, text in sent], b=[text for _j, text in back], autojunk=False
    )
    found = {
        back[b + k][0]: sent[a + k][0]
        for a, b, size in matcher.get_matching_blocks()
        for k in range(size)
    }
    taken = set(found.values())
    left_sent: dict[str, list[int]] = {}
    for i, text in sent:
        if i not in taken:
            left_sent.setdefault(text, []).append(i)
    left_back: dict[str, list[int]] = {}
    for j, text in back:
        if j not in found:
            left_back.setdefault(text, []).append(j)
    # One copy left over on each side is the same heading, wherever it now is. Paired only
    # when its text was unique in the whole document, a dragged "Outcome" with another
    # "Outcome" elsewhere in the paper was paired with nothing, and the drag went unreported.
    for text, js in left_back.items():
        if len(js) == 1 and len(left_sent.get(text, ())) == 1:
            found[js[0]] = left_sent[text][0]
    return found


def _sections(known: dict, held: Collection[str] = ()) -> dict[str, tuple[Path, int]]:
    """Which section of its file each paragraph is in: how many headings, tables or figures
    come before it there, or paragraphs held in place, each of which is a section of its own.

    Import fills paragraph slots, and a heading is not a slot: it cannot change how many
    paragraphs a section holds. It used to fill slots per file, so a paragraph moved from the
    Discussion to the Introduction pushed one paragraph out of every section in between. A
    section is therefore the unit a move is applied within.

    A link or footnote definition between two paragraphs is no boundary. It renders nothing
    in the body, and pandoc reads it wherever it stands; counted as untagged text, it made a
    move across it a move into another section, refused as one past a heading, a table or a
    figure. The paragraphs change places around it, and it stays where it was written.
    """
    out: dict[str, tuple[Path, int]] = {}
    texts: dict[Path, str] = {}
    section: dict[Path, int] = {}
    end: dict[Path, int] = {}
    alone: dict[Path, bool] = {}
    for name, (path, para, start) in sorted(
        known.items(), key=lambda item: (str(item[1][0]), item[1][2])
    ):
        if path not in texts:
            texts[path] = path.read_text(encoding="utf-8")
            section[path] = 0
        elif (
            name in held
            or alone[path]
            or not only_definitions_between(texts[path][end[path] : start])
        ):
            section[path] += 1
        out[name] = (path, section[path])
        end[path] = start + len(para)
        alone[path] = name in held
    return out


def _counterparts(
    reference: list[Block], returned: list[Block], texts: dict[int, int] | None = None
) -> tuple[dict[int, int], tuple[str, ...]]:
    """Which table or figure of the document as sent each returned one is, by index, and
    the kinds of those sent that could not be found.

    By what it holds first, where that is unique on both sides: a table by its text, a figure
    by its picture. Word renumbers the relationship a picture hangs on and renames its file
    when it saves, so neither says which figure it is; the picture's bytes do. What is left is
    paired by place: by position among its kind within the stretch between the same two
    headings, captions or matched tables and figures, when that stretch holds as many of the
    kind in both documents. A table with a corrected cell, or a picture Word stored anew, is
    the one in that place. Tables and figures used to be paired by position alone, both kinds
    together, and only while their total was unchanged: a co-author who deleted one table or
    pasted in one picture turned every one of them off, and a paragraph dragged past a figure
    went unseen. Paired by position within their kind anywhere in the document, a table
    deleted from the Results and another pasted into the Funding were taken for one table.
    """
    def ident(block: Block) -> tuple[str, str]:
        return block.kind, block.key

    sent = [i for i, block in enumerate(reference) if block.table]
    back = [j for j, block in enumerate(returned) if block.table]
    in_sent = Counter(ident(reference[i]) for i in sent)
    in_back = Counter(ident(returned[j]) for j in back)
    where = {ident(reference[i]): i for i in sent}
    found = {
        j: where[ident(returned[j])]
        for j in back
        if returned[j].key and in_sent[ident(returned[j])] == in_back[ident(returned[j])] == 1
    }

    if texts is None:
        texts = _text_counterparts(reference, returned)

    def stretches(
        blocks: list[Block], matched: dict[int, int], marks: dict[int, int]
    ) -> dict[tuple, list[int]]:
        """The unmatched tables and figures, grouped by kind and by the last heading,
        caption or matched table or figure before them."""
        out: dict[tuple, list[int]] = {}
        last: tuple | None = None
        for index, block in enumerate(blocks):
            if block.table and index in matched:
                last = ("block", matched[index])
            elif block.table:
                out.setdefault((last, block.kind), []).append(index)
            elif index in marks:
                last = ("text", marks[index])
        return out

    left = stretches(reference, {i: i for i in found.values()}, {i: i for i in texts.values()})
    right = stretches(returned, found, texts)
    lost: list[str] = []
    for (stretch, kind), indices in left.items():
        there = right.get((stretch, kind), [])
        if len(there) == len(indices):
            found.update(zip(there, indices, strict=True))
        else:
            lost += [kind] * len(indices)
    return found, tuple(lost)


def _boundaries(reference: list[Block], rank) -> dict[tuple, deque]:
    """The headings, tables and figures of the document as sent, each ranked as the opening
    of the section after it, keyed by their index in the document as sent.

    Only what stands between two sections counts. Pandoc can render an untagged paragraph
    inside a section - display maths, say - and ranked as a boundary it would make every
    untouched document look as if a paragraph had crossed it. Those between the same two
    sections are ranked in their order, so a figure dragged past the heading after it is seen.
    """
    found: dict[tuple, deque] = {}
    pending: list[tuple] = []
    previous: tuple | None = None
    for index, block in enumerate(reference):
        if block.names and not block.table:
            here = rank(block.names[0])
            if previous is None or previous[:2] != here[:2]:
                for place, key in enumerate(pending):
                    found.setdefault(key, deque()).append((*here[:2], 0, place))
            pending, previous = [], here
        elif block.table:
            pending.append(("block", index))
        elif block.text:
            pending.append(("text", index))
    for place, key in enumerate(pending):
        found.setdefault(key, deque()).append((float("inf"), place))
    return found


def _misplaced(
    reference: list[Block],
    returned: list[Block],
    order: list[str],
    moved: set[str],
    rank,
    held: Collection[str] = (),
    counterparts: dict[int, int] | None = None,
    texts: dict[int, int] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Paragraphs that came back outside their own section or file, and the headings, tables
    and figures that came back somewhere else.

    Every paragraph is judged, not only those the order diff calls moved: a paragraph dragged
    from the end of one section to just below the next heading keeps its place among the
    paragraphs, so the diff saw nothing and the move was dropped with "nothing came back".
    The largest set whose sections read in order is kept, and whatever falls outside it is out
    of place. The headings, tables and figures as sent outweigh everything else together. A
    paragraph held in place outweighs one other paragraph but not two, so a paragraph dragged
    past it is the one named, and so is a held paragraph dragged past several; weighed above
    all of them together, it had the four paragraphs it passed reported instead. The order
    diff only breaks ties, so the paragraph that crossed a heading is named rather than a
    neighbour the diff happened to prefer.

    Whatever falls outside is named. A paragraph held in place took part as an anonymous
    anchor once, and dragged past a heading it was dropped without a word; a table dragged
    into another section was the anchor dropped, and said "nothing came back".
    """
    boundaries = _boundaries(reference, rank)
    if texts is None:
        texts = _text_counterparts(reference, returned)
    if counterparts is None:
        counterparts = _counterparts(reference, returned, texts)[0]
    ordered = set(order)
    # (what, rank, tier): a boundary is ("table" | "figure" | "text", its text), tier 2; a
    # paragraph is its identifier, tier 1 if held in place and 0 otherwise.
    sequence: list[tuple[str | tuple[str, str], tuple, int]] = []
    for index, block in enumerate(returned):
        if block.table:
            key = ("block", counterparts.get(index))
            if boundaries.get(key):
                sequence.append(((block.kind, ""), boundaries[key].popleft(), 2))
        elif block.names:
            sequence += [
                (name, rank(name), 1 if name in held else 0)
                for name in block.names
                if name in ordered
            ]
        elif block.text and boundaries.get(key := ("text", texts.get(index))):
            sequence.append((("text", block.text), boundaries[key].popleft(), 2))

    # The heaviest subsequence whose ranks never decrease. A paragraph weighs 3 if the diff
    # called it moved and 4 otherwise, a held one 5, and a boundary more than all of them:
    # any one paragraph is lighter than a held one, and any two are heavier. At 3 against 1
    # and 2, and then 5 against 2 and 4, a held paragraph dragged past two paragraphs the diff
    # called moved outweighed them, and the two were named instead of it.
    tiers = {0: 0, 1: 5, 2: 5 * len(sequence) + 1}
    weight = [
        tiers[tier] or (3 if what in moved else 4) for what, _rank, tier in sequence
    ]
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
    dropped = [what for i, (what, _rank, _tier) in enumerate(sequence) if i not in kept]
    return (
        [what for what in dropped if isinstance(what, str)],
        [what for what in dropped if isinstance(what, tuple)],
    )


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
    for index, block in enumerate(reference):
        if block.names and not block.table:
            name = block.names[0]
            if last and between and sections.get(last, 0) == sections.get(name, 1):
                found.add(last)
            last, between = name, False
            # An equation directly after it is its own, wherever the paragraph stands: the
            # document as sent says so, where reading the source for `$$` can be fooled.
            following = reference[index + 1] if index + 1 < len(reference) else None
            if block.text and following is not None and following.kind == "equation":
                found.add(name)
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


def plan_import(
    known: dict,
    reference: list[Block],
    returned: list[Block],
    marked: list[Block] | None = None,
    abbreviations: frozenset[str] = frozenset(),
) -> Plan:
    """Compare the document as sent with the document as returned, paragraph by paragraph.

    `marked` is the same document built with each binding and citation bookmarked, which is
    where `align` learns each token's extent. It is trusted only for a paragraph that reads
    exactly as it does in `reference`: if marking changed a rendering, that paragraph is
    refused rather than aligned on extents that describe different text. Exactly but for
    pandoc's no-break space, which it puts after "et al." before a bookmark and not before a
    citation: one character for one, so the extents still fit, and every edit to "Smith et
    al. [@key]" was refused without it.

    `abbreviations` are the words pandoc puts that no-break space after, from
    `build.document.abbreviations`: a rewording writes it back as the space pandoc makes one
    of again, rather than into the source as a character nobody can see.
    """
    rendered = {b.names[0]: b.text for b in reference if b.names and not b.table}

    def fits(text: str, name: str) -> bool:
        sent = rendered.get(name)
        return sent is not None and sent.replace("\u00a0", " ") == text.replace("\u00a0", " ")

    extents = {
        b.names[0]: b.tokens
        for b in marked or ()
        if b.names and not b.table and fits(b.text, b.names[0])
    }
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

    # Whether a paragraph reaches Word in parts is judged within the sections the source
    # has, before paragraphs held in place split them further: one held after it hid the
    # split, and a rewording of the first part deleted the rest.
    in_parts = _in_parts(reference, _sections(known))
    held = _held_in_place(known, rendered, in_parts)
    sections = _sections(known, held)
    headings = _text_counterparts(reference, returned)
    counterparts, lost = _counterparts(reference, returned, headings)
    beside_new = _beside_new_text(reference, returned, counterparts)
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
        elif _same(was, now) or (
            # Only the part that carries the identifier is compared here. With new text
            # beside it - the part after an equation reworded - skipping it lost that edit.
            name in held and name not in beside_new and _typeset_only(was, now, source)
        ):
            continue
        elif not was.strip():
            refused.append(Refusal(name, now, (_HIDDEN,)))
        elif held.get(name) == "runs-on":
            refused.append(Refusal(name, now, (_RUNS_ON,)))
        elif held.get(name) == "glued":
            refused.append(Refusal(name, now, (_GLUED,)))
        elif name in in_parts or held.get(name) == "in-parts":
            refused.append(Refusal(name, now, (_IN_PARTS,)))
        elif took := _took_in(name, now, was, reference, missing):
            refused.append(Refusal(name, now, (_TOOK_IN.format(text=took[:60]),)))
        elif name in beside_new:
            refused.append(Refusal(name, now, (_SPLIT,)))
        else:
            aligned = align(source, was, now, extents.get(name), abbreviations)
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

    diffed = moves([n for n in rendered if n in set(order)], order)
    misplaced, strayed = _misplaced(
        reference, returned, order, {m[0] for m in diffed}, rank, held, counterparts, headings
    )
    # What moved among the paragraphs that will be reordered. Taken from the diff above, a
    # paragraph passed by a misplaced one was reported as reordered, and nothing was written.
    stays = {*misplaced, *held}
    kept = [n for n in order if n not in stays]
    moved = moves([n for n in rendered if n in set(kept)], kept)

    # A paragraph without an identifier is never compared, and it is also what bounds a
    # section: once a quotation or a list item was reworded it no longer marked where its
    # section began, a paragraph moved past it read as in order, and import said the
    # document matched the manuscript. What changed is at least said.
    # In order, not as a bag: list items swapped in Word were all still there, and the
    # document was said to match.
    sent_untagged = [b.text for b in reference if not b.names and not b.table and b.text]
    back_untagged = [b.text for b in returned if not b.names and not b.table and b.text]
    unchanged = Counter(sent_untagged)
    unidentified: list[str] = []
    for text in back_untagged:
        if unchanged[text]:
            unchanged[text] -= 1
        else:
            unidentified.append(text)
    left = Counter(missing)
    vanished: list[str] = []
    for text in sent_untagged:
        if left[text]:
            left[text] -= 1
            vanished.append(text)
    reordered: list[str] = []
    if not (unidentified or vanished) and sent_untagged != back_untagged:
        matcher = difflib.SequenceMatcher(a=sent_untagged, b=back_untagged, autojunk=False)
        for kind, _a1, _a2, b1, b2 in matcher.get_opcodes():
            if kind != "equal":
                reordered.extend(back_untagged[b1:b2])
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
        lost=lost,
        strayed=tuple(strayed),
        unidentified=tuple(unidentified),
        vanished=tuple(vanished),
        reordered=tuple(reordered),
    )


_SPLIT = (
    "it came back with a new paragraph beside it: split in two in Word, new text written "
    "next to it, or a heading, list item or quotation beside it reworded. Merging a split "
    "would replace the whole source paragraph with only part of it. Make the edit in the .md."
)
_HIDDEN = (
    "text was typed where this paragraph renders nothing - a spacer such as `&nbsp;`, or "
    "markup that prints no text. Merging it would replace what is there. Add the text in "
    "the .md."
)
_RUNS_ON = (
    "it opens an HTML comment with `<!--` in the .md, which can hide what follows it, so it "
    "is held where it is. Make the edit in the .md."
)
_GLUED = (
    "in the .md a line that opens or closes a block, or looks as if it does, follows it with "
    "no blank line between - a `:::` or code fence, `\\end{table}`, a line starting `: ` - "
    "so it is held where it is rather than merged with that line. Make the edit in the .md; "
    "a blank line before that line frees the paragraph on the next build."
)
_IN_PARTS = (
    "display maths follows it directly in the .md, or Word shows it as more than one "
    "paragraph, so it is held where it is: merged, its first part could replace the whole. "
    "Make the edit in the .md."
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
    if aligned.touching:
        return (
            "the text between two of its numbers or citations was deleted, so they would "
            "touch: one could turn the other into a link, and the paragraph could not be "
            "lined up with its source again. Make the edit in the .md, keeping at least a "
            "space between them.",
        )
    if aligned.alone:
        return (
            f"everything but {aligned.alone} was deleted, and a paragraph that is nothing but "
            "a table, a figure or a misspelt placeholder gets no identifier at the next "
            "build: a later edit to it in Word could not come back. Make the edit in the .md.",
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
        "its numbers, citations and markup could not be told apart from its prose, or its "
        "numbers and citations from each other where two touch. Make the edit in the .md.",
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
