"""Journal limits and reporting checklists.

The example carries an openly invented journal and checklist, the same way it carries
invented literature sources: no real journal's guidelines and no real guideline's item text
ship with this toolkit, because both change and both would be wrong silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_journal, check_reporting, scaffold_completion
from manuscript_guard.text.sections import count_words, headings, measure, split_sections

JOURNAL = Path("profiles") / "journals" / "demo-journal.yaml"


def test_the_shipped_template_is_a_valid_profile() -> None:
    """The template is the first thing an author edits, so it must not start out broken.

    It also has to keep validating as the schema changes, which is the whole reason this is
    a test rather than a promise in the documentation.
    """
    from manuscript_guard.contracts._schema import read_structured, validate
    from manuscript_guard.paths import SHIPPED_JOURNALS

    path = SHIPPED_JOURNALS / "TEMPLATE.yaml"
    report = validate(read_structured(path), "journal", path)
    assert report.ok, report.render()


def test_the_template_is_not_offered_as_a_journal(project: Path) -> None:
    """It names no journal. Listing it as one invites `target_journal: TEMPLATE`."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.journal import available_profiles

    loaded, _ = load_project(project)
    assert "TEMPLATE" not in available_profiles(loaded)
CHECKLIST = Path("reporting") / "DEMO-OBS.yaml"


def journal_report(root: Path):
    project, _ = load_project(root)
    return check_journal(project)


def reporting_report(root: Path):
    project, _ = load_project(root)
    return check_reporting(project)


def codes(report) -> set[str]:
    return {f.code for f in report.failures}


def edit_yaml(path: Path, mutate) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- counting


def test_words_exclude_what_journals_exclude() -> None:
    text = (
        "Prose here [@smith2020] and more prose.\n\n"
        "| a | b |\n| - | - |\n| 1 | 2 |\n\n"
        ": A caption.\n\n"
        "![](figures/x.png)\n\n"
        "`code_token` and **bold** words.\n"
    )
    # "Prose here and more prose" = 5, "code_token and bold words" = 4 (code is masked).
    assert count_words(text) == 8


def test_sections_are_split_on_top_level_headings() -> None:
    text = "# Abstract\n\nA.\n\n# Methods\n\nB.\n\n## Detail\n\nC.\n\n# References\n\nD.\n"
    sections = split_sections(text)
    assert [s.title for s in sections] == ["Abstract", "Methods", "Detail", "References"]
    assert sections[0].is_abstract
    assert sections[-1].is_references


def test_the_abstract_and_references_are_counted_apart(project: Path) -> None:
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    counts = measure(text)
    assert counts.abstract_words > 0
    assert counts.main_text_words > counts.abstract_words
    assert counts.tables == 2  # baseline characteristics and the 2 x 2
    assert counts.figures == 1


def test_headings_are_found_for_the_checklist_to_point_at(project: Path) -> None:
    found = headings((project / "manuscript" / "main.md").read_text(encoding="utf-8"))
    assert {"Abstract", "Methods", "Results", "Discussion", "Funding"} <= set(found)


# ---------------------------------------------------------------- the journal gate


def test_the_example_satisfies_its_journal(project: Path) -> None:
    report = journal_report(project)
    assert report.ok, report.render(project)
    assert report.counts["main_text_words"] > 0


def test_no_journal_chosen_is_information_not_failure(project: Path) -> None:
    path = project / "paper.yaml"
    edit_yaml(path, lambda d: d.pop("target_journal"))
    report = journal_report(project)
    assert report.ok
    assert any(f.code == "no-journal-chosen" for f in report.findings)


def test_an_unknown_journal_is_a_failure(project: Path) -> None:
    edit_yaml(project / "paper.yaml", lambda d: d.update(target_journal="not-a-journal"))
    assert "journal-profile-missing" in codes(journal_report(project))


def test_exceeding_a_word_limit_is_caught(project: Path) -> None:
    edit_yaml(project / JOURNAL, lambda d: d["limits"].update(main_text_words=50))
    report = journal_report(project)
    assert "over-journal-limit" in codes(report)
    assert any("limit 50" in f.message for f in report.failures)


def test_approaching_a_limit_warns(project: Path) -> None:
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    actual = measure(text).main_text_words
    edit_yaml(project / JOURNAL, lambda d: d["limits"].update(main_text_words=actual + 1))
    report = journal_report(project)
    assert report.ok
    assert any(f.code == "near-journal-limit" for f in report.warnings)


def test_too_many_display_items_is_caught(project: Path) -> None:
    edit_yaml(project / JOURNAL, lambda d: d["limits"].update(figures=0))
    assert "over-journal-limit" in codes(journal_report(project))


