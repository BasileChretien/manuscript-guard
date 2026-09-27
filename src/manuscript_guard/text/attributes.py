"""Pandoc attribute blocks at the end of a heading, `# References {-}` or
`## Results {#sec-results}`, which pandoc reads and does not print.

Shared by the heading walk in `text/blocks.py`, which titles every heading without its
block, and the audit, which reads a heading line the same way.
"""

from __future__ import annotations

import re

# The spaces pandoc's `isSpace` takes, which is Haskell's: space, tab, the line breaks, form
# feed, vertical tab, the no-break space and the other space separators (category Zs). Not
# `\s`, which also takes U+0085, U+2028, U+2029 and U+001C to U+001F: a quoted value opening
# with one of those is a value to pandoc, and refusing it kept `{title="<U+0085>x y"}` in a
# Results title.
_PANDOC_SPACE = (
    r" \t\n\r\f\v\xa0\N{OGHAM SPACE MARK}\N{EN QUAD}-\N{HAIR SPACE}"
    r"\N{NARROW NO-BREAK SPACE}\N{MEDIUM MATHEMATICAL SPACE}\N{IDEOGRAPHIC SPACE}"
)

# One item of a pandoc attribute block, as pandoc 3 reads it: `#id`, `.class`, `key=value`
# or `-`, which pandoc reads as `.unnumbered`. A class or a key opens with a letter, which
# `strip_attributes` checks, since `[^\W\d_]` also takes `²` and `Ⅷ`. A value is quoted,
# and then may not open with one of pandoc's spaces (`title=" Works"` is not one, and pandoc
# prints the braces), or runs to a space, a tab, a line break or the closing brace. Only
# those: `\s` would also end it at a no-break space, a thin space or a form feed, which
# pandoc reads as part of the value, so a heading whose `lang=fr` and `FR` were joined by a
# no-break space kept its block.
#
# A value may hold backslash escapes, `title="the \"main\" one"` or `note=a\}b`, and an
# escaped `}` ends nothing: `{k=a\}` is not a block, and pandoc prints it. Each escape is one
# backslash and the character after it, and every other character is one of the rest, so a
# value can be read only one way. Items need no space between them: `{#a.b}` is one
# identifier and `{#a#b}` two, because pandoc takes the longest item it can at each point
# and never goes back. `strip_attributes` does the same, one item at a time. With the items
# under one quantifier in a single pattern, a run such as `#a.b.c` could be divided between
# items in more ways than it has characters, and a block that failed at its last character
# would try every one of them.
_ATTRIBUTE_ITEM = re.compile(
    r"#[\w:.-]+"
    r"|\.(?P<lead>[^\W\d_])[\w:.-]*"
    r"|(?P<key>[^\W\d_])[\w:.-]*="
    r"(?:\"(?![" + _PANDOC_SPACE + r"])(?:[^\"\\]|\\.)*\""
    r"|'(?![" + _PANDOC_SPACE + r"])(?:[^'\\]|\\.)*'"
    r"|(?:[^ \t\n\r}\\]|\\.)*)"
    r"|-"
)


def _escaped(text: str, index: int) -> tuple[bool, int]:
    """Whether the character at `index` is escaped, and where the backslashes before it
    start. An odd run escapes it: `\\{` is a brace, `\\\\{` a backslash and then a brace."""
    start = index
    while start > 0 and text[start - 1] == "\\":
        start -= 1
    return (index - start) % 2 == 1, start


def strip_attributes(text: str) -> str:
    """`text` without the pandoc attribute block it ends with, if it ends with one.

    `# References {-}` prints as "References", unnumbered, and `## Results {#sec-results}`
    as "Results". Kept in the title, the block made it another word: `is_methods` matches a
    title whole, so `Results {#sec-results}` was not Results, and a subsection under it named
    like a Methods one made a reported `p < 0.001` the alpha chosen in advance.

    Only what pandoc reads as attributes goes. "Results {and more}" and "Results \\{-}"
    print as they stand, and so does every block but the last. The block opens at the last
    brace no backslash escapes, and `{k=a\\{b}` is one block. Nothing else in the title
    changes: `# **Results**` keeps its asterisks. `text` comes back unchanged when nothing
    goes, so a caller can tell.

    Only spaces and tabs may follow the block, and only they are taken off what precedes it.
    `rstrip()` takes every Unicode space, and `# References {-}` with a no-break space after
    it, which pandoc prints braces and all, lost its block.
    """
    body = text.rstrip(" \t")
    if not body.endswith("}"):
        return text
    opening = len(body)
    while True:
        opening = body.rfind("{", 0, opening)
        if opening < 0:
            return text
        escaped, before = _escaped(body, opening)
        if not escaped:
            break
        opening = before
    inner, position = body[opening + 1 : -1], 0
    while True:
        while position < len(inner) and inner[position] in " \t":
            position += 1
        if position == len(inner):
            return body[:opening].rstrip(" \t")
        item = _ATTRIBUTE_ITEM.match(inner, position)
        if item is None:
            return text
        letter = item.group("lead") or item.group("key")
        if letter and not letter.isalpha():
            return text
        position = item.end()


__all__ = ["strip_attributes"]
