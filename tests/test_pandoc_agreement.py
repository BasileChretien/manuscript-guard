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

A third came from asking pandoc: a `## Methods` line directly under a line of Results prose.
Pandoc does not let a heading interrupt a paragraph and printed it as text. The toolkit took
it for a heading, and the `p < 0.001` below it passed as the alpha chosen in advance.

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
    # A heading cannot interrupt a paragraph (pandoc's `blank_before_header`), so each of
    # these is printed as text inside the paragraph above it.
    "atx continuing a paragraph": (
        "## Results\n\nThe excess was significant\n## Methods\n(p < 0.001).\n"
    ),
    "setext continuing a paragraph": (
        "## Results\n\nThe excess was significant\nMethods\n-------\n\n(p < 0.001).\n"
    ),
    "setext with equals continuing a paragraph": (
        "## Results\n\nThe excess was significant\nMethods\n=======\n\n(p < 0.001).\n"
    ),
    "atx continuing a list item": "- An item\n## Methods\n",
    "atx continuing a list paragraph": "- An item\n\n  More of it\n## Methods\n",
    "atx continuing a block quote": "> A quotation\n## Methods\n",
    "atx continuing a block quote past an html tag": "> A quotation\n<p>\n## Methods\n",
    "atx directly under a fence after a block quote": (
        f"> A quotation\n{FENCE}\nx\n{FENCE}\n## Results\n"
    ),
    "atx continuing a caption": "| a |\n|---|\n| 1 |\n\n: A caption\n## Methods\n",
    "setext continuing a caption under its table": "| a |\n|---|\n| 1 |\n: A caption\n-------\n",
    "atx after an inline html comment": "Prose.\n<!-- a note -->\n## Methods\n",
    "atx after an inline tex command": "Prose.\n\\newpage\n## Methods\n",
    "atx after a line of inline tex": "\\textbf{Note}\n## Methods\n",
    "atx after a tilde fence inside a paragraph": "Prose.\n~~~\nx\n~~~\n## Methods\n",
    # A lone `#` is an empty heading, not the first half of one spread over two lines.
    "lone hash above a line": "#\nMethods\n\nProse.\n",
    # ...and needs no blank line after any block that is not a paragraph.
    "atx directly under atx": "# Title\n## Methods\n\nProse.\n",
    "atx directly under a table": "| a | b |\n|---|---|\n| 1 | 2 |\n## Results\n\nProse.\n",
    "atx directly under a fenced listing": f"{FENCE}r\nx <- 1\n{FENCE}\n## Results\n\nProse.\n",
    "atx directly under a fence after prose": f"Prose.\n{FENCE}\nx\n{FENCE}\n## Results\n",
    "atx directly under a tilde fence after a list item": "- An item\n~~~\nx\n~~~\n## Results\n",
    "atx directly under an html comment": "<!-- a note -->\n## Results\n\nProse.\n",
    "atx directly under front matter": "---\ntitle: T\n---\n## Results\n\nProse.\n",
    "atx directly under a thematic break": "Prose.\n\n***\n## Results\n\nProse.\n",
    "atx directly under a setext heading": "Title\n=====\n## Results\n\nProse.\n",
    "atx directly under a fenced div": "::: note\nProse.\n:::\n## Results\n\nProse.\n",
    "atx directly under a page break": "\\newpage\n## Results\n\nProse.\n",
    "atx directly under an indented listing": "Prose.\n\n    x <- 1\n## Results\n\nProse.\n",
    "atx directly under an html block": "<div>\nProse.\n</div>\n## Results\n\nProse.\n",
    "atx directly under an html tag after prose": "Prose.\n<p>\n## Results\n",
    "atx directly under a line block": "| A line of verse\n## Results\n\nProse.\n",
    "atx directly under a tex environment after prose": (
        "Prose.\n\\begin{landscape}\nx\n\\end{landscape}\n## Results\n"
    ),
    "atx inside a tex environment": "\\begin{landscape}\n## Methods\n\\end{landscape}\n",
    "setext directly under atx": "# Title\nMethods\n-------\n\nProse.\n",
    "setext directly under a table": "| a |\n|---|\n| 1 |\nMethods\n-------\n",
    "setext directly under a page break": "\\newpage\nMethods\n-------\n",
    # Pandoc tries a setext heading before an ATX one, and takes any line as its title.
    "setext titled like atx": "## Methods\n-------\n\nProse.\n",
    "setext titled like a quotation": "> Methods\n-------\n",
    # Found by review: what ends a paragraph, a list item or a block quote, and what only
    # looks as though it might.
    "atx under a div closing a list": (
        '## Methods\n\n<div custom-style="Key points">\n- One\n- Two\n</div>\n## Results\n'
    ),
    "atx under a div closing a block quote": "<div>\n> A quotation\n</div>\n## Results\n",
    "atx under a line ending in a block tag": (
        'Prose. <div style="page-break-after: always"></div>\n## Results\n'
    ),
    "atx under prose ending in a closing tag": "<div>\nSome text</div>\n## Results\n",
    "atx under a block tag inside a line of prose": "Prose <div>x</div> more\n## Methods\n",
    "atx under a textarea tag": "Prose.\n<textarea>\n## Results\n",
    "atx under a noscript tag": "Prose.\n<noscript>\n## Methods\n",
    "atx under an indented fence in a paragraph": (
        f"The excess\n  {FENCE}\n  x\n  {FENCE}\n## Methods\n"
    ),
    "atx under a comment holding a blank line": "The excess\n<!--\n\n-->\n## Methods\n",
    "atx under a block comment holding a blank line": "<!--\n\n-->\n## Results\n",
    "atx under a line of no-break spaces": f"The excess\n{chr(0xA0)}\n## Methods\n",
    "atx under a line starting with a plus": "+12% more reports\n## Methods\n",
    "atx under a line starting with a pipe": "|d| exceeded the bound\n## Methods\n",
    "atx under colons that open no div": "::: note text here\nThe excess\n:::\n## Methods\n",
    "atx under a citation shaped like a link": "[@smith2020]: they found it\n## Methods\n",
    "atx under a link definition with a title": '[a]: http://x.org "T"\n## Results\n',
    "atx under a page reference": "\\pageref{x}\n## Results\n",
    "atx under a fence closing a roman list item": "(ii) An item\n~~~\nx\n~~~\n## Results\n",
    "atx under a fence in a paragraph starting A.": "A. Smith agreed\n~~~\nx\n~~~\n## Methods\n",
    # Found by the second review.
    "atx under a link definition with attributes": "[f]: fig.png {width=80%}\n## Results\n",
    "atx under a link definition in angle brackets": "[a]: <my file.png>\n## Results\n",
    "atx under an inline tag after a block tag": "The excess.<hr><br>\n## Methods\n",
    "atx under a closing span after a closing div": "<div>\nIt was.</div></span>\n## Methods\n",
    "atx inside a pre block opened after prose": "The excess.<pre>\n## Methods\n</pre>\n",
    "atx inside a textarea": "<textarea>\n## Methods\n</textarea>\n",
    "atx under a closed style block": "<style>\n## Methods\n</style>\n## Results\n",
    "atx under an unclosed style tag": "<style>\n## Results\n",
    "atx under a noscript tag at the margin": "<noscript>\n## Results\n",
    "atx under a quote after a div in inline code": (
        "Wrap it in `<div>` tags.\n\n> A quotation\n</div>\n## Methods\n"
    ),
    "atx under an indented closing div in a quote": "<div>\n> A quotation\n </div>\n## Methods\n",
    "atx under a section closing a block quote": (
        "<section>\n> A quotation\n</section>\n## Results\n"
    ),
    "atx under a list item ending in a block tag": "- An item <hr>\n## Results\n",
    "atx under a fence ending a lettered item": "(A) An item\n~~~\nx\n~~~\n## Results\n",
    "atx under a fence ending a roman item": "II. An item\n~~~\nx\n~~~\n## Results\n",
    "atx under a fence in a paragraph starting dim.": "dim. light\n~~~\nx\n~~~\n## Methods\n",
    "atx under a fence in a paragraph starting p. 12": "p. 12 of it\n~~~\nx\n~~~\n## Methods\n",
    "atx under a div with a colon in its class": "::: fig:one\nProse.\n:::\n## Results\n",
    "setext titled with a block tag": "Some text.<pre>\n-------\n",
    "atx past a tilde fence in a definition in a list item": (
        "- An item\n: a definition\n~~~\nx\n~~~\n## Methods\n"
    ),
    "atx under a fence opened in the front matter": (
        f"---\ntitle: T\nabstract: |\n  {FENCE}\n---\n\n## Results\n\n{FENCE}\n"
    ),
}


