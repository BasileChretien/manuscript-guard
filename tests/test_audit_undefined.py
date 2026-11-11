"""`audit` says the short forms a paper uses and does not define in one finding, and passes
over those that journals' style guides say need no definition (`auditing.undefined`).

The corpus run of 2026-11-11 audited 52 real preprints, and judges read a sample of the
findings: 354 of the 427 `abbreviation-undefined` warnings they read were false, the field's
own terms, institutions, gene and instrument names, often dozens to a paper, and the true
ones were lost among them. The author decided on one finding per paper, with `--known` as its
remedy, a sourced list of forms the audit does not report, and `check` unchanged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.auditing import undefined
from manuscript_guard.cli import main

#: The shape the corpus found: a Methods section naming its instruments, genes and
#: institutions in capitals, none defined, beside forms every reader takes for words (HIV,
#: MRI, EEG); one form used only in the Abstract, where the main text defines it.
PAPER = (
    "# Abstract\n\nThe HR rose in people with HIV.\n\n"
    "# Methods\n\n"
    "Scans were taken on the SIGNA scanner at the CHUV with MRI and EEG. The UMCG and NTNU "
    "cohorts were read. The SIGNA scans were read twice. People with HIV were seen.\n\n"
    "# Results\n\nThe hazard ratio (HR) was 2, and the HR held.\n"
)
#: The forms the audit lists, in the order the paper first uses them, and those it passes
#: over for being on the list.
LISTED = ("HR", "SIGNA", "CHUV", "UMCG", "NTNU")
PASSED = ("HIV", "MRI", "EEG")


def written(folder: Path, text: str = PAPER, name: str = "paper.md") -> Path:
    paper = folder / name
    paper.write_text(text, encoding="utf-8")
    return paper


def _json(paper: Path, capsys, *flags: str) -> dict:
    assert main(["audit", str(paper), "--json", *flags]) == 0
    return json.loads(capsys.readouterr().out)


def test_the_short_forms_left_undefined_are_one_finding_at_the_first_use(
    tmp_path: Path, capsys
) -> None:
    """One finding where there were eight: the forms in the order of their first use, the
    first quoted where it stands, the one the abstract alone leaves undefined said so, and
    the forms on the list counted, named and passed over by the list's sources."""
    report = _json(written(tmp_path), capsys)
    (found,) = [f for f in report["findings"] if f["code"] == "abbreviation-undefined"]
    assert found["line"] == 3 and "HR" in found["context"]
    assert found["message"].startswith(
        "5 short forms are used and not defined as G14 reads the paper: 'HR' (in the abstract) "
        "here, then SIGNA, CHUV, UMCG, NTNU; 3 more passed over (HIV, MRI and EEG), being on "
        "the list of short forms that the Cochrane Style Manual, Brain's instructions to "
        "authors and Medical Writing's instructions for authors (EMWA) say need no "
        "definition"), found["message"]  # fmt: skip
    assert "--known" in found["hint"]
    # Each form keeps what G14 said of it and where it is first used.
    assert [form["form"] for form in found["forms"]] == list(LISTED)
    assert [form["line"] for form in found["forms"]] == [3, 7, 7, 7, 7]
    assert found["forms"][1]["message"] == (
        "SIGNA is used 2 times in the main text as G14 reads it, and not defined there")
    assert found["forms"][1]["context"] and "SIGNA" in found["forms"][1]["context"]
    assert found["passed_over"] == list(PASSED)
    assert found["passed_over_by"] == "journal_abbreviations.yaml"


def test_the_summary_counts_the_forms_and_details_list_each(tmp_path: Path, capsys) -> None:
    """The kind's line counts the five forms, not the one finding; `--details` gives each
    form's first use with G14's words on it."""
    paper = written(tmp_path)
    main(["audit", str(paper)])
    out = capsys.readouterr().out
    assert "Abbreviations used and not defined (G14, 5)" in out
    assert out.count("short forms are used and not defined") == 1
    main(["audit", str(paper), "--details"])
    out = capsys.readouterr().out
    assert "  Each short form used and not defined, where it is first used:" in out
    assert "    line 7: CHUV is used once in the main text as G14 reads it" in out
    assert "    line 3: HR is used once in the abstract as G14 reads it" in out


