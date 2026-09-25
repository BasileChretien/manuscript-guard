"""What the toolkit thinks the document is, against what pandoc actually makes of it.

Two of the worst holes so far were disagreements with the renderer, not bugs in isolation:

* a `# Methods` comment inside a fenced listing became a heading, popped the real one, and
  let a fabricated `p < 0.001` in the Results pass as the pre-specified alpha;
* a setext heading underlined with two dashes was invisible, because the toolkit demanded
  three and pandoc accepts one — so Results content inherited the enclosing Methods chain.

Both were found by a person comparing the code against the CommonMark spec. Neither could
have been caught by a unit test of the regex, because the regex was self-consistent; what it
disagreed with was pandoc. So this asks pandoc directly, for every structural construct
worth arguing about, and fails when the two views differ.

The point is not that pandoc is a specification. It is that pandoc is *the thing that builds
the document the reader receives*, so where the toolkit and pandoc disagree about what is a
heading or what is code, the toolkit is wrong by definition.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from manuscript_guard.text.fences import fenced_spans
from manuscript_guard.text.masking import FRONTMATTER
from manuscript_guard.text.sections import headings

PANDOC = shutil.which("pandoc")
pytestmark = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")

FENCE = "`" * 3


def _inline_text(nodes) -> str:
    out = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("t") == "Str":
            out.append(node["c"])
        elif node.get("t") == "Space":
            out.append(" ")
        elif isinstance(node.get("c"), list):
            out.append(_inline_text(node["c"]))
    return "".join(out)


# Containers whose contents are quoted or set apart rather than being this document's own
# structure. See `test_a_quoted_heading_is_deliberately_not_a_section`.
NESTED = {"BlockQuote", "Note", "Figure"}


def _collect(node, out: list) -> None:
    if isinstance(node, dict):
        if node.get("t") in NESTED:
            return
        if node.get("t") == "Header":
            out.append(_inline_text(node["c"][2]).strip())
        for value in node.values():
            _collect(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect(value, out)


def pandoc_headings(markdown: str) -> list[str]:
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    found: list[str] = []
    _collect(json.loads(finished.stdout)["blocks"], found)
    return found


# ---------------------------------------------------------------- headings

CONSTRUCTS = {
    "atx level 1": "# Methods\n\nProse.\n",
    "atx level 3": "### Statistical analysis\n\nProse.\n",
    "atx indented one space": " # Methods\n\nProse.\n",
    "atx indented three spaces": "   # Methods\n\nProse.\n",
    "setext with equals": "Methods\n=======\n\nProse.\n",
    "setext one dash": "Methods\n-\n\nProse.\n",
    "setext two dashes": "Methods\n--\n\nProse.\n",
    "setext many dashes": "Methods\n----------\n\nProse.\n",
    "hash inside a fenced listing": f"## Real\n\n{FENCE}python\n# Fake\n{FENCE}\n\nProse.\n",
    "hash inside an html comment": "## Real\n\n<!--\n## Fake\n-->\n\nProse.\n",
    "setext inside a blockquote": "## Real\n\n> Fake\n> ----\n\nProse.\n",
    "front matter closing delimiter": "---\ntitle: T\nlang: en-GB\n---\n\n# Real\n\nProse.\n",
    "thematic break after a paragraph": "# Real\n\nSome prose.\n\n***\n\nMore prose.\n",
    "no headings at all": "Just a paragraph with 42 in it.\n",
}


@pytest.mark.parametrize("name", sorted(CONSTRUCTS))
def test_the_toolkit_sees_the_headings_pandoc_renders(name: str) -> None:
    """Where these disagree, the toolkit is wrong: pandoc builds what the reader receives."""
    markdown = CONSTRUCTS[name]
    assert headings(markdown) == pandoc_headings(markdown), (
        f"{name}: toolkit saw {headings(markdown)}, pandoc renders "
        f"{pandoc_headings(markdown)}"
    )


def test_a_quoted_heading_is_deliberately_not_a_section() -> None:
    """One divergence from pandoc, chosen rather than overlooked.

    Pandoc emits a `Header` for `> ## Methods` — it is nested inside a `BlockQuote`, but it
    is a header. The toolkit does not treat it as one, and should not: a heading inside a
    quotation is part of the thing being quoted, not a section of this paper. Recognising it
    would let `> ## Methods` above a Results paragraph re-admit every `methods_only` rule,
    which is a spoof; ignoring it leaves those numbers unclassified, which is strict.

    Every other divergence found so far ran the other way — the toolkit failing to see
    something pandoc renders — and each was a hole. This one is the exception, so it is
    written down as a test rather than left as a silent difference.
    """
    markdown = "## Real\n\n> Fake\n> ----\n\nThe excess was significant (p < 0.001).\n"
    assert "Fake" not in headings(markdown)

    from manuscript_guard.classify import UNCLASSIFIED, Classifier
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.sections import section_chain
    from manuscript_guard.text.tokens import find_atoms

    atom = next(a for a in find_atoms(markdown, mask(markdown)) if a.text == "0.001")
    chain = section_chain(markdown, atom.start)
    assert Classifier.load().classify(atom, chain).kind == UNCLASSIFIED


# ---------------------------------------------------------------- fences

FENCE_CASES = {
    "equal closer": f"{FENCE}python\nx = 1\n{FENCE}\n\nProse 9.99.\n",
    "longer closer": f"{FENCE}python\nx = 1\n{'`' * 4}\n\nProse 9.99.\n",
    "tilde fence": "~~~r\nx <- 1\n~~~\n\nProse 9.99.\n",
    "tilde closed by more tildes": "~~~r\nx <- 1\n~~~~~\n\nProse 9.99.\n",
    "backticks cannot close tildes": "~~~r\nx <- 1\n```\ny <- 2\n~~~\n\nProse 9.99.\n",
    "indented three spaces is still a fence": (
        f"   {FENCE}python\nx = 1\n   {FENCE}\n\nProse 9.99.\n"
    ),
    "unterminated fence": f"{FENCE}python\nx = 1\n\nProse 9.99.\n",
}


def pandoc_code_text(markdown: str) -> str:
    """Everything pandoc puts inside a CodeBlock, concatenated."""
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    blocks: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("t") == "CodeBlock":
                blocks.append(node["c"][1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(finished.stdout)["blocks"])
    return "\n".join(blocks)


# ---------------------------------------------------------------- front matter

FRONT_MATTER_CASES = {
    "closed by dashes": "---\ntitle: T\n---\n\nProse 9.99.\n",
    "closed by dots": "---\ntitle: T\n...\n\nProse 9.99.\n",
    "trailing spaces on both delimiters": "--- \ntitle: T\n---  \n\nProse 9.99.\n",
    "a blank line after the opening": "---\n\ntitle: T\n---\n\nProse 9.99.\n",
    "a line of spaces after the opening": "---\n  \ntitle: T\n---\n\nProse 9.99.\n",
    "a rule, prose, and a rule": "---\n\nProse 9.99.\n\n---\n\nMore prose.\n",
    "closed by dots, then a rule": "---\ntitle: T\n...\n\nProse 9.99.\n\n---\n\nMore prose.\n",
    "closed by dots on the last line": "---\ntitle: T\n...",
    "closed by dashes on the last line": "---\ntitle: T\n---",
    "a list between the delimiters": "---\n- a\n- b\n---\n\nProse 9.99.\n",
    "a sentence closed by dots": "---\nJust a sentence.\n...\n\nProse 9.99.\n",
    "never closed": "---\ntitle: T\n\nProse 9.99.\n",
    "behind a byte-order mark": "\N{ZERO WIDTH NO-BREAK SPACE}---\ntitle: T\n---\n\nProse 9.99.\n",
    "after a blank first line": "\n---\ntitle: T\n---\n\nProse 9.99.\n",
    "after a line of spaces": "   \n---\ntitle: T\n---\n\nProse 9.99.\n",
    "a blank first line, then a rule": "\n---\n\nProse 9.99.\n\n---\n\nMore prose.\n",
    "a tab after a key": "---\ntitle:\tT\n---\n\nProse 9.99.\n",
    "a tab indenting a value": "---\nabstract: |\n\tA tabbed line.\n---\n\nProse 9.99.\n",
    # PyYAML refuses both; pandoc lets an anchor be defined again, and reads the first of
    # two documents.
    "an anchor defined twice": "---\na: &x 1\nb: &x 2\n---\n\nProse 9.99.\n",
    "a second document": "---\ntitle: T\n--- # a note\n---\n\nProse 9.99.\n",
    # Pandoc reads every document, and an anchor in one can be used in the next.
    "an alias to an anchor in an earlier document": "---\ntitle: &x T\n--- *x\n---\n\nProse.\n",
}
# Pandoc keeps a header holding only a comment, or nothing, as empty metadata: nothing in
# `meta`, and nothing printed either.
STRIPPED_CASES = {
    **FRONT_MATTER_CASES,
    "only a comment": "---\n# a note\n---\n\nProse 9.99.\n",
    # A line that reads as YAML between the empty header and the rule: run on to the rule,
    # the header took it as metadata.
    "empty, closed by dashes, then a rule": (
        "---\n---\n\nNote: 9.99 in the pilot.\n\n---\n\nMore prose.\n"
    ),
    "empty, closed by dots, then a rule": (
        "---\n...\n\nNote: 9.99 in the pilot.\n\n---\n\nMore prose.\n"
    ),
    # Metadata only when the first document is a mapping, or there is nothing at all.
    "a comment document, then a mapping": "---\n--- # a note\n--- {a: 1}\n---\n\nProse.\n",
    "two documents of comments": "---\n# a note\n--- # another\n---\n\nProse.\n",
}
# Headers pandoc refuses to build, and the toolkit must report; and some it reads, which
# the toolkit must not.
REFUSED_OR_NOT = {
    **STRIPPED_CASES,
    "a comment on its first line": "---\n<!-- a note -->\ntitle: T\n---\n\nProse.\n",
    "an unquoted colon in a value": "---\ntitle: A study: of things\n---\n\nProse.\n",
    "never closed before a rule": "---\ntitle: T\n\n# Methods\n\nProse.\n\n---\n\nMore.\n",
    "prose between two rules": "---\nNote: this draft: not final\n---\n\nProse.\n",
    # An anchor exists only once its node is finished.
    "an alias inside its own anchor": "---\na: &x [*x]\n---\n\nProse.\n",
    "an alias to the whole document": "---\n&t\na: 1\nb: *t\n---\n\nProse.\n",
}


def pandoc_meta(markdown: str) -> dict:
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout)["meta"]


@pytest.mark.parametrize("name", sorted(FRONT_MATTER_CASES))
def test_the_toolkit_finds_the_front_matter_pandoc_reads(name: str) -> None:
    """The gates mask the front matter and the build strips it, both where `FRONTMATTER`
    says it ends. Taking too much hides prose that prints from every gate; the build having
    a pattern of its own let G2 read a heading the document never printed."""
    markdown = FRONT_MATTER_CASES[name]
    toolkit = FRONTMATTER.match(markdown) is not None
    assert toolkit == bool(pandoc_meta(markdown)), (
        f"{name}: pandoc {'reads' if not toolkit else 'does not read'} front matter here; "
        f"the toolkit thinks the opposite"
    )


def pandoc_blocks(markdown: str) -> list:
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout)["blocks"]


@pytest.mark.parametrize("name", sorted(STRIPPED_CASES))
def test_the_build_strips_only_what_pandoc_does_not_print(name: str) -> None:
    """The build takes each file's front matter off before pandoc sees it, so what it takes
    must be exactly what pandoc would not have printed. A list or a sentence between two
    delimiters is not metadata to pandoc, which prints it; stripped, it vanished."""
    from manuscript_guard.build.assemble import strip_front_matter

    markdown = STRIPPED_CASES[name]
    body, _title = strip_front_matter(markdown)
    assert pandoc_blocks(body) == pandoc_blocks(markdown), f"{name}: stripped {markdown!r}"


@pytest.mark.parametrize("name", sorted(REFUSED_OR_NOT))
def test_a_header_is_reported_exactly_when_pandoc_refuses_it(name: str) -> None:
    """G2 and the build stop on a header pandoc cannot read. Stopping on one it reads blocks
    a build for nothing, and PyYAML refuses some pandoc takes: an anchor defined twice, or a
    second document after the first."""
    from manuscript_guard.text.masking import front_matter_problem

    markdown = REFUSED_OR_NOT[name]
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    refused = finished.returncode != 0
    assert (front_matter_problem(markdown) is not None) == refused, (
        f"{name}: pandoc {'refuses' if refused else 'reads'} it; the toolkit thinks otherwise"
    )


def test_front_matter_pandoc_refuses_is_left_for_pandoc_to_refuse() -> None:
    """A header that is never closed, with a rule further down, is YAML to pandoc up to the
    rule; with prose in it, it is not valid YAML, and pandoc refuses the file. Stripped to
    the rule, the file built, without the Introduction between."""
    from manuscript_guard.build.assemble import strip_front_matter

    markdown = "---\ntitle: T\n\n# Introduction\n\nProse 9.99.\n\n---\n\nMore prose.\n"
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode != 0, "pandoc read this front matter; the test assumes not"
    assert strip_front_matter(markdown) == (markdown, "")


@pytest.mark.parametrize("name", sorted(FENCE_CASES))
def test_prose_outside_a_fence_is_prose_to_both(name: str) -> None:
    """The specific failure: a longer closing fence made the toolkit swallow a paragraph.

    Asked as "is the prose after the block inside code, according to each of us?" rather
    than by comparing spans, because pandoc reports content and the toolkit reports offsets.
    """
    markdown = FENCE_CASES[name]
    in_code_for_pandoc = "9.99" in pandoc_code_text(markdown)

    masked = list(markdown)
    for fence in fenced_spans(markdown):
        for index in range(fence.start, fence.end):
            masked[index] = " "
    in_code_for_toolkit = "9.99" not in "".join(masked)

    assert in_code_for_toolkit == in_code_for_pandoc, (
        f"{name}: pandoc puts the prose {'inside' if in_code_for_pandoc else 'outside'} a "
        f"code block; the toolkit thinks the opposite"
    )
