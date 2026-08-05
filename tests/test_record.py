"""Writing a review record: the gate that blocked submission with no command behind it.

G11 refuses a submission until a panel exists and every reviewer in it has filed a record,
and G10 refuses a build until every figure has been read. Both asked for a SHA-256 the
toolkit computed and never printed. An author who reaches those gates and finds no command
does not hand-write the YAML — they reach for `--skip-checks`, and the gate has then made the
project worse than having no gate.

The other half of this file is about what the command must *not* do: re-stamp a record after
the manuscript has changed. The digest is the only thing separating "somebody read this
version" from "somebody read a version", and one convenient flag would turn the whole review
system into theatre.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.gates import check_figure_reviews, check_review
from manuscript_guard.gates.figures import content_digest
from manuscript_guard.record import RecordError, write_figure_review, write_review


@pytest.fixture
def unreviewed(project: Path) -> Path:
    """The example with its reviews removed: a project at the wall G11 puts up."""
    shutil.rmtree(project / "review")
    (project / "figures" / "forest.review.yaml").unlink()
    return project


def loaded(path: Path):
    return load_project(path)[0]


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


# ---------------------------------------------------------------- the manuscript review


def test_a_recorded_review_satisfies_the_gate_that_asked_for_it(unreviewed: Path) -> None:
    """End to end, because the two halves of this were written from the same schema and
    could agree with each other while disagreeing with the gate."""
    assert "no-review" in codes(check_review(loaded(unreviewed), submission=True))

    write_review(
        loaded(unreviewed),
        "clinical-reader",
        verdict="minor-revision",
        remit="whether a clinician would act on this",
    )

    report = check_review(loaded(unreviewed), submission=True)
    assert "no-review" not in codes(report)
    assert report.counts["review_rounds_complete"] == 1


def test_the_record_matches_its_schema(unreviewed: Path) -> None:
    written = write_review(
        loaded(unreviewed), "desk-editor", verdict="pass", remit="would this pass triage"
    )
    document = read_structured(written.path)
    assert validate(document, "review", written.path).ok
    assert validate(read_structured(written.panel), "panel", written.panel).ok


def test_the_record_carries_the_digest_of_what_was_read(unreviewed: Path) -> None:
    """The part a person cannot get right by hand: a digest of a canonical join of their own
    manuscript, recomputed whenever a word moves."""
    from manuscript_guard.gates.review import file_digests, manuscript_digest

    written = write_review(
        loaded(unreviewed), "reader", verdict="pass", remit="reads the paper as a reader"
    )
    document = read_structured(written.path)
    assert document["manuscript_sha256"] == manuscript_digest(loaded(unreviewed))
    assert document["file_sha256"] == file_digests(loaded(unreviewed))
    assert "supplementary/S1_code_lists.md" in document["file_sha256"], "the supplement too"


def test_recording_twice_is_refused_rather_than_restamped(unreviewed: Path) -> None:
    """The one convenience this must never offer.

    Re-stamping a record after the manuscript moved makes the review system theatre: the
    digest is the whole difference between "somebody read this version" and "somebody read a
    version". A second reading is a second round, which is a decision for a person.
    """
    write_review(loaded(unreviewed), "reader", verdict="pass", remit="reads it")

    main = unreviewed / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8") + "\n\nA new paragraph.\n", encoding="utf-8")

    with pytest.raises(RecordError, match="already exists"):
        write_review(loaded(unreviewed), "reader", verdict="pass", remit="reads it")

    # And the record still describes the version it actually described.
    assert "review-stale" in codes(check_review(loaded(unreviewed)))


def test_a_second_round_records_the_new_reading(unreviewed: Path) -> None:
    """Which is the supported way through the case above."""
    write_review(loaded(unreviewed), "reader", verdict="major-revision", remit="reads it")
    main = unreviewed / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8") + "\n\nA revision.\n", encoding="utf-8")

    second = write_review(
        loaded(unreviewed), "reader", verdict="pass", round_number=2, remit="reads it again"
    )
    assert second.path.parent.name == "round-2"
    assert read_structured(second.path)["manuscript_sha256"] != (
        read_structured(unreviewed / "review" / "round-1" / "reader.yaml")["manuscript_sha256"]
    )


# ---------------------------------------------------------------- the panel


def test_a_new_reviewer_must_say_what_they_are_responsible_for(unreviewed: Path) -> None:
    """Two reviewers with the same remit are one reviewer, and the panel file exists to make
    somebody answer that. A record filed by a reviewer nobody appointed is a note."""
    with pytest.raises(RecordError, match="--remit"):
        write_review(loaded(unreviewed), "reader", verdict="pass")


def test_a_second_reviewer_joins_the_panel_rather_than_replacing_it(unreviewed: Path) -> None:
    write_review(loaded(unreviewed), "first-reader", verdict="pass", remit="the clinical read")
    write_review(loaded(unreviewed), "second-reader", verdict="pass", remit="the statistics")

    panel = read_structured(unreviewed / "review" / "panel-1.yaml")
    assert [entry["id"] for entry in panel["reviewers"]] == ["first-reader", "second-reader"]
    assert panel["reviewers"][0]["remit"] == "the clinical read"


def test_a_reviewer_keeps_their_remit_into_the_next_round(unreviewed: Path) -> None:
    """"Same reviewer, next round" is what a revision produces. Asking for the remit again
    every time is friction that teaches people to type anything into the field."""
    write_review(loaded(unreviewed), "reader", verdict="major-revision", remit="reads it")
    written = write_review(loaded(unreviewed), "reader", verdict="pass", round_number=2)
    assert written.path.exists()
    panel = read_structured(unreviewed / "review" / "panel-2.yaml")
    assert panel["reviewers"] == [{"id": "reader", "remit": "reads it"}]


def test_a_figure_review_records_who_looked(unreviewed: Path) -> None:
    """A manuscript review falls back to the reviewer's panel id; a figure review has no id
    to fall back to, and who looked is the whole content of the record."""
    with pytest.raises(RecordError, match="--by is required"):
        write_figure_review(loaded(unreviewed), "forest", verdict="pass")


@pytest.mark.parametrize("bad", ["Reader", "a reader", "1reader", "reader/../x"])
def test_a_reviewer_id_that_would_not_name_a_file_is_refused(unreviewed: Path, bad: str) -> None:
    with pytest.raises(RecordError, match="lowercase"):
        write_review(loaded(unreviewed), bad, verdict="pass", remit="x")


def test_an_unknown_verdict_is_refused(unreviewed: Path) -> None:
    with pytest.raises(RecordError, match="verdict must be"):
        write_review(loaded(unreviewed), "reader", verdict="looks-fine", remit="x")


# ---------------------------------------------------------------- the figure review


def test_a_figure_record_carries_the_digest_the_gate_recomputes(unreviewed: Path) -> None:
    """`content_sha256` is a digest of the figure's content rather than of the file, so an
    author could not obtain it at all: the gate blocked the build asking for a number the
    toolkit computed and never printed."""
    written = write_figure_review(loaded(unreviewed), "forest", verdict="pass", reviewed_by="me")
    document = read_structured(written.path)
    assert validate(document, "figure_review", written.path).ok
    assert document["content_sha256"] == content_digest(unreviewed / "figures" / "forest.svg")
    assert "figure-review-stale" not in codes(
        check_figure_reviews(loaded(unreviewed), content_digest)
    )


def test_the_figure_record_starts_as_a_to_do_list(unreviewed: Path) -> None:
    """Written with every check passed, the command would be doing the review. Written with
    none, the file fails its schema and reads as a bug rather than as work outstanding."""
    from manuscript_guard.gates.figure_review import REQUIRED_CHECKS

    written = write_figure_review(loaded(unreviewed), "forest", verdict="pass", reviewed_by="me")
    checks = read_structured(written.path)["checks"]
    assert [c["id"] for c in checks] == list(REQUIRED_CHECKS)
    assert not any(c["ok"] for c in checks)

    report = check_figure_reviews(loaded(unreviewed), content_digest)
    assert "figure-review-incomplete" not in codes(report), "the checks are all present"
    assert "figure-check-failed" in codes(report) or any(
        "did not pass" in (f.message or "") for f in report.findings
    ), "and every one of them is still outstanding"


def test_a_figure_review_lands_where_the_gate_looks_for_it(unreviewed: Path) -> None:
    """Named for the PNG, recorded against the SVG: the gate reads one file per figure, and a
    review filed against the other one is a review it cannot find."""
    written = write_figure_review(
        loaded(unreviewed), "forest.png", verdict="pass", reviewed_by="me"
    )
    assert written.path.name == "forest.review.yaml"
    report = check_figure_reviews(loaded(unreviewed), content_digest)
    assert "figure-unreviewed" not in codes(report)


def test_a_figure_that_does_not_exist_says_which_ones_do(unreviewed: Path) -> None:
    with pytest.raises(RecordError, match="forest"):
        write_figure_review(loaded(unreviewed), "funnel", verdict="pass", reviewed_by="me")


def test_an_existing_figure_review_is_not_overwritten(unreviewed: Path) -> None:
    write_figure_review(loaded(unreviewed), "forest", verdict="pass", reviewed_by="me")
    with pytest.raises(RecordError, match="already exists"):
        write_figure_review(loaded(unreviewed), "forest", verdict="concerns", reviewed_by="me")


# ---------------------------------------------------------------- through the CLI


def test_the_command_requires_a_verdict(unreviewed: Path, capsys) -> None:
    """Written after the reading. A record with a placeholder verdict is a claim that
    somebody looked."""
    from manuscript_guard.cli import main

    assert main(["review", str(unreviewed), "--record", "reader", "--remit", "x"]) == 2
    assert "--verdict is required" in capsys.readouterr().err


def test_the_command_writes_both_files_and_says_where(unreviewed: Path, capsys) -> None:
    from manuscript_guard.cli import main

    code = main(
        [
            "review",
            str(unreviewed),
            "--record",
            "reader",
            "--remit",
            "reads the paper",
            "--verdict",
            "pass",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "panel-1.yaml" in out and "reader.yaml" in out
    assert yaml.safe_load((unreviewed / "review" / "round-1" / "reader.yaml").read_text("utf-8"))


def test_a_refusal_exits_two_rather_than_raising(unreviewed: Path, capsys) -> None:
    from manuscript_guard.cli import main

    argv = ["review", str(unreviewed), "--record", "reader", "--verdict", "pass"]
    assert main(argv) == 2
    assert "--remit" in capsys.readouterr().err
