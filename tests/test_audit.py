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
    parts_of,
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


# ------------------------------------------------- an interval is two numbers, not one token


@pytest.mark.parametrize(
    ("atom", "expected"),
    [
        ("0.72–0.82", ["0.72", "0.82"]),
        ("2000-3999", ["2000", "3999"]),
        ("77/412", ["77", "412"]),
        ("350", ["350"]),
        ("3.84", ["3.84"]),
        # Anything with a letter is left whole. Splitting an email address or a model name
        # would let it match on whatever digit it happens to contain, and a false match is
        # worse than an unexplained number.
        ("claude-sonnet-4-5-20250929", ["claude-sonnet-4-5-20250929"]),
        ("a.person@example.invalid", ["a.person@example.invalid"]),
    ],
)
def test_the_numbers_an_atom_carries(atom: str, expected: list[str]) -> None:
    assert parts_of(atom) == expected


def test_an_interval_whose_bounds_are_both_published_is_found(tmp_path: Path) -> None:
    """A confidence interval written as a range is one atom, and matching it as one string
    matched nothing — so an interval sitting in the outputs was reported as not found.

    Found on a real submitted paper: 29 of its 232 unexplained numbers were intervals, and
    they are the paper's actual results rather than incidental numbers. The ones an audit
    exists to check were the ones it was worst at.
    """
    outputs = tmp_path / "gini.csv"
    outputs.write_text("estimate,lo,hi\n0.77,0.72,0.82\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The jackknife interval was 0.72–0.82.\n", encoding="utf-8")

    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == []
    assert any(c.text == "0.72–0.82" for c in report.matched)


def test_an_interval_with_one_bound_missing_is_still_reported(tmp_path: Path) -> None:
    """Every part has to be there, not just one. "0.72-0.99" with only 0.72 published is
    exactly the discrepancy this command exists to find, and matching on either part would
    have hidden it."""
    outputs = tmp_path / "gini.csv"
    outputs.write_text("estimate,lo,hi\n0.77,0.72,0.82\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The jackknife interval was 0.72–0.99.\n", encoding="utf-8")

    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["0.72–0.99"]


# ------------------------------------------------- what a submitted document is full of


def test_vancouver_citations_are_not_unexplained_numbers(tmp_path: Path) -> None:
    """Every numbered-reference journal prints [11], and an atom runs to the next space, so
    each marker arrived dragging the preceding word with it. On a real paper that was 25
    unexplained numbers, none of them a number anyone had written."""
    outputs = tmp_path / "out.csv"
    outputs.write_text("n\n412\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(
        "Editors shape rejection[1,2] and outcomes[7,8]; see earlier work[13-15].\n"
        "We included 412 records.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == []
    assert report.classified >= 3


def test_an_orcid_is_not_an_unexplained_number(tmp_path: Path) -> None:
    outputs = tmp_path / "out.csv"
    outputs.write_text("n\n412\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("A. Author (ORCID 0000-0002-7483-2489) wrote it.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == []


def test_a_section_sign_reference_is_not_an_unexplained_number(tmp_path: Path) -> None:
    """`§3.1` is a section reference in every journal that uses it, and only the word form
    was recognised — which also missed "Section 4.2", because the number was undotted."""
    outputs = tmp_path / "out.csv"
    outputs.write_text("n\n412\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The model is given in §3.1, and validated in Section 4.2.\n", "utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == []


def test_a_real_number_beside_all_of_that_is_still_reported(tmp_path: Path) -> None:
    """The point of widening a rule is to make the remaining findings readable, not fewer."""
    outputs = tmp_path / "out.csv"
    outputs.write_text("n\n412\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(
        "See §3.1 and earlier work[13-15]. A. Author (ORCID 0000-0002-7483-2489) "
        "reports 9999 events among 412 records.\n",
        encoding="utf-8",
    )
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["9999"]
