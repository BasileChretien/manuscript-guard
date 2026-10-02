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
from manuscript_guard.findings import INFO
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


# ------------------------------------------------ what a review says it read (file_sha256)


def scope_reviews(root: Path, files: dict[str, str] | None = None, *, only: str = "") -> None:
    """Give every review record in the project a `file_sha256` map."""
    from manuscript_guard.gates.review import file_digests

    digests = file_digests(load_project(root)[0]) if files is None else files
    for path in sorted((root / "review").rglob("*.yaml")):
        if only and path.stem != only:
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema", "").endswith("panel/1"):
            continue
        document["file_sha256"] = dict(digests)
        path.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


def split_manuscript(root: Path) -> tuple[Path, Path]:
    """Two files where the example has one, so scoping has something to scope."""
    main = root / "manuscript" / "main.md"
    discussion = root / "manuscript" / "zz-discussion.md"
    discussion.write_text(
        "# Discussion\n\nThe finding is, on the whole, consistent with the literature.\n",
        encoding="utf-8",
    )
    return main, discussion


def test_editing_one_file_does_not_void_a_review_of_another(project: Path) -> None:
    """`review-stale` is a hard failure at submission, and it fired on a comma.

    `manuscript_digest` hashes every byte of every manuscript file together, so a typo fixed
    in the Discussion invalidated both completed panel rounds — including the
    biostatistician's read of the Methods. Copy-editing is the last thing anyone does to a
    paper, which put the harshest check in the toolkit at the worst possible moment.
    """
    main, discussion = split_manuscript(project)
    scope_reviews(project)
    assert "review-stale" not in codes(report_for(project, submission=True))

    scope_reviews(project, only="biostatistician", files=_digests_of(project, main))
    discussion.write_text(discussion.read_text(encoding="utf-8").replace(",", ""), encoding="utf-8")

    report = report_for(project, submission=True)
    stale = [f for f in report.findings if f.code == "review-stale"]
    assert stale, "reviewers who read the Discussion are stale"
    assert all("zz-discussion.md" in f.message for f in stale), "and it says which file moved"
    assert not any("biostatistician" in f.message for f in stale), (
        "the reviewer who only read the Methods is untouched"
    )


def test_a_reviewer_is_stale_when_the_file_they_read_changes(project: Path) -> None:
    main, _discussion = split_manuscript(project)
    scope_reviews(project)
    main.write_text(main.read_text(encoding="utf-8") + "\n\nA later thought.\n", encoding="utf-8")
    report = report_for(project, submission=True)
    assert "review-stale" in failures(report)
    assert all("main.md" in f.message for f in report.failures if f.code == "review-stale")


def test_a_file_nobody_read_leaves_the_round_incomplete(project: Path) -> None:
    """The hole that scoping would open, closed in the same change.

    Judging a record on the files it lists is only defensible while every manuscript file is
    on somebody's list. Otherwise a round of reviewers who each read the Methods would
    report complete over a Discussion none of them saw.
    """
    main, _discussion = split_manuscript(project)
    scope_reviews(project, files=_digests_of(project, main))
    report = report_for(project, submission=True)
    assert "review-uncovered" in failures(report)
    assert any("zz-discussion.md" in f.message for f in report.failures)
    assert report.counts["review_rounds_complete"] == 0


def test_a_record_that_lists_nothing_still_means_the_whole_manuscript(project: Path) -> None:
    """An older record falls back to what its writer intended, not to being current."""
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later thought.\n", encoding="utf-8")
    assert "review-stale" in codes(report_for(project, submission=True))
    assert "review-uncovered" not in codes(report_for(project, submission=True))


def test_one_unscoped_record_covers_the_round(project: Path) -> None:
    """A reviewer who read everything answers the coverage question for everyone."""
    main, _discussion = split_manuscript(project)
    scope_reviews(project, files=_digests_of(project, main), only="biostatistician")
    assert "review-uncovered" not in codes(report_for(project, submission=True))


