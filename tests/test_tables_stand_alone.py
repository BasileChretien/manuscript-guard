"""A table or a figure stands alone (Basile, 2026-11-21, "Table stands alone"; 2026-11-22,
"Ask, don't drop" and "Still counts").

"A caption, legend or note defines for its own table or figure only: its definitions cover
the uses in that table, and are never compared with the text's." A display's own text is its
table's cells, header and caption, a legend that opens with its number, and the notes after
it (`gates.displays`); in LaTeX, the table's float, or a `tabular` that stands in none.

* A definition there that gives the text's long form again says nothing. One that gives
  another long form than the text's is asked about, a question (INFO), never a warning; each
  such meaning once. Two displays are never compared with each other, and within one display
  two meanings are a warning, as in the text.
* A use there that the same display defines is no `abbreviation-used-before-defined`,
  wherever the definition stands in it: a header above the note that defines it.
* A definition there used only in its own display is not `abbreviation-unused`.
* Where the text defines a form nowhere, a display's definition still counts for a use in
  the text.

What the text does is unchanged: a second definition there, a use before its definition
there, and a form defined nowhere are each still said, a table's form among them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from manuscript_guard.auditing.undefined import unasked
from manuscript_guard.contracts import load_project
from manuscript_guard.findings import INFO
from manuscript_guard.gates import check_language
from manuscript_guard.gates.language import _file, _judge, _Known, _latex_read

NOTHING = _Known(frozenset(), frozenset())

METHODS = ("# Methods\n\nWe used the Beck Depression Inventory (BDI) and the Cigarette "
           "Dependence Scale (CDS), and the BDI and the CDS were read.\n\n"
           "# Results\n\n")  # fmt: skip
TABLE = "| Score | BDI | CDS |\n|---|---|---|\n| one | 12 | 40 |\n"
#: What a finding is said as: a question, or a warning.
ASKED, WARNED = "asked", "warned"


def _said(findings) -> list[tuple[str, str, str]]:
    """Each finding's code, short form and whether it is asked or warned, G14's question on
    the short forms never defined given back as a warning for each form."""
    return sorted((f.code, f.message.split()[0], ASKED if getattr(f, "question", False)
                   else WARNED) for f in unasked(list(findings)))  # fmt: skip


def _found(text: str) -> list[tuple[str, str, str]]:
    return _said(_judge([_file(0, Path("main.md"), text, [], False)], NOTHING,
                        Path(".")).findings)  # fmt: skip


def _latex_found(tmp_path: Path, body: str) -> list[tuple[str, str, str]]:
    (tmp_path / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\begin{{document}}\n{body}\n\\end{{document}}\n",
        encoding="utf-8")  # fmt: skip
    return _said(_judge(_latex_read(tmp_path, None), NOTHING, tmp_path).findings)


@pytest.mark.parametrize("after", [
    # A note that opens with its mark.
    "*Note.* BDI = Beck Depression Inventory; CDS = Cigarette Dependence Score.",
    # A note with no mark, after pandoc's caption under the table.
    ": **Table 1.** Scores by group.\n\nData are means. BDI: Beck Depression Inventory; CDS: "
    "Cigarette Dependence Score.",
    # A note in italics, its opening star glued to the word.
    "*BDI = Beck Depression Inventory; CDS = Cigarette Dependence Score*",
    # A footnote's mark.
    "^a^ Cigarette Dependence Score (CDS); Beck Depression Inventory (BDI).",
])  # fmt: skip
def test_a_table_s_note_with_another_meaning_is_asked_and_one_word_for_word_is_silent(
    after: str,
) -> None:
    """"Score" for the text's "Scale" in a table's note is asked about, not warned of and not
    passed over; the note's BDI, the text's word for word, says nothing."""
    text = f"{METHODS}{TABLE}\n{after}\n\nThe BDI and the CDS were low.\n"
    assert _found(text) == [("abbreviation-redefined", "CDS", ASKED)]


def test_the_question_names_both_meanings_and_where_the_text_gives_its_own() -> None:
    text = (f"{METHODS}{TABLE}\n*Note.* CDS = Cigarette Dependence Score.\n\nThe CDS was "
            "low.\n")  # fmt: skip
    report = _judge([_file(0, Path("main.md"), text, [], False)], NOTHING, Path("."))
    (asked,) = [f for f in report.findings if f.code == "abbreviation-redefined"]
    assert asked.severity == INFO and asked.question, asked
    assert asked.line == 11, asked
    assert "'Cigarette Dependence Score'" in asked.message, asked.message
    assert "'Cigarette Dependence Scale' at main.md:3" in asked.message, asked.message


def test_each_other_meaning_of_the_displays_is_asked_once() -> None:
    """Three tables' notes giving the same other meaning are one question, at the first; a
    fourth giving a third meaning is a question of its own."""
    tables = "".join(f"{TABLE}\n*Note.* CDS = Cigarette Dependence Score.\n\nRead {n}.\n\n"
                     for n in range(3))  # fmt: skip
    text = (f"{METHODS}{tables}{TABLE}\n*Note.* CDS = Cigarette Dependence Survey.\n\nThe CDS "
            "was low.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "CDS", ASKED)] * 2


@pytest.mark.parametrize("legend", [
    # A figure's legend restating a form with another long form.
    "***Fig 1. The design.** The dose was low dose (LD) or high dose (HD).",
    "Figure 2: The dose was low dose (LD) or high dose (HD) in each session.",
    "**Table 3.** The dose was low dose (LD) or high dose (HD).",
])  # fmt: skip
def test_a_legend_with_another_meaning_is_asked(legend: str) -> None:
    text = ("# Methods\n\nThe dose was the low daily dose (LD) or the high daily dose (HD), "
            f"and LD and HD were kept.\n\n# Results\n\n{legend}\n\nThe LD and the HD "
            "sessions differed.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "HD", ASKED),
                            ("abbreviation-redefined", "LD", ASKED)]


def test_two_tables_notes_are_never_compared() -> None:
    """The notes of two tables each define one form, one way and another."""
    text = ("# Results\n\n| RoS | n |\n|---|---|\n| 3 | 4 |\n\n*Note.* RoS: rating of sleep.\n\n"
            "Table 3. The second.\n\n| RoS | n |\n|---|---|\n| 3 | 4 |\n\n*Note.* RoS: ratings "
            "of sleep scale.\n")  # fmt: skip
    assert _found(text) == []


@pytest.mark.parametrize("text", [
    # The rows use ICC, the note under pandoc's caption defines it.
    "# Results\n\n| Effect | Value |\n|---|---|\n| ICC | 0.73 |\n\n: **Table 2.** Effects.\n\n"
    "Values are estimates. ICC: intraclass correlation coefficient.\n",
    # APA's number, then the title, then the table and its note.
    "# Tables\n\nTable 1.\n\n*Means by group.*\n\n| Variable | Mean |\n|---|---|\n| KQS | 62 |"
    "\n| IQ | 100 |\n\n*Note.* KQS: Kids Quiet Scale; IQ: intelligence quotient.\n",
    # A header defined in the note right under it, two forms a slash joins.
    "# Results\n\n**Table 1. Arms.**\n\n| Site | TA/CA |\n|---|---|\n| one | 3/4 |\n\n"
    "*TA/CA = treated/control arm.*\n",
])  # fmt: skip
def test_a_use_in_a_table_its_own_note_defines_is_not_used_before_it(text: str) -> None:
    assert _found(text) == []


def test_a_note_s_definition_used_only_in_its_table_is_used() -> None:
    text = ("# Results\n\n| Group | ICC |\n|---|---|\n| one | 0.7 |\n\n*Note.* ICC: intraclass "
            "correlation coefficient.\n\nThe groups were alike.\n")  # fmt: skip
    assert _found(text) == []


def test_a_latex_table_s_header_above_its_caption_is_not_used_before_it(tmp_path: Path) -> None:
    """The header uses KD, the caption under the table defines it, and is no use before its
    definition; the float's AT, another long form than the text's, is asked about."""
    body = ("\\section{Methods}\nWe used the Anderson test (AT), and the AT held.\n"
            "\\begin{table}\n\\begin{tabular}{ll}\nKD & AT \\\\\n1 & 2 \\\\\n\\end{tabular}\n"
            "\\caption{The Kolmogorov distance (KD) and the Anderson test statistic (AT).}\n"
            "\\end{table}\n")  # fmt: skip
    assert _latex_found(tmp_path, body) == [("abbreviation-redefined", "AT", ASKED)]


# ----------------------------------------------------------- what the text does is unchanged


def test_a_second_definition_in_the_text_is_still_warned_of_beside_a_table() -> None:
    """The text's own second meaning is a warning. The note gives a meaning the text gives
    too, its second, and says nothing of its own: the warning on the text covers it."""
    text = (f"{METHODS}{TABLE}\n*Note.* CDS = Cigarette Dependence Score.\n\n# Discussion\n\n"
            "The Cigarette Dependence Score (CDS) was low, and the CDS fell.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "CDS", WARNED)]


def test_a_use_before_the_text_s_definition_is_still_said_beside_a_table() -> None:
    """A table that does not define the form leaves its use to the text: DMB in the note,
    before the text defines it, is used before it is defined."""
    text = ("# Results\n\n| Class | n |\n|---|---|\n| one | 4 |\n\n*Note.* Each DMB read it "
            "twice.\n\n# Discussion\n\nThe data monitoring boards (DMB) were many, and the DMB "
            "met.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-used-before-defined", "DMB", WARNED)]


def test_a_table_s_form_defined_nowhere_is_still_asked() -> None:
    """A form in a table's body that nothing defines; one in its header in capitals is a
    label, and not asked about, as before."""
    text = ("# Results\n\n| Group | n |\n|---|---|\n| QXR | 4 |\n\n*Note.* Means.\n\nThe groups "
            "were alike.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-undefined", "QXR", WARNED)]


def test_a_paragraph_after_a_table_that_is_no_note_is_the_text_s() -> None:
    """A paragraph after a table that opens with no note's mark and pairs no form is the
    text's own, and a second meaning there is a warning."""
    text = (f"{METHODS}{TABLE}\nThe Cigarette Dependence Score (CDS) was low, and the CDS "
            "fell.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "CDS", WARNED)]


def test_one_display_s_own_definitions_are_compared() -> None:
    """A table is read alone, not unread: its caption and its note giving one form two
    meanings is still two meanings, a warning."""
    text = ("# Results\n\n**Table 1.** The relative odds ratio (ROR) by drug.\n\n| Drug | ROR |\n"
            "|---|---|\n| one | 3 |\n\n*Note.* ROR: reporting odds ratio.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "ROR", WARNED)]


def test_check_asks_of_a_table_s_other_meaning_and_warns_of_nothing(project: Path) -> None:
    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    (project / "manuscript" / "main.md").write_text(
        f"{METHODS}{TABLE}\n*Note.* BDI = Beck Depression Inventory; CDS = Cigarette "
        "Dependence Score.\n\nThe BDI and the CDS were low.\n", encoding="utf-8")  # fmt: skip
    report = check_language(load_project(project)[0])
    said = [f for f in unasked(list(report.findings)) if f.code.startswith("abbreviation-")]
    assert [(f.code, f.severity, f.message.split()[0]) for f in said] == [
        ("abbreviation-redefined", INFO, "CDS")], said
    assert not [f for f in report.warnings if f.code.startswith("abbreviation-")]


# --------------------------------- a use in the text only a table defines (Basile, "Still counts")


def test_a_use_in_the_text_only_a_table_defines_is_held_to_the_table_s_definition() -> None:
    """Where the text defines a form nowhere, a table's definition still counts for the
    text (Basile, 2026-11-22, "Still counts"): a use after it is defined, and one before it
    is used before it is defined (`language._DISPLAYS_DEFINE_FOR_THE_TEXT`)."""
    table = ("| Group | PSR |\n|---|---|\n| one | 0.7 |\n\n*Note.* PSR: pooled signal ratio.\n"
             "\n")  # fmt: skip
    assert _found(f"# Results\n\n{table}The PSR was high.\n") == []
    assert _found(f"# Methods\n\nThe PSR was high.\n\n# Results\n\n{table}") == [
        ("abbreviation-used-before-defined", "PSR", WARNED)]


# ------------------------------------------------------------------------- round 1 of #759


def test_a_meaning_warned_of_in_its_own_display_is_not_asked_about_too() -> None:
    """The note's ROR differs from its legend's and from the text's: one finding, the
    warning of its own display. (Round 1's "ROR: rank ratio" holds no O, so the letter rule
    reads no definition in it; "relative outcome ratio" is one.)"""
    text = ("# Methods\n\nWe used the reporting odds ratio (ROR), and the ROR was read.\n\n"
            "# Results\n\n**Table 1.** The reporting odds ratio (ROR) by drug.\n\n| Drug | ROR |\n"
            "|---|---|\n| one | 3 |\n\n*Note.* ROR: relative outcome ratio.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "ROR", WARNED)]


def test_a_text_use_after_a_legend_and_before_the_text_s_definition_is_used_before_it() -> None:
    """Where the text defines the form, a use in the text is held to the text's definition
    alone: one between a legend's definition and the text's later one is used before it."""
    text = ("# Results\n\nFigure 1. The pooled signal ratio (PSR) by week.\n\nThe PSR rose.\n\n"
            "# Discussion\n\nThe pooled signal ratio (PSR) was high, and the PSR "
            "held.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-used-before-defined", "PSR", WARNED)]


def test_a_note_typed_on_the_line_under_its_table_is_its_note() -> None:
    text = ("# Methods\n\nThe Cigarette Dependence Scale (CDS) was given, and the CDS held.\n\n"
            "# Results\n\n| a | CDS |\n|---|---|\n| 1 | 2 |\n^a^ Cigarette Dependence Score (CDS)."
            "\n\nThe CDS was low.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "CDS", ASKED)]


@pytest.mark.parametrize("between", ["\n## Discussion\n", "\n\n## Discussion\n\n"])
def test_a_heading_after_a_table_ends_it_glued_to_the_paragraph_or_not(between: str) -> None:
    """The paragraph under a heading after a table is the text's, though it pairs a form."""
    text = ("# Methods\n\nThe Cigarette Dependence Scale (CDS) was given, and the CDS held.\n\n"
            f"# Results\n\n| a | CDS |\n|---|---|\n| 1 | 2 |\n{between}*Note.* CDS = Cigarette "
            "Dependence Score.\n\nThe CDS was low.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "CDS", WARNED)]


def test_a_paragraph_of_the_text_under_a_table_that_opens_on_note_is_taken_for_its_note() -> None:
    """The other half of the Known gap: "Note that ..." under a table is read as its note, so
    another meaning there is asked about and not warned of."""
    text = ("# Methods\n\nWe read the heart rate (HR), and the HR held.\n\n# Results\n\n| Group "
            "| HR |\n|---|---|\n| one | 2 |\n\nNote that the hazard ratio (HR) was adjusted.\n\n"
            "The HR was low.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "HR", ASKED)]


def test_the_question_says_the_text_s_definition_stands_later_on_the_same_line(
    tmp_path: Path,
) -> None:
    body = ("\\section{Methods}\n\\begin{table}\\begin{tabular}{l}ROR\\end{tabular}\\caption{The "
            "relative odds ratio (ROR).}\\end{table} The reporting odds ratio (ROR) was read, and "
            "the ROR held.\n")  # fmt: skip
    (tmp_path / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\begin{{document}}\n{body}\n\\end{{document}}\n",
        encoding="utf-8")  # fmt: skip
    report = _judge(_latex_read(tmp_path, None), NOTHING, tmp_path)
    (asked,) = [f for f in report.findings if f.code == "abbreviation-redefined"]
    assert asked.question and "later on the same line" in asked.message, asked.message


# ------------------------------------------------------------------------- round 2 of #759


def test_a_meaning_warned_of_in_its_display_and_given_again_there_is_not_asked() -> None:
    text = ("# Methods\n\nWe used the reporting odds ratio (ROR), and the ROR was read.\n\n"
            "# Results\n\n**Table 1.** The reporting odds ratio (ROR) by drug.\n\n| Drug | ROR |\n"
            "|---|---|\n| one | 3 |\n\n^a^ ROR: relative outcome ratio.\n\n^b^ ROR: relative "
            "outcome ratio.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "ROR", WARNED)]


def test_a_note_giving_its_legend_s_meaning_again_says_nothing() -> None:
    """Within one display, the same meaning given again by a caption or a legend and a
    note's pair restates, as in the text."""
    text = ("# Results\n\n**Table 1.** The reporting odds ratio (ROR) by drug.\n\n| Drug | ROR |\n"
            "|---|---|\n| one | 3 |\n\nROR: reporting odds ratio.\n")  # fmt: skip
    assert _found(text) == []


def test_a_line_of_a_note_that_g14_reads_nothing_of_ends_nothing() -> None:
    """A line of code alone inside a note is part of the note, so the pair on its next line
    is the note's and asked about."""
    text = ("# Methods\n\nWe read the intra-class correlation coefficient (ICC), and the ICC "
            "held.\n\n# Results\n\n| Group | ICC |\n|---|---|\n| one | 0.7 |\n\n*Note.* Values are "
            "means of\n`score_total`\nacross sites; ICC: intraclass correlation.\n\nThe ICC was "
            "low.\n")  # fmt: skip
    assert _found(text) == [("abbreviation-redefined", "ICC", ASKED)]
