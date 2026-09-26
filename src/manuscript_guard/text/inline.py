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
    `10^-3^`, only if every sub- and superscript in it opens and closes there.
    """
    found = text[start:end]
    runs = [
        (start + run.start(), start + run.end())
        for run in _PLAIN_RUN.finditer(found)
        if any(character.isdigit() for character in run.group())
    ]
    if len(runs) == 1:
        return runs[0]
    if not runs or any(character in found for character in "`*_<>[]{}\\|"):
        return None
    if found.count("~") % 2 or found.count("^") % 2:
        return None
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
# differently: every mark in it was then taken out, where only this one needs to be.
_LINK_TEXT = re.compile(r"(?<!!)\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\](?=[(\[])")


def link_text_spans(text: str) -> list[tuple[int, int]]:
    """Link texts in `text` as written: masked, a target that is not a URL, `(#tbl-2)`, is
    blanked, and its text was not found."""
    return [found.span() for found in _LINK_TEXT.finditer(text)]
