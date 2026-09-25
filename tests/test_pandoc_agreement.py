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


# ------------------------------------------------ what import holds a paragraph in place for

TICKS = "`" * 2
AFTER = " ratio from `ror` was used. <!-- a draft quoted `grep`:"

#: A paragraph whose comment runs past it, or which holds display maths, is held in place by
#: `import`: moved, it would carry the comment's opening or the equation away from the rest.
#: `merge._bare` decides both without pandoc, by setting aside what pandoc does not read as
#: prose. Backticks pandoc reads as something other than code, taken for code, paired with a
#: real code span and hid the `<!--` after it, and the paragraph was moved into the comment.
HOLD_CASES = {
    "inline maths holding backticks": "The $\\text{" + TICKS + "crude''}$" + AFTER,
    "raw TeX holding backticks": "The \\emph{" + TICKS + "crude''}" + AFTER,
    "raw TeX with nested braces": "The \\textbf{a{" + TICKS + "b}c}" + AFTER,
    "link address holding backticks": "The [link](http://x/" + TICKS + "y)" + AFTER,
    "link title holding backticks": 'The [link](http://x/y "a' + TICKS + 'b")' + AFTER,
    "image address holding backticks": "The ![alt](pic" + TICKS + ".png)" + AFTER,
    "link text holding code": "The [`a`](http://x/" + TICKS + "y)" + AFTER,
    "autolink holding backticks": "The <http://x.org/" + TICKS + "y>" + AFTER,
    "html attribute holding backticks": 'The <span title="' + TICKS + 'q">a</span>' + AFTER,
    "display maths holding backticks": "The $$\\text{" + TICKS + "x''}$$" + AFTER,
    "escaped backtick before a code span": "The \\`" + "`onset`" + AFTER,
    "dollar amounts": "It cost $5 and $10 by `ror`. <!-- a",
    "an unclosed comment and nothing else": "Plain prose. <!-- a draft",
    "raw TeX then a brace that does not close": "The \\text{a<!--}{b and more",
    "raw TeX holding a dollar without its pair": "The \\emph{a$b} `c`" + AFTER,
    "raw TeX holding a dollar pair": "The \\emph{a$b$ " + TICKS + "c} d" + AFTER,
    "raw TeX holding a percent sign": "The \\emph{a%b} `c`" + AFTER,
    "raw TeX with braces nested three deep": "The \\textbf{a{b{" + TICKS + "c}}}" + AFTER,
    "an autolink holding a tag and a backtick": "The <http://x/`<br/> page" + AFTER,
    "a comment opener that reads like an email": "The <!--a@b.org> note, and more",
    "a display opener that does not close": "The $$x$ y <!-- z",
    # Each of these, read as something set aside, hid a comment pandoc opens.
    "maths closing inside its text": "Let $f = \\text{if $x$ is positive}$. <!-- a ($f$) said",
    "maths closing after a no-break space": "The $a" + chr(0xA0) + "$-fold. <!-- a ($y$) said",
    "raw TeX with a group that is not its argument": "The \\emph{a}{crude <!-- a draft}, b",
    "raw TeX that takes no argument": "The ratio\\ldots{crude <!-- a draft}, b",
    "raw TeX with an optional argument": "The \\emph[b <!-- c]{d} end.",
    "raw TeX that takes no argument, then a group": "The \\LaTeX{b <!-- c} end.",
    "raw TeX taking fewer groups than follow": "The \\href{a}{b}{c <!-- d} end.",
    "raw TeX ending an environment": "The \\end{b <!-- c} end.",
    "raw TeX beginning an environment it never ends": "The \\begin{b <!-- c} end.",
    "raw TeX whose dollars pair across a brace": "The \\foo{a$}$b <!-- c} end.",
    "brackets around code that holds a link end": "See [the `f](x)` here" + AFTER,
    "a footnote reference before parentheses": "As shown[^note](a`b) and `ror." + AFTER,
    "a reference link before parentheses": "[a][b](x`y) z `w <!-- q` end.",
    "link text holding a dollar": "[a $](x)$ and <!-- b ($c$) end.",
    "an autolink with a scheme pandoc does not know": "See <zzz:a`b> and `ror." + AFTER,
    "an attribute name with a dot": 'Text <span data.x="a`b"> x `c <!-- d` end.',
    "an attribute name opening with an underscore": 'Text <span _x="a`b"> x `c <!-- d` end.',
    "an attribute name opening with a colon": 'Text <span :x="a`b"> x `c <!-- d` end.',
    "maths closing after a thin space": "The $a" + chr(0x2009) + "$b and <!-- c ($y$) end.",
    "dollars inside two autolinks": "See <$$a@b> c <$$d@e> end.",
}


