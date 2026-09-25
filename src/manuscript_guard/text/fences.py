"""Where the fenced code blocks are. One implementation, scanned linearly.

There were three copies of a regex for this — in `masking.py`, `sections.py` and
`gates/numbers.py` — and they were wrong in the same two ways, which is what three copies
of anything eventually are.

**They required the closing fence to be exactly the opening run.** CommonMark, and pandoc,
close a fence on any run of the same character *at least as long*. So

    ```python
    x = 1
    ````                                    <- four: closes for pandoc, not for the regex

    The reporting odds ratio was 9.99.      <- an ordinary paragraph in the .docx

    ```python
    y = 2
    ```

left a whole paragraph of prose inside what the toolkit believed was one code block. G2 saw
no atoms at all, and `explain` did not mention the number. A laundering route needing one
extra backtick.

**And they backtracked.** `(?P<tick>`{3,})...(.*?)^(?P=tick)$` with DOTALL re-scans the rest
of the document for every opener-shaped line that never closes, which is O(n²): 1,000 such
lines took 0.24s, 4,000 took 6.1s, and a 3,000-line file made `manuscript-guard check`
exceed a minute. That is reachable by accident — a paper about Markdown, or one missing a
closing fence — and it undermines the claim that `check` is safe to run on a manuscript
someone sent you.

A line scanner has neither problem and is easier to read than the regex was.

**A line is what pandoc reads as one.** Python's `splitlines` also breaks at a form feed, a
vertical tab, U+001C to U+001E, U+0085, U+2028 and U+2029, and `str.strip` takes every
Unicode space off. Pandoc breaks at a newline alone, deletes a carriage return wherever it
is, and allows only spaces and tabs around a fence. So `We found it.` followed by a form
feed and three backticks opened a listing to the gates that pandoc never made, and a closer
ending in a no-break space closed one pandoc kept open, pairing the next fence with the one
after it. Either way prose that printed was code to every gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Up to three spaces of indent; four would be an indented code block, not a fence. A tab
# in the indent reaches column four, since pandoc expands tabs to four columns first.
_OPENER = re.compile(r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")
# A line and its newline. Pandoc breaks lines there and nowhere else.
_LINE = re.compile(r"[^\n]*\n|[^\n]+")
# Haskell's `isSpace`, which ends pandoc's words. Python's `str.isspace` also counts U+001C
# to U+001F, U+0085, U+2028 and U+2029, which pandoc keeps inside a word.
_SPACES = frozenset(
    chr(code)
    for code in (0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0xA0, 0x1680, 0x202F, 0x205F, 0x3000)
) | frozenset(chr(code) for code in range(0x2000, 0x200B))
# The language word after a fence: no space, no backtick and no brace.
_WORD = re.compile("[^`{}" + re.escape("".join(sorted(_SPACES))) + "]+")
# A raw block's `{=format}`.
_RAW = re.compile(r"\{[ \t]*=[\w-]+[ \t]*\}")
# An unquoted attribute value. A backslash escapes whatever is not a letter or a digit, as
# pandoc's `all_symbols_escapable` has it; before anything else it is a backslash.
_BARE_VALUE = re.compile(r"(?:\\[\W_]|[^ \t}])*")
_BLANKS = re.compile(r"[ \t]*")
# What may stand in front of a line of backticks or tildes. Past three spaces it is
# indented code or a list item's listing, which the gates read as text; a no-break space, a
# byte-order mark or another zero-width mark makes a line pandoc may not read as a fence.
_LEAD = re.compile(
    "[\\s" + "".join(chr(code) for code in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060)) + "]*"
)
# A list, definition or footnote marker, a task's box after it: pandoc opens a listing in
# the item, and takes the item's indentation off the lines before it looks for the closer.
_MARKER = re.compile(
    r"[ ]{0,3}(?:[*+:~-]|\(?(?:\d{1,9}|#|@[\w-]*|[A-Za-z]|[ivxlcdmIVXLCDM]+)[.)]"
    r"|\[\^[^\]\n]*\]:)(?:[ \t]+\[[ xX]\])?[ \t]+"
)
# The marks that open or close a comment or a raw block. Inside one, a fence is raw text to
# pandoc, and only the mark that closes it counts: a comment closes on `-->`, `<pre>` on
# `</pre>`, `<?php` on `?>`, and `\begin{x}` on `\end{x}`, one of the same name opened inside
# counted, as pandoc counts them, save a `<script>`. `<!-->` and `<!--->` are comments closed
# at once, and `<?` opens nothing before anything but a letter. Every mark is found, at every
# position of a line, in one pass: `<?>` holds a `?>`. Searched for mark by mark from each
# one's end, a line of 300,000 characters inside a `<pre>` took eighteen seconds.
_MARKS = re.compile(
    r"(?=(?P<comment><!--(?!-?>))"
    r"|(?P<uncomment>-->)"
    r"|(?P<tag><(?i:(?P<tagname>pre|script|style|textarea))(?=[\s>/]|$))"
    r"|(?P<untag></(?i:(?P<untagname>pre|script|style|textarea))\s*>)"
    r"|(?P<instruction><\?(?=[A-Za-z]))"
    r"|(?P<uninstruction>\?>)"
    r"|(?P<environment>\\begin[ \t]*\{(?P<envname>[^{}\n]*)\})"
    r"|(?P<unenvironment>\\end[ \t]*\{(?P<unenvname>[^{}\n]*)\}))"
)
# Each opening mark, and the mark that closes what it opens.
_CLOSING = {
    "comment": "uncomment",
    "tag": "untag",
    "instruction": "uninstruction",
    "environment": "unenvironment",
}
# Opened inside one of their name, these are counted; a `<script>` is not.
_NESTING = frozenset({"pre", "style", "textarea"})
_BACKTICKS = re.compile(r"`+")


@dataclass(frozen=True)
class _Raw:
    """A comment or raw block open: which kind, its name, and how many are open."""

    kind: str
    name: str
    depth: int = 1

    def nests(self) -> bool:
        return self.kind == "environment" or self.name in _NESTING


def _mark(found: re.Match[str]) -> tuple[str, str, int]:
    """A mark `_MARKS` found: its kind, the name it carries, and where it ends."""
    kind = found.lastgroup or ""
    name = {
        "tag": found.group("tagname"),
        "untag": found.group("untagname"),
        "environment": found.group("envname"),
        "unenvironment": found.group("unenvname"),
    }.get(kind) or ""
    lowered = name.lower() if kind in ("tag", "untag") else name
    return kind, lowered, found.start() + len(found.group(kind))


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
        """The language word after the fence, or else the first class in its attributes,
        lowercased, as pandoc takes it. Empty when untagged. Split on spaces, `{.python}`
        and `r{.x}` were languages no lexer knew, and the listing went unread."""
        info = self.info.strip(" \t")
        word = _WORD.match(info)
        if word:
            return word.group().lower()
        # Read an attribute at a time, so that `.b` inside `k='a .b'` is no class.
        position = _BLANKS.match(info, info.find("{") + 1).end() if "{" in info else len(info)
        while (after := _attribute_end(info, position)) is not None:
            if info.startswith(".", position):
                return info[position + 1 : after].lower()
            position = _BLANKS.match(info, after).end()
        return ""

    @property
    def is_raw(self) -> bool:
        """A pandoc raw-attribute block: ```{=openxml}, ```{=html}, ```{=latex}.

        Not a listing at all — pandoc splices its contents into the output format verbatim,
        so the text inside reaches the reader as formatted prose. Reporting it as "a
        language with no lexer" was actively misleading: the advice was to tag the fence,
        which would have made it quieter still. Pandoc allows spaces inside the braces, so
        `{ =openxml}` is one too.
        """
        return _RAW.fullmatch(self.info.strip(" \t")) is not None


def _bare(line: str) -> str:
    """A line as pandoc reads it: without its newline, with no carriage return, and with
    tabs expanded to four columns, which pandoc does before it parses anything."""
    return line.rstrip("\n").replace("\r", "").expandtabs(4)


def _closer(line: str) -> tuple[str, int] | None:
    """The fence character and width of a line that could close a listing: up to three
    spaces, a run of three or more, and nothing but spaces after. "At least as long", per
    CommonMark: requiring equality let a longer closer slip past and swallow the prose after
    it. A no-break space or a form feed after the run leaves pandoc's block open."""
    run_start = len(line) - len(line.lstrip(" "))
    char = line[run_start : run_start + 1]
    if run_start > 3 or char not in ("`", "~"):
        return None
    run = len(line) - run_start - len(line[run_start:].lstrip(char))
    return (char, run) if run >= 3 and not line[run_start + run :].strip(" ") else None


