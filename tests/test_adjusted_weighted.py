"""A P an adjustment for multiple comparisons may explain, and a share a table's weighting may,
are questions to the author, in `audit` and in `check` (Basile, 2026-11-16, decision 31:
"Both").

The P recomputed from a statistic is the textbook two-sided one. Many papers say once, in
their Methods, that their P values are adjusted (Holm, Bonferroni, the false discovery rate),
and never again beside a test, so every adjusted P was a P that does not follow from its
statistic. An adjustment only makes a P larger: a P stated wholly above the range its
statistic gives is asked about, quoting the statement and its place; one below it is wrong
under any adjustment and stays a finding. In the same way a share off its column's n, in a
table whose caption, cells or note says its shares are weighted, is asked about; another
table of the same paper is held as before.

Real cases, from the corpus run on 0223ca005: docx-sport-A3 says "Greenhouse-Geisser and
Bonferroni corrections were applied where necessary" and gives P = 0.013 beside a t that
gives 0.0041, and P > 0.999 beside one that gives 0.096; docx-psych-A3 says it controlled for
multiple comparisons with the false discovery rate and gives P = .61 beside an F that gives
0.54; docx-educ-B1 gives P < .001 beside a t that gives 0.0055, smaller, and says nothing of
an adjustment; docx-psych-B2's Table 1 has the note "Weighted statistics computed using the
tbl_svysummary function", and its supplementary tables, whose shares are weighted, say so in
legends "Table S1a", "Table S1b", ... that do not number them, as "nationally
representative" (Basile, 2026-11-21, "Caption wording" and "Adjacent fallback").
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.audit import audit
from manuscript_guard.auditing import report as sections
from manuscript_guard.auditing.adjusted import ASKED_ADJUSTED, ASKED_WEIGHTED
from manuscript_guard.cli import main
from manuscript_guard.findings import INFO, WARN
from manuscript_guard.stats.adjusted import adjustment, weighting

#: A Methods section that says its P values are adjusted, then three tests: a P larger than
#: its t gives, one smaller, and an interval whose P is on the other side of its level.
ADJUSTED = ("# Methods\n\nP values were adjusted for multiple comparisons by the Holm method. "
            "Models were adjusted for age and sex.\n\n# Results\n\nThe groups differed, "
            "t(23) = 2.71, P = 0.048. They differed again, t(23) = 2.71, P = 0.002. The odds "
            "were higher, OR 2.0 (95% CI 1.5-2.7), P = 0.30.\n")  # fmt: skip
LARGER = ("The paper says its P values are adjusted (\"P values were adjusted for multiple "
          "comparisons by the Holm method.\", line 3). P = 0.048 is larger than the 0.0124 to "
          "0.0126 that t(23) = 2.71 gives on its own. Is it the adjusted P? If not, check the "
          "statistic and the P against the analysis.")  # fmt: skip


def audited(tmp_path: Path, text: str, name: str = "paper.md"):
    paper = tmp_path / name
    paper.write_text(text, encoding="utf-8")
    return audit([paper], None)


# ------------------------------------------------------------------------------ the reading


@pytest.mark.parametrize("said", [
    "P values were adjusted using the Bonferroni correction.",
    "We applied the Holm-Bonferroni method.",
    "Significance was set by the Benjamini-Hochberg procedure.",
    "Hochberg's step-up procedure was used.",
    "The Benjamini-Yekutieli procedure controlled for dependence.",
    "We controlled the false discovery rate at 5%.",
    "After controlling for multiple comparisons using False Discovery Rate, one remained.",
    "Tests were corrected with FDR.",
    "We used the \N{LATIN CAPITAL LETTER S WITH CARON}id\N{LATIN SMALL LETTER A WITH ACUTE}k "
    "correction.",
    "Pairwise contrasts used Tukey's HSD.",
    "Each arm was compared with control by Dunnett's test.",
    "All P values were adjusted for multiple testing.",
    "Results were corrected for multiple comparisons.",
    "A correction for multiple tests was made.",
    "A multiple-comparison correction was applied.",
])  # fmt: skip
def test_each_named_adjustment_is_a_statement(said: str) -> None:
    found = adjustment(f"Methods first. {said} Then results.")
    assert found is not None and found.quote == said, found


@pytest.mark.parametrize("said", [
    "Models were adjusted for age and sex.",
    "Estimates were corrected for baseline values.",
    "We adjusted for multiple confounders.",
    "The fdr column is blank.",
    # Negated, in its clause before the words (round 1 of #703).
    "P values were not adjusted for multiple comparisons.",
    "No correction for multiple testing was applied.",
    "We did not correct for multiple comparisons.",
    "There was no multiple-comparison correction.",
    "Tests were done without Bonferroni correction.",
    "We didn't adjust for multiple testing.",
    # A surname that cites a paper, or stands beside no word of a method.
    "This follows the procedure as Holm et al. reported it.",
    "Hochberg and colleagues showed the test was conservative.",
    "Tukey and coworkers described the test of additivity.",
    "Outliers were found with Tukey's fences.",
    "As Bonferroni noted in 1936, inequalities hold.",
    # Negated after the words, and across a comma (round 2 of #703).
    "Correction for multiple comparisons was not performed.",
    "Adjustment for multiple comparisons was not made.",
    "The Bonferroni correction was not applied.",
    "P values were not, however, adjusted for multiple comparisons.",
    "No adjustment, such as the Bonferroni correction, was made.",
    # A surname followed by a year or a number in brackets cites a paper.
    "Groups were compared with the Kruskal-Wallis test (Dunnett, 1955).",
    "Each arm was compared with the test of Dunnett [12].",
    "The test follows Holm (1979).",
])  # fmt: skip
def test_a_covariate_adjustment_a_negation_and_a_citation_are_no_statement(said: str) -> None:
    """ "Adjusted for age and sex" names covariates, not an adjustment of P values; a
    statement its clause negates, before the words or after them, says none was made; a
    method's surname that cites a paper ("Holm et al.", "(Dunnett, 1955)", "Holm (1979)",
    "Dunnett [12]"), or stands beside no word of a method in its clause, is no statement."""
    assert adjustment(said) is None


def test_the_search_goes_on_past_a_negated_or_cited_match() -> None:
    """A negated clause, or a cited surname, is passed over and the next match read."""
    for text in ("No correction was needed for the primary outcome; secondary outcomes were "
                 "corrected for multiple comparisons.",
                 "As Holm et al. showed, P values were adjusted by the Bonferroni method."):
        found = adjustment(text)
        assert found is not None and text[found.start:].startswith(("corrected", "Bonferroni"))


@pytest.mark.parametrize("said", [
    "Weighted % of each category.", "Weighted percentages are shown.", "n (weighted %)",
    "Weighted n", "Survey-weighted proportions.", "Inverse probability weighted cohort.",
    "Data are IPW estimates.", "1Weighted statistics computed using the survey package.",
    "Percentages are weighted to the census.", "Weighted \\% of each category.",
    "After IPTW (n = 1200)", "No. (weighted %)",
    # Basile, 2026-11-21, "Caption wording": "nationally representative" reads as weighted.
    "Table S1a. Nationally representative shares, Region A.", "Exposed, nationally "
    "representative", "Proportions are nationally-representative.",
    # A word ending in "non" is no negation (round 2 of the review of #718).
    "Table S1a. Lebanon nationally representative survey, shares.", "Shannon nationally "
    "representative panel.",
])  # fmt: skip
def test_each_weighting_said_is_read(said: str) -> None:
    assert weighting(said) is not None, said


@pytest.mark.parametrize("said", [
    "Unweighted n (%).", "unweighted", "Weighted mean (SD).", "Weighted median.",
    "Population-weighted meta-analysis.", "Inverse-variance weighting.", "Before IPTW (n = 1200)",
    "Prior to weighting, n (%)", "Crude, not weighted %",
    # The same clause rule against negation holds for "nationally representative".
    "Shares, not nationally representative.", "Crude counts before weighting to be nationally "
    "representative.", "Unweighted nationally representative sample.",
    "Non-nationally representative shares.", "Shares, non-nationally representative.",
    "Non nationally representative sample.",
    "Non\N{NON-BREAKING HYPHEN}nationally representative shares.",
    "Non\N{HYPHEN}nationally representative shares.",
    "Non\N{NO-BREAK SPACE}nationally representative shares.",
])  # fmt: skip
def test_an_estimate_weighted_and_unweighted_shares_are_no_weighting(said: str) -> None:
    assert weighting(said) is None, said


@pytest.mark.parametrize("said", [
    "The Bonferroni correction was applied to the secondary outcomes only.",
    "The FDR of the classifier was 0.30.",
    "Tukey's test for nonadditivity was run.",
])  # fmt: skip
def test_a_statement_is_read_by_its_words_alone(said: str) -> None:
    """The limits of exact words (DESIGN.md, Known gaps): a statement that adjusts some tests,
    and a name in another sense (tex-stat-ap-A2's false discovery rate of a classifier,
    Tukey's test of additivity), are each read as a statement, and the paper's larger P
    values asked about."""
    assert adjustment(said) is not None


# ------------------------------------------------------------------------------- the audit


def test_an_adjusted_paper_asks_of_a_larger_p_and_finds_a_smaller(tmp_path: Path) -> None:
    """The larger P is asked about, quoting the statement and its line; the smaller one, and
    the interval's P, stay findings: an adjustment may widen the interval too, or not, so no
    exact rule says which way it would make the two disagree."""
    report = audited(tmp_path, ADJUSTED)
    (asked,) = report.arithmetic_asked
    assert (asked.code, asked.line, asked.message) == (ASKED_ADJUSTED, 7, LARGER)
    assert asked.context == "t(23) = 2.71, P = 0.048"
    assert [(d.line, d.message.split(",")[0]) for d in report.disagreements] == [
        (7, "t(23) = 2.71 gives a two-sided P between 0.0124 and 0.0126"),
        (7, "OR 2.0 (95% CI 1.5 to 2.7) excludes 1")]


def test_with_no_adjustment_statement_both_ps_are_findings(tmp_path: Path) -> None:
    """The same paper with "Models were adjusted for age and sex." alone: covariates, no
    adjustment of P values, so both P values are findings as before."""
    text = ADJUSTED.replace("P values were adjusted for multiple comparisons by the Holm "
                            "method. ", "")  # fmt: skip
    report = audited(tmp_path, text)
    assert report.arithmetic_asked == []
    assert len(report.disagreements) == 3


def test_a_statement_in_the_reference_list_is_none(tmp_path: Path) -> None:
    """docx-educ-A3's reference list names Benjamini and Hochberg's paper on the false
    discovery rate: no statement of the paper's own."""
    text = ADJUSTED.replace("P values were adjusted for multiple comparisons by the Holm "
                            "method. ", "") + (  # fmt: skip
        "\n# References\n\n1. Benjamini Y, Hochberg Y. Controlling the false discovery rate. "
        "J R Stat Soc B. 1995;57:289-300.\n")
    assert audited(tmp_path, text).arithmetic_asked == []


def test_a_statement_after_the_tests_still_holds(tmp_path: Path) -> None:
    """Said anywhere in the paper, after its tests too: in the Discussion."""
    text = ADJUSTED.replace("P values were adjusted for multiple comparisons by the Holm "
                            "method. ", "") + (  # fmt: skip
        "\n# Discussion\n\nBonferroni-corrected P values are given throughout.\n")
    (asked,) = audited(tmp_path, text).arithmetic_asked
    assert '("Bonferroni-corrected P values are given throughout.", line 11)' in asked.message


def test_a_latex_paper_s_statement_in_another_file_holds_for_its_tests(tmp_path: Path) -> None:
    """A LaTeX paper is one paper across its files: the statement in the methods file it
    inputs holds for a test in its main file, said with the file's name; and the reference
    list it types, which names Bonferroni, is no statement."""
    (tmp_path / "methods.tex").write_text(
        "\\section{Methods}\nAll P values were Holm-adjusted.\n", encoding="utf-8")
    main_tex = tmp_path / "main.tex"
    main_tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{methods}\n\\section{Results}\n"
        "The groups differed, $t(23) = 2.71$, $P = 0.048$.\n"
        "\\begin{thebibliography}{1}\n\\bibitem{a} Bonferroni C. Teoria. 1936.\n"
        "\\end{thebibliography}\n\\end{document}\n", encoding="utf-8")  # fmt: skip
    report = audit([main_tex], None, found_tex=[tmp_path / "methods.tex"])
    (asked,) = report.arithmetic_asked
    assert asked.source == main_tex and asked.line == 5
    assert '("All P values were Holm-adjusted.", methods.tex, line 2)' in asked.message, asked
    alone = tmp_path / "alone"
    alone.mkdir()
    lone = alone / "main.tex"
    lone.write_text(main_tex.read_text(encoding="utf-8").replace("\\input{methods}\n", ""),
                    encoding="utf-8")  # fmt: skip
    found = audit([lone], None)
    assert found.arithmetic_asked == [] and len(found.disagreements) == 1


