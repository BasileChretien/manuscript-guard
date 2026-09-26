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
from dataclasses import dataclass, replace

from manuscript_guard.text.attributes import strip_attributes
from manuscript_guard.text.fences import fenced_spans
from manuscript_guard.text.masking import blank, fenced_blocks, front_matter_end, html_comments
from manuscript_guard.text.placeholders import PLACEHOLDER


def _scanned(text: str) -> tuple[str, list[tuple[int, int]]]:
    """`scannable(text)`, and where its comments were in `text`."""
    # Front matter too, now that setext headings are recognised: its closing `---` sits
    # directly under a YAML line, which would otherwise read as `key: value` underlined —
    # a level-2 heading conjured out of the document's own delimiter. It is found in the
    # text as written, as the build and `mask` find it. Blanked first, a comment on the
    # YAML's first line read as a blank line after the opening `---`, which is not front
    # matter, so a `# Methods` in the YAML headed a body the build printed without it.
    #
    # Fences and comments are found in the text as written too, the comments as `mask`
    # finds them (text/comments.py): a `<!--` in inline code opens none, and blanking the
    # comments first made "```<!-- TODO -->" a bare closing fence.
    head = front_matter_end(text)
    fences = fenced_blocks(text)
    comments = html_comments(text, fences)
    spans = [(0, head), *((fence.start, fence.end) for fence in fences), *comments]
    return blank(text, spans), comments


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
    return _scanned(text)[0]


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
#
# Hashes and a space, and nothing more: the title is worked out in Python. A pattern that
# also matched the title and its closing hashes backtracked, cubically, on one heading line of
# spaces: 2,000 of them took 67 s. Any number of hashes: pandoc prints `####### Note` as a
# heading of level 7, and read as a paragraph it swallowed the `## Results` under it.
ATX_LINE = re.compile(r"^(?P<hashes>#+)(?=[ \t]|$)")


def _atx(line: str) -> tuple[int, str] | None:
    """The level and title of an ATX heading line, or None. "# Methods #" and "# C#" are
    titled "Methods" and "C", as pandoc titles them; a lone `#` is an empty heading.

    Titled as pandoc prints them, without an attribute block: pandoc reads the closing `#`s,
    then spaces, then the block, so `## Results ## {#sec-results}` is "Results", and a block
    before the closing `#`s is text, `# Results {-} ##` "Results {-}"."""
    opening = ATX_LINE.match(line)
    if opening is None:
        return None
    rest = line[opening.end() :].strip(" \t")
    printed = strip_attributes(rest)
    title = (rest if printed == rest else printed).rstrip("#").strip()
    return len(opening.group("hashes")), title


def _setext_title(line: str) -> str:
    """A setext title as pandoc prints it: `Methods {#sec-methods}` is "Methods"."""
    return strip_attributes(line.strip(" \t")).strip()

# Setext: a title underlined with `=` (level 1) or `-` (level 2). One dash is enough for
# pandoc, and requiring three left a "Results" heading under `--` invisible, so its content
# inherited the Methods chain above. Pandoc tries this before ATX and takes any line as the
# title, `## Methods` and `> Methods` included, so nothing is excluded from the title here.
_UNDERLINE = re.compile(r"^(?:=+|-+)[ \t]*$")

