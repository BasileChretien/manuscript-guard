"""A PDF manuscript read by `audit` and `compare` (`auditing.pdf`, docs/refereeing.md).

The PDFs are written here (`tests/proof_pdf.py`), so that every pdftotext on the machine reads
the same bytes, and the tests skip where none is installed, as `proof`'s do. Two builds read a
PDF differently (Xpdf gives a paragraph a line in its layout order, poppler sets the margin's
line numbers apart as a column): what is held here is what each gives, the reading kept being
the one in which the PDF's lines and their numbers are read.

What these hold: each place is a page and a line; the readings that work on text run on a
PDF's (the arithmetic of a test, the Abstract against Results, the reference list, the causal
words, the cited sentences, G6 and G14, G4 with a journal's profile, the blinding check on the
PDF's Author field); its tables and figures are said not to be read, and `compare` never says
one is the same; a PDF is read only where it is named; and without pdftotext it is refused
with one sentence.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from manuscript_guard.auditing import pdf as reading
from manuscript_guard.auditing.pdf import HEADINGS, heading_title
from manuscript_guard.cli import main

sys.path.insert(0, str(Path(__file__).parent))
from proof_pdf import typeset  # noqa: E402

# The loopback registries, standing in for Crossref, OpenAlex and PubMed: no test here
# reaches a registry.
from test_audit_sections import registries  # noqa: E402, F401

needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                     reason="pdftotext is not installed")  # fmt: skip
needs_pdfinfo = pytest.mark.skipif(shutil.which("pdfinfo") is None,
                                   reason="pdfinfo is not installed")  # fmt: skip

#: A paper as a PDF sets it, a line of the PDF to an item. Line 4 of page 1 holds a number of
#: the Abstract the Results do not, line 11 a P that does not follow from its t.
PAPER = [
    "A study of things",
    "Abstract",
    "Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).",
    "The rate was 21.4% in the exposed.",
    "Introduction",
    "Drugs cause harm [1].",
    "Methods",
    "We read 412 records [2].",
    "Results",
    "Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).",
    "The difference was t(48) = 2.10, P = 0.30.",
    "Discussion",
    "Exposure causes the event.",
    "References",
    "1. Smith A. A paper. J Things. 2019;12:345-56. doi:10.1000/xyz123",
    "2. Jones B. Another paper. J Things. 2020;13:1-9.",
    "Table 1. Baseline",
    "Age 54 61",
]


def write(path: Path, lines: list[str] = PAPER, **options) -> Path:
    """`lines` set twelve to a page, under a running head, with the page's number under it."""
    options = {"per_column": 12, "head": "Journal of Things", "foot": "Page", "first_page": 1,
               **options}  # fmt: skip
    path.write_bytes(typeset(lines, columns=1, **options))
    return path