def _closes(line: str, char: str, width: int) -> bool:
    """Does this line close a listing opened with a run of `width` of `char`?"""
    closer = _closer(line)
    return closer is not None and closer[0] == char and closer[1] >= width


def _quote_end(info: str, at: int) -> int | None:
    """Where a value quoted from `at` ends, as pandoc's `enclosed` reads it: no space just
    inside the opening quote, a backslash escaping what is not a letter or a digit."""
    quote = info[at]
    if info[at + 1 : at + 2] in _SPACES:
        return None
    position = at + 1
    while position < len(info):
        escaped = info[position + 1 : position + 2]
        if info[position] == "\\" and escaped and not escaped.isalnum():
            position += 2
        elif info[position] == quote:
            return position + 1
        else:
            position += 1
    return None


def _name_end(info: str, at: int, *, letter_first: bool) -> int | None:
    """Where an attribute's name from `at` ends: letters, digits and `-_:.`, a class's and a
    key's starting with a letter. Python's `isalpha` and `isalnum` take the Unicode
    categories Haskell's do; `\\w` would take a superscript digit for a letter."""
    start = at
    if letter_first and not info[at : at + 1].isalpha():
        return None
    while at < len(info) and (info[at].isalnum() or info[at] in "-_:."):
        at += 1
    return at if at > start else None


