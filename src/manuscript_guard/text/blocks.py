"""Which lines pandoc starts a block on, and so which `#` lines are headings.

A heading is a line that starts a block, and pandoc's markdown reader (`blank_before_header`)
does not let one interrupt a paragraph. So

    ## Results

    The excess was significant
    ## Methods
    (p < 0.001).

is one paragraph under Results, with "## Methods" printed in it as text. Scanning for `^#`
wherever it stood took that line for a Methods heading, and the p-value under it passed G2 as
the alpha chosen in advance. A setext title is the same, and so is a line continuing a list
item or a block quote.

The rule is not "a blank line before", though. A heading directly under a table, a fenced
listing, a fenced div, an HTML comment, a thematic break or another heading needs none, and
asking for one would lose a real `## Results` written straight under a Methods table: the
same hole from the other side. So this walks the document a line at a time and carries what
the line above left open (a paragraph, a list item, a block quote), plus what it takes to
know that (an open list, an open div). Each construct it knows is checked against pandoc in
`tests/test_pandoc_agreement.py`; one it does not know reads as paragraph text.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from manuscript_guard.text.fences import blank_fences, fenced_spans
from manuscript_guard.text.masking import FRONTMATTER
from manuscript_guard.text.placeholders import PLACEHOLDER

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def scannable(text: str) -> str:
    """`text` with code fences and HTML comments blanked, offsets preserved.

    `#` is a comment character in Python, R, shell and YAML. Once fenced code stopped being
    masked — correctly, because it renders — an ordinary comment inside a listing became a
    heading:

        ## Methods
        ```python
        # Methods          <- level 1, so it *pops* the real level-2 Methods
        ```
        ## Results
        The excess was significant (p < 0.001).   <- nests under the fake heading

    `is_methods` looks at the whole enclosing chain, so a threshold in the Results was
    accepted as the alpha chosen in advance. No attacker required: that is a comment
    character in a code block. An HTML comment does the same thing while being invisible in
    the rendered document, which is worse.

    Blanked rather than removed, because callers index back into the original text.
    Newlines are kept so line numbers and `^` anchors still line up.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    # Front matter too, now that setext headings are recognised: its closing `---` sits
    # directly under a YAML line, which would otherwise read as `key: value` underlined —
    # a level-2 heading conjured out of the document's own delimiter. It is found in the
    # text as written, as the build and `mask` find it, and fences and comments are looked
    # for only after it. Blanked first, a comment on the YAML's first line read as a blank
    # line after the opening `---`, which is not front matter, so a `# Methods` in the YAML
    # headed a body the build printed without it.
    opening = FRONTMATTER.match(text)
    rest = _HTML_COMMENT.sub(blank, blank_fences(text[opening.end() if opening else 0 :]))
    return blank(opening) + rest if opening else rest


@dataclass(frozen=True)
class Heading:
    #: Where the heading's first line starts: the `#` line, or a setext heading's title.
    start: int
    level: int
    title: str
    setext: bool = False


# The shape of an ATX heading line. Whether one is a heading depends on the line above. `[ \t]`
# where `\s` used to be: `\s+` crossed the line break, so a lone `#`, which pandoc prints as an
# empty heading, took the line below it for its title.
ATX_LINE = re.compile(r"^(?P<hashes>#{1,6})(?:[ \t]+(?P<title>.*?))?[ \t]*#*[ \t]*$")

# Setext: a title underlined with `=` (level 1) or `-` (level 2). One dash is enough for
# pandoc, and requiring three left a "Results" heading under `--` invisible, so its content
# inherited the Methods chain above. Pandoc tries this before ATX and takes any line as the
# title, `## Methods` and `> Methods` included, so nothing is excluded from the title here.
_UNDERLINE = re.compile(r"^(?:=+|-+)[ \t]*$")

