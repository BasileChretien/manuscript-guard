"""The methods of similar studies, read at the design stage.

`design/methods_review.yaml` holds, for each study of the same question, its methods in its
own words, an appraisal of each against a methodological standard, and the author's decision
(Basile's four answers of 2026-10-21). G7 looks for each passage in the study's stored copy,
failing from the analysis stage; G12 holds each appraisal to a standard and its domain, each
decision to a person, and each method taken into the plan to a citation there, with its
standard. A design round reads the record, and its digest holds it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from test_hooks import _writes, codex_edit, decision, in_claude_code, patch_of, reason, run

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates.design import study_types
from manuscript_guard.gates.design_review import plan_digest
from manuscript_guard.gates.methods_review import check_method_passages, check_methods_review
from manuscript_guard.methods_review import (
    built_in_standards,
    read_review,
    review_keys,
    standards_for,
    standards_table,
)

__all__ = ["in_claude_code"]

REVIEW = Path("design") / "methods_review.yaml"
COHORT = "fictionalHepaticCohort2021"
#: The example's passage, in the cohort's stored copy.
PASSAGE = (
    "Hepatic injury was defined as a hospital discharge diagnosis of toxic liver disease, "
    "confirmed by an alanine aminotransferase above three times the upper limit of normal"
)
DOMAIN = "Definition and validation of drug exposure, outcomes and covariates"
#: A decision, as a person records it.
DECIDED = {"choice": "adapt", "why": "the enzyme criterion only, where a report gives it",
           "decided_by": "Ada Example", "decided_on": "2026-10-21"}  # fmt: skip


def document(root: Path) -> dict:
    return yaml.safe_load((root / REVIEW).read_text(encoding="utf-8"))


def write(root: Path, written: dict) -> None:
    text = yaml.safe_dump(written, sort_keys=False, allow_unicode=True)
    (root / REVIEW).write_text(text, encoding="utf-8")


def method(root: Path) -> dict:
    """The example's one method, to change and write back with `write`."""
    return document(root)["studies"][0]["methods"][0]


def with_method(root: Path, **changed: object) -> dict:
    """The example's record with its one method changed; a value of None takes the key out."""
    written = document(root)
    entry = written["studies"][0]["methods"][0]
    for key, value in changed.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    write(root, written)
    return written


def appraised(root: Path, **changed: object) -> None:
    entry = dict(method(root)["appraisal"], **changed)
    with_method(root, appraisal={k: v for k, v in entry.items() if v is not None})


def said(root: Path) -> list[tuple[str, str]]:
    project = load_project(root)[0]
    found = check_method_passages(project).merge(check_methods_review(project))
    return [(f.code, f.severity) for f in found.findings]


def at_stage(root: Path, stage: str, capsys) -> dict[str, str]:
    """What `check` says of the methods review at a stage, code by code."""
    main(["check", str(root), "--json", "--stage", stage])
    printed = json.loads(capsys.readouterr().out)
    return {
        f["code"]: f["severity"] for f in printed["findings"]
        if (f.get("path") or "").replace("\\", "/").endswith(REVIEW.as_posix())
    }  # fmt: skip


def plan(root: Path) -> Path:
    return root / "design" / "plan.md"


