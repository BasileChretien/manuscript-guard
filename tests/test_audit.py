"""Auditing a paper that was never written with this toolkit.

The audit answers a weaker question than `check` — does this number appear anywhere in the
outputs? — so the tests hold it to two things: it must catch a number that appears nowhere,
and it must report honestly how little a match is worth.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from manuscript_guard.audit import (
    audit,
    load_backing,
    looks_like_reference,
    measure_discrimination,
    normalise_number,
    render,
    strip_bibliography,
)
from manuscript_guard.text.docx import NotADocx, read_docx

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path: Path, body: str) -> Path:
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    return path


def para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def row(*cells: str) -> str:
    inner = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in cells)
    return f"<w:tr>{inner}</w:tr>"


# ---------------------------------------------------------------- reading .docx


def test_table_cells_are_kept_apart(tmp_path: Path) -> None:
    """Concatenated cells turn a row of counts into one enormous number.

    "39 | 20 | 26 | 16" became 39202616 in the project this one learned from, so no cell
    could be matched and every table was silently skipped.
    """
    table = f"<w:tbl>{row('Unique publishers', '39', '20', '26')}</w:tbl>"
    text = read_docx(make_docx(tmp_path / "t.docx", table))
    assert "39202616" not in text
    assert "39" in text and "20" in text and "26" in text
    assert "|" in text


def test_tracked_deletions_are_dropped_and_insertions_kept(tmp_path: Path) -> None:
    body = (
        "<w:p>"
        "<w:del><w:r><w:t>The old value was 41.</w:t></w:r></w:del>"
        "<w:ins><w:r><w:t>The new value is 77.</w:t></w:r></w:ins>"
        "</w:p>"
    )
    text = read_docx(make_docx(tmp_path / "d.docx", body))
    assert "77" in text
    assert "41" not in text, "a deleted number is not in the paper anyone will read"


def test_a_file_that_is_not_a_docx_says_so(tmp_path: Path) -> None:
    path = tmp_path / "fake.docx"
    path.write_bytes(b"not a zip at all")
    with pytest.raises(NotADocx, match="not a readable"):
        read_docx(path)


# ---------------------------------------------------------------- normalising


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234", "1234"), ("3.80", "3.8"), ("12%", "12"), ("0012", "12"), ("3.0", "3")],
)
def test_numbers_compare_in_a_common_form(raw: str, expected: str) -> None:
    assert normalise_number(raw) == expected


def test_a_hex_digest_does_not_overflow(tmp_path: Path) -> None:
    """A sha256 contains runs like 4e308, which parse as an overflowing float."""
    assert normalise_number("4e308000") == "4e308000"


def test_digests_are_kept_out_of_the_backing_set(tmp_path: Path) -> None:
    """Their digit fragments would match anything and inflate the honesty statistic."""
    path = tmp_path / "r.json"
    path.write_text('{"sha256": "451fb94f87f4e266abf6018bf1ca7204", "n": 77}', encoding="utf-8")
    values, _used = load_backing([path])
    assert "77" in values
    assert not any(len(v) > 12 for v in values), values


# ---------------------------------------------------------------- bibliographies


def test_a_reference_heading_truncates_the_paper() -> None:
    text = "We found 77 cases.\n\nReferences\n\nSmith 2019. Journal 12: 45-52.\n"
    assert "45-52" not in strip_bibliography(text)
    assert "77" in strip_bibliography(text)


def test_a_reference_entry_is_recognised_without_a_heading() -> None:
    """citeproc appends the bibliography with no heading, so there is nothing to cut at."""
    assert looks_like_reference(
        "Fictional, Anne, and Bernard Fictional. 2021. 'Hepatic Injury'. Journal 12: 101-9."
    )
    assert not looks_like_reference("The reporting odds ratio was 3.84 in 77 cases.")


# ---------------------------------------------------------------- the audit itself


@pytest.fixture
def outputs(tmp_path: Path) -> Path:
    path = tmp_path / "results.json"
    path.write_text('{"ror": 3.84, "low": 2.89, "high": 5.12, "cases": 77}', encoding="utf-8")
    return path


def test_a_paper_whose_numbers_are_all_present_is_clean(tmp_path: Path, outputs: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(
        "The odds ratio was 3.84 (95% CI 2.89 to 5.12) in 77 cases.\n", encoding="utf-8"
    )
    report = audit([paper], [outputs])
    assert report.unmatched == []
    assert len(report.matched) == 4


def test_a_stale_number_is_caught(tmp_path: Path, outputs: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("The odds ratio was 3.94 in 77 cases.\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["3.94"]
    assert report.unmatched[0].line == 1
    assert "3.94" in report.unmatched[0].context


def test_conventions_are_not_reported(tmp_path: Path, outputs: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("Significance was p < 0.05, with 95% CI. See Table 2.\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert report.unmatched == []
    assert report.classified >= 3


def test_an_unreadable_paper_is_reported_not_skipped(tmp_path: Path, outputs: Path) -> None:
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"nope")
    report = audit([broken], [outputs])
    assert report.unreadable
    assert "not a readable" in report.unreadable[0]


# ---------------------------------------------------------------- honesty


def test_a_dense_backing_set_is_reported_as_worthless(tmp_path: Path) -> None:
    """The measurement that stops a clean report being mistaken for a clean paper.

    The predecessor project measured 100% of integers up to 100 as already backed, and
    caught 0 of 15 deliberately corrupted numbers while reporting success.
    """
    raw = tmp_path / "raw.csv"
    raw.write_text("\n".join(",".join(str(n) for n in range(1, 101)) for _ in range(3)), "utf-8")
    values, _used = load_backing([raw])
    discrimination = measure_discrimination(values)
    assert discrimination.small_integers == 1.0
    assert "almost nothing" in discrimination.verdict()


def test_a_sparse_backing_set_is_reported_as_informative(tmp_path: Path, outputs: Path) -> None:
    values, _used = load_backing([outputs])
    discrimination = measure_discrimination(values)
    assert discrimination.small_integers < 0.2
    assert "real information" in discrimination.verdict()


def test_the_report_always_states_what_a_match_is_worth(tmp_path: Path, outputs: Path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("The odds ratio was 3.84.\n", encoding="utf-8")
    report = audit([paper], [outputs])
    text = render(report, measure_discrimination(report.backing_values))
    assert "What a match is worth here" in text
    assert "cannot tell whether it appears in the right place" in text
    assert "bind the numbers instead" in text


def test_a_dense_backing_set_earns_advice_about_raw_data(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("\n".join(",".join(str(n) for n in range(1, 101)) for _ in range(3)), "utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("We saw 7 events.\n", encoding="utf-8")
    report = audit([paper], [raw])
    text = render(report, measure_discrimination(report.backing_values))
    assert "rather than the raw data" in text
