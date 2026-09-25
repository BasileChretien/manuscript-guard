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
import re
import shutil
import subprocess
from pathlib import Path

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
    # Found by the review of the pushed head.
    "atx under an either-tag block": "## Methods\n\n<ins>\nThe new text\n</ins>\n## Results\n",
    "atx under prose closing an either-tag block": "<ins>\nThe new text</ins>\n## Results\n",
    "atx under seven hashes": "####### Note\n## Results\n",
    "atx under prose after a comment at a line's start": (
        "## Results\n\n<!-- check this --> The excess was significant\n## Methods\n"
    ),
    "atx after a comment on the same line": "<!-- x -->## Results\n",
    "atx under a plus-minus at a line's start": (
        "## Results\n\n+-0.3 SD was the spread\n## Methods\n"
    ),
    "atx under a grid table": "+---+---+\n| a | b |\n+---+---+\n## Results\n",
    "atx under a footnote's second paragraph": (
        "## Results\n\nText.[^1]\n\n[^1]: A note.\n\n    More of the note.\n## Methods\n"
    ),
    "atx under a stray colon fence after a four-colon div": (
        "## Results\n\n:::: {.box}\nText.\n::::\n\nThe excess was significant\n:::\n## Methods\n"
    ),
    "atx under a pandoc title block": "% Title\n% Author\n# Abstract\n",
    "atx under a title block's continuation": "% Title\n  continued\n% Author\n# Abstract\n",
    "atx under a fourth percent line": "% a\n% b\n% c\n% d\n# Abstract\n",
    "atx under a title block after front matter": "---\ntitle: x\n---\n% Title\n# Abstract\n",
    # A tag at the margin is a block, and the rest of its line starts the next one.
    "atx under text after a block tag": "<div>Text\n## Results\n",
    "atx under text after an either tag": "<ins>Text\n## Results\n",
    "atx under text closing the either tag it follows": "<ins>Text</ins>\n## Results\n",
    "atx after a block tag on the same line": "<div>## Results\n",
    "atx under a grid border nothing closes": "+---+---+\n| a | b |\n## Results\n",
    "atx under a closed grid table": "+---+---+\n| a | b |\n+---+---+\n## Results\n",
    # A footnote takes every line up to a blank one.
    "atx under a block tag in a footnote": "T.[^1]\n\n[^1]: A note.\n<div>\n## Methods\n",
    "atx under a fence in a footnote": (
        f"T.[^1]\n\n[^1]: A note.\n{FENCE}\nx\n{FENCE}\n## Methods\n"
    ),
    "atx under code in a footnote": "T.[^1]\n\n[^1]: A note.\n\n        code\n## Methods\n",
    "atx after a footnote and a blank line": "T.[^1]\n\n[^1]: A note.\n\n## Methods\n",
    "atx under a footnote's three-space line": (
        "T.[^1]\n\n[^1]: A note.\n\n   Three.\n## Methods\n"
    ),
    # Found by the fourth review. A note with nothing on its marker line takes the next
    # stretch of lines after the blank as its first paragraph, indented or not.
    "atx in an empty footnote's first paragraph": "T.[^1]\n\n[^1]:\n\n## Methods\n",
    "atx after an empty footnote's first paragraph": (
        "T.[^1]\n\n[^1]:\n\nNote text.\n\n## Methods\n"
    ),
    # Indented one to three spaces, a comment is inline and starts a paragraph.
    "atx under an indented comment": "## Results\n\n <!-- TODO -->\n## Methods\n",
    "atx under an indented comment and text": "## Results\n\n  <!-- x --> Text\n## Methods\n",
    "setext from an indented comment and text": "## Results\n\n  <!-- x --> Text\n=====\n",
    "atx under an indented comment under an either tag": "<ins>\n <!-- c -->\n## Methods\n",
    "atx under an indented comment under a div": "<div>\n <!-- c -->\n## Methods\n",
    # A `<del>` closed in the middle of a line is closed: a later line ending in `</del>`
    # is inline text, and the paragraph goes on.
    "atx under a deletion closed mid-line earlier": (
        "## Results\n\n<del>Not\nsignificant.</del> It was.\n\nIt was <del>not</del>\n"
        "## Methods\n"
    ),
    # Found by the fifth review. What follows a comment on its line is text, not an underline
    # or a rule; the rest of a tag's line over an underline is a setext title.
    "setext under an underline after a comment": "## Results\n\nMethods\n<!-- -->===\n",
    "atx under a rule with a comment after it": (
        "## Results\n\nText.\n\n--- <!-- revised -->\n## Methods\n"
    ),
    "setext from the rest of a tag's line": "## Results\n\n<div># Methods\n-\n\nText.\n\n</div>\n",
    # `</pre>` does not close a `<p>`: counted as one, the quote below ran on past the `</p>`
    # that ends its lazy lines, and took the heading under it.
    "atx under a quote stopped by a p closer after a pre closer": (
        "<p>\nIntro </pre> here\n\n> Quote\n</p>\n## Results\n"
    ),
    "atx under inline latex qty": "\\qty{1}{m}\n## Methods\n",
    "atx under inline latex ac": "\\ac{ROR}\n## Methods\n",
    "atx under inline latex acrshort": "\\acrshort{x}\n## Methods\n",
    "atx under inline latex bfseries": "\\bfseries\n## Methods\n",
    "atx under inline latex colorbox": "\\colorbox{red}{x}\n## Methods\n",
    "atx under inline latex vref": "\\vref{x}\n## Methods\n",
    "atx under inline latex pilcrow": "\\P\n## Methods\n",
    "atx under latex texttrademark": "\\texttrademark\n## Methods\n",
    "atx under latex hypertarget": "\\hypertarget{a}{b}\n## Methods\n",
    # A definition indented to a list item's text is a definition list inside the item, so
    # the fence after it ends the item and the heading under the fence is printed.
    "atx under a fence after an indented definition in a list item": (
        "## Methods\n\n- Disproportionality\n  : a reporting odds ratio above one\n~~~\n"
        "x <- 1\n~~~\n## Results\n"
    ),
    "atx under a fence after a definition in a list item": (
        "## Methods\n\n- Disproportionality\n: a reporting odds ratio above one\n~~~\n"
        "x <- 1\n~~~\n## Results\n"
    ),
    "atx under an inline latex index": "\\index{x}\n## Methods\n",
    "atx under an inline latex si unit": "\\SI{1}{m}\n## Methods\n",
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


