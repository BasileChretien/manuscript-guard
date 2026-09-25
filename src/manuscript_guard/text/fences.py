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
from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate

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
# An unquoted attribute value. A backslash escapes whatever is not a letter or a digit, a
# space included, as pandoc's `all_symbols_escapable` has it; before one it is a backslash.
_BARE_VALUE = re.compile(r"(?:\\[\W_]|[^ \t\n}])*")
_BLANKS = re.compile(r"[ \t]*")


@dataclass(frozen=True)
class Fence:
    """One fenced block, as offsets into the original text."""

    start: int  # first character of the opening line
    body_start: int  # first character after the opener, whose attributes may take lines
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


def _bare(line: str) -> str:
    """A line as pandoc reads it: without its newline, and with no carriage return."""
    return line.rstrip("\n").replace("\r", "")


def _closes(line: str, char: str, width: int) -> bool:
    """Is this line a closing fence for a run of `width` of `char`?

    "At least as long", per CommonMark. Requiring equality is what let a longer closer
    slip past and swallow the prose after it. Up to three spaces before it, and nothing but
    spaces and tabs after: a no-break space or a form feed there leaves pandoc's block open.
    """
    bare = line.lstrip(" ")
    if len(line) - len(bare) > 3:
        return False
    run = len(bare) - len(bare.lstrip(char))
    return run >= width and not bare[run:].strip(" \t")


# The attributes are read over the whole text, with carriage returns deleted: pandoc lets
# them run on to the next line, and a value's quotes too, while no line between is blank.


def _blank_from(clean: str, at: int) -> bool:
    """Is the line that starts at `at` blank, or the text over?"""
    at = _BLANKS.match(clean, at).end()
    return at == len(clean) or clean[at] == "\n"


def _spaces_and_a_newline(clean: str, at: int) -> int | None:
    """Past spaces and tabs and at most one newline, or None at a blank line."""
    at = _BLANKS.match(clean, at).end()
    if clean.startswith("\n", at):
        if _blank_from(clean, at + 1):
            return None
        at = _BLANKS.match(clean, at + 1).end()
    return at


def _quote_end(clean: str, at: int) -> int | None:
    """Where a value quoted from `at` ends, as pandoc's `enclosed` reads it: no space just
    inside the opening quote, a backslash escaping what is not a letter or a digit, no
    blank line."""
    quote = clean[at]
    if clean[at + 1 : at + 2] in _SPACES:
        return None
    position = at + 1
    while position < len(clean):
        char = clean[position]
        escaped = clean[position + 1 : position + 2]
        if char == "\\" and escaped and not escaped.isalnum():
            position += 2
        elif char == quote:
            return position + 1
        elif char == "\n" and _blank_from(clean, position + 1):
            return None
        else:
            position += 1
    return None


def _identifier_end(clean: str, at: int) -> int | None:
    """Where an attribute's name from `at` ends: a letter, then letters, digits and `-_:.`.
    Python's `isalpha` and `isalnum` take the Unicode categories Haskell's do; its `\\w`
    would take a superscript digit for a letter."""
    if not clean[at : at + 1].isalpha():
        return None
    at += 1
    while at < len(clean) and (clean[at].isalnum() or clean[at] in "-_:."):
        at += 1
    return at


def _attribute_end(clean: str, at: int) -> int | None:
    """Where one attribute from `at` ends: `#id`, `.class`, `key=value` or `-`. Each is
    tried in turn and the first that reads is kept, as pandoc's parser does."""
    if clean[at : at + 1] in ("#", "."):
        return _identifier_end(clean, at + 1)
    name = _identifier_end(clean, at)
    if name is not None and clean.startswith("=", name):
        value = name + 1
        if clean[value : value + 1] in ('"', "'"):
            quoted = _quote_end(clean, value)
            if quoted is not None:
                return quoted
        return _BARE_VALUE.match(clean, value).end()
    return at + 1 if clean.startswith("-", at) else None


def _attributes_end(clean: str, at: int) -> int | None:
    """Where `{attributes}` from `at` end, or None where pandoc reads none. An attribute
    that does not read ends the list, and then only `}` may follow."""
    position = _spaces_and_a_newline(clean, at + 1)
    while position is not None:
        after = _attribute_end(clean, position)
        if after is None:
            break
        position = _spaces_and_a_newline(clean, after)
    if position is None or not clean.startswith("}", position):
        return None
    return position + 1


