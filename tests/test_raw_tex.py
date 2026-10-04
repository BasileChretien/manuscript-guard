"""TeX in the manuscript's text that the Word writer leaves out of the document.

Pandoc reads a backslash directly before a letter as TeX wherever it stands, and takes with
it what TeX would: the number after `\\approx`, the words between the braces of `\\textit`,
everything from `\\begin` to its `\\end`. The Word writer keeps TeX only as maths, between
dollar signs, and leaves the rest out. `check` reads the sources and counts each number in
them as printed, so `\\approx {{results.cohort.n_reports}}` passed every gate and the build,
and the document was printed without the number.

The build asks pandoc how it reads the text before it makes the document
(`reading.misreading`), so what pandoc reads as TeX is in hand there, exactly, values in.
These tests put each shape to that reading.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manuscript_guard.build.reading import misreading

PANDOC = shutil.which("pandoc")
pytestmark = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")

#: A backslash, a line feed and a fence, written so that no tool between the author of a
#: test and this file can halve the first or read it as the start of an escape.
B = chr(92)
N = chr(10)
FENCE = "`" * 3
HEADER = "---" + N + "title: A study" + N + "---" + N
#: What stands above each shape, so that the line a refusal names is not the first.
ABOVE = "# Results" + N + N + "The first paragraph." + N + N


def refusal(
    written: str, built: str | None = None, inert: list[str] | None = None
) -> str | None:
    """What the build says of a text holding `written` under a heading and a paragraph;
    `built` is the same with its values put in, where it holds a placeholder. `inert`
    takes what the build only warns of."""
    source = ABOVE + written + N
    document = ABOVE + (written if built is None else built) + N
    return misreading(
        HEADER + document,
        HEADER,
        [("main.md", source)],
        PANDOC,
        Path(),
        built=[document],
        inert=inert,
    )


#: Text the document would be printed without part of: what is written, what the build
#: hands pandoc where a value is put in, and the TeX the refusal names.
LEFT_OUT = {
    "a sign before a bound number": (
        f"The database held {B}approx {{{{results.cohort.n_reports}}}} reports.",
        f"The database held {B}approx 4127 reports.",
        f"{B}approx 4127",
    ),
    "a sign between two numbers": (
        f"A mean of 12.4 {B}pm 3.1 years was seen.",
        None,
        f"{B}pm 3.1",
    ),
    "a Greek letter": (f"IFN-{B}gamma release was measured.", None, f"{B}gamma"),
    "a command with its words": (
        f"Measured {B}textit{{in vivo}} throughout.",
        None,
        f"{B}textit{{in vivo}}",
    ),
    "an environment with its words": (
        f"{B}begin{{center}}{N}Centred words.{N}{B}end{{center}}",
        None,
        f"{B}begin{{center}}` to `{B}end{{center}}",
    ),
    "an equation with no dollar signs": (
        f"{B}begin{{equation}}{N}a = b{N}{B}end{{equation}}",
        None,
        f"{B}begin{{equation}}` to `{B}end{{equation}}",
    ),
    "a citation as TeX writes it": (
        f"As shown before {B}cite{{smith2020}}, it holds.",
        None,
        f"{B}cite{{smith2020}}",
    ),
    "a path": (f"Saved under C:{B}Users{B}name.", None, f"{B}Users"),
    "in a heading": (f"## The role of IFN-{B}gamma{N}{N}Text.", None, f"{B}gamma"),
    "in a footnote": (f"Text.^[Measured as IFN-{B}gamma.]", None, f"{B}gamma"),
    "in a table": (
        f"| Marker | Reports |{N}|---|---|{N}| TNF-{B}alpha | 12 |",
        None,
        f"{B}alpha",
    ),
    "in a list": (f"- one{N}- IFN-{B}gamma release", None, f"{B}gamma"),
    # Pandoc folds digits that open the next line into a command that takes no braces.
    "a bound number folded into a page break": (
        f"{B}newpage{N}{{{{results.cohort.n_reports}}}} reports were in the database.",
        f"{B}newpage{N}4000 reports were in the database.",
        f"{B}newpage` to `4000",
    ),
    "a number folded into a skip": (
        f"{B}bigskip{N}412 reports were in the database.",
        None,
        f"{B}bigskip` to `412",
    ),
    "a page break with a bracket after it": (f"{B}newpage[412]", None, f"{B}newpage[412]"),
    "a page break with words in braces after it": (
        f"{B}newpage{{412 patients}}",
        None,
        f"{B}newpage{{412 patients}}",
    ),
    "a command that is no layout command": (f"{B}centering", None, f"{B}centering"),
    "an environment defined": (
        f"{B}newenvironment{{foo}}{{start}}{{end}}",
        None,
        f"{B}newenvironment{{foo}}{{start}}{{end}}",
    ),
    "a macro used outside maths": (
        f"{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{N}The set {B}RR is used.",
        None,
        f"{B}mathbb{{R}}",
    ),
}


@pytest.mark.parametrize("case", list(LEFT_OUT))
def test_tex_the_document_would_be_printed_without_is_refused(case: str) -> None:
    written, built, named = LEFT_OUT[case]
    said = refusal(written, built)
    assert said is not None, "the build made the document"
    assert f"`{named}" in said, said
    assert "the Word writer leaves" in said
    assert "between dollar signs" in said


def test_the_refusal_names_the_file_and_the_line() -> None:
    written, built, _named = LEFT_OUT["a sign before a bound number"]
    said = refusal(written, built)
    assert said is not None
    assert "main.md:5" in said, said


def test_the_refusal_says_how_many_more_there_are() -> None:
    """One sentence names the first and counts the rest, so that an author with a dozen does
    not rebuild a dozen times to learn of each."""
    written = (
        f"IFN-{B}gamma and TNF-{B}alpha were measured.{N}{N}"
        f"A mean of 12.4 {B}pm 3.1 years."
    )
    said = refusal(written)
    assert said is not None
    assert f"`{B}gamma" in said
    assert "2 more" in said, said


#: Text the document is printed with, whole: maths, code, a comment, a backslash that is no
#: TeX, and TeX the author marked as raw for another format.
KEPT = {
    "inline maths": f"IFN-${B}gamma$ release and a mean of 12.4 ${B}pm$ 3.1 years.",
    "display maths": f"$${B}frac{{a}}{{b}}$$",
    "an environment in display maths": (
        f"$${N}{B}begin{{aligned}} a &= b {B}end{{aligned}}{N}$$"
    ),
    "a code span": f"Saved under `C:{B}Users{B}name`.",
    "a fenced listing": f"{FENCE}{N}{B}d+{B}s{B}w{N}{FENCE}",
    "an indented listing": f"    {B}indented listing",
    "a comment in a paragraph": f"Kept. <!-- {B}gamma is not printed --> After.",
    "a comment of its own": f"<!--{N}{B}begin{{x}}{N}-->",
    "a doubled backslash": f"The command {B}{B}gamma is typed so.",
    "escaped signs": f"Up 5{B}% in A{B}&B, under {B}$10.",
    "a block marked for LaTeX": f"{FENCE}{{=latex}}{N}{B}clearpage{N}{FENCE}",
    "a span marked for LaTeX": f"Text `{B}hfill`{{=latex}} more.",
    "a block of Word's own": (
        f"{FENCE}{{=openxml}}{N}<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>{N}{FENCE}"
    ),
    "a macro defined and used in maths": (
        f"{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{N}The set ${B}RR$ is used."
    ),
    "a macro with arguments": (
        f"{B}newcommand{{{B}pair}}[2]{{({B}mathbf{{#1}}, #2)}}{N}{N}${B}pair{{a}}{{b}}$"
    ),
    "a macro defined twice": (
        f"{B}newcommand{{{B}x}}{{y}}{N}{B}renewcommand{{{B}x}}{{z}}{N}{N}We write ${B}x$."
    ),
    "a macro provided, and one defined as TeX does": (
        f"{B}providecommand{{{B}p}}{{q}}{N}{N}{B}def{B}x{{y}}{N}{N}We write ${B}p + {B}x$."
    ),
    "a macro defined in a paragraph": (
        f"Text {B}newcommand{{{B}x}}{{y}} then ${B}x$."
    ),
    "an operator declared and used in maths": (
        f"{B}DeclareMathOperator{{{B}argmax}}{{argmax}}{N}{N}We take ${B}argmax f$."
    ),
    "no backslash": "A plain paragraph with 12 of 40 reports.",
}


@pytest.mark.parametrize("case", list(KEPT))
def test_text_the_document_is_printed_with_whole_is_not_refused(case: str) -> None:
    assert refusal(KEPT[case]) is None


#: Layout commands, which print no word in LaTeX either and do nothing in a Word document:
#: the build warns of each and makes the document. What is written, and what it warns of.
INERT = {
    "a page break": (f"{B}newpage", [f"{B}newpage"]),
    "a page break over a word": (f"{B}newpage{N}Reports were in the database.", [f"{B}newpage"]),
    "a page break with its number": (f"{B}pagebreak[4]", [f"{B}pagebreak[4]"]),
    "space with a length": (f"{B}vspace{{1em}}", [f"{B}vspace{{1em}}"]),
    "space with a length, over a number": (
        f"{B}vspace{{1em}}{N}4000 reports were in the database.",
        [f"{B}vspace{{1em}}"],
    ),
    "space that stays at a page's top": (f"{B}vspace*{{2cm}}", [f"{B}vspace*{{2cm}}"]),
    "space as long as a line": (
        f"{B}vspace{{{B}baselineskip}}",
        [f"{B}vspace{{{B}baselineskip}}"],
    ),
    "two on one line": (f"{B}clearpage{B}newpage", [f"{B}clearpage{B}newpage"]),
    "a skip and a paragraph that is not indented": (
        f"{B}bigskip{N}{B}noindent{N}Two words.",
        [f"{B}bigskip", f"{B}noindent"],
    ),
    "a fill in a line": (f"Left {B}hfill right.", [f"{B}hfill"]),
    "a line break in a paragraph": (f"Two {B}linebreak three.", [f"{B}linebreak"]),
}


@pytest.mark.parametrize("case", list(INERT))
def test_a_layout_command_alone_is_warned_of_and_the_document_is_made(case: str) -> None:
    """A manuscript with a bare `\\newpage` built before the refusal and loses no word by
    it, so it still builds. The command does nothing in a Word document, which the build
    says."""
    written, warned = INERT[case]
    inert: list[str] = []
    assert refusal(written, inert=inert) is None
    assert [raw.strip() for raw in inert] == warned


def test_a_layout_command_beside_tex_that_loses_words_does_not_stop_the_refusal() -> None:
    inert: list[str] = []
    said = refusal(f"{B}newpage{N}{N}IFN-{B}gamma release was measured.", inert=inert)
    assert said is not None and f"`{B}gamma" in said


def test_a_macro_defined_in_a_marked_block_is_not_applied_which_is_why_one_may_stand_bare() -> None:
    """A definition is raw TeX to pandoc, prints nothing, and is applied in maths. Marked
    `{=latex}` it is no longer applied, and the maths keeps the macro's name, which Word
    cannot show: refusing a bare definition would leave the author no way to write one."""
    import json
    import subprocess

    marked = (
        f"{FENCE}{{=latex}}{N}{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{FENCE}{N}{N}"
        f"The set ${B}RR$ is used.{N}"
    )
    bare = f"{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{N}The set ${B}RR$ is used.{N}"
    maths = {}
    for name, text in (("marked", marked), ("bare", bare)):
        finished = subprocess.run(
            [PANDOC, "-f", "markdown", "-t", "json"],
            input=text.encode("utf-8"),
            capture_output=True,
            check=True,
        )
        paragraph = json.loads(finished.stdout)["blocks"][-1]["c"]
        maths[name] = next(inline["c"][1] for inline in paragraph if inline["t"] == "Math")
    assert maths == {"marked": f"{B}RR", "bare": f"{B}mathbb{{R}}"}
