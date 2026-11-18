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
tbl_svysummary function", and its supplementary tables, whose shares are weighted, say so
only in a sentence of the Methods.
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
])  # fmt: skip
def test_a_covariate_adjustment_and_other_words_are_no_statement(said: str) -> None:
    """ "Adjusted for age and sex" names covariates, not an adjustment of P values."""
    assert adjustment(said) is None


@pytest.mark.parametrize("said", [
    "Weighted % of each category.", "Weighted percentages are shown.", "n (weighted %)",
    "Weighted n", "Survey-weighted proportions.", "Inverse probability weighted cohort.",
    "Data are IPW estimates.", "1Weighted statistics computed using the survey package.",
    "Percentages are weighted to the census.", "Weighted \\% of each category.",
])  # fmt: skip
def test_each_weighting_said_is_read(said: str) -> None:
    assert weighting(said) is not None, said


@pytest.mark.parametrize("said", [
    "Unweighted n (%).", "Weighted mean (SD).", "Weighted median.", "Population-weighted "
    "meta-analysis.", "Inverse-variance weighting.",
])  # fmt: skip
def test_an_estimate_weighted_and_unweighted_shares_are_no_weighting(said: str) -> None:
    assert weighting(said) is None, said


@pytest.mark.parametrize("said", [
    "P values were not adjusted for multiple comparisons.",
    "The Bonferroni correction was applied to the secondary outcomes only.",
    "The FDR of the classifier was 0.30.",
    "Outliers were found with Tukey's fences.",
])  # fmt: skip
def test_a_statement_is_read_by_its_words_alone(said: str) -> None:
    """The limits of exact words (DESIGN.md, Known gaps): a statement that no adjustment was
    made, one that adjusts some tests, and a name in another sense (tex-stat-ap-A2's false
    discovery rate of a classifier) are each read as a statement, and the paper's larger P
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
    assert asked.message.startswith("Table 1 says its shares are weighted (\"")
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
    """docx-psych-B2's supplementary tables: their shares are weighted, and only a sentence of
    the Methods says so ("weighted to be nationally representative"). No exact rule names a
    table from it, so each share off its n stays a finding (DESIGN.md, Known gaps)."""
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
