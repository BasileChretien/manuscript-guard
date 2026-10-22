"""`explain` and `bind` on a LaTeX manuscript (DESIGN.md, "LaTeX manuscripts", step 12).

Each reads a file as G2 reads it, through the include tree and under the headings over a
number, and a binding is written `\\mg{...}`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"


@pytest.fixture
def twin(project: Path) -> Path:
    """The example project with the twin for its manuscript: its `main.tex`."""
    shutil.rmtree(project / "manuscript")
    shutil.copytree(TWIN, project / "manuscript")
    return project / "manuscript" / "main.tex"


def _typed_before(entry: Path, anchor: str, typed: str) -> None:
    text = entry.read_text(encoding="utf-8")
    assert text.count(anchor) == 1
    entry.write_text(text.replace(anchor, f"{typed}\n{anchor}"), encoding="utf-8")


def _display(project: Path, key: str) -> str:
    return load_namespace(load_project(project)[0])[0][key].display


def test_explain_classifies_a_latex_file_as_g2_does(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A number typed in the Results fails, as `check` fails it; one in a file the entry
    inputs is explained in that file."""
    (twin.parent / "part.tex").write_text("Of the 9137 records.\n", encoding="utf-8")
    _typed_before(twin, "\\section{Discussion}", "Of 4100 reports typed.\n\\input{part}\n")
    assert main(["explain", str(twin)]) == 0
    said = capsys.readouterr().out
    assert any(line.startswith("FAIL") and "4100" in line for line in said.splitlines()), said
    assert main(["explain", str(twin.parent / "part.tex")]) == 0
    assert "9137" in capsys.readouterr().out


def test_explain_refuses_a_tex_the_gates_do_not_read(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file nothing inputs is read on its own, as G2 reads it and warns of it; a `.tex` in
    a Markdown manuscript is read by no gate."""
    (twin.parent / "loose.tex").write_text("Nothing inputs 12 of these.\n", encoding="utf-8")
    assert main(["explain", str(twin.parent / "loose.tex")]) == 0
    assert "12" in capsys.readouterr().out
    shutil.rmtree(project / "manuscript")
    shutil.copytree(Path(__file__).parents[1] / "example" / "manuscript", project / "manuscript")
    stray = project / "manuscript" / "stray.tex"
    stray.write_text("12\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["explain", str(stray)]) == 2
    assert "Markdown manuscript" in capsys.readouterr().err


def test_bind_offers_and_writes_a_latex_binding(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typed number that reads as one published value is offered as `\\mg{...}`, and
    `--apply` writes that; one in a siunitx command, where the reader refuses a binding, is
    left as typed."""
    point = _display(project, "results.ror.point")
    _typed_before(twin, "\\begin{document}", "\\usepackage{siunitx}")
    typed = f"The estimate was {point} again, and \\num{{{point}}} in siunitx.\n"
    _typed_before(twin, "\\section{Discussion}", typed)
    assert main(["bind", str(project)]) == 1
    said = capsys.readouterr().out
    assert "replace it with \\mg{results.ror.point}" in said, said
    main(["bind", str(project), "--apply"])
    written = twin.read_text(encoding="utf-8")
    assert "The estimate was \\mg{results.ror.point} again" in written, written
    assert f"\\num{{{point}}}" in written, written


def test_bind_pointers_says_latex_numbers_its_tables(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["bind", str(project), "--pointers"]) == 2
    assert "\\ref" in capsys.readouterr().err
