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
    """Each name, numbered or not; the singular "Result" numbered only (`NUMBERED_ONLY`)."""
    title = name[:1].upper() + name[1:]
    numbered = (f"2. {title}", f"2.1 {title}", f"IV. {title}", f"3 {title}")
    bare = () if name in reading.NUMBERED_ONLY else (title, title.upper(), f"{title}:")
    for written in (*numbered, *bare):
        assert heading_title(written) == (title.upper() if written.isupper() else title), written


@pytest.mark.parametrize("line", [
    "results", "Results of the trial", "The results", "Results were mixed.", "Methodsx",
    "12 patients", "", "References 1. Smith A.", "Table 1. Results",
    # The singular as a heading's words alone (Basile, 2026-11-15): not in small letters, not
    # opening a sentence, not in a table's row read as a line, and, in a PDF, not unnumbered,
    # as a table's column headed "Result" is (round 1 of #687).
    "result", "Result of the survey", "Outcome Result 95% CI P", "Result", "RESULT",
    "Result:",
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
    # G14 on the PDF's text, grouped by kind, each place the PDF's page and line.
    assert "(G14, " in out and "    page 1, line 3: " in out
    assert " line 11:" not in out.replace("page 1, line 11:", "")
    assert main(["audit", str(paper), "--details"]) == 0
    assert "G14 paper.pdf, page 1, line 3" in capsys.readouterr().out


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
    them and none of their names again: which Results are the paper's is not read, the
    Abstract is not compared, and that is said."""
    lines = [PAPER[1], "Methods", "We read 412 records.", "Results", PAPER[3],
             *(line for line in PAPER[4:] if line not in ("Introduction", "Methods", "Results"))]
    _code, report, _err = audited(capsys, str(write(tmp_path / "paper.pdf", lines)))
    said = " ".join(f["message"] for f in found(report, "not-audited"))
    assert "its lines were placed in no section" in said and "no Introduction after" in said
    assert found(report, "abstract-not-compared")


@needs_pdftotext
def test_a_structured_abstract_ends_where_the_main_text_names_a_part_again(
    tmp_path: Path, capsys
) -> None:
    """BMC's journals set a structured abstract's Background, Methods and Results on lines of
    their own and open the main text on a second "Background", with no Introduction: the
    abstract's parts end where one of their names comes again, and its Abstract is compared
    with the paper's own Results."""
    lines = [PAPER[1], "Methods", "We read 412 records.", "Results", PAPER[3],
             *(line for line in PAPER[4:] if line != "Introduction")]  # fmt: skip
    pdf = reading.read_pdf(write(tmp_path / "paper.pdf", lines))
    assert [level for _line, _title, level in pdf.placed] == [1, 2, 2, 1, 1, 1, 1]
    _code, report, _err = audited(capsys, str(tmp_path / "paper.pdf"))
    assert not found(report, "abstract-not-compared")


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
def test_a_results_section_numbered_in_the_singular_is_the_results(
    tmp_path: Path, capsys
) -> None:
    """"3. Result" over "3.1. Preliminary Analyses", as pdf-psych-B3 of the real-paper corpus
    numbers its Results (Basile, 2026-11-15): "Result" named no section, its lines were the
    Methods', and the Abstract was compared with nothing. It is the Results' heading now,
    and the Abstract is compared with what it holds."""
    lines = [("3. Result" if line == "Results" else line) for line in PAPER]
    at = lines.index("3. Result") + 1
    lines[at:at] = ["3.1. Preliminary Analyses"]
    pdf = reading.read_pdf(write(tmp_path / "paper.pdf", lines))
    assert [title for _line, title in pdf.headings] == [
        "Abstract", "Introduction", "Methods", "Result", "Discussion", "References"]
    _code, report, _err = audited(capsys, str(tmp_path / "paper.pdf"))
    assert not found(report, "abstract-not-compared")
    assert [f["context"] for f in found(report, "abstract-not-found")] == [
        "The rate was 21.4% in the exposed."]


def _set(rows: list[str | tuple[tuple[float, str], ...]]) -> bytes:
    """A page of `rows`, a line of text or a table's row, each of its cells set at its own
    left edge on one line, as a journal sets a table."""
    from proof_pdf import LEADING, LEFT, TOP, Piece, pdf

    pieces = []
    for at, row in enumerate(rows):
        y = TOP - LEADING * at
        cells = ((0.0, row),) if isinstance(row, str) else row
        pieces += [Piece(LEFT + x, y, text) for x, text in cells]
    return pdf([pieces])


#: A paper's lines on one page, long enough that pdftotext reads its text as one column.
_LONG = "Of 412 patients enrolled at three centres, 77 had the event during follow-up."


def _table(at: int = 120) -> list:
    """A table's caption, its column headed "Result" on a line of its own, and its rows, each
    cell set apart: poppler's layout order (pdftotext 24.04.0) sets each cell on a line of
    its own, its header row's too."""
    return ["Table 1. Outcomes", ((at, "Result"),),
            *(((0, f"Outcome {k}"), (at, f"{7 * k}"), (220, f"1.{k}-2.{k}"))
              for k in range(1, 7))]  # fmt: skip


@needs_pdftotext
def test_a_table_s_column_headed_result_is_no_heading(tmp_path: Path) -> None:
    """A table's column headed "Result" on a line of its own holds a section's name alone,
    and in a PDF the singular is a heading only numbered as a section (round 1 of #687): the
    column is a line of the table, and the PDF is placed."""
    rows = ["Abstract", _LONG, "Introduction", _LONG, "Methods", _LONG, "Results", _LONG,
            *_table(), "Discussion", _LONG]  # fmt: skip
    path = tmp_path / "paper.pdf"
    path.write_bytes(_set(rows))
    pdf = reading.read_pdf(path)
    assert [title for _line, title in pdf.headings] == [
        "Abstract", "Introduction", "Methods", "Results", "Discussion"], pdf.text
    assert pdf.placed is not None


@needs_pdftotext
def test_a_numbered_result_beside_a_column_headed_result_is_placed(tmp_path: Path) -> None:
    """Round 1 of #687: "3. Result" and a table's column headed "Result" on a line of its
    own named the section twice, and a PDF that was placed before was placed in no section.
    The column is no heading, and the PDF is placed."""
    rows = ["Abstract", _LONG, "1. Introduction", _LONG, "2. Methods", _LONG, "3. Result",
            _LONG, *_table(), "4. Discussion", _LONG]  # fmt: skip
    path = tmp_path / "paper.pdf"
    path.write_bytes(_set(rows))
    pdf = reading.read_pdf(path)
    assert [title for _line, title in pdf.headings] == [
        "Abstract", "Introduction", "Methods", "Result", "Discussion"], pdf.text
    assert pdf.placed is not None


@needs_pdftotext
def test_a_column_headed_result_in_the_discussion_opens_no_results(
    tmp_path: Path, capsys
) -> None:
    """Round 1 of #687: a table's column headed "Result" in the Discussion opened a Results
    there, and an Abstract's number the Results do not give but the Discussion repeats after
    the table was found. The column is no heading: the number is not found."""
    rows = ["Abstract", "In all, 1,284 adults were enrolled.", "Introduction", _LONG,
            "Methods", _LONG, "Results", _LONG, "Discussion", _LONG, *_table(),
            "In all, 1,284 adults were enrolled, as earlier work found."]  # fmt: skip
    path = tmp_path / "paper.pdf"
    path.write_bytes(_set(rows))
    _code, report, _err = audited(capsys, str(path))
    assert not found(report, "abstract-not-compared")
    assert [f["context"] for f in found(report, "abstract-not-found")] == [
        "In all, 1,284 adults were enrolled."]


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
def test_a_place_a_finding_names_in_a_pdf_is_its_page_and_line(tmp_path: Path, capsys) -> None:
    """End to end, as round 1 of #545 asked (finding 4): the place G14 names is the PDF's
    page and line, mapped through the staged lines, and no finding names the staged
    Markdown. `audit --journal` does not map it so (Known gaps, the audit's places)."""
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(typeset(["Methods", "We report the standard deviation (SD) of each score.",
                               "Results",
                               "The SD was small, and the standard deviation (SD) was stable."],
                              columns=1))  # fmt: skip
    assert main(["audit", str(paper), "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["findings"]
    again = [f["message"] for f in found if f["gate"] == "G14" and "defined again" in f["message"]]
    assert again == ["SD is defined again; it was defined at page 1, line 2"], found
    assert not any("main.md" in json.dumps(f) for f in found), found


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
    are placed exactly, and "not checked" where they are not (no Introduction after its
    parts and none of their names again), never silence."""
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
    unplaced = write(tmp_path / "unplaced.pdf", [*abstract, *body[4:]], per_column=70)
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


# ---------------------------------------------------------------------- the report draft (#487)


@needs_pdftotext
def test_an_audit_draft_places_a_pdfs_findings_by_page(tmp_path: Path, capsys) -> None:
    """With #487's `--report-draft`: a finding in a PDF is at its page and line, as the report
    gives it, and the draft says the PDF's tables and lists were not read as such."""
    paper = write(tmp_path / "paper.pdf")
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    placed = [line for line in text.splitlines()
              if line.startswith(("- paper.pdf line ", "- paper.pdf page "))]  # fmt: skip
    assert placed and all(line.startswith("- paper.pdf page ") for line in placed), placed
    unchecked = text.split("## Exact findings")[0]
    assert "A PDF's tables and lists:" in unchecked
    # The paper is no figure: none was given, though its labels drawn as text were read.
    assert "Figures: none was given (`--figures`)" in unchecked


@needs_pdftotext
def test_a_pdf_figure_is_no_pdf_paper_in_the_draft(tmp_path: Path, capsys) -> None:
    """A PDF given with `--figures` is read as a figure, not through pdftotext as a paper: the
    draft says nothing of a PDF's tables, and that a figure was given."""
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nOf 412 patients, 37 had dark urine.\n", encoding="utf-8")
    figure = write(tmp_path / "forest.pdf", ["Figure 1", "Odds ratio 1.42"])
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--figures", str(figure),
                 "--report-draft", str(target)]) in (0, 1)  # fmt: skip
    capsys.readouterr()
    unchecked = target.read_text(encoding="utf-8").split("## Exact findings")[0]
    assert "A PDF's tables and lists:" not in unchecked
    assert "Figures: none was given" not in unchecked


@needs_pdftotext
def test_a_compare_draft_beside_a_pdf_lists_no_table_or_figure_check(tmp_path: Path,
                                                                       capsys) -> None:  # fmt: skip
    """Where either version is a PDF, the tables and the figures are not compared: the draft
    says so, and does not list them among the checks that found nothing."""
    old = tmp_path / "v1.md"
    old.write_text("# Results\n\n| Age | 54 |\n|---|---|\n| Sex | 61 |\n\nTable 1. Baseline\n",
                   encoding="utf-8")  # fmt: skip
    new = write(tmp_path / "v2.pdf")
    target = tmp_path / "d.md"
    assert main(["compare", str(old), str(new), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    nothing = text.split("## Checks that ran and found nothing")[1]
    assert "Tables, cell by cell" not in nothing and "Figures, by their captions" not in nothing
    assert "The tables and the figures: not compared, since v2 is a PDF" in text


# ---------------------------------------------------------------------------- reference lists


@pytest.mark.parametrize("dash", ["-", "\N{EN DASH}"])
def test_a_wrapped_page_range_opens_no_entry(tmp_path: Path, dash: str) -> None:
    """Note 3 of round 1: "118." after "112-" opens no entry 118. A line that ends in a hyphen
    or a dash never ends an entry (the fix-only round), so the list stays numbered and its
    citations are held to it."""
    from manuscript_guard.auditing.references import NUMBERED, census_of_printed

    text = (f"References\n1. Smith A. A paper. J Things. 2019;12:112{dash}\n118. More of it.\n"
            "2. Jones B. Another. J Things. 2020;13:1-9.\n")
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 4)], "Of 4 [1, 3].\n", [])
    assert census.style == NUMBERED and [e.number for e in census.entries] == [1, 2]
    assert sorted(p.code for p in census.problems) == ["citation-beyond-list",
                                                       "entry-never-cited"]


def test_a_page_range_wrapped_across_a_blank_line_opens_no_entry(tmp_path: Path) -> None:
    """The last fix-only round: the line before is the entry's last, a blank between them or
    not."""
    from manuscript_guard.auditing.references import NUMBERED, census_of_printed

    text = "References\n1. Smith A. 2019;12:112-\n\n118. More.\n2. Jones B. 2020;1:1-9.\n"
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 5)], "As [1, 2] show.\n", [])
    assert census.style == NUMBERED and [e.number for e in census.entries] == [1, 2]


