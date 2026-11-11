"""`audit --pdf`: the report as a PDF, with its contents as bookmarks and each check a link
to its section (the author's audit, 2026-11-10: "The best would be an interactive pdf";
written by the package's own `pdfwriter`, as he chose)."""

from __future__ import annotations

import io
import re
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
    # Each link goes to a place in the document, or out to the project's page (the foot of
    # every page, and the closing's "how to use it fully").
    assert links and all(link["/Subtype"] == "/Link" and ("/Dest" in link or (
        link["/A"]["/S"] == "/URI" and link["/A"]["/URI"].startswith("https://")))
        for link in links)  # fmt: skip
    assert any("/Dest" in link for link in links)
    text = "".join(page.extract_text() for page in reader.pages)
    # The Abstract's 412, not found where the paper reports, with its quote.
    assert "Of the patients, 412 improved." in text
    # The report's last line, as the text and the page end with it (round 1 of #618).
    assert "bind the numbers instead" in " ".join(text.split())
    # The title's bookmark holds the checks' table's, and no other.
    top = reader.trailer["/Root"]["/Outlines"]["/First"].get_object()
    assert top["/Count"] == 1


def test_the_pdf_is_framed_says_where_each_check_stands_and_how_to_use_the_tool(
    tmp_path: Path, capsys
) -> None:
    """The author, 2026-11-11: "Make the pdf interactive and visually appealing", "Add a line
    at the bottom 'made with manuscript-guard'", and "only a few gates were checked, see this
    link to see how use fully this programme". Every page's foot says it was made with
    manuscript-guard, links to the project and gives its number of all; every page but the
    first has the title at its top; each check's tile says where it stands and links to its
    section; each section links back to the summary; and the closing says how few gates an
    audit runs, with the link."""
    from manuscript_guard import __version__
    from manuscript_guard.auditing.report_pdf import HOME, STANDING
    from manuscript_guard.gates import GATES

    paper = tmp_path / "paper.md"
    paper.write_text(PAPER + "\n".join(f"\nThe XYZ was seen again in case {n}." for n in
                                       range(60)), encoding="utf-8")  # fmt: skip
    target = tmp_path / "report.pdf"
    assert main(["audit", str(paper), "--pdf", str(target)]) == 0
    capsys.readouterr()
    reader = pypdf.PdfReader(io.BytesIO(target.read_bytes()), strict=True)
    pages = [" ".join(page.extract_text().split()) for page in reader.pages]
    assert len(pages) > 1
    for at, text in enumerate(pages, 1):
        assert f"Made with manuscript-guard {__version__}" in text, at
        assert f"Page {at} of {len(pages)}" in text, at
        assert "Audit of paper.md" in text, at
    first = pages[0]
    assert STANDING["not run"][1] in first and STANDING["look"][1] in first
    assert "Back to the summary" in " ".join(pages)
    # The gates the audit ran, by name (round 1 of #635); G7 found no reference list and left
    # only a note of it, so it is not named (round 2).
    assert f"3 of manuscript-guard's {len(GATES)} gates (G2, G6 and G14)" in " ".join(pages)
    out = [annot.get_object()["/A"]["/URI"] for page in reader.pages
           for annot in page.get("/Annots") or [] if "/A" in annot.get_object()]  # fmt: skip
    assert len(out) >= len(pages) + 1 and set(out) == {HOME}
    places = {annot.get_object()["/Dest"][0].get_object()["/Type"] for page in reader.pages
              for annot in page.get("/Annots") or [] if "/Dest" in annot.get_object()}
    assert places == {"/Page"}


def test_where_each_check_stands_is_read_from_what_it_found() -> None:
    """A check's tile is coloured by what it found, not by its line's words: not run without
    outputs, counted where --strict counts what it found, to look at where a reader has
    something to read, and clear where it found nothing. A paper that gave no number leaves
    its numbers' checks not run, and one that could not be read leaves none clear; a check
    that ran on no paper is not run (round 1 of #635)."""
    from types import SimpleNamespace

    from manuscript_guard.auditing.summary import CLEAR, COUNTED, LOOK, NOT_RUN, standings

    nothing = SimpleNamespace(compared=False, unmatched=[], sums_off=[], over_n=[],
                              flows_broken=[], over_n_rounding=[], disagreements=[],
                              recovered=[], recovered_by_n=[], abstract=None, gates=[],
                              references=[], lookups=None, journal=None, causal=None,
                              cited=None, self_citation=None, package=None, examined=12,
                              unreadable=[], reference_like=[])  # fmt: skip
    said = standings(nothing)
    assert said == {"Numbers in the outputs": NOT_RUN, "Arithmetic": CLEAR,
                    "Small cells": CLEAR}  # fmt: skip
    worse = SimpleNamespace(**{**vars(nothing), "compared": True, "unmatched": [1],
                               "over_n_rounding": [1], "recovered_by_n": [1]})
    assert standings(worse) == {"Numbers in the outputs": COUNTED, "Arithmetic": LOOK,
                                "Small cells": LOOK}  # fmt: skip
    beside = SimpleNamespace(**{**vars(nothing), "compared": True, "reference_like": [1]})
    assert standings(beside)["Numbers in the outputs"] == LOOK
    none_read = SimpleNamespace(**{**vars(nothing), "compared": True, "examined": 0})
    assert set(standings(none_read).values()) == {NOT_RUN}
    unread = SimpleNamespace(**{**vars(nothing), "unreadable": ["scan.pdf"]})
    assert standings(unread)["Arithmetic"] == standings(unread)["Small cells"] == LOOK
    noted = SimpleNamespace(writing=[], language=[], note="G6 and G14 could not run")
    listless = SimpleNamespace(note="no reference list was found", problems=[], unsent=[])
    alone = SimpleNamespace(**{**vars(nothing), "gates": [noted], "references": [listless]})
    assert standings(alone)["Writing and language"] == standings(alone)["References"] == NOT_RUN


