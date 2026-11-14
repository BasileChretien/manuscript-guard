"""Auditing a paper that was never written with this toolkit.

The audit answers a weaker question than `check` — does this number appear anywhere in the
outputs? — so the tests hold it to two things: it must catch a number that appears nowhere,
and it must report honestly how little a match is worth.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from manuscript_guard import from_word
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


def make_docx(path: Path, body: str, styles: str = "", numbering: str = "") -> Path:
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), document)
        if styles:
            part = f"<w:styles {NS}>{styles}</w:styles>"
            archive.writestr(zipfile.ZipInfo("word/styles.xml", FIXED_TIME), part)
        if numbering:
            archive.writestr(zipfile.ZipInfo("word/numbering.xml", FIXED_TIME), numbering)
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


@pytest.mark.parametrize(
    ("cell", "line", "is_heading"),
    [
        (gone("-0.5") + para("1"), "-0.51", False),
        (gone("Table") + heading("References"), "TableReferences", True),
        (gone("References", "Heading1") + para("Table"), "ReferencesTable", False),
    ],
    ids=["text", "text-then-heading", "heading-then-text"],
)
def test_a_joined_line_in_a_table_cell_is_still_a_cell(
    tmp_path: Path, cell: str, line: str, is_heading: bool
) -> None:
    """A cell's line is marked, because "References" there is a column header. The mark goes
    at the start of the joined line, not in the middle of it, and after the heading mark
    when the last paragraph is a heading."""
    table = f"<w:tbl><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"
    document = read_docx_text(make_docx(tmp_path / "c.docx", table))
    lines = document.body.split("\n")
    assert lines[-1] == line, lines
    assert len(lines) - 1 in document.cells
    assert (len(lines) - 1 in document.headings) == is_heading


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


def tracked(change: str, text: str, style: str = "", runs: str = "") -> str:
    """A paragraph whose mark and text were deleted, inserted or moved as a tracked change,
    with any further `runs` inside the same change."""
    styled = f'<w:pStyle w:val="{style}"/>' if style else ""
    kind = "delText" if change == "del" else "t"
    return (
        f'<w:p><w:pPr>{styled}<w:rPr><w:{change} w:id="2" w:author="a"/></w:rPr></w:pPr>'
        f'<w:{change} w:id="3" w:author="a"><w:r><w:{kind}>{text}</w:{kind}></w:r>{runs}'
        f"</w:{change}></w:p>"
    )


def tracked_row(change: str, *cells: str, style: str = "") -> str:
    """A table row inserted, deleted or moved away as a tracked change, as Word 16 writes
    one: each cell paragraph's mark and text marked with the change, and the row marked in
    its properties when it was inserted or deleted. A row moved away is not marked as one."""
    inner = "".join(f"<w:tc>{tracked(change, c, style)}</w:tc>" for c in cells)
    props = f'<w:trPr><w:{change} w:id="1" w:author="a"/></w:trPr>' if change != "moveFrom" else ""
    return f"<w:tr>{props}{inner}</w:tr>"


# A row moved away holding a text box: Word 16 marks no paragraph of the box, in either
# copy, since its anchor went with the text around it (verified 2026-09-25).
BOXED = tracked("moveFrom", "b", runs=text_box(para("Box 9"), fallback=True))
# A row moved away holding a table: Word 16 moves that table's paragraph marks too.
NESTED = f"{tracked('moveFrom', 'b')}<w:tbl>{tracked_row('moveFrom', '9')}</w:tbl>"
# The same, but with the nested table's paragraph left in place: the row stays.
AROUND = f"{tracked('moveFrom', 'b')}<w:tbl>{row('9')}</w:tbl>{tracked('moveFrom', '')}"


@pytest.mark.parametrize(
    ("tracked_table", "plain"),
    [
        (
            f"<w:tbl>{row('a', '11')}{tracked_row('del', 'b', '22', style='Heading1')}"
            f"{row('c', '33')}</w:tbl>",
            f"<w:tbl>{row('a', '11')}{row('c', '33')}</w:tbl>",
        ),
        (
            f"<w:tbl>{tracked_row('del', 'a', '11')}{tracked_row('del', 'b', '22')}</w:tbl>",
            "",
        ),
        (
            f"<w:tbl>{row('a', '11')}{tracked_row('moveFrom', 'b', '22', style='Heading1')}"
            f"{row('c', '33')}</w:tbl>",
            f"<w:tbl>{row('a', '11')}{row('c', '33')}</w:tbl>",
        ),
        (
            f"<w:tbl>{row('a', '11')}<w:tr><w:tc>{BOXED}</w:tc></w:tr>{row('c', '33')}</w:tbl>",
            f"<w:tbl>{row('a', '11')}{row('c', '33')}</w:tbl>",
        ),
        (
            f"<w:tbl>{row('a', '11')}<w:tr><w:tc>{NESTED}{tracked('moveFrom', '')}</w:tc></w:tr>"
            "</w:tbl>",
            f"<w:tbl>{row('a', '11')}</w:tbl>",
        ),
        (
            f"<w:tbl>{row('a', '11')}{tracked_row('ins', 'c', '33')}</w:tbl>",
            f"<w:tbl>{row('a', '11')}{row('c', '33')}</w:tbl>",
        ),
        (
            f"<w:tbl><w:tr><w:tc>{tracked('moveFrom', 'b')}{para('22')}</w:tc></w:tr></w:tbl>",
            f"<w:tbl>{row('22')}</w:tbl>",
        ),
        (
            f"<w:tbl><w:tr><w:tc>{AROUND}</w:tc></w:tr></w:tbl>",
            f"<w:tbl><w:tr><w:tc><w:p/><w:tbl>{row('9')}</w:tbl><w:p/></w:tc></w:tr></w:tbl>",
        ),
    ],
    ids=[
        "deleted-row",
        "deleted-table",
        "moved-row",
        "moved-row-with-text-box",
        "moved-row-with-table",
        "inserted-row",
        "moved-from-cell",
        "moved-around-a-kept-table",
    ],
)
def test_a_table_row_gone_is_read_as_absent_and_an_inserted_one_as_present(
    tmp_path: Path, tracked_table: str, plain: str
) -> None:
    """A deleted row's text was dropped, but the row and its cells still broke lines, and a
    cell styled as a heading was recorded as an empty heading - which ended the reference
    list it stood in. A deleted table is every row deleted, and a row moved away has every
    paragraph mark in it moved, a nested table's too, though not a text box's. The document
    reads as it will once the changes are accepted, as if the row had never been there, or
    always had. A paragraph moved out of a cell leaves the row, which keeps the mark of the
    cell's last paragraph, and so does a row whose nested table stays."""

    def read(name: str, table: str) -> DocxText:
        body = para("Intro") + table + para("End")
        return read_docx_text(make_docx(tmp_path / f"{name}.docx", body))

    assert read("tracked", tracked_table) == read("plain", plain)


@pytest.mark.parametrize(
    ("table", "lines"),
    [
        (f"<w:tbl>{tracked_row('del', '7')}{tracked_row('del', '8')}</w:tbl>", ["-0.51"]),
        (f"<w:tbl>{tracked_row('moveFrom', '7')}{tracked_row('moveFrom', '8')}</w:tbl>", ["-0.51"]),
        (f"<w:tbl>{tracked_row('del', '7')}{row('8')}</w:tbl>", ["-0.5", "|", "8", "1"]),
    ],
    ids=["deleted", "moved", "one-row-kept"],
)
def test_a_join_runs_past_a_table_word_drops_whole(
    tmp_path: Path, table: str, lines: list[str]
) -> None:
    """A table whose every row was deleted or moved away is not there once the changes are
    accepted, and Word 16 joins the paragraphs either side of it: "-0.5" and "1" read apart
    matched two outputs where Word shows -0.51. A table with a row left still parts them."""
    text = read_docx(make_docx(tmp_path / "t.docx", gone("-0.5") + table + para("1")))
    assert [line.strip() for line in text.split("\n") if line.strip()] == lines


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


GREEK_STYLE = (
    '<w:style w:type="character" w:styleId="Greek"><w:name w:val="Greek"/>'
    '<w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol"/></w:rPr></w:style>'
)


@pytest.mark.parametrize(
    ("run", "styles"),
    [
        ('<w:r><w:sym w:font="Symbol" w:char="F06D"/></w:r>', ""),
        ('<w:r><w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol"/></w:rPr><w:t>m</w:t></w:r>', ""),
        (f"<w:r><w:rPr><w:rFonts w:hAnsi=\"Symbol\"/></w:rPr><w:t>{chr(0xF06D)}</w:t></w:r>", ""),
        ('<w:r><w:rPr><w:rStyle w:val="Greek"/></w:rPr><w:t>m</w:t></w:r>', GREEK_STYLE),
    ],
    ids=["inserted", "typed", "typed-private-use", "from-a-style"],
)
def test_the_symbol_font_is_read_as_what_it_draws(tmp_path: Path, run: str, styles: str) -> None:
    """Insert > Symbol writes the μ of the Symbol font as `w:sym`, which the reader knew only
    for the five characters that stand beside a number, and read as a space otherwise. Typed
    in that font it is an `m`, or the private-use U+F06D, which Word draws as μ."""
    body = f'<w:p><w:r><w:t xml:space="preserve">5 </w:t></w:r>{run}<w:r><w:t>g</w:t></w:r></w:p>'
    assert read_docx(make_docx(tmp_path / "s.docx", body, styles)) == f"\n5 {chr(0x03BC)}g"


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


def test_a_link_to_the_references_alone_on_a_wrapped_line_cuts_the_paper() -> None:
    """A known gap (DESIGN.md, Known gaps): the audit takes a bibliography's title on any
    line, and a link is read by its words, so a hard wrap that leaves `[References](#refs)`
    alone on a line inside a paragraph cuts the paper there. `check` asks for a paragraph's
    first line and opens no list."""
    from manuscript_guard.audit import bibliography_spans
    from manuscript_guard.text.reference_lists import unmarked_reference_lists

    text = "The entries are listed in the\n[References](#refs)\nwith 77 cases.\n"
    assert bibliography_spans(text) == [(1, 3)]
    assert unmarked_reference_lists(text) == []


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


def test_a_bound_written_hard_against_a_citation_marker_is_still_audited(
    tmp_path: Path,
) -> None:
    """The marker rule's prefix took a `]`, so in `3.40][12]` the bound was matched as part
    of a citation and never compared with the outputs: a fabricated interval passed."""
    outputs = tmp_path / "out.csv"
    outputs.write_text("v\n2.51\n1.20\n1.87\n1.10\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(
        "The reporting odds ratio was 2.51 [95% CI 1.20, 3.40][12]—consistent with it.\n"
        "The second estimate was 1.87 [95% CI 1.10, 9.99][14]. Across cohorts.\n",
        encoding="utf-8",
    )
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert "3.40" in unmatched and "9.99" in unmatched, unmatched


