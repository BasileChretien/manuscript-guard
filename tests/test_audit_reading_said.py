"""What `audit` reads of a paper and says it did not (Basile, 2026-11-11, "Read more, and be
honest"): a LaTeX folder read in the input encoding it declares, a LaTeX file read only to
where the reader stopped, said in the summary, and a PDF in which no heading was read said to
be read as one text, as a .docx in that state is. The template shapes of the corpus run are
in `tests/test_corruption.py` and `tests/test_latex_mask.py`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.audit import AuditReport, _pdf_structure, audit
from manuscript_guard.cli import main

_E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"


@pytest.mark.parametrize(
    ("declared", "codec"),
    [("latin1", "latin_1"), ("latin9", "iso8859_15"), ("cp1252", "cp1252"),
     ("ansinew", "cp1252")],
)
def test_a_latex_folder_is_read_in_the_encoding_it_declares(
    tmp_path: Path, declared: str, codec: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The corpus run of 2026-11-11: a paper saved in Latin-1 that declares it was read as
    UTF-8, its accented letters replacement characters, and refused at the declaration, the
    rest of the file read as typed. Its folder is read in that encoding now, a file it
    inputs too, so that the gates read the letters TeX prints."""
    paper = tmp_path / "paper.tex"
    paper.write_bytes(("\\documentclass{article}\n"
                       f"\\usepackage[{declared}]{{inputenc}}\n\\begin{{document}}\n"
                       f"\\section{{Results}}\nThe caf{_E_ACUTE} cohort held 4100 reports.\n"
                       "\\input{part}\n\\end{document}\n").encode(codec))  # fmt: skip
    (tmp_path / "part.tex").write_bytes(f"Of them, 12 were na{_E_ACUTE}ve.\n".encode(codec))
    outputs = tmp_path / "outputs.csv"
    outputs.write_text("n,k\n4100,12\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert report.unreadable == [] and len(report.matched) == 2, report.unreadable
    texts = {source.path: source.text for tree in report.trees
             for _path, source in tree.files}  # fmt: skip
    assert f"caf{_E_ACUTE}" in texts["paper.tex"] and f"na{_E_ACUTE}ve" in texts["part.tex"]
    assert main(["audit", str(paper), "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["findings"]
    assert not any("\N{REPLACEMENT CHARACTER}" in json.dumps(one) for one in found), found


def test_an_encoding_the_audit_does_not_read_in_is_still_refused(tmp_path: Path) -> None:
    """Only the encodings of `text.latex.encodings.CODECS` are read in: a folder that
    declares another, or two that decode otherwise, is read as UTF-8, and a declaration in a
    file that is not ASCII refused, the rest of the file not read."""
    paper = tmp_path / "paper.tex"
    paper.write_bytes(("\\documentclass{article}\n\\usepackage[latin2]{inputenc}\n"
                       f"\\begin{{document}}\nThe caf{_E_ACUTE} cohort.\n\\end{{document}}\n"
                       ).encode("latin_1"))  # fmt: skip
    report = audit([paper], None)
    assert len(report.unreadable) == 1 and "not read past line 2" in report.unreadable[0]


def test_the_summary_says_a_latex_file_was_not_read_past_where_the_reader_stopped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The corpus run of 2026-11-11: a file the reader stopped in on its preamble's line was
    said to have "nothing reported" by G6 and G14. Past the line nothing of it is read, and
    the summary says so, under the findings' count where there are any."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\catcode`\\@=11\n\\begin{document}\n"
                     "It is groundbreaking. % TODO: fill in\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    assert main(["audit", str(paper)]) == 0
    said = capsys.readouterr().out
    line = next(line for line in said.splitlines() if line.strip().startswith("Writing"))
    assert line.split(None, 3)[-1] == ("nothing reported in what was read; not read past "
                                       "line 2 of paper.tex"), line  # fmt: skip
    assert "paper.tex: not read past line 2" in said and "TODO" not in said, said


def test_a_block_skipped_in_the_body_is_said_by_its_lines_and_the_rest_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Basile, 2026-11-13: the reading of three real papers stopped at a `\\makeatletter` in
    the body (tex-stat-ap-B2, tex-qbio-pe-B1) or a conditional (tex-stat-ap-A1), and no check
    read the rest. Each block is skipped, the report names its lines and why where it said
    "not read past line N", and what follows is read: compared, and G6's."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\nOf 4100 reports.\n"
                     "\\makeatletter \\pdfbookmark[0]{\\@title}{title} \\makeatother\n"
                     "\\if0\\blind\n{\\title{Blind 55}\n\\maketitle}\n\\fi\n"
                     "Then 77 died. % TODO: fill in\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    outputs = tmp_path / "outputs.csv"
    outputs.write_text("n,k\n4100,77\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert sorted(c.text for c in report.matched) == ["4100", "77"]
    first, second = report.unreadable
    assert first.startswith("paper.tex: line 4 skipped, which no check read: \\makeatletter "
                            "in the body"), first  # fmt: skip
    assert first.endswith("up to its \\makeatother"), first
    assert second.startswith("paper.tex: lines 5-8 skipped") and second.endswith("\\fi"), second
    assert main(["audit", str(paper), "--against", str(outputs)]) == 0
    said = capsys.readouterr().out
    line = next(line for line in said.splitlines() if line.strip().startswith("Writing"))
    assert line.endswith("; line 4 of paper.tex skipped, lines 5-8 of paper.tex skipped"), line
    assert "not read past" not in said and "TODO" in said, said
    # One with no end in the file stops the reading there, as before.
    paper.write_text(paper.read_text(encoding="utf-8").replace("\\fi\n", ""), encoding="utf-8")
    (stop,) = [one for one in audit([paper], [outputs]).unreadable if "not read past" in one]
    assert stop.startswith("paper.tex: not read past line 5"), stop


def test_a_file_input_only_from_a_skipped_block_is_said_so(tmp_path: Path) -> None:
    """Round 1 of #674: a file the paper inputs only inside a block the reader skips was
    passed over with the advice to input it from the paper's main file, which it does."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\nOf 4100 reports.\n"
                     "\\if0\\blind\n\\input{names}\n\\fi\nThen 77 died.\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    (tmp_path / "names.tex").write_text("Ada Example.\n", encoding="utf-8")
    (said,) = [one for one in audit([paper], None).passed_over if "names.tex" in one]
    assert "inside a block the reader skipped" in said and "paper.tex, lines 4-6" in said, said
    assert "\\input it" not in said, said


def test_a_file_input_past_a_skipped_block_s_own_inputs_keeps_the_old_advice(
    tmp_path: Path,
) -> None:
    """Known gaps (round 2 of #674): only a braced `\\input` or `\\include` a skipped block
    holds is said to be inside it. A braceless one, and a file the file it names inputs, are
    given the advice for a file nothing inputs."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\nOf 4100 reports.\n"
                     "\\if0\\blind\n\\input{names}\n\\input bare\n\\fi\nThen 77 died.\n"
                     "\\end{document}\n", encoding="utf-8")  # fmt: skip
    (tmp_path / "names.tex").write_text("Ada Example.\n\\input{deeper}\n", encoding="utf-8")
    (tmp_path / "deeper.tex").write_text("Mary Ann.\n", encoding="utf-8")
    (tmp_path / "bare.tex").write_text("Sean.\n", encoding="utf-8")
    passed = audit([paper], None).passed_over
    for name in ("deeper.tex", "bare.tex"):
        (said,) = [one for one in passed if one.split(": ")[0].endswith(name)]
        assert "\\input it from the paper's main file" in said, said


def test_a_pdf_in_which_no_heading_was_read_is_said_to_be_read_as_one_text() -> None:
    """A PDF with no line that holds a section's name alone places no heading (2509.01351's
    small capitals, corpus run of 2026-11-11), and was said nothing of: it is read as one
    text, said as a .docx with no heading is (`audit._headings_said`)."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    lines = ["Gains from monetary policy", "We estimate the response of output.", "It falls."]
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(lines),
                  tuple(Place(1, at) for at in range(1, len(lines) + 1)), ())
    report = AuditReport()
    _pdf_structure(report, pdf)
    (said,) = report.headings
    assert said.startswith("p.pdf: no line of it holds a section's name alone"), said
    assert "read as one text" in said
    headed = PdfText(Path("q.pdf"), "test", 1, "Methods\nWe read.\nResults\nIt fell.",
                     tuple(Place(1, at) for at in range(1, 5)), ((1, "Methods"), (3, "Results")))
    report = AuditReport()
    _pdf_structure(report, headed)
    assert report.headings == []


def test_a_refusal_of_the_tree_says_what_it_is_and_the_file_is_read_past_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Round 1 of #637, finding 1: an `\\input` the tree cannot follow is refused for the
    tree, not where the reader stopped, and the file is read past it; the report said no
    check read what followed it, though its numbers were compared. It says what it is."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
                     "Of 4100 reports.\n\\input{absent}\n\n"
                     "Then 77 died.\n\\end{document}\n", encoding="utf-8")  # fmt: skip
    outputs = tmp_path / "outputs.csv"
    outputs.write_text("n,k\n4100,77\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert sorted(c.text for c in report.matched) == ["4100", "77"]
    (said,) = report.unreadable
    assert "not read past" not in said and "line 5" in said and "absent" in said, said
    assert "the rest of the file was read" in said, said
    assert main(["audit", str(paper)]) == 0
    assert "not read past" not in capsys.readouterr().out


def test_a_folder_that_declares_utf8_and_latin1_is_read_as_utf8(tmp_path: Path) -> None:
    """Round 1 of #637, finding 2: a `[utf8]` declaration was not counted, so a folder whose
    paper declares it and whose old draft declares `[latin1]` was read as Latin-1 whole, the
    paper's letters misread. Two declarations that decode otherwise are read as UTF-8."""
    from manuscript_guard.text.latex.encodings import declared

    assert declared(["\\usepackage[utf8]{inputenc}", "\\usepackage[latin1]{inputenc}"]) is None
    assert declared(["\\usepackage[ascii]{inputenc}", "\\inputencoding{latin9}"]) is None
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n"
                     f"\\begin{{document}}\nThe caf{_E_ACUTE} cohort.\n\\end{{document}}\n",
                     encoding="utf-8")  # fmt: skip
    (tmp_path / "draft.tex").write_bytes(("\\documentclass{article}\n"
                                          "\\usepackage[latin1]{inputenc}\n\\begin{document}\n"
                                          f"Caf{_E_ACUTE}.\n\\end{{document}}\n"
                                          ).encode("latin_1"))  # fmt: skip
    report = audit([paper], None)
    texts = {source.path: source.text for tree in report.trees
             for _path, source in tree.files}  # fmt: skip
    assert f"caf{_E_ACUTE}" in texts["paper.tex"], texts["paper.tex"]
    assert report.unreadable == []


def test_a_file_input_past_where_the_reader_stopped_is_said_so(tmp_path: Path) -> None:
    """Round 1 of #637, finding 3: a file the paper inputs past where its reading stopped
    was said to be input by no entry, with the advice to `\\input` it, which the paper does.
    It is said not to be followed, past that line."""
    # A font switch round `\@startsection`, which is not read as before.
    (tmp_path / "arxiv.sty").write_text(
        "\\renewcommand\\section{\\bf\\@startsection{section}{1}{\\z@}{-1ex}{1ex}{}}\n",
        encoding="utf-8")  # fmt: skip
    (tmp_path / "methods.tex").write_text("We read 4100 reports.\n", encoding="utf-8")
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\usepackage{arxiv}\n\\begin{document}\n"
                     "\\section{Introduction}\nWords.\n\\input{methods}\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    report = audit([paper], None, found_tex=[tmp_path / "methods.tex"])
    (said,) = [one for one in report.passed_over if "methods.tex" in one]
    assert "paper.tex was not read past line 4" in said and "\\input it" not in said, said


def test_the_authors_check_and_the_placed_pictures_read_the_tree_s_encoding(
    tmp_path: Path,
) -> None:
    """Round 1 of #637, finding 5: in a folder read as Latin-1, the authors' check read the
    files again as UTF-8 and said the paper could not be read, and the pictures it places
    were passed over in silence."""
    from manuscript_guard.auditing.journal import _placed_pictures, _places
    from manuscript_guard.auditing.latex import read_latex

    (tmp_path / "fig.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    paper = tmp_path / "paper.tex"
    paper.write_bytes(("\\documentclass{article}\n\\usepackage[latin1]{inputenc}\n"
                       "\\begin{document}\nRen\N{LATIN SMALL LETTER E WITH ACUTE}e Martin wrote "
                       "it.\n\\includegraphics{fig}\n\\end{document}\n").encode("latin_1"))
    (tree,) = read_latex([paper]).trees
    assert _placed_pictures(tree) == [tmp_path / "fig.pdf"]
    places = _places(paper, tree)
    assert not isinstance(places, str), places
    assert any(f"Ren{_E_ACUTE}e Martin" in text for _where, text in places), places


@pytest.mark.parametrize("stray", ["cover_letter.tex", "old/draft_v1.tex", "iffalse"])
def test_a_stray_latin1_declaration_does_not_decide_a_paper_s_encoding(
    tmp_path: Path, stray: str
) -> None:
    """Round 2 of #637, finding 1: the encoding was decided for the folder, so a cover letter
    or an old draft beside the paper declaring `[latin1]`, or one in an `\\iffalse` block,
    had a paper that declares nothing, UTF-8, read as "ChrÃ©tien". It is the tree's: the
    entry and the files it reaches, where the reader reads them."""
    from manuscript_guard.auditing.journal import _places
    from manuscript_guard.auditing.latex import read_latex

    hidden = "\\iffalse\n\\usepackage[latin1]{inputenc}\n\\fi\n" if stray == "iffalse" else ""
    paper = tmp_path / "paper.tex"
    paper.write_text(f"\\documentclass{{article}}\n{hidden}\\begin{{document}}\n"
                     f"Chr{_E_ACUTE}tien wrote it.\n\\end{{document}}\n",
                     encoding="utf-8")  # fmt: skip
    if stray != "iffalse":
        (tmp_path / stray).parent.mkdir(exist_ok=True)
        (tmp_path / stray).write_bytes((f"\\documentclass{{letter}}\n\\usepackage[latin1]"
                                        f"{{inputenc}}\n\\begin{{document}}\nCaf{_E_ACUTE}.\n"
                                        "\\end{document}\n").encode("latin_1"))  # fmt: skip
    (tree,) = read_latex([paper]).trees
    text = dict(tree.files)[paper].text
    assert f"Chr{_E_ACUTE}tien" in text and "\N{LATIN CAPITAL LETTER A WITH TILDE}" not in text
    assert any(f"Chr{_E_ACUTE}tien" in found for _where, found in _places(paper, tree))


def test_a_refusal_of_the_tree_in_a_file_the_reader_stopped_in_says_how_far(
    tmp_path: Path,
) -> None:
    """Round 2 of #637, finding 2: an `\\input` the tree cannot follow said the rest of the
    file was read, beside the note that the same file was not read past a later line."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\nOf 4100.\n\n"
                     "\\input{missing}\nThen 77.\n\n\n\\catcode`\\@=11\n\\end{document}\n",
                     encoding="utf-8")  # fmt: skip
    said = audit([paper], None).unreadable
    (missing,) = [one for one in said if "missing" in one]
    assert "the rest of the file was read to line 9" in missing, said
    assert any("not read past line 9" in one for one in said), said


def test_a_file_nothing_inputs_beside_a_stopped_paper_keeps_its_advice(tmp_path: Path) -> None:
    """Round 2 of #637, finding 3: every file nothing read, in a folder where a paper
    stopped, was said to be input past the stop. Only one whose `\\input` stands past it
    is; one nothing inputs is said to be input by no entry."""
    (tmp_path / "methods.tex").write_text("We read 4100 reports.\n", encoding="utf-8")
    (tmp_path / "stray.tex").write_text("Notes.\n", encoding="utf-8")
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\n\\catcode`\\@=11\n"
                     "\\input{methods}\n\\end{document}\n", encoding="utf-8")  # fmt: skip
    found = [tmp_path / "methods.tex", tmp_path / "stray.tex"]
    said = audit([paper], None, found_tex=found).passed_over
    (methods,) = [one for one in said if "methods.tex" in one]
    (stray,) = [one for one in said if "stray.tex" in one]
    assert "paper.tex was not read past line 3" in methods, methods
    assert "no entry inputs it" in stray and "not read past" not in stray, stray


@pytest.mark.parametrize(
    "inputs",
    ["!!input{sections}", "!!import{./}{sections}", "!!subimport{./}{sections}"],
)
def test_a_file_input_past_a_stop_through_another_is_said_not_followed(
    tmp_path: Path, inputs: str
) -> None:
    """Final check of round 2 of #637, findings 1 and 2: the "not followed" note went only to
    a file typed as an input in the stopped file itself, in braces, and to one in a comment.
    It goes to each file the inputs past the stop reach, as the reader records an input, an
    import and a braceless `\\input` in the preamble, and not to one in a comment."""
    (tmp_path / "sections.tex").write_text("\\input{methods}\n", encoding="utf-8")
    for name in ("methods", "macros", "stray"):
        (tmp_path / f"{name}.tex").write_text("We read 4100 reports.\n", encoding="utf-8")
    paper = tmp_path / "paper.tex"
    paper.write_text(("!!documentclass{article}\n!!catcode`!!@=11\n!!input macros\n"
                      "!!begin{document}\n% !!input{stray}\n" + inputs + "\n!!end{document}\n"
                      ).replace("!!", chr(92)), encoding="utf-8")  # fmt: skip
    found = sorted(tmp_path.glob("*.tex"))
    said = audit([paper], None, found_tex=found).passed_over
    for name in ("sections.tex", "methods.tex", "macros.tex"):
        (note,) = [one for one in said if one.split(": ")[0].endswith("/" + name)]
        assert "paper.tex was not read past line 2" in note, note
    (stray,) = [one for one in said if one.split(": ")[0].endswith("/stray.tex")]
    assert "no entry inputs it" in stray, stray


def test_an_input_on_the_line_of_a_stop_is_said_not_followed(tmp_path: Path) -> None:
    """Round 4 of #637: the inputs past a stop were read from the next line, so one on the
    stop's own line was said to be input by no entry."""
    (tmp_path / "sections.tex").write_text("We read 4100 reports.\n", encoding="utf-8")
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\n"
                     "\\catcode`\\@=11 \\input{sections}\n\\end{document}\n", encoding="utf-8")
    said = audit([paper], None, found_tex=[tmp_path / "sections.tex"]).passed_over
    assert any("paper.tex was not read past line 3" in one for one in said), said


def test_a_declaration_past_a_stop_still_decodes_the_file(tmp_path: Path) -> None:
    """Final check of round 2 of #637, finding 3: a declaration past where the reader
    stopped did not count, so the title of a Latin-1 file before it read "?tude". TeX applies
    it whether the reader reads past the stop or not."""
    from manuscript_guard.auditing.latex import read_latex

    paper = tmp_path / "paper.tex"
    paper.write_bytes(("\\documentclass{article}\n\\title{\N{LATIN CAPITAL LETTER E WITH ACUTE}"
                       "tude}\n\\catcode`\\@=11\n\\usepackage[latin1]{inputenc}\n"
                       "\\begin{document}\nx\n\\end{document}\n").encode("latin_1"))
    (tree,) = read_latex([paper]).trees
    assert "\N{LATIN CAPITAL LETTER E WITH ACUTE}tude" in dict(tree.files)[paper].text
