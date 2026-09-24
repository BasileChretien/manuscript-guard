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
  not lie past a blank line or into a fenced block. A run with no closer gives up one
  backtick as text and the rest try again: in `` ```<!--`` `` the last two open a span
  around `<!--`. Inside a code span a backslash is only a backslash.
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
from bisect import bisect_left
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
_EARLY_END = re.compile(r"--(?:\s+|!)>")


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
    runs = _Runs(text, sorted(stops + nuls + [fence.start for fence in fences]))
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


__all__ = ["comment_spans"]
