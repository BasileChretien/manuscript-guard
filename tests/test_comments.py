"""Where the HTML comments are, and where a code span makes `<!--` mere text.

Pandoc prints `` `<!--` `` as code. The regex this replaced took it for the start of a
comment and hid everything up to the next `-->` from G2, the audit, the heading scan and
the binding parser, so a paper that wrote both markers in backticks had the prose between
them checked by nothing. Every case below was read with pandoc 3.9.0.2 (`-f markdown -t
native`); `test_pandoc_agreement.py` asks pandoc directly wherever it is installed.
"""

from __future__ import annotations

import time

import pytest

from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.sections import headings
from manuscript_guard.text.tokens import find_atoms

BACKSLASH = "\\"
FENCE = "`" * 3


def atoms_of(text: str) -> list[str]:
    return [a.text.rstrip(".,") for a in find_atoms(text, mask(text))]


PRINTED = {
    "a comment opened in code": (
        "We stripped `<!--` markers. The ROR was 9.99.\n\nNote: `-->` closes.\n"
    ),
    "double-backtick code": "Strip ``<!--`` first. The ROR was 9.99, and ``-->`` last.\n",
    "code across a line break": "a `<!--\nb` 9.99 -->\n",
    "a shorter run inside the code": "a ``x`<!--`` 9.99 -->\n",
    "a longer opener gives up one backtick at a time": "a ```<!--`` 9.99 -->\n",
    "an escaped backtick opens nothing": f"a {BACKSLASH}`x` <!-- 9.99 --> `y`\n",
    "an escaped backslash leaves the code alone": f"a {BACKSLASH * 2}`<!--` 9.99 `-->`\n",
    "an escaped angle bracket opens nothing": f"a {BACKSLASH}<!-- 9.99 --> b\n",
    "a comment ends at its first -->, even in backticks": "<!-- 1.23 `-->` 9.99\n",
    "an unclosed comment": "`x` <!-- 9.99\n",
    "<!--> opens nothing": "a <!--> 9.99 --> b\n",
    "<!---> opens nothing": "a <!---> 9.99 --> b\n",
    # Pandoc's HTML reader ends the comment at `-- >`, finds no `-->`, and prints it all.
    "a comment cut short by -- >": "a <!-- was 9.99 -- > 5 --> b\n",
    "a comment cut short by --, a newline and >": (
        "<!-- Cut after review --\n> The pilot ROR was 9.99.\n-->\n"
    ),
    "a comment cut short by --!>": "a <!-- x --!> 9.99 --> b\n",
    "a comment opened in a listing": f"{FENCE}html\n<!-- a template\n{FENCE}\n\nROR 9.99. -->\n",
    "a comment closed in a listing": (
        f"<!-- draft\n{FENCE}r\nx <- 1 # -->\n{FENCE}\n\nThe ROR was 9.99. <!-- a -->\n"
    ),
    "a comment opened in the title": (
        "---\ntitle: Stripping <!-- markers\n---\n\nThe ROR was 9.99. <!-- note -->\n"
    ),
    "code opened in the title": (
        "---\ntitle: A stray `\n---\n\nStrip `<!--` first; 9.99; then `-->`.\n"
    ),
    # A fence interrupts a paragraph, but not a code span already open: the listing becomes
    # part of the span, and the `-->` in it closes no comment.
    "code across a fence line": f"Set `<!-- ROR 9.99\n{FENCE}\n-->\n{FENCE}\n` in the template.\n",
    "code across a listing": f"a `<!--\n{FENCE}\ncode\n{FENCE}\nb`\n\nThe ROR was 9.99. -->\n",
}


@pytest.mark.parametrize("name", sorted(PRINTED))
def test_a_number_pandoc_prints_is_read(name: str) -> None:
    assert "9.99" in atoms_of(PRINTED[name])


