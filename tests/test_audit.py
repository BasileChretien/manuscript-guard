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
from manuscript_guard.text.docx import DocxText, NotADocx, read_docx, read_docx_text

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'

# A fixed timestamp, so the same body always gives the same bytes (see test_transcribe).
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def make_docx(path: Path, body: str) -> Path:
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), document)
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


def gone(text: str, style: str = "") -> str:
    """A paragraph whose mark was deleted as a tracked change: it runs on into the next."""
    styled = f'<w:pStyle w:val="{style}"/>' if style else ""
    mark = f'<w:pPr>{styled}<w:rPr><w:del w:id="1" w:author="a"/></w:rPr></w:pPr>'
    return f"<w:p>{mark}<w:r><w:t>{text}</w:t></w:r></w:p>"


def heading(text: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'


@pytest.mark.parametrize(
    ("body", "line", "is_heading"),
    [
        (gone("Appendix", "Heading1") + para("Text"), "AppendixText", False),
        (gone("Text") + heading("Appendix"), "TextAppendix", True),
        (gone("A1") + gone("B2", "Heading1") + para("C3"), "A1B2C3", False),
    ],
    ids=["heading-then-text", "text-then-heading", "three"],
)
def test_a_joined_line_takes_the_last_paragraphs_style(
    tmp_path: Path, body: str, line: str, is_heading: bool
) -> None:
    """The mark that is left is the last paragraph's, and so is the style: Word 16, accepting
    the change, keeps it. When Word deletes a mark itself it first copies the first
    paragraph's style onto the second, recording the old one in `w:pPrChange`, so this is
    what Word shows either way."""
    document = read_docx_text(make_docx(tmp_path / "j.docx", para("Intro") + body))
    assert document.body.split("\n") == ["", "Intro", line]
    assert document.headings == (frozenset({2}) if is_heading else frozenset())


def test_a_join_stops_at_a_table(tmp_path: Path) -> None:
    """Only a sibling paragraph continues the line, and only empty elements - a bookmark, a
    comment's range - may sit between them. Joined past the table, "-0.5" and the "1" after
    the table read as -0.51."""
    table = f"<w:tbl>{row('0.3')}</w:tbl>"
    text = read_docx(make_docx(tmp_path / "t.docx", gone("-0.5") + table + para("1")))
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    assert lines == ["-0.5", "|", "0.3", "1"]


def test_a_joined_line_in_a_table_cell_is_still_a_cell(tmp_path: Path) -> None:
    """A cell's line is marked, because "References" there is a column header. The mark goes
    at the start of the joined line, not in the middle of it."""
    cell = f"<w:tc>{gone('-0.5')}{para('1')}</w:tc>"
    table = f"<w:tbl><w:tr>{cell}</w:tr></w:tbl>"
    document = read_docx_text(make_docx(tmp_path / "c.docx", table))
    lines = document.body.split("\n")
    assert lines[-1] == "-0.51", lines
    assert len(lines) - 1 in document.cells


def text_box(inside: str, *, fallback: bool) -> str:
    """A run holding a text box: as DrawingML alone, or as Word writes one, with the same box
    again in VML in an AlternateContent fallback for readers that predate DrawingML."""
    content = f"<w:txbxContent>{inside}</w:txbxContent>"
    choice = f'<mc:Choice Requires="wps"><w:drawing>{content}</w:drawing></mc:Choice>'
    spare = f"<mc:Fallback><w:pict>{content}</w:pict></mc:Fallback>" if fallback else ""
    return f"<w:r><mc:AlternateContent {MC}>{choice}{spare}</mc:AlternateContent></w:r>"


@pytest.mark.parametrize(
    ("inside", "number"),
    [(para("Panel 12"), "12"), (f"<w:tbl>{row('7', '8')}</w:tbl>", "7")],
    ids=["paragraph", "table"],
)
def test_a_text_box_is_read_once_although_word_writes_it_twice(
    tmp_path: Path, inside: str, number: str
) -> None:
    """Both copies were read, so every line of the box came twice and each number in it was
    reported twice. The fallback's paragraphs, rows and cells break nothing either: only the
    lines of the box as Word shows it are read."""

    def read(*, fallback: bool) -> DocxText:
        body = f"<w:p><w:r><w:t>Host</w:t></w:r>{text_box(inside, fallback=fallback)}</w:p>"
        return read_docx_text(make_docx(tmp_path / f"{fallback}.docx", body))

    once, twice = read(fallback=False), read(fallback=True)
    assert once.body.count(number) == 1, once.body
    assert twice == once, twice.body


@pytest.mark.parametrize(
    ("code", "shown"),
    [("1F642", chr(0x1F642)), ("zz", " "), ("1E", " "), ("D800", " "), ("110000", " ")],
    ids=["emoji", "unreadable", "control", "surrogate", "past-unicode"],
)
def test_an_emoji_word_inserted_is_read_from_the_choice(
    tmp_path: Path, code: str, shown: str
) -> None:
    """Word writes an emoji it inserts as a `w16se:symEx` element in an AlternateContent
    choice, with the character as text only in the fallback, which is not read. A code that
    is not a character text can hold reads as a space, as an unknown Symbol-font character
    does: U+001E is the mark the reader puts on a heading's line."""
    se = 'xmlns:w16se="http://schemas.microsoft.com/office/word/2015/wordml/symex"'
    emoji = (
        f'<w:r><mc:AlternateContent {MC} {se}><mc:Choice Requires="w16se">'
        f'<w16se:symEx w16se:font="Segoe UI Emoji" w16se:char="{code}"/></mc:Choice>'
        f"<mc:Fallback><w:t>{chr(0x1F642)}</w:t></mc:Fallback></mc:AlternateContent></w:r>"
    )
    body = f"<w:p><w:r><w:t>12</w:t></w:r>{emoji}<w:r><w:t>34</w:t></w:r></w:p>"
    assert read_docx(make_docx(tmp_path / "e.docx", body)) == f"\n12{shown}34"


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
    values, _used, _skipped = load_backing([path])
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
    values, _used, _skipped = load_backing([raw])
    discrimination = measure_discrimination(values)
    assert discrimination.small_integers == 1.0
    assert "almost nothing" in discrimination.verdict()


def test_a_sparse_backing_set_is_reported_as_informative(tmp_path: Path, outputs: Path) -> None:
    values, _used, _skipped = load_backing([outputs])
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
        # A short statistical label closed up against its number. With spaces it is already
        # two tokens and reads correctly; closed up it stopped looking like a number at all.
        ("n=8,393", ["8393"]),
        ("p=0.03", ["0.03"]),
        ("df=2", ["2"]),
        # Three letters at most, so a label is stripped and a word never is.
        ("beta=0.4", ["beta=0.4"]),
    ],
)
def test_the_numbers_an_atom_carries(atom: str, expected: list[str]) -> None:
    assert parts_of(atom) == expected


