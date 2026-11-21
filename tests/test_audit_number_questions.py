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
    in: a number found only there stays not found, a note (`auditing.measured`)."""
    text = POPULATION.replace("## Introduction", where)
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [(one["code"], one["severity"]) for one in said] == [("abstract-not-found", "info")]


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
    assert '0 not found, 1 question for the author (under "Questions for the author").' in text
    # The summary says the questions open, not "clear" (Basile, 2026-11-17).
    assert "0 not found; 1 question for the author (not counted by --strict)" in text
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


def test_a_draft_says_what_the_author_is_asked_and_the_pdf_and_the_copy_ask_it(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Round 1 of #700: `--report-draft`, a referee's, says each question asked of a number
    in a referee's words, the number and where it stands, that the author is asked, and no
    flag; its Abstract row counts it. Left out, the "391" base listed as not found vanished
    and the draft looked clean. `--pdf` and the `--commented` copy ask, the copy at the
    Abstract's number, and the PDF's tile says the question open."""
    from test_audit_commented import docx
    from test_audit_questions import _comments, _pdf_text

    from manuscript_guard.auditing.commented import QUESTION

    monkeypatch.chdir(tmp_path)
    paper = _write(tmp_path, POPULATION)
    assert main(["audit", str(paper), "--report-draft", "draft.md", "--pdf", "report.pdf"]) == 0
    capsys.readouterr()
    draft = (tmp_path / "draft.md").read_text("utf-8")
    assert ('391 in the Abstract is found only under "Introduction" (line '
            in draft), draft  # fmt: skip
    assert ("the author is asked whether the paper reports it there or gives it as "
            "background") in draft
    assert "--results" not in draft and "`audit`" not in draft
    assert "Abstract against Results:" not in draft.split("## Checks that ran")[1]
    background = _write(tmp_path, BACKGROUND, name="bg")
    assert main(["audit", str(background), "--report-draft", "background.md"]) == 0
    capsys.readouterr()
    draft = (tmp_path / "background.md").read_text("utf-8")
    assert abstract.REFEREE_BACKGROUND.format("15") in draft
    assert abstract.ASK_BACKGROUND.format("15") not in draft
    pdf = _pdf_text(tmp_path / "report.pdf")
    assert "391 in the Abstract is found only" in pdf and "1 QUESTION " in pdf
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


# ------------------------------------------------------------------------- round 1 of #700

#: The shape of a JAMA Abstract: its Objective, then labels the audit's list of part names
#: does not hold, the study's own numbers under them.
JAMA = ("# A cohort\n\n## Abstract\n\nObjective: To assess mortality. LABEL A cohort of 1,248 "
        "adults. Results: Mortality fell.\n\n## Methods\n\nWe enrolled 1,284 adults.\n\n"
        "## Results\n\nMortality fell.\n")


@pytest.mark.parametrize("label", [
    "Design, Setting, and Participants:", "Exposures:", "Main Outcomes and Measures:",
    "Study design:", "**Design, Setting, and Participants:**", "Methods:", "Findings:",
    "DESIGN, SETTING, AND PARTICIPANTS:",
])  # fmt: skip
def test_a_background_ends_at_the_next_label_of_any_wording(
    tmp_path: Path, capsys, label: str
) -> None:
    """Round 1 of #700: the Background ran on to the next label of the closed list, and
    JAMA's are not on it, so the study's own "1,248", given nowhere, was asked about as the
    literature's and its warning lost. It ends at the next run-in label of any wording."""
    said = _of(_found(capsys, _write(tmp_path, JAMA.replace("LABEL", label))))
    assert [(one["code"], one["message"].split()[0]) for one in said] == [
        ("abstract-not-found", "1,248")], (label, said)


def test_a_background_figure_rounded_in_the_introduction_is_found_as_a_rounding(
    tmp_path: Path, capsys
) -> None:
    """Round 1 of #700: a Background's "15" the Introduction gives as "15.2", and the
    Discussion as printed, is a rounding found in the Introduction, not a question naming
    the Discussion."""
    text = BACKGROUND.replace("The tumour is\ncommon.", "The tumour is common.").replace(
        "The tumour is common.", "The median survival is 15.2 months [1].").replace(
        "Macrophages make up 30-40% of its mass.", "It is common.") + (
        "\n## Discussion\n\nIt was 15 months.\n")  # fmt: skip
    read = audit([_write(tmp_path, text)], None).abstract
    assert [c.text for c in read.rounded] == ["15"] and not read.only_in, read