_THEMATIC_BREAK = re.compile(r"^[ ]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_LIST_ITEM = re.compile(
    r"^(?P<marker>[ ]{0,3}(?:[-*+]|\d{1,9}[.)]|\(\d{1,9}\)|#[.)]|[a-z][.)]|\([a-z]\)))"
    r"(?P<gap>[ \t]+|$)"
)
_QUOTE = re.compile(r"^[ ]{0,3}>")
_DIV_OPEN = re.compile(r"^:{3,}[ \t]*[^\s:]")
_DIV_CLOSE = re.compile(r"^:{3,}[ \t]*$")
_TABLE_RULE = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_GRID_OR_LINE_BLOCK = re.compile(r"^[ ]{0,3}[|+]")
_CONTINUATION = re.compile(r"^[ \t]+\S")
_CAPTION = re.compile(r"^[ ]{0,3}(?:[Tt]able:|:(?![^\w\s]))")
_REFERENCE = re.compile(r"^[ ]{0,3}\[(?!\^)[^\]]+\]:")

# Tags pandoc will not read inline. A line starting with one ends a paragraph and is a block.
_BLOCK_TAGS = (
    "address|article|aside|blockquote|body|canvas|caption|center|col|colgroup|dd|details|dir|"
    "div|dl|dt|fieldset|figcaption|figure|footer|form|h[1-6]|head|header|hgroup|hr|html|li|"
    "main|menu|meta|nav|noscript|ol|p|pre|script|section|style|summary|table|tbody|td|tfoot|"
    "th|thead|tr|ul"
)
_BLOCK_TAG = re.compile(rf"^[ ]{{0,3}}</?(?:{_BLOCK_TAGS})(?=[\s/>]|$)", re.IGNORECASE)

# Raw LaTeX. A line of nothing but commands is a block unless a command is one pandoc reads
# inline, so `\newpage` over `# References` leaves the heading a heading, and `\textbf{Note}`
# over `# Methods` does not. `\begin{...}` holds everything up to its `\end{...}`, and ends a
# paragraph it starts under.
_TEX_COMMAND = re.compile(
    r"\\(?P<name>[A-Za-z]+)\*?(?:\[[^\]\n]*\]|\{(?:[^{}\n]|\{[^{}\n]*\})*\})*[ \t]*"
)
_TEX_BEGIN = re.compile(r"^\\begin\{(?P<env>[^}\n]+)\}")
_TEX_INLINE = frozenset(
    {
        "emph", "underline", "uline", "sout", "noindent", "newline", "url", "href", "label",
        "ref", "eqref", "autoref", "cref", "Cref", "pageref", "nameref", "footnote",
        "footnotemark", "includegraphics", "mbox", "hbox", "fbox", "ensuremath", "LaTeX",
        "TeX", "ldots", "dots", "today", "hyperref", "hyperlink", "hypertarget",
    }
)


def _tex_block(line: str) -> bool:
    """A line of nothing but LaTeX commands, none of which pandoc reads inline."""
    stripped = line.rstrip()
    position = 0
    for command in _TEX_COMMAND.finditer(stripped):
        if command.start() != position:
            return False
        name = command.group("name")
        if name in ("begin", "end") or name in _TEX_INLINE:
            return False
        if name.startswith(("text", "cite")) or name.endswith("cite"):
            return False
        position = command.end()
    return position > 0 and position == len(stripped)


def _lone_table(line: str) -> bool:
    """A line that is only a `{{table.x}}` placeholder. The build puts a pipe table there, and
    a table ends at its last row, so what follows starts a block. Read as prose, the line
    hid a heading directly under it that the document prints. With a caption the build ends
    the table on the caption instead, which a heading does continue: see Known gaps."""
    found = PLACEHOLDER.fullmatch(line.strip())
    return found is not None and found.group("ns") == "table"


@dataclass(frozen=True)
class _Line:
    start: int
    #: The line as the scan sees it: fences, comments and front matter blanked, no `\r`.
    shown: str
    #: Blank in the source, not merely blanked. A comment inside a paragraph is blanked and
    #: the paragraph goes on; a blank line ends it.
    blank: bool


