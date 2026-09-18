"""Finding citations in manuscript source.

Both pandoc forms are recognised, and the distinction matters at build time: a bracketed
`[@key]` becomes a parenthetical citation, while a narrative `@key` renders the author in
the sentence. The `zotero.lua` filter handles them differently, and an early test of the
pipeline found that narrative citations produced no field at all unless configured, so the
build has to know which is which rather than counting them together.
"""

from __future__ import annotations

import re
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


@dataclass(frozen=True)
class CitationUse:
    citekey: str
    path: Path
    line: int
    narrative: bool
    raw: str


def find_citations(text: str, path: Path) -> list[CitationUse]:
    uses: list[CitationUse] = []
    bracketed_spans: list[tuple[int, int]] = []

    for match in BRACKETED.finditer(text):
        bracketed_spans.append(match.span())
        body_start = match.start("body")
        for key_match in KEY_IN_BODY.finditer(match.group("body")):
            uses.append(
                CitationUse(
                    citekey=key_match.group("key").rstrip(".,;:"),
                    path=path,
                    # The line the key itself is on: in a wrapped group that is not the
                    # line the group opens on.
                    line=text.count("\n", 0, body_start + key_match.start()) + 1,
                    narrative=False,
                    raw=match.group(0),
                )
            )

    for match in NARRATIVE.finditer(text):
        if any(start <= match.start() < end for start, end in bracketed_spans):
            continue
        uses.append(
            CitationUse(
                citekey=match.group("key").rstrip(".,;:"),
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
                narrative=True,
                raw=match.group(0),
            )
        )

    return uses