def test_a_flag_s_tile_is_not_run_counted_or_to_look_at_as_its_section_is() -> None:
    """G4 that could not run is not run, though its section says why; an author named where
    the journal reviews blind is counted, though the documents hold it; causal words read in
    no sentence are not run; self-citation not counted is not run, and references by an
    author are to look at; the file of cited sentences is to look at; each is clear only
    where it found nothing (round 2 of #635)."""
    from types import SimpleNamespace

    from manuscript_guard.auditing import report as sections
    from manuscript_guard.auditing.causal import CausalRead
    from manuscript_guard.auditing.cited import CitedRead, Row
    from manuscript_guard.auditing.journal import JournalRun
    from manuscript_guard.auditing.selfcite import Author, SelfCitation
    from manuscript_guard.auditing.summary import CLEAR, COUNTED, LOOK, NOT_RUN, _flagged
    from manuscript_guard.findings import Finding

    paper = Path("p.md")

    def journal(**given) -> str:
        run = JournalRun(paper, Path("j.yaml"), **given)
        return _flagged("Journal", run, sections._journal_items(run))

    assert journal(note="G4 could not run on p.md") == NOT_RUN
    assert journal(note="G4 could not run on p.md", skipped=["the word count"]) == NOT_RUN
    assert journal() == CLEAR
    assert journal(manual=[("a cover letter", "")]) == LOOK
    named = Finding("audit", "author-named", "Ada Lovelace is named", path=paper)
    assert journal(named=[named]) == journal(note="G4 could not run", named=[named]) == COUNTED
    # A blind review whose authors nobody looked for is to look at; a review that is not
    # blind, with its note of why nobody looked, is clear (round 3).
    blind = "the journal's review is double-blind, and the authors were not looked for"
    assert journal(blind_note=blind, unsearched=True) == LOOK
    assert journal(blind_note="the profile says the journal's review is open") == CLEAR

    def causal(**given) -> str:
        read = CausalRead("observational", **given)
        return _flagged("Causal words", read, sections._causal_items(read))

    assert causal(unplaced=[paper]) == NOT_RUN
    assert causal(read=12) == CLEAR
    assert causal(read=12, unplaced=[Path("q.md")]) == LOOK

    def self_citation(**given) -> str:
        said = SelfCitation(**given)
        return _flagged("Self-citation", said, sections._self_citation_items(said))

    one = SimpleNamespace(entry=SimpleNamespace(label="[2]"))
    ada = Author("Ada", "Lovelace")
    assert self_citation(note="no reference list was found") == NOT_RUN
    assert self_citation(looked=9, authors=[(ada, [])]) == CLEAR
    assert self_citation(looked=9, authors=[(ada, [one])]) == LOOK
    assert self_citation(looked=9, unlooked=2) == LOOK
    assert self_citation(looked=9, no_people=4, authors=[(ada, [])]) == LOOK
    assert self_citation(looked=9, journal="BMJ", no_journal=3) == LOOK

    def cited(**given) -> str:
        read = CitedRead(**given)
        return _flagged("Cited sentences", read, sections._cited_items(read))

    assert cited() == CLEAR
    assert cited(rows=[Row(paper, 3, "Introduction", "As shown [1].", "[1]", None)]) == LOOK
    assert cited(author_year=12) == cited(pandoc=3) == LOOK


