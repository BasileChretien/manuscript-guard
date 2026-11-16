"""The audit's questions to the author (Basile, 2026-11-16, decision 27): where no exact rule
can decide, a finding of its own kind that never fails a build says what it saw, asks one
question and names the answer that ends it. The first two are the Abstract against Results'
"no Abstract found" and "no Results found", answered by `--no-abstract`, `--results TITLE`
and `--no-results` (`auditing.abstract.Answers`)."""

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

#: A paper with an Abstract and its results under a descriptive title, no heading the
#: Results by name: the shape of tex-astro-ga-B2 of the real-paper corpus, whose results
#: stand under "Electron temperature relations" and its subsections. Its Abstract's
#: interval differs from the one reported there in one number.
DESCRIPTIVE = (
    "!documentclass{article}\n!begin{document}\n!begin{abstract}\n"
    "The OR was 1.52 (95!% CI 1.21--1.90).\n!end{abstract}\n"
    "!section{Introduction}\nIt matters.\n!section{Data}\nWe took it.\n"
    "!section{Electron temperature relations}\n!subsection{Electron temperature measurements}\n"
    "The OR was 1.52 (95!% CI 1.21--1.89).\n"
    "!section{Summary and discussion}\nIt was so.\n!end{document}\n"
).replace("!", chr(92))
#: The same paper in Markdown with no heading over its Abstract, which opens the paper.
UNLABELLED = (
    "# A study of temperatures\n\nThe OR was 1.52 (95% CI 1.21-1.90).\n\n"
    "## Methods\n\nWe took it.\n\n## Results\n\nThe OR was 1.52 (95% CI 1.21-1.89).\n"
)
#: A paper whose Abstract and Results are named.
NAMED = (
    "# A study\n\n## Abstract\n\nThe OR was 1.52 (95% CI 1.21-1.90).\n\n"
    "## Methods\n\nWe took it.\n\n## Results\n\nThe OR was 1.52 (95% CI 1.21-1.89).\n"
)


def _write(folder: Path, text: str, suffix: str = ".md") -> Path:
    paper = folder / f"paper{suffix}"
    paper.write_text(text, encoding="utf-8")
    return paper


def _findings(capsys, paper: Path, *given: str) -> list[dict]:
    assert main(["audit", str(paper), "--json", *given]) == 0
    return json.loads(capsys.readouterr().out)["findings"]


def _of(found: list[dict], section: str = report.ABSTRACT) -> list[dict]:
    return [one for one in found if one["section"] == section]


def test_no_abstract_heading_is_a_question_its_answer_ends(tmp_path: Path, capsys) -> None:
    """docx-educ-A2 and pdf-educ-B2 have no Abstract, pdf-socio-A3 and pdf-sport-A1 one with
    no label: either way the audit asks, at INFO, never counted, marked as a question in the
    JSON; `--no-abstract` ends the question, and the report says once, as a plain note, that
    the author says there is none."""
    paper = _write(tmp_path, UNLABELLED)
    asked = _of(_findings(capsys, paper))
    assert [(one["code"], one["question"], one["severity"], one["counted"])
            for one in asked] == [(abstract.ASKED_NO_ABSTRACT, True, "info", False)]
    assert asked[0]["message"] == abstract.ASK_NO_ABSTRACT
    assert "--no-abstract" in asked[0]["message"] and 'heading "Abstract"' in asked[0]["message"]
    answered = _of(_findings(capsys, paper, "--no-abstract"))
    assert [(one["code"], one["question"], one["message"]) for one in answered] == [
        ("abstract-not-compared", False, f"not compared: {abstract.SAID_NO_ABSTRACT}")]
    assert main(["audit", str(paper), "--no-abstract"]) == 0
    text = capsys.readouterr().out
    assert report.QUESTIONS not in text and text.count(abstract.SAID_NO_ABSTRACT) == 1


def test_a_paper_with_an_abstract_answered_as_having_none_is_compared_as_usual(
    tmp_path: Path, capsys
) -> None:
    """The paper's own heading wins over a contradicting answer, and the report says so as a
    plain note: never silently either way."""
    paper = _write(tmp_path, NAMED)
    found = _findings(capsys, paper, "--no-abstract")
    codes = [one["code"] for one in _of(found)]
    assert abstract.CONTRADICTED in codes and "abstract-conflict" in codes
    assert not any(one["question"] for one in found)
    assert main(["audit", str(paper), "--no-abstract", "--strict"]) == 1
    text = capsys.readouterr().out
    assert report.ANSWERS in text and "--no-abstract: a heading names the Abstract" in text