def test_an_entry_number_is_not_read_as_a_pmid(tmp_path: Path) -> None:
    """The last fix-only round: "PMID:" with no digits, the next line opening "4.", reads no
    PMID 4; the cut "PMID:" is listed."""
    from manuscript_guard.auditing.references import census_of_printed

    text = "References\n1. A. One.\n2. B. PMID:\n4. D. Four.\n"
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 4)], "As [1] [2] [4].\n", [])
    assert all(not entry.pmids for entry in census.entries)
    assert census.unsent == [(3, "PMID:")]
    # A PMID that short, a stop after it, is read so too (DESIGN.md, Known gaps).
    census = census_of_printed(tmp_path / "p.pdf", "References\n1. A. PMID:\n123. Epub.\n",
                               [(0, 3)], "As [1].\n", [])  # fmt: skip
    assert all(not entry.pmids for entry in census.entries)
    assert census.unsent == [(2, "PMID:")]


def test_an_entry_whose_identifier_was_held_back_is_not_said_to_have_none(tmp_path: Path) -> None:
    """The review of #632: a DOI that ends a line its entry runs on past, and a "PMID:" cut
    short, are listed as not sent; their entries are not named again as having no DOI or
    PMID, nor counted so. An entry with neither is."""
    from manuscript_guard.auditing.references import census_of_printed, without_identifier
    from manuscript_guard.auditing.report import _shown, _unlooked

    text = ("References\n1. Brown L. A note. Drug Saf. 2021;44:1-2. doi:10.1016/j.ds.2021\n"
            "more of it. Epub.\n2. Green M. A review. PMID:\n3. Clark C. A letter. J X. "
            "2019;1:2.\n")  # fmt: skip
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 5)], "As [1-3] show.\n", [])
    assert sorted(census.unsent) == [(2, "10.1016/j.ds.2021"), (4, "PMID:")]
    assert [without_identifier(entry) for entry in census.entries] == [False, False, True]
    assert _unlooked(census, _shown(None))[:2] == [
        "    with no DOI or PMID given: 1 entry",
        "      line 5: entry 3: Clark C. A letter. J X. 2019;1:2."]
    # The summary counts both kinds (round 2 of #632), and an unnumbered entry keeps its year.
    from types import SimpleNamespace

    from manuscript_guard.auditing.summary import _references

    said = _references(SimpleNamespace(references=[census], lookups=[]))
    assert said.endswith("1 entry to check by hand (its title too short to look up, or not "
                         "read) and 2 entries not looked up, their DOI or PMID perhaps running "
                         "on to the next line: see below"), said  # fmt: skip
    from manuscript_guard.auditing.references import BY_PLACE, Entry

    unnumbered = SimpleNamespace(path=tmp_path / "p.md", style="not numbered", entries=(
        Entry("entry 2 of the list", 3, text="2019. Another guideline. Geneva."),))
    assert _unlooked(unnumbered, _shown(None))[1] == (
        "      line 3: entry 2 of the list: 2019. Another guideline. Geneva.")
    # Nor one Word numbers, whose text holds no number (round 3 of #632).
    by_word = SimpleNamespace(path=tmp_path / "p.md", style=BY_PLACE, entries=(
        Entry("entry 4", 3, number=4, text="2019. WHO guideline on X."),))
    assert _unlooked(by_word, _shown(None))[1] == "      line 3: entry 4: 2019. WHO guideline on X."