def _lines(text: str) -> list[_Line]:
    out = []
    offset = 0
    for source, shown in zip(text.split("\n"), scannable(text).split("\n"), strict=True):
        out.append(_Line(offset, shown.rstrip("\r"), not source.strip()))
        offset += len(source) + 1
    return out


def _fences(text: str, lines: list[_Line]) -> dict[int, tuple[int, str, bool]]:
    """Each fence's opening line: its closing line, its character, and whether indented."""
    starts = [line.start for line in lines]
    found = {}
    for fence in fenced_spans(text):
        first = bisect_right(starts, fence.start) - 1
        last = bisect_right(starts, fence.end - 1) - 1
        opener = text[fence.start : fence.body_start]
        found[first] = (last, opener.lstrip(" ")[:1], opener.startswith(" "))
    return found


# What the line above left open, which decides what the next line can be. Each carries on
# through a `#` line or an underline, and each stops somewhere different:
#
#   _PARAGRAPH  at a blank line, a backtick fence, a block-level HTML tag, a LaTeX
#               environment, or the fence closing its div;
#   _QUOTE_LINES  a block quote's lazy lines: at a blank line or a backtick fence. The rest is
#               the quotation's own, and a heading in it is quoted, not this paper's;
#   _ITEM       a list item's lazy lines: at a blank line or any fence. The rest is nested in
#               the item.
_PARAGRAPH, _QUOTE_LINES, _ITEM = "paragraph", "quote", "item"


