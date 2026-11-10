"""`audit --pdf`: the report as a PDF, with its contents as bookmarks and each check a link
to its section (the author's audit, 2026-11-10: "The best would be an interactive pdf";
written by the package's own `pdfwriter`, as he chose)."""

from __future__ import annotations

import io
from pathlib import Path

import pypdf
import pytest

from manuscript_guard.cli import main

PAPER = (
    "# Abstract\n\nOf the patients, 412 improved.\n\n# Methods\n\nThe XYZ panel read every "
    "record (CI 0.1 to 0.2).\n\n# Results\n\nOf the patients, 40 improved (p ≥ 0.05).\n"
)


def _titles(items, depth: int = 0) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for item in items:
        if isinstance(item, list):
            out += _titles(item, depth + 1)
        else:
            out.append((depth, item.title))
    return out


def test_the_audit_writes_its_report_as_a_pdf(tmp_path: Path, capsys) -> None:
    """The PDF reads strictly; its first page says what the text says at its top; each
    section and each kind of finding is a bookmark; each check whose section is printed is
    a link to it."""
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    target = tmp_path / "report.pdf"
    assert main(["audit", str(paper), "--pdf", str(target)]) == 0
    out, err = capsys.readouterr()
    assert f"wrote {target}" in err
    reader = pypdf.PdfReader(io.BytesIO(target.read_bytes()), strict=True)
    first = reader.pages[0].extract_text()
    assert "Audit of paper.md" in first and "numbers read" in first
    assert "What was checked" in first and "Abstract against Results" in first
    titles = _titles(reader.outline)
    assert (0, "Audit of paper.md") in titles and (1, "What was checked") in titles
    assert any(title.startswith("Writing and language") for _depth, title in titles)
    assert any(title.startswith("Abstract against Results") for _depth, title in titles)
    links = [annot.get_object() for page in reader.pages for annot in page.get("/Annots") or []]
    assert links and all(link["/Subtype"] == "/Link" and "/Dest" in link for link in links)
    text = "".join(page.extract_text() for page in reader.pages)
    # The Abstract's 412, found nowhere the paper reports, with its quote.
    assert "Of the patients, 412 improved." in text
    # The report's last line, as the text and the page end with it (round 1 of #618).
    assert "bind the numbers instead" in " ".join(text.split())
    # The title's bookmark holds the checks' table's, and no other.
    top = reader.trailer["/Root"]["/Outlines"]["/First"].get_object()
    assert top["/Count"] == 1


def test_a_bookmark_counts_every_level_under_it() -> None:
    from manuscript_guard.pdfwriter import Pdf

    pdf = Pdf(title="Audit")
    for level, title in ((1, "One"), (2, "Two"), (3, "Three"), (2, "Four"), (1, "Five")):
        pdf.heading(title, level)
    reader = pypdf.PdfReader(io.BytesIO(pdf.bytes()), strict=True)
    first = reader.trailer["/Root"]["/Outlines"]["/First"].get_object()
    assert first["/Title"] == "One" and first["/Count"] == 3


@pytest.mark.parametrize(("target", "said"), [
    ("there.pdf", "the file is there already"),
    ("report.txt", "writes a PDF (.pdf)"),
    ("missing/report.pdf", "its folder does not exist"),
])  # fmt: skip
def test_a_pdf_is_refused_where_it_cannot_be_written(
    tmp_path: Path, capsys, target: str, said: str
) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    (tmp_path / "there.pdf").write_bytes(b"theirs")
    assert main(["audit", str(paper), "--pdf", str(tmp_path / target)]) == 2
    assert said in capsys.readouterr().err
    assert (tmp_path / "there.pdf").read_bytes() == b"theirs"


@pytest.mark.parametrize(("text", "printed"), [
    ("p ≥ 0.05, −2", "p >= 0.05, -2"),
    ("α and β", "alpha and beta"),
    ("Évaluée – “done” ±2", "Évaluée – “done” ±2"),
    ("ő, 結", "o, ?"),
    ("tab\there", "tab here"),
    # A letter and its mark typed apart, as pdftotext and a Mac's file names give them.
    ("E" + chr(0x301) + "tude", "Étude"),
    # A superscript minus, whose plain form Windows-1252 lacks too.
    ("10" + chr(0x207B) + "³", "10-³"),
    # Word's optional hyphen, which would print as a hyphen in mid-line.
    ("hy" + chr(0xAD) + "phen", "hyphen"),
])  # fmt: skip
def test_what_the_fonts_lack_is_written_as_a_reader_would_type_it(text: str, printed: str) -> None:
    from manuscript_guard.pdfwriter import printable

    assert printable(text) == printed


def test_the_page_writes_the_pdf_from_the_audit_it_drew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page saves the report as a PDF (`web.report_pdf`), from the audit `view` ran."""
    from manuscript_guard import web

    monkeypatch.chdir(tmp_path)
    web._AUDITED.clear()
    assert web.report_pdf("out.pdf") == {"error": "no audit was run"}
    (tmp_path / "paper.md").write_text(PAPER, encoding="utf-8")
    assert web.view(["audit", "paper.md"])["view"] is not None
    said = web.report_pdf(str(tmp_path / "out.pdf"))
    assert said["bytes"] > 1000, said
    reader = pypdf.PdfReader(str(tmp_path / "out.pdf"), strict=True)
    assert "Audit of paper.md" in reader.pages[0].extract_text()