#: Two tables of one paper with the same share off its column's n.
TABLES = ("# Results\n\n{caption}\n\n| Characteristic | {header} (n = 1200) |\n|---|---|\n"
          "| {label}, n (%) | 640 (58.0%) |\n| Smokers, n (%) | 600 (50.0%) |\n\n{note}\n\n"
          "Table 2. Characteristics at follow-up.\n\n| Characteristic | Exposed (n = 1200) |\n"
          "|---|---|\n| Male sex, n (%) | 640 (58.0%) |\n")  # fmt: skip
PLAIN = {"caption": "Table 1. Characteristics.", "header": "Exposed", "label": "Male sex",
         "note": "Shares are of the column."}  # fmt: skip


@pytest.mark.parametrize(("where", "words"), [
    ("caption", "Table 1. Characteristics, weighted percentages."),
    ("header", "Exposed, weighted %"),
    ("label", "Male sex (survey-weighted)"),
    ("note", "Note. Weighted statistics computed with the survey package."),
])  # fmt: skip
def test_a_weighted_table_asks_of_its_share_and_lets_off_no_other(
    tmp_path: Path, where: str, words: str
) -> None:
    """The word in the caption, the header, a row's label or the note: Table 1's off share
    is asked about; Table 2's, the same share in a table that says nothing, is a finding."""
    report = audited(tmp_path, TABLES.format(**{**PLAIN, where: words}))
    (asked,) = report.arithmetic_asked
    assert asked.code == ASKED_WEIGHTED and asked.line == 7, asked
    # A header's words let off its column alone, and say so (round 1 of #703).
    said = {"header": "Table 1's column", "label": "Table 1's row"}.get(where, "Table 1")
    assert asked.message.startswith(f"{said} says its shares are weighted (\"")
    assert asked.message.endswith("\"). 640 (58.0%) is not 640 of 1200 (53.3%). Is 58.0% the "
                                  "weighted share? If so nothing is wrong; if not, check the "
                                  "count, the share and the column's n.")  # fmt: skip
    (finding,) = report.disagreements
    assert finding.line == 16 and finding.message.startswith("n (%) 640 (58.0%)")


