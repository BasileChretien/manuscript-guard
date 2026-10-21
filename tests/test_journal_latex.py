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
