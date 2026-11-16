"""Where a Markdown paper's text holds maths, as pandoc's `tex_math_dollars` reads it.

The Abstract against Results reads a `~` as TeX's tie, a gap around a times sign, only in
maths (`auditing.abstract.ties`): in Markdown's text it marks pandoc's subscript, `CO~2~`.
Read within one line, maths wrapped across a line break, or display maths on lines of its
own, had each of its ties read as no gap (the check of 191d0e7c2 in #696). So maths is
found here as pandoc finds it (Basile: "`$...$` within a paragraph across line breaks, with
pandoc's rules for where `$` opens and closes; `$$...$$` across lines; none inside code";
pandoc's `mathInlineWith` and `mathDisplayWith`):

- `$$...$$` first, at least one character between, across lines but no blank line.
- `$...$`: the `$` that opens has no space after it; within, a backslash takes the
  character after it and `\\text{...}` its braces whole, and a run of spaces, or one line
  break with no blank line after it, is never directly before the `$` that closes; the `$`
  that closes has no digit after it, or no maths is read from the `$` that opened.
- None in a code span, a fenced code block or an HTML comment, which are read first, and
  none from an escaped `\\$`. `\\(...\\)` is no maths: pandoc's Markdown does not read it
  as maths by default.
"""

from __future__ import annotations

import re

_BLANK_LINE = re.compile(r"[ \t]*(?:\n|$)")
#: A line that opens a block of its own, which pandoc parses apart, so that no inline maths
#: runs into it: a list item, a table row, a heading, a block quote, a fence (round of 1f0ced14a).
_NEW_BLOCK = re.compile(r"[ \t]*(?:[-*+][ \t]|\d+[.)][ \t]|[|#>]|`{3}|~{3})")


def _blank_after(text: str, at: int) -> bool:
    """Whether a blank line, or the end, follows the line break at `at`."""
    return _BLANK_LINE.match(text, at + 1) is not None


def _display_end(text: str, at: int) -> int | None:
    """Past the `$$` that closes display maths opening at `at`, or None."""
    index = at + 2
    while index < len(text):
        if text.startswith("$$", index) and index > at + 2:
            return index + 2
        if text[index] == "\n" and _blank_after(text, index):
            return None
        index += 1
    return None


def _group_end(text: str, at: int) -> int | None:
    """Past the `}` that closes the `{` at `at`, braces nesting, or None."""
    depth = 0
    for index in range(at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _inline_end(text: str, at: int) -> int | None:
    """Past the `$` that closes inline maths opening at `at`, or None where pandoc reads
    none from it."""
    index = at + 1
    if index >= len(text) or text[index].isspace():
        return None
    while index < len(text):
        character = text[index]
        if character == "$" and index > at + 1:
            after = index + 1
            return None if after < len(text) and text[after].isdigit() else after
        if character == "\\":
            group = _group_end(text, index + 5) if text.startswith("\\text{", index) else None
            index = index + 2 if group is None else group
            continue
        if character in " \t\n":
            while index < len(text) and text[index] in " \t":
                index += 1
            if index < len(text) and text[index] == "\n":
                if _blank_after(text, index) or _NEW_BLOCK.match(text, index + 1):
                    return None
                index += 1
            if index >= len(text) or text[index] == "$":
                return None
            continue
        index += 1
    return None


def _code(text: str) -> list[tuple[int, int]]:
    """Where no maths is read, as the mask finds it: each fenced code block
    (`fences.fenced_spans`), HTML comment (`comments.comment_spans`) and code span
    (`masking._code_spans`), in order."""
    from manuscript_guard.text.comments import comment_spans
    from manuscript_guard.text.fences import fenced_spans
    from manuscript_guard.text.masking import _code_spans

    fences = fenced_spans(text)
    return sorted([(fence.start, fence.end) for fence in fences]
                  + comment_spans(text, fences) + _code_spans(text))  # fmt: skip


def markdown_maths(text: str) -> list[tuple[int, int]]:
    """Each stretch of maths in a Markdown paper's text, as offsets `[start, end)`."""
    spans: list[tuple[int, int]] = []
    skipped, next_skip = _code(text), 0
    index = 0
    while index < len(text):
        while next_skip < len(skipped) and skipped[next_skip][1] <= index:
            next_skip += 1
        if next_skip < len(skipped) and skipped[next_skip][0] <= index:
            index = skipped[next_skip][1]
            continue
        character = text[index]
        if character == "\\":
            index += 2
        elif character == "$":
            end = (_display_end(text, index) if text.startswith("$$", index) else None) or (
                _inline_end(text, index))  # fmt: skip
            if end is None:
                index += 1
            else:
                spans.append((index, end))
                index = end
        else:
            index += 1
    return spans