def _audited(tmp_path: Path, outputs: list[str], text: str):
    csv = tmp_path / "out.csv"
    csv.write_text("v\n" + "\n".join(outputs) + "\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text(text, encoding="utf-8")
    report = audit([paper], [csv])
    return [c.text for c in report.unmatched], [c.text for c in report.matched]


def test_a_value_glued_to_a_citation_marker_is_audited_apart_from_it(tmp_path: Path) -> None:
    """The marker rule spanned the word before a marker, digits included, so in
    `(95% CI 1.20, 9.99)[12]` the bound was filed as part of the citation and never compared
    with the outputs: a fabricated bound in a numbered-reference paper passed."""
    unmatched, matched = _audited(
        tmp_path,
        ["2.51", "1.20", "3.40"],
        "It was 2.51 (95% CI 1.20, 9.99)[12]. Rates reached 45%[14] overall.\n"
        "The upper bound was 3.40[12], and later work[13-15] agreed.\n",
    )
    assert "9.99" in unmatched and "45%" in unmatched, unmatched
    # A value that is in the outputs still matches: reading it apart adds no noise.
    assert "3.40" in matched, matched
    # The markers themselves are still citations.
    assert not any("[" in text or text in ("12", "14", "13-15") for text in unmatched), unmatched


def test_a_number_glued_to_a_marker_that_is_no_result_is_listed(tmp_path: Path) -> None:
    """The cost of reading them apart, chosen knowingly: a version is a number, and one the
    outputs do not hold is listed. A year in brackets is still a citation."""
    unmatched, _ = _audited(
        tmp_path, ["412"], "The pipeline (OEP 2026.1)[15] ran, as described (2019)[4].\n"
    )
    assert unmatched == ["2026.1"], unmatched


@pytest.mark.parametrize(
    ("text", "bounds"),
    [
        ("Age, median [IQR]: 64 [55-72] years.\n", "55-72"),
        ("Age was 64 [55, 72] years.\n", "55"),
        ("Length of stay was 7 [4-12] days.\n", "4-12"),
        ("| Age | 64 [55–72] | 61 [50–70] |\n", "55–72"),
    ],
)
def test_a_whole_number_interval_after_its_value_is_audited(
    tmp_path: Path, text: str, bounds: str
) -> None:
    """A bracketed run of whole numbers was always a citation marker, so the bounds of a
    median [IQR] went unaudited. An interval encloses the value before it; a citation range
    does not, so `[13-15]` after a word, and `12% [4-6]`, are still citations."""
    unmatched, _ = _audited(tmp_path, ["64", "61", "7"], text)
    assert bounds in unmatched, unmatched


@pytest.mark.parametrize(
    ("text", "bounds"),
    [
        ("Le score était de 12,5 [10-15] points.\n", "10-15"),
        ("Median stay was 1,204 [1,100-1,300] days.\n", "1,100-1,300"),
        ("Rates were 45 % [40-50] overall.\n", "40-50"),
        ("Rates were 45\N{NO-BREAK SPACE}% [40, 50] overall.\n", "40"),
    ],
)
def test_an_interval_after_a_comma_or_a_spaced_percent_is_audited(
    tmp_path: Path, text: str, bounds: str
) -> None:
    """The test that the bounds enclose the value read the value as digits with a point and
    a percent sign against it, so after a decimal comma, a thousands comma or a spaced
    percent sign the interval was filed as a citation and its bounds never compared."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert bounds in unmatched, unmatched


@pytest.mark.parametrize(
    "text",
    [
        "Rates of 12,5 [4-6] were seen.\n",
        "In n=1,204 [1-3] records.\n",
        "In n=1,204 [0-3] records.\n",
        "In n=1,204 [150-300] records.\n",
        "Rates were 45 % [4-6] overall.\n",
        "In n=1,204 [1,100,200] records.\n",
    ],
)
def test_a_citation_after_a_comma_written_value_it_does_not_enclose_is_a_citation(
    tmp_path: Path, text: str
) -> None:
    """A thousands comma is read as one, so `1,204 [1-3]` is no interval, and the bounds are
    whole numbers of a citation's size: `[1,100,200]` is three citations."""
    unmatched, _ = _audited(tmp_path, ["7", "1,204", "12,5", "45 %", "45"], text)
    assert not any("[" in listed or "-" in listed for listed in unmatched), unmatched


def test_a_citation_range_after_a_value_it_does_not_enclose_is_a_citation(
    tmp_path: Path,
) -> None:
    unmatched, _ = _audited(
        tmp_path,
        ["12", "412"],
        "Rates of 12% [4-6] were reported, in 412 records [3], as earlier work [13-15] had.\n",
    )
    assert unmatched == [], unmatched


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("The earlier trial (N=2004)[4] was larger.\n", "2004"),
        ("A registry study (reported in 2019, n=412)[5] found it.\n", "412"),
        ("The pooled estimate (2019; 95% CI 1.20–9.99)[12] held.\n", "9.99"),
        ("As before (Smith 2019, n=412)[5], rates rose.\n", "412"),
    ],
)
def test_a_value_read_apart_from_its_marker_is_not_filed_as_an_author_year_citation(
    tmp_path: Path, text: str, value: str
) -> None:
    """Read apart from the marker, the value sat inside a parenthetical holding a year, and
    the author-year rule filed it: `(N=2004)[4]` was listed whole before, and hidden after."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert any(value in listed for listed in unmatched), unmatched


@pytest.mark.parametrize(
    ("text", "bound"),
    [
        ("Le rapport était de 2,51[1,20-9,99] dans la cohorte.\n", "9,99"),
        ("Median stay was 1,204[1,100-1,300] days.\n", "1,300"),
    ],
)
def test_a_comma_written_value_keeps_its_bracket(tmp_path: Path, text: str, bound: str) -> None:
    """With a comma in the value, the bracket glued to it may be a decimal-comma interval,
    `[1,20-9,99]`, which a marker's shape also fits: split off, its bounds were filed as a
    citation. The run is left whole, and listed, as before."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert any(bound in listed for listed in unmatched), unmatched


@pytest.mark.parametrize(
    ("text", "bound"),
    [
        ("The odds were OR=3[1,20-9,99] overall.\n", "9,99"),
        ("Median stay N=1204[1,100-1,300] days.\n", "1,300"),
        ("Age 64 (Q1–Q3)[55–72] years.\n", "55–72"),
    ],
)
def test_a_run_the_marker_rule_never_took_whole_is_listed_whole(
    tmp_path: Path, text: str, bound: str
) -> None:
    """Read apart, these left their bracket to the marker rule, which filed the bounds; the
    rule never took the whole run, so it used to be listed. Only a run the rule took whole
    is read apart now, and reading one apart can only add to what is compared."""
    unmatched, _ = _audited(tmp_path, ["3", "64"], text)
    assert any(bound in listed for listed in unmatched), unmatched


@pytest.mark.parametrize(
    "text",
    [
        "As reported (Smith 2019, p. 12)[5], rates rose.\n",
        "Fitted as before (Smith 2019; R 4.3.1)[5] here.\n",
    ],
)
def test_a_number_read_apart_falls_through_to_the_other_rules(tmp_path: Path, text: str) -> None:
    """The author-year verdict is not taken for a number read apart, but the locator and
    version rules after it still are: `p. 12` is a page, `R 4.3.1` a version."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert unmatched == [], unmatched


@pytest.mark.parametrize(
    "text",
    ["Rates of 12,5 [4-6] were seen.\n", "In n=1,204 [150-300] records.\n"],
)
def test_digits_after_a_comma_are_not_taken_for_the_value(tmp_path: Path, text: str) -> None:
    """`12,5 [4-6]` read 5 as the value, which the citation range encloses, so the marker
    was taken for an interval and listed."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert not any(listed in ("4-6", "150-300") for listed in unmatched), unmatched


