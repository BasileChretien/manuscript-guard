"""A power in the Abstract, read whole (`auditing.abstract.powers`).

tex-astro-ga-B1 of the real-paper corpus has in its Abstract "masses of $\\sim 10^{-2}$" and
"densities of $\\sim 10^8$". The LaTeX reader blanks a group's braces, so `10^{-2}` was read
as two numbers, "10^" and "-2", and the finding named "10^", which the paper does not hold;
and `10^8` was looked for as printed among the bare numbers the paper reports, where no
power is one, so it was never found, even beside its copy in the Results.

A power, a number with a caret and a braced exponent or a single digit after it, or pandoc's
superscript `10^-2^`, is read whole, in the Abstract and where the paper reports alike, and
found only where the paper prints the same power, its base and its exponent each read as a
number: never by its pieces, and never as its value.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from manuscript_guard.audit import audit

sys.path.insert(0, str(Path(__file__).parent))
from test_audit import heading, make_docx, para  # noqa: E402

B = chr(92)

#: A LaTeX paper, `ABSTRACT` its Abstract's sentence and `RESULTS` its Results'.
LATEX = ("@documentclass{article}\n@begin{document}\n@begin{abstract}\nABSTRACT\n"
         "@end{abstract}\n@section{Results}\nRESULTS\n@section{Discussion}\nDISCUSSION\n"
         "@end{document}\n")  # fmt: skip
MARKDOWN = ("# A study\n\n## Abstract\n\nABSTRACT\n\n## Results\n\nRESULTS\n\n## Discussion\n\n"
            "DISCUSSION\n")  # fmt: skip


def _read(tmp_path: Path, suffix: str, abstract: str, results: str, discussion: str = "So."):
    template = LATEX if suffix == ".tex" else MARKDOWN
    text = (template.replace("ABSTRACT", abstract).replace("RESULTS", results)
            .replace("DISCUSSION", discussion))  # fmt: skip
    if suffix == ".tex":
        text = text.replace("@", B)
    paper = tmp_path / f"paper{suffix}"
    paper.write_text(text, encoding="utf-8")
    read = audit([paper], None).abstract
    assert read is not None and read.compared, read
    return read


def _texts(listed) -> list[str]:
    return [candidate.text for candidate in listed]


#: The shape of tex-astro-ga-B1's Abstract, line 91: two powers in maths beside a unit's.
ASTRO = ("masses of $@sim 10^{-2}$ M$_@odot$ and mean densities of $@sim 10^8$ cm$^{-3}$, "
         "are likely bound.")  # fmt: skip


@pytest.mark.parametrize("suffix", [".tex", ".md"])
def test_the_real_shape_names_each_power_whole(tmp_path: Path, suffix: str) -> None:
    """tex-astro-ga-B1: neither power is printed where the paper reports, and each is said
    not found by its whole name; the unit's exponent, which the Results give, is found."""
    abstract = ASTRO if suffix == ".tex" else ASTRO.replace("@", B)
    read = _read(tmp_path, suffix, abstract, "It was 4 cm$^{-3}$ there.")
    assert _texts(read.not_found) == ["10^{-2}", "10^8"]
    assert not any(text.endswith("^") for text in _texts(read.not_found + read.found))


@pytest.mark.parametrize("suffix", [".tex", ".md"])
@pytest.mark.parametrize(("abstract", "results", "name"), [
    ("$10^{-2}$", "$10^{-2}$", "10^{-2}"),
    ("$10^8$", "$10^8$", "10^8"),
    ("$10^{8}$", "$10^8$", "10^{8}"),
    ("$10^{@,8}$", "$10^{8}$", "10^{@,8}"),
    ("$10^{+8}$", "$10^{8}$", "10^{+8}"),
    ("$10^{-2.0}$", "$10^{-2}$", "10^{-2.0}"),
    ("$2^{10}$", "$2^{10}$", "2^{10}"),
    ("$10^{@alpha}$", "$10^{@alpha}$", "10^{@alpha}"),
])  # fmt: skip
def test_a_power_the_paper_prints_again_is_found(tmp_path: Path, suffix: str, abstract: str,
                                                 results: str, name: str) -> None:  # fmt: skip
    """A power is found where the Results print the same power, however its exponent is
    spelled: braced or not, a thin space before it, a plus sign, a trailing zero."""
    read = _read(tmp_path, suffix, f"It was {abstract} here.".replace("@", B),
                 f"It was {results} here.".replace("@", B))  # fmt: skip
    assert _texts(read.found) == [name.replace("@", B)] and read.not_found == [], read


