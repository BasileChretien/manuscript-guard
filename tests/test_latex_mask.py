"""The LaTeX reader's mask, rule by rule (`text/latex/mask.py`; DESIGN.md, "LaTeX
manuscripts", "What the LaTeX reader reads"). Each case is written with `·` for a blanked
character, so that what a rule keeps and what it hides can be read off the line. The generated
inputs are in `tests/test_properties.py`."""

from __future__ import annotations

import pytest

from manuscript_guard.text.latex.mask import NUL, mask, read

DOT = "\N{MIDDLE DOT}"


def shown(text: str, *, body: bool | None = True) -> str:
    return mask(text, body=body).replace(NUL, DOT)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Prose, and the arguments of commands that print, are read.
        ("Of 4100, 12 died.", "Of 4100, 12 died."),
        ("\\emph{12 died}", "······12 died·"),
        ("\\footnote{note 77}", "··········note 77·"),
        ("\\section*{Results 2}", "··········Results 2·"),
        # A command not in the table: its name is blanked, its arguments read.
        ("\\unknown{7 words}", "·········7 words·"),
        # Machinery is blanked.
        ("\\label{sec:2}", "·············"),
        ("\\ref{t3}", "········"),
        ("\\includegraphics[width=5cm]{f1}", "·" * 31),
        ("\\mg{results.ror}", "················"),
        ("\\url{http://a.b/c%20d}", "·" * 22),
        # A citation: its notes read, its keys not.
        ("\\cite[see][p.~33]{smith2019}", "······see··p. 33············"),
        # Escapes and spaces keep the length.
        ("95\\% CI", "95%· CI"),
        ("Table~2", "Table 2"),
        ("10\\,000", "10 ·000"),
        ("a\\quad b", "a ···· b"),
        # A comment, to its line's end and no further.
        ("x % 99\ny 3", "x ····\ny 3"),
        # Maths keeps what it holds, its commands, braces and delimiters blanked.
        ("$p < 0.05$", "·p < 0.05·"),
        ("$\\beta = 0.42$", "······ = 0.42·"),
        ("$10^{-8}$", "·10^·-8··"),
        ("\\[x = 1\\]", "··x = 1··"),
        # Listings and code.
        ("\\verb|x=5| and \\verb+y=6+", "······x=5· and ······y=6·"),
        ("\\begin{verbatim}\n55\n\\end{verbatim}", "················\n··\n··············"),
        # A table's cells, its column specification blanked.
        ("\\begin{tabular}{lc}a & 7 \\\\\\end{tabular}", "·" * 19 + "a   7  " + "·" * 14),
        # Quotation marks, typed the TeX way.
        ("``quoted 6''", "\N{LEFT DOUBLE QUOTATION MARK}·quoted 6\N{RIGHT DOUBLE QUOTATION MARK}·"),
        # A block nobody prints.
        ("a \\iffalse 9 \\fi b", "a ·············· b"),
        ("\\begin{comment}\n9\n\\end{comment}", "···············\n·\n·············"),
    ],
)
def test_each_rule_reads_or_blanks_what_it_says(text: str, expected: str) -> None:
    assert shown(text) == expected


def test_the_preamble_is_blanked_but_for_the_title_and_its_thanks() -> None:
    text = (
        "\\documentclass{article}\n\\newcommand{\\n}{4100}\n"
        "\\title{A 10-year cohort\\thanks{Grant 42}}\n\\author{A\\thanks{14000 Caen}}\n"
        "\\begin{document}\nBody 3\n\\end{document}\nafter 88\n"
    )
    masked = mask(text)
    for read_here in ("4100", "A 10-year cohort", "Grant 42", "Body 3"):
        start = text.index(read_here)
        assert masked[start : start + len(read_here)] == read_here, read_here
    for hidden in ("article", "14000", "after 88"):
        start = text.index(hidden)
        assert set(masked[start : start + len(hidden)]) == {NUL}, hidden


def test_a_file_with_no_document_is_body_and_one_whose_document_is_commented_too() -> None:
    assert mask("Of 4100.") == "Of 4100."
    text = "% \\begin{document}\nOf 4100."
    assert mask(text).endswith("Of 4100.")


@pytest.mark.parametrize(
    ("text", "code", "at"),
    [
        ("a {b 12", "tex-unbalanced", 2),
        ("a } b", "tex-unbalanced", 2),
        ("$x = 1", "tex-unbalanced", 0),
        ("\\begin{itemize} 3", "tex-unbalanced", 0),
        ("\\end{itemize}", "tex-unbalanced", 0),
        ("\\verb|unclosed 3", "tex-unbalanced", 0),
        ("\\iffalse 3", "tex-unbalanced", 0),
        ("\\catcode`\\@=11 5", "tex-refused", 0),
        ("x \\ifdefined\\y 1\\fi", "tex-refused", 2),
        ("\\makeatletter", "tex-refused", 0),
        ("\\lstinputlisting{code.R}", "tex-refused", 0),
        ("\\def\\x[#1]{#1}", "tex-refused", 0),
        ("\\renewcommand{\\emph}[1]{#1}", "tex-refused", 13),
        ("\\begin{minted}{r}\n1\n\\end{minted}", "tex-refused", 0),
    ],
)
def test_what_is_not_read_exactly_is_refused_and_the_rest_left_as_typed(
    text: str, code: str, at: int
) -> None:
    reading = read(text, body=True)
    assert [(r.code, r.offset) for r in reading.refusals] == [(code, at)]
    assert reading.masked[at:] == text[at:]


def test_an_input_encoding_other_than_utf8_is_refused() -> None:
    text = "\\documentclass{article}\n\\usepackage[latin1]{inputenc}\n\\begin{document}\n"
    assert [r.code for r in read(text + "\\end{document}").refusals] == ["tex-refused"]
    utf8 = text.replace("latin1", "utf8") + "\\end{document}"
    assert read(utf8).refusals == ()


def test_a_preamble_conditional_is_read_through_and_makeatletter_accepted() -> None:
    text = (
        "\\documentclass{article}\n\\makeatletter\\ifdefined\\x\\fi\\makeatother\n"
        "\\begin{document}\nBody 3\n\\end{document}\n"
    )
    assert read(text).refusals == ()


def test_the_mask_keeps_the_length_and_every_line_break() -> None:
    text = "\\begin{verbatim}\r\n1\r\n\\end{verbatim}\n% c\r\n$x\n= 1$\n"
    masked = mask(text, body=True)
    assert len(masked) == len(text)
    assert [i for i, c in enumerate(masked) if c in "\r\n"] == [
        i for i, c in enumerate(text) if c in "\r\n"
    ]


@pytest.mark.parametrize(
    "unit",
    [
        "\\emph{a} ", "{", "% c\n", "\\verb|x| ", "$x$ ", "\\label{x} ", "\\begin{itemize} ",
        "\\cite[p.~1]{k} ", "``q'' ", "\\iffalse x \\fi ",
    ],
)  # fmt: skip
def test_the_reader_is_linear_in_the_file(assert_linear, unit: str) -> None:
    assert_linear(lambda count: unit * count, lambda text: read(text, body=True), 2000,
                  f"the LaTeX reader on {unit!r}")  # fmt: skip
