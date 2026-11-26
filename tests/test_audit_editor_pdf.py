"""`audit --editor --pdf`: the editor's report as a PDF, in its four parts, every place of
every finding listed (`auditing.editor_pdf`; Basile, 2026-11-26: with `--editor` alone, the
PDF without it staying the full report)."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pypdf
import pytest
from test_audit_readers import profile

from manuscript_guard.auditing import editor
from manuscript_guard.auditing.editor_pdf import FULL, NONE_FOUND
from manuscript_guard.cli import main

#: A paper with findings in every part: an estimate outside its interval (look); a citation
#: past the end of its list, an entry cited nowhere, and, held to `profile`, the main text
#: over 40 words and no Funding statement (ask); three British spellings in an American
#: paper (copyediting); its reference list and the profile's rule to tick (what was read).
PAPER = (
    "# Introduction\n\nThe colour of the urine was recorded in every patient who came to the "
    "clinic during the study [1].\n\n"
    "# Methods\n\nWe counted the patients seen in each month of the year and the share of "
    "them whose urine was dark [3].\n\n"
    "# Results\n\nOf 40 patients, 12 (30%) had dark urine at the first visit, and the odds "
    "ratio was 2.1 (95% CI 2.5 to 3.0).\n\n"
    "# Discussion\n\nDark urine was common among the patients seen at this clinic, as the "
    "behaviour of the colour suggests, and we analysed it.\n\n"
    "# References\n\n1. Smith J. Urine colour. J Ex. 2020;1:1-2.\n"
    "2. Jones K. Another study. J Ex. 2021;2:3-4.\n"
)


def _titles(items, depth: int = 0) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for item in items:
        if isinstance(item, list):
            out += _titles(item, depth + 1)
        else:
            out.append((depth, item.title))
    return out


def _pdf(tmp_path: Path, capsys, text: str = PAPER, *more: str) -> tuple[pypdf.PdfReader, str]:
    paper = tmp_path / "paper.md"
    paper.write_text(text, encoding="utf-8")
    target = tmp_path / "report.pdf"
    assert main(["audit", str(paper), "--english", "american", "--pdf", str(target),
                 *more]) == 0  # fmt: skip
    err = capsys.readouterr().err
    return pypdf.PdfReader(io.BytesIO(target.read_bytes()), strict=True), err


def test_the_editor_s_pdf_gives_the_four_parts_and_every_place(tmp_path: Path, capsys) -> None:
    """The cover names the editor's report and its counts; each part is a bookmark with its
    count, each kind one under its part's with its count; copyediting lists every place,
    as the text does only with --details; and it ends as the full report's does."""
    reader, err = _pdf(tmp_path, capsys, PAPER, "--editor", "--journal",
                       str(profile(tmp_path)))  # fmt: skip
    assert "the editor's report as a PDF, every place in its four parts" in err
    first = reader.pages[0].extract_text()
    assert "Editor's report on paper.md" in first and "to look at before you decide" in first
    assert "In this report" in first
    titles = _titles(reader.outline)
    for number, (_key, heading) in enumerate(editor.PARTS, 1):
        assert any(depth == 0 and title.startswith(f"{number}. {heading} (")
                   for depth, title in titles), heading  # fmt: skip
    disagree = editor.kind_named("numbers-disagree").says
    assert (1, f"{disagree} (1)") in titles
    text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    # Every place of the copyediting: the text gives its first place alone, without --details.
    for spelt in ("'colour' is the British spelling", "'behaviour' is the British spelling",
                  "'analysed' is the British spelling"):
        assert spelt in text, spelt
    assert "Right in 13 of 13 judged on published papers." in text
    assert "paper.md:7" in text and "the journal requires a funding statement" in text
    assert " ".join(FULL.split()) in text and "This audit ran only a few" in text


def test_a_part_with_nothing_in_it_says_so(tmp_path: Path, capsys) -> None:
    reader, _ = _pdf(tmp_path, capsys, "# Methods\n\nWe counted the patients.\n", "--editor")
    text = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
    assert NONE_FOUND in text
    assert _titles(reader.outline)[0] == (0, "Editor's report on paper.md")


def test_without_editor_the_pdf_stays_the_full_report(tmp_path: Path, capsys) -> None:
    reader, err = _pdf(tmp_path, capsys)
    assert "the report as a PDF with every place and every section" in err
    first = reader.pages[0].extract_text()
    assert "Audit of paper.md" in first and "What was checked" in first
    assert "Editor's report" not in first


def test_every_line_of_the_editor_s_pdf_stands_within_the_page(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A place in a deep folder wraps, and every line the report sets stands within the
    margins, as the full report's do (`test_report_pdf`)."""
    from manuscript_guard import pdfwriter

    deep = tmp_path.joinpath(*(["a-very-deep-folder-of-a-latex-tree"] * 6))
    deep.mkdir(parents=True)
    (deep / "paper.md").write_text(PAPER + "".join(
        f"\nThe colour was seen again in case {n}.\n" for n in range(40)), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    kept: list = []
    real = pdfwriter.Pdf.bytes
    monkeypatch.setattr(pdfwriter.Pdf, "bytes", lambda self: kept.append(self) or real(self))
    assert main(["audit", str((deep / "paper.md").relative_to(tmp_path)), "--english",
                 "american", "--editor", "--pdf", "report.pdf"]) == 0  # fmt: skip
    capsys.readouterr()
    line = re.compile(rb"BT /(F\d) ([\d.]+) Tf (-?[\d.]+) (-?[\d.]+) Td \(((?:[^()\\]|\\.)*)\) Tj")

    def said(raw: bytes) -> str:
        unescaped = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m[1], 8)]), raw)
        return re.sub(rb"\\([()\\])", rb"\1", unescaped).decode("cp1252")

    placed = [(float(x), float(y), pdfwriter.width(said(text), font.decode(), float(size)))
              for page in kept[-1].pages for command in page.commands
              for font, size, x, y, text in line.findall(command)]  # fmt: skip
    assert len(kept[-1].pages) > 1 and len(placed) > 50
    right = pdfwriter.WIDTH - pdfwriter.MARGIN + 0.5
    for x, y, wide in placed:
        assert x >= pdfwriter.MARGIN - 0.01 and x + wide <= right, (x, y, wide)
        assert 0 < y < pdfwriter.HEIGHT
