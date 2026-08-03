"""Finding the things in a manuscript that might be numbers.

The unit is an *atom*: a maximal run of non-whitespace containing at least one digit, with
surrounding punctuation trimmed. Atoms rather than bare numbers, because splitting on
digits alone turns CYP3A4 into "3" and "4" and COVID-19 into "19", and a checker that
reports those has to be silenced to be usable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# `\d` is Unicode Nd, which is the right default and misses two families of character that
# render as numbers and read as numbers. A manuscript writing "½ of the cohort" or "④ events"
# said something numeric that no gate saw, because no Nd digit was present anywhere in the
# atom. Both families are listed explicitly rather than taken as the whole of Unicode N:
#
#   Superscripts are deliberately excluded. `m²`, `cm³`, `R²` and `χ²` are units and names,
#   not claims, and admitting them would report every square metre in the paper. `10⁶` is
#   already caught by its `10`.
#   Roman numerals (Nl) are excluded for the same reason: "phase Ⅲ" is a label.
_FRACTIONS = "¼½¾⅐⅑⅒⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞↉"
_ENCLOSED = "①-⒛⓪⓵-⓾❶-➓"
DIGIT = re.compile(f"[\\d{_FRACTIONS}{_ENCLOSED}]")
# An atom is bounded by whitespace *or* by a masked region. Both boundaries matter, and the
# second one is easy to get wrong: `mask()` preserves offsets by writing NUL, which is not
# whitespace, so a run of `\S+` reaches straight through a mask boundary. Written that way,
# `3.84[@smith2020]` is one atom, that atom contains NUL, and the whole run — the visible
# 3.84 included — was discarded before it was ever classified. Any value written hard against
# a citation, a footnote marker, inline code or a pandoc attribute disappeared from the gate
# that carries the core invariant. Splitting at the mask boundary instead keeps the claim and
# drops only the masked part, which is what masking was always supposed to mean.
_ATOM = re.compile(r"[^\s\x00]+")

# Trimmed from either end. Percent, degree and prime are kept: they belong to the value.
# Backticks are delimiters like any other now that inline code is read rather than masked:
# `3.84` is the value 3.84 wrapped in punctuation, and must compare equal to it.
_LEAD = "([{<\"'“‘«¡¿*_~|>#+`"
# `[` trails now that citation *keys* are masked rather than whole brackets: `3.84[@key]`
# leaves the digits hard against an opening bracket, and an atom of `3.84[` matches no
# results display and reads badly in a finding.
_TRAIL = ")]}>\"'”’»,;:!?*_~|.…`["


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
        if not DIGIT.search(raw):
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