def _digests_of(root: Path, *files: Path) -> dict[str, str]:
    import hashlib

    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def test_two_files_with_the_same_name_are_both_covered(project: Path) -> None:
    """`file_digests` keyed by filename, and `source_files` walks subdirectories.

    Two files sharing a name collapsed into one dict entry. The loser vanished not only
    from `file_sha256` but from the set `review-uncovered` subtracts from — so a whole
    file could be unreviewed while the round reported complete.
    """
    from manuscript_guard.gates.review import file_digests

    nested = project / "manuscript" / "parts"
    nested.mkdir()
    (nested / "main.md").write_text("# Extra\n\nA section nobody reviewed.\n", encoding="utf-8")

    keys = set(file_digests(load_project(project)[0]))
    # The supplement is in scope for review too: a finding list describes what the reviewer
    # read, and leaving the supplement out is what lets it change under a review that still
    # claims to cover the manuscript.
    assert keys == {"main.md", "parts/main.md", "supplementary/S1_code_lists.md"}, keys

    scope_reviews(project, files={"main.md": file_digests(load_project(project)[0])["main.md"]})
    report = report_for(project, submission=True)
    assert "review-uncovered" in failures(report)
    assert any("parts/main.md" in f.message for f in report.failures)


def test_a_duplicated_reviewer_id_is_reported(project: Path) -> None:
    """One review file answers every slot sharing its id, so a duplicate let one record
    stand in for two reviewers — and a panel's composition is the point of recording it."""

    def mutate(document):
        document["reviewers"].append(dict(document["reviewers"][0], remit="Something else."))

    edit_yaml(project / PANEL_1, mutate)
    report = report_for(project, submission=True)
    assert "duplicate-reviewer" in failures(report)


def test_editing_the_bibliography_makes_the_built_document_stale(project: Path) -> None:
    """An offline build bakes citeproc's output into the .docx from references.bib.

    Leaving that file out of the digest meant editing a reference's authors changed what
    the document says while the stamp still matched — the same slip `document_digest` was
    written to close, for the one input it forgot.
    """
    from manuscript_guard.gates.review import document_digest

    projekt, _ = load_project(project)
    bib = project / "literature" / "references.bib"
    before = document_digest(projekt)
    bib.write_text(
        bib.read_text(encoding="utf-8") + "\n@misc{extra, title={X}}\n", encoding="utf-8"
    )
    assert document_digest(projekt) != before


# ------------------------------------------------ after a revision: a later round supersedes


def revise(root: Path) -> None:
    path = root / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nAdded in revision.\n", "utf-8")


def record_round(root: Path, number: int, *reviewers: str) -> None:
    from manuscript_guard.record import write_review

    for reviewer in reviewers:
        write_review(
            load_project(root)[0],
            reviewer,
            verdict="minor-revision",
            round_number=number,
            remit="the revised manuscript as it now stands",
        )
    edit_yaml(project_panel(root, number), lambda d: d.update(blinded=True))


def project_panel(root: Path, number: int) -> Path:
    return root / "review" / f"panel-{number}.yaml"


def test_a_complete_later_round_supersedes_the_stale_ones(project: Path) -> None:
    """Editing the manuscript made every earlier record stale, and recording a new round —
    what `review --record` tells the author to do instead of re-stamping one — cleared none
    of them. The only ways to pass were hand-editing a digest or deleting a round."""
    revise(project)
    record_round(project, 3, "fresh-reader")

    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    superseded = [f for f in report.findings if f.code == "review-superseded"]
    assert len(superseded) == 5, [f.message for f in report.findings]
    assert all(f.severity == INFO and "round 3" in f.message for f in superseded)
    assert report.counts["review_rounds_complete"] == 3


def test_a_superseding_round_must_itself_be_current(project: Path) -> None:
    revise(project)
    record_round(project, 3, "fresh-reader")
    revise(project)

    report = report_for(project, submission=True)
    stale = [f for f in report.failures if f.code == "review-stale"]
    assert len(stale) == 6, "rounds one, two and three all describe an earlier manuscript"
    assert "review-superseded" not in codes(report)


def test_an_incomplete_later_round_supersedes_nothing(project: Path) -> None:
    revise(project)
    record_round(project, 3, "fresh-reader")
    edit_yaml(
        project_panel(project, 3),
        lambda d: d["reviewers"].append({"id": "absent-reader", "remit": "the Discussion"}),
    )

    report = report_for(project, submission=True)
    assert "review-missing" in failures(report)
    assert len([f for f in report.failures if f.code == "review-stale"]) == 5


