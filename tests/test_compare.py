"""`compare OLD NEW`: two versions of a manuscript side by side, for an editor or a referee.

Each part of the comparison is held to what it says on small versions written here: the
sections, the tables cell by cell, the figures, the numbers, the claims, v2's audit and its
marks, the response letter's quotations and what it names, and the referee's comments. The
generated letters are in `tests/test_properties.py`.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.comparing import NOTICE, differences, letters
from manuscript_guard.comparing.report import NEW_IN_V2, STOOD_IN_V1, compare, render
from manuscript_guard.comparing.versions import Unreadable, markdown_version, read_version

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def tex(text: str) -> str:
    """LaTeX written with `!` for each backslash."""
    return text.replace("!", chr(92))


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def version(text: str, name: str = "v.md"):
    return markdown_version(Path(name), text)


def codes(found) -> list[tuple[str, str]]:
    return [(item.code, item.message) for item in found]


# ---------------------------------------------------------------------------- sections

OLD_SECTIONS = """# Introduction

Drugs harm the liver.

# Methods

We counted the reports.

# Results

There were many.

# Limitations

Few.
"""
NEW_SECTIONS = """# Introduction

Drugs harm the liver.

# Results

There were many.

# 2. Methods

We counted the reports twice.

# Funding

None.
"""


def test_sections_are_matched_by_title_and_said_same_changed_moved_new_or_gone() -> None:
    found = {item.message.split(":")[0].split(" is ")[0]: item
             for item in differences.sections(version(OLD_SECTIONS), version(NEW_SECTIONS))}
    assert found["the section 'Introduction'"].code == "section-same"
    # A number before a title is no part of it; of Methods and Results, one is out of order.
    moved = {found["the section 'Methods'"].code, found["the section 'Results'"].code}
    assert "section-moved" in moved
    assert "changed: 4 words in v1, 5 in v2" in found["the section 'Methods'"].message
    assert found["the section 'Funding'"].code == "section-new"
    assert found["the section 'Limitations'"].code == "section-gone"
    assert found["the section 'Limitations'"].line == 13


# ------------------------------------------------------------------------------ tables

OLD_TABLES = """# Results

Table 1. Patients by group

| Group | n |
|---|---|
| A | 10 |
| B | 20 |

Table 2. Doses

| Dose | Reports |
|---|---|
| Low | 3 |

Supplementary Table 1. Sites

| Site | n |
|---|---|
| North | 5 |
"""
NEW_TABLES = """# Results

Table 1. Patients by group

| Group | n |
|---|---|
| A | 11 |
| C | 4 |

Table 3. Doses

| Dose | Reports |
|---|---|
| Low | 3 |

Table S1. Sites

| Site | n |
|---|---|
| North | 5 |
"""


def test_tables_are_matched_by_label_and_compared_cell_by_cell() -> None:
    found = differences.tables(version(OLD_TABLES), version(NEW_TABLES))
    said = [item.message for item in found]
    assert "Table 1, row 'A', column 'n': '10' in v1, '11' in v2" in said
    assert "Table 1: the row 'C' is new in v2" in said
    assert "Table 1: the row 'B' is gone from v2" in said
    # "Supplementary Table 1" and "Table S1" are one table, the same cell by cell.
    assert any(m.startswith("Table S1: the same in both versions") for m in said)
    # A table renumbered is one gone and one new (DESIGN.md, Known gaps).
    assert "Table 2 is gone from v2" in said and "Table 3 is new in v2" in said


def test_a_caption_changed_and_a_figure_are_said() -> None:
    old = version("Table 1. Patients\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                  "Figure 1. Flow of the reports.\n\n![Figure 2. Doses](f2.png)\n")
    new = version("Table 1. Patients included\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                  "Figure 1. Flow of the reports.\n")
    said = [item.message for item in differences.tables(old, new)]
    assert said == ["Table 1: its caption changed: 'Patients' in v1, 'Patients included' in v2"]
    figures = [item.message for item in differences.figures(old, new)]
    assert figures == [
        "Figure 1: its caption is the same in both versions (its picture is not compared)",
        "Figure 2 is gone from v2",
    ]


# ----------------------------------------------------------------------------- numbers

OLD_PROSE = """# Methods

We included 412 patients from two centres [@lee2019].

The oldest was 99 years old.

# Discussion

Use may increase the risk of injury.
"""
NEW_PROSE = """# Methods

We included 415 patients from two centres [@lee2020].

# Discussion

