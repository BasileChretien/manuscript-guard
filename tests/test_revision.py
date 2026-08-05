"""G13 — the response to the reviewers says what actually happened.

A point-by-point response is a document made almost entirely of claims about the paper, and
nothing verified any of them. The commonest failure is not dishonesty: it is a response
written before the change, and the change then made differently, or not at all.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_revision


def opened(root: Path, points: list[dict]) -> Path:
    """A revision round whose baseline is the manuscript as it stands now."""
    from manuscript_guard.gates.review import file_digests

    project, _ = load_project(root)
    path = root / "revision" / "round-1.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "manuscript-guard/revision/1",
                "round": 1,
                "journal": "demo-journal",
                "received_on": "2026-08-04",
                "submitted_files": file_digests(project),
                "reviewers": [{"id": "reviewer-1", "points": points}],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


def report_for(root: Path, *, submission: bool = True):
    project, _ = load_project(root)
    return check_revision(project, submission=submission)


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


def revise(root: Path) -> None:
    path = root / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later sentence.\n", encoding="utf-8")


# ---------------------------------------------------------------- nothing to answer


def test_a_paper_with_no_revision_round_says_nothing(project: Path) -> None:
    """The ordinary state of a paper nobody has submitted. Inventing a finding here would
    teach an author to ignore this gate."""
    report = report_for(project)
    assert report.ok
    assert report.counts["revision_rounds"] == 0


# ---------------------------------------------------------------- the claim it checks


def test_a_claimed_revision_that_did_not_happen_is_caught(project: Path) -> None:
    """The point of the gate. "We have revised the Methods" is a claim like any other."""
    opened(
        project,
        [
            {
                "id": "1.1",
                "comment": "The case definition is not stated.",
                "response": "We have revised the Methods.",
                "changed": [{"kind": "manuscript", "name": "main.md"}],
            }
        ],
    )
    assert "claimed-change-did-not-happen" in codes(report_for(project))


def test_the_same_claim_passes_once_the_file_really_changes(project: Path) -> None:
    opened(
        project,
        [
            {
                "id": "1.1",
                "comment": "The case definition is not stated.",
                "response": "We have revised the Methods.",
                "changed": [{"kind": "manuscript", "name": "main.md"}],
            }
        ],
    )
    revise(project)
    report = report_for(project)
    assert report.ok, report.render(project)
    assert report.counts["revision_points_answered"] == 1


def test_a_response_naming_a_results_key_nothing_emits_is_caught(project: Path) -> None:
    opened(
        project,
        [
            {
                "id": "1.2",
                "comment": "Report the absolute counts.",
                "response": "Added.",
                "changed": [{"kind": "results", "name": "case.n_invented"}],
            }
        ],
    )
    assert "claimed-change-did-not-happen" in codes(report_for(project))


def test_a_response_naming_a_real_results_key_is_accepted(project: Path) -> None:
    opened(
        project,
        [
            {
                "id": "1.2",
                "comment": "Report the absolute counts.",
                "response": "Added.",
                "changed": [{"kind": "results", "name": "case.n_cases"}],
            }
        ],
    )
    assert report_for(project).ok


def test_a_response_naming_a_file_that_is_not_in_the_manuscript_is_caught(project: Path) -> None:
    opened(
        project,
        [
            {
                "id": "1.3",
                "comment": "Revise the supplement.",
                "response": "Done.",
                "changed": [{"kind": "manuscript", "name": "supplement.md"}],
            }
        ],
    )
    assert "claimed-change-did-not-happen" in codes(report_for(project))


# ---------------------------------------------------------------- answering at all


def test_an_unanswered_point_blocks_a_resubmission(project: Path) -> None:
    opened(project, [{"id": "1.4", "comment": "Explain the denominator.", "response": ""}])
    assert "point-unanswered" in codes(report_for(project))


def test_a_response_that_claims_nothing_is_caught(project: Path) -> None:
    """"Done." with nothing named cannot be checked against the paper at all."""
    opened(project, [{"id": "1.5", "comment": "Fix the typo.", "response": "Done."}])
    assert "response-claims-nothing" in codes(report_for(project))


def test_a_reasoned_rebuttal_is_a_complete_answer(project: Path) -> None:
    """Disagreeing with a reviewer is often the right answer, and is not the same as
    ignoring them. The record is what makes it a decision."""
    opened(
        project,
        [
            {
                "id": "1.6",
                "comment": "Use a Bayesian model.",
                "response": "We have not made this change.",
                "rebutted": "The synthetic data do not support it.",
            }
        ],
    )
    report = report_for(project)
    assert report.ok, report.render(project)


def test_an_empty_rebuttal_does_not_answer_anything(project: Path) -> None:
    opened(
        project,
        [
            {
                "id": "1.7",
                "comment": "Use a Bayesian model.",
                "response": "No.",
                "rebutted": "   ",
            }
        ],
    )
    assert "response-claims-nothing" in codes(report_for(project))


# ---------------------------------------------------------------- severity and rendering


def test_an_unanswered_point_only_warns_mid_revision(project: Path) -> None:
    """An author part-way through a revision must still be able to build something to read."""
    opened(project, [{"id": "1.8", "comment": "Explain the denominator.", "response": ""}])
    report = report_for(project, submission=False)
    assert report.ok
    assert "point-unanswered" in codes(report)


def test_the_response_document_carries_every_point(project: Path) -> None:
    from manuscript_guard.cli import main

    opened(
        project,
        [
            {
                "id": "1.1",
                "comment": "The case definition is not stated.",
                "response": "We have revised the Methods.",
                "changed": [{"kind": "manuscript", "name": "main.md", "note": "definition added"}],
            },
            {
                "id": "1.2",
                "comment": "Use a Bayesian model.",
                "response": "We prefer not to.",
                "rebutted": "The synthetic data do not support it.",
            },
        ],
    )
    revise(project)
    main(["respond", str(project)])

    letter = (project / "build" / "response-to-reviewers.md").read_text(encoding="utf-8")
    assert "The case definition is not stated." in letter
    assert "We have revised the Methods." in letter
    assert "definition added" in letter
    assert "We have not made this change: The synthetic data do not support it." in letter


def test_opening_a_round_records_the_manuscript_as_submitted(project: Path) -> None:
    """Without a baseline there is nothing to check a claimed revision against."""
    from manuscript_guard.cli import main
    from manuscript_guard.gates.review import file_digests

    assert main(["respond", str(project), "--open"]) == 0
    document = yaml.safe_load(
        (project / "revision" / "round-1.yaml").read_text(encoding="utf-8")
    )
    projekt, _ = load_project(project)
    assert document["submitted_files"] == file_digests(projekt)
