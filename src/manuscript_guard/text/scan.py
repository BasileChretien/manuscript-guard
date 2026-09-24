"""One pass that finds fenced blocks, code spans and HTML comments together.

Each can swallow the others, so none can be found alone. Pandoc reads from the left: a code
span already open runs across a fence line, a comment runs across a listing to its `-->`,
and a fence line either of them swallowed opens nothing. Fences are looked for again once
they end. `fences.py` used to find every fence before anything else and `comments.py` read
what was left, so neither saw what the other had swallowed:

* `<!-- draft`, a fence line, `-->`: the fence line was still an opener and paired with
  the next fence line below, so a `## Results` between them was blanked from the heading
  scan, and the p-value under it read as the alpha chosen in advance;
* a code span holding a fence line: the listing pandoc then found was never looked for, so
  a `<!--` inside it opened a comment and hid the prose after the listing.

What counts, as pandoc 3.9.0.2 reads it (`-f markdown -t native`):

* **A fence** is a line of three or more backticks or tildes, indented at most three
  spaces, closed by the next line of the same character at least as long. What follows
  the fence must be a language word and attributes pandoc can parse, or a raw `{=format}`:
  ```` ```{r, echo=FALSE} ```` is prose. One with no closer is not a fence. One whose line
  a code span or a comment swallowed is not a fence either, and its backticks are ordinary
  text.
* **A fence interrupts a paragraph only with backticks at the margin.** A `~~~` fence, or a
  backtick fence indented one to three spaces, opens only where no paragraph is open: at
  the start, after a blank line, a heading, a rule, a table row, a listing or a comment
  block. After a line of prose, or an inline comment, it is prose. In a list it opens, since
  the list ends there; after a blockquote line only backticks do.
* **A code span** is opened by a run of N backticks and closed by the next run of exactly N,
  which may not lie past a blank line. It may lie past a fence line: the listing becomes
  part of the span. A run with no closer gives up one backtick as text and the rest try
  again, so in `` ```<!--`` `` the last two open a span around `<!--`. Inside a code span a
  backslash is only a backslash.
* **A backslash** outside code escapes the character after it, so `` \\` `` opens nothing
  and neither does `\\<!--`.
* **A comment** runs from `<!--` to the first `-->` after it, across blank lines, backticks
  and listings alike. `<!-->` and `<!--->` open nothing. Nor does a `<!--` whose text holds
  `--`, then HTML whitespace or `!`, then `>`: pandoc's HTML reader ends the comment there,
  finds no `-->`, and prints the whole of it.
* **The front matter** is read apart from the body. Nothing opened on one side of `begin`
  closes on the other, and a NUL stops a comment and a code span: `masking.py` writes one
  over the front matter's machinery, because pandoc reads each rendered value on its own.
  A fence in a value, as in an abstract, is a listing wherever it stands.

Linear in the length of the text, give or take a logarithm. Each fence opener's closer, and
whether it has one at all, is fixed by the lines below it, so it is worked out once; only
whether an opener is still live depends on the scan, and that is asked once, when the scan
reaches it.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

# ---------------------------------------------------------------- fences, line by line

# Up to three spaces of indent; four would be an indented code block, not a fence.
_OPENER = re.compile(r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")

# What pandoc takes after the fence: a raw attribute, `{=latex}`; or a language word, then
# an attribute block that parses whole, each attribute an `#id`, a `.class`, a `key=value`
# or a bare `-`. Anything else and the line is prose, so ```{r, echo=FALSE}, ```{r} and
# ```python title="x" open nothing, and pandoc prints the chunk as a paragraph.
_ATTRIBUTE = (
    r"""(?:\#[\w\-:.]+|\.[A-Za-z][\w\-:.]*"""
    r"""|[A-Za-z][\w\-:.]*=(?:"[^"]*"|'[^']*'|[^\s}]*)|-)"""
)
_INFO = re.compile(
    r"[ \t]*(?:\{[ \t]*=[A-Za-z0-9_-]+[ \t]*\}"
    rf"|[^\s`{{}}]*[ \t]*(?:\{{\s*(?:{_ATTRIBUTE}(?:\s+{_ATTRIBUTE})*)?\s*\}})?)[ \t]*"
)


