"""The LaTeX submission folder (`build/latex_pack.py`, DESIGN.md step 10).

The tests of what the folder holds run the writer with the build and the compile alone
stood in for, so that they need no LaTeX; those that compile skip without latexmk and
pdfLaTeX, and CI's `latex` job runs them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.build import BuildError, latex_pack
from manuscript_guard.build.latex import Compiled
from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.text.latex.mask import read

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"
_LATEX = shutil.which("latexmk") and shutil.which("pdflatex")
needs_latex = pytest.mark.skipif(not _LATEX, reason="latexmk and pdflatex are needed")


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


def _packed(root: Path, monkeypatch: pytest.MonkeyPatch, read: tuple[Path, ...] = (),
            cited: tuple[str, ...] = ()) -> latex_pack.LatexPack:  # fmt: skip
    """What the writer makes, with the build and the compile alone stood in for: `read` the
    files the build's LaTeX read, `cited` the keys its `.aux` holds."""
    monkeypatch.setattr(latex_pack, "build_latex",
                        lambda *_a, **_k: [Compiled(Path("x.pdf"), (), read, cited)])  # fmt: skip

    def alone(_project, folder, names, _engine):
        for name in names:
            (folder / f"{name}.pdf").write_bytes(b"%PDF")
        return [Compiled(folder / f"{name}.pdf") for name in names]

    monkeypatch.setattr(latex_pack, "_alone", alone)
    project = load_project(root)[0]
    (project.path("build") / "latex").mkdir(parents=True, exist_ok=True)
    namespace, results = load_namespace(project)[:2]
    return latex_pack.pack_latex(project, namespace, results)


def _written(root: Path, monkeypatch: pytest.MonkeyPatch, read: tuple[Path, ...] = ()) -> Path:
    """The folder the writer makes."""
    return _packed(root, monkeypatch, read).folder


def test_the_reader_records_comments_what_tex_never_prints_and_pictures() -> None:
    text = ("\\documentclass{article}\n\\begin{document}\nA 95\\% x% old: 12 cases\n"
            "\\iffalse draft 13 \\fi y\n\\begin{comment}\nold 14\n\\end{comment}\n"
            "\\includegraphics[width=2cm]{img/a} and \\verb|%x| z\n\\end{document}\n")  # fmt: skip
    reading = read(text)
    assert [text[start:end] for start, end in reading.comments] == ["% old: 12 cases"]
    assert [text[start:end] for start, end in reading.unprinted] == [" draft 13 ", "\nold 14"]
    assert [(text[start:end], text[opened:end]) for start, end, opened in reading.graphics] == [
        ("\\includegraphics[width=2cm]{img/a}", "{img/a}")]