def audited(capsys, *argv: str) -> tuple[int, dict, str]:
    code = main(["audit", *argv, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def found(report: dict, code: str) -> list[dict]:
    return [f for f in report["findings"] if f["code"] == code]


# ---------------------------------------------------------------------------- headings


@pytest.mark.parametrize("name", sorted(HEADINGS))
def test_a_line_that_holds_a_sections_name_alone_is_a_heading(name: str) -> None:
    title = name[:1].upper() + name[1:]
    for written in (title, title.upper(), f"2. {title}", f"2.1 {title}", f"IV. {title}",
                    f"{title}:"):  # fmt: skip
        assert heading_title(written) == (title.upper() if written.isupper() else title), written


@pytest.mark.parametrize("line", [
    "results", "Results of the trial", "The results", "Results were mixed.", "Methodsx",
    "12 patients", "", "References 1. Smith A.", "Table 1. Results",
])
def test_any_other_line_is_none(line: str) -> None:
    """Exact: a section's name and nothing else, a capital first; a wrapped line that happens
    to end on the word is lower case."""
    assert heading_title(line) is None


# ---------------------------------------------------------------------------- audit


@needs_pdftotext
def test_each_place_in_a_pdf_is_a_page_and_a_line(tmp_path: Path, capsys) -> None:
    paper = write(tmp_path / "paper.pdf")
    code, report, _err = audited(capsys, str(paper))
    assert code == 0 and report["counts"]["files"] == 1
    test = found(report, "does-not-fit")
    assert [(f["page"], f["line"]) for f in test] == [(1, 11)], test
    assert "t(48) = 2.10 gives a two-sided P of 0.041" in test[0]["message"]
    abstract = found(report, "abstract-not-found")
    assert [(f["page"], f["line"], f["context"]) for f in abstract] == [
        (1, 4, "The rate was 21.4% in the exposed.")]
    # The reference list, cut at the table's caption under it, is counted and held to the
    # citations; the table's numbers are read as the text's.
    assert report["counts"]["reference_entries"] == 2
    said = [f["message"] for f in found(report, "not-audited")]
    assert any("page 2, lines 2-4, read as the reference list" in s for s in said), said
    assert any("its tables are lines of text, not rows of cells" in s for s in said), said
    assert any("read by pdftotext" in s for s in said), said


@needs_pdftotext
def test_the_text_report_says_page_and_line(tmp_path: Path, capsys) -> None:
    paper = write(tmp_path / "paper.pdf")
    assert main(["audit", str(paper)]) == 0
    out = capsys.readouterr().out
    assert "page 1, line 11: t(48) = 2.10 gives" in out
    assert "page 1, line 4: 21.4%" in out
    # G14 on the PDF's text, at the PDF's page and line.
    assert "G14 paper.pdf, page 1, line 3" in out or "G14 " in out
    assert " line 11:" not in out.replace("page 1, line 11:", "")


@needs_pdftotext
def test_a_pdf_that_numbers_its_lines_gives_the_number(tmp_path: Path, capsys) -> None:
    paper = write(tmp_path / "paper.pdf", line_numbers=True)
    _code, report, _err = audited(capsys, str(paper))
    test = found(report, "does-not-fit")
    assert [(f["page"], f["line"], f["printed_line"]) for f in test] == [(1, 11, 11)], test
    assert main(["audit", str(paper)]) == 0
    assert "page 1, line 11 (numbered 11): t(48)" in capsys.readouterr().out


@needs_pdftotext
def test_a_conflict_between_the_abstract_and_the_results_fails_strict(
    tmp_path: Path, capsys
) -> None:
    """The corruption is in the Abstract: its interval differs in one bound from the
    Results', which --strict counts in a PDF as in any paper."""
    clean = write(tmp_path / "clean.pdf")
    assert main(["audit", str(clean), "--strict"]) == 0
    capsys.readouterr()
    corrupted = [PAPER[0], PAPER[1], PAPER[2].replace("2.10)", "2.20)"), *PAPER[3:]]
    paper = write(tmp_path / "paper.pdf", corrupted)
    code, report, _err = audited(capsys, str(paper), "--strict")
    conflicts = found(report, "abstract-conflict")
    assert code == 1 and [(f["page"], f["line"]) for f in conflicts] == [(1, 3)], conflicts


@needs_pdftotext
def test_causal_words_and_cited_sentences_read_a_pdf(tmp_path: Path, capsys) -> None:
    paper = write(tmp_path / "paper.pdf")
    cited = tmp_path / "cited.md"
    code, report, _err = audited(capsys, str(paper), "--design", "observational", "--cited",
                                 str(cited))  # fmt: skip
    causal = found(report, "causal-word-observational")
    assert code == 0 and [(f["page"], f["line"]) for f in causal] == [(2, 1)], causal
    table = cited.read_text(encoding="utf-8")
    assert "paper.pdf, page 1, line 6 | Introduction | Drugs cause harm [1]." in table
    assert "paper.pdf, page 1, line 8 | Methods | We read 412 records [2]." in table


@needs_pdftotext
def test_headings_that_cannot_be_placed_place_nothing(tmp_path: Path, capsys) -> None:
    """A structured abstract's own headings on lines of their own, with no Introduction after
    them: which Results are the paper's is not read, the Abstract is not compared, and that is
    said."""
    lines = [PAPER[1], "Methods", "We read 412 records.", "Results", PAPER[3],
             *(line for line in PAPER[4:] if line != "Introduction")]  # fmt: skip
    _code, report, _err = audited(capsys, str(write(tmp_path / "paper.pdf", lines)))
    said = " ".join(f["message"] for f in found(report, "not-audited"))
    assert "its lines were placed in no section" in said and "no Introduction after" in said
    assert found(report, "abstract-not-compared")


@needs_pdftotext
def test_a_structured_abstract_before_an_introduction_is_the_abstracts(
    tmp_path: Path, capsys
) -> None:
    """Its headings between the Abstract's and the Introduction's are placed exactly, under
    the Abstract: its Results are the Abstract's, and the paper's own are compared with
    them."""
    lines = [PAPER[1], "Methods", "We read 412 records.", "Results", PAPER[3], *PAPER[4:]]
    pdf = reading.read_pdf(write(tmp_path / "paper.pdf", lines))
    assert [level for _line, _title, level in pdf.placed] == [1, 2, 2, 1, 1, 1, 1, 1]
    _code, report, _err = audited(capsys, str(tmp_path / "paper.pdf"))
    assert not found(report, "abstract-not-compared")
    assert [f["context"] for f in found(report, "abstract-not-found")] == [
        "The rate was 21.4% in the exposed."]


@needs_pdftotext
def test_a_pdf_in_a_folder_is_not_read(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "submission"
    folder.mkdir()
    write(folder / "paper.pdf")
    (folder / "paper.md").write_text("# Results\n\nOf 412 patients, 77 had it.\n",
                                     encoding="utf-8")  # fmt: skip
    code, report, _err = audited(capsys, str(folder))
    assert code == 0 and report["counts"]["files"] == 1
    assert [f["message"] for f in found(report, "passed-over")] == [
        "1 PDF file in the folder given was not read: a PDF is audited only where it is "
        "named on its own"]


def test_without_pdftotext_a_pdf_is_refused_with_one_sentence(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(PAPER, columns=1))
    which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "pdftotext"
                        else which(name, *a, **k))  # fmt: skip
    assert main(["audit", str(paper)]) == 2
    err = capsys.readouterr().err
    assert "paper.pdf is a PDF, and a PDF is read by pdftotext, which is not installed here" in err
    other = tmp_path / "other.md"
    other.write_text("# Results\n\nOf 412.\n", encoding="utf-8")
    assert main(["compare", str(other), str(paper)]) == 2
    assert "which is not installed here" in capsys.readouterr().err


@needs_pdftotext
def test_a_pdf_with_no_text_is_refused(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "scan.pdf"
    paper.write_bytes(typeset([" "], columns=1))
    assert main(["audit", str(paper)]) == 2
    assert "holds no text pdftotext can read" in capsys.readouterr().err


def test_pdftotext_and_pdfinfo_are_given_a_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each program the reading runs is waited for a while only; one that takes longer is
    said not to have answered (CLAUDE.md: `check` never waits on a program without one)."""
    asked: list[float | None] = []

    def run(argv, **options):
        asked.append(options.get("timeout"))
        raise subprocess.TimeoutExpired(argv, options.get("timeout") or 0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: f"/bin/{name}")
    assert reading.author(tmp_path / "x.pdf") == (None, "pdfinfo took more than 30 seconds")
    with pytest.raises(reading.UnreadablePdf, match="pdftotext did not answer within 120"):
        reading._read(tmp_path / "x.pdf")
    assert asked and all(limit for limit in asked), asked


@needs_pdftotext
def test_a_failing_pdftotext_is_said_to_have_failed(tmp_path: Path, capsys) -> None:
    """A damaged PDF is no scan: pdftotext failed on it, and that is what is said."""
    paper = tmp_path / "broken.pdf"
    paper.write_bytes(b"%PDF-1.4\nnot a PDF at all\n")
    assert main(["audit", str(paper)]) == 2
    err = capsys.readouterr().err
    assert "broken.pdf could not be read: pdftotext failed on it" in err, err


@needs_pdftotext
def test_a_line_number_counted_on_is_not_given_as_the_pdfs(tmp_path: Path) -> None:
    """The PDF prints each line's number but the seventh's: line 8's is the PDF's, line 7's
    is only counted on, and is not shown as the PDF's."""
    from proof_pdf import LEADING, LEFT, TOP, Piece, pdf

    pieces = []
    for row in range(25):
        y = TOP - LEADING * row
        if row != 6:
            pieces.append(Piece(LEFT - 22, y, str(row + 1), size=6.0))
        pieces.append(Piece(LEFT, y, f"Line of text {chr(97 + row)} here."))
    path = tmp_path / "paper.pdf"
    path.write_bytes(pdf([pieces]))
    read = reading.read_pdf(path)
    assert read.numbered, read.reader
    printed = {place.line: place.printed for place in read.places}
    assert printed[8] == 8 and printed[7] is None, printed


# ---------------------------------------------------------------------------- reader options


def profile(tmp_path: Path, *, blinding: str = "double") -> Path:
    path = tmp_path / "journal.yaml"
    path.write_text(
        "schema: manuscript-guard/journal/1\nname: The Journal of Examples\n"
        "source_url: https://example.org/authors\n"
        f"retrieved_on: {date.today().isoformat()}\n"
        f"blinding: {blinding}\n"
        "limits:\n  main_text_words: 4000\n  tables: 5\n",
        encoding="utf-8",
    )
    return path


def authors(tmp_path: Path) -> Path:
    path = tmp_path / "authors.yaml"
    path.write_text("authors:\n  - given: Ada\n    family: Example\n    email: ada@example.org\n",
                    encoding="utf-8")  # fmt: skip
    return path


@needs_pdftotext
def test_a_journals_limits_on_tables_are_not_checked_in_a_pdf(tmp_path: Path, capsys) -> None:
    paper = write(tmp_path / "paper.pdf")
    _code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)))
    skipped = [f["message"] for f in found(report, "journal-not-checked")]
    assert any("a PDF's tables and figures are not read as such" in s for s in skipped), skipped
    document = found(report, "document-holds")
    assert [f["message"].split(":")[0] for f in document] == ["paper.pdf"]
    assert "whose tracked changes, comments and hidden text" in document[0]["message"]
    assert "tracked_insertions" not in report["counts"]