def test_no_results_heading_is_a_question_and_a_title_given_ends_it(
    tmp_path: Path, capsys
) -> None:
    """tex-astro-ga-B2 puts its results under "Electron temperature relations": the audit
    asks which heading holds them; given it with `--results`, as its case and a number
    before it allow, the Abstract is compared there, and its interval that differs fails
    --strict, where without the answer it was not compared."""
    paper = _write(tmp_path, DESCRIPTIVE, ".tex")
    asked = _of(_findings(capsys, paper))
    assert [(one["code"], one["question"]) for one in asked] == [
        (abstract.ASKED_NO_RESULTS, True)]
    assert '--results "<that heading>"' in asked[0]["message"]
    assert "--no-results" in asked[0]["message"]
    assert main(["audit", str(paper), "--strict"]) == 0
    capsys.readouterr()
    for title in ("Electron temperature relations", "3. ELECTRON TEMPERATURE RELATIONS"):
        found = _findings(capsys, paper, "--results", title)
        assert [one["code"] for one in _of(found)] == ["abstract-conflict"], title
        assert main(["audit", str(paper), "--strict", "--results", title]) == 1
        capsys.readouterr()


def test_a_results_title_that_names_no_heading_is_said(tmp_path: Path, capsys) -> None:
    """A title `--results` gives that no heading has is a plain note naming it, and the
    question is still asked; one whose heading stands where the paper reports nothing, under
    the Discussion, is said too, and never passed over."""
    paper = _write(tmp_path, DESCRIPTIVE, ".tex")
    found = _of(_findings(capsys, paper, "--results", "Findings of note"))
    said = {one["code"]: one["message"] for one in found}
    assert said[abstract.UNMATCHED] == ('--results "Findings of note": no heading is '
                                        '"Findings of note"')
    assert abstract.ASKED_NO_RESULTS in said
    # Beside a title that is found, the one that is not is still said.
    found = _of(_findings(capsys, paper, "--results", "Findings of note", "--results", "Data"))
    assert [one["code"] for one in found] == [abstract.UNMATCHED, "abstract-conflict"]
    under = DESCRIPTIVE.replace(chr(92) + "section{Electron", chr(92) + "subsection{Electron")
    under = under.replace(chr(92) + "section{Data}", chr(92) + "section{Discussion}")
    found = _of(_findings(capsys, _write(tmp_path, under, ".tex"), "--results",
                          "Electron temperature relations"))
    assert abstract.NOT_TAKEN in [one["code"] for one in found]


def test_a_paper_that_reports_no_results_is_answered_so(tmp_path: Path, capsys) -> None:
    """tex-cs-lg-A2, tex-econ-em-B2 and tex-stat-ap-A2 are methods papers: `--no-results`
    ends the question, said once; on a paper with a Results heading it is contradicted, said,
    and the Abstract compared as usual."""
    paper = _write(tmp_path, DESCRIPTIVE, ".tex")
    found = _of(_findings(capsys, paper, "--no-results"))
    assert [(one["code"], one["message"]) for one in found] == [
        ("abstract-not-compared", f"not compared: {abstract.SAID_NO_RESULTS}")]
    found = _of(_findings(capsys, _write(tmp_path, NAMED), "--no-results"))
    assert [one["code"] for one in found] == [abstract.CONTRADICTED, "abstract-conflict"]


def test_a_question_is_marked_in_the_json_and_no_other_finding_is(tmp_path: Path, capsys) -> None:
    found = _findings(capsys, _write(tmp_path, UNLABELLED))
    assert all("question" in one for one in found)
    assert [one["code"] for one in found if one["question"]] == [abstract.ASKED_NO_ABSTRACT]