def test_an_html_tag_read_inline_over_an_underline_is_a_heading() -> None:
    """Pandoc looks for a heading before an HTML block, `<div>` apart, so `<noscript>` over
    an underline is a heading with the tag as its raw title. Compared by count: pandoc's
    title has no text in it, the toolkit's is the tag."""
    markdown = "<noscript>\n-------\n\nProse.\n"
    assert len(headings(markdown)) == len(pandoc_headings(markdown)) == 1


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


def test_a_heading_in_a_list_item_ends_a_section_and_opens_none() -> None:
    """A second divergence, for the same reason as the quoted one.

    Pandoc reads `- Results` over an underline as a list item holding a heading titled
    "Results". The toolkit keeps the marker in the title. It still ends the section above,
    and is printed as a heading, so the p-value under it is not taken for Methods. But a
    title of "- Methods" never matches Methods, so `- Methods` over an underline cannot
    re-admit the `methods_only` rules below a Results section.
    """
    from manuscript_guard.classify import UNCLASSIFIED, Classifier
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.sections import section_chain
    from manuscript_guard.text.tokens import find_atoms

    ended = "## Methods\n\n- Results\n---------\n\nThe excess was significant (p < 0.001).\n"
    opened = "## Results\n\n- Methods\n---------\n\nThe excess was significant (p < 0.001).\n"
    for markdown in (ended, opened):
        atom = next(a for a in find_atoms(markdown, mask(markdown)) if a.text == "0.001")
        chain = section_chain(markdown, atom.start)
        assert chain[-1].startswith("- ")
        assert Classifier.load().classify(atom, chain).kind == UNCLASSIFIED