Use increases the risk of injury. Seven were lost, 7 in all.
"""


def test_numbers_and_citations_are_changed_gone_or_new_where_they_stand() -> None:
    found = codes(differences.numbers(version(OLD_PROSE), version(NEW_PROSE)))
    assert ("fact-changed", "'412' on line 3 of v1 is '415' in v2") in found
    assert ("fact-changed", "@lee2019 on line 3 of v1 is @lee2020 in v2") in found
    assert ("fact-gone", "'99' is gone: it stood on line 5 of v1") in found
    assert ("fact-new", "'7' is new in v2") in found
    assert len(found) == 4


def test_a_table_s_numbers_are_left_to_the_table() -> None:
    assert differences.numbers(version(OLD_TABLES), version(NEW_TABLES)) == []


def test_a_claim_made_stronger_is_said_against_v1() -> None:
    (moved,) = differences.claim_moves(version(OLD_PROSE), version(NEW_PROSE))
    assert moved.code == "claim-stronger" and moved.severity == "warn"
    # The sentence and the one added after it are read together, as `reworded` reads them.
    assert moved.message == "these sentences claim more than they did in v1: 'may' is gone"
    assert moved.line == 7


# ------------------------------------------------------------------------ the letter

OLD_PAPER = """# Methods

We included 412 patients from two centres. Odds ratios were computed by logistic regression.

# Results

Of 412 patients, 37 developed hepatic injury.
"""
NEW_PAPER = """# Methods

We included 415 patients from three centres. Odds ratios were computed by logistic regression.

# Results

Of 415 patients, 37 developed hepatic injury.
"""
LETTER = """We now write \N{LEFT DOUBLE QUOTATION MARK}We included 415 patients from three
centres\N{RIGHT DOUBLE QUOTATION MARK} in the Methods.

We changed "Of 412 patients, 37 developed hepatic injury" in the Results.

We added "Odds ratios were computed by logistic regression" as asked.

> The reviewer\N{RIGHT SINGLE QUOTATION MARK}s own words are quoted here in full.

We call it "a strong finding" and "this sentence is in no version at all".
"""


def test_each_quotation_of_the_letter_is_held_to_both_versions() -> None:
    held = [(quote.line, quote.block, outcome)
            for quote, outcome in letters.held(LETTER, OLD_PAPER, NEW_PAPER)]  # fmt: skip
    assert held == [
        (1, False, letters.NEW_AS_QUOTED),
        (4, False, letters.FIRST_VERSION),
        (6, False, letters.NOT_NEW),
        (8, True, letters.NEITHER),
        # "a strong finding" is three words, and not read.
        (10, False, letters.NEITHER),
    ]
    mine = "I wrote: The reviewer's own words are quoted here in full."
    assert [outcome for _q, outcome in letters.held(LETTER, OLD_PAPER, NEW_PAPER, mine)][3] == (
        letters.YOURS)  # fmt: skip


def test_what_the_letter_names_is_a_fact_with_no_verdict(tmp_path: Path) -> None:
    old = version(OLD_PAPER + "\nTable 1. Sites\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    new = version(NEW_PAPER + "\nTable 1. Sites\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    letter = ("Table 1 is as it was. The Methods were revised.\n\nSee Figure 4 and "
              "supplementary table 2.\n")  # fmt: skip
    found = {item.message for item in letters.letter_items(tmp_path / "l.md", letter, old, new)}
    assert found == {
        "Table 1, named on line 1: its cells and caption the same in both versions",
        "Methods, named on line 1: its text changed",
        "Figure 4, named on line 3: found in neither version",
        "Table S2, named on line 3: found in neither version",
    }


# ---------------------------------------------------------------------- the comments

MINE = """1. The sentence "We included 412 patients from two centres" is unclear.

2. "Odds ratios were computed by logistic regression" needs a reference.

3) Table 1 should give the sites.

Comment 4: The writing could be tighter.

