"""A reworded stretch of a paragraph written into its source word by word.

`roundtrip.align` rebuilds a paragraph that came back reworded from the source's bindings and
citations and the co-author's words. Between two of them is a stretch of prose, and a
stretch that came back changed used to be written whole from Word's text, which holds no
markup: one word changed in "**Background.** Fictional described ... from {{results.a}}"
wrote the stretch back from its first word, without the bold, and with every straight
apostrophe in it turned into Word's curly one. A stretch runs from one binding or citation to
the next, which is usually from the paragraph's first word.

Here the stretch as the build printed it and as it came back are compared word by word, and
only the words that differ are written, each where the source has it; every other character
of the source is kept as it is, its emphasis, code, escapes and quotes with it. The source is
lined up with what the build printed of it character by character (`_units`), through what
each character of the source shows in Word (`roundtrip._read`), so nothing about where a
word is in the source is guessed.

An edit inside emphasis is written inside it, and the emphasis goes round the new words. An
edit that meets emphasis, code or a character written as an escape or an entity anywhere but
inside it - words typed just where a span opens or closes, or a change that runs across one
end of it - cannot be placed by Word's text: it does not say whether the new words are
inside. Such a span is written from Word's text whole, with the edit, and loses its
formatting, which the dry run names (`flattened`). Where the source's straight quotes could
pair differently once a word beside them is changed, or the stretch cannot be lined up with
what was printed, nothing is written here and `align` writes the stretch from Word's text,
as it did before.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from manuscript_guard.roundtrip import (
    _SET_ASIDE,
    _TAG_OPENS,
    _UNESCAPED_CLOSE,
    _UNESCAPED_OPEN,
    _WORD,
    _escaped,
    _opened,
    _Reading,
    _respaced,
    _spaced,
)

#: What pandoc's smart typesetting prints for what the source has, one printed character for
#: each: the reading Word's text is lined up with the source by.
_TYPESET = (
    ("---", "—"),
    ("--", "–"),
    ("...", "…"),
    ("'", "‘"),
    ("'", "’"),
    ('"', "“"),
    ('"', "”"),
)


#: What Markdown can read as markup with what stands beside it. Words deleted next to one
#: bring the source either side up against it: `]` against a value that opens with `(` is a
#: link, and `{k={{results.a}} y}` without its ` y` is a block of attributes.
_TOUCHY = frozenset("\\`*_[](){}<>$^~@&#|!:=")
#: A `>` the source has bare, which closes a tag a `<` before it opens.
_BARE_CLOSE = re.compile(r"(?<!\\)>")
#: What opens a tag or an entity straight after a kept `<` or `&`.
_OPENS_AFTER = {"<": re.compile(r"[^\W\d_]|[/!?]"), "&": re.compile(r"#|[^\W\d_]")}


@dataclass(frozen=True)
class Rewritten:
    """A stretch with the co-author's words written in: the source stretch as written, what
    it shows in Word with each `<` Word typed set aside (`roundtrip._closers`), and the words
    written plain over markup they replaced (see `flattened`)."""

    text: str
    bare: str
    flattened: tuple[str, ...]


@dataclass
class _Edit:
    """One change, as where it is in the source stretch and in what the build printed."""

    s1: int
    s2: int
    p1: int
    p2: int


def _units(shown: str, printed: str) -> list[tuple[int, int, int, int]] | None:
    """`shown` (what the source stretch shows in Word, layout spaces as typed) lined up with
    `printed` (what the build printed of it), as (shown start, end, printed start, end): one
    character for one, a run of spaces for a run, `--` for an en dash, a straight quote for a
    curly one. None where they part otherwise, or a space on one side has none on the other."""
    units: list[tuple[int, int, int, int]] = []
    i = j = 0
    while i < len(shown) or j < len(printed):
        here, there = shown[i : i + 1], printed[j : j + 1]
        if here.isspace() or there.isspace():
            i2, j2 = i, j
            while i2 < len(shown) and shown[i2].isspace():
                i2 += 1
            while j2 < len(printed) and printed[j2].isspace():
                j2 += 1
            if i2 == i or j2 == j:
                return None
            units.append((i, i2, j, j2))
            i, j = i2, j2
            continue
        if here and here == there:
            units.append((i, i + 1, j, j + 1))
            i, j = i + 1, j + 1
            continue
        typed = next(
            (typed for typed, char in _TYPESET if shown.startswith(typed, i) and there == char),
            None,
        )
        if typed is None:
            return None
        units.append((i, i + len(typed), j, j + 1))
        i, j = i + len(typed), j + 1
    return units


def _pairing_quote(text: str, at: int) -> bool:
    """Whether the character at `at` is a straight quote pandoc may pair with another: a
    double one, or a single one that is not an apostrophe between two letters or digits, and
    not escaped."""
    char = text[at]
    if char not in "'\"" or (at > 0 and text[at - 1] == "\\"):
        return False
    if char == '"':
        return True
    inside = 0 < at < len(text) - 1 and text[at - 1].isalnum() and text[at + 1].isalnum()
    return not inside


def _diff(printed: str, piece: str) -> list[tuple[str, int, int, int, int]]:
    """The two texts compared word by word, as difflib's opcodes in characters. A run of
    layout spaces is one space, as `roundtrip._unchanged` reads it."""
    was, now = _WORD.findall(printed), _WORD.findall(piece)

    def keys(words: list[str]) -> list[str]:
        return [_spaced(word) if word.isspace() else word for word in words]

    def offsets(words: list[str]) -> list[int]:
        out = [0]
        for word in words:
            out.append(out[-1] + len(word))
        return out

    at_was, at_now = offsets(was), offsets(now)
    matcher = difflib.SequenceMatcher(a=keys(was), b=keys(now), autojunk=False)
    ops = [list(op) for op in matcher.get_opcodes()]
    # A lone mark of punctuation the comparison kept between two changes is part of them:
    # the full stop of "e.g." typed before a paragraph's last one was matched with it, and
    # the words around it were read as two edits, neither with "e.g." whole.
    at = 1
    while at < len(ops) - 1:
        tag, a1, a2, _b1, _b2 = ops[at]
        lone = a2 - a1 == 1 and len(was[a1]) == 1 and not (was[a1].isalnum() or was[a1].isspace())
        if tag == "equal" and lone and ops[at - 1][0] != "equal" and ops[at + 1][0] != "equal":
            ops[at - 1 : at + 2] = [["replace", ops[at - 1][1], ops[at + 1][2],
                                     ops[at - 1][3], ops[at + 1][4]]]  # fmt: skip
        else:
            at += 1
    return [
        (tag, at_was[a1], at_was[a2], at_now[b1], at_now[b2]) for tag, a1, a2, b1, b2 in ops
    ]


def _widened(edit: _Edit, marks, sources) -> bool:
    """Widen `edit` over each span of markup it meets other than from inside its text, and
    over each unit of the lining-up it takes part of. Whether it grew."""
    grew = False
    again = True
    while again:
        again = False
        for start, end, inner, inner_end, _formatting in marks:
            if edit.s2 <= start or edit.s1 >= end:
                continue
            if inner >= 0 and inner <= edit.s1 and edit.s2 <= inner_end:
                continue
            if start < edit.s1 or edit.s2 < end:
                edit.s1, edit.s2 = min(edit.s1, start), max(edit.s2, end)
                again = grew = True
        for start, end in sources:
            if start < edit.s2 and edit.s1 < end and (start < edit.s1 or edit.s2 < end):
                edit.s1, edit.s2 = min(edit.s1, start), max(edit.s2, end)
                again = grew = True
    return grew


def _placed(
    ops, units, sources, marks, length: int
) -> list[_Edit] | None:
    """Each changed run of words as an edit of the source stretch, widened over markup it
    cannot be written into and merged with any edit it then meets. None where a change starts
    or ends inside what the lining-up takes as one unit."""
    at_unit = {unit[2]: index for index, unit in enumerate(units)}
    end = units[-1][3] if units else 0
    at_unit.setdefault(end, len(units))

    def left(k: int) -> int:
        return sources[k - 1][1] if k > 0 else 0

    def right(k: int) -> int:
        return sources[k][0] if k < len(units) else length

    edits: list[_Edit] = []
    for tag, p1, p2, _q1, _q2 in ops:
        if tag == "equal":
            continue
        if p1 not in at_unit or p2 not in at_unit:
            return None
        k1, k2 = at_unit[p1], at_unit[p2]
        if p1 < p2:
            edits.append(_Edit(right(k1), left(k2), p1, p2))
        else:
            edits.append(_Edit(left(k1), right(k1), p1, p2))

    changed = True
    while changed:
        changed = False
        for edit in edits:
            if _widened(edit, marks, sources):
                changed = True
                after = [units[k][2] for k in range(len(units)) if sources[k][0] >= edit.s1]
                before = [units[k][3] for k in range(len(units)) if sources[k][1] <= edit.s2]
                edit.p1 = min(edit.p1, after[0] if after else end)
                edit.p2 = max(edit.p2, before[-1] if before else 0)
        edits.sort(key=lambda e: (e.s1, e.s2))
        merged: list[_Edit] = []
        for edit in edits:
            last = merged[-1] if merged else None
            if last and (edit.s1 <= last.s2 or edit.p1 <= last.p2):
                last.s1, last.s2 = min(last.s1, edit.s1), max(last.s2, edit.s2)
                last.p1, last.p2 = min(last.p1, edit.p1), max(last.p2, edit.p2)
                changed = True
            else:
                merged.append(edit)
        edits = merged
    return edits


def _in_word(ops, p: int, start: bool) -> int | None:
    """Where the position `p` of what the build printed is in Word's text: at the start of an
    edit before the words it inserts there, at its end after them."""
    found = []
    for tag, a1, a2, b1, b2 in ops:
        if tag == "equal" and a1 <= p <= a2:
            found.append(b1 + p - a1)
        elif tag != "equal" and p == (a1 if start else a2):
            found.append(b1 if start else b2)
    if not found:
        return None
    return min(found) if start else max(found)


def rewritten(
    reading: _Reading,
    index: int,
    printed: str,
    piece: str,
    *,
    ahead: str,
    bare: str,
    last: bool,
    binding_next: bool,
    abbreviations: frozenset[str],
) -> Rewritten | None:
    """The stretch `index` of the paragraph `reading` read, which the build printed as
    `printed` and came back from Word as `piece`, with only the words that changed written
    into its source; or None where that cannot be done exactly. `ahead` and `bare` are what
    stands before the stretch in Word's text, as `align` keeps them; `last` says no binding
    or citation follows it, and `binding_next` that a binding does.

    A paragraph whose prose holds a bare brace is not written so: a brace kept bare beside
    words written from Word can complete what pandoc reads as attributes, which the reading
    here does not see, and `align` refuses a pair it would split (#90)."""
    if any(_UNESCAPED_OPEN.search(t) or _UNESCAPED_CLOSE.search(t) for t in reading.prose):
        return None
    a, b = reading.ranges[index]
    source = reading.prose[index]
    chars: list[str] = []
    owners: list[int] = []
    for at in range(a, b):
        for char in reading.shows[at]:
            chars.append(char)
            owners.append(at - a)
    units = _units("".join(chars), printed)
    if units is None:
        return None
    sources = [(owners[h1], owners[h2 - 1] + 1) for h1, h2, _p1, _p2 in units]
    marks = [
        (start - a, end - a, inner - a if inner >= 0 else -1, inner_end - a, formatting)
        for start, end, inner, inner_end, formatting in reading.marks
        if a <= start and end <= b
    ]
    ops = _diff(printed, piece)
    edits = _placed(ops, units, sources, marks, len(source))
    if edits is None:
        return None
    for edit in edits:
        near = range(max(edit.s1 - 1, 0), min(edit.s2 + 1, len(source)))
        if any(_pairing_quote(source, at) for at in near):
            return None
    delimiters = {
        at
        for start, end, inner, inner_end, _formatting in marks
        if inner >= 0
        for at in (*range(start, inner), *range(inner_end, end))
    }
    beyond = "".join(reading.prose[index + 1 :])

    out: list[str] = []
    word_bare = ""
    flattened: list[str] = []
    written_at: list[tuple[int, int]] = []
    cursor = q_cursor = 0
    for edit in edits:
        q1, q2 = _in_word(ops, edit.p1, True), _in_word(ops, edit.p2, False)
        if q1 is None or q2 is None:
            return None
        out.append(source[cursor : edit.s1])
        word_bare += piece[q_cursor:q1]
        if not _beside(source, edit, piece[q1:q2], delimiters, bare + word_bare, beyond):
            return None
        written = _written(
            piece[q1:q2], source, edit, index == 0, last,
            shown_before=ahead + piece[:q1], bare_before=bare + word_bare,
        )  # fmt: skip
        length = sum(len(part) for part in out)
        written_at.append((length, length + len(written)))
        out.append(written)
        word_bare += piece[q1:q2].replace("<", _SET_ASIDE)
        lost = any(
            formatting and edit.s1 <= start and end <= edit.s2
            for start, end, _i, _e, formatting in marks
        )
        if lost and piece[q1:q2].strip():
            flattened.append(" ".join(piece[q1:q2].split()))
        cursor, q_cursor = edit.s2, q2
    out.append(source[cursor:])
    word_bare += piece[q_cursor:]
    text = _respaced_in("".join(out), written_at, abbreviations, index == 0, binding_next)
    if index == 0 and edits and edits[0].s1 == 0:
        # The paragraph opens otherwise now, and is escaped as it opens: "1." typed for
        # "The" before a kept " ratio" makes a list of it, and deleting the first words can
        # leave a kept `# ` in front.
        text = _opened(text.lstrip(), whole=last)
    return Rewritten(text, word_bare, tuple(flattened))


def _beside(
    source: str, edit: _Edit, words: str, delimiters: set[int], bare: str, beyond: str
) -> bool:
    """Whether `words` can be written at `edit` in the stretch `source` without what is kept
    beside them reading otherwise. Deleted, they must leave no character that reads as
    markup against what is beyond them (`_TOUCHY`), but for a delimiter of emphasis kept
    round them. Written, they must not open a tag or an entity after a kept `<` or `&`. And
    no tag may be open before them, by a `<` that Word's text shows bare (`bare`), with a
    bare `>` of the source after them, in the stretch or beyond it in the paragraph: pandoc
    read the two as text only because something between them was not an attribute, and the
    edit may be what was not."""
    before, rest = source[: edit.s1], source[edit.s2 :]
    if not words:
        for at in (edit.s1 - 1, edit.s2):
            if 0 <= at < len(source) and source[at] in _TOUCHY and at not in delimiters:
                return False
    elif before[-1:] in _OPENS_AFTER and _OPENS_AFTER[before[-1]].match(words):
        return False
    return not (_TAG_OPENS.search(bare) and _BARE_CLOSE.search(rest + beyond))


def _respaced_in(
    text: str,
    written_at: list[tuple[int, int]],
    abbreviations: frozenset[str],
    lead: bool,
    binding_next: bool,
) -> str:
    """`text`, the stretch with Word's words written in at `written_at`, with the no-break
    space pandoc puts after an abbreviation written as a space in those words alone
    (`roundtrip._respaced`), each word read with the kept text around it. One the source
    has is its own, and stays."""
    spaced = _respaced(text, abbreviations, lead=lead, binding_next=binding_next)
    out = list(text)
    for start, end in written_at:
        out[start:end] = spaced[start:end]
    return "".join(out)


def _written(
    words: str,
    source: str,
    edit: _Edit,
    first: bool,
    last: bool,
    *,
    shown_before: str,
    bare_before: str,
) -> str:
    """Word's `words` as Markdown, to stand at `edit` in the stretch `source`: escaped as
    `roundtrip._escaped` escapes Word's text, with what stands beside them in the source.

    A `(` is escaped after a kept `]` or a token, and a `<`, `&`, `]` or `{` before a token
    or before kept text it could run into, as `_escaped` escapes them at a token's edge."""
    rest = source[edit.s2 :]
    before = source[: edit.s1]
    written = ""
    if words:
        written = _escaped(
            words,
            opening=False,
            after_token=before.endswith("]") if before else not first,
            before_token=(not rest and not last) or (bool(rest) and not rest[0].isspace()),
            shown_before=shown_before,
            bare_before=bare_before,
        )
    if first and not before and written:
        # Escaped as they open the paragraph before a no-break space is judged: `p\.` is no
        # abbreviation to pandoc, so the one after it stays.
        written = written.lstrip()
        joined = _opened(written + rest, whole=last)
        if joined.endswith(rest):
            written = joined[: len(joined) - len(rest)]
    return written
