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
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.docxtext import Block, spaced
from manuscript_guard.roundtrip import (
    Alignment,
    align,
    marked_blocks,
    moves,
    only_definitions_between,
)


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
    #: The text the document as sent did not have that held them.
    held_by: tuple[str, ...] = ()
    #: Identifier -> (file, section): the stretch between headings, tables, figures and
    #: paragraphs held in place that the paragraph belongs to, which is what a move is applied
    #: within.
    sections: dict[str, tuple[Path, int]] = field(default_factory=dict)
    #: The kind of each table, figure or equation of the document as sent that the returned
    #: one could not be matched with: deleted, pasted twice, or changed while others of its
    #: kind were added or removed. A move past one of them cannot be seen.
    lost: tuple[str, ...] = ()
    #: Headings, tables, figures and equations that came back in another place, as (kind,
    #: text): kind is "table", "figure", "equation", or "text" for a heading, caption, list
    #: item, quotation or any other paragraph without an identifier, whose text is as
    #: `reordered` lists it, with what in it has no text named. None of them moves in the .md.
    strayed: tuple[tuple[str, str], ...] = ()
    #: Text of paragraphs without an identifier - a heading, a list item, a quotation, a
    #: caption, a new paragraph - that the document did not have when it was sent.
    unidentified: tuple[str, ...] = ()
    #: Text of such paragraphs of the document as sent that did not come back as they were.
    vanished: tuple[str, ...] = ()
    #: Text of such paragraphs that all came back unchanged, but out of their order.
    reordered: tuple[str, ...] = ()
    #: Kept in their own slots: a section in which the moves would leave a paragraph where
    #: the next build does not find it again (see `_identified`).
    held: frozenset[str] = frozenset()
    #: (moved paragraph, the paragraph its section's moves would have left without an
    #: identifier): moves not applied for that reason.
    held_back: tuple[tuple[str, str], ...] = ()

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
            or self.lost
            or self.strayed
            or self.unidentified
            or self.vanished
            or self.reordered
            or self.held_back
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


def _squashed(text: str) -> str:
    return spaced(text).strip()


def _untagged_counts(reference: list[Block]) -> Counter:
    """What the document as sent held without an identifier - headings, captions - by text."""
    return Counter(_squashed(b.text) for b in reference if not b.names and not b.table and b.text)


def _untagged_missing(reference: list[Block], returned: list[Block]) -> Counter:
    """Text without an identifier that the document as sent held and the returned one does
    not - a heading, a caption - by text, as many times as it went."""
    untagged = Counter(b.text for b in reference if not b.names and not b.table and b.text)
    untagged.subtract(b.text for b in returned if not b.names and not b.table and b.text)
    return +untagged


