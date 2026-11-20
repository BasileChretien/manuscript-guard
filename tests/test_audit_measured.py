"""`audit` and `compare` give a code the severity its precision on real papers decided
(`auditing.measured`), and `check` gives it what it gave before.

The author's decisions of 2026-11-20: G14's names from the code and G6's bare placeholders
are notes in the two reports that read papers written without the tool, a journal template's
instruction left in the text still fails there, and a PDF's reference list whose entries
could not be told apart is a warning. Every paper here is made up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from manuscript_guard.auditing import measured as table
from manuscript_guard.auditing.references import UNTOLD, Census
from manuscript_guard.auditing.report import _printed_items
from manuscript_guard.cli import main
from manuscript_guard.findings import FAIL, INFO, WARN, Finding

#: A name from the code in the prose, a bare placeholder, and a journal template's
#: instruction in Word's words and in a template's, each in a paragraph of its own.
PAPER = (
    "# Methods\n\n"
    "The score pupil_sleep_total was summed for each of the 212 pupils.\n\n"
    "# Results\n\n"
    "The mean was xxxx in the second wave, and 41 pupils left.\n\n"
    "# Acknowledgements\n\n"
    "In this section you can acknowledge any support given which is not covered here.\n\n"
    "Click or tap here to enter text.\n"
)
TEMPLATE = "placeholder-template"
BARE = "placeholder-word"


def _rule(finding: dict) -> str:
    return finding["key"].split("|")[2].partition(":")[0]


def _of(report: dict, code: str) -> list[dict]:
    return [f for f in report["findings"] if f["code"] == code]


def audited(paper: Path, capsys) -> dict:
    assert main(["audit", str(paper), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def checked(folder: Path, capsys, text: str = PAPER) -> dict:
    """`check --json` on a project at drafting whose manuscript is `text`."""
    (folder / "manuscript").mkdir(parents=True)
    (folder / "paper.yaml").write_text("stage: drafting\n", encoding="utf-8")
    (folder / "manuscript" / "main.md").write_text(text, encoding="utf-8", newline="\n")
    main(["check", "--json", str(folder)])
    return json.loads(capsys.readouterr().out)


def _paper(folder: Path, text: str = PAPER, name: str = "paper.md") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------------------------ audit


def test_a_name_from_the_code_is_a_note_in_an_audit(tmp_path: Path, capsys) -> None:
    (found,) = _of(audited(_paper(tmp_path), capsys), "code-name-in-prose")
    assert "pupil_sleep_total" in found["message"] and found["severity"] == "info"


def test_a_bare_placeholder_is_a_note_in_an_audit(tmp_path: Path, capsys) -> None:
    bare = [f for f in _of(audited(_paper(tmp_path), capsys), "model-artefact")
            if _rule(f) == BARE]  # fmt: skip
    assert [(f["severity"], "xxxx" in f["message"]) for f in bare] == [("info", True)]


def test_a_template_s_instruction_still_fails_an_audit(tmp_path: Path, capsys) -> None:
    template = [f for f in _of(audited(_paper(tmp_path), capsys), "model-artefact")
                if _rule(f) == TEMPLATE]  # fmt: skip
    assert len(template) == 2 and {f["severity"] for f in template} == {"fail"}
    assert any("Click or tap" in f["message"] for f in template)


#: A slot in brackets that tells the writer what to put, of each rule of the kind the corpus
#: never judged, and instructions left for the writer in brackets, which the bracket's rule
#: finds before `placeholder-filler` does: "[fill in later]", "[add your affiliation here]".
INSTRUCTIONS = (
    "# Results\n\n"
    "The mean was [fill in later] for 212 pupils.\n\n"
    "The cohort is [describe the cohort], and 41 pupils left.\n\n"
    "The interval is [TO BE COMPLETED] in the second wave.\n\n"
    "The data are at INSERT_SOURCE_URL, and TODO: check the totals.\n\n"
    "# Authors\n\n"
    "Written by [your name], [add your affiliation here].\n"
)


def test_a_slot_that_tells_the_writer_what_to_put_still_fails(tmp_path: Path, capsys) -> None:
    found = _of(audited(_paper(tmp_path, INSTRUCTIONS), capsys), "model-artefact")
    said = sorted((_rule(f), f["severity"]) for f in found)
    assert said == sorted([("placeholder", "fail")] * 3 + [(BARE, "fail")] * 2 + [
        ("placeholder-capitals", "fail"), ("placeholder-your", "fail")])  # fmt: skip


def test_a_latex_paper_is_audited_the_same_way(tmp_path: Path, capsys) -> None:
    source = ("\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
              "The score pupil\\_sleep\\_total was XXXX for 212 pupils.\n\n"
              "In this section you can acknowledge any support given.\n\\end{document}\n")
    found = audited(_paper(tmp_path, source, "paper.tex"), capsys)
    (names,) = _of(found, "code-name-in-prose")
    said = {_rule(f): f["severity"] for f in _of(found, "model-artefact")}
    assert names["severity"] == "info" and said == {BARE: "info", TEMPLATE: "fail"}


def test_the_text_report_marks_only_the_template_as_failing(tmp_path: Path, capsys) -> None:
    """The report's line for each place says "FAIL:" of a failure only (`auditing.summary`)."""
    assert main(["audit", str(_paper(tmp_path))]) == 0
    out = capsys.readouterr().out
    placed = [line.strip() for line in out.splitlines() if line.strip().startswith("line ")]
    failing = [line for line in placed if ": FAIL: " in line]
    assert len(failing) == 2 and all("template's instruction" in line for line in failing)
    assert [line for line in placed if "'xxxx'" in line and ": FAIL: " not in line]


