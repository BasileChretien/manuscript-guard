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


#: A modification time for a lock nobody holds any more: the first day of 2000. A fixed
#: moment, so that no test here reads a clock.
LONG_AGO = 946_684_800


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


# ---------------------------------------------------------------- a named reading


def test_a_named_reading_is_a_record_of_its_own(unreviewed: Path) -> None:
    """One remit read twice, by a model and by a person, is two records. The second must not
    need the first to be overwritten, which the command refuses to do."""
    first = write_review(loaded(unreviewed), "statistics", verdict="pass", remit="the analysis")
    second = write_review(
        loaded(unreviewed), "statistics", verdict="major-revision", reading="openai/model-a"
    )
    assert first.path.name == "statistics.yaml"
    assert second.path.name == "statistics.openai-model-a.yaml"

    document = read_structured(second.path)
    assert validate(document, "review", second.path).ok
    assert document["reader"] == "openai/model-a"
    assert document["reviewer"] == "statistics"
    assert document["reviewed_by"] == "openai/model-a"
    assert "reader" not in read_structured(first.path)

    panel = read_structured(second.panel)
    assert panel["reviewers"] == [
        {"id": "statistics", "remit": "the analysis", "readers": ["openai/model-a"]}
    ], "filing a named reading names its reader in the panel, or the gate would not read it"
    assert check_review(loaded(unreviewed), submission=True).counts["review_readings"] == 2


def test_who_did_the_reading_can_still_be_named_apart_from_the_reader(unreviewed: Path) -> None:
    written = write_review(
        loaded(unreviewed),
        "statistics",
        verdict="pass",
        remit="the analysis",
        reading="second opinion",
        reviewed_by="Dr Tanaka",
    )
    document = read_structured(written.path)
    assert written.path.name == "statistics.second-opinion.yaml"
    assert (document["reader"], document["reviewed_by"]) == ("second opinion", "Dr Tanaka")


def test_a_named_reading_is_not_restamped_either(unreviewed: Path) -> None:
    kwargs = {"verdict": "pass", "remit": "the analysis", "reading": "openai/model-a"}
    write_review(loaded(unreviewed), "statistics", **kwargs)
    with pytest.raises(RecordError, match="already exists"):
        write_review(loaded(unreviewed), "statistics", **kwargs)


