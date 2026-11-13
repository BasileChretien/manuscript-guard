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
        # A straight `"` closes a quotation `` opened in its paragraph, and is the character
        # typed after a blank line, alone, once the quotation is closed, or before a letter
        # (corpus round, 2026-10-23).
        ('``quoted 6"', "\N{LEFT DOUBLE QUOTATION MARK}·quoted 6\N{RIGHT DOUBLE QUOTATION MARK}"),
        ('``a\n\nb 6"', '\N{LEFT DOUBLE QUOTATION MARK}·a\n\nb 6"'),
        ('a 6" b', 'a 6" b'),
        ("``a'' 6\"", "\N{LEFT DOUBLE QUOTATION MARK}·a\N{RIGHT DOUBLE QUOTATION MARK}· 6\""),
        ('``Gr"une', '\N{LEFT DOUBLE QUOTATION MARK}·Gr"une'),
        ('% ``a\nb 6"', '·····\nb 6"'),
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
        # A conditional or a `\makeatletter` in the body with no end in the file (2026-11-13).
        ("x \\ifdefined\\y 1", "tex-refused", 2),
        ("\\makeatletter", "tex-refused", 0),
        ("\\lstinputlisting{code.R}", "tex-refused", 0),
        ("\\def\\x[#1]{#1} use \\x[2]", "tex-refused", 19),
        ("\\def\\x}{1}", "tex-refused", 0),
        ("\\renewcommand{\\emph}[1]{#1}", "tex-refused", 13),
        ("\\let\\emph\\relax", "tex-refused", 4),
        ("\\let\\footnote=\\textbf", "tex-refused", 4),
        ("\\begin{minted}{r}\n1\n\\end{minted}", "tex-refused", 0),
        ("\\inputfrom{a/}{b}", "tex-refused", 0),
        # Round 1 of real templates: let to a command of the same form that prints another
        # level or another kind of citation; a delimited use in a hook, which LaTeX runs
        # where it stands; the import package's starred form, named.
        ("\\let\\chapter\\section", "tex-refused", 4),
        ("\\let\\cite\\citet", "tex-refused", 4),
        ("\\def\\p(#1){#1}\\AtBeginDocument{\\p(12)}", "tex-refused", 31),
        ("\\import*{sec/}{a}", "tex-refused", 0),
        # Round 2: let between commands the reader reads apart, an input or code.
        ("\\let\\include\\input", "tex-refused", 4),
        ("\\let\\texttt\\textrm", "tex-refused", 4),
    ],
)
def test_what_is_not_read_exactly_is_refused_and_the_rest_not_read(
    text: str, code: str, at: int
) -> None:
    """Past a refusal nothing is read: the rest is blanked, its line breaks kept (Basile,
    2026-11-11: read as typed, a template's comments and commands were G6's findings)."""
    reading = read(text, body=True)
    assert [(r.code, r.offset) for r in reading.refusals] == [(code, at)]
    assert set(reading.masked[at:]) <= {NUL, "\n"}
    assert reading.masked[at:].count("\n") == text[at:].count("\n")


#: The shapes of the three real papers whose reading stopped at a block in the body (corpus
#: run of 2026-11-13): tex-stat-ap-B2's bookmark on one line, tex-qbio-pe-B1's definition in
#: a figure, tex-stat-ap-A1's blind and named title pages, a group in the first.
_REAL_BLOCKS = (
    "\\makeatletter \\pdfbookmark[0]{\\@title}{title} \\makeatother",
    "\\begin{figure}\n\\makeatletter\\long\\def\\@ifdim#1#2#3{#2}\\makeatother\n"
    "\\caption{Mean of 31 runs}\n\\end{figure}",
    "\\if0\\blind\n{\\title{\\tit\\thanks{Funded by 32.}}\n\\maketitle\n}\\fi\n"
    "\\if1\\blind \\title{\\bf \\tit} \\maketitle\n\\fi",
)  # fmt: skip


@pytest.mark.parametrize("block", _REAL_BLOCKS, ids=["bookmark", "figure", "blind"])
def test_a_bounded_block_in_the_body_is_skipped_and_the_rest_read(block: str) -> None:
    """Basile, 2026-11-13: a `\\makeatletter` in the body, or a conditional, stopped the
    reading of three real papers, and with it 61 true findings past it. Each is skipped to
    its `\\makeatother` or its `\\fi`, nothing in it read, and the file read on past it."""
    text = f"Of 4100 reports.\n{block}\nThen 77 died, 12 later.\n"
    reading = read(text, body=True)
    assert reading.refusals == (), reading.refusals
    assert reading.masked.endswith("Then 77 died, 12 later.\n"), reading.masked
    for skipped in reading.skipped:
        assert skipped.code == "tex-refused" and skipped.end > skipped.offset
        assert set(reading.masked[skipped.offset : skipped.end]) <= {NUL, "\n"}
        closer = "\\makeatother" if "makeat" in skipped.message else "\\fi"
        assert text[: skipped.end].endswith(closer) and skipped.message.endswith(closer)
    assert len(reading.skipped) == block.count("\\if") + block.count("\\makeatletter")
    # Neither 32 in a branch nor anything a block holds is read; the figure's caption is.
    assert "32" not in reading.masked and "title" not in reading.masked.replace("\n", "")
    assert ("Mean of 31 runs" in reading.masked) == ("caption" in block)


