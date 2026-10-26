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
# An `@` glued to the word before it is an e-mail address's, and pandoc reads no citation
# there, in a group or out of one: "[name@example.org]", "[*name@example.org*](mailto:...)",
# "write to name@example.org". Glued is after a letter or a digit, or after full stops that
# are not whole ellipses, as pandoc's word runs on through a full stop and "..." is an
# ellipsis: "x.@key" and "x....@key" are no citation, "x...@key" and "x......@key" are one.
# A run of dots is counted up to fourteen; a longer one is read as ellipses. `check` read
# the host of each address as a key that "matches nothing in the library", which fails a
# submission. Each pattern asks first whether an `@` follows, so that the assertions are
# made at the signs only.
_NOT_GLUED = r"(?<![^\W_])" + "".join(
    rf"(?<!(?<!\.)\.{{{dots}}})" for dots in range(1, 15) if dots % 3
)
# A group holds an `@` no word is glued to: "[name@example.org]" is text to pandoc.
BRACKETED = re.compile(rf"\[(?P<body>{_IN_GROUP}*(?=@){_NOT_GLUED}@{_IN_GROUP}*)\]")
# A narrative @key, not preceded by a word character, a backtick or a bracket, nor glued.
NARRATIVE = re.compile(
    rf"(?=-?@)(?<![\w`\[]){_NOT_GLUED}(?P<suppress>-?)@(?P<key>[A-Za-z][\w:.#$%&+?<>~/-]*)"
)
KEY_IN_BODY = re.compile(rf"(?=-?@){_NOT_GLUED}-?@(?P<key>[A-Za-z][\w:.#$%&+?<>~/-]*)")
# An `@` that can open a key: what makes a bracketed span a citation group.
_SIGN = re.compile(rf"(?=@){_NOT_GLUED}@")
# A line break that `_IN_GROUP` does not take: one with a blank line after it.
_BLANK_BREAK = re.compile(r"\n(?=[ \t]*\n)")
# The LaTeX citation command a use was read in starts with: `\citep`, `\citet*`.
_COMMAND = re.compile(r"\\[A-Za-z]+\*?")


def cited_as(key: str, raw: str = "", *, latex: bool = False) -> str:
    """How a finding names a cited work, as the manuscript cites it: `@key` in Markdown, and
    in LaTeX with the command `raw`, the citation a use was read in, starts with,
    `\\citep{key}`, or `\\cite{key}` where none is at hand (corpus round, 2026-10-23: a
    LaTeX paper's finding said `@key` of what its author typed as `\\citep{key}`)."""
    command = _COMMAND.match(raw)
    if command is not None:
        return f"{command.group(0)}{{{key}}}"
    return f"\\cite{{{key}}}" if latex else f"@{key}"


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
    opens one exactly when the next `]` comes before the next such break, and an `@` no word
    is glued to lies between them. Those three are found once each as the reading moves on,
    and the pattern is matched only where they say it holds, which it then does at once."""
    closes = _Next(re.compile(r"\]"), text)
    breaks = _Next(_BLANK_BREAK, text)
    signs = _Next(_SIGN, text)
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
