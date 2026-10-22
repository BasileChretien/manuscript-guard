"""LaTeX out of a Markdown manuscript, `build --latex` (`build/latex_out.py`, DESIGN.md step 11).

The checks of what pandoc writes need pandoc and skip without it; the builds need latexmk and
pdfLaTeX too, which CI's `latex` job installs. The comparison over generated Markdown is in
`tests/test_properties.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.build import latex_out
from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.text.latex.mask import read

_PANDOC = shutil.which("pandoc")
_LATEX = shutil.which("latexmk") and shutil.which("pdflatex")
needs_pandoc = pytest.mark.skipif(not _PANDOC, reason="pandoc writes the LaTeX")
needs_latex = pytest.mark.skipif(not (_PANDOC and _LATEX),
                                 reason="pandoc, latexmk and pdflatex are needed")  # fmt: skip


def _profile(project: Path, **latex: object) -> None:
    """The example's journal profile with `latex:` set."""
    path = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["latex"] = latex
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _typed_into_results(project: Path, typed: str) -> None:
    """`typed` as a paragraph of its own before the Results heading of the example."""
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("\n# Results") == 1
    path.write_text(text.replace("\n# Results", f"\n{typed}\n\n# Results"), encoding="utf-8")


def test_the_comparison_names_where_the_digits_part() -> None:
    markdown = "Of 4100 reports.\n\nA second line with 77 cases.\n"
    body = "Of 4100 reports.\n\nA second line with 78 cases.\n"
    said = latex_out.compare_digits(markdown, body, read(body, body=True), citeproc=False)
    assert said == ("LaTeX prints '8' at line 3 of the body, where the Markdown has '7' at "
                    "line 3"), said
    assert latex_out.compare_digits(markdown, markdown, read(markdown, body=True),
                                    citeproc=False) is None  # fmt: skip


def test_a_manuscript_with_no_supplement_has_no_supplement_to_write(project: Path) -> None:
    """Round 1 of step 11: `document_files` refused it, and `build --latex` with it."""
    from manuscript_guard.build.assemble import assemble
    from manuscript_guard.contracts import load_namespace

    shutil.rmtree(project / "manuscript" / "supplementary")
    root = load_project(project)[0]
    namespace, results = load_namespace(root)[:2]
    assembled = assemble(root, namespace, results)[0]
    assert latex_out._markdown(root, assembled, supplementary=True) is None
    assert latex_out._markdown(root, assembled, supplementary=False)


def _compared(markdown: str, *arguments: str) -> str | None:
    """`compare_digits` on `markdown` and the body pandoc writes for it."""
    import subprocess

    done = subprocess.run([_PANDOC, "-f", "markdown", "-t", "latex", "--wrap=preserve",
                           "--no-highlight", *(arguments or ("--natbib",))], input=markdown,
                          capture_output=True, text=True, encoding="utf-8", check=True)  # fmt: skip
    body = done.stdout
    citeproc = "--citeproc" in arguments
    reading = read(latex_out._without_citeproc_keys(body) if citeproc else body, body=True)
    return latex_out.compare_digits(markdown, body, reading, citeproc=citeproc)


@needs_pandoc
@pytest.mark.parametrize("markdown", [
    "Code at https://www.example.edu/~smith/data2024 and https://x.org/a_b|c9 here.\n",
    "Data at https://doi.org/10.5281/zenodo.1[^a] here.\n\n[^a]: 2023 release.\n",
    "Text 5.\n\n[^z]: A note nothing marks, 25 excluded.\n",
    "```\ngsub(\"[^0-9]\", \"\", x)\n```\n\nA mark with no note[^q7].\n",
    # Round 4: a mark inside another note, which pandoc prints as typed; and smart dots.
    "Text[^a].\n\n[^a]: See [^b2].\n\n[^b2]: Details.\n",
    # Round 5: one inside a note whose label the text marks as well.
    "Text[^1] and[^2].\n\n[^1]: See note [^2].\n\n[^2]: Details.\n",
    "See https://github.com/o/r/compare/v1.2...v1.3 now.\n",
])  # fmt: skip
def test_what_pandoc_writes_otherwise_on_purpose_is_put_right(markdown: str) -> None:
    """An address with a sign pandoc writes as a command, and one a note's mark follows; a
    note nothing marks, which pandoc drops; a mark in a listing, which is no mark (rounds 2
    and 3 of step 11)."""
    assert _compared(markdown) is None


@needs_pandoc
def test_a_bracket_pandoc_reads_as_text_is_compared_under_citeproc(tmp_path: Path) -> None:
    """An item with no key makes the bracket text to pandoc, `[see 42 cases; @key]`, and so
    does one whose `@` is in an address (rounds 2 and 3 of step 11)."""
    bib = tmp_path / "references.bib"
    bib.write_text("@article{smith2020, author = {Smith, Ann}, title = {T}, year = {2020}}\n"
                   "@article{2020who, author = {Who}, title = {U}, year = {2020}}\n",
                   encoding="utf-8")  # fmt: skip
    for markdown in ("A [see 42 cases; @smith2020] b.\n", "A [see a@b.org 42; @smith2020] b.\n",
                     "A [see @2020who, p. 12] b.\n"):
        assert _compared(markdown, "--citeproc", f"--bibliography={bib}",
                         "--metadata=link-citations:true") is None, markdown  # fmt: skip