HIDDEN = {
    "a comment after code": "`x` <!-- 9.99 --> y\n",
    "backticks inside a comment": "<!-- `a` 9.99 `b` -->\n",
    "a stray backtick": "A stray ` then <!-- 9.99 --> hidden.\n",
    "code does not cross a blank line": "A `x\n\ny` <!-- 9.99 --> z\n",
    "code does not cross a CRLF blank line": "A `x\r\n \r\ny` <!-- 9.99 --> z\r\n",
    "an escaped backtick before a comment": f"a {BACKSLASH}`<!-- 9.99 --> b\n",
    "a comment across a blank line": "a <!-- x\n\n9.99 --> b\n",
    "a commented-out blockquote": "<!--\n> quoted 9.99\n-->\n\nafter\n",
    "a double dash inside a comment": "a <!-- x -- y 9.99 --> b\n",
    "a double dash before other text and >": "a <!-- x --x> 9.99 --> b\n",
    "a comment around a listing": f"<!--\n{FENCE}r\nx <- 1\n{FENCE}\n9.99 -->\n",
    # HTML's whitespace is not Python's: `--`, a no-break space, `>` does not end it.
    "a double dash, a no-break space and >": "a <!-- x -- > 9.99 --> b\n",
}


@pytest.mark.parametrize("name", sorted(HIDDEN))
def test_a_number_pandoc_drops_is_not_read(name: str) -> None:
    """The other direction: knowing about code must not stop a real comment being one."""
    assert "9.99" not in atoms_of(HIDDEN[name])


def test_a_heading_after_code_that_names_a_comment_is_a_heading() -> None:
    """The heading scan blanked `## Results` as part of the comment, so the Results
    paragraph sat under Methods and its `p < 0.05` read as the alpha chosen in advance."""
    text = (
        "## Methods\n\nWe strip `<!--` markers.\n\n## Results\n\n"
        "Significant (p < 0.05).\n\nThey end at `-->`.\n"
    )
    assert headings(text) == ["Methods", "Results"]


@pytest.mark.parametrize(
    "opening",
    [
        f"<!-- draft\n{FENCE}r\nx <- 1 # -->\n{FENCE}\n",
        '---\nnote: "<!-- legacy"\n---\n',
    ],
    ids=["closed in a listing", "opened in the front matter"],
)
def test_a_comment_that_pandoc_ends_early_hides_no_heading(opening: str) -> None:
    text = f"{opening}\n# Methods\n\nx\n\n# Results\n\ny <!-- z -->\n"
    assert headings(text) == ["Methods", "Results"]


def test_a_comment_after_a_fence_does_not_make_it_a_closer() -> None:
    """Comments were blanked before fences were looked for, so "```<!-- TODO -->" became a
    bare closing fence. It paired with the stray opener above and blanked `## Results`."""
    text = (
        f"## Methods\n\nWe used\n{FENCE}\n\n## Results\n\nThe ROR was 9.99.\n\n"
        f"{FENCE}<!-- TODO: listing -->\n"
    )
    assert headings(text) == ["Methods", "Results"]


def test_a_binding_after_a_comment_closed_in_a_listing_is_substituted() -> None:
    """The old regex read the raw text and ended this comment where pandoc does. Reading it
    with the fences already blanked ran it on to the next `-->`, over the binding."""
    text = f"<!-- draft\n{FENCE}r\nx <- 1 # -->\n{FENCE}\n\nn = {{{{results.n}}}}. <!-- a -->\n"
    assert [p.ref for p in parse(text)[0]] == ["results.n"]


def test_a_binding_after_code_that_names_a_comment_is_substituted() -> None:
    """Skipped as commented out, the binding reached the document as `{{results.n}}`."""
    text = "Strip `<!--` first; n = {{results.n}}; then `-->`.\n"
    assert [p.ref for p in parse(text)[0]] == ["results.n"]
    assert substitute(text, {"results.n": "413"}) == "Strip `<!--` first; n = 413; then `-->`.\n"


def test_a_comment_marker_in_a_listing_does_not_hide_the_bindings_after_it() -> None:
    """The binding parser read the raw text, fences and all, so an HTML listing that opens
    a comment hid the bindings in the prose after it up to the next `-->`."""
    text = f"{FENCE}html\n<!-- a template\n{FENCE}\n\nThe cohort had {{{{results.n}}}}. -->\n"
    assert [p.ref for p in parse(text)[0]] == ["results.n"]


