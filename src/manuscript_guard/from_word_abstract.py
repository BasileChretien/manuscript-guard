"""`init --from`'s reading of a Word paper's Abstract in the two shapes the audit reads where
no heading names it (`text.docx_abstract`), so that the two take the same headings: a run-in
label, "Abstract: text", made a heading "Abstract" over a paragraph "text"; and, in a paper
with heading styles, a paragraph whose words are "Abstract" alone, in bold or not, made a
heading. Each is given the level of the next heading, and ends at a typed title that is no
part of it before that heading, made a heading too, as `section_levels` places a structured
abstract's parts; with neither after it, nothing is made.

pandoc reads an indented paragraph as a block quote: a run-in label opening one is read in
it, and the rest of the quote is kept a quote. The label is taken off the paragraph's words
where it ends where a word does, a no-break or a thin space pandoc keeps inside one piece of
text among the places a word ends (round 1 of #683); one that runs on into a note's mark, a
link or the rest of the paragraph's words in one piece of text is left as it is (DESIGN.md,
"Known gaps").
"""

from __future__ import annotations

import json
import re

from manuscript_guard.text.docx_abstract import _closing
from manuscript_guard.text.section_names import (
    abstract_alone,
    abstract_end,
    names_abstract,
    run_in_abstract,
    section_name_alone,
)


def abstract_headings(blocks: list, styled: bool) -> tuple[list, tuple[str, ...]]:
    """`blocks`, which hold a heading, with the Abstract's heading made of a run-in label or,
    where `styled`, of a paragraph that names it alone, and the typed title that
    ends it; and the titles of the headings made. As they came where a heading names the
    Abstract, or where neither shape is found or ends."""
    from manuscript_guard.from_word import text_of

    headers = [at for at, block in enumerate(blocks) if block.get("t") == "Header"]
    if not headers or any(names_abstract(text_of(blocks[at]["c"][2])) for at in headers):
        return blocks, ()
    opened = _opened(blocks, styled)
    if opened is None:
        return blocks, ()
    at, made, run_in = opened
    later = [one for one in headers if one > at]
    limit = later[0] if later else len(blocks)
    level = blocks[limit]["c"][0] if later else 1
    titles = _titles(blocks, at + 1, limit)
    ends = [one for one, _name, _typed in titles] + [limit]
    worded = [run_in or _worded(blocks[at + 1 : ends[0]])] + [
        _worded(blocks[one + 1 : end])
        for (one, _name, _typed), end in zip(titles, ends[1:], strict=True)]  # fmt: skip
    # The next heading's title read after them, as the audit reads it (`_closing`).
    closing = _closing([text_of(blocks[limit]["c"][2])] if later else [])
    end = abstract_end(["Abstract", *(name for _one, name, _typed in titles), *closing],
                       worded + [False] * len(closing))  # fmt: skip
    if end is not None and end <= len(titles):
        closing = (titles[end - 1][0], titles[end - 1][2])
    elif later:
        closing = None
    else:
        return blocks, ()
    return _made(blocks, at, made, level, closing)


def _made(blocks: list, at: int, made: list, level: int,
          closing: tuple[int, str] | None) -> tuple[list, tuple[str, ...]]:  # fmt: skip
    from manuscript_guard.from_word import _heading, text_of

    named = []
    for block in made:
        if block.get("t") == "Header":
            block["c"][0] = level
            named.append(text_of(block["c"][2]))
    out = [*blocks[:at], *made]
    if closing is not None:
        one, typed = closing
        out += blocks[at + 1 : one] + [_heading(typed, level, identifier="")] + blocks[one + 1 :]
        named.append(typed)
    else:
        out += blocks[at + 1 :]
    return out, tuple(named)


