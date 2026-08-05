"""The submission pack, and the pre-analysis design gate.

Everything in a submission except the covering letter is already recorded somewhere in the
project, so the tests are mostly about it not being written twice: the title page, the
CRediT statement and the declarations must come from authors.yaml and change when it does.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.build import (
    SubmissionError,
    assemble_pack,
    credit_statement,
    declarations,
    title_page,
)
from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_design
from manuscript_guard.gates.design import plan_path

AUTHORS = Path("authors.yaml")
PLAN = Path("design") / "plan.md"


def edit_yaml(path: Path, mutate) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


# ---------------------------------------------------------------- title page


def test_the_title_page_carries_what_the_manuscript_leaves_out(project: Path) -> None:
    page = title_page(load_project(project)[0])
    assert "Ada Example, PharmD, MSc" in page
    assert "Example University" in page
    assert "0000-0002-1825-0097" in page
    assert "ada.example@invalid.example" in page
    assert "Word count" in page


def test_affiliation_superscripts_follow_the_declared_order(project: Path) -> None:
    page = title_page(load_project(project)[0])
    assert "Ada Example, PharmD, MSc^1^" in page
    assert "Blaise Sample, MD, PhD^2^" in page


def test_an_equal_contribution_group_is_marked_and_footnoted(project: Path) -> None:
    def mutate(document):
        for author in document["authors"]:
            author["equal_contribution"] = True

    edit_yaml(project / AUTHORS, mutate)
    page = title_page(load_project(project)[0])
    assert page.count("\\*") >= 3, "a mark on each author and the footnote"
    assert "contributed equally" in page


def test_the_title_page_changes_when_the_authors_do(project: Path) -> None:
    """The point of generating it is that it cannot list someone who left the paper."""
    before = title_page(load_project(project)[0])
    edit_yaml(project / AUTHORS, lambda d: d["authors"].pop())
    after = title_page(load_project(project)[0])
    assert "Blaise Sample" in before
    assert "Blaise Sample" not in after


# ---------------------------------------------------------------- CRediT and declarations


def test_credit_is_grouped_by_role_as_journals_print_it(project: Path) -> None:
    statement = credit_statement(load_project(project)[0])
    assert "**Conceptualization:** A.E." in statement
    assert "**Supervision:** B.S." in statement


def test_credit_roles_keep_the_taxonomy_order(project: Path) -> None:
    statement = credit_statement(load_project(project)[0])
    assert statement.index("Conceptualization") < statement.index("Formal analysis")
    assert statement.index("Methodology") < statement.index("Writing – original draft")


def test_missing_credit_roles_are_said_out_loud(project: Path) -> None:
    def mutate(document):
        for author in document["authors"]:
            author.pop("credit", None)

    edit_yaml(project / AUTHORS, mutate)
    assert "No CRediT roles are recorded" in credit_statement(load_project(project)[0])


def test_an_empty_competing_interest_is_not_a_declaration_of_none(project: Path) -> None:
    """The distinction journals care about, and the one an empty field destroys."""

    def mutate(document):
        document["authors"][0]["competing_interests"] = ""

    edit_yaml(project / AUTHORS, mutate)
    text = declarations(load_project(project)[0])
    assert "No declaration is recorded for: Ada Example" in text
    assert "not a declaration of none" in text


def test_funding_is_listed_per_author(project: Path) -> None:
    edit_yaml(project / AUTHORS, lambda d: d["authors"][0].update(funding=["Grant ABC/123"]))
    assert "A.E.: Grant ABC/123" in declarations(load_project(project)[0])


def test_a_project_without_authors_cannot_make_a_title_page(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    (root / "manuscript").mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    with pytest.raises(SubmissionError, match="authors.yaml is required"):
        title_page(load_project(root)[0])


# ---------------------------------------------------------------- the pack


def test_the_pack_gathers_every_part(project: Path) -> None:
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(projekt, document)
    names = {p.name for p in pack.files}
    assert {"manuscript.docx", "title-page.md", "credit-statement.md", "declarations.md"} <= names
    assert any(n.startswith("checklist-") for n in names)
    assert any(p.suffix == ".png" for p in pack.files)


def test_the_manifest_records_what_was_sent(project: Path) -> None:
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(projekt, document)
    manifest = yaml.safe_load(pack.manifest.read_text(encoding="utf-8"))
    assert manifest["journal"] == "demo-journal"
    assert len(manifest["files"]) == len(pack.files)
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])
    assert len(manifest["manuscript_sha256"]) == 64


def test_the_pack_offers_a_checklist_a_journal_can_read(project: Path) -> None:
    """What the pack sent in answer to "attach your completed STROBE checklist" was YAML.

    An editor wants the items and where each is addressed. The YAML stays — it is the record,
    and it diffs — but a table goes beside it, generated so it cannot drift from the file the
    gate checks.
    """
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(projekt, document)
    table = next(p for p in pack.files if p.name == "checklist-DEMO-OBS.md")
    text = table.read_text(encoding="utf-8")
    assert "| Item | Recommendation | Addressed in | Not applicable because |" in text
    assert "| Abstract |" in text, text
    assert any(p.name == "checklist-DEMO-OBS.yaml" for p in pack.files), "the record is still sent"


def test_an_unanswered_checklist_item_still_appears_in_the_table(project: Path) -> None:
    """The item text comes from the published guideline, not from the completion — so an item
    nobody answered shows with the answer blank rather than vanishing from what a journal
    receives, which is the difference between an incomplete checklist and a shorter one."""
    from manuscript_guard.build.submission import checklist_table

    completion = project / "reporting" / "DEMO-OBS.yaml"
    document = yaml.safe_load(completion.read_text(encoding="utf-8"))
    dropped = document["items"].pop()["id"]
    completion.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    projekt, _ = load_project(project)
    rows = checklist_table(projekt, completion).splitlines()
    assert any(row.startswith(f"| {dropped} |") for row in rows), rows[-4:]


def test_a_pipe_in_an_item_does_not_break_the_table(project: Path) -> None:
    """A pipe inside a cell ends the cell, and reporting checklists contain "and/or" lists."""
    from manuscript_guard.build.submission import checklist_table

    completion = project / "reporting" / "DEMO-OBS.yaml"
    document = yaml.safe_load(completion.read_text(encoding="utf-8"))
    document["items"][0]["where"] = "Methods | Statistical analysis"
    completion.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    projekt, _ = load_project(project)
    row = next(
        line
        for line in checklist_table(projekt, completion).splitlines()
        if "Statistical analysis" in line
    )
    assert "\\|" in row
    assert len(re.findall(r"(?<!\\)\|", row)) == 5, row


def test_reassembling_clears_the_previous_pack(project: Path) -> None:
    """A stale file left in the directory is a file that gets sent by mistake."""
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04")

    pack = assemble_pack(projekt, document)
    stray = pack.directory / "old-version.docx"
    stray.write_bytes(b"PK\x03\x04 stale")
    assemble_pack(projekt, document)
    assert not stray.exists()


# ---------------------------------------------------------------- the design gate


def test_a_complete_plan_is_recognised(project: Path) -> None:
    report = check_design(load_project(project)[0])
    assert report.ok
    assert report.counts["design_sections"] == report.counts["design_expected"]
    assert "plan-complete" in codes(report)


def test_analysis_without_a_plan_warns_but_never_blocks(project: Path) -> None:
    """Warning by decision: blocking exploratory work is a gate that gets bypassed."""
    shutil.rmtree(project / "design")
    report = check_design(load_project(project)[0])
    assert "no-analysis-plan" in codes(report)
    assert report.ok, "the design gate never fails a build"


def test_a_missing_section_is_named(project: Path) -> None:
    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8").replace("## Deviations from the plan", "## Notes")
    path.write_text(text, encoding="utf-8")
    report = check_design(load_project(project)[0])
    assert "plan-section-missing" in codes(report)
    assert any("deviations" in f.message for f in report.findings)


@pytest.mark.parametrize("filler", ["", "TBD", "n/a", "   ", "TODO"])
def test_a_heading_with_nothing_under_it_is_not_a_section(project: Path, filler: str) -> None:
    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8")
    head = text.index("## Deviations from the plan")
    path.write_text(text[:head] + f"## Deviations from the plan\n\n{filler}\n", encoding="utf-8")
    report = check_design(load_project(project)[0])
    assert "plan-section-empty" in codes(report)


def test_a_project_with_no_analysis_and_no_plan_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "manuscript").mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    report = check_design(load_project(root)[0])
    assert report.ok
    assert not report.findings