# ---------------------------------------------------------------- never more than before


def _old_rule(text: str) -> set[int]:
    """Every offset `<!--.*?-->` hid, with fenced blocks and the front matter's machinery
    blanked, on each side of the front matter: the rule `mask` applied before the scanner
    replaced the regexes."""
    import re

    from manuscript_guard.text.masking import _frontmatter_spans, fenced_blocks, front_matter_end

    blanked = list(text)
    for start, end in [*((f.start, f.end) for f in fenced_blocks(text)), *_frontmatter_spans(text)]:
        blanked[start:end] = "\x00" * (end - start)
    flat, head = "".join(blanked), front_matter_end(text)
    comment = re.compile(r"<!--.*?-->", re.DOTALL)
    hidden: set[int] = set()
    for match in [*comment.finditer(flat, 0, head), *comment.finditer(flat, head)]:
        hidden.update(range(match.start(), match.end()))
    return hidden


def test_the_scanner_hides_nothing_the_old_rule_did_not() -> None:
    """Hiding less than the regex is the point: `` `<!--` `` and an escaped `\\<!--` print.
    Hiding more is the dangerous direction, and the scanner's guesses about where pandoc
    ends a code span or opens a comment are not always pandoc's, so a comment is hidden only
    where the old rule hid it too."""
    import random

    from manuscript_guard.text.masking import html_comments

    # Whole lines, so that listings, list items and indented code blocks actually form.
    lines = [
        FENCE, f"{FENCE}html", "````", "~~~", "<!-- a", "-->", "x -->", "    <!-- b", "",
        "- item ```", "- `a", "> q `", "b`", "`c` d", "$a <!-- b$", "\\<!-- e", "9.99",
        "Prose with 9.99.", "<!-- f -->", "`<!--`", "---", "title: <!-- g",
        "author: <!-- h -->", "abstract: |", "  $x <!-- y$ 9.99", "  -->",
    ]
    rng = random.Random(20260925)
    for _ in range(4000):
        text = "\n".join(rng.choice(lines) for _ in range(rng.randint(1, 14))) + "\n"
        hidden = {i for start, end in html_comments(text) for i in range(start, end)}
        assert hidden <= _old_rule(text), repr(text)


# ---------------------------------------------------------------- linear time


def _unmatched_runs(size: int) -> str:
    """One paragraph of about `size` characters of backtick runs, each of a length no later
    run shares, so none closes and every one gives up a backtick at a time, as pandoc does."""
    count = int((2 * size) ** 0.5)
    return " ".join("`" * length + "x" for length in range(1, count + 1)) + " <!-- x\n"


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("one long backtick run", lambda size: "a " + "`" * size + " <!-- x\n"),
        ("unmatched backtick runs", _unmatched_runs),
        ("comment openers with no closer", lambda size: "<!-- " * (size // 5) + "\n"),
        ("code between unclosed comments", lambda size: "`a` <!-- " * (size // 9) + "\n"),
        ("comments cut short", lambda size: "<!-- -- > " * (size // 10) + "-->\n"),
        ("listings between openers", lambda size: "<!--\n```\nx\n```\n" * (size // 16)),
    ],
)
def test_the_comment_scanner_is_linear(name: str, build) -> None:
    """`<!--.*?-->` read to the end of the text for every opener that never closed: 5,000
    of them kept `mask` busy for over two minutes, and the first version of this scanner
    re-read a long backtick run once per backtick it gave up. Every input here holds a
    `<!--`, or the scanner returns before reading anything. Four times the input must not
    take much more than four times as long."""
    from manuscript_guard.text.comments import comment_spans

    def measure(size: int) -> float:
        text = build(size)
        started = time.perf_counter()
        comment_spans(text)
        return time.perf_counter() - started

    measure(5_000)  # warm the caches
    small = max(measure(20_000), 1e-3)
    large = measure(80_000)
    assert large / small < 12, f"{name}: 4x the input took {large / small:.1f}x the time"
