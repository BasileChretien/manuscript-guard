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


# ---------------------------------------------------------------- linear time


def _unmatched_runs(size: int) -> str:
    """One paragraph of about `size` characters of backtick runs, each of a length no later
    run shares, so none closes and every one gives up a backtick at a time, as pandoc does."""
    count = int((2 * size) ** 0.5)
    return " ".join("`" * length + "x" for length in range(1, count + 1)) + "\n"


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("unmatched backtick runs", _unmatched_runs),
        ("comment openers with no closer", lambda size: "<!-- " * (size // 5) + "\n"),
        ("code between unclosed comments", lambda size: "`a` <!-- " * (size // 9) + "\n"),
    ],
)
def test_the_comment_scanner_is_linear(name: str, build) -> None:
    """`<!--.*?-->` read to the end of the text for every opener that never closed: 5,000
    of them kept `mask` busy for over two minutes. Four times the input must not take much
    more than four times as long."""
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
