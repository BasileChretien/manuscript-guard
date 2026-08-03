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

# [@key], [-@key], [@key, p. 4; @other]
BRACKETED = re.compile(r"\[(?P<body>[^\]\n]*@[^\]\n]*)\]")
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
        line = text.count("\n", 0, match.start()) + 1
        for key_match in KEY_IN_BODY.finditer(match.group("body")):
            uses.append(
                CitationUse(
                    citekey=key_match.group("key").rstrip(".,;:"),
                    path=path,
                    line=line,
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
