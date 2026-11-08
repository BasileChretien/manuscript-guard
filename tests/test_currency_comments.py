"""Reference currency in Word: each proposal nobody answered as a comment on its citing
sentence (`references --comments`), a reply to it filed by `import`, and the reply read and
assessed (`references --assess`). The gate's failures are in tests/test_corruption.py, and the
anchoring held over generated paragraphs in tests/test_properties.py.

The worked case is `tests/currency_records.py`: the rules propose to replace the citation of
@fictionalClassSignal2019 in the Introduction, and nobody has answered. Word's replies are
written by `tests/word_edits.py`, as Word 16 saves one.
"""

from __future__ import annotations

import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import currency_records as case
import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

AUTHOR = "manuscript-guard (references)"
#: The sentence the case marks, as the build prints it: its values and citations rendered.
PRINTED_START = "In a national cohort, the crude incidence was"


def run(*argv: str) -> tuple[int, str]:
    printed = StringIO()
    with redirect_stdout(printed):
        code = main(list(argv))
    return code, printed.getvalue()


def document_of(project: Path) -> Path:
    return project / "build" / "currency" / "suggestions.docx"


def written(project: Path) -> Path:
    """The worked case, its proposal written as a comment."""
    case.case(project)
    code, said = run("references", str(project), "--comments")
    assert code == 0, said
    assert "c1 @fictionalClassSignal2019" in said and "commented on its sentence" in said, said
    return document_of(project)


def currency_yaml(project: Path) -> dict:
    return yaml.safe_load((project / "literature" / "currency.yaml").read_text("utf-8"))


# --------------------------------------------------------------------------- the comments


@needs_pandoc
def test_a_proposal_is_a_comment_on_its_sentence_and_nothing_else_changes(
    project: Path,
) -> None:
    from manuscript_guard import tracked
    from manuscript_guard.docxtext import blocks, comment_ranges

    document = written(project)
    comments, _parents = tracked.comments_of(document)
    assert [c.author for c in comments] == [AUTHOR]
    text = comments[0].text
    for said in ("Suggestion (c1): replace @fictionalClassSignal2019 in this sentence with "
                 "DOI 10.5555/class.trial.2023.",
                 "The work: Hepatic injury with the drug class: a randomized trial (2023), "
                 "DOI 10.5555/class.trial.2023.",
                 "(K1, K2, K3, D1)", "R1 level: \N{LEFT DOUBLE QUOTATION MARK}This randomized "
                 "trial\N{RIGHT DOUBLE QUOTATION MARK}",
                 "R2 population: \N{LEFT DOUBLE QUOTATION MARK}adults exposed to the drug "
                 "class\N{RIGHT DOUBLE QUOTATION MARK}",
                 "R3 stance: \N{LEFT DOUBLE QUOTATION MARK}The class was associated with "
                 "hepatic injury\N{RIGHT DOUBLE QUOTATION MARK}",
                 "To accept, cite this work (add it in Zotero, then run sync-bib). To refuse, "
                 "reply with your reason."):  # fmt: skip
        assert said in text, (said, text)
    # Nothing of the abstract but the quotes.
    assert "Follow-up ended" not in text
    # Over the sentence as the build printed it: its values and its citations rendered.
    (anchored,) = comment_ranges(document).values()
    assert anchored.startswith(PRINTED_START), anchored
    assert anchored.rstrip().endswith(").") and "[@" not in anchored and "{{" not in anchored
    assert "has been reported for the drug class as a whole" in anchored
    # No tracked change, and the text is the build's.
    assert tracked.pending(document, {AUTHOR}) == 0
    assert tracked.offered_of(document) is None
    (offered,) = tracked.currency_offered_of(document)
    assert set(offered) == {"n", "entry", "decision", "author", "written", "date"}
    assert (offered["entry"], offered["author"]) == ("c1", AUTHOR)
    plain = project / "build" / "plain.docx"
    run("build", str(project), "--offline", "--skip-checks", "--output", str(plain))
    assert [b.text for b in blocks(document)] == [b.text for b in blocks(plain)]


@needs_pandoc
def test_with_no_proposal_waiting_nothing_is_written(project: Path) -> None:
    case.case(project, readings=False)
    code, said = run("references", str(project), "--comments")
    assert code == 0 and "no proposed change waits for an answer" in said, said
    assert not document_of(project).exists()


