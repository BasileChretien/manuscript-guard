"""A power in the Abstract, read whole (`auditing.abstract.powers`).

tex-astro-ga-B1 of the real-paper corpus has in its Abstract "masses of $\\sim 10^{-2}$" and
"densities of $\\sim 10^8$". The LaTeX reader blanks a group's braces, so `10^{-2}` was read
as two numbers, "10^" and "-2", and the finding named "10^", which the paper does not hold;
and `10^8` was looked for as printed among the bare numbers the paper reports, where no
power is one, so it was never found, even beside its copy in the Results.

A power, a number with a caret and a braced exponent or a single digit after it, or pandoc's
superscript `10^-2^`, is read whole, in the Abstract and where the paper reports alike, and
found only where the paper prints the same power, its base and its exponent each read as a
number: never by its pieces, and never as its value. A number in scientific notation, a
sign, a mantissa, a times sign and a power, is one number, and a bare power is one with a
mantissa of 1; a power after a times sign with no mantissa is a scale, no number (round 1
of #696).
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
@pytest.mark.parametrize(("abstract", "results", "name"), [
    ("$3@times 10^{8}$", "$3@times 10^{8}$", "3@times 10^{8}"),
    ("$3@times10^{8}$", "$3.0 @cdot 10^8$", "3@times10^{8}"),
    ("$-2.5@,@times@,10^{-3}$", "$-2.5 @times 10^{-3}$", "-2.5@,@times@,10^{-3}"),
    ("$3 \N{MULTIPLICATION SIGN} 10^{8}$", "$3@times 10^{8}$",
     "3 \N{MULTIPLICATION SIGN} 10^{8}"),
    ("$-10^{8}$", "$-1@times 10^{8}$", "-10^{8}"),
    ("$10^{\N{EN DASH}2}$", "$10^{-2}$", "10^{\N{EN DASH}2}"),
    ("$3~@times~10^{8}$", "$3@ @times\N{NO-BREAK SPACE}10^{8}$", "3~@times~10^{8}"),
    ("$1@,500@times10^{3}$", "$1500 @times 10^{3}$", "1@,500@times10^{3}"),
    ("$1{,}5@times10^{-3}$", "$1{,}5 @times 10^{-3}$", "1{,}5@times10^{-3}"),
])  # fmt: skip
def test_a_number_in_scientific_notation_is_found_whole(tmp_path: Path, suffix: str,
                                                        abstract: str, results: str,
                                                        name: str) -> None:  # fmt: skip
    """A mantissa times a power is one number, its sign, its mantissa and its power; a bare
    power is the same with a mantissa of 1 and keeps its sign; an en dash in an exponent is
    a minus, as `audit._NUMBER` reads one."""
    read = _read(tmp_path, suffix, f"It was {abstract} here.".replace("@", B),
                 f"It was {results} here.".replace("@", B))  # fmt: skip
    assert _texts(read.found) == [name.replace("@", B)] and read.not_found == [], read


@pytest.mark.parametrize("suffix", [".tex", ".md"])
@pytest.mark.parametrize(("abstract", "results", "name"), [
    # A scale: the paper's 0.05 is five times the Abstract's 0.01.
    ("$10^{-2}$", "$5@times 10^{-2}$", "10^{-2}"),
    # Another mantissa, the Abstract's own given alone elsewhere.
    ("$3@times 10^{8}$", "$5@times 10^{8}$ in 3 runs", "3@times 10^{8}"),
    # A sign dropped, either way.
    ("$-10^{8}$", "$10^{8}$", "-10^{8}"),
    ("$10^{8}$", "$-10^{8}$", "10^{8}"),
    ("$-3@times 10^{8}$", "$3@times 10^{8}$", "-3@times 10^{8}"),
    # A column header's scale is no number.
    ("$10^{8}$", "Density ($@times 10^8$ cm$^{-3}$) was read.", "10^{8}"),
    ("$10^{-3}$", "Mass (\N{MULTIPLICATION SIGN}10^{-3}) was read.", "10^{-3}"),
    # Round 2 of #696: every gap TeX or a typist leaves around a times sign.
    *(row for gap in ("~", "@ ", "\N{NO-BREAK SPACE}", "\N{THIN SPACE}",
                      "\N{NARROW NO-BREAK SPACE}", "@,~", "~@; ")
      for row in (("$10^{-2}$", f"$5{gap}@times{gap}10^{{-2}}$", "10^{-2}"),
                  (f"$3{gap}@times{gap}10^{{8}}$", f"$5{gap}@times{gap}10^{{8}}$ in 3 runs",
                   f"3{gap}@times{gap}10^{{8}}"))),
    # A decimal comma or a digit group is part of the mantissa.
    ("$1{,}5@times10^{-3}$", "$2{,}5@times10^{-3}$ in 1 run", "1{,}5@times10^{-3}"),
    ("$1@,500@times10^{3}$", "$500@times10^{3}$ and $1{,}5@times10^{3}$",
     "1@,500@times10^{3}"),
    # A times sign after no number alone is a scale's.
    ("$10^{3}$", "$k_2@times10^{3}$", "10^{3}"),
])  # fmt: skip
def test_a_number_in_scientific_notation_is_never_found_by_a_part(
    tmp_path: Path, suffix: str, abstract: str, results: str, name: str
) -> None:
    """Round 1 of #696: neither a power nor its mantissa is found apart from the other, a
    sign is part of the number, and a scale after a times sign with no mantissa before it is
    no number where the paper reports."""
    read = _read(tmp_path, suffix, f"It was {abstract} here.".replace("@", B),
                 f"It was {results}.".replace("@", B))  # fmt: skip
    assert _texts(read.not_found) == [name.replace("@", B)] and read.found == [], read


@pytest.mark.parametrize("suffix", [".tex", ".md"])
@pytest.mark.parametrize("scale", ["($@times 10^{8}$ per ml)", "($@cdot 10^{-3}$)",
                                   "(\N{MULTIPLICATION SIGN}10^{-3} g)"])
def test_a_scale_in_the_abstract_is_no_number(tmp_path: Path, suffix: str,
                                              scale: str) -> None:  # fmt: skip
    """A power after a times sign with no mantissa before it, as a header scales a column,
    is never looked for: no finding names it, nor a text ending in a times sign."""
    read = _read(tmp_path, suffix, f"Densities {scale} were read.".replace("@", B),
                 "It was so.")  # fmt: skip
    assert read.numbers == 0 and read.not_found == [] and read.found == [], read


@pytest.mark.parametrize("suffix", [".tex", ".md"])
def test_an_unbraced_digit_before_a_full_stop_is_an_exponent(tmp_path: Path,
                                                             suffix: str) -> None:  # fmt: skip
    """`$n = 10^8.$` and `10^8.` at a sentence's end are the power 10^8."""
    read = _read(tmp_path, suffix, "It was $n = 10^8.$ Then $10^8$.", "It was $10^{8}$ here.")
    assert _texts(read.found) == ["10^8", "10^8"] and read.not_found == [], read