@pytest.mark.parametrize(
    ("text", "number"),
    [("About [½][12] of them.\n", "½"), ("Item [①][12] held.\n", "①")],
)
def test_a_number_in_the_bracket_before_a_marker_is_compared(
    tmp_path: Path, text: str, number: str
) -> None:
    """The one-word bracket the marker rule allows, for `[SmPC][4]`, took any character but
    a decimal digit, and `½` and `①` are numbers that are not: they were filed as part of the
    citation, where the audit used to compare them."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert any(number in listed for listed in unmatched), unmatched


def test_a_marker_that_never_closes_leaves_its_run_whole(tmp_path: Path) -> None:
    """The marker rule takes a closed bracket, so a run whose bracket never closes was never
    one it took, and is listed whole, not read apart into a table reference and a number."""
    unmatched, _ = _audited(tmp_path, ["7"], "Shown in Table 2[3. then it held.\n")
    assert "2[3" in unmatched, unmatched


def test_emphasis_before_a_marker_is_a_citation(tmp_path: Path) -> None:
    unmatched, _ = _audited(tmp_path, ["7"], "Infection with _E. coli_[3] was common.\n")
    assert unmatched == [], unmatched


@pytest.mark.parametrize(
    ("text", "listed"),
    [
        ("About [x]½[12] of them.\n", "x]½[12"),
        ("Median [IQR][55-72] years.\n", "IQR][55-72"),
        ("See the Summary of Product Characteristics [SmPC][4].\n", "SmPC][4"),
    ],
)
def test_a_run_opening_on_a_bracketed_word_is_listed_whole(
    tmp_path: Path, text: str, listed: str
) -> None:
    """The marker rule once allowed a bracketed word before a marker, so that `[SmPC][4]`
    was not listed. It filed `½` and a whole-number interval with the citation too, where
    they used to be compared; the false positive is the smaller cost, and it is listed."""
    unmatched, _ = _audited(tmp_path, ["7"], text)
    assert listed in unmatched, unmatched


def test_a_value_before_a_spaced_citation_list_is_compared(tmp_path: Path) -> None:
    """The atom stops at the list's first number, so the marker's `]` is not right after it:
    requiring that left `9.99)[1` whole, and a correct value was listed as unexplained."""
    unmatched, matched = _audited(
        tmp_path, ["1.20", "9.99", "45"], "CI 1.20, 9.99)[1, 2] and 45%[3; 4] held.\n"
    )
    assert "9.99" in matched and "45%" in matched, (matched, unmatched)
    assert unmatched == [], unmatched


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


def test_a_decimal_with_no_digit_before_its_point_is_read_as_one(tmp_path: Path) -> None:
    """APA writes a p or an r with no nought before the point. The reader of the outputs
    needed a digit before a point, so `p = .661` went into the backing set as 661: the
    paper's .661 never matched, and a stray integer joined the set. A point after a letter,
    a digit or another point is not a leading point: `a.0.b` and `results.json` are keys."""
    outputs = tmp_path / "out.txt"
    outputs.write_text(
        "p = .661, r (.30), d -.25, s –.45, a.0.b in results.json, v1.2.7, wait...5\n", "utf-8"
    )
    values, _used, _skipped = load_backing([outputs])
    assert {"0.661", "0.3", "-0.25", "-0.45", "0", "1.2", "7", "5"} <= values
    assert not {"661", "30", "25", "0.25", "0.7", "0.5", "-0.5"} & values

    paper = tmp_path / "paper.md"
    paper.write_text("The test gave p = .661 and r = .30.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == []


def test_an_interval_of_leading_point_bounds_is_split() -> None:
    assert parts_of(".72–.82") == ["0.72", "0.82"]
    assert parts_of("-.30–.15") == ["-0.3", "0.15"]


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
    "heading",
    [
        "# References {-}",
        "# References {.unnumbered}",
        "# References {#refs .unnumbered}",
        '## Bibliography {#refs .unnumbered title="Works cited"}',
        "References {-}",
        "**References** {-}",
        "# References # {-}",
        "# References ##",
        '# References {#refs title="the \\"cited\\" works"}',
        "# References {#refs note=a\\}b}",
        "# References {k=a\\{b}",
        "# References {#refs lang=fr\u00a0FR}",
        '# References {title=""}',
        '# References {title="\N{NEXT LINE}x y"}',
        '# References {title="\N{LINE SEPARATOR}x y"}',
        "# References {.\N{LATIN CAPITAL LETTER D WITH SMALL LETTER Z WITH CARON}}",
        "# References {-} \t",
    ],
)
def test_a_marked_heading_may_end_in_what_pandoc_does_not_print(heading: str) -> None:
    """Pandoc prints `# References {-}` as "References", unnumbered. Only the heading word and
    `[\\s*_:.|]` were allowed after it, so the attribute block, or the closing `#`s it may
    follow, made the line no heading at all."""
    from manuscript_guard.audit import is_bibliography_heading

    assert is_bibliography_heading(heading, marked=True)


@pytest.mark.parametrize(
    "line", ["References {-}", "References {.unnumbered}", "**References** {#refs}"]
)
def test_an_unmarked_line_with_an_attribute_block_is_not_a_heading(line: str) -> None:
    """Braces are markup only where pandoc reads a heading. A line judged by its shape is
    printed as it stands, so "References {-}" there is text."""
    from manuscript_guard.audit import is_bibliography_heading

    assert not is_bibliography_heading(line)


@pytest.mark.parametrize(
    "heading",
    [
        "# References {and further reading}",
        "# References \\{-}",
        "# References {-} ##",
        "# References {k=\\}",
        "# References {k=a\\}",
        '# References {title=" Works cited"}',
        "# References {k=' a'}",
        '# References {title="\tWorks"}',
        '# References {title="\N{IDEOGRAPHIC SPACE}x y"}',
        "# References {-}\N{NO-BREAK SPACE}",
        "# References {-}\N{IDEOGRAPHIC SPACE}",
        "# References {-}\f",
        "# References #\N{NO-BREAK SPACE}",
        "# References {.\N{SUPERSCRIPT TWO}}",
        "# References {\N{SUPERSCRIPT TWO}=1}",
        "# References {.\N{ROMAN NUMERAL EIGHT}}",
    ],
)
def test_braces_pandoc_prints_are_part_of_the_heading(heading: str) -> None:
    """Pandoc takes off an attribute block and nothing else in braces: these print as they
    stand, so none of them is a heading that says only "References". In `{k=\\}` and
    `{k=a\\}` the closing brace is escaped, so there is no block to take off; pandoc reads
    no quoted value that opens with a space; only spaces and tabs may follow a block or a
    closing `#`; and a class or a key opens with a letter."""
    from manuscript_guard.audit import is_bibliography_heading

    assert not is_bibliography_heading(heading, marked=True)


def test_a_word_heading_keeps_its_hashes() -> None:
    """Closing `#`s are Markdown syntax. In a .docx a heading style marks the paragraph, and
    Word prints every `#` in "# References #"."""
    from manuscript_guard.audit import is_bibliography_heading

    assert is_bibliography_heading("# References #", marked=True)
    assert not is_bibliography_heading("# References #", marked=True, markdown=False)
    assert is_bibliography_heading("# References", marked=True, markdown=False)


@pytest.mark.parametrize("line", ["References #", "References ##", "Bibliography #"])
def test_a_hash_ends_only_a_heading_that_opens_with_one(line: str) -> None:
    """Closing `#`s belong to an ATX heading. A setext heading or a styled Word paragraph
    reading "References #" prints the `#`, so it is not a heading that says only
    "References"."""
    from manuscript_guard.audit import is_bibliography_heading

    assert not is_bibliography_heading(line, marked=True)


@pytest.mark.parametrize(
    ("title", "printed"),
    [
        ("Results \\{-}", "Results \\{-}"),
        ("Results \\\\{-}", "Results \\\\"),
        ("Results \\\\\\{-}", "Results \\\\\\{-}"),
    ],
)
def test_a_brace_after_an_odd_run_of_backslashes_is_escaped(title: str, printed: str) -> None:
    """`\\{` is a brace, and `\\\\{` a backslash and then the block."""
    from manuscript_guard.text.sections import strip_attributes

    assert strip_attributes(title) == printed


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


#: Entries of the kinds the shapes did not know, one or more of each.
OTHER_ENTRIES = {
    "the BMJ's style": "Smith J, Jones K. Hepatic injury in reports. BMJ 2021;372:n71.",
    "no stop after a journal's name": (
        "3. Smith J, Jones K, et al. Hepatic injury. N Engl J Med 2019;380(3):100-10."
    ),
    "the BMJ's style with a DOI": (
        "Smith J. Hepatic injury. J Clin Epidemiol 2019;112:1-9. doi:10.1016/j.x.2019.01.001"
    ),
    "a book": "Smith J, Jones K. Hepatic injury. 2nd ed. London: Example Press; 2019.",
    "a chapter": (
        "Smith J. Liver. In: Jones K, editor. Hepatic injury. London: Example Press; 2019. "
        "p. 100-10."
    ),
    "a web page": (
        "Smith J. Hepatic injury [Internet]. Geneva: Example Agency; 2020 [cited 2021 Mar 5]. "
        "Available from: https://example.org/injury"
    ),
    "a web page in AMA style": (
        "Smith J. Hepatic injury. Example Agency. Published 2020. Accessed March 5, 2021. "
        "https://example.org/injury"
    ),
    "a web page in Harvard style": (
        "Smith, J. (2020) Hepatic injury. Available at: https://example.org/injury "
        "(Accessed: 5 March 2021)."
    ),
    "an organisation's web page": (
        "Example Agency. Hepatic injury [Internet]. 2020 [cited 2021 Mar 5]. Available from: "
        "https://example.org/injury"
    ),
    "online first": "Smith J, Jones K. Hepatic injury. Drug Saf. 2019. doi:10.1007/s40264-019-1",
    "online first in AMA style": (
        "Smith J. Hepatic injury. Drug Saf. Published online March 5, 2019. doi:10.1001/x.2019.1"
    ),
    "Harvard with no stop after the year": (
        "Smith, J. and Jones, K. (2019) 'Hepatic injury', Drug Safety, 42(3), pp. 1-9."
    ),
    "Harvard with no stop, a title in capitals": (
        "Smith, J. (2019) Hepatic injury. Drug Safety, 42, 1-9."
    ),
}


@pytest.mark.parametrize("kind", list(OTHER_ENTRIES))
def test_an_entry_of_another_style_is_recognised_without_a_heading(kind: str) -> None:
    """A book, a web page, an article online first, the BMJ's house style with no full stop
    before the year, and a Harvard entry with none after it: each was taken for prose, and
    its volume, pages and years were reported as unexplained numbers."""
    assert looks_like_reference(OTHER_ENTRIES[kind])


@pytest.mark.parametrize(
    "line",
    [
        "Figure A. Enrolment to Dec 2019;2:1 randomisation followed.",
        "Figure A. Case-control design, 2010 to 2019;1:4 matching.",
        "Figure A. Enrolment in 2019. Events were counted.",
        "Table S1. Characteristics by site: Tokyo; 2019 and 412 reports.",
        "Smith J reported 77 cases in 2019, available from the registry.",
        "Data were taken from the registry (available from https://example.org) in 2019.",
        "Smith, Jones and Brown (2019) found 77 cases.",
        "The code is in the Internet archive, 2019 release, at https://example.org.",
        "Figure A. Reports by year. Accessed on 412 sites in 2019, and more.",
    ],
)
def test_a_caption_or_a_sentence_is_not_mistaken_for_an_entry_of_another_style(
    line: str,
) -> None:
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


# ------------------------------------------------- a .docx with no heading styles

#: What ends a reference list under a paragraph that is no heading, in a .docx as `check`
#: ends one in Markdown: a caption, a back-matter title alone, a table.
ENDS_IN_A_DOCX = {
    "a figure's caption": para("Figure 1. Reports by year; 9.99 of them were serious."),
    "a table's caption": para("Table 2. Characteristics; 9.99 of them were serious."),
    "a back-matter title": para("Figure legends") + para("Reports by year; 9.99 were serious."),
    "a statement's title": para("Funding") + para("Grant 9.99 paid for it."),
    "a table": f"<w:tbl>{row('Serious', '9.99')}</w:tbl>",
    "an appendix": para("Appendix A. Search terms; 9.99 records were found."),
}


@pytest.mark.parametrize("kind", list(ENDS_IN_A_DOCX))
def test_a_reference_list_in_a_docx_with_no_heading_styles_ends_where_check_ends_one(
    tmp_path: Path, kind: str
) -> None:
    """With no heading styles the cut ran from "References" to the end of the body, and a
    caption, a statement or a table after the list was never audited. "References" typed
    alone on its line is the paper's heading, and the list is placed under it."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    body = (
        para("We saw 77.") + para("References")
        + para("Smith J, Jones K. Title. Lancet. 2019;393:100-10.")
        + para("Doe A. Title. BMJ. 2020;370:m1.") + ENDS_IN_A_DOCX[kind]
    )  # fmt: skip
    paper = make_docx(tmp_path / "paper.docx", body)

    report = audit([paper], [outputs])
    assert "9.99" in [c.text for c in report.unmatched], report.not_audited
    assert report.not_audited == ["paper.docx: References, paragraphs 1-2, read as the "
                                  "reference list"]


def test_a_styled_reference_heading_in_a_docx_still_runs_to_the_next_heading(
    tmp_path: Path,
) -> None:
    """A heading names where the list ends, as `# References` does in Markdown: the list
    under it runs on to the next heading, through a caption."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    body = (
        para("We saw 77.") + heading("References")
        + para("Smith J, Jones K. Title. Lancet. 2019;393:100-10.")
        + para("Figure 1. Reports by year; 9.99 of them.") + heading("Appendix")
        + para("It was 4.44.")
    )  # fmt: skip
    report = audit([make_docx(tmp_path / "paper.docx", body)], [outputs])
    assert [c.text for c in report.unmatched] == ["4.44"]


# ------------------------------------------------- HTML comments outside Markdown

#: A paragraph that mentions both of HTML's comment markers, with numbers between them.
MARKERS = "We strip &lt;!-- from the notes; 9.99 of them held, t(20) = 5.00, P = 0.80; and --&gt;."


def test_a_docx_prints_the_markers_of_an_html_comment_as_typed(tmp_path: Path) -> None:
    """Word prints `<!--` as typed, and its text went through the mask Markdown does, so a
    paragraph that mentions both markers hid everything between them from the comparison
    and from the test against its P."""
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    paper = make_docx(tmp_path / "paper.docx", para("We saw 77.") + para(MARKERS))

    report = audit([paper], [outputs])
    held = [c for c in report.unmatched if c.text == "9.99"]
    assert held, report.unmatched
    assert [d.line for d in report.disagreements] == [held[0].line]


def test_a_figure_prints_the_markers_of_an_html_comment_as_typed(
    tmp_path: Path, monkeypatch
) -> None:
    import manuscript_guard.audit as audit_module

    said = MARKERS.replace("&lt;", "<").replace("&gt;", ">")
    monkeypatch.setattr(audit_module, "read_figure", lambda path: f"77\n{said}\n")
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    figure = tmp_path / "forest.svg"
    figure.write_text("<svg/>", encoding="utf-8")

    report = audit([], [outputs], figures=[figure])
    assert "9.99" in [c.text for c in report.unmatched]
    assert [d.line for d in report.disagreements] == [2]


def test_markdown_still_hides_its_comments(tmp_path: Path) -> None:
    outputs = tmp_path / "out.json"
    outputs.write_text('{"n": 77}', encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("We saw 77.\n\n<!-- 9.99 was t(20) = 5.00, P = 0.80 -->\n", "utf-8")

    report = audit([paper], [outputs])
    assert report.unmatched == [] and report.disagreements == []


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


def attribute_blocks(n: int) -> list[str]:
    """Marked headings whose attribute blocks grow with `n`, about 2n characters each. None
    of them is a heading, and most fail only at their last character, where a pattern with a
    quantifier inside a quantifier would try every way of dividing the run between items."""
    return [
        "# References {" + "#a" * n + " !}",
        "# References {" + ".a" * n + "!}",
        "# References {" + "a" * 2 * n + "}",
        "# References {" + " " * 2 * n + "!}",
        "# References {" + "-" * 2 * n + "!}",
        "# References " + "{" * 2 * n + "}",
        "# References " + "{}" * n,
        "# References " + "{-} " * (n // 2),
        "# References " + "\\{" * n + "}",
        "# References {" + "k=\"a\\\" k='a\\' " * (n // 7) + "!}",
        '# References {k=" ' + "a" * 2 * n + '"}',
    ]


def attribute_values(n: int) -> list[str]:
    """More of them, each a `k=` value whose reading costs more per character past a size
    that falls between the two a ratio compares: from n = 400 to 3,200, or 1,600 to 12,800,
    they read 5 to 90 times the time while linear, often past a quadratic's 64. So a budget
    holds them, and the ratio does not."""
    return [
        '# References {k="' + "a" * 2 * n + " !}",
        '# References {k="' + '\\"' * n + " !}",
        "# References {k='" + "\\'" * n + " !}",
        "# References {k=" + "\\}" * n + " !}",
        "# References {k=" + "\\" * (2 * n + 1) + "}",
        "# References {k=" + "\u00a0" * 2 * n + " !}",
    ]


def test_a_long_attribute_block_does_not_stall_the_heading_check() -> None:
    """A marked heading's attribute block is read item by item, each character once."""
    import time

    from manuscript_guard.audit import is_bibliography_heading

    # 20,000 characters each. A linear reading of all eighteen took 300 to 400 ms on a loaded
    # machine, which the old 0.5 s budget barely covered; a quadratic one takes tens of
    # seconds (`_escaped` scanning back from the start of the line: 35 s). The run of 999
    # backslashes is as long whatever `n` is, and the `k=` values cost more per character
    # past a size, which is why they are timed here and not below.
    fixed = "# References " + ("\\" * 999 + "{") * 20 + "}"
    started = time.perf_counter()
    for line in (*attribute_blocks(10000), *attribute_values(10000), fixed):
        assert not is_bibliography_heading(line, marked=True)
    assert time.perf_counter() - started < 5.0