def test_a_missing_required_statement_is_caught(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("# Funding", "# Acknowledgements"),
        encoding="utf-8",
    )
    report = journal_report(project)
    assert "missing-required-statement" in codes(report)
    assert any("funding" in f.message for f in report.failures)


def test_a_missing_required_section_is_caught(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("# Methods", "# How we did it"), encoding="utf-8"
    )
    assert "missing-required-section" in codes(journal_report(project))


def test_a_structured_abstract_missing_a_heading_is_caught(project: Path) -> None:
    def mutate(document):
        document["structure"]["abstract_headings"] = ["Background", "Methods", "Objective"]

    edit_yaml(project / JOURNAL, mutate)
    report = journal_report(project)
    assert "abstract-headings-missing" in codes(report)
    assert any("Objective" in f.message for f in report.failures)


def test_an_english_variant_clash_is_caught(project: Path) -> None:
    edit_yaml(project / JOURNAL, lambda d: d.update(english_variant="en-US"))
    assert "english-variant-mismatch" in codes(journal_report(project))


def test_an_old_profile_warns(project: Path) -> None:
    edit_yaml(project / JOURNAL, lambda d: d.update(retrieved_on="2020-01-01"))
    report = journal_report(project)
    assert any(f.code == "journal-profile-stale" for f in report.warnings)


# ---------------------------------------------------------------- the reporting gate


def test_the_example_checklist_is_complete(project: Path) -> None:
    report = reporting_report(project)
    assert report.ok, report.render(project)
    assert report.counts["checklists_complete"] == 1


def test_a_guideline_with_no_retrieved_checklist_fails_loudly(project: Path) -> None:
    """The one thing it must not do is pass quietly.

    A name no recipe will ever produce, so this keeps testing the missing case even as
    more checklists are transcribed into the shipped profiles directory.
    """
    edit_yaml(project / "paper.yaml", lambda d: d.update(reporting_guideline=["NOT-A-GUIDELINE"]))
    report = reporting_report(project)
    assert "checklist-not-retrieved" in codes(report)
    assert any("reporting-checklist skill" in (f.hint or "") for f in report.failures)


def test_an_unanswered_item_is_caught(project: Path) -> None:
    edit_yaml(project / CHECKLIST, lambda d: d["items"][3].update(where=""))
    assert "checklist-item-unanswered" in codes(reporting_report(project))


def test_a_tick_is_not_a_reason(project: Path) -> None:
    def mutate(document):
        document["items"][3].update(where="", not_applicable="n/a")

    edit_yaml(project / CHECKLIST, mutate)
    report = reporting_report(project)
    assert "checklist-non-reason" in codes(report)


@pytest.mark.parametrize("reason", ["no interventions were assigned", "the study had no follow-up"])
def test_a_real_reason_is_accepted(project: Path, reason: str) -> None:
    def mutate(document):
        document["items"][3].update(where="", not_applicable=reason)

    edit_yaml(project / CHECKLIST, mutate)
    assert reporting_report(project).ok


def test_pointing_at_a_section_that_does_not_exist_warns(project: Path) -> None:
    edit_yaml(project / CHECKLIST, lambda d: d["items"][0].update(where="Appendix Q"))
    report = reporting_report(project)
    assert any(f.code == "checklist-location-unknown" for f in report.warnings)


def test_a_dropped_item_is_caught(project: Path) -> None:
    edit_yaml(project / CHECKLIST, lambda d: d["items"].pop(2))
    assert "checklist-item-missing" in codes(reporting_report(project))


def test_an_item_the_guideline_does_not_have_warns(project: Path) -> None:
    edit_yaml(project / CHECKLIST, lambda d: d["items"].append({"id": "99", "where": "Methods"}))
    report = reporting_report(project)
    assert any(f.code == "checklist-item-unknown" for f in report.warnings)


def test_no_checklist_file_at_all_is_caught(project: Path) -> None:
    (project / CHECKLIST).unlink()
    assert "checklist-not-started" in codes(reporting_report(project))


def test_scaffolding_preserves_answers_already_given(project: Path) -> None:
    project_obj, _ = load_project(project)
    before = yaml.safe_load((project / CHECKLIST).read_text(encoding="utf-8"))
    path, total, added = scaffold_completion(project_obj, "DEMO-OBS")
    after = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert added == 0
    assert total == len(before["items"])
    assert [i.get("where") for i in after["items"]] == [i.get("where") for i in before["items"]]


def test_scaffolding_adds_only_new_items(project: Path) -> None:
    edit_yaml(project / CHECKLIST, lambda d: d["items"].pop())
    project_obj, _ = load_project(project)
    _path, _total, added = scaffold_completion(project_obj, "DEMO-OBS")
    assert added == 1