def test_a_superseded_rounds_unanswered_major_finding_still_blocks(project: Path) -> None:
    """History is not absolution: what a reviewer raised still needs an answer."""
    edit_yaml(
        project / BIOSTAT,
        lambda d: d["findings"].append(
            {"id": "b-99", "severity": "major", "where": "Methods", "finding": "No model."}
        ),
    )
    revise(project)
    record_round(project, 3, "fresh-reader")

    report = report_for(project, submission=True)
    assert "open-major-finding" in failures(report)
    assert "review-stale" not in failures(report)


def test_a_file_added_in_revision_does_not_void_the_earlier_rounds(project: Path) -> None:
    """Scoped records cannot list a file written after them, so every earlier round was
    `review-uncovered` for ever, and `rounds_required` could not be met by one new round."""
    scope_reviews(project)
    split_manuscript(project)
    assert "review-uncovered" in failures(report_for(project, submission=True))

    record_round(project, 3, "fresh-reader")
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    assert "review-superseded" in codes(report)


def test_following_the_refusal_to_restamp_leads_somewhere(project: Path, capsys) -> None:
    """End to end, through the commands: the advice `review --record` gives when it refuses
    to re-stamp a record has to be advice that works."""
    from manuscript_guard.cli import main

    revise(project)
    args = ["review", str(project), "--record", "biostatistician", "--verdict", "pass"]
    assert main(args) == 2
    assert "further round" in capsys.readouterr().err

    assert main([*args, "--round", "3"]) == 0
    assert main(["check", str(project), "--submission"]) == 0, capsys.readouterr().out


def test_the_stale_hint_is_a_command_that_runs(project: Path) -> None:
    """The hint left out --verdict, which the command requires, so following it exited 2."""
    revise(project)
    stale = next(f for f in report_for(project).findings if f.code == "review-stale")
    assert "--verdict" in stale.hint


# ---------------------------------------------------------------- several readings of a remit
#
# One reviewer's remit can be read more than once: by several models, by a model and a
# person. Each reading is a record of its own, `<reviewer>.<reader>.yaml`, beside the plain
# `<reviewer>.yaml`. A panel may name the readers it expects of a reviewer, and then each of
# them has to file. A panel that names none is read exactly as before.

MODEL_A = "openai/model-a"
MODEL_B = "mistral/model-b"
DESK = Path("review") / "round-2" / "desk-editor.yaml"
DESK_A = Path("review") / "round-2" / "desk-editor.openai-model-a.yaml"
DESK_B = Path("review") / "round-2" / "desk-editor.mistral-model-b.yaml"


def add_reading(
    root: Path, reviewer: str, reader: str, *, number: int = 2, verdict: str = "minor-revision"
) -> Path:
    from manuscript_guard.record import write_review

    project, _ = load_project(root)
    return write_review(
        project, reviewer, verdict=verdict, round_number=number, reading=reader
    ).path


def expect_readers(root: Path, number: int, reviewer: str, *readers: str) -> None:
    def mutate(document):
        entry = next(r for r in document["reviewers"] if r["id"] == reviewer)
        entry["readers"] = list(readers)

    edit_yaml(project_panel(root, number), mutate)


def test_a_reading_by_a_model_counts_beside_a_record_filed_by_hand(project: Path) -> None:
    path = add_reading(project, "desk-editor", MODEL_A)
    assert path == project / DESK_A
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    assert report.counts["review_rounds_complete"] == 2
    assert report.counts["review_readings"] == 6


def test_a_remit_needs_one_reading_and_any_kind_will_do(project: Path) -> None:
    """A panel that names no readers is read as it always was, whoever filed."""
    (project / DESK).unlink()
    assert "review-missing" in failures(report_for(project, submission=True))
    add_reading(project, "desk-editor", MODEL_A)
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)


def test_a_reader_the_panel_names_must_report(project: Path) -> None:
    """One provider failing must not leave a round that looks complete."""
    expect_readers(project, 2, "desk-editor", MODEL_A, MODEL_B)
    add_reading(project, "desk-editor", MODEL_A)

    report = report_for(project, submission=True)
    missing = [f for f in report.failures if f.code == "reading-missing"]
    assert len(missing) == 1
    assert "desk-editor" in missing[0].message and MODEL_B in missing[0].message
    assert missing[0].path == project / DESK_B
    assert "rounds-outstanding" in failures(report)
    assert report.counts["review_rounds_complete"] == 1