5. "A passage that the authors never wrote anywhere" is missing.
"""


def test_each_comment_is_matched_only_by_what_it_quotes_or_names(tmp_path: Path) -> None:
    old = version(OLD_PAPER + "\nTable 1. Sites\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    new = version(NEW_PAPER + "\nTable 1. Sites\n\n| a | b |\n|---|---|\n| 1 | 3 |\n")
    found = [(item.code, item.message, item.line)
             for item in letters.comment_items(tmp_path / "mine.md", MINE, old, new)]
    assert found == [
        ("comment-quote-changed", "comment 1: the passage it quotes changed in v2; v2 has "
         "there: 'We included 415 patients from three centres.'", 1),
        ("comment-quote-unchanged", "comment 2: the passage it quotes is unchanged in v2", 3),
        ("comment-named", "comment 3: it names Table 1: its cells and caption changed", 5),
        ("comment-not-matched", "comment 4: not matched: it quotes no passage and names no "
         "table, figure or section; read it", 7),
        ("comment-quote-in-neither", "comment 5: the passage it quotes is not in v1 either, "
         "nor in v2", 9),
    ]  # fmt: skip


def test_a_passage_deleted_whole_is_gone_and_paragraphs_are_comments(tmp_path: Path) -> None:
    old = version("# Results\n\nThe first finding stands. The cohort was small in size.\n")
    new = version("# Results\n\nThe first finding stands.\n")
    mine = "\"The cohort was small in size\" is a limit.\n\nNothing else.\n"
    found = [(item.code, item.message)
             for item in letters.comment_items(tmp_path / "m.md", mine, old, new)]
    assert found == [
        ("comment-quote-gone", "paragraph 1: the passage it quotes is gone from v2"),
        ("comment-not-matched", "paragraph 2: not matched: it quotes no passage and names no "
         "table, figure or section; read it"),
    ]  # fmt: skip


# ----------------------------------------------------------------- the whole command

ABSTRACT_OLD = """# Abstract

The odds ratio was 4.4 in the cohort.

# Results

Of 412 patients, 37 developed hepatic injury.
"""
ABSTRACT_NEW = """# Abstract

The odds ratio was 4.4 in the cohort. The hazard ratio was 6.6 in the cohort.

# Results