def test_a_number_that_skips_tells_no_entry_apart(tmp_path: Path) -> None:
    """Round 2: "1. 2. 4. 5." cited [1] [2] [4] [5] was "cites entries 4, 5 ... it has 2
    entries". The list is not told apart, says why, and nothing is held to its count."""
    from manuscript_guard.auditing.references import UNTOLD, census_of_printed
    from manuscript_guard.auditing.report import _printed_items

    text = "References\n1. A. doi:10.5555/a.1 One.\n2. B. Two.\n4. D. Four.\n5. E. Five.\n"
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 5)],
                               "As [1] [2] [4] [5] show.\n", [])  # fmt: skip
    assert census.style == UNTOLD and not census.problems
    assert "its numbers go from 2 to 4, at line 4" in census.untold
    said = [item.message for item in _printed_items(census)]
    assert said and "its numbers go from 2 to 4" in said[0], said
    assert [entry.dois for entry in census.entries] == [("10.5555/a.1",)]


def test_an_untold_list_looks_up_each_identifier_ending_a_line(tmp_path: Path) -> None:
    """Round 2: in an author-year list each DOI ends its line, with more of the list after
    it; each is looked up all the same."""
    from manuscript_guard.auditing.references import UNTOLD, census_of_printed, look_up

    text = ("References\nAdams A (2019) A first paper. J X. doi:10.5555/one.1\n"
            "Brown B (2020) A second paper. J X. doi:10.5555/two.2\n"
            "Clark C (2021) A third paper. J X. doi:10.5555/three.3\n")
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 4)], "As shown.\n", [])
    assert census.style == UNTOLD and census.unsent == []
    asked = [one.entry.dois for one in look_up([census], dry_run=True)]
    assert asked == [("10.5555/one.1",), ("10.5555/two.2",), ("10.5555/three.3",)]
    assert [entry.ends_line for entry in census.entries] == [True, True, False]