@needs_pdftotext
@needs_pdfinfo
def test_an_author_in_a_blind_pdfs_author_field_is_counted(tmp_path: Path, capsys) -> None:
    clean = write(tmp_path / "clean.pdf", author="Editorial Office")
    code, report, _err = audited(capsys, str(clean), "--journal", str(profile(tmp_path)),
                                 "--authors", str(authors(tmp_path)), "--strict")  # fmt: skip
    assert code == 0 and not found(report, "blind-document-names-author")
    assert [f["message"] for f in found(report, "document-person")] == [
        f"{reading.AUTHOR_FIELD}: Editorial Office"]
    paper = write(tmp_path / "paper.pdf", author="Ada Example")
    code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)),
                                 "--authors", str(authors(tmp_path)), "--strict")  # fmt: skip
    named = found(report, "blind-document-names-author")
    assert code == 1 and len(named) == 1 and "the PDF's author" in named[0]["message"], named


@needs_pdftotext
def test_an_author_in_a_blind_pdfs_running_head_is_counted(tmp_path: Path, capsys) -> None:
    """The reading takes the running head out of the text; the blinding check reads it."""
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(PAPER, columns=1, per_column=12, head="Ada Example et al.",
                              foot="Page", first_page=1))  # fmt: skip
    code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)),
                                 "--authors", str(authors(tmp_path)), "--strict")  # fmt: skip
    named = found(report, "blind-document-names-author")
    assert code == 1 and [f["message"].split(" of paper.pdf")[0] for f in named] == [
        "'Ada Example' is in the running head of page 1 (and of 1 more page)"], named


