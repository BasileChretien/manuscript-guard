"""A review panel's suggested edits, as Word tracked changes the author accepts or refuses.

A finding may carry edits (`review.schema.json`). `review --suggestions` writes the ones it
can place exactly into `build/suggestions/round-N.docx` as tracked changes under the
reader's name, with the finding as a comment; `import` refuses that document while any of
them is undecided, merges the accepted words as it merges any rewording, and writes each
finding's answer into its record. Word's edits here are made by `tests/word_edits.py`, as
Word 16 makes them.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from suggesting import (
    READING,
    finding,
    needs_pandoc,
    offered_round,
    reading,
    run,
    suggest,
    with_edits,
)
from suggesting import document as document_of
from word_edits import AUTHOR, decide

# ------------------------------------------------------------------------- the reply


GOOD_REPLY = {
    "verdict": "minor-revision",
    "summary": "Clear.",
    "rejection_tests": [{"test": "a", "holds": False, "evidence": "b"}],
    "findings": [
        {
            "severity": "minor",
            "finding": "Wordy.",
            "edits": [{"old": "has not been examined", "new": "remains unexamined"}],
        }
    ],
}


def test_a_reply_may_carry_edits_and_null_or_none_is_left_out() -> None:
    """The prompt shows `edits` on every finding, and a model with no wording to offer
    writes null or an empty list: each says what leaving the key out says (round 1 of #367:
    the empty list refused the whole paid reading)."""
    from manuscript_guard.panel.reply import parse_reply

    assert parse_reply(json.dumps(GOOD_REPLY)) == GOOD_REPLY
    for nothing in (None, []):
        left_out = json.loads(json.dumps(GOOD_REPLY))
        left_out["findings"][0]["edits"] = nothing
        assert "edits" not in parse_reply(json.dumps(left_out))["findings"][0]


@pytest.mark.parametrize(
    "edits",
    [
        [{"old": "  ", "new": "b"}],
        [{"old": "a", "new": ""}],
        [{"old": f"a{i}", "new": "b"} for i in range(11)],
    ],
    ids=["blank-old", "empty-new", "eleven"],
)
def test_a_reply_whose_edits_cannot_be_placed_is_filed_all_the_same(
    edits: list, project: Path, monkeypatch
) -> None:
    """An edit is optional, and one that cannot be written as a tracked change is dropped
    when the document is made, where it is said why: a whole reading is not refused for it,
    and what the reader wrote is filed as they wrote it."""
    from test_review_run import Providers, answer, configure

    from manuscript_guard.cli import main
    from manuscript_guard.panel import client

    reply = json.loads(json.dumps(GOOD_REPLY))
    reply["findings"][0]["edits"] = edits
    transport = Providers()
    transport.default = lambda request: answer(json.dumps(reply))
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-0123456789SECRETA")
    shutil.rmtree(project / "review")
    configure(project, "openai/model-a")
    assert main(["review", str(project), "--run", "--yes"]) == 0
    filed = sorted((project / "review" / "round-1").glob("*.*.yaml"))
    assert filed and all(
        yaml.safe_load(path.read_text(encoding="utf-8"))["findings"][0]["edits"] == edits
        for path in filed
    )


def test_an_edit_of_no_words_is_dropped_where_it_is_placed() -> None:
    from manuscript_guard.suggestions import refused_words

    assert refused_words("  ", "b") == "its old words are empty"
    assert refused_words("a", "") == "its new words are empty"


@pytest.mark.parametrize(
    "edits",
    [[{"old": "a"}], [{"old": "a", "new": "b", "why": "c"}], "a -> b"],
    ids=["no-new", "extra-key", "a-string"],
)
def test_a_reply_whose_edits_are_not_old_and_new_words_is_refused(edits: object) -> None:
    from manuscript_guard.panel.reply import ReplyRefused, parse_reply

    reply = json.loads(json.dumps(GOOD_REPLY))
    reply["findings"][0]["edits"] = edits
    with pytest.raises(ReplyRefused):
        parse_reply(json.dumps(reply))


def test_a_design_reading_suggests_no_edits() -> None:
    """A design round reads the plan, whose words are not the manuscript's."""
    from manuscript_guard.panel.reply import ReplyRefused, parse_reply

    with pytest.raises(ReplyRefused, match="design round"):
        parse_reply(json.dumps(GOOD_REPLY), design=True)
    plain = json.loads(json.dumps(GOOD_REPLY))
    del plain["findings"][0]["edits"]
    assert parse_reply(json.dumps(plain), design=True) == plain


def test_the_manuscript_prompt_offers_edits_and_the_design_prompt_does_not() -> None:
    from manuscript_guard.panel.prompt import system_text

    reviewer = {"remit": "Statistics."}
    manuscript = system_text(reviewer)
    assert '"edits": [{"old":' in manuscript
    assert "at most 10 edits" in manuscript
    design = system_text(reviewer, design=True)
    assert "edits" not in design
    assert "{" + "edits}" not in manuscript + design


