"""Where the HTML comments are. One implementation, scanned left to right.

There were three copies of `<!--.*?-->` — in `masking.py`, `sections.py` and
`placeholders.py` — and they shared two faults.

**They did not know about code.** Pandoc prints `` `<!--` `` as code, not as the start of
a comment. The regex took it for one and hid everything up to the next `-->`, so

    We stripped `<!--` markers. The ROR was 9.99.

    Note: `-->` closes.

printed the ROR while G2, the audit, the heading scan and the binding parser all read
nothing between the two markers. The audit reported 0 numeric tokens and `--strict` passed.
Code spans, raw HTML and fenced blocks each start where they start, and whichever starts
first wins, so the only way to know is to read from the left.

**And they backtracked.** Every `<!--` with no `-->` after it read to the end of the text:
5,000 of them kept `mask` busy for over two minutes.

What counts, as pandoc 3.9.0.2 reads it (`-f markdown -t native`):

* A run of N backticks opens a code span closed by the next run of exactly N, which may
  not lie past a blank line. It may lie past a fence line: a fence interrupts a paragraph,
  but not a code span that is already open, and the listing becomes part of the span. A
  run with no closer gives up one backtick as text and the rest try again: in
  `` ```<!--`` `` the last two open a span around `<!--`. Inside a code span a backslash
  is only a backslash.
* A backslash outside code escapes the character after it, so `` \\` `` opens nothing and
  neither does `\\<!--`.
* A fenced block that starts first is code, and a `<!--` inside it opens nothing. A comment
  that starts first runs to its `-->`, even one inside what would have been a listing.
* `<!--` opens a comment that runs to the first `-->` after it, across blank lines and
  backticks alike. `<!-->` and `<!--->` open nothing. Nor does a `<!--` whose text holds
  `--` then whitespace or `!` then `>`: pandoc's HTML reader ends the comment there, finds
  no `-->`, and prints the whole of it.
* A NUL stops a comment and a code span. `masking.py` writes one over the front matter's
  machinery, because pandoc reads each rendered value on its own: a `<!--` in the title
  does not run on to the first `-->` in the body.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence

from manuscript_guard.text.fences import Fence, fenced_spans

# Everything that can decide whether a `<!--` is a comment, in one alternation, so the
# leftmost wins: an escape, a run of backticks, or the opener itself. Fenced blocks are the
# other contender, and are found by `fenced_spans`.
_TOKEN = re.compile(r"\\[\s\S]|`+|<!--")
_RUN = re.compile(r"`+")
_BLANK_LINE = re.compile(r"\n(?=[ \t\r]*\n)")
_NUL = re.compile("\x00")
_CLOSE = re.compile("-->")
# HTML's whitespace, not Python's: a no-break space there does not end the comment.
_EARLY_END = re.compile(r"--(?:[ \t\n\f\r]+|!)>")


class _Next:
    """The first match of `pattern` at or after an offset, for offsets that only grow.

    Remembered between calls, so a text full of openers that never close is still read
    once: a later opener asks again only once it has passed the last answer.
    """

    def __init__(self, pattern: re.Pattern[str], text: str) -> None:
        self._pattern = pattern
        self._text = text
        self._found: int | None = None

    def at_or_after(self, offset: int) -> int:
        """Where the next match starts, or -1 if there is none."""
        if self._found is None or -1 < self._found < offset:
            match = self._pattern.search(self._text, offset)
            self._found = -1 if match is None else match.start()
        return self._found


class _Runs:
    """Every run of backticks, indexed so that "the next run of exactly N" is a lookup.

    Scanning forward for a closer is what made the naive version quadratic: a paragraph of
    backtick runs that never close read to the paragraph's end once per backtick.
    """

    def __init__(self, text: str, stops: list[int]) -> None:
        self._starts: dict[int, list[int]] = {}
        for run in _RUN.finditer(text):
            self._starts.setdefault(run.end() - run.start(), []).append(run.start())
        self._stops = stops

    def skip(self, start: int, end: int) -> int:
        """Where reading resumes after the backticks at `start:end`.

        Past the code span they open, if they open one; past the run if no part of it does.
        The whole run is tried first and then one backtick shorter each time, as pandoc
        does. Each try is a lookup, so a run of any length costs no more than its length.
        """
        index = bisect_left(self._stops, end)
        stop = self._stops[index] if index < len(self._stops) else None
        for opener in range(start, end):
            width = end - opener
            starts = self._starts.get(width, [])
            found = bisect_left(starts, end)
            # Runs are maximal, so a longer run inside the span is never taken for a closer.
            if found < len(starts) and (stop is None or starts[found] < stop):
                return starts[found] + width
        return end


def comment_spans(text: str, fences: Sequence[Fence] | None = None) -> list[tuple[int, int]]:
    """Every HTML comment pandoc drops from `text`, as (start, end) offsets, in order.

    `text` is the source with its fenced blocks in place; `fences` are those blocks, found
    here if not given. Linear in the length of the text, give or take a logarithm.
    """
    if "<!--" not in text:
        return []
    if fences is None:
        fences = fenced_spans(text)
    nuls = [found.start() for found in _NUL.finditer(text)]
    stops = [found.start() for found in _BLANK_LINE.finditer(text)]
    runs = _Runs(text, sorted(stops + nuls))
    closes = _Next(_CLOSE, text)
    early = _Next(_EARLY_END, text)

    spans: list[tuple[int, int]] = []
    position = 0
    upcoming = 0  # the first fence not yet passed
    while True:
        while upcoming < len(fences) and fences[upcoming].start < position:
            upcoming += 1  # opened inside a comment or a code span: not a fence after all
        limit = fences[upcoming].start if upcoming < len(fences) else len(text)
        token = _TOKEN.search(text, position, limit)
        if token is None:
            if upcoming == len(fences):
                return spans
            position = fences[upcoming].end  # the fence started first
            continue

        start, end = token.span()
        if text[start] == "\\":
            position = end
        elif text[start] == "`":
            position = runs.skip(start, end)
        else:
            close = closes.at_or_after(end)
            if close == -1 or text.startswith((">", "->"), end):
                position = end
                continue
            stop = bisect_left(nuls, end)
            if stop < len(nuls) and nuls[stop] < close:
                position = end
                continue
            cut = early.at_or_after(end)
            if cut != -1 and cut < close:
                position = end
                continue
            spans.append((start, close + 3))
            position = close + 3


# The start of a block pandoc reads apart from the text around it, comments and code spans
# included: a list item, an example, a definition, a footnote, a line of a line block, each
# behind any quotation marks. Its first line, and the lines under it up to a blank line.
_QUOTES = re.compile(r"(?:[ \t]*>)+")
_ITEM = re.compile(
    r"[ \t]*(?:(?:[*+:~-]|\(?(?:\d{1,9}|#|@[\w-]*|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]"
    r"|\[\^[^\]\n]*\]:)(?:[ \t]|$)|\|)"
)
# A line that ends such a block, or may: blank, or blank but for quotation marks, a fence,
# a div's `:::` or a closing tag.
_BREAK = re.compile(r"[ \t>]*(?:$|```|~~~|:::|</)")
# A list item's marker, its tabs expanded: the item's text starts past the spaces after it.
_LIST = re.compile(r" *(?:[*+-]|\(?(?:\d{1,9}|#|@[\w-]*|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)])(?= |$)")


def _text_column(body: str) -> int | None:
    """The column a list item's text starts at, as pandoc's `rawListItem` places it: past
    the marker and the spaces after it, or one space past the marker when more than four
    follow; None when `body` is not a list item's line."""
    expanded = body.expandtabs(4)
    marker = _LIST.match(expanded)
    if marker is None:
        return None
    rest = expanded[marker.end() :]
    gap = len(rest) - len(rest.lstrip(" "))
    return marker.end() + (gap if rest.strip(" ") and gap <= 4 else min(gap, 1))