Of 412 patients, 37 developed hepatic injury.
"""


def test_v2_is_audited_and_each_finding_marked_by_its_sentence(tmp_path: Path) -> None:
    old = write(tmp_path, "v1.md", ABSTRACT_OLD)
    new = write(tmp_path, "v2.md", ABSTRACT_NEW)
    found = compare(old, new)
    marks = {item.message.split(": ", 1)[1]: mark for item, mark in found.items
             if item.code == "abstract-not-found"}  # fmt: skip
    assert marks == {
        "4.4 in the Abstract is found nowhere the paper reports": STOOD_IN_V1,
        "6.6 in the Abstract is found nowhere the paper reports": NEW_IN_V2,
    }
    assert all(not item.counted for item, _mark in found.items)


def test_the_command_reports_and_says_the_notice(tmp_path: Path, capsys) -> None:
    old = write(tmp_path, "v1.md", OLD_PAPER)
    new = write(tmp_path, "v2.md", NEW_PAPER)
    letter = write(tmp_path, "letter.md", LETTER)
    mine = write(tmp_path, "mine.md", MINE)
    argv = ["compare", str(old), str(new), "--response", str(letter), "--comments", str(mine)]
    assert main(argv) == 0
    out, err = capsys.readouterr()
    assert NOTICE in err
    for section in ("Sections", "Numbers, citations and bindings", "Response letter",
                    "Your comments", "v2 audited"):  # fmt: skip
        assert f"\n{section}" in out, section
    assert "letter line 4: the quotation: quotes the first version" in out
    # It never says a comment was answered.
    assert "address" not in out.lower() and "answered" not in out.lower()
    assert main([*argv, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["counts"]["facts_changed"] == 2
    assert {"section", "gate", "code", "severity", "counted", "message", "path", "line",
            "context", "hint", "mark"} <= set(data["findings"][0])  # fmt: skip


def test_the_report_goes_to_a_new_file_only(tmp_path: Path, capsys) -> None:
    old = write(tmp_path, "v1.md", OLD_PAPER)
    new = write(tmp_path, "v2.md", NEW_PAPER)
    out = tmp_path / "report.txt"
    assert main(["compare", str(old), str(new), "--out", str(out)]) == 0
    said = capsys.readouterr().out
    assert said.count("\n") == 1 and str(out) in said
    assert out.read_text(encoding="utf-8").startswith("Compared ")
    out.write_text("kept", encoding="utf-8")
    assert main(["compare", str(old), str(new), "--out", str(out), "--json"]) == 2
    assert "is there already" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "kept"


@pytest.mark.parametrize(
    ("name", "said"),
    [
        ("v2.pdf", "is a PDF, which compare does not read yet"),
        ("missing.md", "does not exist"),
        ("folder", "is a folder"),
        ("v2.rtf", "is not a .docx, .md, .txt or .tex"),
        ("empty.md", "holds no text to compare"),
    ],
)
def test_a_version_that_cannot_be_read_is_refused(tmp_path: Path, name: str, said: str,
                                                  capsys) -> None:  # fmt: skip
    old = write(tmp_path, "v1.md", OLD_PAPER)
    (tmp_path / "folder").mkdir()
    write(tmp_path, "v2.pdf", "%PDF-1.4")
    write(tmp_path, "v2.rtf", "{\\rtf1}")
    write(tmp_path, "empty.md", "\n\n12\n")
    assert main(["compare", str(old), str(tmp_path / name)]) == 2
    assert said in capsys.readouterr().err
    assert main(["compare", str(old), str(tmp_path / name), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_a_letter_that_cannot_be_read_is_refused(tmp_path: Path, capsys) -> None:
    old = write(tmp_path, "v1.md", OLD_PAPER)
    assert main(["compare", str(old), str(old), "--response", str(tmp_path / "no.md")]) == 2
    assert "the letter" in capsys.readouterr().err


# ------------------------------------------------------------------ Word and LaTeX


def _docx(path: Path, paragraphs: list[tuple[str, str]], table: list[list[str]]) -> Path:
    """A .docx of (style, text) paragraphs, the table after the paragraph styled "table"."""
    styles = (f"<w:styles {NS}><w:style w:type='paragraph' w:styleId='Heading1'>"
              "<w:name w:val='heading 1'/></w:style></w:styles>")  # fmt: skip
    rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>"
                                      for cell in row) + "</w:tr>" for row in table)
    body = ""
    for style, text in paragraphs:
        styled = "<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>" if style == "heading" else ""
        body += f"<w:p>{styled}<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"
        if style == "table":
            body += f"<w:tbl>{rows}</w:tbl>"
    document = f"<?xml version='1.0'?><w:document {NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
    return path


def test_a_docx_is_read_as_audit_reads_one(tmp_path: Path) -> None:
    def paper(name: str, n: str, cell: str):
        paragraphs = [("heading", "Methods"), ("", f"We included {n} patients."),
                      ("heading", "Results"), ("table", "Table 1. Patients by site"),
                      ("", "Figure 1. The flow of patients.")]  # fmt: skip
        return read_version(_docx(tmp_path / name, paragraphs, [["Site", "n"], ["A", cell]]))

    old, new = paper("v1.docx", "412", "10"), paper("v2.docx", "415", "11")
    assert [h.title for h in new.sections] == ["Methods", "Results"]
    assert [(t.label, t.caption) for t in new.tables] == [("Table 1", "Patients by site")]
    assert [f.label for f in new.figures] == ["Figure 1"]
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1, row 'A', column 'n': '10' in v1, '11' in v2"]
    (changed,) = differences.numbers(old, new)
    # The heading is no part of the sentence after it, and the line is the paragraph's, as
    # `audit` counts them: a .docx's body opens with an empty line.
    assert changed.message == "'412' on line 3 of v1 is '415' in v2"
    assert changed.context == "We included 415 patients."


LATEX_MAIN = tex(
    "!documentclass{article}\n"
    "!begin{document}\n"
    "!section{Methods}\n"
    "We included NUMBER patients.\n"
    "!input{results}\n"
    "!end{document}\n"
)
LATEX_RESULTS = tex(
    "!section{Results}\n"
    "Of NUMBER patients, 37 had an injury.\n"
    "!begin{table}\n"
    "!caption{Patients by site}\n"
    "!begin{tabular}{ll}\n"
    "Site & n !!\n"
    "A & CELL !!\n"
    "!end{tabular}\n"
    "!end{table}\n"
)


def test_a_latex_tree_is_read_and_placed_at_its_files(tmp_path: Path) -> None:
    for name, number, cell in (("v1", "412", "10"), ("v2", "415", "11")):
        write(tmp_path / name, "main.tex", LATEX_MAIN.replace("NUMBER", number))
        write(tmp_path / name, "results.tex",
              LATEX_RESULTS.replace("NUMBER", number).replace("CELL", cell))
    old = read_version(tmp_path / "v1" / "main.tex")
    new = read_version(tmp_path / "v2" / "main.tex")
    assert [h.title for h in new.sections if h.level] == ["Methods", "Results"]
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1, row 'A', column 'n': '10' in v1, '11' in v2"]
    changed = differences.numbers(old, new)
    assert [(item.message, item.path.name, item.line) for item in changed] == [
        ("'412' on line 4 of v1 is '415' in v2", "main.tex", 4),
        ("'412' on results.tex line 2 of v1 is '415' in v2", "results.tex", 2),
    ]


def test_render_names_each_file_by_its_version(tmp_path: Path) -> None:
    old = write(tmp_path, "a/paper.md", OLD_PROSE)
    new = write(tmp_path, "b/paper.md", NEW_PROSE)
    said = render(compare(old, new), tmp_path)
    assert "v2 line 3: '412' on line 3 of v1 is '415' in v2" in said
    assert "v2 line 7: '7' is new in v2" in said
    with pytest.raises(Unreadable):
        compare(old, tmp_path / "b" / "nothing.md")


def test_a_citation_changed_in_a_sentence_otherwise_the_same_is_one_changed() -> None:
    """A sentence's words leave its citations out, so the two sentences stand alike and are
    not among those the texts differ in: the citation changed is paired all the same."""
    old = version("# Results\n\nThe rate was high [@lee2019]. Of 12 sites, 12 reported.\n\n"
                  "The 12 others were closed.\n")
    new = version("# Results\n\nThe rate was high [@kim2021]. Of 12 sites, 12 reported.\n")
    assert codes(differences.numbers(old, new)) == [
        ("fact-changed", "@lee2019 on line 3 of v1 is @kim2021 in v2"),
        # Where it stood in a sentence v2 does not have.
        ("fact-gone", "'12' stood 3 times in v1 and stands twice in v2; on line 5 of v1"),
    ]


# ------------------------------------------------------------ round 1 of the review


def test_a_finding_stands_in_v1_only_where_v1_s_audit_has_it(tmp_path: Path) -> None:
    """A finding on a line that did not change can come from a change elsewhere: v2 changes
    only the Results, and the Abstract's 12% is found nowhere in v2. It is new in v2."""
    old = write(tmp_path, "v1.md", "# Abstract\n\nMortality was 12% in 412 patients.\n\n"
                "# Results\n\nMortality was 12%.\n")
    new = write(tmp_path, "v2.md", "# Abstract\n\nMortality was 12% in 412 patients.\n\n"
                "# Results\n\nMortality was 13%.\n")
    marks = {item.message.split(": ", 1)[1]: mark for item, mark in compare(old, new).items
             if item.code == "abstract-not-found"}  # fmt: skip
    assert marks == {"12% in the Abstract is found nowhere the paper reports": NEW_IN_V2,
                     "412 in the Abstract is found nowhere the paper reports": STOOD_IN_V1}


