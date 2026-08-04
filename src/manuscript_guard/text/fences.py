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
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Up to three spaces of indent; four would be an indented code block, not a fence.
_OPENER = re.compile(r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")


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


def _closes(line: str, char: str, width: int) -> bool:
    """Is this line a closing fence for a run of `width` of `char`?

    "At least as long", per CommonMark. Requiring equality is what let a longer closer
    slip past and swallow the prose after it.
    """
    stripped = line.strip()
    if not stripped or stripped[0] != char:
        return False
    if len(line) - len(line.lstrip(" ")) > 3:
        return False
    return set(stripped) == {char} and len(stripped) >= width


def fenced_spans(text: str) -> list[Fence]:
    """Every fenced block, in document order. Linear in the length of the text.

    An unterminated fence runs to the end of the document, which is what pandoc does with
    it too.
    """
    found: list[Fence] = []
    offset = 0
    lines = text.splitlines(keepends=True)
    index = 0

    while index < len(lines):
        line = lines[index]
        bare = line.rstrip("\r\n")
        opener = _OPENER.match(bare)
        if opener is None:
            offset += len(line)
            index += 1
            continue

        fence = opener.group("fence")
        # A backtick fence's info string may not contain a backtick; that construct is
        # inline code, not a fence. Tilde fences have no such restriction.
        if fence[0] == "`" and "`" in opener.group("info"):
            offset += len(line)
            index += 1
            continue

        start = offset
        offset += len(line)
        index += 1
        body_start = offset

        while index < len(lines) and not _closes(
            lines[index].rstrip("\r\n"), fence[0], len(fence)
        ):
            offset += len(lines[index])
            index += 1

        body_end = offset
        if index < len(lines):  # consume the closing line
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
