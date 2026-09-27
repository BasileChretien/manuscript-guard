"""Inline markup a mark must not break, read the way pandoc reads it.

The annotated copy wraps each number in a mark, and a mark in the wrong place changes how
pandoc reads the text: split from its closing `~`, a subscript is text, and inside a code
span the mark prints as written. These find where a mark cannot go at all, and, for a
number the finder read with markup around it, the part a mark can go around. They are a
model of pandoc's inline reader, so `annotate` has pandoc check what they decide.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Callable

# Characters that open or close inline markup: code, sub- and superscripts, emphasis and
# struck text, HTML, links and spans, attributes, escapes and table cells. Not `$`: beside
# a number it is a currency's, and marked on the digits alone, `US$5` left one dollar sign
# facing another across the paragraph, which pandoc read as an equation. Equations are
# found apart (`equation_spans`), and a number in one takes no mark.
_MARKUP = r"`~^*_<>\[\]{}\\|"
_PLAIN_RUN = re.compile(rf"[^{_MARKUP}]+")


def markable_core(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Where a mark can go around the number the finder read at `text[start:end]`, or
    None when nowhere can.

    The finder reads raw text, and takes markup in: `HbA~1c` from `HbA~1c~`, `CO~2` from
    `CO~2~`, `span>7</span` from `<span>7</span>`. A mark around what it found split the
    markup, and pandoc read none. So the mark goes around the one run free of markup that
    holds a digit, inside the subscript or the span, where pandoc reads a mark as well as
    anywhere; and around the whole of what was found when several runs hold digits,
    `10^-3^`, only if every sub- and superscript in it opens and closes there. Brackets
    there are escaped in the mark and read as the text they were, `[12][13]`; a link's text
    is found apart (`link_text_spans`). An escaped dollar sign is text, so `\\$10-\\$50` is
    one run, not two split at a backslash; and, around the whole, so is anything else a
    backslash escapes, `5\\%-10\\%`, `\\~5-\\~7` or `5\\°-10\\°`, but a bracket, which the
    mark escapes again, or a backslash. No mark opens straight after a `]`: pandoc read the
    two brackets, `[B][[7](…)]{…}`, as a reference, and the paragraph otherwise.
    """
    found = _escapes_as_text(text[start:end], lambda escaped: escaped == "$")
    runs = [
        (start + run.start(), start + run.end())
        for run in _PLAIN_RUN.finditer(found)
        if any(character.isdigit() for character in run.group())
    ]
    whole = _escapes_as_text(text[start:end], _escapable)
    if len(runs) == 1:
        core = _settled(text, *runs[0])
    elif (
        not runs
        or any(character in whole for character in "`*_<>{}\\|")
        or whole.count("~") % 2
        or whole.count("^") % 2
    ):
        return None
    else:
        core = _settled(text, start, end)
    return None if core[0] > 0 and text[core[0] - 1] == "]" else core


def _escapable(character: str) -> bool:
    """Is `character`, after a backslash, text? Pandoc's `all_symbols_escapable` makes text
    of anything that is not a letter or a digit. Left out here: a space, which pandoc turns
    into a no-break space or a line break and the finder splits a number at; the brackets,
    which `_wrap` escapes again; and the backslash itself."""
    return not (character.isalnum() or character.isspace() or character in "[]\\")


def _escapes_as_text(found: str, escaped: Callable[[str], bool]) -> str:
    """`found` with each backslash before a character `escaped` accepts read, with that
    character, as two dollar signs, which are no markup; the length is kept, and with it
    every offset. A backslash escaped by another is left as it is."""
    out: list[str] = []
    at = 0
    while at < len(found):
        if found[at] == "\\" and at + 1 < len(found):
            out.append("$$" if escaped(found[at + 1]) else found[at : at + 2])
            at += 2
            continue
        out.append(found[at])
        at += 1
    return "".join(out)