# -------------------------------------------------------------------------- compare


def test_compare_gives_v2_the_audit_s_severities(tmp_path: Path, capsys) -> None:
    old = _paper(tmp_path, "# Results\n\nThe mean was 3 for 212 pupils.\n", "v1.md")
    new = _paper(tmp_path, PAPER, "v2.md")
    assert main(["compare", str(old), str(new), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    (names,) = _of(report, "code-name-in-prose")
    said = sorted((_rule(f), f["severity"]) for f in _of(report, "model-artefact"))
    assert names["severity"] == "info"
    assert said == sorted([(BARE, "info"), (TEMPLATE, "fail"), (TEMPLATE, "fail")])


# ---------------------------------------------------------------------------- check


def test_check_keeps_its_severities(tmp_path: Path, capsys) -> None:
    """At drafting `check` warns on the name and fails both kinds of artefact, as it did."""
    report = checked(tmp_path, capsys)
    (names,) = _of(report, "code-name-in-prose")
    said = sorted((_rule(f), f["severity"]) for f in _of(report, "model-artefact"))
    assert names["severity"] == "warn"
    assert said == sorted([(BARE, "fail"), (TEMPLATE, "fail"), (TEMPLATE, "fail")])


# -------------------------------------------------------------------- reference list


def test_entries_not_told_apart_is_a_warning(tmp_path: Path) -> None:
    census = Census(tmp_path / "paper.pdf", style=UNTOLD,
                    untold="its first entry carries no number, so none is told from the next")
    (found,) = [i for i in _printed_items(census) if i.code == "entries-not-told-apart"]
    assert found.severity == WARN and not found.counted


# ---------------------------------------------------------------------------- table


def _artefact_rules() -> list[dict]:
    path = Path(table.__file__).parent.parent / "data" / "ai_writing.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["artefacts"]


def test_the_bare_placeholders_are_the_rules_judged() -> None:
    """The two rules of the kind whose findings the corpus judged, each still a rule of
    "Unfilled placeholder text"; a slot that tells the writer what to put, an instruction left
    for the writer, `placeholder-filler`, and a template's keep failing."""
    bare = {rule["id"] for rule in _artefact_rules() if rule["why"] == "Unfilled placeholder text"}
    lowered = table.BARE_PLACEHOLDERS
    assert lowered == {BARE, "placeholder-slot"} and lowered <= bare
    kept = {"placeholder", "placeholder-your", "placeholder-capitals", "placeholder-filler"}
    assert (kept | {TEMPLATE}).isdisjoint(table.BARE_PLACEHOLDERS)


@pytest.mark.parametrize(("subject", "severity"), [
    ("placeholder-word: xxxx", INFO), ("placeholder-slot: [url]", INFO),
    ("placeholder-word: tbd", INFO), ("placeholder-word: 2025-xx", INFO),
    ("placeholder-word: todo", FAIL), ("placeholder-word: fixme", FAIL),
    ("placeholder-word: insert_source_url", FAIL), ("placeholder-word: paste_table_2", FAIL),
    ("placeholder: [fill in later]", FAIL), ("placeholder-your: [your name]", FAIL),
    ("placeholder-capitals: [TO BE COMPLETED]", FAIL),
    ("placeholder-filler: fill in later", FAIL), (f"{TEMPLATE}: keyword 1; keyword 2", FAIL),
    ("chatgpt-markers: oaicite", FAIL), (None, FAIL),
])  # fmt: skip
def test_only_a_bare_placeholder_is_lowered(subject: str | None, severity: str) -> None:
    found = Finding("G6", "model-artefact", "said", FAIL, subject=subject)
    assert table.measured(found).severity == severity


def test_a_code_the_table_does_not_name_is_left_alone() -> None:
    found = Finding("G14", "spelling-mixed", "said", WARN)
    assert table.measured(found) is found


def test_each_entry_keeps_to_the_rule() -> None:
    """A code lowered has 10 or more judged, under half true and its false ones from 3 papers
    or more; one raised, 10 or more judged and 0.9 or more true."""
    for code, entry in table.MEASURED.items():
        assert entry.judged >= 10, code
        if entry.severity == INFO:
            assert entry.true / entry.judged < 0.5 and (entry.papers or 0) >= 3, code
        else:
            assert entry.severity == WARN and entry.true / entry.judged >= 0.9, code
