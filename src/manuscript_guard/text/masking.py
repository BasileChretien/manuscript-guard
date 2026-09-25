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

from manuscript_guard.text.comments import comment_spans
from manuscript_guard.text.fences import Fence, fenced_spans

NUL = "\x00"

# Where the front matter ends, as pandoc reads it, for the gates and the build alike. The
# opening `---` must not be followed by a blank line: one that is, is a horizontal rule,
# and the prose after it prints. Either delimiter may carry trailing spaces, and `...`
# closes the block as well as `---`. The build had a copy of its own that differed on each
# of these, and where the two disagreed a heading could be read by G2 and stripped by the
# build: `p < 0.001` under it passed as the alpha chosen in advance and printed without it.
FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(?![ \t]*\r?\n)(?P<yaml>.*?)\r?\n(?:---|\.\.\.)[ \t]*\r?\n", re.DOTALL
)


def front_matter_end(text: str) -> int:
    """Where the body begins: just past the front matter, or 0 when there is none.

    Nothing opened on one side of it closes on the other. Pandoc reads the YAML apart from
    the body, and each value apart from the rest, so a `<!--` in a title or a fence opener in
    an abstract ends with its value. Read as one text, a title's comment ran on to the next
    `-->` in the body, and everything between was hidden from G2 and the audit while pandoc
    printed it.
    """
    opening = FRONTMATTER.match(text)
    return opening.end() if opening else 0


def fenced_blocks(text: str) -> list[Fence]:
    """The fenced blocks of the front matter and of the body, none opening in one and
    closing in the other. A code block in an abstract is still code: looked for in the body
    alone, its `<!--` opened a comment that hid the abstract's prose."""
    head = front_matter_end(text)
    return [*fenced_spans(text[:head]), *fenced_spans(text, head)]

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
# that is partly machinery and partly prose. HTML comments are handled separately too, and
# before any of these, by `text/comments.py`: whether `<!--` opens one depends on whether a
# code span opened first, which no pattern here can see.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A fenced block is masked *here* and read by a different reader. Inline code is not
    # masked at all.
    #
    # Both render, so neither may go unchecked: `3.84` in backticks prints as 3.84. But they
    # are not the same kind of text. Inline code is a word in a sentence, and the prose rules
    # are the right ones for it. A fenced block is a *listing*, and judging its contents as
    # prose produced eleven failures on one honest Methods section — `1.96`, `sqrt(1/a`,
    # `set.seed(20240115`, a package version — which is the pressure that drives an author to
    # `conventions:`, the one mechanism that makes G2 vacuous. So G2 masks fenced blocks and
    # `check_numbers` runs the *code* checker over them instead, the same one G3 uses on
    # figure scripts: a number inside a string literal in the listing is still a claim, a
    # loop bound is not.
    ("placeholder", re.compile(r"\{\{[^}\n]*\}\}")),
    ("autolink", re.compile(r"<(?:https?|doi|mailto):[^>\s]+>")),
    ("url", re.compile(r"(?:https?://|www\.|doi:\s*|10\.\d{4,9}/)\S+", re.IGNORECASE)),
    ("link-target", re.compile(r"\]\([^)\n]*\)")),
    ("footnote", re.compile(r"\[\^[^\]\n]+\]")),
    # Citation KEYS, not whole citation brackets. Better BibTeX keys routinely end in a year,
    # so the key itself must go; everything else in the bracket must stay.
    #
    # This used to mask `\[-?@[^\]\n]+\]` — the entire bracket — and pandoc renders a
    # citation's prefix and suffix. So
    #
    #     [@smith2019, which reported an ROR of 9.99 (95% CI 7.10 to 14.02)]
    #
    # printed all four numbers in the .docx and no gate read any of them: a fabricated value
    # carrying a citation, which DESIGN calls worse than an unsourced one because it looks
    # checked. Ordinary pandoc usage, too — `[@key, p. 33]` is how anyone writes a locator —
    # so an honest author got no warning either way. The prefix form `[see 42; @key]` was
    # already read, because the old pattern was anchored at `[@`; the asymmetry was accidental.
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


def _filled(text: str, spans: list[tuple[int, int]], fill: str) -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if fill == NUL or chars[index] != "\n":
                chars[index] = fill
    return "".join(chars)


def html_comments(text: str, fences: list[Fence] | None = None) -> list[tuple[int, int]]:
    """The HTML comments pandoc drops from a manuscript source. See text/comments.py.

    Read with the front matter's machinery blanked to NUL, which neither a comment nor a
    code span crosses, because pandoc reads each rendered value on its own. Read whole, a
    `<!--` in a title ran on to the first `-->` in the body and hid everything between.
    """
    if "<!--" not in text:
        return []
    view = _filled(text, _frontmatter_spans(text), NUL)
    if fences is None:
        fences = fenced_blocks(text)
    bound = _fence_first_comments(view, fences, front_matter_end(text))
    return _within(comment_spans(view, fences), bound)