def add_to_plan(root: Path, text: str) -> None:
    path = plan(root)
    path.write_text(path.read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8")


# ---------------------------------------------------------------- the example


def test_the_example_passage_is_found_and_its_method_awaits_a_decision(project: Path) -> None:
    project_ = load_project(project)[0]
    passages = check_method_passages(project_)
    assert passages.counts["similar_passages_verified"] == 1
    assert passages.findings == ()
    reviewed = check_methods_review(project_)
    assert [(f.code, f.severity) for f in reviewed.findings] == [("similar-undecided", INFO)]
    assert reviewed.counts["similar_methods_appraised"] == 1


def test_a_project_with_no_review_is_told_nothing(project: Path) -> None:
    (project / REVIEW).unlink()
    assert said(project) == []


def test_check_runs_both_checks(project: Path, capsys) -> None:
    main(["check", str(project), "--json", "--stage", "design"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["counts"]["similar_passages_verified"] == 1
    assert "similar-undecided" in {f["code"] for f in printed["findings"]}


# ---------------------------------------------------------------- the schema


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param({"field": "time zero"}, id="a field not in the list"),
        pytest.param({"field": "other"}, id="other with no label"),
        pytest.param({"locator": None}, id="no locator"),
        pytest.param({"passage": "  "}, id="an empty passage"),
        pytest.param({"decision": {"choice": "adopt", "decided_by": "Ada Example",
                                   "decided_on": "2026-10-21"}}, id="a decision with no why"),
        pytest.param({"decision": dict(DECIDED, choice="keep")}, id="a choice not in the list"),
    ],
)  # fmt: skip
def test_a_record_out_of_its_schema_is_refused(project: Path, changed: dict) -> None:
    with_method(project, **changed)
    assert ("schema-violation", FAIL) in said(project)


def test_an_appraisal_with_no_concern_or_no_proposer_is_refused(project: Path) -> None:
    appraised(project, concern=None)
    assert ("schema-violation", FAIL) in said(project)
    appraised(project, concern="some", proposed_by=None)
    assert ("schema-violation", FAIL) in said(project)


def test_a_field_named_other_carries_its_label(project: Path) -> None:
    with_method(project, field="other", label="dose")
    review, _report = read_review(load_project(project)[0])
    assert review is not None and review.methods[0].what == "dose"


def test_several_appraisals_are_read_as_one_each(project: Path) -> None:
    first = method(project)["appraisal"]
    second = dict(first, standard="readus-pv", domain="Variables definition")
    with_method(project, appraisal=[first, second])
    review, _report = read_review(load_project(project)[0])
    assert review is not None
    assert [one.standard for one in review.methods[0].appraisals] == ["encepp-guide", "readus-pv"]
    assert said(project) == [("similar-undecided", INFO)]


# ---------------------------------------------------------------- the passages


def test_a_passage_not_in_its_study_is_a_note_at_design_and_fails_from_analysis(
    project: Path, capsys
) -> None:
    """Basile, 2026-10-21: the plan frozen at the first results was built on it."""
    with_method(project, passage=PASSAGE.replace("toxic liver disease", "liver disease"))
    assert at_stage(project, "design", capsys)["similar-passage-not-in-source"] == INFO
    assert at_stage(project, "analysis", capsys)["similar-passage-not-in-source"] == FAIL


def test_a_passage_with_words_left_out_is_looked_for_piece_by_piece(project: Path) -> None:
    with_method(project, passage="Hepatic injury was defined as [...] three times the upper limit")
    assert said(project) == [("similar-undecided", INFO)]


def test_a_passage_of_a_study_with_no_stored_copy_is_unchecked(project: Path) -> None:
    (project / "literature" / "sources" / f"{COHORT}.txt").unlink()
    assert said(project)[0] == ("similar-passage-unchecked", WARN)


def test_a_passage_of_three_words_shows_little(project: Path) -> None:
    with_method(project, passage="toxic liver disease")
    assert said(project)[0] == ("similar-passage-too-short", WARN)


# ---------------------------------------------------------------- the appraisals


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        pytest.param({"standard": None}, "appraisal-without-standard", id="no standard"),
        pytest.param({"standard": " "}, "appraisal-without-standard", id="a blank standard"),
        pytest.param({"standard": "common-practice"}, "appraisal-standard-unknown",
                     id="a standard nothing describes"),
        pytest.param({"domain": None}, "appraisal-domain-unknown", id="no domain"),
        pytest.param({"domain": "Exposure"}, "appraisal-domain-unknown",
                     id="a domain the standard does not have"),
        pytest.param({"standard": "robins-i"}, "appraisal-domain-unknown",
                     id="another standard's domain"),
    ],
)  # fmt: skip
def test_an_appraisal_says_what_standard_and_domain_it_rests_on(
    project: Path, changed: dict, code: str
) -> None:
    appraised(project, **changed)
    assert said(project) == [(code, WARN), ("similar-undecided", INFO)]


