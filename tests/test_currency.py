"""Whether a cited work is still the one to cite: the rules, the hierarchy, the records and
the `references` command. The gate's failures are in tests/test_corruption.py; the rules'
properties, with rules broken on purpose, in tests/test_properties.py."""

from __future__ import annotations

from pathlib import Path

import currency_records as case
import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import ContractError, load_project
from manuscript_guard.currency import command, records, rules
from manuscript_guard.currency.hierarchy import BUILT_IN, hierarchies, level_problem
from manuscript_guard.currency.rules import Fields, Reading, Work, after, decide

SAME = Fields(level=1, population="same", exposure="same", outcome="same", stance="supports")


def _two(cited_level: int = 3, **candidates: Fields) -> list[Reading]:
    one = Reading("a", "ocebm-2011", "benefit", cited_level, candidates)
    return [one, Reading("b", "ocebm-2011", "benefit", cited_level, candidates)]


def _works(*ids: str, **changed) -> dict[str, Work]:
    return {work: Work(work, **changed) for work in ids}


# ------------------------------------------------------------------------------- the rules


def test_one_reading_decides_nothing() -> None:
    assert decide(Work("c"), _works("x"), _two(x=SAME)[:1]) is None
    # One reader's reading given twice is one reading (round 1 of #499).
    first = _two(x=SAME)[0]
    assert decide(Work("c"), _works("x"), [first, first]) is None
    assert decide(Work("c"), _works("x"), [first, Reading(**{**first.__dict__, "number": 2})]
                  ).action == "replace"  # fmt: skip


def test_a_candidate_off_the_question_read_at_two_levels_leaves_a_clear_replace() -> None:
    """Round 1 of #499: D4 compared every field of every candidate, and a candidate that is
    not the same question for either reader, read at two levels, made a clear `replace`
    `uncertain`. What decides each candidate is compared, and nothing else."""
    clear = Fields(level=1, population="same", exposure="same", outcome="same",
                   stance="supports")  # fmt: skip
    off = Fields(level=3, population="different", exposure="same", outcome="same",
                 stance="neither")  # fmt: skip
    readings = [Reading("a", "ocebm-2011", "benefit", 2, {"a": clear, "b": off}),
                Reading("b", "ocebm-2011", "benefit", 2,
                        {"a": clear, "b": Fields(**{**off.__dict__, "level": 4})})]
    decided = decide(Work("c"), _works("a", "b"), readings)
    assert (decided.action, decided.candidate) == ("replace", "a")
    # Weaker than the cited work, its search end date decides nothing either.
    weaker = Fields(**{**clear.__dict__, "level": 3, "search_end": "2024"})
    readings = [Reading("a", "ocebm-2011", "benefit", 2, {"a": clear, "w": weaker}),
                Reading("b", "ocebm-2011", "benefit", 2,
                        {"a": clear, "w": Fields(**{**weaker.__dict__, "search_end": None})})]
    assert decide(Work("c"), _works("a", "w"), readings).candidate == "a"


def test_a_weaker_candidate_read_at_two_weaker_levels_leaves_a_clear_replace() -> None:
    """Basile, 2026-11-05 (item 3 of round 2 of #499): only what can change the outcome is
    compared. x is agreed at level 1 against a cited level 2; y, weaker in both readings,
    is read at 4 and at 5, and once as `supports`, once as `neither`."""
    x = Fields(level=1, population="same", exposure="same", outcome="same", stance="supports")
    y = Fields(level=4, population="same", exposure="same", outcome="same", stance="supports")
    readings = [Reading("a", "ocebm-2011", "benefit", 2, {"x": x, "y": y}),
                Reading("b", "ocebm-2011", "benefit", 2,
                        {"x": x, "y": Fields(**{**y.__dict__, "level": 5,
                                                "stance": "neither"})})]  # fmt: skip
    decided = decide(Work("c"), _works("x", "y"), readings)
    assert (decided.action, decided.candidate) == ("replace", "x")
    # Two search ends on the same side of the publication decide nothing either.
    at = Fields(level=2, population="same", exposure="same", outcome="same",
                stance="supports", search_end="2021")  # fmt: skip
    readings = [Reading("a", "ocebm-2011", "benefit", 2, {"x": x, "d": at}),
                Reading("b", "ocebm-2011", "benefit", 2,
                        {"x": x, "d": Fields(**{**at.__dict__, "search_end": "2023-04"})})]
    assert decide(Work("c", published="2020"), _works("x", "d"), readings).candidate == "x"


def test_a_candidate_one_reading_names_and_the_other_does_not_is_uncertain() -> None:
    first, _second = _two(x=SAME)
    alone = Reading("b", "ocebm-2011", "benefit", 3, {})
    decided = decide(Work("c"), _works("x"), [first, alone])
    assert (decided.action, decided.rules) == ("uncertain", ("D4",))


def test_a_stronger_candidate_on_the_same_question_replaces_the_citation() -> None:
    decided = decide(Work("c"), _works("x"), _two(x=SAME))
    assert (decided.action, decided.candidate, decided.rules) == (
        "replace", "x", ("K1", "K2", "K3", "D1"))


def test_at_the_same_level_a_search_that_ended_after_the_cited_work_replaces_it() -> None:
    late = Fields(**{**SAME.__dict__, "level": 3, "search_end": "2021-02"})
    decided = decide(Work("c", published="2020"), _works("x"), _two(x=late))
    assert (decided.action, decided.rules) == ("replace", ("K1", "K2", "K3", "K4", "D1"))
    # Equal at the precision both have is not after.
    same_year = Fields(**{**late.__dict__, "search_end": "2020-11-30"})
    assert decide(Work("c", published="2020"), _works("x"), _two(x=same_year)).action == "keep"


@pytest.mark.parametrize(
    ("later", "earlier", "is_after"),
    [("2021", "2020-12-31", True), ("2020-05", "2020", False), ("2020", "2020-05", False),
     ("2020-06-02", "2020-06-01", True), ("2020-06", "2020-07-01", False),
     (None, "2020", False), ("2020", None, False)],
)  # fmt: skip
def test_dates_are_compared_at_the_finest_precision_both_have(later, earlier, is_after) -> None:
    assert after(later, earlier) is is_after


def test_a_candidate_against_the_sentence_is_added_and_never_replaces() -> None:
    against = Fields(**{**SAME.__dict__, "stance": "contradicts"})
    supporting = Fields(**{**SAME.__dict__, "level": 2})
    decided = decide(Work("c"), _works("x", "y"), _two(x=against, y=supporting))
    assert (decided.action, decided.candidate, decided.rules[-1]) == ("add", "x", "D2")
    weaker = Fields(**{**against.__dict__, "level": 4})
    assert decide(Work("c"), _works("x"), _two(x=weaker)).action == "keep"


@pytest.mark.parametrize("changed", [{"retracted": True}, {"withdrawn": True},
                                     {"under_concern": True}, {"published_as": ("doi:10.1/v",)}])
