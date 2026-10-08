"""Sending a manuscript's numbers to a co-author, and taking their answers back.

The thing being protected here is a person's word. A co-author says "yes, the source says that",
and months later someone has to know what exactly they said yes to. So the tests are mostly
about the digest: that it covers what they read, that it does not cover how it was drawn, and
that an answer about text the project no longer has is refused rather than recorded.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from manuscript_guard.checking import (
    AnswersError,
    BundleError,
    ItemsError,
    build_bundle,
    import_answers,
    load_items,
    status,
)
from manuscript_guard.checking.items import digest_of

#: A one-pixel PNG: the smallest thing that is really an image.
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def write_items(root: Path, items: list[dict] | None = None, *, title: str = "A paper") -> Path:
    """An items file of the shape a project writes, with one image on disk beside it."""
    (root / "checks" / "evidence").mkdir(parents=True, exist_ok=True)
    (root / "checks" / "evidence" / "page.png").write_bytes(PIXEL)
    document = {
        "schema": "manuscript-guard/checking/1",
        "title": title,
        "groups": [
            {
                "id": "literature",
                "title": "Numbers from the literature",
                "ask": "Does the source say this number?",
                "seconds": 25,
            },
            {"id": "claim", "title": "Cited statements", "ask": "Does the paper say this?"},
        ],
        "items": items
        if items is not None
        else [
            {
                "id": "lit-1",
                "group": "literature",
                "title": "18.4 % of the treated group",
                "facts": [["Value as printed", "18.4"]],
                "sentences": [
                    {"text": "Among the 94 patients who changed treatment ... (18.4%).",
                     "line": 510, "section": "Treatment patterns", "mark": ["18.4"]}
                ],
                "evidence": [
                    {"kind": "image", "caption": "page 65", "file": "evidence/page.png"},
                    {"kind": "text", "caption": "the source", "line": 212,
                     "lines": [[212, "changed treatment (17 individuals, 18.4%)"]]},
                ],
            },
            {
                "id": "claim-1",
                "group": "claim",
                "title": "Arrests reflect enforcement",
                "sentences": [{"text": "Arrests mainly reflect enforcement.", "line": 594}],
            },
        ],
    }
    path = root / "checks" / "items.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def answers_for(items, *, by: str, statuses: dict[str, str], bundle: str = "b1") -> dict:
    return {
        "schema": "manuscript-guard/checking-answers/1",
        "bundle": bundle,
        "by": by,
        "answers": [
            {
                "id": item["id"],
                "digest": item["digest"],
                "status": statuses[item["id"]],
                "note": "",
                "at": "2026-10-08T09:00:00",
            }
            for item in items.items
            if item["id"] in statuses
        ],
    }


# ---------------------------------------------------------------- the items and their digest


def test_the_digest_covers_what_a_person_read(tmp_path: Path) -> None:
    """Their yes is about this value in these sentences. Change either and it is another item."""
    item = {"id": "a", "group": "g", "title": "t", "facts": [["Value", "18.4"]],
            "sentences": [{"text": "A sentence.", "line": 1, "section": "S"}]}
    before = digest_of(item)
    assert digest_of({**item, "title": "another title"}) != before
    assert digest_of({**item, "facts": [["Value", "18.5"]]}) != before
    reworded = {**item, "sentences": [{"text": "Another sentence.", "line": 1, "section": "S"}]}
    assert digest_of(reworded) != before


def test_the_digest_does_not_cover_where_the_sentence_sits(tmp_path: Path) -> None:
    """A paragraph added to the Introduction moves every line below it and changes not one
    sentence. With the line in the digest, that edit would refuse every answer in the paper."""
    item = {"id": "a", "group": "g", "title": "t", "facts": [["Value", "18.4"]],
            "sentences": [{"text": "A sentence.", "line": 11, "section": "S"}]}
    moved = {**item, "sentences": [{"text": "A sentence.", "line": 94, "section": "S"}]}
    assert digest_of(moved) == digest_of(item)
    elsewhere = {**item, "sentences": [{"text": "A sentence.", "line": 11, "section": "Other"}]}
    assert digest_of(elsewhere) != digest_of(item)


def test_the_digest_does_not_cover_how_the_evidence_was_drawn(tmp_path: Path) -> None:
    """A page re-rendered larger is the same page, and a co-author's answer still stands."""
    item = {"id": "a", "group": "g", "title": "t",
            "evidence": [{"kind": "image", "file": "evidence/page.png"}]}
    assert digest_of(item) == digest_of(
        {**item, "evidence": [{"kind": "image", "file": "evidence/page@2x.png"}]}
    )


def test_items_that_do_not_fit_the_schema_say_so(tmp_path: Path) -> None:
    path = write_items(tmp_path, items=[{"id": "x", "group": "literature"}])  # no title
    with pytest.raises(ItemsError, match="does not fit the schema"):
        load_items(tmp_path, path)


def test_an_item_in_no_declared_group_is_refused(tmp_path: Path) -> None:
    path = write_items(tmp_path, items=[{"id": "x", "group": "nowhere", "title": "t"}])
    with pytest.raises(ItemsError, match="not one of"):
        load_items(tmp_path, path)


def test_two_items_with_one_id_are_refused(tmp_path: Path) -> None:
    """Answers are keyed by id; two items sharing one would record each other's."""
    twice = [
        {"id": "x", "group": "claim", "title": "a"},
        {"id": "x", "group": "claim", "title": "b"},
    ]
    path = write_items(tmp_path, items=twice)
    with pytest.raises(ItemsError, match="appears twice"):
        load_items(tmp_path, path)


def test_a_missing_items_file_names_the_schema(tmp_path: Path) -> None:
    with pytest.raises(ItemsError, match="checking.schema.json"):
        load_items(tmp_path)