@pytest.mark.parametrize("suffix", [".tex", ".md"])
def test_no_finding_names_a_text_ending_in_a_caret_or_a_times_sign(
    tmp_path: Path, suffix: str
) -> None:
    """Every number of scientific notation is named whole, whatever is found."""
    abstract = (f"It was $3{B}times 10^{{8}}$, $2.5 {B}cdot 10^{{-3}}$, $-10^{{4}}$ and "
                "$7 \N{MULTIPLICATION SIGN} 10^5$ here.")  # fmt: skip
    read = _read(tmp_path, suffix, abstract, "It was 3, 8, 2.5 and 7 here.")
    named = _texts(read.not_found + read.found)
    assert len(named) == 4 and not any(text.rstrip().endswith(("^", "times", "cdot",
                                                               "\N{MULTIPLICATION SIGN}"))
                                       for text in named), named  # fmt: skip
    assert read.found == [], named


def test_a_markdown_subscript_before_a_times_sign_is_no_mantissa(tmp_path: Path) -> None:
    """In a Markdown paper's text `~` is pandoc's subscript mark, `CO~2~`, and no gap: the
    subscript's digit before a spaced times sign is no mantissa, and the power after it is a
    scale (Basile, after the check of b95b6a89f: "`~` counts as a space only in LaTeX and
    inside maths")."""
    read = _read(tmp_path, ".md", f"It was $2{B}times10^{{3}}$ here.",
                 f"It was VCO~2~ {B}times10^{{3}} rose.")  # fmt: skip
    assert _texts(read.not_found) == [f"2{B}times10^{{3}}"] and read.found == [], read
    read = _read(tmp_path, ".md", "It was $10^{3}$ here.", f"It was X~2~ {B}times10^3 rose.")
    assert _texts(read.not_found) == ["10^{3}"] and read.found == [], read
    read = _read(tmp_path, ".md", f"It was X~2~ {B}times10^3 here.", "It was so.")
    assert not any("times" in text or "^" in text for text in _texts(read.not_found)), read


