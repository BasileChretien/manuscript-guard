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


def test_a_heading_is_found_where_its_command_stands(tmp_path: Path) -> None:
    from manuscript_guard.text.latex.mask import read

    text = "\\section*[Short]{Methods 2}\n\\abstract{We found 12.}\n"
    reading = read(text, body=True)
    assert [(h.start, h.level, h.title) for h in reading.headings] == [
        (0, 1, "Methods 2"), (text.index("\\abstract"), 1, "Abstract")
    ]
    assert reading.abstracts == ((text.index("\\abstract"), len(text) - 1),)