def test_a_candidate_that_fails_k1_is_never_proposed(changed: dict) -> None:
    decided = decide(Work("c"), _works("x", **changed), _two(x=SAME))
    assert (decided.action, decided.candidate) == ("keep", None)
    assert decide(Work("c"), {}, _two(x=SAME)).action == "keep"  # no works record


def test_two_readings_that_disagree_on_a_field_the_rules_use_are_uncertain() -> None:
    first, second = _two(x=SAME)
    other = Reading("b", "ocebm-2011", "benefit", 3,
                    {"x": Fields(**{**SAME.__dict__, "outcome": "unclear"})})  # fmt: skip
    decided = decide(Work("c"), _works("x"), [first, other])
    assert (decided.action, decided.candidate, decided.rules) == ("uncertain", None, ("D4",))
    assert "what decides x" in decided.why
    # A disagreement on a candidate K1 puts out is no disagreement on what the rules use.
    assert decide(Work("c"), _works("x", retracted=True), [first, other]).action == "keep"
    assert decide(Work("c"), _works("x"), [first, second]).action == "replace"


def test_a_synthesis_never_replaces_the_source_of_a_number() -> None:
    works = {"r": Work("r", published="2023", types=("Systematic Review",)),
             "t": Work("t", published="2021", types=("Randomized Controlled Trial",))}
    readings = _two(x=SAME)
    readings = [Reading(one.reader, one.hierarchy, one.scale, 3, {"r": SAME, "t": SAME})
                for one in readings]  # fmt: skip
    decided = decide(Work("c"), works, readings)
    # The more recent, and K4 chose it; K5 is not recorded where no number is given.
    assert (decided.candidate, decided.rules) == ("r", ("K1", "K2", "K3", "K4", "D1"))
    decided = decide(Work("c"), works, readings, number=True)
    assert (decided.candidate, decided.rules) == ("t", ("K1", "K2", "K3", "K5", "D1"))
    # Basile, 2026-11-04, "primary only": a synthesis alone, however strong, is set aside.
    alone = [Reading(one.reader, one.hierarchy, one.scale, 3, {"r": SAME}) for one in readings]
    decided = decide(Work("c"), works, alone, number=True)
    assert (decided.action, decided.rules) == ("keep", ("K1", "K2", "K3", "K5", "D3"))
    assert decide(Work("c"), works, alone).rules == ("K1", "K2", "K3", "D1")
    # A synthesis against the sentence is still added.
    against = Fields(**{**SAME.__dict__, "stance": "contradicts"})
    alone = [Reading(one.reader, one.hierarchy, one.scale, 3, {"r": against})
             for one in readings]  # fmt: skip
    decided = decide(Work("c"), works, alone, number=True)
    assert (decided.action, decided.candidate, decided.rules) == (
        "add", "r", ("K1", "K2", "K3", "D2"))


def test_the_reviewers_example_a_review_does_not_replace_the_cohort_a_number_is_from() -> None:
    """Item 6 of round 1 of #499, as Basile decided it: "The incidence was 12% [@cohort]",
    the cohort's value in the ledger, cited at level 3, and a review at level 1 that is the
    same question and supports the sentence: nothing replaces the cohort."""
    from types import SimpleNamespace

    from manuscript_guard.contracts.values import Value
    from manuscript_guard.gates.currency import quotes_a_number

    sentence = "The incidence was 12% [@cohort]."
    ledger = SimpleNamespace(values={"incidence": Value(
        key="incidence", value=12, display="12%", origin="literature",
        detail={"citekey": "cohort"})})  # fmt: skip
    assert quotes_a_number(sentence, "cohort", ledger)
    assert quotes_a_number("Incidence was {{lit.incidence}} [@cohort].", "cohort", ledger)
    # A year, another digit, another work's value: none quotes the cohort's number.
    for other in ("In 2012 the incidence rose [@cohort].", "Of 120 cases [@cohort].",
                  "The incidence was 12.5% [@cohort]."):
        assert not quotes_a_number(other, "cohort", ledger), other
    assert not quotes_a_number(sentence, "another", ledger)
    review = Fields(level=1, population="same", exposure="same", outcome="same",
                    stance="supports")  # fmt: skip
    readings = [Reading(reader, "ocebm-2011", "frequency", 3, {"r": review})
                for reader in ("a", "b")]  # fmt: skip
    works = {"r": Work("r", published="2024", types=("Systematic Review",))}
    decided = decide(Work("cohort", published="2019"), works, readings,
                     number=quotes_a_number(sentence, "cohort", ledger))  # fmt: skip
    assert (decided.action, decided.candidate) == ("keep", None)
    assert "K5" in decided.rules


def _cohort_ledger(display: str):
    """A literature ledger holding one value of the work `cohort`, displayed `display`."""
    from types import SimpleNamespace

    from manuscript_guard.contracts.values import Value

    return SimpleNamespace(values={"incidence": Value(
        key="incidence", value=float(display.rstrip("%")), display=display,
        origin="literature", detail={"citekey": "cohort"})})  # fmt: skip


def test_k5_knows_a_synthesis_by_its_types_and_a_number_by_the_ledgers_display() -> None:
    """A known gap (DESIGN.md, Known gaps, "K5 knows a synthesis by its PubMed publication
    types"): K5 sets aside a candidate its works record types a review, a systematic review
    or a meta-analysis; one whose types are not known is read as a primary study, and
    replaces the source of a number. The number is known only as the ledger's display of it:
    the same value written otherwise in the sentence is not it."""
    from manuscript_guard.gates.currency import quotes_a_number

    readings = [Reading(reader, "ocebm-2011", "benefit", 3, {"r": SAME}) for reader in "ab"]
    for kind in ("Review", "Systematic Review", "Meta-Analysis"):
        works = {"r": Work("r", published="2023", types=(kind,))}
        decided = decide(Work("c"), works, readings, number=True)
        assert (decided.action, decided.rules) == ("keep", ("K1", "K2", "K3", "K5", "D3")), kind
    # The other side of K5: a works record that gives no types is a primary study's.
    untyped = records.as_work(case.work("doi:10.5555/r", published="2023"))
    assert untyped.types == ()
    decided = decide(Work("c"), {"doi:10.5555/r": untyped},
                     [Reading(one.reader, one.hierarchy, one.scale, 3, {"doi:10.5555/r": SAME})
                      for one in readings], number=True)  # fmt: skip
    assert (decided.action, decided.candidate, decided.rules) == (
        "replace", "doi:10.5555/r", ("K1", "K2", "K3", "D1"))
    ledger = _cohort_ledger("12%")
    assert quotes_a_number("The incidence was 12% [@cohort].", "cohort", ledger)
    for other in ("The incidence was 12 percent [@cohort].",
                  "The incidence was twelve per cent [@cohort].",
                  "The incidence was 0.12 [@cohort]."):  # fmt: skip
        assert not quotes_a_number(other, "cohort", ledger), other


