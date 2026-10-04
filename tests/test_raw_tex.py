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
    "a macro used outside maths": (
        f"{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{N}The set {B}RR is used.",
        None,
        f"{B}mathbb{{R}}",
    ),
    # Pandoc holds what stands before and after a key in a citation's brackets apart from
    # the rest of its reading, and the build did not look there: the headline sentence
    # moved inside the brackets passed `check` and the build, and lost its number.
    "a bound number in a citation's prefix": (
        f"It was high [of {B}approx {{{{results.cohort.n_reports}}}} reports, see @smith2020].",
        f"It was high [of {B}approx 4000 reports, see @smith2020].",
        f"{B}approx 4000",
    ),
    "in a citation's suffix": (
        f"It was high [@smith2020, in {B}approx 12 reports].",
        None,
        f"{B}approx 12",
    ),
    "in a citation's locator": (f"As shown [@smith2020, {B}S 3.2].", None, f"{B}S"),
    "after a citation in the text": (f"As @smith2020 [{B}S 3.2] shows.", None, f"{B}S"),
    "in the second of two citations": (
        f"As shown [@smith2020; see IFN-{B}gamma in @jones2021].",
        None,
        f"{B}gamma",
    ),
    # Each of these was read, and no row held it: with the reading stopped at any one of
    # them every test passed.
    "in a block quote": (f"> IFN-{B}gamma release", None, f"{B}gamma"),
    "in a div": (f"::: note{N}IFN-{B}gamma release{N}:::", None, f"{B}gamma"),
    "in a span": (f"[IFN-{B}gamma]{{.smallcaps}} release", None, f"{B}gamma"),
    "in a link's text": (f"[IFN-{B}gamma](https://example.org) release", None, f"{B}gamma"),
    "in emphasis": (f"*IFN-{B}gamma* release", None, f"{B}gamma"),
    "in a figure's caption": (
        f"![Release of IFN-{B}gamma by group](figures/forest.svg)",
        None,
        f"{B}gamma",
    ),
    # An image in a paragraph is no figure, and its own text is read. Inside a figure
    # every image's text was passed over, not only the figure's own, which the caption
    # holds: an image in a caption lost the TeX of its description unseen.
    "in the text of an image in a paragraph": (
        f"As ![the IFN-{B}gamma assay](figures/forest.svg) shows, it rose.",
        None,
        f"{B}gamma",
    ),
    "in the text of an image in a figure's caption": (
        f"![Outer ![inner IFN-{B}gamma text](figures/forest.svg) words](figures/forest.svg)",
        None,
        f"{B}gamma",
    ),
    "in a definition": (f"Term{N}:   IFN-{B}gamma release", None, f"{B}gamma"),
    "in a line block": (f"| IFN-{B}gamma release{N}| a second line", None, f"{B}gamma"),
    "in a subscript": (f"x~a{B}gamma~ y", None, f"{B}gamma"),
    "in a superscript": (f"x^a{B}gamma^ y", None, f"{B}gamma"),
    "in quotation marks": (f'"IFN-{B}gamma release" was said', None, f"{B}gamma"),
    # A length is a number with a unit or a command. Anything was taken for one, and
    # `We enrolled \hspace{412} patients` was printed without its number, with a
    # warning only.
    "a number where a length belongs": (
        f"We enrolled {B}hspace{{412}} patients.",
        None,
        f"{B}hspace{{412}}",
    ),
    "words where a length belongs": (
        f"{B}vspace{{412 patients were included}}",
        None,
        f"{B}vspace{{412 patients were included}}",
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
    assert "(main.md:5)" in said, said


def test_the_line_named_is_the_line_of_the_source_and_not_of_the_text_as_built() -> None:
    """The build takes the front matter off a file and puts tables in, so a line of the
    text it hands pandoc is another line of the file: the example's Results sentence was
    named at line 68 and stands on line 72."""
    front = "---" + N + "title: A study" + N + "---" + N + N
    held = f"The database held {B}approx "
    source = front + ABOVE + held + "{{results.cohort.n_reports}} reports." + N
    document = ABOVE + held + "4000 reports." + N
    said = misreading(
        HEADER + document, HEADER, [("main.md", source)], PANDOC, Path(), built=[document]
    )
    assert said is not None
    assert "(main.md:9)" in said, said


def test_tex_a_value_puts_in_is_said_to_be_put_in() -> None:
    """A table's label written by the analysis with `\\dagger` in it: the source holds
    a placeholder and no backslash, and a line of it was named all the same."""
    source = ABOVE + "{{table.baseline}}" + N
    document = ABOVE + f"| Serious {B}dagger | 12 |" + N + "|---|---|" + N + "| Other | 3 |" + N
    said = misreading(
        HEADER + document, HEADER, [("main.md", source)], PANDOC, Path(), built=[document]
    )
    assert said is not None
    assert f"`{B}dagger" in said
    assert "(main.md, where a value or a table puts it)" in said, said


def test_tex_over_several_lines_in_a_quotation_is_found_where_it_stands() -> None:
    """Pandoc takes the `> ` off each line, so the piece as it reads it is in no source,
    and the refusal said a macro had put it there."""
    said = refusal(f"> {B}begin{{center}}{N}> Centred words.{N}> {B}end{{center}}")
    assert said is not None
    assert "(main.md:5)" in said, said
    assert "macro" not in said


def test_a_macro_that_comes_to_nothing_is_named_as_one() -> None:
    """`reports\\hide{to check}` with `\\hide` defined to print nothing loses its
    words. Pandoc reads an empty piece of TeX there, and the refusal named "``" in the
    build's own prologue."""
    said = refusal(
        f"{B}newcommand{{{B}hide}}[1]{{}}{N}{N}There were reports{B}hide{{to check}} here."
    )
    assert said is not None
    assert "``" not in said
    assert "a macro" in said
    assert "prologue" not in said
    assert "(main.md" not in said, "nothing is looked for, so no line is named"


def test_a_piece_no_text_holds_is_said_to_be_found_nowhere() -> None:
    from manuscript_guard.build.reading import _tex_left_out

    said = _tex_left_out([f"{B}gamma "], [("main.md", "No such letters.")], ["Nor here."])
    assert said is not None
    assert "(not found as written in a source: a macro or a value makes it)" in said


def test_the_refusal_says_what_to_do_with_text_that_is_no_tex() -> None:
    said = refusal(f"Saved under C:{B}Users{B}name.")
    assert said is not None
    assert "goes in a code span or has its backslash doubled" in said


def test_one_command_in_a_figures_caption_is_counted_once() -> None:
    """Pandoc holds a figure's caption twice, as the caption and as the image's own text."""
    said = refusal(f"![Release of IFN-{B}gamma by group](figures/forest.svg)")
    assert said is not None
    assert "more after it" not in said, said


def test_two_pieces_are_the_first_and_one_more() -> None:
    said = refusal(f"IFN-{B}gamma was measured.{N}{N}So was TNF-{B}alpha, later.")
    assert said is not None
    assert f"`{B}gamma` (main.md:5), and 1 more after it" in said, said


def test_a_definition_in_a_form_that_is_not_read_is_told_how_to_be_written() -> None:
    """Pandoc applies `\\let`, `\\gdef` and `\\DeclareRobustCommand` in maths
    as it applies `\\newcommand`, and only the forms named in `text/tex.py` are read
    here. The general remedy, a code span marked `{=latex}`, would stop the macro being
    applied, so such a piece is told to be a `\\newcommand`."""
    for definition in (
        f"{B}let{B}a{B}alpha",
        f"{B}gdef{B}x{{y}}",
        f"{B}DeclareRobustCommand{{{B}z}}{{w}}",
        f"{B}newcommand{{{B}x}}{B}alpha",
    ):
        said = refusal(definition + N + N + "Text.")
        assert said is not None, definition
        assert f"`{B}newcommand{{" in said, said
        assert "{=latex}" not in said, said


def test_a_definition_that_is_read_is_not_told_to_be_written_as_it_is() -> None:
    """A read definition directly over a page break directly over a line that opens with a
    number is one piece to pandoc, which is refused for the number. It was told that it
    "opens as a macro's definition, in a form that is not read here", and to be a
    `\\newcommand` with its braces, which it is. So was a read definition over
    `\\centering`, and an environment, which no `\\newcommand` can be."""
    for piece in (
        f"{B}newcommand{{{B}RR}}{{{B}mathbb{{R}}}}{N}{B}newpage{N}4000 reports were found.",
        f"{B}newcommand{{{B}x}}{{y}}{N}{B}centering",
        f"{B}newenvironment{{foo}}{{start}}{{end}}",
    ):
        said = refusal(piece + N + N + "Text.")
        assert said is not None, piece
        assert "in a form that is not read" not in said, said
        assert "between dollar signs" in said, said


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
    assert "and 2 more after it" in said, said


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
    # Not layout commands: those are let pass marked or not, and with these rows holding
    # one each, the mark read as no mark passed every test.
    "a block marked for LaTeX": (
        f"{FENCE}{{=latex}}{N}{B}textbf{{for the PDF only}}{N}{FENCE}"
    ),
    "a span marked for LaTeX": f"Text `{B}textit{{for the PDF}}`{{=latex}} more.",
    "a page break as a span of Word's own": (
        '`<w:r><w:br w:type="page"/></w:r>`{=openxml}'
    ),
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
    inert: list[str] = []
    assert refusal(KEPT[case], inert=inert) is None
    assert inert == [], "and none of it is taken for a layout command"


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
    "a length that is part of the page's width": (
        f"Left {B}hspace{{0.5{B}textwidth}} right.",
        [f"{B}hspace{{0.5{B}textwidth}}"],
    ),
    # One piece of TeX to pandoc, which was refused: the definition is let pass on its own
    # and so is the page break.
    # The warning names the page break and not the definition, which does something.
    "a definition directly over a page break": (
        f"{B}newcommand{{{B}x}}{{y}}{N}{B}newpage{N}{N}We write ${B}x$.",
        [f"{B}newpage"],
    ),
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


def test_the_warning_counts_the_rest_of_a_kind_and_names_where_the_first_stands() -> None:
    """Its count was not held by any test, nor its place, and its hint named a block,
    which `check` fails from `drafting` on: the page break is given as a code span."""
    from manuscript_guard.build.document import _does_nothing

    source = ABOVE + (f"{B}newpage" + N + N + "Words." + N + N) * 3
    report = _does_nothing(
        [f"{B}newpage"] * 3, [("main.md", source)], [source], Path("manuscript.docx")
    )
    (finding,) = report.findings
    assert finding.code == "tex-does-nothing" and finding.severity == "warn"
    assert finding.message == (
        f"`{B}newpage` (main.md:5) does nothing in a Word document, nor do 2 more like it"
    )
    assert '`<w:r><w:br w:type="page"/></w:r>`{=openxml}' in finding.hint
    assert "code span marked `{=latex}`" in finding.hint
    assert "block" not in finding.hint


def test_many_kinds_of_layout_command_are_twenty_warnings_and_a_count() -> None:
    """Each kind was looked for in the whole text, so the warnings took time with the
    square of the number of kinds: 40,000 took 19 seconds. Twenty are named."""
    from manuscript_guard.build.document import _does_nothing

    kinds = [f"{B}vspace{{{number}pt}}" for number in range(1, 31)]
    source = N.join(kinds)
    report = _does_nothing(kinds, [("main.md", source)], [source], Path("manuscript.docx"))
    assert len(report.findings) == 21
    assert report.findings[-1].message.startswith("10 more kinds of layout command")


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