def test_a_doi_on_the_line_after_its_prefix_is_sent(tmp_path: Path) -> None:
    """The fix-only round: NLM breaks at the space in "doi: 10...", and the DOI on the next
    line is read and sent; its prefix is not listed as not looked up."""
    from manuscript_guard.auditing.references import NUMBERED, census_of_printed

    text = ("References\n1. Smith A. A paper. J X. 2020;1:1-9. doi:\n10.1016/j.x.2020.01.001\n"
            "2. Jones B. Another. PMID:\n31000001\n3. Clark C. https://doi.org/\n"
            "10.5555/c.3\n")
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 7)], "As [1-3] show.\n", [])
    assert census.style == NUMBERED and census.unsent == []
    assert [(e.dois, e.pmids) for e in census.entries] == [
        (("10.1016/j.x.2020.01.001",), ()), ((), ("31000001",)), (("10.5555/c.3",), ())]


def test_an_identifier_cut_before_it_starts_is_listed(tmp_path: Path) -> None:
    """Round 2, note 4: "doi:10.1016/" or "PMID:" at a line's end, the rest of the identifier
    not beginning the next line, is read as no identifier; it is listed as not looked up,
    never dropped without a word."""
    from manuscript_guard.auditing.references import NUMBERED, census_of_printed

    text = ("References\n1. Smith A. A paper. doi:10.1016/\nj.x.2020.01.001. More.\n"
            "2. Jones B. Another. PMID:\nEpub 31000001.\n")
    census = census_of_printed(tmp_path / "p.pdf", text, [(0, 5)], "As [1, 2] show.\n", [])
    assert census.style == NUMBERED
    assert census.unsent == [(2, "10.1016/"), (4, "PMID:")]
    assert all(not entry.dois and not entry.pmids for entry in census.entries)


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
def test_an_untold_identifier_not_found_is_said_as_printed(tmp_path: Path, registries,  # noqa: F811
                                                           capsys) -> None:  # fmt: skip
    """Round 2: one that ends a line with more of the list after it is asked about, and a "not
    found" for it says it may run on, never that no registry has the work's DOI."""
    registries.answers = {"doi_org": (404, {"responseCode": 100})}
    lines = ["Results", "Of 412, 77 had it (Adams, 2019).", "References",
             "Adams A (2019) A first paper. J X. doi:10.5555/one.1",
             "Brown B (2020) A second paper. J X. doi:10.5555/two.2"]
    # One page, with no running head or foot, which a one-page PDF does not have taken out.
    paper = write(tmp_path / "paper.pdf", lines, head=None, foot=None, first_page=None)
    _code, report, _err = audited(capsys, str(paper), "--lookup")
    printed = found(report, "not-found-as-printed")
    assert [f["message"].split(": ", 1)[0] for f in printed] == [
        "the DOI 10.5555/one.1 of the list"], printed
    assert "may run on to the next" in printed[0]["message"]
    assert [f["message"].split(": ", 1)[0] for f in found(report, "doi-unregistered")] == [
        "the DOI 10.5555/two.2 of the list"]
    assert main(["audit", str(tmp_path / "paper.pdf")]) == 0
    assert "2 DOI(s) and 0 PMID(s) read; its entries could not be told apart" in (
        capsys.readouterr().out)


@pytest.mark.parametrize("titles", [
    # The Lancet's: "Summary", its parts, a Funding line, then the paper's own.
    ("Summary", "Background", "Methods", "Findings", "Funding", "Introduction", "Methods",
     "Results", "Discussion", "Funding"),
    # The BMJ's: its Objectives, Design and Setting are no heading here; its Results are.
    ("Abstract", "Objectives", "Design", "Setting", "Participants", "Main outcome measures",
     "Results", "Conclusions", "Introduction", "Methods", "Results", "Discussion"),
])
def test_a_structured_abstract_is_placed_under_it(titles: tuple[str, ...]) -> None:
    """Fix-only round of #486: every heading between the Abstract and the Introduction is the
    Abstract's, a heading of the main text's name among them."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    headings = tuple((at, title) for at, title in enumerate(titles, 1)
                     if heading_title(title) is not None)  # fmt: skip
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(titles),
                  tuple(Place(1, at) for at in range(1, len(titles) + 1)), headings)
    placed = pdf.placed
    assert placed is not None
    levels = [(title, level) for _line, title, level in placed]
    opening = [title for title, _level in levels].index("Introduction")
    assert {level for _title, level in levels[1:opening]} == {2}, levels
    assert {level for _title, level in levels[opening:]} == {1}, levels


def test_a_pdf_with_no_heading_read_places_none() -> None:
    """Corpus run of 2026-11-11: a PDF whose headings the reader does not find, 2509.01351's
    small capitals, stopped `audit` on `zip()`'s length check; it has no heading to place."""
    from manuscript_guard.auditing.pdf import PdfText, Place

    lines = ["Gains from monetary policy", "We estimate the response of output.", "It falls."]
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(lines),
                  tuple(Place(1, at) for at in range(1, len(lines) + 1)), ())
    assert pdf.placed == ()