def test_a_bare_whole_number_in_the_ledger_is_found_in_any_equal_number_of_the_sentence(
) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "A ledger display that is a bare whole number"):
    a display "12" is found in "in 12 countries [@cited]", which quotes no value of the
    cited work, and K5 then sets a synthesis aside there."""
    from manuscript_guard.gates.currency import quotes_a_number

    ledger = _cohort_ledger("12")
    sentence = "The class was studied in 12 countries [@cohort]."
    assert quotes_a_number(sentence, "cohort", ledger)
    # The other side: another number, or the same digits in a longer one, is not the display.
    for other in ("The class was studied in 13 countries [@cohort].",
                  "The class was studied in 112 countries [@cohort].",
                  "The class was studied in 12.5% of countries [@cohort]."):  # fmt: skip
        assert not quotes_a_number(other, "cohort", ledger), other
    review = Fields(level=1, population="same", exposure="same", outcome="same",
                    stance="supports")  # fmt: skip
    readings = [Reading(reader, "ocebm-2011", "benefit", 3, {"r": review}) for reader in "ab"]
    works = {"r": Work("r", published="2024", types=("Systematic Review",))}
    decided = decide(Work("cohort", published="2019"), works, readings,
                     number=quotes_a_number(sentence, "cohort", ledger))  # fmt: skip
    assert (decided.action, decided.rules) == ("keep", ("K1", "K2", "K3", "K5", "D3"))
    decided = decide(Work("cohort", published="2019"), works, readings,
                     number=quotes_a_number("In 13 countries [@cohort].", "cohort",
                                            ledger))  # fmt: skip
    assert (decided.action, decided.candidate) == ("replace", "r")


# --------------------------------------------------------------------------- the hierarchy


def test_the_built_in_hierarchy_has_seven_scales_and_cebms_citation() -> None:
    found = hierarchies()
    oxford = found["ocebm-2011"]
    assert set(oxford.scales) == {"frequency", "diagnosis", "prognosis", "benefit",
                                  "harms-common", "harms-rare", "screening"}  # fmt: skip
    # The table gives how often a condition occurs and prognosis no fifth level.
    assert {scale: sorted(levels) for scale, levels in oxford.scales.items()} == {
        scale: [1, 2, 3, 4] if scale in ("frequency", "prognosis") else [1, 2, 3, 4, 5]
        for scale in oxford.scales}
    assert "no level 5" in level_problem(found, "ocebm-2011", "prognosis", [5])
    assert "none of the above" not in BUILT_IN.read_text(encoding="utf-8")
    assert oxford.citation.startswith('OCEBM Levels of Evidence Working Group. "The Oxford')
    text = BUILT_IN.read_text(encoding="utf-8")
    assert "Introductory Document" in text and "20%" in text
    assert "Explanation of the 2011 OCEBM Levels of Evidence" in text
    assert level_problem(found, "ocebm-2011", "benefit", [1, 5]) is None
    assert "no level 6" in level_problem(found, "ocebm-2011", "benefit", [6])
    assert "no scale" in level_problem(found, "ocebm-2011", "harms", [1])


def test_a_project_may_declare_its_own_hierarchy(project: Path) -> None:
    (project / "design").mkdir(exist_ok=True)
    (project / "design" / "levels.yaml").write_text(
        "schema: manuscript-guard/evidence-hierarchy/1\nhierarchies:\n  ours:\n    name: Ours\n"
        "    scales:\n      method:\n        question: which method\n        levels:\n"
        "          1: a validation study\n          2: a description\n", encoding="utf-8")
    with (project / "paper.yaml").open("a", encoding="utf-8") as paper:
        paper.write("references:\n  hierarchy: design/levels.yaml\n")
    found = hierarchies(load_project(project)[0])
    assert list(found) == ["ours"] and found["ours"].scales == {
        "method": {1: "a validation study", 2: "a description"}}
    (project / "design" / "levels.yaml").write_text("schema: wrong\n", encoding="utf-8")
    with pytest.raises(ContractError, match="not a hierarchy of evidence"):
        hierarchies(load_project(project)[0])


# ----------------------------------------------------------------------------- the records


def test_a_works_record_is_sealed_and_its_store_kept_out_of_git(project: Path) -> None:
    loaded = load_project(project)[0]
    path = records.write_work(loaded, case.work(case.CANDIDATE, abstract="Words."))
    assert path.name == "doi%3a10%2e5555%2fclass%2etrial%2e2023.yaml"
    ignore = path.parent / ".gitignore"
    assert ignore.read_text(encoding="utf-8").splitlines()[-2:] == ["*", "!.gitignore"]
    assert records.read_work(loaded, case.CANDIDATE).problem is None
    path.write_text(path.read_text(encoding="utf-8").replace("Words.", "Other words."),
                    encoding="utf-8")  # fmt: skip
    edited = records.read_work(loaded, case.CANDIDATE)
    assert edited.edited and "answers_sha256" in edited.problem


def test_a_reading_is_numbered_filed_once_and_sealed(project: Path) -> None:
    loaded = load_project(project)[0]
    first = records.file_reading(loaded, case.reading("Ada Example"), "2026-11-04")
    second = records.file_reading(loaded, case.reading("Ada Example"), "2026-11-04")
    assert (first.name, second.name) == ("c1.Ada%20Example.1.yaml", "c1.Ada%20Example.2.yaml")
    filed = yaml.safe_load(second.read_text(encoding="utf-8"))
    assert filed["number"] == 2 and filed["reading_sha256"] == records.sealed_digest(
        filed, "reading_sha256")
    with pytest.raises(FileExistsError):
        records._write_new(first, "again")
    assert [read.problem for read in records.read_readings(loaded)] == [None, None]
    # Round 1 of #499: neither a bad entry id nor a reading its schema refuses is filed.
    with pytest.raises(ContractError, match="not the id of an entry"):
        records.file_reading(loaded, {**case.reading("Ada Example"), "entry": "../x"},
                             "2026-11-04")  # fmt: skip
    with pytest.raises(ContractError, match="the reading is not valid"):
        records.file_reading(loaded, {**case.reading("Ada Example"), "scale": ""},
                             "2026-11-04")  # fmt: skip
    assert len(list(first.parent.glob("*.yaml"))) == 2


@pytest.mark.parametrize(
    "copy", ["c1.Ada%20Example.2.yaml", "c1.Bob.1.yaml", "c2.Ada%20Example.1.yaml"]
)
def test_a_reading_copied_under_another_name_is_edited_and_counts_once(
    project: Path, copy: str
) -> None:
    """Round 1 of #499: a reading copied under another reader's name, or as its reader's
    second, kept its seal, and the rules decided from one reading."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    said = case.file(project, case.reading("Ada Example"), "first")
    assert "the rules decide from 2 readings" in said
    folder = project / "literature" / "currency" / "readings"
    (folder / copy).write_bytes((folder / "c1.Ada%20Example.1.yaml").read_bytes())
    loaded = load_project(project)[0]
    assert [(read.path.name, read.edited) for read in records.read_readings(loaded)] == sorted(
        [("c1.Ada%20Example.1.yaml", False), (copy, True)])
    codes = sorted(f.code for f in check_currency(loaded).findings)
    # Read once, so not decided: the copy is no second reading.
    assert codes == ["currency-record-edited", "currency-record-missing"]
    assert case.decision(project) is None