def test_the_next_table_s_weighted_caption_is_no_note_of_the_table_before(
    tmp_path: Path,
) -> None:
    """Table 1 with no note, then Table 2 captioned as weighted: the paragraph after Table 1
    is Table 2's caption, and lets off Table 2's share, not Table 1's."""
    table = "| Characteristic | Exposed (n = 1200) |\n|---|---|\n| Male sex, n (%) | 640 (58.0%) |"
    report = audited(tmp_path, f"# Results\n\nTable 1. Counts.\n\n{table}\n\nTable 2. Weighted "
                               f"percentages.\n\n{table}\n")  # fmt: skip
    assert [d.line for d in report.arithmetic_asked] == [13]
    assert [d.line for d in report.disagreements] == [7]


def test_the_same_table_without_the_word_is_a_finding(tmp_path: Path) -> None:
    report = audited(tmp_path, TABLES.format(**PLAIN))
    assert report.arithmetic_asked == [] and [d.line for d in report.disagreements] == [7, 16]


def test_a_paper_s_weighted_sentence_alone_lets_off_no_table(tmp_path: Path) -> None:
    """A sentence of the Methods that says the shares are weighted ("weighted to be
    nationally representative"): no exact rule names a table from it, so each share off its
    n stays a finding (DESIGN.md, Known gaps)."""
    text = ("# Methods\n\nDescriptive statistics were weighted to be nationally representative, "
            "and weighted percentages are shown.\n\n") + TABLES.format(**PLAIN)  # fmt: skip
    report = audited(tmp_path, text)
    assert report.arithmetic_asked == [] and len(report.disagreements) == 2


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(path: Path, body: str) -> Path:
    document = f"<?xml version='1.0'?><w:document {W}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", (2020, 1, 1, 0, 0, 0)), document)
    return path


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc>{_para(cell)}</w:tc>" for cell in cells) + "</w:tr>"


def test_a_docx_says_both_questions_at_their_paragraphs(tmp_path: Path) -> None:
    """docx-sport-A3's and docx-psych-B2's shapes in Word: the statement in one paragraph, a
    test in another; a table whose note after it says its statistics are weighted. Each
    question gives the statement's place as the report gives a .docx's."""
    body = (_para("Methods") + _para("Greenhouse-Geisser and Bonferroni corrections were "
                                     "applied where necessary.")
            + _para("Results") + _para("Power was higher, t(29) = 3.11, P = 0.013.")
            + _para("Table 1. Characteristics")
            + f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
            f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>"
            + _para("Note. 1Weighted statistics computed using the survey package."))
    paper = _docx(tmp_path / "paper.docx", body)
    report = audit([paper], None)
    codes = [d.code for d in report.arithmetic_asked]
    assert codes == [ASKED_ADJUSTED, ASKED_WEIGHTED], report.arithmetic_asked
    assert ('("Greenhouse-Geisser and Bonferroni corrections were applied where necessary.", '
            "Methods, paragraph 1)") in report.arithmetic_asked[0].message
    assert report.disagreements == []


# ------------------------------------------------- round 1 of #703: what is no statement, no note

NEGATED = ("P values were not adjusted for multiple comparisons.",
           "No correction for multiple testing was applied.",
           "We did not correct for multiple comparisons.",
           # Negated after the words (round 2 of #703).
           "Correction for multiple comparisons was not performed.",
           "Adjustment for multiple comparisons was not made.",
           "The Bonferroni correction was not applied.")  # fmt: skip


@pytest.mark.parametrize("said", NEGATED)
def test_a_negated_statement_leaves_the_larger_p_a_finding(tmp_path: Path, said: str) -> None:
    """The audit gives the number that does not fit, as main does, and asks nothing."""
    report = audited(tmp_path, f"# Methods\n\n{said}\n\n# Results\n\nThe groups differed, "
                               "t(23) = 2.71, P = 0.048.\n")  # fmt: skip
    assert report.arithmetic_asked == []
    (found,) = report.disagreements
    assert found.message.endswith("and the text says P = 0.048")


@pytest.mark.parametrize("said", [
    "This follows the procedure as Holm et al. reported it.",
    "Hochberg and colleagues showed it.",
])  # fmt: skip
def test_a_cited_surname_leaves_the_larger_p_a_finding(tmp_path: Path, said: str) -> None:
    report = audited(tmp_path, f"# Methods\n\n{said}\n\n# Results\n\nThe groups differed, "
                               "t(23) = 2.71, P = 0.048.\n")  # fmt: skip
    assert report.arithmetic_asked == [] and len(report.disagreements) == 1


@pytest.mark.parametrize("said", ["We used the Holm correction.", "Bonferroni-corrected P values "
                                  "are given."])  # fmt: skip