@pytest.mark.parametrize(
    ("block", "skipped"),
    [
        # Each conditional inside opens a `\fi` of its own, whatever primitive or `\newif`
        # made it; `\else` and a `\fi` in a comment close nothing.
        ("\\ifx\\a\\b 1\\ifnum\\c>2 3\\else 4\\fi\\ifdefined\\d 5\\fi\\fi", True),
        ("\\ifmine 1 % \\fi\n\\iffalse 2\\fi\\ifcsname e\\endcsname 3\\fi\\fi", True),
        # A `\newif` inside defines its conditional, which opens nothing.
        ("\\ifx\\a\\b \\newif\\iffound 1\\fi", True),
        # No end in the file, or one past a brace that closes a group opened before the
        # block, or before a group it opens is closed: refused, as before.
        ("\\ifx\\a\\b 1 \\ifnum\\c>2 3\\fi", False),
        ("{\\makeatletter 1} \\makeatother", False),
        ("\\ifx\\a\\b {1 \\fi}", False),
        ("\\makeatletter 1 \\makeatotherwise", False),
        # Round 1 of #674: a block that defines a name with no `@`, which changes how the
        # rest of the file reads, or changes a character's category, is refused as before;
        # one that defines an internal `@` name, tex-qbio-pe-B1's, is skipped.
        ("\\makeatletter\\renewcommand{\\emph}[1]{\\textbf{#1}}\\makeatother", False),
        ("\\makeatletter\\let\\x\\relax\\makeatother", False),
        ("\\ifx\\a\\b \\def\\x{1}\\fi", False),
        ("\\ifx\\a\\b \\newcommand*{\\y}{2}\\fi", False),
        ("\\ifx\\a\\b \\DeclareRobustCommand\\z{2}\\fi", False),
        ("\\ifx\\a\\b \\catcode`\\@=11 \\fi", False),
        ("\\makeatletter\\long\\def\\@ifdim#1#2#3{#2}\\makeatother", True),
        ("\\makeatletter\\def\\@x{1}\\let\\@y\\@x\\makeatother", True),
        # A `\makeatother` inside a conditional the block opened ends nothing, and a
        # `\makeatletter` a conditional opens and does not close outlives its `\fi`.
        ("\\makeatletter \\ifx\\a\\b x \\makeatother \\else Hidden 55 \\fi", False),
        ("\\ifx\\a\\b \\makeatletter \\fi", False),
        ("\\ifx\\a\\b \\makeatletter x\\makeatother \\fi", True),
        # Round 2 of #674: the name a definition defines is read with `@` a letter only
        # inside a `\makeatletter`; `\@namedef`, xparse's commands and the environments'
        # are definitions too, of an `@` name skipped; and branches that leave `@` in other
        # states refuse their conditional.
        ("\\ifx\\a\\b \\def\\emph@x{}\\fi", False),
        ("\\makeatletter\\def\\emph@x{}\\makeatother", True),
        ("\\makeatletter\\@namedef{emph}{x}\\makeatother", False),
        ("\\makeatletter\\@namedef{@foo}{x}\\makeatother", True),
        ("\\ifx\\a\\b \\NewDocumentCommand\\y{m}{x}\\fi", False),
        ("\\ifx\\a\\b \\ProvideDocumentCommand{\\y}{m}{x}\\fi", False),
        ("\\ifx\\a\\b \\DeclareDocumentCommand{\\y}{m}{x}\\fi", False),
        ("\\ifx\\a\\b \\newenvironment{panel}{}{}\\fi", False),
        ("\\ifx\\a\\b \\renewenvironment*{panel}{}{}\\fi", False),
        ("\\makeatletter\\renewenvironment{@panel}{}{}\\makeatother", True),
        ("\\ifx\\a\\b \\makeatletter \\else \\makeatother \\fi", False),
        ("\\ifx\\a\\b \\makeatletter x\\makeatother \\else y \\fi", True),
        ("\\ifcase\\c 1 \\or \\makeatletter \\or 3 \\fi", False),
        # Known gaps: four rare blocks that TeX would end where the reader skips, which the
        # reader's tokens read otherwise, and refuse as before (round 2 of #674).
        ("\\makeatletter\\let\\if@mine\\iftrue\\makeatother", False),
        ("\\makeatletter\\def\\let@x{}\\makeatother", False),
        ("\\makeatletter\\def\\fi@x{}\\makeatother", False),
        ("\\ifx\\a\\b {\\makeatletter x} \\fi", False),
    ],
)
def test_a_block_is_skipped_to_its_matching_end_or_refused(block: str, skipped: bool) -> None:
    text = f"Of 4100 reports. {block} Then 77 died."
    at = text.index("\\", text.index("reports"))
    reading = read(text, body=True)
    if skipped:
        assert reading.refusals == () and [s.offset for s in reading.skipped] == [at], block
        assert reading.skipped[0].end == text.index(" Then")
        assert reading.masked.endswith(" Then 77 died.")
    else:
        assert reading.skipped == () and [r.offset for r in reading.refusals] == [at], block
        assert set(reading.masked[at:]) <= {NUL, "\n"}
    # A `\newif` in the body defines a conditional, and is no block; one in a comment or a
    # `\verb` defines nothing (round 1 of #674).
    defined = read("\\newif\\iffound Then 77 died.", body=True)
    assert defined.refusals == defined.skipped == () and "77" in defined.masked
    for written in ("% see \\newif\n", "\\verb|\\newif|"):
        conditional = read(f"{written}\\ifx\\a\\b Hidden 55\\fi Then 77.", body=True)
        assert len(conditional.skipped) == 1 and "55" not in conditional.masked, written
        assert "77" in conditional.masked
    # Known gaps: a comment between a `\newif` and its name, where TeX defines the name, and
    # the reader opens a block at it (round 2 of #674).
    noted = read("\\newif % note\n\\iffoo Hidden 55\\fi Then 77.", body=True)
    assert len(noted.skipped) == 1 and "55" not in noted.masked and "77" in noted.masked


@pytest.mark.parametrize(
    "block",
    [
        "\\makeatletter\\renewcommand{\\emph}[1]{\\textbf{#1}}\\makeatother",
        # Round 2 of #674: LaTeX's `\@namedef` and xparse's definitions, and `\def\emph@x`
        # in a conditional, where `@` is no letter and the name it defines is `\emph`.
        "\\makeatletter\\@namedef{emph}#1{\\textbf{#1}}\\makeatother",
        "\\ifx\\a\\b \\RenewDocumentCommand{\\emph}{m}{x}\\fi",
        "\\ifx\\a\\b \\def\\emph@x{}\\fi",
    ],
    ids=["renewcommand", "namedef", "RenewDocumentCommand", "def-at-delimited"],
)
def test_a_redefinition_in_a_block_stops_the_reading_as_before(block: str) -> None:
    """Round 1 of #674: skipped, a `\\renewcommand{\\emph}` in a `\\makeatletter` block was
    lost, and `\\emph` past it read as LaTeX's, where the base refused the block."""
    text = f"\\begin{{document}}\n{block}\nSee \\emph{{12 cases}}."
    reading = read(text)
    at = text.index("\\", len("\\begin{document}"))
    assert reading.skipped == () and [r.offset for r in reading.refusals] == [at], block
    said = ("\\makeatletter in the body changes how characters are read" if "makeat" in block
            else "\\ifx is not read: a conditional in the body prints one branch, and which "
            "is not read")  # fmt: skip
    assert reading.refusals[0].message == said
    assert "12" not in reading.masked


def test_a_delimited_definition_is_read_and_each_use_where_it_prints_refused() -> None:
    """Two real papers' templates (2026-10-23): `\\def\\bSig\\mathbf{\\Sigma}` and natbib's
    `\\def` of a delimited macro were refused, and the rest of the file read as typed. The
    definition is read, its parameter text blanked, and a use refused only where it would
    print, not in a blanked argument, the preamble or another definition's body."""
    preamble = ("\\documentclass{article}\n\\def\\bSig\\mathbf{\\Sigma}\n"
                "\\def\\pair(#1,#2){#1 to #2}\n\\newcommand{\\both}{\\bSig}\n\\bSig\n")  # fmt: skip
    quiet = preamble + "\\begin{document}\nNo use \\label{\\bSig} of 12.\n\\end{document}\n"
    reading = read(quiet)
    assert reading.refusals == () and reading.delimited == ("pair",)
    # `\bSig` has a parameter text and no parameter, `\mathbf`, which TeX stops on where it
    # does not follow a use (2026-10-23, `literal`).
    assert reading.literal == (("bSig", "\\mathbf"),)
    for used, name in (("in maths $\\bSig$", "\\bSig"), ("in prose \\pair(1,2)", "\\pair"),
                       ("in a caption \\caption{\\bSig}", "\\bSig")):  # fmt: skip
        text = preamble + f"\\begin{{document}}\nUsed {used}.\n\\end{{document}}\n"
        (refusal,) = read(text).refusals
        assert refusal.offset == text.rindex(name), used
        said = "delimited parameters" if name == "\\pair" else "TeX stops there"
        assert said in refusal.message, used
    # In the body the parameter text is blanked, and the definition's body is prose there.
    body = "\\def\\pair(#1,#2){#1 to #2}\n"
    masked = read(body, body=True).masked
    assert set(masked[body.index("(") : body.index("{")]) == {NUL} and " to " in masked


def test_a_definition_whose_parameter_text_is_spaces_or_a_comment_delimits_nothing() -> None:
    """Round 1 of real templates: TeX skips the spaces after a control word, and a comment to
    its line's end with the next line's spaces, so `\\def\\journal {Lancet}` and a `\\def` whose
    body is on the line after a `%` are ordinary macros; their uses are read, not refused."""
    for defined in ("\\def\\journal {Lancet}", "\\def\\journal%\n  {Lancet}",
                    "\\def\\journal#1 %note\n{#1}"):  # fmt: skip
        text = f"{defined}\n\\begin{{document}}\nIn \\journal{{x}} 12.\n\\end{{document}}\n"
        reading = read(text)
        delimited = defined.endswith("{#1}")
        assert reading.delimited == (("journal",) if delimited else ()), defined
        assert bool(reading.refusals) == delimited, defined
    assert read("\\def\\x%note\n{1}\n", body=True).comments == ((6, 11),)


