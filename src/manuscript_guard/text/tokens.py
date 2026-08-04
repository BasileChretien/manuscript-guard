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

# Characters of context kept either side of an atom for rule matching. Generous enough for
# the longest shipped pattern and its keyword; small enough that cost is linear in the text.
WINDOW = 160

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
    line_start: int
    line_end: int
    # The document this atom came from, held by reference. `line_text` and `window` used to
    # be materialised strings on every atom, which meant one copy of the enclosing line per
    # number: a paragraph written on a single 80 KB line with 20,000 numbers copied 1.6 GB
    # of substrings before any rule ran. Slices on demand instead.
    source: str = ""

    @property
    def line_text(self) -> str:
        return self.source[self.line_start : self.line_end]

    @property
    def window_start(self) -> int:
        return max(0, self.start - WINDOW)

    @property
    def window(self) -> str:
        """A bounded slice of surrounding text with line breaks flattened to spaces.

        Rules are matched against this rather than against the atom's own line, for two
        reasons, and the first is the one that matters.

        Matching a line meant a rule broke wherever the author's editor happened to wrap:
        "a 95% confidence interval" classified, and the identical phrase split as
        "a 95%\nconfidence interval" did not. Every manuscript here is hard-wrapped, so
        roughly one convention in ten failed for a reason invisible in the error message —
        which makes the gate look random rather than strict, and that is how an author
        learns to stop reading it.

        The second is cost: a rule ran against the entire line once per atom, so a long
        line was quadratic. A paragraph written on one 80 KB line took minutes.
        """
        end = self.end + WINDOW
        return self.source[self.window_start : end].replace("\r", " ").replace("\n", " ")

    @property
    def in_line(self) -> tuple[int, int]:
        """Span of this atom within its own line."""
        return self.start - self.line_start, self.end - self.line_start

    @property
    def in_window(self) -> tuple[int, int]:
        return self.start - self.window_start, self.end - self.window_start


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
    # Line numbers counted incrementally. `original.count("\n", 0, start)` per atom is a
    # full scan per number, so a document with many numbers was quadratic in its own length
    # — 20,000 atoms in an 80 KB file meant 1.6 billion character comparisons just to
    # number the lines. Atoms arrive in document order, so only the gap needs counting.
    seen_upto = 0
    seen_lines = 0

    for match in _ATOM.finditer(masked):
        raw = match.group(0)
        if not DIGIT.search(raw):
            continue
        text, start = _trim(raw, match.start())
        if not text or not DIGIT.search(text):
            continue
        end = start + len(text)
        seen_lines += original.count("\n", seen_upto, start)
        seen_upto = start
        line_start = original.rfind("\n", 0, start) + 1
        found_end = original.find("\n", start)
        line_end = len(original) if found_end == -1 else found_end
        atoms.append(
            Atom(
                text=text,
                start=start,
                end=end,
                line=seen_lines + 1,
                col=start - line_start + 1,
                line_start=line_start,
                line_end=line_end,
                source=original,
            )
        )
    return atoms
