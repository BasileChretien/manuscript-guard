"""G2's pointers to tables and figures in a LaTeX manuscript (step 13, `gates/pointers_latex.py`).

The twin numbers its two tables and its figure with a float's `\\caption`, and its supplement
its two; each test types a pointer or a cross-reference into it and holds G2 to what LaTeX
numbers.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.gates.pointers_latex import check_pointers_latex

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"


@pytest.fixture
def twin(project: Path) -> Path:
    """The example project with the twin for its manuscript; its entry file."""
    shutil.rmtree(project / "manuscript")
    shutil.copytree(TWIN, project / "manuscript")
    return project / "manuscript" / "main.tex"


def _said(entry: Path) -> list[tuple[str, str, str, int | None]]:
    report = check_pointers_latex(load_project(entry.parent.parent)[0])
    return [(f.code, f.severity, f.path.name, f.line) for f in report.findings]


def _replaced(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def _line(path: Path, typed: str) -> int:
    text = path.read_text(encoding="utf-8")
    return text.count("\n", 0, text.index(typed)) + 1


def test_the_twin_points_at_what_it_numbers(twin: Path) -> None:
    report = check_pointers_latex(load_project(twin.parent.parent)[0])
    assert report.findings == ()
    assert report.counts == {"pointers": 7, "pointers_checked": 7, "tables_placed": 2,
                             "figures_placed": 1}  # fmt: skip


def test_a_pointer_past_what_the_document_numbers_is_said_at_its_line(twin: Path) -> None:
    _replaced(twin, "in Table~2, so", "in Table~2 and Table~3, so")
    assert _said(twin) == [("pointer-to-nothing", "fail", "main.tex", _line(twin, "Table~3"))]


def test_a_supplement_s_table_is_counted_in_the_supplement(twin: Path) -> None:
    _replaced(twin, "Table\nS2 describes", "Table\nS3 describes")
    # Placed at the line its first word is typed on.
    assert _said(twin) == [("pointer-to-nothing", "fail", "main.tex", _line(twin, "Table\nS3"))]


def test_a_cross_reference_cites_what_it_points_at(twin: Path) -> None:
    """`\\ref` to a table's label is its citation, in order, as a ref binding is in Markdown;
    `\\pageref` is a page's, and cites nothing."""
    _replaced(twin, "in Table~2, so", "in Table~\\ref{tab:counts}, so")
    assert _said(twin) == []
    _replaced(twin, "in Table~\\ref{tab:counts}, so", "on page~\\pageref{tab:counts}, so")
    assert [code for code, *_rest in _said(twin)] == ["display-not-cited"]


def test_a_table_first_cited_after_a_later_one_is_out_of_order(twin: Path) -> None:
    _replaced(twin, "shown in Table~1.", "shown in Table~\\ref{tab:counts} and Table~1.")
    assert _said(twin) == [("cited-out-of-order", "fail", "main.tex",
                            _line(twin, "Table~\\ref{tab:counts}"))]  # fmt: skip


def test_a_pointer_in_a_file_the_entry_inputs_is_placed_there(twin: Path) -> None:
    _replaced(twin, "Baseline characteristics are shown in Table~1.", "\\input{shown}")
    shown = twin.parent / "shown.tex"
    shown.write_text("Words first.\n\nBaseline characteristics are shown in Table~4.\n",
                     encoding="utf-8")  # fmt: skip
    said = _said(twin)
    assert ("pointer-to-nothing", "fail", "shown.tex", 3) in said, said


@pytest.mark.parametrize(
    "placed",
    [
        "\\begin{table}\\mg{table.extra}\\end{table}",
        "\\captionof{table}{Typed outside a float.}",
        "\\begin{longtable}{l}\\caption{Long.}\\\\ x \\\\\\end{longtable}",
    ],
)
def test_a_table_the_view_cannot_count_leaves_tables_unchecked(twin: Path, placed: str) -> None:
    """A float with no caption the reader reads, a `\\captionof`, a `longtable`'s caption:
    LaTeX may number one, so the main text's tables are not counted, and a note says so."""
    _replaced(twin, "in Table~2, so", "in Table~7, so")
    _replaced(twin, "\\section{Discussion}", placed + "\n\n\\section{Discussion}")
    assert [(code, severity) for code, severity, *_rest in _said(twin)] == [
        ("pointers-unchecked", "info")
    ]