@needs_pandoc
def test_a_proposal_answered_or_accepted_gets_no_comment(project: Path) -> None:
    from manuscript_guard.currency import command

    case.case(project)
    command.refuse(load_project(project)[0], "c1", "another population", "Ada Example")
    code, said = run("references", str(project), "--comments")
    assert code == 0 and "no proposed change waits for an answer" in said, said


@needs_pandoc
def test_a_sentence_twice_in_its_paragraph_gets_no_comment_and_says_why(project: Path) -> None:
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text("utf-8")
    old = "by the end of its last published review."
    assert old in text
    # The case's sentence written again at the end of its paragraph.
    again = ("a disproportionality signal has been reported for the\ndrug class as a whole "
             "(ROR {{lit.background.class_ror}}) [@fictionalClassSignal2019].")  # fmt: skip
    main_md.write_text(text.replace(old, old + " In a national cohort, the crude incidence "
                                    "was\n{{lit.background.reported_incidence}} per 100 000 "
                                    "person-years\n[@fictionalHepaticCohort2021], and " + again,
                                    1), "utf-8")  # fmt: skip
    case.case(project)
    code, said = run("references", str(project), "--comments")
    assert code == 0, said
    assert "not commented: its sentence is in its paragraph 2 times" in said, said
    assert "no comment could be placed; nothing written" in said
    assert not document_of(project).exists()


@needs_pandoc
def test_an_unplaced_entry_gets_no_comment_and_says_why(project: Path) -> None:
    case.case(project)
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text("utf-8")
    old = text[text.index("In a national cohort"):text.index(" [@fictionalClassSignal2019]")]
    main_md.write_text(text.replace(old, "One study saw something odd", 1), "utf-8")
    code, said = run("references", str(project), "--comments")
    assert code == 0
    assert "not commented: no sentence of the manuscript matches it (unplaced)" in said, said


@needs_pandoc
def test_the_comments_leave_the_normal_build_and_the_suggestions_alone(project: Path) -> None:
    written(project)
    assert not (project / "build" / "suggestions").exists()
    assert sorted(p.name for p in (project / "build" / "currency").iterdir()
                  if p.suffix == ".docx") == ["suggestions.docx"]  # fmt: skip


# ------------------------------------------------------------------------ the import


@needs_pandoc
def test_a_reply_is_filed_as_word_kept_it_once_and_decides_nothing(
    project: Path, tmp_path: Path
) -> None:
    """`import` files the reply under literature/currency/replies/, sealed, and decides
    nothing; the comment and its reply are no co-author's comments, and a co-author's own
    comment elsewhere is filed as before. Imported again, the reply is not filed twice."""
    from word_edits import comment_on, reply_to

    from manuscript_guard.currency import records

    document = written(project)
    before = (project / "literature" / "currency.yaml").read_bytes()
    returned = reply_to(document, tmp_path / "back.docx", AUTHOR, case.REPLY, by="Ada Example")
    returned = comment_on(returned, returned, "asks whether", "Say since when.",
                          by="Blaise Sample")  # fmt: skip
    code, said = run("import", str(returned), str(project))
    assert ("c1: a reply by Ada Example, to be filed as literature/currency/replies/c1.1.yaml; "
            "--apply files it") in said, said  # fmt: skip
    assert not (project / "literature" / "currency" / "replies").exists()
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    assert "filed as literature/currency/replies/c1.1.yaml" in said
    assert f"    > {case.REPLY}" in said
    record = yaml.safe_load((project / "literature" / "currency" / "replies" / "c1.1.yaml")
                            .read_text("utf-8"))  # fmt: skip
    assert (record["entry"], record["number"], record["by"], record["date"], record["text"]) == (
        "c1", 1, "Ada Example", "2026-10-21", case.REPLY)
    assert record["reply_sha256"] == records.sealed_digest(record, "reply_sha256")
    assert (project / "literature" / "currency.yaml").read_bytes() == before
    # The co-author's own comment is filed; the tool's comment and the reply are not.
    filed = "".join(path.read_text("utf-8")
                    for path in (project / "review" / "comments").rglob("*.yaml"))  # fmt: skip
    assert "Say since when." in filed
    assert case.REPLY not in filed and "Suggestion (c1)" not in filed
    code, said = run("import", str(returned), str(project), "--apply")
    assert "the reply by Ada Example is filed already, as c1.1.yaml" in said, said
    assert sorted(p.name for p in (project / "literature" / "currency" / "replies").iterdir()
                  ) == ["c1.1.yaml"]  # fmt: skip


