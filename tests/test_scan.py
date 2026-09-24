"""One pass for fences, code spans and comments, because each can swallow the others.

`fences.py` used to find every fence before anything else, and `comments.py` read the rest.
Neither saw what the other had swallowed. Every case here was read with pandoc 3.9.0.2
(`-f markdown -t native`); `test_pandoc_agreement.py` asks pandoc directly.
"""

from __future__ import annotations

import time

import pytest

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.text.fences import fenced_spans
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import count_words, headings, section_chain
from manuscript_guard.text.tokens import find_atoms

FENCE = "`" * 3
LONGER = "`" * 4
TILDE = "~" * 3


def atoms_of(text: str) -> list[str]:
    return [a.text.rstrip(".,") for a in find_atoms(text, mask(text))]


def listings(text: str) -> list[str]:
    return [text[f.body_start : f.body_end] for f in fenced_spans(text)]


# ---------------------------------------------------------------- what is a listing

LISTINGS = {
    # A fence line inside something that started first opens nothing.
    "swallowed by a code span": (f"Set `x\n{FENCE}\ny`.\n\nThe ROR was 9.99.\n\n{FENCE}\n", []),
    "swallowed by a comment": (
        f"<!--\n{FENCE}r\nold\n-->\n\nProse 9.99.\n\n{FENCE}r\nnew\n{FENCE}\n",
        ["new\n"],
    ),
    # And the fences pandoc finds once the code span has ended are still found.
    "found again after a code span": (
        f"Set `x\n{LONGER}\ny`\n{FENCE}\n<!--\n{LONGER}\n\nThe ROR was 9.99. -->\n",
        ["<!--\n"],
    ),
    # A backtick fence at the margin interrupts a paragraph; nothing else does.
    "backticks at the margin interrupt a paragraph": (
        f"The ROR\n{FENCE}\nwas 9.99.\n{FENCE}\n",
        ["was 9.99.\n"],
    ),
    "tildes do not": (f"The ROR\n{TILDE}\nwas 9.99.\n{TILDE}\n", []),
    "indented backticks do not": (f"The ROR\n  {FENCE}\nwas 9.99.\n  {FENCE}\n", []),
    "nor do tildes after a blockquote line": (f"> quote\n{TILDE}\nx 9.99\n{TILDE}\n", []),
    "nor after an inline comment": (f"Text <!-- x -->\n{TILDE}\nx 9.99\n{TILDE}\n", []),
    # Where no paragraph is open, tildes open a listing as ever.
    "tildes after a blank line": (f"The ROR\n\n{TILDE}\nx 9.99\n{TILDE}\n", ["x 9.99\n"]),
    "tildes after a heading": (f"# Head\n{TILDE}\nx 9.99\n{TILDE}\n", ["x 9.99\n"]),
    "tildes after a listing": (
        f"{FENCE}\na\n{FENCE}\n{TILDE}\nx 9.99\n{TILDE}\n",
        ["a\n", "x 9.99\n"],
    ),
    "tildes after a comment block": (f"<!--\nx\n-->\n{TILDE}\nx 9.99\n{TILDE}\n", ["x 9.99\n"]),
    "tildes after a list item": (f"- item\n{TILDE}\nx 9.99\n{TILDE}\n", ["x 9.99\n"]),
    "tildes after a table row": (
        f"| a | b |\n|---|---|\n| 1 | 2 |\n{TILDE}\nx\n{TILDE}\n",
        ["x\n"],
    ),
    "tildes after a rule": (f"***\n{TILDE}\nx 9.99\n{TILDE}\n", ["x 9.99\n"]),
    "tildes at the start": (f"{TILDE}\nx 9.99\n{TILDE}\n", ["x 9.99\n"]),
    "a dead opener leaves the next one alone": (
        f"The ROR\n{TILDE}\nwas\n\n{TILDE}\nx 9.99\n{TILDE}\n",
        ["x 9.99\n"],
    ),
    # In a list, backticks as far in as the item's own text are at its margin.
    "backticks in a list item's second paragraph": (
        f"1. Step.\n\n   Then run:\n   {FENCE}r\n   x <- 1\n   {FENCE}\n",
        ["   x <- 1\n"],
    ),
    "tildes after a definition": (f"Term\n:   def\n{TILDE}\nx\n{TILDE}\n", ["x\n"]),
    "tildes after an HTML block's tag": (f"<div>\n{TILDE}\nx\n{TILDE}\n</div>\n", ["x\n"]),
    "tildes after indented code": (f"    code\n{TILDE}\nx\n{TILDE}\n", ["x\n"]),
    # What follows the fence has to be something pandoc can parse, or the line is prose.
    "an R Markdown chunk": (f"{FENCE}{{r, echo=FALSE}}\nx <- 9.99\n{FENCE}\n", []),
    "a bare word in braces": (f"{FENCE}{{r}}\nx <- 9.99\n{FENCE}\n", []),
    "a key without braces": (f'{FENCE}python title="x"\nx = 9.99\n{FENCE}\n', []),
    "a class and a key in braces": (f"{FENCE}{{.r echo=FALSE}}\nx\n{FENCE}\n", ["x\n"]),
    "a raw block": (f"{FENCE}{{=openxml}}\nx\n{FENCE}\n", ["x\n"]),
    "a rejected opener moves the pairing on": (
        f'Intro.\n\n{FENCE}python title="x"\na\n\nb\n{FENCE}\n\nText one.\n\nText two.\n\n'
        f"{FENCE}\nc\n{FENCE}\n\nAfter.\n",
        ["\nText one.\n\nText two.\n\n"],
    ),
    "a dead tilde opener moves the pairing on": (
        "Intro.\n\nPara one.\n~~~\n\nText A.\n\n~~~\ncode\n\nText B.\n\nText C.\n~~~\n\nAfter.\n",
        ["code\n\nText B.\n\nText C.\n"],
    ),
    "a commented opener moves the pairing on": (
        f"<!-- old:\n{FENCE}\nx <- 1\n-->\n\nPara A.\n\n{FENCE}\ncode\n\nmore code\n\nend\n"
        f"{FENCE}\n\nPara B.",
        ["code\n\nmore code\n\nend\n"],
    ),
}


