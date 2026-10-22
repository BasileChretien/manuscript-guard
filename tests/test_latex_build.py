"""The PDF of a LaTeX manuscript (`build/latex.py`, DESIGN.md step 9).

Each test that compiles needs latexmk and pdfLaTeX, and skips without them; CI's `latex` job
installs a pinned TeX Live and sets `MANUSCRIPT_GUARD_REQUIRE_LATEX`, with which
`tests/conftest.py` refuses to start unless that TeX Live is the one on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manuscript_guard.build import BuildError, MisreadError
from manuscript_guard.build import latex as latex_build
from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"
_LATEX = shutil.which("latexmk") and shutil.which("pdflatex")
needs_latex = pytest.mark.skipif(not _LATEX, reason="latexmk and pdflatex are needed")


@pytest.fixture
def twin(project: Path) -> Path:
    """The example project with the twin for its manuscript: its `main.tex`."""
    shutil.rmtree(project / "manuscript")
    shutil.copytree(TWIN, project / "manuscript")
    return project / "manuscript" / "main.tex"


def _build(root: Path) -> list[latex_build.Compiled]:
    project = load_project(root)[0]
    namespace, results = load_namespace(project)[:2]
    return latex_build.build_latex(project, namespace, results)


def _typed_before(entry: Path, anchor: str, typed: str) -> int:
    """`typed` put on its own line before `anchor`; the line it is on."""
    text = entry.read_text(encoding="utf-8")
    assert text.count(anchor) == 1
    entry.write_text(text.replace(anchor, f"{typed}\n{anchor}"), encoding="utf-8")
    return text[: text.index(anchor)].count("\n") + 1


def _tree(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*")) if path.is_file()}  # fmt: skip


@needs_latex
def test_build_writes_the_twins_pdfs_and_leaves_its_manuscript_alone(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The main text and the supplement, each its own PDF, built from a copy: nothing is
    written in `manuscript/`, and LaTeX's headings are the reader's."""
    before = _tree(project / "manuscript")
    assert main(["build", str(project), "--skip-checks"]) == 0, capsys.readouterr()
    built = sorted(path.name.replace(".UNCHECKED", "")
                   for path in (project / "build").glob("*.pdf"))  # fmt: skip
    assert built == ["manuscript.pdf", "supplementary.pdf"], built
    assert _tree(project / "manuscript") == before


@needs_latex
def test_an_error_is_named_at_the_manuscripts_file_and_line(project: Path, twin: Path) -> None:
    line = _typed_before(twin, "\\section{Discussion}", "\\undefinedcommandhere")
    with pytest.raises(BuildError) as raised:
        _build(project)
    assert str(raised.value).startswith(f"{project / 'manuscript' / 'main.tex'}:{line}:"), raised


@needs_latex
def test_an_error_in_a_file_input_is_named_in_that_file(project: Path, twin: Path) -> None:
    (twin.parent / "part.tex").write_text("Words.\n\n\\undefinedcommandhere\n", encoding="utf-8")
    _typed_before(twin, "\\section{Discussion}", "\\input{part}")
    with pytest.raises(BuildError) as raised:
        _build(project)
    assert str(raised.value).startswith(f"{twin.parent / 'part.tex'}:3:"), raised


@needs_latex
def test_a_package_not_installed_is_named_and_not_fetched(project: Path, twin: Path) -> None:
    _typed_before(twin, "\\begin{document}", "\\usepackage{nosuchpackageanywhere}")
    with pytest.raises(BuildError) as raised:
        _build(project)
    assert "nosuchpackageanywhere.sty" in str(raised.value), raised


@needs_latex
def test_a_file_written_outside_the_copy_is_refused(project: Path, twin: Path) -> None:
    """TeX writes in the copy and nowhere else: `openout_any=p`, which MiKTeX holds to
    without being told."""
    escaped = project.parent / "escaped.txt"
    _typed_before(twin, "\\begin{document}",
                  "\\newwrite\\out\\immediate\\openout\\out=../../../../escaped.txt"
                  "\\immediate\\write\\out{x}\\immediate\\closeout\\out")  # fmt: skip
    with pytest.raises(BuildError):
        _build(project)
    assert not escaped.exists()


@needs_latex
def test_an_undefined_reference_is_listed_and_fails_at_submission(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A label longer than the log's lines once were, which a wrapped line hid (round 1 of
    step 9)."""
    label = "tab:" + "nowhere" * 7
    _typed_before(twin, "\\section{Discussion}", f"See Table~\\ref{{{label}}}.\n")
    assert main(["build", str(project), "--skip-checks"]) == 0
    assert f"reference {label}" in capsys.readouterr().out
    assert main(["build", str(project), "--skip-checks", "--submission"]) == 1
    assert "fails at submission" in capsys.readouterr().out


@needs_latex
def test_the_headings_latex_numbers_otherwise_than_it_reads_them_are_no_misreading(
    project: Path, twin: Path
) -> None:
    """A `\\paragraph`, which LaTeX does not number, a short title for the contents, a
    binding in a title and a file `\\include`d, whose headings LaTeX writes to an `.aux` of
    its own, are the reader's headings all the same (round 1 of step 9); and so is a title with
    an author's macro in it, which the `.aux` holds expanded and the reader blanks (round 2)."""
    (twin.parent / "added.tex").write_text("\\section{Included part}\nWords.\n",
                                           encoding="utf-8")  # fmt: skip
    _typed_before(twin, "\\begin{document}", "\\newcommand{\\drug}{nivolumab}")
    _typed_before(twin, "\\section{Discussion}",
                  "\\paragraph{Statistical analysis} Words.\n\n"
                  "\\section[Short]{A long title}\nWords.\n\n"
                  "\\section{Of \\mg{results.cohort.n_reports} reports}\nWords.\n\n"
                  "\\section{Safety of \\drug}\nWords.\n\n"
                  "\\include{added}\n")  # fmt: skip
    assert [compiled.pdf.is_file() for compiled in _build(project)] == [True, True]