def _fence_first_comments(view: str, fences: list[Fence], head: int) -> list[tuple[int, int]]:
    """The comments the old rule found: from `<!--` to the first `-->`, with the fences and
    the front matter's machinery blanked, as `mask` blanked them before looking.

    The scanner knows code spans and where pandoc ends a comment, but not every place pandoc
    ends a code span or starts a block: an indented code block, a list item, maths. Where it
    guessed one pandoc does not make, a `<!--` it should have ignored closed on a `-->`
    inside a listing, or one it should have found in a listing opened a comment, and prose
    pandoc prints was hidden that the old rule had read. So a comment is hidden only where
    this rule hides it too: the scanner can hide less than the regexes it replaced, never
    more. Found with `find`, on each side of the front matter, and linear: once a `<!--`
    has no `-->` after it, none later can.

    `view` has the machinery blanked already. Built from the raw text, the bound let a `-->`
    in `author:`, which the old rule never read, close a comment the scanner had guessed in
    the abstract.
    """
    flat = list(view)
    for fence in fences:
        flat[fence.start : fence.end] = " " * (fence.end - fence.start)
    blanked = "".join(flat)
    found: list[tuple[int, int]] = []
    for low, high in ((0, head), (head, len(blanked))):
        position = low
        while (opening := blanked.find("<!--", position, high)) != -1:
            closing = blanked.find("-->", opening + 4, high)
            if closing == -1:
                break
            found.append((opening, closing + 3))
            position = closing + 3
    return found


def _within(spans: list[tuple[int, int]], allowed: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The parts of `spans` that lie inside `allowed`. Both sorted, neither overlapping."""
    kept: list[tuple[int, int]] = []
    first = 0
    for start, end in spans:
        while first < len(allowed) and allowed[first][1] <= start:
            first += 1
        index = first
        while index < len(allowed) and allowed[index][0] < end:
            low, high = max(start, allowed[index][0]), min(end, allowed[index][1])
            if low < high:
                kept.append((low, high))
            index += 1
    return kept


def blank(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` with `spans` replaced by spaces, offsets and newlines kept."""
    return _filled(text, spans, " ")


def blank_comments(text: str) -> str:
    """`text` with the comments `mask` drops replaced by spaces, offsets and newlines kept."""
    return blank(text, html_comments(text))


def _either_side(pattern: re.Pattern[str], text: str, head: int) -> list[re.Match[str]]:
    """Matches in the front matter and in the body, none running from one into the other."""
    return [*pattern.finditer(text, 0, head), *pattern.finditer(text, head)]


def mask(text: str) -> str:
    """Return `text` with non-claim regions replaced by NUL, preserving length."""
    chars = list(text)
    head = front_matter_end(text)
    # Fenced blocks go first, and through the shared scanner rather than a regex of their
    # own: three copies of that regex all required the closing fence to be *exactly* the
    # opening run, so a longer closer swallowed the prose after it. See text/fences.py.
    fences = fenced_blocks(text)
    for fence in fences:
        for index in range(fence.start, fence.end):
            chars[index] = NUL
    for start, end in _frontmatter_spans(text):
        for index in range(start, end):
            chars[index] = NUL
    # Found in the source, not in what is left once fences are gone: a comment opened
    # before a listing ends at a `-->` inside it, and the prose after it is printed.
    for start, end in html_comments(text, fences):
        for index in range(start, end):
            chars[index] = NUL
    for _name, pattern in _PATTERNS:
        for match in _either_side(pattern, "".join(chars), head):
            for index in range(match.start(), match.end()):
                chars[index] = NUL
    return "".join(chars)


def masked_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    """What each pattern matched. Used by the test suite and by `explain` output."""
    found: dict[str, list[tuple[int, int]]] = {}
    working = text
    head = front_matter_end(text)
    blocks = fenced_blocks(text)
    comments = html_comments(text, blocks)
    fences = [(f.start, f.end) for f in blocks]
    if fences:
        found["fenced-code"] = fences
        chars = list(working)
        for start, end in fences:
            for index in range(start, end):
                chars[index] = NUL
        working = "".join(chars)
    frontmatter = _frontmatter_spans(text)
    if frontmatter:
        found["frontmatter"] = frontmatter
        chars = list(working)
        for start, end in frontmatter:
            for index in range(start, end):
                chars[index] = NUL
        working = "".join(chars)
    if comments:
        found["html-comment"] = comments
        chars = list(working)
        for start, end in comments:
            for index in range(start, end):
                chars[index] = NUL
        working = "".join(chars)
    for name, pattern in _PATTERNS:
        spans = [(m.start(), m.end()) for m in _either_side(pattern, working, head)]
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