def test_the_folder_holds_each_document_whole_with_its_values_and_no_comments(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each input written in, an `\\include`d one between `\\clearpage`s; each binding as the
    values file prints it, a table as its `tabular` and a figure with its options; `mgvalues`
    as `graphicx`; a comment's text out and its `%` kept; an `\\iffalse` block's content and a
    `comment` environment's lines out; an escaped `%` and one in `\\verb` kept."""
    (twin.parent / "part.tex").write_text("Part words.% a draft said DRAFTD\n",
                                          encoding="utf-8")  # fmt: skip
    (twin.parent / "chap.tex").write_text("Chapter words.\n", encoding="utf-8")
    text = twin.read_text(encoding="utf-8").replace("\\usepackage{mgvalues}",
                                                    "\\usepackage{amsmath,mgvalues}")  # fmt: skip
    twin.write_text(text, encoding="utf-8")
    _typed_before(twin, "\\section{Discussion}",
                  "\\input{part}\n\\include{chap}\n"
                  "Kept 95\\% and \\verb|50%|.% an old draft said DRAFTA\n"
                  "\\iffalse DRAFTB\\fi\n"
                  "\\begin{comment} DRAFTE\nDRAFTC\n\\end{comment}\n"
                  "\\mg[width=3cm]{figure.forest}\n")  # fmt: skip
    folder = _written(project, monkeypatch)
    written = (folder / "manuscript.tex").read_text(encoding="utf-8")
    assert "\\mg" not in written and "mgvalues" not in written, written
    assert "\\usepackage{amsmath,graphicx}" in written
    assert "Part words.%\n" in written and "\\clearpage\nChapter words.\n\n\\clearpage" in written
    assert "Kept 95\\% and \\verb|50%|.%\n" in written
    assert "\\iffalse\\fi" in written and "\\begin{comment}\n\\end{comment}" in written
    for draft in ("DRAFTA", "DRAFTB", "DRAFTC", "DRAFTD", "DRAFTE"):
        assert draft not in written, draft
    assert "\\includegraphics[width=3cm]{forest.png}" in written
    assert (folder / "forest.png").is_file()
    namespace = load_namespace(load_project(project)[0])[0]
    assert namespace["results.param.alpha"].display in written


def test_the_bibliography_holds_the_cited_entries_and_those_they_need(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bib = project / "literature" / "references.bib"
    bib.write_text(bib.read_text(encoding="utf-8")
                   + "\n@string{jr = {Journal}}\n@comment{a note}\n"
                   + "@article{uncitedOne2020, title = {Not cited}}\n"
                   + "@book{neededBook2018, title = {Named by a crossref}}\n",
                   encoding="utf-8")  # fmt: skip
    bib.write_text(bib.read_text(encoding="utf-8")
                   + "@misc{relatedOne2017, title = {Named by related}}\n"
                   + "@misc{inAuxOnly2016, title = {Cited through a macro}}\n",
                   encoding="utf-8")  # fmt: skip
    text = bib.read_text(encoding="utf-8").replace(
        "@article{fictionalClassSignal2019,", "@article{fictionalClassSignal2019,\n  crossref = "
        "{NEEDEDBOOK2018},\n  related = {relatedOne2017},")  # fmt: skip
    bib.write_text(text, encoding="utf-8")
    folder = _packed(project, monkeypatch, cited=("inAuxOnly2016",)).folder
    kept = (folder / "references.bib").read_text(encoding="utf-8")
    for key in ("fictionalHepaticCohort2021", "fictionalClassSignal2019", "neededBook2018",
                "relatedOne2017", "inAuxOnly2016"):  # fmt: skip
        assert f"{{{key}," in kept, key
    assert "@string{jr" in kept
    assert "uncitedOne2020" not in kept and "a note" not in kept


def test_every_entry_is_kept_where_the_document_cites_them_all(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bib = project / "literature" / "references.bib"
    bib.write_text(bib.read_text(encoding="utf-8") + "\n@article{uncitedOne2020, title = {x}}\n",
                   encoding="utf-8")  # fmt: skip
    _typed_before(twin, "\\bibliographystyle{plain}", "\\nocite{*}")
    assert "uncitedOne2020" in (_written(project, monkeypatch) / "references.bib").read_text(
        encoding="utf-8")


def test_a_picture_of_the_manuscript_is_in_the_folder_under_its_name(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named from a folder, by its name without an extension, as graphicx finds it; and one of
    the same name in another folder under its path's name."""
    (twin.parent / "img").mkdir()
    (twin.parent / "other").mkdir()
    picture = shutil.copyfile(project / "figures" / "forest.png", twin.parent / "img" / "a.png")
    other = shutil.copyfile(picture, twin.parent / "other" / "a.png")
    _typed_before(twin, "\\section{Discussion}",
                  "\\includegraphics{img/a}\n\\includegraphics{other/a.png}\n")  # fmt: skip
    folder = _written(project, monkeypatch, read=(Path(picture), Path(other)))
    written = (folder / "manuscript.tex").read_text(encoding="utf-8")
    assert "\\includegraphics{a.png}\n\\includegraphics{other-a.png}\n" in written
    assert (folder / "a.png").is_file() and (folder / "other-a.png").is_file()


def test_a_pdf_picture_is_sent_and_only_the_documents_pdfs_are_left_out(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 1 of step 10: every `.pdf` was left out, a PDF picture among them."""
    (project / "figures" / "forest.pdf").write_bytes(b"%PDF-1.5 a picture")
    pack = _packed(project, monkeypatch)
    assert "forest.pdf" in {path.name for path in pack.files}
    assert not {"manuscript.pdf", "supplementary.pdf"} & {path.name for path in pack.files}


def test_a_file_named_by_its_name_keeps_it_or_is_refused(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A picture found through `\\graphicspath` is found under its name; where another file
    the build read has it, the folder would print the other (round 1 of step 10)."""
    (twin.parent / "img").mkdir()
    (twin.parent / "other").mkdir()
    picture = shutil.copyfile(project / "figures" / "forest.png", twin.parent / "img" / "a.png")
    other = shutil.copyfile(picture, twin.parent / "other" / "a.png")
    _typed_before(twin, "\\begin{document}", "\\graphicspath{{img/}}")
    _typed_before(twin, "\\section{Discussion}",
                  "\\includegraphics{other/a}\n\\includegraphics{a}\n")  # fmt: skip
    with pytest.raises(BuildError, match="two files the manuscript reads are named a.png"):
        _written(project, monkeypatch, read=(Path(other), Path(picture)))


def test_an_input_file_ends_its_last_line_and_stops_at_endinput(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TeX ends a file's last line, so a comment on it does not take the line after the
    `\\input` with it; and `\\endinput` ends the file, not the document (round 1 of
    step 10)."""
    (twin.parent / "part.tex").write_text("Words.% a note", encoding="utf-8")
    (twin.parent / "short.tex").write_text("Shown.\\endinput kept\nHidden DRAFTF.\n",
                                           encoding="utf-8")  # fmt: skip
    _typed_before(twin, "\\section{Discussion}", "\\input{part} Kept.\n\\input{short}\n")
    written = (_written(project, monkeypatch) / "manuscript.tex").read_text(encoding="utf-8")
    assert "Words.%\n Kept." in written and "Shown. kept\n" in written
    assert "DRAFTF" not in written and "\\endinput" not in written


def test_a_file_the_import_package_names_is_written_in_where_it_stands(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file an `\\import` or a `\\subimport` names is the one the tree found, in its
    folder, and not one of the same name in the entry file's; a picture an imported file
    names is found in the folder it was imported from, as LaTeX finds it (2026-10-23)."""
    (twin.parent / "sections" / "parts").mkdir(parents=True)
    (twin.parent / "sections" / "intro.tex").write_text(
        "Imported words.\n\\subimport{parts/}{deep}\n\\includegraphics{pic}\n",
        encoding="utf-8")  # fmt: skip
    (twin.parent / "sections" / "parts" / "deep.tex").write_text("Deep words.\n",
                                                                 encoding="utf-8")  # fmt: skip
    (twin.parent / "deep.tex").write_text("Wrong DRAFTG.\n", encoding="utf-8")
    picture = shutil.copyfile(project / "figures" / "forest.png",
                              twin.parent / "sections" / "pic.png")  # fmt: skip
    _typed_before(twin, "\\section{Discussion}", "\\import{sections/}{intro}\n")
    folder = _written(project, monkeypatch, read=(Path(picture),))
    written = (folder / "manuscript.tex").read_text(encoding="utf-8")
    assert "Imported words.\nDeep words.\n\\includegraphics{pic.png}" in written, written
    assert "DRAFTG" not in written and "import{" not in written
    assert (folder / "pic.png").is_file()


def test_what_filecontents_writes_and_a_commented_bibliography_are_kept(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `%` in a file `filecontents` writes is the file's; a comment in a bibliography's list
    of names is taken out with the list (round 1 of step 10)."""
    _typed_before(twin, "\\begin{document}", "\\begin{filecontents*}{notes.txt}\n"
                  "fifty % of it\n\\end{filecontents*}")  # fmt: skip
    text = twin.read_text(encoding="utf-8").replace(
        "\\bibliography{references}", "\\bibliography{references,% the main list\n}")
    twin.write_text(text, encoding="utf-8")
    written = (_written(project, monkeypatch) / "manuscript.tex").read_text(encoding="utf-8")
    assert "fifty % of it" in written and "\\bibliography{references}" in written


def test_the_aux_s_citations_are_read_in_order(tmp_path: Path) -> None:
    from manuscript_guard.build import latex as latex_build

    (tmp_path / "main.aux").write_text("\\citation{a,b}\n\\abx@aux@cite{0}{c}\n"
                                       "\\@input{part.aux}\n", encoding="utf-8")  # fmt: skip
    (tmp_path / "part.aux").write_text("\\citation{d}\n", encoding="utf-8")
    assert latex_build.aux_citations(tmp_path / "main.aux") == ["a", "b", "c", "d"]


def test_a_figure_the_build_wrote_is_none_of_the_authors(tmp_path: Path) -> None:
    """The build writes a rendered figure over an old one of the author's of the same name;
    the copy's is not taken for the author's (round 1 of step 10)."""
    from manuscript_guard.build import latex as latex_build

    source, root = tmp_path / "manuscript", tmp_path / "copy"
    (source / "figures").mkdir(parents=True)
    (source / "figures" / "forest.png").write_bytes(b"old")
    (source / "logo.png").write_bytes(b"logo")
    shutil.copytree(source, root / "manuscript")
    entry = root / "manuscript" / "main.tex"
    (entry.parent / "main.fls").write_text(
        f"PWD {entry.parent.as_posix()}\nINPUT ./figures/forest.png\nINPUT ./logo.png\n",
        encoding="utf-8")  # fmt: skip
    made = frozenset({(entry.parent / "figures" / "forest.png").resolve()})
    copy = latex_build._Copy(root, source, (entry.parent,), made=made)
    assert [path.name for path in latex_build._recorded(copy, entry)] == ["logo.png"]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc writes the abstract")
def test_an_abstract_with_a_formula_is_left_out_of_abstract_txt(project: Path, twin: Path) -> None:
    """The printed view writes an inline formula as a word, which is no text for a portal's
    box: the abstract is left out with the reason, as a Markdown one with maths is (round 2
    of step 10)."""
    from manuscript_guard.build.submission import abstract_text

    original = twin.read_text(encoding="utf-8")
    # Inline, and displayed (round 3 of step 10).
    for formula in ("$P<0.001$", "\\[P<0.001\\]"):
        twin.write_text(original.replace("(95\\% CI \\mg{results.ror.ci_low}",
                                         f"({formula}; 95\\% CI \\mg{{results.ror.ci_low}}"),
                        encoding="utf-8")  # fmt: skip
        written, why = abstract_text(load_project(project)[0])
        assert written is None and "maths" in why, (formula, written, why)


def test_endinput_where_tex_reads_it_as_text_ends_nothing(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a definition, a `\\verb` or a listing `\\endinput` stops no file (round 2 of
    step 10)."""
    (twin.parent / "part.tex").write_text(
        "\\newcommand{\\stopped}{\\endinput}\nShown \\verb|\\endinput| here.\n"
        "\\begin{verbatim}\n\\endinput\n\\end{verbatim}\nKept after.\n",
        encoding="utf-8")  # fmt: skip
    _typed_before(twin, "\\section{Discussion}", "\\input{part}\n")
    written = (_written(project, monkeypatch) / "manuscript.tex").read_text(encoding="utf-8")
    assert "Kept after." in written and written.count("\\endinput") == 3


def test_the_other_document_and_a_tested_path_are_named_as_the_folder_holds_them(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """xr's `\\externaldocument{../main}` in the supplement is the folder's `manuscript`, and
    a path `\\IfFileExists` tests is the file's name there (round 2 of step 10)."""
    (twin.parent / "img").mkdir()
    logo = shutil.copyfile(project / "figures" / "forest.png", twin.parent / "img" / "logo.png")
    _typed_before(twin, "\\section{Discussion}",
                  "\\IfFileExists{img/logo.png}{\\includegraphics{img/logo}}{}\n")  # fmt: skip
    supplement = twin.parent / "supplementary" / "main.tex"
    _typed_before(supplement, "\\begin{document}", "\\usepackage{xr}\n\\externaldocument{../main}")
    folder = _written(project, monkeypatch, read=(Path(logo),))
    assert ("\\IfFileExists{logo.png}{\\includegraphics{logo.png}}{}" in
            (folder / "manuscript.tex").read_text(encoding="utf-8"))  # fmt: skip
    assert "\\externaldocument{manuscript}" in (folder / "supplementary.tex").read_text(
        encoding="utf-8")


def test_a_tested_path_is_the_files_own_name_in_the_folder(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An author's package keeps its name, a rendered figure has its own, and a test shown in
    `\\verb` is text; a `\\texttt` is no `\\verb`, and an `\\endinput` in it ends the file
    (round 3 of step 10)."""
    package = twin.parent / "mine.sty"
    package.write_text("\\newcommand{\\mine}{}\n", encoding="utf-8")
    (twin.parent / "part.tex").write_text("A\\texttt{\\endinput}\nDRAFTH\n", encoding="utf-8")
    (twin.parent / "sections").mkdir()
    (twin.parent / "sections" / "extra.tex").write_text("Extra words.\n", encoding="utf-8")
    _typed_before(twin, "\\begin{document}",
                  "\\begin{filecontents*}{written.tex}\n"
                  "\\IfFileExists{figures/forest.png}{}{}\n\\end{filecontents*}")  # fmt: skip
    _typed_before(twin, "\\section{Discussion}",
                  "\\IfFileExists{sections/extra.tex}{\\input{sections/extra}}{}\n"
                  "\\IfFileExists{mine.sty}{\\usepackage{mine}}{}\n"
                  "\\IfFileExists{figures/forest.png}{\\includegraphics{figures/forest}}{}\n"
                  "\\verb|\\IfFileExists{figures/forest.png}|\n\\input{part}\n")  # fmt: skip
    folder = _written(project, monkeypatch, read=(package,))
    written = (folder / "manuscript.tex").read_text(encoding="utf-8")
    assert "\\IfFileExists{mine.sty}{\\usepackage{mine}}{}" in written
    # Round 4: in a file `filecontents` writes, rewritten; of a file written in, as typed.
    assert "\\begin{filecontents*}{written.tex}\n\\IfFileExists{forest.png}" in written
    assert "\\IfFileExists{sections/extra.tex}{Extra words.\n}" in written
    assert "\\IfFileExists{forest.png}{\\includegraphics{forest.png}}{}" in written
    assert "\\verb|\\IfFileExists{figures/forest.png}|" in written
    assert "DRAFTH" not in written and (folder / "mine.sty").is_file()


def test_a_rendered_figure_named_by_its_path_is_in_the_folder(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`\\includegraphics{figures/forest}`, the path the build gives the rendered figure
    beside the entry file, with no binding (round 2 of step 10)."""
    _typed_before(twin, "\\section{Discussion}", "\\includegraphics{figures/forest}\n")
    folder = _written(project, monkeypatch)
    assert "\\includegraphics{forest.png}" in (folder / "manuscript.tex").read_text(
        encoding="utf-8")
    assert (folder / "forest.png").is_file()


def test_bibtex_and_biber_look_in_the_folder_alone(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.bib` an author keeps on BIBINPUTS is not read (round 2 of step 10)."""
    from manuscript_guard.build import latex as latex_build

    seen = {}

    def run(_command, _folder, env):
        seen.update(env)
        return False, ""

    monkeypatch.setattr(latex_build, "_run", run)
    monkeypatch.setattr(latex_build, "_miktex", lambda _binary: False)
    monkeypatch.setenv("BIBINPUTS", "elsewhere")
    with pytest.raises(BuildError):
        latex_build._compile(load_project(project)[0],
                             latex_build._Copy(twin.parent, twin.parent, (), inner=""), twin,
                             ("latexmk", "pdflatex"), "pdflatex", supplementary=False)  # fmt: skip
    assert seen["BIBINPUTS"] == seen["BSTINPUTS"] == seen["TEXINPUTS"]


def test_a_reference_list_typed_in_the_source_names_no_author(project: Path) -> None:
    """A self-citation in `thebibliography` is the list's, as the Word check passes the
    bibliography over (round 2 of step 10)."""
    from manuscript_guard.build.blinding import check_blinded_latex

    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["blinding"] = "double"
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    first = yaml.safe_load((project / "authors.yaml").read_text(encoding="utf-8"))["authors"][0]
    name = f"{first['given']} {first['family']}"
    source = project / "listed.tex"
    source.write_text("\\begin{document}\nText.\n\\begin{thebibliography}{1}\n"
                      f"\\bibitem{{x}} {name}. A title.\n\\end{{thebibliography}}\n"
                      "\\end{document}\n", encoding="utf-8")  # fmt: skip
    assert check_blinded_latex(load_project(project)[0], [source]).ok
    source.write_text(f"\\begin{{document}}\n{name} wrote it.\n\\end{{document}}\n",
                      encoding="utf-8")  # fmt: skip
    assert not check_blinded_latex(load_project(project)[0], [source]).ok


@pytest.mark.parametrize(
    "typed",
    [
        "\\fnm{Ada} \\sur{Example}",
        "A.~Example",
        "Ada~Example",
        "Example,~A.",
        "Zo\\'e Chr\\'{e}tien",
        "Z.~Chr{\\'e}tien",
        "\\email{first\\_last@uni.edu}",
        "Faculty of Arts \\& Sciences",
        "Bj\\o rn Mart\\'\\i nez",
        "Ece Y{\\i}ld{\\i}z",
    ],
)
def test_a_name_is_found_as_latex_types_it(typed: str) -> None:
    """A tie, a template's commands between the words, an accent as a command, and `\\_` or
    `\\&` (round 3 of step 12, part 2)."""
    from manuscript_guard.build.blinding import names_in, sought

    acute = "\N{LATIN SMALL LETTER E WITH ACUTE}"
    authors = {
        "authors": [
            {"given": "Ada", "family": "Example", "email": "first_last@uni.edu"},
            {"given": f"Zo{acute}", "family": f"Chr{acute}tien"},
            {"given": "Bj\N{LATIN SMALL LETTER O WITH STROKE}rn",
             "family": "Mart\N{LATIN SMALL LETTER I WITH ACUTE}nez"},
            {"given": "Ece", "family": "Y\N{LATIN SMALL LETTER DOTLESS I}ld"
             "\N{LATIN SMALL LETTER DOTLESS I}z"},
        ],
        "affiliations": [{"text": "Faculty of Arts & Sciences, Springfield"}],
    }
    assert names_in(f"See {typed} here.", sought(authors, latex=True))
    assert not names_in("\\fnm{Ada} \\sur{Exampled} and Chr\\'{e}tiens",
                        sought(authors, latex=True))  # fmt: skip


def test_a_picture_outside_the_manuscript_is_refused(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _typed_before(twin, "\\section{Discussion}", "\\includegraphics{../figures/forest}\n")
    with pytest.raises(BuildError, match="outside the manuscript's folder"):
        _written(project, monkeypatch)


def test_an_authors_package_is_written_as_the_documents_are(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (twin.parent / "mine.sty").write_text(
        "\\newcommand{\\alphalevel}{\\mg{results.param.alpha}}% was 0.01 in a draft\n",
        encoding="utf-8")  # fmt: skip
    _typed_before(twin, "\\begin{document}", "\\usepackage{mine}")
    written = (_written(project, monkeypatch) / "mine.sty").read_text(encoding="utf-8")
    assert "\\mg" not in written and "0.01" not in written and written.endswith("}%\n")


def test_a_document_the_reader_refuses_is_not_written(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _typed_before(twin, "\\section{Discussion}", "\\ifdefined\\x a\\fi\n")
    with pytest.raises(BuildError, match="the reader refused it"):
        _written(project, monkeypatch)


def test_submit_refuses_a_document_for_a_latex_manuscript(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["submit", str(project), "--skip-checks", "--document", str(twin)]) == 2
    assert "packed from its source" in capsys.readouterr().err


def test_submit_refuses_a_source_that_names_an_author_where_review_is_blind(
    project: Path, twin: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The preamble's `\\author` is in the source the journal is sent."""
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["blinding"] = "double"
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    authors = yaml.safe_load((project / "authors.yaml").read_text(encoding="utf-8"))
    first = authors["authors"][0]
    name = f"{first['given']} {first['family']}"
    _typed_before(twin, "\\begin{document}", f"\\author{{{name}}}")
    monkeypatch.setattr(latex_pack, "build_latex",
                        lambda *_a, **_k: [Compiled(Path("x.pdf"))] * 2)  # fmt: skip
    monkeypatch.setattr(latex_pack, "_alone", lambda _p, folder, names, _e: [
        Compiled(Path(shutil.copyfile(project / "figures" / "forest.png",
                                      folder / f"{name}.pdf"))) for name in names])  # fmt: skip
    (project / "build" / "latex").mkdir(parents=True, exist_ok=True)
    assert main(["submit", str(project), "--skip-checks"]) == 1
    said = capsys.readouterr().out
    assert name in said and "not assembled" in said, said


@needs_latex
def test_submit_packs_the_twin_as_one_folder_that_compiles_alone(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Its PDFs the compile alone's, at the pack's root as the Word documents are; its source in
    `latex/` with the `.bbl`, each file in the manifest; and a Word supplement an earlier build
    left is not packed."""
    (project / "build").mkdir(exist_ok=True)
    (project / "build" / "supplementary.docx").write_bytes(b"an old build's")
    assert main(["submit", str(project), "--skip-checks"]) == 0, capsys.readouterr()
    pack = project / "build" / "submission"
    held = {path.name for path in (pack / "latex").iterdir()}
    assert {"manuscript.tex", "supplementary.tex", "references.bib", "manuscript.bbl",
            "forest.png"} <= held, held  # fmt: skip
    assert (pack / "manuscript.pdf").read_bytes()[:4] == b"%PDF"
    assert (pack / "supplementary.pdf").read_bytes()[:4] == b"%PDF"
    assert not (pack / "supplementary.docx").exists()
    listed = {entry["file"] for entry in yaml.safe_load(
        (pack / "MANIFEST.yaml").read_text(encoding="utf-8"))["files"]}  # fmt: skip
    assert {"latex/manuscript.tex", "latex/references.bib", "manuscript.pdf",
            "supplementary.pdf"} <= listed, listed  # fmt: skip


@needs_latex
def test_a_folder_that_needs_a_file_it_does_not_hold_is_refused(
    project: Path, twin: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A package named by a path into a folder builds, and the folder, which holds it under
    its name, does not compile alone. A picture found through `\\graphicspath` does: graphicx
    looks where TeX finds files too, and the folder holds it there."""
    (twin.parent / "img").mkdir()
    shutil.copyfile(project / "figures" / "forest.png", twin.parent / "img" / "logo.png")
    (twin.parent / "sty").mkdir()
    (twin.parent / "sty" / "mine.sty").write_text("\\newcommand{\\mine}{}\n", encoding="utf-8")
    _typed_before(twin, "\\begin{document}", "\\graphicspath{{img/}}\n\\usepackage{sty/mine}")
    _typed_before(twin, "\\section{Discussion}", "\\includegraphics{logo}\n")
    assert main(["submit", str(project), "--skip-checks"]) == 1
    said = capsys.readouterr().err
    assert "does not compile alone" in said and "sty/mine" in said, said
    assert "logo" not in said, said