def _attribute_end(info: str, at: int) -> int | None:
    """Where one attribute from `at` ends: `#id`, `.class`, `key=value` or `-`. Each is
    tried in turn and the first that reads is kept, as pandoc's parser does."""
    if info.startswith("#", at):
        return _name_end(info, at + 1, letter_first=False)
    if info.startswith(".", at):
        return _name_end(info, at + 1, letter_first=True)
    name = _name_end(info, at, letter_first=True)
    if name is not None and info.startswith("=", name):
        value = name + 1
        if info[value : value + 1] in ('"', "'"):
            # Not closed on the line, pandoc reads the value on over the lines after, and
            # what it then makes of them the gates do not guess: the opener is refused.
            return _quote_end(info, value)
        return _BARE_VALUE.match(info, value).end()
    return at + 1 if info.startswith("-", at) else None


def _attributes_end(info: str, at: int) -> int | None:
    """Where `{attributes}` from `at` end, or None where pandoc reads none. An attribute
    that does not read ends the list, and then only `}` may follow."""
    position = _BLANKS.match(info, at + 1).end()
    while (after := _attribute_end(info, position)) is not None:
        position = _BLANKS.match(info, after).end()
    return position + 1 if info.startswith("}", position) else None


def _info_opens(info: str) -> bool:
    """Does pandoc 3.9 open a fence with `info` after it, on the line? Spaces and tabs,
    then a raw `{=format}`, or a language word and `{attributes}`, either or both, then
    spaces and tabs. `r foo`, `{r, echo=FALSE}` and `{.r} x` open none: pandoc prints the
    lines as text, or as inline code running to the closer."""
    at = _BLANKS.match(info).end()
    raw = _RAW.match(info, at)
    if raw:
        at = raw.end()
    else:
        word = _WORD.match(info, at)
        if word:
            at = _BLANKS.match(info, word.end()).end()
        if info.startswith("{", at):
            end = _attributes_end(info, at)
            if end is None:
                return False
            at = end
    return not info[at:].strip(" \t")