@needs_pdftotext
def test_word_limits_of_a_pdf_whose_abstract_cannot_be_placed_are_not_checked(
    tmp_path: Path, capsys
) -> None:
    """A 400-word structured abstract against a limit of 250: a finding where its headings
    are placed exactly, and "not checked" where they are not, never silence."""
    words = " ".join(["word"] * 8)
    abstract = ["Abstract", "Background", *[f"{words}."] * 25, "Methods", *[f"{words}."] * 25]
    body = ["Introduction", "Drugs cause harm.", "Methods", "We read 412 records.", "Results",
            "Of 412, 77 had it.", "Discussion", "It was so."]  # fmt: skip
    journal = tmp_path / "words.yaml"
    journal.write_text(profile(tmp_path).read_text(encoding="utf-8").replace(
        "  tables: 5\n", "  abstract_words: 250\n"), encoding="utf-8")  # fmt: skip
    placed = write(tmp_path / "placed.pdf", [*abstract, *body], per_column=70)
    _code, report, _err = audited(capsys, str(placed), "--journal", str(journal))
    over = [f["message"] for f in found(report, "over-journal-limit")]
    assert any(m.startswith("abstract: 4") for m in over), over
    unplaced = write(tmp_path / "unplaced.pdf", [*abstract, *body[2:]], per_column=70)
    _code, report, _err = audited(capsys, str(unplaced), "--journal", str(journal))
    assert not [f for f in found(report, "over-journal-limit")
                if f["message"].startswith("abstract: ")]  # fmt: skip
    skipped = [f["message"] for f in found(report, "journal-not-checked")]
    assert any("headings could not be placed exactly" in m for m in skipped), skipped