def test_a_search_record_is_sealed(project: Path) -> None:
    loaded = load_project(project)[0]
    path = records.write_search(loaded, {
        "entry": "c1", "number": 1, "step": "S2", "source": "pubmed", "query": "x AND y",
        "searched_on": "2026-11-01", "hits": 0, "candidates": []})  # fmt: skip
    assert [read.problem for read in records.read_searches(loaded)] == [None]
    path.write_text(path.read_text(encoding="utf-8").replace("hits: 0", "hits: 3"),
                    encoding="utf-8")  # fmt: skip
    assert records.read_searches(loaded)[0].edited


def test_entries_that_would_not_be_valid_are_never_written(project: Path) -> None:
    with pytest.raises(ContractError, match="would not be valid"):
        records.write_document(load_project(project)[0], {
            "schema": records.SCHEMA, "entries": [{"id": "c1", "sentence": "x", "citekey": "k",
                                                   "decision": {"action": "replace"}}]})
    assert not (project / "literature" / "currency.yaml").exists()


def test_references_writes_currency_yaml_whole_and_a_comment_in_it_is_lost(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "`references` writes `literature/currency.yaml`
    whole"): a comment a person wrote in the file is not kept when the command writes it."""
    path = case.case(project, readings=False)
    note = "# Ada: the Discussion's sentence is to be marked too.\n"
    path.write_text(path.read_text(encoding="utf-8") + note, encoding="utf-8")
    assert note in path.read_text(encoding="utf-8")
    assert [entry.id for entry in records.read_entries(load_project(project)[0])[0]] == ["c1"]
    command.mark(load_project(project)[0], "reported previously", case.CITED_KEY, None)
    text = path.read_text(encoding="utf-8")
    assert note.strip() not in text and text.startswith(records.HEADER)
    assert [entry.id for entry in records.read_entries(load_project(project)[0])[0]] == [
        "c1", "c2"]


# ----------------------------------------------------------------------------- the command


def test_marking_takes_exactly_one_sentence(project: Path) -> None:
    case.given_a_doi(project)
    loaded = load_project(project)[0]
    with pytest.raises(command.Refused, match="0 sentences"):
        command.mark(loaded, "words no sentence has", "@" + case.CITED_KEY, None)
    # The work is cited in the Introduction and in the Discussion.
    with pytest.raises(command.Refused, match="2 sentences"):
        command.mark(loaded, "ROR", case.CITED_KEY, None)
    assert command.mark(loaded, case.MARKED, case.CITED_KEY, None).startswith("marked as c1")
    with pytest.raises(command.Refused, match="marked already, as c1"):
        command.mark(load_project(project)[0], case.MARKED, case.CITED_KEY, None)
    assert (project / "literature" / "currency" / "works" / ".gitignore").is_file()


def test_an_entry_reworded_a_little_stays_placed_and_one_unplaced_is_put_back(
    project: Path,
) -> None:
    case.case(project, readings=False)
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8")
    main_md.write_text(text.replace("has been reported", "was reported", 1), encoding="utf-8")
    rows, unplaced = command.listing(load_project(project)[0])
    assert [row.id for row in rows] == ["c1"] and unplaced == []
    main_md.write_text(text.replace("[@fictionalClassSignal2019]. The", "The", 1)
                       .replace("reported previously [@fictionalClassSignal2019]",
                                "reported previously [@fictionalClassSignal2019] for the "
                                "drug class as a whole in a national cohort"),
                       encoding="utf-8")  # fmt: skip
    rows, unplaced = command.listing(load_project(project)[0])
    assert rows == [] and [entry.id for entry in unplaced] == ["c1"]
    said = command.mark(load_project(project)[0], "reported previously", case.CITED_KEY, None,
                        "c1")  # fmt: skip
    assert said.startswith("c1 placed again")
    assert [row.id for row in command.listing(load_project(project)[0])[0]] == ["c1"]


def test_an_entry_is_placed_while_half_its_words_stand_and_mark_reads_them_as_one_run(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "An entry is placed on a sentence reworded beyond
    its words"): an entry stays on a sentence citing its work that holds half or more of its
    words (`NEAR`), one that now says the opposite too, and is unplaced below half. `--mark`
    finds its sentence by its words folded and taken as one run, and refuses words that two
    sentences citing the work hold."""
    from manuscript_guard.checking.produce import CitedSentence
    from manuscript_guard.currency.survey import place
    from manuscript_guard.literature.passages import NEAR, statement_words

    assert NEAR == 0.5
    entry = "Statins raised the risk of hepatic injury in older adults [@k]."
    assert len(set(statement_words(entry).split())) == 10

    def placed(text: str, keys: tuple[str, ...] = ("k",)) -> bool:
        cited = [CitedSentence(project / "m.md", 1, text, keys)]
        return place(entry, "k", cited, [statement_words(text)]) is not None

    assert placed("Statins raised the risk of falls among frail young children [@k].")  # 5
    assert not placed("Statins raised the odds of falls among frail young children [@k].")
    assert placed("Statins did not raise the risk of hepatic injury in older adults [@k].")
    assert not placed("Statins raised the risk of hepatic injury in older adults [@j].", ("j",))
    case.given_a_doi(project)
    loaded = load_project(project)[0]
    # The words must stand as one run in the sentence: these are its words, out of their run.
    with pytest.raises(command.Refused, match="0 sentences"):
        command.mark(loaded, "disproportionality signal reported", case.CITED_KEY, None)
    # "reported" is in the Introduction's sentence and the Discussion's, which both cite it.
    with pytest.raises(command.Refused, match="2 sentences citing @fictionalClassSignal2019 "
                       "hold those words"):  # fmt: skip
        command.mark(loaded, "reported", case.CITED_KEY, None)
    said = command.mark(loaded, "A DISPROPORTIONALITY  Signal has been reported",
                        case.CITED_KEY, None)  # fmt: skip
    assert said == "marked as c1: manuscript/main.md:19"


def test_a_claim_in_the_supplement_is_marked_and_held_as_one_in_the_main_text(
    project: Path,
) -> None:
    """Basile, 2026-10-21: the supplement is read with the same rules."""
    from manuscript_guard.gates.currency import check_currency

    case.given_a_doi(project)
    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    with supplement.open("a", encoding="utf-8") as text:
        text.write("\nThe code lists follow a class review [@fictionalClassSignal2019].\n")
    loaded = load_project(project)[0]
    said = command.mark(loaded, "follow a class review", case.CITED_KEY, None)
    assert said == "marked as c1: manuscript/supplementary/S1_code_lists.md:" + said.rsplit(
        ":", 1)[1]
    rows, unplaced = command.listing(load_project(project)[0])
    assert [(row.id, row.where.split(":")[0]) for row in rows] == [
        ("c1", "manuscript/supplementary/S1_code_lists.md")] and unplaced == []
    found = check_currency(load_project(project)[0], "internal-review").findings
    assert [(f.code, f.path.name) for f in found] == [
        ("currency-record-missing", "S1_code_lists.md")]


def test_no_decision_is_written_while_a_work_a_reading_names_has_no_record(
    project: Path,
) -> None:
    """Round 1 of #499: a candidate with no works record fails K1, so two readings wrote
    `keep` from an empty store and the claim stopped being missing."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    (project / "literature" / "currency" / "works" / (
        records.safe_name(case.CANDIDATE) + ".yaml")).unlink()
    case.file(project, case.reading("Ada Example"), "first")
    said = case.file(project, case.reading("Bo Example"), "second")
    assert f"the works store holds no record of {case.CANDIDATE}" in said
    assert case.decision(project) is None
    found = {f.code: f for f in check_currency(load_project(project)[0],
                                                "internal-review").findings}
    assert sorted(found) == ["currency-quote-unchecked", "currency-record-missing"]
    assert "read 2 time(s)" in found["currency-record-missing"].message
    assert f"no record of {case.CANDIDATE}" in found["currency-quote-unchecked"].message


