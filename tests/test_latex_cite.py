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


@pytest.mark.parametrize("command", ["mycite", "mycitep", "posscite", "citeZ", "Citeyearpar"])
def test_a_citation_command_the_reader_does_not_know_is_refused(command: str) -> None:
    """An author's own, whose name holds `cite` anywhere: its keys would be hidden from G7
    (round 1 of #442: `\\mycitep` passed unread under a rule for names that begin or end
    with it)."""
    text = DOC + f"As \\{command}{{smith2019}} found.\n" + END
    refusals = read(text).refusals
    if command == "Citeyearpar":
        assert refusals == ()
        return
    (refusal,) = refusals
    assert refusal.code == "tex-refused" and f"\\{command}" in refusal.message


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        ("\\citeA<see>[p.~3]{a}", [("a", True)]),
        ("\\citeNP{a, b}", [("a", False), ("b", False)]),
        ("\\shortciteNP{a}", [("a", False)]),
        ("\\shortciteA{a}", [("a", True)]),
        ("\\fullciteA{a}", [("a", True)]),
        ("\\fullciteNP{a}", [("a", False)]),
        ("\\fullciteauthorNP{a}", [("a", True)]),
        ("\\citeyearNP{a}", [("a", False)]),
        ("\\citeN{a}", [("a", True)]),
        ("\\shortciteN{a}", [("a", True)]),
        ("\\nocitemeta{a}", [("a", False)]),
        ("\\footcitetexts{a}{b}", [("a", False), ("b", False)]),
    ],
)
def test_apacite_s_chicago_s_and_biblatex_s_citations_are_read(
    used: str, expected: list[tuple[str, bool]]
) -> None:
    """apacite's and chicago's commands, read from their `.sty`, and biblatex's
    `\\footcitetexts`, cite their keys; apacite's prenote is read as a note (round 1 of
    #442: they were refused, then passed unread)."""
    text = DOC + f"As {used} found.\n" + END
    reading = read(text)
    assert reading.refusals == ()
    assert [(found.key, found.narrative) for found in reading.cited] == expected
    if "<see>" in used:
        assert "see" in reading.masked and "p. 3" in reading.masked


def test_a_citation_command_defined_by_the_author_is_refused_where_it_is_used() -> None:
    text = DOC + "\\newcommand{\\mycite}[1]{\\cite{#1}}\nOf \\mycite{smith2019}.\n" + END
    (refusal,) = read(text).refusals
    assert refusal.offset == text.index("\\mycite{smith")
    assert _cited(DOC + "\\newcommand{\\mycite}[1]{\\cite{#1}}\n" + END) == []


def test_a_comment_in_a_citations_keys_is_no_part_of_a_key() -> None:
    """LaTeX drops `%` to the end of its line, a brace in it too (round 1 of step 5)."""
    assert _cited(DOC + "\\citep{a,%\n b}\n" + END) == [("a", 3, False), ("b", 4, False)]
    assert _cited(DOC + "\\cite{a, % old}\n b}\n" + END) == [("a", 3, False), ("b", 4, False)]


def test_natbib_and_biblatex_commands_that_cite_or_set_the_style_are_read() -> None:
    """The preamble's settings are not refused, and the commands that cite are read (round 1
    of step 5: `\\setcitestyle` was refused, and the document read as typed past it)."""
    text = (
        "\\documentclass{article}\n\\usepackage{natbib}\n\\setcitestyle{authoryear,round}\n"
        "\\defcitealias{a}{Paper I}\n\\DeclareCiteCommand{\\citeyearonly}{}{}{}{}\n"
        "\\begin{document}\n\\citetalias{a} and \\citepalias{a}, \\footfullcite{b},\n"
        "\\citeurl{c} and \\citedate{c}.\n" + END
    )
    assert read(text).refusals == ()
    assert _cited(text) == [("a", 7, True), ("a", 7, False), ("b", 7, False), ("c", 8, False),
                            ("c", 8, False)]  # fmt: skip


def test_a_multi_citations_global_note_may_be_a_phrase() -> None:
    text = DOC + "\\textcites(see the reviews of this question in)()[p.~2]{ghost}{b}.\n" + END
    assert _cited(text) == [("ghost", 3, True), ("b", 3, True)]
    # One not closed within reach is refused, not read past (round 2 of step 5).
    (refusal,) = read(DOC + "\\cites(" + "x" * 301 + ")(){a}{b}.\n" + END).refusals
    assert "global note" in refusal.message


def test_natbibs_and_biblatexs_other_commands_are_read_in_the_body() -> None:
    text = DOC + ("\\citetext{see \\citealp{a}} \\defcitealias{a}{Paper I} \\citereset\n"
                  "\\notecite[p.~2]{b} \\pnotecite{b} \\fnotecite{b}.\n") + END  # fmt: skip
    assert read(text).refusals == ()
    assert [key for key, _line, _narrative in _cited(text)] == ["a", "b", "b", "b"]


def test_sync_bib_refuses_a_manuscript_its_reader_refuses(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The keys after a refusal are not read, so a bibliography written from the rest would
    lose them (round 1 of step 5)."""
    from manuscript_guard import zotero
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.citations import sync_bib
    from manuscript_guard.text.reader import CitationsUnknown

    asked: list[list[str]] = []
    monkeypatch.setattr(zotero, "export", lambda keys: asked.append(list(keys)) or "")
    folder = project / "manuscript"
    for path in folder.rglob("*.md"):
        path.unlink()
    entry = folder / "main.tex"
    entry.write_text(DOC + "\\citep{a} and \\citep{b}.\n" + END, encoding="utf-8")
    sync_bib(load_project(project)[0])
    assert asked == [["a", "b"]]
    entry.write_text(DOC + "\\citep{a}, \\mycitep{x}, \\citep{b}.\n" + END, encoding="utf-8")
    with pytest.raises(CitationsUnknown, match=r"manuscript/main\.tex:3 is refused"):
        sync_bib(load_project(project)[0])
    assert asked == [["a", "b"]]
