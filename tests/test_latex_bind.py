"""`explain`, `bind`, `init --latex` and the hooks on a LaTeX manuscript (DESIGN.md, "LaTeX
manuscripts", step 12).

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


def _failing(root: Path) -> set[tuple[str, str]]:
    import io
    import json
    from contextlib import redirect_stdout

    from manuscript_guard.cli import main as run

    out = io.StringIO()
    with redirect_stdout(out):
        run(["check", str(root), "--stage", "drafting", "--json"])
    found = json.loads(out.getvalue())["findings"]
    return {(each["gate"], each["code"]) for each in found if each["severity"] == "fail"}


def test_init_latex_makes_a_project_that_fails_as_a_markdown_one_does(tmp_path: Path) -> None:
    """Its manuscript is `main.tex` with its values file beside it, which `check` finds
    current, and AGENTS.md writes a binding as LaTeX does (step 12)."""
    assert main(["init", str(tmp_path / "md")]) == 0
    assert main(["init", str(tmp_path / "tex"), "--latex", "--title", "Fifty & more"]) == 0
    manuscript = tmp_path / "tex" / "manuscript"
    assert sorted(path.name for path in manuscript.iterdir()) == ["main.tex", "mgvalues.sty"]
    assert "\\title{Fifty \\& more}" in (manuscript / "main.tex").read_text(encoding="utf-8")
    assert "\\mg{results.<key>}" in (tmp_path / "tex" / "AGENTS.md").read_text(encoding="utf-8")
    assert _failing(tmp_path / "tex") == _failing(tmp_path / "md")


def test_init_latex_beside_a_markdown_manuscript_makes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["init", str(tmp_path), "--latex"]) == 2
    assert "Markdown manuscript" in capsys.readouterr().err
    assert not (tmp_path / "manuscript" / "main.tex").exists()


def test_the_hooks_refuse_the_values_file_and_note_a_typed_number(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`mgvalues.sty` is written by `values`, not by hand; and a LaTeX file saved with a
    number bound to nothing is noted with the LaTeX binding (step 12)."""
    import json

    from manuscript_guard.hooks import dispatch

    def run(handler: str, path: Path) -> dict:
        assert dispatch(handler, {"tool_input": {"file_path": str(path)}}) == 0
        out = capsys.readouterr().out.strip()
        return json.loads(out) if out else {}

    refused = run("guard-write", twin.parent / "mgvalues.sty")
    assert refused["hookSpecificOutput"]["permissionDecision"] == "deny", refused
    assert run("guard-write", twin.parent / "supplementary" / "mgvalues.sty")
    _typed_before(twin, "\\section{Discussion}", "Of 4100 reports typed.\n")
    noted = run("after-edit", twin)["hookSpecificOutput"]["additionalContext"]
    assert "4100" in noted and "\\mg{results.<key>}" in noted, noted
