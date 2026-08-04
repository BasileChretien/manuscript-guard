"""The binding syntax: `{{results.key}}`, `{{lit.key}}`, `{{table.key}}`, `{{figure.key}}`.

There is deliberately no formatting option. How a value is written is decided once, at emit
time, by the script that computed it, and every place that quotes the value gets the same
string. An author who genuinely needs a coarser form in the abstract emits a second key for
it, which makes the second rounding a visible decision rather than an accident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VALUE_NAMESPACES = ("results", "lit")
BLOCK_NAMESPACES = ("table", "figure")
NAMESPACES = VALUE_NAMESPACES + BLOCK_NAMESPACES

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
LOOSE = re.compile(r"\{\{\s*[a-z]+\.[^}\n]*\}{1,2}|\{\{[^}\n]*\}\}")


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


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _without_comments(text: str) -> str:
    """The same text with HTML comments blanked, offsets and line breaks intact.

    Pandoc deletes an HTML comment, so a binding inside one is never rendered and never
    substituted — and requiring it to resolve made an ordinary editing habit fail the gate.
    Commenting out a draft paragraph and then removing the key it quoted reported
    `unresolved-binding` against text that reaches no document. The project's own `init`
    scaffold hit this on its first run: its guidance names `{{results.some_key}}` to explain
    the syntax, and the explanation failed the check it was explaining.

    Blanked rather than removed so every offset, line and column still refers to the file
    the author is looking at.
    """
    if "<!--" not in text:
        return text
    out = list(text)
    for match in _COMMENT.finditer(text):
        for index in range(match.start(), match.end()):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


def parse(text: str) -> tuple[list[Placeholder], list[tuple[str, int, int]]]:
    """Return well-formed placeholders and the malformed ones, with positions."""
    good: list[Placeholder] = []
    spans: set[tuple[int, int]] = set()
    text = _without_comments(text)
    for match in PLACEHOLDER.finditer(text):
        namespace = match.group("ns")
        if namespace not in NAMESPACES:
            continue
        line = text.count("\n", 0, match.start()) + 1
        col = match.start() - (text.rfind("\n", 0, match.start()) + 1) + 1
        good.append(
            Placeholder(
                namespace=namespace,
                key=match.group("key"),
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
                line=line,
                col=col,
            )
        )
        spans.add((match.start(), match.end()))

    malformed = [
        (m.group(0), m.start(), text.count("\n", 0, m.start()) + 1)
        for m in LOOSE.finditer(text)
        if (m.start(), m.end()) not in spans
    ]
    return good, malformed


def substitute(text: str, rendered: dict[str, str]) -> str:
    """Replace every placeholder whose ref is in `rendered`. Others are left untouched.

    Substitution walks backwards so that earlier offsets stay valid.
    """
    placeholders, _ = parse(text)
    out = text
    for placeholder in sorted(placeholders, key=lambda p: p.start, reverse=True):
        if placeholder.ref in rendered:
            out = out[: placeholder.start] + rendered[placeholder.ref] + out[placeholder.end :]
    return out