def test_a_heading_under_a_table_placeholder_is_read_as_the_build_prints_it() -> None:
    """The gates read `{{table.t}}`; pandoc reads the pipe table the build puts in its place,
    and a table ends at its last row. Read as a line of prose, the placeholder hid the
    `## Results` under it: the heading the document prints was lost to G2, and a p-value
    below it would have passed as Methods."""
    from pathlib import Path

    from manuscript_guard.build.assemble import render_table
    from manuscript_guard.contracts.results import Table

    table = Table(
        key="t",
        columns=("Arm", "Reports"),
        rows=(("Drug", "412"),),
        caption=None,
        align=("left", "right"),
        quoted=True,
        source=Path("t.json"),
    )
    source = "## Methods\n\n{{table.t}}\n## Results\n\nProse.\n"
    built = source.replace("{{table.t}}", render_table(table))
    assert headings(source) == pandoc_headings(built) == ["Methods", "Results"]


# ---------------------------------------------------------------- list items


def pandoc_list_items(markdown: str) -> list[str]:
    """The first line of every list item pandoc makes, outside quotations, in order."""
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    found: list[str] = []

    def first_line(item: list) -> str:
        inlines = item[0]["c"] if item and item[0].get("t") in {"Plain", "Para"} else []
        cut = next(
            (i for i, n in enumerate(inlines) if n.get("t") in {"SoftBreak", "LineBreak"}),
            len(inlines),
        )
        return _inline_text(inlines[:cut]).strip()

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("t") in NESTED:
                return
            items = {"OrderedList": lambda c: c[1], "BulletList": lambda c: c}.get(node.get("t"))
            if items is not None:
                for item in items(node["c"]):
                    found.append(first_line(item))
                    walk(item)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(finished.stdout)["blocks"])
    return found


