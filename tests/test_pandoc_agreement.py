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
    # An attribute block is not printed, so it is not part of the title.
    "atx unnumbered": "# References {-}\n\nProse.\n",
    "atx identifier and class": "# References {#refs .unnumbered}\n\nProse.\n",
    "atx key and quoted value": '## Results {#sec-results lang="en-GB"}\n\nProse.\n',
    "atx attributes after closing hashes": "## Results ## {#sec-results}\n\nProse.\n",
    "setext with attributes": "Methods {#sec-methods}\n-------\n\nProse.\n",
    # Braces pandoc prints: not an attribute block, or not the last thing on the line.
    "atx braces that are not attributes": "# Results {and more}\n\nProse.\n",
    "atx closing hashes after braces": "# Results {-} ##\n\nProse.\n",
    "atx two blocks": "# Results {.a} {-}\n\nProse.\n",
    # A value may hold backslash escapes, as pandoc reads them.
    "atx escaped quote in a quoted value": (
        '# Results {#sec-results title="the \\"main\\" results"}\n\nProse.\n'
    ),
    "atx escaped quote in a single-quoted value": "# Results {k='a\\'b'}\n\nProse.\n",
    "atx escaped space in a value": "# Results {k=a\\ b}\n\nProse.\n",
    "atx escaped closing brace in a value": "# Results {#sec-results note=a\\}b}\n\nProse.\n",
    "atx escaped opening brace in a value": "# Results {k=a\\{b}\n\nProse.\n",
    # An unquoted value ends at a space, a tab, a line break or `}`, and at no other space.
    "atx no-break space in a value": "# Results {#sec-results lang=fr\u00a0FR}\n\nProse.\n",
    "atx thin space in a value": "# Results {#sec-results lang=fr\u2009FR}\n\nProse.\n",
    "atx form feed in a value": "# Results {#sec-results lang=fr\fFR}\n\nProse.\n",
    "atx empty quoted value": '# References {title=""}\n\nProse.\n',
    "atx empty single-quoted value": "# References {title=''}\n\nProse.\n",
    "atx quoted value ending in a space": '# References {title="Works "}\n\nProse.\n',
    # Only spaces and tabs may follow a block or closing `#`s; any other space is printed.
    "atx no-break space after the block": "# References {-}\N{NO-BREAK SPACE}\n\nProse.\n",
    "atx ideographic space after the block": "# References {-}\N{IDEOGRAPHIC SPACE}\n\nProse.\n",
    "atx form feed after the block": "# References {-}\f\n\nProse.\n",
    "atx no-break space after a closing hash": "# References #\N{NO-BREAK SPACE}\n\nProse.\n",
    "atx no-break space between a hash and the block": (
        "# References #\N{NO-BREAK SPACE}{-}\n\nProse.\n"
    ),
    # A class or a key opens with a letter, and a number that is not a digit is not one.
    "atx class opening with a superscript": "# References {.\N{SUPERSCRIPT TWO}}\n\nProse.\n",
    "atx key opening with a roman numeral": (
        "# References {\N{ROMAN NUMERAL EIGHT}=1}\n\nProse.\n"
    ),
    "atx class opening with a titlecase letter": (
        "# References {.\N{LATIN CAPITAL LETTER D WITH SMALL LETTER Z WITH CARON}}\n\nProse.\n"
    ),
    "atx class opening with a modifier letter": (
        "# References {.\N{MODIFIER LETTER SMALL H}}\n\nProse.\n"
    ),
    "atx identifier opening with a superscript": (
        "# References {#\N{SUPERSCRIPT TWO}}\n\nProse.\n"
    ),
    # A quoted value may open with any character pandoc's `isSpace` refuses, which is not
    # every character Python's `\s` takes.
    "atx quoted value opening with a next line": (
        '# Results {title="\N{NEXT LINE}x y"}\n\nProse.\n'
    ),
    "atx quoted value opening with a line separator": (
        '# Results {title="\N{LINE SEPARATOR}x y"}\n\nProse.\n'
    ),
    "atx quoted value opening with a file separator": (
        '# Results {title="\N{INFORMATION SEPARATOR FOUR}x y"}\n\nProse.\n'
    ),
    "atx quoted value opening with a unit separator": (
        '# Results {title="\N{INFORMATION SEPARATOR ONE}x y"}\n\nProse.\n'
    ),
    "atx quoted value opening with a zero-width space": (
        '# Results {title="\N{ZERO WIDTH SPACE}x y"}\n\nProse.\n'
    ),
}