class _Walk:
    """One pass over a document, remembering what the line above left open."""

    def __init__(self, text: str) -> None:
        self.lines = _lines(text)
        self.fences = _fences(text, self.lines)
        self.found: list[Heading] = []
        self.open: str | None = None
        #: The column an open list item's content starts at; None outside a list.
        self.list_indent: int | None = None
        self.divs = 0
        self._ends: dict[str, list[int]] | None = None

    def run(self) -> list[Heading]:
        index = 0
        while index < len(self.lines):
            index = self._step(index)
        return self.found

    def _step(self, index: int) -> int:
        fence = self.fences.get(index)
        if fence is not None:
            return self._fence(*fence)
        line = self.lines[index]
        if not line.shown.strip():
            if line.blank:
                self.open = None
            return index + 1
        if self.open is not None and self._continues(index):
            return index + 1
        self.open = None
        return self._block(index)

    def _fence(self, last: int, char: str, indented: bool) -> int:
        # A backtick fence interrupts a paragraph. A tilde one does not: pandoc prints it as
        # text inside the paragraph, which goes on past it. Either one ends a list item.
        if not (self.open in (_PARAGRAPH, _QUOTE_LINES) and char == "~"):
            self.open = None
            if not indented:
                self.list_indent = None
        return last + 1

    def _continues(self, index: int) -> bool:
        """Whether a line carries on what the line above left open. See `_PARAGRAPH`."""
        shown = self.lines[index].shown
        if self.divs and _DIV_CLOSE.match(shown):
            return False
        if self.open != _PARAGRAPH:
            return True
        return not _BLOCK_TAG.match(shown) and self._environment(index) is None

    def _block(self, index: int) -> int:
        if self.list_indent is not None and self._in_list(self.lines[index].shown):
            return index + 1
        for opens in (self._container, self._heading, self._leaf):
            after = opens(index)
            if after is not None:
                return after
        self.open = _PARAGRAPH
        return index + 1

    def _in_list(self, shown: str) -> bool:
        """An indented line under a list item belongs to it: a paragraph, or code if it is
        indented four more. Anything else at the margin closes the list."""
        indent = len(shown.expandtabs(4)) - len(shown.expandtabs(4).lstrip())
        if indent == 0:
            if not _LIST_ITEM.match(shown):
                self.list_indent = None
            return False
        self.open = _ITEM if indent < (self.list_indent or 0) + 4 else None
        return True

    def _container(self, index: int) -> int | None:
        """Fenced divs and HTML blocks, which pandoc reads before it looks for a heading."""
        shown = self.lines[index].shown
        if _DIV_OPEN.match(shown):
            self.divs += 1
        elif self.divs and _DIV_CLOSE.match(shown):
            self.divs -= 1
        elif not _BLOCK_TAG.match(shown):
            return None
        return index + 1

    def _heading(self, index: int) -> int | None:
        line = self.lines[index]
        below = self.lines[index + 1] if index + 1 < len(self.lines) else None
        if below is not None and _UNDERLINE.match(below.shown):
            level = 1 if below.shown.startswith("=") else 2
            self.found.append(Heading(line.start, level, line.shown.strip(), setext=True))
            return index + 2
        atx = ATX_LINE.match(line.shown)
        if atx is None:
            return None
        title = (atx.group("title") or "").strip()
        self.found.append(Heading(line.start, len(atx.group("hashes")), title))
        return index + 1

    def _leaf(self, index: int) -> int | None:
        """Blocks that end at their own last line, so a heading may follow with no blank."""
        shown = self.lines[index].shown
        if shown.startswith(("    ", "\t")) or _THEMATIC_BREAK.match(shown):
            return index + 1
        item = _LIST_ITEM.match(shown)
        if item is not None:
            gap = len(item.group("gap"))
            self.list_indent = len(item.group("marker")) + (gap if 0 < gap <= 4 else 1)
            self.open = _ITEM
            return index + 1
        if _QUOTE.match(shown):
            self.open = _QUOTE_LINES
            return index + 1
        if _REFERENCE.match(shown) or _tex_block(shown) or _lone_table(shown):
            return index + 1
        return self._environment(index) or self._table(index)

    def _table(self, index: int) -> int | None:
        """A pipe table runs while its rows have a pipe; a grid table or a line block while
        its lines start with one (or continue the line above, for a line block). A caption
        directly under a table is part of it, and reads on like a paragraph."""
        shown = self.lines[index].shown
        below = self.lines[index + 1].shown if index + 1 < len(self.lines) else ""
        if "|" in shown and "|" in below and _TABLE_RULE.match(below):
            end = index + 2
            while end < len(self.lines) and "|" in self.lines[end].shown:
                end += 1
            return self._caption(end)
        if not _GRID_OR_LINE_BLOCK.match(shown):
            return None
        end = index + 1
        while end < len(self.lines) and (
            _GRID_OR_LINE_BLOCK.match(self.lines[end].shown)
            or _CONTINUATION.match(self.lines[end].shown)
        ):
            end += 1
        return self._caption(end) if shown.lstrip().startswith("+") else end

    def _caption(self, end: int) -> int:
        if end < len(self.lines) and _CAPTION.match(self.lines[end].shown):
            self.open = _PARAGRAPH
            return end + 1
        return end

    def _environment(self, index: int) -> int | None:
        """`\\begin{name}` through its `\\end{name}`, which pandoc passes through raw. An
        environment that never ends is printed, and is not one."""
        begin = _TEX_BEGIN.match(self.lines[index].shown)
        if begin is None:
            return None
        if self._ends is None:
            self._ends = {}
            for number, line in enumerate(self.lines):
                for env in re.findall(r"\\end\{([^}\n]+)\}", line.shown):
                    self._ends.setdefault(env, []).append(number)
        ends = self._ends.get(begin.group("env"), [])
        later = bisect_right(ends, index - 1)
        return ends[later] + 1 if later < len(ends) else None


def find_headings(text: str) -> list[Heading]:
    """Every heading pandoc prints, ATX and setext, in document order."""
    return _Walk(text).run()


__all__ = ["ATX_LINE", "Heading", "find_headings", "scannable"]