def _table(header: str, *rows: str) -> str:
    columns = header.count("|") - 1
    return "\n".join(["Table 1. Sites", "", header, "|" + "---|" * columns, *rows, ""])


def test_a_column_inserted_is_said_and_the_others_compared_by_their_headers() -> None:
    old = version(_table("| Site | n | % |", "| North | 10 | 50 |"))
    new = version(_table("| Site | 95% CI | n | % |", "| North | 1.2-3.4 | 10 | 51 |"))
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1: the column '95% CI' is new in v2",
        "Table 1, row 'North', column '%': '50' in v1, '51' in v2",
    ]


def test_columns_reordered_are_paired_by_their_headers() -> None:
    old = version(_table("| Site | n | % |", "| North | 10 | 50 |"))
    new = version(_table("| Site | % | N |", "| North | 50 | 10 |"))
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1: the same in both versions, cell by cell (6 cells)"]


def test_two_headers_alike_but_for_case_stay_two_columns() -> None:
    old = version(_table("| Site | n | N |", "| North | 10 | 200 |"))
    new = version(_table("| Site | N | n |", "| North | 200 | 11 |"))
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1, row 'North', column 'n': '10' in v1, '11' in v2"]


def test_columns_with_no_header_or_one_repeated_are_paired_by_their_place() -> None:
    old = version(_table("| Site | n | n |", "| North | 10 | 20 |"))
    new = version(_table("| Site | n | n |", "| North | 10 | 21 |"))
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1, row 'North', column 'n': '20' in v1, '21' in v2"]


FLOAT = tex("!begin{table}\n!caption{CAPTION}\n!begin{tabular}{ll}\nA & B !!\n"
            "!end{tabular}\n!end{table}\n")


