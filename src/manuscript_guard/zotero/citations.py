"""Finding citations in manuscript source.

Both pandoc forms are recognised, and the distinction matters at build time: a bracketed
`[@key]` becomes a parenthetical citation, while a narrative `@key` renders the author in
the sentence. The `zotero.lua` filter handles them differently, and an early test of the
pipeline found that narrative citations produced no field at all unless configured, so the
build has to know which is which rather than counting them together.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# [@key], [-@key], [@key, p. 4; @other]. A group may wrap onto the next line, as it does in
# any hard-wrapped Markdown and as pandoc reads it, but not across a blank line: a paragraph
# break ends a citation group in pandoc too, and without that limit a stray "[" could swallow
# the next paragraph's narrative citations.
_IN_GROUP = r"(?:[^\]\n]|\n(?![ \t]*\n))"
BRACKETED = re.compile(rf"\[(?P<body>{_IN_GROUP}*@{_IN_GROUP}*)\]")
# A narrative @key, not preceded by a word character or a backtick.
NARRATIVE = re.compile(r"(?<![\w`\[])(?P<suppress>-?)@(?P<key>[A-Za-z][\w:.#$%&+?<>~/-]*)")
KEY_IN_BODY = re.compile(r"-?@(?P<key>[A-Za-z][\w:.#$%&+?<>~/-]*)")
# A line break that `_IN_GROUP` does not take: one with a blank line after it.
_BLANK_BREAK = re.compile(r"\n(?=[ \t]*\n)")


class _Next:
    """Where `pattern` next matches at or after an offset, for offsets that only grow: asked
    again only once an offset has passed the last answer, so the text is read once."""

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


def bracketed(text: str) -> Iterator[re.Match[str]]:
    """Every citation group in `text`: what `BRACKETED.finditer(text)` finds, in one pass.

    The search tried a group at every `[` and read on to the next `]` or blank line before it
    knew there was no `@`, so a run of brackets took time in its square: three seconds a call
    for 5,000. A group's body takes neither `]` nor a line break before a blank line, so a `[`
    opens one exactly when the next `]` comes before the next such break, and an `@` lies
    between them. Those three are found once each as the reading moves on, and the pattern
    is matched only where they say it holds, which it then does at once."""
    closes = _Next(re.compile(r"\]"), text)
    breaks = _Next(_BLANK_BREAK, text)
    signs = _Next(re.compile("@"), text)
    position = 0
    while (start := text.find("[", position)) != -1:
        close = closes.at_or_after(start + 1)
        if close == -1:
            return
        blank = breaks.at_or_after(start + 1)
        sign = signs.at_or_after(start + 1)
        if (blank == -1 or blank > close) and -1 < sign < close:
            match = BRACKETED.match(text, start)
            if match is not None:
                yield match
                position = match.end()
                continue
        position = start + 1


@dataclass(frozen=True)
class CitationUse:
    citekey: str
    path: Path
    line: int
    narrative: bool
    raw: str
    #: Where the key's sign stands in the text, for a reader that needs the uses in the
    #: order they are written: the groups are listed first here, and the narrative keys
    #: after them.
    start: int = -1


def find_citations(text: str, path: Path) -> list[CitationUse]:
    """Every citation in `text`, in groups and narrative. Line numbers are looked up among
    the line breaks, and a narrative key among the groups, by bisection: counted from the top
    and checked against every group, a paper of many citations took time in their square."""
    uses: list[CitationUse] = []
    starts: list[int] = []
    ends: list[int] = []
    breaks = [found.start() for found in re.finditer("\n", text)]

    def line_of(offset: int) -> int:
        return bisect_left(breaks, offset) + 1

    for match in bracketed(text):
        starts.append(match.start())
        ends.append(match.end())
        body_start = match.start("body")
        for key_match in KEY_IN_BODY.finditer(match.group("body")):
            uses.append(
                CitationUse(
                    citekey=key_match.group("key").rstrip(".,;:"),
                    path=path,
                    # The line the key itself is on: in a wrapped group that is not the
                    # line the group opens on.
                    line=line_of(body_start + key_match.start()),
                    narrative=False,
                    raw=match.group(0),
                    start=body_start + key_match.start(),
                )
            )

    for match in NARRATIVE.finditer(text):
        # Groups do not overlap, so the only one that can hold this key opened last before it.
        group = bisect_right(starts, match.start()) - 1
        if group >= 0 and match.start() < ends[group]:
            continue
        uses.append(
            CitationUse(
                citekey=match.group("key").rstrip(".,;:"),
                path=path,
                line=line_of(match.start()),
                narrative=True,
                raw=match.group(0),
                start=match.start(),
            )
        )

    return uses