@dataclass(frozen=True)
class Fence:
    """One fenced block, as offsets into the original text."""

    start: int  # first character of the opening line
    body_start: int  # first character after the opening line's newline
    body_end: int  # first character of the closing line, or end of text
    end: int  # first character after the block
    info: str  # the info string, e.g. "python" or "{=openxml}"

    @property
    def language(self) -> str:
        """The first word of the info string, lowercased. Empty when untagged."""
        stripped = self.info.strip()
        return stripped.split()[0].lower() if stripped else ""

    @property
    def is_raw(self) -> bool:
        """A pandoc raw-attribute block: ```{=openxml}, ```{=html}, ```{=latex}.

        Not a listing at all — pandoc splices its contents into the output format verbatim,
        so the text inside reaches the reader as formatted prose. Reporting it as "a
        language with no lexer" was actively misleading: the advice was to tag the fence,
        which would have made it quieter still.
        """
        return self.info.strip().startswith("{=")


def _closing(line: str) -> tuple[str, int] | None:
    """The character and width of the fences this line could close, or None."""
    stripped = line.strip()
    if not stripped or stripped[0] not in "`~" or set(stripped) != {stripped[0]}:
        return None
    if len(line) - len(line.lstrip(" ")) > 3:
        return None
    return stripped[0], len(stripped)


def _closes(line: str, char: str, width: int) -> bool:
    """Is this line a closing fence for a run of `width` of `char`?

    "At least as long", per CommonMark. Requiring equality is what let a longer closer
    slip past and swallow the prose after it.
    """
    closing = _closing(line)
    return closing is not None and closing[0] == char and closing[1] >= width


@dataclass(frozen=True)
class _Opener:
    line: int  # index into the text's lines
    start: int  # offset of the line
    char: str
    width: int
    at_margin: bool  # no indent: backticks there interrupt a paragraph
    in_front_matter: bool
    info: str


class _Lines:
    """The text's lines, and the fence openers among them that have a closer below.

    The front matter and the body are separate regions: an opener's closer is looked for
    only in its own.
    """

    def __init__(self, text: str, begin: int) -> None:
        self.lines = text.splitlines(keepends=True)
        self.starts: list[int] = []
        offset = 0
        for line in self.lines:
            self.starts.append(offset)
            offset += len(line)
        self.starts.append(offset)
        self.body = bisect_left(self.starts, begin)  # the body's first line

        # The widest line at or below each line that could close a fence, by character, in
        # the same region. A closing line of width w closes every opener of width <= w, so
        # an opener has a closer exactly when the widest one below it is at least as wide.
        # That rejects an opener with none in constant time: every unterminated opener
        # reading to the end of the file is what made the old scanners quadratic, 8,000 of
        # them 55 seconds, and openers each narrower than the last 33 seconds for 400 KB.
        count = len(self.lines)
        widest = {char: [0] * (count + 1) for char in "`~"}
        for below in range(count - 1, -1, -1):
            for char in widest:
                widest[char][below] = 0 if below + 1 == self.body else widest[char][below + 1]
            closing = _closing(self.lines[below].rstrip("\r\n"))
            if closing is not None:
                char, width = closing
                widest[char][below] = max(widest[char][below], width)

        self.openers: list[_Opener] = []
        for index, line in enumerate(self.lines):
            found = _OPENER.match(line.rstrip("\r\n"))
            if found is None:
                continue
            fence, info = found.group("fence"), found.group("info")
            # A backtick fence's info string may not contain a backtick; that construct is
            # inline code, not a fence. Tilde fences have no such restriction.
            if fence[0] == "`" and "`" in info:
                continue
            if not _INFO.fullmatch(info):
                continue
            below = 0 if index + 1 == self.body else widest[fence[0]][index + 1]
            if below < len(fence):
                continue  # no closer: pandoc prints it, and so it stays prose here
            self.openers.append(
                _Opener(
                    line=index,
                    start=self.starts[index],
                    char=fence[0],
                    width=len(fence),
                    at_margin=not found.group("indent"),
                    in_front_matter=index < self.body,
                    info=info,
                )
            )

    def line_of(self, offset: int) -> int:
        return bisect_right(self.starts, offset) - 1

    def fence_at(self, opener: _Opener) -> tuple[Fence, int]:
        """The block `opener` opens, and the index of its closing line.

        Its closer exists, in its own region; the block ends at the first one.
        """
        index = opener.line + 1
        while not _closes(self.lines[index].rstrip("\r\n"), opener.char, opener.width):
            index += 1
        fence = Fence(
            start=opener.start,
            body_start=self.starts[opener.line + 1],
            body_end=self.starts[index],
            end=self.starts[index + 1],
            info=opener.info,
        )
        return fence, index