def test_a_parameter_of_a_definition_inside_a_body_is_doubled_and_blanked() -> None:
    """natbib's `\\gdef\\NAT@biblabelnum##1{##1.}` in a body was read as delimited."""
    text = "\\newcommand{\\x}{\\gdef\\y##1{##1 is 5}}\n"
    reading = read(text, body=True)
    assert reading.refusals == () and reading.delimited == ()
    assert set(reading.masked[text.index("##1 is") : text.index(" is 5")]) == {NUL}
    assert "5" in reading.masked


def test_a_command_let_to_one_read_the_same_way_is_read_as_before() -> None:
    """`\\let\\footnote=\\endnote` in an Elsevier template was refused as `\\footnote`
    defined again; the endnotes package's note is the same prose, printed at the end."""
    text = ("\\documentclass{article}\n\\usepackage{endnotes}\n\\let\\footnote=\\endnote\n"
            "\\begin{document}\nA claim\\footnote{of 12 sites}.\n\\end{document}\n")  # fmt: skip
    reading = read(text)
    assert reading.refusals == ()
    assert "of 12 sites" in reading.masked and "endnote" not in reading.masked


def test_a_classs_front_matter_is_passed_over_and_its_abstract_read() -> None:
    """Elsevier's `frontmatter` holds the title, the addresses, the abstract, the highlights
    and the keywords, and Wiley's template types its issue and dates in the body: each is
    passed over, as Markdown's YAML header is, but the abstract, read under its heading, and
    the highlights, the paper's claims (Basile, 2026-10-23; round 1). So is an abstract in a
    box inside the front matter, BMC's `abstractbox`; one in a blanked argument is not
    lifted. A front matter command the author defines, as an article's preamble often defines
    `\\keywords`, is the author's, read as an unknown command is (round 1)."""
    text = ("\\documentclass{elsarticle}\n\\newcommand{\\keywords}[1]{Keywords: #1}\n"
            "\\begin{document}\n\\begin{frontmatter}\n\\title{A 10-year cohort}\n"
            "\\address[a]{Unit 1181}\n\\begin{abstractbox}\\begin{abstract}\nOf 4100 cases.\n"
            "\\end{abstract}\\end{abstractbox}\n\\begin{highlights}\n\\item Of 4371, 12\\%.\n"
            "\\end{highlights}\n\\begin{keyword}\nkey 77\n\\end{keyword}\n"
            "\\end{frontmatter}\n\\Volume{46}\\pagespan{1}{9}\\affil*[2]{Unit 1182}\n"
            "\\keywords{dose 5}\n\\section{Intro}\nBody 3.\n\\end{document}\n")  # fmt: skip
    reading = read(text)
    assert reading.refusals == () and reading.own == ("keywords",)
    for hidden in ("10-year", "1181", "77", "46", "9}", "1182"):
        start = text.index(hidden)
        assert set(reading.masked[start : start + len(hidden)]) <= {NUL, "}"}, hidden
    for printed in ("Of 4100 cases.", "Of 4371, 12", "dose 5", "Body 3."):
        assert printed in reading.masked, printed
    assert [heading.title for heading in reading.headings] == ["Abstract", "Intro"]
    assert "Of 12" not in read("\\author{\\begin{abstract}Of 12\\end{abstract}}",
                               body=True).masked  # fmt: skip
    # Round 2: in a group inside the front matter, `{\small ...}`, it is read all the same.
    grouped = ("\\begin{frontmatter}{\\small\\begin{abstract}Of 4100.\\end{abstract}}"
               "\\end{frontmatter}")  # fmt: skip
    assert "Of 4100." in read(grouped, body=True).masked


def test_a_file_input_inside_the_front_matter_is_read_as_it_is() -> None:
    """A file input from inside `frontmatter` starts there: passed over, but an abstract."""
    reading = read("\\address{Unit 1181}\n\\begin{abstract}Of 4100.\\end{abstract}\n",
                   body=True, environments=("frontmatter",))  # fmt: skip
    assert "1181" not in reading.masked and "Of 4100." in reading.masked
    abstract = read("Of 4100.\n", body=True, environments=("frontmatter", "abstract"))
    assert "Of 4100." in abstract.masked


def test_a_front_matter_command_the_author_defines_in_another_file_is_the_author_s() -> None:
    """Round 1 of real templates, part 2: an article's own `\\journal`, defined in its package
    and used in a file the entry inputs, prints what its definition says; its argument is
    read, as before the table held the name. One the class defines is passed over."""
    from manuscript_guard.text.latex.structure import read_tree

    files = {"main.tex": "\\documentclass{article}\n\\usepackage{macros}\n\\begin{document}\n"
                         "\\input{a}\n\\Volume{46}\n\\end{document}\n",
             "a.tex": "As in \\journal{Lancet 2019}.\n"}  # fmt: skip
    document = read_tree(files, packages={"macros.sty": "\\newcommand{\\journal}[1]{#1}\n"})
    (main, macros, inputs) = document.sources
    assert "Lancet 2019" in inputs.reading.masked and "46" not in main.reading.masked
    assert document.refusals == ()
    # Round 2: the file that defines it says so, on the tree's second reading too.
    assert macros.reading.own == ("journal",)


def _hidden(text: str, masked: str, typed: str) -> bool:
    start = text.index(typed)
    return set(masked[start : start + len(typed)]) == {NUL}


def test_acmart_s_ccs_xml_is_passed_over_as_the_class_excludes_it() -> None:
    """2311.00579: acmart excludes `CCSXML` as the comment package's environment, and its
    concepts' ids and weights were numbers; `\\ccsdesc[300]{...}`, the concept the title page
    prints, is front matter, its weight none of the paper's (2026-10-23)."""
    text = ("\\begin{CCSXML}\n<ccs2012>\n <concept_id>10002978.10003001</concept_id>\n"
            " <concept_significance>300</concept_significance>\n</ccs2012>\n\\end{CCSXML}\n"
            "\\ccsdesc[500]{Security and privacy~Embedded systems}\nOf 4100.\n")  # fmt: skip
    reading = read(text, body=True)
    assert reading.refusals == () and reading.listings == () and reading.unprinted == ()
    for typed in ("10002978.10003001", "300", "500", "Embedded systems"):
        assert _hidden(text, reading.masked, typed), typed
    assert "Of 4100." in reading.masked


def test_elsevier_s_cas_title_page_is_passed_over_but_the_title() -> None:
    """2604.24157, Elsevier's CAS double column: the title's option list with a space before
    it, an ORCID iD in an option after the author's name, the marks of the title page's notes,
    the CRediT roles and the running heads were read as the text (2026-10-23). The title is
    read, as before."""
    text = ("\\title [mode = title]{OxyPOM in 2024}\n\\tnotemark[1]\n"
            "\\shorttitle{Oxygen 7}\n\\shortauthors{A and B 8}\n"
            "\\author{Ovidio}[%type=editor,\n   orcid=0000-0001-6060-2001]\n\\cormark[1]\n"
            "\\fnmark[2]\n\\credit{Writing 3}\n\\nonumnote{Grant 4}\n"
            "\\affiliation[1]{organization={Hereon}, postcode={21502}}[type=alt]\n"
            "\\author[1,3]{Carsten}[orcid=0000-0003-3483-6036]\nOf 4100.\n")  # fmt: skip
    reading = read(text, body=True)
    assert reading.refusals == ()
    for typed in ("mode = title", "[1]", "Oxygen 7", "A and B 8", "0000-0001-6060-2001",
                  "[2]", "Writing 3", "Grant 4", "21502", "type=alt", "1,3",
                  "0000-0003-3483-6036"):  # fmt: skip
        assert _hidden(text, reading.masked, typed), typed
    assert "OxyPOM in 2024" in reading.masked and "Of 4100." in reading.masked
    # elsarticle's marks name a note's label inside the title and the author.
    marked = "\\title{A cohort\\tnoteref{t1}}\\author{A\\corref{c1}\\fnref{f2}}"
    assert _hidden(marked, read(marked, body=True).masked, "t1")