def test_the_text_report_shows_the_questions_apart(tmp_path: Path, capsys) -> None:
    """Under a heading of their own, before what each check found, and the notes on the
    answers under another."""
    paper = _write(tmp_path, DESCRIPTIVE, ".tex")
    assert main(["audit", str(paper), "--results", "Nothing like it"]) == 0
    text = capsys.readouterr().out
    asked, answers, checked = (text.index(report.QUESTIONS), text.index(report.ANSWERS),
                               text.index("What was checked:"))  # fmt: skip
    assert asked < answers < checked
    block = text[asked:answers]
    assert abstract.ASK_NO_RESULTS in block
    assert '--results "Nothing like it": no heading is "Nothing like it"' in text[answers:checked]


def test_the_page_and_the_pdf_ask_in_the_page_s_words(tmp_path: Path, monkeypatch) -> None:
    """The view the page and the PDF draw names no flag: each question points at the page's
    box or tick for its answer (`reader.for_a_reader`)."""
    from manuscript_guard.auditing.reader import NO_ABSTRACT_FIELD, NO_RESULTS_FIELD, RESULTS_FIELD

    monkeypatch.chdir(tmp_path)
    _write(tmp_path, UNLABELLED)
    (tmp_path / "other.tex").write_text(DESCRIPTIVE, encoding="utf-8")
    flags = re.compile(r"--no-abstract|--no-results|--results|`audit`")
    for given, field in ((["paper.md"], NO_ABSTRACT_FIELD),
                         (["other.tex", "--results", "Nope"], RESULTS_FIELD),
                         (["other.tex"], NO_RESULTS_FIELD)):  # fmt: skip
        result = web.view(["audit", *given])
        assert flags.search(result["out"])
        notes = dict(result["view"]["notes"])
        drawn = json.dumps(notes, ensure_ascii=False)
        assert not flags.search(drawn), drawn
        assert field in drawn, drawn
        assert "Questions for the author" in "".join(notes), notes


def test_a_referee_s_draft_leaves_the_question_to_the_author(tmp_path: Path, capsys) -> None:
    """`--report-draft` says under what was not checked why the Abstract was not compared,
    and asks the author nothing."""
    paper = _write(tmp_path, UNLABELLED)
    draft = tmp_path / "draft.md"
    assert main(["audit", str(paper), "--report-draft", str(draft)]) == 0
    written = draft.read_text(encoding="utf-8")
    assert abstract.NO_ABSTRACT in written and abstract.ASK_NO_ABSTRACT not in written


def test_a_commented_copy_lists_a_question_as_one(tmp_path: Path) -> None:
    from manuscript_guard.auditing.commented import QUESTION, notes_of

    paper = _write(tmp_path, UNLABELLED)
    said = [note.comment for note in notes_of(audit([paper], None), paper)
            if note.code == abstract.ASKED_NO_ABSTRACT]
    assert len(said) == 1 and said[0].startswith(f"{QUESTION}: No heading names the Abstract")


def test_results_named_are_no_results_to_any_other_reader(tmp_path: Path) -> None:
    """`--results` is the Results to the Abstract against Results alone: G8's reading of the
    same headings, and the parts the audit's sentences are placed in, are unchanged."""
    from manuscript_guard.auditing.sentences import RESULTS, placing
    from manuscript_guard.gates.reported import REPORTED, Walk
    from manuscript_guard.text.sections import scannable, split_sections

    text = ("# A study\n\n## Abstract\n\nThe OR was 1.52 (95% CI 1.21-1.90).\n\n"
            "## Introduction\n\nIt matters.\n\n## Electron temperature relations\n\n"
            "The OR was 1.52 (95% CI 1.21-1.89).\n\n## Summary and discussion\n\nIt was so.\n")
    paper = _write(tmp_path, text)
    read = audit([paper], None, answers=Answers(results=("Electron temperature relations",)))
    assert read.abstract.compared
    sections = [s for s in split_sections(scannable(text)) if s.level]
    heading = next(s for s in sections if s.title == "Electron temperature relations")
    assert Walk().placing(sections)(heading.line + 1) is not REPORTED
    assert placing(sections)(heading.line + 1).part != RESULTS


@pytest.mark.parametrize("flag", [["--no-abstract"], ["--no-results"], ["--results", "Data"]])
def test_an_answer_reads_a_paper_and_is_refused_with_a_package_alone(
    tmp_path: Path, capsys, flag: list[str]
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    assert main(["audit", "--package", str(package), *flag]) == 2
    assert f"{flag[0]} reads a paper" in capsys.readouterr().err