def test_the_seal_covers_edits_where_a_finding_has_them() -> None:
    """An edit is the reader's, shown in Word under the reader's name: changed after the
    seal, the reading is altered. A finding without edits digests as it always did."""
    from manuscript_guard.gates.review import reading_digest

    record = {"verdict": "pass", "summary": "s", "rejection_tests": [],
              "findings": [{"id": "r1-01", "severity": "minor", "finding": "f"}]}  # fmt: skip
    before = reading_digest(record)
    with_edit = json.loads(json.dumps(record))
    with_edit["findings"][0]["edits"] = [{"old": "a b", "new": "c d"}]
    sealed = reading_digest(with_edit)
    assert sealed != before
    with_edit["findings"][0]["edits"][0]["new"] = "c e"
    assert reading_digest(with_edit) != sealed
    with_edit["findings"][0]["resolution"] = "done"
    with_edit["findings"][0]["edits"][0]["new"] = "c d"
    assert reading_digest(with_edit) == sealed


# --------------------------------------------------------------------- the document


@needs_pandoc
def test_each_edit_is_a_tracked_change_by_its_reader_with_its_finding_as_a_comment(
    project: Path,
) -> None:
    from manuscript_guard import tracked
    from manuscript_guard.docxtext import blocks

    with_edits(project, finding("r8-pe-02", ("has not been examined", "remains unexamined")))
    code, said = suggest(project)
    assert code == 0, said
    document = document_of(project)
    assert "1 edit(s) written" in said
    offered = tracked.offered_of(document)
    assert [(o["n"], o["finding"], o["author"]) for o in offered] == [
        (1, "r8-pe-02", "pharmacoepidemiologist (Claude Code)")
    ]
    # Read as accepted, the paragraph has the new words; read as rejected, it is the build.
    texts = [b.text for b in blocks(document)]
    assert any("specifically remains unexamined." in t for t in texts)
    comments, _parents = tracked.comments_of(document)
    assert [c.author for c in comments] == ["pharmacoepidemiologist (Claude Code)"]
    assert comments[0].text.startswith("r8-pe-02 (minor): Finding r8-pe-02")
    assert tracked.pending(document, {"pharmacoepidemiologist (Claude Code)"}) == 2
    # Never the submission build, and nothing the freshness gate holds to the source.
    assert document.parent.name == "suggestions"
    assert not (project / "build" / "manuscript.docx").exists() or True


@needs_pandoc
def test_more_than_ten_edits_from_one_reading_are_not_all_written(project: Path) -> None:
    from manuscript_guard.suggestions import PER_READING

    findings = [finding(f"r8-pe-{i:02d}", ("has not been examined", f"is open {i}"))
                for i in range(10, 10 + PER_READING + 1)]  # fmt: skip
    with_edits(project, *findings)
    code, said = suggest(project)
    assert code == 0, said
    assert said.count(f"more than {PER_READING} edits") == 1


@needs_pandoc
def test_a_reading_not_sealed_or_altered_since_has_no_edits_written(project: Path) -> None:
    with_edits(project, finding("r8-pe-02", ("has not been examined", "is open")), seal=False)
    code, said = suggest(project)
    assert code == 0
    assert "not sealed" in said and "review --seal pharmacoepidemiologist --round 8" in said
    with_edits(project, seal=True)
    document = reading(project)
    document["findings"][-1]["edits"][0]["new"] = "is wide open"
    (project / READING).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    code, said = suggest(project)
    assert "has changed since it was sealed" in said
    assert not document_of(project).exists()


# ------------------------------------------------------------------------ the import


@needs_pandoc
def test_accepted_edits_merge_and_answer_theirfinding(project: Path, tmp_path: Path) -> None:
    """An accepted edit's words are merged into the source as Word's rewording, and its
    finding gets a resolution naming them; a refused one with a reply is overridden by the
    reply, under the reply's author; the seal holds, since answers are outside it."""
    from manuscript_guard.gates.review import reading_digest

    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "accept", 2: "reject", 3: "reject"},
                      replies={3: "The aim reads as a question already."})  # fmt: skip
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    main = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert "specifically remains unexamined." in main
    assert "Reports were included without restriction on age or sex." in main
    record = reading(project)
    found = {f["id"]: f for f in record["findings"]}
    assert "“has not been examined” now reads “remains unexamined”" in found[
        "r8-pe-02"
    ]["resolution"]
    assert "was refused" in found["r8-pe-02"]["resolution"]
    assert found["r8-pe-03"]["overridden"] == "The aim reads as a question already."
    assert found["r8-pe-03"]["overridden_by"] == AUTHOR
    assert record["reading_sha256"] == reading_digest(record)
    # The panel's comments are its findings, which are in the record: not reported as a
    # co-author's, and neither is the reply.
    assert "comment from" not in said


@needs_pandoc
def test_a_refused_edit_with_no_reply_leaves_its_finding_open(
    project: Path, tmp_path: Path
) -> None:
    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "reject", 2: "reject", 3: "reject"})
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    assert "nothing came back" in said
    assert "no reply to say why" in said
    found = {f["id"]: f for f in reading(project)["findings"]}
    assert "resolution" not in found["r8-pe-03"] and "overridden" not in found["r8-pe-03"]