def test_the_heading_check_reads_an_attribute_block_in_linear_time(assert_linear) -> None:
    """The blocks that grow smoothly, timed as they grow. Timed with the run of 999
    backslashes among them, `_escaped` scanning back from the start of the line passed: that
    one line took over the 20 ms floor by itself, so the input never grew, and the ratio
    compared two times made mostly of the same constant. Without it, the same rescan reads 80
    times the time. The `k=` values are left to the budget above: with them, correct code
    read over 16 in 4 of 24 runs."""
    from manuscript_guard.audit import is_bibliography_heading

    def read(lines: list[str]) -> None:
        for line in lines:
            is_bibliography_heading(line, marked=True)

    assert_linear(attribute_blocks, read, 50, "the heading check, by attribute block")


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


def test_indented_lines_do_not_stall_the_reference_list_search(assert_linear) -> None:
    """`pdftotext -layout` indents a right-hand column by a hundred spaces or more, and the
    heading check was quadratic in leading whitespace: 20 s for 3,000 such lines. Timed as
    the indent grows, since that is what it was quadratic in, and as the lines do; a budget
    of 1 s for 3,000 lines left 2x headroom on a loaded machine. Both start small, so that
    a quadratic that has come back fails in seconds rather than being timed at length."""
    from manuscript_guard.audit import bibliography_spans, strip_bibliography

    def indented(width: int, lines: int = 300) -> str:
        return "\n".join([" " * width + "Some text 12"] * lines)

    def search(text: str) -> None:
        bibliography_spans(text)
        strip_bibliography(text)

    assert bibliography_spans(indented(150)) == []
    assert_linear(indented, search, 20, "the reference-list search, by indent")
    assert_linear(
        lambda lines: indented(150, lines), search, 20, "the reference-list search, by lines"
    )


def test_an_entry_with_et_al_after_initials_is_recognised() -> None:
    assert looks_like_reference("Smith, J. et al. (2020). Hepatic injury. Drug Safety, 42, 1-9.")


def test_indented_prose_does_not_stall_the_entry_shape(assert_linear) -> None:
    """Two whitespace runs side by side at the start of the numbered-style shape made every
    unclassified number on an indented line quadratic: 17.5 s to audit 3,000 such lines.
    Timed as the indent grows, from a small indent, as the search above is. The shape reads
    one line, so the number of lines is the caller's loop, not the shape's."""

    def indented(width: int) -> str:
        return " " * width + "accounted for 12 of 8,393 cases"

    def recognise(line: str) -> None:
        for _ in range(300):
            looks_like_reference(line)

    assert not looks_like_reference(indented(150))
    assert_linear(indented, recognise, 20, "the entry shape, by indent")


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


# ---------------------------------------------------------------- titles typed in bold


def bold(text: str, props: str = "<w:b/>") -> str:
    """A paragraph of one run whose properties are `props`, bold by default."""
    return f"<w:p><w:r><w:rPr>{props}</w:rPr><w:t>{text}</w:t></w:r></w:p>"


#: A character style in bold, one based on it, and a paragraph style in bold.
BOLD_STYLES = (
    '<w:style w:type="character" w:styleId="Strong"><w:name w:val="Strong"/>'
    "<w:rPr><w:b/></w:rPr></w:style>"
    '<w:style w:type="character" w:styleId="StrongToo"><w:name w:val="Strong too"/>'
    '<w:basedOn w:val="Strong"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="BoldPara"><w:name w:val="Bold para"/>'
    "<w:rPr><w:b/></w:rPr></w:style>"
)


def test_a_line_wholly_in_bold_is_known_as_pandoc_knows_bold(tmp_path: Path) -> None:
    """Bold as pandoc reads it (3.9.0.2): a run's own `w:b`, or its character style's; not
    the bold of a style that one is based on, nor a paragraph style's, which pandoc prints as
    plain text, nor `w:b` turned off, a run's own off over its style's on, a paragraph only
    half in bold, or a cell of a table. Read otherwise, the audit and `init --from` would
    make headings of different paragraphs."""
    half = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Half</w:t></w:r>'
            '<w:r><w:t xml:space="preserve"> plain</w:t></w:r></w:p>')  # fmt: skip
    cell = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Cell</w:t></w:r></w:p>"
            "</w:tc></w:tr></w:tbl>")  # fmt: skip
    # Round 1 of #598: a link's words, and a note's mark, are no title's to pandoc, and a
    # text box's paragraph is no paper's heading.
    link = ('<w:p><w:hyperlink w:anchor="m"><w:r><w:rPr><w:b/></w:rPr><w:t>Linked</w:t>'
            "</w:r></w:hyperlink></w:p>")  # fmt: skip
    noted = ('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Noted</w:t></w:r>'
             '<w:r><w:rPr><w:b/></w:rPr><w:footnoteReference w:id="1"/></w:r></w:p>')
    boxed = f"<w:p>{text_box(bold('Boxed'), fallback=False)}</w:p>"
    body = (bold("Direct") + bold("Character", '<w:rStyle w:val="Strong"/>')
            + bold("Based", '<w:rStyle w:val="StrongToo"/>')
            + '<w:p><w:pPr><w:pStyle w:val="BoldPara"/></w:pPr><w:r><w:t>Styled</w:t></w:r></w:p>'
            + bold("Off", '<w:b w:val="0"/>')
            + bold("Overruled", '<w:rStyle w:val="Strong"/><w:b w:val="false"/>')
            + half + cell + link + noted + boxed)  # fmt: skip
    document = read_docx_text(make_docx(tmp_path / "bold.docx", body, BOLD_STYLES))
    lines = document.body.split("\n")
    assert sorted(lines[at] for at in document.bold) == ["Character", "Direct"]
    assert "Boxed" in document.body and "Linked" in document.body


#: A paper with no heading style: an abstract of one paragraph, and its sections titled in
#: bold, the Results among them, then a reference list.
TITLED = (para("A study of things") + bold("Abstract")
          + para("Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).")
          + bold("Background") + para("Drugs cause harm.") + bold("Results")
          + para("Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).")
          + bold("References") + para("1. Doe J. A title. BMJ. 2020;1:2."))  # fmt: skip


def test_a_docx_titled_in_bold_is_placed_by_its_titles_and_says_so(tmp_path: Path) -> None:
    """In a .docx with no heading style, its titles in bold that name a section are its
    headings, as `init --from` makes them: the Abstract is compared with the Results, which
    it never was, and the report says how the headings were read and how to do better."""
    report = audit([make_docx(tmp_path / "paper.docx", TITLED)], [])
    assert report.abstract is not None and report.abstract.compared
    (said,) = report.headings
    assert said.startswith("paper.docx: no paragraph is in a heading style, so the 4 paragraphs "
                           "that name a section alone (Abstract, Background, Results, "
                           "References) were read as its headings, in bold or not")  # fmt: skip
    assert "give its section titles Word's heading styles" in said
    # Said in the text and on the page, under its own heading (the merge of main into #601
    # put it by hand where the page reads the notes).
    from manuscript_guard.auditing.report import render, view

    measured = measure_discrimination(report.backing_values)
    assert f"How the headings were read:\n  {said}" in render(report, measured, tmp_path)
    # The page and the PDF say it without the command `init --from` (`reader.for_a_reader`).
    plain = said.replace(", as `init --from` makes them;", ";")
    assert plain != said
    assert ["How the headings were read:", [plain]] in view(report, measured, tmp_path)["notes"]


def test_a_docx_with_no_heading_is_said_to_be_read_as_one_text(tmp_path: Path) -> None:
    """A .docx with no heading style and no line that names a section alone is read as one
    text, and the report says what that costs, where it said nothing. A sentence that opens
    with "Results", and a section's name in a table's cell or in a list Word bullets, are
    no heading."""
    from generated import TYPED_PARAGRAPH_NUMBERING, numbered

    body = (para("A study of things") + para("Summary of the study")
            + para("Of 412 patients, 77 (18.7%) had the event.") + para("Results were clear.")
            + numbered(0, 2).format("Methods") + f"<w:tbl>{row('ABSTRACT', '9')}</w:tbl>"
            + para("Of 412 patients, 77 (18.7%) had the event."))  # fmt: skip
    report = audit([make_docx(tmp_path / "paper.docx", body,
                              numbering=TYPED_PARAGRAPH_NUMBERING)], [])  # fmt: skip
    (said,) = report.headings
    assert "none on a line of its own names a section, so it was read as one text" in said
    assert "Abstract is not compared with its Results" in said
    assert not (report.abstract and report.abstract.compared)


#: A paper converted to Word with no heading style, its titles typed and in no bold, as the
#: real-paper corpus had them: "ABSTRACT" in capitals as a paragraph, numbered titles in
#: capitals or not ("1. INTRODUCTION", "3. Results"), and a sentence that opens with the word
#: "Results", which stays text.
TYPED = (para("A study of things") + para("ABSTRACT")
         + para("Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).")
         + para("1. INTRODUCTION") + para("Drugs cause harm.") + para("2. Methods")
         + para("We read 412 records.") + para("3. RESULTS")
         + para("Results were clear: of 412 patients, 77 (18.7%) had the event (OR 1.52, "
                "95% CI 1.10-2.10).")
         + para("4. Discussion") + para("It was so."))  # fmt: skip


def test_a_docx_whose_titles_are_typed_is_placed_by_them(tmp_path: Path) -> None:
    """The real-paper corpus (52 preprints, 2026-11-11): a Word paper with no heading style
    whose titles are typed as plain paragraphs, "ABSTRACT" and "3. RESULTS" among them, had
    no Abstract to the audit, which said so of 79% of such papers wrongly. A typed title
    that names a section alone is a heading now, in bold or not, numbered or not, in capitals
    or not; a sentence that opens with "Results" stays text."""
    document = read_docx_text(make_docx(tmp_path / "paper.docx", TYPED))
    lines = document.body.split("\n")
    from manuscript_guard.text.docx import typed_heading_levels

    assert [lines[at] for at, _level in typed_heading_levels(document)] == [
        "ABSTRACT", "1. INTRODUCTION", "2. Methods", "3. RESULTS", "4. Discussion"]
    report = audit([tmp_path / "paper.docx"], [])
    assert report.abstract is not None and report.abstract.compared
    assert report.abstract.not_found == [] and report.abstract.conflicts == []
    (said,) = report.headings
    assert said.startswith("paper.docx: no paragraph is in a heading style, so the 5 paragraphs "
                           "that name a section alone (ABSTRACT, INTRODUCTION, Methods, RESULTS, "
                           "Discussion) were read as its headings")  # fmt: skip


def _listed_titles(sentences: str = "") -> str:
    """A paper with no heading style whose titles Word numbers as a list's items, as six of
    the real-paper corpus had them (docx-educ-A3, docx-med-A3, docx-socio-A1 among them,
    2026-11-14): in capitals, with a colon, in title case, one numbered by its style with a
    subtitle beside it; `sentences` after the Results' first paragraph."""
    from generated import numbered

    def item(text: str, level: int = 0) -> str:
        return numbered(level).format(text)

    title = '<w:p><w:pPr><w:pStyle w:val="NumTitle"/></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>'
    sub = '<w:p><w:pPr><w:pStyle w:val="NumSub"/></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>'
    return (para("A study of things") + para("ABSTRACT")
            + para("Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).")
            + item("INTRODUCTION:") + para("Drugs cause harm.")
            + title.format("Methods") + sub.format("Study design and setting")
            + para("We read 412 records.") + item("RESULTS")
            + para("Of 412 patients, 77 (18.7%) had the event (OR 1.52, 95% CI 1.10-2.10).")
            + sentences + item("Discussion") + para("It was so."))  # fmt: skip


