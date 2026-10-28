"""A LaTeX file's tables as rows of cells, as `audit` reads a Markdown or a Word table
(`text.tables`).

Each table the author typed (`Reading.tables`, the environments of `commands.TYPED_TABLES`)
is split into rows at each `\\\\` and `\\tabularnewline`, and each row into cells at each
`&`, where LaTeX splits them: outside braces, outside a nested environment, and outside a
comment. An escaped `\\&` is a character, and so is a `\\\\` inside `\\makecell{1\\\\2}`. The
reader's mask says which separators print: a separator it reads is a space there, one in a
comment or escaped is not.

A cell's text is what the file prints there, from its Markdown view
(`views.markdown_view`), with what the reader blanks taken out, as the classifier takes it
out (`classify._printed`): so `30.0\\%` is "30.0%", `\\multirow{2}{*}{Age}` prints "Age",
and `\\multicolumn{2}{c}{Total}` prints "Total" and spans two columns. A rule, `\\hline`,
`\\midrule[1pt]`, `\\cline{2-3}` or `\\cmidrule(lr){2-3}`, is no part of a cell, nor is a
colour, `\\rowcolor{gray!20}` or `\\cellcolor[rgb]{0.9,0.9,0.9}`, and a row that holds
nothing but rules is no row. The optional space after a row, `\\\\[2pt]`, is not read.
A cell's line is the `.tex` line its text starts on, from 1.
"""

from __future__ import annotations

import re

from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import Source
from manuscript_guard.text.latex.views import bindings, markdown_view
from manuscript_guard.text.tables import Table, TableCell

#: The opening of a table and the arguments before its rows: the position, a width for the
#: environments that take one, and the column specification, braced.
_OPENING = re.compile(r"\\begin\s*\{(?P<name>tabular\*?|tabularx|tabulary|longtable)\}")
_WIDTHS = frozenset({"tabular*", "tabularx", "tabulary"})
#: An environment opened or closed inside a cell.
_ENVIRONMENT = re.compile(r"\\(?P<how>begin|end)\s*\{[^{}]*\}")
#: A rule between rows, with its arguments, which prints no cell; and a row's or a cell's
#: colour, which prints nothing either, so that a `\\multicolumn` after `\\rowcolor` still
#: opens its cell (round 1 of #463).
_RULE = re.compile(
    r"\\(?:(?:hline|endhead|endfirsthead|endfoot|endlastfoot)(?![A-Za-z@])"
    r"|(?:toprule|midrule|bottomrule|addlinespace)(?![A-Za-z@])(?:\s*\[[^\]]*\])?"
    r"|(?:cline|hhline)(?![A-Za-z@])\s*\{[^{}]*\}"
    r"|cmidrule(?![A-Za-z@])\s*(?:\[[^\]]*\])?\s*(?:\([^()]*\))?\s*\{[^{}]*\}"
    r"|(?:rowcolor|cellcolor)(?![A-Za-z@])\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}"
    r"|specialrule(?![A-Za-z@])\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{[^{}]*\})"
)
#: What may follow `\\\\`: a star, and a length in brackets.
_AFTER_BREAK = re.compile(r"\*?(?:[ \t]*\[[^\]\n]*\])?")
_SPAN = re.compile(r"\s*\\multicolumn\s*\{\s*(\d{1,2})\s*\}")
_NEWLINE_COMMAND = "\\tabularnewline"
#: What prints nothing at the start of a cell.
_BLANK = " \t\r\n" + NUL


def latex_tables(source: Source) -> list[Table]:
    """Each table the author typed in `source`, its rows in the order they stand. A table
    inside another's cell is read as a table of its own, and its text is in that cell."""
    view = markdown_view(source, bindings(source)[0], blank=NUL)
    tables: list[Table] = []
    for start, end in source.reading.tables:
        opened = _rows_start(source.text, start)
        if opened is None or opened >= end:
            continue
        rows = []
        comments = _in_comment(source, opened, end)
        for cells in _split(source, opened, end):
            row = tuple(_cell(source.text, view, _past_blanks(source.text, at, to, comments), to)
                        for at, to in cells)  # fmt: skip
            if any(cell.text for cell in row):
                rows.append(row)
        if rows:
            tables.append(tuple(rows))
    return tables