@pytest.mark.parametrize("command", ["\\newpage", "\\clearpage", "\\pagebreak"])
def test_a_numbered_title_under_a_page_break_is_still_a_heading(command: str) -> None:
    """Pandoc folds the digits opening the line under a bare LaTeX command into the raw
    block, so "412. Of these" there is no list item. A title over an underline is still a
    heading: pandoc prints it as ". Results", and the gates keep its number. Read as a
    paragraph, it lost the Results heading and left a p-value under it in the Methods."""
    from manuscript_guard.text.blocks import find_headings

    markdown = f"## 1. Methods\n\nText.\n\n{command}\n2. Results\n----------\n\nText.\n"
    assert pandoc_headings(markdown) == ["1. Methods", ". Results"]
    assert [(h.level, h.title) for h in find_headings(markdown)] == [
        (2, "1. Methods"),
        (2, "2. Results"),
    ]


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
        if item and item[0].get("t") == "DefinitionList":
            # An item whose first line is a term: `- Term` over `  : its definition`.
            inlines = item[0]["c"][0][0]
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
    # Found by the review of the pushed head. A tab after the marker reaches the next tab
    # stop, so the item's text starts at column 4, and a paragraph indented three is not in
    # it. A Word list pasted as plain text is written `1.<tab>`.
    "a count under a paragraph short of a tabbed item": (
        "1.\tFirst\n\n   Of the rest, the count was\n412. Of these\n"
    ),
    "a count under a paragraph short of a tabbed bullet": (
        "-\tFirst\n\n  Of the rest, the count was\n412. Of these\n"
    ),
    "a count under a paragraph short of a tabbed letter": (
        "a.\tFirst\n\n   Of the rest, the count was\n412. Of these\n"
    ),
    "a count under a paragraph indented to a tabbed item": (
        "1.\tFirst\n\n    Of the rest, the count was\n412. Of these\n"
    ),
    # A thematic break under an item is a rule, not an item, and ends the list.
    "a count under a thematic break after an item": (
        "1. First\n* * *\n\n  The count was\n412. Of these\n"
    ),
    # A definition indented to the item's text is a definition list inside the item.
    "a numbered line past a fence under an indented definition": (
        "- An item\n  : a definition\n~~~\nx\n~~~\n2. Second\n"
    ),
    # Pandoc numbers a list with ASCII digits only. Full-width ones are prose.
    "a full-width count at a block start": (
        "Intro.\n\n" + "".join(map(chr, (0xFF14, 0xFF11, 0xFF12))) + ". reports\n"
    ),
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


# ---------------------------------------------------------------- paragraph identifiers