def test_a_doi_in_capitals_is_one_work_with_its_lower_case(project: Path) -> None:
    case.case(project, readings=False)
    upper = case.reading("Ada Example")
    upper["candidates"][0]["work"] = case.CANDIDATE.upper().replace("DOI:", "doi:")
    case.file(project, upper, "first")
    case.file(project, case.reading("Bo Example"), "second")
    assert case.decision(project)["candidate"] == case.CANDIDATE


def test_filing_two_readings_writes_the_rules_decision(project: Path) -> None:
    case.case(project, readings=False)
    said = case.file(project, case.reading("Ada Example"), "first")
    assert "the rules decide from 2 readings" in said and case.decision(project) is None
    said = case.file(project, case.reading("Bo Example"), "second")
    assert "the rules give replace doi:10.5555/class.trial.2023" in said
    assert case.decision(project) == {
        "action": "replace", "candidate": case.CANDIDATE,
        "rules": ["K1", "K2", "K3", "D1"], "by": "rules",
        "decided_on": case.decision(project)["decided_on"]}  # fmt: skip


@pytest.mark.parametrize(
    ("changed", "refused"),
    [({"scale": "harms"}, "no scale 'harms'"),
     ({"cited": {"work": "doi:10.5555/other", "level": {"value": 4, "quote": "x"}}},
      "is doi:10.5555/class.signal.2019"),
     ({"entry": "c9"}, "no entry c9"),
     ({"reader": ""}, "does not match")],
)  # fmt: skip
def test_a_reading_that_does_not_fit_is_refused_and_nothing_filed(
    project: Path, changed: dict, refused: str
) -> None:
    case.case(project, readings=False)
    with pytest.raises(command.Refused, match=refused):
        case.file(project, {**case.reading("Ada Example"), **changed}, "bad")
    assert not (project / "literature" / "currency" / "readings").exists()


def _cut(reading: dict) -> dict:
    """The reading with its stance quoted from inside the hyphen-joined "Follow-up": the
    words are the abstract's, and G7 refuses the quote, which does not start at a word's
    edge."""
    reading["candidates"][0]["stance"]["quote"] = "up ended in March 2023"
    return reading


def test_a_reading_whose_quote_the_gate_refuses_is_not_filed(project: Path, capsys) -> None:
    """Found taking a real paper through the loop: `--reading` filed a reading whose quote
    started inside a hyphen-joined word, and G7 then failed on it. It is refused when filed,
    each quote named, with the rule."""
    case.case(project, readings=False)
    with pytest.raises(command.Refused) as refused:
        case.file(project, _cut(case.reading("Ada Example")), "first")
    said = str(refused.value)
    assert "stance of doi:10.5555/class.trial.2023: 'up ended in March 2023'" in said
    assert "starts and ends at a word's edge" in said and "hyphen-joined word whole" in said
    assert not (project / "literature" / "currency" / "readings").exists()
    path = project / "first.yaml"
    assert main(["references", str(project), "--reading", str(path)]) == 2
    assert "'up ended in March 2023'" in capsys.readouterr().err
    # A quote of a work the store holds nothing of cannot be looked for, and is filed: G7
    # says it is unchecked.
    for stored in (project / "literature" / "currency" / "works").glob("*trial*"):
        stored.unlink()
    assert "filed" in case.file(project, _cut(case.reading("Ada Example")), "first")


def test_a_corrected_reading_replaces_the_one_it_corrects(project: Path, capsys) -> None:
    """Found taking a real paper through the loop: a reading G7 refused a quote of could not
    be cleared, since a reader's further reading is read beside the earlier one. One filed
    with `--replaces N` is read in place of the reader's reading N, by the gate and by the
    rules; one filed without it is a further reading, as before."""
    from manuscript_guard.gates.currency import _Records, check_currency

    case.case(project, readings=False)
    loaded = load_project(project)[0]
    # Filed before `--reading` looked at the quotes, as the paper's was.
    records.file_reading(loaded, _cut(case.reading("Ada Example")), "2026-11-04")
    codes = [f.code for f in check_currency(load_project(project)[0]).findings]
    assert "currency-quote-not-found" in codes
    path = project / "again.yaml"
    path.write_text(yaml.safe_dump(case.reading("Ada Example"), sort_keys=False), "utf-8")
    assert main(["references", str(project), "--reading", str(path), "--replaces", "2"]) == 2
    assert "Ada Example has no reading 2 of c1" in capsys.readouterr().err
    assert main(["references", str(project), "--replaces", "1"]) == 2
    assert "--replaces goes with --reading" in capsys.readouterr().err
    said = command.file_reading(load_project(project)[0], path, replaces=1)
    assert "readings/c1.Ada%20Example.2.yaml" in said and "decide from 2 readings" in said
    filed = yaml.safe_load(next((project / "literature" / "currency" / "readings").glob(
        "c1.Ada%20Example.2.yaml")).read_text(encoding="utf-8"))  # fmt: skip
    assert filed["replaces"] == 1
    loaded = load_project(project)[0]
    codes = [f.code for f in check_currency(loaded).findings]
    assert "currency-quote-not-found" not in codes, codes
    # The two are one reading: the rules decide nothing from them.
    assert case.decision(project) is None
    assert "read 1 of 2" in command.state_of(records.read_entries(loaded)[0][0],
                                              _Records(loaded))
    with pytest.raises(command.Refused, match="reading 1 of c1 is replaced already"):
        command.file_reading(loaded, path, replaces=1)
    # A further reading by the same reader, without --replaces, counts as one more.
    said = case.file(project, case.reading("Ada Example"), "third")
    assert "the rules give replace" in said