def test_springer_s_running_title_and_corresponding_author_are_passed_over() -> None:
    """2112.07039, Springer's `sn-jnl`: `\\title[short]{long}` read the title twice, its
    short form being the running head, and `\\author*[1]` read a 1 (2026-10-23)."""
    text = "\\title[Limits 12]{Limits of 4100}\n\\author*[1]{Omar}\n\\affil*[1]{Duke}\n"
    reading = read(text, body=True)
    assert reading.refusals == ()
    assert _hidden(text, reading.masked, "Limits 12") and _hidden(text, reading.masked, "*[1]")
    assert "Limits of 4100" in reading.masked


def test_a_colon_inside_a_tikz_labels_braces_is_its_text() -> None:
    """TikZ cuts a label's angle at a colon outside braces only, and its manual has a label
    that holds a colon braced: a colon inside braces is the label's text, and the brace before
    it is read (round 2 of #443: the reader jumped past that brace and refused the file as
    unbalanced, where main read the picture)."""
    for label, printed in (("{{1:2}}", "1:2"), ("{[red]{09:30}}", "09:30"),
                           ("{90:{Time 11:45}}", "Time 11:45")):  # fmt: skip
        text = f"\\begin{{tikzpicture}}\\node[label={label}] {{A}};\\end{{tikzpicture}}\n"
        reading = read(text, body=True)
        assert reading.refusals == (), label
        assert printed in reading.masked, label
    text = "\\begin{tikzpicture}\\node[label={\\ref{fig:a}}] {A};\\end{tikzpicture}\n"
    assert read(text, body=True).refusals == ()


def test_a_tikz_picture_is_passed_over_as_a_picture_file_is() -> None:
    """2311.00579, 2401.04687 and 2405.21051: a TikZ picture's options, its sizes and shifts,
    and the old `\\tikzstyle{name} = [...]` were read as the text (2026-10-23). The picture is
    passed over as `\\includegraphics` passes over a picture's file, and so is one in a
    definition's body, whose `\\end` stands in the same body. What it prints as text is read:
    a node's, in a path too, a label's and a pin's past their angle, and pgfplots' axis labels
    and legend (round 1 of #443: a flow diagram's 4371 was seen by no gate)."""
    text = ("\\tikzset{>={Latex[width=2mm]}}\n\\tikzstyle{latent} = [circle, line width=0.35mm]\n"
            "\\tikzstyle{data}=[draw,\n  minimum height=2em]\n"
            "\\newcommand{\\dot}[1]{\\begin{tikzpicture}[baseline={(0,-0.5ex)}]\n"
            "  \\node[minimum size=1em, inner sep=1pt] {#1 of 77};\\end{tikzpicture}}\n"
            "\\begin{tikzpicture}[remember picture, shift={(1,2)}]\n"
            "\\node[anchor=north east,xshift=-4cm] (box) at (3,4) {n = 412 $x^3$};\n"
            "\\draw (5,6) -- (7,8) node[above, pos=0.25] {excluded 61}; % node {99}\n"
            "\\node[label={[red]270:Label 33}, pin=45:Pin 44] {};\n"
            "\\begin{axis}[xmin=5, xlabel={Day 21}, title=Arm 22]\n"
            "\\addplot coordinates {(1,6)};\\addlegendentry{Dose 23}\\end{axis}\n"
            "\\node[node contents={Box 24}, minimum width=9mm];\n"
            "\\matrix[matrix of nodes, row sep=8mm] { Cell 25 \\\\ };\n"
            "\\matrix[row sep=7mm] { \\node {Node 26}; \\\\ };\n"
            "\\end{tikzpicture}\nOf 4100 \\dot{a}.\n")  # fmt: skip
    reading = read(text, body=True)
    assert reading.refusals == ()
    for typed in ("2mm", "0.35mm", "2em", "0.5ex", "1em", "1pt", "(1,2)", "-4cm", "(3,4)",
                  "(5,6)", "(7,8)", "pos=0.25", "{99}", "270:", "45:", "xmin=5", "(1,6)", "9mm",
                  "8mm", "7mm"):  # fmt: skip
        assert _hidden(text, reading.masked, typed), typed
    for printed in ("of 77", "n = 412", "x^3", "excluded 61", "Label 33", "Pin 44", "Day 21",
                    "Arm 22", "Dose 23", "Box 24", "Cell 25", "Node 26", "Of 4100"):  # fmt: skip
        assert printed in reading.masked, printed
    # A picture opened in one definition and closed in another is text expanded at each use,
    # as any environment in a body is: its options are passed over, and nothing is left open.
    split = ("\\newenvironment{pic}{\\begin{tikzpicture}[x=2cm]}{\\end{tikzpicture}}\n"
             "\\begin{pic}Of 4100\\end{pic}\n")  # fmt: skip
    reading = read(split, body=True)
    assert reading.refusals == () and _hidden(split, reading.masked, "2cm")
    # So is one whose `\end` in the same body stands in a comment.
    commented = ("\\newcommand{\\pa}{\\begin{tikzpicture}[x=3cm]% \\end{tikzpicture}\n}"
                 "\\newcommand{\\pb}{\\end{tikzpicture}}\nOf 4100.\n")  # fmt: skip
    reading = read(commented, body=True)
    assert reading.refusals == () and _hidden(commented, reading.masked, "3cm")
    assert "Of 4100." in reading.masked
    # A file input inside a picture starts there: passed over, but what it prints.
    inside = read("\\node[xshift=5cm] {412};\n", body=True, environments=("tikzpicture",))
    assert "412" in inside.masked and "5cm" not in inside.masked


def test_an_input_encoding_other_than_utf8_is_refused_where_the_file_is_not_ascii() -> None:
    """A file all of ASCII reads the same in each encoding inputenc knows, so one it declares
    is accepted (2026-10-23: `latin9` in such a file was refused); one with a character past
    ASCII is read as UTF-8, and refused."""
    text = "\\documentclass{article}\n\\usepackage[latin1]{inputenc}\n\\begin{document}\n"
    accented = text + "Caf\N{LATIN SMALL LETTER E WITH ACUTE}\n\\end{document}"
    assert [r.code for r in read(accented).refusals] == ["tex-refused"]
    assert read(text + "Cafe\n\\end{document}").refusals == ()
    assert read(text + "Cafe\n\\end{document}").encodings == (text.index("\\usepackage"),)
    assert read(accented.replace("latin1", "utf8")).refusals == ()


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
    ("text", "printed"),
    [
        # Round 1 of #380: numbers LaTeX prints that the reader had blanked.
        ("\\iffalse Old: 10 cases.\\else New: 12 cases.\\fi", "12"),
        ("\\begin{align}a &= b \\\\\n[0.5, 1.2] &= c\\end{align}", "0.5, 1.2"),
        ("\\iffalse a % \\fi\n b\\fi Then 42.", "42"),
    ],
)
def test_what_round_one_found_blanked_is_read(text: str, printed: str) -> None:
    reading = read(text, body=True)
    assert reading.refusals == ()
    assert printed in reading.masked