def test_two_readers_whose_names_make_one_file_name_do_not_overwrite(unreviewed: Path) -> None:
    write_review(
        loaded(unreviewed), "statistics", verdict="pass", remit="x", reading="openai/model.a"
    )
    with pytest.raises(RecordError, match="already exists"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", reading="openai/model-a")


def test_each_reader_filed_is_added_to_the_panel_once(unreviewed: Path) -> None:
    project = loaded(unreviewed)
    write_review(project, "statistics", verdict="pass", remit="x", reading="openai/model-a")
    write_review(project, "statistics", verdict="pass", reading="Dr Tanaka")
    panel = unreviewed / "review" / "panel-1.yaml"
    assert read_structured(panel)["reviewers"][0]["readers"] == ["openai/model-a", "Dr Tanaka"]
    assert validate(read_structured(panel), "panel", panel).ok
    report = check_review(loaded(unreviewed), submission=True)
    assert "reading-unnamed" not in codes(report) and "reading-missing" not in codes(report)


def test_a_reader_the_panel_already_names_is_left_as_the_panel_spells_it(
    unreviewed: Path,
) -> None:
    project = loaded(unreviewed)
    write_review(project, "statistics", verdict="pass", remit="x")
    panel = unreviewed / "review" / "panel-1.yaml"
    document = yaml.safe_load(panel.read_text(encoding="utf-8"))
    document["reviewers"][0]["readers"] = ["Dr. Tanaka"]
    panel.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    write_review(loaded(unreviewed), "statistics", verdict="pass", reading="Dr Tanaka")
    assert read_structured(panel)["reviewers"][0]["readers"] == ["Dr. Tanaka"]
    report = check_review(loaded(unreviewed), submission=True)
    assert "reading-missing" not in codes(report)


@pytest.mark.parametrize("bad", ["///", "  ", "-"])
def test_a_reader_whose_name_leaves_no_file_name_is_refused(unreviewed: Path, bad: str) -> None:
    with pytest.raises(RecordError, match="--reading"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x", reading=bad)


def test_the_command_files_a_named_reading(unreviewed: Path, capsys) -> None:
    from manuscript_guard.cli import main

    argv = ["review", str(unreviewed), "--record", "statistics", "--verdict", "pass"]
    assert main([*argv, "--remit", "the analysis", "--reading", "openai/model-a"]) == 0
    assert "statistics.openai-model-a.yaml" in capsys.readouterr().out
    assert main([*argv, "--reading", "Dr Tanaka"]) == 0
    assert (unreviewed / "review" / "round-1" / "statistics.dr-tanaka.yaml").exists()
    assert main([*argv, "--reading", "Dr Tanaka"]) == 2
    assert "already exists" in capsys.readouterr().err


def test_a_readers_name_is_recorded_without_the_space_around_it(unreviewed: Path) -> None:
    written = write_review(
        loaded(unreviewed), "statistics", verdict="pass", remit="x", reading="  Dr Tanaka \n"
    )
    assert read_structured(written.path)["reader"] == "Dr Tanaka"


def test_a_reading_filed_under_the_panels_spelling_of_the_same_reader_is_the_same_file(
    unreviewed: Path,
) -> None:
    """`Dr. Tanaka` and `Dr Tanaka` are one reader and one file, so the second is a second
    reading by the same reader, refused, and the message says which file holds the first."""
    write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x", reading="Dr Tanaka")
    with pytest.raises(RecordError, match="statistics.dr-tanaka.yaml already exists"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", reading="Dr. Tanaka")


def test_a_readers_name_too_long_for_a_file_name_is_refused_in_words(unreviewed: Path) -> None:
    with pytest.raises(RecordError, match="--reading"):
        write_review(
            loaded(unreviewed), "statistics", verdict="pass", remit="x", reading="x" * 300
        )
    # Counted in bytes, which is what a file system counts: 80 characters of three bytes
    # each made a 257-byte name.
    with pytest.raises(RecordError, match="--reading"):
        write_review(
            loaded(unreviewed),
            "statistics",
            verdict="pass",
            remit="x",
            reading="\N{CJK UNIFIED IDEOGRAPH-7530}" * 80,
        )


@pytest.mark.parametrize(
    "others",
    [[], ["--record-figure", "forest", "--verdict", "pass", "--by", "me"], ["--files"]],
    ids=["alone", "with a figure review", "with --files"],
)
@pytest.mark.parametrize("reader", ["openai/model-a", ""])
def test_naming_a_reader_without_recording_a_review_is_refused(
    unreviewed: Path, capsys, others: list[str], reader: str
) -> None:
    """Ignored in silence, it looked as though a reading had been filed."""
    from manuscript_guard.cli import main

    assert main(["review", str(unreviewed), "--reading", reader, *others]) == 2
    assert "--record" in capsys.readouterr().err
    assert not (unreviewed / "review").exists()


# ---------------------------------------------------------------- several writers at once
#
# Found by the last check of #128. Several models' readings filed by several processes at
# the same moment is what the multi-provider panel is for, and the panel file was read,
# changed and written back with nothing to stop two writers doing it together.


def test_readings_filed_at_the_same_moment_all_reach_the_panel(unreviewed: Path) -> None:
    """Six `review --record --reading` calls started together each wrote its record, and the
    panel ended up listing two, three or five of the six readers. The gate does not read a
    reading the panel does not name."""
    import subprocess
    import sys

    write_review(loaded(unreviewed), "statistics", verdict="pass", remit="the analysis")
    readers = [f"reader-{number}" for number in range(6)]
    started = [
        subprocess.Popen(
            [sys.executable, "-m", "manuscript_guard.cli", "review", str(unreviewed), "--record",
             "statistics", "--reading", reader, "--verdict", "pass"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for reader in readers
    ]
    for process in started:
        out, err = process.communicate(timeout=300)
        assert process.returncode == 0, err.decode(errors="replace")

    panel = read_structured(unreviewed / "review" / "panel-1.yaml")
    assert sorted(panel["reviewers"][0]["readers"]) == readers
    report = check_review(loaded(unreviewed))
    assert "reading-unnamed" not in codes(report)
    assert report.counts["review_readings"] == 7
    assert not list((unreviewed / "review").glob("*.lock")), "no lock is left behind"


def test_a_lock_left_by_a_writer_that_died_is_taken_over(unreviewed: Path) -> None:
    import os

    (unreviewed / "review").mkdir()
    lock = unreviewed / "review" / "panel-1.yaml.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (LONG_AGO, LONG_AGO))
    written = write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x")
    assert written.path.exists() and not lock.exists()


def test_a_panel_another_writer_holds_is_waited_for_and_then_refused_in_words(
    unreviewed: Path, monkeypatch
) -> None:
    from manuscript_guard import record

    (unreviewed / "review").mkdir()
    lock = unreviewed / "review" / "panel-1.yaml.lock"
    lock.write_text("", encoding="utf-8")
    monkeypatch.setattr(record, "LOCK_WAIT_SECONDS", 0.3)
    with pytest.raises(RecordError, match="panel-1.yaml.lock"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x")
    assert lock.exists(), "another writer's lock is not removed"
    assert not (unreviewed / "review" / "round-1").exists()


def test_a_record_that_appears_while_this_one_is_being_written_is_not_replaced(
    unreviewed: Path, monkeypatch
) -> None:
    """Two calls for one reader at once both found no file. The second to write replaced the
    first, which is a record re-stamped."""
    from manuscript_guard import record

    target = unreviewed / "review" / "round-1" / "statistics.yaml"
    ensure = record._ensure_panel

    def and_somebody_files_first(*args, **kwargs):
        panel = ensure(*args, **kwargs)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("filed by somebody else\n", encoding="utf-8")
        return panel

    monkeypatch.setattr(record, "_ensure_panel", and_somebody_files_first)
    with pytest.raises(RecordError, match="already exists"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x")
    assert target.read_text(encoding="utf-8") == "filed by somebody else\n"


def test_a_folder_that_cannot_be_written_is_refused_in_words_and_not_waited_on(
    unreviewed: Path, monkeypatch
) -> None:
    """The lock could not be made, and no lock was there to wait for. The wait had no end
    and no pause: one processor, fully, until the command was killed."""
    from manuscript_guard import record

    tried: list[str] = []

    def refused(path, flags, *more):
        tried.append(str(path))
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(record.os, "open", refused)
    monkeypatch.setattr(record, "LOCK_DENIED_SECONDS", 0.2)
    with pytest.raises(RecordError, match="cannot be written"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x")
    # A pause between tries: a fifth of a second of trying without one was 100,000 tries.
    assert 1 < len(tried) < 200
    assert not (unreviewed / "review" / "round-1").exists()


def test_a_lock_left_behind_that_cannot_be_removed_is_refused_in_words(
    unreviewed: Path, monkeypatch
) -> None:
    import os

    from manuscript_guard import record

    (unreviewed / "review").mkdir()
    lock = unreviewed / "review" / "panel-1.yaml.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (LONG_AGO, LONG_AGO))
    real = Path.unlink

    tried: list[str] = []

    def held(self, *args, **how):
        if self.name.endswith(".lock"):
            tried.append(self.name)
            raise PermissionError(13, "in use", str(self))
        return real(self, *args, **how)

    monkeypatch.setattr(Path, "unlink", held)
    monkeypatch.setattr(record, "LOCK_WAIT_SECONDS", 0.3)
    with pytest.raises(RecordError, match="panel-1.yaml.lock"):
        write_review(loaded(unreviewed), "statistics", verdict="pass", remit="x")
    assert lock.exists()
    # The wait ends when this test says, not at thirty seconds: about seven tries in a
    # third of a second, and six hundred in thirty. Counted, so that no clock is read.
    assert 1 <= len(tried) < 100, len(tried)


def test_a_record_that_is_refused_leaves_no_folder_behind(unreviewed: Path) -> None:
    """The panel's lock is made in `review/`. A reviewer with no remit is refused, and the
    folder made for the lock was left: an empty `review/` where there had been none."""
    with pytest.raises(RecordError, match="--remit"):
        write_review(loaded(unreviewed), "somebody", verdict="pass")
    assert not (unreviewed / "review").exists()


class _TimeThatTells:
    """The `time` module as `record` sees it, telling the test when the lock's loop pauses.
    Everything but `sleep` is the real module's."""

    def __init__(self, real, paused) -> None:
        self._real = real
        self._paused = paused

    def __getattr__(self, name: str):
        return getattr(self._real, name)

    def sleep(self, seconds: float) -> None:
        self._paused.set()
        self._real.sleep(seconds)


def _second_writer_in_the_loop(monkeypatch):
    """An event set when a writer first pauses in the lock's loop. The loop pauses only
    after it has tried for the lock and found it held, and the first writer never pauses,
    so this is the second writer, waiting. With it, no sleep in a test has to guess how
    long the second writer takes to get there."""
    import threading

    from manuscript_guard import record

    paused = threading.Event()
    monkeypatch.setattr(record, "time", _TimeThatTells(record.time, paused))
    return paused


def test_a_writer_that_is_refused_does_not_take_the_folder_from_one_that_waits(
    tmp_path: Path, monkeypatch
) -> None:
    """The holder made `review/` for its lock and was refused inside it. It then removed the
    folder it had made, from under a writer waiting for the same lock, which ended in a
    `FileNotFoundError` traceback. Found by the second review round of the run.

    The waiting loop has since learnt to make a folder that went, so the second writer
    would write either way and could no longer tell this test anything. What is asserted is
    the thing itself: nobody removes the folder."""
    import threading

    from manuscript_guard.record import panel_lock

    in_the_loop = _second_writer_in_the_loop(monkeypatch)
    panel = tmp_path / "review" / "panel-1.yaml"
    waiting: list[str] = []
    removed: list[str] = []
    real_rmdir = Path.rmdir

    def rmdir(self) -> None:
        removed.append(self.name)
        real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", rmdir)

    def second() -> None:
        try:
            with panel_lock(panel):
                panel.write_text("written by the second\n", encoding="utf-8")
            waiting.append("wrote")
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever it was
            waiting.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=second)
    with pytest.raises(RecordError, match="refused"), panel_lock(panel):
        thread.start()
        assert in_the_loop.wait(60), "the second writer never waited for the lock"
        raise RecordError("refused: no remit")
    thread.join(60)
    assert waiting == ["wrote"], waiting
    assert removed == [], "the refused holder took a folder away"


def test_a_folder_removed_while_a_writer_waits_is_made_again(
    tmp_path: Path, monkeypatch
) -> None:
    """The folder goes while a second writer waits for the lock; it makes the folder again
    and writes.

    No timing decides this. The first version slept and then removed the folder with
    `rmtree`, which takes the lock file away before the folder: the waiting writer could
    take the lock, make its file and write in between, and `rmtree` then failed on a folder
    that was no longer empty (seen once in CI on macOS). The lock had done what this test
    is named for; the test's own removal lost the race. Here the folder is taken away in
    one step, by renaming it, only once the second writer has tried for the lock, found it
    held and paused, and the holder lets go only when the second has finished.
    """
    import threading

    from manuscript_guard import record

    in_the_loop = _second_writer_in_the_loop(monkeypatch)
    panel = tmp_path / "review" / "panel-1.yaml"
    waiting: list[str] = []

    def second() -> None:
        try:
            with record.panel_lock(panel):
                panel.write_text("written by the second\n", encoding="utf-8")
            waiting.append("wrote")
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever it was
            waiting.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=second)
    gone = tmp_path / "review-taken-away"
    with record.panel_lock(panel):
        thread.start()
        assert in_the_loop.wait(60), "the second writer never waited for the lock"
        _rename_away(panel.parent, gone)
        thread.join(60)
    assert waiting == ["wrote"], waiting
    assert panel.read_text(encoding="utf-8") == "written by the second\n"
    assert [found.name for found in gone.iterdir()] == ["panel-1.yaml.lock"], (
        "the folder that was taken away held the first writer's lock and nothing else"
    )


def _rename_away(folder: Path, to: Path) -> None:
    """Take a folder away in one step. Windows refuses for the instant another thread has a
    file in it open, so it is asked again; how often decides nothing."""
    import time

    for _ in range(2000):
        try:
            folder.rename(to)
            return
        except PermissionError:
            time.sleep(0.005)
    raise AssertionError(f"{folder.name} could not be renamed away")


def test_six_records_refused_at_the_same_moment_are_each_refused_in_words(
    unreviewed: Path,
) -> None:
    """No remit, on a project with no `review/` yet: each is refused, and none of them makes
    the folder, so none can take it from another."""
    import subprocess
    import sys

    started = [
        subprocess.Popen(
            [sys.executable, "-m", "manuscript_guard.cli", "review", str(unreviewed), "--record",
             "somebody", "--reading", f"reader-{number}", "--verdict", "pass"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for number in range(6)
    ]
    for process in started:
        out, err = process.communicate(timeout=300)
        said = err.decode(errors="replace")
        assert process.returncode == 2, said
        assert "--remit" in said and "Traceback" not in said
    assert not (unreviewed / "review").exists()


def test_a_reviewer_on_the_panel_is_not_refused_while_the_panel_is_being_rewritten(
    unreviewed: Path, monkeypatch
) -> None:
    """A writer that holds the panel empties the file and then fills it. A second writer
    read it in that instant, before asking for the lock, found no reviewers, and refused a
    reading for a reviewer who is on the panel: `'statistics' is not on any panel before
    round 1. Pass --remit`. Six readings filed at once lost one that way, now and then.
    Found by the final check of the run; the panel is read under its lock again."""
    import threading
    import time

    from manuscript_guard import record

    write_review(loaded(unreviewed), "statistics", verdict="pass", remit="the analysis")
    project = loaded(unreviewed)
    panel = unreviewed / "review" / "panel-1.yaml"
    whole = panel.read_bytes()
    said: list[str] = []
    waiting = threading.Event()
    takes: list[int] = []
    real_take = record._take

    def take(lock, panel_file):
        takes.append(1)
        if len(takes) == 2:
            waiting.set()
        return real_take(lock, panel_file)

    monkeypatch.setattr(record, "_take", take)

    def second() -> None:
        try:
            write_review(project, "statistics", verdict="pass", reading="reader-1")
            said.append("filed")
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever it was
            said.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=second)
    with record.panel_lock(panel):
        panel.write_bytes(b"")
        thread.start()
        # Until the second writer is waiting for the lock, or has given up.
        while thread.is_alive() and not waiting.is_set():
            time.sleep(0.01)
        panel.write_bytes(whole)
    thread.join(60)
    assert said == ["filed"], said
    assert read_structured(panel)["reviewers"][0]["readers"] == ["reader-1"]
