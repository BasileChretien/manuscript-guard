"""Where the HTML comments are. One scanner, and a linear one.

There were three copies of `<!--.*?-->` with DOTALL — in the masking, the placeholder parser
and the heading scan — and the regex read to the end of the text for every `<!--` that never
closed: 2.5 s for 2,000 such lines, 9.8 s for 4,000, twice over in one `check`. Once one
`<!--` has no closer, none after it can have one, so a scan that stops there gives the same
spans in one pass. One function, so the three cannot disagree about what is a comment.
"""

from __future__ import annotations


def comment_spans(text: str, begin: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Every `<!-- ... -->` wholly inside `text[begin:end]`, as offsets into `text`.

    The spans `re.finditer(r"<!--.*?-->", text, re.DOTALL)` finds with the same bounds: each
    comment closes at the first `-->` after its opener, and `<!-->` is not one.
    """
    stop = len(text) if end is None else end
    found = []
    position = begin
    while (opening := text.find("<!--", position, stop)) != -1:
        closing = text.find("-->", opening + 4, stop)
        if closing == -1:
            break
        found.append((opening, closing + 3))
        position = closing + 3
    return found


def blank_comments(text: str, spans: list[tuple[int, int]], fill: str = " ") -> str:
    """`text` with each span in `spans` replaced by `fill`, line breaks kept."""
    if not spans:
        return text
    pieces = []
    position = 0
    for start, finish in spans:
        pieces.append(text[position:start])
        pieces.append("".join("\n" if ch == "\n" else fill for ch in text[start:finish]))
        position = finish
    pieces.append(text[position:])
    return "".join(pieces)


__all__ = ["blank_comments", "comment_spans"]
