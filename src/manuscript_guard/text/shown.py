"""Text somebody else wrote, made safe to show in a terminal.

A co-author's comment, a reply in Word, a reviewer's words: printed as written, an escape
sequence in them could move the cursor, recolour the terminal or hide the lines before it,
and a bidirectional control could make a line read in another order than it holds. So they
are shown with every such character as `?`, and stored as written.
"""

from __future__ import annotations

import unicodedata

#: The bidirectional controls, which reorder what follows them on screen.
_BIDI = frozenset(map(chr, (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F),
                            *range(0x2066, 0x206A))))  # fmt: skip


def printable(text: str) -> str:
    """`text` with every character a terminal would act on, rather than show, as `?`: a
    control character (an escape, a carriage return) and a bidirectional control. A line
    break is kept, and so is a no-break space, which Word puts in "5 mg" and before a
    French colon."""
    return "".join(
        "?" if c in _BIDI or (unicodedata.category(c) == "Cc" and c != "\n") else c for c in text
    )


def one_line(text: str, limit: int) -> str:
    """`text` as `printable` shows it, on one line, cut at `limit` characters."""
    shown = " ".join(printable(text).split())
    return shown if len(shown) <= limit else shown[:limit] + " [...]"