def test_a_starred_or_a_subfigure_s_caption_numbers_nothing(twin: Path) -> None:
    _replaced(twin, "\\section{Discussion}",
              "\\begin{table}\\caption*{Not numbered.}\\caption{Third.}\\end{table}\n"
              "\\begin{figure}\\subcaption{A part.}\\caption{Second.}\\end{figure}\n\n"
              "Both are in Table~3 and Figure~2.\n\n\\section{Discussion}")  # fmt: skip
    assert _said(twin) == []


def test_a_subfigure_s_caption_numbers_a_part_and_a_continued_float_nothing(
    twin: Path,
) -> None:
    """Round 1 of step 13, part 2: a `\\caption` in a `subfigure` numbers a part, (a), and a
    float `\\ContinuedFloat` continues numbers what the last of its kind did."""
    _replaced(twin, "\\section{Discussion}", (
        "\\begin{figure}\\ContinuedFloat\\caption{The estimate, continued.}\\end{figure}\n"
        "\\begin{figure}\\begin{subfigure}{.4\\linewidth}\\caption{Left.}\\label{fig:2a}"
        "\\end{subfigure}\\begin{subfigure}{.4\\linewidth}\\caption{Right.}\\end{subfigure}"
        "\\caption{Both.}\\label{fig:two}\\end{figure}\n\n"
        "Figure~\\ref{fig:two} shows both, and Figure~2 is the last.\n\n\\section{Discussion}"))
    assert _said(twin) == []


def test_a_part_s_label_cites_its_figure(twin: Path) -> None:
    """Round 2 of step 13, part 2: `\\ref` to a subfigure's label prints "2a", and cites
    Figure 2; a caption in a file read inside a subfigure numbers a part too."""
    (twin.parent / "part_b.tex").write_text("\\caption{Right.}\\label{fig:2b}\n",
                                            encoding="utf-8")  # fmt: skip
    _replaced(twin, "\\section{Discussion}", (
        "\\begin{figure}\\begin{subfigure}{.4\\linewidth}\\caption{Left.}\\label{fig:2a}"
        "\\end{subfigure}\\begin{subfigure}{.4\\linewidth}\\input{part_b}\\end{subfigure}"
        "\\caption{Both.}\\label{fig:two}\\end{figure}\n\n"
        "Figure~\\ref{fig:2a} shows the left.\n\n\\section{Discussion}"))
    assert _said(twin) == []


def test_a_caption_in_a_float_the_reader_does_not_know_leaves_both_kinds_unchecked(
    twin: Path,
) -> None:
    """Round 2 of step 13, part 2: a `\\caption` in `SCfigure` numbers a display of a kind
    the view cannot tell, so neither kind is counted, and "Figure 2" is not said to point at
    nothing."""
    _replaced(twin, "\\section{Discussion}",
              "\\begin{SCfigure}\\caption{Beside.}\\end{SCfigure}\n\nFigure~2 is beside.\n\n"
              "\\section{Discussion}")  # fmt: skip
    assert [code for code, *_rest in _said(twin)] == ["pointers-unchecked"] * 2


@pytest.mark.parametrize(
    "placed",
    [
        "\\begin{algorithm}\\caption{Matching.}\\end{algorithm}",
        "\\begin{listing}\\caption{The code.}\\end{listing}",
        "\\newcommand{\\figcap}[1]{\\caption{#1}}",
    ],
)
def test_a_caption_that_numbers_no_table_or_figure_leaves_them_counted(
    twin: Path, placed: str
) -> None:
    """Round 3 of step 13, part 2: an algorithm's caption, a listing's, or one in a
    definition's body numbers neither a table nor a figure, so "Table 3" is still said."""
    _replaced(twin, "\\section{Discussion}", placed + "\n\n\\section{Discussion}")
    _replaced(twin, "in Table~2, so", "in Table~2 and Table~3, so")
    assert _said(twin) == [("pointer-to-nothing", "fail", "main.tex", _line(twin, "Table~3"))]


def test_a_definition_that_prints_a_float_leaves_both_kinds_unchecked(twin: Path) -> None:
    """Round 4 of step 13, part 2: a command that wraps a whole float prints it where it is
    used, which the reader does not see, so neither kind is counted."""
    _replaced(twin, "\\section{Discussion}",
              "\\newcommand{\\fig}[1]{\\begin{figure}\\caption{#1}\\end{figure}}\\fig{Extra.}\n\n"
              "Figure~2 is the extra one.\n\n\\section{Discussion}")  # fmt: skip
    assert [code for code, *_rest in _said(twin)] == ["pointers-unchecked"] * 2