@pytest.mark.parametrize("name", sorted(LISTINGS))
def test_a_listing_is_what_pandoc_reads_as_one(name: str) -> None:
    text, expected = LISTINGS[name]
    assert listings(text) == expected


# ---------------------------------------------------------------- what each caller sees


@pytest.mark.parametrize(
    "text",
    [
        f"Set `x\n{LONGER}\ny`\n{FENCE}\n<!--\n{LONGER}\n\nThe ROR was 9.99. -->\n",
        f"Set `x\n{FENCE}\ny`.\n\nThe ROR was 9.99.\n\n{FENCE}\n",
        f"<!--\n{FENCE}r\nold\n-->\n\nThe ROR was 9.99.\n\n{FENCE}r\nnew\n{FENCE}\n",
        f"The ROR\n{TILDE}\nwas 9.99.\n{TILDE}\n",
    ],
    ids=[
        "a listing after a code span",
        "a code span over an opener",
        "a half-commented listing",
        "tildes in a paragraph",
    ],
)
def test_mask_reads_what_pandoc_prints_as_prose(text: str) -> None:
    assert "9.99" in atoms_of(text)


def test_a_heading_after_a_fence_line_in_a_comment_is_a_heading() -> None:
    """The fence line inside the comment paired with the one below `## Results`, and the
    heading scan blanked Results, so the p-value under it read as the alpha chosen in
    advance."""
    text = (
        f"## Methods\n\n<!-- draft\n{FENCE}\n-->\n\n## Results\n\n{FENCE}\n\n"
        "The excess was significant (p < 0.001).\n"
    )
    assert headings(text) == ["Methods", "Results"]
    atom = next(a for a in find_atoms(text, mask(text)) if a.text == "0.001")
    chain = section_chain(text, atom.start)
    assert chain == ("Results",)
    assert Classifier.load().classify(atom, chain).kind == UNCLASSIFIED


def test_a_heading_after_a_fence_line_in_a_code_span_is_a_heading() -> None:
    text = f"## Methods\n\nSet `x\n{FENCE}\ny`.\n\n## Results\n\nThe ROR was 9.99.\n\n{FENCE}\n"
    assert headings(text) == ["Methods", "Results"]


def test_a_binding_after_a_listing_found_again_is_parsed() -> None:
    text = f"Set `x\n{LONGER}\ny`\n{FENCE}\n<!--\n{LONGER}\n\nn = {{{{results.n}}}}. -->\n"
    assert [p.ref for p in parse(text)[0]] == ["results.n"]


def test_words_in_a_paragraph_that_holds_tildes_are_counted() -> None:
    """Blanked as a listing, "was 9.99." counted for nothing against the journal's limit."""
    assert count_words(f"The ROR\n{TILDE}\nwas 9.99.\n{TILDE}\n") == 4


# ---------------------------------------------------------------- linear time


@pytest.mark.parametrize(
    ("name", "build"),
    [
        (
            "dead openers in one paragraph",
            lambda size: "x\n" + f"{TILDE}\nprose line\n" * (size // 15) + f"{TILDE}\n<!-- a\n",
        ),
        (
            "openers swallowed by code spans",
            lambda size: f"`a\n{FENCE}\nb` " * (size // 11) + f"\n{FENCE}\n<!-- a\n",
        ),
        (
            "openers swallowed by comments",
            lambda size: f"<!--\n{FENCE}\n-->\n" * (size // 13) + f"{FENCE}\n",
        ),
        (
            "listings between code spans",
            lambda size: f"`a` <!-- \n\n{FENCE}\nx\n{FENCE}\n\n" * (size // 25),
        ),
    ],
)
def test_the_one_pass_is_linear(name: str, build) -> None:
    from manuscript_guard.text.scan import scan

    def measure(size: int) -> float:
        text = build(size)
        started = time.perf_counter()
        scan(text)
        return time.perf_counter() - started

    measure(5_000)  # warm the caches
    small = max(measure(20_000), 1e-3)
    large = measure(80_000)
    assert large / small < 12, f"{name}: 4x the input took {large / small:.1f}x the time"
