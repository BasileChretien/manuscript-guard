"""Where the HTML comments are.

There were three copies of `<!--.*?-->` — in `masking.py`, `sections.py` and
`placeholders.py` — and they shared two faults.

**They did not know about code.** Pandoc prints `` `<!--` `` as code, not as the start of
a comment. The regex took it for one and hid everything up to the next `-->`, so

    We stripped `<!--` markers. The ROR was 9.99.

    Note: `-->` closes.

printed the ROR while G2, the audit, the heading scan and the binding parser all read
nothing between the two markers. The audit reported 0 numeric tokens and `--strict` passed.
Code spans, raw HTML and fenced blocks each start where they start, and whichever starts
first wins, so the only way to know is to read from the left.

**And they backtracked.** Every `<!--` with no `-->` after it read to the end of the text:
5,000 of them kept `mask` busy for over two minutes.

Comments are found in the same pass as fences and code spans, because each can swallow the
others: see `text/scan.py`, which holds the rules. `masking.html_comments` asks with the
front matter set apart.
"""

from __future__ import annotations

from manuscript_guard.text.scan import scan


def comment_spans(text: str, begin: int = 0) -> list[tuple[int, int]]:
    """Every HTML comment pandoc drops from `text`, as (start, end) offsets, in order.

    Linear in the length of the text, give or take a logarithm.
    """
    return scan(text, begin).comments


__all__ = ["comment_spans"]
