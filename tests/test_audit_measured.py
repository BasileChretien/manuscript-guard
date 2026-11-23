"""`audit` and `compare` give a code the severity its precision on real papers decided
(`auditing.measured`), and `check` gives it what it gave before.

The author's decisions of 2026-11-20: G14's names from the code and G6's bare placeholders
are notes in the two reports that read papers written without the tool, a journal template's
instruction left in the text still fails there, and a PDF's reference list whose entries
could not be told apart is a warning. By the same rule, once the two judges had read the
findings no verdict covered (2026-11-21): a number of the Abstract found nowhere, and a
sentence that may now say the opposite, are notes. And on 2026-11-23 ("INFO on PDFs now"): a
short form used before its definition is a note in text the audit read from a PDF, and keeps
its warning from Word, LaTeX and Markdown. Every paper here is made up.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

from manuscript_guard import reworded
from manuscript_guard.auditing import measured as table
from manuscript_guard.auditing.references import UNTOLD, Census
from manuscript_guard.auditing.report import _printed_items
from manuscript_guard.cli import main
from manuscript_guard.findings import FAIL, INFO, WARN, Finding

sys.path.insert(0, str(Path(__file__).parent))
from proof_pdf import typeset  # noqa: E402

needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                     reason="pdftotext is not installed")  # fmt: skip

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


#: An Abstract with a number the paper reports nowhere, 57, and one it reports, 212.
ABSTRACT = (
    "# Abstract\n\n"
    "We followed 212 pupils for a year, and 57 left the study.\n\n"
    "# Methods\n\n"
    "The pupils were followed for a year.\n\n"
    "# Results\n\n"
    "Of the 212 pupils, 41 left the study.\n"
)


def test_a_number_of_the_abstract_found_nowhere_is_a_note(tmp_path: Path, capsys) -> None:
    report = audited(_paper(tmp_path, ABSTRACT), capsys)
    (found,) = _of(report, "abstract-not-found")
    assert found["message"].startswith("57 in the Abstract") and found["severity"] == "info"


def test_a_journal_s_abstract_missing_still_warns_in_an_audit(tmp_path: Path, capsys) -> None:
    """G4's code of the same name, a journal's limited Abstract under no heading, is another
    finding than a number found nowhere, and keeps its warning."""
    profile = tmp_path / "journal.yaml"
    profile.write_text("schema: manuscript-guard/journal/1\nname: The Journal of Examples\n"
                       "source_url: https://example.org/authors\nretrieved_on: "
                       f"{date.today().isoformat()}\nlimits:\n  abstract_words: 250\n",
                       encoding="utf-8")  # fmt: skip
    paper = _paper(tmp_path, ABSTRACT.replace("# Abstract\n\n", ""))
    main(["audit", str(paper), "--journal", str(profile), "--json"])
    report = json.loads(capsys.readouterr().out)
    said = [(f["gate"], f["severity"]) for f in _of(report, "abstract-not-found")]
    assert said == [("G4", "warn")]


def test_the_text_report_marks_only_the_template_as_failing(tmp_path: Path, capsys) -> None:
    """The report's line for each place says "FAIL:" of a failure only (`auditing.summary`)."""
    assert main(["audit", str(_paper(tmp_path))]) == 0
    out = capsys.readouterr().out
    placed = [line.strip() for line in out.splitlines() if line.strip().startswith("line ")]
    failing = [line for line in placed if ": FAIL: " in line]
    assert len(failing) == 2 and all("template's instruction" in line for line in failing)
    assert [line for line in placed if "'xxxx'" in line and ": FAIL: " not in line]


# ------------------------------------------------------------------- read from a PDF

BEFORE = "abbreviation-used-before-defined"
#: A short form used in the Introduction and defined in the Methods, and another defined
#: twice, whose finding is G14's too and was not measured on PDFs.
LINES = [
    "Introduction",
    "The QXR was raised in the second wave of the study.",
    "Methods",
    "The quarterly exam ratio (QXR) was summed for each pupil.",
    "The QXR was high in both waves of the study.",
    "The weekly sleep score (WSS) was read for each pupil.",
    "The WSS was low in the first wave of the study.",
    "Results",
    "The weekly sleep score (WSS) fell in the second wave.",
    "The WSS and the QXR were read for 212 pupils.",
]
HEADINGS = ("Introduction", "Methods", "Results")


def _as_markdown(lines: list[str] = LINES) -> str:
    return "".join(f"# {line}\n\n" if line in HEADINGS else f"{line}\n\n" for line in lines)


def _as_pdf(path: Path, lines: list[str] = LINES) -> Path:
    path.write_bytes(typeset(lines, columns=1, per_column=40))
    return path