def test_a_count_written_closed_up_is_found(tmp_path: Path) -> None:
    """"n=8,393" is one atom and no longer looks like a number, so a count sitting in the
    outputs was reported as unexplained — thirty of them on one real paper's supplements."""
    outputs = tmp_path / "out.csv"
    outputs.write_text("group,n\nexposed,8393\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The exposed group (n=8,393) was analysed.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == []


def test_a_labelled_count_that_is_wrong_is_still_reported(tmp_path: Path) -> None:
    """Reading the label must not mean accepting whatever follows it."""
    outputs = tmp_path / "out.csv"
    outputs.write_text("group,n\nexposed,8393\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The exposed group (n=9,999) was analysed.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["n=9,999"]


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


# ------------------------------------------------- a sign is part of the number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("-0.51", "-0.51"), ("−0.51", "-0.51"), ("-0.00", "0"), ("+0.51", "0.51")],
)
def test_a_sign_is_kept_and_its_spelling_is_not(raw: str, expected: str) -> None:
    """"No sign noise" means a typographic minus and a hyphen compare equal. It never meant
    the sign could be dropped."""
    assert normalise_number(raw) == expected


def test_a_negative_output_keeps_its_sign(tmp_path: Path) -> None:
    """The backing pattern had no sign at all, so -0.51 in the outputs went in as 0.51 and a
    paper quoting the value correctly — with its minus, hyphen or U+2212 — never matched."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"log_ror": -0.51}', encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("It was -0.51 here.\n\nIt was −0.51 there.\n", encoding="utf-8")

    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == []
    assert len(report.matched) == 2


def test_a_hyphen_between_numbers_is_not_a_sign(tmp_path: Path) -> None:
    """Ranges and dates in the outputs must not grow negative numbers they never held."""
    outputs = tmp_path / "out.txt"
    outputs.write_text("range 0.72-0.82, run on 2019-03-04, id x-5, estimate -0.51\n", "utf-8")
    values, _used, _skipped = load_backing([outputs])
    assert {"0.72", "0.82", "2019", "3", "4", "5", "-0.51"} <= values
    assert not {"-0.82", "-3", "-4", "-5"} & values


@pytest.mark.parametrize(
    ("atom", "expected"),
    [
        ("−0.72–−0.30", ["-0.72", "-0.3"]),
        ("-0.72–0.30", ["-0.72", "0.3"]),
        ("0.72-0.82", ["0.72", "0.82"]),
        # A hyphen after a symbol that ends a number is still a separator.
        ("50%-60%", ["50", "60"]),
        # A minus after the separator is a sign: U+2212 always, a hyphen after a hyphen or a
        # slash, in every format. Markdown's "--" meaning pandoc's en dash is read this way
        # too, which errs toward a false alarm.
        ("-0.72--0.30", ["-0.72", "-0.3"]),
        ("−0.72-−0.30", ["-0.72", "-0.3"]),
        ("−0.72/−0.30", ["-0.72", "-0.3"]),
    ],
)
def test_an_interval_with_a_negative_bound_is_split(atom: str, expected: list[str]) -> None:
    assert parts_of(atom) == expected


# ------------------------------------------------- what --against could not use


def test_a_format_the_audit_cannot_read_is_named(tmp_path: Path) -> None:
    """An .xlsx or .rds among the outputs used to vanish, and every number it held was then
    reported as missing from the paper with no hint why."""
    usable = tmp_path / "out.json"
    usable.write_text('{"n": 77}', encoding="utf-8")
    sheet = tmp_path / "results.xlsx"
    sheet.write_bytes(b"PK\x03\x04")
    paper = tmp_path / "paper.md"
    paper.write_text("We saw 77.\n", encoding="utf-8")

    report = audit([paper], [usable, sheet])
    assert any("results.xlsx" in item for item in report.skipped)
    assert "results.xlsx" in render(report, measure_discrimination(report.backing_values))


def test_a_directory_says_what_it_skipped(tmp_path: Path) -> None:
    folder = tmp_path / "outputs"
    folder.mkdir()
    (folder / "a.csv").write_text("n\n77\n", encoding="utf-8")
    (folder / "model.rds").write_bytes(b"\x1f\x8b")
    (folder / "fit.rds").write_bytes(b"\x1f\x8b")
    _values, used, skipped = load_backing([folder])
    assert [p.name for p in used] == ["a.csv"]
    assert any(".rds (2)" in item for item in skipped), skipped


def test_json_that_does_not_parse_is_read_as_text_and_said_so(tmp_path: Path) -> None:
    """JSON Lines is the common case: one object per line is not one JSON document."""
    lines = tmp_path / "fits.json"
    lines.write_text('{"n": 77}\n{"n": 412}\n', encoding="utf-8")
    values, used, skipped = load_backing([lines])
    assert {"77", "412"} <= values
    assert used == [lines]
    assert any("fits.json" in item and "not valid JSON" in item for item in skipped)


# ------------------------------------------------- the reference list, and what follows it


@pytest.mark.parametrize(
    "heading",
    ["Reference list", "## Reference List", "**References**", "References cited", "5 References"],
)
def test_other_bibliography_headings_are_recognised(heading: str) -> None:
    text = f"We found 77 cases.\n\n{heading}\n\n1. Smith J. Title. Lancet. 2019;393:45-52.\n"
    assert "45-52" not in strip_bibliography(text)
    assert "77" in strip_bibliography(text)


@pytest.mark.parametrize(
    "entry",
    [
        "Smith J, Jones K. Hepatic injury in reports. Lancet. 2019;393:100-10.",
        "1. Smith J, Jones K. Hepatic injury in reports. Lancet. 2019;393:100-10.",
        "[12] Smith JA, Jones K, et al. Hepatic injury. Drug Saf. 2019 Mar;42(3):100-10.",
        "Smith J. Hepatic injury in reports. BMJ. 2021;372:n71.",
    ],
)
def test_a_vancouver_entry_is_recognised_without_a_heading(entry: str) -> None:
    """DESIGN says entries are recognised by shape; the only shape was author-year."""
    assert looks_like_reference(entry)


@pytest.mark.parametrize(
    "line",
    [
        "Figure A. Reports by year, 2015 to 2019: 412 cases.",
        "Table S1. Characteristics in 2019; 412 reports.",
        "Smith J reported 77 cases in 2019.",
    ],
)
def test_a_caption_is_not_mistaken_for_a_vancouver_entry(line: str) -> None:
    """Recognising a line as a reference hides every number on it, so the shape has to be
    one that a caption or a sentence does not share."""
    assert not looks_like_reference(line)


def test_the_report_says_where_the_reference_list_was_cut(tmp_path: Path) -> None:
    """Dropping text unannounced is how a cut in the wrong place stays invisible."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(
        "We saw 77.\n\n# References\n\nSmith J. T. Lancet. 2019;393:1-2.\n", encoding="utf-8"
    )
    report = audit([paper], [outputs])
    assert any("reference list" in item for item in report.not_audited)
    assert "lines 3-5" in render(report, measure_discrimination(report.backing_values))