# ---------------------------------------------------------------- the file a co-author opens


def test_the_bundle_is_one_file_that_asks_the_network_for_nothing(tmp_path: Path) -> None:
    """A co-author opens it on a hospital laptop with no connection, from wherever their mail
    client put it. Anything fetched at open time is a thing that will not be there."""
    items = load_items(tmp_path, write_items(tmp_path))
    out, size = build_bundle(items, person="Ada Example", title="A paper",
                             out=tmp_path / "check.html", to="the corresponding author")
    page = out.read_text(encoding="utf-8")
    assert size > 1000
    assert "data:image/png;base64," in page, "the image is carried, not referenced"
    assert "evidence/page.png" not in page, "and its path is gone with it"
    assert page.count("data:image/png;base64,") == 1, "and carried once"
    for fetched in ("src=\"http", "href=\"http", "@import", "fetch(", "XMLHttpRequest"):
        assert fetched not in page, f"the page reaches for {fetched}"


def test_the_bundle_carries_the_items_and_who_it_is_for(tmp_path: Path) -> None:
    items = load_items(tmp_path, write_items(tmp_path))
    out, _ = build_bundle(items, person="Blaise Sample", title="A paper",
                          out=tmp_path / "check.html")
    page = out.read_text(encoding="utf-8")
    assert "Blaise Sample" in page
    assert "18.4 % of the treated group" in page
    assert "Does the source say this number?" in page
    assert "answers-blaise-sample.json" in page, "the file they send back is named for them"


def test_a_bundle_with_no_name_is_refused(tmp_path: Path) -> None:
    """A decision is recorded under a person's name; an anonymous one records nothing."""
    items = load_items(tmp_path, write_items(tmp_path))
    with pytest.raises(BundleError, match="who the file is for"):
        build_bundle(items, person="  ", title="A paper", out=tmp_path / "check.html")


def test_evidence_that_is_not_there_is_named(tmp_path: Path) -> None:
    items = load_items(tmp_path, write_items(tmp_path))
    (tmp_path / "checks" / "evidence" / "page.png").unlink()
    with pytest.raises(BundleError, match="is named as evidence and is not there"):
        build_bundle(items, person="A Person", title="A paper", out=tmp_path / "check.html")


def test_an_image_too_large_to_send_is_refused(tmp_path: Path) -> None:
    """One file has to arrive. A page rendered at 600 dpi is how it stops arriving."""
    from manuscript_guard.checking import bundle as module

    items = load_items(tmp_path, write_items(tmp_path))
    (tmp_path / "checks" / "evidence" / "page.png").write_bytes(PIXEL + b"\0" * 2048)
    original = module.MAX_IMAGE_BYTES
    try:
        module.MAX_IMAGE_BYTES = 1024
        with pytest.raises(BundleError, match="Render the page smaller"):
            build_bundle(items, person="A Person", title="A paper", out=tmp_path / "check.html")
    finally:
        module.MAX_IMAGE_BYTES = original


def test_a_script_ending_inside_the_data_cannot_end_the_page(tmp_path: Path) -> None:
    """A manuscript sentence may contain anything, `</script>` included, and the page that
    carries it must still be the page."""
    items = load_items(
        tmp_path,
        write_items(
            tmp_path,
            items=[{"id": "x", "group": "claim", "title": "t",
                    "sentences": [{"text": "A sentence with </script> in it."}]}],
        ),
    )
    out, _ = build_bundle(items, person="A Person", title="A paper", out=tmp_path / "check.html")
    page = out.read_text(encoding="utf-8")
    assert "<\\/script>" in page
    assert page.count("</script>") == 1, "only the page's own script element ends"


# ---------------------------------------------------------------- what comes back


def test_answers_are_recorded_under_the_name_of_whoever_made_them(tmp_path: Path) -> None:
    items = load_items(tmp_path, write_items(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            answers_for(items, by="Ada Example", statuses={"lit-1": "ok", "claim-1": "wrong"})
        ),
        encoding="utf-8",
    )
    brought = import_answers(tmp_path, answers, items)
    assert brought.by == "Ada Example"
    assert {d.id: d.status for d in brought.recorded} == {"lit-1": "ok", "claim-1": "wrong"}
    written = (tmp_path / "checks" / "decisions.csv").read_text(encoding="utf-8")
    assert "Ada Example" in written and "lit-1" in written


def test_an_answer_about_an_item_that_has_changed_is_not_recorded(tmp_path: Path) -> None:
    """The sentence was reworded after they read it. Their yes is about text nobody has now, so
    the item is outstanding again rather than silently confirmed."""
    path = write_items(tmp_path)
    items = load_items(tmp_path, path)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(answers_for(items, by="A Person", statuses={"lit-1": "ok", "claim-1": "ok"})),
        encoding="utf-8",
    )

    document = json.loads(path.read_text(encoding="utf-8"))
    document["items"][0]["sentences"][0]["text"] = (
        "Among patients who changed treatment ... (18.4%)."
    )
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    moved = load_items(tmp_path, path)

    brought = import_answers(tmp_path, answers, moved)
    assert [d.id for d in brought.recorded] == ["claim-1"]
    # Named by its title, not by the twelve hex characters of its id: whoever reads this refusal
    # has to find the thing and ask somebody about it again.
    assert brought.stale and brought.stale[0][0] == "18.4 % of the treated group"
    assert brought.stale[0][0] != "lit-1"
    assert "changed after it was checked" in brought.stale[0][1]
    assert status(tmp_path, moved).outstanding == 1


def test_an_answer_to_an_item_this_project_does_not_have_is_not_recorded(tmp_path: Path) -> None:
    items = load_items(tmp_path, write_items(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "schema": "manuscript-guard/checking-answers/1",
                "by": "A Person",
                "answers": [{"id": "from-another-paper", "digest": "x", "status": "ok"}],
            }
        ),
        encoding="utf-8",
    )
    brought = import_answers(tmp_path, answers, items)
    assert brought.recorded == () and brought.unknown == ("from-another-paper",)