@pytest.mark.parametrize("broken", ["schema: nothing\n", "entry: [c1\n"], ids=["schema", "yaml"])
def test_replaces_names_a_reading_that_cannot_be_read_replaced_already(
    project: Path, broken: str
) -> None:
    """A known gap (DESIGN.md, Known gaps, "`--replaces N`, where N cannot be used"): a
    reading N whose file fails its schema or its YAML is not among those `_check_replaces`
    looks at, and `--replaces N` is refused as replacing a reading "replaced already". The
    2026-11-09 triage planned a fix (F15), which will change this test."""
    case.case(project, readings=False)
    case.file(project, case.reading("Ada Example"), "first")
    folder = project / "literature" / "currency" / "readings"
    path = project / "again.yaml"
    path.write_text(yaml.safe_dump(case.reading("Ada Example"), sort_keys=False), "utf-8")
    # The other side: while reading 1 reads, --replaces 1 is filed, as reading 2.
    said = command.file_reading(load_project(project)[0], path, replaces=1)
    assert said.startswith("filed literature/currency/readings/c1.Ada%20Example.2.yaml; ")
    (folder / "c1.Ada%20Example.2.yaml").unlink()
    (folder / "c1.Ada%20Example.1.yaml").write_text(broken, encoding="utf-8")
    with pytest.raises(command.Refused, match="Ada Example's reading 1 of c1 is replaced "
                       "already: replace the reading that replaced it"):  # fmt: skip
        command.file_reading(load_project(project)[0], path, replaces=1)
    assert sorted(one.name for one in folder.glob("*.yaml")) == ["c1.Ada%20Example.1.yaml"]


def test_replaces_takes_an_edited_reading_silently_and_g7_still_fails_it(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "`--replaces N`, where N cannot be used"): an
    edited reading N, its seal broken, is replaced without a word, and `records.current`
    never sets it aside, so G7 still fails `currency-record-edited` on it. The next reading's
    number is the first one free: with readings 1 and 3, 2 deleted, a new reading is filed as
    2, and `--replaces 3` is refused as replacing no earlier reading. The 2026-11-09 triage
    planned a fix (F15), which will change this test."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    case.file(project, case.reading("Ada Example"), "first")
    folder = project / "literature" / "currency" / "readings"
    first = folder / "c1.Ada%20Example.1.yaml"
    first.write_text(first.read_text(encoding="utf-8").replace("2026-11-02", "2026-11-03", 1),
                     encoding="utf-8")  # fmt: skip
    path = project / "again.yaml"
    path.write_text(yaml.safe_dump(case.reading("Ada Example"), sort_keys=False), "utf-8")
    said = command.file_reading(load_project(project)[0], path, replaces=1)
    assert said.startswith("filed literature/currency/readings/c1.Ada%20Example.2.yaml; ")
    edited = [f.path.name for f in check_currency(load_project(project)[0]).findings
              if f.code == "currency-record-edited"]  # fmt: skip
    assert edited == ["c1.Ada%20Example.1.yaml"]
    # Readings 1 and 3 by Ada, 2 deleted by hand.
    first.unlink()
    case.file(project, case.reading("Ada Example"), "again")
    case.file(project, case.reading("Ada Example"), "third")
    assert sorted(one.name for one in folder.glob("*.yaml")) == [
        "c1.Ada%20Example.1.yaml", "c1.Ada%20Example.2.yaml", "c1.Ada%20Example.3.yaml"]
    (folder / "c1.Ada%20Example.2.yaml").unlink()
    with pytest.raises(command.Refused, match="Ada Example has no reading 3 of c1 to replace"):
        command.file_reading(load_project(project)[0], path, replaces=3)
    assert case.file(project, case.reading("Ada Example"), "again").startswith(
        "filed literature/currency/readings/c1.Ada%20Example.2.yaml")


def test_the_cited_work_under_its_other_identifier_is_no_candidate(project: Path) -> None:
    """Round 3 of #499: the cited work, filed as `doi:...`, was refused as a candidate only
    under that id, and under its PMID it was a candidate of its own."""
    bib = project / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    old = "  pages   = {45--52},\n"
    assert old in text
    bib.write_text(text.replace(old, old + "  pmid    = {31000099},\n", 1), encoding="utf-8")
    with pytest.raises(command.Refused, match="the cited work is not a candidate"):
        case.case(project, candidate="pmid:31000099")
    assert not (project / "literature" / "currency" / "readings").exists()


def test_a_reading_that_would_change_an_answered_proposal_is_refused(project: Path) -> None:
    case.case(project)
    loaded = load_project(project)[0]
    assert command.refuse(loaded, "c1", "the review pools another population",
                          "Ada Example").endswith("refused by Ada Example")  # fmt: skip
    with pytest.raises(command.Refused, match="takes their answer away first"):
        case.file(project, case.reading("Cy Example", level=2, stance="contradicts"), "third")
    assert len(list((project / "literature" / "currency" / "readings").glob("*.yaml"))) == 2
    # A reading that leaves the proposal as it was is filed, and the answer stands.
    case.file(project, case.reading("Cy Example"), "third")
    entry = yaml.safe_load((project / "literature" / "currency.yaml").read_text("utf-8"))
    assert entry["entries"][0]["answer"]["by"] == "Ada Example"


def test_a_ledger_value_recorded_after_the_rules_decided_turns_their_replace_into_a_mismatch(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A value recorded in the literature ledger from
    the cited work after the rules decided"): the rules replace the cited work with a
    synthesis while the ledger records no value of it; once it does, and the sentence quotes
    that value, K5 sets the synthesis aside and G7 fails `currency-decision-mismatch`.
    Nothing decides again from the readings filed, and a further reading is refused once the
    proposal is answered; with the answer taken away, it is filed and decides again."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    records.write_work(load_project(project)[0], case.work(
        case.CANDIDATE, title="Hepatic injury with the drug class: a review",
        published="2023-06-01", publication_types=["Systematic Review"],
        abstract=case.TRIAL_ABSTRACT))  # fmt: skip
    ledger = project / "literature" / "ledger.yaml"
    kept = ledger.read_bytes()
    text = kept.decode("utf-8")
    value = text[text.index("  - key: background.class_ror"):]
    ledger.write_bytes(text.replace(value, "").encode("utf-8"))
    case.file(project, case.reading("Ada Example"), "first")
    case.file(project, case.reading("Bo Example"), "second")
    decided = case.decision(project)
    assert (decided["action"], decided["rules"]) == ("replace", ["K1", "K2", "K3", "D1"])
    codes = sorted(f.code for f in check_currency(load_project(project)[0]).findings)
    assert codes == ["currency-change-unanswered"]
    ledger.write_bytes(kept)  # the value of the cited work its sentence quotes, recorded
    found = {f.code: f.message for f in check_currency(load_project(project)[0]).findings}
    assert sorted(found) == ["currency-change-unanswered", "currency-decision-mismatch"]
    assert "the rules give keep (K1, K2, K3, K5, D3)" in found["currency-decision-mismatch"]
    command.listing(load_project(project)[0])
    assert case.decision(project) == decided
    command.refuse(load_project(project)[0], "c1", "the review pools another population",
                   "Ada Example")  # fmt: skip
    with pytest.raises(command.Refused, match="takes their answer away first"):
        case.file(project, case.reading("Cy Example"), "third")
    assert case.decision(project) == decided
    # The other side: the answer taken away, the same reading is filed and decides again.
    path = project / "literature" / "currency.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    del document["entries"][0]["answer"]
    records.write_document(load_project(project)[0], document)
    assert "the rules give keep" in case.file(project, case.reading("Cy Example"), "third")
    assert case.decision(project)["rules"] == ["K1", "K2", "K3", "K5", "D3"]