def test_a_method_s_surname_beside_its_word_still_asks(tmp_path: Path, said: str) -> None:
    report = audited(tmp_path, f"# Methods\n\n{said}\n\n# Results\n\nThe groups differed, "
                               "t(23) = 2.71, P = 0.048.\n")  # fmt: skip
    assert [d.code for d in report.arithmetic_asked] == [ASKED_ADJUSTED]


#: A table with no note, then a legend in capitals of a table said to be weighted.
CAPITALS = ("# Results\n\nTable 1. Counts.\n\n| Characteristic | Exposed (n = 1200) |\n|---|---|\n"
            "| Male sex, n (%) | 640 (58.0%) |\n\n{after}\n\n| Characteristic | Exposed (n = 1200) "
            "|\n|---|---|\n| Male sex, n (%) | 640 (58.0%) |\n")  # fmt: skip


@pytest.mark.parametrize("after", ["TABLE 2. Weighted percentages.",
                                   "**TABLE 2.** Weighted percentages.",
                                   "*Table 2. Weighted percentages.*"])  # fmt: skip
def test_a_next_legend_in_any_case_is_no_note_of_the_table_before(
    tmp_path: Path, after: str
) -> None:
    """Round 1 of #703: "TABLE 2." was not taken for a legend, and became Table 1's note, so
    Table 1's share was let off. Table 1's stays a finding; Table 2's, under its legend, is
    asked about."""
    report = audited(tmp_path, CAPITALS.format(after=after))
    assert [d.line for d in report.disagreements] == [7]
    assert [d.line for d in report.arithmetic_asked] == [13]