def test_an_answers_file_with_no_name_is_refused(tmp_path: Path) -> None:
    items = load_items(tmp_path, write_items(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps({"schema": "manuscript-guard/checking-answers/1", "answers": []}),
        encoding="utf-8",
    )
    with pytest.raises(AnswersError, match="does not say who made it"):
        import_answers(tmp_path, answers, items)


def test_something_that_is_not_an_answers_file_is_refused(tmp_path: Path) -> None:
    items = load_items(tmp_path, write_items(tmp_path))
    answers = tmp_path / "answers.json"
    answers.write_text("the co-author pasted the email instead", encoding="utf-8")
    with pytest.raises(AnswersError, match="not an answers file"):
        import_answers(tmp_path, answers, items)


# ---------------------------------------------------------------- where the round stands


def test_two_people_disagreeing_about_one_item_is_reported(tmp_path: Path) -> None:
    """The reason for sending the same items to two readers is this moment, and it has to be
    visible rather than resolved by whoever imported last."""
    items = load_items(tmp_path, write_items(tmp_path))
    for person, said in (("Ada Example", "ok"), ("Blaise Sample", "wrong")):
        answers = tmp_path / f"answers-{person[:3]}.json"
        answers.write_text(
            json.dumps(answers_for(items, by=person, statuses={"lit-1": said})), encoding="utf-8"
        )
        import_answers(tmp_path, answers, items)

    standing = status(tmp_path, items)
    assert standing.people == ("Ada Example", "Blaise Sample")
    assert standing.outstanding == 1, "claim-1 is still nobody's"
    assert len(standing.disagreements) == 1
    identifier, decisions = standing.disagreements[0]
    assert identifier == "lit-1"
    assert {d.by: d.status for d in decisions} == {"Ada Example": "ok", "Blaise Sample": "wrong"}


def test_the_latest_answer_by_one_person_is_the_one_that_counts(tmp_path: Path) -> None:
    """They changed their mind, which is allowed; the earlier answer stays in the file."""
    items = load_items(tmp_path, write_items(tmp_path))
    for said in ("wrong", "ok"):
        answers = tmp_path / f"answers-{said}.json"
        answers.write_text(
            json.dumps(answers_for(items, by="A Person", statuses={"lit-1": said})),
            encoding="utf-8",
        )
        import_answers(tmp_path, answers, items)

    standing = status(tmp_path, items)
    assert standing.by_person["A Person"] == {"ok": 1}
    assert standing.disagreements == ()
    assert (tmp_path / "checks" / "decisions.csv").read_text(encoding="utf-8").count("lit-1") == 2


def test_an_item_someone_has_already_checked_is_not_asked_again(tmp_path: Path) -> None:
    items = load_items(
        tmp_path,
        write_items(
            tmp_path,
            items=[
                {"id": "x", "group": "claim", "title": "t", "already": "checked on 2026-09-17"},
                {"id": "y", "group": "claim", "title": "u"},
            ],
        ),
    )
    assert [item["id"] for item in items.outstanding] == ["y"]
    assert status(tmp_path, items).already == 1


def test_a_passage_of_a_source_travels_as_evidence(tmp_path: Path) -> None:
    """The question "does the cited source say what this sentence says" needs the passage, which
    is neither a picture, a table, nor lines with numbers."""
    items = load_items(
        tmp_path,
        write_items(
            tmp_path,
            items=[
                {
                    "id": "c1",
                    "group": "claim",
                    "title": "Three epidemics",
                    "sentences": [{"text": "The review described two distinct periods."}],
                    "evidence": [
                        {
                            "kind": "quote",
                            "caption": "fictionalReview2011.pdf, page 1",
                            "text": "is characterised by two distinct periods of rising incidence",
                            "mark": ["two distinct periods"],
                        }
                    ],
                }
            ],
        ),
    )
    out, _ = build_bundle(items, person="A Person", title="A paper", out=tmp_path / "check.html")
    page = out.read_text(encoding="utf-8")
    assert "two distinct periods of rising incidence" in page
    assert '"kind":"quote"' in page.replace(" ", "")


# ---------------------------------------------------------------- what the toolkit finds itself
#
# The producer's job is to need nothing of the project but the files the project already keeps.
# What these hold is that each of the four kinds reaches a co-author as something a person can
# answer: a value with the sentence it was taken from, an author's degrees as words rather than
# as a list, a reference with its journal and year whichever dialect the .bib is written in.


def produced(root: Path) -> dict:
    """What this project offers, checked against the schema the same way a project's file is."""
    from manuscript_guard.checking.items import items_from
    from manuscript_guard.checking.produce import produce
    from manuscript_guard.cli import load_project

    project, _ = load_project(root)
    document, unread = produce(project)
    assert unread == (), f"this project's own files could not all be read: {unread}"
    items_from(document, root / "checks" / "items.json")  # refuses anything malformed
    return document


def only(document: dict, group: str) -> list[dict]:
    return [item for item in document["items"] if item["group"] == group]


def test_produce_finds_all_four_kinds_in_the_example(project: Path) -> None:
    document = produced(project)
    found = {item["group"] for item in document["items"]}
    assert found == {"literature", "claim", "reference", "author"}


def test_a_ledger_value_travels_with_the_quote_it_came_from(project: Path) -> None:
    item = next(i for i in only(produced(project), "literature") if "class_ror" in i["title"])
    quote = next(e for e in item["evidence"] if e["kind"] == "quote")
    assert "ROR 2.6" in quote["text"]
    assert "2.6" in quote["mark"]  # highlighted, so the eye lands on the number


def test_an_attested_value_travels_with_the_attestation(project: Path) -> None:
    """There is no quote and no stored file for one of these, by definition. What there is to
    check is the author's statement, and a co-author shown nothing cannot answer at all."""
    item = next(
        i for i in only(produced(project), "literature") if "withdrawn_estimate" in i["title"]
    )
    assert [e["kind"] for e in item["evidence"]] != ["none"]
    attestation = next(e for e in item["evidence"] if "attestation" in (e.get("caption") or ""))
    assert "printed report held in the hospital library" in attestation["note"]
    assert ["Attested by", "Ada Example"] in attestation["rows"]
    assert [
        "Source",
        "Fictional National Agency, annual pharmacovigilance report 2019, print edition",
    ] in item["facts"]


def test_a_cited_sentence_reaches_the_co_author_without_its_bindings(project: Path) -> None:
    """A binding is markup. The claim is what the sentence says, and a `{{results.x}}` in front
    of a reader is a question about the toolkit instead of about the paper."""
    claims = only(produced(project), "claim")
    assert claims
    for item in claims:
        assert "{{" not in item["title"]
        for sentence in item["sentences"]:
            assert "{{" not in sentence["text"]


def test_an_authors_degrees_and_roles_are_words_not_a_list(project: Path) -> None:
    item = next(i for i in only(produced(project), "author") if i["title"] == "Ada Example")
    facts = {label: value for label, value in item["facts"]}
    assert facts["Degrees"] == "PharmD, MSc"
    assert facts["Corresponding author"] == "yes"
    assert facts["CRediT roles"].startswith("Conceptualization, Formal analysis")


def test_an_author_sees_their_affiliation_and_not_its_id(project: Path) -> None:
    item = next(i for i in only(produced(project), "author") if i["title"] == "Ada Example")
    affiliations = [value for label, value in item["facts"] if label == "Affiliation"]
    assert affiliations == [
        "Department of Clinical Pharmacology, Example University Graduate School of Medicine, "
        "Springfield, Japan"
    ]


def test_a_reference_carries_its_journal_and_date_in_either_bib_dialect(project: Path) -> None:
    """Better BibTeX writes biblatex (`journaltitle`, `date`); a hand-kept file is often plain
    BibTeX (`journal`, `year`). A reference shown with neither cannot be checked."""
    from manuscript_guard.checking.produce import (
        REFERENCE_FIELDS,
        _bib_records,
        _rows_for,
    )
    from manuscript_guard.cli import load_project

    (project / "literature" / "references.bib").write_text(
        "@article{bibtex2019,\n"
        "  author = {Plain, Bib},\n"
        "  title = {A paper in the older dialect},\n"
        "  journal = {Journal of Older Dialects},\n"
        "  year = {2019},\n"
        "}\n\n"
        "@article{biblatex2021,\n"
        "  author = {Bib, Latex},\n"
        "  title = {A paper in the newer dialect},\n"
        "  journaltitle = {Journal of Newer Dialects},\n"
        "  date = {2021-06},\n"
        "}\n",
        encoding="utf-8",
    )
    loaded, _ = load_project(project)
    records = _bib_records(loaded)
    for key, journal, date in (
        ("bibtex2019", "Journal of Older Dialects", "2019"),
        ("biblatex2021", "Journal of Newer Dialects", "2021-06"),
    ):
        rows = {label: value for label, value in _rows_for(records[key], REFERENCE_FIELDS)}
        assert rows["Journal"] == journal
        assert rows["Date"] == date


def test_an_item_keeps_its_identifier_across_runs(project: Path) -> None:
    """An answer is recorded against an id. If the id moved between builds, a co-author's "yes"
    would attach to nothing, so nothing here may depend on a clock or on a hash seed."""
    first = {item["id"] for item in produced(project)["items"]}
    second = {item["id"] for item in produced(project)["items"]}
    assert first == second


def test_a_claim_keeps_its_identifier_when_a_bound_value_changes(project: Path) -> None:
    """The question put to a co-author is whether the cited paper says what the sentence says.
    Re-running the analysis does not change that question, so it does not reopen the answer."""
    before = {item["id"] for item in only(produced(project), "claim")}
    ledger = project / "literature" / "ledger.yaml"
    text = ledger.read_text(encoding="utf-8")
    # Value and display together: a display that disagrees with its value is a finding of its
    # own, which `produce` now reports rather than swallowing.
    assert 'display: "14"' in text and "value: 14.0" in text
    ledger.write_text(
        text.replace('display: "14"', 'display: "15"').replace("value: 14.0", "value: 15.0"),
        encoding="utf-8",
    )
    assert {item["id"] for item in only(produced(project), "claim")} == before


def test_a_long_title_says_where_it_was_cut(project: Path) -> None:
    items = produced(project)["items"]
    for item in items:
        assert len(item["title"]) <= 110
    assert [item for item in items if item["title"].endswith("…")], (
        "the example has sentences past 110 characters, and a title cut mid-word reads as a typo"
    )


def test_a_projects_own_items_come_first_and_win_a_shared_id() -> None:
    from manuscript_guard.checking.produce import merge

    mine = {
        "schema": "manuscript-guard/checking/1",
        "title": "the project's own",
        "groups": [{"id": "table", "title": "Transcribed", "ask": "Does row 14 say this?"}],
        "items": [
            {"id": "shared", "group": "table", "title": "the project's version"},
            {"id": "table-1", "group": "table", "title": "a number from a workbook"},
        ],
    }
    theirs = {
        "schema": "manuscript-guard/checking/1",
        "title": "the toolkit's",
        "groups": [{"id": "literature", "title": "Numbers", "ask": "Does the source say this?"}],
        "items": [
            {"id": "shared", "group": "literature", "title": "the toolkit's version"},
            {"id": "lit-1", "group": "literature", "title": "a value from the ledger"},
        ],
    }
    merged, skipped = merge(theirs, mine)
    assert skipped == {}  # the project filled no group the toolkit produces
    assert merged["title"] == "the project's own"
    assert [group["id"] for group in merged["groups"]] == ["table", "literature"]
    assert [item["id"] for item in merged["items"]] == ["shared", "table-1", "lit-1"]
    shared = next(item for item in merged["items"] if item["id"] == "shared")
    assert shared["title"] == "the project's version"


def test_a_group_the_project_fills_takes_none_of_the_toolkits() -> None:
    """Found on the paper this was built for: its own items file fills four of the groups the
    toolkit also produces, with each value traced to a row of a source document. The two
    producers key their ids on different things, so the same value gets two ids, nothing
    deduplicates, and a co-author is asked about it twice. A group is therefore taken whole."""
    from manuscript_guard.checking.produce import merge

    theirs = {
        "schema": "manuscript-guard/checking/1",
        "title": "the toolkit's",
        "groups": [
            {"id": "literature", "title": "Numbers", "ask": "Does the source say this?"},
            {"id": "author", "title": "Authors", "ask": "Is this right?"},
        ],
        "items": [
            {"id": "lit-a", "group": "literature", "title": "a value the toolkit found"},
            {"id": "lit-b", "group": "literature", "title": "another"},
            {"id": "author-a", "group": "author", "title": "a person"},
        ],
    }
    merged, skipped = merge(
        theirs,
        {
            "schema": "manuscript-guard/checking/1",
            "title": "the project's own",
            "groups": [{"id": "literature", "title": "Numbers", "ask": "Does it say this?"}],
            # One item in that group, traced to a row only the project knows.
            "items": [{"id": "mine", "group": "literature", "title": "row 14 of table 3"}],
        },
    )
    assert [item["id"] for item in merged["items"]] == ["mine", "author-a"]
    assert skipped == {"literature": 2}, "both of the toolkit's literature items, and counted"


def test_an_item_in_a_group_nothing_declares_is_not_sent() -> None:
    """A group is how the page asks its question, so an item in none has no question to put.
    The same with and without a project's own file: a producer that forgot to declare a group
    should not have it slip through on the projects that contribute nothing."""
    from manuscript_guard.checking.produce import merge

    theirs = {
        "schema": "manuscript-guard/checking/1",
        "title": "the toolkit's",
        "groups": [{"id": "literature", "title": "Numbers", "ask": "Does the source say this?"}],
        "items": [
            {"id": "lit-1", "group": "literature", "title": "a value"},
            {"id": "orphan", "group": "undeclared", "title": "no group asks about this"},
        ],
    }
    alone, _ = merge(theirs, None)
    assert [item["id"] for item in alone["items"]] == ["lit-1"]
    with_mine, _ = merge(
        theirs,
        {
            "schema": "manuscript-guard/checking/1",
            "title": "the project's own",
            "groups": [{"id": "table", "title": "Transcribed", "ask": "Does row 14 say this?"}],
            "items": [{"id": "mine", "group": "table", "title": "a number from a workbook"}],
        },
    )
    assert [item["id"] for item in with_mine["items"]] == ["mine", "lit-1"]


def test_a_project_with_nothing_to_check_is_told_so_in_words(project: Path) -> None:
    """The schema's own refusal here is "items: [] should be non-empty", about a file the author
    never wrote. An author early enough in a paper to have nothing to send should be told what
    was looked at, not shown a rule."""
    from manuscript_guard.checking.items import ItemsError
    from manuscript_guard.cli import _checking_items, load_project

    (project / "literature" / "ledger.yaml").write_text(
        "schema: manuscript-guard/ledger/1\nentries: []\n", encoding="utf-8"
    )
    (project / "literature" / "attested.yaml").unlink()
    (project / "literature" / "references.bib").write_text("", encoding="utf-8")
    (project / "authors.yaml").write_text(
        "schema: manuscript-guard/authors/1\naffiliations: []\nauthors: []\n", encoding="utf-8"
    )
    for page in (project / "manuscript").rglob("*.md"):
        page.write_text("# Introduction\n\nNothing cited here yet.\n", encoding="utf-8")

    loaded, _ = load_project(project)
    with pytest.raises(ItemsError) as refused:
        _checking_items(loaded, None)
    said = str(refused.value)
    assert "nothing to check yet" in said
    assert "ledger.yaml" in said and "authors.yaml" in said
    assert "non-empty" not in said


def test_a_reference_is_shown_without_its_tex(project: Path) -> None:
    """`pages = {425--440}` is a page range, and `425--440` in front of a co-author reads as a
    mistake in the paper. A DOI is left alone: a few really do carry a double hyphen."""
    from manuscript_guard.checking.produce import (
        REFERENCE_FIELDS,
        _records_read_here,
        _rows_for,
    )

    bib = project / "literature" / "references.bib"
    bib.write_text(
        "@article{dashes2019,\n"
        "  author = {Writer, Some},\n"
        "  title = {Hepatic injury, 2010--2019},\n"
        "  journal = {Research \\& Practice},\n"
        "  pages = {425--440},\n"
        "  doi = {10.1234/some--journal.2019},\n"
        "  year = {2019},\n"
        "}\n",
        encoding="utf-8",
    )
    # The fallback reader by name. With pandoc on the path the entry is parsed instead, and
    # pandoc writes that page range with a plain hyphen; both identify the same pages.
    rows = {
        label: value
        for label, value in _rows_for(_records_read_here(bib)["dashes2019"], REFERENCE_FIELDS)
    }
    assert rows["Pages"] == "425–440"
    assert rows["Title"] == "Hepatic injury, 2010–2019"
    assert rows["Journal"] == "Research & Practice"
    assert rows["DOI"] == "10.1234/some--journal.2019"


def test_an_equals_sign_inside_a_value_does_not_become_a_field(project: Path) -> None:
    """Found on a real bibliography. Looking for `name =` anywhere in an entry finds one inside
    a value: four entries in fifty-eight gained a field no line of the file declares — `tstat`
    from a URL's query string, `n` from "(n = 866)" in an abstract, `given` and `family` from a
    biblatex extended name. The one that matters is a URL carrying `&title=`, which replaced the
    entry's real title with a fragment of a link, and a co-author would have been shown that as
    the thing to check."""
    from manuscript_guard.checking.produce import (
        REFERENCE_FIELDS,
        _bib_records,
        _rows_for,
    )
    from manuscript_guard.cli import load_project

    (project / "literature" / "references.bib").write_text(
        "@article{query2019,\n"
        "  author = {Writer, Some},\n"
        "  title = {The real title},\n"
        "  url = {https://example.invalid/down.asp?id=22862&title=Not+The+Title},\n"
        "  abstract = {A study of 866 people (n = 866) and what they did.},\n"
        "  year = {2019},\n"
        "}\n",
        encoding="utf-8",
    )
    loaded, _ = load_project(project)
    record = _bib_records(loaded)["query2019"]
    assert record["title"] == "The real title"
    assert record["url"].endswith("title=Not+The+Title")
    assert "id" not in record and "n" not in record
    rows = {label: value for label, value in _rows_for(record, REFERENCE_FIELDS)}
    assert rows["Title"] == "The real title"


def test_a_value_that_holds_commas_in_braces_stays_one_field(project: Path) -> None:
    """A biblatex extended name puts commas inside the author's braces. Cutting the entry at
    every comma would make four fields of one author."""
    from manuscript_guard.checking.produce import _records_read_here

    bib = project / "literature" / "references.bib"
    bib.write_text(
        "@article{extended2026,\n"
        "  title = {A paper},\n"
        "  author = {Low, Lambert and family=Eijk, given=Yvette, prefix=van der, "
        "useprefix=true and See, Kay Choong},\n"
        "  date = {2026-02-02},\n"
        "}\n",
        encoding="utf-8",
    )
    # The fallback reader, which shows the field as the file writes it. pandoc reads that
    # extended name into "van der Eijk, Yvette", which is better and is what a project with
    # pandoc gets; what this holds is that neither reader makes four fields of one author.
    record = _records_read_here(bib)["extended2026"]
    assert record["author"].startswith("Low, Lambert and family=Eijk")
    assert record["author"].endswith("See, Kay Choong")
    assert record["date"] == "2026-02-02"
    assert "given" not in record and "prefix" not in record


def test_a_project_with_its_own_items_file_builds(project: Path) -> None:
    """The path every real project takes, and the one the other tests missed. Reading the
    project's file through `load_items` returned items carrying the `digest` it adds, and the
    schema allows no property it does not know — so every project that had an items file of its
    own, the only ones with anything to merge, was refused item by item."""
    import json

    from manuscript_guard.cli import _checking_items, load_project

    (project / "checks").mkdir(exist_ok=True)
    (project / "checks" / "items.json").write_text(
        json.dumps(
            {
                "schema": "manuscript-guard/checking/1",
                "title": "this project's own",
                "groups": [
                    {"id": "official", "title": "Numbers from official tables",
                     "ask": "Does the table say this?", "seconds": 30}
                ],
                "items": [
                    {
                        "id": "official-1",
                        "group": "official",
                        "title": "41 200 exposed patients",
                        "facts": [["Row", "14"]],
                        "evidence": [{"kind": "facts", "caption": "table 3",
                                      "rows": [["Row 14", "41 200"]]}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded, _ = load_project(project)
    items = _checking_items(loaded, None)

    assert items.title == "this project's own"
    assert [item["id"] for item in items.items][0] == "official-1", "the project's go first"
    assert all(item.get("digest") for item in items.items), "every item is digested once"
    groups = [group["id"] for group in items.groups]
    assert groups[0] == "official"
    # The toolkit's groups follow, and its items in them are kept: this project filled none.
    assert {"literature", "claim", "reference", "author"} <= set(groups)
    assert len(items.items) > 1


def test_a_project_items_file_with_the_wrong_schema_is_refused(project: Path) -> None:
    """The merged document carries the toolkit's own schema key, so a wrong one in the project's
    file has to be caught before the merge or it passes unremarked."""
    import json

    from manuscript_guard.checking.items import ItemsError
    from manuscript_guard.cli import _checking_items, load_project

    (project / "checks").mkdir(exist_ok=True)
    (project / "checks" / "items.json").write_text(
        json.dumps({"schema": "something/else/1", "groups": [], "items": []}), encoding="utf-8"
    )
    loaded, _ = load_project(project)
    with pytest.raises(ItemsError, match="schema is 'something/else/1'"):
        _checking_items(loaded, None)


# --------------------------------------------------------- what round 1 of #221 found, held
#
# Three of its six blocking findings said the same thing: the promise that an answer cannot
# outlive the text it was about held once, at import, and nowhere else. These are the tests
# that would have caught each one.


def test_an_answer_stops_counting_when_its_item_changes(tmp_path: Path) -> None:
    """`status` compared no digest at all: it marked an item answered if any decision carried
    its id. So editing a value the day after a round came back left every item reading as
    answered by everybody, which is the opposite of what the digest is for."""
    path = write_items(tmp_path)
    items = load_items(tmp_path, path)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(answers_for(items, by="Ada Example", statuses={"lit-1": "ok", "claim-1": "ok"})),
        encoding="utf-8",
    )
    import_answers(tmp_path, answers, items)
    assert status(tmp_path, items).outstanding == 0

    document = json.loads(path.read_text(encoding="utf-8"))
    document["items"][0]["title"] = "the value, rewritten after they looked"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    moved = load_items(tmp_path, path)

    standing = status(tmp_path, moved)
    assert standing.outstanding == 1, "the changed item is outstanding again"
    assert [d.id for d in standing.stale] == ["lit-1"]
    assert standing.by_person["Ada Example"] == {"ok": 1}, "only the answer that still stands"


def test_an_unsure_leaves_the_item_outstanding(tmp_path: Path) -> None:
    """The skill and `store.py`'s own comment both say an "unsure" keeps the item outstanding for
    someone else. `status` counted it answered and closed the item."""
    path = write_items(tmp_path)
    items = load_items(tmp_path, path)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            answers_for(items, by="Ada Example", statuses={"lit-1": "unsure", "claim-1": "ok"})
        ),
        encoding="utf-8",
    )
    import_answers(tmp_path, answers, items)

    standing = status(tmp_path, items)
    assert standing.outstanding == 1, "the one they could not settle"
    assert standing.by_person["Ada Example"] == {"unsure": 1, "ok": 1}, "both are still recorded"


def test_a_decision_about_an_item_that_is_gone_is_reported_not_counted(tmp_path: Path) -> None:
    path = write_items(tmp_path)
    items = load_items(tmp_path, path)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(answers_for(items, by="Ada Example", statuses={"lit-1": "ok", "claim-1": "ok"})),
        encoding="utf-8",
    )
    import_answers(tmp_path, answers, items)

    document = json.loads(path.read_text(encoding="utf-8"))
    document["items"] = [item for item in document["items"] if item["id"] != "lit-1"]
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    fewer = load_items(tmp_path, path)

    standing = status(tmp_path, fewer)
    assert [d.id for d in standing.orphaned] == ["lit-1"]
    assert standing.outstanding == 0, "what is left was answered"


def test_the_digest_covers_the_words_of_the_evidence(tmp_path: Path) -> None:
    """The literature group asks "Does the quoted passage say this number?" — so the passage is
    the question, and it was not in the digest. A quote replaced between build and import left a
    co-author's "yes" recorded against a sentence they never read."""
    item = {
        "id": "a", "group": "g", "title": "t",
        "evidence": [{"kind": "quote", "caption": "a source, p. 1", "text": "the passage"}],
    }
    before = digest_of(item)
    reworded = {**item, "evidence": [{**item["evidence"][0], "text": "another passage"}]}
    assert digest_of(reworded) != before, "the words of the evidence are in it"

    recaptioned = {**item, "evidence": [{**item["evidence"][0], "caption": "a source, p. 2"}]}
    assert digest_of(recaptioned) != before, "so is what it is said to be"

    # Still out, by the argument that held for the image: how it was drawn, and where to look.
    marked = {**item, "evidence": [{**item["evidence"][0], "mark": ["passage"]}]}
    assert digest_of(marked) == before
    table = {"id": "b", "group": "g", "title": "t",
             "evidence": [{"kind": "table", "grid": [["14"]], "target": [0, 0]}]}
    moved_outline = {**table, "evidence": [{**table["evidence"][0], "target": [0, 1]}]}
    assert digest_of(moved_outline) == digest_of(table)
    other_cell = {**table, "evidence": [{**table["evidence"][0], "grid": [["41"]]}]}
    assert digest_of(other_cell) != digest_of(table)


def test_a_paragraph_added_above_keeps_every_claim_answer(project: Path) -> None:
    """The case DESIGN.md said had been removed. It was removed from the digest and left in the
    claim's id, so one paragraph added to the Introduction threw away every claim answer below
    it, each refused with a line naming twelve hex characters."""
    before = {item["id"] for item in only(produced(project), "claim")}
    assert before

    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    at = text.index("# Introduction") + len("# Introduction")
    main.write_text(
        text[:at] + "\n\nThis paragraph cites nothing and moves every line below it.\n" + text[at:],
        encoding="utf-8",
    )
    assert {item["id"] for item in only(produced(project), "claim")} == before


def test_a_citation_after_an_abbreviation_keeps_its_sentence(project: Path) -> None:
    """"described by Okada et al. [@key]." was cut at the stop in "al.", so the item a co-author
    was asked about read "[@key]." and the half carrying the claim was on no item at all."""
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8")
        + "\n\nThe association was first described by Okada et al. "
        "[@fictionalClassSignal2019]. A later study agreed.\n",
        encoding="utf-8",
    )
    titles = [item["title"] for item in only(produced(project), "claim")]
    assert any(title.startswith("The association was first described by Okada et al.")
               for title in titles), titles
    assert not any(title.startswith("[@") for title in titles), "no item is only a citation"


def test_a_narrative_citation_that_ends_a_sentence_is_offered(project: Path) -> None:
    """The key carried the full stop, so it matched nothing the toolkit knew and the sentence was
    on no item. `zotero/citations.py` strips it; this now does the same."""
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8")
        + "\n\nA later cohort reached the same conclusion as @fictionalHepaticCohort2021.\n",
        encoding="utf-8",
    )
    titles = [item["title"] for item in only(produced(project), "claim")]
    assert any("reached the same conclusion" in title for title in titles), titles


def test_a_binding_written_with_spaces_is_found(project: Path) -> None:
    """`{{ lit.x }}` is a binding to the renderer, which prints its value. An exact-string search
    missed it, so that value reached a co-author with no sentence at all."""
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    assert "{{lit.background.class_ror}}" in text
    main.write_text(
        text.replace("{{lit.background.class_ror}}", "{{ lit.background.class_ror }}"),
        encoding="utf-8",
    )
    item = next(i for i in only(produced(project), "literature") if "class_ror" in i["title"])
    assert item["sentences"], "the sentence that uses it"


def test_a_commented_out_sentence_is_not_offered_as_a_claim(project: Path) -> None:
    """A sentence a draft has commented out is not a sentence of the paper, and a co-author asked
    to check one has been asked about nothing."""
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8")
        + "\n\n<!-- Dropped from this draft: the risk doubles in adults over 65 "
        "[@fictionalClassSignal2019]. -->\n",
        encoding="utf-8",
    )
    titles = [item["title"] for item in only(produced(project), "claim")]
    assert not any("Dropped from this draft" in title for title in titles), titles
    assert not any("risk doubles" in title for title in titles), titles