def _indent(text: str) -> int:
    expanded = text.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _blocks(lines: list[str], held: list[int | None]) -> list[tuple[int, int]]:
    """The runs of `lines`, as [first, last), that pandoc may read apart from the rest. They
    are cut short rather than long wherever pandoc's reading was not worth modelling: every
    marker starts one, even where pandoc reads the line as text, and a blank line ends one,
    even where an item's indented lines go on. A term, the line over a definition, is one.

    Two exceptions, each where pandoc's reading is known. Inside a comment a list item
    opened, `held[i]` being the line it opened on, a line at or past the item's text is the
    item's: pandoc ends the item only at a marker short of it, so a sub-list commented out
    stays in the item. Not for an item on a line that may continue a deeper quotation since
    the last blank line, which is an item of the quotation's list. And the `|` lines of a
    table or a line block end at a line at the margin, which at the top level starts
    afresh: a `<!--` under a table's last row is not the table's."""
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    kind = ""  # "list" for a list item, "bar" for a `|` line, "tail" for lines under one
    top = False  # the `|` lines stand at the top level, where the margin starts afresh
    column = 0  # where the list item's text starts
    depth = 0  # the `>` the open block starts behind; a `>` line goes on with a quoted one
    context = 0  # the deepest quotation since the last blank line, which lines may continue
    resumes = False  # an item's lines may go on, indented, after a blank line
    blank = True  # the line above is blank, or there is none
    last = -1  # the last line that is not a break

    def close(at: int) -> None:
        nonlocal start, kind
        if start is not None and start < at:
            blocks.append((start, at))
        start, kind = None, ""

    def goes_on(line: str, quotes: re.Match[str] | None, deep: int) -> bool:
        if not depth:
            return _indent(line) >= column
        return deep == depth and quotes is not None and _indent(line[quotes.end() :]) >= column

    for index, line in enumerate(lines):
        quotes = _QUOTES.match(line)
        deep = line[: quotes.end()].count(">") if quotes else 0
        alone = deep > 0 and not line.strip(" \t>")
        if _BREAK.match(line) and not alone:
            was_open = start is not None
            close(index)
            blank = not line.strip(" \t")
            if was_open and not blank:
                start = index + 1  # the lines after a fence or a tag may go on with the item
            context = 0 if blank else context
            continue
        context = max(context, deep)
        indented = line[:1] in (" ", "\t")
        body = line[quotes.end() :] if quotes else line
        pipe = body.lstrip(" \t")[:1] == "|"
        if kind == "tail" and indented and not pipe and not _ITEM.match(body):
            blank, last = False, index
            continue
        if alone or (kind in ("bar", "tail") and indented and not pipe):
            # A `>` alone is a blank line in a quotation, which ends an item there, or text
            # continuing an item; and a line indented under a `|` line goes on with a line
            # block, or opens a block after a table, a marker an item. Either way what came
            # before ends here, and what follows is read as a block the margin ends.
            close(index)
            start, depth, kind = index, deep, "tail" if not alone else ""
            blank, last = False, index
            continue
        opened = held[index]
        inside = kind == "list" and start is not None and opened is not None and opened >= start
        if inside and goes_on(line, quotes, deep):
            blank, last = False, index
            continue
        if pipe:
            # A line block or a table's row, which a line at the margin ends. At the top
            # level that line starts afresh; after a `|` line that may be text continuing
            # an item, it may be the item's too.
            if kind not in ("bar", "tail"):
                top = start is None and not (resumes and indented)
            close(index)
            start, kind, depth = index, "bar", deep
            resumes = False if top else resumes
            blank, last = False, index
            continue
        if _ITEM.match(body):
            if body.lstrip(" \t")[:1] in ":~" and last >= 0:
                close(last)
                if blocks and blocks[-1][0] <= last < blocks[-1][1]:
                    first, _end = blocks.pop()
                    blocks += [(first, last)] if first < last else []
                blocks.append((last, last + 1))
            # A marker on a line continuing a deeper quotation is an item of its list.
            text = _text_column(body) if deep >= context else None
            close(index)
            start, depth, resumes = index, deep, True
            kind, column = ("list", text) if text is not None else ("", 0)
        elif quotes:
            if start is None or not depth:
                close(index)
                start, depth, resumes = index, deep, False
        elif kind == "bar" and not indented:
            close(index)
            if top:
                resumes = False
            else:
                start = index  # it may continue the item the `|` line was text in
        elif kind == "tail" and not indented:
            close(index)
            start = index  # it ends a line block, or goes on with what followed a table
        elif blank:
            close(index)
            if resumes and indented:
                start, depth = index, 0
            else:
                resumes = False
        blank, last = False, index
    close(len(lines))
    return blocks


