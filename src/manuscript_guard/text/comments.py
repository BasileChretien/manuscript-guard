"""Where the HTML comments are. One implementation, scanned left to right.

There were three copies of `<!--.*?-->` — in `masking.py`, `sections.py` and
`placeholders.py` — and they shared two faults.

**They did not know about code.** Pandoc prints `` `<!--` `` as code, not as the start of
a comment. The regex took it for one and hid everything up to the next `-->`, so

    We stripped `<!--` markers. The ROR was 9.99.

    Note: `-->` closes.

printed the ROR while G2, the audit, the heading scan and the binding parser all read
nothing between the two markers. The audit reported 0 numeric tokens and `--strict` passed.
Code spans, raw HTML and autolinks have equal precedence, so whichever starts first wins,
and the only way to know which starts first is to read from the left.

**And they backtracked.** Every `<!--` with no `-->` after it read to the end of the text:
5,000 of them kept `mask` busy for over two minutes.

What counts, as pandoc 3.9.0.2 reads it (`-f markdown -t native`):

* A run of N backticks opens a code span closed by the next run of exactly N, which may
  not lie past a blank line. A run with no closer gives up one backtick as text and the
  rest try again: in `` ```<!--`` `` the last two open a span around `<!--`. Inside a code
  span a backslash is only a backslash.
* A backslash outside code escapes the character after it, so `` \\` `` opens nothing and
  neither does `\\<!--`.
* `<!--` opens a comment that runs to the first `-->` after it, across blank lines and
  backticks alike. `<!-->` and `<!--->` open nothing; pandoc prints them.

A fenced block is code too. `blank_comments` sees to that itself; `comment_spans` expects
its caller to have blanked them already, as `mask` has.
"""

from __future__ import annotations

import re
from bisect import bisect_left

from manuscript_guard.text.fences import blank_fences

# Everything that can decide whether a `<!--` is a comment, in one alternation, so the
# leftmost wins: an escape, a run of backticks, or the opener itself.
_TOKEN = re.compile(r"\\[\s\S]|`+|<!--")
_RUN = re.compile(r"`+")

# Where a code span has to stop: a newline that starts a blank line, or a NUL, which `mask`
# leaves where a block was removed — a fenced listing, or the front matter between two
# separately rendered values.
_BREAK = re.compile(r"\n(?=[ \t\r]*\n)|\x00")


class _Runs:
    """Every run of backticks, indexed so that "the next run of exactly N" is a lookup.

    Scanning forward for a closer is what made the naive version quadratic: a paragraph of
    backtick runs that never close read to the paragraph's end once per backtick.
    """

    def __init__(self, text: str) -> None:
        self._starts: dict[int, list[int]] = {}
        for run in _RUN.finditer(text):
            self._starts.setdefault(run.end() - run.start(), []).append(run.start())
        self._breaks = [found.start() for found in _BREAK.finditer(text)]

    def closer(self, after: int, width: int) -> int | None:
        """Where the run closing a span opened by `width` backticks ending at `after` starts.

        Runs are maximal, so a longer run inside the span is never taken for its closer.
        """
        starts = self._starts.get(width, [])
        index = bisect_left(starts, after)
        if index == len(starts):
            return None
        breaks = bisect_left(self._breaks, after)
        if breaks < len(self._breaks) and self._breaks[breaks] < starts[index]:
            return None
        return starts[index]


def comment_spans(text: str) -> list[tuple[int, int]]:
    """Every HTML comment pandoc drops from `text`, as (start, end) offsets, in order.

    `text` must have its fenced blocks blanked already, as `mask` and `blank_fences` do.
    Linear in its length, give or take a logarithm.
    """
    if "<!--" not in text:
        return []
    runs = _Runs(text)
    spans: list[tuple[int, int]] = []
    position = 0
    closable = True  # False once a `<!--` has no `-->` after it: none later can have one

    while (token := _TOKEN.search(text, position)) is not None:
        start, end = token.span()
        lead = text[start]
        if lead == "\\":
            position = end
        elif lead == "`":
            width = end - start
            closer = runs.closer(end, width)
            position = start + 1 if closer is None else closer + width
        elif text.startswith((">", "->"), end):
            position = end
        else:
            close = text.find("-->", end) if closable else -1
            if close == -1:
                closable = False
                position = end
            else:
                spans.append((start, close + 3))
                position = close + 3
    return spans


def blank_comments(text: str) -> str:
    """`text` with every HTML comment replaced by spaces, offsets and newlines preserved.

    Fenced blocks are left as they are, and a `<!--` inside one opens nothing.
    """
    spans = comment_spans(blank_fences(text))
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


__all__ = ["blank_comments", "comment_spans"]