@needs_pdftotext
def test_compare_places_a_pdfs_structured_abstract_under_it(tmp_path: Path, capsys) -> None:
    """Round 2, note 3: the PDF's structured abstract's headings sit under its Abstract, as
    the .docx's styles set them, and each section is matched with its own."""
    import zipfile

    from manuscript_guard.comparing.versions import read_version

    paper = [("1", "Abstract"), ("2", "Methods"), ("", "We read records."), ("2", "Results"),
             ("", "Of 412, 77 had it."), ("1", "Introduction"), ("", "Drugs harm."),
             ("1", "Methods"), ("", "We read 412 records."), ("1", "Results"),
             ("", "Of 412, 77 had it."), ("1", "Discussion"), ("", "It was so.")]
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    styles = (f"<w:styles {ns}>" + "".join(
        f"<w:style w:type='paragraph' w:styleId='Heading{n}'><w:name w:val='heading {n}'/>"
        "</w:style>" for n in (1, 2)) + "</w:styles>")  # fmt: skip
    body = "".join(
        (f"<w:p><w:pPr><w:pStyle w:val='Heading{level}'/></w:pPr>" if level else "<w:p>")
        + f"<w:r><w:t>{text}</w:t></w:r></w:p>" for level, text in paper)
    old = tmp_path / "v1.docx"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("word/document.xml", f"<?xml version='1.0'?><w:document {ns}>"
                         f"<w:body>{body}</w:body></w:document>")  # fmt: skip
        archive.writestr("word/styles.xml", styles)
    new = write(tmp_path / "v2.pdf", [text for _level, text in paper], per_column=40,
                head=None, foot=None, first_page=None)
    assert [(h.title, h.level) for h in read_version(new).sections if h.level][:3] == [
        ("Abstract", 1), ("Methods", 2), ("Results", 2)]
    assert main(["compare", str(old), str(new), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    codes = [f["code"] for f in report["findings"] if f["section"] == "Sections"]
    assert "section-new" not in codes and "section-gone" not in codes, codes


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


# --------------------------------------- a run-in "Abstract:", and a study's own heading

#: pdf-socio-B1 of the real-paper corpus, in MDPI's layout: its Abstract titled by a run-in
#: "Abstract:" on a line of its words, then "Keywords:", then "1. Introduction". No line
#: names the Abstract alone, and the audit said no file has a heading that names it.
RUN_IN = [
    "A study of things",
    "Abstract: Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).",
    "The rate was 21.4% in the exposed.",
    "Keywords: harm; drugs; records",
    "1. Introduction",
    "Drugs cause harm [1].",
    "2. Methods",
    "We read 412 records [2].",
    "3. Results",
    "Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).",
    "4. Discussion",
    "It was so.",
    "References",
    "1. Smith A. A paper. J Things. 2019;12:345-56.",
    "2. Jones B. Another paper. J Things. 2020;13:1-9.",
]


def test_a_run_in_abstract_label_before_the_first_heading_is_the_abstract_s() -> None:
    """Basile, 2026-11-15, decision 22: the label is the Abstract's heading and the rest of
    its line the Abstract's first text; it runs to the next heading. "Abstract." and
    "ABSTRACT:" are read as a Word paper's run-in label is."""
    from manuscript_guard.auditing.pdf import PdfText, Place, headings_of

    headings, run_in = headings_of(RUN_IN)
    assert headings[:2] == ((2, "Abstract"), (5, "Introduction")) and run_in == {2}
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(RUN_IN),
                  tuple(Place(1, at) for at in range(1, len(RUN_IN) + 1)), headings,
                  run_in=run_in)  # fmt: skip
    assert [level for _line, _title, level in pdf.placed] == [1] * len(headings)
    for label in ("Abstract.", "ABSTRACT:", "Abstract :"):
        lines = [RUN_IN[0], RUN_IN[1].replace("Abstract:", label), *RUN_IN[2:]]
        assert headings_of(lines)[0][0] == (2, label.rstrip(" :.")), label


@pytest.mark.parametrize("line", [
    # After the first heading, a reference's title or a quotation that opens on the label.
    None,
    # A sentence that opens with the word, and the label with nothing after it on its line.
    "Abstracts were screened by two reviewers.",
    "abstract: of 412 patients, 77 had the event.",
])
def test_no_other_line_that_opens_on_the_word_titles_an_abstract(line: str | None) -> None:
    from manuscript_guard.auditing.pdf import headings_of

    lines = ([*RUN_IN[:1], *RUN_IN[2:], f"Abstract: {RUN_IN[2]}"] if line is None
             else [RUN_IN[0], line, *RUN_IN[2:]])  # fmt: skip
    headings, run_in = headings_of(lines)
    assert not run_in and all(title != "Abstract" for _line, title in headings), headings


@needs_pdftotext
def test_a_pdf_s_abstract_under_a_run_in_label_is_compared_with_its_results(
    tmp_path: Path, capsys
) -> None:
    """The numbers on the label's own line are the Abstract's, matched in the Results, and the
    one the Results do not report is said not found, at its page and line: the line as the
    PDF's text reads it, which the two pdftotext builds lay out differently (Windows CI's
    puts it a line lower)."""
    paper = write(tmp_path / "paper.pdf", RUN_IN, per_column=40)
    _code, report, _err = audited(capsys, str(paper))
    assert not found(report, "abstract-not-compared")
    assert report["counts"]["abstract_matched"] >= 5, report["counts"]
    said = "The rate was 21.4% in the exposed."
    read = reading.read_pdf(paper)
    at = read.places[next(i for i, line in enumerate(read.text.split("\n")) if said in line)]
    assert [(f["page"], f["line"], f["context"]) for f in found(report, "abstract-not-found")] \
        == [(at.page, at.line, said)]
    assert at.page == 1
    # The rest of the label's line is the Abstract's text where G4, G6 and G14 read the PDF,
    # and where `compare` does.
    from manuscript_guard.auditing.gates import _staged_pdf
    from manuscript_guard.comparing.versions import read_version

    staged = _staged_pdf(paper).files["main.md"]
    assert "\n# Abstract\n\nOf 412 patients, 77 (18.7%) had the event" in staged, staged
    abstract = next(one for one in read_version(paper).sections if one.title == "Abstract")
    assert abstract.body.startswith("Of 412 patients, 77 (18.7%)"), abstract.body


#: pdf-psych-A2 of the real-paper corpus: four experiments, each with its "Method" and its
#: "Results and Discussion" under "Experiment N: <title>". Each name stood on four lines,
#: and its headings were placed nowhere. Its prose names an experiment with no colon after
#: the number, at a line's start too.
STUDIES = [
    "Abstract",
    "Of 412 listeners, 77 (18.7%) heard speech, and in one experiment 21.4% did so.",
    "Introduction",
    "Experiment 3 (n = 99) confirmed this pattern with a new stimulus.",
    "Experiment 1. In addition, half of them were primed.",
    *(line for number in (1, 2, 3, 4) for line in (
        f"Experiment {number}: Modulating prior knowledge of speech",
        "Method", f"We tested {number}0 listeners.",
        "Results and Discussion",
        "In this one, 21.4% heard speech." if number == 3 else
        "Of 412 listeners, 77 (18.7%) heard speech.")),
    "General Discussion",
    "It was so.",
    "References",
    "1. Smith A. A paper. J Things. 2019;12:345-56.",
]


def test_a_study_s_own_heading_is_one_level_above_the_names_after_it() -> None:
    """Basile, 2026-11-15, decision 23: "Experiment N:" and "Study N:", N a number or a Roman
    numeral, a colon required, are headings over the names after them, up to the next."""
    from manuscript_guard.auditing.pdf import PdfText, Place, headings_of, study_title

    headings, run_in = headings_of(STUDIES)
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(STUDIES),
                  tuple(Place(1, at) for at in range(1, len(STUDIES) + 1)), headings)
    levels = [(title.split(":")[0], level) for _line, title, level in pdf.placed]
    assert levels == [("Abstract", 1), ("Introduction", 1), *(
        one for number in (1, 2, 3, 4) for one in (
            (f"Experiment {number}", 1), ("Method", 2), ("Results and Discussion", 2))),
        ("General Discussion", 2), ("References", 2)], levels
    assert not run_in
    for line in ("Study 1: A first look", "STUDY II: Again", "Experiment IV: Last",
                 "Study  2:  spaced"):  # fmt: skip
        assert study_title(line) == " ".join(line.split()), line
    for line in STUDIES[3:5] + ["Experiment 2 included a version of the scale.",
                                "In Experiment 4: a sentence.", "Study one: words",
                                "experiment 1: lower case"]:  # fmt: skip
        assert study_title(line) is None, line


