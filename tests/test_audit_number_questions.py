"""The questions the Abstract against Results asks of single numbers (Basile, 2026-11-16,
decision 27, part B): a number not found where the paper reports that a section reporting
nothing gives, the Introduction, the Discussion, a "Limitations" or a conclusion, is asked
about, not said not found; and a number of a structured Abstract's Background, looked for in
the Introduction too, found nowhere is asked about as the literature's. Each shape is a real
paper's of the corpus, written fresh."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from manuscript_guard import web
from manuscript_guard.audit import audit
from manuscript_guard.auditing import abstract, report
from manuscript_guard.auditing.abstract import Answers
from manuscript_guard.cli import main

BACKSLASH = chr(92)


def _write(folder: Path, text: str, suffix: str = ".md", name: str = "paper") -> Path:
    paper = folder / f"{name}{suffix}"
    paper.write_text(text, encoding="utf-8")
    return paper


def _found(capsys, paper: Path, *given: str) -> dict:
    assert main(["audit", str(paper), "--json", *given]) == 0
    return json.loads(capsys.readouterr().out)


def _line(text: str, words: str) -> int:
    """The line `words` open on, the last time they stand in `text`."""
    return text[: text.rindex(words)].count("\n") + 1


def _of(found: dict) -> list[dict]:
    return [one for one in found["findings"] if one["section"] == report.ABSTRACT]


#: The shape of docx-med-B1 of the real-paper corpus: the Introduction holds the study's own
#: design and population, which the Abstract repeats, and the Methods do not.
POPULATION = (
    "# A study of children\n\n## Abstract\n\nInvolving 51 educators and 391 children, the tool "
    "worked.\n\n## Introduction\n\nThe tool is new.\n\nThe population included 391 children "
    "and 51 educators from 32 schools.\n\n## Methods\n\nThe 51 educators rated them.\n\n"
    "## Results\n\nIt worked.\n\n## Discussion\n\nIt matters.\n"
)
#: The shape of docx-socio-A1: a sample size the Abstract gives, which the paper gives again
#: only in its Limitations.
LIMITED = (
    "# A study of dropout\n\n## Abstract\n\nIn a sample of 5000 individuals the model "
    "worked.\n\n## Methods\n\nWe fitted it.\n\n## Results\n\nIt worked.\n\n## Discussion\n\n"
    "It matters.\n\n## Limitations\n\nOnly a sub-sample of 5000 was used.\n"
)
#: The shape of docx-pharm-epi-B2: a structured Abstract's run-in Background gives figures
#: from the literature, a median survival and a share of the tumour, which the paper gives
#: nowhere else; one of them stands in a reference entry.
BACKGROUND = (
    "# Repurposing drugs\n\n## Abstract\n\nBackground: The tumour is lethal, with a median "
    "survival of 15 months. Macrophages make up 30-40% of its mass.\n\nMethods: We ranked "
    "812 drugs.\n\nResults: 812 drugs were ranked.\n\n## Introduction\n\nThe tumour is "
    "common.\n\n## Methods\n\nWe ranked 812 drugs.\n\n## Results\n\nIt held.\n\n"
    "## References\n\n1. Lim M. A review. Nat Rev Clin Oncol. 2018;15:422-442.\n"
)


def test_a_number_the_introduction_alone_gives_is_asked_about(tmp_path: Path, capsys) -> None:
    """docx-med-B1's "391": a question at the Abstract's number, at INFO, never counted, that
    names the Introduction and its line, and no warning that the number is not found."""
    paper = _write(tmp_path, POPULATION)
    found = _found(capsys, paper)
    said = _of(found)
    assert [(one["code"], one["question"], one["severity"], one["counted"], one["line"])
            for one in said] == [(abstract.ASKED_ONLY_IN, True, "info", False, 5)]
    message = said[0]["message"]
    at = _line(POPULATION, "The population")
    assert message.startswith(f'391 in the Abstract is found only under "Introduction" (line {at})')
    assert "Is that where the paper reports it, or is it background?" in message
    assert 'run `audit` again with `--results "Introduction"`' in message
    assert "otherwise give it in the Methods or the Results" in message
    assert found["counts"]["abstract_not_found"] == 0
    assert found["counts"]["abstract_asked_only_in"] == 1
    assert found["counts"]["abstract_asked_background"] == 0
    assert main(["audit", str(paper), "--strict"]) == 0
    capsys.readouterr()


def test_the_introduction_given_as_the_results_ends_the_question(tmp_path: Path, capsys) -> None:
    """The answer the question names: `--results "Introduction"`, and the number is found
    there, said in a note as part A says it (#697)."""
    paper = _write(tmp_path, POPULATION)
    said = _of(_found(capsys, paper, "--results", "Introduction"))
    assert [one["code"] for one in said] == [abstract.LIFTED]
    read = audit([paper], None, answers=Answers(results=("Introduction",))).abstract
    assert read.matched == read.numbers and not read.only_in


def test_a_number_a_limitations_alone_gives_is_asked_about(tmp_path: Path, capsys) -> None:
    """docx-socio-A1's "5000", given again only in its Limitations."""
    said = _of(_found(capsys, _write(tmp_path, LIMITED)))
    assert [one["code"] for one in said] == [abstract.ASKED_ONLY_IN]
    at = _line(LIMITED, "Only a sub-sample")
    wanted = f'5000 in the Abstract is found only under "Limitations" (line {at})'
    assert wanted in said[0]["message"]
    assert '`--results "Limitations"`' in said[0]["message"]


def test_each_section_a_number_stands_in_is_named_with_its_first_line(
    tmp_path: Path, capsys
) -> None:
    """docx-socio-A1's "5000" stands in its Introduction and its Limitations: both, each by
    its first line, and the answer for either."""
    text = LIMITED.replace("## Methods", "## Introduction\n\nA 5000 sample.\n\nOf 5000, all.\n\n"
                           "## Methods")
    message = _of(_found(capsys, _write(tmp_path, text)))[0]["message"]
    first, last = _line(text, "A 5000 sample"), _line(text, "Only a sub-sample")
    assert (f'found only under "Introduction" (line {first}) and under "Limitations" '
            f"(line {last})") in message, message
    assert '`--results "Introduction"` or `--results "Limitations"`' in message


def test_a_limitations_under_the_discussion_names_both_headings(tmp_path: Path, capsys) -> None:
    """Under the Discussion, a "Limitations" is searched only with both named: the answer
    names both."""
    text = LIMITED.replace("## Limitations", "### Limitations")
    message = _of(_found(capsys, _write(tmp_path, text)))[0]["message"]
    assert f'under "Discussion", "Limitations" (line {_line(text, "Only")})' in message, message
    assert '`--results "Discussion" --results "Limitations"`' in message


@pytest.mark.parametrize("where", ["## Conclusions", "## Related work", "## Discussion"])
def test_the_discussion_a_conclusion_and_the_introduction_s_material_are_asked_about(
    tmp_path: Path, capsys, where: str
) -> None:
    text = POPULATION.replace("## Introduction", where)
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [one["code"] for one in said] == [abstract.ASKED_ONLY_IN], (where, said)
    assert f'under "{where[3:]}"' in said[0]["message"]


@pytest.mark.parametrize("where", ["## Funding", "## Author summary", "## Keywords"])
def test_a_number_a_statement_or_a_summary_alone_gives_stays_not_found(
    tmp_path: Path, capsys, where: str
) -> None:
    """The statements, a summary of the paper and the keywords are no section a paper reports
    in: a number found only there stays not found, a warning."""
    text = POPULATION.replace("## Introduction", where)
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [(one["code"], one["severity"]) for one in said] == [("abstract-not-found", "warn")]


def test_a_number_a_reference_entry_alone_gives_stays_not_found(tmp_path: Path, capsys) -> None:
    """docx-pharm-epi-B2's "15" stands in a reference entry, "2018;15:422", which counts for
    nothing: outside the Background it is not found, and in it the Background's question is
    asked."""
    text = BACKGROUND.replace("Background: ", "")
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [(one["code"], one["message"].split()[0]) for one in said] == [
        ("abstract-not-found", "15"), ("abstract-not-found", "30-40%")]


def test_a_title_page_s_number_stays_not_found(tmp_path: Path, capsys) -> None:
    text = POPULATION.replace("## Abstract", "Of 391 authors.\n\n## Abstract").replace(
        "The population included 391 children", "The population included the children")
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [one["code"] for one in said] == ["abstract-not-found"]


def test_a_background_figure_found_nowhere_is_asked_about(tmp_path: Path, capsys) -> None:
    """docx-pharm-epi-B2's "15" and "30-40%": in the Abstract's Background, given nowhere
    else, each a question that asks whether it is the literature's."""
    found = _found(capsys, _write(tmp_path, BACKGROUND))
    said = _of(found)
    assert [(one["code"], one["question"], one["severity"], one["counted"], one["message"])
            for one in said] == [
        (abstract.ASKED_BACKGROUND, True, "info", False, abstract.ASK_BACKGROUND.format(number))
        for number in ("15", "30-40%")]  # fmt: skip
    assert said[0]["message"] == ("15 in the Abstract's Background is given nowhere in the "
                                  "paper. Is it from the literature? The Introduction should "
                                  "give it, with its source.")
    assert found["counts"]["abstract_asked_background"] == 2
    assert found["counts"]["abstract_not_found"] == 0


def test_a_background_figure_the_introduction_gives_is_found(tmp_path: Path, capsys) -> None:
    """The answer to the Background's question is the paper's change: the Introduction gives
    the figure, with its source, and it is found there; no question is asked. A figure of the
    Background the Discussion alone gives is asked about as any number found only there."""
    text = BACKGROUND.replace("The tumour is\ncommon.", "The tumour is common.").replace(
        "The tumour is common.",
        "The median survival is 15 months [1]. Macrophages make up 30-40% of it [2].")
    paper = _write(tmp_path, text)
    assert _of(_found(capsys, paper)) == []
    read = audit([paper], None).abstract
    assert read.matched == read.numbers and not read.unsourced
    moved = text.replace("## Introduction", "## Discussion")
    said = _of(_found(capsys, _write(tmp_path, moved)))
    assert [one["code"] for one in said] == [abstract.ASKED_ONLY_IN] * 2


@pytest.mark.parametrize("label", ["Background:", "**Background:**", "BACKGROUND:",
                                   "Context.", "Objectives:", "Background and aims:"])  # fmt: skip
def test_each_name_of_the_background_is_read_as_its_label(
    tmp_path: Path, capsys, label: str
) -> None:
    text = BACKGROUND.replace("Background:", label)
    assert [one["code"] for one in _of(_found(capsys, _write(tmp_path, text)))] == [
        abstract.ASKED_BACKGROUND] * 2, label


def test_a_background_under_its_own_heading_in_the_abstract_is_read_as_one(
    tmp_path: Path, capsys
) -> None:
    text = BACKGROUND.replace("Background: ", "### Background\n\n").replace(
        "Methods: We", "### Methods\n\nWe")
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [one["code"] for one in said] == [abstract.ASKED_BACKGROUND] * 2


def test_the_parts_after_the_background_are_read_as_now(tmp_path: Path, capsys) -> None:
    """docx-sport-A3's Abstract is one paragraph, "Background: ... Methods: ... Results:
    ...": a number of its Results is no Background figure, and found nowhere is not found."""
    text = ("# A study\n\n## Abstract\n\nBackground: It is unclear. Methods: Thirty men took "
            "part. Results: It fell by 14% and by 18.5%. Conclusions: It matters.\n\n"
            "## Introduction\n\nIt is unclear, by 14% [14].\n\n## Methods\n\nThirty men.\n\n"
            "## Results\n\nIt fell.\n")
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [(one["code"], one["message"].split()[0]) for one in said] == [
        (abstract.ASKED_ONLY_IN, "14%"), ("abstract-not-found", "18.5%")]


def test_a_latex_background_the_introduction_gives_is_found(tmp_path: Path, capsys) -> None:
    """tex-stat-ap-B2's Abstract opens on `\\textbf{Background:}` with the WHO's count of
    deaths, which its Introduction gives with its source: found, and no question asked."""
    text = ("!documentclass{article}\n!begin{document}\n!begin{abstract}\n!textbf{Background:} "
            "More than 700,000 died in 2021.\n\n!textbf{Methods:} We fitted 12 models.\n"
            "!end{abstract}\n!section{Introduction}\nMore than 700,000 died in 2021 (WHO).\n"
            "!section{Methods}\nWe fitted 12 models.\n!section{Results}\nIt held.\n"
            "!end{document}\n").replace("!", BACKSLASH)
    paper = _write(tmp_path, text, ".tex")
    assert _of(_found(capsys, paper)) == []
    without = _write(tmp_path, text.replace("More than 700,000 died in 2021 (WHO).", "It is."),
                     ".tex", "other")  # fmt: skip
    assert [one["code"] for one in _of(_found(capsys, without))] == [abstract.ASKED_BACKGROUND] * 2


def test_the_text_report_lists_the_questions_apart_and_counts_them(
    tmp_path: Path, capsys
) -> None:
    paper = _write(tmp_path, POPULATION)
    assert main(["audit", str(paper)]) == 0
    text = capsys.readouterr().out
    asked, checked = text.index(report.QUESTIONS), text.index("What was checked:")
    assert "391 in the Abstract is found only under" in text[asked:checked]
    assert '0 not found, 1 asked of the author (under "Questions for the author").' in text
    assert "0 not found; 1 asked of the author" in text
    assert "NOT FOUND IN" not in text


def test_the_page_asks_in_its_own_words(tmp_path: Path, monkeypatch) -> None:
    """On the page, the answer is the heading given in its field, and no flag is named; a
    pair of headings, one under the other, is said as the command line says it (DESIGN.md,
    "Known gaps")."""
    from manuscript_guard.auditing.reader import RESULTS_FIELD, for_a_reader

    monkeypatch.chdir(tmp_path)
    _write(tmp_path, LIMITED.replace("## Methods", "## Introduction\n\nA 5000 one.\n\n## Methods"))
    result = web.view(["audit", "paper.md"])
    drawn = " ".join(said for _heading, notes in result["view"]["notes"] for said in notes)
    assert not re.search(r"--results|`audit`", drawn), drawn
    assert (f'check it again with "Introduction" given as "{RESULTS_FIELD}" or "Limitations" '
            f'given as "{RESULTS_FIELD}"') in drawn, drawn
    pair = abstract.asked_only_in("5000", [(("Discussion", "Limitations"), "line 3")])
    assert '--results "Discussion" --results "Limitations"' in for_a_reader(pair, page=True)


def test_a_draft_leaves_the_questions_out_and_the_pdf_and_the_copy_ask_them(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """`--report-draft` is a referee's, and asks the author nothing; `--pdf` and the
    `--commented` copy ask, the copy at the Abstract's number."""
    from test_audit_commented import docx
    from test_audit_questions import _comments, _pdf_text

    from manuscript_guard.auditing.commented import QUESTION

    monkeypatch.chdir(tmp_path)
    paper = _write(tmp_path, POPULATION)
    assert main(["audit", str(paper), "--report-draft", "draft.md", "--pdf", "report.pdf"]) == 0
    capsys.readouterr()
    assert "391 in the Abstract is found only" not in (tmp_path / "draft.md").read_text("utf-8")
    assert "391 in the Abstract is found only" in _pdf_text(tmp_path / "report.pdf")
    body = "".join(
        f"<w:p>{style}<w:r><w:t xml:space='preserve'>{said}</w:t></w:r></w:p>"
        for style, said in (("<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>", "Abstract"),
                            ("", "Of the 391 children, all took part."),
                            ("<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>", "Introduction"),
                            ("", "The population included 391 children."),
                            ("<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>", "Methods"),
                            ("", "We rated them."),
                            ("<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>", "Results"),
                            ("", "It worked.")))  # fmt: skip
    word = docx(tmp_path / "paper.docx", body)
    assert main(["audit", str(word), "--commented", "commented.docx"]) == 0
    capsys.readouterr()
    said = [one for one in _comments(tmp_path / "commented.docx") if one.startswith(QUESTION)]
    assert len(said) == 1 and '"Introduction" (Introduction, paragraph 1)' in said[0], said


def test_a_number_in_another_file_is_named_by_its_file(tmp_path: Path) -> None:
    """A paper split into files: the number stands only in the Introduction of another file
    with an Abstract of its own, named by the file and its line."""
    main_paper = _write(tmp_path, POPULATION.replace(
        "The population included 391 children", "The population included the children"))
    other = _write(tmp_path, "## Abstract\n\nIt.\n\n## Introduction\n\nOf 391 children.\n\n"
                   "## Results\n\nIt.\n", name="other")
    asked = [item.message for item in report.items(audit([main_paper, other], None))
             if item.code == abstract.ASKED_ONLY_IN]
    assert len(asked) == 1 and '"Introduction" (other.md:7)' in asked[0], asked
