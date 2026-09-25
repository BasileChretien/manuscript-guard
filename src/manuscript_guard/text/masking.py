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
from bisect import bisect_right

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

_BACKSLASHES = re.compile(r"\\+(?=[<>])")
# A run of backticks, closed by the next run exactly as long, within a paragraph: pandoc's
# rule, less its fallbacks. It is not pandoc's reader: a `~~~` block, or a ```` ``` ```` one
# with a blank line inside, is not seen as code here, nor is code handed over without its
# fence, a listing's string or a figure script's. And the runs are paired in the text as it
# stands, so a backtick inside a `~~~` block pairs with one in the prose after it, and a
# code span there goes unseen. DESIGN.md's Known gaps has the rest.
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(?:[^\n]|\n(?![ \t]*\n))+?(?<!`)\1(?!`)")


def comparison_escapes(text: str) -> list[int]:
    """Where a backslash escapes a `<` or `>`, so that it prints the bare character.

    Pandoc's Markdown writer puts one before every comparison, so a paper converted from
    Word reads `p \\< 0.05` and `ROR \\> 2`; `import` puts one before a `>` that a `<` earlier
    in the paragraph could close as a tag. G2 read neither: the threshold rules never
    matched, and `\\>3` was an atom no rule began at. `mask` blanks these, so `\\>3` is read
    from its `3`, and the classifier matches its rules without them. Blanked, one also ends
    the atom before it, where the printed `>` does not: `n\\>3` is read as `n` and `>3`.

    Only a backslash that prints nothing counts: the last of an odd run, since `\\\\>` is a
    backslash printed before a `>`, and none inside inline code, which prints it as typed.
    Reading either as an escape let `` `ROR \\> 2` `` pass as the threshold it does not print.
    """
    code = [m.span() for m in _CODE_SPAN.finditer(text)]
    starts = [start for start, _end in code]
    found = []
    for run in _BACKSLASHES.finditer(text):
        inside = bisect_right(starts, run.start()) - 1
        if len(run.group()) % 2 and not (inside >= 0 and run.start() < code[inside][1]):
            found.append(run.end() - 1)
    return found


# Ordered: earlier patterns win, because a URL inside a code fence is already gone.
# Front matter is handled separately, by `_mask_frontmatter`, because it is the one region
# that is partly machinery and partly prose.
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
    ("html-comment", re.compile(r"<!--.*?-->", re.DOTALL)),
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
    for fence in fenced_blocks(text):
        for index in range(fence.start, fence.end):
            chars[index] = NUL
    for start, end in _frontmatter_spans(text):
        for index in range(start, end):
            chars[index] = NUL
    for _name, pattern in _PATTERNS:
        for match in _either_side(pattern, "".join(chars), head):
            for index in range(match.start(), match.end()):
                chars[index] = NUL
    for index in comparison_escapes(text):
        chars[index] = NUL
    return "".join(chars)


def masked_spans(text: str) -> dict[str, list[tuple[int, int]]]:
    """What each pattern matched. Used by the test suite and by `explain` output."""
    found: dict[str, list[tuple[int, int]]] = {}
    working = text
    head = front_matter_end(text)
    fences = [(f.start, f.end) for f in fenced_blocks(text)]
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
    for name, pattern in _PATTERNS:
        spans = [(m.start(), m.end()) for m in _either_side(pattern, working, head)]
        if spans:
            found[name] = spans
            chars = list(working)
            for start, end in spans:
                for index in range(start, end):
                    chars[index] = NUL
            working = "".join(chars)
    escapes = [(index, index + 1) for index in comparison_escapes(text)]
    if escapes:
        found["escaped-comparison"] = escapes
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
