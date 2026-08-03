"""Blanking the regions of a Markdown source where a digit is not a claim.

Masking replaces characters with NUL rather than deleting them, so every offset in the
masked string still points at the same place in the original. That is what lets a finding
report a real line and column.

Getting this list wrong is the main way a checker like this goes quietly wrong. Too little
masking and the author drowns in findings about DOIs and citation keys, then stops reading
them. Too much and a genuine claim hides inside a masked region — which is the more
dangerous direction, so anything questionable is left unmasked and allowed to fail loudly.
"""

from __future__ import annotations

import re

NUL = "\x00"

# Ordered: earlier patterns win, because a URL inside a code fence is already gone.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # YAML frontmatter, only when it opens the file.
    ("frontmatter", re.compile(r"\A---\r?\n.*?\r?\n(?:---|\.\.\.)\r?\n", re.DOTALL)),
    (
        "fenced-code",
        re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.DOTALL | re.MULTILINE),
    ),
    ("html-comment", re.compile(r"<!--.*?-->", re.DOTALL)),
    ("inline-code", re.compile(r"`[^`\n]+`")),
    ("placeholder", re.compile(r"\{\{[^}\n]*\}\}")),
    ("autolink", re.compile(r"<(?:https?|doi|mailto):[^>\s]+>")),
    ("url", re.compile(r"(?:https?://|www\.|doi:\s*|10\.\d{4,9}/)\S+", re.IGNORECASE)),
    ("link-target", re.compile(r"\]\([^)\n]*\)")),
    ("footnote", re.compile(r"\[\^[^\]\n]+\]")),
    # Citation keys, bracketed and narrative. Better BibTeX keys routinely end in a year.
    ("citation", re.compile(r"\[-?@[^\]\n]+\]")),
    ("citation-bare", re.compile(r"(?<![\w`])-?@[A-Za-z][\w:.#$%&+?<>~/-]*")),
    ("pandoc-attr", re.compile(r"\{[.#][^}\n]*\}")),
)


def mask(text: str) -> str:
    """Return `text` with non-claim regions replaced by NUL, preserving length."""
    chars = list(text)
    for _name, pattern in _PATTERNS:
        for match in pattern.finditer("".join(chars)):
            for index in range(match.start(), match.end()):
                chars[index] = NUL
    return "".join(chars)


def masked_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    """What each pattern matched. Used by the test suite and by `explain` output."""
    found: dict[str, list[tuple[int, int]]] = {}
    working = text
    for name, pattern in _PATTERNS:
        spans = [(m.start(), m.end()) for m in pattern.finditer(working)]
        if spans:
            found[name] = spans
            chars = list(working)
            for start, end in spans:
                for index in range(start, end):
                    chars[index] = NUL
            working = "".join(chars)
    return found


def line_col(text: str, offset: int) -> tuple[int, int]:
    """1-indexed line and column of a character offset."""
    line = text.count("\n", 0, offset) + 1
    start = text.rfind("\n", 0, offset) + 1
    return line, offset - start + 1


def line_at(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start : len(text) if end == -1 else end]