def _as_latex(path: Path) -> Path:
    body = "".join(f"\\section{{{line}}}\n" if line in HEADINGS else f"{line}\n\n"
                   for line in LINES)  # fmt: skip
    path.write_text("\\documentclass{article}\n\\begin{document}\n" + body
                    + "\\end{document}\n", encoding="utf-8", newline="\n")  # fmt: skip
    return path


def _as_word(path: Path) -> Path:
    from manuscript_guard.build.document import BuildError, pandoc

    try:
        program = pandoc()
    except BuildError:
        pytest.skip("pandoc is not installed")
    source = _paper(path.parent, _as_markdown(), "source.md")
    subprocess.run([str(program), str(source), "-o", str(path)], check=True, timeout=120)
    source.unlink()
    return path


def _severities(report: dict, code: str = BEFORE) -> list[str]:
    return [f["severity"] for f in _of(report, code)]


@needs_pdftotext
def test_a_short_form_used_before_its_definition_is_a_note_from_a_pdf(
    tmp_path: Path, capsys
) -> None:
    (found,) = _of(audited(_as_pdf(tmp_path / "paper.pdf"), capsys), BEFORE)
    assert found["message"].startswith("QXR is used here") and found["severity"] == "info"


@pytest.mark.parametrize(("name", "make"), [
    ("paper.md", lambda path: _paper(path.parent, _as_markdown(), path.name)),
    ("paper.tex", _as_latex),
    ("paper.docx", _as_word),
])  # fmt: skip
def test_the_same_finding_keeps_its_warning_from_any_other_format(
    tmp_path: Path, capsys, name: str, make
) -> None:
    (found,) = _of(audited(make(tmp_path / name), capsys), BEFORE)
    assert found["message"].startswith("QXR is used here") and found["severity"] == "warn"


@needs_pdftotext
def test_a_paper_s_own_pdf_is_text_read_from_a_pdf(tmp_path: Path, capsys) -> None:
    """What decides is what the finding was read from. A LaTeX paper's source warns, and the
    PDF made of it, audited as a PDF (the corpus's `audit-pdf`), gives the note: nothing in a
    PDF says what it was made from, and its paragraphs are gone either way. On the corpus
    these findings were right 10 times of 16, which DESIGN.md's Known gaps records."""
    source = audited(_as_latex(tmp_path / "paper.tex"), capsys)
    printed = audited(_as_pdf(tmp_path / "paper.pdf"), capsys)
    assert (_severities(source), _severities(printed)) == (["warn"], ["info"])


@needs_pdftotext
def test_a_pdf_s_other_findings_on_short_forms_keep_their_severity(
    tmp_path: Path, capsys
) -> None:
    """Only the code that was measured on PDFs moves: the same words give the same warning
    on a definition given twice, from a PDF and from Markdown."""
    printed = audited(_as_pdf(tmp_path / "paper.pdf"), capsys)
    typed = audited(_paper(tmp_path, _as_markdown()), capsys)
    code = "abbreviation-redefined"
    assert _severities(printed, code) == _severities(typed, code) == ["warn"]


@needs_pdftotext
def test_a_note_from_a_pdf_is_still_said_and_changes_no_exit(tmp_path: Path, capsys) -> None:
    """The summary still counts it among what there is to look at, the report lists it at its
    page and line, no line calls it a failure, and `--strict`, which never counted G14, exits
    as it does on the same words in Markdown."""
    paper = _as_pdf(tmp_path / "paper.pdf")
    assert main(["audit", str(paper)]) == 0
    out = capsys.readouterr().out
    assert "Abbreviations used before they are defined (G14, 1)" in out
    (line,) = [one for one in out.splitlines() if "QXR is used here" in one]
    assert "page 1" in line and "FAIL" not in line
    (summary,) = [one for one in out.splitlines() if one.strip().startswith("Writing and")]
    assert "to look at" in summary and "not counted by --strict" in summary
    assert main(["audit", str(paper), "--strict"]) == main(
        ["audit", str(_paper(tmp_path, _as_markdown())), "--strict"]) == 0
    capsys.readouterr()


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


#: Two sentences of v1, one made to say the opposite in v2 and one made to claim more.
CLAIMED = ("# Discussion\n\nThe two rates are directly comparable across the cohorts.\n\n"
           "The exposure may be associated with a higher rate of injury.\n")  # fmt: skip
CLAIMED_AGAIN = ("# Discussion\n\nThe two rates are not directly comparable across the "
                 "cohorts.\n\nThe exposure increased the rate of injury.\n")  # fmt: skip