# ------------------------------------------------- figures with nothing to read


def test_a_pdf_with_no_text_is_not_counted_as_audited(tmp_path: Path, monkeypatch) -> None:
    import manuscript_guard.audit as audit_module

    monkeypatch.setattr(audit_module, "read_figure", lambda path: "  \n")
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    figure = tmp_path / "scan.pdf"
    figure.write_bytes(b"%PDF-1.4")

    report = audit([], [outputs], figures=[figure])
    assert figure not in report.papers
    assert any("scan.pdf" in item for item in report.unreadable)


@pytest.mark.parametrize(
    "entry",
    [
        "Fictional, Anne, and Bernard Fictional. 2021. 'Hepatic Injury'. Journal 12: 101-9.",
        "Smith, J. A., & Jones, K. (2019). Hepatic injury. Drug Safety, 42(3), 100-110.",
        "Smith, J. (2019a). Hepatic injury. Drug Safety, 42, 100-110.",
        "Smith, John, and Kate Jones. 2019. Hepatic Injury. London: Example Press.",
    ],
)
def test_an_author_year_entry_is_still_recognised(entry: str) -> None:
    """Tightened so a sentence opening "Overall, Japanese patients" is not one; the entries
    citeproc actually writes must still be."""
    assert looks_like_reference(entry)