def _settled(text: str, start: int, end: int) -> tuple[int, int]:
    """`text[start:end]`, taking in the backslashes just before it and leaving out the
    dollar signs it ends with. A backslash escapes what follows it, and outside the mark it
    escaped the mark's own bracket: `\\$5` lost its mark, and its paragraph with it. A dollar
    sign after a number, `5$ … 10$`, faced the next one across the marks between, which
    pandoc read as an equation; one before a number is a currency's, and stays with it. An
    escaped one, `5\\$`, is left out with its backslash, which inside the mark escaped the
    mark's closing bracket."""
    while start > 0 and text[start - 1] == "\\":
        start -= 1
    while end - start > 1 and text[end - 1] == "$":
        end -= 1
        slashes = 0
        while end - slashes > start and text[end - slashes - 1] == "\\":
            slashes += 1
        end -= slashes % 2
    return start, end


_RUN = re.compile(r"`+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")


def code_spans(masked: str) -> list[tuple[int, int]]:
    """Where pandoc reads inline code in `masked`, a file with its listings and comments
    already masked: a run of backticks opens a span that the next run of the same length
    in the same paragraph closes, runs of other lengths between being code; a run with no
    such closer is text. A backslash before a run escapes its first backtick. Paired in
    one pass, each run's closer found by reading the runs from the end once."""
    breaks = [found.end() for found in _PARAGRAPH_BREAK.finditer(masked)]
    runs: list[tuple[int, int, int]] = []
    for found in _RUN.finditer(masked):
        start, end = found.start(), found.end()
        slashes = 0
        while start - slashes > 0 and masked[start - slashes - 1] == "\\":
            slashes += 1
        start += slashes % 2
        if start < end:
            runs.append((start, end, bisect.bisect_right(breaks, start)))
    closer: list[int | None] = [None] * len(runs)
    later: dict[tuple[int, int], int] = {}
    for index in range(len(runs) - 1, -1, -1):
        start, end, paragraph = runs[index]
        closer[index] = later.get((paragraph, end - start))
        later[(paragraph, end - start)] = index
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        close = closer[index]
        if close is None:
            index += 1
            continue
        spans.append((runs[index][0], runs[close][1]))
        index = close + 1
    return spans


# Pandoc's dollars: `$$` to `$$`, and `$` with no space inside either end, and no digit
# after the closing one, neither running over a blank line.
_EQUATION = re.compile(
    r"\$\$(?:[^$]|\$(?!\$))+?\$\$"
    r"|(?<![\\$])\$(?=\S)(?:[^$\n]|\n(?![ \t]*\n))*?(?<=\S)\$(?!\d)"
)


def equation_spans(masked: str, code: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Where pandoc reads an equation in `masked`, outside the code spans `code`: a dollar
    sign in code, `` `df$age` ``, opened one that ran to the next code span's and took the
    prose between."""
    pieces: list[str] = []
    at = 0
    for start, end in code:
        pieces += [masked[at:start], " " * (end - start)]
        at = end
    pieces.append(masked[at:])
    return [found.span() for found in _EQUATION.finditer("".join(pieces))]


# A link's text, brackets one deep inside it, before its target or its reference, and not
# an image's. A mark there nested a link in a link, and pandoc read the paragraph
# differently: every mark in it was then taken out, where only this one needs to be. A
# bracket holding `@` is a citation, not a link's text. A bracket after it is a reference
# only when the file defines its label, `[tbl]: #tbl-2`, or, empty, the text's own: pandoc
# reads `[95% CI 1.2-3.4][^2]`, `[…][@smith2021]` and `[12][13]` as text, and read as
# links, their numbers went unmarked.
_LINK_TEXT = re.compile(
    r"(?<!!)\[((?:[^\[\]\n@]|\[[^\[\]\n]*\])*)\](?=(\()|\[([^\[\]\n]*)\])"
)
_DEFINITION = re.compile(r"^ {0,3}\[(?!\^)([^\[\]\n]+)\]:", re.MULTILINE)


def _label(text: str) -> str:
    """A reference's label as pandoc matches it: case and runs of white space ignored."""
    return " ".join(text.split()).casefold()


def link_text_spans(text: str) -> list[tuple[int, int]]:
    """Link texts in `text` as written: masked, a target that is not a URL, `(#tbl-2)`, is
    blanked, and its text was not found."""
    defined = {_label(found.group(1)) for found in _DEFINITION.finditer(text)}
    return [
        found.span()
        for found in _LINK_TEXT.finditer(text)
        if found.group(2) or _label(found.group(3) or found.group(1)) in defined
    ]