@pytest.mark.parametrize("maths", [f"$5~{B}times~10^{{-2}}$", f"$$5~{B}times~10^{{-2}}$$"])
def test_a_tie_inside_markdown_maths_is_a_gap(tmp_path: Path, maths: str) -> None:
    """Inside a Markdown paper's maths, `$...$` or `$$...$$`, `~` is TeX's tie, a space:
    `5~\\times~10^{-2}` is one number there, never the bare power. `\\(...\\)` is no maths
    to pandoc's Markdown (`test_a_markdown_paper_s_maths_holds_its_ties_across_lines`)."""
    read = _read(tmp_path, ".md", "It was $10^{-2}$ here.", f"It was {maths} here.")
    assert _texts(read.not_found) == ["10^{-2}"] and read.found == [], read
    read = _read(tmp_path, ".md", f"It was {maths} here.", f"It was $5{B}times 10^{{-2}}$ here.")
    assert _texts(read.found) == [f"5~{B}times~10^{{-2}}"] and read.not_found == [], read


def test_markdown_maths_is_found_as_pandoc_finds_it() -> None:
    """Basile, after the check of 191d0e7c2: `$...$` within a paragraph across a line break,
    opened before a non-space and closed after one with no digit after it; `$$...$$` across
    lines; none in code, after an escaped `\\$`, across a blank line, nor `\\(...\\)`."""
    from manuscript_guard.auditing.abstract import markdown_maths

    def read(text: str) -> list[str]:
        return [text[start:end] for start, end in markdown_maths(text)]

    assert read("masses of $\\sim\n5~\\times~10^{-2}$ here") == ["$\\sim\n5~\\times~10^{-2}$"]
    assert read("It was\n$$\n5~\\times~10^{-2}\n$$\nthen.") == ["$$\n5~\\times~10^{-2}\n$$"]
    assert read("It was $$5~\\times~10^{-2}$$ then.") == ["$$5~\\times~10^{-2}$$"]
    assert read("costs $5 ~ $7 and $x$") == ["$x$"]
    assert read("Set `$PATH` and VCO~2~ \\times10^{3} rose to 5$.") == []
    assert read("A `` x$ `` and ```\n$y$\n```\n$z$") == ["$z$"]
    assert read("```\n$y$\n```\n$z$") == ["$z$"]
    assert read("\\(VCO~2~ \\times10^{3}\\)") == []
    assert read("An escaped \\$5~x$ and $a$") == ["$a$"]
    assert read("open $a\n\nb$ and $c $ and $d$5") == []
    assert read("<!-- $a$ -->$b$") == ["$b$"]