#: Every block construct pandoc's markdown reader distinguishes, and prose openings that
#: look like one and are not. `tag` may mark a paragraph and nothing else.
TAGGING = {
    "prose": "Just prose, with a figure of 3.84.\n",
    "prose opening with emphasis": "*Emphasis* opens this.\n",
    "prose opening with a plus sign": "+/- two units either way.\n",
    "prose opening with a negative number": "-5 is below zero.\n",
    "prose opening with a decimal": "1.5 mg was given.\n",
    "prose opening with an initial": "C. difficile was isolated.\n",
    "prose opening with a capital roman one": "I. first, in one sense.\n",
    "prose opening with i.e.": "i.e. this one.\n",
    "prose opening with a citation": "[@k] reported this.\n",
    "prose opening with an in-text citation": "@k reported this.\n",
    "prose opening with a quotation mark": '"Quoted" words open this.\n',
    "prose opening with inline html": "<span>x</span> and <sup>a</sup> text.\n",
    "prose opening with an autolink": "<https://example.org> is a link.\n",
    "prose opening with a less-than": "<0.001 was the smallest value.\n",
    "prose with a hard line break": "line one  \nline two\n",
    "prose with an inline footnote": "Text^[a note] here.\n",
    "prose with display math": "The model:\n$$y = x$$\n",
    "a line starting with a dash does not end a paragraph": "text\n- item\n",
    "a line starting with a number does not end a paragraph": "text\n1. item\n",
    "a line starting with > does not end a paragraph": "text\n> quote\n",
    "a three-line paragraph ending in a colon line": "one\ntwo\n: three\n",
    "an image with text is not a figure": "![a](x.png) and text.\n",
    "bullet list": "- item one\n- item two\n",
    "bullet list with stars": "* item one\n* item two\n",
    "bullet list with pluses": "+ item one\n+ item two\n",
    "bullet list after a tab": "-\titem\n",
    "loose bullet list": "- item one\n\n- item two\n",
    "nested list": "- a\n    - b\n- c\n",
    "list item continued at two spaces": "- item\n\n  continuation\n",
    "list item continued at four spaces": "- item\n\n    continuation\n",
    "numbered list": "1. first\n2. second\n",
    "numbered list with parentheses": "1) first\n2) second\n",
    "numbered list in parentheses": "(1) first\n(2) second\n",
    "lettered list": "a. first\nb. second\n",
    "capital letters with two spaces": "A.  first\nB.  second\n",
    "capital letter with a parenthesis": "C) first\n",
    "roman numerals": "i. first\nii. second\n",
    "capital roman numerals": "II. first\nIII. second\n",
    "example list": "(@) first\n(@good) second\n",
    "a year is a list marker to pandoc": "2020. was a year\n",
    "block quote": "> quoted\n> more\n",
    "block quote, lazy": "> quoted\nlazy\n",
    "block quotes, loose": "> a\n\n> b\n",
    "line block": "| line one\n| line two\n",
    "pipe table": "| a | b |\n|---|---|\n| 1 | 2 |\n",
    "pipe table without edges": "a | b\n--|--\n1 | 2\n",
    "simple table": "  a     b\n ---   ---\n  1     2\n",
    "grid table": "+---+---+\n| a | b |\n+===+===+\n| 1 | 2 |\n+---+---+\n",
    "multiline table": "-------------\n a     b\n------ ------\n 1     2\n-------------\n",
    "table with a caption above": "Table: Cap\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    "table with a caption below": "| a | b |\n|---|---|\n| 1 | 2 |\n\n: Cap\n",
    "definition list": "Term\n: definition\n",
    "definition list with tildes": "Term\n~ definition\n",
    "definition list, loose": "Term\n\n:   definition\n",
    "setext heading": "Title\n=====\n",
    "setext heading, short underline": "Title\n--\n",
    "thematic break": "---\n",
    "thematic break with stars": "* * *\n",
    "thematic break with underscores": "___\n",
    "yaml block mid-document": "---\nkey: v\n---\n",
    "footnote definition": "Text[^1].\n\n[^1]: A footnote.\n",
    "link definition": "[a link][r]\n\n[r]: https://example.org\n",
    "figure": "![A figure](fig.png)\n",
    "figure with attributes": "![Cap [@k]](f.png){width=50%}\n",
    "indented code": "    code line\n    more\n",
    "fenced code with a blank line": f"{FENCE}\ncode\n\nmore code\n{FENCE}\n",
    "paragraph interrupted by a fence": f"text\n{FENCE}\ncode\n{FENCE}\n",
    "fenced div": "::: note\n\nInner paragraph.\n\n:::\n",
    "html block": "<div>\nhello\n</div>\n",
    "html block around markdown": "<div>\n\nInner paragraph.\n\n</div>\n",
    "html block opened by a tag pandoc treats as block": "<del>x</del> text\n",
    "paragraph interrupted by an html block": "text\n<div>\nx\n</div>\n",
    "html comment": "<!-- a note -->\n",
    "html comment across a blank line": "Before.\n\n<!--\nA note.\n\nMore of it.\n-->\n\nAfter.\n",
    "comment opened inside a paragraph": "text <!-- note\n\nmore -->\n\nafter\n",
    "raw openxml": f"{FENCE}{{=openxml}}\n<w:p/>\n{FENCE}\n",
    # Found by review after the first version of the fix, each by running pandoc.
    "fenced div closed without a blank line": (
        "::: {.note}\n\nInner paragraph here.\n:::\n\nAfter the note.\n"
    ),
    "nested fenced divs closed without a blank line": "::: a\n::: b\n\nInner.\n:::\n:::\n",
    "nested list straight after a continuation": (
        "- Reports were deduplicated.\n\n  Duplicates were matched on case identifier:\n"
        "  - by age\n  - by sex\n- Drugs were mapped.\n"
    ),
    "next item after a lazy continuation": "- a\n\n  cont\nlazy\n- b\n",
    "numbered item after a continuation": "1. a\n\n   cont\n3. three\n",
    "figure with brackets two deep": "![Caption^[Source: [@k].]](f.png)\n",
    "figure with a parenthesis in its path": "![A](fig(1).png)\n",
    "figure with a title": '![A](fig.png "Figure (a)")\n',
    "page break": "\\newpage\n",
    "page break then prose": "\\newpage\ntext after\n",
    "latex environment across a blank line": (
        "\\begin{figure}\nx\n\nmiddle\n\n\\end{figure}\n\nAfter.\n"
    ),
    "pre across a blank line": "<pre>\ncode\n\nmore\n</pre>\n\nAfter.\n",
    "a comment opened in the block where another closes": (
        "Before.\n\n<!-- one\n\nmore --> text <!-- two\n\ninside two\n\n-->\n\nAfter.\n"
    ),
    "latex environment opened after a paragraph's first line": (
        "Results are shown below.\n\\begin{table}\nrow one\n\nrow two\n\\end{table}\n\n"
        "After the table.\n"
    ),
    "latex environment opened mid-line": "text \\begin{x}\nrow\n\nrow two\n\\end{x}\n\nAfter.\n",
    "latex environment closed inside a paragraph": (
        "text \\begin{x}\nrow one\n\\end{x} more text\n\nAfter.\n"
    ),
    "nested latex environments of one name": (
        "\\begin{itemize}\n\\begin{itemize}\na\n\\end{itemize}\n\nb\n\n\\end{itemize}\n\n"
        "After.\n"
    ),
    "pre on a paragraph's second line": "text\n<pre>\ncode\n\nmore\n</pre>\n\nAfter.\n",
    "pre indented": "Before.\n\n  <pre>\na\n\nb\n\nc\n</pre>\n\nAfter.\n",
    "a closing tag that only starts like the right one": (
        "<pre>\ncode\n</preamble>\n\nmore\n</pre>\n\nAfter.\n"
    ),
    "a latex environment opened where a comment closes": (
        "<!-- one\n\nmore --> \\begin{x}\n\nrow\n\n\\end{x}\n\nAfter.\n"
    ),
    # Found by the review standing in for CodeRabbit on the PR, the first two only in the .docx.
    "display math inside a paragraph": (
        "The fitted model is\n$$\ny = a + bx\n$$\nwhere b is the slope.\n"
    ),
    "display math within a sentence": "The model: $$y = x$$ inline.\n",
    "a block html tag mid-line": (
        "The signal was stronger in women. <div>See the note below.</div> It was weaker.\n"
    ),
    "a paragraph tag mid-line": "text <p>x</p> more\n",
    "a rule tag mid-line": "text <hr> more\n",
    "tags pandoc keeps inline mid-line": "text <del>x</del> and <style>y</style> more\n",
    "a less-than before a word": "Values <LOQ were imputed as half the limit.\n",
    "latex environment written with a space": (
        "Results are shown below.\n\\begin {table}\nrow one\n\\end{table}\n\nAfter.\n"
    ),
    "latex environment closed with a space": (
        "Results are shown below.\n\\begin{table}\nrow one\n\\end {table}\n\nAfter.\n"
    ),
    "html block inside a list item's continuation": (
        "- item\n\n  para\n    <div>\n    x\n    </div>\n"
    ),
    "pre opened mid-line": "text <pre>code\n\nmore</pre>\n\nAfter.\n",
    "raw tex argument across a blank line": (
        "The signal was confirmed \\footnote{In the sensitivity analysis.\n\n"
        "And in the restricted cohort.} in both periods.\n\nAfter.\n"
    ),
    "a line holding only a non-breaking space": "Para one.\n \nPara two.\n\nAfter.\n",
    "a line holding only an ideographic space": "Para one.\n　\nPara two.\n\nAfter.\n",
    "a line holding only a form feed": "Para one.\n\f\nPara two.\n\nAfter.\n",
    "a definition inside a list item's continuation": "- a\n\n  para\n    : def\n",
    "balanced braces in prose": "The set {a, b} was used, and [a span]{.note} too.\n",
    "multiline table with three rows": (
        "Before.\n\n"
        "---------- -----------------------\n Drug      Signal\n"
        "---------- -----------------------\nWarfarin   Bleeding, strongest\n"
        "           in older patients.\n\nApixaban   Bleeding, weaker\n"
        "           than warfarin.\n\nHeparin    Thrombocytopenia.\n"
        "---------- -----------------------\n\nAfter.\n"
    ),
    "yaml block with a blank line, closed by dots": (
        "Intro.\n\n---\ntitle: x\nabstract: |\n  a\n\n  b\n...\n\nAfter.\n"
    ),
    "a rule between paragraphs": "Before.\n\n---\n\nAfter.\n",
    "multiline table with its caption straight under it": (
        "Before.\n\n"
        "---------- -----------------------\n Drug      Signal\n"
        "---------- -----------------------\nWarfarin   Bleeding, strongest\n"
        "           in older patients.\n\nApixaban   Bleeding, weaker\n"
        "           than warfarin.\n\nHeparin    Thrombocytopenia.\n"
        "---------- -----------------------\nTable: Signals by drug.\n\nAfter.\n"
    ),
    "multiline table with a colon caption straight under it": (
        "Before.\n\n"
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    Thrombocytopenia\n---------- ----------\n"
        ": Signals by drug.\n\nAfter.\n"
    ),
    "multiline table whose first column is two dashes wide": (
        "Before.\n\n-- ---------- ----------\n#  Drug       Signal\n-- ---------- ----------\n"
        "1  Warfarin   Bleeding\n\n2  Apixaban   Bleeding\n\n3  Heparin    HIT\n"
        "-- ---------- ----------\n\nAfter.\n"
    ),
    "a rule over text with a line of dots later": (
        "Before.\n\n---\nText.\n\nP1.\n...\n\nP2.\n\nMethods\n-------\n\nP3.\n"
    ),
    "yaml block closing in the middle of a block": (
        "Intro.\n\n---\ntitle: x\n\nsubtitle: y\n\nabstract: z\n---\nPara A right after.\n"
    ),
    "yaml block closing on dots in the middle of a block": (
        "Intro.\n\n---\ntitle: x\n\nsubtitle: y\n\nabstract: z\n...\nPara A right after.\n"
    ),
    "yaml that is not a mapping, which pandoc reads as prose": (
        "Intro.\n\n---\n# Afterword\n\nThe signal was strong.\n\nIt held, and then\n...\n\n"
        "After.\n"
    ),
    "yaml with an impossible date": (
        "Intro.\n\n---\ndate: 2026-02-30\n\nnote: revised\n...\n\nAfter.\n"
    ),
    "a yaml example inside a comment before real yaml": (
        "Intro.\n\n<!--\n---\nk: v\n\nj: w\n-->\n\n---\ntitle: x\n\nsubtitle: y\n...\n\n"
        "After.\n"
    ),
    "a yaml example inside a code fence before real yaml": (
        f"Intro.\n\n{FENCE}\n\n---\nk: v\n\nj: w\n{FENCE}\n\n---\ntitle: x\n\nsubtitle: y\n...\n\n"
        "After.\n"
    ),
    "yaml pandoc gives up on, stopping on a later yaml opener": (
        "Intro.\n\n---\nText under.\n\n------\n\nMore.\n\n---\ntitle: x\n\nsubtitle: y\n...\n\n"
        "After.\n"
    ),
    "yaml pandoc gives up on, over a setext heading, before a later yaml opener": (
        "Intro.\n\n---\nText under.\n\nResults\n-------\n\nMore.\n\n---\ntitle: x\n\n"
        "subtitle: y\n...\n\nAfter.\n"
    ),
    "yaml pandoc gives up on, stopping on a later table": (
        "Intro.\n\n---\nText under.\n\n------\n\nMore.\n\n---\n Drug   Signal\n------ ------\n"
        "First  1.2\n\nSecond 2.3\n---------------\n\nAfter.\n"
    ),
    "yaml given up on whose stop of dots opens a block": (
        "Intro.\n\n---\n- item\n\n...\nMore.\n\nAfter.\n\n---\ntitle: x\n...\n\nEnd.\n"
    ),
    "yaml holding only null, whose stop of dots opens a block": (
        "Intro.\n\n---\nnull\n\n...\nMore.\n\nEnd.\n"
    ),
    "a multiline table with a paragraph straight under its closing rule": (
        "Intro.\n\n---------- ----------\n Drug      Signal\n---------- ----------\n"
        "Warfarin   Bleeding\n\nApixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n"
        "The signals are listed above.\n"
    ),
    "yaml after a blank first line": "\n---\ntitle: x\n\nabstract: y\n...\n\nIntro.\n",
    # Pandoc tries a headed multiline table first: a header down to the first line of
    # dashes, then rows to the next one, when text follows the first straight away.
    "a rule over text, then a headed table's underline with rows under it": (
        "Intro.\n\n---\nText under.\n\nPara A.\n\n  Drug     Signal\n--------  --------\n"
        "Warfarin  Bleeding\n\nAfter the table, a long paragraph.\n\nMethods\n-------\n\nEnd.\n"
    ),
    "a headless table whose closing rule has prose under it, then a setext heading": (
        "Intro.\n\n---------- ----------\nWarfarin   Bleeding\n\nApixaban   Bleeding\n"
        "---------- ----------\nThe signals are listed above.\n\nPara X.\n\nMethods\n-------\n\n"
        "End.\n"
    ),
    "yaml given up on, stopping on a yaml opener, then a later rule": (
        "Intro.\n\n---\nText under.\n\nPara A.\n\n---\ntitle: x\n...\n\nPara C.\n\n-----\n\n"
        "End.\n"
    ),
    "a setext underline with text straight under it, then a later rule": (
        "Intro.\n\nHeading\n---\nText straight under.\n\nPara B.\n\n-----\n\nEnd.\n"
    ),
    "a one-block headless table with its caption straight under, then a setext heading": (
        "Intro.\n\n----------  ----------\nWarfarin    Bleeding\nApixaban    Bleeding\n"
        "----------  ----------\nTable: Signals of interest.\n\nWe found two signals in total.\n\n"
        "Both concern bleeding.\n\nDiscussion\n----------\n"
    ),
    "a table whose first column is one dash wide": (
        "Before.\n\n- ---------- ----------\n#  Drug       Signal\n- ---------- ----------\n"
        "1  Warfarin   Bleeding\n\n2  Apixaban   Bleeding\n\n3  Heparin    HIT\n"
        "- ---------- ----------\n\nAfter.\n"
    ),
    "a headless table whose first column is one dash wide": (
        "Before.\n\n-   ----------  ----------\na   Warfarin    Bleeding\n\n"
        "b   Apixaban    Bleeding\n\nc   Heparin     HIT\n-   ----------  ----------\n\nAfter.\n"
    ),
    "a row of dashes above the bottom rule, then a caption": (
        "Intro.\n\n--------  --------  --------\nWarfarin  Bleeding  12\n--        --        --\n"
        "--------  --------  --------\nTable: Signals.\n\nWe found one.\n\n"
        "Discussion\n----------\n\nEnd.\n"
    ),
    "a table opened by two dashes, then a setext heading": (
        "Intro.\n\n--\nA note.\n\nPara A.\n\nMethods\n-------\n\nEnd.\n"
    ),
    "a rule with a blank line under it, then a headed table": (
        "Intro.\n\n---\n\nPara A.\n\n---------- ----------\n Drug      Signal\n"
        "---------- ----------\nWarfarin   Bleeding\n\nApixaban   Bleeding\n\n"
        "Heparin    HIT\n---------- ----------\n\nAfter.\n"
    ),
    "a rule with a blank line under it, then yaml with a blank line": (
        "Intro.\n\n---\n\nPara A.\n\n---\ntitle: x\n\nsubtitle: y\n...\n\nAfter.\n"
    ),
    "a table, a rule straight under it, then a headed table": (
        "Intro.\n\n----------  ----------\nWarfarin    Bleeding\n----------  ----------\n"
        "----------\n\nPara A.\n\n---------- ----------\n Drug      Signal\n"
        "---------- ----------\nWarfarin   Bleeding\n\nApixaban   Bleeding\n\n"
        "Heparin    HIT\n---------- ----------\n\nAfter.\n"
    ),
    "a table, a line of dashes that opens nothing, then text": (
        "Intro.\n\n----------  ----------\nWarfarin    Bleeding\n\nApixaban    Bleeding\n\n"
        "Heparin     HIT\n----------  ----------\n----------\nText after.\n\nAfter.\n"
    ),
    **{
        f"a {kind} table straight under {name}": (
            f"Intro.\n\n{above}\n{table}{closer}\n\nAfter.\n"
        )
        for kind, table in (
            (
                "headless",
                "----------  ----------\nWarfarin    Bleeding\n\nApixaban    Bleeding\n\n"
                "Heparin     HIT\n----------  ----------",
            ),
            (
                "headed",
                "---------- ----------\n Drug      Signal\n---------- ----------\n"
                "Warfarin   Bleeding\n\nApixaban   Bleeding\n\nHeparin    HIT\n"
                "---------- ----------",
            ),
        )
        for name, above, closer in (
            ("a div fence", "::: {#tbl-a}", "\n:::"),
            ("an ATX heading", "## Table 1", ""),
            ("an HTML comment", "<!-- the signals -->", ""),
            ("a div tag", '<div class="x">', "\n</div>"),
            ("a setext heading", "Table 1\n=======", ""),
            ("a setext heading underlined with dashes", "Table 1\n-------", ""),
            ("a code block", "```\ncode\n```", ""),
            ("a yaml block", "---\ntitle: x\n---", ""),
            ("a pipe table", "| a | b |\n|---|---|\n| 1 | 2 |", ""),
            ("a yaml block closed by dots", "---\ntitle: x\n...", ""),
            ("a comment's closing line", "<!-- a\nnote -->", ""),
            ("the end of an environment", "\\begin{landscape}\n\\end{landscape}", ""),
            ("a grid table", "+---+---+\n| a | b |\n+---+---+", ""),
            ("a pipe table without outer pipes", "a | b\n--|--\n1 | 2", ""),
            ("a heading of seven hashes", "####### x", ""),
        )
    },
    **{
        f"a one-column table straight under {name}": (
            f"Intro.\n\n{above}\n----------\nWarfarin\n\nApixaban\n\nHeparin\n"
            f"----------{closer}\n\nAfter.\n"
        )
        for name, above, closer in (
            ("a div tag", '<div class="x">', "\n</div>"),
            ("a comment's closing line", "<!-- a\nnote -->", ""),
            ("the end of an environment", "\\begin{landscape}\n\\end{landscape}", ""),
            ("a pipe table without outer pipes", "a | b\n--|--\n1 | 2", ""),
            ("a code block", "```\ncode\n```", ""),
        )
    },
    "a table opening in the block where another ends, under a heading": (
        "Intro.\n\n---------- ----------\n Drug      Signal\n---------- ----------\n"
        "Warfarin   Bleeding\n\nApixaban   Bleeding\n---------- ----------\n## Table 2\n"
        "----------  ----------\nRivaroxaban Bleeding\n\nEdoxaban    Bleeding\n\n"
        "Dabigatran  Bleeding\n----------  ----------\n\nAfter.\n"
    ),
    "two table divs back to back": (
        "Intro.\n\n::: {#tbl-a}\n----------  ----------\nWarfarin    Bleeding\n\n"
        "Apixaban    Bleeding\n----------  ----------\n:::\n::: {#tbl-b}\n"
        "----------  ----------\nHeparin     HIT\n\nEdoxaban    Bleeding\n\n"
        "Dabigatran  Bleeding\n----------  ----------\n:::\n\nAfter.\n"
    ),
    "a table opening in the block where another ends, under a comment": (
        "Intro.\n\n---------- ----------\n Drug      Signal\n---------- ----------\n"
        "Warfarin   Bleeding\n\nApixaban   Bleeding\n---------- ----------\n<!-- next -->\n"
        "----------  ----------\nHeparin     HIT\n\nEdoxaban    Bleeding\n\n"
        "Dabigatran  Bleeding\n----------  ----------\n\nAfter.\n"
    ),
    "a table straight under yaml that holds a blank line": (
        "Intro.\n\n---\ntitle: x\n\nsubtitle: y\n---\n----------  ----------\n"
        "Warfarin    Bleeding\n\nApixaban    Bleeding\n\nHeparin     HIT\n"
        "----------  ----------\n\nAfter.\n"
    ),
    **{
        f"a span taken for a table, ending in a headed table, after {name}": (
            f"Intro.\n\n{before}\n\nTable: Signals.\n\n---------- ----------\n"
            " Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
            "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n\nAfter.\n"
        )
        for name, before in (
            ("a line block", "|x| was large.\n----------  ----------\nText."),
            ("a line of dots", "Text\n...\n----------  ----------\nMore."),
            (
                "a trailing comment",
                "Results <!-- to check -->\n-----------------------------\nWe found three signals.",
            ),
            ("an arrow", "The flow was A -->\n----------  ----------\nx  y"),
            ("two plus signs", "Text\n++\n----------\nMore."),
        )
    },
    **{
        f"a span taken for a table, ending in a table under code, after {name}": (
            f"Intro.\n\n{before}\n\n```r\nx <- 1\n\ny <- 2\n```\n---------- ----------\n"
            " Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
            "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n\nAfter.\n"
        )
        for name, before in (
            ("a line block", "|x| was large.\n----------  ----------\nText."),
            ("a line of dots", "Text\n...\n----------  ----------\nMore."),
            ("an arrow", "The flow was A -->\n----------  ----------\nx  y"),
        )
    },
    # Under these pandoc opens no table, and the rows are paragraphs.
    **{
        f"a line of dashes straight under {name}": (
            f"Intro.\n\n{above}\n{rule}\nWarfarin    Bleeding\n\n"
            f"Apixaban    Bleeding\n\nHeparin     HIT\n{rule}\n\nAfter.\n"
        )
        for name, above, rule in (
            ("prose", "Some text.", "----------  ----------"),
            ("prose holding a pipe", "P(A|B) was high.", "----------  ----------"),
            ("a list item", "- item", "----------  ----------"),
            ("a block quote", "> quoted", "----------  ----------"),
            ("a definition", "Term\n:   definition", "----------  ----------"),
            ("a caption", "Table: Signals.", "----------  ----------"),
            ("a TeX command", "\\newpage", "----------  ----------"),
            ("an image", "![Figure](f.png)", "----------  ----------"),
            ("a reference definition", "[a]: https://example.org", "----------  ----------"),
            ("a heading, as one run", "## Title", "----------"),
            ("a one-line comment, as one run", "<!-- a note -->", "----------"),
        )
    },
    "a top rule over a line holding only a no-break space": (
        "Intro.\n\n----------  ----------\n\N{NO-BREAK SPACE}\n----------  ----------\n"
        "Warfarin    Bleeding\n\nApixaban    Bleeding\n\nHeparin     HIT\n"
        "----------  ----------\n\nAfter.\n"
    ),
    "a header underline over a line holding only a no-break space": (
        "Intro.\n\n-------------------\n Drug     Signal\n--------  --------\n \n"
        "Warfarin  Bleeding\n\nApixaban  Bleeding\n\nHeparin   HIT\n-------------------\n\n"
        "After.\n"
    ),
    "a rule over text, then a line of two dashes": (
        "Intro.\n\n---\nText under.\n\nPara A.\n\n--\n\nPara B.\n"
    ),
    "yaml longer than four thousand characters": (
        "Intro.\n\n---\ntitle: x\nabstract: |\n  "
        + "\n\n  ".join(["word " * 300] * 4)
        + "\n...\n\nAfter.\n"
    ),
    "yaml closed in its own block, then prose and a setext heading": (
        "Intro.\n\n---\ntitle: x\n...\n\nPara one.\n\nPara two.\n\nMethods\n-------\n\nP3.\n"
    ),
    "a table whose header has a colon, with a row of dots": (
        "Before.\n\n---\nRatio (a:b)    Value\n-------------- -----\nFirst          1.2\n\n"
        "Second         2.3\n...\n\nThird          3.4\n\nFourth         4.5\n"
        "--------------------\n\nAfter.\n"
    ),
    "a table whose header starts with a hash, with a row of dots": (
        "Before.\n\n---\n# of reports   Value\n-------------- -----\nFirst          1.2\n\n"
        "Second         2.3\n...\n\nThird          3.4\n\nFourth         4.5\n"
        "--------------------\n\nAfter.\n"
    ),
    "yaml block opening on a comment": (
        "Before.\n\n---\n# a comment\nkey: value\n\nother: value\n...\n\nAfter.\n"
    ),
    "yaml block opening on a quoted key": (
        'Before.\n\n---\n"key": value\n\nother: value\n...\n\nAfter.\n'
    ),
    "yaml block whose first key is table": (
        "Before.\n\n---\ntable: x\nabstract: |\n  a\n\n  b\n...\n\nAfter.\n"
    ),
    "multiline table with a row reading dots": (
        "Before.\n\n"
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n"
        "            ...\n\nApixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n\n"
        "After.\n"
    ),
    "multiline table with a caption and no space after the colon": (
        "Before.\n\n"
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n\n"
        "Apixaban   Bleeding\n\nHeparin    HIT\n---------- ----------\n:Caption.\n\nAfter.\n"
    ),
    "one-row table with its caption straight under it, then prose": (
        "---------- ----------\n Drug      Signal\n---------- ----------\nWarfarin   Bleeding\n"
        "---------- ----------\nTable: One row.\n\nP1.\n\nP2.\n\nMethods\n-------\n\nP3.\n"
    ),
    "a comment opened in the block where a fence closes": (
        f"{FENCE}\ncode\n\nmore\n{FENCE}\ntext <!-- two\n\ninside two\n\n-->\n\nAfter.\n"
    ),
    "example list without parentheses": "@good. second\n",
    "example list closed by a parenthesis": "@k) reported\n",
    "a capital and a period alone": "A.\n",
    "a capital and a period, then a line": "C.\nmore text\n",
    "a word made of roman letters": "dim. lights were used.\n",
    "a valid roman numeral": "mix. up\n",
}