WORD_SAVED = Path(__file__).parent / "data" / "word" / "currency-replied.docx"


def test_what_word_saved_is_read_as_a_reply_to_the_tool_s_comment(project: Path) -> None:
    """A document Word 16 itself saved (2026-11-05, over COM), from the case's copy that
    `references --comments` wrote: opened in compatibility mode, as a pandoc build opens, a
    reply added to the comment with `Replies.Add`, and saved. Word kept the comment's words,
    so its digest, and the document's list of proposals, and wrote the reply's parent in
    `commentsExtended.xml`. The person who saved it is renamed `Ada Example`, with initials
    `AE`, and Word's account record of them is removed; nothing else was changed, but for
    the example's sentence that is no longer a claim of absence, whose words were changed
    in document.xml on 2026-11-08 to match the example (item 4)."""
    from manuscript_guard import tracked
    from manuscript_guard.currency import replies
    from manuscript_guard.filed_comments import threads_of

    (offered,) = tracked.currency_offered_of(WORD_SAVED)
    assert (offered["entry"], offered["author"]) == ("c1", AUTHOR)
    assert tracked.offered_of(WORD_SAVED) is None
    assert tracked.pending(WORD_SAVED, {AUTHOR}) == 0
    found = replies.replies_in(WORD_SAVED, [offered])
    assert [(one.by, one.date, one.text) for one in found] == [
        ("Ada Example", "2026-11-05", case.REPLY)]
    # Neither the comment nor the reply is a co-author's comment.
    assert threads_of(WORD_SAVED, vouched={}, sources={},
                      panel=[{**offered, "comment": offered["written"]}]) == []  # fmt: skip
    # Filed and read, it answers the case's proposal under Ada Example's name.
    case.case(project)
    said = replies.file_replies(load_project(project)[0], WORD_SAVED, found, applying=True)
    assert said == ["c1: a reply by Ada Example, filed as literature/currency/replies/c1.1.yaml"]
    assert assess(project, "refuses")[0] == 0
    assert currency_yaml(project)["entries"][0]["answer"]["by"] == "Ada Example"


@needs_pandoc
def test_a_comment_left_without_a_reply_files_nothing(project: Path, tmp_path: Path) -> None:
    document = written(project)
    returned = tmp_path / "back.docx"
    shutil.copy(document, returned)
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    assert "reference proposals in back.docx: 1, replies: 0" in said
    assert not (project / "literature" / "currency" / "replies").exists()


# ----------------------------------------------------------------------- the assessment


def assess(project: Path, says: str, quote: str = case.REFUSING, reader: str = "Claude",
           number: int = 1) -> tuple[int, str]:  # fmt: skip
    return run("references", str(project), "--assess", "c1", "--reply", str(number),
               "--says", says, "--quote", quote, "--as", reader)


def listed(project: Path) -> str:
    code, said = run("references", str(project))
    assert code == 0, said
    return said


def test_a_reply_that_refuses_from_an_author_is_the_entry_s_answer(project: Path) -> None:
    from manuscript_guard.gates.currency import check_currency

    case.case(project)
    case.replied(project)
    code, said = assess(project, "refuses")
    assert code == 0, said
    assert "refused by Ada Example, by reply 1" in said
    answer = currency_yaml(project)["entries"][0]["answer"]
    assert answer == {"status": "refused", "by": "Ada Example", "why": case.REFUSING,
                      "answered_on": "2026-11-06", "reply": 1, "assessed_by": "Claude"}
    found = check_currency(load_project(project)[0], "submission").findings
    assert [f.code for f in found] == []
    shown = listed(project)
    assert "refused by Ada Example" in shown
    assert ("reply 1 by Ada Example (2026-11-06): refuses (Claude): it is the entry's answer"
            in shown), shown  # fmt: skip
    assert (project / "literature" / "currency" / "replies" / "c1.1.Claude.yaml").is_file()