def toolkit_list_items(markdown: str) -> list[str]:
    import re

    from manuscript_guard.text.blocks import list_items

    lines = [markdown[start:].split("\n", 1)[0] for start in list_items(markdown)]
    return [re.sub(r"^\s*\S+\s*", "", line, count=1).strip() for line in lines]


# Where a list may start. Pandoc does not let one interrupt a paragraph
# (`lists_without_preceding_blankline` is off), so a count that a hard wrap put at the start
# of a line is prose, and `ordered-list-marker` exempted it as list numbering.
LIST_CONSTRUCTS = {
    "a count at a wrap point": "The number of reports was\n412. Of these, most were hepatic.\n",
    "a bracketed count at a wrap point": "The number of reports was\n412) of them hepatic.\n",
    "a count at a wrap point past a comment": "The number was\n<!-- note -->\n412. Of these.\n",
    "a count at a wrap point past a tilde fence": "The number was\n~~~\nx\n~~~\n412. Of these.\n",
    "a count at a wrap point in a block quote": "> The number was\n412. Of these.\n",
    "a count at a wrap point in a caption": "| a |\n|---|\n| 1 |\n: Counts were\n412. Of these.\n",
    "a numbered list after a blank line": "Criteria:\n\n1. First\n2. Second\n",
    "a numbered list under a heading": "# Methods\n1. First\n2. Second\n",
    "a numbered list under a table": "| a |\n|---|\n| 1 |\n1. First\n",
    "a numbered list under a fence": f"{FENCE}\nx\n{FENCE}\n1. First\n",
    "a numbered list in a div": "::: note\n1. First\n:::\n",
    "a numbered list under a block tag": "Prose.<hr>\n1. First\n",
    "a numbered item under a bullet item": "- First\n1. Second\n",
    "a nested numbered item": "1. First\n   1. Inner\n",
    "a count wrapped inside a list item": "1. The count was\n412. Of these\n",
    "numbered items apart": "1. First\n\n2. Second\n",
    "an underlined numbered line": "1. Methods\n---\n",
    "a numbered line in a fence": f"{FENCE}\n1. First\n{FENCE}\n",
    # Pandoc folds the digits after a bare LaTeX command into the raw block: `\newpage` over
    # "1. First" is the raw "\newpage\n1" and a paragraph ". First".
    "a numbered line under a bare latex command": "\\newpage\n412. Of these.\n",
    "a numbered line under a latex command with an argument": "\\vspace{1cm}\n1. First\n",
    # A definition in a list item's lazy lines turns the rest into its paragraph.
    "a count after a definition in a list item": "- An item\n: a definition\n412. Of these\n",
    "a numbered item after a term in a list item": "1. First\nTerm\n:   Def\n2. Second\n",
    "a numbered line past a tilde fence in a definition": (
        "- An item\n: a definition\n~~~\nx\n~~~\n2. Second\n"
    ),
    # A paragraph after a blank line stays in the list only indented to the item's text.
    "a count under a paragraph indented short of its item": "1. First\n\n  More\n2. Second\n",
    "a count under a paragraph indented to its item": "1. First\n\n   More\n2. Second\n",
    "a count under a paragraph short of a wide marker": "10. First\n\n   More\n2. Second\n",
}


@pytest.mark.parametrize("name", sorted(LIST_CONSTRUCTS))
def test_the_toolkit_sees_the_list_items_pandoc_renders(name: str) -> None:
    """`ordered-list-marker` holds only where one of these starts."""
    markdown = LIST_CONSTRUCTS[name]
    assert toolkit_list_items(markdown) == pandoc_list_items(markdown), (
        f"{name}: toolkit saw {toolkit_list_items(markdown)}, pandoc renders "
        f"{pandoc_list_items(markdown)}"
    )


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