def test_a_docx_whose_titles_word_numbers_is_placed_by_them(tmp_path: Path) -> None:
    """A title Word numbers as a list's item, "1. INTRODUCTION" where the "1." is Word's,
    was a numbered line to the audit and no heading: four of six such papers in the
    real-paper corpus had "no Results heading" and their Abstract compared with nothing
    (2026-11-14). An item whose words name a section alone is a typed title now, its colon
    left out of its name; a numbered list of sentences, an item "Results of the survey" and
    one the list bullets stay a list's items, and are read as a flow is."""
    from generated import NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING, numbered

    from manuscript_guard.stats.flows import docx_lists
    from manuscript_guard.text.docx import typed_heading_levels

    listed = (numbered().format("Of 412 records, 30 were excluded.")
              + numbered().format("Results of the survey")
              + numbered(0, 2).format("Conclusions"))  # fmt: skip
    path = make_docx(tmp_path / "paper.docx", _listed_titles(para("We counted:") + listed),
                     NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING)  # fmt: skip
    document = read_docx_text(path)
    lines = document.body.split("\n")
    levels = typed_heading_levels(document)
    assert [lines[at] for at, _level in levels] == [
        "ABSTRACT", "INTRODUCTION:", "Methods", "RESULTS", "Discussion"]
    report = audit([path], [])
    assert report.abstract is not None and report.abstract.compared
    assert report.abstract.not_found == [] and report.abstract.conflicts == []
    (said,) = report.headings
    assert ("the 5 paragraphs that name a section alone (ABSTRACT, INTRODUCTION, Methods, "
            "RESULTS, Discussion) were read as its headings") in said, said
    # A title placed is a heading, not a list's item; the sentences are a list's.
    lists = docx_lists(lines, dict(document.levels), {at + 1: level for at, level in levels})

    def texts(items: tuple) -> list[str]:
        return [text for item in items for text in (item.text.strip(), *texts(item.children))]

    items = {text for one in lists for text in texts(one.items)}
    assert not {"INTRODUCTION:", "Methods", "RESULTS", "Discussion"} & items, lists
    assert {"Of 412 records, 30 were excluded.", "Results of the survey", "Conclusions"} <= items


def test_a_title_word_numbers_holding_more_than_its_line_is_no_heading(tmp_path: Path) -> None:
    """A known limit (DESIGN.md, "Known gaps"): a title Word numbers with its subsections
    numbered straight under it, "2. Methods" then "2.1 Participants", is an item holding a
    list to pandoc, and no heading to `init --from` nor to the audit, as docx-psych-B1 of
    the real-paper corpus has its Methods and Results; so is one with a paragraph pandoc
    joins to its item, a numbering's paragraph with no level."""
    from generated import TYPED_PARAGRAPH_NUMBERING, numbered

    from manuscript_guard.text.docx import typed_titles

    body = (para("ABSTRACT") + para("It was so.") + numbered().format("Methods")
            + numbered(1).format("Participants") + para("We read 412 records.")
            + numbered().format("Results") + numbered(0, 0).format("Of 412, 77 had it.")
            + numbered().format("Discussion") + para("It was so."))  # fmt: skip
    path = make_docx(tmp_path / "paper.docx", body, numbering=TYPED_PARAGRAPH_NUMBERING)
    assert [title for _at, title in typed_titles(read_docx_text(path))] == [
        "ABSTRACT", "Discussion"]


def test_a_run_in_label_typed_alone_is_read_as_a_heading(tmp_path: Path) -> None:
    """A known limit (DESIGN.md, "Known gaps"): a one-word paragraph "Results" typed as a
    label in the middle of the Methods is a heading, as a title typed alone is, and what
    follows it is placed under it; nothing tells the two apart in a paper with no heading
    style."""
    from manuscript_guard.text.docx import typed_heading_levels

    body = (para("ABSTRACT") + para("It was so.") + para("METHODS") + para("We ran one model.")
            + para("Results") + para("It fitted.") + para("Its sensitivity was checked."))
    document = read_docx_text(make_docx(tmp_path / "paper.docx", body))
    lines = document.body.split("\n")
    assert [lines[at] for at, _level in typed_heading_levels(document)] == [
        "ABSTRACT", "METHODS", "Results"]
    # Round 2 of #641: a second "RESULTS" in the Discussion, a section's name typed twice,
    # left the paper placed in no section; its titles in bold are placed, as they were
    # before a typed title was read, and the Abstract is compared.
    twice = (bold("Abstract") + para("Of 412 patients, 77 had it.") + bold("Introduction")
             + para("Drugs cause harm.") + bold("Methods") + para("We read 412 records.")
             + bold("Results") + para("Of 412 patients, 77 had it.") + bold("Discussion")
             + para("RESULTS") + para("A second study agreed.") + bold("References")
             + para("1. Doe J. A title. BMJ. 2020;1:2."))  # fmt: skip
    document = read_docx_text(make_docx(tmp_path / "twice.docx", twice))
    lines = document.body.split("\n")
    assert [lines[at] for at, _level in typed_heading_levels(document)] == [
        "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"]
    report = audit([tmp_path / "twice.docx"], [])
    assert report.abstract is not None and report.abstract.compared
    assert report.abstract.not_found == []


needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


MIXED = (bold("Abstract") + para("BACKGROUND") + para("Of 412, 77 had it.") + bold("Results")
         + para("Of 412, 77 had it.") + para("CONCLUSIONS") + bold("References"))


def test_bold_abstract_parts_beside_plain_ones_are_placed_at_one_level(tmp_path: Path) -> None:
    """A known limit (DESIGN.md, "Known gaps"): bold parts of an abstract beside plain ones
    cannot all be placed, and those in bold alone are placed at one level, its own "Results"
    the paper's, by the audit and by `init --from`, as a paper titled in bold alone was read
    before: the Abstract is compared with itself, and every number of it is found."""
    from manuscript_guard.text.docx import typed_heading_levels

    document = read_docx_text(_package(tmp_path / "mixed.docx", MIXED, ""))
    lines = document.body.split("\n")
    assert [(lines[at], level) for at, level in typed_heading_levels(document)] == [
        ("Abstract", 1), ("Results", 1), ("References", 1)]
    read = audit([tmp_path / "mixed.docx"], []).abstract
    assert read is not None and read.compared and read.matched == read.numbers > 0
    assert read.not_found == []


@needs_pandoc
def test_init_from_makes_bold_abstract_parts_beside_plain_ones_one_level(tmp_path: Path) -> None:
    made, titles = from_word.typed_headings(_blocks(_package(tmp_path / "m.docx", MIXED, "")))
    assert titles == ("Abstract", "Results", "References")
    assert [block["c"][0] for block in made if block["t"] == "Header"] == [1, 1, 1]


def _package(path: Path, body: str, styles: str, numbering: str = "") -> Path:
    """A .docx with the parts pandoc needs to read it (`test_from_word._package`)."""
    from test_from_word import _package as package

    return package(path, body, styles, numbering)


def _blocks(path: Path) -> list:
    """The blocks pandoc reads in a .docx, as `init --from` reads them."""
    import json
    import subprocess

    return json.loads(subprocess.run(["pandoc", str(path), "-f", "docx", "-t", "json"],
                                     capture_output=True, text=True, check=True,
                                     timeout=120).stdout)["blocks"]  # fmt: skip


@needs_pandoc
def test_pandoc_reads_a_numbered_paragraph_as_the_audit_takes_it(tmp_path: Path) -> None:
    """What pandoc (3.9.0.2) makes of each shape of numbered paragraph, read from its tree,
    that `Numbering.pandoc_item` and `text.docx._in_lists` are written from: a list's lone
    item; an item holding an item a level deeper, a paragraph with a numbering of 0 or of
    no level, or an empty item a level deeper; items at one level and numbering in one list,
    an empty paragraph between them; a list for each numbering; a subtitle whose style names
    a level and no numbering beside its base's title; a paragraph naming a numbering pandoc
    reads no level of, on its own; a bulleted item. Round 1 of #682: an item in List
    Paragraph indented from the left more than it hangs, an item to pandoc whatever its own
    indent, and so is a paragraph naming no level or a numbering of 0, a paragraph and no
    block quote; a level with no `w:numFmt` or no `w:lvlText`, which pandoc reads as no
    level, a paragraph on its own and joined to the item before it."""
    from generated import NUMBERED_STYLES, TYPED_PARAGRAPH_NUMBERING, numbered

    shapes = {
        "lone": (numbered().format("A"), [["A"]]),
        "indented, in List Paragraph": (numbered(style="ListParagraph", indent=True).format(
            "A"), [["A"]]),
        "no level, indented": (numbered(0, 77, indent=True).format("A"), "a paragraph"),
        "numbering 0, indented": (numbered(0, 0, indent=True).format("A"), "a paragraph"),
        "no format, alone": (numbered(0, 4).format("A"), "a paragraph"),
        "no text, alone": (numbered(0, 5).format("A"), "a paragraph"),
        "holding no format": (numbered().format("A") + numbered(0, 4).format("B"), [["A", "B"]]),
        "holding no text": (numbered().format("A") + numbered(0, 5).format("B"), [["A", "B"]]),
        "holding an item": (numbered().format("A") + numbered(1).format("B"), [["A", ["B"]]]),
        "holding numbering 0": (numbered().format("A") + numbered(0, 0).format("B"),
                                [["A", "B"]]),
        "holding no level": (numbered().format("A") + numbered(0, 77).format("B"), [["A", "B"]]),
        "holding an empty item": (numbered().format("A") + numbered(1).format(""),
                                  [["A", []]]),
        "two items, empty between": (numbered().format("A") + para("") + numbered().format("B"),
                                     [["A"], ["B"]]),
        "two numberings": (numbered().format("A") + numbered(0, 3).format("B"), "two lists"),
        "a subtitle by its style": (
            '<w:p><w:pPr><w:pStyle w:val="NumTitle"/></w:pPr><w:r><w:t>A</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="NumSub"/></w:pPr><w:r><w:t>B</w:t></w:r></w:p>',
            [["A"], ["B"]]),
        "no level, alone": (numbered(0, 77).format("A"), "a paragraph"),
        "bulleted": (numbered(0, 2).format("A"), "bulleted"),
    }  # fmt: skip
    # 3 a second numbering of 1's count; 4 a level with no format, 5 one with no text.
    numbering = TYPED_PARAGRAPH_NUMBERING.replace('<w:num w:numId="1">', (
        '<w:abstractNum w:abstractNumId="4"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
        '<w:lvlText w:val="%1."/></w:lvl></w:abstractNum><w:abstractNum w:abstractNumId="5">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/></w:lvl>'
        '</w:abstractNum><w:num w:numId="1">')).replace("</w:numbering>", (
        '<w:num w:numId="3"><w:abstractNumId w:val="0"/></w:num>'
        '<w:num w:numId="4"><w:abstractNumId w:val="4"/></w:num>'
        '<w:num w:numId="5"><w:abstractNumId w:val="5"/></w:num></w:numbering>'))
    from manuscript_guard.text.docx import read_docx_text

    def titles(blocks: list) -> set[str]:
        """What `init --from` reads a title from: a top-level paragraph, and a numbered
        list's item that is one paragraph."""
        said = [item[0]["c"] for block in blocks if block["t"] in ("Para", "OrderedList")
                for item in (block["c"][1] if block["t"] == "OrderedList" else [[block]])
                if len(item) == 1 and item[0]["t"] in ("Para", "Plain")]  # fmt: skip
        return {" ".join(from_word.text_of(inlines).split()) for inlines in said}

    def items(blocks: list) -> list:
        return [[" ".join(from_word.text_of(block["c"]).split()) if block["t"] == "Para"
                 else items(block["c"][1])[0] if block["t"] == "OrderedList" else block["t"]
                 for block in item] for item in blocks]  # fmt: skip

    for name, (shape, expected) in shapes.items():
        path = _package(tmp_path / "shape.docx", para("Before.") + shape + para("After."),
                        NUMBERED_STYLES, numbering)
        middle = _blocks(path)[1:-1]
        kinds = [block["t"] for block in middle]
        if expected == "two lists":
            assert kinds == ["OrderedList", "OrderedList"], name
        elif expected == "a paragraph":
            assert kinds == ["Para"], name
        elif expected == "bulleted":
            assert kinds == ["BulletList"], name
        else:
            assert kinds == ["OrderedList"] and items(middle[0]["c"][1]) == expected, (name, middle)
        # The audit takes as a line a title can be typed as what pandoc reads as one.
        document = read_docx_text(path)
        lines = document.body.split("\n")
        typed = {lines[at] for at in document.typed} - {"Before.", "After."}
        assert typed == titles(middle), (name, typed, middle)


