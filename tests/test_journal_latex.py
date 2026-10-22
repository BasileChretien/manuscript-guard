"""G4 against a journal profile's `latex:` block (`gates/journal_latex.py`), step 6 of
DESIGN.md's "LaTeX manuscripts": the class and the bibliography a LaTeX manuscript states,
against what the journal asks for."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_journal
from manuscript_guard.gates.journal_quotes import rules_of

PROFILE = Path("profiles") / "journals" / "demo-journal.yaml"


def _latex(root: Path, preamble: str) -> None:
    folder = root / "manuscript"
    for path in folder.rglob("*.md"):
        path.unlink()
    (folder / "main.tex").write_text(
        "\\documentclass" + preamble + "\n\\begin{document}\n\\section{Introduction}\nx\n"
        "\\end{document}\n",
        encoding="utf-8",
    )


def _asks(root: Path, latex: dict) -> None:
    path = root / PROFILE
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["latex"] = latex
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _said(root: Path) -> dict[str, str]:
    report = check_journal(load_project(root)[0])
    return {f.code: f.message for f in report.findings if f.code.startswith("latex-")}


@pytest.mark.parametrize(
    ("preamble", "latex", "codes"),
    [
        ("{article}\n\\bibliographystyle{plain}",
         {"class": "article", "bibliography": {"kind": "bibtex", "bst": "plain"}}, set()),
        ("{article}\n\\bibliographystyle{plain}",
         {"class": "elsarticle", "bibliography": {"kind": "bibtex", "bst": "elsarticle-num"}},
         {"latex-class-differs", "latex-bibliography-differs"}),
        ("[12pt]{article}\n\\usepackage[backend=biber,style=apa]{biblatex}",
         {"bibliography": {"kind": "biblatex", "style": "apa"}}, set()),
        ("{article}\n\\usepackage[style=numeric]{biblatex}",
         {"bibliography": {"kind": "biblatex", "style": "apa"}}, {"latex-bibliography-differs"}),
        ("{article}\n\\usepackage{biblatex}",
         {"bibliography": {"kind": "bibtex", "bst": "plain"}}, {"latex-bibliography-differs"}),
        ("{article}\n\\bibliographystyle{plain}",
         {"bibliography": {"kind": "biblatex", "style": "apa"}}, {"latex-bibliography-differs"}),
        ("{article}\n% \\documentclass{elsarticle}\n\\bibliographystyle{plain}",
         {"class": "elsarticle"}, {"latex-class-differs"}),
    ],
)
def test_g4_warns_where_the_class_or_the_bibliography_is_not_the_journals(
    project: Path, preamble: str, latex: dict, codes: set[str]
) -> None:
    _latex(project, preamble)
    _asks(project, latex)
    said = _said(project)
    assert set(said) == codes, said


def test_a_markdown_manuscript_has_no_class_to_compare(project: Path) -> None:
    _asks(project, {"class": "elsarticle"})
    assert _said(project) == {}


def test_each_part_of_the_latex_block_is_a_rule_its_quote_is_filed_under() -> None:
    rules = rules_of({"latex": {"class": "elsarticle", "engine": "pdflatex"}})
    assert {"latex.class", "latex.engine"} <= set(rules)


def test_g4_reads_a_file_input_where_its_input_stands(project: Path) -> None:
    """An abstract input inside its environment is the abstract, and a file input under
    Methods is Methods' text: the printed view writes each file where LaTeX prints it, not
    after the file that inputs it."""
    from manuscript_guard.gates.journal import main_text
    from manuscript_guard.text.sections import measure, split_sections

    _latex(project, "{article}")
    folder = project / "manuscript"
    (folder / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{abstract}\n\\input{abstract}\n\\end{abstract}\n"
        "\\section{Methods}\n\\input{methods}\n\\section{Results}\nThe results.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (folder / "abstract.tex").write_text("Five words of the abstract.\n", encoding="utf-8")
    (folder / "methods.tex").write_text("How it was done.\n", encoding="utf-8")
    text = main_text(load_project(project)[0])
    sections = {section.title: section.body for section in split_sections(text)}
    assert "Five words of the abstract." in sections["Abstract"], text
    assert "How it was done." in sections["Methods"], text
    assert measure(text).abstract_words == 5, text


def _measured(project: Path, files: dict[str, str]):
    from manuscript_guard.gates.journal import main_text
    from manuscript_guard.text.sections import measure

    folder = project / "manuscript"
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return measure(main_text(load_project(project)[0]))


def test_g4_counts_no_word_of_a_typed_reference_list_and_each_word_in_single_quotes(
    project: Path,
) -> None:
    """A reference list typed in `thebibliography` is no part of the text, as Markdown's is
    none of the source; LaTeX's single opening quote does not open a code span that hides the
    words up to the next one (round 1 of step 6)."""
    _latex(project, "{article}")
    body = "We used the `as-treated' analysis and the `per-protocol' one.\n"
    plain = body.replace("`", "'")
    references = (
        "\\begin{thebibliography}{9}\n\\bibitem{a} A. Author, A long title of many words. "
        "J Med 2020;1:1-9.\n\\end{thebibliography}\n"
    )
    head = "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\n"
    typed = _measured(project, {"main.tex": head + body + references + "\\end{document}\n"})
    bare = _measured(project, {"main.tex": head + plain + "\\end{document}\n"})
    assert typed.main_text_words == bare.main_text_words > 8


def test_g4_counts_an_abstract_written_in_the_preamble(project: Path) -> None:
    """A class that prints an abstract written before `\\begin{document}` (round 1 of step 6:
    it was dropped with the preamble, and G4 said no heading names the abstract)."""
    _latex(project, "{article}")
    counts = _measured(project, {"main.tex": (
        "\\documentclass{pnas-new}\n\\title{A title}\n\\begin{abstract}\n" + "word " * 300
        + "\n\\end{abstract}\n\\begin{document}\n\\section{Introduction}\nx\n"
        "\\end{document}\n"
    )})  # fmt: skip
    assert counts.abstract_words == 300


def test_the_class_and_bibliography_are_read_wherever_the_preamble_states_them(
    project: Path,
) -> None:
    """In a file the preamble inputs, and with an option on the line after a comment (round 1
    of step 6)."""
    _latex(project, "{article}\n\\input{preamble}")
    (project / "manuscript" / "preamble.tex").write_text(
        "\\usepackage[backend=biber,%\n  % style=numeric,\n  style=apa]{biblatex}\n",
        encoding="utf-8",
    )
    _asks(project, {"class": "article", "bibliography": {"kind": "biblatex", "style": "apa"}})
    assert _said(project) == {}


def test_an_entry_file_that_cannot_be_read_is_not_said_to_have_another_class(
    project: Path,
) -> None:
    """Its encoding is refused where it is read; G4 does not add a class it could not read."""
    _latex(project, "{article}")
    entry = project / "manuscript" / "main.tex"
    entry.write_bytes(entry.read_text(encoding="utf-8").encode("utf-16"))
    _asks(project, {"class": "article"})
    assert _said(project) == {}


def test_g4_reads_a_latex_legend_in_its_caption(project: Path) -> None:
    """G4 says nothing of legends where no figure is captioned (round 2 of step 6: a note on
    them failed a submission over a rule about figures that do not exist), and reads a
    figure's caption as its legend from step 13: not a table's, a starred one or a
    subfigure's, which number no figure."""
    _latex(project, "{article}")
    path = project / PROFILE
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["figures"] = {"source_url": "https://journal.example/artwork",
                           "read_on": "2026-10-15", "confirmed": True,
                           "legend_words": 5}  # fmt: skip
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = check_journal(load_project(project)[0])
    assert not [f for f in report.findings if f.code in ("not-read-in-latex", "legend-words")]
    main = project / "manuscript" / "main.tex"
    long = "one two three four five six"
    main.write_text(main.read_text(encoding="utf-8").replace("\nx\n", (
        f"\nx\n\\begin{{table}}\\caption{{{long}}}\\end{{table}}\n"
        f"\\begin{{figure}}\\caption*{{{long}}}\\end{{figure}}\n"
        f"\\begin{{figure}}\\subcaption{{{long}}}\\caption{{Short.}}\\end{{figure}}\n"
        f"\\begin{{figure}}\n\\caption{{{long}}}\\end{{figure}}\n")), encoding="utf-8")
    report = check_journal(load_project(project)[0])
    said = [(f.code, f.line) for f in report.findings if f.code == "legend-words"]
    assert said == [("legend-words", 9)], report.findings


def test_the_printed_view_of_files_given_without_those_they_input_reads_what_it_has() -> None:
    """A file input that is not among the files given prints nothing, where it raised
    `RuntimeError` (round 1 of step 7: `Methods.TEX` was left out by a filter on `.tex`)."""
    from manuscript_guard.text.latex.printed import printed_view
    from manuscript_guard.text.latex.structure import read_tree

    files = {"main.tex": "\\documentclass{article}\n\\begin{document}\nOne.\n"
                         "\\input{Methods.TEX}\nTwo.\n\\end{document}\n",
             "Methods.TEX": "Inside.\n"}  # fmt: skip
    sources = read_tree(files).sources
    assert [source.path for source in sources] == ["main.tex", "Methods.TEX"]
    alone = printed_view([sources[0]])
    assert "One." in alone and "Two." in alone and "Inside." not in alone
    assert "Inside." in printed_view(list(sources))