@pytest.mark.parametrize(
    ("by", "said"),
    [("Ana Author", "'Ana Author' is no person of authors.yaml"),
     ("gpt-4o", "'gpt-4o' is a model's name"),
     ("", "Word gives the reply no author's name")],
)  # fmt: skip
def test_a_refusal_by_nobody_authors_yaml_names_writes_nothing(
    project: Path, by: str, said: str, capsys
) -> None:
    case.case(project)
    case.replied(project, by=by)
    before = (project / "literature" / "currency.yaml").read_bytes()
    assert main(["references", str(project), "--assess", "c1", "--reply", "1", "--says",
                 "refuses", "--quote", case.REFUSING, "--as", "Claude"]) == 2
    err = capsys.readouterr().err
    assert said in err and "Nothing is written" in err, err
    assert (project / "literature" / "currency.yaml").read_bytes() == before
    assert [p.name for p in (project / "literature" / "currency" / "replies").iterdir()] == [
        "c1.1.yaml"]
    shown = listed(project)
    assert said in shown and "so a refusal in it cannot answer the proposal" in shown, shown


def test_an_assessment_quotes_the_reply_word_for_word_and_is_written_once(
    project: Path, capsys
) -> None:
    case.case(project)
    case.replied(project)
    assert main(["references", str(project), "--assess", "c1", "--reply", "1", "--says",
                 "refuses", "--quote", "the trial was too small", "--as", "Claude"]) == 2
    assert "the quote is not in reply 1, word for word" in capsys.readouterr().err
    assert main(["references", str(project), "--assess", "c1", "--reply", "2", "--says",
                 "agrees", "--quote", "Kept", "--as", "Claude"]) == 2
    assert "c1 has no reply 2 filed" in capsys.readouterr().err
    assert main(["references", str(project), "--assess", "c1", "--reply", "1",
                 "--says", "agrees", "--as", "Claude"]) == 2
    assert "--assess needs --reply, --says, --quote and --as" in capsys.readouterr().err
    assert assess(project, "other", "Kept")[0] == 0
    assert main(["references", str(project), "--assess", "c1", "--reply", "1", "--says",
                 "refuses", "--quote", case.REFUSING, "--as", "Claude"]) == 2
    assert "Claude assessed reply 1 of c1 already" in capsys.readouterr().err
    assert "answer" not in currency_yaml(project)["entries"][0]


def test_a_reply_that_agrees_answers_nothing_and_is_listed_so(project: Path) -> None:
    case.case(project)
    case.replied(project, text="Agreed, the trial is the better source.")
    code, said = assess(project, "agrees", "Agreed")
    assert code == 0 and "agreed in Word, not yet cited" in said, said
    assert "answer" not in currency_yaml(project)["entries"][0]
    assert "agreed in Word (Claude), not yet cited" in listed(project)
    code, explained = run("references", str(project), "--explain", "c1")
    assert "agreed in Word (Claude), not yet cited" in explained
    assert "      > Agreed, the trial is the better source." in explained


def test_a_reply_that_says_something_else_is_listed_for_the_author(project: Path) -> None:
    case.case(project)
    case.replied(project, text="Ask Blaise.")
    assert assess(project, "other", "Ask Blaise")[0] == 0
    assert ("says something else (Claude): read it with `references --explain c1`"
            in listed(project))  # fmt: skip
    assert "answer" not in currency_yaml(project)["entries"][0]


def test_a_reply_to_a_proposal_that_changed_since_answers_nothing(project: Path) -> None:
    """The proposal the comment showed is not the entry's now: the reply is filed, and no
    assessment can make it the answer."""
    case.case(project)
    case.replied(project)
    path = project / "literature" / "currency.yaml"
    document = yaml.safe_load(path.read_text("utf-8"))
    decision = document["entries"][0]["decision"]
    document["entries"][0]["decision"] = {"action": "add", "candidate": decision["candidate"],
                                          "rules": ["D2"], "by": "Ada Example",
                                          "why": "it disagrees", "decided_on": "2026-11-06"}
    path.write_text(yaml.safe_dump(document, sort_keys=False), "utf-8")
    code, said = assess(project, "refuses")
    assert code == 0, said
    assert "no answer is written: the proposal changed since the document was written" in said
    assert "answer" not in currency_yaml(project)["entries"][0]
    assert "the proposal changed since the document was written" in listed(project)