@needs_pandoc
def test_a_plain_abstract_beside_bold_titles_named_twice_is_no_heading(tmp_path: Path) -> None:
    """A known limit (DESIGN.md, "Known gaps"): a plain "ABSTRACT" among titles in bold, one
    of whose names is typed again plain, "RESULTS" in the Discussion. The typed titles
    cannot be placed, so both readers take those in bold alone, and the Abstract is no
    heading: `init --from` sets it aside in the title page's comment, and the audit
    compares nothing, as both did before a plain title was read."""
    body = (para("ABSTRACT") + para("Of 412 patients, 77 had it.") + bold("Introduction")
            + para("Drugs cause harm.") + bold("Methods") + para("We read 412 records.")
            + bold("Results") + para("Of 412 patients, 77 had it.") + bold("Discussion")
            + para("RESULTS") + para("A second study agreed.") + bold("References")
            + para("1. Doe J. A title. BMJ. 2020;1:2."))  # fmt: skip
    path = _package(tmp_path / "paper.docx", body, "")
    document = read_docx_text(path)
    lines = document.body.split("\n")
    from manuscript_guard.text.docx import typed_heading_levels

    titles = ("Introduction", "Methods", "Results", "Discussion", "References")
    assert tuple(lines[at] for at, _level in typed_heading_levels(document)) == titles
    assert from_word.typed_headings(_blocks(path))[1] == titles
    comment, end, rest = from_word.convert(path).text.partition("-->")
    assert end and "ABSTRACT" in comment and "ABSTRACT" not in rest
    read = audit([path], []).abstract
    assert not (read and read.compared)


def test_a_typed_title_in_a_caption_a_cell_or_a_heading_styled_paper_is_no_heading(
    tmp_path: Path,
) -> None:
    """A section's name typed in Word's caption style or in a table's cell is no heading, as
    pandoc sets the caption beside a table as the table's and the other in a cell. In a
    document with a paragraph in a heading style, the styles alone are read, and a typed
    "RESULTS" is text."""
    styles = ('<w:style w:type="paragraph" w:styleId="Legende"><w:name w:val="caption"/>'
              "</w:style>")  # fmt: skip
    caption = '<w:p><w:pPr><w:pStyle w:val="Legende"/></w:pPr><w:r><w:t>RESULTS</w:t></w:r></w:p>'
    body = (para("ABSTRACT") + para("It was so.") + caption
            + f"<w:tbl>{row('Methods', '9')}</w:tbl>" + para("Of 9, 4 were."))  # fmt: skip
    document = read_docx_text(make_docx(tmp_path / "caption.docx", body, styles))
    lines = document.body.split("\n")
    from manuscript_guard.text.docx import typed_heading_levels

    assert [lines[at] for at, _level in typed_heading_levels(document)] == ["ABSTRACT"]
    styled = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Introduction</w:t>'
              "</w:r></w:p>" + para("RESULTS") + para("It was so."))  # fmt: skip
    document = read_docx_text(make_docx(tmp_path / "styled.docx", styled))
    assert typed_heading_levels(document) == ()


def test_a_heading_style_in_a_table_s_cell_makes_no_heading(tmp_path: Path) -> None:
    """A paragraph in a heading style in a table's cell places nothing where the cells are a
    paper's only such paragraphs, as pandoc keeps them in their cells and `init --from` makes
    no heading of them: the paper is placed by its typed titles, and the audit says its only
    heading styles are in a table. It was placed by its cells, and its typed "ABSTRACT" went
    unfound (docx-med-A3 of the corpus run of 2026-11-13). Beside a heading outside a table,
    a cell places as before: a boxed Abstract titled in its cell is compared (round 1 of
    #678). Either way the cell ends a reference list (DESIGN.md, "Known gaps")."""
    styles = ('<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
              "</w:style>")  # fmt: skip

    def heading(text: str) -> str:
        return f'<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'

    table = f"<w:tbl><w:tr><w:tc>{heading('Sr. No')}</w:tc></w:tr>{row('1')}</w:tbl>"
    body = (para("ABSTRACT") + para("Of 412 patients, 77 had it.") + para("INTRODUCTION")
            + para("Drugs cause harm.") + para("RESULTS") + para("Of 412 patients, 77 had it.")
            + para("REFERENCES") + para("Smith J. A study. Lancet. 2019;393:100-9.") + table
            + para("Of 9, 4 were."))  # fmt: skip
    path = make_docx(tmp_path / "paper.docx", body, styles)
    document = read_docx_text(path)
    lines = document.body.split("\n")
    from manuscript_guard.audit import bibliography_spans
    from manuscript_guard.text.docx import typed_heading_levels

    assert document.heading_levels == ()
    (cell,) = document.headings
    assert lines[cell] == "Sr. No"
    assert [lines[at] for at, _level in typed_heading_levels(document)] == [
        "ABSTRACT", "INTRODUCTION", "RESULTS", "REFERENCES"]  # fmt: skip
    report = audit([path], [])
    assert report.abstract and report.abstract.compared, report.abstract
    (said,) = report.headings
    assert "no paragraph outside a table is in a heading style" in said, said
    boxed = (f"<w:tbl><w:tr><w:tc>{heading('Abstract')}{para('Of 412 patients, 77 had it.')}"
             f"</w:tc></w:tr></w:tbl>{heading('Introduction')}{para('Drugs cause harm.')}"
             f"{heading('Results')}{para('Of 412 patients, 77 had it.')}{heading('References')}"
             f"{para('Smith J. A study. Lancet. 2019;393:100-9.')}{table}"
             f"{para('Of 9, 4 were.')}")  # fmt: skip
    path = make_docx(tmp_path / "boxed.docx", boxed, styles)
    report = audit([path], [])
    assert report.abstract and report.abstract.compared, report.abstract
    assert report.headings == []
    document = read_docx_text(path)
    lines = document.body.split("\n")
    spans = bibliography_spans(document.body, document.headings, document.cells)
    assert [lines[end] for _start, end in spans] == ["Sr. No"], spans


def test_bold_titles_that_cannot_be_placed_place_nothing(tmp_path: Path) -> None:
    """A structured abstract's parts in bold straight under its Abstract, with no
    Introduction after them and none of their names again: which Results are the paper's is
    not read, and that is said, as for a PDF. Placed at one level, the Abstract's own
    "Results" would be the paper's, and the Abstract compared with itself. So too where its
    parts are typed in plain capitals (round 2 of #641)."""
    body = (bold("Abstract") + bold("Background") + para("Drugs cause harm.") + bold("Results")
            + para("Of 412 patients, 77 had it.") + bold("Discussion") + para("It was so."))
    report = audit([make_docx(tmp_path / "paper.docx", body)], [])
    (said,) = report.headings
    assert "could not be placed" in said and "its lines were placed in no section" in said
    typed = (para("ABSTRACT") + para("BACKGROUND") + para("Drugs cause harm.")
             + para("RESULTS") + para("Of 412 patients, 77 had it.") + para("DISCUSSION")
             + para("It was so."))  # fmt: skip
    report = audit([make_docx(tmp_path / "typed.docx", typed)], [])
    (said,) = report.headings
    assert "could not be placed" in said
    assert not (report.abstract and report.abstract.compared)


def test_headings_in_a_style_are_read_and_nothing_is_said(tmp_path: Path) -> None:
    styles = ('<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
              "</w:style>")  # fmt: skip
    body = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Results</w:t></w:r></w:p>'
    report = audit([make_docx(tmp_path / "paper.docx", body + bold("Methods") + para("x"),
                              styles)], [])  # fmt: skip
    assert report.headings == []
    markdown = tmp_path / "paper.md"
    markdown.write_text("Of 412 patients, 77 had it.\n", encoding="utf-8")
    (said,) = audit([markdown], []).headings
    assert said.startswith("paper.md: it has no heading, so it was read as one text")


@pytest.mark.parametrize(
    ("atom", "parts"),
    [
        ("0.41points", ["0.41"]), ("10hours", ["10"]), ("to+0.77", ["+0.77"]),
        ("CI):+0.05", ["+0.05"]), ("students(66%", ["66%"]),
        ("95%CI:0.03-0.88", ["95%", "0.03", "0.88"]),
        ("45%(95%CI:40-50%", ["45%", "95%", "40", "50"]),
        ("+0.41points(95%CI:+0.09-0.77", ["+0.41", "95%", "0.09", "0.77"]),
        ("2ndyear", []), ("21stcentury", []), ("11thgrade", []),
        ("312students", ["312"]), ("20studies", ["20"]), ("4stages", ["4"]),
        ("10therapists", ["10"]), ("21students", ["21"]), ("2ndly", ["2"]),
        ("CYP3A4", ["CYP3A4"]), ("user@x.org", ["user@x.org"]), ("v2.1", ["v2.1"]),
        ("0.72-0.82", ["0.72", "0.82"]),
    ],
)  # fmt: skip
def test_the_abstract_reads_the_number_a_space_was_left_out_of(atom: str, parts: list) -> None:
    """The author's Abstract typed its numbers against their words (2026-11-10). Each
    number of such an atom is read, a label's and the estimate's before it alike; an
    ordinal with its own suffix before a word a rank takes gives none; any other atom with
    letters is read whole (round 1 of #613: "312students" was taken for an ordinal and
    passed unread, and "45%(95%CI:40-50%)" lost its 45%)."""
    from manuscript_guard.auditing.abstract import printed_parts

    assert printed_parts(atom) == parts


#: The shape of a genetics preprint of the real-paper corpus (pharm-epi, 2026-11-11): its
#: Abstract names its data release, its GWAS, a variant and its chromosome by identifiers
#: the Methods print again, one with a stop after it and one in brackets.
_IDENTIFIED = (
    "# A study\n\n## Abstract\n\nWe used GTEx v8 and the GWAS ieu-a-1185, and rs75015950 on "
    "chr15 led, beside MPL-9 and K-12 here.\n\n## Methods\n\nWe used GTEx v8. Variant "
    "rs75015950 lies on chr15. The GWAS (ieu-a-1185) was read, with MPL-9 and [K-12].\n\n"
    "## Results\n\nIt was so.\n"
)


def _abstract_of(tmp_path: Path, text: str, suffix: str = ".md"):
    paper = tmp_path / f"paper{suffix}"
    paper.write_text(text, encoding="utf-8")
    read = audit([paper], None).abstract
    assert read is not None and read.compared, text
    return read


def test_an_identifier_of_the_abstract_is_found_where_the_methods_print_it(
    tmp_path: Path,
) -> None:
    """An atom with letters is read whole, and was looked for among the bare numbers only:
    "v8", "rs75015950" and "chr15" beside the same words in the Methods were each not
    found (pharm-epi of the real-paper corpus). Each is found now as printed, a whole word
    there, its stop and brackets aside."""
    read = _abstract_of(tmp_path, _IDENTIFIED)
    assert [c.text for c in read.not_found] == [], [c.text for c in read.not_found]
    assert {"v8", "rs75015950", "chr15", "ieu-a-1185", "MPL-9", "K-12"} <= {
        c.text for c in read.found}, [c.text for c in read.found]  # fmt: skip