@needs_latex
def test_a_build_that_runs_too_long_is_stopped_with_what_it_started(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """latexmk stopped alone left its engine running, which held the pipes open (round 1 of
    step 9)."""
    monkeypatch.setattr(latex_build, "TIMEOUT", 5)
    _typed_before(twin, "\\section{Discussion}", "\\def\\loop{\\loop}\\loop")
    with pytest.raises(BuildError, match="took longer than 5 s"):
        _build(project)


@needs_latex
def test_a_supplement_whose_entry_declares_no_class_is_not_built(
    project: Path, twin: Path
) -> None:
    """As `values` writes no values file for it (round 1 of step 9)."""
    (twin.parent / "supplementary" / "main.tex").write_text("A fragment.\n", encoding="utf-8")
    assert [compiled.pdf.name for compiled in _build(project)] == ["main.pdf"]


@pytest.mark.parametrize("build", [".", "manuscript/build"])
def test_a_build_folder_that_would_take_the_authors_files_is_refused(
    project: Path, twin: Path, build: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`paths.build` may name any folder. One whose `latex/` the author keeps is not
    replaced, and one inside the manuscript is not copied into itself (round 2 of step 9)."""
    import yaml

    monkeypatch.setattr(latex_build, "_programs", lambda engine: ("latexmk", engine))
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["paths"] = {**document.get("paths", {}), "build": build}
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    kept = project / build / "latex" / "keep.txt"
    kept.parent.mkdir(parents=True)
    kept.write_text("the author's\n", encoding="utf-8")
    with pytest.raises(BuildError):
        _build(project)
    assert kept.read_text(encoding="utf-8") == "the author's\n"


def test_build_compiles_with_the_engine_the_journal_names(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`latex: {engine: ...}` in the journal's profile is the engine `build` runs."""
    import yaml

    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["latex"] = {"engine": "lualatex"}
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    asked = []
    monkeypatch.setattr(latex_build, "build_latex",
                        lambda *_a, engine: asked.append(engine) or [])  # fmt: skip
    assert main(["build", str(project), "--skip-checks"]) == 0
    assert asked == ["lualatex"]


def test_an_error_at_a_windows_path_is_read() -> None:
    """TeX on Windows may write the file it stopped in with its drive (round 2 of step 9)."""
    found = latex_build._ERROR.search("C:/copy/main.tex:3: Undefined control sequence.\n")
    assert found is not None and (found["file"], found["line"]) == ("C:/copy/main.tex", "3")


@needs_latex
def test_the_folders_paper_yaml_names_are_the_ones_built(project: Path, twin: Path) -> None:
    """The manuscript under another name, and the build folder too (round 1 of step 9)."""
    import yaml

    shutil.move(str(project / "manuscript"), str(project / "paper"))
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["paths"] = {**document.get("paths", {}), "manuscript": "paper", "build": "out"}
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert main(["build", str(project), "--skip-checks"]) == 0
    assert sorted(path.name.replace(".UNCHECKED", "")
                  for path in (project / "out").glob("*.pdf")) == ["manuscript.pdf",
                                                                   "supplementary.pdf"]  # fmt: skip


@needs_latex
def test_a_heading_a_macro_makes_is_a_misreading(project: Path, twin: Path) -> None:
    """LaTeX numbers a section the reader does not see, so the gates read the paper
    otherwise than it prints: refused, as pandoc's headings are compared."""
    _typed_before(twin, "\\begin{document}", "\\newcommand{\\madesection}[1]{\\section{#1}}")
    _typed_before(twin, "\\section{Discussion}", "\\madesection{Made by a macro}\n")
    with pytest.raises(MisreadError) as raised:
        _build(project)
    assert "Made by a macro" in str(raised.value), raised


def test_without_latex_build_says_so_and_exits_2(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(latex_build.shutil, "which", lambda name: None)
    assert main(["build", str(project), "--skip-checks"]) == 2
    said = capsys.readouterr().err
    assert "latexmk" in said and "not installed" in said, said


def test_the_aux_s_numbered_headings_are_read_in_order(tmp_path: Path) -> None:
    """Each `\\@writefile{toc}` line with a number, a title holding braces whole; one with no
    number, as `\\addcontentsline` writes for a starred section, is left out; and an included
    file's `.aux`, where its `\\@input` stands (round 1 of step 9)."""
    (tmp_path / "main.aux").write_text(
        "\\@writefile{toc}{\\contentsline {section}{\\numberline {1}Methods}{1}{}}%\n"
        "\\@input{part.aux}\n"
        "\\@writefile{toc}{\\contentsline {section}{Unnumbered}{2}{}}%\n"
        "\\@writefile{toc}{\\contentsline {subsection}{\\numberline {1.1}Data, "
        "\\emph {2010--2019}}{2}{section.1.1}}%\n", encoding="utf-8")
    (tmp_path / "part.aux").write_text(
        "\\@writefile{toc}{\\contentsline {section}{\\numberline {2}Included}{1}{}}%\n",
        encoding="utf-8")
    assert latex_build.aux_headings(tmp_path / "main.aux") == [
        "Methods", "Included", "Data, \\emph {2010--2019}"]
