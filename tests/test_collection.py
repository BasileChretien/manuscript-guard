"""G12's collection plan: the data dictionary held to the analysis plan, both ways.

Every variable the plan names in backticks has an entry, and every entry is needed: named
by the plan, an input of a variable it names, the variable that decides whether one is
asked, a reporting item, or a reason the author gave. Each finding warns, at every stage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.contracts.dictionary import DICTIONARY
from manuscript_guard.findings import FAIL, WARN
from manuscript_guard.gates import check_design
from manuscript_guard.gates.collection import is_deviations, needed, variables_named

PAPER = 'schema: manuscript-guard/paper/1\ntitle: "A study"\nenglish_variant: en-GB\n'

PLAN = """\
# Analysis plan

Agreed before the data, for `age` among others.

## Exposure

`drug` against no drug.

## Analysis

A logistic model of `outcome` on `drug`, adjusted for `age` and `sex`, fitted with `glm()`
and `stats::glm`, a missing value coded `NA`.

## Planned results

- `ror.*`: the ratio of `outcome` with `drug`

## Deviations from the plan

None so far.
"""

ENTRIES = """\
schema: manuscript-guard/data-dictionary/1
code_lists:
  yes_no:
    - {code: 1, label: "Yes"}
    - {code: 0, label: "No"}
variables:
  - {name: drug, label: Drug, definition: The drug was taken., type: binary, code_list: yes_no}
  - {name: outcome, label: Outcome, definition: The event., type: binary, code_list: yes_no}
  - name: age
    label: Age
    definition: Completed years at the visit.
    type: continuous
    derived_from: [dob, visit_date]
    derivation: completed years between dob and visit_date
  - {name: dob, label: Birth, definition: Date of birth., type: date}
  - {name: visit_date, label: Visit, definition: Date of the visit., type: date}
  - name: sex
    label: Sex
    definition: Sex as recorded.
    type: categorical
    values: [{code: 1, label: Male}, {code: 2, label: Female}]
"""


def project(root: Path, plan: str | None = PLAN, entries: str = ENTRIES) -> Path:
    (root / "paper.yaml").write_bytes(PAPER.encode("utf-8"))
    (root / "design").mkdir(exist_ok=True)
    if plan is not None:
        (root / "design" / "plan.md").write_bytes(plan.encode("utf-8"))
    (root / DICTIONARY).write_bytes(entries.encode("utf-8"))
    return root


def said(root: Path, stage: str | None = None) -> list[tuple[str, str]]:
    """G12's collection findings: each code, and the line it points at."""
    loaded, _report = load_project(root)
    found = []
    for finding in check_design(loaded, None, stage).findings:
        if not finding.code.startswith(("plan-variable", "dictionary-")):
            continue
        text = finding.path.read_text(encoding="utf-8").splitlines()
        found.append((finding.code, text[finding.line - 1].strip() if finding.line else ""))
    return found


def edited(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new, 1)


def test_a_dictionary_that_meets_its_plan_says_nothing(tmp_path: Path) -> None:
    assert said(project(tmp_path)) == []
    loaded, _report = load_project(tmp_path)
    counts = check_design(loaded).counts
    assert counts["plan_variables"] == 4 and counts["dictionary_variables"] == 6


def test_a_variable_the_plan_names_and_the_dictionary_lacks_is_a_warning(tmp_path: Path) -> None:
    plan = edited(PLAN, "adjusted for `age` and `sex`", "adjusted for `age`, `sex` and `bmi`")
    root = project(tmp_path, plan)
    assert said(root) == [("plan-variable-undefined", "A logistic model of `outcome` on "
                           "`drug`, adjusted for `age`, `sex` and `bmi`, fitted with `glm()`")]
    loaded, _report = load_project(root)
    [finding] = [f for f in check_design(loaded).findings if f.code == "plan-variable-undefined"]
    assert finding.severity == WARN
    assert finding.message == "the plan names `bmi`, which design/data_dictionary.yaml does " \
        "not define"  # fmt: skip
    assert "add an entry for `bmi`" in finding.hint


def test_a_name_the_dictionary_spells_otherwise_is_told_how(tmp_path: Path) -> None:
    root = project(tmp_path, edited(PLAN, "and `sex`,", "and `Sex`,"))
    loaded, _report = load_project(root)
    findings = {f.code: f for f in check_design(loaded).findings}
    assert findings["plan-variable-undefined"].hint == (
        "the dictionary has `sex`; write the name as it does"
    )
    assert "dictionary-entry-unused" in findings


def test_an_entry_nothing_needs_is_a_warning(tmp_path: Path) -> None:
    entries = ENTRIES + ("  - {name: smoking, label: Smoking, definition: Smokes now., "
                         "type: binary, code_list: yes_no}\n")  # fmt: skip
    root = project(tmp_path, entries=entries)
    assert said(root) == [("dictionary-entry-unused", "- {name: smoking, label: Smoking, "
                           "definition: Smokes now., type: binary, code_list: yes_no}")]


