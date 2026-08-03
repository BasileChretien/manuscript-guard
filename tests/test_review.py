"""G11 — the manuscript has been reviewed by a recorded panel.

The gate's severity depends on what is being built, so most tests assert both: a warning
during ordinary work and a failure for a submission. An author mid-draft must be able to
produce a document to read.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_review, manuscript_digest, open_panel, panels

PANEL_1 = Path("review") / "panel-1.yaml"
PANEL_2 = Path("review") / "panel-2.yaml"
BIOSTAT = Path("review") / "round-1" / "biostatistician.yaml"


def report_for(root: Path, *, submission: bool = False):
    project, _ = load_project(root)
    return check_review(project, submission=submission)


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


def failures(report) -> set[str]:
    return {f.code for f in report.failures}


def edit_yaml(path: Path, mutate) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- the complete case


def test_the_example_passes_a_submission_check(project: Path) -> None:
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    assert report.counts["review_rounds_complete"] == 2
    assert report.counts["review_open_major"] == 0


def test_every_review_applies_to_the_current_manuscript(project: Path) -> None:
    projekt, _ = load_project(project)
    digest = manuscript_digest(projekt)
    for path in (project / "review").rglob("*.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert document["manuscript_sha256"] == digest, path.name


# ---------------------------------------------------------------- no review at all


def test_an_unreviewed_manuscript_informs_but_does_not_block_a_draft(project: Path) -> None:
    shutil.rmtree(project / "review")
    report = report_for(project)
    assert "no-review" in codes(report)
    assert report.ok, "a draft build must not require a completed review"


def test_an_unreviewed_manuscript_blocks_a_submission(project: Path) -> None:
    shutil.rmtree(project / "review")
    assert "no-review" in failures(report_for(project, submission=True))


# ---------------------------------------------------------------- incomplete rounds


def test_a_reviewer_who_has_not_reported_is_named(project: Path) -> None:
    (project / BIOSTAT).unlink()
    report = report_for(project, submission=True)
    assert "review-missing" in failures(report)
    assert any("biostatistician" in f.message for f in report.failures)


def test_a_missing_reviewer_only_warns_on_a_draft(project: Path) -> None:
    (project / BIOSTAT).unlink()
    report = report_for(project)
    assert report.ok
    assert "review-missing" in codes(report)


def test_too_few_rounds_is_reported(project: Path) -> None:
    shutil.rmtree(project / "review" / "round-2")
    (project / PANEL_2).unlink()
    report = report_for(project, submission=True)
    assert "rounds-outstanding" in failures(report)


def test_the_required_number_of_rounds_is_configurable(project: Path) -> None:
    shutil.rmtree(project / "review" / "round-2")
    (project / PANEL_2).unlink()
    edit_yaml(project / "paper.yaml", lambda d: d.update(review={"rounds_required": 1}))
    assert report_for(project, submission=True).ok


# ---------------------------------------------------------------- staleness


def test_editing_the_manuscript_makes_the_reviews_stale(project: Path) -> None:
    """A review of the old Results is not a review of the new ones."""
    path = project / "manuscript" / "main.md"
    edited = path.read_text(encoding="utf-8") + "\n\nAn added paragraph.\n"
    path.write_text(edited, encoding="utf-8")
    report = report_for(project, submission=True)
    assert "review-stale" in failures(report)
    assert len([f for f in report.failures if f.code == "review-stale"]) == 5


# ---------------------------------------------------------------- open findings


def test_an_unanswered_major_finding_blocks_a_submission(project: Path) -> None:
    def mutate(document):
        document["findings"][0]["resolution"] = ""
        document["findings"][0].pop("overridden", None)

    edit_yaml(project / BIOSTAT, mutate)
    report = report_for(project, submission=True)
    assert "open-major-finding" in failures(report)
    assert report.counts["review_open_major"] == 1


def test_an_override_answers_a_major_finding(project: Path) -> None:
    """A recorded reason is a legitimate answer to a reviewer; silence is not."""

    def mutate(document):
        document["findings"][0]["resolution"] = ""
        document["findings"][0]["overridden"] = "The cell counts are large; no action needed."

    edit_yaml(project / BIOSTAT, mutate)
    assert report_for(project, submission=True).ok


def test_unanswered_minor_findings_do_not_block(project: Path) -> None:
    def mutate(document):
        for finding in document["findings"]:
            if finding["severity"] != "major":
                finding["resolution"] = ""
                finding.pop("overridden", None)

    edit_yaml(project / BIOSTAT, mutate)
    assert report_for(project, submission=True).ok


def test_an_open_finding_is_reported_with_its_text(project: Path) -> None:
    def mutate(document):
        document["findings"][0]["resolution"] = ""
        document["findings"][0].pop("overridden", None)

    edit_yaml(project / BIOSTAT, mutate)
    finding = next(f for f in report_for(project).findings if f.code == "open-major-finding")
    assert "biostatistician" in finding.message
    assert "contingency table" in finding.message


# ---------------------------------------------------------------- blinding


def test_an_unblinded_second_round_warns(project: Path) -> None:
    """A second panel that read the first inherits its blind spots."""
    edit_yaml(project / PANEL_2, lambda d: d.update(blinded=False))
    report = report_for(project)
    assert "round-not-blinded" in codes(report)


def test_the_first_round_is_not_expected_to_be_blinded(project: Path) -> None:
    assert not yaml.safe_load((project / PANEL_1).read_text(encoding="utf-8"))["blinded"]
    assert "round-not-blinded" not in codes(report_for(project))


# ---------------------------------------------------------------- panel mechanics


def test_opening_a_panel_records_the_manuscript_it_saw(project: Path) -> None:
    projekt, _ = load_project(project)
    path = open_panel(
        projekt,
        3,
        [{"id": "adversarial", "remit": "Find the reason to reject."}],
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["manuscript_sha256"] == manuscript_digest(projekt)
    assert document["blinded"] is True, "rounds after the first default to blinded"
    assert (project / "review" / "round-3").is_dir()


def test_a_first_panel_defaults_to_unblinded(project: Path) -> None:
    shutil.rmtree(project / "review")
    projekt, _ = load_project(project)
    path = open_panel(projekt, 1, [{"id": "someone", "remit": "Everything."}])
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["blinded"] is False


def test_panels_are_found_in_order(project: Path) -> None:
    projekt, _ = load_project(project)
    assert [number for number, _path in panels(projekt)] == [1, 2]


@pytest.mark.parametrize("field", ["remit", "id"])
def test_a_panel_missing_a_required_field_is_rejected(project: Path, field: str) -> None:
    edit_yaml(project / PANEL_1, lambda d: d["reviewers"][0].pop(field))
    assert "schema-violation" in failures(report_for(project))


def test_the_digest_changes_with_the_manuscript_and_not_otherwise(project: Path) -> None:
    projekt, _ = load_project(project)
    before = manuscript_digest(projekt)
    assert manuscript_digest(projekt) == before
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "x", encoding="utf-8")
    assert manuscript_digest(projekt) != before