def _off_headings(
    rendered: dict[str, str], reference: list[Block], returned: list[Block], expected: Counter
) -> list[Block]:
    """Identifiers taken off a heading, caption or reference entry they slid onto.

    Deleted or cut without Track Changes, the last paragraph of a section leaves its
    identifier on the heading after it - above a table, on its caption; after the last
    paragraph of all, on the first entry of the reference list. Read as the paragraph's text,
    the heading was merged into it: "Methods", bindings intact. Recognised by its text alone,
    a heading retitled in the same round was merged too - "Study design" - so it is
    recognised by its style as well, and an identifier on it names a paragraph that is no
    longer there.

    Unless the block is plainly that paragraph, and reported deleted it would invite deleting
    it: one restyled as a heading in Word, its words mostly its own; one the heading before it
    was joined into, which keeps the heading's style and is refused as a join; or one sent
    with the role it has, such as a note the source styles as a caption. The join is read as
    `_took_in` reads it, by the heading gone from before the paragraph and its text turned up
    here: whether the paragraph's own text survived whole did not say, since a paragraph
    reworded in the same round - or made the heading's run-in text - was reported deleted.
    Only the heading before: one after it, retitled around its old title, is the heading an
    identifier slid onto.

    Which headings are gone is read as `plan_import` reads it, after the identifiers taken off
    by exact text. Read before, a heading that still stood but carried an identifier slid onto
    it counted as gone, a join into the paragraph after it was read, and the next heading,
    retitled to take in its words ("Funding and competing interests"), merged into the slot
    of the paragraph deleted under it.
    """
    sent_roles = {b.names[0]: b.role for b in reference if b.names and not b.table}

    def by_text(block: Block) -> bool:
        # It reads exactly as a heading or caption the document was sent with, and not as
        # its own paragraph.
        text = _squashed(block.text)
        return (
            bool(block.names)
            and not block.table
            and bool(expected[text])
            and not any(_squashed(rendered.get(name, "")) == text for name in block.names)
        )

    missing = _untagged_missing(
        reference, [replace(b, names=()) if by_text(b) else b for b in returned]
    )
    out = []
    for block in returned:
        text = _squashed(block.text)
        own = [rendered.get(name, "") for name in block.names]
        joined = any(
            name in rendered
            and _took_in(name, block.text, rendered[name], reference, missing, steps=(-1,))
            for name in block.names
        )
        restyled = joined or any(was.strip() and _alike(was, block.text) for was in own)
        sent_so = any(sent_roles.get(name, "") == block.role for name in block.names)
        if by_text(block) or (
            block.names
            and not block.table
            and block.role
            and not restyled
            and not sent_so
            and not any(_squashed(was) == text for was in own)
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

    The same exact reading gives back a paragraph cut and pasted just below the line its
    identifier slid onto, which is where Word shows it.

    Not from text: a paste or a new paragraph typed there reads the same way as a paragraph
    rewritten with a copy of its old text pasted after it, and a first version that gave
    identifiers back from pasted text was beaten three times in review. Those are refused.
    """
    out = list(returned)
    for index, block in enumerate(out):
        # A line holding a symbol with no text is not empty: something was typed there.
        if block.table or not block.names or block.text or block.unread:
            continue
        after = index + 1
        while after < len(out) and not (
            out[after].table or out[after].names or out[after].text or out[after].unread
        ):
            after += 1
        if after == len(out) or out[after].table or out[after].names:
            continue
        text = _squashed(out[after].text)
        theirs = [n for n in block.names if n in rendered and _squashed(rendered[n]) == text]
        # Not to a line with no text: one holding only a symbol read as the empty line a
        # `&nbsp;` spacer renders as, and took that spacer's identifier.
        if not text or len(theirs) != 1 or expected[text]:
            continue
        # Only the one it matched: another identifier on the line - a `&nbsp;` spacer's, say -
        # is that line's, and taken with it was reported deleted.
        out[after] = replace(out[after], names=(theirs[0],))
        out[index] = replace(block, names=tuple(n for n in block.names if n != theirs[0]))
    return out


def _recovered(
    rendered: dict[str, str], reference: list[Block], returned: list[Block]
) -> list[Block]:
    """The returned document with identifiers put back where only exact text can say.
    `docxtext` has already put them back where the tracked changes say."""
    expected = _untagged_counts(reference)
    off = _off_headings(rendered, reference, returned, expected)
    return _given_back(rendered, off, expected)


def _took_vanished(was: str, now: str, rendered: dict[str, str], vanished: list[str]) -> str:
    """The text of a paragraph gone from its place, most of it now added to this one.

    Pasted onto the end of a paragraph elsewhere, with a word typed to join them, a paragraph
    has no identifier of its own left and does not read exactly as anything. The paragraph it
    joined merged holding it, and it was then in the source twice. A judgement - most of its
    words, in order, among the words this paragraph gained - and it only refuses.
    """
    before, after = was.split(), now.split()
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    gained = [
        word
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes()
        if tag in ("insert", "replace")
        for word in after[j1:j2]
    ]
    for name in vanished if gained else ():
        words = rendered[name].split()
        shared = difflib.SequenceMatcher(a=words, b=gained, autojunk=False).get_matching_blocks()
        if words and sum(block.size for block in shared) >= _ALIKE * len(words):
            return rendered[name]
    return ""


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
    returned: list[Block],
    sections: dict,
    shown: Counter,
    suspects: set[str],
    misplaced: set[str],
) -> tuple[set, list[tuple[str, frozenset]]]:
    """Sections whose paragraphs cannot be placed with certainty.

    One gained text the document as sent did not have - a split's second half, a paragraph
    typed there - or holds an identifier on text not its own. A move there was reordered
    among paragraphs import cannot see: a paragraph moved between the halves of a split went
    to after the whole of it. The sections either side of the new text count, since which of
    them it belongs to is not written anywhere; and a paragraph moved in from another
    section standing beside the new text says nothing about which section that is, so the
    search goes past it, to the first paragraph that is where it belongs. Returns the
    sections, and each new text with the sections it unsettled, for the report: quoted for a
    move in another section, it pointed the author at the wrong place.

    Text is compared as `_listed` shows it, against `shown`, the document as sent shown the
    same way: by its text alone, a heading that gained a symbol with no text read as
    unchanged, and the moves beside it were applied.
    """
    found = {sections[name] for name in suspects if name in sections}
    because: list[tuple[str, frozenset]] = []
    unchanged = Counter(shown)
    for index, block in enumerate(returned):
        if block.table or block.names or not (block.text or block.unread):
            continue
        key = _squashed(_listed(block))
        if unchanged[key]:
            unchanged[key] -= 1
            continue
        these: set = set()
        for step in (-1, 1):
            i = index + step
            passed = False
            while 0 <= i < len(returned) and returned[i].kind not in ("table", "figure"):
                here = returned[i]
                # Once past a paragraph moved in, a heading or caption as it was sent ends
                # the search: the one moved in stood at the edge of its own section, and the
                # search went on into the next and held a clear move there. Not text that
                # arrived itself - a list item moved in beside a split's second half.
                if (
                    passed
                    and not here.names
                    and not here.arrived
                    and shown[_squashed(_listed(here))]
                ):
                    break
                names = [n for n in here.names if n in sections]
                these.update(sections[n] for n in names)
                # Past a paragraph moved in, named misplaced or not: across a boundary Word
                # does not show - an HTML comment - one moved in is not named, and it hid the
                # section of a split's new half beside it.
                if names and not set(names) <= misplaced and not here.arrived:
                    break
                passed = passed or (here.arrived and bool(names))
                i += step
        found |= these
        because.append((_listed(block), frozenset(these)))
    return found, because


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


#: Most of the words, in order: a judgement. It chooses the words of a refusal, and one more
#: thing: whether a paragraph restyled as a heading or caption keeps its identifier, and so
#: whether its rewording can merge (see `_off_headings`).
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
    expected = _untagged_counts(reference)
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


def _beside_new_text(
    sent: list[Block], returned: list[Block], counterparts: dict[int, int] | None = None
) -> set[str]:
    """Identifiers whose paragraph came back directly beside text the document did not have.

    A split leaves the second half as a paragraph with no identifier next to the first, and
    that is the only trace it leaves: the first half is merely a shorter paragraph. So any
    untagged paragraph whose text was not in the document as sent is new, and a tagged
    paragraph touching one - across nothing but empty paragraphs - may have been split. So
    may one touching a paragraph that arrived with Track Changes on, identifier or not.
    Compared by text rather than by position, because a move changes every neighbour and
    creates no text at all. An edited heading is new text too, which costs a refusal of the
    paragraph beside it when both were edited; the alternative is a split that truncates. A
    paragraph holding only a symbol with no text is new text as well: skipped as empty, the
    rewording beside it merged and the symbol was dropped.

    A table, figure or equation the document as sent did not have is new too. The search
    stopped at any block that was not prose, so a paragraph split around a pasted picture or
    a new equation was merged as its first half.
    """

    def content(block: Block) -> tuple[str, tuple[str, ...]]:
        return block.text, block.unread

    unchanged = Counter(content(b) for b in sent if not b.table and not b.names and any(content(b)))
    # Paragraphs sent with no text: a `&nbsp;` or `<br>` spacer, or any line whose identifier
    # is on something that is not text, such as maths alone. Nothing was split around one.
    spacers = {n for b in sent if b.names and not b.table and not any(content(b)) for n in b.names}
    new: set[int] = set()
    for index, block in enumerate(returned):
        if block.table or block.names or not any(content(block)):
            continue
        if unchanged[content(block)]:
            unchanged[content(block)] -= 1
        else:
            new.add(index)

    def touches(indices: range) -> bool:
        for i in indices:
            block = returned[i]
            # A paragraph moved here, identifier and all, is no neighbour to vouch for: it
            # stood where the second half of a split had, and the split merged as the whole.
            # Whatever it still holds: its moved text deleted, or replaced by a symbol with no
            # text, it was looked past as an empty line, and vouched for the split again.
            # One that holds nothing and names only paragraphs sent empty - a spacer - is an
            # empty line wherever it came from, and is looked past as one: Enter pressed on a
            # spacer reads as arrived, and as a paragraph that vouches for nothing it had the
            # rewording beside it refused; as a neighbour, a spacer moved in with the paragraph
            # under it vouched for the split whose halves it stood between.
            if block.arrived and not any(content(block)) and set(block.names) <= spacers:
                continue
            if block.arrived and (any(content(block)) or block.names):
                return True
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
            if any(content(block)):
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
            if here is None:
                continue
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
            # As the untagged texts are listed, so that the report folds it in with them: by
            # its text alone, a heading holding a symbol with no text was named twice.
            sequence.append((("text", _listed(block)), boundaries[key].popleft(), 2))

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

    An equation directly after a paragraph was taken for part of it too, wherever the
    paragraph stood. No paragraph with `$$` in it carries an identifier any more, so that
    rule only ever found an equation standing on its own, or a list item or quotation holding
    only maths, which Word also shows as an equation, and held the paragraph above it for
    nothing.
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


def _took_in(
    name: str,
    now: str,
    was: str,
    reference: list[Block],
    missing: Counter,
    steps: tuple[int, ...] = (-1, 1),
) -> str:
    """The heading or caption beside this paragraph that it absorbed, if it absorbed one.

    Delete at the end of a heading makes a run-in heading: one paragraph, carrying the
    paragraph's identifier, reading "MethodsWe analysed...". It merged as prose, and the
    heading stayed in the file above it. The heading has no identifier to be joined by, so
    it is recognised by having vanished while its text turned up in its neighbour - counted,
    not merely found, because a paragraph often opens by naming its heading ("Statistical
    analysis used..."), and requiring the text to be new let that join through as
    "Statistical analysisStatistical analysis used...".
    """
    squashed_now, squashed_was = " ".join(now.split()), " ".join(was.split())
    for block in _headings_beside(name, reference, steps):
        text = " ".join(block.text.split())
        if missing[block.text] and squashed_now.count(text) > squashed_was.count(text):
            return block.text
    return ""


def _headings_beside(
    name: str, reference: list[Block], steps: tuple[int, ...] = (-1, 1)
) -> list[Block]:
    """The blocks without an identifier directly above and below this paragraph - only
    above, with `steps` of (-1,) - past empty ones: a heading, a caption, anything a
    run-in could take. A paragraph or a table there takes nothing in."""
    at = next(i for i, b in enumerate(reference) if b.names and b.names[0] == name)
    found = []
    for step in steps:
        i = at + step
        while 0 <= i < len(reference) and not (
            reference[i].names or reference[i].table or reference[i].text
        ):
            i += step
        if 0 <= i < len(reference) and not (reference[i].names or reference[i].table):
            found.append(reference[i])
    return found


def _printed_otherwise(name: str, reference: list[Block], missing: Counter) -> bool:
    """Whether a heading or caption beside this paragraph is missing from the returned
    document, asked of one built from other inputs than are on disk.

    Its source can be as it was and its text not: a value in it changed, or a citation, or
    a number pandoc gives it. What it printed at the build is not known, so `_took_in`
    looked for the wrong text, and a heading run into the paragraph in Word merged, "Results
    in 4000 reports" typed into prose where a binding now prints 4100.
    """
    return any(missing[block.text] for block in _headings_beside(name, reference))


def _read_returned(
    returned: list[Block], rendered: dict[str, str]
) -> tuple[dict[str, str], list[tuple[str, ...]], set[str]]:
    """Each identifier's text, the groups that were joined, and identifiers that slid.

    When a paragraph is deleted in Word its bookmark can survive, pushed to the start of the
    next paragraph. A block carrying two identifiers whose text is exactly one of them
    unchanged is that, not a join.

    An identifier left out of the comparison still counts here. Ignored, a paragraph joined
    to one of those read as the first paragraph reworded, and merged with the second's
    text in it, while the second stayed in the source too.
    """
    texts: dict[str, str] = {}
    joined: list[tuple[str, ...]] = []
    slid: set[str] = set()
    for block in returned:
        names = [name for name in block.names if name in rendered]
        if block.table or not names:
            continue
        if len(block.names) == 1:
            texts.setdefault(names[0], block.text)
            continue
        kept = [name for name in names if _same(rendered[name], block.text)]
        if len(kept) == 1:
            texts.setdefault(kept[0], block.text)
            slid.update(name for name in block.names if name != kept[0])
        else:
            joined.append(tuple(dict.fromkeys(block.names)))
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


def _unread(
    reference: list[Block], returned: list[Block], rendered: dict[str, str]
) -> dict[str, tuple[str, ...]]:
    """What each paragraph came back holding that is not read as text, and was not sent.

    Pandoc writes no `w:sym` and sets no font on text, so what the document as sent did not
    hold was put there in Word. What it held already - a private-use character pasted into
    the source, a reference document that gives a style the Symbol font - is not the
    co-author's.
    """
    sent = {b.names[0]: Counter(b.unread) for b in reference if b.names and not b.table}
    found: dict[str, tuple[str, ...]] = {}
    for block in returned:
        if block.table or not block.unread:
            continue
        for name in (n for n in block.names if n in rendered):
            new = Counter(block.unread) - sent.get(name, Counter())
            if new:
                found[name] = tuple(new)
    return found


def _beside_lost(
    rendered: dict[str, str], texts: dict[str, str], built: Sequence[str], present: set[str]
) -> set[str]:
    """Paragraphs changed in Word whose next paragraph in the document as sent is left out
    of the comparison and did not come back.

    That one may have been joined into this one with its bookmark lost, as a join retyped
    across the boundary loses it, and `_absorbed` cannot weigh a text it does not know:
    merged, the lost paragraph's words went into the source a second time.
    """
    found = set()
    for before, name in zip(built, built[1:], strict=False):
        now = texts.get(before)
        if (
            before in rendered
            and name not in rendered
            and name not in present
            and now is not None
            and not _same(rendered[before], now)
        ):
            found.add(before)
    return found


def plan_import(
    known: dict,
    reference: list[Block],
    returned: list[Block],
    marked: list[Block] | None = None,
    abbreviations: frozenset[str] = frozenset(),
    *,
    every: dict | None = None,
    built: Sequence[str] = (),
    unsure: frozenset[str] = frozenset(),
    beside_changed: frozenset[str] = frozenset(),
    stale: bool = False,
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

    `known` holds the paragraphs to compare, and `every` all of the manuscript's, compared
    or not, for what only the source can say: which section a paragraph is in. `built` is
    every identifier the document was built with, in its order, when it records them.
    `unsure` names paragraphs the document may have carried without an identifier: in one
    that records nothing, those older releases did not tag (`roundtrip.Numbering.unsure`);
    in one that does, those its record does not hold. Missing from it, each is still weighed
    as a join into the paragraph before it.

    `reference` is built from the source as it is now, and when the document was built from
    other inputs (`stale`) the blocks beside a paragraph there may not be the ones the
    co-author had: a heading run into the paragraph in Word is then looked for under the
    wrong text. A rewording is not merged into a paragraph whose record says a block beside
    it changed since (`beside_changed`, from `roundtrip.Numbering`), nor, when `stale`, into
    one beside a heading or caption missing from the returned document.
    """
    # Only the identifiers in `known`. The import leaves out one that no longer names the
    # paragraph it named when the document was built, and its block is then neither
    # compared nor moved: the edit in it belongs to a paragraph that is not there now.
    rendered = {
        b.names[0]: b.text
        for b in reference
        if b.names and not b.table and b.names[0] in known
    }
    carried_by = {n: b.text for b in returned if not b.table for n in b.names}
    returned = _recovered(rendered, reference, returned)
    # Identifiers taken off a heading or caption they slid onto: see the refusal below.
    taken_off = set(carried_by) - {n for b in returned if not b.table for n in b.names}

    def fits(text: str, name: str) -> bool:
        sent = rendered.get(name)
        return sent is not None and sent.replace("\u00a0", " ") == text.replace("\u00a0", " ")

    extents = {
        b.names[0]: b.tokens
        for b in marked or ()
        if b.names and not b.table and fits(b.text, b.names[0])
    }
    texts, joined, slid = _read_returned(returned, rendered)
    unread = _unread(reference, returned, rendered)
    in_join = {name for group in joined for name in group}
    present = {n for b in returned if not b.table for n in b.names}
    # One the document may never have carried, missing from it, is not compared - and still
    # weighed as a join into the paragraph before: its text is the source's, as the document
    # was not stale. Left out, a value retyped into its neighbour merged as a rewording, and
    # the number was in the source twice.
    weighed = {
        b.names[0]: b.text
        for b in reference
        if b.names
        and not b.table
        and (b.names[0] in rendered or (b.names[0] in unsure and b.names[0] not in present))
    }
    joined += _joined_without_bookmark(weighed, texts, in_join)
    beside_lost = _beside_lost(rendered, texts, built, present)
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
    # split, and a rewording of the first part deleted the rest. And of every paragraph:
    # judged by the section of the one after it, a paragraph beside one left out of the
    # comparison was never found in parts, and its first part merged.
    in_parts = _in_parts(reference, _sections(every if every is not None else known))
    held = _held_in_place(known, rendered, in_parts)
    sections = _sections(known, held)
    headings = _text_counterparts(reference, returned)
    counterparts, lost = _counterparts(reference, returned, headings)
    beside_new = _beside_new_text(reference, returned, counterparts)
    expected = _untagged_counts(reference)
    not_its_own = _not_its_own(rendered, texts, returned, expected)
    missing = _untagged_missing(reference, returned)
    gone_from_place = [
        name
        for name in rendered
        if name not in in_join
        and counts[name] <= 1
        and name not in not_its_own
        and (texts.get(name) is None or (not texts[name].strip() and rendered[name].strip()))
    ]
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
        elif now is not None and name in unread:
            # Before the comparison: with nothing else edited, the paragraph reads as
            # unchanged, and the co-author's symbol was dropped without a word. And before
            # a deletion: a paragraph replaced by a symbol alone read as deleted.
            refused.append(Refusal(name, now, _unread_why(unread[name])))
        elif (
            now is None
            and name in taken_off
            and not expected[_squashed(carried_by[name])]
            and (name in beside_changed or (stale and _printed_otherwise(name, reference, missing)))
        ):
            # Its identifier came back on a heading beside it and was taken off by that
            # heading's style, and that heading is not the one the document was sent with, so
            # a heading joined into the paragraph could not be told from one it slid onto.
            # Not one taken off by its exact text: that heading reads as it was sent, no join
            # can be in it, and the paragraph is deleted or moved as on main.
            # Reported deleted, beside Word's heading listed as changed, it read as advice to
            # delete the paragraph and retype Word's copy. Kept on the heading instead, it
            # gave the paragraph text again, and a paragraph it was pasted onto merged
            # holding its words. Refused, as main refuses it; still missing, for the rest.
            refused.append(Refusal(name, carried_by[name], (_BESIDE_CHANGED,)))
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
        elif name in beside_changed or (stale and _printed_otherwise(name, reference, missing)):
            refused.append(Refusal(name, now, (_BESIDE_CHANGED,)))
        elif name in beside_new:
            refused.append(Refusal(name, now, (_SPLIT,)))
        elif name in beside_lost:
            refused.append(Refusal(name, now, (_BESIDE_LOST,)))
        elif other := _swallowed(name, was, now, rendered) or _took_vanished(
            was, now, rendered, gone_from_place
        ):
            refused.append(Refusal(name, now, (_SWALLOWED.format(text=_squashed(other)[:60]),)))
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

    def rank(name: str) -> tuple | None:
        # None for an identifier left out of `known`, whose paragraph is not ranked at all.
        if name not in sections:
            return None
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
    shown = Counter(
        _squashed(_listed(b))
        for b in reference
        if not b.names and not b.table and (b.text or b.unread)
    )
    unsettled, because = _unsettled(
        returned, sections, shown, not_its_own, set(misplaced)
    )
    withheld = [entry[0] for entry in moved if sections[entry[0]] in unsettled]
    moved = [entry for entry in moved if entry[0] not in set(withheld)]
    order = _kept_in_place(order, rendered, sections, unsettled)
    displaced = _displaced(gone, rendered, reference, returned)

    # A paragraph without an identifier is never compared, and it is also what bounds a
    # section: once a quotation or a list item was reworded it no longer marked where its
    # section began, a paragraph moved past it read as in order, and import said the
    # document matched the manuscript. What changed is at least said.
    # In order, not as a bag: list items swapped in Word were all still there, and the
    # document was said to match. By what each says and what in it has no text, named: by
    # its text alone, a heading that gained a smiley typed in Wingdings read as unchanged,
    # and a new paragraph holding only a check box as empty.
    sent_blocks = [b for b in reference if not b.names and not b.table and (b.text or b.unread)]
    back_blocks = [b for b in returned if not b.names and not b.table and (b.text or b.unread)]
    sent_untagged = [_listed(b) for b in sent_blocks]
    back_untagged = [_listed(b) for b in back_blocks]
    unchanged = Counter(sent_untagged)
    unidentified: list[str] = []
    for text in back_untagged:
        if unchanged[text]:
            unchanged[text] -= 1
        else:
            unidentified.append(text)
    # Keyed on the text alone, as `missing` is.
    left = Counter(missing)
    vanished: list[str] = []
    for block in sent_blocks:
        if left[block.text]:
            left[block.text] -= 1
            vanished.append(block.text)
    reordered: list[str] = []
    if not (unidentified or vanished) and sent_untagged != back_untagged:
        matcher = difflib.SequenceMatcher(a=sent_untagged, b=back_untagged, autojunk=False)
        for kind, _a1, _a2, b1, b2 in matcher.get_opcodes():
            if kind != "equal":
                reordered.extend(back_untagged[b1:b2])
    plan = Plan(
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
        # Only the new text in the withheld moves' own sections.
        held_by=tuple(
            text for text, where in because if where & {sections[n] for n in withheld}
        ),
        sections=sections,
        lost=lost,
        strayed=tuple(strayed),
        unidentified=tuple(unidentified),
        vanished=tuple(vanished),
        reordered=tuple(reordered),
    )
    return _identified(known, plan, {name: texts[name] for name in merged})


_SPLIT = (
    "it came back with a new paragraph beside it: split in two in Word, new text written "
    "next to it, or a heading, list item or quotation beside it reworded. Merging a split "
    "would replace the whole source paragraph with only part of it. Make the edit in the .md. "
    "If the text shown is a paragraph moved from elsewhere, move that paragraph in the .md "
    "rather than retyping it."
)
_HIDDEN = (
    "text was typed where this paragraph renders nothing - a spacer such as `&nbsp;`, or "
    "markup that prints no text. Merging it would replace what is there. Add the text in "
    "the .md; if it is a paragraph moved from elsewhere, move that paragraph rather than "
    "retyping it."
)
_RUNS_ON = (
    "it holds a `<!--` that nothing in the .md seems to close, so it is held where it is, as "
    "a paragraph opening a comment would be. Make the edit in the .md; closing the comment in "
    "the same paragraph, or removing the `<!--`, frees the paragraph on the next build."
)
_GLUED = (
    "in the .md a line directly under it, with no blank line between, looks as if it opens "
    "or closes a block - an unmatched `\\end{table}`, a line starting `: `, an indented `:::` "
    "fence - so it is held where it is rather than merged with that line. Make the edit in "
    "the .md; a blank line before that line frees the paragraph on the next build."
)
_IN_PARTS = (
    "Word shows it as more than one paragraph, so it is held where it is: merged, its first "
    "part would replace the whole. Make the edit in the .md."
)
_TOOK_IN = (
    "it came back joined with the heading or caption beside it ('{text}'). Merging it would "
    "copy that text into the paragraph while the heading stays where it is. Undo the join, or "
    "make the edit in the .md."
)
_BESIDE_CHANGED = (
    "a heading or other block beside it is not the one the document was sent with: changed "
    "in the .md since the build, or printing otherwise now. A heading run into this paragraph "
    "in Word could not be told from a rewording, and merged, its text would be in the source "
    "twice. Make the edit in the .md."
)
_NOT_ITS_OWN = (
    "the paragraph opening '{opening}' came back with its identifier on other text (shown): "
    "text pasted or typed in front of it took the identifier, and its own text came back "
    "without one, or the text shown reads exactly as another paragraph or a heading. Nothing "
    "is merged into it, and nothing in its section is reordered. Make the edits in the .md; "
    "if a paragraph was moved, move it there rather than retyping it."
)
_SWALLOWED = (
    "it came back holding another paragraph ('{text}'): joined to it, or pasted into it, in "
    "Word. Merging would put that paragraph's text in the source a second time. Make the edit "
    "in the .md, and move or join that paragraph there if that was meant."
)
_UNREAD = (
    "Word draws something in it that has no text the source can hold: {what}. Merging would "
    "leave it out. Type the character itself in Word - Ctrl+Z straight after AutoCorrect "
    "turns ':)' or '-->' into a symbol undoes it - or make the edit in the .md."
)
_STYLED = (
    "part of it is in the Symbol font, set by {where}: read as that font draws it, but a font "
    "set by a style, the defaults or the theme is not taken as exact. Set the font on the "
    "text itself in Word, type the characters, or make the edit in the .md."
)
_PRIVATE = (
    "it holds {what}, which only a symbol or icon font draws as Word shows it. The source "
    "would keep the code, but the build draws it in the body font. Type the character "
    "itself in Word, or make the edit in the .md."
)
_STYLED_PREFIX = "Symbol font from "
_PRIVATE_PREFIX = "private-use character "


def _listed(block: Block) -> str:
    """A paragraph without an identifier as a report lists it: its text, then each thing in
    it with no text, named - "Funding [Wingdings character F04A]"."""
    return " ".join([block.text, *(f"[{name}]" for name in block.unread)]).strip()


def _unread_why(names: tuple[str, ...]) -> tuple[str, ...]:
    """Why a paragraph holding what `wordfonts` names is refused, each kind named once."""
    names = tuple(dict.fromkeys(names))
    styled = [n.removeprefix(_STYLED_PREFIX) for n in names if n.startswith(_STYLED_PREFIX)]
    private = [n for n in names if n.startswith(_PRIVATE_PREFIX)]
    missing = [n for n in names if n not in private and not n.startswith(_STYLED_PREFIX)]
    why = []
    if missing:
        why.append(_UNREAD.format(what="; ".join(missing)))
    for name in private:
        # One sentence each: rarely more than one, and a plural sentence read as one anyway.
        why.append(_PRIVATE.format(what=f"a {name}"))
    if styled:
        why.append(_STYLED.format(where=" and ".join(styled)))
    return tuple(why)


_TWICE = (
    "its identifier appears {n} times in the returned document, so which copy is the "
    "paragraph cannot be told. Make the edit in the .md."
)
_STRANDED = (
    "reworded so, the next build would give it no identifier: with what is around it, pandoc "
    "would read it as something other than this paragraph - a definition, a heading, part of "
    "a comment - and a later edit to it could not come back. Make the edit in the .md."
)
_STRANDS = (
    "with this change, another paragraph in the file would reach the next build without its "
    "identifier, so the rewordings in this file are not applied. Make them in the .md."
)
_BESIDE_LOST = (
    "the paragraph after it in the document as sent did not come back, and is not compared, "
    "because its identifier no longer names the paragraph it named at the build, so whether "
    "it was joined into this one cannot be told. Merging a join would put its text in the "
    "source twice. Make the edit in the .md."
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
    if aligned.unpaired:
        return (
            "the braces would not pair: a brace kept from the .md would be left without its "
            "partner, which was edited, moved or deleted in Word, or a brace typed in Word "
            "pairs with nothing. A brace from Word is written escaped, so that it prints as "
            "typed: written bare, it can complete what pandoc reads as attributes and drop "
            "text. Braces inside code count too, though pandoc pairs none there. The next "
            "build would give the paragraph no identifier, and a later edit to it in Word "
            "could not come back. Make the edit in the .md.",
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


def _arranged(
    slots: list[str], order: dict[str, int], fixed: set[str], pinned: frozenset[str]
) -> dict[str, str]:
    """Which paragraph each slot of one section receives: slot -> paragraph.

    A paragraph with no place of its own in the returned document - deleted in Word, moved
    somewhere it cannot go, absorbed by a join that lost its bookmark, or present twice -
    travels with the paragraph it followed in the section, or stays first if it was first.
    It used to keep its slot while the others moved around it, so a move could land between
    the two halves of a join; and anchoring across a heading carried it into the section
    before. A pinned paragraph does keep its slot, and the others are arranged around it:
    anywhere else, the next build would not find it again.
    """
    free = [n for n in slots if n not in pinned]
    placed = [n for n in free if n in order and n not in fixed]
    followers: dict[str | None, list[str]] = {}
    anchor: str | None = None
    for name in free:
        if name in placed:
            anchor = name
        else:
            followers.setdefault(anchor, []).append(name)
    sequence = list(followers.get(None, []))
    for name in sorted(placed, key=order.__getitem__):
        sequence += [name, *followers.get(name, [])]
    return {**dict(zip(free, sequence, strict=True)), **{n: n for n in slots if n in pinned}}


def _occupants(known: dict, plan: Plan) -> dict[Path, list[tuple[str, str]]]:
    """Per file, each slot a paragraph occupied and the paragraph that now belongs there."""
    order = {name: position for position, name in enumerate(plan.order)}
    fixed = set(plan.misplaced)
    by_section: dict[tuple[Path, int], list[str]] = {}
    for name, (path, _text, _start) in known.items():
        if name in plan.reached:
            where = plan.sections.get(name, (path, 0))
            by_section.setdefault(where, []).append(name)

    by_file: dict[Path, list[tuple[str, str]]] = {}
    for (path, _section), slots in by_section.items():
        occupant = _arranged(slots, order, fixed, plan.held)
        by_file.setdefault(path, []).extend((slot, occupant[slot]) for slot in slots)
    return by_file


def _edits(known: dict, plan: Plan, occupants: list[tuple[str, str]]) -> list[tuple]:
    """The splices one file receives, in source order: (start, end, text, paragraph)."""
    edits = []
    for slot, incoming in occupants:
        _p, original, start = known[slot]
        replacement = plan.merged.get(incoming, known[incoming][1])
        if replacement != original:
            edits.append((start, start + len(original), replacement, incoming))
    return sorted(edits)


def _spliced(text: str, edits: list[tuple]) -> str:
    """`text` with each edit spliced in at the offsets the identifiers carry, so a repeated
    paragraph cannot be confused for its twin: one pass, joined once."""
    parts, at = [], 0
    for start, end, replacement, _name in edits:
        parts += [text[at:start], replacement]
        at = end
    return "".join([*parts, text[at:]])


def _unidentified(known: dict, plan: Plan) -> dict[str, str]:
    """The paragraphs this plan writes that the next build would not find again, each with
    the reason.

    Each file is worked out as `apply_plan` would write it and read the way `tag` reads it.
    A paragraph written must be a block `tag` marks, at the offset the splice put it, with
    the text that was written; one not written must still be marked, with its own text. The
    first can go wrong on its own: a line in a definition's shape is marked where what
    surrounds it makes it prose to pandoc, and moved or reworded into a place with blank
    lines around it, it is a definition that prints nothing. The second can only follow from
    another write, so then every paragraph written in that file is named.

    Only an identifier the file has can be lost. A paragraph the build does not mark as the
    file stands - one `import` was handed from somewhere other than `tagged_paragraphs` -
    is not held for coming out unmarked again: a move past it held its whole section.
    """
    lost: dict[str, str] = {}
    for path, occupants in _occupants(known, plan).items():
        edits = _edits(known, plan, occupants)
        if not edits:
            continue
        raw = path.read_text(encoding="utf-8")
        had = {start for _index, _body, start in marked_blocks(raw)}
        text = _spliced(raw, edits)
        marked = {start: body for _index, body, start in marked_blocks(text)}
        written = {start: (replacement, name) for start, _end, replacement, name in edits}
        # Slots in source order, each shifted by what the splices before it added.
        shifts, shift, pending = {}, 0, iter(edits)
        edit = next(pending, None)
        for start in sorted(known[slot][2] for slot, _incoming in occupants):
            while edit is not None and edit[0] < start:
                shift += len(edit[2]) - (edit[1] - edit[0])
                edit = next(pending, None)
            shifts[start] = shift
        spoilt = False
        for slot, _incoming in occupants:
            _p, original, start = known[slot]
            body, name = written.get(start, (original, None))
            if known[name or slot][2] not in had:
                continue
            if marked.get(start + shifts[start] + len(body) - len(body.lstrip())) != body.strip():
                if name is None:
                    spoilt = True
                else:
                    lost[name] = _STRANDED
        if spoilt:
            lost.update({name: _STRANDS for _s, _e, _r, name in edits if name not in lost})
    return lost


def _identified(known: dict, plan: Plan, came_back: dict[str, str]) -> Plan:
    """The plan without a write the next build would not find again. `came_back` is each
    reworded paragraph's text as it came back from Word, which a refusal shows.

    A paragraph that would come out without its identifier is looked at again, one kind of
    cause at a time, and the plan checked afresh after each, so that nothing is withdrawn
    for what another write did:
    - a rewording that comes out so is refused: that may be what does it;
    - then a moved paragraph that comes out so: it is where the moves put it that does it,
      and no move in its section is applied - holding back its own move alone would push
      the paragraphs around it into other slots, one of them a paragraph nobody moved;
    - then, when a paragraph not written loses its identifier, which write did it cannot be
      told: the rewordings in that file are refused first, and the moves held after.
    A held section's rewordings still land, in place, and are checked there too: back in
    place, a rewording can do what it did not do where it was moved. Each round refuses a
    rewording or holds a section, so it ends.
    """
    held = set(plan.held)
    merged = dict(plan.merged)
    refused = {refusal.name: refusal for refusal in plan.refused}
    held_back: dict[str, str] = {}
    moves = {entry[0] for entry in plan.moved}

    def section(name: str) -> tuple[Path, int]:
        return plan.sections.get(name, (known[name][0], 0))

    while lost := {
        name: reason
        for name, reason in _unidentified(
            known, replace(plan, merged=merged, held=frozenset(held))
        ).items()
        # A held paragraph is written only if it is reworded.
        if name in merged or name not in held
    }:
        stages = (
            {n: why for n, why in lost.items() if why == _STRANDED and n in merged},
            {n: why for n, why in lost.items() if why == _STRANDED},
            {n: why for n, why in lost.items() if n in merged},
            lost,
        )
        current = _occupants(known, replace(plan, merged=merged, held=frozenset(held)))
        for name, reason in sorted(next(stage for stage in stages if stage).items()):
            if name in merged:
                earlier = refused.get(name)
                refused[name] = (
                    Refusal(name, earlier.text, (*earlier.why, reason))
                    if earlier
                    else Refusal(name, came_back.get(name, merged[name]), (reason,))
                )
                del merged[name]
                continue
            members = {n for n in known if n in plan.reached and section(n) == section(name)}
            shifted = [
                incoming
                for slot, incoming in current.get(known[name][0], [])
                if slot in members and incoming != slot
            ]
            # The moves the co-author made, not every paragraph they shift along.
            for incoming in [n for n in shifted if n in moves] or shifted:
                held_back.setdefault(incoming, name)
            held |= members
    final = replace(plan, merged=merged, held=frozenset(held))
    moving = {
        incoming
        for occupants in _occupants(known, final).values()
        for slot, incoming in occupants
        if incoming != slot
    }
    return replace(
        final,
        refused=tuple(refused.values()),
        # Only what lands somewhere else. Named by the order diff, a paragraph that stays in
        # its slot once another is held was still reported as reordered.
        moved=tuple(entry for entry in plan.moved if entry[0] in moving),
        held_back=tuple(sorted(held_back.items())),
    )


def apply_plan(known: dict, plan: Plan) -> list[Path]:
    """Write the moves and the rewordings, together, from one snapshot of the offsets.

    Per section of each file, every slot a paragraph occupied receives the paragraph that now
    belongs there, in its reworded form if it has one. Returns the files that changed.
    """
    written = []
    for path, occupants in _occupants(known, plan).items():
        edits = _edits(known, plan, occupants)
        if not edits:
            continue
        text = _spliced(path.read_text(encoding="utf-8"), edits)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
