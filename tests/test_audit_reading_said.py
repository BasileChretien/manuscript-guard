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