def test_a_reply_never_changes_an_answer_given_already(project: Path) -> None:
    from manuscript_guard.currency import command

    case.case(project)
    case.replied(project)
    command.refuse(load_project(project)[0], "c1", "another population", "Blaise Sample")
    code, said = assess(project, "refuses")
    assert code == 0
    assert "only they take their answer back" in said, said
    answer = currency_yaml(project)["entries"][0]["answer"]
    assert (answer["by"], answer["why"]) == ("Blaise Sample", "another population")
    assert "reply" not in answer


def test_a_proposal_cited_and_refused_by_a_reply_is_accepted_and_both_are_shown(
    project: Path,
) -> None:
    """Accepted by citation and refused in Word at once: the manuscript wins. The
    assessment writes no answer, and the listing shows the reply beside the acceptance for
    the authors to settle."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project)
    case.replied(project)
    _cite_the_candidate(project)
    code, said = assess(project, "refuses")
    assert code == 0
    assert "no answer is written: the sentence cites the work it proposes" in said, said
    assert "answer" not in currency_yaml(project)["entries"][0]
    shown = listed(project)
    assert "accepted: the sentence cites it" in shown
    assert ("refuses (Claude), and the sentence cites the work: accepted; the authors settle "
            "it") in shown, shown  # fmt: skip
    assert [f.code for f in check_currency(load_project(project)[0], "submission").findings
            ] == []  # fmt: skip


def test_a_proposal_cited_after_a_reply_refused_it_is_accepted_and_both_are_shown(
    project: Path,
) -> None:
    """The other order: the reply's refusal is the entry's answer, and the author cites the
    work afterwards. The manuscript wins all the same (Basile, 2026-11-05): the proposal
    counts as accepted, and the reply is shown beside it for the authors to settle. A
    refusal by `references --refuse` is a person's answer, which a citation does not
    overrule."""
    from manuscript_guard.currency.survey import survey
    from manuscript_guard.gates.currency import check_currency

    case.case(project)
    case.replied(project)
    assert assess(project, "refuses")[0] == 0
    assert currency_yaml(project)["entries"][0]["answer"]["reply"] == 1
    _cite_the_candidate(project)
    assert "c1" in survey(load_project(project)[0])[0].accepted
    shown = listed(project)
    assert "accepted: the sentence cites it" in shown, shown
    assert ("refuses (Claude), and the sentence cites the work: accepted; the authors settle "
            "it") in shown, shown  # fmt: skip
    assert [f.code for f in check_currency(load_project(project)[0], "submission").findings
            ] == []  # fmt: skip


def test_a_person_s_refusal_stands_when_the_work_is_cited_afterwards(project: Path) -> None:
    from manuscript_guard.currency import command
    from manuscript_guard.currency.survey import survey

    case.case(project)
    command.refuse(load_project(project)[0], "c1", "another population", "Blaise Sample")
    _cite_the_candidate(project)
    assert "c1" not in survey(load_project(project)[0])[0].accepted
    assert currency_yaml(project)["entries"][0]["answer"]["by"] == "Blaise Sample"


def _cite_the_candidate(project: Path) -> None:
    bib = project / "literature" / "references.bib"
    with bib.open("a", encoding="utf-8") as entries:
        entries.write("\n@article{classTrial2023,\n  title = {A trial},\n"
                      "  author = {Fictional, Eve},\n  journal = {Imaginary Trials},\n"
                      "  year = {2023},\n  doi = {10.5555/class.trial.2023}\n}\n")
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text("utf-8")
    old = "[@fictionalClassSignal2019]. The"
    assert old in text
    main_md.write_text(text.replace(old, "[@classTrial2023]. The", 1), "utf-8")


# ------------------------------------------------- round 1 of #531: the reply's own words


def _assessments(project: Path) -> list[str]:
    return sorted(p.name for p in (project / "literature" / "currency" / "replies").iterdir()
                  if p.name.count(".") == 3)  # fmt: skip


@pytest.mark.parametrize(
    ("quote", "said"),
    [("...", "no words left out"),
     ("I do ... refuse this", "no words left out"),
     ("I do [\N{HORIZONTAL ELLIPSIS}] refuse this", "no words left out"),
     ("I do not refuse this [sic]", "no [sic]"),
     ("[sic]", "no [sic]"),
     (";", "a letter or digit")],
)  # fmt: skip
def test_a_reply_s_quote_is_its_own_words_whole(
    project: Path, quote: str, said: str, capsys
) -> None:
    """A reply is short and to hand: its quote is its own words, with nothing left out, nothing
    marked [sic] and at least a letter or digit. `I do ... refuse this` would make "I do not
    refuse this" a refusal."""
    case.case(project)
    case.replied(project, text="I do not refuse this; cite it.")
    assert main(["references", str(project), "--assess", "c1", "--reply", "1", "--says",
                 "refuses", "--quote", quote, "--as", "Claude"]) == 2
    err = capsys.readouterr().err
    assert "--quote is the reply's own words, whole" in err and said in err, err
    assert "Traceback" not in err
    assert _assessments(project) == []
    assert "answer" not in currency_yaml(project)["entries"][0]