def test_a_name_twice_under_one_study_places_nothing() -> None:
    from manuscript_guard.auditing.pdf import PdfText, Place, headings_of

    lines = [*STUDIES[:8], "Method", *STUDIES[8:]]
    headings, _run_in = headings_of(lines)
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(lines),
                  tuple(Place(1, at) for at in range(1, len(lines) + 1)), headings)
    assert pdf.placed is None


@needs_pdftotext
def test_a_multi_study_pdf_s_results_are_all_compared_with_its_abstract(
    tmp_path: Path, capsys
) -> None:
    """The number of the Abstract only Experiment 3's Results report is found there, and the
    staged Markdown G4, G6 and G14 read sets each study's sections under it."""
    from manuscript_guard.auditing.gates import _staged_pdf

    paper = write(tmp_path / "paper.pdf", STUDIES, per_column=40)
    _code, report, _err = audited(capsys, str(paper))
    assert not found(report, "abstract-not-compared")
    assert not found(report, "abstract-not-found"), found(report, "abstract-not-found")
    assert report["counts"]["abstract_matched"] == report["counts"]["abstract_numbers"] >= 4
    staged = _staged_pdf(paper).files["main.md"]
    assert "\n# Experiment 3: Modulating prior knowledge of speech\n" in staged
    assert "\n## Results and Discussion\n" in staged


# ------------------------------------------- the new shapes only where nothing else places

#: Round 1 of #686: a structured Abstract that lists its studies line by line under its
#: Methods, and a main text whose names each stand once. The base placed it and compared it.
LISTED_STUDIES = [
    "Falls in nurses", "Abstract", "Background", "Falls are common among nurses.",
    "Methods", "Study 1: 412 nurses were surveyed.", "Study 2: 20 were interviewed.",
    "Results", "Of 412 nurses, 77 fell.", "Conclusions", "Falls are common.",
    "Introduction", "Falls harm nurses.", "Methods", "We surveyed 412 nurses.",
    "Results", "Of 412 nurses, 77 fell.", "Discussion", "Falls are common.",
    "Study 1: d = 0.45 for the survey.",
    "References", "Smith J. Falls. BMJ 2019;1:1.", "Experiment 2: a title wrapped. J. 2020."]
#: Round 1 of #686: a title page's count of words, "Abstract: 248 words", over the Abstract's
#: own heading. The base placed it and compared it.
WORD_COUNT = [
    "Falls in nurses", "Word count", "Abstract: 248 words", "Main text: 3,500 words",
    "Abstract", "Of 412 nurses, 77 fell.", "Introduction", "Falls harm nurses.",
    "Methods", "We surveyed 412 nurses.", "Results", "Of 412 nurses, 77 fell.",
    "Discussion", "Falls are common.", "References", "Smith J. Falls. BMJ 2019;1:1."]