def test_the_domain_unknown_lists_the_domains_there_are(project: Path) -> None:
    appraised(project, domain="Exposure")
    [finding] = [f for f in check_methods_review(load_project(project)[0]).findings
                 if f.code == "appraisal-domain-unknown"]  # fmt: skip
    assert "Methods to address bias and confounding" in finding.message


@pytest.mark.parametrize(
    "domain",
    [DOMAIN.upper(), DOMAIN.replace(" ", "  "), "definition-and-validation of drug exposure, "
     "outcomes and covariates"],
)  # fmt: skip
def test_a_domain_is_read_loosely(project: Path, domain: str) -> None:
    appraised(project, domain=domain)
    assert said(project) == [("similar-undecided", INFO)]


def test_a_standard_the_record_describes_is_known_with_its_domains(project: Path) -> None:
    written = with_method(project)
    written["standards"] = [{"id": "house-guide", "name": "Our unit's guide",
                             "citekey": "unit2024", "domains": ["Case definitions"]}]  # fmt: skip
    written["studies"][0]["methods"][0]["appraisal"].update(
        standard="house-guide", domain="case definitions"
    )
    write(project, written)
    assert said(project) == [("similar-undecided", INFO)]


def test_a_standard_named_only_by_its_key_is_still_unknown(project: Path) -> None:
    written = with_method(project)
    written["standards"] = [{"id": "house-guide", "citekey": "unit2024"}]
    written["studies"][0]["methods"][0]["appraisal"]["standard"] = "house-guide"
    write(project, written)
    assert said(project)[0] == ("appraisal-standard-unknown", WARN)


def test_a_built_in_standard_described_again_keeps_the_table_s_domains(project: Path) -> None:
    written = with_method(project)
    written["standards"] = [{"id": "encepp-guide", "citekey": "encepp2023",
                             "domains": ["Anything"]}]  # fmt: skip
    write(project, written)
    assert ("standard-redescribed", WARN) in said(project)
    appraised(project, domain="Anything")
    assert ("appraisal-domain-unknown", WARN) in said(project)


def test_methods_with_no_appraisal_are_counted(project: Path) -> None:
    with_method(project, appraisal=None)
    assert said(project) == [("similar-unappraised", INFO)]


# ---------------------------------------------------------------- the decisions


@pytest.mark.parametrize("decider", ["Claude", "GPT-5", "Codex", "an AI", "Gemini 3"])
def test_a_decision_a_model_signed_fails_from_analysis(
    project: Path, decider: str, capsys
) -> None:
    add_to_plan(project, f"The case definition follows [@{COHORT}].")
    with_method(project, decision=dict(DECIDED, decided_by=decider))
    assert ("similar-decision-not-human", FAIL) in said(project)
    assert at_stage(project, "design", capsys)["similar-decision-not-human"] == INFO
    assert at_stage(project, "analysis", capsys)["similar-decision-not-human"] == FAIL


def test_a_person_s_decision_is_counted(project: Path) -> None:
    add_to_plan(project, f"The case definition follows [@{COHORT}].")
    with_method(project, decision=DECIDED)
    found = check_methods_review(load_project(project)[0])
    assert [(f.code, f.severity) for f in found.findings] == [("adopted-standard-uncited", WARN)]
    assert found.counts["similar_methods_decided"] == found.counts["similar_methods_taken"] == 1


def test_check_says_what_the_review_rests_on(project: Path, capsys) -> None:
    main(["check", str(project)])
    printed = capsys.readouterr().out
    assert ("    recorded:    methods of similar studies: 1 from 1 study, 1 judged against a "
            "named standard, 0 decided by a person") in printed  # fmt: skip


def test_only_what_the_gate_accepts_is_counted_as_resting_on_anything(project: Path) -> None:
    """A decision a model signed is no person's, and an appraisal against a domain the
    standard lacks rests on no standard."""
    appraised(project, domain="Exposure")
    with_method(project, decision=dict(DECIDED, decided_by="Claude"))
    counts = check_methods_review(load_project(project)[0]).counts
    assert counts["similar_methods_appraised"] == counts["similar_methods_decided"] == 0
    assert counts["similar_methods_taken"] == 0