def test_a_ledger_entry_that_cannot_be_read_is_reported(project: Path) -> None:
    """One entry failing its schema takes every literature value out of the round, because the
    contract reads the file as a whole. It used to do that in silence: a page with two items
    instead of a hundred and thirty, and three ordinary lines of output."""
    from manuscript_guard.checking.produce import produce
    from manuscript_guard.cli import load_project

    ledger = project / "literature" / "ledger.yaml"
    text = ledger.read_text(encoding="utf-8")
    assert "depth: full-text" in text
    ledger.write_text(text.replace("depth: full-text", "", 1), encoding="utf-8")

    loaded, _ = load_project(project)
    document, unread = produce(loaded)
    assert unread, "the author is told the ledger could not be read"
    # Every value of that file is gone, because the contract reads it whole, while
    # `attested.yaml` is its own file and still loads.
    titles = [item["title"] for item in document["items"] if item["group"] == "literature"]
    assert not [title for title in titles if "lit.background" in title], titles


def test_the_page_stamps_an_answer_with_its_offset() -> None:
    """`toISOString()` wrote UTC with no zone, so an answer given at 09:00 in Japan was recorded
    at midnight, on the day before. No test runs this page's JavaScript; what is held here is
    that the call is gone and the local stamp is there."""
    from manuscript_guard.checking.bundle import TEMPLATE

    page = TEMPLATE.read_text(encoding="utf-8")
    assert "new Date().toISOString" not in page
    assert "function stamp()" in page and "getTimezoneOffset" in page
    assert "at: stamp()" in page and "saved_on: stamp()" in page