def _levels_of(lines: list[str]) -> list[tuple[str, int]] | None:
    from manuscript_guard.auditing.pdf import PdfText, Place, headings_of

    headings, run_in = headings_of(lines)
    pdf = PdfText(Path("p.pdf"), "test", 1, "\n".join(lines),
                  tuple(Place(1, at) for at in range(1, len(lines) + 1)), headings,
                  run_in=run_in)  # fmt: skip
    placed = pdf.placed
    return None if placed is None else [(title, level) for _line, title, level in placed]


def test_a_study_line_where_the_names_are_placed_without_it_is_no_heading() -> None:
    """Studies listed under a structured Abstract's Methods, a summary row in the Discussion
    and a reference that opens "Experiment 2:": the paper's names are placed without them,
    so none is a heading, and the paper is placed as the base placed it."""
    assert _levels_of(LISTED_STUDIES) == [
        ("Abstract", 1), ("Background", 2), ("Methods", 2), ("Results", 2),
        ("Conclusions", 2), ("Introduction", 1), ("Methods", 1), ("Results", 1),
        ("Discussion", 1), ("References", 1)]


def test_a_study_line_inside_the_abstract_or_with_no_name_after_it_is_no_heading() -> None:
    """In a multi-study paper, whose names are placed only under its studies: a line of its
    Abstract that opens "Study 1:", and a reference that opens "Experiment 2:" with no name
    after it, are no study's headings; the studies' own are."""
    lines = [STUDIES[0], "Study 1: 412 listeners heard speech.", *STUDIES[1:],
             "Experiment 2: a title wrapped. 2020."]
    assert _levels_of(lines) == [
        ("Abstract", 1), ("Introduction", 1), *(
            one for number in (1, 2, 3, 4) for one in (
                (f"Experiment {number}: Modulating prior knowledge of speech", 1),
                ("Method", 2), ("Results and Discussion", 2))),
        ("General Discussion", 2), ("References", 2)]


def test_a_summary_row_with_only_the_back_matter_after_it_is_no_heading() -> None:
    """In a multi-study paper's General Discussion, a summary row that opens "Study 1:" with
    the next row's "Study 2:" after it and no name between is no heading, and nor is the last
    row, with only the back matter's names after it (round 2 of #686). A limit (DESIGN.md,
    Known gaps): a row with a name of the main text after it, "Limitations", is a study's
    heading over it."""
    rows = ["Study 1: d = 0.45 in the first.", "Study 2: d = 0.30 in the second.",
            "It was so."]
    lines = [*STUDIES[:-2], *rows, "Acknowledgements", "We thank them.", *STUDIES[-2:]]
    assert _levels_of(lines)[-3:] == [("General Discussion", 2), ("Acknowledgements", 2),
                                      ("References", 2)]
    lines = [*STUDIES[:-2], *rows, "Limitations", "They were few.", *STUDIES[-2:]]
    assert _levels_of(lines)[-4:] == [("General Discussion", 2),
                                      ("Study 2: d = 0.30 in the second.", 1),
                                      ("Limitations", 2), ("References", 2)]


def test_a_study_s_heading_ends_an_abstract_with_no_introduction_after_it() -> None:
    """Round 2 of #686: an APA paper whose Introduction has no heading. Over the names alone,
    the Abstract's parts ran to the second study's "Method", and the first study's sections
    were its parts. A study's line names no part of an Abstract, so the Abstract ends at the
    first, and every study is placed."""
    lines = [line for line in STUDIES if line != "Introduction"]
    assert _levels_of(lines) == [
        ("Abstract", 1), *(
            one for number in (1, 2, 3, 4) for one in (
                (f"Experiment {number}: Modulating prior knowledge of speech", 1),
                ("Method", 2), ("Results and Discussion", 2))),
        ("General Discussion", 2), ("References", 2)]


@needs_pdftotext
def test_nothing_of_the_first_study_is_compared_as_the_abstract_s(tmp_path: Path,
                                                                  capsys) -> None:  # fmt: skip
    """The same paper as a PDF: its Abstract is compared with every study's Results, and no
    number of the first study's sections is read as the Abstract's. Its Introduction's own
    lines, under no heading, are the Abstract's (DESIGN.md, Known gaps)."""
    lines = [line for line in STUDIES if line != "Introduction"]
    _code, report, _err = audited(capsys, str(write(tmp_path / "paper.pdf", lines,
                                                    per_column=40)))  # fmt: skip
    assert not found(report, "abstract-not-compared")
    assert {f["context"] for f in found(report, "abstract-not-found")} <= set(STUDIES[3:5])


@needs_pdftotext
@pytest.mark.parametrize("lines", [LISTED_STUDIES, WORD_COUNT], ids=["studies", "word count"])
def test_a_paper_the_base_placed_is_compared_as_it_was(
    tmp_path: Path, capsys, lines: list[str]
) -> None:
    """Round 1 of #686: each was compared at the base, and not at 2299323. What the main text
    does not report is the Abstract's own studies' 20 interviewed, said not found as at the
    base; the title page's count of words is no number of the Abstract's."""
    paper = write(tmp_path / "paper.pdf", lines, per_column=40)
    _code, report, _err = audited(capsys, str(paper))
    assert not found(report, "abstract-not-compared")
    assert {f["context"] for f in found(report, "abstract-not-found")} <= {
        "Study 1: 412 nurses were surveyed.", "Study 2: 20 were interviewed."}


#: Every title page's count after the label seen in #686's rounds of review.
COUNTS = ["248 words", "250-word limit", "248 words.", "1,250 Words", "word count 248", "248",
          "max 250 words", "250 words max", "248 words; Main text: 3,512 words",
          "250 words, Text: 3,000 words, Tables: 2", "248 words (limit 250)",
          "248 | Main text: 3,512", "248 words. Main text: 3,512 words.",
          "250 words, Text: 3,000 words, 4 tables, 2 figures", "(248 words)"]