@needs_pdftotext
def test_without_pdfinfo_the_author_field_is_said_not_read(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = write(tmp_path / "paper.pdf", author="Ada Example")
    which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "pdfinfo"
                        else which(name, *a, **k))  # fmt: skip
    code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)),
                                 "--authors", str(authors(tmp_path)), "--strict")  # fmt: skip
    notes = [f["message"] for f in found(report, "authors-not-looked-for")]
    assert code == 0 and notes == [
        "paper.pdf: its Author field was not read for the authors' names: pdfinfo is not "
        "installed"]
    assert "its Author field was not read: pdfinfo is not installed" in found(
        report, "document-holds")[0]["message"]


# ---------------------------------------------------------------------------- compare


@needs_pdftotext
def test_compare_reads_two_pdfs_and_never_says_a_table_is_the_same(
    tmp_path: Path, capsys
) -> None:
    old = write(tmp_path / "v1.pdf")
    new = write(tmp_path / "v2.pdf", [line.replace("21.4%", "22.4%") for line in PAPER])
    letter = tmp_path / "letter.md"
    letter.write_text("We revised Table 1 as asked.\n", encoding="utf-8")
    assert main(["compare", str(old), str(new), "--response", str(letter), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    changed = found(report, "fact-changed")
    assert [(f["page"], f["line"], f["message"]) for f in changed] == [
        (1, 4, "'21.4' on page 1, line 4 of v1 is '22.4' in v2")], changed
    codes = {f["code"] for f in report["findings"]}
    assert "displays-not-compared" in codes and not {"table-same", "figure-same"} & codes
    named = found(report, "named")
    assert [f["message"] for f in named] == ["Table 1, named on line 1: not compared: v1 and "
                                             "v2 are PDFs"]  # fmt: skip
    assert {f["message"].split(":")[0] for f in found(report, "section-same")} >= {
        "the section 'Methods'", "the section 'Results'"}


@needs_pdftotext
def test_a_tables_numbers_are_read_alike_beside_a_pdf(tmp_path: Path, capsys) -> None:
    """A PDF's table is prose, and so is the other version's where one side is a PDF: 54 and
    61, in v1's table and in v2's lines, are neither gone nor new."""
    old = tmp_path / "v1.md"
    old.write_text("# Results\n\nOf 412 patients, 77 had the event.\n\nTable 1. Baseline\n\n"
                   "| | Cases |\n|---|---|\n| Age | 54 |\n| Weight | 61 |\n",
                   encoding="utf-8")  # fmt: skip
    # One page, with no running head or foot, which a one-page PDF does not have taken out.
    new = write(tmp_path / "v2.pdf", ["Results", "Of 412 patients, 77 had the event.",
                                      "Table 1. Baseline", "Cases", "Age 54", "Weight 61"],
                head=None, foot=None, first_page=None)
    assert main(["compare", str(old), str(new), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    moved = [f["message"] for f in report["findings"]
             if f["code"] in ("fact-new", "fact-gone", "fact-changed")]  # fmt: skip
    assert moved == [], moved
    assert [f["message"] for f in found(report, "tables-read-as-prose")] == [
        "tables are read as prose in both versions, since v2 is a PDF, whose tables cannot be "
        "set apart"]


@needs_pdftotext
def test_compare_sets_a_pdf_beside_a_word_or_markdown_version(tmp_path: Path, capsys) -> None:
    old = tmp_path / "v1.md"
    old.write_text("# Results\n\n| Age | 54 |\n|---|---|\n| Sex | 61 |\n\nTable 1. Baseline\n",
                   encoding="utf-8")  # fmt: skip
    new = write(tmp_path / "v2.pdf")
    assert main(["compare", str(old), str(new)]) == 0
    out = capsys.readouterr().out
    assert "the tables are not compared: v2 is a PDF" in out
    assert "table-gone" not in out and "is gone from v2" not in out.split("Tables")[1].split(
        "Figures")[0]


# ---------------------------------------------------------------------------- reference lists


def test_a_wrapped_page_range_opens_no_entry(tmp_path: Path) -> None:
    """Note 3 of round 1: "118." after "112-" goes on entry 1; only "2." opens the next."""
    from manuscript_guard.auditing.references import NUMBERED, census_of_printed

    text = "References\n1. Smith A. A paper. J Things. 2019;12:112-\n118. More of it.\n" \
           "2. Jones B. Another. J Things. 2020;13:1-9.\n"
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 4)], "Of 4 [1, 2].\n", [])
    assert census.style == NUMBERED and [e.number for e in census.entries] == [1, 2]
    assert not census.problems


def test_entries_not_told_apart_have_each_identifier_looked_up(tmp_path: Path,
                                                               capsys) -> None:  # fmt: skip
    """An author-year list in a PDF is one stretch of lines: each DOI is asked alone, no
    citation is held to an entry, and the report says why."""
    from manuscript_guard.auditing.references import UNTOLD, census_of_printed, look_up

    text = ("References\nAdams A (2019) doi:10.5555/one.1 A first paper.\n"
            "Brown B (2020) doi:10.5555/two.2 A second paper.\n"
            "Clark C (2021) doi:10.5555/three.3 A third paper.\n")
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 4)], "As shown [9].\n", [])
    assert census.style == UNTOLD and not census.problems
    asked = [one.entry.dois for one in look_up([census], dry_run=True)]
    assert asked == [("10.5555/one.1",), ("10.5555/two.2",), ("10.5555/three.3",)]