def test_the_closing_names_the_gates_the_audit_ran() -> None:
    """--journal runs G4 as well: the closing names every gate that ran, and counts them
    (round 1 of #635); a gate that left only a note of why it did not run is not named
    (round 2)."""
    from types import SimpleNamespace

    from manuscript_guard.auditing.report_pdf import gates_run, written
    from manuscript_guard.gates import GATES

    view = {"header": [], "notes": [], "checks": [], "standing": {}, "words": [],
            "sections": [], "closing": ""}  # fmt: skip
    data = written(view, "Audit of p.md", "0", ran=("G2", "G4", "G6", "G7", "G14"))
    text = " ".join("".join(page.extract_text() for page in
                            pypdf.PdfReader(io.BytesIO(data), strict=True).pages).split())
    assert f"5 of manuscript-guard's {len(GATES)} gates (G2, G4, G6, G7 and G14)" in text
    ran = SimpleNamespace(writing=[1], language=[], note="")
    noted = SimpleNamespace(writing=[], language=[], note="G6 and G14 could not run")
    counted = SimpleNamespace(note="")
    listless = SimpleNamespace(note="no reference list was found")
    report = SimpleNamespace(gates=[ran, noted], references=[counted],
                             journal=SimpleNamespace(note=""))  # fmt: skip
    assert gates_run(report) == ("G2", "G4", "G6", "G7", "G14")
    report = SimpleNamespace(gates=[noted], references=[listless],
                             journal=SimpleNamespace(note="G4 could not run"))  # fmt: skip
    assert gates_run(report) == ("G2",)
    assert gates_run(SimpleNamespace(gates=[], references=[], journal=None)) == ("G2",)


def test_every_line_stands_within_the_page(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """Every line the report sets, the frame's among them, stands within the margins: a
    running title that names many papers is cut, a long place wraps (round 1 of #635)."""
    from manuscript_guard import pdfwriter, web
    from manuscript_guard.auditing.report_pdf import written

    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.md").write_text(PAPER + "".join(f"\nThe XYZ was seen again in case {n}.\n"
                                                       for n in range(80)), encoding="utf-8")
    view = web.view(["audit", "paper.md", "--details"])["view"]
    for kind in view["words"][0]["kinds"]:
        for place in kind["places"]:
            place["where"] = "a/very/deep/folder/of/a/latex/tree/" * 4 + place["where"]
    # Each line as the writer set it, read back from its pages' commands: pypdf places a
    # line set on another's baseline, a heading's back link, at (0, 0).
    kept: list = []
    real = pdfwriter.Pdf.bytes
    monkeypatch.setattr(pdfwriter.Pdf, "bytes", lambda self: kept.append(self) or real(self))
    written(view, "Audit of " + ", ".join(f"paper-number-{n}.docx" for n in range(12)),
            "0.0.0", ran=("G2", "G6", "G14"))  # fmt: skip
    line = re.compile(rb"BT /(F\d) ([\d.]+) Tf (-?[\d.]+) (-?[\d.]+) Td \(((?:[^()\\]|\\.)*)\) Tj")

    def said(raw: bytes) -> str:
        unescaped = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m[1], 8)]), raw)
        return re.sub(rb"\\([()\\])", rb"\1", unescaped).decode("cp1252")

    placed = [(font.decode(), float(x), float(y),
               pdfwriter.width(said(text), font.decode(), float(size)))
              for page in kept[0].pages for command in page.commands
              for font, size, x, y, text in line.findall(command)]  # fmt: skip
    assert len(kept[0].pages) > 1 and len(placed) > 50
    right = pdfwriter.WIDTH - pdfwriter.MARGIN + 0.5
    for _font, x, y, wide in placed:
        assert x >= pdfwriter.MARGIN - 0.01 and x + wide <= right, (x, y, wide)
        assert 0 < y < pdfwriter.HEIGHT
    # The text read back is set in the regular, the bold and the oblique fonts, so the widths
    # above were measured in each.
    assert {font for font, *_rest in placed} >= {"F1", "F2", "F3"}


def test_a_bookmark_counts_every_level_under_it() -> None:
    from manuscript_guard.pdfwriter import MARGIN, Pdf

    pdf = Pdf(title="Audit")
    for level, title in ((1, "One"), (2, "Two"), (3, "Three"), (2, "Four"), (1, "Five")):
        pdf.heading(title, level)
    reader = pypdf.PdfReader(io.BytesIO(pdf.bytes()), strict=True)
    first = reader.trailer["/Root"]["/Outlines"]["/First"].get_object()
    assert first["/Title"] == "One" and first["/Count"] == 3
    # A heading at a page's foot goes over with the next level's under it.
    for gap in (0, 20, 40, 60, 80, 100):
        low = Pdf(title="Audit")
        low.text("First")
        low.y = MARGIN + 60 + gap
        low.heading("A", 1)
        low.heading("B", 2)
        low.heading("C", 3)
        assert low.outline[0][2] == low.outline[1][2] == low.outline[2][2], gap


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
    # A stroke negates its sign, and is said, not dropped (fix round of #618).
    ("p " + chr(0x2270) + " 0.05", "p not <= 0.05"),
    ("<" + chr(0x338), "not <"),
    ("p <" + chr(0x20D2) + " 0.05", "p not < 0.05"),
    ("so" + chr(0x338) + "ster", "so?ster"),
    # A mark no letter takes, x-bar: "?", never the letter alone.
    ("x" + chr(0x304), "x?"),
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
