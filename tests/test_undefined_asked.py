"""G14 asks the author one question of the short forms a paper uses and never defines, in
`check` and in `audit` (Basile, 2026-11-16, decision 30: "Question, both").

In the judges' sample of the real-paper corpus, 82% of G14's undefined short forms were
false: names (BOSS, 2MASS, STARLIGHT), designations (ISO-Oph31) and everyday forms (TV,
GDP), which no exact rule tells from a short form that needs defining. `check` gave a
warning for each form, 1,004 over the corpus; it now asks one question for the paper, at
the first form's first use, listing every form at its first use. The answer that ends it is
the author's: list those the readers know under `language: known_abbreviations` in
paper.yaml, and define the others. A question never fails, is never counted as a warning,
and changes no exit code at any stage; `--json` marks it `"question": true`, and the text
shows it apart, under "Questions for the author".
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, QUESTIONS, WARN, Finding, Question, Report
from manuscript_guard.gates import check_language
from manuscript_guard.gates.language import ASK_HINT, UNDEFINED, Asked

#: An Abstract leaving one form undefined that the main text defines, a Methods section with
#: two forms used and never defined, one twice, and a supplement with one more.
MAIN = ("# Abstract\n\nThe HR rose.\n\n# Methods\n\nScans were read on the SIGNA scanner at "
        "the CHUV. The SIGNA scans were read twice.\n\n# Results\n\nThe hazard ratio (HR) was "
        "2, and the HR held.\n")  # fmt: skip
SUPPLEMENT = "# Methods\n\nThe QXZ ran.\n"


def staged(root: Path, main_text: str = MAIN, supplement: str | None = SUPPLEMENT) -> Path:
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "main.md").write_text(main_text, encoding="utf-8")
    if supplement is not None:
        (root / "manuscript" / "supplementary").mkdir()
        (root / "manuscript" / "supplementary" / "S1.md").write_text(supplement,
                                                                    encoding="utf-8")
    return root


def asked_of(root: Path, paper: dict | None = None) -> list[Finding]:
    report = check_language(Project(root=root, paper=paper or {}, authors=None))
    return [finding for finding in report.findings if finding.code == UNDEFINED]


def test_check_asks_one_question_listing_every_form_at_its_first_use(tmp_path: Path) -> None:
    """One question where there were four warnings: at the first form's first use, each form
    with its first use, the Abstract's and the supplement's said so; whether any needs
    defining, and the answer in paper.yaml. A note, never a warning."""
    root = staged(tmp_path)
    (asked,) = asked_of(root)
    assert isinstance(asked, Asked) and isinstance(asked, Question) and asked.question
    assert asked.severity == INFO and asked.line == 3 and "HR" in asked.context
    assert asked.message == (
        "4 short forms are used and never defined as G14 reads the paper: HR at "
        "manuscript/main.md:3 (in the abstract), SIGNA at manuscript/main.md:7, CHUV at "
        "manuscript/main.md:7, QXZ at manuscript/supplementary/S1.md:3 (in the supplement). "
        "Do any of them need defining?"), asked.message
    assert asked.hint == ASK_HINT and "`language: known_abbreviations` in paper.yaml" in ASK_HINT
    assert "define the others at their first use" in ASK_HINT
    # Each form keeps the warning G14 gave it, at its first use.
    assert [(form, warning.line) for form, warning in asked.forms] == [
        ("HR", 3), ("SIGNA", 7), ("CHUV", 7), ("QXZ", 3)]
    assert asked.forms[1][1].message == (
        "SIGNA is used 2 times in the main text as G14 reads it, and not defined there")


def test_the_main_text_s_form_the_abstract_defines_is_said_so(tmp_path: Path) -> None:
    root = staged(tmp_path, "# Abstract\n\nThe reporting odds ratio (ROR) rose.\n\n# Methods"
                            "\n\nThe ROR was computed.\n", None)  # fmt: skip
    (asked,) = asked_of(root)
    assert ("1 short form is used and never defined as G14 reads the paper: ROR at "
            "manuscript/main.md:7 (the abstract defines it, and is read apart from the paper)"
            ) in asked.message, asked.message


def test_known_abbreviations_end_the_question_form_by_form(tmp_path: Path) -> None:
    """The answer: each form listed under `language: known_abbreviations` leaves the
    question, and with every form listed, nothing is asked."""
    root = staged(tmp_path)
    (asked,) = asked_of(root, {"language": {"known_abbreviations": ["SIGNA", "CHUV"]}})
    assert [form for form, _warning in asked.forms] == ["HR", "QXZ"]
    assert asked.message.startswith("2 short forms are used and never defined")
    every = {"language": {"known_abbreviations": ["HR", "SIGNA", "CHUV", "QXZ"]}}
    assert asked_of(root, every) == []


def test_no_warning_is_left_and_the_rest_of_g14_is_as_it_was(tmp_path: Path) -> None:
    """No warning of a form used and not defined is left; one used before its definition is
    still a warning, as redefined and unused are."""
    root = staged(tmp_path, MAIN + "\nThe ICU was full. The intensive care unit (ICU) was "
                  "busy.\n", None)  # fmt: skip
    report = check_language(Project(root=root, paper={}, authors=None))
    assert not [f for f in report.warnings if f.code == UNDEFINED]
    (before,) = [f for f in report.findings if f.code == "abbreviation-used-before-defined"]
    assert before.severity == WARN and not before.question and before in report.warnings
    assert report.ok


def test_the_json_marks_the_question_and_no_other_finding(tmp_path: Path) -> None:
    """`check --json` gives the question `"question": true` and the forms it lists, each
    with its first use; a finding that is no question has no such field."""
    root = staged(tmp_path)
    report = check_language(Project(root=root, paper={}, authors=None))
    said = json.loads(report.to_json())
    (asked,) = [f for f in said["findings"] if f["code"] == UNDEFINED]
    assert asked["question"] is True and asked["severity"] == "info"
    assert [(f["form"], f["line"]) for f in asked["forms"]] == [
        ("HR", 3), ("SIGNA", 7), ("CHUV", 7), ("QXZ", 3)]
    assert Path(asked["forms"][3]["path"]).name == "S1.md"
    plain = Report((Finding("G14", "abbreviation-unused", "unused", WARN),)).to_json()
    assert "question" not in json.loads(plain)["findings"][0]


def test_the_text_shows_the_questions_apart_after_the_findings() -> None:
    """Under their own heading, after every finding, whatever their order by place."""
    report = Report((Question("G14", UNDEFINED, "1 short form ... Do any need defining?",
                              line=1),
                     Finding("G6", "ai-phrasing", "a phrase", WARN, line=9)))  # fmt: skip
    lines = report.render().splitlines()
    assert lines.index(QUESTIONS) > next(i for i, line in enumerate(lines) if "a phrase" in line)
    assert lines[lines.index(QUESTIONS) + 1].startswith("  [INFO] G14")
    assert report.ok and [f.code for f in report.warnings] == ["ai-phrasing"]


def _counts(out: str) -> str:
    """The last line `check` prints of what fails and what warns."""
    return next(line for line in reversed(out.splitlines()) if " failing, " in line)


def test_check_s_exit_code_and_counts_are_the_question_s_none(project: Path, capsys) -> None:
    """The example leaves ROR undefined: `check` asks it as the question, at drafting and at
    submission, and its exit code and its counts of failures and warnings are those of the
    same paper with ROR listed as known, which asks nothing."""
    outcomes = {}
    for known in (["CI"], ["CI", "ROR"]):
        paper = project / "paper.yaml"
        document = yaml.safe_load(paper.read_text(encoding="utf-8"))
        document["language"]["known_abbreviations"] = known
        paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        for flags in ((), ("--submission",)):
            code = main(["check", str(project), *flags])
            out = capsys.readouterr().out
            main(["check", str(project), "--json", *flags])
            said = json.loads(capsys.readouterr().out)
            asked = [f for f in said["findings"] if f["code"] == UNDEFINED]
            outcomes[(len(known), flags)] = (code, _counts(out), said["ok"])
            if known == ["CI"]:
                (one,) = asked
                assert one["question"] is True and [f["form"] for f in one["forms"]] == ["ROR"]
                # Apart, after every finding that is no question.
                assert QUESTIONS in out and "ROR at manuscript/" in out
                assert out.index(QUESTIONS) > max(out.rfind("[WARN]"), out.rfind("[FAIL]"))
            else:
                assert asked == [] and "ROR at manuscript/" not in out
    for flags in ((), ("--submission",)):
        assert outcomes[(1, flags)] == outcomes[(2, flags)], outcomes


def test_the_audit_s_question_is_not_counted_by_strict(tmp_path: Path, capsys) -> None:
    """`audit --strict` counts nothing of the question: the paper whose only finding is the
    short forms never defined passes it."""
    paper = tmp_path / "paper.md"
    paper.write_text("# Methods\n\nThe SIGNA scanner read 412 scans.\n\n# Results\n\nOf "
                     "412 scans, 77 were read.\n", encoding="utf-8")  # fmt: skip
    assert main(["audit", str(paper), "--strict", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    (asked,) = [f for f in said["findings"] if f["code"] == UNDEFINED]
    assert asked["question"] is True and asked["counted"] is False and said["ok"]
