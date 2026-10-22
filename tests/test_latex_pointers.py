"""G2's pointers to tables and figures in a LaTeX manuscript (step 13, `gates/pointers_latex.py`).

The twin numbers its two tables and its figure with a float's `\\caption`, and its supplement
its two; each test types a pointer or a cross-reference into it and holds G2 to what LaTeX
numbers.
"""

from __future__ import annotations

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