def test_a_refusal_is_a_named_persons(project: Path) -> None:
    case.case(project)
    loaded = load_project(project)[0]
    with pytest.raises(command.Refused, match="only a named person"):
        command.refuse(loaded, "c1", "no", "Claude")
    assert "refused" in command.refuse(loaded, "c1", "another population", "Ada Example")
    # Round 1 of #499: an answer given is not written over.
    with pytest.raises(command.Refused, match="answered already, refused by Ada Example on "):
        command.refuse(load_project(project)[0], "c1", "no", "Bo Example")
    # The Discussion's sentence, marked and never decided: there is nothing to refuse.
    command.mark(load_project(project)[0], "reported previously", case.CITED_KEY, None)
    with pytest.raises(command.Refused, match="proposes no change"):
        command.refuse(load_project(project)[0], "c2", "no", "Ada Example")


def test_references_lists_explains_and_says_why_it_refuses(project: Path, capsys) -> None:
    case.case(project)
    assert main(["references", str(project)]) == 0
    out = capsys.readouterr().out
    assert "c1  @fictionalClassSignal2019  manuscript/main.md:19  replace " in out
    assert "claims in scope: 1, decided: 1; unplaced entries: 0" in out
    assert main(["references", str(project), "--explain", "c1"]) == 0
    out = capsys.readouterr().out
    assert "the rules give: replace doi:10.5555/class.trial.2023 (K1, K2, K3, D1)" in out
    assert "readings: 2 filed" in out
    assert main(["references", str(project), "--explain", "c1", "--readings"]) == 0
    assert "reading 1 by gpt-test (gpt-test)" in capsys.readouterr().out
    assert main(["references", str(project), "--readings"]) == 2
    assert "--readings goes with --explain" in capsys.readouterr().err
    assert main(["references", str(project), "--refuse", "c1", "--why", "no"]) == 2
    assert "--refuse needs --why and --as" in capsys.readouterr().err
    assert main(["references", str(project), "--explain", "c7"]) == 2
    assert "no entry c7" in capsys.readouterr().err


def test_explain_shows_a_second_reader_nothing_of_the_first_reading(project: Path) -> None:
    """Found taking a real paper through the loop: the skill has each reader run `--explain`
    first and says the second reading is made without seeing the first, and `--explain`
    printed every filed reading's levels, fields and quotes. It now says how many are filed;
    their fields are printed with `--readings` only."""
    case.case(project, readings=False)
    case.file(project, case.reading("Bo Example", quote="associated with hepatic injury in "
                                    "the pooled analysis"), "first")  # fmt: skip
    loaded = load_project(project)[0]
    said = command.explain(loaded, "c1")
    assert "readings: 1 filed" in said
    assert "the rules: 1 reading(s); they decide from 2" in said
    for shown in ("Bo Example", "level 4", "associated with hepatic injury in the pooled",
                  "This randomized trial", "harms-rare", "population"):  # fmt: skip
        assert shown not in said, shown
    full = command.explain(loaded, "c1", readings=True)
    assert "reading 1 by Bo Example on 2026-11-02: ocebm-2011, harms-rare" in full
    assert "associated with hepatic injury in the pooled analysis" in full
    # A reading the rules cannot read is counted, and what is wrong with it is not shown.
    bad = next((project / "literature" / "currency" / "readings").glob("c1.*.yaml"))
    bad.write_text(bad.read_text(encoding="utf-8").replace("harms-rare", "harms-often"),
                   encoding="utf-8")  # fmt: skip
    said = command.explain(load_project(project)[0], "c1")
    assert "readings: 1 filed, 1 of them unusable" in said and "harms-often" not in said