def test_a_number_s_part_found_elsewhere_is_left_out_of_its_question(
    tmp_path: Path, capsys
) -> None:
    """Round 1 of #700: where the Methods give "30" of "30-40%" and the Discussion alone
    "40%", the question names the part that stands only there."""
    text = ("# A study\n\n## Abstract\n\nIt was 30-40% here.\n\n## Methods\n\nWe had 30.\n\n"
            "## Results\n\nIt held.\n\n## Discussion\n\nUp to 40% of them.\n")
    said = _of(_found(capsys, _write(tmp_path, text)))
    assert [one["code"] for one in said] == [abstract.ASKED_ONLY_IN], said
    assert said[0]["message"].startswith(
        'Of 30-40% in the Abstract, 40 is found only under "Discussion"'), said[0]["message"]


def test_two_parts_found_only_elsewhere_take_a_plural_verb() -> None:
    """Round 2 of #700: where two of a number's parts stand only in a section that reports
    nothing, the question says they "are" found there, as the draft does."""
    places = [(("Discussion",), "line 9")]
    for said in (abstract.asked_only_in("X", places, ("A", "B")),
                 abstract.referee_only_in("X", places, ("A", "B"))):  # fmt: skip
        assert said.startswith('Of X in the Abstract, A and B are found only under'), said
    assert abstract.asked_only_in("X", places, ("A",)).startswith(
        "Of X in the Abstract, A is found only under")


def test_a_heading_given_already_is_named_again_with_the_one_under_it(
    tmp_path: Path, capsys
) -> None:
    """Round 1 of #700: with `--results "Discussion"`, a "Limitations" under it is still
    searched for nothing; the question names both, not "Limitations" alone, whose answer
    then asked for "Discussion" again."""
    paper = _write(tmp_path, LIMITED.replace("## Limitations", "### Limitations"))
    said = _of(_found(capsys, paper, "--results", "Discussion"))
    asked = [one["message"] for one in said if one["code"] == abstract.ASKED_ONLY_IN]
    assert len(asked) == 1 and '`--results "Discussion" --results "Limitations"`' in asked[0]
    said = _of(_found(capsys, paper, "--results", "Discussion", "--results", "Limitations"))
    assert abstract.ASKED_ONLY_IN not in [one["code"] for one in said]


def test_a_word_introduction_with_no_heading_under_its_keywords_counts_for_nothing(
    tmp_path: Path, capsys
) -> None:
    """The Known gap as it stands in Word: an Introduction with no heading of its own, under
    the run-in "Keywords:" that ends the Abstract, counts for nothing, and its number is not
    found, not asked about."""
    from test_audit import heading, make_docx, para

    body = (heading("Abstract") + para("Of 391 children, all took part.")
            + para("Keywords: falls; children") + para("The population included 391 children.")
            + heading("Methods") + para("We rated them.") + heading("Results")
            + para("It worked."))  # fmt: skip
    said = _of(_found(capsys, make_docx(tmp_path / "paper.docx", body)))
    assert [one["code"] for one in said] == ["abstract-not-found"], said


def test_the_summary_says_the_questions_open_instead_of_clear(
    tmp_path: Path, monkeypatch
) -> None:
    """Basile, 2026-11-17, "Show the questions": the Abstract against Results stands
    `ASKED` where it asks and has nothing else to say, its tile saying how many, on the
    page and in the PDF; part A's questions too, where they stand alone. A question still
    never fails --strict."""
    from test_audit_questions import UNLABELLED

    from manuscript_guard.auditing.report_pdf import asked_words
    from manuscript_guard.auditing.summary import ASKED, LOOK, asked, standings

    monkeypatch.chdir(tmp_path)
    # With whether G14 asks of the paper's short forms never defined: UNLABELLED's OR and CI.
    for text, count, words in ((POPULATION, 1, 0), (BACKGROUND, 2, 0), (UNLABELLED, 1, 1)):
        paper = _write(tmp_path, text)
        found = audit([paper], None)
        assert standings(found)["Abstract against Results"] == ASKED, text
        assert asked(found) == {"Abstract against Results": count}
        view = web.view(["audit", "paper.md"])["view"]
        assert view["standing"]["Abstract against Results"] == ASKED
        # And G14's question on the short forms never defined, where the paper has one, is
        # counted for the words (decision 30).
        assert view["asked"] == {"Abstract against Results": count,
                                 **({"Writing and language": words} if words else {})}
        line = dict(view["checks"])["Abstract against Results"]
        assert line.endswith(f"{count} question{'s' if count > 1 else ''} for the author"), line
        assert main(["audit", str(paper), "--strict"]) == 0
    assert asked_words(1) == "1 QUESTION" and asked_words(2) == "2 QUESTIONS"
    # Beside a number not found, the tile is to look at, and its line counts the question.
    both = _write(tmp_path, POPULATION.replace("51 educators and", "51 educators, 17 aides and"))
    found = audit([both], None)
    assert standings(found)["Abstract against Results"] == LOOK