@pytest.mark.parametrize(
    "extra",
    ["reason: stratifies the randomisation", "reporting: {STROBE: [13a]}"],
)
def test_an_entry_with_a_reason_or_a_reporting_item_is_needed(tmp_path: Path, extra) -> None:
    entries = ENTRIES + ("  - {name: site, label: Site, definition: The site., "
                         f"type: categorical, values: [{{code: 1, label: A}}], {extra}}}\n")
    codes = [code for code, _line in said(project(tmp_path, entries=entries))]
    assert "dictionary-entry-unused" not in codes


def test_the_inputs_of_a_named_variable_and_the_variable_it_is_asked_under_are_needed(
    tmp_path: Path,
) -> None:
    entries = ENTRIES + ("  - {name: pregnant, label: Pregnant, definition: Pregnant now., "
                         "type: binary, code_list: yes_no, applies_if: {variable: sex, "
                         "in: [2]}}\n")  # fmt: skip
    plan = edited(PLAN, "adjusted for `age` and `sex`", "adjusted for `age` and `pregnant`")
    assert said(project(tmp_path, plan, entries)) == []


@pytest.mark.parametrize("kept", ["reporting: {STROBE: [14a]}", "reason: asked by the funder"])
def test_the_inputs_of_an_entry_kept_for_a_reason_or_an_item_are_needed(
    tmp_path: Path, kept: str
) -> None:
    """Round 1: an entry kept for its reporting item or its reason needed nothing, so the
    inputs the skill tells the author to collect for it were said to be unused."""
    entries = ENTRIES + (
        "  - {name: weight_kg, label: Weight, definition: Weight., type: continuous}\n"
        "  - {name: height_cm, label: Height, definition: Height., type: continuous}\n"
        "  - {name: bmi, label: BMI, definition: Body mass index., type: continuous, "
        f"derived_from: [weight_kg, height_cm], derivation: weight over height squared, {kept}}}\n"
        "  - {name: pregnant, label: Pregnant, definition: Pregnant now., type: binary, "
        f"code_list: yes_no, applies_if: {{variable: sex, in: [2]}}, {kept}}}\n"
    )
    plan = edited(PLAN, "adjusted for `age` and `sex`", "adjusted for `age`")
    codes = [code for code, _line in said(project(tmp_path, plan, entries))]
    assert "dictionary-entry-unused" not in codes, codes


def test_a_title_that_names_an_amendment_heads_the_plan_and_not_its_deviations() -> None:
    """Round 1: `# Statistical analysis plan (amendment 2)` was read as the Deviations, and
    nothing under it was read."""
    used, undefined = variables_named(
        "# Statistical analysis plan (amendment 2)\n\n## Analysis\n\n`age` and `weight`\n",
        ["age"],
    )
    assert [n.name for n in used] == ["age"] and [n.name for n in undefined] == ["weight"]
    # An appendix at the title's level after the plan leaves the title a title.
    used, undefined = variables_named(
        "# Statistical analysis plan (amendment 2)\n\n## Analysis\n\n`age`\n\n# Appendix\n\n"
        "`notes`\n",
        ["age"],
    )
    assert [n.name for n in used] == ["age"] and [n.name for n in undefined] == ["notes"]


def test_what_the_deviations_name_is_not_read(tmp_path: Path) -> None:
    plan = edited(PLAN, "None so far.", "We dropped `smoking`.\n\n### Later\n\nAnd `alcohol`.")
    entries = ENTRIES + ("  - {name: smoking, label: Smoking, definition: Smokes now., "
                         "type: binary, code_list: yes_no}\n")  # fmt: skip
    assert said(project(tmp_path, plan, entries)) == [
        ("dictionary-entry-unused", "- {name: smoking, label: Smoking, definition: Smokes now., "
         "type: binary, code_list: yes_no}")
    ]  # fmt: skip


@pytest.mark.parametrize(
    "title, deviations",
    [
        ("Deviations from the plan", True),
        ("Changes to the plan", True),
        ("Protocol amendments", True),
        ("Changes to the planned results", True),
        ("Planned results and amendments", False),
        ("Planned results", False),
        ("Analysis", False),
    ],
)
def test_the_deviations_are_told_from_the_planned_results(title: str, deviations: bool) -> None:
    assert is_deviations(title) is deviations


def test_code_values_and_hidden_text_are_not_read_as_variables() -> None:
    plan = (
        "# Plan\n\n## Analysis\n\nFitted with `glm()`, `stats::glm`, `lme4::glmer()`, keys "
        "`ror.point` and `results.dose`, values `NA` and `TRUE`.\n\n```r\nfit(`hidden`)\n```\n"
        "\n<!-- `commented` -->\n\nAnd `real`.\n"
    )
    used, undefined = variables_named(plan, ["BEN.SEX"])
    assert used == [] and [(n.name, n.line) for n in undefined] == [("real", 13)]


