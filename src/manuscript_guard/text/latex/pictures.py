"""What a TikZ picture prints as text, found in its source (DESIGN.md, "LaTeX manuscripts").

The reader passes a `tikzpicture` over, its options, coordinates, styles and paths, as
`\\includegraphics` passes over a picture's file. What the picture prints as text is read:
a flow diagram's boxes, `\\node[draw] {Reports screened (n = 4371)};`, hold the paper's
numbers (round 1 of #443: blanked whole, such a number was seen by no gate). That is:

- a node's text, the braces after `\\node`, or after `node` in a path, past the node's name
  `(a)`, its options `[...]` and its place `at (x,y)`;
- a label's and a pin's text, `label={[red]above:Text}` or `label=above:Text`, past its
  options and its angle, which TikZ takes to the first colon;
- a node's text given as `node contents=`, and the cells of a `matrix of nodes`, its braces
  read whole, the cells' own options `|[draw]|` with them;
- pgfplots' axis labels and title, `xlabel=...`, `ylabel=`, `zlabel=`, `title=`, its
  `legend entries=` and the text of `\\addlegendentry{...}` and `\\legend{...}`.

A text in braces is read as prose, by the reader, from where its prose starts. One without
braces, `label=above:Text`, runs to the next comma, bracket or brace of its options, or its
line's end, and is read as typed.
"""

from __future__ import annotations

import re

#: A comment to its line's end, which the scan reads as spaces.
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
#: A node: `\\node`, or `node` as a word of a path; `every node/.style` and `node distance`
#: name none, since no brace follows them.
_NODE = re.compile(r"\\node(?![A-Za-z@])|(?<![\\A-Za-z@])node(?![A-Za-z@])")
#: A matrix of nodes, whose cells are nodes' text: its braces, after its options, are read.
_MATRIX = re.compile(r"\\matrix(?![A-Za-z@])")
#: The keys whose value the picture prints as text.
_KEYS = re.compile(
    r"(?<![\\A-Za-z@])(label|pin|xlabel|ylabel|zlabel|title|legend entries|node contents)"
    r"[ \t]*=[ \t]*"
)
#: The keys whose value opens with options and an angle before its text.
_ANGLED = frozenset({"label", "pin"})
#: pgfplots' commands that print a legend's text.
_LEGEND = re.compile(r"\\(?:addlegendentry|legend)(?![A-Za-z@])\*?[ \t]*(?:\[[^\]\n]*\])?[ \t]*")


def printed_in(text: str, start: int, end: int) -> tuple[dict[int, int], list[tuple[int, int]]]:
    """What the picture between `start` and `end` prints as text: each brace that opens a
    text, with where its prose starts; and each text without braces, as a span."""
    view = _COMMENT.sub(lambda found: " " * len(found.group(0)), text[start:end])
    braces: dict[int, int] = {}
    spans: list[tuple[int, int]] = []
    for found in _NODE.finditer(view):
        opened = _node_text(view, found.end())
        if opened >= 0:
            braces[start + opened] = start + opened + 1
    for found in _MATRIX.finditer(view):
        opened = _node_text(view, found.end())
        if opened >= 0 and "matrix of" in view[found.end() : opened]:
            braces[start + opened] = start + opened + 1
    for found in _LEGEND.finditer(view):
        if view[found.end() : found.end() + 1] == "{":
            braces[start + found.end()] = start + found.end() + 1
    for found in _KEYS.finditer(view):
        at, angled = found.end(), found.group(1) in _ANGLED
        if view[at : at + 1] == "{":
            closed = _closing(view, at, "{", "}")
            if closed > 0:
                prose = _past_angle(view, at + 1, closed - 1) if angled else at + 1
                braces[start + at] = start + prose
            continue
        stop = _value_end(view, at)
        prose = _past_angle(view, at, stop) if angled else at
        if stop > prose:
            spans.append((start + prose, start + stop))
    return braces, spans


def _skip_spaces(view: str, at: int) -> int:
    while at < len(view) and view[at] in " \t\r\n":
        at += 1
    return at


def _node_text(view: str, at: int) -> int:
    """Where the braces of a node's text open, past its name, options and place; -1 where
    something else follows, which is then no node's text."""
    while True:
        at = _skip_spaces(view, at)
        here = view[at : at + 1]
        if here == "{":
            return at
        if here in ("[", "("):
            at = _closing(view, at, here, "]" if here == "[" else ")")
            if at < 0:
                return -1
        elif view.startswith("at", at) and not view[at + 2 : at + 3].isalpha():
            at += 2
        else:
            return -1


def _closing(view: str, at: int, opener: str, closer: str) -> int:
    """Past the `closer` that closes the `opener` at `at`, braces nested in it; -1 where
    none does."""
    depth, braces = 0, 0
    for index in range(at, len(view)):
        character = view[index]
        if character == "\\":
            continue
        if opener != "{" and character in "{}":
            braces += 1 if character == "{" else -1
            continue
        if braces:
            continue
        if character == opener and (index == at or view[index - 1] != "\\"):
            depth += 1
        elif character == closer and view[index - 1] != "\\":
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def _past_angle(view: str, at: int, stop: int) -> int:
    """Where a label's text starts: past its options and its angle, to the first colon."""
    at = _skip_spaces(view, at)
    if view[at : at + 1] == "[":
        closed = _closing(view, at, "[", "]")
        at = closed if 0 < closed <= stop else at
    colon = view.find(":", at, stop)
    return at if colon < 0 else colon + 1


def _value_end(view: str, at: int) -> int:
    """Where a value without braces ends: at a comma, a bracket or a brace of its options,
    or its line's end, braces and brackets in it nested."""
    depth = 0
    for index in range(at, len(view)):
        character = view[index]
        if character in "{[":
            depth += 1
        elif character in "}]":
            if not depth:
                return index
            depth -= 1
        elif character in ",\n" and not depth:
            return index
    return len(view)