@pytest.mark.parametrize("caption_in_the_file", [False, True])
def test_a_float_whose_content_a_file_inputs_is_one_display(
    twin: Path, caption_in_the_file: bool
) -> None:
    """Round 1 of step 13, part 2: a float that inputs its table, as one an analysis writes,
    is one table, its caption in the float or in the file."""
    caption = "\\caption{Characteristics of the reports.}\\label{tab:baseline}"
    float_typed = f"\\begin{{table}}{caption}\\mg{{table.baseline}}\\end{{table}}"
    if caption_in_the_file:
        _replaced(twin, float_typed, "\\begin{table}\\input{tab1}\\end{table}")
        (twin.parent / "tab1.tex").write_text(f"{caption}\n\\mg{{table.baseline}}\n",
                                              encoding="utf-8")  # fmt: skip
    else:
        _replaced(twin, float_typed, f"\\begin{{table}}{caption}\\input{{tab1}}\\end{{table}}")
        (twin.parent / "tab1.tex").write_text("\\mg{table.baseline}\n", encoding="utf-8")
    assert _said(twin) == []
    _replaced(twin, "in Table~2, so", "in Table~2 and Table~5, so")
    assert _said(twin) == [("pointer-to-nothing", "fail", "main.tex", _line(twin, "Table~5"))]


def test_a_pointer_in_a_captionof_s_caption_cites_nothing(twin: Path) -> None:
    """Round 1 of step 13, part 2: a `\\captionof`'s caption goes with it, as a float's does."""
    _replaced(twin, "Baseline characteristics are shown",
              "\\captionof{figure}{As Table~\\ref{tab:counts}.}\n\nBaseline characteristics are "
              "shown")  # fmt: skip
    assert [code for code, *_rest in _said(twin)] == ["pointers-unchecked"]


def test_a_page_a_pdf_puts_in_leaves_tables_and_figures_unchecked(twin: Path) -> None:
    _replaced(twin, "\\section{Discussion}", "\\includepdf{form.pdf}\n\n\\section{Discussion}")
    assert [code for code, *_rest in _said(twin)] == ["pointers-unchecked"] * 2


_CODES = "\\begin{table}\\caption{Codes.}\\label{tab:codes}\\end{table}\n"


@pytest.mark.parametrize(
    "opened",
    ["\\appendix\n\\section{Codes}\n", "\\begin{appendices}\n\\section{Codes}\n",
     "\\section{Supplementary materials}\n\\subsection{Codes}\n",
     # Round 2: IEEEtran's command and an `appendix` environment.
     "\\appendices\n\\section{Codes}\n", "\\begin{appendix}\n\\section{Codes}\n",
     # The fix round: two nouns, and a label's title after it.
     "\\section{Supplementary tables and figures}\n", "\\section{Appendix A Proofs}\n"],
)
def test_a_table_in_the_appendix_is_the_supplement_s(twin: Path, opened: str) -> None:
    """An Elsevier paper cited its "Supplementary Table" in the Methods, a table its own
    appendix holds, and was told it was out of order (2026-10-23): a table after
    `\\appendix`, in the appendix package's `appendices` or under a heading that names a
    supplement is the supplement's, held neither to ICMJE's order nor to being cited, and a
    pointer typed past it is still held to what the document numbers."""
    environment = re.match(r"\\begin\{(\w+)\}", opened)
    closed = f"\\end{{{environment[1]}}}\n" if environment else ""
    _replaced(twin, "\\bibliographystyle{plain}", opened + _CODES + _CODES.replace("codes", "more")
              + closed + "\\bibliographystyle{plain}")  # fmt: skip
    _replaced(twin, "\\section{Methods}\n", "\\section{Methods}\nThe codes are in Supplementary "
              "Table~\\ref{tab:codes}.\n")  # fmt: skip
    assert _said(twin) == []
    _replaced(twin, "in Table~2, so", "in Table~2, Table~4 and Table~5, so")
    assert _said(twin) == [("pointer-to-nothing", "fail", "main.tex", _line(twin, "Table~5"))]


