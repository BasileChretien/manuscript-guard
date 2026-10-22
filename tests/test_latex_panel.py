"""A review panel and a revision round on a LaTeX manuscript (DESIGN.md, "LaTeX manuscripts",
step 12): each is given the documents as the submission folder writes them, their inputs
written in, their values in and their comments out.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"


@pytest.fixture
def twin(project: Path) -> Path:
    """The example project with the twin for its manuscript: its `main.tex`."""
    shutil.rmtree(project / "manuscript")
    shutil.copytree(TWIN, project / "manuscript")
    return project / "manuscript" / "main.tex"


def test_the_panel_is_sent_each_document_as_the_submission_folder_writes_it(
    project: Path, twin: Path
) -> None:
    """Values in, comments out, the files it inputs written in; and the digests G11 holds
    the round to, of the `.tex` files."""
    from manuscript_guard.panel.prompt import gather

    (twin.parent / "part.tex").write_text("Input words.% the round-one statistician asked\n",
                                          encoding="utf-8")  # fmt: skip
    text = twin.read_text(encoding="utf-8")
    authors = yaml.safe_load((project / "authors.yaml").read_text(encoding="utf-8"))
    first = authors["authors"][0]
    name = f"{first['given']} {first['family']}"
    twin.write_text(text.replace("\\section{Discussion}", "\\input{part}\n\\section{Discussion}")
                    .replace("\\begin{document}", "\\author{Zelda Quincey\\thanks{14000 Caen}}\n"
                             f"\\begin{{document}}\n\\author{{{name}}}\\affil{{Sent nowhere}}"
                             "\n\\author{\\fnm{" + first["given"] + "} \\sur{"
                             + first["family"] + "}}\\includegraphics{/home/aexample/f.pdf}"
                             '\\includegraphics{"C:/Users/aexample/my fig.pdf"}')
                    .replace("\\end{document}", "\\begin{thebibliography}{1}\n\\bibitem{x} "
                             f"{first['given'][0]}. {first['family']}, J. Foo 12 (2020) 1--9.\n"
                             "\\end{thebibliography}\n\\end{document}"),
                    encoding="utf-8")  # fmt: skip
    root = load_project(project)[0]
    material = gather(root)
    assert "Input words.%" in material.user and "statistician" not in material.user
    # The preamble's authors stay on the machine (round 1 of step 12, part 2), and so do the
    # names authors.yaml gives, where a template puts them in the body (round 2).
    assert "Zelda Quincey" not in material.user and "Caen" not in material.user
    assert name not in material.user and "\\author{[withheld]}" in material.user
    # As a template types them, and not in a reference list typed in the source, which the
    # journal receives as typed; a picture outside the manuscript by its name (round 3).
    assert "\\fnm{[withheld]}" in material.user
    assert f"{first['given'][0]}. {first['family']}, J. Foo" in material.user
    assert "/home/aexample" not in material.user and "Users/aexample" not in material.user
    assert "\\includegraphics{f.pdf}" in material.user
    assert '\\includegraphics{"my fig.pdf"}' in material.user
    assert material.unrendered == 0
    assert "\\mg{" not in material.user
    alpha = load_namespace(root)[0]["results.param.alpha"].display
    assert alpha in material.user
    assert {"main.tex", "part.tex", "supplementary/main.tex"} <= set(material.file_sha256)
    labels = [sent.label for sent in material.sent]
    assert "manuscript/main.tex" in labels and "manuscript/supplementary/main.tex" in labels


def test_a_panel_round_on_a_latex_manuscript_is_not_refused(project: Path, twin: Path) -> None:
    """`review --run` and `--dry-run` read it; Word's suggestions are a Markdown manuscript's."""
    from manuscript_guard import cli

    def refused(*argv: str) -> str | None:
        return cli._refused_for_latex(cli.build_parser().parse_args(["review", str(project),
                                                                      *argv]))  # fmt: skip

    assert refused("--run") is None and refused("--dry-run") is None
    assert refused("--suggestions", "--round", "1") is not None


def test_a_round_keeps_the_sources_the_journal_received(project: Path, twin: Path) -> None:
    """Beside the printed copy G13 reads, the documents as the submission folder writes
    them."""
    from manuscript_guard.cli import _keep_submitted

    folder = _keep_submitted(load_project(project)[0], 1)
    kept = (folder / "latex" / "manuscript.tex").read_text(encoding="utf-8")
    assert "\\mg{" not in kept and "\\begin{document}" in kept
    assert (folder / "latex" / "supplementary.tex").is_file()
    assert any(path.suffix == ".md" for path in folder.iterdir())
