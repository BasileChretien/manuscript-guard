"""The binding syntax: `{{results.key}}`, `{{lit.key}}`, `{{table.key}}`, `{{figure.key}}`,
and `{{method.step}}`, the anchor that points a Methods claim at the code step it describes.

There is deliberately no formatting option. How a value is written is decided once, at emit
time, by the script that computed it, and every place that quotes the value gets the same
string. An author who genuinely needs a coarser form in the abstract emits a second key for
it, which makes the second rounding a visible decision rather than an accident.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass

from manuscript_guard.text.masking import blank_comments

VALUE_NAMESPACES = ("results", "lit")
BLOCK_NAMESPACES = ("table", "figure")
#: An anchor prints nothing. It says which step of the analysis the text before it describes,
#: back to the anchor before it or the start of its paragraph (`gates/methods.py`).
ANCHOR_NAMESPACE = "method"
NAMESPACES = VALUE_NAMESPACES + BLOCK_NAMESPACES + (ANCHOR_NAMESPACE,)

PLACEHOLDER = re.compile(
    r"\{\{\s*(?P<ns>[a-z]+)\.(?P<key>[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)\s*\}\}"
)
# Anything with the shape of a placeholder. Used to catch typos that the strict pattern
# would otherwise skip in silence, which is the worst possible outcome for a binding.
#
# The closing brace is optional because a missing one is the typo most worth catching:
# `{{results.ror.point}` required `}}` to be recognised at all, so it was neither a binding
# nor "malformed" — it travelled all the way into the built document as literal text, in
# the place where a number was supposed to be. A stray `{{` on its own line is left alone;
# this needs the namespace-and-key shape before it will call anything a placeholder.
#
# The last alternative takes no closing brace at all. A binding cut in half by a bad merge -
# `{{lit.agency.withdrawnWhether the signal extends` - has none on its line, so the first
# alternative never matched it and `check` passed a paragraph that `build` then printed.
LOOSE = re.compile(
    r"\{\{\s*[a-z]+\.[^}\n]*\}{1,2}|\{\{[^}\n]*\}\}|\{\{\s*[a-z]+\.[A-Za-z0-9_.]+"
)


@dataclass(frozen=True)
class Placeholder:
    namespace: str
    key: str
    raw: str
    start: int
    end: int
    line: int
    col: int

    @property
    def ref(self) -> str:
        return f"{self.namespace}.{self.key}"

    @property
    def is_value(self) -> bool:
        return self.namespace in VALUE_NAMESPACES

    @property
    def is_anchor(self) -> bool:
        return self.namespace == ANCHOR_NAMESPACE


def _without_comments(text: str) -> str:
    """The same text with HTML comments blanked, offsets and line breaks intact.

    Pandoc deletes an HTML comment, so a binding inside one is never rendered and never
    substituted — and requiring it to resolve made an ordinary editing habit fail the gate.
    Commenting out a draft paragraph and then removing the key it quoted reported
    `unresolved-binding` against text that reaches no document. The project's own `init`
    scaffold hit this on its first run: its guidance names `{{results.some_key}}` to explain
    the syntax, and the explanation failed the check it was explaining.

    Blanked rather than removed so every offset, line and column still refers to the file
    the author is looking at. Only what pandoc drops is blanked: `` `<!--` `` is code, and
    so is a `<!--` in a listing, and a binding after either is printed like any other. A
    comment opened in the front matter ends with it, as pandoc reads it: run on to the next
    comment in the body, it took every binding between out of G2, and a reversed interval
    passed.
    """
    if "<!--" not in text:
        return text
    return blank_comments(text)


def parse(text: str) -> tuple[list[Placeholder], list[tuple[str, int, int]]]:
    """Return well-formed placeholders and the malformed ones, with positions.

    A line is looked up among the starts of the lines, by bisection, and the column is
    counted from the start found. Each binding had its line breaks counted from the top of
    the file: 5,000 bindings took 0.35 seconds and 40,000 took 18.5, on every `check`.
    """
    good: list[Placeholder] = []
    spans: set[tuple[int, int]] = set()
    text = _without_comments(text)
    # A line ends at a line feed and nowhere else: a form feed or a carriage return alone,
    # where `str.splitlines` starts another line, is a character of its line.
    starts = [0, *(found.end() for found in re.finditer("\n", text))]
    for match in PLACEHOLDER.finditer(text):
        namespace = match.group("ns")
        if namespace not in NAMESPACES:
            continue
        line = bisect_right(starts, match.start())
        good.append(
            Placeholder(
                namespace=namespace,
                key=match.group("key"),
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
                line=line,
                col=match.start() - starts[line - 1] + 1,
            )
        )
        spans.add((match.start(), match.end()))

    malformed = [
        (m.group(0), m.start(), bisect_right(starts, m.start()))
        for m in LOOSE.finditer(text)
        if (m.start(), m.end()) not in spans
    ]
    return good, malformed


def anchor_cuts(text: str, placeholders: Iterable[Placeholder]) -> list[tuple[int, int]]:
    """What the anchors among `placeholders` take out of `text` when it is printed, in order:
    each anchor, and the whole of a line that holds nothing but anchors and spaces, with its
    line break. Everything that prints a manuscript takes these out and nothing else for an
    anchor: the build, the annotated copy, `render` and a review panel's prompt.

    An anchor on a line of its own, after the sentence it is about, once left that line
    behind, empty, and an empty line ends a paragraph: the document broke a paragraph in two
    where the source has one. A line with anything else on it stays, less its anchors. That
    includes the mark of a quotation or a list, `> {{method.a}}`: what a mark with nothing
    after it reads as depends on the lines around it, and this does not look.
    """
    anchors = sorted((found.start, found.end) for found in placeholders if found.is_anchor)
    cuts: list[tuple[int, int]] = []
    first = 0
    while first < len(anchors):
        # The line the anchor stands on, to the end of the line its last brace is on: one
        # line, unless the braces were typed on lines of their own.
        start = text.rfind("\n", 0, anchors[first][0]) + 1
        end = text.find("\n", anchors[first][1]) + 1 or len(text)
        after = first + 1
        while after < len(anchors) and anchors[after][0] < end:
            end = text.find("\n", anchors[after][1]) + 1 or len(text)
            after += 1
        here = anchors[first:after]
        beside = zip([start, *(b for _a, b in here)], [*(a for a, _b in here), end], strict=True)
        alone = not "".join(text[a:b] for a, b in beside).strip(" \t\r\n")
        cuts += [(start, end)] if alone else here
        first = after
    return cuts


def spliced(text: str, pieces: Iterable[tuple[int, int, str]]) -> str:
    """`text` with each `(start, end, replacement)` put in. No two may overlap."""
    out: list[str] = []
    at = 0
    for start, end, replacement in sorted(pieces):
        out += [text[at:start], replacement]
        at = end
    return "".join([*out, text[at:]])


def substitute(text: str, rendered: dict[str, str]) -> str:
    """Replace every placeholder whose ref is in `rendered`, and print nothing for an anchor
    (`anchor_cuts`). Others are left untouched.
    """
    placeholders, _ = parse(text)
    pieces = [(start, end, "") for start, end in anchor_cuts(text, placeholders)]
    pieces += [
        (found.start, found.end, rendered[found.ref])
        for found in placeholders
        if not found.is_anchor and found.ref in rendered
    ]
    return spliced(text, pieces)