# ---------------------------------------------------------------- what is open below a line

# After each line of the body, what is still open: nothing, a paragraph, a blockquote or a
# list. A `~~~` fence, or backticks off the margin, open only where no paragraph is. Pandoc
# ends a paragraph at a newline only before a blank line or backticks at the margin, so
# anything else is more of the paragraph; a list or a blockquote ends at a fence line of
# either kind, though a blockquote takes tildes in as lazy text.
_NOTHING, _PARAGRAPH, _QUOTE, _LIST = range(4)

_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
# A rule or setext underline, a table row, a fenced div's fence, a link's reference
# definition, or a line of HTML tags alone, which opens or closes a raw HTML block.
_CLOSED = re.compile(
    r"^ {0,3}(?:(?:=+|-+)[ \t]*$|(?:[-*_][ \t]*){3,}$|\||:{3,}|\[(?!\^)[^\]]+\]:"
    r"|(?:</?[A-Za-z][^<>]*>[ \t]*)+$)"
)
# A list item's first line, with any of pandoc's markers, or a definition's.
_MARKER = r"(?:\d+|#|[A-Za-z]|[ivxlcdmIVXLCDM]+)"
_LIST_ITEM = re.compile(
    rf"^ {{0,3}}(?:[-+*]|{_MARKER}[.)]|\({_MARKER}\)|\(?@[\w-]*\)?|[:~])(?:[ \t]|$)"
)
_QUOTED = re.compile(r"^ {0,3}>")
# Four spaces or a tab: an indented code block where nothing is open, more prose where
# a paragraph is.
_INDENTED = re.compile(r"^(?: {4}|\t)")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


# ---------------------------------------------------------------- inline, left to right

# Everything inline that can decide what a `<!--` or a fence line is, in one alternation so
# the leftmost wins: an escape, a run of backticks, or a comment's opener.
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


# ---------------------------------------------------------------- the pass


@dataclass(frozen=True)
class Scan:
    """What one pass over a text found: the listings, and the comments pandoc drops."""

    fences: list[Fence]
    comments: list[tuple[int, int]]


