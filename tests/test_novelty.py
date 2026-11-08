"""A claim of novelty or absence, held to a recorded search for the earlier study (DESIGN.md,
"A claim to be first, or that nothing is known, rests on a recorded search"): the list that
reads the claims, the entries and their searches, G7's findings, `references --novelty`,
N1 and N2, a search by hand and the hook. The failures a manuscript gives are in
tests/test_corruption.py too, and the reading held over generated inputs in
tests/test_properties.py."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from test_currency_searches import SERVICES, TRIAL_DOI, Registry

from manuscript_guard.contracts import ContractError, load_project
from manuscript_guard.contracts._schema import load_schema
from manuscript_guard.currency import command, novelty, novelty_command, novelty_search, records
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates import currency as gate
from manuscript_guard.lookup.run import Credentials, Pacer
from manuscript_guard.policy import DRAFTING, SUBMISSION

TODAY = date(2026, 11, 7)
CLAIM = "To our knowledge, this is the first study of statin use and delirium in children."
ABSENT = "No study has examined whether statins are associated with delirium in children."
SOFTER = "Little is known about the long-term effects of statins in children."
NOTE = "Embase, Web of Science, conference abstracts, theses and work not in English"

#: The design's list of what is read, each with its list.
READ = [
    ("priority", CLAIM),
    ("priority", "This study is the first to examine it."),
    ("priority", "The present analysis is, to our knowledge, the first to report this."),
    ("priority", "Ours is the first cohort of its kind."),
    ("priority", "We are the first to describe the association."),
    ("priority", "We report the first case of drug-induced pancreatitis with dupilumab."),
    ("priority", "Here we show for the first time that the drug lowers the risk."),
    ("priority", "We show here, for the first time, that it works."),
    ("priority", "We show in this cohort for the first time that it works."),
    ("priority", "For the first time, we describe the course of the disease."),
    # Another's priority in the passive, after a verb of reporting: read (Known gaps).
    ("priority", "Statin myopathy was described for the first time in 1988."),
    ("absence", ABSENT),
    ("absence", "No previous trials have compared the two drugs."),
    ("absence", "No study to date has looked at this outcome."),
    ("absence", "This association has not been reported."),
    ("absence", "Such effects have never been studied in children."),
    ("absence", "The interaction has not yet been described."),
    ("absence", "The safety of this combination has yet to be established."),
    ("absence", "There are no published data on the use of the drug in pregnancy."),
    ("absence", "The question remains unexplored."),
    ("absence", "It hasn\N{RIGHT SINGLE QUOTATION MARK}t been studied."),
    ("softer", SOFTER),
    ("softer", "The mechanism remains unclear."),
    ("softer", "It is poorly understood."),
    ("softer", "It is unclear whether the drug works."),
    ("softer", "Few studies have examined this."),
    ("softer", "Data on the use of the drug in older adults are limited."),
    ("softer", "There is a paucity of evidence."),
    ("softer", "The question has received little attention."),
    ("softer", "This fills a gap in the literature."),
]
#: And what none of the lists reads.
NOT_READ = [
    "This is not the first study to report it.",
    "Ours is not the first study.",
    "The drug was given, not for the first time, to the patient.",
    "Smith et al. were the first to describe it.",
    "The first case was reported in 1985.",
    "The interaction had not been reported by 2015.",
    "No trial had compared the two drugs.",
    "To our knowledge, the drug is metabolised by CYP3A4.",
    "There is no evidence that the effect differed by sex.",
    "Patients treated for the first time were included.",
    "Patients we saw for the first time were included.",
    "Patients seen for the first time this year were included.",
    "This is the first study visit of the cohort.",
    "This was the first dose they received.",
    "This is the first time the patient received the drug.",
    "Novel oral anticoagulants were prescribed.",
    "New-onset atrial fibrillation was the outcome.",
    "This study is a first step.",
    "The denominator is unknown.",
    "This analysis asks whether the signal extends to example-drug specifically.",
    # "That" ends the window (Known gaps), and so does a semicolon between citation keys.
    "We show that, for the first time, statins reduce delirium.",
    "As reported [@a; @b] for the first time in children.",
    # Round 1 of #583: a hyphenated "first" names a kind of thing, and a paper's own data
    # being limited is a limitation, not a claim about the literature.
    "This is the first-line treatment for gout.",
    "This represents the first-in-class inhibitor.",
    "Our data are limited by under-reporting.",
    "These data are limited.",
]


def test_novelty_refuses_a_currency_file_it_cannot_read_and_leaves_it(tmp_path: Path) -> None:
    """Round 1 of #583: an unreadable literature/currency.yaml was read as empty and written
    over with the new entry alone, every entry before it lost."""
    root = _project(tmp_path, _text(ABSENT))
    path = root / "literature" / "currency.yaml"
    path.write_bytes(b"schema: manuscript-guard/currency/1\nentries: [\n- id: c1\n")
    before = path.read_bytes()
    with pytest.raises(command.Refused):
        novelty_command.mark(load_project(root)[0], "no study has examined", "Ada Example")
    assert path.read_bytes() == before


def test_the_listing_and_explain_say_what_g7_says_of_a_no_claim_and_a_stale_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 1 of #583: the listing read the first entry's `not_a_claim` where another carried
    it, and crashed; it took a model's for a person's, as G7 does not; it counted a stale
    search as searched; and `--explain` said nothing of a `not_a_claim`."""
    from manuscript_guard.gates.currency import _Records as held

    monkeypatch.setattr(gate, "today", lambda: TODAY)
    root = _project(tmp_path, _text(ABSENT, CLAIM))
    said = {"by": "Ada Example", "why": "said of the sponsor", "decided_on": "2026-11-07"}
    _entries(root, NOVEL, {**NOVEL, "id": "c2", "not_a_claim": said},
             {"id": "c3", "kind": "novelty", "sentence": CLAIM})
    _search(root, 1, entry="c3", on="2026-01-02")
    project = load_project(root)[0]
    rows = {row.sentence: row.state for row in novelty_command.rows(project, held(project))}
    assert rows[ABSENT] == "absence: no claim, by Ada Example"
    assert rows[CLAIM].startswith("priority: stale, searched as of 2026-01-02")
    entries = {one.id: one for one in records.read_entries(project)[0]}
    assert "G7: no claim, by Ada Example" in novelty_command.explain(
        project, entries["c2"], held(project))
    assert "more than 6 months ago" in novelty_command.explain(project, entries["c3"],
                                                                 held(project))
    _entries(root, NOVEL, {**NOVEL, "id": "c2", "not_a_claim": {**said, "by": "Claude"}})
    rows = {row.sentence: row.state for row in novelty_command.rows(project, held(project))}
    assert rows[ABSENT] == "absence: c1 is marked, not searched"


