"""The values file of a LaTeX manuscript, `mgvalues.sty` (`build/latex_values.py`): what it
writes for each kind of key, its escaping, and, where LaTeX is installed, what pdfLaTeX prints
of each escape (DESIGN.md, "LaTeX manuscripts", "The values file")."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from manuscript_guard.build.latex_values import NotPrintable, contents, escaped, tabular
from manuscript_guard.contracts.results import Results, Table
from manuscript_guard.contracts.values import Value

#: Latin-1 is written as it is, which LaTeX reads as UTF-8.
_LATIN_1 = "caf\N{LATIN SMALL LETTER E WITH ACUTE} 5\N{DEGREE SIGN}C"


def _value(display: str) -> Value:
    return Value(key="x", value=None, display=display, origin="test", source=Path("r.json"))


@pytest.mark.parametrize(
    ("display", "written"),
    [
        ("12.5%", r"12.5\%"),
        ("<0.001", r"\ensuremath{<}0.001"),
        ("\N{MINUS SIGN}0.42", r"\ensuremath{-}0.42"),
        ("3.84 (2.10\N{EN DASH}7.02)", r"3.84 (2.10\textendash{}7.02)"),
        # A dash before a minus sign keeps the sign (round 1 of step 4b).
        ("-0.80\N{EN DASH}-0.12", r"-0.80\textendash{}-0.12"),
        ("1\N{THIN SPACE}234", r"1\,234"),
        ("\N{GREEK SMALL LETTER BETA} = 0.3", r"\ensuremath{\beta} = 0.3"),
        ("A_B & C#1 {x} ~ ^ $ \\", r"A\_B \& C\#1 \{x\} \textasciitilde{} \textasciicircum{} "
                                   r"\$ \textbackslash{}"),
        (_LATIN_1, _LATIN_1),
    ],
)
def test_a_display_is_written_as_pdflatex_prints_it(display: str, written: str) -> None:
    assert escaped(display, "results.x") == written


@pytest.mark.parametrize("character", ["\N{ALMOST EQUAL TO}", "\N{RIGHTWARDS ARROW}", "\u4e2d"])
def test_a_character_outside_the_table_is_refused_not_guessed(character: str) -> None:
    with pytest.raises(NotPrintable) as found:
        escaped(f"about {character} 5", "results.x")
    assert found.value.character == character and "results.x" in str(found.value)


def _results(**fields) -> Results:
    return replace(Results({}, ()), **fields)


def test_the_file_defines_each_value_table_figure_and_anchor_in_the_order_of_their_keys(
    tmp_path: Path,
) -> None:
    table = Table("t", ("Group", "n"), (("A", "12"), ("B", "7%")), "Caption", ("left", "right"),
                  True, Path("r.json"))  # fmt: skip
    folder = tmp_path / "manuscript"
    figure = tmp_path / "figures" / "forest.pdf"
    namespace = {"results.b": _value("2"), "results.a": _value("1")}
    curve = tmp_path / "figures" / "km_curve.pdf"
    written = contents(folder, namespace, _results(tables={"t": table}),
                       {"forest": figure, "km_curve": curve}, "ab")  # fmt: skip
    text = written.text
    assert text.startswith("% manuscript-guard values, from the results sha256:ab\n")
    assert text.index("mg@results.a") < text.index("mg@results.b")
    assert r"\includegraphics[#1]{../figures/forest.pdf}" in text
    # An underscore in a file's name is no special to `\includegraphics` (round 1 of step 4b).
    assert r"\includegraphics[#1]{../figures/km_curve.pdf}" in text
    assert tabular(table, "table.t") in text and "Caption" not in text
    assert r"B & 7\% \\" in text
    again = contents(folder, dict(reversed(namespace.items())), _results(tables={"t": table}),
                     {"km_curve": curve, "forest": figure}, "ab")  # fmt: skip
    assert again.text == text


def test_a_value_it_cannot_print_refuses_the_file(tmp_path: Path) -> None:
    written = contents(tmp_path, {"results.x": _value("\N{ALMOST EQUAL TO}5")}, _results(), {},
                       "ab")  # fmt: skip
    assert written.text is None and [found.ref for found in written.refused] == ["results.x"]


_PDFLATEX = shutil.which("pdflatex")
_PDFTOTEXT = shutil.which("pdftotext")

#: The displays each escape is printed from, each read back by pdftotext as it is.
_PRINTED = (
    "12.5%", "<0.001", ">5", "a|b", "\N{MINUS SIGN}0.42", "\N{PLUS-MINUS SIGN}2",
    "3\N{MULTIPLICATION SIGN}4", "2.10\N{EN DASH}7.02", "A_B", "C#1", "x&y",
    "-0.80\N{EN DASH}-0.12", "a\N{EM DASH}-b",
)  # fmt: skip
#: What pdftotext reads otherwise, measured under MiKTeX 24.4 (2026-10-21), and why: OT1 draws
#: `\\_` as a rule, which holds no character, and T1's dash has no Unicode in the font's map.
_READ_AS = {"OT1": {"A_B": "AB"}, "T1": {"2.10\N{EN DASH}7.02": "2.10\x157.02",
                                        "-0.80\N{EN DASH}-0.12": "-0.80\x15-0.12",
                                        "a\N{EM DASH}-b": "a\x16-b"}}  # fmt: skip


@pytest.mark.skipif(not (_PDFLATEX and _PDFTOTEXT), reason="pdflatex and pdftotext are needed")
@pytest.mark.parametrize("encoding", ["OT1", "T1"])
def test_pdflatex_prints_each_escape_as_the_value(tmp_path: Path, encoding: str) -> None:
    """Each display, escaped, compiles and prints as the value, under pdfLaTeX's default font
    encoding and T1. The first measurement is recorded in the pull request; CI runs it from
    step 9, which installs TeX Live."""
    # One to a page, so that pdftotext reads each apart, at its page break.
    pages = [escaped(display, "results.x") for display in _PRINTED]
    font = "" if encoding == "OT1" else "\\usepackage[T1]{fontenc}\n"
    (tmp_path / "probe.tex").write_text(
        "\\documentclass{article}\n" + font + "\\pagestyle{empty}\n\\begin{document}\n"
        + "\n\\newpage\n".join(pages) + "\n\\end{document}\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        [_PDFLATEX, "-interaction=nonstopmode", "-halt-on-error", "probe.tex"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout[-2000:]
    read = subprocess.run([_PDFTOTEXT, "-enc", "UTF-8", "probe.pdf", "-"], cwd=tmp_path,
                          capture_output=True, timeout=60, check=False)  # fmt: skip
    printed = [page.strip() for page in read.stdout.decode("utf-8").split("\f") if page.strip()]
    assert printed == [_READ_AS[encoding].get(display, display) for display in _PRINTED]


# ------------------------------------------------------------------------ the check


def _as_latex_with_values(root: Path) -> Path:
    """The example project with a LaTeX manuscript that loads the values file and binds."""
    folder = root / "manuscript"
    for path in folder.rglob("*.md"):
        path.unlink()
    entry = folder / "main.tex"
    entry.write_text(
        "\\documentclass{article}\n\\usepackage{mgvalues}\n\\begin{document}\n"
        "Of \\mg{results.cohort.n_reports} reports.\n\\end{document}\n",
        encoding="utf-8",
    )
    return entry


def _values_findings(root: Path) -> list[str]:
    from manuscript_guard.build.latex_values import check_values
    from manuscript_guard.contracts import load_namespace, load_project

    project, _ = load_project(root)
    namespace, results, _literature, _ = load_namespace(project)
    return [f.code for f in check_values(project, namespace, results).findings]


def test_the_values_file_is_missing_then_written_then_stale(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing where the entry loads it; `values` writes it, and `check` finds it as it would
    write it; edited, or its results changed, it is stale."""
    from manuscript_guard.cli import main

    entry = _as_latex_with_values(project)
    assert _values_findings(project) == ["values-file-missing"]
    assert main(["values", str(project)]) == 0
    written = entry.parent / "mgvalues.sty"
    text = written.read_text(encoding="utf-8")
    assert "mg@results.cohort.n_reports" in text and "mg@figure.forest" in text
    assert _values_findings(project) == []
    edited = text.replace("mg@results.cohort.n_reports\\endcsname#1{",
                          "mg@results.cohort.n_reports\\endcsname#1{9", 1)  # fmt: skip
    assert edited != text
    written.write_text(edited, encoding="utf-8")
    assert _values_findings(project) == ["values-file-stale"]
    assert "wrote" in capsys.readouterr().out


def test_values_refuses_a_markdown_manuscript(project: Path) -> None:
    from manuscript_guard.cli import main

    assert main(["values", str(project)]) == 2
    assert not (project / "manuscript" / "mgvalues.sty").exists()
    assert _values_findings(project) == []


def test_an_entry_that_does_not_load_the_values_file_is_not_told_it_is_missing(
    project: Path,
) -> None:
    entry = _as_latex_with_values(project)
    text = entry.read_text(encoding="utf-8")
    entry.write_text(text.replace("\\usepackage{mgvalues}", "% \\usepackage{mgvalues}"),
                     encoding="utf-8")  # fmt: skip
    assert _values_findings(project) == []

