"""Where an audit has got to, for a reader who waits on it.

The in-browser page runs the audit in one call it cannot look inside, and showed only a clock
while it ran. The author asked to see what is being done and how long is left (2026-11-12).
So the audit says each step as it starts, and the page draws the steps and the time left
from them. The command line tells nothing: `STEP` is None there, and `step` costs a test.

The steps, in the order an audit takes them: `read` (the papers and the outputs), `numbers`
(their numbers, against the outputs and each other, and the reference lists read), `words`
(G6 and G14), `lookup` (each reference asked of the registries, with how many of how many),
and `report`. The page adds its own after them: the PDF, and the copy with comments.
"""

from __future__ import annotations

from collections.abc import Callable

#: Told of each step as it starts: its key, how many of its items are done, and of how many
#: (both 0 for a step not counted). None tells nothing. Set by the page (`web.view`).
STEP: Callable[[str, int, int], None] | None = None

#: The steps an audit says, in order.
STEPS = ("read", "numbers", "words", "lookup", "report")


def step(key: str, done: int = 0, total: int = 0) -> None:
    """Say that step `key` has started, or with `total`, that `done` of its items are."""
    if STEP is not None:
        STEP(key, done, total)


__all__ = ["STEP", "STEPS", "step"]
