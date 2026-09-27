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
    one run, not two split at a backslash; and, around the whole, so is a backslash before
    anything but a space, a bracket or a backslash: pandoc makes text of a symbol after it,
    `5\\%-10\\%`, `\\~5-\\~7` or `5\\°-10\\°`, and keeps it before a letter or a digit, as text
    or a TeX command, `1.2\\pm0.3` or `data\\2021\\05`, the same inside the mark as outside.
    A `@` there, marked, was a citation's. No mark opens straight after a `]`, where pandoc
    read the two brackets, `[B][[7](…)]{…}`, as a reference, nor after a TeX command, which
    took the mark for its argument.
    """
    found = _escapes_as_text(text[start:end], lambda escaped: escaped == "$")
    runs = [
        (start + run.start(), start + run.end())
        for run in _PLAIN_RUN.finditer(found)
        if any(character.isdigit() for character in run.group())
    ]
    whole = _escapes_as_text(text[start:end], _read_alike)
    if len(runs) == 1:
        core = _settled(text, *runs[0])
    elif (
        not runs
        or any(character in whole for character in "`*_<>{}\\|@")
        or whole.count("~") % 2
        or whole.count("^") % 2
    ):
        return None
    else:
        core = _settled(text, start, end)
    return None if _takes_a_mark_as_argument(text, core[0]) else core


def _read_alike(character: str) -> bool:
    """Is a backslash before `character` read the same inside a mark as outside it? Pandoc's
    `all_symbols_escapable` makes text of a symbol after it, and keeps it before a letter or
    a digit, as text or a TeX command. Left out: a space, which pandoc turns into a no-break
    space or a line break and the finder splits a number at; the brackets, which `_wrap`
    escapes again; and the backslash itself."""
    return not (character.isspace() or character in "[]\\")


_TEX_COMMAND_BEFORE = re.compile(r"\\[A-Za-z@]+\*?[ \t]*$")
# How far back on its line a mark's opening is read: a command or a bracket further back
# is not found, and `_checked` has pandoc read the paragraph all the same. Read back to the
# line's start, a line of thousands of numbers was read quadratically.
_LOOK_BACK = 200


def _takes_a_mark_as_argument(text: str, at: int) -> bool:
    """Whether a mark opening at `at` would be read as what comes before it takes: the
    label of a bracket closed straight before it, or a TeX command's argument. After a
    footnote's marker or a lone `]` it would not, but the rule stays whole: letting a mark
    open there, `[^1]$5 `df$a``, exposed an equation pandoc closes inside a code span,
    which `equation_spans` does not find (see Known gaps)."""
    if at > 0 and text[at - 1] == "]":
        return True
    window = max(0, at - _LOOK_BACK)
    line = max(text.rfind("\n", window, at) + 1, window)
    return _TEX_COMMAND_BEFORE.search(text, line, at) is not None


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


# A bracket's text, brackets one deep inside it, not an image's, and what follows it: a
# target, a second bracket or a span's attributes. A mark in a link's text nested a link in
# a link, and pandoc read the paragraph differently: every mark in it was then taken out,
# where only this one needs to be. A bracket holding `@` is a citation, not a link's text.
_LINK_TEXT = re.compile(
    r"(?<!!)\[((?:[^\[\]\n@]|\[[^\[\]\n]*\])*)\](?=(\()|\[([^\[\]\n]*)\]|(\{)|)"
)
# A link's definition, at the margin or in a quotation, which pandoc reads only where a
# block may start: under a blank line or another definition, not under a paragraph's line.
_DEFINITION = re.compile(r"(?:[ ]{0,3}>[ ]?)*[ ]{0,3}\[(?!\^)([^\[\]\n]+)\]:")
_QUOTE_MARKS = re.compile(r"(?:[ ]{0,3}>[ ]?)*")


def _label(text: str) -> str:
    """A reference's label as pandoc matches it: runs of white space as one, and lower
    case, not folded case: pandoc keeps `ß` apart from `ss`."""
    return " ".join(text.split()).lower()


def _definitions(text: str) -> list[tuple[int, int, str]]:
    """Each link definition in `text` as pandoc reads one, where a block may start and
    outside listings and comments: where its line starts and ends, and its label."""
    from manuscript_guard.text.sections import scannable

    found: list[tuple[int, int, str]] = []
    starts = True
    offset = 0
    for line in scannable(text).split("\n"):
        defined = _DEFINITION.match(line)
        if defined is not None and starts:
            found.append((offset, offset + len(line), defined.group(1)))
        starts = defined is not None or not line[_QUOTE_MARKS.match(line).end() :].strip()
        offset += len(line) + 1
    return found


def definition_spans(text: str) -> list[tuple[int, int]]:
    """The lines of `text` that define a link. A mark in one, around a number in its label
    or its target, `[tbl]: #tbl-2`, broke the definition, and every paragraph using it lost
    its marks."""
    return [(start, end) for start, end, _label_text in _definitions(text)]


def _labels(text: str) -> set[str]:
    """The labels `text` defines, as pandoc reads them: each link definition's, and each
    printed heading's title, which pandoc takes for a label as well; a line shaped like a
    heading that pandoc prints as text (`Unprinted`) is none."""
    from manuscript_guard.text.blocks import Unprinted
    from manuscript_guard.text.sections import heading_index

    labels = {
        _label(found.title)
        for found in heading_index(text)
        if type(found.title) is not Unprinted
    }
    return labels | {_label(label) for _start, _end, label in _definitions(text)}


def _is_link(found: re.Match[str], labels: set[str]) -> bool:
    """Whether pandoc reads the bracket `found` as a link's text. A target makes it one. A
    second bracket makes it a reference by that label, or, empty, holding a citation or a
    footnote's marker, by the first one's text, which pandoc falls back to; a label nothing
    defines leaves both text. Attributes make a span. Alone, it is a link when its text is
    a label."""
    text, target, label, attributes = found.group(1, 2, 3, 4)
    if target:
        return True
    if label is not None and label and "@" not in label and not label.startswith("^"):
        return _label(label) in labels
    if label is None and attributes:
        return False
    return _label(text) in labels


def link_text_spans(text: str) -> list[tuple[int, int]]:
    """Link texts in `text` as written: masked, a target that is not a URL, `(#tbl-2)`, is
    blanked, and its text was not found. Pandoc reads `[95% CI 1.2-3.4][^2]`,
    `[…][@smith2021]` and `[12][13]` as text, unless the file defines the first one's
    text, and their numbers are marked."""
    labels = _labels(text)
    spans: list[tuple[int, int]] = []
    label_at = -1
    for found in _LINK_TEXT.finditer(text):
        # A bracket that is the label of the one before it, `[t]` in `[Table 2][t]`, or a
        # definition's own, `[t]: #x`, is no link's text.
        line = text.rfind("\n", 0, found.start()) + 1
        defines = text.startswith(":", found.end()) and _QUOTE_MARKS.fullmatch(
            text, line, found.start()
        )
        if found.start() != label_at and not defines and _is_link(found, labels):
            spans.append(found.span())
        label_at = found.end() if found.group(3) is not None else -1
    return spans
