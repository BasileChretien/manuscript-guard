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
from word_edits import AUTHOR, decide, retype

# ------------------------------------------------------------------------- the reply


GOOD_REPLY = {
    "verdict": "minor-revision",
    "summary": "Clear.",
    "rejection_tests": [{"test": "a", "holds": False, "evidence": "b"}],
    "findings": [
        {
            "severity": "minor",
            "finding": "Wordy.",
            "edits": [{"old": "asks whether", "new": "asks only whether"}],
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

    with_edits(project, finding("r8-pe-02", ("asks whether", "asks only whether")))
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
    assert any("asks only whether the signal" in t for t in texts)
    comments, _parents = tracked.comments_of(document)
    assert [c.author for c in comments] == ["pharmacoepidemiologist (Claude Code)"]
    assert comments[0].text.startswith("r8-pe-02 (minor): Finding r8-pe-02")
    # The edit puts an "only" in, which `reworded` warns of: the edit is written, and its
    # comment says so after the finding (Basile, 2026-10-20). Here the limit is meant, so
    # the note is one the author can dismiss.
    assert comments[0].text.endswith(
        "Note: This sentence claims less than it did before the edit: 'only' is new."
    ), comments[0].text
    assert tracked.pending(document, {"pharmacoepidemiologist (Claude Code)"}) == 2
    # Never the submission build, and nothing the freshness gate holds to the source.
    assert document.parent.name == "suggestions"
    assert not (project / "build" / "manuscript.docx").exists() or True


@needs_pandoc
def test_more_than_ten_edits_from_one_reading_are_not_all_written(project: Path) -> None:
    from manuscript_guard.suggestions import PER_READING

    findings = [finding(f"r8-pe-{i:02d}", ("asks whether", f"asks ({i}) whether"))
                for i in range(10, 10 + PER_READING + 1)]  # fmt: skip
    with_edits(project, *findings)
    code, said = suggest(project)
    assert code == 0, said
    assert said.count(f"more than {PER_READING} edits") == 1


@needs_pandoc
@pytest.mark.parametrize("unplaced", [10, 9], ids=["ten", "nine"])
def test_the_ten_edits_a_reading_may_have_written_are_counted_though_none_was(
    project: Path, unplaced: int
) -> None:
    """A known gap (DESIGN.md, Known gaps, "What round 1 of #367's review recorded and
    left", "The ten a reading may have written are counted as suggested"): the cap counts
    every edit of a reading, placed or not. Ten whose words are nowhere in the manuscript
    use it up, and the eleventh, which could be written, is dropped for it; after nine, the
    same edit is the tenth and is written."""
    findings = [finding(f"r8-pe-{i:02d}", (f"nowhere word {i}", f"no word {i}"))
                for i in range(10, 10 + unplaced)]  # fmt: skip
    findings.append(finding("r8-pe-30", ("asks whether", "asks only whether")))
    with_edits(project, *findings)
    code, said = suggest(project)
    assert code == 0, said
    assert said.count("its words are not in the manuscript as it stands") == unplaced
    if unplaced == 10:
        assert "r8-pe-30: 'asks whether': its reading suggests more than 10 edits, and only " \
               "the first 10 are written" in said, said  # fmt: skip
        assert "edit(s) written" not in said
        assert not document_of(project).exists()
    else:
        assert "1 edit(s) written" in said and "more than 10 edits" not in said, said
        assert document_of(project).exists()


@needs_pandoc
def test_a_reading_not_sealed_or_altered_since_has_no_edits_written(project: Path) -> None:
    with_edits(project, finding("r8-pe-02", ("asks whether", "asks again whether")), seal=False)
    code, said = suggest(project)
    assert code == 0
    assert "not sealed" in said and "review --seal pharmacoepidemiologist --round 8" in said
    with_edits(project, seal=True)
    document = reading(project)
    document["findings"][-1]["edits"][0]["new"] = "asks once more whether"
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
    assert "This analysis asks only whether the signal" in main
    assert "Reports were included without restriction on age or sex." in main
    record = reading(project)
    found = {f["id"]: f for f in record["findings"]}
    assert "“asks whether” now reads “asks only whether”" in found[
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
@pytest.mark.parametrize("severity", ["minor", "major"])
@pytest.mark.parametrize("first", ["accept", "reject"])
def test_an_accepted_edit_answers_its_finding_beside_a_refused_one(
    project: Path, tmp_path: Path, severity: str, first: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "What round 1 of #367's review recorded and
    left", "An accepted edit answers its finding beside a refused one"): of a finding's two
    edits, one accepted and one refused with no reply, the acceptance is its resolution,
    major or not, and the refusal is named in it. Only a finding whose edits were all
    refused needs a reply: with both refused and none, it stays open."""
    with_edits(project, finding(
        "r8-pe-02", ("asks whether", "asks only whether"),
        ("Reports were included without restriction on age or sex.",
         "Reports of any age or sex were included."), severity=severity,
    ))  # fmt: skip
    code, said = suggest(project)
    assert code == 0 and "2 edit(s) written" in said, said
    returned = decide(document_of(project), tmp_path / "back.docx", {1: first, 2: "reject"})
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    found = {f["id"]: f for f in reading(project)["findings"]}["r8-pe-02"]
    assert "overridden" not in found
    if first == "accept":
        assert found["resolution"] == (
            "Edited in Word as pharmacoepidemiologist (Claude Code) suggested: “asks "
            "whether” now reads “asks only whether”; the edit to “Reports were included "
            "without restriction on age or sex.” was refused."
        )
    else:
        # The other side: every edit refused, and no reply to say why.
        assert "resolution" not in found
        assert "no reply to say why" in said


@needs_pandoc
def test_an_edit_dropped_when_the_document_was_made_goes_unmentioned(
    project: Path, tmp_path: Path
) -> None:
    """A known gap (DESIGN.md, Known gaps, "What round 1 of #367's review recorded and
    left", "An edit dropped when the document was made goes unmentioned"): a finding with
    one edit written and accepted and another dropped is resolved by the first, and its
    resolution does not say the second was never offered. The 2026-11-09 triage planned a
    fix (F15), which will change this test."""
    with_edits(project, finding("r8-pe-02", ("asks whether", "asks only whether"),
                                ("words the manuscript lacks", "other words")))  # fmt: skip
    code, said = suggest(project)
    assert code == 0, said
    assert "1 edit(s) written" in said and "1 edit(s) not written" in said, said
    returned = decide(document_of(project), tmp_path / "back.docx", {1: "accept"})
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    found = {f["id"]: f for f in reading(project)["findings"]}["r8-pe-02"]
    assert found["resolution"] == (
        "Edited in Word as pharmacoepidemiologist (Claude Code) suggested: “asks whether” "
        "now reads “asks only whether”."
    )


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


def _without_the_suggestion(document: Path, number: int) -> None:
    """`document` with suggestion `number` deleted whole, Track Changes off: everything
    from its bookmark's start to the mark of its comment, and the comment."""
    import zipfile
    from xml.etree import ElementTree as ET

    from manuscript_guard.tracked import _namespaces, _serialised

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(document) as archive:
        names = archive.namelist()
        parts = {name: archive.read(name) for name in names}
    root = ET.fromstring(parts["word/document.xml"])
    comments = ET.fromstring(parts["word/comments.xml"])
    for paragraph in root.iter(W + "p"):
        children = list(paragraph)
        at = next((i for i, c in enumerate(children) if c.tag == W + "bookmarkStart"
                   and c.get(W + "name") == f"mg-s-{number}"), None)  # fmt: skip
        if at is None:
            continue
        note = children[at + 1].get(W + "id")
        end = next(i for i, c in enumerate(children) if i > at
                   and c.find(W + "commentReference") is not None)  # fmt: skip
        for child in children[at : end + 1]:
            paragraph.remove(child)
        for comment in list(comments):
            if comment.get(W + "id") == note:
                comments.remove(comment)
        break
    parts["word/document.xml"] = _serialised(root, _namespaces(parts["word/document.xml"]))
    parts["word/comments.xml"] = _serialised(comments, _namespaces(parts["word/comments.xml"]))
    with zipfile.ZipFile(document, "w") as archive:
        for name in names:
            archive.writestr(name, parts[name])


def _comment_retyped(document: Path, author: str) -> None:
    """`document` with the text of `author`'s comment changed by the person deciding."""
    import zipfile
    from xml.etree import ElementTree as ET

    from manuscript_guard.tracked import _namespaces, _serialised

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(document) as archive:
        names = archive.namelist()
        parts = {name: archive.read(name) for name in names}
    comments = ET.fromstring(parts["word/comments.xml"])
    mine = next(c for c in comments.iter(W + "comment") if c.get(W + "author") == author)
    last = [t for t in mine.iter(W + "t") if t.text][-1]
    last.text += " Seen."
    parts["word/comments.xml"] = _serialised(comments, _namespaces(parts["word/comments.xml"]))
    with zipfile.ZipFile(document, "w") as archive:
        for name in names:
            archive.writestr(name, parts[name])


def _without_extended(document: Path) -> None:
    """`document` as an editor that writes no `word/commentsExtended.xml` saves it: the
    reply is a comment of its own over the same words, and nothing says whose reply."""
    import re
    import zipfile

    with zipfile.ZipFile(document) as archive:
        names = [n for n in archive.namelist() if n != "word/commentsExtended.xml"]
        parts = {name: archive.read(name) for name in names}
    types = parts["[Content_Types].xml"].decode("utf-8")
    parts["[Content_Types].xml"] = re.sub(
        r'<Override PartName="/word/commentsExtended\.xml"[^>]*/>', "", types
    ).encode("utf-8")
    rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
    parts["word/_rels/document.xml.rels"] = re.sub(
        r'<Relationship [^>]*Target="commentsExtended\.xml"[^>]*/>', "", rels
    ).encode("utf-8")
    with zipfile.ZipFile(document, "w") as archive:
        for name in names:
            archive.writestr(name, parts[name])


@needs_pandoc
@pytest.mark.parametrize(
    "how", ["as-word-saves-it", "deleted-whole", "deletion-only", "comment-retyped",
            "no-extended-part"],
)  # fmt: skip
def test_what_was_decided_in_word_is_read_from_the_bookmark_and_the_comment(
    project: Path, tmp_path: Path, how: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "What was decided in Word is read from the
    bookmark and the comment"): a suggestion whose words were deleted whole, or whose
    deletion was accepted and insertion rejected, has no bookmark, and its finding is left
    to answer by hand. A refused edit with a reply is answered by the reply only where the
    comment is the one the document wrote and `word/commentsExtended.xml` says the reply is
    to it: a comment whose text was edited, or a document with no such part, leaves the
    finding open. None of these answers it wrongly. The first case is the other side: the
    reply, as Word saves it, overrides the finding."""
    with_edits(project, finding("r8-pe-02", ("asks whether", "asks only whether")))
    code, said = suggest(project)
    assert code == 0 and "1 edit(s) written" in said, said
    reason = "The aim reads as a question already."
    choice = "deletion" if how == "deletion-only" else "reject"
    returned = decide(document_of(project), tmp_path / "back.docx", {1: choice},
                      replies={} if how.startswith("delet") else {1: reason})  # fmt: skip
    if how == "deleted-whole":
        _without_the_suggestion(returned, 1)
    elif how == "comment-retyped":
        _comment_retyped(returned, "pharmacoepidemiologist (Claude Code)")
    elif how == "no-extended-part":
        import zipfile

        _without_extended(returned)
        with zipfile.ZipFile(returned) as archive:
            assert "word/commentsExtended.xml" not in archive.namelist()
            # The reply is still in the document, as a comment of its own.
            assert reason in archive.read("word/comments.xml").decode("utf-8")
    code, said = run("import", str(returned), str(project), "--apply")
    found = {f["id"]: f for f in reading(project)["findings"]}["r8-pe-02"]
    assert "resolution" not in found
    if how == "as-word-saves-it":
        assert code == 0, said
        assert found["overridden"] == reason and found["overridden_by"] == AUTHOR
        return
    assert "overridden" not in found
    if how.startswith("delet"):
        assert "r8-pe-02: gone" in said and "place is gone from the document" in said, said
    else:
        assert code == 0, said
        assert "no reply to say why" in said, said


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
@pytest.mark.parametrize(
    "how, why",
    [
        ("source-changed", "its words are in the paragraph 2 times as the build printed it"),
        ("record-changed", "the words are not known: its finding in the record is not the one "
                           "the document was made from"),
        ("record-gone", "the words are not known: its review record is not there to answer"),
        ("marked-build-unreadable", "its values and citations could not be lined up with "
                                    "the build"),
    ],
)  # fmt: skip
def test_an_accepted_suggestion_that_cannot_be_written_refuses_its_paragraph(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, how: str, why: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A suggested edit is placed only where it can be
    written exactly", "A write that cannot be made refuses the paragraph"): at import, an
    accepted suggestion whose words cannot be written exactly has its whole paragraph
    refused, the author's own edit there with it. A source changed since the document was
    made (imported with `--force`; here the analysis was run again, so that the old words
    now print twice in their paragraph), a record changed or gone since, and a marked build
    `import` could not read each reach it. With none of them, both come back
    (`test_an_accepted_edit_and_the_author_s_own_edit_in_its_paragraph_both_come_back`)."""
    from manuscript_guard import roundtrip
    from manuscript_guard.emit import write_digest
    from manuscript_guard.gates.review import reading_digest

    main = project / "manuscript" / "main.md"
    sentence = "Reports were included without restriction on age or sex."
    edit = (sentence, "Reports of any age or sex were included.")
    if how == "source-changed":
        # The paragraph's own source cannot change, or its identifier no longer names it
        # and it is not compared at all: what changed is what the analysis prints there.
        sentence = "Reports over 11 years were included without restriction on age or sex."
        main.write_text(main.read_text(encoding="utf-8").replace(
            "Reports were included without", "Reports over 11 years were included without"
        ), encoding="utf-8")  # fmt: skip
        edit = ("11 years", "11 full years")
    with_edits(project, finding("r8-pe-02", edit))
    code, said = suggest(project)
    assert code == 0 and "1 edit(s) written" in said, said
    returned = decide(document_of(project), tmp_path / "back.docx", {1: "accept"})
    retype(returned, 1, "We analysed", "We examined")
    force = []
    if how == "source-changed":
        # The analysis run again: the period it prints, "10 years", is now "11 years" too.
        results = project / "results" / "01_disproportionality.json"
        data = json.loads(results.read_text(encoding="utf-8"))
        data["values"]["cohort.n_years"].update(value=11, display="11")
        results.write_text(json.dumps(data, indent=2), encoding="utf-8")
        write_digest(results)
        force = ["--force"]
    elif how == "record-changed":
        document = reading(project)
        document["findings"][-1]["edits"][0]["new"] = "Reports of every age were included."
        document["reading_sha256"] = reading_digest(document)
        (project / READING).write_text(yaml.safe_dump(document, sort_keys=False),
                                       encoding="utf-8")  # fmt: skip
    elif how == "record-gone":
        (project / READING).unlink()
    else:
        reader = roundtrip.read_blocks

        def unreadable(document: Path):
            if document.name == "reference-tokens.docx":
                raise roundtrip.RoundTripError(f"{document.name} is not a readable .docx")
            return reader(document)

        monkeypatch.setattr(roundtrip, "read_blocks", unreadable)
    code, said = run("import", str(returned), str(project), "--apply", *force)
    said += capsys.readouterr().err
    assert code == 1, said
    assert ("it holds a suggestion accepted in Word that cannot be written into the source "
            f"where its words were: {why}.") in said, said  # fmt: skip
    text = " ".join(main.read_text(encoding="utf-8").split())
    assert sentence in text and "We analysed" in text
    assert edit[1] not in text and "We examined" not in text


@needs_pandoc
@pytest.mark.parametrize(
    "choices, holds",
    [({1: "accept", 2: "reject", 3: "accept"}, False),
     ({1: "reject", 2: "accept", 3: "accept"}, True)],
    ids=["first-and-third", "second-and-third"],
)  # fmt: skip
def test_a_mix_of_three_edits_that_was_not_tried_is_written_only_if_it_holds(
    project: Path, tmp_path: Path, choices: dict[int, str], holds: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A suggested edit is placed only where it can be
    written exactly", "Several edits in one paragraph"): three edits in one paragraph are
    tried alone and each with the ones before it written, so the first and third together
    are not tried. Accepted in Word, that mix is written by `import` only if it holds. Here
    it does not: together they make `<alphaword betaword gammaword deltaword>` an HTML tag,
    which the second, between them, keeps from being one. So the paragraph is refused and
    the findings stay open. The second and third, also untried, hold and are written."""
    main = project / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8").replace(
        "the signal extends", "the signal <(alphaword) betaword gammaword, deltaword> extends"
    ), encoding="utf-8")  # fmt: skip
    with_edits(project, finding("r8-pe-02", ("(alphaword)", "alphaword")),
               finding("r8-pe-03", ("betaword", "betaword,")),
               finding("r8-pe-04", ("gammaword, deltaword", "gammaword deltaword")))  # fmt: skip
    code, said = suggest(project)
    assert code == 0 and "3 edit(s) written" in said, said
    returned = decide(document_of(project), tmp_path / "back.docx", choices)
    code, said = run("import", str(returned), str(project), "--apply")
    found = {f["id"]: f for f in reading(project)["findings"]}
    text = main.read_text(encoding="utf-8")
    if holds:
        assert code == 0, said
        assert "the signal <(alphaword) betaword, gammaword deltaword> extends" in text
        assert "now reads" in found["r8-pe-03"]["resolution"]
        assert "now reads" in found["r8-pe-04"]["resolution"]
        return
    assert code == 1, said
    assert "it holds a suggestion accepted in Word that cannot be written into the source " \
           "where its words were: written into the source, it would not read as Word shows " \
           "it." in said, said  # fmt: skip
    assert "the signal <(alphaword) betaword gammaword, deltaword> extends" in text
    assert all("resolution" not in found[f"r8-pe-0{i}"] for i in (2, 3, 4))
    assert all("overridden" not in found[f"r8-pe-0{i}"] for i in (2, 3, 4))


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


# --------------------------------------------------------------- beside and inside markup


@pytest.mark.parametrize(
    "source, printed, old, new, written",
    [
        ("Growth of *E. coli* was slow and the cohort was small.",
         "Growth of E. coli was slow and the cohort was small.", "cohort was small",
         "group was small", "Growth of *E. coli* was slow and the group was small."),
        ("The *cohort was small* overall.", "The cohort was small overall.", "cohort",
         "group", "The *group was small* overall."),
        ("The **cohort was small** overall.", "The cohort was small overall.",
         "was small", "was tiny", "The **cohort was tiny** overall."),
        ("We ran `glm` and the cohort\nwas small.", "We ran glm and the cohort was small.",
         "cohort was", "group was", "We ran `glm` and the group was small."),
        ("See [the protocol](https://example.org/p); the cohort was small.",
         "See the protocol; the cohort was small.", "the cohort", "the  group",
         "See [the protocol](https://example.org/p); the  group was small."),
        ("The cohort was small. <!-- cohort was small? check -->", "The cohort was small.",
         "cohort was small", "group was tiny",
         "The group was tiny. <!-- cohort was small? check -->"),
    ],
    ids=["beside-emphasis", "inside-emphasis", "inside-strong", "beside-code", "beside-link",
         "repeated-in-a-comment"],
)  # fmt: skip
def test_a_suggestion_is_written_where_its_words_are_and_the_markup_stays(
    source: str, printed: str, old: str, new: str, written: str
) -> None:
    """What `import` writes for a suggestion accepted in Word: the new words where the old
    ones were, and nothing else touched. Merged from Word's text, which holds no markup, the
    emphasis, code and link here were flattened, and such an edit was not offered at all.
    Inside emphasis the new words take it, as Word shows them."""
    from manuscript_guard.suggestions import Words, write_in

    result = write_in(source, printed, None, [Words(old, new)])
    assert not isinstance(result, str), result
    assert result.source == written
    assert result.shown == printed.replace(" ".join(old.split()), " ".join(new.split()))
    assert result.tokens is None


def test_a_value_after_the_written_words_is_moved_along_with_them() -> None:
    from manuscript_guard.roundtrip import align
    from manuscript_guard.suggestions import Words, write_in

    source = "The *cohort* was small ({{results.x}}) and the period short ({{results.y}})."
    printed = "The cohort was small (12) and the period short (3.4)."
    tokens = [(22, 24), (48, 51)]
    result = write_in(source, printed, tokens, [Words("was small", "was very small indeed")])
    assert not isinstance(result, str), result
    assert result.source == source.replace("was small", "was very small indeed")
    assert [result.shown[a:b] for a, b in result.tokens] == ["12", "3.4"]
    # Accepted alone it comes back as written; with the author's word in another stretch,
    # that stretch is merged from Word's text and the emphasis beside the edit stays.
    assert align(result.bare, result.shown, result.shown, result.tokens).rebuilt == result.bare
    retyped = result.shown.replace("period short", "period brief")
    merged = align(result.bare, result.shown, retyped, result.tokens).rebuilt
    assert merged == result.source.replace("period short", "period brief")


@pytest.mark.parametrize(
    "source, printed, tokens, edits, why",
    [
        ("The cohort was small.", "The cohort was small.", None,
         [("group was", "x")], "not in the paragraph as it stands"),
        ("The cohort was small and the cohort was old.",
         "The cohort was small and the cohort was old.", None,
         [("cohort was", "group was")], "in the paragraph 2 times"),
        ("We ran `the glm` here.", "We ran the glm here.", None,
         [("the glm", "a model")], "inside code"),
        ("See [the protocol](https://example.org/p) here.", "See the protocol here.", None,
         [("the protocol", "a plan")], "inside a link"),
        ("The cohort was  \nsmall.", "The cohort was small.", None,
         [("was small", "was tiny")], "across a line break"),
        ("The cohort was small.", "The cohort was small.", None,
         [("cohort was", "group was"), ("was small", "is small")], "the same words"),
        ("The cohort was small.", "The cohort was small.", None,
         [("cohort", "group", "0" * 16)], "not the ones the document showed"),
        ("The _cohort_, said one, was small.", "The cohort, said one, was small.", None,
         [(", said", "s said")], "would not read as Word shows it"),
        ("The cohort was small.", "The cohort was small.", None,
         [("cohort was", "cohort of 12 was")], "more than a change of words"),
        ("The cohort ({{results.x}}) was small.", "The cohort (12) was small.", None,
         [("was small", "was tiny")], "could not be lined up"),
        ("The {{method.a}} cohort was small.", "The cohort was small.", None,
         [("was small", "was tiny")], "ends in a way import cannot merge"),
    ],
    ids=["nowhere", "twice", "inside-code", "inside-link", "line-break", "same-words",
         "not-as-shown", "underscore-glued", "a-number", "values-unplaced", "anchor-inside"],
)  # fmt: skip
def test_a_suggestion_that_cannot_be_written_exactly_is_not_written(
    source: str, printed: str, tokens, edits: list, why: str
) -> None:
    """Each way the words could land somewhere other than where Word showed them, or change
    more than words, refuses the write, and `import` then refuses the paragraph: merged
    from Word's text instead, the suggestion's stretch would lose its markup."""
    from manuscript_guard.suggestions import Words, write_in

    result = write_in(source, printed, tokens, [Words(*edit) for edit in edits])
    assert isinstance(result, str) and why in result, result


#: Words in or across each kind of markup the reader cannot see, and why each takes no edit.
ACROSS_MARKUP = {
    "emphasis-edge": ("Pword value", "across markup the build does not print"),
    "code": ("glmword code", "inside code"),
    "link-text": ("linkword text", "inside a link"),
    "span": ("spanword text", "inside a span with attributes"),
    "struck": ("struckword text", "inside struck-through text"),
    "raised": ("raisedword", "inside a superscript"),
    "lowered": ("loweredword", "inside a subscript"),
    "line-break": ("brokenword across", "run across a line break"),
}


@needs_pandoc
def test_words_across_markup_take_no_edit(project: Path) -> None:
    """A known gap (DESIGN.md, Known gaps, "A suggested edit is placed only where it can be
    written exactly", "Words across markup"): words that cross the edge of emphasis, as
    "Pword value" quoting `*Pword* value`, or lie inside code, a link's text, a span,
    struck-through, raised or lowered text, or run across a hard line break, take no edit.
    The other side, words beside all of it in the same paragraph, is written."""
    main = project / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8").replace(
        "This analysis asks whether the signal extends to example-drug specifically.",
        "This analysis asks whether the *Pword* value of `glmword code`, "
        "[linkword text](https://example.org/l), [spanword text]{.x}, ~~struckword text~~, "
        "x^raisedword^ and y~loweredword~ hold for brokenword  \nacross the line.",
    ), encoding="utf-8")  # fmt: skip
    findings = [finding(f"r8-pe-{i:02d}", (old, "other words"))
                for i, (old, _why) in enumerate(ACROSS_MARKUP.values(), start=10)]  # fmt: skip
    findings.append(finding("r8-pe-30", ("asks whether", "asks only whether")))
    with_edits(project, *findings)
    code, said = suggest(project)
    assert code == 0, said
    assert "1 edit(s) written" in said and "r8-pe-30: 'asks whether' -> 'asks only" in said
    assert f"{len(ACROSS_MARKUP)} edit(s) not written" in said, said
    for i, (old, why) in enumerate(ACROSS_MARKUP.values(), start=10):
        line = next(line for line in said.splitlines() if f"r8-pe-{i}: '{old}'" in line)
        assert why in line, line


MARKED_DRUG = {
    "emphasis": "*example-drug*",
    "strong": "**example-drug**",
    "code": "`example-drug`",
    "link": "[example-drug](https://example.org/drug)",
}


@needs_pandoc
@pytest.mark.parametrize("marked", sorted(MARKED_DRUG))
def test_an_accepted_edit_beside_markup_comes_back_with_the_markup(
    project: Path, tmp_path: Path, marked: str
) -> None:
    """The edit is offered beside emphasis, code or a link, and accepted in Word it is
    written into the source where its words were: the markup stays, which a merge from
    Word's text would have flattened."""
    main = project / "manuscript" / "main.md"
    drug = MARKED_DRUG[marked]
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "extends to example-drug specifically", f"extends to {drug} specifically"
        ),
        encoding="utf-8",
    )
    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "accept", 2: "accept", 3: "accept"})
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    text = main.read_text(encoding="utf-8")
    assert f"This analysis asks only whether the signal extends to {drug} in particular." in text
    found = {f["id"]: f for f in reading(project)["findings"]}
    assert "now reads" in found["r8-pe-02"]["resolution"]
    assert "now reads" in found["r8-pe-03"]["resolution"]


@needs_pandoc
def test_an_accepted_edit_inside_emphasis_keeps_it(project: Path, tmp_path: Path) -> None:
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "analysis asks whether the", "analysis *asks whether* the"
        ),
        encoding="utf-8",
    )
    with_edits(project, finding("r8-pe-02", ("asks whether", "asks only whether")))
    code, said = suggest(project)
    assert code == 0 and "1 edit(s) written" in said, said
    returned = decide(document_of(project), tmp_path / "back.docx", {1: "accept"})
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    assert "analysis *asks only whether* the" in main.read_text(encoding="utf-8")


METHODS_EMPHASIS = (
    "a property of the synthetic data rather than a design choice.",
    "a property of the *synthetic* data rather than a design choice.",
)


@needs_pandoc
@pytest.mark.parametrize(
    "retyped",
    [("We analysed", "We examined"), ("de-duplication", "deduplication")],
    ids=["another-stretch", "the-same-stretch"],
)
def test_an_accepted_edit_and_the_author_s_own_edit_in_its_paragraph_both_come_back(
    project: Path, tmp_path: Path, retyped: tuple[str, str]
) -> None:
    """The suggestion is written where its words were, and then the author's own edit in
    the same paragraph is merged as any rewording is, against the source with the
    suggestion in it. Retyped between other values, the stretch with the suggestion and
    its emphasis is kept as written. Retyped in the suggestion's own stretch, only the
    retyped word is written there, and the emphasis beside it stays: it used to be rebuilt
    from Word's text, and the emphasis went."""
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(*METHODS_EMPHASIS), encoding="utf-8"
    )
    with_edits(project, finding("r8-pe-02", ("Reports were included without restriction on "
                                             "age or sex.", "Reports of any age or sex were "
                                             "included.")))  # fmt: skip
    code, said = suggest(project)
    assert code == 0 and "1 edit(s) written" in said, said
    returned = decide(document_of(project), tmp_path / "back.docx", {1: "accept"})
    retype(returned, 1, *retyped)
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    text = " ".join(main.read_text(encoding="utf-8").split())
    assert "Reports of any age or sex were included." in text
    assert retyped[1] in text and retyped[0] not in text
    assert "*synthetic*" in text
    found = {f["id"]: f for f in reading(project)["findings"]}
    assert "now reads" in found["r8-pe-02"]["resolution"]


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