def test_a_missing_reading_only_warns_on_a_draft(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", MODEL_A)
    report = report_for(project)
    assert report.ok
    assert "reading-missing" in codes(report)


def test_every_named_reader_reporting_completes_the_round(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", MODEL_A, MODEL_B)
    add_reading(project, "desk-editor", MODEL_A)
    add_reading(project, "desk-editor", MODEL_B)
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    assert report.counts["review_rounds_complete"] == 2


def test_a_record_filed_by_hand_does_not_stand_in_for_a_named_reader(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", MODEL_A)
    assert (project / DESK).exists()
    report = report_for(project, submission=True)
    assert "reading-missing" in failures(report)
    assert "review-missing" not in codes(report), "the remit was read, only not by that reader"


def test_a_person_can_be_a_named_reader(project: Path) -> None:
    """Mixed panels: a co-author's reading is asked for beside the models'."""
    expect_readers(project, 2, "desk-editor", MODEL_A, "Dr Tanaka")
    add_reading(project, "desk-editor", MODEL_A)
    assert "reading-missing" in failures(report_for(project, submission=True))
    path = add_reading(project, "desk-editor", "Dr Tanaka")
    assert path.name == "desk-editor.dr-tanaka.yaml"
    assert report_for(project, submission=True).ok


def test_a_major_finding_from_any_reader_must_be_answered(project: Path) -> None:
    """Another reader's clean reading of the same remit does not answer it."""
    path = add_reading(project, "desk-editor", MODEL_A, verdict="major-revision")
    edit_yaml(
        path,
        lambda d: d["findings"].append(
            {"id": "f1", "severity": "major", "finding": "The abstract claims a risk."}
        ),
    )
    report = report_for(project, submission=True)
    blocking = [f for f in report.failures if f.code == "open-major-finding"]
    assert len(blocking) == 1
    assert "desk-editor" in blocking[0].message and MODEL_A in blocking[0].message
    assert "The abstract claims a risk." in blocking[0].message

    edit_yaml(path, lambda d: d["findings"][0].update(overridden="It says reporting, not risk."))
    assert report_for(project, submission=True).ok


def test_an_open_finding_from_a_record_filed_by_hand_reads_as_before(project: Path) -> None:
    def mutate(document):
        document["findings"][0]["resolution"] = ""
        document["findings"][0].pop("overridden", None)

    edit_yaml(project / BIOSTAT, mutate)
    finding = next(f for f in report_for(project).findings if f.code == "open-major-finding")
    assert finding.message.startswith("biostatistician ")
    assert "[" not in finding.message.split(":")[0]


def test_a_reading_goes_stale_like_any_record(project: Path) -> None:
    add_reading(project, "desk-editor", MODEL_A)
    revise(project)
    stale = [f for f in report_for(project, submission=True).failures if f.code == "review-stale"]
    assert len(stale) == 6
    assert any(MODEL_A in f.message for f in stale)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(reader=MODEL_B),
        lambda d: d.update(reviewer="clinical-reader"),
        lambda d: d.update(round=1),
    ],
    ids=["another reader's name", "another reviewer", "another round"],
)
def test_a_reading_that_is_not_what_its_file_name_says_is_refused(project: Path, change) -> None:
    """The file name is how a reader is asked for and found. A record under one name that
    says another inside it is one reader's work standing in for another's."""
    expect_readers(project, 2, "desk-editor", MODEL_A)
    edit_yaml(add_reading(project, "desk-editor", MODEL_A), change)
    report = report_for(project, submission=True)
    assert "reading-misfiled" in failures(report)
    assert "reading-missing" in failures(report), "a misfiled record answers for nobody"
    assert report.counts["review_rounds_complete"] == 1


def test_a_copy_of_one_readers_record_does_not_answer_for_another(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", MODEL_A, MODEL_B)
    shutil.copy(add_reading(project, "desk-editor", MODEL_A), project / DESK_B)
    report = report_for(project, submission=True)
    assert "reading-misfiled" in failures(report)
    assert any(MODEL_B in f.message for f in report.failures if f.code == "reading-missing")


def test_two_records_claiming_one_reader_are_reported(project: Path) -> None:
    add_reading(project, "desk-editor", MODEL_A)
    edit_yaml(project / DESK, lambda d: d.update(reader=MODEL_A))
    report = report_for(project, submission=True)
    duplicate = [f for f in report.failures if f.code == "duplicate-reading"]
    assert len(duplicate) == 1 and MODEL_A in duplicate[0].message


def test_a_malformed_reading_leaves_the_round_unfinished(project: Path) -> None:
    (project / DESK_A).write_text(
        f"schema: manuscript-guard/review/1\nround: 2\nreader: {MODEL_A}\n", "utf-8"
    )
    report = report_for(project, submission=True)
    assert "schema-violation" in failures(report)
    assert report.counts["review_rounds_complete"] == 1


def test_a_copy_kept_beside_a_record_does_not_start_failing_a_submission(project: Path) -> None:
    """Before readings had names, `biostatistician.old.yaml` was nothing to the gate."""
    shutil.copy(project / BIOSTAT, project / "review" / "round-1" / "biostatistician.old.yaml")
    (project / "review" / "round-1" / "biostatistician.notes.yaml").write_text("- a note\n")
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    assert report.counts["review_readings"] == 5
    unnamed = [f for f in report.findings if f.code == "reading-unnamed"]
    assert sorted(f.path.name for f in unnamed) == [
        "biostatistician.notes.yaml",
        "biostatistician.old.yaml",
    ]


def test_a_reading_that_lost_its_reader_is_said_and_answers_for_nobody(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", MODEL_A)
    edit_yaml(add_reading(project, "desk-editor", MODEL_A), lambda d: d.pop("reader"))
    report = report_for(project, submission=True)
    assert "reading-unnamed" in codes(report)
    assert "reading-missing" in failures(report)


def test_a_file_that_only_looks_like_a_reading_of_another_reviewer_is_not_one(
    project: Path,
) -> None:
    """`desk-editor.x.yaml` is a reading for `desk-editor`, and never for `desk`."""
    edit_yaml(
        project_panel(project, 2),
        lambda d: d["reviewers"].append({"id": "desk", "remit": "the desk"}),
    )
    add_reading(project, "desk-editor", MODEL_A)
    report = report_for(project, submission=True)
    assert [f.message for f in report.failures if f.code == "review-missing"] == [
        "round 2: desk has not reported"
    ]


def test_the_strictest_verdict_is_reported_and_decides_nothing(project: Path) -> None:
    """G11 has never gated on a verdict: a record cannot be re-stamped, so a verdict could
    only be cleared by a further round. What blocks is an unanswered major finding."""
    from manuscript_guard.gates.review import round_summaries

    add_reading(project, "desk-editor", MODEL_A, verdict="reject")
    projekt, _ = load_project(project)
    first, second = round_summaries(projekt)
    assert (first.number, second.number) == (1, 2)
    assert second.strictest.verdict == "reject"
    assert (second.strictest.reviewer, second.strictest.reader) == ("desk-editor", MODEL_A)
    assert [(r.reviewer, r.reader) for r in second.readings] == [
        ("desk-editor", None),
        ("desk-editor", MODEL_A),
        ("clinical-reader", None),
    ]
    assert report_for(project, submission=True).ok


def test_the_status_names_each_reading_and_the_strictest_verdict(project: Path, capsys) -> None:
    from manuscript_guard.cli import main

    add_reading(project, "desk-editor", MODEL_A, verdict="reject")
    assert main(["review", str(project), "--submission"]) == 0
    out = capsys.readouterr().out
    assert "round 2: panel-2.yaml" in out
    assert "strictest verdict: reject (desk-editor, openai/model-a)" in out
    line = next(line for line in out.splitlines() if MODEL_A in line and "desk-editor" in line)
    assert "reject" in line


@pytest.mark.parametrize(
    "reader, slug",
    [
        ("openai/model-a", "openai-model-a"),
        ("openrouter/vendor/Model.4.1:free", "openrouter-vendor-model-4-1-free"),
        ("Dr Tanaka", "dr-tanaka"),
        ("--x--", "x"),
        ("///", ""),
    ],
)
def test_a_readers_name_as_part_of_a_file_name(reader: str, slug: str) -> None:
    from manuscript_guard.gates.review import reading_slug

    assert reading_slug(reader) == slug


def test_a_record_may_say_who_read_and_how_the_reading_was_made(project: Path) -> None:
    from manuscript_guard.contracts._schema import read_structured, validate

    path = project / DESK
    document = read_structured(path)
    document["reader"] = MODEL_A
    document["rejection_tests"] = [
        {"test": "The abstract claims more than the paper.", "holds": False, "evidence": "None."}
    ]
    document["provenance"] = {
        "provider": "openai",
        "model": "model-a",
        "model_reported": "model-a-2026-09-01",
        "host": "api.openai.com",
        "prompt_sha256": "0" * 64,
        "response_id": "chatcmpl-123",
        "finish": "stop",
        "input_tokens": 4000,
        "output_tokens": 900,
        "tool_version": "0.2.340",
    }
    assert validate(document, "review", path).ok

    for extra in ({"api_key": "x"}, {"authorization": "Bearer x"}, {"prompt": "the text"}):
        refused = {**document, "provenance": {**document["provenance"], **extra}}
        assert not validate(refused, "review", path).ok, extra
    assert not validate({**document, "reader": ""}, "review", path).ok
    assert not validate(
        {**document, "provenance": {"provider": "openai"}}, "review", path
    ).ok, "a provenance that cannot trace the reading is not one"


def test_a_panel_may_name_the_readers_of_a_remit(project: Path) -> None:
    from manuscript_guard.contracts._schema import read_structured, validate

    path = project / PANEL_2
    document = read_structured(path)
    document["reviewers"][0]["readers"] = [MODEL_A, MODEL_B]
    assert validate(document, "panel", path).ok
    for bad in ([], [MODEL_A, MODEL_A], [""], MODEL_A):
        document["reviewers"][0]["readers"] = bad
        assert not validate(document, "panel", path).ok, bad


# ---------------------------------------------------------------- found by the review of #128


@pytest.mark.parametrize(
    "name, content",
    [
        # `manuscript-guard review --files > ...` in Windows PowerShell 5 writes UTF-16.
        ("biostatistician.files.yaml", b"\xff\xfe" + "file_sha256:\n".encode("utf-16-le")),
        # A note saved in the Windows code page.
        (
            "biostatistician.notes.yaml",
            "note: relu apr\N{LATIN SMALL LETTER E WITH GRAVE}s la r"
            "\N{LATIN SMALL LETTER E WITH ACUTE}vision\n".encode("cp1252"),
        ),
        ("biostatistician.draft.yaml", b"summary: Fixed: not YAML\n"),
        ("biostatistician.date.yaml", b"seen_on: 2026-09-31\n"),
    ],
    ids=["utf-16", "cp1252", "not YAML", "an impossible date"],
)
def test_a_note_beside_a_record_that_cannot_be_read_does_not_take_the_gate_down(
    project: Path, name: str, content: bytes, capsys
) -> None:
    """`main` never opened these files. Opened and unreadable, they raised: `check` reported
    gate-errored and failed at every stage, and `manuscript-guard review` ended in a
    traceback."""
    from manuscript_guard.cli import main

    (project / "review" / "round-1" / name).write_bytes(content)
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)
    unnamed = [f for f in report.findings if f.code == "reading-unnamed"]
    assert len(unnamed) == 1 and name in unnamed[0].message
    assert main(["check", str(project)]) == 0, capsys.readouterr().out[-800:]
    assert main(["review", str(project), "--submission"]) == 0


def test_a_folder_named_like_a_reading_is_nothing_to_the_gate(project: Path) -> None:
    (project / "review" / "round-1" / "biostatistician.attachments.yaml").mkdir()
    report = report_for(project, submission=True)
    assert report.ok and not report.findings, report.render(project)


def test_a_plain_record_that_names_a_reader_is_held_to_its_place(project: Path) -> None:
    """A plain record may say who made it, and then answers for that reader. It must be this
    reviewer's and this round's: another remit's reading copied to the plain name satisfied
    the panel's named reader, with none of the checks a named file gets."""
    expect_readers(project, 2, "desk-editor", MODEL_A)
    expect_readers(project, 2, "clinical-reader", MODEL_A)
    theirs = add_reading(project, "clinical-reader", MODEL_A)
    assert "reading-missing" in failures(report_for(project, submission=True))

    shutil.copy(theirs, project / DESK)
    report = report_for(project, submission=True)
    misfiled = [f for f in report.failures if f.code == "reading-misfiled"]
    assert len(misfiled) == 1 and "clinical-reader" in misfiled[0].message
    assert "reading-missing" in failures(report)
    assert report.counts["review_rounds_complete"] == 1


def test_an_earlier_rounds_reading_under_the_plain_name_answers_for_nobody(project: Path) -> None:
    edit_yaml(
        project_panel(project, 2),
        lambda d: d["reviewers"].append(
            {"id": "biostatistician", "remit": "the estimator", "readers": [MODEL_A]}
        ),
    )
    earlier = add_reading(project, "biostatistician", MODEL_A, number=1)
    shutil.copy(earlier, project / "review" / "round-2" / "biostatistician.yaml")
    report = report_for(project, submission=True)
    assert "reading-misfiled" in failures(report)
    assert "reading-missing" in failures(report)


def test_a_plain_record_with_a_reader_in_its_own_place_still_counts(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", MODEL_A)
    edit_yaml(project / DESK, lambda d: d.update(reader=MODEL_A))
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)


def test_a_reading_that_cannot_be_parsed_is_refused_and_says_so(project: Path) -> None:
    """It names its reader on a line of its own, so it is a reading and not a note. What it
    held, unanswered findings included, cannot be read, so the round is not finished."""
    path = add_reading(project, "desk-editor", MODEL_A)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "findings: []", "summary: Fixed: it says reporting now.\nfindings: []"
        ),
        encoding="utf-8",
    )
    report = report_for(project, submission=True)
    unreadable = [f for f in report.failures if f.code == "reading-unreadable"]
    assert len(unreadable) == 1
    assert path.name in unreadable[0].message and "names no reader" not in unreadable[0].message
    assert "reading-unnamed" not in codes(report)
    assert report.counts["review_rounds_complete"] == 1
    assert not report_for(project).ok, "a draft is told too: the findings in it are unread"