def test_an_identifier_is_not_found_by_its_digits_nor_outside_what_the_paper_reports(
    tmp_path: Path,
) -> None:
    """An identifier is found only as printed: "rs4242" is not found where the Methods give
    4242 alone, nor "rs1101" where only the Discussion gives it; nor is a number found as a
    rounding of an identifier's, or as a word: 7.25 is not found beside "v7.3"."""
    text = (
        "# A study\n\n## Abstract\n\nVariant rs4242 and rs1101 gave 7.25 here.\n\n"
        "## Methods\n\nIt was 4242 then, with v7.3.\n\n## Results\n\nIt was so.\n\n"
        "## Discussion\n\nWe saw rs1101.\n"
    )
    read = _abstract_of(tmp_path, text)
    assert sorted(c.text for c in read.not_found) == ["7.25", "rs1101", "rs4242"], [
        c.text for c in read.not_found]  # fmt: skip
    assert read.found == [] and read.rounded == []


@pytest.mark.parametrize("written", [
    "*rs75015950*", "_rs75015950_", "**rs75015950**", "\N{LEFT DOUBLE QUOTATION MARK}"
    "rs75015950\N{RIGHT DOUBLE QUOTATION MARK}", '"rs75015950"', "'rs75015950'",
    "rs75015950\N{RIGHT SINGLE QUOTATION MARK}s", "rs75015950's", "rs75015950:1234",
    "(*rs75015950*).",
])  # fmt: skip
def test_an_identifier_is_found_in_emphasis_quotes_a_possessive_or_before_a_colon(
    tmp_path: Path, written: str
) -> None:
    """The text the Abstract is held to keeps a Markdown paper's emphasis marks, and a word
    may be quoted, possessive, or a chromosome's before its position, "chr15:1234": the
    identifier is the word without them (round 1 of #624)."""
    text = (f"# A study\n\n## Abstract\n\nThe variant rs75015950 led here.\n\n## Methods\n\n"
            f"Variant {written} lies there.\n\n## Results\n\nIt was so.\n")  # fmt: skip
    read = _abstract_of(tmp_path, text)
    assert [c.text for c in read.found] == ["rs75015950"], [c.text for c in read.not_found]


def test_an_abstract_s_identifier_with_a_colon_is_found_whole(tmp_path: Path) -> None:
    """"chr15:1234" in the Abstract is read whole, and found where the Methods print it."""
    text = ("# A study\n\n## Abstract\n\nIt lies at chr15:1234 here.\n\n## Methods\n\nIt lies "
            "at chr15:1234.\n\n## Results\n\nIt was so.\n")  # fmt: skip
    assert [c.text for c in _abstract_of(tmp_path, text).found] == ["chr15:1234"]


def test_a_method_subsection_of_the_results_and_discussion_is_no_methods(
    tmp_path: Path,
) -> None:
    """Round 1 of #624: with "method" read anywhere in a title, "Performance of the proposed
    method" under "Results and discussion" was a Methods, the Results over it no longer the
    Results, and the Abstract was not compared, where main compared it."""
    text = ("# Abstract\n\nIt was 41.7.\n\n# Materials and methods\n\n# Results and "
            "discussion\n\nIt was 41.7.\n\n## Performance of the proposed method\n\nFine.\n")
    read = _abstract_of(tmp_path, text)
    assert read.matched == 1 and read.not_found == []


@pytest.mark.parametrize(("title", "methods"), [
    ("Method", True), ("2. Method", True), ("**3. Method**", True), ("METHOD", True),
    ("Methodology", True), ("Materials and Method", True), ("Material and method", True),
    ("Method and materials", True), ("Method:", True),
    # As main read them: the plural anywhere.
    ("Statistical methods", True), ("eMethods 1", True), ("Limitations of existing methods",
                                                          True),
    ("Performance of the proposed method", False), ("A method for signal detection", False),
    ("Proposed method", False), ("Methodological notes", False), ("Our methodology", False),
])  # fmt: skip
def test_the_singular_method_names_the_methods_only_as_the_whole_title(
    title: str, methods: bool
) -> None:
    from manuscript_guard.text.section_names import names_methods

    assert names_methods(title) is methods


@pytest.mark.parametrize("title", ["Method", "3. Method", "Methodology", "Materials and method"])
@pytest.mark.parametrize("suffix", [".md", ".tex"])
def test_a_number_of_the_abstract_is_found_under_a_method_heading(
    tmp_path: Path, title: str, suffix: str
) -> None:
    """A machine-learning paper of the real-paper corpus (cs-lg, 2026-11-11) titles its
    Methods "Method", as APA does: a heading without "methods" was no Methods, and the
    Abstract's numbers reported there were each not found."""
    if suffix == ".md":
        text = (f"# A study\n\n## Abstract\n\nIt has 9.2 million weights and ran 5.9 hours."
                f"\n\n## {title}\n\nIt has 9.2 million weights and ran 5.9 hours.\n\n"
                "## Results\n\nIt was so.\n")  # fmt: skip
    else:
        text = ("\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\nIt has 9.2 "
                "million weights and ran 5.9 hours.\n\\end{abstract}\n\\section{"
                f"{title}}}\nIt has 9.2 million weights and ran 5.9 hours.\n\n"
                "\\section{Results}\nIt was so.\n\\end{document}\n")  # fmt: skip
    read = _abstract_of(tmp_path, text, suffix)
    assert read.not_found == [] and read.matched == 2, [c.text for c in read.not_found]


def test_a_number_not_found_says_where_it_was_looked_for(tmp_path: Path, capsys) -> None:
    """The finding said "found nowhere the paper reports", and the Introduction, the
    Discussion and a conclusion are not read for it. It says what was searched, in the
    words of the heading over the list."""
    from manuscript_guard.cli import main

    paper = tmp_path / "paper.md"
    paper.write_text("# A study\n\n## Abstract\n\nIt was 41.7 here.\n\n## Results\n\nIt was "
                     "so.\n\n## Discussion\n\nIt was 41.7 here.\n", encoding="utf-8")  # fmt: skip
    main(["audit", str(paper), "--json"])
    import json

    report = json.loads(capsys.readouterr().out)
    (found,) = [f for f in report["findings"] if f["code"] == "abstract-not-found"]
    assert found["message"] == ("41.7 in the Abstract is not found in the tables or any "
                                "part of the paper but the Introduction and its material, "
                                "the Discussion with its limitations, an interpretation, a "
                                "conclusion or a closing summary, a summary of the paper, the "
                                "title page, the back matter and the notes")  # fmt: skip
    main(["audit", str(paper)])
    assert ("NOT FOUND IN THE TABLES OR ANY PART OF THE PAPER BUT THE INTRODUCTION AND ITS "
            "MATERIAL") in capsys.readouterr().out


def test_an_abstract_number_is_found_in_any_section_but_the_opening_and_the_argument(
    tmp_path: Path,
) -> None:
    """The real-paper corpus (52 preprints, 2026-11-11): a paper that reports a number under
    a section of another name than the Methods or the Results, "Participants", "Study
    design", "Data analysis and results", an appendix, had its Abstract's number said not
    found. Every section is searched now but the Abstract, the Introduction, the Discussion
    and a conclusion; a number only there is still not found."""
    paper = tmp_path / "paper.md"
    paper.write_text(
        "# A study\n\n## Abstract\n\n"
        + "".join(f"It was {value} here.\n\n"
                  for value in ("41.7", "52.3", "63.9", "74.1", "85.6", "96.2", "17.4", "28.8"))
        + "## Introduction\n\nIt was 96.2 before.\n\n## Participants\n\nIt was 41.7 then.\n\n"
        "## Study design\n\n### Sampling\n\nIt was 52.3 then.\n\n"
        "## Data analysis and results\n\nIt was 63.9 then.\n\n## Results\n\nIt was so.\n\n"
        "## Discussion\n\nIt was 17.4 after.\n\n### Limitations\n\nIt was 85.6 after.\n\n"
        "## Conclusions\n\nIt was 28.8 after.\n\n## Appendix\n\nIt was 74.1 then.\n",
        encoding="utf-8",
    )  # fmt: skip
    read = audit([paper], []).abstract
    assert read is not None and read.compared
    assert sorted(c.text for c in read.found) == ["41.7", "52.3", "63.9", "74.1"]
    assert sorted(c.text for c in read.not_found) == ["17.4", "28.8", "85.6", "96.2"]


@pytest.mark.parametrize(("kind", "paper"), [
    ("a summary of the paper", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n"
     "## Author summary\n\nIt was 18.7% here.\n\n## Results\n\nIt was 17.8%.\n"),
    ("an Abstract in another language", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n"
     "## Resumen\n\nFue 18.7% aquí.\n\n## Results\n\nIt was 17.8%.\n"),
    ("the title page under a title beside the Abstract", "# A study of 18.7% of things\n\n"
     "Anne Example, 18.7 Main Street.\n\n# Abstract\n\nIt was 18.7% here.\n\n# Results\n\n"
     "It was 17.8%.\n"),
    ("related work", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n## Related work\n\n"
     "Smith found 18.7%.\n\n## Results\n\nIt was 17.8%.\n"),
    ("prior work", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n## 2. Prior work\n\n"
     "Smith found 18.7%.\n\n## Results\n\nIt was 17.8%.\n"),
    ("key findings", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n## Key findings\n\n"
     "It was 18.7%.\n\n## Results\n\nIt was 17.8%.\n"),
    ("what this study adds", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n"
     "## What this study adds\n\nIt was 18.7%.\n\n## Results\n\nIt was 17.8%.\n"),
    ("a statement", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n## Results\n\nIt was "
     "17.8%.\n\n## Funding\n\nGrant 18.7% of it.\n"),
    ("a footnote under a statement", "# A study\n\n## Abstract\n\nIt was 18.7% here.\n\n"
     "## Results\n\nIt was 17.8%.[^1]\n\n## Acknowledgements\n\nWe thank them.\n\n"
     "[^1]: Smith J. A title of 18.7% of it. Lancet 2019;12:45-67.\n\n## References\n\n"
     "Doe J. BMJ. 2020;1:2.\n"),
])
def test_an_abstract_number_is_not_found_where_the_paper_does_not_report(
    tmp_path: Path, kind: str, paper: str
) -> None:
    """Round 1 of #641: searched wider, the Abstract against Results took a number repeated
    in a summary of the paper, an Abstract in another language, the title page, a section
    of the Introduction's material, a statement or a note for one the paper reports, and a
    stale 18.7% in the Abstract beside the Results' 17.8% was said found."""
    path = tmp_path / "paper.md"
    path.write_text(paper, encoding="utf-8")
    read = audit([path], []).abstract
    assert read is not None and read.compared
    assert [c.text for c in read.not_found] == ["18.7%"], kind


def test_text_over_a_methods_subsection_is_searched(tmp_path: Path) -> None:
    """Round 1 of #641: a "Study design" with its own words and then a "Statistical
    methods" under it was taken for the paper's title written over it, as G8 takes a heading
    over the Methods, and its words were not searched."""
    path = tmp_path / "paper.md"
    path.write_text("# A study\n\n## Abstract\n\nWe enrolled 1,284 adults.\n\n## Study design\n\n"
                    "We enrolled 1,284 adults.\n\n### Statistical methods\n\nWe fitted a model.\n\n"
                    "## Results\n\nIt was so.\n", encoding="utf-8")  # fmt: skip
    read = audit([path], []).abstract
    assert read is not None and read.compared
    assert read.not_found == [] and [c.text for c in read.found] == ["1,284"]
    # Round 2 of #641: a subsection that opens with "Background" is no Introduction, and the
    # section over it no title over the paper.
    path.write_text("# A study\n\n## Abstract\n\nWe enrolled 1,284 adults.\n\n## Participants"
                    "\n\nWe enrolled 1,284 adults.\n\n### Background characteristics\n\nThey "
                    "were old.\n\n## Results\n\nIt was so.\n", encoding="utf-8")  # fmt: skip
    read = audit([path], []).abstract
    assert read.not_found == [] and [c.text for c in read.found] == ["1,284"]


