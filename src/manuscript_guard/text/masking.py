"""Blanking the regions of a Markdown source where a digit is not a claim.

Masking replaces characters with NUL rather than deleting them, so every offset in the
masked string still points at the same place in the original. That is what lets a finding
report a real line and column.

Getting this list wrong is the main way a checker like this goes quietly wrong. Too little
masking and the author drowns in findings about DOIs and citation keys, then stops reading
them. Too much and a genuine claim hides inside a masked region — which is the more
dangerous direction, so anything questionable is left unmasked and allowed to fail loudly.
"""

from __future__ import annotations

import re

NUL = "\x00"

FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n(?:---|\.\.\.)\r?\n", re.DOTALL)

# Front-matter keys whose value pandoc renders into the document. Masking the whole block
# put the abstract — the most-read part of a paper — entirely outside the gate: a title of
# "A 3.84-fold excess" and an abstract quoting an ROR and a cohort size were checked by
# nothing at all and printed normally. The rest of the block really is machinery (`lang`,
# `zotero`, `bibliography`, ids, dates) and stays masked.
RENDERED_KEYS = (
    "title",
    "subtitle",
    "short_title",
    "running_title",
    "abstract",
    "summary",
    "keywords",
)
_KEY_LINE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>" + "|".join(RENDERED_KEYS) + r")[ \t]*:[ \t]*(?P<value>.*)$"
)

# Ordered: earlier patterns win, because a URL inside a code fence is already gone.
# Front matter is handled separately, by `_mask_frontmatter`, because it is the one region
# that is partly machinery and partly prose.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Inline code and fenced blocks are NOT masked, though they once were. Both render:
    # `3.84` in backticks appears in the .docx as 3.84, and a fenced block is a visible
    # display element. Masking them meant a number could be published by wrapping it in
    # punctuation. The usual argument for masking code — that a Methods section describing
    # `p.adjust()` should not be nagged about `n = 42` — turns out to be an argument about
    # READMEs rather than manuscripts: G2 reads `manuscript/` only, and a paper that
    # genuinely lists code can declare it in `conventions:` with a reason, which is the
    # visible, per-project escape this toolkit prefers to a silent global one.
    ("html-comment", re.compile(r"<!--.*?-->", re.DOTALL)),
    ("placeholder", re.compile(r"\{\{[^}\n]*\}\}")),
    ("autolink", re.compile(r"<(?:https?|doi|mailto):[^>\s]+>")),
    ("url", re.compile(r"(?:https?://|www\.|doi:\s*|10\.\d{4,9}/)\S+", re.IGNORECASE)),
    ("link-target", re.compile(r"\]\([^)\n]*\)")),
    ("footnote", re.compile(r"\[\^[^\]\n]+\]")),
    # Citation keys, bracketed and narrative. Better BibTeX keys routinely end in a year.
    ("citation", re.compile(r"\[-?@[^\]\n]+\]")),
    ("citation-bare", re.compile(r"(?<![\w`])-?@[A-Za-z][\w:.#$%&+?<>~/-]*")),
    ("pandoc-attr", re.compile(r"\{[.#][^}\n]*\}")),
)


def _frontmatter_spans(text: str) -> list[tuple[int, int]]:
    """The parts of the opening YAML block to mask: everything but the rendered values.

    Returned as spans rather than applied here, so `masked_spans` can report them under one
    name and `mask` can apply them with everything else.
    """
    opening = FRONTMATTER.match(text)
    if opening is None:
        return []

    spans: list[tuple[int, int]] = []
    offset = opening.start()
    block = text[opening.start() : opening.end()]
    keeping_from: int | None = None  # indent of an open block scalar, e.g. `abstract: |`

    for line in block.splitlines(keepends=True):
        start, offset = offset, offset + len(line)
        bare = line.rstrip("\r\n")
        stripped = bare.strip()

        if keeping_from is not None:
            indent = len(bare) - len(bare.lstrip())
            if stripped and indent <= keeping_from:
                keeping_from = None  # dedented: the block scalar ended
            else:
                continue  # a continuation line of a rendered value; leave it readable

        match = _KEY_LINE.match(bare)
        if match is None:
            spans.append((start, offset))
            continue

        value = match.group("value").strip()
        # Mask the key and colon; keep whatever follows on the line.
        spans.append((start, start + match.start("value")))
        if value in ("|", ">", "|-", ">-", "|+", ">+", ""):
            keeping_from = len(match.group("indent"))
        if not bare.endswith(match.group("value")):  # trailing newline characters
            spans.append((start + len(bare), offset))
        else:
            spans.append((start + len(bare), offset))

    return [(a, b) for a, b in spans if b > a]


def mask(text: str) -> str:
    """Return `text` with non-claim regions replaced by NUL, preserving length."""
    chars = list(text)
    for start, end in _frontmatter_spans(text):
        for index in range(start, end):
            chars[index] = NUL
    for _name, pattern in _PATTERNS:
        for match in pattern.finditer("".join(chars)):
            for index in range(match.start(), match.end()):
                chars[index] = NUL
    return "".join(chars)


def masked_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    """What each pattern matched. Used by the test suite and by `explain` output."""
    found: dict[str, list[tuple[int, int]]] = {}
    working = text
    frontmatter = _frontmatter_spans(text)
    if frontmatter:
        found["frontmatter"] = frontmatter
        chars = list(working)
        for start, end in frontmatter:
            for index in range(start, end):
                chars[index] = NUL
        working = "".join(chars)
    for name, pattern in _PATTERNS:
        spans = [(m.start(), m.end()) for m in pattern.finditer(working)]
        if spans:
            found[name] = spans
            chars = list(working)
            for start, end in spans:
                for index in range(start, end):
                    chars[index] = NUL
            working = "".join(chars)
    return found


def line_col(text: str, offset: int) -> tuple[int, int]:
    """1-indexed line and column of a character offset."""
    line = text.count("\n", 0, offset) + 1
    start = text.rfind("\n", 0, offset) + 1
    return line, offset - start + 1


def line_at(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start : len(text) if end == -1 else end]