def test_compare_says_a_claim_reversed_as_a_note(tmp_path: Path, capsys) -> None:
    """A sentence that may now say the opposite is a note, and one that claims more is still
    a warning."""
    old, new = _paper(tmp_path, CLAIMED, "v1.md"), _paper(tmp_path, CLAIMED_AGAIN, "v2.md")
    assert main(["compare", str(old), str(new), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    said = sorted((f["code"], f["severity"]) for f in report["findings"]
                  if f["code"].startswith("claim-"))  # fmt: skip
    assert said == [("claim-negation", "info"), ("claim-stronger", "warn")]


@needs_pdftotext
def test_compare_says_it_by_what_v2_was_read_from(tmp_path: Path, capsys) -> None:
    """v2 as a PDF gives the note and v2 as Markdown the warning, against the same v1, and
    the finding stands in v1 by its words whatever severity each version gave it."""
    old = _paper(tmp_path, _as_markdown(), "v1.md")
    said = {}
    for new in (_as_pdf(tmp_path / "v2.pdf"), _paper(tmp_path, _as_markdown(), "v2.md")):
        assert main(["compare", str(old), str(new), "--json"]) == 0
        said[new.suffix] = _severities(json.loads(capsys.readouterr().out))
    assert said == {".pdf": ["info"], ".md": ["warn"]}


def test_compare_audits_v2_s_abstract_numbers_as_notes(tmp_path: Path, capsys) -> None:
    """The audit of v2 that `compare` gives says a number found nowhere as the audit does."""
    old = _paper(tmp_path, ABSTRACT.replace(", and 57 left the study", ""), "v1.md")
    new = _paper(tmp_path, ABSTRACT, "v2.md")
    assert main(["compare", str(old), str(new), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [f["severity"] for f in _of(report, "abstract-not-found")] == ["info"]


def test_reworded_keeps_its_warning_on_a_claim_reversed() -> None:
    """`reworded` reads an edit of a project's own text, and never reads the table."""
    said = {(f.code, f.severity) for f in reworded.compare(CLAIMED, CLAIMED_AGAIN).findings}
    assert ("claim-negation", WARN) in said


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


@pytest.mark.parametrize(("gate", "code", "severity"), [
    ("audit", "abstract-not-found", INFO), ("G4", "abstract-not-found", WARN),
    ("compare", "claim-negation", INFO), ("REWORDED", "claim-negation", WARN),
    ("compare", "claim-stronger", WARN),
])  # fmt: skip
def test_an_entry_holds_for_the_gate_it_was_judged_under(gate: str, code: str,
                                                         severity: str) -> None:
    """G4's `abstract-not-found`, a journal's Abstract missing, is another finding than the
    audit's number found nowhere, and `reworded`'s reversed claim than `compare`'s."""
    assert table.measured(Finding(gate, code, "said", WARN)).severity == severity


@pytest.mark.parametrize(("gate", "code", "read_from", "severity"), [
    ("G14", BEFORE, "PDF", INFO), ("G14", BEFORE, None, WARN),
    ("G14", BEFORE, "Word", WARN), ("G4", BEFORE, "PDF", WARN),
    ("G14", "abbreviation-redefined", "PDF", WARN),
    ("G14", "code-name-in-prose", None, INFO), ("G14", "code-name-in-prose", "PDF", INFO),
])  # fmt: skip
def test_an_entry_holds_for_the_format_it_was_measured_on(
    gate: str, code: str, read_from: str | None, severity: str
) -> None:
    """An entry that names a format holds for findings read from it alone; one that names
    none holds for all of them."""
    found = Finding(gate, code, "said", WARN)
    assert table.measured(found, read_from=read_from).severity == severity


def test_the_entry_for_a_pdf_says_so_and_its_figures_are_the_corpus_s() -> None:
    """35 true of the 81 reported from text read from a PDF at main-77abd45db, the false ones
    from 17 papers: the `audit` of a PDF paper (25 of 65, from 12) and the `audit-pdf` of a
    LaTeX paper (10 of 16, from 5). The corpus holds no Word paper's own PDF."""
    entry = table.MEASURED[BEFORE]
    assert (entry.severity, entry.true, entry.judged, entry.papers, entry.gate,
            entry.read_from) == (INFO, 35, 81, 17, "G14", table.PDF)  # fmt: skip
    assert [code for code, one in table.MEASURED.items() if one.read_from] == [BEFORE]


def test_a_finding_lowered_keeps_its_key() -> None:
    """A key is what the corpus pairs a finding by, and a severity is no part of it."""
    found = Finding("G14", BEFORE, "said", WARN, subject="QXR@main", at=4)
    assert table.measured(found, read_from=table.PDF).key == found.key


def test_each_entry_keeps_to_the_rule() -> None:
    """A code lowered has 10 or more judged, under half true and its false ones from 3 papers
    or more; one raised, 10 or more judged and 0.9 or more true."""
    for code, entry in table.MEASURED.items():
        assert entry.judged >= 10, code
        if entry.severity == INFO:
            assert entry.true / entry.judged < 0.5 and (entry.papers or 0) >= 3, code
        else:
            assert entry.severity == WARN and entry.true / entry.judged >= 0.9, code