def test_latex_tables_are_numbered_in_the_order_they_print(tmp_path: Path) -> None:
    """A float in a file input before main.tex's own float prints first, and the floats are
    counted as the printed view counts them: a sidewaystable is a table, a float of two
    captions numbers two, and one continued from the last numbers none."""
    write(tmp_path, "main.tex", tex(
        "!documentclass{article}\n!begin{document}\n!section{Results}\nText.\n"
        "!input{results}\n!begin{sidewaystable}!caption{Side}!end{sidewaystable}\n"
        "!begin{table}!caption{First}x!caption{Second}!end{table}\n"
        "!begin{table}!ContinuedFloat!caption{Second, continued}!end{table}\n"
        + FLOAT.replace("CAPTION", "Last") + "!end{document}\n"))  # fmt: skip
    write(tmp_path, "results.tex", FLOAT.replace("CAPTION", "Input"))
    version = read_version(tmp_path / "main.tex")
    assert [(t.label, t.caption) for t in version.tables] == [
        ("Table 1", "Input"), ("Table 2", "Side"), ("Table 3", "First"), ("Table 4", "Second"),
        ("Table 5", "Last"),
    ]
    assert version.notes == ()


def test_tables_the_view_cannot_count_are_not_numbered(tmp_path: Path) -> None:
    """A longtable's caption and a `!captionof` number a table the printed view does not
    count: the version's tables are then given no number, and a note says why."""
    write(tmp_path, "main.tex", tex(
        "!documentclass{article}\n!begin{document}\nText.\n" + FLOAT.replace("CAPTION", "Main")
        + "!begin{longtable}{ll}\n!caption{Long}!!\nA & B !!\n!end{longtable}\n"
        "!end{document}\n"))  # fmt: skip
    version = read_version(tmp_path / "main.tex")
    assert [t.label for t in version.tables] == [None, None]
    assert [t.caption for t in version.tables] == ["Main", "Long"]
    (note,) = version.notes
    assert note.startswith("its tables are not numbered here")


INPUT_FLOAT = tex("!documentclass{article}\n!begin{document}\nText.\n!begin{table}!caption{Doses}"
                  "!input{tab1}!end{table}\n" + FLOAT.replace("CAPTION", "After")
                  + "!end{document}\n")  # fmt: skip
TAB1 = tex("!begin{tabular}{ll}\nDose & n !!\nLow & CELL !!\n!end{tabular}\n")


def test_a_table_s_cells_input_from_another_file_are_its_own(tmp_path: Path) -> None:
    for name, cell in (("v1", "3"), ("v2", "4")):
        write(tmp_path / name, "main.tex", INPUT_FLOAT)
        write(tmp_path / name, "tab1.tex", TAB1.replace("CELL", cell))
    old = read_version(tmp_path / "v1" / "main.tex")
    new = read_version(tmp_path / "v2" / "main.tex")
    assert [(t.label, t.caption) for t in new.tables] == [("Table 1", "Doses"),
                                                          ("Table 2", "After")]
    assert [item.message for item in differences.tables(old, new)] == [
        "Table 1, row 'Low', column 'n': '3' in v1, '4' in v2",
        "Table 2: the same in both versions, cell by cell (2 cells)",
    ]
    assert letters.status("Table 1", old, new) == "its cells and caption changed"


def test_a_caption_input_from_another_file_numbers_its_float(tmp_path: Path) -> None:
    write(tmp_path, "main.tex", INPUT_FLOAT.replace(tex("!caption{Doses}"), ""))
    write(tmp_path, "tab1.tex", tex("!caption{Doses}\n") + TAB1.replace("CELL", "3"))
    tables = read_version(tmp_path / "main.tex").tables
    assert [(t.label, t.caption, t.rows) for t in tables] == [
        ("Table 1", "Doses", (("Dose", "n"), ("Low", "3"))), ("Table 2", "After", (("A", "B"),)),
    ]


def test_a_table_whose_input_is_not_read_is_never_the_same(tmp_path: Path) -> None:
    for name in ("v1", "v2"):
        write(tmp_path / name, "main.tex", INPUT_FLOAT)
    old = read_version(tmp_path / "v1" / "main.tex")
    new = read_version(tmp_path / "v2" / "main.tex")
    said = [item.message for item in differences.tables(old, new)]
    assert said[0] == ("Table 1: its cells in v1 and v2 were not read: the float there holds "
                       "no one table this reading pairs with its one caption, or a file it "
                       "inputs was not read")  # fmt: skip
    assert letters.status("Table 1", old, new) == "its cells were not read"


