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


# ---------------------------------------------------------------- the resubmission pack


def _answered(project: Path) -> None:
    """A round with every point answered and the manuscript really revised."""
    opened(
        project,
        [
            {
                "id": "1.1",
                "comment": "The case definition is not stated.",
                "response": "We have revised the Methods.",
                "changed": [{"kind": "manuscript", "name": "main.md", "note": "definition added"}],
            }
        ],
    )
    revise(project)


def test_the_response_letter_reaches_the_submission_pack(project: Path) -> None:
    """The one artefact whose claims G13 actually checks was the one not sent.

    `respond` wrote it into build/ and nothing collected it, so a resubmission pack held the
    revised manuscript and no answer to the reviewers — the document a resubmission is judged
    on as much as the paper.
    """
    from manuscript_guard.build import assemble_pack

    _answered(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(load_project(project)[0], document)
    letter = next(p for p in pack.files if p.name == "response-to-reviewers.md")
    assert "The case definition is not stated." in letter.read_text(encoding="utf-8")


def test_a_first_submission_has_no_response_letter(project: Path) -> None:
    """A letter answering nobody is worse than none: an editor reads it as a resubmission."""
    from manuscript_guard.build import assemble_pack

    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(load_project(project)[0], document)
    assert not any(p.name == "response-to-reviewers.md" for p in pack.files)
    manifest = yaml.safe_load(pack.manifest.read_text(encoding="utf-8"))
    assert manifest["submission"] == "first submission"


def test_the_pack_says_which_submission_this_is(project: Path) -> None:
    """A pack for a revision and a pack for a first submission were byte-indistinguishable
    in this respect, and "which version did the journal get" is a question about a round as
    much as about a checksum."""
    from manuscript_guard.build import assemble_pack

    _answered(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    manifest = yaml.safe_load(
        assemble_pack(load_project(project)[0], document).manifest.read_text(encoding="utf-8")
    )
    assert manifest["submission"] == "revision 1"


def test_the_packed_letter_is_generated_not_collected(project: Path) -> None:
    """Read out of build/, the pack would send whatever `respond` last happened to write.

    G13 checks the claims in the revision records; a stale letter means a checked set of
    claims and an unchecked document making them.
    """
    from manuscript_guard.build import assemble_pack
    from manuscript_guard.cli import main

    _answered(project)
    assert main(["respond", str(project)]) in (0, 1)

    stale = project / "build" / "response-to-reviewers.md"
    stale.write_text("# Nothing to see here\n", encoding="utf-8")

    document = project / "build" / "manuscript.docx"
    document.write_bytes(b"PK\x03\x04 placeholder")
    pack = assemble_pack(load_project(project)[0], document)
    packed = next(p for p in pack.files if p.name == "response-to-reviewers.md")
    assert "Nothing to see here" not in packed.read_text(encoding="utf-8")
    assert "The case definition is not stated." in packed.read_text(encoding="utf-8")


def test_the_letter_a_person_reads_is_the_letter_that_is_sent(project: Path) -> None:
    """Two renderers would drift, and the drift would be invisible: both look like letters."""
    from manuscript_guard.build.submission import response_letter
    from manuscript_guard.cli import main

    _answered(project)
    assert main(["respond", str(project)]) in (0, 1)
    written = (project / "build" / "response-to-reviewers.md").read_text(encoding="utf-8")
    assert written == response_letter(load_project(project)[0])
