"""The passage of a cited work that supports a sentence citing it.

`literature/passages.yaml` holds, for a sentence that cites a work, the words of that work
that support it. G7 looks for each in the work's stored files, belongs it to its sentence by
the sentence's words and the key, says where a sentence lost its passage, and counts the
statements that carry none (Basile's four answers of 2026-10-20). The co-author checker shows
the passage beside the sentence, and `passages` lists them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates import check_passages
from manuscript_guard.literature.passages import statement_words

PASSAGES = Path("literature") / "passages.yaml"
#: The example's first cited sentence, as its passage records it.
SENTENCE = (
    "In a national cohort, the crude incidence was {{lit.background.reported_incidence}} per "
    "100 000 person-years, and a disproportionality signal has been reported for the drug "
    "class as a whole (ROR {{lit.background.class_ror}})."
)
CLASS = "fictionalClassSignal2019"
COHORT = "fictionalHepaticCohort2021"


def entries(root: Path) -> list[dict]:
    return yaml.safe_load((root / PASSAGES).read_text(encoding="utf-8"))["passages"]


def write(root: Path, *passages: dict) -> None:
    document = {"schema": "manuscript-guard/passages/1", "passages": list(passages)}
    (root / PASSAGES).write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                                 encoding="utf-8")  # fmt: skip


def entry(**changed: str) -> dict:
    return {"sentence": SENTENCE, "citekey": CLASS,
            "passage": "A signal was detected for the class as a whole",
            "locator": "Abstract, Results", **changed}  # fmt: skip


def report(root: Path, stage: str = "drafting"):
    return check_passages(load_project(root)[0], stage)


def said(root: Path, stage: str = "drafting") -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in report(root, stage).findings]


def main_md(root: Path) -> Path:
    return root / "manuscript" / "main.md"


def swap(root: Path, old: str, new: str) -> None:
    path = main_md(root)
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------- the example


def test_the_example_passage_is_verified_and_the_others_counted(project: Path) -> None:
    found = report(project)
    assert found.counts["passages_verified"] == 1
    assert found.counts["cited_statements"] == 3
    assert found.counts["cited_statements_with_passage"] == 1
    [note] = found.findings
    assert (note.code, note.severity) == ("statements-without-passage", INFO)
    assert note.message.endswith(": 2 of 3")


@pytest.mark.parametrize(
    ("stage", "severity"),
    [("design", INFO), ("drafting", INFO), ("internal-review", WARN), ("submission", WARN)],
)
def test_statements_without_a_passage_are_a_note_then_a_warning(
    project: Path, stage: str, severity: str
) -> None:
    """Basile, 2026-10-20: a note while drafting, a warning from internal-review, never a
    failure, whatever the stage."""
    assert said(project, stage) == [("statements-without-passage", severity)]


def test_a_project_that_cites_nothing_has_no_note(project: Path) -> None:
    path = main_md(project)
    path.write_text(path.read_text(encoding="utf-8").replace("@", ""), encoding="utf-8")
    found = report(project, "submission")
    assert found.counts["cited_statements"] == 0
    assert [f.code for f in found.findings] == ["passage-stale"]


def test_check_runs_the_gate_at_the_project_stage(project: Path, capsys) -> None:
    main(["check", str(project), "--json", "--stage", "internal-review"])
    printed = json.loads(capsys.readouterr().out)
    [note] = [f for f in printed["findings"] if f["code"] == "statements-without-passage"]
    assert note["severity"] == WARN
    assert printed["counts"]["cited_statements_with_passage"] == 1


# ------------------------------------------------------- belonging to the sentence


@pytest.mark.parametrize(
    "sentence",
    [
        pytest.param(SENTENCE, id="without its citations"),
        pytest.param(SENTENCE.replace(" (ROR", " [@a; @b, p. 4] (ROR") + " [@x]", id="others"),
        pytest.param(SENTENCE.upper(), id="in capitals"),
        pytest.param(SENTENCE.replace(" ", "\n  ", 4), id="wrapped"),
        pytest.param(SENTENCE.rstrip("."), id="no final stop"),
        pytest.param(SENTENCE.replace("cohort,", "cohort ,"), id="a space before a comma"),
        pytest.param(SENTENCE.replace(" a whole", "\N{NO-BREAK SPACE}a whole"), id="nbsp"),
    ],
)
def test_a_passage_belongs_to_its_sentence_however_it_is_typed(
    project: Path, sentence: str
) -> None:
    write(project, entry(sentence=sentence))
    found = report(project)
    assert found.counts["cited_statements_with_passage"] == 1
    assert "passage-stale" not in [f.code for f in found.findings]


def test_a_sentence_that_moves_keeps_its_passage(project: Path) -> None:
    """Keyed on the words and the key, never on a file or a line (DESIGN.md, "What the digest
    covers"): to another place in the file, and to another file."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    start = text.index("In a national cohort")
    end = text.index("The\nnational agency")
    moved = text[start:end]
    elsewhere = text.replace(moved, "").replace("# Discussion\n", f"# Discussion\n\n{moved}\n\n")
    path.write_text(elsewhere, encoding="utf-8")
    assert report(project).counts["cited_statements_with_passage"] == 1
    path.write_text(text.replace(moved, ""), encoding="utf-8")
    supplement = project / "manuscript" / "supplementary" / "s9.md"
    supplement.write_text(f"# More\n\n{moved}\n", encoding="utf-8")
    assert report(project).counts["cited_statements_with_passage"] == 1


@pytest.mark.parametrize(
    ("change", "why"),
    [
        pytest.param(("has been reported", "was reported"), "was reworded; it may now read",
                     id="reworded"),
        pytest.param(("[@fictionalClassSignal2019]", ""), "no longer cites", id="uncited"),
        pytest.param(("In a national cohort, the crude", "Nothing here. The crude"),
                     "was reworded", id="cut in two, most words kept"),
    ],
)  # fmt: skip
def test_a_sentence_reworded_or_uncited_leaves_its_passage_stale(
    project: Path, change: tuple[str, str], why: str
) -> None:
    swap(project, *change)
    found = report(project)
    stale = [f for f in found.findings if f.code == "passage-stale"]
    assert [f.severity for f in stale] == [INFO]
    assert why in stale[0].message
    assert found.counts["passages_stale"] == 1


def test_a_sentence_gone_leaves_its_passage_stale_with_nowhere_named(project: Path) -> None:
    write(project, entry(sentence="An entirely different claim about something else."))
    [stale] = [f for f in report(project).findings if f.code == "passage-stale"]
    assert "no sentence of the manuscript citing @fictionalClassSignal2019 reads so" in (
        stale.message
    )


def test_a_passage_of_a_work_the_sentence_does_not_cite_is_stale(project: Path) -> None:
    write(project, entry(citekey="fictionalAgencyReport"))
    [stale] = [f for f in report(project).findings if f.code == "passage-stale"]
    assert "no longer cites @fictionalAgencyReport" in stale.message


def test_the_words_folded_are_only_those_no_reader_would_tell_apart() -> None:
    assert statement_words("Risk rose [@a].") == statement_words("risk  rose")
    assert statement_words("As @a showed, risk rose.") != statement_words("As showed, risk rose")
    assert statement_words("Risk rose.") != statement_words("Risk fell.")
    assert statement_words("Risk rose in 2019.") != statement_words("Risk rose in 2018.")
    assert statement_words("“Rare” [@a].") == statement_words('"rare"')


# ------------------------------------------------------------- in the source


def test_a_passage_from_another_work_fails(project: Path) -> None:
    """The cohort's words, recorded for the class signal."""
    write(project, entry(passage="Incidence rose with age and did not differ meaningfully"))
    found = report(project)
    [failed] = [f for f in found.findings if f.severity == FAIL]
    assert failed.code == "passage-not-in-source"
    assert "fictionalClassSignal2019.txt" in failed.message
    assert found.counts["passages_failed"] == 1


def test_a_passage_with_words_left_out_is_looked_for_piece_by_piece(project: Path) -> None:
    write(project, entry(passage="A signal was detected [...] as a whole (ROR 2.6"))
    assert report(project).counts["passages_verified"] == 1
    write(project, entry(passage="as a whole [...] A signal was detected"))
    assert report(project).counts["passages_failed"] == 1


def test_a_passage_of_a_work_with_no_stored_copy_is_a_warning(project: Path) -> None:
    (project / "literature" / "sources" / f"{CLASS}.txt").unlink()
    found = report(project)
    assert ("passage-unchecked", WARN) in said(project)
    assert found.counts["passages_unchecked"] == 1


def test_a_short_passage_is_a_warning(project: Path) -> None:
    write(project, entry(passage="the class as"))
    assert ("passage-too-short", WARN) in said(project)
    write(project, entry(passage="A signal was detected [...]"))
    assert ("passage-too-short", WARN) not in said(project)


# ------------------------------------------------------------- a person's judgement


def judged(support: str, by: str = "Ada Example") -> dict:
    return entry(support=support, judged_by=by, judged_on="2026-10-20")


@pytest.mark.parametrize(
    ("support", "expected"),
    [
        ("supports", []),
        ("partly", [("passage-partly-supports", WARN)]),
        ("does-not", [("passage-does-not-support", FAIL)]),
    ],
)
def test_a_judgement_is_reported_as_it_says(project: Path, support: str, expected: list) -> None:
    """`does-not` is a failure here; the stage policy makes it a note until internal-review."""
    write(project, judged(support))
    assert [x for x in said(project) if x[0] != "statements-without-passage"] == expected


def test_a_judgement_that_the_passage_does_not_support_waits_for_internal_review(
    project: Path, capsys
) -> None:
    write(project, judged("does-not"))

    def severity(stage: str) -> str:
        main(["check", str(project), "--json", "--stage", stage])
        printed = json.loads(capsys.readouterr().out)
        [found] = [f for f in printed["findings"] if f["code"] == "passage-does-not-support"]
        return found["severity"]

    assert severity("drafting") == INFO
    assert severity("internal-review") == FAIL


@pytest.mark.parametrize("judge", ["Claude", "GPT-5", "an AI assistant"])
def test_a_model_may_not_judge(project: Path, judge: str) -> None:
    write(project, judged("supports", by=judge))
    assert ("judgement-not-human", FAIL) in said(project)


def test_a_judgement_of_a_stale_passage_is_said_in_the_note_only(project: Path) -> None:
    write(project, judged("does-not"))
    swap(project, "has been reported", "was reported")
    findings = report(project).findings
    assert "passage-does-not-support" not in [f.code for f in findings]
    [stale] = [f for f in findings if f.code == "passage-stale"]
    assert "Ada Example's judgement (does-not) was of the old words" in stale.message


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"support": "supports"}, id="a judgement with no judge"),
        pytest.param({"judged_by": "Ada Example"}, id="a judge with no judgement"),
        pytest.param({"support": "yes", "judged_by": "A", "judged_on": "2026-10-20"},
                     id="a judgement of no kind"),
        pytest.param({"passage": "  "}, id="a blank passage"),
        pytest.param({"locator": ""}, id="no locator"),
    ],
)  # fmt: skip
def test_the_schema_refuses_an_entry_that_says_less_than_it_must(
    project: Path, broken: dict
) -> None:
    write(project, entry(**broken))
    found = report(project)
    assert "schema-violation" in [f.code for f in found.failures]
    assert found.counts["cited_statements_with_passage"] == 0


