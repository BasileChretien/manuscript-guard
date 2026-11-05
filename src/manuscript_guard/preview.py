"""The part of a paragraph an edit changed, as `import` shows it before anything is written.

The dry run used to print each paragraph it would merge, or refused, cut to its first 150
characters. An edit past them was never seen before `--apply`, and the cut could fall inside
a binding, `{{results.hs.any_ill`, which reads as a broken one. What is shown now is each
changed stretch, the words removed and the words added, with a few words on either side.

Text is cut only between words, and a binding, a bracketed citation or a short parenthesis
counts as one word however many spaces it holds: `[@a; @b]` and "(Fictional 2021)" are
shown whole or not at all.
"""

from __future__ import annotations

import difflib
import re

#: One word as shown: a binding, a bracketed group such as a citation, a parenthesis of
#: up to `PARENTHESIS` characters such as a citation as Word prints it, or any other run of
#: characters that are not spaces, all of them joined where they touch, as in
#: `({{results.n}}%)`. A longer parenthesis is a clause more than a citation, and is cut
#: between its words like the rest, as is a bracket or a parenthesis with another inside it.
PARENTHESIS = 160
_WORD = re.compile(
    r"(?:\{\{.*?\}\}|\[[^\[\]]*\]|\([^()]{0," + str(PARENTHESIS - 2) + r"}\)|\S)+"
)
#: Words of context on either side of a change.
CONTEXT = 5
#: Changed stretches shown for one paragraph; the rest are counted. A stretch is shown whole,
#: every word changed in it: edits ten words apart or fewer are one stretch, and a stretch
#: shown by its two ends hid an edit in its middle that `--apply` wrote.
MOST = 3
#: Words of a paragraph shown where none of its words changed.
OPENING = 30
ELIDED = "..."


def _words(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in _WORD.finditer(text)]


def _shown(text: str, spans: list[tuple[int, int]], start: int, end: int) -> str:
    """The words `start` to `end` of `text`, with its spaces run together, marked where words
    before or after them are left out."""
    if start >= end:
        return ""

    middle = " ".join(text[spans[start][0] : spans[end - 1][1]].split())
    before = f"{ELIDED} " if start > 0 else ""
    after = f" {ELIDED}" if end < len(spans) else ""
    return f"{before}{middle}{after}"


def changes(was: str, now: str) -> tuple[list[tuple[str, str]], int]:
    """Each stretch of `now` that differs from `was`, as (what `was` had there, what `now`
    has), with `CONTEXT` words either side; at most `MOST` of them, and how many more there
    are. Nothing where the two have the same words."""
    old, new = _words(was), _words(now)
    words_was = [was[a:b] for a, b in old]
    words_now = [now[a:b] for a, b in new]
    matcher = difflib.SequenceMatcher(a=words_was, b=words_now, autojunk=False)
    groups = list(matcher.get_grouped_opcodes(CONTEXT))
    if groups and all(tag == "equal" for group in groups for tag, *_ in group):
        groups = []
    found = [
        (
            _shown(was, old, group[0][1], group[-1][2]),
            _shown(now, new, group[0][3], group[-1][4]),
        )
        for group in groups[:MOST]
    ]
    return found, max(0, len(groups) - MOST)


def opening(text: str, most: int = OPENING) -> str:
    """The first `most` words of `text`, never cut inside one."""
    spans = _words(text)
    return _shown(text, spans, 0, min(most, len(spans))) if spans else ""
