"""A LaTeX file's citations (`text/latex/cite.py`, and the scanner's records in
`text/latex/mask.py`), step 5 of DESIGN.md's "LaTeX manuscripts". The generated campaign is in
`tests/test_properties.py`; the twin's citations against the example's in
`tests/test_latex_twin.py`."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.text.latex.cite import citations
from manuscript_guard.text.latex.mask import read
from manuscript_guard.text.latex.structure import Source

DOC = "\\documentclass{article}\n\\begin{document}\n"
END = "\\end{document}\n"


def _cited(text: str, bibliography: tuple[str, ...] = ()) -> list[tuple[str, int, bool]]:
    uses = citations(Source("main.tex", text, read(text)), Path("main.tex"), bibliography)
    return [(use.citekey, use.line, use.narrative) for use in uses]


def test_each_key_carries_its_own_line_in_a_group_that_runs_over_lines() -> None:
    text = DOC + "Seen \\citep{a,\n  b} and \\citet{c}.\n" + END
    assert _cited(text) == [("a", 3, False), ("b", 4, False), ("c", 4, True)]


def test_nocite_of_every_key_cites_each_entry_of_the_bibliography() -> None:
    text = DOC + "\\nocite{*}\n" + END
    assert _cited(text, ("x2019", "y2020")) == [("x2019", 3, False), ("y2020", 3, False)]


@pytest.mark.parametrize("command", ["citeA", "citeNP", "mycite", "Citeyearpar"])
def test_a_citation_command_the_reader_does_not_know_is_refused(command: str) -> None:
    """apacite's `\\citeA`, or an author's own: its keys would be hidden from G7."""
    text = DOC + f"As \\{command}{{smith2019}} found.\n" + END
    refusals = read(text).refusals
    if command == "Citeyearpar":
        assert refusals == ()
        return
    (refusal,) = refusals
    assert refusal.code == "tex-refused" and f"\\{command}" in refusal.message


def test_a_citation_command_defined_by_the_author_is_refused_where_it_is_used() -> None:
    text = DOC + "\\newcommand{\\mycite}[1]{\\cite{#1}}\nOf \\mycite{smith2019}.\n" + END
    (refusal,) = read(text).refusals
    assert refusal.offset == text.index("\\mycite{smith")
    assert _cited(DOC + "\\newcommand{\\mycite}[1]{\\cite{#1}}\n" + END) == []