def test_a_search_by_hand_that_says_what_it_left_out_in_a_list_is_refused(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    project = load_project(root)[0]
    novelty_command.mark(project, "no study has examined", "Ada Example")
    given = tmp_path / "embase.yaml"
    given.write_bytes(yaml.safe_dump({
        "step": "N1", "source": "Embase", "query": "q", "searched_on": "2026-11-02",
        "hits": 0, "not_searched": ["Scopus", "grey literature"]}).encode())
    with pytest.raises(command.Refused, match="not-searched"):
        novelty_search.hand_search(project, "c1", given, "Ada Example")


def test_a_claim_after_two_blank_lines_is_placed_on_its_own_line() -> None:
    assert novelty.claims_in("A.\n\n\nNo study has examined X.\n")[0][0] == 4


def test_a_seed_named_by_a_key_with_no_identifier_is_refused(tmp_path: Path) -> None:
    root = _project(tmp_path, _text(ABSENT))
    (root / "literature" / "references.bib").write_bytes(
        b"@article{smith2020,\n  title = {A study},\n  year = {2020}\n}\n")
    with pytest.raises(command.Refused, match="no DOI and no PMID"):
        novelty_search.seed_of(load_project(root)[0], "@smith2020")
    assert novelty_search.seed_of(load_project(root)[0], "https://doi.org/10.5555/AB").work == (
        "doi:10.5555/ab")
    assert novelty_search.seed_of(load_project(root)[0], "pmid:123").work == "pmid:123"


@pytest.mark.parametrize(("wanted", "sentence"), READ)
def test_each_claim_the_design_lists_is_read_by_its_list(wanted: str, sentence: str) -> None:
    read = novelty.read_sentence(sentence)
    assert read is not None and read[0].list == wanted, (sentence, read)


@pytest.mark.parametrize("sentence", NOT_READ)
def test_what_the_design_says_is_not_read_is_not(sentence: str) -> None:
    assert novelty.read_sentence(sentence) is None


def test_a_claim_is_read_across_a_line_break_and_in_capitals() -> None:
    assert novelty.read_sentence("NO STUDY HAS\nEXAMINED IT.")[0].id == "no-study-has"


# --------------------------------------------------------------------------- the project


def _project(root: Path, main: str, *, stage: str = DRAFTING, supplement: str | None = None
             ) -> Path:  # fmt: skip
    (root / "manuscript").mkdir(parents=True)
    (root / "literature").mkdir()
    (root / "paper.yaml").write_bytes(
        f"schema: manuscript-guard/paper/1\ntitle: A test\nstage: {stage}\n".encode())
    (root / "manuscript" / "main.md").write_bytes(main.encode("utf-8"))
    if supplement is not None:
        (root / "manuscript" / "supplementary").mkdir()
        (root / "manuscript" / "supplementary" / "s1.md").write_bytes(supplement.encode())
    return root


def _text(*sentences: str) -> str:
    return "---\ntitle: A test\n---\n\n# Introduction\n\n" + "\n\n".join(sentences) + "\n"


def _g7(root: Path, stage: str = DRAFTING, today: date = TODAY,
        monkeypatch: pytest.MonkeyPatch | None = None) -> list:  # fmt: skip
    if monkeypatch is not None:
        monkeypatch.setattr(gate, "today", lambda: today)
    report = gate.check_currency(load_project(root)[0], stage)
    return [one for one in report.findings
            if one.code.startswith(("novelty-", "currency-"))]  # fmt: skip


def _codes(found: list) -> list[tuple[str, str]]:
    return [(one.code, one.severity) for one in found]


def _entries(root: Path, *entries: dict) -> None:
    records.write_document(load_project(root)[0],
                           {"schema": records.SCHEMA, "entries": list(entries)})


def _search(root: Path, number: int, step: str = "N1", *, on: str = "2026-11-01",
            status: str = "run", candidates: tuple[str, ...] = (), entry: str = "c1",
            **more) -> None:  # fmt: skip
    record = {"entry": entry, "number": number, "step": step, "source": "pubmed",
              "query": "statins delirium children", "terms_by": "Ada Example",
              "searched_on": on, "years": {"from": None, "to": on}, "not_searched": NOTE,
              "status": status, "candidates": list(candidates), **more}  # fmt: skip
    if status == "not asked":
        record["why"] = "no reason"
    else:
        record["hits"] = len(candidates)
    if step == "N2" and status != "not asked":
        record.setdefault("seed", "doi:10.5555/near")
    records.write_search(load_project(root)[0], record)


NOVEL = {"id": "c1", "kind": "novelty", "sentence": ABSENT}


# --------------------------------------------------------------------------- the findings


def test_a_claim_with_no_search_warns_while_drafting_and_fails_at_submission(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, _text(ABSENT, SOFTER))
    assert _codes(_g7(root)) == [("novelty-unsearched", WARN), ("novelty-softer", INFO)]
    assert "no entry in literature/currency.yaml" in _g7(root)[0].message
    assert _codes(_g7(root, SUBMISSION)) == [("novelty-unsearched", FAIL),
                                             ("novelty-softer", INFO)]  # fmt: skip


def test_the_supplement_is_read_as_the_main_text_is(tmp_path: Path) -> None:
    root = _project(tmp_path, _text("Words."), supplement=_text(CLAIM))
    found = _g7(root)
    assert _codes(found) == [("novelty-unsearched", WARN)]
    assert found[0].path.name == "s1.md"


def test_a_latex_claim_is_read_as_it_prints_with_its_abstract(tmp_path: Path) -> None:
    root = _project(tmp_path, "")
    (root / "manuscript" / "main.md").unlink()
    (root / "manuscript" / "main.tex").write_bytes(
        b"\\documentclass{article}\n\\begin{abstract}\n" + CLAIM.encode() + b"\n"
        b"\\end{abstract}\n\\begin{document}\n\\section{Introduction}\n"
        b"No study has examined \\texttt{this} in children \\cite{a}.\n"
        b"% No study has examined this comment\n\\end{document}\n")
    found = novelty.claims(load_project(root)[0])
    assert [(one.list, one.path.name, one.line) for one in found] == [
        ("priority", "main.tex", 3), ("absence", "main.tex", 7)]


def test_what_is_not_prose_is_not_read(tmp_path: Path) -> None:
    text = ("---\ntitle: No study has examined X\n---\n\n# Introduction\n\n"
            "A `no study has examined` code span, $no study has examined$ maths.\n\n"
            "<!-- No study has examined this -->\n\n![No study has examined it](f.png)\n\n"
            "```\nNo study has examined it.\n```\n")
    assert novelty.claims_in(text) == []


def test_a_search_for_the_earlier_study_that_found_nothing_answers_the_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    _entries(root, NOVEL)
    assert "marked, not searched" in _g7(root, monkeypatch=monkeypatch)[0].message
    _search(root, 1)
    assert _g7(root, monkeypatch=monkeypatch) == []


def test_works_found_and_none_followed_forward_leave_the_claim_unsearched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    _entries(root, NOVEL)
    _search(root, 1, candidates=("doi:10.5555/near",))
    found = _g7(root, monkeypatch=monkeypatch)
    assert _codes(found) == [("novelty-unsearched", WARN)]
    assert "none was followed forward" in found[0].message
    _search(root, 2, "N2", candidates=("doi:10.5555/later",))
    assert _g7(root, monkeypatch=monkeypatch) == []


def test_a_search_more_than_six_months_old_is_stale_by_its_older_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    _entries(root, NOVEL)
    _search(root, 1, on="2026-11-01", candidates=("doi:10.5555/near",))
    _search(root, 2, "N2", on="2026-05-06")
    found = _g7(root, monkeypatch=monkeypatch)
    assert _codes(found) == [("novelty-search-stale", WARN)]
    assert "2026-05-06" in found[0].message
    assert _codes(_g7(root, SUBMISSION, monkeypatch=monkeypatch)) == [
        ("novelty-search-stale", FAIL)]
    # Six calendar months, not 180 days: on 2026-11-07 a search of 2026-05-07 is not stale.
    _search(root, 3, "N2", on="2026-05-07")
    assert _g7(root, monkeypatch=monkeypatch) == []


@pytest.mark.parametrize(("status", "said"), [("by hand", "searched by hand only"),
                                              ("not asked", "asked of no source")])
def test_a_search_by_hand_or_not_asked_is_no_n1(tmp_path: Path, status: str, said: str,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path, _text(ABSENT))
    _entries(root, NOVEL)
    _search(root, 1, status=status)
    found = _g7(root, monkeypatch=monkeypatch)
    assert _codes(found) == [("novelty-unsearched", WARN)] and said in found[0].message


def test_an_edited_search_record_is_edited_and_answers_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    _entries(root, NOVEL)
    _search(root, 1)
    path = root / "literature" / "currency" / "searches" / "c1-1.yaml"
    path.write_bytes(path.read_bytes().replace(b"statins delirium", b"statins coma"))
    assert sorted(_codes(_g7(root, monkeypatch=monkeypatch))) == [
        ("currency-record-edited", FAIL), ("novelty-unsearched", WARN)]


def test_a_persons_word_that_it_is_no_claim_answers_it_and_a_models_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text("Adverse events have not been reported to the sponsor."))
    sentence = "Adverse events have not been reported to the sponsor."
    _entries(root, {"id": "c1", "kind": "novelty", "sentence": sentence, "not_a_claim": {
        "by": "Ada Example", "why": "said of this trial's sponsor", "decided_on": "2026-11-07"}})
    assert _g7(root, monkeypatch=monkeypatch) == []
    _entries(root, {"id": "c1", "kind": "novelty", "sentence": sentence, "not_a_claim": {
        "by": "Claude", "why": "said of the sponsor", "decided_on": "2026-11-07"}})
    assert sorted(_codes(_g7(root, monkeypatch=monkeypatch))) == [
        ("currency-decision-not-human", FAIL), ("novelty-unsearched", WARN)]