def test_json_with_a_byte_order_mark_is_json(tmp_path: Path) -> None:
    """Windows PowerShell 5.1's `Out-File -Encoding utf8` writes a BOM, and the file was
    reported as not being JSON at all."""
    path = tmp_path / "out.json"
    path.write_bytes(b'\xef\xbb\xbf{"n": 77}')
    values, used, skipped = load_backing([path])
    assert "77" in values and used == [path]
    assert skipped == []


def test_an_output_with_nul_bytes_and_no_bom_is_named_not_misread(tmp_path: Path) -> None:
    """UTF-16 without a byte-order mark cannot be told from binary, so it is not guessed at."""
    path = tmp_path / "out.txt"
    path.write_bytes("8393 3.84".encode("utf-16-le"))
    values, used, skipped = load_backing([path])
    assert used == [] and values == set()
    assert any("out.txt" in item and "NUL" in item for item in skipped)


def test_numbers_on_lines_read_as_references_are_listed_apart(tmp_path: Path) -> None:
    """A shape can be wrong, so what it accepts is compared like anything else and reported
    in a section of its own, where volume and page numbers do not bury the findings."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(
        "We saw 77 cases.\n\nSmith J, Jones K. Title. Lancet. 2019;393:100-10.\n", "utf-8"
    )
    report = audit([paper], [outputs])
    assert report.unmatched == []
    assert {c.line for c in report.reference_like} == {3}
    rendered = render(report, measure_discrimination(report.backing_values))
    assert "READ AS REFERENCE ENTRIES" in rendered


def test_a_long_run_of_spaces_does_not_stall_the_heading_check() -> None:
    """Five optional whitespace runs in a row backtracked polynomially: 26 s for one line of
    the kind `pdftotext -layout` writes."""
    import time

    from manuscript_guard.audit import is_bibliography_heading

    started = time.perf_counter()
    for line in (" " * 200 + "references" + " " * 200 + "x", "References" + " " * 300 + "12"):
        assert not is_bibliography_heading(line)
    assert time.perf_counter() - started < 0.5


def test_a_number_on_a_line_misread_as_a_reference_is_still_shown(tmp_path: Path) -> None:
    """The first version named the lines and never compared their numbers, and a later one
    stopped naming them after twelve: the thirteenth was the one hiding a number."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    entries = "\n\n".join(
        f"Smith{i} J, Jones K. Title. Lancet. 2019;393:{i}-10." for i in range(1, 13)
    )
    paper = tmp_path / "paper.md"
    paper.write_text(
        f"We saw 77.\n\n{entries}\n\n## Appendix\n\n"
        "Tanaka, Suzuki and Sato (2019). The sensitivity estimate was 9.99.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert any(c.text == "9.99" and c.line == 29 for c in report.reference_like)


@pytest.mark.parametrize(
    "entry",
    [
        "Smith, J., Østergaard, K. (2019). Hepatic injury. Drug Safety, 42, 1-9.",
        "Éric, M., & Jones, K. (2019). Hepatic injury. Drug Safety, 42, 1-9.",
        "Smith, J., dos Santos, A. (2019). Hepatic injury. Drug Safety, 42, 1-9.",
        "Smith, J., d'Alembert, A. (2019). Hepatic injury. Drug Safety, 42, 1-9.",
    ],
)
def test_an_entry_with_accented_or_particled_names_is_recognised(entry: str) -> None:
    assert looks_like_reference(entry)


def test_indented_lines_do_not_stall_the_reference_list_search() -> None:
    """`pdftotext -layout` indents a right-hand column by a hundred spaces or more, and the
    heading check was quadratic in leading whitespace: 20 s for 3,000 such lines."""
    import time

    from manuscript_guard.audit import bibliography_spans, strip_bibliography

    text = "\n".join([" " * 150 + "Some text 12"] * 3000)
    started = time.perf_counter()
    assert bibliography_spans(text) == []
    strip_bibliography(text)
    assert time.perf_counter() - started < 1.0


def test_an_entry_with_et_al_after_initials_is_recognised() -> None:
    assert looks_like_reference("Smith, J. et al. (2020). Hepatic injury. Drug Safety, 42, 1-9.")


def test_indented_prose_does_not_stall_the_entry_shape() -> None:
    """Two whitespace runs side by side at the start of the numbered-style shape made every
    unclassified number on an indented line quadratic: 17.5 s to audit 3,000 such lines."""
    import time

    started = time.perf_counter()
    for _ in range(3000):
        assert not looks_like_reference(" " * 150 + "accounted for 12 of 8,393 cases")
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "entry",
    [
        "Smith J, Jones K. Title. Lancet. 2019;393(Suppl 1):S1-S10.",
        "Smith J. Title. PLoS One. 2019;14(3):e0213. doi:10.1371/journal.pone.0213",
        "Smith J, Jones K. Title. Lancet. 2019;393:100-10. Epub 2019 Jan 5.",
        "Smith J. Title. Drug Saf. 2019 Mar 5;42(3):100-10. PMID: 12345678.",
    ],
)
def test_a_numbered_entry_with_a_trailing_note_is_recognised(entry: str) -> None:
    """The shape now ends at the pages, so what may follow them is named."""
    assert looks_like_reference(entry)