def test_the_page_takes_an_image_only_from_the_builders_own_map() -> None:
    """An `src` on a piece of evidence went into an `img` attribute unescaped, and a remote one
    would have made the page fetch when opened. Nothing in the toolkit writes that field."""
    from manuscript_guard.checking.bundle import TEMPLATE

    page = TEMPLATE.read_text(encoding="utf-8")
    assert "e.src" not in page
    assert '<img src="${esc(src)}"' in page


def test_an_evidence_block_may_not_carry_a_key_the_schema_does_not_know(tmp_path: Path) -> None:
    """An item already refused one; a block did not, so `src` — which the page read — was
    accepted without being declared anywhere, and `row_labels` misspelt was dropped in silence."""
    path = write_items(
        tmp_path,
        items=[
            {
                "id": "x", "group": "literature", "title": "t",
                "evidence": [{"kind": "image", "src": "https://example.invalid/p.png"}],
            }
        ],
    )
    with pytest.raises(ItemsError, match="does not fit the schema"):
        load_items(tmp_path, path)


def test_build_counts_what_has_been_checked_not_only_what_the_file_says(project: Path) -> None:
    """"0 already checked by someone" was printed after a whole round had come back and been
    imported, because this counted only the `already` field a project may write."""
    from manuscript_guard.checking.store import status as standing_of
    from manuscript_guard.cli import _checking_items, load_project

    loaded, _ = load_project(project)
    items = _checking_items(loaded, None)
    answers = project / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "schema": "manuscript-guard/checking-answers/1",
                "by": "Ada Example",
                "answers": [
                    {"id": item["id"], "digest": item["digest"], "status": "ok", "note": ""}
                    for item in items.items[:3]
                ],
            }
        ),
        encoding="utf-8",
    )
    import_answers(project, answers, items)
    assert len(standing_of(project, items).answered) == 3