def test_a_latex_footnote_under_the_results_is_searched(tmp_path: Path) -> None:
    """A known limit (DESIGN.md, "Known gaps"): a LaTeX paper's footnote is printed in its
    sentence, and a number only a footnote under the Results gives is found."""
    paper = tmp_path / "paper.tex"
    paper.write_text("\\documentclass{article}\n\\begin{document}\n\\begin{abstract}\nWe "
                     "followed 45 patients.\n\\end{abstract}\n\\section{Results}\nWe followed "
                     "54 patients.\\footnote{Smith J. Lancet 2019;12:45-67.}\n"
                     "\\end{document}\n", encoding="utf-8")  # fmt: skip
    read = audit([paper], []).abstract
    assert read is not None and read.compared and read.not_found == []


#: The shape of tex-qbio-pe-A1 (decision 17, 2026-11-14): LaTeXTemplates' Stylish Article,
#: whose class defines `\Abstract` and prints it in its title, and the paper's abstract
#: written as `\Abstract{...}` in its preamble.
_STYLISH_CLASS = (
    "@NeedsTeXFormat{LaTeX2e}\n@ProvidesClass{stylish}\n@LoadClass{article}\n"
    "@newcommand{@Abstract}[1]{@def@@Abstract{#1}}\n"
    "@renewcommand{@@maketitle}{{@textbf{@abstractname}@@Abstract}}\n"
)
_STYLISH_PAPER = (
    "@documentclass{stylish}\n@title{A model}\n"
    "@Abstract{We followed 45 patients for 12 months.}\n@begin{document}\n@maketitle\n"
    "@section{Introduction}\nIt matters.\n@section{Results}\nWe followed 54 patients for 12 "
    "months.\n@end{document}\n"
)


def test_a_template_s_abstract_command_has_the_abstract_compared(tmp_path: Path) -> None:
    """Decision 17 (tex-qbio-pe-A1): a class that defines `\\Abstract` and prints what it is
    given, the paper's abstract written in it. The audit said no file had a heading that names
    the Abstract; it now compares it with the Results, and finds 45 nowhere they report."""
    (tmp_path / "stylish.cls").write_text(_STYLISH_CLASS.replace("@", chr(92)), encoding="utf-8")
    paper = tmp_path / "paper.tex"
    paper.write_text(_STYLISH_PAPER.replace("@", chr(92)), encoding="utf-8")
    read = audit([paper], []).abstract
    assert read is not None and read.compared
    assert [c.text for c in read.not_found] == ["45"] and [c.text for c in read.found] == ["12"]


#: A paper whose words G14 asks a project to set paper.yaml for: abbreviations used and not
#: defined, one word in British spelling and six in American, enough for a paper declared
#: British to be told it is not (`spelling.MANY`), and a name written as code writes it.
_PROJECT_ASKS = (
    "# Methods\n\nThe QR codes were scanned by the CHU staff. Their behaviour was recorded, "
    "and the color, the center and the program were noted, as the analyzed data show. The "
    "gray files were labeled, with the favor, the honor and the flavor of each. The "
    "hr_adj_main model was fitted.\n"
)


def _said(run) -> list[str]:
    """What G14 said, the one finding on the short forms left undefined and the warning on
    each form it stands for (`auditing.undefined`)."""
    each = [warning for finding in run.language for _form, warning in getattr(finding, "forms", ())]
    return [text for finding in (*run.language, *each)
            for text in (finding.message, finding.hint or "")]  # fmt: skip


def _found(run) -> set[tuple[str, str]]:
    """Each of G14's findings by its code and the word its message opens with, a short form
    left undefined by its code and the form."""
    return {(f.code, form) for f in run.language for form, _warning in getattr(f, "forms", ())} | {
        (f.code, f.message.split()[0]) for f in run.language if not getattr(f, "forms", ())}


def test_an_audit_says_its_own_settings_where_a_gate_says_paper_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A paper audited alone has no paper.yaml, so a hint that says to list a word under
    `language:` there, or to set `english_variant:`, is said as the page's setting and the
    command line's flag (the author's audit, 2026-11-10). Each pattern of `_FOR_AN_AUDIT`
    matches what G14 writes, undeclared and declared, so a gate reworded under it is caught."""
    from manuscript_guard.auditing import gates

    paper = tmp_path / "paper.md"
    paper.write_text(_PROJECT_ASKS, encoding="utf-8")
    said = [*_said(gates.run_gates(paper)), *_said(gates.run_gates(paper, english="british"))]
    assert said and not [text for text in said if "paper.yaml" in text], said
    assert any("--known" in text for text in said) and any("--english" in text for text in said)
    monkeypatch.setattr(gates, "for_an_audit", lambda text: text)
    raw = [*_said(gates.run_gates(paper)), *_said(gates.run_gates(paper, english="british"))]
    for pattern, _say in gates._FOR_AN_AUDIT:
        assert any(pattern.search(text) for text in raw), pattern.pattern
    # The summary's name for each kind is the audit's own too.
    from manuscript_guard.auditing.summary import KINDS

    assert not [name for name in KINDS.values() if "paper.yaml" in name]


def test_known_words_are_neither_undefined_nor_misspelt(tmp_path: Path) -> None:
    """`--known` lists the words the paper's readers know: an institution's acronym, a
    field's spelling and a name written as code writes it, which the code-name hint tells
    the reader to give it, are then not reported; the rest still is."""
    from manuscript_guard.auditing.gates import run_gates

    paper = tmp_path / "paper.md"
    paper.write_text(_PROJECT_ASKS, encoding="utf-8")
    run = run_gates(paper)
    found = run.language
    before = _found(run)
    known = ("CHU", "behaviour", "hr_adj_main")
    after = _found(run_gates(paper, known=known))
    assert ("abbreviation-undefined", "CHU") in before
    assert ("abbreviation-undefined", "CHU") not in after
    assert ("abbreviation-undefined", "QR") in after
    assert any(word == "'behaviour'" for _code, word in before)
    assert not any(word == "'behaviour'" for _code, word in after)
    assert [f for f in found if f.code == "code-name-in-prose" and "hr_adj_main" in f.message]
    assert not [code for code, _word in after if code == "code-name-in-prose"]


def test_a_known_word_with_a_stop_inside_it_is_matched(tmp_path: Path) -> None:
    """G14 reads "L.AS" whole (#612), so `--known L.AS` holds it (#615): a gap closed when
    both merged (DESIGN.md, "Closed since")."""
    from manuscript_guard.auditing.gates import run_gates

    paper = tmp_path / "paper.md"
    paper.write_text("# Methods\n\nStudents of L.AS were enrolled. The L.AS track was new.\n",
                     encoding="utf-8")  # fmt: skip
    assert ("abbreviation-undefined", "L.AS") in _found(run_gates(paper))
    assert not run_gates(paper, known=("L.AS",)).language


#: The shape of the real-paper corpus's papers whose Abstract was not compared for want of a
#: Results heading: tex-astro-ga-A2 ("Numerical Results"), tex-cs-lg-A1 ("Experiments and
#: Results") and tex-stat-ap-B1 ("Empirical analysis"), 2026-11-13.
_RESULTS_ELSEWHERE = (
    "@documentclass{article}\n@begin{document}\n@begin{abstract}\n"
    "The OR was 1.52 (95@% CI 1.21--1.89).\n@end{abstract}\n@section{Introduction}\n"
    "It matters.\n@section{Model}\nWe fit it.\n@section{HEADING}\n"
    "The OR was 1.52 (95@% CI 1.21--1.89).\n@section{Conclusions}\nIt held.\n@end{document}\n"
)


@pytest.mark.parametrize("heading", ["Numerical Results", "Experiments and Results",
                                     "Empirical analysis", "4. Experiments", "Evaluation",
                                     "Experiments @& Results"])
def test_a_heading_that_is_the_results_by_another_name_has_the_abstract_compared(
    tmp_path: Path, heading: str
) -> None:
    """Basile, 2026-11-13: a heading whose whole title is one of the names the Results go by
    in machine learning, statistics and astronomy is the Results to the Abstract against
    Results, and the Abstract is held to what it reports."""
    paper = tmp_path / "paper.tex"
    paper.write_text(_RESULTS_ELSEWHERE.replace("HEADING", heading).replace("@", chr(92)),
                     encoding="utf-8")  # fmt: skip
    read = audit([paper], []).abstract
    assert read is not None and read.compared and read.matched == read.numbers > 0, heading


@pytest.mark.parametrize("heading", ["Analysis", "Data analysis", "Statistical analysis",
                                     "Experimental setup", "Experiments on synthetic data",
                                     "Simulation studies"])
def test_a_heading_that_only_resembles_the_results_leaves_the_abstract_uncompared(
    tmp_path: Path, heading: str
) -> None:
    """A title that is none of those names whole, or one as often the Methods' as the
    Results', is no Results: the Abstract is not compared, the comparison does not fall back
    to the whole body, and the reason names the headings that would have been read."""
    from manuscript_guard.auditing.abstract import RESULTS_LIKE

    paper = tmp_path / "paper.tex"
    paper.write_text(_RESULTS_ELSEWHERE.replace("HEADING", heading).replace("@", chr(92)),
                     encoding="utf-8")  # fmt: skip
    read = audit([paper], []).abstract
    assert read is not None and not read.compared, heading
    assert all(name in read.why_not.lower() for name in RESULTS_LIKE), read.why_not


@pytest.mark.parametrize(("heading", "compared"), [
    ("## Methods\n\n### Evaluation", False), ("## Methods\n\n### Experiments", False),
    ("## Methods\n\n### Evaluation\n\nWe judged it so.\n\n### Limitations", False),
    ("## Method\n\n### Evaluation", False), ("## Materials and method\n\n### Experiments", False),
    ("## (3) Methods\n\n### Evaluation", False), ("## A. Methods\n\n### Evaluation", False),
    ("## Study design\n\n### Experiments", False),
    ("## Methods\n\n### Background\n\nIt was.\n\n### Evaluation", False),
    ("## Methods\n\n### Discussion of assumptions\n\nIt was.\n\n### Evaluation", False),
    ("## Methods\n\n### Simulation results", True),
    ("## Comparison with existing methods\n\n### Simulation results", True),
    ("## Comparison with existing methods\n\n### Experiments", True),
])  # fmt: skip
def test_a_results_name_under_the_methods_leaves_the_abstract_uncompared(
    tmp_path: Path, heading: str, compared: bool
) -> None:
    """Rounds 1 and 2 of #672: a heading of the list under a heading whose whole title names
    the Methods is a part of the set-up, as "### Evaluation" of how a model was judged,
    unless its name says "results"; under "Comparison with existing methods" it counts."""
    paper = tmp_path / "paper.md"
    paper.write_text(f"# A study\n\n## Abstract\n\nThe value was 812.5 here.\n\n{heading}\n\n"
                     "We judged it so.\n\n## Outcomes in context\n\nIt was 812.5 then.\n",
                     encoding="utf-8")  # fmt: skip
    read = audit([paper], []).abstract
    assert read is not None and read.compared == compared, heading


def test_a_paper_s_title_naming_methods_is_no_methods_over_a_results_name(
    tmp_path: Path,
) -> None:
    """Round 3 of #672: a paper's title written as a heading over the whole paper, "Methods
    and algorithms for robust estimation", is no Methods, since an Introduction stands under
    it: "## Experiments" under it is the Results, and the Abstract is compared."""
    paper = tmp_path / "paper.md"
    paper.write_text("# Methods and algorithms for robust estimation\n\n## Abstract\n\n"
                     "The value was 812.5 here.\n\n## Introduction\n\nIt matters.\n\n"
                     "## Experiments\n\nIt was 812.5 then.\n\n## Discussion\n\nIt was so.\n",
                     encoding="utf-8")  # fmt: skip
    read = audit([paper], []).abstract
    assert read is not None and read.compared