def _opened(blocks: list, styled: bool) -> tuple[int, list, bool] | None:
    """The first block that is the Abstract's heading in one of the two shapes: its index,
    the blocks it is made into, and whether it was a run-in label."""
    from manuscript_guard.from_word import _heading, _words_only, text_of

    for at, block in enumerate(blocks):
        kind = block.get("t")
        if kind in ("Para", "Plain"):
            split = _split(block)
            if split is not None:
                return at, split, True
        if kind == "BlockQuote":
            for inner, quoted in enumerate(block["c"]):
                split = _split(quoted) if quoted.get("t") in ("Para", "Plain") else None
                if split is not None:
                    before = block["c"][:inner]
                    after = [split[1], *block["c"][inner + 1 :]]
                    made = ([{"t": "BlockQuote", "c": before}] if before else []) + [
                        split[0], {"t": "BlockQuote", "c": after}]
                    return at, made, True
        if styled and kind == "Para" and _words_only(block["c"]) \
                and abstract_alone(text_of(block["c"])):  # fmt: skip
            typed = " ".join(text_of(block["c"]).split()).rstrip(" :.")
            return at, [_heading(typed, 1, identifier="")], False
    return None


def _split(block: dict) -> list | None:
    """A paragraph that opens on the Abstract's run-in label, as a heading of the label's
    name over the paragraph's other words; None where it opens on none, or where the label
    cannot be taken off where its words end."""
    from manuscript_guard.from_word import _heading, text_of

    label = run_in_abstract(text_of(block["c"]))
    if label is None:
        return None
    rest = _cut(json.loads(json.dumps(block["c"])), _Cut(len(label.split())))
    if not rest:
        return None
    return [_heading(label.rstrip(" :."), 1, identifier=""), {"t": block["t"], "c": rest}]


class _Cut:
    """How many of the label's words are still to be taken off, whether one has started, and
    whether they all have."""

    def __init__(self, words: int) -> None:
        self.words, self.started, self.done = words, False, False


def _cut(inlines: list, state: _Cut) -> list | None:
    """`inlines` with the first of their words taken off, and the gaps after them; None where
    one of them is in anything but words and how they look."""
    from manuscript_guard.from_word import _GAPS, _LOOKS

    out: list = []
    for node in inlines:
        kind = node.get("t")
        if state.done:
            out.append(node)
        elif kind in _GAPS:
            if state.started:
                state.words, state.started = state.words - 1, False
        elif state.words == 0:
            state.done = True
            out.append(node)
        elif kind == "Str":
            rest = _cut_text(node["c"], state)
            if rest:
                out.append({"t": "Str", "c": rest})
        elif kind in _LOOKS:
            place = _LOOKS[kind]
            kept = _cut(node["c"][place] if place is not None else node["c"], state)
            if kept is None:
                return None
            if kept:
                if place is None:
                    node["c"] = kept
                else:
                    node["c"][place] = kept
                out.append(node)
        else:
            return None
    return out


#: A space pandoc keeps inside one piece of text, a no-break or a thin one, which the label's
#: pattern reads as a space (`section_names._RUN_IN_ABSTRACT`).
_SPACED = re.compile(r"(\s+)")


def _cut_text(text: str, state: _Cut) -> str:
    """What is left of one piece of text once the label's words still to be taken off are:
    split at the spaces pandoc keeps in it, "Abstract:", a no-break space and "412" in one
    piece, so that the 412 stays (round 1 of #683: it went with the label)."""
    pieces = _SPACED.split(text)
    for at, piece in enumerate(pieces):
        if not piece:
            continue
        if piece.isspace():
            if state.started:
                state.words, state.started = state.words - 1, False
        elif state.words == 0:
            state.done = True
            return "".join(pieces[at:])
        else:
            state.started = True
    return ""


def _titles(blocks: list, start: int, limit: int) -> list[tuple[int, str, str]]:
    """Each paragraph from `start` up to `limit` whose words are a section's name alone, as
    `from_word.typed_headings` reads one, by index, with that name and its words as typed,
    less a colon or a stop after them."""
    from manuscript_guard.from_word import _words_only, text_of

    found = []
    for at in range(start, limit):
        block = blocks[at]
        if block.get("t") != "Para" or not _words_only(block["c"]):
            continue
        typed = " ".join(text_of(block["c"]).split())
        name = section_name_alone(typed)
        if name is not None:
            found.append((at, name, typed.rstrip(" :.")))
    return found


def _worded(blocks: list) -> bool:
    from manuscript_guard.from_word import _words

    return _words(blocks) > 0