def test_a_table_not_read_in_one_version_names_that_version(tmp_path: Path) -> None:
    tabular = "\n!begin{tabular}{ll}\nA & 1 !!\n!end{tabular}\n"
    for name, body in (("v1", "!caption{A}TABULARTABULAR"), ("v2", "!caption{A}TABULAR")):
        write(tmp_path / name, "main.tex", tex(
            "!documentclass{article}\n!begin{document}\nText.\n!begin{table}"
            + body.replace("TABULAR", tabular) + "!end{table}\n!end{document}\n"))  # fmt: skip
    old = read_version(tmp_path / "v1" / "main.tex")
    new = read_version(tmp_path / "v2" / "main.tex")
    (said,) = [i.message for i in differences.tables(old, new) if i.code == "table-not-read"]
    assert said.startswith("Table 1: its cells in v1 were not read")


@pytest.mark.parametrize(
    "body",
    [
        # Two captions and two tabulars: which caption numbers which cannot be told here.
        "!caption{A}TABULAR!caption{B}TABULAR",
        # One caption over two tabulars, as subtables have.
        "!caption{A}TABULARTABULAR",
        # One caption and no tabular: a picture of a table.
        "!caption{A}!includegraphics{t}",
    ],
)
def test_a_float_whose_captions_and_tables_are_not_one_to_one_is_not_read(
    tmp_path: Path, body: str
) -> None:
    tabular = "\n!begin{tabular}{ll}\nA & CELL !!\n!end{tabular}\n"
    for name, cell in (("v1", "1"), ("v2", "2")):
        write(tmp_path / name, "main.tex", tex(
            "!documentclass{article}\n!begin{document}\nText.\n!begin{table}"
            + body.replace("TABULAR", tabular.replace("CELL", cell))
            + "!end{table}\n!end{document}\n"))  # fmt: skip
    old = read_version(tmp_path / "v1" / "main.tex")
    new = read_version(tmp_path / "v2" / "main.tex")
    assert all(not table.read for table in new.tables if table.label)
    said = [item.message for item in differences.tables(old, new)]
    assert not any("the same" in one for one in said), said
    assert all(letters.status(t.label, old, new) == "its cells were not read"
               for t in new.tables if t.label)  # fmt: skip


def test_a_file_two_floats_input_is_read_for_the_first_only(tmp_path: Path) -> None:
    write(tmp_path, "main.tex", tex(
        "!documentclass{article}\n!begin{document}\nText.\n"
        "!begin{table}!caption{One}!input{tab1}!end{table}\n"
        "!begin{table}!caption{Two}!input{tab1}!end{table}\n!end{document}\n"))  # fmt: skip
    write(tmp_path, "tab1.tex", TAB1.replace("CELL", "3"))
    tables = read_version(tmp_path / "main.tex").tables
    assert [(t.label, t.read) for t in tables] == [("Table 1", True), ("Table 2", False)]


def test_a_number_changed_is_paired_with_the_one_in_its_own_sentence() -> None:
    old = version("# Results\n\nA came first. B was 7.\n")
    new = version("# Results\n\nA came first. C was 9. B was 8.\n")
    assert codes(differences.numbers(old, new)) == [
        ("fact-changed", "'7' on line 3 of v1 is '8' in v2"),
        ("fact-new", "'9' is new in v2"),
    ]


def test_a_quotation_matches_only_whole_words_and_numbers() -> None:
    """In curly marks, which a number may close; straight marks, one after a number, are not
    read at all."""
    letter = ("We now say \N{LEFT DOUBLE QUOTATION MARK}the odds ratio was 2.1"
              "\N{RIGHT DOUBLE QUOTATION MARK} and \"5 sites reported a rise\".\n")  # fmt: skip
    old = "Here the odds ratio was 2.15. And 15 sites reported a rise.\n"
    new = "Here the odds ratio was 2.1. And 5 sites reported a rise.\n"
    assert [outcome for _q, outcome in letters.held(letter, old, new)] == [
        letters.NEW_AS_QUOTED, letters.NEW_AS_QUOTED]
    assert [outcome for _q, outcome in letters.held(letter, old, old)] == [
        letters.NEITHER, letters.NEITHER]


