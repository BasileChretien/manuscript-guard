"""A LaTeX manuscript's include tree (`text/latex/structure.py`) and what BUILD says of it
(DESIGN.md, "LaTeX manuscripts", "Includes"). The generated trees are in
`tests/test_properties.py`."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.text.latex.structure import read_tree

DOC = "\\documentclass{article}\n\\begin{document}\n"
END = "\\end{document}\n"


def titles(document, path: str) -> list[str]:
    (source,) = [s for s in document.sources if s.path == path]
    return [heading.title for heading in source.under]


def test_files_are_read_in_input_order_each_under_the_headings_in_force() -> None:
    files = {
        "main.tex": DOC + "\\section{Methods}\n\\input{chapters/data}\n\\input{late}\n" + END,
        "chapters/data.tex": "\\subsection{Data}\nOf 4100.\n",
        "late.tex": "after\n",
    }
    document = read_tree(files)
    assert [s.path for s in document.sources] == ["main.tex", "chapters/data.tex", "late.tex"]
    assert titles(document, "chapters/data.tex") == ["Methods"]
    # A heading of a file input reaches the text after its `\input`, as LaTeX prints it.
    assert titles(document, "late.tex") == ["Methods", "Data"]
    assert document.refusals == ()


def test_a_path_resolves_from_the_entry_files_folder_with_tex_added() -> None:
    files = {
        "main.tex": DOC + "\\input{chapters/a}\n" + END,
        "chapters/a.tex": "\\input{chapters/b}\n",
        "chapters/b.tex": "b\n",
    }
    assert [s.path for s in read_tree(files).sources] == [
        "main.tex", "chapters/a.tex", "chapters/b.tex"
    ]


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("missing", "missing.tex is not in the manuscript folder"),
        ("../out", "is outside the manuscript folder"),
        ("_drafts/old", "under a folder set aside"),
        ("\\dir/x", "is not written out in full"),
    ],
)
def test_an_input_that_cannot_be_followed_is_refused_where_it_stands(
    written: str, said: str
) -> None:
    text = DOC + "x\n\\input{" + written + "}\n" + END
    document = read_tree({"main.tex": text})
    ((path, refusal),) = document.refusals
    assert path == "main.tex" and refusal.code == "tex-refused" and said in refusal.message
    assert refusal.offset == text.index("\\input")


def test_a_file_that_inputs_itself_is_refused_and_one_input_twice_is_read_once() -> None:
    files = {
        "main.tex": DOC + "\\input{a}\n\\input{a}\n" + END,
        "a.tex": "\\input{b}\n",
        "b.tex": "\\input{a}\n",
    }
    document = read_tree(files)
    assert [s.path for s in document.sources] == ["main.tex", "a.tex", "b.tex"]
    ((path, refusal),) = document.refusals
    assert path == "b.tex" and "inputs itself" in refusal.message


def test_a_file_starts_in_the_state_its_input_stands_in() -> None:
    files = {
        "main.tex": DOC + "\\begin{abstract}\\input{summary}\\end{abstract}\n"
        "\\begin{tabular}{ll}\\input{cells}\\end{tabular}\n" + END,
        "summary.tex": "We found 12.\n",
        "cells.tex": "3 & 4 \\\\\n",
    }
    document = read_tree(files)
    assert titles(document, "summary.tex") == ["Abstract"]
    (cells,) = [s for s in document.sources if s.path == "cells.tex"]
    assert cells.reading.masked.startswith("3   4")
    assert document.refusals == ()


def test_the_authors_package_is_read_as_a_package_and_the_values_file_is_not() -> None:
    preamble = "\\documentclass{article}\n\\usepackage{macros,mgvalues}\n"
    files = {"main.tex": preamble + "\\begin{document}\n" + END}
    packages = {
        "macros.sty": "\\newcommand{\\n}{4100}\n\\def\\x@y{2}\n",
        "mgvalues.sty": "\\newcommand{\\mg}[2][]{}\n",
    }
    document = read_tree(files, packages=packages)
    assert [s.path for s in document.sources] == ["main.tex", "macros.sty"]
    (macros,) = [s for s in document.sources if s.path == "macros.sty"]
    assert "4100" in macros.reading.masked and document.refusals == ()


def test_a_file_nothing_inputs_is_read_loose_and_accepts_what_a_preamble_does() -> None:
    files = {"main.tex": DOC + "x\n" + END, "old.tex": "\\makeatletter loose 7\n"}
    document = read_tree(files)
    assert document.loose == ("old.tex",) and document.refusals == ()


@pytest.mark.parametrize(
    "abstract",
    ["\\abstract{Of 4100 reports, 12 were fatal.}", "\\begin{abstract}12\\end{abstract}"],
)
def test_an_abstract_in_the_preamble_is_read_under_abstract_and_naming_it_is_no_abstract(
    abstract: str,
) -> None:
    """Round 1 of #385 found it blanked unread; round 2 found the refusal that followed fail
    a class that prints it from the preamble, as PNAS's does, and a restyling that only names
    the command. It is read as prose under Abstract."""
    from manuscript_guard.text.latex.mask import read

    text = "\\documentclass{article}\n" + abstract + "\n\\begin{document}\nx\n" + END
    reading = read(text)
    assert reading.refusals == () and "12" in reading.masked
    assert [(h.start, h.title) for h in reading.headings] == [(text.index("\\", 5), "Abstract")]
    restyled = ("\\documentclass{article}\n\\let\\oldabstract\\abstract\n"
                "\\let\\endoldabstract\\endabstract\n"
                "\\renewenvironment{abstract}{\\begin{oldabstract}}{\\end{oldabstract}}\n"
                "\\renewcommand{\\abstract}[1]{\\textbf{#1}}\n"
                "\\newcommand{\\summary}{\\abstract{12}}\n\\let\\abstract\\relax\n"
                "\\begin{document}\n\\begin{abstract}12\\end{abstract}\n" + END)  # fmt: skip
    assert read(restyled).refusals == ()
    # Round 3: one a `filecontents` holds is written to a file, and printed by nothing.
    kept = ("\\documentclass{article}\n\\begin{filecontents}{a.tex}\n" + abstract
            + "\n\\end{filecontents}\n\\begin{document}\nx\n" + END)  # fmt: skip
    assert "12" not in read(kept).masked and read(kept).headings == ()


def test_a_bare_name_input_from_the_preamble_is_the_distributions() -> None:
    """Round 1 of #385: `\\input{glyphtounicode}`, common in templates, failed BUILD. In the
    body a missing file is still refused, its prose unread."""
    preamble = "\\documentclass{article}\n\\input{glyphtounicode}\n\\input glyphtounicode\n"
    assert read_tree({"main.tex": preamble + "\\begin{document}\n" + END}).refusals == ()
    text = preamble + "\\begin{document}\n\\input{glyphtounicode}\n" + END
    ((_path, refusal),) = read_tree({"main.tex": text}).refusals
    assert refusal.offset == text.rindex("\\input")


def test_an_input_without_braces_is_named_so_and_one_past_a_line_break_is_followed() -> None:
    text = DOC + "\\input methods\n\\input\n  {results}\n" + END
    document = read_tree({"main.tex": text, "methods.tex": "m\n", "results.tex": "r\n"})
    ((_path, refusal),) = document.refusals
    assert "no path is written in braces" in refusal.message
    assert [s.path for s in document.sources if not s.loose] == ["main.tex", "results.tex"]


def test_the_chain_at_a_point_takes_a_heading_right_after_an_input_and_a_part_over_a_chapter(
) -> None:
    """Round 1 of #385: a heading that starts where an `\\input` ends was lost, and a chapter
    closed its part."""
    text = DOC + "\\part{I}\\chapter{A}\\input{a}\\section{B}\nafter\n" + END
    (main, _a) = read_tree({"main.tex": text, "a.tex": "\\section{C}\n"}).sources
    assert [h.title for h in main.chain_at(text.index("after"))] == ["I", "A", "B"]


def test_a_heading_is_found_where_its_command_stands(tmp_path: Path) -> None:
    from manuscript_guard.text.latex.mask import read

    text = "\\section*[Short]{Methods 2}\n\\abstract{We found 12.}\n"
    reading = read(text, body=True)
    assert [(h.start, h.level, h.title) for h in reading.headings] == [
        (0, 1, "Methods 2"), (text.index("\\abstract"), 1, "Abstract")
    ]
    assert reading.abstracts == ((text.index("\\abstract"), len(text) - 1),)
