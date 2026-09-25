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

from manuscript_guard.text.fences import fenced_spans, unclear_fence_lines
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

# Characters that end a line for Python, or are space to it, and what pandoc makes of each.
_ODD = {
    "a vertical tab": 0x0B,
    "a form feed": 0x0C,
    "a lone carriage return": 0x0D,
    "a file separator": 0x1C,
    "a group separator": 0x1D,
    "a record separator": 0x1E,
    "a next-line control": 0x85,
    "a no-break space": 0xA0,
    "an en quad": 0x2000,
    "a line separator": 0x2028,
    "a paragraph separator": 0x2029,
    "an ideographic space": 0x3000,
}
# What may follow an opening fence. Pandoc takes a raw `{=format}`, or a word and
# `{attributes}`, either or both; anything more and the lines are a paragraph.
_INFOS = [
    "", "r", " r", "r ", "\tr\t", "r foo", "r`x", "r{x}", "r{.x}", "r {.x}", "r {r}",
    "{}", "{-}", "{.r}", "{ .r }", "{.r}\t", "{#id .r}", '{.r .numberLines startFrom="5"}',
    "{.r key='a b'}", '{.r k=""}', "{.r k=}", '{.r k="a"b}', '{.r k=" a"}', "{.r k=a`b}",
    "{.r k=a\\}b}", "{.r k=a\\ b}", "{.r k=a\\bc}", '{.r k="a\\"b"}', '{.r k="a\\\\"}',
    "{.r k=a\\é}", "{.é}", "{.x²}", "{.²x}", "{.2x}", "{r}", "{r, echo=FALSE}",
    "{r echo=FALSE}", "{.r} x", "{.r}x", "{.r}}", "{.r", "{=html}", " {=html} ", "{= html}",
    "{=openxml} x", "{ =openxml}", "{#1 .r}", "{#1}", "{#_x}", "{#-x}", "{#.x}", "{#}",
]
FENCE_CASES.update(
    {
        **{
            f"opener {FENCE}{info!r}": f"Prose.\n\n{FENCE}{info}\nProse 9.99.\n{FENCE}\n\nEnd.\n"
            for info in _INFOS
        },
        "tilde opener with a backtick": "Prose.\n\n~~~r`x\nProse 9.99.\n~~~\n\nEnd.\n",
        # A chunk header pandoc rejects, and its closer, which then paired with the next.
        "two R Markdown chunks": (
            f"{FENCE}{{r setup}}\nx <- 1\n{FENCE}\n\nProse 9.99.\n\n{FENCE}{{r plot}}\ny\n{FENCE}\n"
        ),
        # Straight under a line of text: pandoc opens a backtick fence there, not a tilde one
        # or an indented one.
        "backtick fence under a line": f"We used:\n{FENCE}r\nProse 9.99.\n{FENCE}\n",
        "tilde fence under a line": "We used:\n~~~\n\nProse 9.99.\n\n~~~r\ny\n~~~\n",
        "indented fence under a line": (
            f"We used:\n  {FENCE}r\nx\n{FENCE}\n\nProse 9.99.\n\n{FENCE}r\ny\n{FENCE}\n"
        ),
        "fence behind a byte-order mark": (
            f"{chr(0xFEFF)}{FENCE}r\nx\n{FENCE}\n\nProse 9.99.\n\n{FENCE}r\ny\n{FENCE}\n"
        ),
        # Pandoc lets attributes, and a quoted value, run on while no line between is blank.
        **{
            f"attributes over lines {opener!r}": (
                f"Prose.\n\n{FENCE}{opener}\nProse 9.99.\n{FENCE}\n\nEnd.\n"
            )
            for opener in (
                "{.r\n.x}",
                "{.r\n  .x\n  k=v}",
                "{\n.r}",
                "r {.x\n}",
                '{.r k="a\nb"}',
                "{.r\n\n.x}",
                '{.r k="a\n\nb"}',
                "{.r\nThe excess}",
                "{.r\n.x} y",
            )
        },
        "tilde opener with a backtick in a value": (
            "Prose.\n\n~~~{.r k=a`b}\nProse 9.99.\n~~~\n\nEnd.\n"
        ),
        **{
            f"opener {FENCE}r then {name}": (
                f"Prose.\n\n{FENCE}r{chr(code)}\nProse 9.99.\n{FENCE}\n\nEnd.\n"
            )
            for name, code in _ODD.items()
        },
        **{
            f"closer {where}": f"{FENCE}r\nx\n{closer}\n\nProse 9.99.\n\n{FENCE}\ny\n{FENCE}\n"
            for where, closer in {
                "after three spaces": "   " + FENCE,
                "after a tab": "\t" + FENCE,
                "after a space and a tab": " \t" + FENCE,
                "then spaces and a tab": FENCE + "  \t",
                "then a word": FENCE + " x",
                **{f"then {name}": FENCE + chr(code) for name, code in _ODD.items()},
                **{f"after {name}": chr(code) + FENCE for name, code in _ODD.items()},
            }.items()
        },
        **{
            f"a fence after {name} on one line": (
                f"We found it.{chr(code)}{FENCE}\n\nProse 9.99.\n\nThe end.{chr(code)}{FENCE}\n"
            )
            for name, code in _ODD.items()
        },
    }
)


def pandoc_code_text(markdown: str) -> str:
    """Everything pandoc puts inside a CodeBlock, or a RawBlock, which a fence opens as well
    and the gates treat the same, concatenated."""
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
            if node.get("t") in ("CodeBlock", "RawBlock"):
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


@pytest.mark.parametrize("name", sorted(FENCE_CASES))
def test_prose_outside_a_fence_is_prose_to_both(name: str) -> None:
    """The specific failure: a longer closing fence made the toolkit swallow a paragraph.

    Asked as "is the prose after the block inside code, according to each of us?" rather
    than by comparing spans, because pandoc reports content and the toolkit reports offsets.
    A fence the toolkit does not claim to read as pandoc does is refused instead
    (`unclear_fence_lines`), so either the two agree or `check` and the build stop.
    """
    markdown = FENCE_CASES[name]
    in_code_for_pandoc = "9.99" in pandoc_code_text(markdown)

    masked = list(markdown)
    for fence in fenced_spans(markdown):
        for index in range(fence.start, fence.end):
            masked[index] = " "
    in_code_for_toolkit = "9.99" not in "".join(masked)

    assert in_code_for_toolkit == in_code_for_pandoc or unclear_fence_lines(markdown), (
        f"{name}: pandoc puts the prose {'inside' if in_code_for_pandoc else 'outside'} a "
        f"code block; the toolkit thinks the opposite, and does not refuse the fence"
    )