def test_explain_names_nothing_a_reading_contested_or_named(project: Path) -> None:
    """Round 1 of #543: without `--readings`, the rules' why for `uncertain` named the
    candidate the readings split on, and the works the store lacks named candidates only an
    earlier reading listed. A third reader was told where to look before reading."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    case.file(project, case.reading("Bo Example"), "first")
    case.file(project, case.reading("Cy Example", level=3), "second")
    loaded = load_project(project)[0]
    said = command.explain(loaded, "c1")
    assert "the rules give: uncertain (D4): the readings disagree" in said
    assert "what decides" not in said and case.CANDIDATE not in said
    assert "what decides doi:10.5555/class.trial.2023" in command.explain(loaded, "c1",
                                                                          readings=True)
    uncertain = [f for f in check_currency(loaded).findings if f.code == "currency-uncertain"]
    hint = uncertain[0].hint
    assert "a person reads the readings with `manuscript-guard references --explain c1 " \
        "--readings`" in hint  # fmt: skip
    assert "a third reader runs `manuscript-guard references --explain c1`, without " \
        "`--readings`" in hint  # fmt: skip
    # A candidate only a reading names, with no works record: not named either.
    other = "doi:10.5555/only.read.2024"
    third = case.reading("Di Example")
    third["candidates"].append({**third["candidates"][0], "work": other})
    case.file(project, third, "third")
    said = command.explain(load_project(project)[0], "c1")
    assert other not in said and "1 work a reading names" in said, said
    assert other in command.explain(load_project(project)[0], "c1", readings=True)


SKILL = Path(__file__).resolve().parents[1] / "plugin" / "skills" / "literature-currency"


def test_the_hint_sends_a_third_reader_though_a_third_reading_cannot_settle_it(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The `currency-uncertain` hint, and the
    literature-currency skill's step 5"): both say a third reading settles an `uncertain`
    entry, and once two readings disagree a third that agrees with one leaves it uncertain.
    `--replaces N` setting a reading aside settles it, and so does a person's decision with
    why. The 2026-11-09 triage planned a fix (F15), which will change this test."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    case.file(project, case.reading("Bo Example"), "first")
    case.file(project, case.reading("Cy Example", level=3), "second")
    uncertain = [f for f in check_currency(load_project(project)[0]).findings
                 if f.code == "currency-uncertain"]  # fmt: skip
    assert uncertain[0].hint.startswith("a person's decision with why settles it, or a third "
                                        "reading: ")  # fmt: skip
    assert "a third reader runs `manuscript-guard references --explain c1`" in uncertain[0].hint
    step = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    step = " ".join(step[step.index("## 5. "):step.index("## 6. ")].split())
    assert "nothing is proposed: a third reading, or a person's decision with why, settles " \
        "it." in step  # fmt: skip
    said = case.file(project, case.reading("Di Example"), "third")
    assert "the rules give uncertain (D4)" in said
    assert case.decision(project)["action"] == "uncertain"
    # Cy's reading set aside by a corrected one that agrees: replace.
    path = project / "corrected.yaml"
    path.write_text(yaml.safe_dump(case.reading("Cy Example"), sort_keys=False), "utf-8")
    said = command.file_reading(load_project(project)[0], path, replaces=1)
    assert "the rules give replace doi:10.5555/class.trial.2023" in said
    # Or a person decides, with why: nothing is uncertain.
    document = yaml.safe_load((project / "literature" / "currency.yaml").read_text("utf-8"))
    document["entries"][0]["decision"] = {"action": "keep", "rules": ["D3"],
                                          "by": "Ada Example", "why": "the trial is another "
                                          "population", "decided_on": "2026-11-09"}
    records.write_document(load_project(project)[0], document)
    codes = [f.code for f in check_currency(load_project(project)[0]).findings]
    assert "currency-uncertain" not in codes and "currency-decision-mismatch" not in codes


def test_explain_counts_a_work_only_a_reading_names_and_names_an_earlier_readers_cited_work(
    project: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "Without `--readings`, `--explain` counts a
    missing work"): the count does not say how to see the work. And where references.bib
    gives the cited work no DOI or PMID, the cited work `--explain` names is the first usable
    reading's own (`cited_id`), so a next reader is shown an earlier reader's choice. The
    2026-11-09 triage planned a fix (F15), which will change this test."""
    from manuscript_guard.gates.currency import _bib, cited_id

    case.case(project, readings=False)
    other = "doi:10.5555/only.read.2024"
    first = case.reading("Bo Example")
    first["candidates"].append({**first["candidates"][0], "work": other})
    case.file(project, first, "first")
    said = command.explain(load_project(project)[0], "c1")
    (line,) = [one for one in said.splitlines() if "the works store holds no record" in one]
    assert line == ("  (the works store holds no record of 1 work a reading names: the rules "
                    "decide nothing until it does)")  # fmt: skip
    # Nowhere in the whole output is it said how to see the work: the one line naming
    # `--readings` is the count of the readings filed, and `check` is not named.
    assert [one for one in said.splitlines() if "--readings" in one or "check" in one] == [
        "  readings: 1 filed; `references --explain c1 --readings` prints them, which a "
        "reader still to read the entry does not run"]
    assert other in command.explain(load_project(project)[0], "c1", readings=True)
    # The cited work with no DOI in references.bib: the first reading's choice is named.
    bib = project / "literature" / "references.bib"
    bib.write_text(bib.read_text(encoding="utf-8").replace(
        "  doi     = {10.5555/class.signal.2019},\n", ""), encoding="utf-8")  # fmt: skip
    for path in (project / "literature" / "currency" / "readings").glob("*.yaml"):
        path.unlink()
    chosen = "doi:10.5555/bo.choice"
    first = case.reading("Bo Example")
    first["cited"] = {**first["cited"], "work": chosen}
    case.file(project, first, "first")
    loaded = load_project(project)[0]
    entry = records.read_entries(loaded)[0][0]
    usable = [read.record for read in records.read_readings(loaded)]
    assert cited_id(entry, usable, _bib(loaded)) == chosen
    said = command.explain(loaded, "c1")
    assert f"(the works store holds no record of {chosen}: the rules decide nothing" in said
    # The other side: with the DOI in references.bib, the bib's is the cited work.
    case.given_a_doi(project)
    loaded = load_project(project)[0]
    assert cited_id(entry, usable, _bib(loaded)) == case.CITED


def test_explain_says_no_decision_without_the_works_and_an_accepted_proposal_as_one(
    project: Path,
) -> None:
    """Round 2 of #499: `--explain` printed "the rules give: keep" with the store gone, and
    called a proposal the listing showed as accepted "not answered"."""
    case.case(project)
    works = project / "literature" / "currency" / "works"
    kept = {path: path.read_bytes() for path in works.glob("*.yaml")}
    for path in kept:
        path.unlink()
    said = command.explain(load_project(project)[0], "c1")
    assert "the rules give:" not in said and "the rules decide nothing" in said
    for path, data in kept.items():
        path.write_bytes(data)
    bib = project / "literature" / "references.bib"
    with bib.open("a", encoding="utf-8") as entries:
        entries.write("\n@article{classTrial2023,\n  title = {A trial},\n"
                      "  author = {Fictional, Eve},\n  journal = {Imaginary Trials},\n"
                      "  year = {2023},\n  doi = {10.5555/class.trial.2023}\n}\n")
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace("[@fictionalClassSignal2019]. The", "[@classTrial2023]. The",
                                 1), encoding="utf-8")  # fmt: skip
    said = command.explain(load_project(project)[0], "c1")
    assert "accepted: the sentence cites it" in said and "not answered" not in said


def test_the_summary_says_who_read_and_who_decided(project: Path) -> None:
    from manuscript_guard.assurance import _currency
    from manuscript_guard.gates.currency import check_currency

    case.case(project, readings=False)
    model = {"provider": "test", "model": "gpt-test"}
    case.file(project, case.reading("gpt-test", provenance=model), "first")
    case.file(project, case.reading("gpt-test", provenance=model), "second")
    loaded = load_project(project)[0]
    said = _currency(check_currency(loaded), loaded)
    assert said == ["entries on whether a cited work is still the one to cite: 1, 1 decided by "
                    "the rules from readings by gpt-test (one model, read twice), 0 by a person"]


def test_an_answer_the_rules_sign_is_not_a_persons(project: Path) -> None:
    """Round 1 of #499: `by: rules` under an answer cleared `currency-change-unanswered`."""
    from manuscript_guard.currency.records import Entry
    from manuscript_guard.gates.currency import _not_human

    entry = Entry("c1", "A sentence.", "key", decision={"by": "rules"},
                  answer={"status": "accepted", "by": "rules"})  # fmt: skip
    assert [f.code for f in _not_human(entry, project)] == ["currency-decision-not-human"]


def test_rules_and_records_reach_the_same_decision(project: Path) -> None:
    """The decision `--reading` writes is the one G7 recomputes: nothing is said of it."""
    from manuscript_guard.gates.currency import check_currency

    case.case(project)
    codes = {f.code for f in check_currency(load_project(project)[0]).findings}
    assert codes == {"currency-change-unanswered"}
    assert rules.READINGS == 2