def test_an_entry_is_placed_by_its_words_exactly(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1 of #580: `NEAR` over every claim let one claim's search cover another, since
    claims share their stock words (12 of these 15)."""
    other = "To our knowledge, this is the first study of opioid use and falls in adults."
    root = _project(tmp_path, _text(other))
    _entries(root, {"id": "c1", "kind": "novelty", "sentence": CLAIM})
    _search(root, 1)
    found = _g7(root, monkeypatch=monkeypatch)
    assert sorted(_codes(found)) == [("currency-entry-unplaced", INFO),
                                     ("novelty-unsearched", WARN)]  # fmt: skip
    # Its case, its line breaks and its citations do not matter.
    (root / "manuscript" / "main.md").write_bytes(
        _text(CLAIM.upper().replace(" study ", " study\n").rstrip(".") + " [@a].").encode())
    assert _g7(root, monkeypatch=monkeypatch) == []


def test_a_reading_of_a_claim_of_novelty_is_invalid(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path, _text(ABSENT))
    _entries(root, NOVEL)
    _search(root, 1)
    folder = root / "literature" / "currency" / "readings"
    folder.mkdir(parents=True)
    said = {"schema": "manuscript-guard/currency-reading/1", "entry": "c1", "reader": "Ada",
            "read_on": "2026-11-02", "hierarchy": "ocebm-2011", "scale": "benefit",
            "cited": {"work": "doi:10.5555/x", "level": {"value": 2, "quote": "x"}},
            "candidates": [], "number": 1, "filed_on": "2026-11-02"}  # fmt: skip
    said["reading_sha256"] = records.sealed_digest(said, "reading_sha256")
    (folder / "c1.Ada.1.yaml").write_bytes(yaml.safe_dump(said).encode())
    assert _codes(_g7(root, monkeypatch=monkeypatch)) == [("currency-reading-invalid", FAIL)]


# ------------------------------------------------------------------------------ the schema


@pytest.mark.parametrize("said", ["none", "None.", " N/A ", "nothing", "nil", "na",
                                  "Not applicable", "", "  ", "---", "12"])
def test_what_was_not_searched_may_not_be_empty_or_say_nothing(said: str,
                                                               tmp_path: Path) -> None:
    assert novelty.not_searched_problem(said)
    root = _project(tmp_path, _text(ABSENT))
    with pytest.raises(ContractError):
        records.write_search(load_project(root)[0], {
            "entry": "c1", "number": 1, "step": "N1", "source": "pubmed", "query": "q",
            "searched_on": "2026-11-01", "years": {"from": None, "to": "2026-11-01"},
            "not_searched": said, "hits": 0, "candidates": []})


def test_the_schema_refuses_every_word_the_list_says_is_nothing() -> None:
    """The schema's pattern is written by hand; it is held to the list in data."""
    pattern = load_schema("currency-search")["properties"]["not_searched"]["not"]["pattern"]
    for word in novelty.nothing_left_out():
        for written in (word, word.upper(), word.capitalize() + "."):
            assert re.search(pattern, written), written
    assert not novelty.not_searched_problem(NOTE)
    assert not re.search(pattern, NOTE)


def test_a_novelty_entry_has_no_decision_and_a_currency_entry_no_not_a_claim(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    for wrong in ({**NOVEL, "decision": {"action": "keep", "rules": ["D3"], "by": "rules",
                                         "decided_on": "2026-11-01"}},
                  {"id": "c1", "sentence": ABSENT, "citekey": "a",
                   "not_a_claim": {"by": "A", "why": "x", "decided_on": "2026-11-01"}},
                  {"id": "c1", "sentence": ABSENT}):  # fmt: skip
        with pytest.raises(ContractError):
            _entries(root, wrong)


# ----------------------------------------------------------------------------- the command


def test_novelty_marks_the_claim_once_wherever_it_is_written(tmp_path: Path) -> None:
    """Round 1 of #580: the same claim in two files was two sentences, and refused."""
    root = _project(tmp_path, _text(ABSENT), supplement=_text(ABSENT))
    project = load_project(root)[0]
    said = novelty_command.mark(project, "no study has examined whether", "Ada Example")
    assert said.startswith("marked as c1")
    entries, _report = records.read_entries(project)
    assert [(one.id, one.kind, one.citekey) for one in entries] == [("c1", "novelty", None)]
    with pytest.raises(command.Refused, match="has an entry already, c1"):
        novelty_command.mark(project, "no study has examined", "Ada Example")
    with pytest.raises(command.Refused, match="0 claims"):
        novelty_command.mark(project, "words of no claim", "Ada Example")


def test_novelty_refuses_words_two_claims_hold(tmp_path: Path) -> None:
    root = _project(tmp_path, _text(ABSENT, CLAIM))
    with pytest.raises(command.Refused, match="2 claims"):
        novelty_command.mark(load_project(root)[0], "in children", "Ada Example")


def test_a_reworded_claim_is_marked_again_and_keeps_its_searches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    project = load_project(root)[0]
    novelty_command.mark(project, "no study has examined", "Ada Example")
    _search(root, 1)
    reworded = ABSENT.replace("whether", "if")
    (root / "manuscript" / "main.md").write_bytes(_text(reworded).encode())
    assert sorted(_codes(_g7(root, monkeypatch=monkeypatch))) == [
        ("currency-entry-unplaced", INFO), ("novelty-unsearched", WARN)]
    said = novelty_command.mark(project, "no study has examined if", "Ada Example", "c1")
    assert "taken out" in said
    entry = records.read_entries(project)[0][0]
    assert (entry.sentence, entry.also) == (reworded, ())
    assert _g7(root, monkeypatch=monkeypatch) == []


def test_not_a_claim_is_a_named_persons_with_why(tmp_path: Path) -> None:
    root = _project(tmp_path, _text("Adverse events have not been reported to the sponsor."))
    project = load_project(root)[0]
    for by, why in (("Claude", "said of the sponsor"), (None, "said of the sponsor")):
        with pytest.raises(command.Refused, match="never a model"):
            novelty_command.mark(project, "reported to the sponsor", by, not_a_claim=why)
    novelty_command.mark(project, "reported to the sponsor", "Ada Example",
                         not_a_claim="said of this trial's sponsor")
    entry = records.read_entries(project)[0][0]
    assert entry.not_a_claim["by"] == "Ada Example"


def test_the_listing_and_explain_say_how_far_each_claim_got(tmp_path: Path, capsys) -> None:
    from manuscript_guard.cli import main

    root = _project(tmp_path, _text(ABSENT, SOFTER))
    novelty_command.mark(load_project(root)[0], "no study has examined", "Ada Example")
    _search(root, 1, candidates=("doi:10.5555/near",))
    assert main(["references", str(root)]) == 0
    out = capsys.readouterr().out
    assert "c1  novelty" in out and "absence: c1's search for the earlier study" in out
    assert "-  novelty" in out and "softer: no entry" in out
    assert "claims of novelty or absence: 2, searched: 0" in out
    assert main(["references", str(root), "--explain", "c1"]) == 0
    out = capsys.readouterr().out
    assert "a claim of novelty" in out and f"not searched: {NOTE}" in out
    assert "none was followed forward" in out


# ---------------------------------------------------------------------------- the searches


def _run(root: Path, registry: Registry, **kwargs) -> novelty_search.Run:
    return novelty_search.run(
        load_project(root)[0], "c1", terms_text=kwargs.pop("terms", None),
        forward=kwargs.pop("forward", None), not_searched=kwargs.pop("note", NOTE),
        by=kwargs.pop("by", "Ada Example"), transport=registry, services=SERVICES,
        credentials=Credentials(), pacer=Pacer(sleep=lambda s: None), today=TODAY,
        **kwargs)  # fmt: skip


def _held(root: Path) -> list[dict]:
    return sorted((read.record for read in records.read_searches(load_project(root)[0])),
                  key=lambda one: one["number"])  # fmt: skip


def test_n1_asks_every_registry_with_no_limit_and_records_what_it_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    novelty_command.mark(load_project(root)[0], "no study has examined", "Ada Example")
    registry = Registry()
    run = _run(root, registry, terms="statins delirium children")
    assert run.whole, run.lines
    held = _held(root)
    assert [(one["step"], one["source"]) for one in held] == [
        ("N1", "pubmed"), ("N1", "europepmc"), ("N1", "openalex")]
    for one in held:
        assert one["years"] == {"from": None, "to": "2026-11-07"}
        assert one["not_searched"] == NOTE and one["terms_by"] == "Ada Example"
        assert "mindate" not in one["sent"] and "systematic" not in one["sent"]
    assert held[2]["candidates"] == [f"doi:{TRIAL_DOI}"]
    assert any("follow the nearest forward" in line for line in run.lines)
    found = _g7(root, monkeypatch=monkeypatch)
    assert "none was followed forward" in found[0].message
    # N2: the works of every type citing the seed, newest first.
    run = _run(root, registry, forward=TRIAL_DOI)
    forward = _held(root)[-1]
    assert (forward["step"], forward["seed"], forward["filters"]["cites"]) == (
        "N2", f"doi:{TRIAL_DOI}", "W100")
    citing = [one for one in registry.asked("openalex")
              if one.params.get("filter", "").startswith("cites:")]
    assert citing and "type:review" not in citing[-1].params["filter"]
    assert citing[-1].params["sort"] == "publication_date:desc"
    assert _g7(root, monkeypatch=monkeypatch) == []


def test_a_novelty_search_is_refused_without_what_it_left_out(tmp_path: Path) -> None:
    root = _project(tmp_path, _text(ABSENT))
    novelty_command.mark(load_project(root)[0], "no study has examined", "Ada Example")
    for note in (None, "none", "N/A"):
        with pytest.raises(command.Refused, match="--not-searched"):
            _run(root, Registry(), terms="statins", note=note)
    with pytest.raises(command.Refused, match="one at a time"):
        _run(root, Registry(), terms="statins", forward=TRIAL_DOI)
    assert _held(root) == []


def test_replay_runs_the_tools_own_searches_past_a_later_search_by_hand(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    novelty_command.mark(load_project(root)[0], "no study has examined", "Ada Example")
    registry = Registry()
    _run(root, registry, terms="statins delirium children")
    _search(root, 4, status="by hand")
    novelty_search.replay(load_project(root)[0], "c1", transport=registry, services=SERVICES,
                          credentials=Credentials(), pacer=Pacer(sleep=lambda s: None),
                          today=TODAY)  # fmt: skip
    again = [one for one in _held(root) if one.get("replay_of")]
    assert sorted((one["source"], one["replay_of"]) for one in again) == [
        ("europepmc", 2), ("openalex", 3), ("pubmed", 1)]


def test_a_search_by_hand_is_a_named_persons_and_adds_to_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, _text(ABSENT))
    project = load_project(root)[0]
    novelty_command.mark(project, "no study has examined", "Ada Example")
    given = tmp_path / "embase.yaml"
    given.write_bytes(yaml.safe_dump({
        "step": "N1", "source": "Embase (Ovid)", "query": "statin* AND delirium AND child*",
        "searched_on": "2026-11-02", "hits": 3, "years": {"from": 1974, "to": "2026-11-02"},
        "not_searched": "Scopus and grey literature"}).encode())
    with pytest.raises(command.Refused, match="cannot file a search by hand"):
        novelty_search.hand_search(project, "c1", given, "Claude")
    said = novelty_search.hand_search(project, "c1", given, "Ada Example")
    assert "never counts as N1" in said
    record = _held(root)[0]
    assert (record["status"], record["terms_by"], record["years"]["from"]) == (
        "by hand", "Ada Example", "1974")
    assert "searched by hand only" in _g7(root, monkeypatch=monkeypatch)[0].message


# ---------------------------------------------------------------------------------- the hook


@pytest.mark.parametrize("line", [
    'manuscript-guard references --novelty "reported to the sponsor" --not-a-claim --why x '
    '--as "Ada Example"',
    "manuscript-guard references --hand-search c1 embase.yaml --as 'Ada Example'",
])  # fmt: skip
def test_the_hook_asks_before_an_agent_writes_a_persons_word(line: str) -> None:
    from manuscript_guard.hooks import _approves

    assert _approves(line) is not None


def test_the_hook_asks_before_id_puts_a_claim_into_a_no_claim_entry(tmp_path: Path) -> None:
    from manuscript_guard.hooks import _places_again

    root = _project(tmp_path, _text(ABSENT))
    _entries(root, {**NOVEL, "not_a_claim": {"by": "Ada Example", "why": "x",
                                             "decided_on": "2026-11-07"}})  # fmt: skip
    line = 'manuscript-guard references --novelty "no study has examined" --id c1'
    payload = {"cwd": str(root)}
    assert "no claim" in (_places_again(line, payload) or "")
    _entries(root, NOVEL)
    assert _places_again(line, payload) is None


def test_the_schema_files_stay_json() -> None:
    for name in ("currency", "currency-search"):
        assert isinstance(load_schema(name), dict)
    assert json.dumps(load_schema("currency"))