def _rows_start(text: str, start: int) -> int | None:
    """Where the rows of the table opening at `start` begin: past its environment's name,
    its position in brackets, its width where it takes one, and its column specification."""
    opening = _OPENING.match(text, start)
    if opening is None:
        return None
    at = _skip_space(text, opening.end())
    if text.startswith("[", at):
        closed = text.find("]", at)
        if closed < 0:
            return None
        at = _skip_space(text, closed + 1)
    for _argument in range(2 if opening["name"] in _WIDTHS else 1):
        at = _group_end(text, _skip_space(text, at))
        if at is None:
            return None
    return at


def _skip_space(text: str, at: int) -> int:
    while at < len(text) and text[at] in " \t\r\n":
        at += 1
    return at


def _group_end(text: str, at: int) -> int | None:
    """Past the brace group that opens at `at`, its escaped braces not counted."""
    if not text.startswith("{", at):
        return None
    depth, index = 0, at
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _split(source: Source, start: int, end: int) -> list[list[tuple[int, int]]]:
    """The table's rows between `start` and `end`, each as its cells' spans."""
    text, masked = source.text, source.reading.masked
    comments = _in_comment(source, start, end)
    rows: list[list[tuple[int, int]]] = []
    cells: list[tuple[int, int]] = []
    cell, depth, nested, index = start, 0, 0, start
    while index < end:
        if index in comments:
            index += 1
            continue
        char = text[index]
        if char == "\\":
            environment = _ENVIRONMENT.match(text, index)
            if environment is not None:
                nested += 1 if environment["how"] == "begin" else -1
                index = environment.end()
                continue
            broken = _breaks(text, masked, index)
            if broken and _at_top(depth, nested):
                cells.append((cell, index))
                rows.append(cells)
                after = index + broken
                cells, index = [], after + _AFTER_BREAK.match(text, after).end() - after
                cell = index
                continue
            index += _ESCAPED
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "&" and _separates(masked, index) and _at_top(depth, nested):
            cells.append((cell, index))
            cell = index + 1
        index += 1
    cells.append((cell, end))
    rows.append(cells)
    return rows


#: How far a backslash reaches that starts no row: the character after it, so that the `&`
#: of an escaped `\\&`, and the brace of `\\{`, is read as a character and not as LaTeX.
_ESCAPED = 2


def _separates(masked: str, at: int) -> bool:
    """Whether the `&` at `at` parts cells: the mask reads it as one, a space, where it
    reads the `&` of `\\&` as nothing it prints there."""
    return masked[at] == " "


def _at_top(depth: int, nested: int) -> bool:
    """Whether a separator stands in the table itself: outside braces, and outside an
    environment opened in a cell."""
    return depth == 0 and nested <= 0


def _breaks(text: str, masked: str, at: int) -> int:
    """How long the row break at `at` is, or 0 where none stands there: `\\\\` the mask
    reads, or `\\tabularnewline`."""
    if text.startswith("\\\\", at) and masked[at] == " ":
        return 2
    if text.startswith(_NEWLINE_COMMAND, at) and not re.match(
        r"[A-Za-z@]", text[at + len(_NEWLINE_COMMAND) : at + len(_NEWLINE_COMMAND) + 1]
    ):
        return len(_NEWLINE_COMMAND)
    return 0


def _in_comment(source: Source, start: int, end: int) -> set[int]:
    """The offsets between `start` and `end` that a comment holds."""
    held: set[int] = set()
    for at, to in source.reading.comments:
        if to > start and at < end:
            held.update(range(max(at, start), min(to, end)))
    return held


def _past_blanks(text: str, at: int, end: int, comments: set[int]) -> int:
    """Where a cell's source starts, past the spaces, the comments and the rules before it:
    a `\\multicolumn` on the line after a comment or an `\\hline` still opens its cell."""
    while at < end:
        rule = _RULE.match(text, at, end)
        if rule is not None:
            at = rule.end()
        elif text[at] in " \t\r\n" or at in comments:
            at += 1
        else:
            break
    return at


def _cell(text: str, view: str, start: int, end: int) -> TableCell:
    """One cell: its printed text, its span, and the line its text starts on."""
    printed = list(view[start:end])
    for rule in _RULE.finditer(text, start, end):
        for index in range(rule.start() - start, rule.end() - start):
            printed[index] = NUL
    shown = "".join(printed)
    first = len(shown) - len(shown.lstrip(_BLANK))
    spanned = _SPAN.match(text, start, end)
    return TableCell(
        text=" ".join(shown.replace(NUL, "").split()),
        line=text.count("\n", 0, start + first) + 1,
        span=int(spanned.group(1)) if spanned and int(spanned.group(1)) > 0 else 1,
    )