def test_an_empty_document_includes_no_picture(project: Path) -> None:
    """Round 2 of step 11: an empty body raised as though the tool were wrong."""
    root = load_project(project)[0]
    assert latex_out._pictures(root, "\\begin{document}\n\\end{document}\n", "\n",
                               read("", body=True), project, None) == (
        "\\begin{document}\n\\end{document}\n")  # fmt: skip


@needs_pandoc
def test_a_pdf_figure_is_in_the_folders_files(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every file but the documents' PDFs is sent: a figure rendered as a PDF only among
    them (round 2 of step 11)."""
    from manuscript_guard.build import latex_pack
    from manuscript_guard.build.assemble import assemble
    from manuscript_guard.build.latex import Compiled
    from manuscript_guard.contracts import load_namespace

    for path in (project / "figures").glob("forest.*"):
        if path.suffix in (".png", ".svg"):
            path.unlink()
    (project / "figures" / "forest.pdf").write_bytes(b"%PDF-1.5 a picture")
    monkeypatch.setattr(latex_pack, "_alone", lambda _p, folder, names, _e, headings: [
        Compiled(folder / f"{name}.pdf") for name in names])  # fmt: skip
    root = load_project(project)[0]
    namespace, results = load_namespace(root)[:2]
    packed = latex_out.build_from_markdown(root, assemble(root, namespace, results)[0])
    assert "forest.pdf" in {path.name for path in packed.files}


def test_the_citations_are_as_the_profile_says(project: Path) -> None:
    root = load_project(project)[0]
    assert latex_out.citations(root, None).kind == "citeproc"
    _profile(project, bibliography={"kind": "bibtex", "bst": "plainnat"})
    assert latex_out.citations(load_project(project)[0], None) == latex_out.Citations(
        "natbib", "plainnat")
    _profile(project, bibliography={"kind": "biblatex", "style": "authoryear"})
    assert latex_out.citations(load_project(project)[0], None).kind == "biblatex"


def test_the_template_names_no_author_where_review_is_blind(project: Path) -> None:
    named = latex_out._header(load_project(project)[0], False)
    assert "author:" in named
    path = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["blinding"] = "double"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert "author:" not in latex_out._header(load_project(project)[0], False)


@needs_pandoc
def test_tex_in_the_markdown_the_reader_refuses_is_not_built(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Raw TeX the Word writer drops reaches the `.tex` and takes effect: a conditional in the
    body is refused there as in a LaTeX manuscript (step 11, check 2)."""
    _typed_into_results(project, "\\ifdefined\\something kept\\fi")
    assert main(["build", str(project), "--latex", "--skip-checks"]) == 1
    said = capsys.readouterr().err
    assert "the LaTeX reader refuses" in said, said


@needs_pandoc
def test_a_number_tex_in_the_markdown_hides_is_not_built(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Markdown reader reads the 7 that `\\iffalse` keeps LaTeX from printing: the digits
    differ, and the build says where (step 11, check 3)."""
    _typed_into_results(project, "Of these \\iffalse 7\\fi none were excluded.")
    assert main(["build", str(project), "--latex", "--skip-checks"]) == 1
    said = capsys.readouterr().err
    assert "prints other digits" in said, said


@needs_latex
def test_build_latex_writes_one_folder_and_its_pdfs(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under natbib as the profile says: the documents, the cut `.bib`, the figure under its
    name, and the PDFs the folder compiles to alone."""
    _profile(project, **{"class": "article", "bibliography": {"kind": "bibtex",
                                                               "bst": "plainnat"}})  # fmt: skip
    assert main(["build", str(project), "--latex", "--skip-checks"]) == 0, capsys.readouterr()
    folder = project / "build" / "latex" / "submission"
    held = {path.name for path in folder.iterdir()}
    assert {"manuscript.tex", "supplementary.tex", "references.bib", "forest.png"} <= held, held
    written = (folder / "manuscript.tex").read_text(encoding="utf-8")
    assert "\\citep{" in written and "\\bibliographystyle{plainnat}" in written
    assert "\\includegraphics" in written and "{forest.png}" in written and "{{" not in written
    built = {path.name.replace(".UNCHECKED", "") for path in (project / "build").glob("*.pdf")}
    assert built == {"manuscript.pdf", "supplementary.pdf"}, built


@needs_latex
def test_submit_latex_packs_a_markdown_manuscript_as_latex(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under citeproc, the profile naming no bibliography: the source in `latex/`, the PDFs
    beside the other documents, and no Word document."""
    assert main(["submit", str(project), "--latex", "--skip-checks"]) == 0, capsys.readouterr()
    pack = project / "build" / "submission"
    assert (pack / "latex" / "manuscript.tex").is_file()
    assert (pack / "manuscript.pdf").read_bytes()[:4] == b"%PDF"
    assert not list(pack.glob("*.docx"))