def test_a_supplement_s_heading_holds_its_part_and_no_further(twin: Path) -> None:
    """The part a heading that names a supplement holds runs to the next heading of its level:
    a table after that is the main text's again, and cited out of order where it is."""
    _replaced(twin, "\\section{Data availability}", "\\section{Supplementary material}\n"
              "\\subsection{Detail}\n" + _CODES + "\\section{Late}\n"
              + _CODES.replace("codes", "late") + "\\section{Data availability}")  # fmt: skip
    assert [code for code, *_rest in _said(twin)] == ["display-not-cited"]
    _replaced(twin, "\\section{Methods}\n", "\\section{Methods}\nSee Table~\\ref{tab:late}.\n")
    assert _said(twin) == [("cited-out-of-order", "fail", "main.tex",
                            _line(twin, "Table~\\ref{tab:late}"))]  # fmt: skip


@pytest.mark.parametrize(
    "heading", ["Supplementary analyses", "Supplemental oxygen", "Supplement use",
                "Supplementary data sources", "Appendix diameter"]  # round 2
)
def test_a_heading_the_word_only_describes_holds_the_main_text_s_tables(
    twin: Path, heading: str
) -> None:
    """Round 1: a heading that uses "supplementary" of what it holds names no supplement, and
    a table under it cited nowhere is said, as any of the main text's is."""
    _replaced(twin, "\\section{Data availability}", f"\\subsection{{{heading}}}\n" + _CODES
              + "\\section{Data availability}")  # fmt: skip
    assert [code for code, *_rest in _said(twin)] == ["display-not-cited"]


def test_the_appendix_package_s_appendices_end_where_the_environment_does(twin: Path) -> None:
    """Round 1: a table after `\\end{appendices}` is the main text's again."""
    _replaced(twin, "\\bibliographystyle{plain}", "\\begin{appendices}\n\\section{Codes}\n"
              + _CODES + "\\end{appendices}\n" + _CODES.replace("codes", "after")
              + "\\bibliographystyle{plain}")  # fmt: skip
    said = check_pointers_latex(load_project(twin.parent.parent)[0]).findings
    assert [(f.code, f.message.split(" is ")[0]) for f in said] == [
        ("display-not-cited", "Table 4")]


def test_an_appendix_command_holds_past_the_end_of_an_environment(twin: Path) -> None:
    """Round 2: `\\appendix` holds to the end of the document, whatever ends after it."""
    _replaced(twin, "\\bibliographystyle{plain}", "\\appendix\n\\begin{appendices}\n"
              "\\section{Codes}\n" + _CODES + "\\end{appendices}\n"
              + _CODES.replace("codes", "after") + "\\bibliographystyle{plain}")  # fmt: skip
    assert _said(twin) == []


@pytest.mark.parametrize(
    "listed", ["\\bibliography{references}\n",
               "\\begin{thebibliography}{1}\n\\bibitem{a} A.\n\\end{thebibliography}\n"],
)
def test_a_supplement_s_part_ends_at_the_reference_list(twin: Path, listed: str) -> None:
    """Round 2: a paper that places its floats after the reference list, as medical
    submissions do, may end its text with a heading for its supplement: the floats after the
    list are the main text's, and held to ICMJE's order; after a typed list too (fix round)."""
    text = twin.read_text(encoding="utf-8")
    floats = re.findall(r"\\begin\{(?:table|figure)\}.*?\\end\{(?:table|figure)\}", text, re.S)
    for typed in floats:
        text = text.replace(typed, "")
    text = text.replace("\\bibliographystyle{plain}", "\\section*{Supplementary data}\nSee "
                        "online.\n\n\\bibliographystyle{plain}").replace(
        "\\bibliography{references}\n", listed + "\n".join(floats) + "\n")
    twin.write_text(text, encoding="utf-8")
    assert _said(twin) == []
    _replaced(twin, "\\section{Methods}\n", "\\section{Methods}\nSee Table~\\ref{tab:counts}.\n")
    assert [code for code, *_rest in _said(twin)] == ["cited-out-of-order"]


def test_an_appendix_in_a_comment_or_a_definition_opens_none(twin: Path) -> None:
    _replaced(twin, "\\section{Results}", "% \\appendix\n\\newcommand{\\appx}{\\appendix}\n"
              "\\section{Results}")  # fmt: skip
    _replaced(twin, "\\section{Methods}\n", "\\section{Methods}\nSee Table~\\ref{tab:counts}.\n")
    assert [code for code, *_rest in _said(twin)] == ["cited-out-of-order"]