def pandoc_ast(markdown: str) -> list:
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout)["blocks"]


def _is_marker(node) -> bool:
    return (
        isinstance(node, dict)
        and node.get("t") == "Span"
        and node["c"][0][0].startswith("mg-p-")
        and node["c"][1] == []
    )


def _unmarked(node):
    """The AST with the identifiers' empty spans taken out."""
    if isinstance(node, list):
        return [_unmarked(item) for item in node if not _is_marker(item)]
    if isinstance(node, dict):
        return {key: _unmarked(value) for key, value in node.items()}
    return node


def _holders(node, found: dict) -> None:
    """Each identifier, mapped to the run of inlines that carries it."""
    if isinstance(node, list):
        for item in node:
            if _is_marker(item):
                found[item["c"][0][0]] = node
            _holders(item, found)
    elif isinstance(node, dict):
        for value in node.values():
            _holders(value, found)


def pandoc_docx(markdown: str, output: Path) -> Path:
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-o", str(output)],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert finished.returncode == 0, finished.stderr
    return output


def word_paragraphs(document: Path) -> list[str]:
    """The text of every block in the body, read by the reader `import` uses. A table is
    one block, and reads as the marker `<table>` so that it cannot pass for a paragraph."""
    from manuscript_guard.roundtrip import read_blocks

    return ["<table>" if block.table else block.text for block in read_blocks(document)]