class _Pass:
    def __init__(self, text: str, begin: int, view: str) -> None:
        self.view = view
        self.begin = begin
        self.lines = _Lines(text, begin)
        self.barriers = [found.start() for found in _NUL.finditer(view)]
        if begin:
            self.barriers = sorted([*self.barriers, begin])
        stops = [found.start() for found in _BLANK_LINE.finditer(view)]
        self.runs = _Runs(view, sorted(stops + self.barriers))
        self.closes = _Next(_CLOSE, view)
        self.early = _Next(_EARLY_END, view)
        self.fences: list[Fence] = []
        self.comments: list[tuple[int, int]] = []
        self.closing_lines: set[int] = set()  # the closing line of each listing taken
        # Lines on which a comment block ends: one opened at the margin where nothing was
        # open, as pandoc's raw HTML blocks are.
        self.block_comment_ends: dict[int, int] = {}
        self.open_after: list[int | None] = [None] * len(self.lines.lines)

    def _settled(self, index: int) -> int | None:
        """What is open after line `index`, if the line decides it without the one above."""
        lines = self.lines
        line = lines.lines[index].rstrip("\r\n")
        if not line.strip() or index in self.closing_lines:
            return _NOTHING
        end = self.block_comment_ends.get(index)
        if end is not None and not self.view[end : lines.starts[index + 1]].strip():
            return _NOTHING
        if _HEADING.match(line) or _INDENTED.match(line):
            return None
        if _CLOSED.match(line):
            return _NOTHING
        if _LIST_ITEM.match(line):
            return _LIST
        if _QUOTED.match(line):
            return _QUOTE
        return None

    def _follows(self, index: int, above: int) -> int:
        """What is open after line `index`, which carries on from `above`."""
        line = self.lines.lines[index].rstrip("\r\n")
        if _HEADING.match(line) or _INDENTED.match(line):
            # A heading or an indented code block where nothing was open; more of whatever
            # was, otherwise.
            return _NOTHING if above == _NOTHING else above
        return _PARAGRAPH if above in (_NOTHING, _PARAGRAPH) else above  # lazy text

    def open_below(self, index: int) -> int:
        """What is still open after line `index` of the body.

        Worked out once per line and remembered: every line up to the scan's position is
        settled by then, so the answer cannot change later.
        """
        pending: list[int] = []
        known = _NOTHING
        while index >= self.lines.body:
            remembered = self.open_after[index]
            if remembered is not None:
                known = remembered
                break
            settled = self._settled(index)
            if settled is not None:
                self.open_after[index] = known = settled
                break
            pending.append(index)
            index -= 1
        for line in reversed(pending):
            known = self._follows(line, known)
            self.open_after[line] = known
        return known

    def opens(self, opener: _Opener) -> bool:
        if opener.in_front_matter or (opener.char == "`" and opener.at_margin):
            return True  # backticks at the margin interrupt a paragraph
        above = self.open_below(opener.line - 1)
        if above in (_NOTHING, _LIST):
            return True
        if opener.char == "~":
            return False
        # Backticks off the margin. Pandoc reads a list item's text with the item's indent
        # taken off, so backticks as far in as the prose above them are at that margin, and
        # interrupt it; further in than the prose, they are more of it.
        prose = self.lines.lines[opener.line - 1]
        indent = _indent(self.lines.lines[opener.line])
        return above == _QUOTE or _indent(prose) >= indent

    def comment(self, start: int, end: int) -> int:
        """Where reading resumes after the `<!--` at `start:end`, recording the comment."""
        view = self.view
        close = self.closes.at_or_after(end)
        if close == -1 or view.startswith((">", "->"), end):
            return end
        barrier = bisect_left(self.barriers, end)
        if barrier < len(self.barriers) and self.barriers[barrier] < close:
            return end
        cut = self.early.at_or_after(end)
        if cut != -1 and cut < close:
            return end
        self.comments.append((start, close + 3))
        line = self.lines.line_of(start)
        if (
            line >= self.lines.body
            and self.lines.starts[line] == start
            and self.open_below(line - 1) == _NOTHING
        ):
            self.block_comment_ends[self.lines.line_of(close + 3)] = close + 3
        return close + 3

    def run(self) -> Scan:
        view = self.view
        openers = self.lines.openers
        position = 0
        upcoming = 0  # the first opener not yet passed
        while True:
            while upcoming < len(openers) and openers[upcoming].start < position:
                upcoming += 1  # its line was swallowed: not a fence after all
            limit = openers[upcoming].start if upcoming < len(openers) else len(view)
            token = _TOKEN.search(view, position, limit)
            if token is not None:
                start, end = token.span()
                if view[start] == "\\":
                    position = end
                elif view[start] == "`":
                    position = self.runs.skip(start, end)
                else:
                    position = self.comment(start, end)
                continue
            if upcoming == len(openers):
                return Scan(fences=self.fences, comments=self.comments)
            opener = openers[upcoming]
            upcoming += 1
            if self.opens(opener):
                fence, closing = self.lines.fence_at(opener)
                self.fences.append(fence)
                self.closing_lines.add(closing)
                position = fence.end
            else:
                position = opener.start  # prose: its backticks are read like any others


def scan(text: str, begin: int = 0, view: str | None = None) -> Scan:
    """Every listing, and every comment pandoc drops, in one pass over `text`.

    `begin`, the start of a line, is where the body starts after the front matter: nothing
    opened before it closes after it. `view` is the same text with NUL wherever a comment
    or a code span may not run across, as `masking.py` writes over the front matter's
    machinery; lines are read from `text`. Offsets are into both.
    """
    return _Pass(text, begin, text if view is None else view).run()


__all__ = ["Fence", "Scan", "scan"]
