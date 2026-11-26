"""G4's check of the statements every paper makes and of empty headings
(`gates/statements.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates.statements import (
    AI_USE,
    EMPTY,
    KINDS,
    MISSING,
    check_statements,
    empty_headings,
    missing,
    severity_at,
    stated,
)

#: The kinds asked for where no AI use is on record.
FIVE = tuple(kind for kind in KINDS if kind != AI_USE)
#: Each of the five statements asked for when no AI use is on record, written plainly.
WHOLE = (
    "# Introduction\n\nWords of the paper.\n\n"
    "# Data availability\n\nThe data are held by the agency.\n\n"
    "# Ethics\n\nThe committee approved the study (CPP 2021-12).\n\n"
    "# Author contributions\n\nAE designed the study.\n\n"
    "# Funding\n\nThis work received no funding.\n\n"
    "# Competing interests\n\nNone declared.\n"
)


def _project(root: Path, main: str, *, supplement: str | None = None,
             paper: dict | None = None, authors: dict | None = None,
             extra: dict[str, str] | None = None) -> Project:  # fmt: skip
    folder = root / "manuscript"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.md").write_text(main, encoding="utf-8")
    if supplement is not None:
        (folder / "supplementary").mkdir(exist_ok=True)
        (folder / "supplementary" / "S1.md").write_text(supplement, encoding="utf-8")
    for name, text in (extra or {}).items():
        (folder / name).write_text(text, encoding="utf-8")
    return Project(root, {"schema": "manuscript-guard/paper/1", **(paper or {})}, authors)


def _said(project: Project, stage: str | None = "drafting") -> list[tuple[str, str, str]]:
    return [(f.code, f.severity, f.subject or "")
            for f in check_statements(project, stage).findings]  # fmt: skip


# ------------------------------------------------------------------------ empty headings


def test_a_heading_over_a_comment_alone_is_empty_at_its_line_in_its_file(
    tmp_path: Path,
) -> None:
    text = ("---\ntitle: A\n---\n\n" + WHOLE.replace(
        "# Data availability\n\nThe data are held by the agency.\n",
        "# Data availability statement\n\n<!-- TO CONFIRM: held by the agency. -->\n"))
    project = _project(tmp_path, text)
    [finding] = check_statements(project, "drafting").findings
    assert (finding.code, finding.severity) == (EMPTY, WARN)
    assert finding.path == tmp_path / "manuscript" / "main.md"
    assert text.splitlines()[finding.line - 1] == "# Data availability statement"
    assert "has nothing under it, so the manuscript has no data availability statement" in (
        finding.message)


def test_a_heading_whose_subsections_say_something_is_not_empty_and_an_empty_one_is() -> None:
    text = ("# Methods\n\n## Design\n\nA cohort.\n\n## Outcome\n\n<!-- to write -->\n\n"
            "# Results\n\nR.\n")
    assert [heading.title for heading in empty_headings(text)] == ["Outcome"]
    nested = "# Methods\n\n## Design\n\n<!-- -->\n\n## Outcome\n\n# Results\n\nR.\n"
    assert [heading.title for heading in empty_headings(nested)] == ["Design", "Outcome"]


def test_a_heading_empty_only_through_its_empty_subsections_is_no_gap_of_its_own() -> None:
    """One gap, one finding (round 1 of #819): the subsections are said, the heading over them
    is not; a heading over nothing but a heading with no title is a gap."""
    text = "# Declarations\n\n## Funding\n\n<!-- -->\n\n## Competing interests\n\n# End\n\nE.\n"
    assert [heading.title for heading in empty_headings(text)] == ["Funding",
                                                                   "Competing interests"]
    assert [heading.title for heading in empty_headings(
        "# Appendix\n\n### {#a}\n\n# End\n\nE.\n")] == ["Appendix"]


def test_a_listing_a_table_or_a_binding_is_something_and_a_hash_in_a_listing_is_no_heading(
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The statements every paper makes are found by
    their headings and labels."): anything printed is something, a placeholder G6 fails among
    it, "TBD"."""
    text = ("# Code\n\n```r\n# Not a heading\nx <- 1\n```\n\n# Table\n\n{{table.main}}\n\n"
            "# Figure\n\n![Forest plot](figures/forest.png)\n\n# Limitations\n\nTBD\n")
    assert empty_headings(text) == []


def test_a_tbd_under_a_heading_is_g6_s_and_a_placeholder_g6_passes_is_empty() -> None:
    """G6 fails "TBD", "TODO" and "XXX" as `model-artefact` wherever they stand, so a heading
    over one of them is said once, by G6; a placeholder G6 has no rule for is no statement,
    and the heading over it is empty (round 1 of #819)."""
    from manuscript_guard.gates.writing import judge_texts

    for word in ("TBD", "TODO: ask the authors", "XXX"):
        said, _totals = judge_texts([(Path("manuscript/main.md"),
                                      f"# Intro\n\nWords.\n\n# Funding\n\n{word}\n")])
        assert "model-artefact" in {finding.code for finding in said.findings}, word
    for word in ("TO CONFIRM WITH THE AUTHORS.", "[Placeholder]", "To be completed.",
                 "*Pending*"):
        assert [h.title for h in empty_headings(f"# Funding\n\n{word}\n")] == ["Funding"], word
    assert missing(stated(WHOLE.replace("# Funding\n\nThis work received no funding.\n",
                                        "**Funding:** To be confirmed by the authors.\n")),
                   FIVE) == ["funding"]


def test_markdown_s_comment_idiom_prints_nothing() -> None:
    text = "# Funding\n\n[//]: # (ask the funder's name)\n\n# Data sharing\n\n[note]: <>\n"
    assert [heading.title for heading in empty_headings(text)] == ["Funding", "Data sharing"]
    assert stated(text) == {"funding": "empty", "data": "empty"}
    # A footnote's definition prints.
    assert empty_headings("# Notes\n\n[^1]: The first note.\n") == []


def test_the_reference_list_s_heading_and_a_heading_with_no_title_are_passed_over() -> None:
    assert empty_headings("# Discussion\n\nD.\n\n### {#inclusion}\n\n# References\n") == []
    assert empty_headings("# Discussion\n\nD.\n\n# Bibliography\n\n::: {#refs}\n:::\n") == []


@pytest.mark.parametrize("title", ["Supplementary references", "Additional references",
                                   "Supplementary bibliography", "S4. References cited"])
def test_a_heading_the_bibliography_is_printed_under_is_not_empty(title: str) -> None:
    """Pandoc prints the bibliography at the end, under the supplement's own reference list
    (round 1 of #819); and a heading over it is not empty either."""
    assert empty_headings(f"# Sensitivity analyses\n\nS.\n\n# {title}\n") == []
    assert empty_headings(f"# Back matter\n\n## {title}\n") == []


def test_a_section_carried_on_into_the_next_file_is_not_empty(tmp_path: Path) -> None:
    project = _project(tmp_path, WHOLE + "\n# Appendix\n",
                       extra={"zz_appendix.md": "The appendix's own words.\n"})
    assert _said(project) == []


def test_an_empty_heading_of_the_supplement_is_said_in_its_file(tmp_path: Path) -> None:
    project = _project(tmp_path, WHOLE, supplement="# Sensitivity analyses\n\n<!-- -->\n")
    [finding] = check_statements(project).findings
    assert finding.code == EMPTY
    assert finding.path == tmp_path / "manuscript" / "supplementary" / "S1.md"
    assert finding.line == 1


# -------------------------------------------------------------------------- statements


def test_a_paper_with_no_statement_lacks_the_five_and_ai_use_only_where_used(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, "# Introduction\n\nWords.\n")
    assert [subject for _code, _severity, subject in _said(project)] == [
        "data", "ethics", "funding", "interests", "contributions"]
    used = {"ai_use": {"declared_by": "A", "declared_on": "2026-11-26",
                       "uses": [{"tool": "Claude Opus 5", "purpose": "editing"}]}}
    project = _project(tmp_path, "# Introduction\n\nWords.\n", authors=used)
    assert "ai_use" in [subject for _code, _severity, subject in _said(project)]


@pytest.mark.parametrize("written", [
    "**Data availability:** The data are held by the agency.",
    "Data availability statement:\n\nThe data are held by the agency.",
    "# Declarations\n\nData availability: the data are held by the agency.",
    "# Statements and declarations\n\nThe data sharing agreement forbids sharing the data.",
])  # fmt: skip
def test_a_statement_is_a_heading_a_label_or_a_declarations_section_s_words(
    written: str,
) -> None:
    text = WHOLE.replace("# Data availability\n\nThe data are held by the agency.\n",
                         written + "\n")
    assert missing(stated(text), FIVE) == []


@pytest.mark.parametrize("written", [
    "# Methods\n\n## Setting\n\nThe ethics committee of the hospital approved the study.",
    "# Data availability\n\nThe data are public, and no ethical approval was required.",
])  # fmt: skip
def test_an_ethics_statement_may_be_in_the_methods_or_a_denial_anywhere(written: str) -> None:
    text = WHOLE.replace("# Ethics\n\nThe committee approved the study (CPP 2021-12).\n",
                         written + "\n")
    assert missing(stated(text), FIVE) == []


@pytest.mark.parametrize("title", [
    "Code and data availability", "Data, Materials, and Software Availability",
    "Data accessibility", "Data and software availability", "Software and data availability",
    "Availability of data and materials", "Data sharing statement",
])  # fmt: skip
def test_a_data_statement_is_known_by_each_heading_journals_ask_for(title: str) -> None:
    """Copernicus's, PNAS's and others' headings (round 1 of #819), as a heading, numbered or
    not, and as a label."""
    for written in (f"# {title}\n\nThe data are held by the agency.\n",
                    f"# 6. {title}\n\nThe data are held by the agency.\n",
                    f"**{title}:** The data are held by the agency.\n"):
        text = WHOLE.replace("# Data availability\n\nThe data are held by the agency.\n",
                             written)
        assert missing(stated(text), FIVE) == [], written


def test_a_label_over_a_comment_states_nothing_in_a_declarations_section() -> None:
    """Springer's layout: a Declarations heading, each statement a label (round 1 of #819).
    The labels print, so the heading is not empty; each statement is missing."""
    text = ("# Introduction\n\nWords.\n\n# Declarations\n\n"
            "**Funding:** <!-- TO CONFIRM -->\n\n**Competing interests:** <!-- -->\n\n"
            "**Ethics approval:** <!-- -->\n\n"
            "**Availability of data and materials:** <!-- -->\n\n"
            "**Author contributions:** <!-- -->\n")
    assert empty_headings(text) == []
    assert missing(stated(text), FIVE) == list(FIVE)
    # A label over a comment heads nothing, the Data availability label after it included;
    # a PLOS statement whose roles come first is a statement, its roles no labels of their own.
    text = WHOLE.replace("# Ethics\n\nThe committee approved the study (CPP 2021-12).\n",
                         "# Declarations\n\n**Ethics approval:** <!-- -->\n\n"
                         "**Data sharing:** The data are held by the agency.\n")
    assert missing(stated(text), FIVE) == ["ethics"]
    text = WHOLE.replace("# Author contributions\n\nAE designed the study.\n\n",
                         "**Author contributions**\n\nFunding acquisition: AE.\n\n"
                         "Supervision: BS.\n\n")
    assert missing(stated(text), FIVE) == []


def test_a_credit_role_states_no_funding() -> None:
    """"Funding acquisition" is a role of the contributions statement, under a label or as a
    sentence of a Declarations section; an item of the ICMJE form is none either."""
    for declared in ("Author contributions: AE: Conceptualization, Funding acquisition.",
                     "AE did the Conceptualization and the Funding acquisition.",
                     "Grants or contracts from any entity: none."):
        text = WHOLE.replace("# Funding\n\nThis work received no funding.\n",
                             f"# Declarations\n\n{declared}\n")
        assert "funding" in missing(stated(text), FIVE), declared


def test_an_empty_methods_subsection_on_ethics_states_no_ethics() -> None:
    text = WHOLE.replace("# Ethics\n\nThe committee approved the study (CPP 2021-12).\n",
                         "# Methods\n\nA cohort.\n\n## Ethical approval\n\n<!-- to ask -->\n")
    assert stated(text)["ethics"] == "empty"


def test_a_statement_under_a_heading_in_another_language_is_not_read() -> None:
    """A known gap (DESIGN.md, Known gaps, "The statements every paper makes are found by
    their headings and labels."): English only."""
    text = WHOLE.replace("# Funding\n\nThis work received no funding.\n",
                         "# Financement\n\nAucun financement.\n")
    assert missing(stated(text), FIVE) == ["funding"]


def test_a_heading_of_another_kind_inside_one_is_not_its_statement() -> None:
    text = WHOLE.replace("# Funding\n\nThis work received no funding.\n\n"
                         "# Competing interests\n\nNone declared.\n",
                         "# Funding\n\n## Competing interests\n\nNone declared.\n")
    assert missing(stated(text), FIVE) == ["funding"]


def test_one_empty_heading_of_three_kinds_is_one_finding(tmp_path: Path) -> None:
    text = WHOLE.split("# Author contributions")[0] + (
        "# Contributors, funding and competing interests\n\n<!-- TO FILL BY THE AUTHORS -->\n")
    [finding] = check_statements(_project(tmp_path, text), "internal-review").findings
    assert (finding.code, finding.severity) == (EMPTY, FAIL)
    assert ("the manuscript has no funding statement, competing interests statement or author "
            "contributions statement") in finding.message


def test_a_kind_stated_elsewhere_is_not_said_to_be_missing_under_its_empty_heading(
    tmp_path: Path,
) -> None:
    text = WHOLE + "\n# Funding sources\n\n<!-- -->\n"
    [finding] = check_statements(_project(tmp_path, text)).findings
    assert finding.code == EMPTY and finding.message.endswith("has nothing under it")


def test_a_profile_that_lists_the_journal_s_statements_asks_for_them_and_this_asks_none(
    tmp_path: Path,
) -> None:
    profiles = tmp_path / "profiles" / "journals"
    profiles.mkdir(parents=True)
    (profiles / "j.yaml").write_text(
        "schema: manuscript-guard/journal/1\nname: J\nretrieved_on: 2026-11-26\n"
        "source_url: https://example.org/j\nrequired_statements:\n"
        "  - id: funding\n    pattern: '(?im)^#+\\s*funding'\n", encoding="utf-8")
    text = "# Introduction\n\nWords.\n\n# Discussion\n\n<!-- -->\n"
    project = _project(tmp_path, text, paper={"target_journal": "j"})
    assert _said(project) == [(EMPTY, WARN, "Discussion")]


@pytest.mark.parametrize(("stage", "severity"), [
    ("design", INFO), ("analysis", INFO), ("drafting", WARN), (None, WARN),
    ("internal-review", FAIL), ("submission", FAIL),
])  # fmt: skip
def test_each_finding_is_a_note_then_a_warning_then_a_failure(stage, severity) -> None:
    assert severity_at(stage) == severity


def test_a_latex_manuscript_s_statements_are_read_and_its_headings_are_not(
    tmp_path: Path,
) -> None:
    (tmp_path / "manuscript").mkdir()
    (tmp_path / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\nWords.\n"
        "\\section{Funding}\n% to write\n\\section{Competing interests}\nNone declared.\n"
        "\\end{document}\n", encoding="utf-8")
    project = Project(tmp_path, {"schema": "manuscript-guard/paper/1"}, None)
    said = _said(project)
    assert {code for code, _severity, _subject in said} == {MISSING}
    assert {subject for _code, _severity, subject in said} == {
        "data", "ethics", "funding", "contributions"}


def test_a_statement_in_the_supplement_is_read(tmp_path: Path) -> None:
    """As G4 reads the declarations and the AI-use statement (round 1 of #819)."""
    used = {"ai_use": {"declared_by": "A", "declared_on": "2026-11-26",
                       "uses": [{"tool": "Claude Opus 5", "purpose": "editing"}]}}
    project = _project(tmp_path, WHOLE, authors=used,
                       supplement="# Use of AI\n\nClaude Opus 5 edited the English.\n")
    assert _said(project) == []
    project = _project(tmp_path, WHOLE, authors=used, supplement="# Use of AI\n\n<!-- -->\n")
    [finding] = check_statements(project).findings
    assert finding.code == EMPTY and finding.message.endswith("has no AI-use statement")


# ------------------------------------------------------------------------------- the run


def _gate_codes(root: Path, stage: str = "drafting") -> list[tuple[str, str]]:
    from manuscript_guard.cli import _run_gates

    report, *_ = _run_gates(root, stage=stage)
    return sorted((f.code, f.subject or "") for f in report.findings if f.code in (
        MISSING, "funding-not-stated", "interests-not-stated", "ai-use-not-stated"))


def test_one_gap_is_one_finding_with_the_notes_of_g4_s_other_checks(tmp_path: Path) -> None:
    """Where `declaration-missing` asks for the funding, competing interests or AI-use
    statement, the note that says the same is not raised, and what it said of the records is
    in the hint (round 1 of #819)."""
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "paper"
    init_project(root, title="A study")
    (root / "manuscript" / "main.md").write_text(
        WHOLE.split("# Funding")[0], encoding="utf-8")
    authors = (root / "authors.yaml").read_text(encoding="utf-8")
    (root / "authors.yaml").write_text(
        "schema: manuscript-guard/authors/1\nauthors:\n"
        "  - given: Ada\n    family: Example\n    funding: ['Agence (ANR-20-CE17-0001)']\n"
        "    competing_interests: Consulting fees from Pharma X.\n"
        "ai_use:\n  declared_by: Ada Example\n  declared_on: 2026-11-26\n  uses:\n"
        "    - tool: Claude Opus 5\n      purpose: editing\n", encoding="utf-8")
    assert authors  # init wrote one, replaced here
    assert _gate_codes(root) == [(MISSING, "ai_use"), (MISSING, "funding"),
                                 (MISSING, "interests")]
    report, *_ = _run_gates(root, stage="drafting")
    hints = {f.subject: f.hint for f in report.findings if f.code == MISSING}
    assert "ANR-20-CE17-0001" in hints["funding"]
    assert "Consulting fees from Pharma X." in hints["interests"]
    assert "Claude Opus 5" in hints["ai_use"]


def test_a_new_project_is_warned_while_drafting_and_told_before(tmp_path: Path) -> None:
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="Something new")
    for stage, severity in (("design", INFO), ("drafting", WARN)):
        report, *_ = _run_gates(root, stage=stage)
        ours = {(f.code, f.severity) for f in report.findings if f.code in (EMPTY, MISSING)}
        assert ours == {(EMPTY, severity), (MISSING, severity)}, ours