def _fence_like(bare: str) -> bool:
    """Does the line start with three backticks or tildes, behind at most three spaces,
    behind whitespace other than spaces or a zero-width mark, or behind a list marker?"""
    marker = _MARKER.match(bare)
    lead = _LEAD.match(bare, marker.end() if marker else 0).end()
    if not bare.startswith(("```", "~~~"), lead):
        return False
    indent = bare[:lead]
    return marker is not None or indent.strip(" ") != "" or len(indent) <= 3


def _without_code_spans(line: str) -> str:
    """`line` with its code spans blanked, paired as pandoc pairs them in one pass: a run of
    backticks opens a span that the next run of the same length closes, and a run behind a
    backslash opens none. A run left unpaired may open a span that closes on a later line,
    so then nothing is blanked. The pattern this replaced retried from every backtick of a
    run, and one line of 20,000 took seven seconds."""
    runs: list[tuple[int, int, bool]] = []
    for found in _BACKTICKS.finditer(line):
        slash = found.start()
        while slash > 0 and line[slash - 1] == "\\":
            slash -= 1
        runs.append((found.start(), found.end(), (found.start() - slash) % 2 == 1))
    following: list[int | None] = [None] * len(runs)
    last: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        size = runs[index][1] - runs[index][0]
        following[index] = last.get(size)
        last[size] = index
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        if runs[index][2]:
            index += 1
            continue
        close = following[index]
        if close is None:
            return line
        spans.append((runs[index][0], runs[close][1]))
        index = close + 1
    pieces: list[str] = []
    at = 0
    for start, end in spans:
        pieces += [line[at:start], " " * (end - start)]
        at = end
    pieces.append(line[at:])
    return "".join(pieces)


def _raw_after(bare: str, raw: _Raw | None) -> _Raw | None:
    """The comment or raw block open after `bare`, None when none is: `raw` is the one open
    before it. Outside one, marks in inline code count for nothing, pandoc printing them as
    code; inside one, everything is raw, and only its own marks count."""
    outside: str | None = None
    at = 0
    for found in _MARKS.finditer(bare):
        if found.start() < at:
            continue
        kind, name, end = _mark(found)
        if raw is not None:
            if kind == _CLOSING[raw.kind] and name == raw.name:
                raw = _Raw(raw.kind, name, raw.depth - 1) if raw.depth > 1 else None
            elif kind == raw.kind and name == raw.name and raw.nests():
                raw = _Raw(raw.kind, name, raw.depth + 1)
            else:
                continue
            at = end
            continue
        if kind not in _CLOSING:
            continue
        if outside is None:
            outside = _without_code_spans(bare)
        start = found.start()
        # In inline code a mark is printed; a raw element or `<?` opens a block only at the
        # start of a line, and in a line of text it is inline markup.
        if outside[start] != bare[start]:
            continue
        if kind in ("tag", "instruction") and (at or start > 3 or outside[:start].strip(" ")):
            continue
        raw, at = _Raw(kind, name), end
    return raw


def fenced_spans(text: str, begin: int = 0) -> list[Fence]:
    """Every fenced block, in document order, in time linear in the length of the text.

    An **unterminated** fence is not a fence. Pandoc's markdown reader renders the opening
    ``` as literal text and the rest of the document as ordinary paragraphs — verified
    against pandoc 3.9.0.2 — so treating it as code to the end of the file would mask prose
    the reader plainly sees. That is the same failure as the longer-closer bug, arrived at
    from the other side, and `tests/test_pandoc_agreement.py` caught it here.

    `begin`, the start of a line, is where the body starts: no fence opens in the front
    matter before it (see `masking.front_matter_end`). Offsets are still into `text`.
    """
    lines = _LINE.findall(text, begin)
    return [fence for _first, _last, fence in _listings(lines, [_bare(x) for x in lines], begin)]