@pytest.mark.parametrize("name", sorted(CONSTRUCTS))
def test_the_toolkit_sees_the_headings_pandoc_renders(name: str) -> None:
    """Where these disagree, the toolkit is wrong: pandoc builds what the reader receives."""
    markdown = CONSTRUCTS[name]
    assert headings(markdown) == pandoc_headings(markdown), (
        f"{name}: toolkit saw {headings(markdown)}, pandoc renders "
        f"{pandoc_headings(markdown)}"
    )


# Where pandoc prints the braces, it also typesets what is between them, `\}` as `}` and a
# straight quote as a curly one, and the toolkit does neither to a title. So these are
# compared on the one thing in question: whether the heading still ends in its braces.
BRACES = {
    "escaped closing brace ends no block": "# References {k=\\}\n\nProse.\n",
    "escaped closing brace after a value": "# Results {k=a\\}\n\nProse.\n",
    "escaped quote in a quoted value": '# Results {title="the \\"main\\" results"}\n',
    "escaped closing brace in a value": "# Results {#sec-results note=a\\}b}\n",
    "escaped backslash before a closing brace": "# Results {k=a\\\\}\n",
    "escaped quote that leaves a quote open": '# Results {k="a\\"}\n',
    "escaped opening brace before the block": "# Results \\{-}\n",
    # A quoted value may not open with a space or a tab.
    "space after an opening quote": '# References {title=" Works cited"}\n',
    "space after an opening single quote": "# References {k=' a'}\n",
    "tab after an opening quote": '# References {title="\tWorks"}\n',
    "no-break space after an opening quote": '# References {title="\u00a0Works"}\n',
    # Every space pandoc's `isSpace` takes, after an opening quote.
    "ideographic space after an opening quote": '# Results {title="\N{IDEOGRAPHIC SPACE}x y"}\n',
    "ogham space mark after an opening quote": '# Results {title="\N{OGHAM SPACE MARK}x y"}\n',
    "en quad after an opening quote": '# Results {title="\N{EN QUAD}x y"}\n',
    "hair space after an opening quote": '# Results {title="\N{HAIR SPACE}x y"}\n',
    "narrow no-break space after an opening quote": (
        '# Results {title="\N{NARROW NO-BREAK SPACE}x y"}\n'
    ),
    "medium mathematical space after an opening quote": (
        '# Results {title="\N{MEDIUM MATHEMATICAL SPACE}x y"}\n'
    ),
    "vertical tab after an opening quote": '# Results {title="\vx y"}\n',
    "no-break space after the block": "# References {-}\N{NO-BREAK SPACE}\n",
    "thin space after the block": "# References {-}\N{THIN SPACE}\n",
    "class opening with a roman numeral": "# References {.\N{ROMAN NUMERAL EIGHT}}\n",
}


@pytest.mark.parametrize("name", sorted(BRACES))
def test_the_toolkit_takes_off_the_attribute_blocks_pandoc_takes_off(name: str) -> None:
    markdown = BRACES[name]
    (toolkit,) = headings(markdown)
    (printed,) = pandoc_headings(markdown)
    assert toolkit.endswith("}") == printed.endswith("}"), (
        f"{name}: toolkit saw {toolkit!r}, pandoc renders {printed!r}"
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
