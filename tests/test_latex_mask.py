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
def test_what_is_not_read_exactly_is_refused_and_the_rest_left_as_typed(
    text: str, code: str, at: int
) -> None:
    reading = read(text, body=True)
    assert [(r.code, r.offset) for r in reading.refusals] == [(code, at)]
    assert reading.masked[at:] == text[at:]


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
        text = "\\begin{document}\nText \\cite{a}.\n" + listed + "\nAfter \\iffalse@ 9\\fi.\n"
        reading = read(text)
        assert reading.refusals == (), header
        start = text.index("\\begin{thebibliography}")
        assert reading.references == ((start, start + len(listed)),)
        assert "Smith A. 2011" in reading.masked and "9" not in reading.masked[-12:]
    # Outside a definition's body there, `\catcode` changes what is read, and is refused.
    changed = "\\begin{thebibliography}{9}\n\\catcode`\\@=11\n\\end{thebibliography}"
    assert [r.code for r in read(changed, body=True).refusals] == ["tex-refused"]
    # Round 1 of #442: the header ends at the first `\bibitem`, past which a conditional is
    # refused; a citation in an entry is one, and one the reader does not know is refused.
    entries = "\\begin{thebibliography}{9}\n\\bibitem{a} A.\n{} \n\\end{thebibliography}"
    for entry, refused in (("\\ifx\\a\\b x\\fi", "\\ifx"), ("See \\mycitep{b}", "\\mycitep"),
                           ("See \\citeA{b}", "")):  # fmt: skip
        text = entries.replace("{} ", entry)
        reading = read(text, body=True)
        assert [r.offset for r in reading.refusals] == ([text.index(refused)] if refused
                                                        else []), entry  # fmt: skip
        if not refused:
            assert [(found.key, found.narrative) for found in reading.cited] == [("b", True)]
    # Outside the list, the header's commands are refused as before.
    for outside in ("\\expandafter\\x", "\\ifx\\a\\b\\fi", "\\makeatletter"):
        assert [r.code for r in read(outside, body=True).refusals] == ["tex-refused"], outside


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
    loaded, or units for `\\unit`, the definition is refused, as before."""
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
        assert refusal.offset == loaded.index(f"{{\\{name}}}") and "again" in refusal.message


def test_a_package_s_command_defined_where_another_file_loads_the_package_is_refused() -> None:
    """The tree tells each file what the others load: siunitx in the author's package makes
    `\\unit` the reader's in the entry file, and its definition there defined again."""
    from manuscript_guard.text.latex.structure import read_tree

    main = ("\\documentclass{article}\n\\usepackage{macros}\n\\newcommand{\\unit}[1]{#1}\n"
            "\\begin{document}\n\\input{a}\n\\end{document}\n")  # fmt: skip
    files = {"main.tex": main, "a.tex": "The vector $\\unit{k}$.\n"}
    ((path, refusal),) = read_tree(files, packages={"macros.sty": "\\RequirePackage{siunitx}\n"}
                                   ).refusals  # fmt: skip
    assert path == "main.tex" and refusal.offset == main.index("{\\unit}")
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
