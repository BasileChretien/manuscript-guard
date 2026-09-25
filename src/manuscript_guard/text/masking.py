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
from functools import lru_cache

from manuscript_guard.text.fences import Fence, fenced_spans

NUL = "\x00"

# Where the front matter ends, as pandoc reads it, for the gates and the build alike. The
# opening `---` must not be followed by a blank line: one that is, is a horizontal rule,
# and the prose after it prints. Either delimiter may carry trailing spaces, `...` closes
# the block as well as `---`, and the closing line may be the file's last. A byte-order
# mark and blank lines before the opening `---` are skipped, as pandoc skips them: taken
# for the start of the body, they left the header in it, its title unchecked against
# paper.yaml. The build had a copy of its own that differed on each of these, and where the
# two disagreed a heading could be read by G2 and stripped by the build: `p < 0.001` under
# it passed as the alpha chosen in advance and printed without it.
_FRONT_MATTER_BLOCK = re.compile(
    r"\A\N{ZERO WIDTH NO-BREAK SPACE}?(?:[ \t]*\r?\n)*---[ \t]*\r?\n(?![ \t]*\r?\n)"
    r"(?P<yaml>.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
# Nesting deeper than this is nobody's metadata. Composing thousands of levels of brackets
# took seconds before the pure-Python loader hit the recursion limit. The count is rough: it
# does not know quotes or block scalars, and does not see nesting made by indentation.
_YAML_DEPTH = 100
_SEQUENCE_ITEMS = re.compile(r"(?:[ \t]*-(?:[ \t]+|$))+")


def _nesting(yaml_text: str) -> int:
    """How deep YAML's flow brackets or block sequences nest, read without parsing."""
    depth = deepest = 0
    for char in yaml_text:
        if char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth = max(depth - 1, 0)
    for line in yaml_text.split("\n"):
        items = _SEQUENCE_ITEMS.match(line)
        if items:
            deepest = max(deepest, items.group(0).count("-"))
    return deepest


@lru_cache(maxsize=256)
def _read_yaml(yaml_text: str) -> tuple[bool, str]:
    """Whether pandoc keeps this YAML as metadata, and why it cannot read it at all.

    Metadata is a mapping, or nothing: a comment alone, or a null. The second item is empty
    unless the text is not YAML, which pandoc refuses to build. Composed, not loaded:
    constructing values raises on YAML pandoc accepts, such as `date: 2026-02-30`, and
    nothing here needs the values. With the pure-Python loader, as the C one overflowed its
    stack on deep nesting. Tabs are expanded first, every four columns, as pandoc expands
    them before it reads the YAML: PyYAML refuses `title:<tab>A study`, which pandoc reads.
    """
    import yaml

    if _nesting(yaml_text) > _YAML_DEPTH:
        return False, ""
    try:
        node = yaml.compose(yaml_text.expandtabs(4), Loader=yaml.SafeLoader)
    except Exception as exc:  # noqa: BLE001 - any failure to parse is "not metadata"
        return False, " ".join(str(exc).split())[:200] or type(exc).__name__
    empty = node is None or (
        isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:null"
    )
    return empty or isinstance(node, yaml.MappingNode), ""


def front_matter_problem(text: str) -> str:
    """Why pandoc cannot read the YAML block that opens `text`; empty when it can, or when
    nothing there looks like one.

    Such a block is not front matter, and pandoc refuses to build the file. Left in the body
    for pandoc to refuse, it never was: the identifier in front of its first paragraph made
    it prose, the build printed the YAML as text, and the gates read a `# Methods` in it as a
    heading. So the gates and the build report it instead, and stop.
    """
    found = _FRONT_MATTER_BLOCK.match(text)
    return _read_yaml(found.group("yaml"))[1] if found else ""


class _FrontMatter:
    """`FRONTMATTER.match(text)`: the YAML block that opens `text`, or None.

    Pandoc reads from the opening `---` to the first `---` or `...` line and keeps what is
    between as metadata only when it is a mapping, or nothing. Anything else it prints: a
    list becomes a table, a sentence a paragraph. And a header that is never closed is read
    to the next rule, where the text between is not YAML, and pandoc refuses the file. The
    pattern alone took all of these for front matter, and the build stripped them: with a
    rule further down, an Introduction under an unclosed header vanished from the document
    with no warning. What pandoc prints is left in the body; what it refuses is reported by
    `front_matter_problem`.
    """

    def match(self, text: str) -> re.Match[str] | None:
        found = _FRONT_MATTER_BLOCK.match(text)
        if found is None or not _read_yaml(found.group("yaml"))[0]:
            return None
        return found


FRONTMATTER = _FrontMatter()


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