def test_a_file_that_cannot_be_parsed_is_said(project: Path) -> None:
    (project / PASSAGES).write_text("passages: [unclosed\n", encoding="utf-8")
    [failed] = report(project).failures
    assert failed.code == "schema-violation" and "cannot parse" in failed.message


# ------------------------------------------------------------- the listing


def test_passages_lists_each_statement_and_writes_nothing(project: Path, capsys) -> None:
    before = sorted(p.read_bytes() for p in project.rglob("*") if p.is_file())
    assert main(["passages", str(project)]) == 0
    printed = capsys.readouterr().out
    assert "@fictionalClassSignal2019: passage 1, Abstract, Results: verified" in printed
    assert "@fictionalHepaticCohort2021: no passage (fictionalHepaticCohort2021.txt)" in printed
    assert printed.rstrip().endswith("a work they cite: 1 of 3; stale passages: 0")
    assert sorted(p.read_bytes() for p in project.rglob("*") if p.is_file()) == before


def test_passages_missing_lists_the_statements_with_none(project: Path, capsys) -> None:
    assert main(["passages", str(project), "--missing", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [s["line"] for s in listed["statements"]] == [111, 116]
    assert all(not c["passages"] for s in listed["statements"] for c in s["cites"])
    assert listed["statements"][0]["sentence"].startswith("The reporting odds ratio")


def test_passages_lists_a_stale_passage(project: Path, capsys) -> None:
    swap(project, "has been reported", "was reported")
    main(["passages", str(project), "--json"])
    [stale] = json.loads(capsys.readouterr().out)["stale"]
    assert (stale["number"], stale["why"]) == (1, "changed")


def test_passages_refuses_a_file_it_cannot_use(project: Path, capsys) -> None:
    write(project, entry(support="supports"))
    assert main(["passages", str(project)]) == 2
    assert "judged_by" in capsys.readouterr().err


# ------------------------------------------------------------- the co-author checker


def claim_items(root: Path) -> list[dict]:
    from manuscript_guard.checking.items import items_from
    from manuscript_guard.checking.produce import produce

    document, unread = produce(load_project(root)[0])
    assert unread == ()
    checked = items_from(document, root / "checks" / "items.json")
    return [item for item in checked.items if item["group"] == "claim"]


def first(items: list[dict]) -> dict:
    [item] = [i for i in items if i["sentences"][0]["text"].startswith("In a national cohort")]
    return item


def test_the_checker_shows_the_passage_and_its_locator_beside_the_sentence(
    project: Path,
) -> None:
    item = first(claim_items(project))
    [shown] = [e for e in item["evidence"] if "supporting this sentence" in (e["caption"] or "")]
    assert shown["text"] == "A signal was detected for the class as a whole"
    assert shown["caption"].endswith(": Abstract, Results")


def test_a_passage_changed_after_a_co_author_read_it_changes_the_item(project: Path) -> None:
    """The evidence's words are in the digest (DESIGN.md, "What the digest covers"): an answer
    about the old passage is not one about the new."""
    before = first(claim_items(project))["digest"]
    write(project, entry(passage="A signal was detected for the class"))
    assert first(claim_items(project))["digest"] != before
    write(project, entry(locator="Abstract"))
    assert first(claim_items(project))["digest"] != before


def test_the_authors_judgement_is_not_shown_to_a_co_author(project: Path) -> None:
    """Shown, it would tell them the answer before they read; and its digest would refuse
    their answer for a judgement recorded after it."""
    before = first(claim_items(project))["digest"]
    write(project, judged("supports"))
    item = first(claim_items(project))
    assert item["digest"] == before
    assert "Ada Example" not in json.dumps(item)


def test_a_passages_file_the_checker_cannot_use_is_said(project: Path) -> None:
    from manuscript_guard.checking.produce import produce

    write(project, entry(judged_by="Ada Example"))
    _document, unread = produce(load_project(project)[0])
    assert unread and "schema-violation" in unread[0]