def test_a_long_chain_of_numbers_does_not_stall_the_interval_split() -> None:
    """The digit each segment requires could be placed in many ways, so the work multiplied
    per segment: 100 s for a 72-character hyphenated token."""
    import time

    started = time.perf_counter()
    parts_of("12345-" * 11 + "12345a")
    parts_of("1.23/" * 14 + "1.23mg")
    parts_of("1" * 4000)
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize(
    "entry",
    [
        "Østergaard L, Smith J. Title. Lancet. 2019;393:100-10.",
        "Smith J. Title. Lancet. 2019;393:100-10. PubMed PMID: 12345678.",
    ],
)
def test_a_numbered_entry_named_in_known_gaps_as_recognised_is(entry: str) -> None:
    assert looks_like_reference(entry)


def test_a_double_hyphen_in_markdown_errs_toward_a_false_alarm(tmp_path: Path) -> None:
    """Pandoc renders "--" in Markdown prose as an en dash, but not in code, where R's
    output puts "-0.72--0.30" meaning -0.30. Emulating pandoc took three review rounds and
    kept flipping signs in code; reading "--" as a minus everywhere errs the safe way, so a
    Markdown range written "2010--2019" is reported, not matched."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"a": 2010, "b": 2019}', encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("Reports from 2010--2019 were read.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["2010--2019"]