def test_a_next_legend_in_capitals_is_no_note_in_a_docx(tmp_path: Path) -> None:
    table = (f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
             f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    body = (_para("Results") + _para("Table 1. Counts.") + table
            + _para("TABLE 2. Weighted percentages.") + table)
    report = audit([_docx(tmp_path / "paper.docx", body)], None)
    assert len(report.disagreements) == 1 and len(report.arithmetic_asked) == 1
    assert report.disagreements[0].line < report.arithmetic_asked[0].line


def test_a_paragraph_after_a_table_with_no_note_s_mark_is_no_note(tmp_path: Path) -> None:
    """A table's note opens with "Note", "Abbreviations" or a footnote's mark: a sentence of
    the text after the table that says the groups were weighted lets off nothing; and in a
    .docx, a paragraph before a table that is no legend is no caption."""
    table = "| Characteristic | Exposed (n = 1200) |\n|---|---|\n| Male sex, n (%) | 640 (58.0%) |"
    for after in ("After inverse probability weighting, the groups were balanced.",
                  "Weighted percentages follow in Table 2."):
        report = audited(tmp_path, f"# Results\n\nTable 1. Counts.\n\n{table}\n\n{after}\n")
        assert report.arithmetic_asked == [] and len(report.disagreements) == 1, after
    for note in ("Note. Shares are survey-weighted.", "a Weighted percentages.",
                 "* IPW estimates."):
        report = audited(tmp_path, f"# Results\n\nTable 1. Counts.\n\n{table}\n\n{note}\n")
        assert len(report.arithmetic_asked) == 1, note
    body = (_para("Shares below are weighted percentages of each group.")
            + f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
            f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    report = audit([_docx(tmp_path / "before.docx", body)], None)
    assert report.arithmetic_asked == [] and len(report.disagreements) == 1


@pytest.mark.parametrize(("crude", "weighted"), [("Before IPTW", "After IPTW"),
                                                 ("Unweighted n (%)", "Weighted %")])  # fmt: skip
def test_a_header_lets_off_its_column_alone(tmp_path: Path, crude: str, weighted: str) -> None:
    """A word of weighting in a column's header lets off that column, not the crude one
    beside it, in either order: each column's count is its own, so the share asked about is
    the weighted column's and the share found the crude one's (round 2 of #703)."""
    for crude_first in (True, False):
        cells = ("640 (58.0%)", "700 (62.0%)")
        heads = (crude, weighted) if crude_first else (weighted, crude)
        text = (f"# Results\n\nTable 1. Balance.\n\n| Characteristic | {heads[0]} (n = 1200) | "
                f"{heads[1]} (n = 1200) |\n|---|---|---|\n| Male sex, n (%) | {cells[0]} | "
                f"{cells[1]} |\n")  # fmt: skip
        report = audited(tmp_path, text)
        (found,), (question,) = report.disagreements, report.arithmetic_asked
        asked, kept = (cells[1], cells[0]) if crude_first else cells
        assert question.message.startswith("Table 1's column says its shares")
        assert f"). {asked} is not" in question.message, question.message
        assert found.message.startswith(f"n (%) {kept}"), found.message


def test_a_row_label_lets_off_its_row_alone(tmp_path: Path) -> None:
    """Round 2 of #703: a row labelled "Weighted n" lets off its own row; the crude column's
    share off its n in another row is still a finding."""
    text = ("# Results\n\nTable 1. Balance.\n\n| Characteristic | Before IPTW (n = 1200) | "
            "After IPTW (n = 1200) |\n|---|---|---|\n| Weighted n (%) | 600 (55.0%) | "
            "600 (55.0%) |\n| Male sex, n (%) | 640 (58.0%) | 700 (62.0%) |\n")  # fmt: skip
    report = audited(tmp_path, text)
    assert [(d.line, d.message.split(":")[0]) for d in report.disagreements] == [
        (8, "n (%) 640 (58.0%)")]
    assert sorted((d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked) == [
        (7, "Table 1's row"), (7, "Table 1's row"), (8, "Table 1's column")]


#: Two tables whose legends stand after them, the first said to be weighted.
LEGENDS_AFTER = ("# Results\n\nThe groups were compared.\n\n{table}\n\nTable 1. Weighted "
                 "percentages.\n\n{table}\n\nTable 2. Counts.\n\n# Discussion\n\nNo more.\n")
TABLE = "| Characteristic | Exposed (n = 1200) |\n|---|---|\n| Male sex, n (%) | 640 (58.0%) |"


def test_a_legend_after_its_table_is_its_own_and_no_caption_of_the_next(
    tmp_path: Path,
) -> None:
    """Round 2 of #703: where a file's legends stand after their tables, "Table 1. Weighted
    percentages." under the first table is its own; the second table's share, under "Table 2.
    Counts.", is a finding, and was asked about as Table 1's."""
    report = audited(tmp_path, LEGENDS_AFTER.format(table=TABLE))
    assert [(d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked] == [
        (7, "Table 1")]
    assert [d.line for d in report.disagreements] == [13]


def test_a_legend_after_its_table_is_its_own_in_a_docx(tmp_path: Path) -> None:
    table = (f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
             f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    body = (_para("Results") + _para("The groups were compared.") + table
            + _para("Table 1. Weighted percentages.") + table + _para("Table 2. Counts.")
            + _para("Discussion"))
    report = audit([_docx(tmp_path / "paper.docx", body)], None)
    assert len(report.disagreements) == 1 and len(report.arithmetic_asked) == 1
    assert report.arithmetic_asked[0].line < report.disagreements[0].line
    assert report.arithmetic_asked[0].message.startswith("Table 1 says")


def test_one_legend_for_two_tables_captions_only_the_table_under_it(tmp_path: Path) -> None:
    """One legend for two tables does not number them: it captions the table directly under
    it alone (Basile, 2026-11-21, "Adjacent fallback"), and the table above it, which it
    stands right after, keeps its share a finding."""
    text = f"# Results\n\n{TABLE}\n\nTable 2. Weighted percentages.\n\n{TABLE}\n"
    report = audited(tmp_path, text)
    assert [d.line for d in report.arithmetic_asked] == [11]
    assert [d.line for d in report.disagreements] == [5]


#: Legends before their tables, a subtitle between each and its table: the scoped check of
#: round 2 of #703, where Table 1 took Table 2's legend.
SUBTITLED_BEFORE = ("# Results\n\nTable 1. Counts.\n\nValues are n (%).\n\n{table}\n\nTable 2. "
                    "Weighted percentages.\n\nValues are n (%).\n\n{table}\n")
#: Legends after their tables, a subtitle between each table and its legend.
SUBTITLED_AFTER = ("# Results\n\nThe groups were compared.\n\n{table}\n\nValues are n (%).\n\n"
                   "Table 1. Weighted percentages.\n\n{table}\n\nValues are n (%).\n\n"
                   "Table 2. Counts.\n\n# Discussion\n\nNo more.\n")


def test_a_legend_captions_the_table_its_number_names(tmp_path: Path) -> None:
    """Basile, 2026-11-18, after the scoped check of round 2 of #703: "Table N" captions the
    Nth table, before it or after it, with paragraphs between but no table. Legends before
    their tables with a subtitle between: Table 1's share, under "Table 1. Counts.", is a
    finding, and was asked about under Table 2's legend; Table 2's, under "Table 2. Weighted
    percentages.", is asked about. Legends after their tables, the same."""
    report = audited(tmp_path, SUBTITLED_BEFORE.format(table=TABLE))
    assert [d.line for d in report.disagreements] == [9]
    assert [(d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked] == [
        (17, "Table 2")]
    report = audited(tmp_path, SUBTITLED_AFTER.format(table=TABLE))
    assert [(d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked] == [
        (7, "Table 1")]
    assert [d.line for d in report.disagreements] == [15]


def test_a_legend_captions_the_table_its_number_names_in_a_docx(tmp_path: Path) -> None:
    table = (f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
             f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    for paragraphs, weighted in (
            (["Table 1. Counts.", "Values are n (%).", table, "Table 2. Weighted percentages.",
              "Values are n (%).", table], 2),
            (["The groups were compared.", table, "Values are n (%).", "Table 1. Weighted "
              "percentages.", table, "Values are n (%).", "Table 2. Counts."], 1)):  # fmt: skip
        body = "".join(one if one.startswith("<w:tbl>") else _para(one) for one in paragraphs)
        report = audit([_docx(tmp_path / f"paper{weighted}.docx", body)], None)
        (found,), (asked,) = report.disagreements, report.arithmetic_asked
        assert asked.message.startswith(f"Table {weighted} says"), asked.message
        assert (asked.line > found.line) == (weighted == 2)


@pytest.mark.parametrize(("legends", "asked"), [
    # Three legends and two tables read: the third table given as a picture, its legend
    # below the last table.
    ("Table 1. Weighted percentages.\n\n{table}\n\nTable 2. Counts.\n\n{table}\n\nTable 3. "
     "Weighted n.\n", [7]),
    # A table that runs on under its legend again.
    ("Table 1. Weighted percentages.\n\n{table}\n\nTable 2. Counts.\n\n{table}\n\nTable 2 "
     "(continued)\n\n{table}\n", [7]),
    # Two forms of legend in one file.
    ("Table 1. Counts.\n\n{table}\n\nTable S1. Weighted percentages.\n\n{table}\n", [13]),
    # Legends that number the tables, one of which names no table it can reach.
    ("Table 2. Weighted percentages.\n\n{table}\n\nTable 1. Counts.\n\n{table}\n", []),
])  # fmt: skip
def test_legends_that_do_not_number_the_tables_caption_the_table_under_them(
    tmp_path: Path, legends: str, asked: list[int]
) -> None:
    """Where the file's legends do not number its tables 1 to the count read, in one form,
    each once, a legend directly above a table, with no paragraph between, captions it
    (Basile, 2026-11-21, "Adjacent fallback"): the weighted one's share is asked about, and a
    weighted legend below the last table captions nothing. Where they do, the numbering rule
    holds as it was: a legend that cannot reach the table its number names, another table
    between them, captions nothing, though it stands right above a table; the file's other
    legends still caption theirs ("Table 1. Counts." its table, in the last case)."""
    report = audited(tmp_path, "# Results\n\n" + legends.format(table=TABLE))
    assert [d.line for d in report.arithmetic_asked] == asked, report.arithmetic_asked
    assert len(report.disagreements) == legends.count("{table}") - len(asked)


#: A supplement whose legends do not number its tables, "a" and "b" of each number, each
#: right above its table.
SUPPLEMENT = ("# Supplementary material\n\nTable S1a. Nationally representative shares, Region "
              "A.\n\n{table}\n\nTable S1b. Proportions by group, Region A.\n\n{table}\n\nTable "
              "S2a. Nationally representative shares, Region B.\n\n{table}\n")  # fmt: skip


def test_a_nationally_representative_legend_right_above_its_table_asks_of_its_shares(
    tmp_path: Path,
) -> None:
    """docx-psych-B2's shape (Basile, 2026-11-21, "Caption wording" and "Adjacent
    fallback"): supplementary legends "Table S1a", "Table S1b", ... do not number the tables,
    and each stands right above its own. The "a" tables, nationally representative, have
    their shares asked about, named by their legends; the "b" table's share is a finding."""
    report = audited(tmp_path, SUPPLEMENT.format(table=TABLE))
    assert [(d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked] == [
        (7, "Table S1a"), (19, "Table S2a")]
    assert [d.line for d in report.disagreements] == [13]


def test_a_nationally_representative_legend_asks_in_a_docx(tmp_path: Path) -> None:
    table = (f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
             f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    body = (_para("Supplementary material")
            + _para("***Table S1a. Nationally representative shares, Region A.***") + table
            + _para("***Table S1b. Proportions by group, Region A.***") + table)
    report = audit([_docx(tmp_path / "paper.docx", body)], None)
    (asked,), (found,) = report.arithmetic_asked, report.disagreements
    assert asked.message.startswith("Table S1a says") and asked.line < found.line


@pytest.mark.parametrize("legends", [
    # A paragraph between the weighted legend and its table.
    "Table S1a. Nationally representative shares.\n\nValues are n (%).\n\n{table}\n\n"
    "Table S1b. Counts.\n\n{table}\n",
    # The weighted legend below the last table.
    "Table S1b. Counts.\n\n{table}\n\nThe next table follows.\n\n{table}\n\nTable S1a. "
    "Nationally representative shares.\n",
    # The weighted legend's words negated in their clause.
    "Table S1a. Shares, not nationally representative.\n\n{table}\n\nTable S1b. Counts.\n\n"
    "{table}\n",
    "Table S1a. Non-nationally representative shares.\n\n{table}\n\nTable S1b. Counts.\n\n"
    "{table}\n",
])  # fmt: skip
def test_under_the_fallback_a_legend_not_right_above_its_table_captions_nothing(
    tmp_path: Path, legends: str
) -> None:
    """The fallback reads only a legend directly above a table: one with a paragraph between,
    or one below a table, captions nothing, and a negated legend says nothing; each share is
    a finding."""
    report = audited(tmp_path, "# Results\n\n" + legends.format(table=TABLE))
    assert report.arithmetic_asked == [], report.arithmetic_asked
    assert len(report.disagreements) == 2


def test_under_the_fallback_a_legend_reaches_no_table_across_another(tmp_path: Path) -> None:
    """Round 1 of the review of #718: a legend above a table that another table follows
    with no paragraph between captions the first alone. The second table's share, under no
    legend of its own, is a finding, and the third's, under "Table S1b. Counts.", too."""
    report = audited(tmp_path, f"# Results\n\nTable S1a. Weighted percentages.\n\n{TABLE}\n\n"
                               f"{TABLE}\n\nTable S1b. Counts.\n\n{TABLE}\n")  # fmt: skip
    assert [(d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked] == [
        (7, "Table S1a")]
    assert [d.line for d in report.disagreements] == [11, 17]


def test_under_the_fallback_a_picture_s_legend_captions_the_table_under_it(
    tmp_path: Path,
) -> None:
    """The limit of the fallback in a .docx (DESIGN.md, Known gaps): a picture's paragraph
    has no text to read, so a legend over a table given as a picture, then a read table with
    no legend of its own, captions the read table. Its share is asked about on the picture's
    words."""
    table = (f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
             f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    picture = "<w:p><w:r><w:drawing/></w:r></w:p>"
    body = (_para("Results") + _para("Table S1a. Weighted percentages.") + picture + table
            + _para("Table S1b. Counts.") + table)
    report = audit([_docx(tmp_path / "paper.docx", body)], None)
    (asked,), (found,) = report.arithmetic_asked, report.disagreements
    assert asked.message.startswith("Table S1a says") and asked.line < found.line


def test_under_the_fallback_a_legend_below_a_table_captions_the_next(tmp_path: Path) -> None:
    """The limit of the fallback (DESIGN.md, Known gaps): in a file whose legends stand below
    their tables and do not number them, a legend below one table and directly above the
    next is read as the next table's, so the first table's weighted share stays a finding
    and the second's, which nothing says is weighted, is asked about."""
    report = audited(tmp_path, f"# Results\n\nThe tables follow.\n\n{TABLE}\n\nTable S1a. "
                               f"Weighted percentages.\n\n{TABLE}\n\nTable S1b. Counts.\n")
    assert [d.line for d in report.arithmetic_asked] == [13]
    assert [d.line for d in report.disagreements] == [7]


def test_a_legend_reaches_its_table_across_no_other_legend(tmp_path: Path) -> None:
    """Round 3 of #703: a legend of a table given as a picture, "Table 1. Weighted
    percentages.", then "Table 2. Counts." and its table, then a table with no legend. The
    legends number the two tables read, but neither reaches its own: the first table's,
    "Table 1", stands across "Table 2"'s legend, and "Table 2"'s across the first table. No
    share is let off. Legends before their tables, after them, and with a subtitle between
    caption as before."""
    text = (f"# Results\n\nTable 1. Weighted percentages.\n\nTable 2. Counts.\n\n{TABLE}\n\n"
            f"{TABLE}\n")
    report = audited(tmp_path, text)
    assert report.arithmetic_asked == [] and len(report.disagreements) == 2
    for shape, asked in ((SUBTITLED_BEFORE, 17), (SUBTITLED_AFTER, 7)):
        report = audited(tmp_path, shape.format(table=TABLE))
        assert [d.line for d in report.arithmetic_asked] == [asked]


#: A comment over three lines above the tables, and a paragraph between Table 1's legend and
#: its table that names the other table as weighted (round 3 of #703).
COMMENTED = ("# Results\n\n<!-- Draft\nfor co-authors\n-->\n\nTable 1. Counts.\n\nUnlike the "
             "survey-weighted Table 2, this table\ngives crude counts of\nthe 1200 patients.\n\n"
             "{table}\n\nTable 2. Weighted percentages.\n\nValues are n (%).\n\n{table}\n")


def test_legends_are_read_on_their_own_lines_below_a_comment(tmp_path: Path) -> None:
    """Round 3 of #703: legends were read on the mask, which keeps no line break of a
    comment, so below a comment of three lines every line was read two lines too early, and
    "Table 1. Counts." took the words of the paragraph under it, "survey-weighted". Table 1's
    share is a finding at line 15; Table 2's is asked about at line 23."""
    report = audited(tmp_path, COMMENTED.format(table=TABLE))
    assert [d.line for d in report.disagreements] == [15]
    assert [(d.line, d.message.split(" says")[0]) for d in report.arithmetic_asked] == [
        (23, "Table 2")]


def test_a_parenthesis_after_table_n_opens_a_legend_only_as_continued(tmp_path: Path) -> None:
    """Round 3 of #703: "Table 1 (weighted percentages) describes the cohort." is a sentence,
    not a legend; the table's caption is pandoc's, "Characteristics.", and its share a
    finding. "Table 2 (continued)" is a legend still, and breaks the numbering."""
    report = audited(tmp_path, f"Table 1 (weighted percentages) describes the cohort.\n\n{TABLE}"
                               "\n\nTable: Characteristics.\n")  # fmt: skip
    assert report.arithmetic_asked == [] and [d.line for d in report.disagreements] == [5]
    from manuscript_guard.auditing.adjusted import LEGEND

    assert LEGEND.match("Table 2 (continued)") and LEGEND.match("TABLE 2 (Continued).")
    assert not LEGEND.match("Table 1 (weighted percentages) describes the cohort.")


def test_pandoc_s_caption_counts_for_its_own_table(tmp_path: Path) -> None:
    """pandoc's caption, "Table: ...", is its table's, before it or after it, where no legend
    numbers the file's tables; and beside a legend that numbers them, both are the table's
    caption."""
    report = audited(tmp_path, f"# Results\n\n{TABLE}\n\nTable: Weighted percentages.\n")
    assert len(report.arithmetic_asked) == 1 and report.disagreements == []
    report = audited(tmp_path, f"# Results\n\nTable 1. Counts.\n\n{TABLE}\n\nTable: Weighted "
                               "percentages.\n")  # fmt: skip
    (asked,) = report.arithmetic_asked
    assert asked.message.startswith("Table 1 says") and report.disagreements == []


@pytest.mark.parametrize("after", ["*After inverse probability weighting, the groups were "
                                   "balanced.*", "**Table 2** weighted percentages"])
def test_emphasis_after_a_table_with_no_note_is_no_note(tmp_path: Path, after: str) -> None:
    """Round 2 of #703: an asterisk opens a note only before a space; emphasis glued to a word
    is no footnote's mark."""
    report = audited(tmp_path, f"# Results\n\nTable 1. Counts.\n\n{TABLE}\n\n{after}\n")
    assert report.arithmetic_asked == [] and len(report.disagreements) == 1


def test_a_docx_note_whose_raised_mark_runs_into_its_word_is_not_read(tmp_path: Path) -> None:
    """A footnote's raised mark in a .docx paragraph outside a table runs on into the next
    word as the reader reads it, "aPercentages are weighted.", so the note is not read and
    the share stays a finding (DESIGN.md, Known gaps); "a Percentages", typed with a space,
    is."""
    table = (f"<w:tbl>{_row('Characteristic', 'All (n = 1200)')}"
             f"{_row('Male sex, n (%)', '640 (58.0%)')}</w:tbl>")  # fmt: skip
    raised = ("<w:p><w:r><w:rPr><w:vertAlign w:val=\"superscript\"/></w:rPr><w:t>a</w:t></w:r>"
              "<w:r><w:t>Percentages are weighted.</w:t></w:r></w:p>")
    report = audit([_docx(tmp_path / "raised.docx", _para("Table 1. Counts.") + table
                          + raised)], None)  # fmt: skip
    assert report.arithmetic_asked == [] and len(report.disagreements) == 1
    report = audit([_docx(tmp_path / "typed.docx", _para("Table 1. Counts.") + table
                          + _para("a Percentages are weighted."))], None)  # fmt: skip
    assert len(report.arithmetic_asked) == 1


def test_a_latex_float_s_note_says_its_table_is_weighted(tmp_path: Path) -> None:
    """In LaTeX the float's text outside its table, its caption and its notes, is read: a
    float whose notes say its percentages are weighted has its share asked about; the same
    table in a float that says nothing keeps its finding."""
    table = ("\\begin{tabular}{ll}\nCharacteristic & Exposed (n = 1200) \\\\\n"
             "Male sex, n (\\%) & 640 (58.0\\%) \\\\\n\\end{tabular}\n")  # fmt: skip
    paper = tmp_path / "paper.tex"
    paper.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
        f"\\begin{{table}}\n\\caption{{Counts.}}\n{table}"
        "\\begin{flushleft}Note. Percentages are weighted.\\end{flushleft}\n\\end{table}\n"
        f"\\begin{{table}}\n\\caption{{Counts again.}}\n{table}\\end{{table}}\n"
        "\\end{document}\n", encoding="utf-8")  # fmt: skip
    report = audit([paper], None)
    assert len(report.arithmetic_asked) == 1 and len(report.disagreements) == 1
    assert report.arithmetic_asked[0].line < report.disagreements[0].line


# ----------------------------------------------------------- the report, its JSON and --strict


def test_the_questions_are_items_the_json_marks_and_strict_does_not_count(
    tmp_path: Path, capsys
) -> None:
    """Each is a question of the report's kind, INFO, never counted, `"question": true` in
    `--json`, counted by kind; `--strict` passes the paper, as it passes the same paper with
    no adjustment statement, whose P is then a warning it does not count either."""
    paper = tmp_path / "paper.md"
    paper.write_text("# Abstract\n\nWe compared two groups.\n\n" + ADJUSTED, encoding="utf-8")
    assert main(["audit", str(paper), "--strict", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    (asked,) = [f for f in said["findings"] if f["code"] == ASKED_ADJUSTED]
    assert asked["question"] is True and asked["counted"] is False
    assert asked["severity"] == INFO and asked["section"] == sections.ARITHMETIC
    assert said["counts"]["asked_p_adjusted"] == 1 and said["counts"]["asked_share_weighted"] == 0
    assert said["ok"] is True
    unadjusted = tmp_path / "unadjusted.md"
    unadjusted.write_text(paper.read_text(encoding="utf-8").replace(
        "adjusted for multiple comparisons by the Holm method", "computed"), encoding="utf-8")
    assert main(["audit", str(unadjusted), "--strict", "--json"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert not [f for f in plain["findings"] if f["code"] in (ASKED_ADJUSTED, ASKED_WEIGHTED)]
    fits = [f for f in plain["findings"] if f["code"] == "does-not-fit"]
    assert len(fits) == 3 and all(f["severity"] == WARN and not f["counted"] for f in fits)
    assert "asked_p_adjusted" not in plain["counts"]


def test_the_text_and_the_summary_say_the_questions(tmp_path: Path) -> None:
    """Under "Questions for the author", at their place; the Arithmetic line of "What was
    checked" counts them, its tile stands asked where nothing else is to say, and the page's
    `asked` names it."""
    from manuscript_guard.auditing.summary import ASKED, asked, standings

    report = audited(tmp_path, "# Methods\n\nAll P values were Holm-adjusted.\n\n# Results\n\n"
                               "The groups differed, t(23) = 2.71, P = 0.048.\n")  # fmt: skip
    text = sections.render(report, None)
    start, end = text.index(sections.QUESTIONS), text.index("What was checked:")
    assert f"paper.md:7: {LARGER[:40]}" in text[start:end].replace(
        "(\"All P values were Holm-adjusted.\", line 3)",
        "(\"P values were adjusted for multiple comparisons by the Holm method.\", line 3)")
    row = next(line for line in text.splitlines() if line.lstrip().startswith("Arithmetic"))
    assert "1 question for the author (not counted by --strict)" in row
    assert standings(report)["Arithmetic"] == ASKED
    assert asked(report) == {"Arithmetic": 1, "Abstract against Results": 1}
    view = sections.view(report, None)
    assert view["asked"]["Arithmetic"] == 1 and view["standing"]["Arithmetic"] == ASKED


def test_the_draft_says_the_question_in_a_referee_s_words(tmp_path: Path) -> None:
    """A referee's draft lists it among the further findings, the author asked, naming no
    answer to type; and its check is no check that found nothing."""
    from manuscript_guard.auditing import draft

    report = audited(tmp_path, ADJUSTED)
    said = draft.for_audit(report, [], lambda path: path.name)
    assert ("an adjustment makes a P larger: the author is asked whether it is the adjusted P"
            ) in said
    assert "- Tests, intervals and n (%) against the numbers beside them" not in said.split(
        "## Checks that ran and found nothing")[1]


# ------------------------------------------------------------------------------- check


def _sentence_in(project: Path, *sentences: str) -> Path:
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8")
    main_md.write_text(text + "\n" + "\n\n".join(sentences) + "\n", encoding="utf-8")
    return main_md


def _g8(project: Path):
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.gates import check_recomputed

    projekt, _ = load_project(project)
    namespace, results, _literature, _rest = load_namespace(projekt)
    return [f for f in check_recomputed(projekt, namespace, results).findings
            if f.code in ("p-inconsistent", "p-decision-error")]  # fmt: skip


def test_check_asks_of_a_larger_p_where_the_manuscript_adjusts(project: Path) -> None:
    """G8 in a project: the larger P is a question (`findings.Question`), its code kept, the
    smaller one a warning; with no statement both are warnings, and a covariate adjustment is
    none."""
    larger = "The arms differed, t(23) = 2.71, p = .048."
    smaller = "The arms differed again, t(23) = 2.71, p = .002."
    main_md = _sentence_in(project, "P values were adjusted for multiple comparisons by the "
                           "Holm method.", larger, smaller)  # fmt: skip
    found = _g8(project)
    asked = [f for f in found if f.question]
    (question,) = asked
    lines = main_md.read_text(encoding="utf-8").split("\n")
    at = next(n for n, line in enumerate(lines, 1) if "Holm method" in line)
    assert question.severity == INFO and question.code == "p-inconsistent"
    assert question.message.split(")")[0].endswith(f"line {at}"), (question.message, at)
    assert question.message.startswith(
        "The paper says its P values are adjusted (\"P values were adjusted for multiple "
        f"comparisons by the Holm method.\", line {at}). P = .048 is larger than the")
    assert "known" not in question.hint and "adjusted P = ..." in question.hint
    (warning,) = [f for f in found if not f.question]
    assert warning.severity == WARN and "P = .002" in warning.message


def test_check_with_a_covariate_adjustment_warns_of_both(project: Path) -> None:
    _sentence_in(project, "Models were adjusted for age and sex.",
                 "The arms differed, t(23) = 2.71, p = .048.",
                 "The arms differed again, t(23) = 2.71, p = .002.")  # fmt: skip
    found = _g8(project)
    assert len(found) == 2 and not any(f.question for f in found)


@pytest.mark.parametrize("said", NEGATED)
def test_check_warns_of_a_larger_p_where_the_statement_is_negated(project: Path,
                                                                 said: str) -> None:  # fmt: skip
    """Round 1 of #703: G8 gives `p-inconsistent` at WARN, as main does."""
    _sentence_in(project, said, "The arms differed, t(23) = 2.71, p = .048.")
    (found,) = [f for f in _g8(project) if "t(23) = 2.71" in (f.context or "")]
    assert (found.code, found.severity, found.question) == ("p-inconsistent", WARN, False)


def test_check_names_the_file_of_a_statement_in_another(project: Path) -> None:
    """A statement in the supplement holds for a test of the main text, said by its path in
    the project."""
    folder = project / "manuscript" / "supplementary"
    folder.mkdir(exist_ok=True)
    (folder / "S9.md").write_text("# Methods\n\nAll P values are Bonferroni-corrected.\n",
                                  encoding="utf-8")  # fmt: skip
    _sentence_in(project, "The arms differed, t(23) = 2.71, p = .048.")
    (question,) = [f for f in _g8(project) if f.question]
    assert ('("All P values are Bonferroni-corrected.", manuscript/supplementary/S9.md:3)'
            in question.message), question.message


def test_check_s_json_exit_code_and_next_carry_the_question(project: Path, capsys) -> None:
    """`--json` marks it `"question": true`; the exit code and the count of failures are
    those of the same paper with a covariate adjustment in place of the statement, whose P is
    a warning, one warning more; at submission too. `next --all` lists it, sent to
    results-binding."""

    def run(*flags: str) -> tuple[int, int, int, dict]:
        code = main(["check", str(project), *flags])
        out = capsys.readouterr().out
        main(["check", str(project), "--json", *flags])
        said = json.loads(capsys.readouterr().out)
        line = next(line for line in reversed(out.splitlines()) if " failing, " in line)
        failing, warnings = (int(part.split()[0]) for part in line.strip().split(", ")[:2])
        return code, failing, warnings, said

    main_md = _sentence_in(project, "Models were adjusted for age and sex.",
                           "The arms differed, t(23) = 2.71, p = .048.")  # fmt: skip
    text = main_md.read_text(encoding="utf-8")
    for flags in ((), ("--submission",)):
        main_md.write_text(text, encoding="utf-8")
        code, failing, warnings, said = run(*flags)
        assert not [f for f in said["findings"] if f.get("question") and f["gate"] == "G8"]
        main_md.write_text(text.replace("Models were adjusted for age and sex.", "P values were "
                                        "adjusted for multiple comparisons by the Holm method."),
                           encoding="utf-8")  # fmt: skip
        asked_code, asked_failing, asked_warnings, asked_said = run(*flags)
        (asked,) = [f for f in asked_said["findings"] if f["code"] == "p-inconsistent"]
        assert asked["question"] is True and asked["severity"] == "info"
        assert (asked_code, asked_failing, asked_warnings) == (code, failing, warnings - 1)
        assert asked_said["ok"] == said["ok"]
    assert main(["next", str(project), "--all"]) == 0
    out = capsys.readouterr().out
    assert "question for the author from G8" in out and "is larger than the" in out, out