def test_a_definitions_default_in_the_preamble_is_read_as_its_body_is() -> None:
    text = (
        "\\documentclass{article}\n\\newcommand{\\ci}[1][95]{#1\\% CI}\n"
        "\\begin{document}x\\end{document}"
    )
    masked = mask(text)
    start = text.index("95")
    assert masked[start : start + 2] == "95"


def test_a_file_refused_before_its_document_is_read_as_body() -> None:
    """Round 1 of #380: one whose only `\\begin{document}` is in a comment, and which is
    refused, was left blanked as preamble up to the refusal."""
    assert "4100" in mask("% \\begin{document}\nOf 4100. \\catcode")


@pytest.mark.parametrize(
    "text",
    [
        "\\documentclass{article}\n\\newenvironment{tight}{\\begin{itemize}}{\\end{itemize}}\n"
        "\\begin{document}x\\end{document}",
        "$A \\iff B$ 3",
        "$x$$y$ 4",
    ],
)
def test_what_round_one_found_refused_wrongly_is_read(text: str) -> None:
    assert read(text, body=None if text.startswith("\\doc") else True).refusals == ()


@pytest.mark.parametrize(
    "text", ["\\RequirePackage[latin1]{inputenc} x", "\\inputencoding{latin1} x"]
)
def test_every_way_of_setting_another_encoding_is_refused(text: str) -> None:
    accented = text + " \N{LATIN SMALL LETTER E WITH ACUTE}"
    assert [r.code for r in read(accented, body=True).refusals] == ["tex-refused"]
    assert read(text, body=True).refusals == ()


@pytest.mark.parametrize(
    "unit",
    [
        "\\emph{a} ", "{", "% c\n", "\\verb|x| ", "$x$ ", "\\label{x} ", "\\begin{itemize} ",
        "\\cite[p.~1]{k} ", "``q'' ", "\\iffalse x \\fi ", "\\cmidrule ", "\\usepackage[ ",
    ],
)  # fmt: skip
def test_the_reader_is_linear_in_the_file(assert_linear, unit: str) -> None:
    assert_linear(lambda count: unit * count, lambda text: read(text, body=True), 2000,
                  f"the LaTeX reader on {unit!r}")  # fmt: skip


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        # Round 4 of #380: amsmath's cases and matrices, a robust command's default in the
        # preamble, and an xparse default.
        ("$\\begin{cases}a \\\\ [0.5, 1.2] b\\end{cases}$", "0.5, 1.2"),
        ("$\\begin{pmatrix}a \\\\ [0.5, 1.2] b\\end{pmatrix}$", "0.5, 1.2"),
        ("\\documentclass{a}\n\\DeclareRobustCommand{\\ci}[1][95]{CI #1}\n"
         "\\begin{document}\\ci\\end{document}", "95"),
        ("\\NewDocumentCommand{\\ci}{O{95}}{CI #1}", "95"),
        ("\\documentclass{a}\n\\NewDocumentCommand{\\ci}{O{95}}{CI #1}\n"
         "\\begin{document}\\ci\\end{document}", "95"),
    ],
)  # fmt: skip
def test_what_round_four_found_blanked_is_read(text: str, printed: str) -> None:
    """Read, and not left as typed past a refusal (round 5)."""
    reading = read(text, body=None if text.startswith("\\doc") else True)
    assert reading.refusals == () and printed in reading.masked


def test_what_round_three_found_is_read_as_latex_reads_it(assert_linear) -> None:
    """Round 3 of #380: the robust and xparse definers' bodies print; an array's `\\\\` skips
    spaces; `\\)` closes no environment; finding the document is linear."""
    for define in ("\\DeclareRobustCommand{\\n}{4100}", "\\NewDocumentCommand{\\n}{}{4100}"):
        document = f"\\documentclass{{a}}\n{define}\n\\begin{{document}}x\\end{{document}}"
        assert "4100" in mask(document)
    assert "2pt" not in mask("$\\begin{array}{l}a \\\\ [2pt] b\\end{array}$", body=True)
    assert [r.code for r in read("\\begin{\\)}x\\)", body=True).refusals] == ["tex-unbalanced"]
    assert_linear(lambda count: "\\%" * count + "%" + "\\begin{document}" * count, read, 500,
                  "finding the document on a commented line")  # fmt: skip


def test_what_round_two_found_is_read_as_latex_reads_it() -> None:
    """Round 2 of #380: a preamble refusal keeps its place; a minipage's width in a definition
    is blanked; the kernel's `\\\\` takes a length after a space; `\\\\else` is no `\\else`."""
    preamble = "\\documentclass{article}\n\\makeatletter\\expandafter\n"
    refused = read(preamble + "\\begin{document}x\\end{document}").refusals
    assert [r.message.split(" is ")[0] for r in refused] == ["\\expandafter"]
    defined = (
        "\\documentclass{article}\n\\newenvironment{half}{\\begin{minipage}{0.45\\linewidth}}"
        "{\\end{minipage}}\n\\begin{document}x\\end{document}"
    )
    assert "0.45" not in mask(defined) and read(defined).refusals == ()
    assert "2pt" not in mask("\\begin{tabular}{l}a \\\\ [2pt]\\end{tabular}", body=True)
    escaped = mask("\\iffalse A\\\\else B \\else C\\fi", body=True)
    assert "B" not in escaped and "C" in escaped


def test_the_reader_is_linear_in_conditionals_on_a_commented_line(assert_linear) -> None:
    """Round 2 of #380: on a commented line each conditional read the line again."""
    assert_linear(lambda count: "\\iffalse %" + "\\fi" * count + "\n\\fi",
                  lambda text: read(text, body=True), 2000,
                  "the LaTeX reader on conditionals in a comment")  # fmt: skip


def test_the_reader_is_linear_in_braces_and_cells(assert_linear) -> None:
    """Round 1 of #380: each `&` walked every open brace to find whether it was in a table."""
    assert_linear(lambda count: "{" * count + "&" * count, lambda text: read(text, body=True),
                  2000, "the LaTeX reader on braces then cells")  # fmt: skip


# What 17 papers from arXiv found refused that LaTeX reads (2026-10-23). A refusal makes the
# rest of its file read as typed, so each cost a whole file.

PANDOC = ("\\documentclass{article}\n\\NewDocumentCommand\\citeproctext{}{}\n"
          "\\NewDocumentCommand\\citeproc{mm}{%\n  \\begingroup\\def\\citeproctext{#2}"
          "\\cite{#1}\\endgroup}\n\\newcommand{\\excite}[1]{#1}\n\\begin{document}\n")  # fmt: skip


@pytest.mark.parametrize(
    ("used", "refused"),
    [
        # IEEE Computer Society's thanks to the authors holds `cite` inside a word; an author's
        # `\excite` is an English word; pandoc's citeproc commands are its own, a citation as
        # citeproc printed it blanked as a citation is.
        ("\\IEEEcompsocitemizethanks{\\IEEEcompsocthanksitem Unit 7.}", ""),
        ("We \\excite{electrons 7}", ""),
        ("As Smith (\\citeproc{ref-smith2020}{2020}) says 7", ""),
        # A name that holds `cite` anywhere else is a citation's, its keys hidden from G7
        # (round 1 of #442: `\mycitep` passed under a rule for its start and end).
        ("As \\mycite{smith2020} says", "\\mycite"),
        ("As \\citeZ{smith2020} says", "\\citeZ"),
        ("As \\mycitep{smith2020} says", "\\mycitep"),
        ("As \\mycites{a}{b} say", "\\mycites"),
        # An English word that holds `cite` is exempt only as the name's start: one inside a
        # name is no word of it (round 2 of #442: `\maincite` lost "incite" and passed).
        ("As \\maincite{smith2020} says", "\\maincite"),
        ("As \\barecite{smith2020} says", "\\barecite"),
        ("As \\pincite{smith2020} says", "\\pincite"),
        ("As \\citemany{a,b} say", "\\citemany"),
        ("We \\recited{the oath 7}", ""),
    ],
)
def test_a_command_whose_name_is_a_citation_s_is_refused_and_one_with_cite_inside_is_not(
    used: str, refused: str
) -> None:
    text = PANDOC + used + ".\n\\end{document}\n"
    reading = read(text)
    assert [r.offset for r in reading.refusals] == ([text.index(refused)] if refused else [])
    if not refused:
        body = reading.masked[text.index("\\begin{document}") :]
        assert "2020" not in body and "7" in body