@pytest.mark.parametrize("count", COUNTS)
def test_a_count_of_words_after_the_label_titles_no_abstract(count: str) -> None:
    from manuscript_guard.auditing.pdf import headings_of

    alone = [line for line in WORD_COUNT if line != "Abstract"]
    for lines in (WORD_COUNT, alone):
        lines = [line.replace("248 words", count) for line in lines]
        headings, run_in = headings_of(lines)
        assert not run_in and [title for _line, title in headings].count("Abstract") == (
            lines.count("Abstract")), headings
    assert _levels_of(WORD_COUNT)[0] == ("Abstract", 1)


@pytest.mark.parametrize("words", ["412 patients were followed for a year.",
                                   "60 word pairs were learned by 40 adults.",
                                   "(Background) Falls are common."])  # fmt: skip
def test_an_abstract_that_opens_on_no_word_is_no_run_in_label_s(words: str) -> None:
    """Round 4 of #686: the label is read only where its line goes on with a word, a capital
    first (DESIGN.md, Known gaps): an Abstract that opens on a number is not read so, as on
    main."""
    from manuscript_guard.auditing.pdf import headings_of

    assert headings_of([RUN_IN[0], f"Abstract: {words}", *RUN_IN[2:]])[1] == frozenset()
    assert headings_of([RUN_IN[0], "Abstract: The second generation of tools.",
                        *RUN_IN[2:]])[1] == {2}


def test_a_run_in_label_where_a_line_names_the_abstract_alone_is_text() -> None:
    from manuscript_guard.auditing.pdf import headings_of

    lines = [RUN_IN[0], RUN_IN[1], "Abstract", "We read records.", *RUN_IN[3:]]
    headings, run_in = headings_of(lines)
    assert not run_in and headings[0] == (3, "Abstract"), headings


def test_a_name_twice_with_no_study_s_line_places_nothing_and_raises_nothing() -> None:
    """Fix-only round of #686: pdf-socio-A3 of the real-paper corpus, whose names stand twice
    and which has no study's line, stopped `audit` on `zip()`'s length check."""
    lines = ["Abstract", "Of 412, 77 fell.", "Introduction", "Falls harm.", "Methods",
             "We read 412.", "Results", "Of 412, 77 fell.", "Methods", "Again."]
    assert _levels_of(lines) is None


# ---------------------------------------------- round 3 of #686: counts, structured abstracts


@pytest.mark.parametrize("count", COUNTS)
def test_a_title_page_s_counts_after_the_label_title_no_abstract(count: str) -> None:
    """Rounds 3 and 4 of #686: the Abstract's count of words, then the title page's others,
    is no label's line; the label's line after it is. Where two lines open on the label and
    a word, the first is the Abstract's."""
    from manuscript_guard.auditing.pdf import headings_of

    lines = ["Title", f"Abstract: {count}", "Abstract: Of 412 patients, 77 fell.",
             "Introduction", "Falls harm.", "Results", "Of 412 patients, 77 fell."]
    assert headings_of(lines) == (((3, "Abstract"), (4, "Introduction"), (6, "Results")),
                                  frozenset({3}))
    assert headings_of([lines[0], lines[2], lines[1], *lines[3:]])[1] == {2}
    assert headings_of([*lines[:3], "Abstract. Then 9 left.", *lines[3:]])[1] == {3}


#: Round 3 of #686: a structured Abstract over a multi-study paper's studies.
_PARTS = ["Abstract", "Background", "Falls are common.", "Methods", "We surveyed 412.",
          "Results", "Of 412, 77 fell."]
_STUDIES = ["Study 1: A survey", "Method", "We surveyed 412.", "Results", "Of 412, 77 fell.",
            "Study 2: Interviews", "Method", "We spoke to 20.", "Results", "Of 20, 4 fell.",
            "General Discussion", "Falls are common.", "References", "1. Smith J. 2019."]
_PLACED = [("Study 1: A survey", 1), ("Method", 2), ("Results", 2), ("Study 2: Interviews", 1),
           ("Method", 2), ("Results", 2), ("General Discussion", 2), ("References", 2)]


def test_a_study_listed_in_a_structured_abstract_ended_by_its_introduction_is_no_heading(
) -> None:
    lines = [*_PARTS, "Study 1: 412 were surveyed.", "Conclusions", "Falls are common.",
             "Introduction", "Falls harm.", *_STUDIES]
    assert _levels_of(lines) == [("Abstract", 1), ("Background", 2), ("Methods", 2),
                                 ("Results", 2), ("Conclusions", 2), ("Introduction", 1),
                                 *_PLACED]


def test_a_study_s_line_ends_a_structured_abstract_s_parts() -> None:
    lines = [*_PARTS, "Conclusions", "Falls are common.", *_STUDIES]
    assert _levels_of(lines) == [("Abstract", 1), ("Background", 2), ("Methods", 2),
                                 ("Results", 2), ("Conclusions", 2), *_PLACED]


def test_a_study_listed_in_an_abstract_over_a_background_is_no_heading() -> None:
    """A one-paragraph Abstract that lists a study, and a main text that opens on
    "Background", over three studies, whose names the base cannot place: the Abstract ends
    at the Background."""
    third = ["Study 3: Again", "Method", "We read 9.", "Results", "Of 9, 1 fell."]
    lines = ["Abstract", "Of 412, 77 fell.", "Study 1: 412 were surveyed.", "Background",
             "Falls harm.", *_STUDIES[:10], *third, *_STUDIES[10:]]
    assert _levels_of(lines) == [("Abstract", 1), ("Background", 1), *_PLACED[:6],
                                 ("Study 3: Again", 1), ("Method", 2), ("Results", 2),
                                 *_PLACED[6:]]