def unclear_comment_lines(text: str) -> list[int]:
    """The lines, numbered from 1, where a comment the gates mask opens in a block pandoc
    reads on its own, and reading that block alone does not find it.

    Pandoc reads a list item, a quotation, a definition, a footnote and a line block apart,
    to where the block ends, and a comment or a code span opened in one ends with it. So a
    `<!--` straight under a list item's line is text continuing the item, and when its
    `-->` lies past a blank line pandoc prints the comment, numbers and all, where the
    gates had masked it. And a backtick in one item pairs, to the gates, with one opening
    `` `<!--` `` in the next, where pandoc prints the comment as text after the code. The
    blocks are found as `_blocks` finds them, cut short where unsure, so a comment the
    gates read on past one is refused rather than guessed at, even where pandoc reads on too.
    """
    from manuscript_guard.text.masking import front_matter_end, html_comments

    comments = html_comments(text)
    if not comments:
        return []
    begin = front_matter_end(text)
    lines = text[begin:].split("\n")
    starts = [begin]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    # For each line a comment is open at the start of, the line it opened on.
    held: list[int | None] = [None] * len(lines)
    for start, end in comments:
        if start >= begin:
            first = bisect_right(starts, start) - 1
            for inside in range(first + 1, min(bisect_left(starts, end), len(lines))):
                held[inside] = first
    blocks = [
        (starts[first], starts[last] - 1)
        for first, last in _blocks([line.replace("\r", "") for line in lines], held)
    ]
    firsts = [first for first, _last in blocks]
    above = text.count("\n", 0, begin)
    read: dict[int, list[tuple[int, int]]] = {}
    found: list[int] = []
    for start, end in comments:
        index = bisect_right(firsts, start) - 1
        if index < 0 or start >= blocks[index][1]:
            continue
        low, high = blocks[index]
        if index not in read:
            read[index] = [(low + a, low + b) for a, b in comment_spans(text[low:high])]
        # The comments found in the block alone are sorted and apart: the one that could
        # hold this one is the last to open at or before it.
        alone = read[index]
        holder = bisect_right(alone, (start, len(text))) - 1
        if holder < 0 or end > alone[holder][1]:
            found.append(above + bisect_right(starts, start))
    return sorted(set(found))


__all__ = ["comment_spans", "unclear_comment_lines"]