@pytest.mark.parametrize(("abstract", "results", "found", "not_found"), [
    # (a) An Abstract's maths wrapped across a line break.
    ("masses of $@sim\n5~@times~10^{-2}$ here", "masses of $5@times 10^{-2}$ there",
     ["5~@times~10^{-2}"], []),
    ("masses of $@sim\n5~@times~10^{-2}$ here", "masses of $10^{-2}$ in 5 runs", [],
     ["5~@times~10^{-2}"]),
    # A list item or a table row is a block of its own: no inline maths runs into the next.
    ("It was $2@times10^{3}$ here.", "- costs $a\n- VCO~2~ @times10^{3} in b$.",
     [], ["2@times10^{3}"]),
    ("It was $2@times10^{3}$ here.", "| $a | x |\n|---|---|\n| VCO~2~ @times10^{3} | b$ |",
     [], ["2@times10^{3}"]),
    # (b) Display maths on lines of its own, and on one line.
    ("It was $5@times10^{-2}$ here.", "It was\n$$\n5~@times~10^{-2}\n$$\nthen.",
     ["5@times10^{-2}"], []),
    ("It was $5@times10^{-2}$ here.", "It was $$5~@times~10^{-2}$$ then.",
     ["5@times10^{-2}"], []),
    # No maths: a `~` is a subscript, so the power is a scale.
    ("It was $2@times10^{3}$ here.", "It costs $5 ~ $7, and VCO~2~ @times10^{3} rose.",
     [], ["2@times10^{3}"]),
    ("It was $2@times10^{3}$ here.", "Set `$PATH` and VCO~2~ @times10^{3} rose to 5$.",
     [], ["2@times10^{3}"]),
    ("It was $2@times10^{3}$ here.", "It was @(VCO~2~ @times10^{3}@) then.",
     [], ["2@times10^{3}"]),
    ("It was $2@times10^{3}$ here.", "An escaped @$5 and VCO~2~ @times10^{3} rose$.",
     [], ["2@times10^{3}"]),
    # A line break is a space around a times sign, as in maths and in prose.
    ("It was $5@times10^{-2}$ here.", "It was $5 @times\n10^{-2}$ then.",
     ["5@times10^{-2}"], []),
    # A `~` in a braced exponent outside maths leaves no control character anywhere.
    ("It was 10^{~3} here.", "It was so.", [], ["10^{~3}"]),
])  # fmt: skip
def test_a_markdown_paper_s_maths_holds_its_ties_across_lines(
    tmp_path: Path, abstract: str, results: str, found: list, not_found: list
) -> None:
    """Basile, after the check of 191d0e7c2: "Find Markdown maths exactly as pandoc does"."""
    read = _read(tmp_path, ".md", abstract.replace("@", B), results.replace("@", B))
    assert _texts(read.found) == [one.replace("@", B) for one in found], read
    assert _texts(read.not_found) == [one.replace("@", B) for one in not_found], read
    assert not any(ord(c) < 32 and c != "\n" for one in read.found + read.not_found
                   for c in one.text + one.normalised), read  # fmt: skip


@pytest.mark.parametrize("suffix", [".tex", ".md"])
def test_a_bracketed_mantissa_s_numbers_are_named_as_looked_for(tmp_path: Path,
                                                                 suffix: str) -> None:  # fmt: skip
    """`(1.4 @pm 0.2)@times10^{-2}`: the power after the bracket is a scale, and 0.2 is
    looked for and named alone, never "0.2)@times10^{-2}" (round 2 of #696)."""
    read = _read(tmp_path, suffix, f"It was $(1.4 {B}pm 0.2){B}times10^{{-2}}$ here.",
                 "It was so.")  # fmt: skip
    named = _texts(read.not_found + read.found)
    assert "0.2" in named, named
    assert not any(text.endswith(("^", "times", "\N{MULTIPLICATION SIGN}", ")"))
                   for text in named), named  # fmt: skip


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
