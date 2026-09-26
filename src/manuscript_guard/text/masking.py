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
from functools import lru_cache

from manuscript_guard.text.comments import comment_spans
from manuscript_guard.text.fences import Fence, fenced_spans

NUL = "\x00"

# Where the front matter ends, as pandoc reads it, for the gates and the build alike. The
# opening `---` must not be followed by a blank line: one that is, is a horizontal rule,
# and the prose after it prints. Either delimiter may carry trailing spaces, `...` closes
# the block as well as `---`, and the closing line may be the file's last or the opening's
# next: an empty header closes there, where it ran on to the next rule and took the text
# between with it. A byte-order mark and blank lines before the opening `---` are skipped,
# as pandoc skips them: taken for the start of the body, they left the header in it, its
# title unchecked against paper.yaml. The build had a copy of its own that differed on each
# of these, and where the two disagreed a heading could be read by G2 and stripped by the
# build: `p < 0.001` under it passed as the alpha chosen in advance and printed without it.
_FRONT_MATTER_BLOCK = re.compile(
    r"\A\N{ZERO WIDTH NO-BREAK SPACE}?(?:[ \t]*\r?\n)*---[ \t]*\r?\n(?![ \t]*\r?\n)"
    r"(?P<yaml>.*?)(?<=\n)(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)",
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


@lru_cache(maxsize=1)
def _loader():
    """PyYAML's safe loader, composing anchors as pandoc's YAML library does.

    An anchor carries into the documents after it, exists only once its node is finished,
    and may be defined again, the later definition winning. PyYAML forgets anchors between
    documents, lets a node refer to itself, and refuses a second definition: pandoc builds
    `title: &x T` with `--- *x` under it, refuses `a: &x [*x]`, and reads `a: &x 1` with
    `b: &x 2`.
    """
    import yaml
    from yaml.composer import ComposerError

    class PandocLoader(yaml.SafeLoader):
        def compose_document(self):
            self.get_event()
            node = self.compose_node(None, None)
            self.get_event()
            return node

        def compose_node(self, parent, index):
            if self.check_event(yaml.AliasEvent):
                event = self.get_event()
                if event.anchor not in self.anchors:
                    raise ComposerError(
                        None, None, f"found undefined alias {event.anchor!r}", event.start_mark
                    )
                return self.anchors[event.anchor]
            anchor = self.peek_event().anchor
            self.descend_resolver(parent, index)
            if self.check_event(yaml.ScalarEvent):
                node = self.compose_scalar_node(None)
            elif self.check_event(yaml.SequenceStartEvent):
                node = self.compose_sequence_node(None)
            else:
                node = self.compose_mapping_node(None)
            self.ascend_resolver()
            if anchor is not None:
                self.anchors[anchor] = node
            return node

    return PandocLoader


@lru_cache(maxsize=256)
def _read_yaml(yaml_text: str) -> tuple[bool, str, int]:
    """Whether pandoc keeps this YAML as metadata, and why and where it cannot read it.

    Read as pandoc reads it: between a `---` and a `...` of its own, so a `---` line inside
    starts another document, and every document is read. It is metadata when the first
    document is a mapping, or when there is nothing: no document, or one that is empty, a
    comment or a null. The reason is empty unless the text is not YAML, which pandoc
    refuses to build, and the line is where the reading failed, counted from 0 inside the
    YAML. Composed, not loaded: constructing values raises on YAML pandoc accepts, such as
    `date: 2026-02-30`, and nothing here needs the values. With the pure-Python loader, as
    the C one overflowed its stack on deep nesting. Tabs are expanded first, every four
    columns, as pandoc expands them before it reads the YAML: PyYAML refuses
    `title:<tab>A study`, which pandoc reads.
    """
    import yaml

    if _nesting(yaml_text) > _YAML_DEPTH:
        return False, "", 0
    wrapped = "---\n" + yaml_text.expandtabs(4) + "...\n"
    try:
        documents = list(yaml.compose_all(wrapped, Loader=_loader()))
    except yaml.MarkedYAMLError as exc:
        return (False, *_failed_at(exc, wrapped))
    except yaml.reader.ReaderError as exc:
        where = wrapped.count("\n", 0, exc.position) - 1
        # PyYAML keeps the character as its code point, an int.
        code = exc.character if isinstance(exc.character, int) else ord(exc.character)
        return False, f"unacceptable character #x{code:04x}: {exc.reason}", max(where, 0)
    except RecursionError:
        # Too deep to compose, like the nesting refused above; see Known gaps.
        return False, "", 0
    if not documents:
        return True, "", 0
    first = documents[0]
    if isinstance(first, yaml.MappingNode):
        return True, "", 0
    empty = isinstance(first, yaml.ScalarNode) and first.tag == "tag:yaml.org,2002:null"
    return empty and len(documents) == 1, "", 0


def _failed_at(exc, wrapped: str) -> tuple[str, int]:
    """The reason and the line inside the YAML for a composing error. One found at the end,
    such as a quote never closed, is placed where the construct it was reading opened.

    Lines are counted at `\\n` from the mark's position, as the file's are. PyYAML's own
    line count also breaks at NEL, LS, PS and a lone CR, and put the error past the closer.
    """
    mark = exc.problem_mark or exc.context_mark
    closer = len(wrapped) - len("...\n")
    if exc.context_mark is not None and mark is not None and mark.index >= closer:
        mark = exc.context_mark
    reason = ", ".join(part for part in (exc.context, exc.problem) if part)
    # Line 0 of the wrapped text is the `---` put in front of the YAML.
    line = wrapped.count("\n", 0, mark.index) - 1 if mark else 0
    return reason or type(exc).__name__, max(line, 0)


def front_matter_problem(text: str) -> tuple[str, int] | None:
    """Why pandoc cannot read the YAML block that opens `text`, and the line of the file
    where the reading failed; None when it can, or when nothing there looks like one.

    Such a block is not front matter, and pandoc refuses to build the file. Left in the body
    for pandoc to refuse, it never was: the identifier in front of its first paragraph made
    it prose, the build printed the YAML as text, and the gates read a `# Methods` in it as a
    heading. So the gates and the build report it instead, and stop.
    """
    found = _FRONT_MATTER_BLOCK.match(text)
    if found is None:
        return None
    _metadata, reason, line = _read_yaml(found.group("yaml"))
    if not reason:
        return None
    return reason, text.count("\n", 0, found.start("yaml")) + 1 + line


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


def front_matter_abstract(text: str) -> tuple[int, str] | None:
    """The line of the file where its front matter's abstract is, and the abstract's words;
    None when there is no abstract, or pandoc would print nothing for it.

    The build strips the block and writes a header of its own from paper.yaml, which has no
    abstract, so one written here was checked by G2 and then left out of the document
    without a word. The gates and the build refuse it instead (`front-matter-abstract`).
    Found by reading the block as pandoc does, not by G2's key-line reader, which misses a
    quoted key, a quoted value continued on the next line, a flow mapping and a merge key,
    and cannot tell `null` or a comment from text.
    """
    opening = FRONTMATTER.match(text)
    if opening is None:
        return None
    found = _abstract_in(opening.group("yaml"))
    if found is None:
        return None
    line, words = found
    return text.count("\n", 0, opening.start("yaml")) + 1 + line, words


@lru_cache(maxsize=256)
def _abstract_in(yaml_text: str) -> tuple[int, str] | None:
    """The abstract pandoc would print from this front matter: its line inside the YAML,
    counted from 0, and its words.

    Composed as `_read_yaml` composes it, which has already succeeded when FRONTMATTER
    matched. Never constructed: constructing expands `<<` merge keys, doubling the work with
    each line of a merge bomb, and nothing here needs the values.
    """
    import yaml

    wrapped = "---\n" + yaml_text.expandtabs(4) + "...\n"
    documents = list(yaml.compose_all(wrapped, Loader=_loader()))
    if not documents or not isinstance(documents[0], yaml.MappingNode):
        return None
    found = _abstract_entry(documents[0])
    if found is None or not _prints(found[1]):
        return None
    key, value = found
    # Counted at `\n` from the key's position, as the file's lines are; line 0 of the
    # wrapped text is the `---` put in front of the YAML.
    line = wrapped.count("\n", 0, key.start_mark.index) - 1
    words = " ".join(value.value.split()) if isinstance(value, yaml.ScalarNode) else ""
    return line, words


_NULL = "tag:yaml.org,2002:null"
_NULLS = ("~", "null", "Null", "NULL")


def _abstract_entry(root):
    """The `abstract` key and value of a mapping node, its own or merged in with `<<`.

    Pandoc honours merge keys: `<<: *base` takes the abstract `base` holds. A mapping's own
    key wins over a merged one, and an earlier merged mapping over a later one, searched
    depth first. Each mapping is visited once, however many aliases reach it.

    Keys are known by their text, as pandoc knows them. PyYAML tags only a plain `<<` as a
    merge, so `"<<": *base` was passed over while pandoc merged it and printed the abstract,
    and `!!merge abstract:` was not taken for the abstract pandoc printed.
    """
    import yaml

    seen: set[int] = set()
    pending = [root]
    while pending:
        mapping = pending.pop()
        if not isinstance(mapping, yaml.MappingNode) or id(mapping) in seen:
            continue
        seen.add(id(mapping))
        scalar_keys = [(k, v) for k, v in mapping.value if isinstance(k, yaml.ScalarNode)]
        own = [(k, v) for k, v in scalar_keys if k.value == "abstract"]
        if own:
            return own[-1]  # pandoc, like PyYAML, keeps the last of a duplicated key
        merged = []
        for key, value in scalar_keys:
            if key.value == "<<":
                merged += value.value if isinstance(value, yaml.SequenceNode) else [value]
        pending += reversed(merged)
    return None


def _prints(node) -> bool:
    """Whether pandoc prints anything for an abstract composed as `node`."""
    import yaml

    if isinstance(node, yaml.ScalarNode):
        # The tag and the spelling both: pandoc prints `!!null Some text` as the text, and a
        # quoted "null" is the word.
        if node.tag == _NULL and node.value in _NULLS:
            return False
        return bool(node.value.strip())
    # A list or a mapping: empty prints nothing, and anything in it is refused, not guessed at.
    return bool(node.value)


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


def without_front_matter(text: str) -> str:
    """`text` after its front matter: the part of a source file the build prints."""
    return text[front_matter_end(text) :]


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
    runs = list(_BACKSLASHES.finditer(text))
    if not runs:
        # `_CODE_SPAN` backtracks on backtick runs that never close: 4 s for 80 KB of them,
        # paid by `mask` and the classifier alike, in every paper, for escapes it held none of.
        return []
    code = [m.span() for m in _CODE_SPAN.finditer(text)]
    starts = [start for start, _end in code]
    found = []
    for run in runs:
        inside = bisect_right(starts, run.start()) - 1
        if len(run.group()) % 2 and not (inside >= 0 and run.start() < code[inside][1]):
            found.append(run.end() - 1)
    return found


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
    for index in comparison_escapes(text):
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