def test_import_without_the_answers_file_says_so(project: Path) -> None:
    """A forgotten flag reached `Path.read_text` on `None` and gave an AttributeError."""
    from manuscript_guard.cli import main

    assert main(["checker", "import", str(project)]) == 2


def test_a_project_item_without_a_group_is_refused_by_the_schema(project: Path) -> None:
    """The merge reads each item's `id` and `group`, so an item written without one raised a
    KeyError from inside it — the ordinary authoring mistake the schema exists to report."""
    import json

    from manuscript_guard.checking.items import ItemsError
    from manuscript_guard.cli import _checking_items, load_project

    (project / "checks").mkdir(exist_ok=True)
    (project / "checks" / "items.json").write_text(
        json.dumps(
            {
                "schema": "manuscript-guard/checking/1",
                "groups": [{"id": "official", "title": "Tables", "ask": "Does it say this?"}],
                "items": [{"id": "official-1", "title": "a number with no group"}],
            }
        ),
        encoding="utf-8",
    )
    loaded, _ = load_project(project)
    with pytest.raises(ItemsError, match="does not fit the schema"):
        _checking_items(loaded, None)


def test_a_paragraph_that_is_only_a_citation_is_not_asked_about(project: Path) -> None:
    """Found by the generated property, on its first run. The splitter joins a piece with no
    word of its own to the piece before it, but a paragraph has nothing before it — so a
    paragraph that is nothing but a citation came through as a claim item whose whole content
    was that citation, and a co-author would have been asked whether a source supports it."""
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8") + "\n\n[@fictionalClassSignal2019]\n", encoding="utf-8"
    )
    for item in only(produced(project), "claim"):
        assert item["title"].strip() != "[@fictionalClassSignal2019]"
        assert any(character.isalpha() for character in item["title"].replace("@", " "))