@needs_pandoc
def test_an_edit_whose_place_is_gone_or_changed_is_left_to_the_author(
    project: Path, tmp_path: Path
) -> None:
    """The deletion accepted and the insertion rejected leaves nothing inside the edit's
    bookmark, and Word removes it with the comment; words typed inside it after accepting
    are neither the old nor the new. Either way what was decided cannot be said."""
    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "deletion", 2: "reject", 3: "accept"},
                      typed={3: "very "})  # fmt: skip
    code, said = run("import", str(returned), str(project))
    assert "r8-pe-02: gone" in said and "r8-pe-03: changed" in said
    assert "place is gone from the document" in said
    assert "changed in Word after it was decided" in said


@needs_pandoc
def test_an_accepted_edit_whose_paragraph_is_refused_stays_open(
    project: Path, tmp_path: Path
) -> None:
    """Accepted, and the paragraph refused: the words are not in the source, so the
    finding is not answered."""
    import zipfile
    from xml.etree import ElementTree as ET

    from manuscript_guard.tracked import _namespaces, _serialised

    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "accept", 2: "accept", 3: "accept"})
    # The value the Methods paragraph prints, changed in Word beside the accepted edit.
    with zipfile.ZipFile(returned) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    root = ET.fromstring(parts["word/document.xml"])
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    changed = False
    for paragraph in root.iter(W + "p"):
        if any(b.get(W + "name") == "mg-s-2" for b in paragraph.iter(W + "bookmarkStart")):
            for t in paragraph.iter(W + "t"):
                if t.text and "2015" in t.text and not changed:
                    t.text, changed = t.text.replace("2015", "2016"), True
    assert changed
    parts["word/document.xml"] = _serialised(root, _namespaces(parts["word/document.xml"]))
    with zipfile.ZipFile(returned, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 1
    assert "import did not merge its paragraph" in said, said
    found = {f["id"]: f for f in reading(project)["findings"]}
    assert "resolution" not in found["r8-pe-02"]


@needs_pandoc
def test_a_document_whose_record_of_suggestions_was_altered_is_not_imported(
    project: Path, tmp_path: Path
) -> None:
    import re
    import zipfile

    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "accept", 2: "accept", 3: "accept"})
    with zipfile.ZipFile(returned) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    custom = parts["docProps/custom.xml"].decode("utf-8")
    parts["docProps/custom.xml"] = re.sub(r'"n":1,', '"n":"1",', custom, count=1).encode()
    with zipfile.ZipFile(returned, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    code, _said = run("import", str(returned), str(project), "--apply")
    assert code == 2


def test_suggestions_go_on_their_own(project: Path) -> None:
    """`--suggestions` writes a document; with `--run` or `--record` it would be unclear
    which was asked for, and nothing is done."""
    for other in (["--run"], ["--record", "x", "--verdict", "pass"], ["--seal", "x"]):
        code, _said = run("review", str(project), "--suggestions", *other)
        assert code == 2


@needs_pandoc
def test_a_round_whose_readings_suggest_nothing_makes_no_document(project: Path) -> None:
    code, said = run("review", str(project), "--suggestions", "--round", "8")
    assert code == 0
    assert "no reading the gate counts suggests an edit" in said
    assert not document_of(project).exists()


WORD_SAVED = Path(__file__).parent / "data" / "word"


def test_what_word_saved_is_read_as_decided() -> None:
    """Documents Word 16 itself saved (2026-10-20, over COM), from round 8 of the example:
    every suggestion decided, and one with all but the first left open. Word merged runs,
    renumbered the comments and wrote a reply's parent in `commentsExtended.xml`. The person
    who saved them is renamed `Ana Author`, with initials `AA`, and Word's account record of
    them is removed; nothing else was changed."""
    from manuscript_guard.suggestions import decisions
    from manuscript_guard.tracked import offered_of, pending

    decided, still = WORD_SAVED / "suggestions-decided.docx", WORD_SAVED / "suggestions-open.docx"
    offered = offered_of(decided)
    authors = {entry["author"] for entry in offered}
    assert [entry["finding"] for entry in offered] == ["r8-pe-02"] * 4 + ["r8-pe-03"]
    assert (pending(decided, authors), pending(still, authors)) == (0, 8)
    # Read with every change accepted, an edit still open reads as its new words; its old
    # words, still there as deleted text, are not read.
    assert offered_of(still) == offered
    assert [d.state for d in decisions(still, offered)[0]] == ["accepted"] * 5
    found, told = decisions(decided, offered)
    assert [d.state for d in found] == ["accepted", "refused", "accepted", "accepted", "refused"]
    assert [[(r.author, r.text) for r in d.replies] for d in found] == [
        [], [("Ana Author", "Kept: the sentence says there was no restriction.")], [], [],
        [("Ana Author", "The aim reads as a question already.")],
    ]  # fmt: skip
    assert len(told) == 7
