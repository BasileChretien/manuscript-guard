"""Where the fenced code blocks are. One implementation, scanned linearly.

There were three copies of a regex for this — in `masking.py`, `sections.py` and
`gates/numbers.py` — and they were wrong in the same two ways, which is what three copies
of anything eventually are.

**They required the closing fence to be exactly the opening run.** CommonMark, and pandoc,
close a fence on any run of the same character *at least as long*. So

    ```python
    x = 1
    ````                                    <- four: closes for pandoc, not for the regex

    The reporting odds ratio was 9.99.      <- an ordinary paragraph in the .docx

    ```python
    y = 2
    ```

left a whole paragraph of prose inside what the toolkit believed was one code block. G2 saw
no atoms at all, and `explain` did not mention the number. A laundering route needing one
extra backtick.

**And they backtracked.** `(?P<tick>`{3,})...(.*?)^(?P=tick)$` with DOTALL re-scans the rest
of the document for every opener-shaped line that never closes, which is O(n²): 1,000 such
lines took 0.24s, 4,000 took 6.1s, and a 3,000-line file made `manuscript-guard check`
exceed a minute. That is reachable by accident — a paper about Markdown, or one missing a
closing fence — and it undermines the claim that `check` is safe to run on a manuscript
someone sent you.

A line scanner has neither problem and is easier to read than the regex was.

It is not a line scanner any more, because a fence cannot be found alone. A code span or a
comment that starts first swallows a fence line, and a `~~~` line inside a paragraph is
prose, so the lines are read in the same pass as those: see `text/scan.py`, which holds the
rules. This module keeps the questions its callers ask.
"""

from __future__ import annotations

from manuscript_guard.text.scan import Fence, scan


def fenced_spans(text: str, begin: int = 0) -> list[Fence]:
    """Every fenced block pandoc reads as one, in document order. Linear in the text.

    An **unterminated** fence is not a fence. Pandoc's markdown reader renders the opening
    ``` as literal text and the rest of the document as ordinary paragraphs — verified
    against pandoc 3.9.0.2 — so treating it as code to the end of the file would mask prose
    the reader plainly sees. That is the same failure as the longer-closer bug, arrived at
    from the other side, and `tests/test_pandoc_agreement.py` caught it here.

    `begin`, the start of a line, is where the body starts: a fence before it, in the front
    matter, closes before it. Offsets are into `text`. `masking.fenced_blocks` asks with the
    front matter found for you.
    """
    return scan(text, begin).fences


def blank_fences(text: str) -> str:
    """`text` with every fenced block replaced by spaces, offsets and newlines preserved."""
    chars = list(text)
    for fence in fenced_spans(text):
        for position in range(fence.start, fence.end):
            if chars[position] != "\n":
                chars[position] = " "
    return "".join(chars)


__all__ = ["Fence", "blank_fences", "fenced_spans"]