@pytest.mark.parametrize(
    "said",
    ["events reported to the U.S. Food and Drug Administration",
     "the cohort seen by Dr. Smith in the clinic", "the counts given in Suppl. Table 2 now"],
)
def test_a_quotation_with_a_stop_inside_is_read(said: str) -> None:
    letter = f'We now write "{said}" in the Methods and "the cohort excluded all children".\n'
    assert [q.quote for q in letters.quotations(letter)] == [
        said, "the cohort excluded all children"]


def test_an_unpaired_straight_mark_reads_none_of_its_paragraph(tmp_path: Path) -> None:
    letter = ('We wrote "the rate fell in all sites and "the cohort grew in size" here.\n\n'
              'Then "the second paragraph is read" alone.\n')  # fmt: skip
    assert [q.quote for q in letters.quotations(letter)] == ["the second paragraph is read"]
    found = letters.letter_items(tmp_path / "l.md", letter, version(OLD_PAPER),
                                 version(NEW_PAPER))  # fmt: skip
    assert [(item.code, item.message, item.line) for item in found][:1] == [
        ("quotation-unpaired", UNPAIRED_NOTE.format("paragraph 1"), 1)]


UNPAIRED_NOTE = ("the straight quotation marks in {} cannot be paired: one has no partner, or "
                 "one follows a number, where it may be an inch's mark or a quotation's end; "
                 "its straight quotations were not read")


@pytest.mark.parametrize(
    "letter",
    [
        'A 5" screen. We now write "the rate fell in all sites" here.\n',
        'We now report "the rate was 12" and "the odds ratio was 2.1" here.\n',
        'A \N{VULGAR FRACTION ONE HALF}" screw was fitted to all of "the rate fell in all sites"'
        ' and a \N{VULGAR FRACTION THREE QUARTERS}" bolt.\n',
    ],
)
def test_a_straight_mark_after_a_number_leaves_its_paragraph_unread(letter: str) -> None:
    assert letters.quotations(letter) == []
    assert letters.unpaired(letter) == [(1, 1)]


def test_a_comment_s_unpaired_mark_is_said_of_the_comment(tmp_path: Path) -> None:
    mine = '1. One.\n\n2. The words "the rate fell were unclear.\n\nMore of it.\n'
    found = [item.message for item in letters.comment_items(tmp_path / "m.md", mine,
                                                               version(OLD_PAPER),
                                                               version(NEW_PAPER))
             if item.code == "quotation-unpaired"]  # fmt: skip
    assert found == ["comment 2: " + UNPAIRED_NOTE.format("this comment")]


def test_a_docx_comments_file_is_a_comment_a_paragraph(tmp_path: Path) -> None:
    """Word numbers a list without writing the numbers into the text, and writes no blank
    paragraph between: each paragraph is a comment."""
    mine = _docx(tmp_path / "mine.docx", [("", "Table 2 should give the sites."),
                                          ("", "The writing is unclear."),
                                          ("", "The aims are vague.")], [])  # fmt: skip
    old = version(OLD_PAPER + "\nTable 2. Sites\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    text = letters.read_text_of(mine, "the comments file")
    found = [(item.code, item.message, item.line)
             for item in letters.comment_items(mine, text, old, old)]
    assert found == [
        ("comment-named", "paragraph 1: it names Table 2: its cells and caption the same in "
         "both versions", 2),
        ("comment-not-matched", "paragraph 2: not matched: it quotes no passage and names no "
         "table, figure or section; read it", 3),
        ("comment-not-matched", "paragraph 3: not matched: it quotes no passage and names no "
         "table, figure or section; read it", 4),
    ]  # fmt: skip


def test_a_finding_whose_line_moved_reads_as_new(tmp_path: Path) -> None:
    """A finding stands in v1 only where v1's says the same word for word: one that names a
    line that moved reads as new, which sends the reader to read it (DESIGN.md, Known gaps);
    masked, a fence at line 10 of v1 and another at line 50 of v2 were one."""
    old = write(tmp_path, "v1.md", "# Abstract\n\nThe odds ratio was 2.1 (95% CI 1.4 to 3.2)."
                "\n\n# Results\n\nThe odds ratio was 2.1 (95% CI 1.5 to 3.2).\n")
    new = write(tmp_path, "v2.md", "# Abstract\n\nThe odds ratio was 2.1 (95% CI 1.4 to 3.2)."
                "\n\n# Results\n\nA new paragraph.\n\n"
                "The odds ratio was 2.1 (95% CI 1.5 to 3.2).\n")
    marks = [mark for item, mark in compare(old, new).items if item.code == "abstract-conflict"]
    assert marks == [NEW_IN_V2]
