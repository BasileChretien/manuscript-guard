"""`audit` holds a paper's tables and figures to the order ICMJE asks for, as G2 holds a
project's, each kind counted by its legends alone (`auditing.displays`; Basile,
2026-11-27, wave B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.auditing import displays
from manuscript_guard.cli import main


def said(text: str, name: str = "main.md") -> displays.Displays:
    return displays.of_files({name: text}, Path("m"))


def codes(read: displays.Displays) -> list[tuple[str, int | None]]:
    return [(f.code, f.line) for f in read.findings]


@pytest.mark.parametrize("legend", [
    "**Table 1.** Baseline", "Table 1. Baseline", "Table 1: Baseline", "Table 1 Baseline",
    "*Table 1.* Baseline", "Table 1 \N{EN DASH} Baseline", "Table 1",
])  # fmt: skip
def test_a_legend_in_each_form_a_paper_sets_one_counts_its_table(legend: str) -> None:
    read = said(f"Patients are in Table 1.\n\n{legend}\n")
    assert read.findings == () and read.notes == () and read.counted == 1, read


@pytest.mark.parametrize("legend", [
    # The corpus run of ea3fc52: Word sets a no-break space between the word and its number,
    # and pandoc writes a legend Word keeps a bookmark at, or links to, with its anchor.
    "Table\N{NO-BREAK SPACE}1", "[]{#_Ref82435516 .anchor}Table 1",
    "[[]{#_Ref89712232 .anchor}Table 1](#_Ref89712232)",
])  # fmt: skip
def test_a_legend_as_word_writes_one_counts_its_table(legend: str) -> None:
    read = said(f"Patients are in Table 1.\n\n{legend}\n")
    assert read.findings == () and read.notes == () and read.counted == 1, read


@pytest.mark.parametrize(("body", "kind"), [
    ("| a |\n|---|\n| 1 |\n\n| b |\n|---|\n| 2 |\n", "tables"),
    ("![](media/image1.png)\n\n![](media/image2.png)\n", "figures"),
])  # fmt: skip
def test_a_file_that_holds_more_of_a_kind_than_its_legends_number_leaves_it_uncounted(
    body: str, kind: str
) -> None:
    """The corpus run of ea3fc52: a legend the check does not read, in a layout table or in
    a picture, leaves the legends one short of the tables or pictures the file holds, and its
    citations would point at nothing. Such a kind is not counted."""
    word = "Table" if kind == "tables" else "Figure"
    read = said(f"In {word} 1 and {word} 2.\n\n{word} 1. A\n\n{body}")
    assert read.findings == () and read.counted == 0, read
    assert len(read.notes) == 1 and f"its legends number 1 {kind[:-1]}" in read.notes[0].message


@pytest.mark.parametrize("legend", [
    "![Figure 1. Flow of patients](media/image1.png)", "Fig. 1. Flow", "Figure 1: Flow",
])  # fmt: skip
def test_a_figure_s_legend_as_a_picture_or_with_fig_counts_its_figure(legend: str) -> None:
    read = said(f"The flow is in Figure 1.\n\n{legend}\n")
    assert read.findings == () and read.notes == () and read.counted == 1, read


@pytest.mark.parametrize("text", [
    # A sentence that opens with a pointer is no legend: it cites the table.
    "Table 1 shows the patients.\n\nTable 2. Outcomes\n",
    # Nor is a pointer that does not open its paragraph.
    "As in\nTable 1. Outcomes go on.\n\nTable 2. Outcomes\n",
])  # fmt: skip
def test_a_sentence_that_opens_with_a_pointer_is_a_citation_and_no_legend(text: str) -> None:
    read = said(text)
    # Table 1's only legend is missing, so the tables are not counted, and nothing is said of
    # them but that.
    assert read.findings == () and read.counted == 0, read
    assert ["not 1 to 1 once each" in note.message for note in read.notes] == [True], read


def test_the_three_findings_each_at_its_place() -> None:
    text = ("Outcomes are in Table 2, patients in Table 1. See also Table 4.\n\n"
            "Table 1. Patients\n\nTable 2. Outcomes\n\nTable 3. Costs\n")
    read = said(text)
    assert codes(read) == [("pointer-to-nothing", 1), ("cited-out-of-order", 1),
                           ("display-not-cited", 7)]  # fmt: skip
    nothing, order, uncited = read.findings
    assert nothing.message == ("'Table 4' points at table 4, and the legends of the paper "
                               "number its tables 1 to 3")  # fmt: skip
    assert order.message == "Table 2 is first cited before table 1"
    assert uncited.message == "Table 3 has its legend in the paper and is cited nowhere in its text"
    assert {f.severity for f in read.findings} == {"warn"}


@pytest.mark.parametrize(("legends", "said_of"), [
    ("Table 1. A\n\nTable 3. B\n", "read 1, 3, not 1 to 2"),
    ("Table 1. A\n\nTable 1. A (continued)\n", "read 1, 1, not 1 to 2"),
    ("Table 2. A\n", "read 2, not 1 to 1"),
])  # fmt: skip
def test_legends_that_do_not_number_a_kind_1_to_n_leave_it_uncounted(
    legends: str, said_of: str
) -> None:
    read = said(f"In Table 1 and Table 2 and Table 3.\n\n{legends}")
    assert read.findings == () and read.counted == 0, read
    assert len(read.notes) == 1 and said_of in read.notes[0].message, read.notes
    assert read.notes[0].subject == "tables"


def test_a_kind_pointed_at_with_no_legend_is_said_not_counted_and_one_with_neither_is_silent(
) -> None:
    read = said("Patients are in Table 1 and the flow in Figure 2.\n\nNo legends here.\n")
    assert read.findings == () and read.counted == 0
    assert [note.subject for note in read.notes] == ["tables", "figures"]
    assert said("Nothing is pointed at.\n").notes == ()


def test_a_pointer_to_the_supplement_is_held_to_the_supplement_s_legends_wherever_given(
) -> None:
    main_text = said("In Table 1, Table S1 and Table S3.\n\nTable 1. Main\n")
    assert codes(main_text) == [] and main_text.to_supplement[0][:2] == ("table", 1)
    supplement = displays.of_files({"supplement.md": "Table S1. A\n\nTable S2. B\n"}, Path("m"))
    found, notes = displays.supplement_findings([main_text, supplement])
    assert [(f.code, f.line) for f in found] == [("pointer-to-nothing", 1)] and notes == []
    assert found[0].message.endswith("the legends of the supplement number its tables 1 to 2")
    # No supplement given: its pointers are not checked, and nothing is said.
    assert displays.supplement_findings([main_text]) == ([], [])
    # A supplement whose legends do not number it 1 to m is said not counted.
    gapped = displays.of_files({"s.md": "Table S1. A\n\nTable S3. B\n"}, Path("m"))
    found, notes = displays.supplement_findings([main_text, gapped])
    assert found == [] and len(notes) == 1 and "read 1, 3" in notes[0].message


def test_a_legend_g2_cannot_see_makes_its_citation_point_at_nothing() -> None:
    """DESIGN.md, Known gaps: a legend in a form G2's pointer does not see, bold set with
    underscores, which pandoc never writes, leaves its kind one short where it is the last,
    and the citation of it reads as a pointer to nothing."""
    read = said("In Table 1 and Table 2.\n\nTable 1. A\n\n__Table 2__ B\n")
    assert codes(read) == [("pointer-to-nothing", 1)], read


def test_a_pdf_whose_lines_were_not_rebuilt_is_said_not_checked() -> None:
    read = displays.unread_pdf(Path("paper.pdf"))
    assert read.findings == () and read.counted == 0
    assert read.notes[0].message == displays.UNREBUILT and read.notes[0].path == Path("paper.pdf")


def test_the_audit_reports_them_in_their_section_and_in_its_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.md").write_text(
        "# Results\n\nOutcomes are in Table 2, patients in Table 1.\n\n"
        "Table 1. Patients\n\nTable 2. Outcomes\n", encoding="utf-8")  # fmt: skip
    assert main(["audit", "paper.md"]) == 0
    out = capsys.readouterr().out
    assert "Tables and figures        1 finding to look at (not counted by --strict)" in out
    assert "=== Tables and figures (G2) (not counted by --strict) ===" in out
    assert "Table 2 is first cited before table 1" in out
    assert main(["audit", "paper.md", "--strict"]) == 0
    capsys.readouterr()
    assert main(["audit", "paper.md", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["findings"]
    assert [(f["gate"], f["code"]) for f in found if f["gate"] == "G2"] == [
        ("G2", "cited-out-of-order")]


def test_a_paper_whose_tables_and_figures_are_in_order_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.md").write_text(
        "# Results\n\nPatients are in Table 1, outcomes in Table 2.\n\n"
        "Table 1. Patients\n\nTable 2. Outcomes\n", encoding="utf-8")  # fmt: skip
    assert main(["audit", "paper.md", "--details"]) == 0
    out = capsys.readouterr().out
    assert "Tables and figures        each counted from its legends is cited, and in the " \
        "order of its number" in out
    assert "Each table and figure counted from its legends is cited" in out


def test_a_failure_of_the_check_is_recorded_and_leaves_the_words_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A crash in reading the tables and figures is recorded as one, and G6 and G14 report
    as before."""
    from manuscript_guard.diagnostics import crashes

    monkeypatch.delenv("MANUSCRIPT_GUARD_DEBUG", raising=False)
    monkeypatch.chdir(tmp_path)
    recorded = []
    monkeypatch.setattr(crashes, "record", lambda exc, **kw: recorded.append((exc, kw)))

    def broken(*_args, **_kwargs):
        raise RuntimeError("a test")

    monkeypatch.setattr(displays, "of_files", broken)
    (tmp_path / "paper.md").write_text("# Results\n\nIn Table 1.\n\nTable 1. A\n",
                                       encoding="utf-8")  # fmt: skip
    assert main(["audit", "paper.md"]) == 0
    out = capsys.readouterr().out
    assert "Writing and language" in out and "Tables and figures" not in out
    assert [kw["name"] for _exc, kw in recorded] == ["G2 on the tables and figures"]