def _opener_end(clean: str, at: int) -> int | None:
    """Where the opening fence whose info starts at `at` ends, or None where pandoc 3.9
    opens no fence. Spaces and tabs, then a raw `{=format}`, or a language word and
    `{attributes}`, either or both, then spaces and tabs to the end of the line. So
    `r foo`, `{r, echo=FALSE}` and `{.r} x` open none: pandoc prints the lines as text."""
    at = _BLANKS.match(clean, at).end()
    raw = _RAW.match(clean, at)
    if raw:
        at = raw.end()
    else:
        word = _WORD.match(clean, at)
        if word:
            at = _BLANKS.match(clean, word.end()).end()
        if clean.startswith("{", at):
            end = _attributes_end(clean, at)
            if end is None:
                return None
            at = end
    at = _BLANKS.match(clean, at).end()
    return at if at == len(clean) or clean[at] == "\n" else None


def fenced_spans(text: str, begin: int = 0) -> list[Fence]:
    """Every fenced block, in document order. Linear in the length of the text.

    An **unterminated** fence is not a fence. Pandoc's markdown reader renders the opening
    ``` as literal text and the rest of the document as ordinary paragraphs — verified
    against pandoc 3.9.0.2 — so treating it as code to the end of the file would mask prose
    the reader plainly sees. That is the same failure as the longer-closer bug, arrived at
    from the other side, and `tests/test_pandoc_agreement.py` caught it here.

    `begin`, the start of a line, is where the body starts: no fence opens in the front
    matter before it (see `masking.front_matter_end`). Offsets are still into `text`.
    """
    found: list[Fence] = []
    offset = begin
    lines = _LINE.findall(text, begin)
    bares = [_bare(line) for line in lines]
    # The lines as pandoc reads them, one to one with `lines`: a deleted carriage return
    # never takes a newline with it.
    clean = "\n".join(bares)
    starts = list(accumulate((len(bare) + 1 for bare in bares), initial=0))
    index = 0

    # Openers proven to have no closer, by fence character. Without this the scan is
    # quadratic again: every unterminated opener reads to the end of the file, and a
    # document of 8,000 of them took 55 seconds — the very cost the regex was replaced to
    # avoid, reintroduced by the fix for unterminated fences.
    #
    # The shortcut is sound because a closing line of width w closes every opener of width
    # <= w. So once a width is known to have no closer in the remainder of the document, no
    # *wider* opener of the same character can have one either, and it can be rejected
    # without looking.
    dead: dict[str, int] = {}

    while index < len(lines):
        line = lines[index]
        opener = _OPENER.match(bares[index])
        if opener is None:
            offset += len(line)
            index += 1
            continue

        fence = opener.group("fence")
        # A backtick in the language word makes the line inline code or text, not a fence,
        # but one in an attribute's value does not: pandoc reads ```{.r k=a`b} as a fence.
        info_start = starts[index] + opener.start("info")
        info_end = _opener_end(clean, info_start)
        if info_end is None or len(fence) >= dead.get(fence[0], 1 << 30):
            offset += len(line)
            index += 1
            continue

        start = offset
        closed_from = index
        # Attributes run on over newlines take the lines they are on into the opener.
        last = bisect_right(starts, info_end) - 1
        offset += sum(len(taken) for taken in lines[index : last + 1])
        index = last + 1
        body_start = offset

        while index < len(lines) and not _closes(bares[index], fence[0], len(fence)):
            offset += len(lines[index])
            index += 1

        body_end = offset
        if index >= len(lines):
            # Ran off the end: no closer, so pandoc does not read this as a code block and
            # neither do we. Resume from the line *after* the opener so the rest stays prose
            # — and so this loop terminates, which rewinding to the opener itself did not.
            dead[fence[0]] = min(dead.get(fence[0], 1 << 30), len(fence))
            index = closed_from + 1
            offset = start + len(lines[closed_from])
            continue
        offset += len(lines[index])
        index += 1

        found.append(
            Fence(
                start=start,
                body_start=body_start,
                body_end=body_end,
                end=offset,
                info=opener.group("info"),
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


__all__ = ["Fence", "blank_fences", "fenced_spans"]