_THEMATIC_BREAK = re.compile(r"^[ ]{0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
# Pandoc's markers: bullets, numbers (ASCII digits only), letters, roman numerals, `#` and
# example `@`, closed by a full stop or a bracket. A capital and a full stop need two spaces
# after them, so "A. Smith agreed" and "I. Introduction" are prose, and so is a page
# reference, "p. 12".
_ROMAN = r"m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"
_ROMAN_UPPER = _ROMAN.upper()
_LIST_ITEM = re.compile(
    r"^(?P<marker>[ ]{0,3}(?!p\.[ \t]+\d)(?:[-*+]"
    rf"|\((?:[0-9]{{1,9}}|#|[A-Za-z]|(?=[ivxlcdm]){_ROMAN}|(?=[IVXLCDM]){_ROMAN_UPPER}|@[\w-]*)\)"
    rf"|(?:[0-9]{{1,9}}|#|[a-z]|(?=[ivxlcdm]{{2}}){_ROMAN}|(?=[IVXLCDM]{{2}}){_ROMAN_UPPER}"
    r"|@[\w-]*)[.)]"
    r"|[A-Z]\)|[A-Z]\.(?=[ \t]{2}|\t)))"
    r"(?P<gap>[ \t]+|$)"
)
# The shape the walk took for a marker before it read list items, any digit included: `* * *`
# and `１. Note` have it. At the margin under a list, such a line ends the items, and the lines
# under it stay the list's for headings, as they did then. See `_Walk._in_list`.
_MARKER_SHAPE = re.compile(_LIST_ITEM.pattern.replace("[0-9]", r"\d"))
_QUOTE = re.compile(r"^[ ]{0,3}>")
_DIV_CLOSE = re.compile(r"^:{3,}[ \t]*$")
_DIV_RUN = re.compile(r":{3,}[ \t]*")


def _div_open(line: str) -> bool:
    """A fence opening a div: three colons or more, then a class or attributes and nothing
    else but closing colons. "::: note text here" is a paragraph.

    Parsed rather than matched. The class cannot open with a colon, or a bare `::::` read as a
    fence with the class `:`; and as a pattern, colons could be split between the run, the
    class and the closing colons so many ways that 10,000 of them took 29 s to reject.
    """
    run = _DIV_RUN.match(line)
    if run is None:
        return False
    rest = line[run.end() :].rstrip(" \t")
    if rest.startswith("{"):
        closing = rest.find("}")
        if closing == -1 or "\n" in rest[:closing]:
            return False
        tail = rest[closing + 1 :]
    else:
        if not rest or rest[0] in ":{}" or rest[0].isspace():
            return False
        end = next((i for i, ch in enumerate(rest) if ch.isspace() or ch in "{}"), len(rest))
        tail = rest[end:]
    return not tail.lstrip(" \t").strip(":")
_TABLE_RULE = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
# A grid table opens on a border, `+---+---+`, and a line block on a pipe and a space:
# "+12% more reports", "+-0.3 SD" and "|d| exceeded" are prose. Both at the margin: indented,
# pandoc reads either as a paragraph, and a `#` line under it as its text.
_GRID_TOP = re.compile(r"^\+(?:[-=:]+\+)+[ \t]*$")
# A pipe table's row has a pipe that is a cell's edge: not escaped, and not in code or math.
# Taken on any pipe, "Results \| x" over `===` under a table was a row, and the heading
# pandoc prints there was lost to the gates.
_ESCAPED_PIPE = re.compile(r"\\\|")
_CODE_OR_MATH = re.compile(r"`[^`\n]*`|\$[^$\n]*\$")


def _cell_pipe(line: str) -> bool:
    return "|" in _CODE_OR_MATH.sub("", _ESCAPED_PIPE.sub("", line))


_GRID_ROW = re.compile(r"^[+|]")
_LINE_BLOCK = re.compile(r"^\|(?:[ \t]|$)")
_CONTINUATION = re.compile(r"^[ \t]+\S")
_CAPTION = re.compile(r"^[ ]{0,3}(?:[Tt]able:|:(?![^\w\s]))")
# A link definition: a destination, then at most a title and attributes.
# "[@smith2020]: they found it" is prose.
_REFERENCE = re.compile(
    r"""^[ ]{0,3}\[(?!\^)[^\]]+\]:[ \t]*(?:<[^>\n]*>|\S+)"""
    r"""(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^)]*\)))?(?:[ \t]*\{[^}\n]*\})?[ \t]*$"""
)
# A footnote holds what is indented under it, as a list item holds its own. Read as a
# paragraph, it let a `#` line under the note's second paragraph be a heading, which pandoc
# prints inside the note.
_FOOTNOTE = re.compile(r"^[ ]{0,3}\[\^[^\]\n]+\]:")

# HTML, with every tag checked against pandoc 3.9. Block-level tags are never read inline: a
# line starting with one is a block, and a paragraph ends at one. Pandoc's "either" tags are
# a block at the margin and inline inside a paragraph. The verbatim ones hold everything up
# to their closing tag, when there is one.
_BLOCK_TAGS = (
    "address|article|aside|blockquote|body|canvas|caption|center|col|colgroup|dd|details|dir|"
    "div|dl|dt|fieldset|figcaption|figure|footer|form|frameset|h[1-6]|head|header|hgroup|hr|"
    "html|isindex|li|main|menu|meta|nav|noframes|ol|output|p|pre|script|section|summary|"
    "table|tbody|td|textarea|tfoot|th|thead|title|tr|ul"
)
_EITHER_TAGS = (
    "applet|area|audio|button|del|embed|iframe|ins|map|noscript|object|progress|source|style|"
    "svg|video"
)
_VOID_TAGS = frozenset({"area", "col", "embed", "hr", "isindex", "meta", "source"})
_BLOCK_TAG = re.compile(rf"^[ ]{{0,3}}</?(?:{_BLOCK_TAGS})(?=[\s/>]|$)", re.IGNORECASE)
_START_TAG = re.compile(
    rf"^[ ]{{0,3}}</?(?:{_BLOCK_TAGS}|{_EITHER_TAGS})(?=[\s/>]|$)", re.IGNORECASE
)
_A_BLOCK_TAG = re.compile(rf"</?(?:{_BLOCK_TAGS})(?=[\s/>]|$)", re.IGNORECASE)
_HTML_DIV = re.compile(r"^[ ]{0,3}</?div(?=[\s/>]|$)", re.IGNORECASE)
_OPENS = re.compile(rf"^[ ]{{0,3}}<({_BLOCK_TAGS}|{_EITHER_TAGS})(?=[\s/>]|$)", re.IGNORECASE)
_CLOSES = re.compile(rf"</({_BLOCK_TAGS}|{_EITHER_TAGS})\s*>$", re.IGNORECASE)
_VERBATIM = re.compile(r"<(pre|script|style|textarea)(?=[\s>])", re.IGNORECASE)
# What ends a block quote's lazy lines: the closing tag of an HTML block it sits in, at the
# margin.
_QUOTE_STOP = re.compile(rf"^</({_BLOCK_TAGS}|{_EITHER_TAGS})\s*>", re.IGNORECASE)


def _blank(line: str) -> bool:
    """Blank as pandoc means it: spaces and tabs. A no-break space is a character."""
    return not line.strip(" \t\r")


def _indent(line: str) -> int:
    """How far in a line's text starts, in columns, with tab stops every four."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _ends_on_block_tag(line: str, html: dict[str, int]) -> bool:
    """A line whose last tag, closing the line, is block-level, or closes an HTML block
    open around it.

    Pandoc will not read a block-level tag inline, so the paragraph ends where one starts,
    and when it closes the line the next line starts a block: "Last sentence.<hr>" over
    `## Results` leaves the heading a heading. An inline tag after it, "<hr><br>", opens a
    new paragraph, which the `#` line then continues. An "either" tag such as `</ins>` is
    inline in a paragraph, but the one closing the `<ins>` block the paragraph sits in ends
    the paragraph all the same.
    """
    rest = line.rstrip(" \t")
    opening = rest.rfind("<")
    if not rest.endswith(">") or opening == -1:
        return False
    if _A_BLOCK_TAG.match(rest, opening) is not None:
        return True
    closes = _CLOSES.match(rest, opening)
    return closes is not None and html.get(closes.group(1).lower(), 0) > 0


def _html_opens(line: str) -> str | None:
    """The HTML block this line opens at its start, if the line does not close it too."""
    opens = _OPENS.match(line)
    opened = opens.group(1).lower() if opens else None
    if opened in _VOID_TAGS or (opened and f"</{opened}" in line[opens.end() :].lower()):
        return None
    return opened


# A comment indented one to three spaces is inline, where one at the margin is a block.
_INDENTED_COMMENT = re.compile(r"^[ ]{1,3}<!--")

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
        "ref", "eqref", "autoref", "cref", "Cref", "footnote", "footnotemark",
        "includegraphics", "mbox", "hbox", "ensuremath", "LaTeX", "TeX", "ldots", "dots",
        "today", "hyperref", "hyperlink", "index", "em", "bf", "it", "rm", "tt", "S",
        "enquote", "gls", "SI", "si", "num", "ul", "hl", "qty", "unit", "ang", "ac", "acs",
        "acl", "acrshort", "acrlong", "acrfull", "bfseries", "itshape", "colorbox", "vref",
        "P", "copyright",
    }
)
# `\text...` commands are inline, apart from these, which pandoc makes a block of.
_TEX_BLOCK_TEXT = frozenset({"texttrademark"})


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
        if name in _TEX_BLOCK_TEXT:
            pass
        elif name.startswith(("text", "cite")) or name.endswith("cite"):
            return False
        position = command.end()
    return position > 0 and position == len(stripped)


def _bare_tex(line: str) -> bool:
    """A LaTeX block line ending on a command with no argument, `\\newpage` say. Pandoc folds
    the digits that open the next line into the raw block, so "412. Of these" under one is
    no list item: the raw "\\newpage\\n412" and a paragraph ". Of these"."""
    commands = list(_TEX_COMMAND.finditer(line.rstrip()))
    return bool(commands) and not re.search(r"[{\[]", commands[-1].group(0))


_DIGIT_FIRST = re.compile(r"^[ \t]*\d")
# A definition marker, with its text or bare: `:` alone on its line is one too.
_DEFINITION = re.compile(r"^[ ]{0,3}[:~](?:[ \t]|$)")


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
    #: The line as written, without its `\r`. Its indentation is what makes an indented code
    #: block, not the space a blanked comment leaves.
    raw: str = ""
    #: Inside a comment that opened on an earlier line. Pandoc reads a comment in a paragraph
    #: inline, blank lines and all, so nothing in one ends the paragraph.
    commented: bool = False


def _underline(line: _Line) -> bool:
    """A setext underline, as written: `<!-- -->===` is text. With the comment blanked, it
    read as `===`, and the prose above it as a heading."""
    return bool(_UNDERLINE.match(line.shown) and _UNDERLINE.match(line.raw))


def _lines(text: str) -> list[_Line]:
    shown_text, comments = _scanned(text)
    out = []
    offset = 0
    for source, shown in zip(text.split("\n"), shown_text.split("\n"), strict=True):
        out.append(_Line(offset, shown.rstrip("\r"), _blank(source), source.rstrip("\r")))
        offset += len(source) + 1
    starts = [line.start for line in out]
    for opening, closing in comments:
        first = bisect_right(starts, opening)
        last = bisect_right(starts, closing - 1)
        for number in range(first, last):
            out[number] = replace(out[number], commented=True)
    # Where a line starts in a comment and goes on after it, what follows the comment is where
    # the line's text starts: `<!-- x -->## Results` is a heading, and "<!-- note --> The
    # excess" is prose, not a line indented as code.
    for number, line in enumerate(out):
        if (line.commented or line.raw.startswith("<!--")) and not _blank(line.shown):
            out[number] = replace(line, shown=line.shown.lstrip(" "))
    return out


def _fences(text: str, lines: list[_Line]) -> dict[int, tuple[int, str, bool]]:
    """Each fence's opening line: its closing line, its character, and whether indented.

    Looked for only after the front matter, as `scannable` looks: an opener in a YAML value
    paired with a fence in the body, and the walk stepped over every heading between.
    """
    starts = [line.start for line in lines]
    found = {}
    for fence in fenced_spans(text, front_matter_end(text)):
        first = bisect_right(starts, fence.start) - 1
        last = bisect_right(starts, fence.end - 1) - 1
        opener = text[fence.start : fence.body_start]
        found[first] = (last, opener.lstrip(" ")[:1], opener.startswith(" "))
    return found


# What the line above left open, which decides what the next line can be. Each carries on
# through a `#` line or an underline, and each stops somewhere different:
#
#   _PARAGRAPH    at a blank line, a backtick fence at the margin, a block-level HTML tag, a
#                 LaTeX environment, or the fence closing its div;
#   _ITEM         a list item's lazy lines: where a paragraph stops, or at any fence;
#   _QUOTE_LINES  a block quote's lazy lines: at a blank line, a backtick fence at the margin,
#                 or the tag closing an HTML div it sits in. The rest is the quotation's own,
#                 and a heading in it is quoted, not this paper's.
_PARAGRAPH, _QUOTE_LINES, _ITEM = "paragraph", "quote", "item"


class _Walk:
    """One pass over a document, remembering what the line above left open."""

    def __init__(self, text: str) -> None:
        self.lines = _lines(text)
        self.fences = _fences(text, self.lines)
        self.found: list[Heading] = []
        #: Where each list item's first line starts.
        self.items: list[int] = []
        self.open: str | None = None
        #: The column an open list item's content starts at; None outside a list.
        self.list_indent: int | None = None
        #: Pandoc has ended the list, and its lines start no item, but they are still the
        #: list's for headings. See `_in_list`.
        self.items_off = False
        self.divs = 0
        #: HTML blocks open around this line, by tag, which a block quote's lazy lines stop
        #: to close. Counted from tags that start or end a line, not from ones in the middle
        #: of one, which is where inline code mentions them.
        self.html: dict[str, int] = {}
        #: Whether the line just walked went on a paragraph or a list item. A tag starting
        #: it is inline there, and opens no HTML block.
        self.inline = False
        #: The lines read as rows of a table, or as a table placeholder. Shaped like a title
        #: over a rule, the last row of one is still a row.
        self.rows: set[int] = set()
        #: The last line holding only an "either" tag, `<ins>` say, which takes an indented
        #: comment under it into its raw block.
        self._raw_tag_line = -2
        #: Where a heading was read from the rest of a tag's line. The walk ends a tag at its
        #: first `>`, and pandoc does not always: `<div class="a>Methods` has no tag.
        self.tagged: set[int] = set()
        self._ends: dict[str, list[int]] | None = None
        self._closers: dict[str, list[int]] = {}
        #: The last line holding a LaTeX block that ends on a bare command. See `_bare_tex`.
        self._bare_tex_line = -2

    def run(self) -> _Walk:
        index = self._title_block()
        while index < len(self.lines):
            index = self._step(index)
        return self

    def _title_block(self) -> int:
        """Where the text starts after a pandoc title block: up to three `%` lines at the very
        top (title, authors, date), each with the indented lines that continue it. They are
        metadata, so a heading directly under them is a heading."""
        index = 0
        for _ in range(3):
            if index >= len(self.lines) or not self.lines[index].raw.startswith("%"):
                break
            index += 1
            while index < len(self.lines) and self.lines[index].raw[:1] in (" ", "\t"):
                if _blank(self.lines[index].raw):
                    break
                index += 1
        return index

    def _step(self, index: int) -> int:
        fence = self.fences.get(index)
        if fence is not None:
            return self._fence(*fence)
        line = self.lines[index]
        if (
            self.open is None
            and self.list_indent is None
            and self._raw_tag_line != index - 1
            and _INDENTED_COMMENT.match(line.raw)
        ):
            # Indented, a comment is inline text: it starts a paragraph, and a `#` line under
            # it goes on that paragraph. With text after it over an underline, it is the
            # title of a heading. Directly under an "either" tag alone on its line, it is
            # part of that tag's raw block.
            heading = self._heading(index)
            if heading is not None:
                return heading
            self.open = _PARAGRAPH
            return self._paragraph_line(index)
        if _blank(line.shown):
            if line.blank and not line.commented:
                self.open = None
            return index + 1
        after = self._line(index)
        opened = _html_opens(line.shown)
        if opened and not self.inline:
            self.html[opened] = self.html.get(opened, 0) + 1
        self._close_tags(line.shown)
        return after

    def _close_tags(self, shown: str) -> None:
        """Close the HTML blocks this line closes, wherever on it the closing tag stands:
        pandoc ends the block there. Counted only at the end of a line, a `<del>` closed in
        the middle of one stayed open for the rest of the file, and a later line ending in
        `</del>` ended a paragraph pandoc goes on with. The whole name: `</pre>` does not
        close a `<p>`."""
        if not any(self.html.values()):
            return
        lowered = shown.lower()
        for name, count in self.html.items():
            if count:
                closed = len(re.findall(rf"</{name}(?=[\s/>]|$)", lowered))
                self.html[name] = max(0, count - closed)

    def _line(self, index: int) -> int:
        self.inline = False
        if self.open is not None and self._continues(index):
            if self.open == _QUOTE_LINES:
                return index + 1
            self.inline = True
            if self.open == _ITEM:
                # Inside a list, a marker ends the lazy lines and starts the next item. A
                # paragraph gets no such line: a list cannot interrupt one.
                shown = self.lines[index].shown
                if _DEFINITION.match(shown):
                    # A definition under the item's text ends the list, and the rest is the
                    # definition's paragraph: a marker starts no item there, and a tilde
                    # fence does not end it. A line indented after a blank stays the list's
                    # for headings, as after any line pandoc ends a list at: see `_in_list`.
                    # Indented to the item's text, it is a definition list inside the item,
                    # and the item goes on.
                    if _indent(shown) < (self.list_indent or 0):
                        self.open = _PARAGRAPH
                        self.items_off = True
                else:
                    self._item(index)
            return self._paragraph_line(index)
        self.open = None
        return self._block(index)

    def _item(self, index: int) -> bool:
        """Record a list item if this line starts one, and where its content starts.

        The gap after the marker is counted in columns: a tab reaches the next tab stop, so
        the text of `1.<tab>First` starts at column 4, where pandoc puts it. `* * *` is not an
        item: at a block's start it is a rule, and under an item it is text of the item."""
        shown = self.lines[index].shown
        item = _LIST_ITEM.match(shown)
        if item is None or _THEMATIC_BREAK.match(shown):
            return False
        marker = item.group("marker")
        gap = len((marker + item.group("gap")).expandtabs(4)) - len(marker)
        self.list_indent = len(marker) + (gap if 0 < gap <= 4 else 1)
        if not self.items_off:
            self.items.append(self.lines[index].start)
        return True

    def _paragraph_line(self, index: int) -> int:
        """After a line of a paragraph or a list item: a block-level tag closing the line ends
        it, and a `<pre>`, `<script>` or `<textarea>` it leaves open holds everything up to
        its closing tag."""
        after = self._verbatim(index, ("pre", "script", "textarea"))
        if after is not None or _ends_on_block_tag(self.lines[index].shown, self.html):
            self.open = None
        return after if after is not None else index + 1

    def _verbatim(self, index: int, tags: tuple[str, ...]) -> int | None:
        """The line after the closing tag of a verbatim element this line leaves open, or
        None. One that is never closed is not verbatim: pandoc reads on as usual."""
        shown = self.lines[index].shown
        opened = [m for m in _VERBATIM.finditer(shown) if m.group(1).lower() in tags]
        if not opened:
            return None
        name = opened[-1].group(1).lower()
        if f"</{name}" in shown[opened[-1].end() :].lower():
            return None
        if name not in self._closers:
            closing = f"</{name}"
            self._closers[name] = [
                number for number, line in enumerate(self.lines) if closing in line.shown.lower()
            ]
        closers = self._closers[name]
        later = bisect_right(closers, index)
        return closers[later] + 1 if later < len(closers) else None

    def _fence(self, last: int, char: str, indented: bool) -> int:
        # A backtick fence at the margin interrupts a paragraph. A tilde one, or an indented
        # one, does not: pandoc prints it as text inside the paragraph, which goes on past it.
        # Any fence ends a list item's lazy lines.
        if self.open in (_PARAGRAPH, _QUOTE_LINES) and (char == "~" or indented):
            return last + 1
        self.open = None
        if not indented:
            self._end_list()
        return last + 1

    def _end_list(self) -> None:
        self.list_indent = None
        self.items_off = False

    def _continues(self, index: int) -> bool:
        """Whether a line carries on what the line above left open. See `_PARAGRAPH`."""
        shown = self.lines[index].shown
        if self.divs and _DIV_CLOSE.match(shown):
            return False
        if self.open == _QUOTE_LINES:
            closes = _QUOTE_STOP.match(shown)
            return not (closes and self.html.get(closes.group(1).lower()))
        return not _BLOCK_TAG.match(shown) and self._environment(index) is None

    def _block(self, index: int) -> int:
        if self._bare_tex_line == index - 1 and _DIGIT_FIRST.match(self.lines[index].shown):
            # The digits go to the raw block, so the line starts no list item. Over an
            # underline it is still a heading: pandoc prints "2. Results" there as ". Results".
            heading = self._heading(index)
            if heading is not None:
                return heading
            self.open = _PARAGRAPH
            return self._paragraph_line(index)
        if self.list_indent is not None and self._in_list(index):
            return index + 1
        for opens in (self._container, self._heading, self._leaf):
            after = opens(index)
            if after is not None:
                return after
        self.open = _PARAGRAPH
        return self._paragraph_line(index)

    def _in_list(self, index: int) -> bool:
        """A line indented to a list item's text, after a blank line, belongs to it: a
        paragraph, a nested item, or code if it is indented four more. A line at the margin
        closes the list, unless it starts an item. A rule shaped like a marker, `* * *`, or a
        marker in digits pandoc does not read, `１.`, ends the items and not the list: the
        walk read both as markers before it read list items, and the lines under them stay
        the list's for headings, as below.

        Pandoc also ends the list at a line indented less than the item's text, and a marker
        under that is prose: "  More" under "1. First". Items end there. For headings the
        line stays the list's, as does everything indented up to the next line at the margin:
        read as blocks of their own, lines indented one to three spaces were misread, and a
        `#` line under a line block, a comment or raw HTML over an indented line, text to
        pandoc, opened Methods. So does a line of the outer item of a nested list, which is
        indented less than the inner item's text and still in the list."""
        shown = self.lines[index].shown
        indent = _indent(shown)
        marker = _LIST_ITEM.match(shown) is not None and not _THEMATIC_BREAK.match(shown)
        if indent == 0:
            if marker:
                self.items_off = False
            elif _MARKER_SHAPE.match(shown):
                self.items_off = True
            else:
                self._end_list()
            return False
        if indent < (self.list_indent or 0):
            if marker and not self.items_off:
                return False
            self.items_off = True
            self.open = _ITEM
            return True
        if indent >= (self.list_indent or 0) + 4:
            self.open = None
            return True
        self._item(index)
        self.open = _ITEM
        return True

    def _container(self, index: int) -> int | None:
        """Divs, fenced or HTML, which pandoc reads before it looks for a heading. Other HTML
        blocks come after: `<noscript>` over an underline is a heading."""
        shown = self.lines[index].shown
        if _div_open(shown):
            self.divs += 1
        elif self.divs and _DIV_CLOSE.match(shown):
            self.divs -= 1
        elif _HTML_DIV.match(shown):
            return self._tag_line(index)
        else:
            return None
        return index + 1

    def _html_block(self, index: int) -> int | None:
        if not _START_TAG.match(self.lines[index].shown):
            return None
        after = self._verbatim(index, ("pre", "script", "style", "textarea"))
        return after if after is not None else self._tag_line(index)

    def _tag_line(self, index: int) -> int:
        """A tag at the margin is a block of its own, and the rest of its line starts the
        next one, as after a comment. `<div>Text` over `## Results` is a raw tag and a
        paragraph, which the `#` line continues; `<div>## Results` is a heading."""
        shown = self.lines[index].shown
        tag = _OPENS.match(shown) or _START_TAG.match(shown)
        closing = shown.find(">", tag.end()) if tag else -1
        rest = shown[closing + 1 :] if closing != -1 else ""
        if _blank(rest):
            if tag is not None and not _BLOCK_TAG.match(shown):
                self._raw_tag_line = index
            return index + 1
        # Over an underline the rest is a setext title, `#` and all: `<div># Methods` over
        # `-` is a heading reading "# Methods".
        if index + 1 < len(self.lines) and _underline(self.lines[index + 1]):
            below = self.lines[index + 1]
            level = 1 if below.shown.startswith("=") else 2
            self.tagged.add(self.lines[index].start)
            self.found.append(
                Heading(self.lines[index].start, level, _setext_title(rest), setext=True)
            )
            return index + 2
        atx = _atx(rest)
        if atx is not None:
            self.tagged.add(self.lines[index].start)
            self.found.append(Heading(self.lines[index].start, *atx))
            return index + 1
        # The paragraph ends where its text closes what the tag opened: `<ins>Text</ins>`.
        opened = dict(self.html)
        if _OPENS.match(shown):
            name = _OPENS.match(shown).group(1).lower()
            opened[name] = opened.get(name, 0) + 1
        self.open = None if _ends_on_block_tag(shown, opened) else _PARAGRAPH
        return index + 1

    def _footnote(self, index: int) -> int:
        """A footnote takes every line up to a blank one, whatever it holds, and then each run
        of lines whose first is indented four spaces or a tab. All of it is the note's own,
        headings included, and the line after it starts a block. With nothing on the marker's
        line, the note's first run is the one after the blank lines under it, indented or
        not."""
        end = index
        marker = _FOOTNOTE.match(self.lines[index].shown)
        if marker is not None and _blank(self.lines[index].shown[marker.end() :]):
            end = index + 1
            while end < len(self.lines) and self._chunk_ends(end):
                end += 1
        while True:
            while end < len(self.lines) and not self._chunk_ends(end):
                end += 1
            after = end
            while after < len(self.lines) and self._chunk_ends(after):
                after += 1
            if after == len(self.lines) or not self.lines[after].raw.startswith(("    ", "\t")):
                return end
            end = after

    def _chunk_ends(self, index: int) -> bool:
        line = self.lines[index]
        return line.blank and not line.commented

    def _heading(self, index: int) -> int | None:
        line = self.lines[index]
        below = self.lines[index + 1] if index + 1 < len(self.lines) else None
        # A block-level tag in the title ends its inline text short, and the underline with it.
        # A table placeholder is no title: the build puts a table there, and a rule under its
        # last row is a rule.
        if (
            below is not None
            and _underline(below)
            and not _A_BLOCK_TAG.search(line.shown)
            and not _lone_table(line.shown)
        ):
            level = 1 if below.shown.startswith("=") else 2
            self.found.append(Heading(line.start, level, _setext_title(line.shown), setext=True))
            return index + 2
        atx = _atx(line.shown)
        if atx is None:
            return None
        self.found.append(Heading(line.start, *atx))
        return index + 1

    def _leaf(self, index: int) -> int | None:
        """Blocks that end at their own last line, so a heading may follow with no blank."""
        shown = self.lines[index].shown
        html = self._html_block(index)
        if html is not None:
            return html
        if shown.startswith(("    ", "\t")):
            # An indented listing runs on to its last indented line, so its second line over
            # a rule is code over a rule, not a heading. Indented as written: a comment
            # blanked to spaces is not code.
            end = index + 1
            while end < len(self.lines) and self._indented_code(end):
                end += 1
            return end
        # A rule as written: `--- <!-- revised -->` is text, not a rule with a comment.
        if _THEMATIC_BREAK.match(shown) and _THEMATIC_BREAK.match(self.lines[index].raw):
            return index + 1
        if self._item(index):
            self.open = _ITEM
            return self._paragraph_line(index)
        if _QUOTE.match(shown):
            self.open = _QUOTE_LINES
            return index + 1
        if _FOOTNOTE.match(shown):
            return self._footnote(index)
        if _lone_table(shown):
            self.rows.add(index)
            return index + 1
        if _tex_block(shown):
            if _bare_tex(shown):
                self._bare_tex_line = index
            return index + 1
        if _REFERENCE.match(shown):
            return index + 1
        return self._environment(index) or self._table(index)

    def _indented_code(self, index: int) -> bool:
        line = self.lines[index]
        return line.raw.startswith(("    ", "\t")) and not _blank(line.shown)

    def _table(self, index: int) -> int | None:
        """A pipe table runs while its rows have a pipe; a grid table or a line block while
        its lines start with one (or continue the line above, for a line block). A caption
        directly under a table is part of it, and reads on like a paragraph."""
        shown = self.lines[index].shown
        below = self.lines[index + 1].shown if index + 1 < len(self.lines) else ""
        if "|" in shown and "|" in below and _TABLE_RULE.match(below):
            end = index + 2
            while end < len(self.lines) and _cell_pipe(self.lines[end].shown):
                end += 1
            self.rows.update(range(index, end))
            return self._caption(end)
        if _GRID_TOP.match(shown):
            end = index + 1
            while end < len(self.lines) and _GRID_ROW.match(self.lines[end].shown):
                end += 1
            # A grid table ends on a border. A border with nothing closing it is text, and a
            # `#` line under it goes on that text.
            last = next(
                (n for n in range(end - 1, index, -1) if _GRID_TOP.match(self.lines[n].shown)),
                None,
            )
            if last is None:
                return None
            self.rows.update(range(index, last + 1))
            return self._caption(last + 1)
        if not _LINE_BLOCK.match(shown):
            return None
        end = index + 1
        while end < len(self.lines) and (
            _LINE_BLOCK.match(self.lines[end].shown)
            or _CONTINUATION.match(self.lines[end].shown)
        ):
            end += 1
        return end

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


@dataclass(frozen=True)
class Blocks:
    """What one walk of a document found."""

    headings: tuple[Heading, ...]
    #: Where the first line of each list item starts, in document order.
    items: tuple[int, ...]


def read_blocks(text: str) -> Blocks:
    walk = _Walk(text).run()
    return Blocks(tuple(walk.found), tuple(walk.items))


def find_headings(text: str) -> list[Heading]:
    """Every heading pandoc prints, ATX and setext, in document order."""
    return list(read_blocks(text).headings)


def list_items(text: str) -> list[int]:
    """Where each list item pandoc makes starts. A marker a hard wrap put at the start of a
    line in a paragraph starts none: a list cannot interrupt a paragraph."""
    return list(read_blocks(text).items)


# Looser than `ATX_LINE`: any whitespace after the hashes, a no-break space included. Pandoc
# prints "#" and a no-break space as text, and a reader takes it for a heading all the same.
_SHAPED_ATX = re.compile(r"^#+(?=\s|$)")


def heading_shaped(lines: list[str]) -> set[int]:
    """The lines that look like headings wherever they stand: `#` lines, and titles over an
    underline. For a caller that must stop at a heading whether or not pandoc prints it."""
    shaped = set()
    for number, line in enumerate(lines):
        below = lines[number + 1].rstrip("\r") if number + 1 < len(lines) else ""
        if _SHAPED_ATX.match(line.rstrip("\r")) or (
            not _blank(line) and _UNDERLINE.match(below)
        ):
            shaped.add(number)
    return shaped


class Unprinted(str):
    """The title of a line shaped like a heading that pandoc prints as text. It ends the
    section it stands in, and opens none: see `section_breaks`."""

    __slots__ = ()


def section_breaks(text: str) -> list[Heading]:
    """Every heading pandoc prints, and every line shaped like one that it prints as text.

    The walk reads a construct it does not model as a paragraph, and a paragraph takes the
    `#` line under it for text. For a heading that would open Methods, that is the safe
    answer. For one that ends them it is not: pandoc prints `# Results` under a table between
    lines of dashes, which the walk does not model, so the Methods ran on past the heading
    and a p-value under it passed as the alpha. So a line shaped like a heading ends the
    section it is in, whether or not the walk places it. One the walk does not place comes
    back titled `Unprinted`, which `is_methods` never takes for Methods: it can close the
    Methods, and never open them. A table row is not such a line: the walk reads the table,
    and the rule under its last row is a rule.

    Three kinds of heading the walk does place come back `Unprinted` as well: a `#` heading
    after a tag or a comment on its line, a setext title after a tag, at the start of its
    line or after a comment, and a heading of seven hashes or more. The scan before the walk
    never read any of them, and wherever the walk wrongly starts a block, under a stray
    `</script>` say, or ends a tag pandoc does not see, one could open Methods. A seven-hash
    Methods did so too under a Results title the gates do not read, `# [Results]{.underline}`.
    And an empty `##` over a line of text breaks there too,
    titled with that line: pandoc prints the line as a paragraph, and the page shows
    "Results" over the numbers under it.
    """
    walk = _Walk(text).run()
    raw_at = {line.start: line.raw for line in walk.lines}
    found = [
        replace(heading, title=Unprinted(heading.title))
        if heading.start in walk.tagged
        or (not heading.setext and not raw_at[heading.start].startswith("#"))
        or (not heading.setext and heading.level >= 7)
        or (heading.setext and _START_TAG.match(raw_at[heading.start]))
        else heading
        for heading in walk.found
    ]
    by_start = {heading.start: heading for heading in found}
    shown = [line.shown for line in walk.lines]
    placed = set(walk.rows)
    for number, line in enumerate(walk.lines):
        heading = by_start.get(line.start)
        if heading is not None:
            placed.update((number, number + 1) if heading.setext else (number,))
    shaped = heading_shaped(shown)
    for number in sorted(shaped - placed):
        line = shown[number]
        below = shown[number + 1] if number + 1 < len(shown) else ""
        if not _blank(line) and _UNDERLINE.match(below):
            level, title, setext = (1 if below.startswith("=") else 2), _setext_title(line), True
        else:
            level = len(line) - len(line.lstrip("#"))
            title, setext = line[level:].strip().rstrip("#").strip(), False
        found.append(Heading(walk.lines[number].start, level, Unprinted(title), setext))
    for number, line in enumerate(walk.lines):
        heading = by_start.get(line.start)
        if heading is None or heading.setext or heading.title:
            continue
        after = number + 1
        while after < len(shown) and _blank(shown[after]):
            after += 1
        if after < len(shown) and after not in placed and after not in shaped:
            title = Unprinted(shown[after].strip())
            found.append(Heading(walk.lines[after].start, heading.level, title))
    return sorted(found, key=lambda heading: heading.start)


__all__ = [
    "ATX_LINE",
    "Blocks",
    "Heading",
    "Unprinted",
    "find_headings",
    "heading_shaped",
    "list_items",
    "read_blocks",
    "scannable",
    "section_breaks",
]