@needs_pdftotext
def test_an_author_year_pdf_is_looked_up_one_identifier_at_a_time(tmp_path: Path,
                                                                  capsys) -> None:  # fmt: skip
    lines = ["Results", "Of 412, 77 had it (Adams, 2019).", "References",
             "Adams A (2019) doi:10.5555/one.1 A first paper.",
             "Brown B (2020) doi:10.5555/two.2 A second paper.",
             "Clark C (2021) doi:10.5555/three.3 A third paper."]
    paper = write(tmp_path / "paper.pdf", lines)
    _code, report, _err = audited(capsys, str(paper), "--lookup", "--dry-run")
    assert len(found(report, "would-ask")) == 3
    assert found(report, "entries-not-told-apart")
    assert not found(report, "entry-never-cited") and not found(report, "citation-not-listed")


@needs_pdftotext
def test_a_doi_cut_at_a_lines_end_is_not_sent(tmp_path: Path, registries,  # noqa: F811
                                             capsys) -> None:  # fmt: skip
    """Review round 1: "10.1056/NEJMoa20" then "34577" on the next line sent the cut DOI,
    and the report said no registry had it."""
    registries.answers = {"doi_org": (404, {"responseCode": 100})}
    lines = ["Results", "Of 412, 77 had it [1].", "References",
             "1. Smith A. A paper. N Engl J Med. doi:10.1056/NEJMoa20",
             "34577. Epub 2020."]
    paper = write(tmp_path / "paper.pdf", lines)
    _code, report, _err = audited(capsys, str(paper), "--lookup")
    assert registries.seen == [], registries.seen
    assert not found(report, "doi-unregistered")
    assert [(f["message"], f["page"]) for f in found(report, "identifier-not-sent")] == [
        ("10.1056/nejmoa20: not looked up: it may continue on the next line", 1)]