@pytest.mark.parametrize("name", sorted(TAGGING))
def test_an_identifier_marks_a_whole_paragraph_and_changes_nothing(
    name: str, tmp_path: Path
) -> None:
    """Two things, both about what pandoc makes of the marked source.

    The marker must change nothing but itself. In front of a list it did: pandoc read
    `[]{#mg-p-...}- item one` as a paragraph, and the document printed the list as one
    run-on line with its dashes in it.

    And the Word paragraph carrying it must be the whole of the block it names, because
    `import` splices that paragraph's text over the block. A marker in a pipe table's first
    cell changes nothing pandoc reads, and a co-author's edit to that cell would have
    replaced the table. Asked of both pandoc's reader and the .docx, because each misses
    what the other sees: display math is inside one paragraph to the reader and gets a
    paragraph of its own from the Word writer, while a LaTeX environment after the first
    line is a separate block to the reader and simply absent from the .docx.
    """
    from manuscript_guard.roundtrip import paragraph_text, tag

    markdown = TAGGING[name]
    tagged = tag(markdown, "main.md")
    ast = pandoc_ast(tagged)
    assert _unmarked(ast) == pandoc_ast(markdown), f"{name}: the marker changed {tagged!r}"

    held: dict = {}
    _holders(ast, held)
    written = re.findall(r"\[\]\{#(mg-p-[^}]+)\}", tagged)
    assert set(held) == set(written), f"{name}: a marker reached no paragraph in {tagged!r}"
    if not written:
        return

    returned = paragraph_text(pandoc_docx(tagged, tmp_path / "tagged.docx"))
    pieces = re.split(r"\n\s*\n", tagged)
    # A footnote or a link resolves against definitions anywhere in the document, so a
    # paragraph read on its own is read with them. Not with a line of dashes under one: over
    # it the definition is a simple table's header, which would come back as a table.
    definitions = "\n\n".join(
        re.split(r"\n(?= {0,3}-+(?:[ \t]+-+)*[ \t]*(?:\n|$))", p)[0]
        for p in pieces
        if re.match(r" {0,3}\[[^\]]+\]:", p)
    )
    for index, piece in enumerate(pieces):
        marker = re.search(r"\[\]\{#(mg-p-[^}]+)\}", piece)
        if marker is None:
            continue
        source = piece.replace(marker.group(0), "", 1) + "\n\n" + definitions
        read = pandoc_ast(source)
        assert [block["t"] for block in read] in (["Para"], ["Plain"]), (
            f"{name}: {piece!r} is marked and pandoc reads it as {[b['t'] for b in read]}"
        )
        assert _unmarked(held[marker.group(1)]) == read[0]["c"], (
            f"{name}: the marked paragraph holds only part of {piece!r}"
        )
        written_out = word_paragraphs(pandoc_docx(source, tmp_path / f"alone-{index}.docx"))
        assert len(written_out) == 1, (
            f"{name}: {piece!r} is marked and is {len(written_out)} paragraphs in Word"
        )
        assert returned.get(marker.group(1)) == written_out[0], (
            f"{name}: the marked Word paragraph holds only part of {piece!r}"
        )