# ---------------------------------------------------------------- what is taken is cited


@pytest.mark.parametrize("choice", ["adopt", "adapt"])
def test_a_method_taken_and_cited_nowhere_is_said(project: Path, choice: str) -> None:
    with_method(project, decision=dict(DECIDED, choice=choice))
    assert ("adopted-method-uncited", WARN) in said(project)


def test_a_method_rejected_needs_no_citation(project: Path) -> None:
    with_method(project, decision=dict(DECIDED, choice="reject"))
    assert said(project) == []


@pytest.mark.parametrize(
    "cited",
    [f"follows [@{COHORT}]", f"follows @{COHORT}", f"follows [@other; @{COHORT}, p. 3]"],
)
def test_a_citation_in_the_plan_credits_the_study(project: Path, cited: str) -> None:
    add_to_plan(project, f"The case definition {cited}.")
    with_method(project, decision=DECIDED)
    assert ("adopted-method-uncited", WARN) not in said(project)


def test_a_citation_in_a_comment_of_the_plan_credits_nothing(project: Path) -> None:
    add_to_plan(project, f"<!-- The case definition follows [@{COHORT}]. -->")
    with_method(project, decision=DECIDED)
    assert ("adopted-method-uncited", WARN) in said(project)


def _in_section(root: Path, heading: str, text: str) -> None:
    path = root / "manuscript" / "main.md"
    body = path.read_text(encoding="utf-8")
    assert f"\n{heading}\n" in body, heading
    path.write_text(body.replace(f"\n{heading}\n", f"\n{heading}\n\n{text}\n", 1), "utf-8")


def test_a_citation_in_the_methods_credits_the_study(project: Path) -> None:
    _in_section(project, "# Methods", f"The case definition follows [@{COHORT}].")
    with_method(project, decision=DECIDED)
    assert ("adopted-method-uncited", WARN) not in said(project)