def test_known_words_are_taken_off_the_list_of_the_finding(tmp_path: Path, capsys) -> None:
    """`--known`, the finding's remedy, takes a form off it; with every form known or on
    the list, there is no finding."""
    paper = written(tmp_path)
    report = _json(paper, capsys, "--known", "SIGNA", "CHUV")
    (found,) = [f for f in report["findings"] if f["code"] == "abbreviation-undefined"]
    assert [form["form"] for form in found["forms"]] == ["HR", "UMCG", "NTNU"]
    report = _json(paper, capsys, "--known", "SIGNA", "CHUV", "UMCG", "NTNU", "HR")
    assert not [f for f in report["findings"] if f["code"] == "abbreviation-undefined"]


def test_a_paper_whose_forms_are_all_on_the_list_has_no_finding(tmp_path: Path, capsys) -> None:
    """Every form left undefined is on the list: nothing is said of them (DESIGN.md, Known
    gaps), and the other findings on the words stand."""
    paper = written(tmp_path, "# Methods\n\nPeople with HIV had an MRI and an EEG.\n")
    report = _json(paper, capsys)
    assert not [f for f in report["findings"] if f["gate"] == "G14"
                and f["code"].startswith("abbreviation-")]  # fmt: skip


def test_check_in_a_project_still_warns_of_each_form_and_reads_no_list(tmp_path: Path) -> None:
    """`check` is unchanged: G14 gives a warning for each form, on the list or not, on the
    same text the audit gave one finding for."""
    from manuscript_guard.auditing.gates import _stage, audit_project
    from manuscript_guard.gates.language import check_language

    paper = written(tmp_path)
    root = tmp_path / "project"
    project = audit_project(root, _stage(paper), None)
    warned = [f.message.split()[0] for f in check_language(project).findings
              if f.code == "abbreviation-undefined"]  # fmt: skip
    assert sorted(warned) == sorted([*LISTED, "HIV", *PASSED]), warned
    assert not any(isinstance(f, undefined.Undefined) for f in check_language(project).findings)


def test_the_finding_reads_what_g14_writes_of_one_form_in_each_part(tmp_path: Path) -> None:
    """G14's message for one form, in the abstract, the main text and the supplement, is what
    the audit reads the form and the part from: a gate reworded under it would leave every
    warning apart, unnoticed."""
    from manuscript_guard.auditing.gates import _Staged, audit_project
    from manuscript_guard.gates.language import check_language

    staged = _Staged({"main.md": PAPER, "supplementary/s1.md": "# Methods\n\nThe QQQ ran.\n"},
                     {})  # fmt: skip
    project = audit_project(tmp_path / "project", staged, None)
    warnings = [f for f in check_language(project).findings if f.code == undefined.CODE]
    scopes = {undefined._SAID.match(f.message)["scope"] for f in warnings}
    assert scopes == {"abstract", "main text", "supplement"}, [f.message for f in warnings]


def test_the_list_cites_each_source_and_each_entry_names_one() -> None:
    """Each source has its address, the day it was read and its own words, short; each
    entry names a source the file holds; and none is a form `abbreviations.yaml` took out
    for its second meaning."""
    listed = yaml.safe_load(undefined.LIST.read_text(encoding="utf-8"))
    sources = listed["sources"]
    for source in sources.values():
        assert source["url"].startswith("https://") and source["read"]
        assert len(source["says"].split()) < 15
    for form, cited in listed["exempt"].items():
        assert cited and set(cited) <= set(sources), form
    assert not {"AD", "BC", "AM", "PM", "GMT"} & set(listed["exempt"])
    assert undefined.exempt() == frozenset(listed["exempt"])


needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


@needs_pandoc
def test_the_commented_copy_puts_the_finding_on_the_first_form(tmp_path: Path, capsys) -> None:
    """In the copy with comments, the one finding stands on the first use of the first form
    it lists, the word its message quotes."""
    from manuscript_guard.docxtext import comment_ranges, word_comments

    written(tmp_path)
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    target = tmp_path / "commented.docx"
    assert main(["audit", str(tmp_path / "paper.docx"), "--commented", str(target)]) == 0
    capsys.readouterr()
    ranges = comment_ranges(target)
    over = [ranges.get(one.identifier) for one in word_comments(target)
            if "short forms are used and not defined" in one.text]  # fmt: skip
    assert over == ["HR"], (over, [one.text for one in word_comments(target)])
    with zipfile.ZipFile(target) as archive:
        assert archive.read("word/comments.xml")