def test_an_ellipsis_the_replier_typed_cannot_be_quoted_whole(project: Path, capsys) -> None:
    """A limit (DESIGN.md, Known gaps; round 2 of #531): an ellipsis in the reply itself is
    read in the quote as words left out, so the reply is not quoted whole; a part of it
    without the ellipsis is."""
    case.case(project)
    typed = "Kept... the trial enrolled another population"
    case.replied(project, text=f"{typed}, so it does not replace the signal.")
    assert assess(project, "refuses", quote=typed)[0] == 2
    assert "--quote is the reply's own words, whole" in capsys.readouterr().err
    assert assess(project, "refuses", quote=case.REFUSING)[0] == 0


def test_a_reply_with_no_paragraph_id_is_not_read(tmp_path: Path) -> None:
    """A reply is tied to its comment by its paragraphs' `w14:paraId` (`w15:paraIdParent`),
    so one with none is not read, and nothing stands in for the id (round 2 of #531: the
    docs said its `w:id` did). Word gives every comment's paragraph one when it saves."""
    import re
    import zipfile

    from manuscript_guard import tracked
    from manuscript_guard.currency import replies

    (offered,) = tracked.currency_offered_of(WORD_SAVED)
    assert len(replies.replies_in(WORD_SAVED, [offered])) == 1
    stripped = tmp_path / "no-ids.docx"
    with zipfile.ZipFile(WORD_SAVED) as source, zipfile.ZipFile(stripped, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "word/comments.xml":
                text = data.decode("utf-8")
                reply = re.search(r'<w:comment [^>]*w:author="Ada Example".*?</w:comment>',
                                  text, re.DOTALL)  # fmt: skip
                assert reply and "w14:paraId=" in reply.group(0)
                bare = re.sub(r' w14:paraId="[0-9A-F]+"', "", reply.group(0))
                data = text.replace(reply.group(0), bare).encode("utf-8")
            target.writestr(item, data)
    assert replies.replies_in(stripped, [offered]) == []


@needs_pandoc
def test_a_reply_of_several_paragraphs_is_filed_with_its_breaks(
    project: Path, tmp_path: Path
) -> None:
    from word_edits import reply_to

    from manuscript_guard import tracked
    from manuscript_guard.currency import replies

    document = written(project)
    text = "Kept.\nThe trial enrolled another population."
    returned = reply_to(document, tmp_path / "back.docx", AUTHOR, text, by="Ada Example")
    (offered,) = tracked.currency_offered_of(returned)
    assert [one.text for one in replies.replies_in(returned, [offered])] == [text]
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    record = yaml.safe_load((project / "literature" / "currency" / "replies" / "c1.1.yaml")
                            .read_text("utf-8"))  # fmt: skip
    assert record["text"] == text
    code, explained = run("references", str(project), "--explain", "c1")
    assert "      > Kept.\n      > The trial enrolled another population." in explained, explained


@needs_pandoc
def test_two_replies_of_the_same_words_are_two_replies(project: Path, tmp_path: Path) -> None:
    """Two people under one Word name, or one person twice, each `Kept.`: two replies, filed
    as two, and once each however often the document is imported."""
    from word_edits import reply_to

    document = written(project)
    returned = reply_to(document, tmp_path / "back.docx", AUTHOR, "Kept.", by="Ada Example")
    returned = reply_to(returned, returned, AUTHOR, "Kept.", by="Ada Example")
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    folder = project / "literature" / "currency" / "replies"
    assert sorted(p.name for p in folder.iterdir()) == ["c1.1.yaml", "c1.2.yaml"], said
    code, said = run("import", str(returned), str(project), "--apply")
    assert said.count("is filed already") == 2, said
    assert sorted(p.name for p in folder.iterdir()) == ["c1.1.yaml", "c1.2.yaml"]


def test_the_replies_of_an_unplaced_entry_are_listed(project: Path) -> None:
    case.case(project)
    case.replied(project)
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text("utf-8")
    old = text[text.index("In a national cohort"):text.index(" [@fictionalClassSignal2019]")]
    main_md.write_text(text.replace(old, "One study saw something odd", 1), "utf-8")
    shown = listed(project)
    assert "c1  @fictionalClassSignal2019  unplaced" in shown, shown
    assert "    reply 1 by Ada Example (2026-11-06): not assessed" in shown, shown


def test_a_document_the_comments_cannot_be_written_in_is_refused_with_the_reason(
    project: Path, monkeypatch, capsys
) -> None:
    from manuscript_guard.currency import comments
    from manuscript_guard.tracked import TrackedError

    def refused(*_args, **_kwargs):
        raise TrackedError("the copy does not read as the build with every change rejected")

    case.case(project)
    monkeypatch.setattr(comments, "write_comments", refused)
    assert main(["references", str(project), "--comments"]) == 2
    err = capsys.readouterr().err
    assert "the copy does not read as the build" in err and "Traceback" not in err, err


def test_a_reading_that_changes_a_proposal_a_reply_refused_is_refused() -> None:
    """The comment showed the proposal with its rule ids, and the reply refused that one: a
    reading after which the rules give it from other rules would leave the answer refusing a
    proposal nobody was shown, so it is refused, as G7 would fail the answer."""
    from manuscript_guard.currency import command, records, rules

    decision = {"action": "replace", "candidate": "10.5555/x", "rules": ["K1", "D1"],
                "by": "rules", "decided_on": "2026-11-01"}
    raw = {"id": "c1", "citekey": "old2019", "sentence": "It was so.", "decision": decision,
           "answer": {"status": "refused", "by": "Ada Example", "why": "Kept",
                      "answered_on": "2026-11-02", "reply": 1, "assessed_by": "Claude"}}
    entry = records._entry(raw)
    with pytest.raises(command.Refused, match="takes their answer away first"):
        command._check_answered(entry, rules.Decision("replace", "10.5555/x", ("K2", "D1"), ""))
    command._check_answered(entry, rules.Decision("replace", "10.5555/x", ("K1", "D1"), ""))
    # A person's own refusal is of the work, whatever rules gave it.
    by_hand = records._entry({**raw, "answer": {"status": "refused", "by": "Ada Example",
                                                "why": "Kept", "answered_on": "2026-11-02"}})
    command._check_answered(by_hand, rules.Decision("replace", "10.5555/x", ("K2", "D1"), ""))


def test_the_skill_says_to_ask_the_author_before_recording_a_refusal() -> None:
    skills = Path(__file__).parents[1] / "plugin" / "skills" / "word-roundtrip"
    body = (skills / "SKILL.md").read_text("utf-8")
    section = body[body.index("## 7. Replies to reference proposals"):]
    section = section[:section.index("\n## ", 4)]
    assert "ask the author before recording `--says refuses`" in " ".join(section.split())
    page = (skills / "references" / "reference-proposals.md").read_text("utf-8")
    assert "--says refuses --quote" not in page


def test_the_gate_s_codes_for_a_reply_are_documented() -> None:
    from manuscript_guard.gates import currency

    design = (Path(__file__).parents[1] / "DESIGN.md").read_text("utf-8")
    table = design[design.index("| `currency-record-missing`"):]
    table = table[:table.index("\n\n")]
    for code in ("currency-reply-missing", "currency-reply-quote-not-found",
                 "currency-reply-not-a-person"):  # fmt: skip
        assert f"`{code}`" in currency.__doc__, code
        assert f"| `{code}` |" in table, code
    edited = next(line for line in table.splitlines() if "`currency-record-edited`" in line)
    assert "reply" in edited and "assessment" in edited, edited
    said = " ".join(currency.__doc__.split())
    assert "reply or assessment record" in said
    assert "refused only by a reply" in said