def test_an_unreadable_file_under_a_named_readers_name_is_refused_too(project: Path) -> None:
    """Nothing in it says `reader:`, but its name is the name the panel asked for."""
    expect_readers(project, 2, "desk-editor", MODEL_A)
    (project / DESK_A).write_bytes(b"\xff\xfe" + "verdict: pass\n".encode("utf-16-le"))
    report = report_for(project, submission=True)
    assert "reading-unreadable" in failures(report)
    assert "reading-missing" in failures(report)


def test_a_misfiled_reading_leaves_the_round_unfinished_with_no_readers_named(
    project: Path,
) -> None:
    edit_yaml(add_reading(project, "desk-editor", MODEL_A), lambda d: d.update(round=1))
    report = report_for(project, submission=True)
    assert "reading-misfiled" in failures(report)
    assert "review-missing" not in codes(report), "the remit was read, by the plain record"
    assert report.counts["review_rounds_complete"] == 1


def test_a_remit_with_only_a_refused_record_is_not_also_called_missing(project: Path) -> None:
    """One finding for one fault: the file is there, and what is wrong with it is said."""
    (project / DESK).unlink()
    edit_yaml(add_reading(project, "desk-editor", MODEL_A), lambda d: d.update(round=1))
    report = report_for(project, submission=True)
    assert "reading-misfiled" in failures(report)
    assert "review-missing" not in codes(report)