def test_a_dotted_name_is_a_variable_where_the_dictionary_has_it() -> None:
    used, undefined = variables_named("# P\n\n## Population\n\n`BEN.SEX` and `ror.point`.\n",
                                      ["BEN.SEX"])  # fmt: skip
    assert [(n.name, n.line) for n in used] == [("BEN.SEX", 5)] and undefined == []


def test_each_name_is_said_once_at_its_first_mention() -> None:
    used, undefined = variables_named("# P\n\n## A\n\n`x` `y`\n\n## B\n\n`y` `x` `z` `z`\n",
                                      ["x"])  # fmt: skip
    assert [(n.name, n.line) for n in used] == [("x", 5)]
    assert [(n.name, n.line) for n in undefined] == [("y", 5), ("z", 9)]


def test_needed_follows_inputs_again_and_again(tmp_path: Path) -> None:
    from manuscript_guard.contracts.dictionary import load_dictionary

    project(tmp_path)
    dictionary, _report = load_dictionary(tmp_path)
    assert needed(dictionary, ["age"]) == {"age", "dob", "visit_date"}
    assert needed(dictionary, ["absent"]) == set()


@pytest.mark.parametrize(
    "old, new, code",
    [
        ("type: binary, code_list: yes_no}\n  - {name: outcome",
         "type: binary}\n  - {name: outcome", "dictionary-codes-undecided"),
        ("    derivation: completed years between dob and visit_date\n", "",
         "dictionary-derivation-unsaid"),
        ("    derived_from: [dob, visit_date]\n", "", "dictionary-derivation-unsaid"),
        ("derived_from: [dob, visit_date]", "derived_from: [dob, visit_day]",
         "dictionary-input-undefined"),
    ],
)  # fmt: skip
def test_what_an_entry_leaves_unsaid_is_a_warning(tmp_path: Path, old, new, code) -> None:
    root = project(tmp_path, entries=edited(ENTRIES, old, new))
    assert code in [found for found, _line in said(root)]
    loaded, _report = load_project(root)
    assert all(f.severity == WARN for f in check_design(loaded).findings if f.code == code)


def test_a_derivation_cycle_is_said_once(tmp_path: Path) -> None:
    entries = ENTRIES + (
        "  - {name: a, label: A, definition: A., type: count, derived_from: [b], "
        "derivation: b plus one, reason: x}\n"
        "  - {name: b, label: B, definition: B., type: count, derived_from: [c], "
        "derivation: c plus one, reason: x}\n"
        "  - {name: c, label: C, definition: C., type: count, derived_from: [a, age], "
        "derivation: a plus age, reason: x}\n"
    )
    loaded, _report = load_project(project(tmp_path, entries=entries))
    cycles = [f.message for f in check_design(loaded).findings
              if f.code == "dictionary-derivation-cycle"]  # fmt: skip
    assert cycles == ["each is derived from the next: a from b from c from a"]


def test_a_reporting_item_is_looked_for_in_its_checklist(tmp_path: Path) -> None:
    entries = ENTRIES.replace("    type: categorical\n",
                              "    type: categorical\n    reporting: {DEMO: ['1', '9']}\n")
    root = project(tmp_path, entries=entries)
    assert ("dictionary-reporting-unchecked", "- name: sex") in said(root)
    checklist = root / "profiles" / "reporting" / "DEMO.yaml"
    checklist.parent.mkdir(parents=True)
    checklist.write_text("items:\n  - {id: '1'}\n  - {id: '2'}\n", encoding="utf-8")
    assert said(root) == [("dictionary-reporting-item-unknown", "- name: sex")]


def test_without_a_plan_the_dictionary_is_held_to_itself_alone(tmp_path: Path) -> None:
    assert said(project(tmp_path, plan=None)) == []
    entries = edited(ENTRIES, "derived_from: [dob, visit_date]", "derived_from: [dob, day]")
    assert said(project(tmp_path, plan=None, entries=entries)) == [
        ("dictionary-input-undefined", "- name: age")
    ]


@pytest.mark.parametrize("stage", ["design", "analysis", "drafting", "internal-review",
                                   "submission"])
def test_the_collection_plan_warns_at_every_stage(tmp_path: Path, stage: str) -> None:
    from manuscript_guard.policy import apply_stage

    plan = edited(PLAN, "and `sex`", "and `bmi`")
    loaded, _report = load_project(project(tmp_path, plan))
    report, _deferred = apply_stage(check_design(loaded, None, stage), stage)
    codes = {f.code for f in report.findings if f.severity == WARN}
    assert {"plan-variable-undefined", "dictionary-entry-unused"} <= codes
    assert not [f for f in report.findings if f.severity == FAIL]


def test_an_invalid_dictionary_is_said_and_held_to_nothing(tmp_path: Path) -> None:
    root = project(tmp_path, edited(PLAN, "and `sex`", "and `bmi`"),
                   edited(ENTRIES, "code_list: yes_no}", "code_list: no_yes}"))  # fmt: skip
    loaded, _report = load_project(root)
    codes = [f.code for f in check_design(loaded).findings]
    assert "dictionary-invalid" in codes and "plan-variable-undefined" not in codes