@pytest.mark.parametrize("suffix", [".tex", ".md"])
def test_a_power_is_never_found_by_its_pieces_nor_by_another_power(
    tmp_path: Path, suffix: str
) -> None:
    """The Results give the base and the exponent apart, and another power: none of them is
    the Abstract's power, which is not found, and named whole."""
    read = _read(tmp_path, suffix, "It was $10^{-2}$ here.",
                 "Of 10 tubes, -2 was the shift, and $10^{-3}$ the rate.")  # fmt: skip
    assert _texts(read.not_found) == ["10^{-2}"] and read.found == []


def test_a_power_only_the_discussion_prints_is_not_found(tmp_path: Path) -> None:
    """Where the paper reports is where a power is looked for, as any number is."""
    read = _read(tmp_path, ".tex", "It was $10^{-2}$ here.", "It was so.",
                 "It was $10^{-2}$ here.")  # fmt: skip
    assert _texts(read.not_found) == ["10^{-2}"]


@pytest.mark.parametrize("suffix", [".tex", ".md"])
def test_the_number_before_a_power_is_looked_for_as_the_paper_reads_it(
    tmp_path: Path, suffix: str
) -> None:
    """`3 @times 10^{8}`: the power is read whole, and the 3 before it, a number of its own
    where the paper reports as here, is looked for as one."""
    read = _read(tmp_path, suffix, f"It was $3{B}times 10^{{8}}$ here.",
                 f"It was $3{B}times 10^{{8}}$ here.")  # fmt: skip
    assert read.not_found == [] and read.matched == 2


def test_pandoc_s_superscript_is_the_same_power(tmp_path: Path) -> None:
    """In Markdown, `10^-2^` is the power `$10^{-2}$` is."""
    read = _read(tmp_path, ".md", "It was 10^-2^ here.", "It was $10^{-2}$ here.")
    assert _texts(read.found) == ["10^-2^"] and read.not_found == []


def test_a_power_in_a_latex_comment_is_not_where_the_paper_reports(tmp_path: Path) -> None:
    """A power in a comment is masked, as any number there is."""
    read = _read(tmp_path, ".tex", "It was $10^{-2}$ here.", "It was so. % $10^{-2}$")
    assert _texts(read.not_found) == ["10^{-2}"]


def test_a_docx_superscript_in_a_paragraph_is_read_flat(tmp_path: Path) -> None:
    """A known limit (DESIGN.md, "Known gaps"): a .docx paragraph's raised run is printed
    flat, "10" and a raised "-2" as "10-2", a range, on both sides alike."""
    raised = ('<w:p><w:r><w:t xml:space="preserve">It was 10</w:t></w:r><w:r><w:rPr>'
              '<w:vertAlign w:val="superscript"/></w:rPr><w:t>-2</w:t></w:r>'
              '<w:r><w:t xml:space="preserve"> here.</w:t></w:r></w:p>')  # fmt: skip
    for results, state in ((raised, "found"), (para("It was 10 and 2 here."), "found"),
                           (para("It was so."), "not_found")):  # fmt: skip
        body = para("A study") + heading("Abstract") + raised + heading("Results") + results
        read = audit([make_docx(tmp_path / "paper.docx", body)], None).abstract
        assert _texts(getattr(read, state)) == ["10-2"], state