def unclear_fence_lines(text: str, begin: int = 0) -> list[int]:
    """The lines, numbered from 1, of each line from `begin` that starts with three
    backticks or tildes and is not a plain fenced listing's, nor inside one.

    A plain listing opens at the margin, under a blank line, the first line or another
    listing's closer, with at most a language word and one-line `{attributes}` after its
    fence, outside any comment or raw block, and closes. Pandoc opens no fence on an R
    Markdown chunk header, `{r, echo=FALSE}`, and prints the lines as inline code running to
    the closer, which then opened a listing to the gates that ran on to the next chunk, over
    the prose between. Nor does it open a tilde fence, or an indented one, under a line of
    text, where it does open a backtick one; it reads attributes on over lines while no line
    is blank; in a list item it takes the item's indentation off before it looks for the
    closer; and inside a comment, a `<pre>` or a TeX environment a fence is raw text.
    Modelling each of those grew a reader review kept finding wrong, so the gates read the
    plain listing and refuse the rest, and the build compares what they read with the code
    pandoc makes (`build.reading`).
    """
    lines = _LINE.findall(text, begin)
    bares = [_bare(line) for line in lines]
    listings = _listings(lines, bares, begin)
    last_of = {first: last for first, last, _fence in listings}
    closers = set(last_of.values())
    inside: set[int] = set()
    raw: _Raw | None = None
    index = 0
    while index < len(bares):
        last = last_of.get(index)
        above = bares[index - 1] if index else ""
        if (
            last is not None
            and raw is None
            and bares[index][:1] in ("`", "~")
            and (index == 0 or not above.strip(" ") or index - 1 in closers)
        ):
            inside.update(range(index, last + 1))
            index = last + 1
            continue
        raw = _raw_after(bares[index], raw)
        index += 1
    above_begin = text.count("\n", 0, begin)
    return [
        above_begin + index + 1
        for index, bare in enumerate(bares)
        if index not in inside and _fence_like(bare)
    ]


def _listings(lines: list[str], bares: list[str], begin: int) -> list[tuple[int, int, Fence]]:
    """Each fenced block with the indexes, in `lines`, of its opening and closing lines."""
    # The widest closer of each fence character still to come after each line, read from
    # the end once. An opener wider than that has no closer and is passed over at once;
    # found by scanning forward, every opener in a run of narrowing ones read to the end of
    # the text, and a run of a hundred over 85 KB took seconds a pass, of which `check`
    # makes several.
    widest = {"`": 0, "~": 0}
    after: list[tuple[int, int]] = [(0, 0)] * len(bares)
    for index in range(len(bares) - 1, -1, -1):
        after[index] = (widest["`"], widest["~"])
        closer = _closer(bares[index])
        if closer is not None:
            widest[closer[0]] = max(widest[closer[0]], closer[1])

    found: list[tuple[int, int, Fence]] = []
    offset = begin
    index = 0
    while index < len(lines):
        line = lines[index]
        opener = _OPENER.match(bares[index])
        fence = opener.group("fence") if opener else ""
        # A backtick in the language word makes the line inline code or text, not a fence,
        # but one in an attribute's value does not: pandoc reads ```{.r k=a`b} as a fence.
        if (
            opener is None
            or not _info_opens(opener.group("info"))
            or after[index][fence[0] == "~"] < len(fence)
        ):
            offset += len(line)
            index += 1
            continue

        start = offset
        opened = index
        offset += len(line)
        index += 1
        body_start = offset
        # A closer wide enough is known to follow, so this stops at it.
        while not _closes(bares[index], fence[0], len(fence)):
            offset += len(lines[index])
            index += 1
        body_end = offset
        offset += len(lines[index])
        index += 1

        found.append(
            (
                opened,
                index - 1,
                Fence(
                    start=start,
                    body_start=body_start,
                    body_end=body_end,
                    end=offset,
                    info=opener.group("info"),
                ),
            )
        )

    return found


def blank_fences(text: str) -> str:
    """`text` with every fenced block replaced by spaces, offsets and newlines preserved."""
    chars = list(text)
    for fence in fenced_spans(text):
        for position in range(fence.start, fence.end):
            if chars[position] != "\n":
                chars[position] = " "
    return "".join(chars)


__all__ = ["Fence", "blank_fences", "fenced_spans", "unclear_fence_lines"]