def test_pandoc_s_reference_list_under_citeproc_is_read() -> None:
    """pandoc's template defines `CSLReferences` with a comment between its arguments and
    `\\citeproctext`, which labels each entry: the list is read (2026-10-23)."""
    text = (PANDOC.replace("\\begin{document}\n", "")
            + "\\newenvironment{CSLReferences}[2] % #1 hanging-indent, #2 entry-spacing\n"
            "{\\begin{list}{}{%\n  \\setlength{\\itemindent}{0pt}\n  \\ifodd #1\n"
            "  \\setlength{\\leftmargin}{1.5em}\n  \\fi\n"
            "  \\setlength{\\itemsep}{#2\\baselineskip}}}\n{\\end{list}}\n\\begin{document}\n"
            "\\begin{CSLReferences}{1}{0}\n\\bibitem[\\citeproctext]{ref-a}\nA. 2020.\n"
            "\\end{CSLReferences}\n\\end{document}\n")  # fmt: skip
    reading = read(text)
    assert reading.refusals == ()
    comment = text.index("% #1")
    assert (comment, text.index("\n", comment)) in reading.comments
    assert "hanging" not in reading.masked


@pytest.mark.parametrize(
    ("between", "taken"),
    [
        (" % note\n", True),
        ("\n% note\n  % more\n", True),
        (" % note\n\n", False),
        ("\n\n", False),
    ],
)
def test_a_comment_between_a_command_and_its_argument_is_passed_over_as_tex_does(
    between: str, taken: bool
) -> None:
    """TeX looks for an argument past spaces, one line break, and a comment with its line's
    break and the next line's spaces; a blank line ends the paragraph and the search
    (2026-10-23)."""
    text = f"\\label{between}{{s12}} after"
    reading = read(text, body=True)
    assert reading.refusals == ()
    assert ("12" not in reading.masked) == taken, between
    for start, end in reading.comments:
        assert text[start] == "%" and set(reading.masked[start:end]) == {NUL}


def test_a_reference_list_bibtex_wrote_is_read_with_its_header() -> None:
    """natbib's and REVTeX's lists open with `\\providecommand`, a conditional on
    `\\csname`, and REVTeX's `\\makeatletter` with `\\catcode` in a definition: the list is
    read to its end, its span kept for G6, the pack and the blind check, and `@` is no letter
    past it, as TeX's group puts it back (2026-10-23: each was refused at its header)."""
    natbib = ("\\providecommand{\\natexlab}[1]{#1}\n\\providecommand{\\url}[1]{\\texttt{#1}}\n"
              "\\expandafter\\ifx\\csname urlstyle\\endcsname\\relax\n"
              "  \\providecommand{\\doi}[1]{doi: #1}\\else\n"
              "  \\providecommand{\\doi}{doi:\\begingroup \\urlstyle{rm}\\Url}\\fi\n")  # fmt: skip
    revtex = ("\\makeatletter\n\\providecommand \\@ifx [1]{%\n \\ifx #1\\expandafter "
              "\\@firstoftwo\n \\else \\expandafter \\@secondoftwo\n \\fi\n}%\n"
              "\\providecommand \\enquote [1]{``#1''}%\n\\providecommand \\citenamefont [1]{#1}%\n"
              "\\providecommand \\@sanitize@url [0]{\\catcode `\\\\12\\catcode `\\$12}%\n"
              "\\let\\auto@bib@innerbib\\@empty\n")  # fmt: skip
    for header in (natbib, revtex):
        listed = ("\\begin{thebibliography}{9}\n" + header
                  + "\\bibitem[{\\citenamefont{Smith}(2011)}]{a} Smith A. 2011.\n"
                  "\\end{thebibliography}")  # fmt: skip
        # `\iffalse@` prints its `\else` branch, which a conditional skipped would not.
        text = ("\\begin{document}\nText \\cite{a}.\n" + listed
                + "\nAfter \\iffalse@ 9\\else 8\\fi.\n")  # fmt: skip
        reading = read(text)
        assert reading.refusals == reading.skipped == (), header
        start = text.index("\\begin{thebibliography}")
        assert reading.references == ((start, start + len(listed)),)
        assert "Smith A. 2011" in reading.masked and "9" not in reading.masked[-20:]
        assert "8" in reading.masked[-20:]
    # Outside a definition's body there, `\catcode` changes what is read, and is refused.
    changed = "\\begin{thebibliography}{9}\n\\catcode`\\@=11\n\\end{thebibliography}"
    assert [r.code for r in read(changed, body=True).refusals] == ["tex-refused"]
    # Round 1 of #442: the header ends at the first `\bibitem`, past which a conditional is
    # not read through: skipped to its `\fi` (2026-11-13); a citation in an entry is one,
    # and one the reader does not know is refused.
    entries = "\\begin{thebibliography}{9}\n\\bibitem{a} A.\n{} \n\\end{thebibliography}"
    for entry, refused in (("\\ifx\\a\\b x\\fi", ""), ("See \\mycitep{b}", "\\mycitep"),
                           ("See \\citeA{b}", "")):  # fmt: skip
        text = entries.replace("{} ", entry)
        reading = read(text, body=True)
        assert [r.offset for r in reading.refusals] == ([text.index(refused)] if refused
                                                        else []), entry  # fmt: skip
        assert [r.offset for r in reading.skipped] == ([text.index("\\ifx")] if "ifx" in entry
                                                       else []), entry  # fmt: skip
        if "cite" in entry and not refused:
            assert [(found.key, found.narrative) for found in reading.cited] == [("b", True)]
    # Outside the list, the header's commands are refused as before, or skipped where they
    # open a block that ends in the file.
    for outside in ("\\expandafter\\x", "\\ifx\\a\\b", "\\makeatletter"):
        assert [r.code for r in read(outside, body=True).refusals] == ["tex-refused"], outside
    assert [r.code for r in read("\\ifx\\a\\b\\fi", body=True).skipped] == ["tex-refused"]


def test_providecommand_of_a_known_command_defines_nothing_and_renewcommand_is_refused() -> None:
    """`\\providecommand` of a command that is defined changes nothing, in the preamble or
    the body (2026-10-23); `\\renewcommand` of it is still refused, and so is a `\\def` after
    a `\\providecommand`, which defines the command again."""
    for text in ("\\documentclass{a}\n\\providecommand{\\url}[1]{\\texttt{#1}}\n"
                 "\\begin{document}x\\end{document}",
                 "\\providecommand*{\\emph}[1]{#1} x",
                 "\\ProvideDocumentCommand{\\emph}{m}{#1} x"):  # fmt: skip
        assert read(text, body=None if text.startswith("\\doc") else True).refusals == ()
    for text in ("\\renewcommand{\\url}[1]{#1}", "\\providecommand{\\x}{1}\\def\\url{2}"):
        assert [r.code for r in read(text, body=True).refusals] == ["tex-refused"], text