def test_a_citation_elsewhere_in_the_manuscript_does_not(project: Path) -> None:
    """The example cites the cohort in its Introduction and Discussion, for its incidence."""
    assert f"@{COHORT}" in (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    with_method(project, decision=DECIDED)
    assert ("adopted-method-uncited", WARN) in said(project)


def test_a_method_taken_is_cited_with_its_standard(project: Path) -> None:
    add_to_plan(project, f"The case definition follows [@{COHORT}].")
    written = with_method(project, decision=DECIDED)
    found = check_methods_review(load_project(project)[0]).findings
    [finding] = [f for f in found if f.code == "adopted-standard-uncited"]
    assert "gives no citation key" in finding.message
    written["standards"] = [{"id": "encepp-guide", "citekey": "encepp2023"}]
    write(project, written)
    [finding] = [f for f in check_methods_review(load_project(project)[0]).findings
                 if f.code == "adopted-standard-uncited"]  # fmt: skip
    assert "@encepp2023" in finding.message
    add_to_plan(project, "The definition is validated as [@encepp2023] advises.")
    assert said(project) == []


def test_a_latex_manuscript_counts_the_plan_and_says_its_methods_were_not_read(
    project: Path,
) -> None:
    for path in (project / "manuscript").glob("*.md"):
        path.unlink()
    (project / "manuscript" / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\section{{Methods}}\nAs \\cite{{{COHORT}}}.\n", "utf-8"
    )
    with_method(project, decision=DECIDED)
    [finding] = [f for f in check_methods_review(load_project(project)[0]).findings
                 if f.code == "adopted-method-uncited"]  # fmt: skip
    assert "LaTeX manuscript's Methods are not read yet" in finding.message


def test_a_manuscript_file_that_cannot_be_read_does_not_stop_the_plan_s_gate(
    project: Path,
) -> None:
    """The unreadable file is said once, of the file; the plan's citations still count."""
    from manuscript_guard.cli import _run_gates

    main_md = project / "manuscript" / "main.md"
    main_md.write_bytes(main_md.read_bytes().replace(b"Methods", "Méthods".encode("cp1252"), 1))
    with_method(project, decision=DECIDED)
    report, _project, _stage, _deferred = _run_gates(project, stage="design")
    [unreadable] = [f for f in report.findings if f.code == "manuscript-unreadable"]
    assert "G12" not in (unreadable.hint or "")
    [finding] = [f for f in report.findings if f.code == "adopted-method-uncited"]
    assert "could not be read, so its Methods were not" in finding.message


# ---------------------------------------------------------------- the design round


def test_the_design_round_is_sent_the_review(project: Path) -> None:
    from manuscript_guard.panel.prompt import gather_design

    material = gather_design(load_project(project)[0])
    assert "# The methods of similar studies" in material.user
    assert "against ENCePP Guide on Methodological Standards" in material.user
    assert "toxic liver disease" in material.user
    assert any(sent.label == REVIEW.as_posix() for sent in material.sent)


def test_a_review_that_cannot_be_read_stops_the_round(project: Path) -> None:
    from manuscript_guard.panel.prompt import PromptError, gather_design

    with_method(project, field="time zero")
    with pytest.raises(PromptError, match="cannot be read"):
        gather_design(load_project(project)[0])


def test_a_review_changed_is_another_plan_to_read(project: Path) -> None:
    before = plan_digest(load_project(project)[0])
    appraised(project, concern="serious")
    assert plan_digest(load_project(project)[0]) != before


def test_a_project_with_no_review_keeps_the_digest_it_had(project: Path) -> None:
    import hashlib

    (project / REVIEW).unlink()
    loaded = load_project(project)[0]
    # As it was written before a review was read (the plan, then the feasibility results).
    digest = hashlib.sha256()
    digest.update(plan(project).read_bytes())
    digest.update(json.dumps({}, sort_keys=True).encode("utf-8"))
    results_counted = any(
        key.startswith("feasibility.")
        for path in (project / "results").glob("*.json")
        for key in (json.loads(path.read_text(encoding="utf-8")).get("values") or {})
    )
    if not results_counted:
        assert plan_digest(loaded) == digest.hexdigest()


# ---------------------------------------------------------------- the stored copies


def test_sync_sources_copies_the_studies_the_review_names(project: Path) -> None:
    from manuscript_guard.literature.copies import wanted_keys

    written = with_method(project)
    written["studies"].append(copy.deepcopy(written["studies"][0]) | {"citekey": "newStudy2024"})
    written["standards"] = [{"id": "encepp-guide", "citekey": "encepp2023"}]
    write(project, written)
    loaded = load_project(project)[0]
    assert review_keys(loaded) == [COHORT, "newStudy2024", "encepp2023"]
    keys = wanted_keys(loaded)
    assert keys[-2:] == ["newStudy2024", "encepp2023"] and keys.count(COHORT) == 1


def test_sync_sources_copies_a_review_s_studies_before_there_is_a_manuscript(
    project: Path,
) -> None:
    from manuscript_guard.literature import copies

    for path in (project / "manuscript").glob("*.md"):
        path.write_text("# Title\n", encoding="utf-8")
    asked: list[str] = []
    outcomes = copies.sync(load_project(project)[0], dry_run=True,
                           fetch=lambda key: asked.append(key) or [])  # fmt: skip
    assert asked == [COHORT] and [o.key for o in outcomes] == [COHORT]


# ---------------------------------------------------------------- the hook


def _decide(root: Path) -> Path:
    """The example's record with its method decided, written as the person did."""
    with_method(root, decision=DECIDED)
    return root / REVIEW


def test_recording_a_decision_is_put_to_the_person(in_claude_code: Path, capsys) -> None:
    """Basile, 2026-10-21: the decision is the author's, recorded like other decisions an
    agent may not make."""
    path = in_claude_code / REVIEW
    written = document(in_claude_code)
    written["studies"][0]["methods"][0]["decision"] = dict(DECIDED, decided_by="Bo Example")
    content = yaml.safe_dump(written, sort_keys=False, allow_unicode=True)
    result = run("guard-write", _writes(in_claude_code, file_path=str(path), content=content),
                 capsys)  # fmt: skip
    assert decision(result) == "ask"
    assert "Bo Example" in reason(result) and "adopt, adapt or reject" in reason(result)


@pytest.mark.parametrize(
    ("old", "new", "asked"),
    [
        ("choice: adapt", "choice: adopt", True),
        ("Hepatic injury was defined", "Hepatic injury was described", True),
        ("field: case definition", "field: outcome", True),
        ("decided_by: Ada Example", "decided_by: Bo Example", True),
        # What the decision is not of: the appraisal, the summary, the locator.
        ("concern: some", "concern: serious", False),
        ("locator: Methods, Outcome", "locator: Methods, Outcome, p. 2", False),
    ],
)  # fmt: skip
def test_an_edit_under_a_standing_decision_is_put_to_the_person(
    in_claude_code: Path, old: str, new: str, asked: bool, capsys
) -> None:
    path = _decide(in_claude_code)
    assert old in path.read_text(encoding="utf-8"), old
    payload = _writes(in_claude_code, "Edit", file_path=str(path), old_string=old, new_string=new)
    assert decision(run("guard-write", payload, capsys)) == ("ask" if asked else None)


def test_taking_a_decision_away_is_put_to_the_person(in_claude_code: Path, capsys) -> None:
    path = _decide(in_claude_code)
    written = document(in_claude_code)
    del written["studies"][0]["methods"][0]["decision"]
    content = yaml.safe_dump(written, sort_keys=False, allow_unicode=True)
    result = run("guard-write", _writes(in_claude_code, file_path=str(path), content=content),
                 capsys)  # fmt: skip
    assert decision(result) == "ask" and "Ada Example" in reason(result)


def test_appraising_a_method_is_the_agents_to_do(in_claude_code: Path, capsys) -> None:
    path = in_claude_code / REVIEW
    payload = _writes(in_claude_code, "Edit", file_path=str(path),
                      old_string="concern: some", new_string="concern: serious")  # fmt: skip
    assert run("guard-write", payload, capsys) is None


def test_a_patch_beside_the_example_s_commented_decision_is_not_put_to_anyone(
    project: Path, capsys
) -> None:
    assert 'decided_by: "A Person"' in (project / REVIEW).read_text(encoding="utf-8")
    patch = patch_of(
        "*** Update File: design/methods_review.yaml",
        "@@",
        '-        locator: "Methods, Outcome"',
        '+        locator: "Methods, Outcome, p. 2"',
    )
    assert run("guard-write", codex_edit(project, patch), capsys) is None


def test_a_patch_to_a_review_that_holds_a_decision_is_refused_in_codex(
    project: Path, capsys
) -> None:
    _decide(project)
    patch = patch_of(
        "*** Update File: design/methods_review.yaml",
        "@@",
        "-    locator: Methods, Outcome",
        "+    locator: Methods",
    )
    result = run("guard-write", codex_edit(project, patch), capsys)
    assert decision(result) == "deny" and "adopt, adapt or reject" in reason(result)


def test_a_file_named_methods_review_elsewhere_holds_no_decision(
    in_claude_code: Path, capsys
) -> None:
    other = in_claude_code / "notes" / "methods_review.yaml"
    other.parent.mkdir()
    payload = _writes(in_claude_code, file_path=str(other), content="decided_by: Bo\n")
    assert run("guard-write", payload, capsys) is None


# ---------------------------------------------------------------- the built-in table


def test_each_built_in_standard_says_where_it_is_and_what_it_holds() -> None:
    designs = set(study_types())
    for ident, entry in standards_table().items():
        assert entry["name"].strip(), ident
        assert entry.get("doi") or entry.get("url"), ident
        assert str(entry["read_on"]), ident
        assert set(entry["applies_to"]) <= designs, ident
        folded = [" ".join(d.casefold().split()) for d in entry["domains"]]
        assert folded and len(set(folded)) == len(folded), ident


def test_every_declared_design_has_a_standard_to_judge_against() -> None:
    for design in study_types():
        assert standards_for(design), design


def test_the_table_is_read_as_standards() -> None:
    known = built_in_standards()
    assert known["target-trial"].domain("follow-up period") == "Follow-up period"
    assert known["target-trial"].found_at == "https://doi.org/10.1093/aje/kwv254"