def test_the_files_a_named_reading_lists_count_towards_coverage(project: Path) -> None:
    """Hand records scoped to the paper alone leave the supplement on nobody's list. A named
    reading that lists every file covers it; one that lists none read the whole manuscript."""
    from manuscript_guard.gates.review import file_digests

    digests = file_digests(load_project(project)[0])
    scope_reviews(project, {"main.md": digests["main.md"]})
    assert "review-uncovered" in failures(report_for(project, submission=True))

    first = add_reading(project, "biostatistician", MODEL_A, number=1)
    second = add_reading(project, "desk-editor", MODEL_A)
    report = report_for(project, submission=True)
    assert "review-uncovered" not in codes(report), report.render(project)

    for path in (first, second):
        edit_yaml(path, lambda d: d.pop("file_sha256"))
    assert "review-uncovered" not in codes(report_for(project, submission=True))


def test_a_stale_named_reading_outdates_its_round(project: Path) -> None:
    """Only the model read the new file, so only its reading goes stale when that changes."""
    from manuscript_guard.gates.review import file_digests

    before = file_digests(load_project(project)[0])
    _main, discussion = split_manuscript(project)
    scope_reviews(project, before)
    add_reading(project, "biostatistician", MODEL_A, number=1)
    add_reading(project, "desk-editor", MODEL_A)
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)

    discussion.write_text(discussion.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
    report = report_for(project, submission=True)
    stale = [f for f in report.failures if f.code == "review-stale"]
    assert len(stale) == 2 and all(MODEL_A in f.message for f in stale)
    assert report.counts["review_rounds_complete"] == 0


def test_a_reader_is_the_same_reader_however_the_name_is_punctuated(project: Path) -> None:
    """The file is named by the reader's name with its punctuation folded, so the panel's
    `Dr. Tanaka` and a reading filed as `Dr Tanaka` are one reader. Matched letter for
    letter, the gate asked for a file that existed and `--record` refused to write it."""
    expect_readers(project, 2, "desk-editor", "Dr. Tanaka", "OpenAI/Model-A")
    add_reading(project, "desk-editor", "Dr Tanaka")
    add_reading(project, "desk-editor", MODEL_A)
    report = report_for(project, submission=True)
    assert report.ok, report.render(project)


def test_a_reader_named_in_another_script_can_be_filed_and_found(project: Path) -> None:
    reader = "\N{CJK UNIFIED IDEOGRAPH-7530}\N{CJK UNIFIED IDEOGRAPH-4E2D} Taro"
    expect_readers(project, 2, "desk-editor", reader)
    assert "reading-missing" in failures(report_for(project, submission=True))
    path = add_reading(project, "desk-editor", reader)
    assert path.name == f"desk-editor.{reader[:2]}-taro.yaml"
    assert report_for(project, submission=True).ok


def test_a_reading_whose_reader_has_no_letter_or_digit_is_not_one(project: Path) -> None:
    """`desk-editor..yaml` with `reader: "???"`: a name that makes no file name."""
    document = yaml.safe_load((project / DESK).read_text(encoding="utf-8"))
    document["reader"] = "???"
    path = project / "review" / "round-2" / "desk-editor..yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = report_for(project, submission=True)
    assert "reading-misfiled" in failures(report)
    assert report.counts["review_readings"] == 5


def test_a_panel_that_names_a_reader_with_no_letter_or_digit_says_so(project: Path) -> None:
    expect_readers(project, 2, "desk-editor", "???")
    report = report_for(project, submission=True)
    missing = [f for f in report.failures if f.code == "reading-missing"]
    assert len(missing) == 1 and "letter or a digit" in missing[0].hint


def test_the_status_says_how_many_major_findings_are_open(project: Path, capsys) -> None:
    from manuscript_guard.cli import main

    path = add_reading(project, "desk-editor", MODEL_A, verdict="major-revision")
    edit_yaml(
        path,
        lambda d: d["findings"].extend(
            [
                {"id": "f1", "severity": "major", "finding": "One."},
                {"id": "f2", "severity": "major", "finding": "Two.", "resolution": "Done."},
                {"id": "f3", "severity": "minor", "finding": "Three."},
            ]
        ),
    )
    assert main(["review", str(project)]) == 0
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if MODEL_A in line and "findings" in line)
    assert "3 findings, 2 major (1 open)" in line
    plain = next(line for line in out.splitlines() if line.strip().startswith("biostatistician"))
    assert "1 major (0 open)" in plain


def test_what_a_record_may_keep_is_closed_at_every_level(project: Path) -> None:
    from manuscript_guard.contracts._schema import read_structured, validate

    path = project / DESK
    document = read_structured(path)
    provenance = {
        "provider": "openai",
        "model": "model-a",
        "prompt_sha256": "0" * 64,
        "tool_version": "0.2.420",
    }
    test = {"test": "x", "holds": True, "evidence": "y"}
    assert validate({**document, "provenance": provenance, "rejection_tests": [test]},
                    "review", path).ok
    for key in provenance:
        partial = {k: v for k, v in provenance.items() if k != key}
        assert not validate({**document, "provenance": partial}, "review", path).ok, key
    extra = {**test, "note": "z"}
    assert not validate({**document, "rejection_tests": [extra]}, "review", path).ok
    assert not validate({**document, "rejection_tests": [{"test": "x"}]}, "review", path).ok