@pytest.mark.parametrize("name", ["unit", "num", "SI", "qty"])
def test_a_package_s_command_is_the_author_s_where_no_package_gives_it(name: str) -> None:
    """`\\newcommand{\\unit}` with no siunitx defines the author's command, read as an unknown
    one is, its argument read (2026-10-23: it was refused as defined again). Where siunitx is
    loaded, or units for `\\unit`, the preamble defines the package's command again, and its
    use is refused where it prints (Basile, 2026-11-11)."""
    define = f"\\newcommand{{\\{name}}}[1]{{\\mbox{{#1}}}}\n"
    text = ("\\documentclass{article}\n" + define
            + f"\\begin{{document}}\nThe vector $\\{name}{{k}}$ of 12.\n\\end{{document}}\n")
    reading = read(text)
    assert reading.refusals == () and reading.own == (name,)
    assert "k" in reading.masked[text.index("$") :]
    givers = {"unit": ("siunitx", "units"), "qty": ("siunitx", "physics")}.get(name, ("siunitx",))
    for package in givers:
        loaded = text.replace(define, f"\\usepackage{{{package}}}\n" + define)
        (refusal,) = read(loaded).refusals
        assert refusal.offset == loaded.index(f"$\\{name}") + 1 and "again" in refusal.message


def test_a_package_s_command_defined_where_another_file_loads_the_package_is_refused() -> None:
    """The tree tells each file what the others load: siunitx in the author's package makes
    `\\unit` the reader's in the entry file, and its definition there defined again, so its
    use in the file the entry inputs is refused where it prints (Basile, 2026-11-11)."""
    from manuscript_guard.text.latex.structure import read_tree

    main = ("\\documentclass{article}\n\\usepackage{macros}\n\\newcommand{\\unit}[1]{#1}\n"
            "\\begin{document}\n\\input{a}\n\\end{document}\n")  # fmt: skip
    files = {"main.tex": main, "a.tex": "The vector $\\unit{k}$.\n"}
    ((path, refusal),) = read_tree(files, packages={"macros.sty": "\\RequirePackage{siunitx}\n"}
                                   ).refusals  # fmt: skip
    assert path == "a.tex" and refusal.offset == files["a.tex"].index("\\unit")
    assert "defines it again" in refusal.message
    document = read_tree(files, packages={"macros.sty": "\\RequirePackage{xcolor}\n"})
    assert document.refusals == ()
    assert "k" in document.sources[-1].reading.masked


def test_an_ascii_file_s_encoding_is_held_to_every_file_of_its_tree() -> None:
    """TeX reads each file of the tree in the encoding one sets: an ASCII entry file's
    `latin9` is refused where a file it inputs is not ASCII (2026-10-23)."""
    from manuscript_guard.text.latex.structure import read_tree

    main = ("\\documentclass{article}\n\\usepackage[latin9]{inputenc}\n\\begin{document}\n"
            "\\input{a}\n\\end{document}\n")  # fmt: skip
    assert read_tree({"main.tex": main, "a.tex": "Cafe.\n"}).refusals == ()
    ((path, refusal),) = read_tree({"main.tex": main,
                                    "a.tex": "Caf\N{LATIN SMALL LETTER E WITH ACUTE}.\n"}
                                   ).refusals  # fmt: skip
    assert path == "main.tex" and refusal.offset == main.index("\\usepackage[latin9]")
    assert "a.tex" in refusal.message


def test_a_parameter_text_with_no_parameter_prints_its_body_and_is_passed_over() -> None:
    """`\\def\\eg/{e.g.\\@}` takes nothing: each use prints its body, and the `/` after it is
    TeX's, passed over (2026-10-23: refused as delimited parameters, in prose and in a
    citation's note). A package of the author's defines them under `\\@ifdefinable`, and the
    file that uses them is told. A use not followed by what the definition says is refused
    where it prints, since TeX stops there."""
    from manuscript_guard.text.latex.structure import read_tree

    package = ("\\makeatletter\n  \\@ifdefinable{\\eg}{\\def\\eg/{e.g.\\@}}\n\\makeatother\n"
               "\\def\\half.5{one half}\n")  # fmt: skip
    main = ("\\documentclass{article}\n\\usepackage{shortcuts}\n\\begin{document}\n"
            "Work \\citep[\\eg/][]{a} and \\eg/ more, \\half.5 and \\eg\n/ of 12.\n"
            "\\end{document}\n")  # fmt: skip
    document = read_tree({"main.tex": main}, packages={"shortcuts.sty": package})
    assert document.refusals == ()
    masked = document.sources[0].reading.masked
    assert "/" not in masked and ".5" not in masked and "of 12." in masked
    assert document.sources[1].reading.literal == (("eg", "/"), ("half", ".5"))
    stopped = main.replace("\\half.5", "\\half")
    ((_path, refusal),) = read_tree({"main.tex": stopped},
                                    packages={"shortcuts.sty": package}).refusals  # fmt: skip
    assert refusal.offset == stopped.index("\\half")
    # Round 1 of #442: a space after a control word in the parameter text is no token, so
    # `\def\x\relax /{a}` is followed by `\relax/`, as TeX reads it.
    relaxed = "\\def\\x\\relax /{a}\nUse \\x\\relax/ here, \\x\\relax\n  / there.\n"
    reading = read(relaxed, body=True)
    assert reading.refusals == () and "/" not in reading.masked


# The corpus run of 2026-11-11: in 3 of 20 LaTeX preprints one construct of the template
# was refused, the rest of its file read as typed, and G6 and G14 reported LaTeX source and
# commented-out template text, or read almost nothing.
_HEAD = "\\documentclass{article}\n"
_BODY = "\\begin{document}\nOf 4100 reports, 12 were fatal. % TODO: the 2019 data\n"


@pytest.mark.parametrize(
    ("defined", "name", "file"),
    [
        # A cross-reference whose body holds another command beside the one it refers by.
        ("\\def\\eqref#1{\\textbf{\\ref{#1}}}\n", "eqref", "math_commands.tex"),
        # iclr2021_conference.sty.
        ("\\def\\addcontentsline#1#2#3{}\n", "addcontentsline", "iclr.sty"),
        # A font switch round arxiv.sty's `\@startsection`.
        ("\\renewcommand\\section{\\bfseries\\@startsection{section}{1}{\\z@}{-1ex}{1ex}{}}\n",
         "section", "arxiv.sty"),
        ("\\renewcommand{\\section}[1]{\\textbf{#1}}\n", "section", "main.tex"),
    ],
    ids=["eqref-in-bold", "iclr-sty", "font-round-startsection", "preamble"],
)
def test_a_known_command_the_preamble_defines_again_is_read_and_refused_where_used(
    defined: str, name: str, file: str
) -> None:
    """Basile, 2026-11-11 ("Read more, and be honest"): a known command defined again in the
    preamble, a file input from it or the author's package is read there, and refused only
    where it prints, since what it prints is the author's; past that use nothing of the
    file is read, its comments no more than the rest. In the body, the definition is still
    refused where it stands."""
    from manuscript_guard.text.latex.structure import read_tree

    preamble = {"main.tex": defined, "math_commands.tex": "\\input{math_commands}\n",
                "iclr.sty": "\\usepackage{iclr}\n", "arxiv.sty": "\\usepackage{arxiv}\n"}[file]
    files = {"main.tex": _HEAD + preamble + _BODY + "\\end{document}\n"}
    packages = {}
    if file == "math_commands.tex":
        files[file] = defined
    elif file.endswith(".sty"):
        packages[file] = defined
    document = read_tree(files, packages=packages)
    assert document.refusals == ()
    assert "Of 4100 reports, 12 were fatal." in document.sources[0].reading.masked
    used = f"See \\{name}{{a}}{'{b}{c}' if name == 'addcontentsline' else ''}. % TODO: 2019\n"
    files["main.tex"] = _HEAD + preamble + _BODY + used + "Then 77 died.\n\\end{document}\n"
    ((path, refusal),) = read_tree(files, packages=packages).refusals
    assert (path, refusal.offset) == ("main.tex", files["main.tex"].index("\\" + name + "{a"))
    assert "defines it again" in refusal.message
    masked = read_tree(files, packages=packages).sources[0].reading.masked
    assert "Then 77" not in masked and "TODO: 2019" not in masked and "fatal." in masked
    # Written in the body, the definition is refused where it stands.
    inside = _HEAD + "\\begin{document}\n" + defined.replace("\\@", "\\") + "x\n\\end{document}"
    assert [r.code for r in read(inside).refusals] == ["tex-refused"]