def pandoc_holds(paragraphs: list[str]) -> list[tuple[bool, bool]]:
    """For each paragraph: does a comment it opens run past it, and does it show display
    maths? Each is followed by a heading and a paragraph of its own, which a comment that
    runs on hides."""
    markdown = "".join(f"# H{i}\n\n{p}\n\nTAIL{i} -->\n\n" for i, p in enumerate(paragraphs))
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    per: dict[int, list] = {i: [] for i in range(len(paragraphs))}
    current = None
    for block in json.loads(finished.stdout)["blocks"]:
        label = _inline_text(block["c"][2]) if block["t"] == "Header" else ""
        if label.startswith("H") and label[1:].isdigit():
            current = int(label[1:])
        elif current is not None:
            per[current].append(block)
    found = []
    for i in range(len(paragraphs)):
        nodes: list = []
        _nodes(per[i], nodes)
        shown = {node["c"] for node in nodes if node.get("t") == "Str"}
        display = any(
            node.get("t") == "Math" and node["c"][0].get("t") == "DisplayMath" for node in nodes
        )
        found.append((f"TAIL{i}" not in shown, display))
    return found


def _nodes(node, out: list) -> None:
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            _nodes(value, out)
    elif isinstance(node, list):
        for value in node:
            _nodes(value, out)


def test_import_holds_the_paragraphs_pandoc_runs_on_or_shows_maths_in() -> None:
    """Named cases: `_bare` finds an open comment wherever pandoc runs one past the
    paragraph, and display maths wherever pandoc shows it. Finding one where pandoc does not
    only holds a paragraph that could have moved; missing one lets a move write into the
    comment. Each is asked of pandoc on its own, so that a brace one leaves open cannot
    close in another. A case where pandoc does neither would test nothing, so none is one."""
    from manuscript_guard.merge import _bare

    wrong = []
    for name in sorted(HOLD_CASES):
        [(runs_on, display)] = pandoc_holds([HOLD_CASES[name]])
        assert runs_on or display, f"{name}: pandoc runs no comment on and shows no maths"
        opens, maths = _bare(HOLD_CASES[name])
        if (runs_on and not opens) or (display and not maths):
            wrong.append(
                f"{name}: pandoc runs on {runs_on}, display {display}; "
                f"_bare finds a comment {opens}, display {maths}"
            )
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize("value", ["0.50", "-0.50", "\N{MINUS SIGN}0.50"])
def test_import_holds_a_paragraph_whatever_sign_a_binding_after_maths_prints(value: str) -> None:
    """`_bare` reads the source, where a binding is `{{...}}`; pandoc reads the build, where it
    is a number. After a closing `$`, a number starting with a digit keeps pandoc from closing
    the maths there, and a negative one does not, which ran the comment on. The maths before
    it hides the comment from the first reading, so the second has to find it."""
    from manuscript_guard.merge import _bare

    source = (
        "The $\\text{" + TICKS + "crude''}$ ratio changed by $x${{results.delta}} units. "
        "<!-- a draft ($y$, " + TICKS + "raw'') said:"
    )
    [(runs_on, display)] = pandoc_holds([source.replace("{{results.delta}}", value)])
    opens, maths = _bare(source)
    assert (runs_on <= opens) and (display <= maths), (
        f"filled with {value}: pandoc runs on {runs_on}; _bare finds a comment {opens}"
    )
