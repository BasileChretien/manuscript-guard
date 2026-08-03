"""Finding the things in a manuscript that might be numbers.

The unit is an *atom*: a maximal run of non-whitespace containing at least one digit, with
surrounding punctuation trimmed. Atoms rather than bare numbers, because splitting on
digits alone turns CYP3A4 into "3" and "4" and COVID-19 into "19", and a checker that
reports those has to be silenced to be usable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DIGIT = re.compile(r"\d")
_ATOM = re.compile(r"\S+")

# Trimmed from either end. Percent, degree and prime are kept: they belong to the value.
_LEAD = "([{<\"'“‘«¡¿*_~|>#+"
_TRAIL = ")]}>\"'”’»,;:!?*_~|.…"


@dataclass(frozen=True)
class Atom:
    """One candidate number, with everything a classifier needs to judge it."""

    text: str
    start: int
    end: int
    line: int
    col: int
    line_text: str
    line_start: int

    @property
    def in_line(self) -> tuple[int, int]:
        """Span of this atom within its own line."""
        return self.start - self.line_start, self.end - self.line_start


def _trim(text: str, start: int) -> tuple[str, int]:
    lead = 0
    while lead < len(text) and text[lead] in _LEAD:
        lead += 1
    trail = len(text)
    while trail > lead and text[trail - 1] in _TRAIL:
        trail -= 1
    return text[lead:trail], start + lead


def find_atoms(original: str, masked: str) -> list[Atom]:
    """Atoms present in `masked`, reported with positions and context from `original`.

    Both strings are required and must be the same length: the mask decides *whether* a
    region counts, while the original supplies the readable context for the report.
    """
    if len(original) != len(masked):
        raise ValueError("masked text must be the same length as the original")

    atoms: list[Atom] = []
    for match in _ATOM.finditer(masked):
        raw = match.group(0)
        if "\x00" in raw or not DIGIT.search(raw):
            continue
        text, start = _trim(raw, match.start())
        if not text or not DIGIT.search(text):
            continue
        end = start + len(text)
        line_start = original.rfind("\n", 0, start) + 1
        line_end = original.find("\n", start)
        line_text = original[line_start : len(original) if line_end == -1 else line_end]
        atoms.append(
            Atom(
                text=text,
                start=start,
                end=end,
                line=original.count("\n", 0, start) + 1,
                col=start - line_start + 1,
                line_text=line_text,
                line_start=line_start,
            )
        )
    return atoms