_ARXIV_SECTION = ("\\renewcommand{\\section}{%\n  \\@startsection{section}{1}{\\z@}%\n"
                  "    {-2.0ex \\@plus -0.5ex \\@minus -.2ex}%\n    {1.5ex \\@plus 0.3ex}%\n"
                  "    {\\normalfont\\large\\bfseries}%\n}\n")  # fmt: skip


@pytest.mark.parametrize(
    ("defined", "file"),
    [
        # arxiv.sty's and style.sty's restyled heading, in the author's package, and in the
        # preamble past `\makeatletter`.
        (_ARXIV_SECTION, "arxiv.sty"),
        ("\\makeatletter\n\\def\\section{\\@startsection {section}{1}{\\z@}{-1ex}{1ex}"
         "{\\bfseries}}\n\\makeatother\n", "main.tex"),
        # ICLR's math_commands.tex, input from the preamble, and parentheses round it.
        ("\\def\\eqref#1{equation~\\ref{#1}}\n", "math_commands.tex"),
        ("\\renewcommand{\\eqref}[1]{Eq.~(\\ref{#1})}\n", "main.tex"),
    ],
    ids=["arxiv-sty", "def-in-preamble", "iclr-math-commands", "in-parentheses"],
)
def test_a_restyled_heading_and_a_cross_reference_defined_as_another_are_read(
    defined: str, file: str
) -> None:
    """Basile, 2026-11-12 ("Yes, read them"): a sectioning command whose whole body is
    LaTeX's own `\\@startsection` of its name, and a cross-reference defined as another of its
    argument among plain words, are read as before: the heading is a heading, the reference
    a cross-reference, and nothing is refused (corpus run of 2026-11-11: arxiv.sty's
    `\\section` and ICLR's `\\eqref`)."""
    from manuscript_guard.text.latex.structure import read_tree

    preamble = {"main.tex": defined, "math_commands.tex": "\\input{math_commands}\n",
                "arxiv.sty": "\\usepackage{arxiv}\n"}[file]
    files = {"main.tex": _HEAD + preamble + _BODY + "\\section{Results}\nAs \\eqref{e1} "
             "shows, 77 died.\n\\end{document}\n"}  # fmt: skip
    packages = {file: defined} if file.endswith(".sty") else {}
    if file == "math_commands.tex":
        files[file] = defined
    document = read_tree(files, packages=packages)
    assert document.refusals == ()
    reading = document.sources[0].reading
    assert [heading.title for heading in reading.headings] == ["Results"]
    assert len(reading.pointers) == 1 and "77 died." in reading.masked
    # Without `\makeatletter`, `\@startsection` is no command, and the use is refused.
    plain = files["main.tex"].replace("\\makeatletter\n", "")
    if file == "main.tex" and "startsection" in defined:
        refused = read_tree({"main.tex": plain}).refusals
        assert [refusal.code for _path, refusal in refused] == ["tex-refused"]


def test_nothing_found_past_an_unclosed_construct_is_kept() -> None:
    """Round 1 of #637, finding 4: a construct left open is refused where it opens, found at
    the end of the run, and the text past it blanked; but the headings, citations, bindings
    and inputs the run found past it were kept, so G7 and the sections read on. Nothing
    found past the refusal is kept."""
    text = (_HEAD + "\\begin{document}\n\\section{Methods}\nOf 4100 \\cite{a}.\n"
            "\\begin{figure}\n\\caption{One}\n\\section{Results}\nSo \\cite{x} and "
            "\\mg{results.k} \\ref{t}.\n\\input{more}\n\\end{document}\n")  # fmt: skip
    reading = read(text)
    ((code, at),) = [(r.code, r.offset) for r in reading.refusals]
    assert (code, at) == ("tex-unbalanced", text.index("\\begin{figure}"))
    assert [found.key for found in reading.cited] == ["a"]
    assert [heading.title for heading in reading.headings] == ["Methods"]
    assert reading.bindings == () and reading.inputs == () and reading.pointers == ()
    assert reading.floats == () and reading.figures == ()


def test_scientific_workplace_s_preamble_expandafter_is_passed_over() -> None:
    """A Scientific WorkPlace preamble adds spacing to `\\normalsize` with
    `\\expandafter\\def\\expandafter\\normalsize\\expandafter{...}`, and `\\expandafter` was
    refused there (corpus run of 2026-11-11). In the preamble such an `\\expandafter` is
    passed over and the `\\def` read; one that builds a name by `\\csname`, and one in the
    body, are refused as before."""
    swp = ("\\expandafter\\def\\expandafter\\normalsize\\expandafter{\\normalsize"
           "\\setlength\\abovedisplayskip{6pt}}\n")  # fmt: skip
    text = _HEAD + swp + _BODY + "\\end{document}\n"
    reading = read(text)
    assert reading.refusals == () and "fatal." in reading.masked
    assert "expandafter" not in reading.masked and "normalsize" not in reading.masked
    built = _HEAD + "\\expandafter\\def\\csname x\\endcsname{1}\n" + _BODY + "\\end{document}"
    assert [r.offset for r in read(built).refusals] == [len(_HEAD)]
    inside = _HEAD + _BODY + swp + "\\end{document}"
    assert [r.offset for r in read(inside).refusals] == [inside.index(swp)]


def test_a_declared_encoding_the_audit_reads_in_is_written_as_utf8_at_its_length() -> None:
    """`audit` reads a folder that declares latin1, latin9, cp1252 or ansinew in that
    encoding, and writes each declaration as UTF-8's at the same length, so that the reader
    reads the file's characters and every offset stays (Basile, 2026-11-11). A project's
    files are UTF-8, and a declaration in one that is not ASCII is refused as before."""
    from manuscript_guard.text.latex.encodings import as_utf8, declared

    accented = (_HEAD + "\\usepackage[T1]{fontenc}\n\\usepackage[latin1]{inputenc}\n"
                "% \\usepackage[latin9]{inputenc}\n" + _BODY
                + "Caf\N{LATIN SMALL LETTER E WITH ACUTE}.\n\\end{document}\n")  # fmt: skip
    assert declared([accented]) == "latin1"
    written = as_utf8(accented)
    assert len(written) == len(accented) and "[utf8  ]{inputenc}" in written
    assert "% \\usepackage[latin9]" in written  # a comment declares nothing
    assert read(written).refusals == () and [r.code for r in read(accented).refusals] == [
        "tex-refused"]
    for name in ("latin9", "cp1252", "ansinew"):
        assert declared([accented.replace("[latin1]", f"[{name}]")]) == name
    assert declared(["\\inputencoding{cp1252}", "\\usepackage[ansinew]{inputenc}"]) == "cp1252"
    assert declared(["\\usepackage[latin1]{inputenc}", "\\inputencoding{latin9}"]) is None
    assert declared(["\\usepackage[latin2]{inputenc}"]) is None
    assert as_utf8("\\inputencoding{ansinew} x") == "\\inputencoding{utf8   } x"
