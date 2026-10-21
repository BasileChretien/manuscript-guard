"""The data dictionary, `design/data_dictionary.yaml`: what reads, and what is refused.

The loader is the contract shared by G12 (the dictionary against the plan) and the
data-quality checks (the data against the dictionary), so what it accepts is what both
trust. Each refusal here is a dictionary that, read as written, would have handed one of
them a wrong code, a wrong bound or another variable's entry.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts.dictionary import (
    DICTIONARY,
    INVALID,
    Code,
    Condition,
    Dictionary,
    load_dictionary,
)

FULL = """\
schema: manuscript-guard/data-dictionary/1
title: Hepatic injury case series
study_period: {start: 2015-01-01, end: 2024-12-31}
datasets:
  - {id: reports, label: Case reports, source: the regional pharmacovigilance database}
forms:
  - {id: baseline, label: Baseline, timing: at the first report, recorded_by: pharmacist}
instruments:
  - id: rucam
    name: Roussel Uclaf Causality Assessment Method
    version: updated 2016
    citation: danan2016
    licence: published in full in the validating paper; no fee
    url: https://example.org/rucam
code_lists:
  yes_no:
    - {code: 1, label: "Yes"}
    - {code: 0, label: "No"}
variables:
  - name: report_id
    label: Report
    definition: The report's number in the database.
    type: identifier
    dataset: reports
    pattern: "^[0-9]{6}$"
    reason: the record's own identifier
  - name: sex
    label: Sex
    definition: Sex as reported.
    type: categorical
    values: [{code: 1, label: Male}, {code: 2, label: Female}]
    missing: [{code: 9, label: not reported}]
    required: true
    form: baseline
    dataset: reports
  - name: pregnant
    label: Pregnant
    definition: Pregnant at the onset of the reaction.
    type: binary
    code_list: yes_no
    applies_if: {variable: sex, in: [2]}
    dataset: reports
  - name: onset_date
    label: Onset
    definition: The date the reaction began, as reported.
    type: date
    range: {min: 2015-01-01, max: 2024-12-31}
    within_study_period: true
    dataset: reports
  - name: drug_start
    label: Start of the drug
    definition: The date the suspected drug was started.
    type: date
    dataset: reports
  - name: alt_ratio
    label: ALT
    definition: Peak alanine aminotransferase over the upper limit of normal.
    type: continuous
    unit: multiples of the upper limit of normal
    range: {min: 0, max: 200}
    source: laboratory report
    standard: {system: CTCAE, version: "5.0", term: Alanine aminotransferase increased}
    reporting: {STROBE: ["14a", 6]}
    dataset: reports
  - name: rucam_score
    label: RUCAM score
    definition: The total score of the updated RUCAM.
    type: count
    instrument: rucam
    item: total
    derived_from: [onset_date, drug_start]
    derivation: the sum of the RUCAM item scores
    dataset: reports
rules:
  - id: onset_after_start
    says: The reaction began on or after the drug
    order: [drug_start, onset_date]
  - {id: one_row_per_report, says: One row per report, unique: [report_id]}
  - {id: no_pregnant_men, says: No man is recorded as pregnant, computed: true}
"""


def write(root: Path, text: str) -> Path:
    path = root / DICTIONARY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def refused(root: Path, text: str) -> list[str]:
    """What the loader says of a dictionary it refuses: one message per fault."""
    write(root, text)
    dictionary, report = load_dictionary(root)
    assert dictionary is None
    assert {f.code for f in report.failures} == {INVALID}, report.findings
    return [f.message for f in report.failures]


def edited(old: str, new: str) -> str:
    assert old in FULL, old
    return FULL.replace(old, new, 1)


def test_a_project_without_a_dictionary_is_asked_for_none(tmp_path: Path) -> None:
    assert load_dictionary(tmp_path) == (None, load_dictionary(tmp_path)[1])
    assert load_dictionary(tmp_path)[1].findings == ()


def test_a_full_dictionary_reads(tmp_path: Path) -> None:
    write(tmp_path, FULL)
    dictionary, report = load_dictionary(tmp_path)
    assert report.findings == ()
    assert report.counts == {"dictionary_variables": 7}
    assert isinstance(dictionary, Dictionary)
    assert dictionary.names[:3] == ("report_id", "sex", "pregnant")
    assert dictionary.study_period == ("2015-01-01", "2024-12-31")
    sex = dictionary.variable("sex")
    assert sex.values == (Code("1", "Male"), Code("2", "Female"))
    assert sex.missing == (Code("9", "not reported"),)
    assert sex.required and sex.form == "baseline"
    assert sex.line == FULL.splitlines().index("  - name: sex") + 1
    pregnant = dictionary.variable("pregnant")
    assert pregnant.values == (Code("1", "Yes"), Code("0", "No"))
    assert pregnant.applies_if == Condition("sex", ("2",))
    alt = dictionary.variable("alt_ratio")
    assert (alt.minimum, alt.maximum) == (0, 200)
    assert alt.reporting == (("STROBE", ("14a", "6")),)
    assert alt.standard.version == "5.0" and alt.standard.code is None
    score = dictionary.variable("rucam_score")
    assert score.derived and score.item == "total"
    assert score.derived_from == ("onset_date", "drug_start")
    assert dictionary.variable("onset_date").minimum == "2015-01-01"
    assert [r.id for r in dictionary.rules] == ["onset_after_start", "one_row_per_report",
                                                "no_pregnant_men"]  # fmt: skip
    assert dictionary.rules[2].computed and dictionary.rules[0].order == ("drug_start",
                                                                          "onset_date")
    assert dictionary.variable("nothing") is None


def test_what_it_reads_cannot_be_changed(tmp_path: Path) -> None:
    write(tmp_path, FULL)
    dictionary, _report = load_dictionary(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        dictionary.variables[0].name = "other"  # type: ignore[misc]
    assert isinstance(dictionary.variables, tuple)


def test_a_minimal_dictionary_reads(tmp_path: Path) -> None:
    write(tmp_path, "schema: manuscript-guard/data-dictionary/1\nvariables:\n"
          "  - {name: age, label: Age, definition: Age in years., type: continuous}\n")  # fmt: skip
    dictionary, report = load_dictionary(tmp_path)
    assert report.findings == () and dictionary.names == ("age",)
    age = dictionary.variable("age")
    assert (age.values, age.required, age.derived) == ((), False, False)


def test_a_coded_variable_whose_codes_are_not_decided_yet_reads(tmp_path: Path) -> None:
    """A gap in the plan, which G12 says; not a fault of the file."""
    write(tmp_path, "schema: manuscript-guard/data-dictionary/1\nvariables:\n"
          "  - {name: site, label: Site, definition: The recruiting site., type: categorical}\n")
    dictionary, report = load_dictionary(tmp_path)
    assert report.findings == () and dictionary.variable("site").values == ()


def test_a_derived_variable_naming_an_input_not_in_the_dictionary_reads(tmp_path: Path) -> None:
    """Also G12's to say, as a warning: the input is a variable the plan forgot to collect."""
    write(tmp_path, edited("derived_from: [onset_date, drug_start]",
                           "derived_from: [onset_date, alt_peak_date]"))  # fmt: skip
    dictionary, report = load_dictionary(tmp_path)
    assert report.findings == ()
    assert dictionary.variable("rucam_score").derived_from == ("onset_date", "alt_peak_date")


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("schema: manuscript-guard/data-dictionary/1", "schema: manuscript-guard/data/1",
         "schema: 'manuscript-guard/data-dictionary/1' was expected"),
        ("    type: identifier", "    type: string", "variables/0/type: 'string' is not one of"),
        ("    definition: Sex as reported.\n", "", "'definition' is a required property"),
        ("    definition: Sex as reported.", "    definition: ' '",
         "variables/1/definition: ' ' does not match"),
        ("  - name: sex\n", "  - name: 2sex\n", "variables/1/name: '2sex' does not match"),
        ("    form: baseline\n", "    form: baseline\n    forms: baseline\n",
         "Additional properties are not allowed ('forms' was unexpected)"),
        ("    licence: published", "    licensed: published", "'licence' is a required"),
        ("unique: [report_id]}", "unique: [report_id], computed: true}",
         "rules/1: {'id': 'one_row_per_report'"),
    ],
)  # fmt: skip
def test_a_dictionary_that_breaks_its_schema_is_refused(
    tmp_path: Path, old: str, new: str, said: str
) -> None:
    messages = refused(tmp_path, edited(old, new))
    assert any(said in message for message in messages), messages


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("  - name: pregnant\n", "  - name: sex\n", "variable sex is given more than once"),
        ("  - {id: baseline,", "  - {id: reports,", None),
        ("{code: 2, label: Female}", "{code: '1', label: Female}",
         "variable sex: code 1 is given more than once"),
        ("{code: 9, label: not reported}", "{code: 2, label: not reported}",
         "variable sex: code 2 is both a value and a missing code"),
        ("    form: baseline\n", "    form: followup\n",
         "variable sex: its form followup is not in the dictionary"),
        ("    code_list: yes_no", "    code_list: no_yes",
         "variable pregnant: its code list no_yes is not in the dictionary"),
        ("    instrument: rucam\n", "    instrument: rucam_2016\n",
         "variable rucam_score: its instrument rucam_2016 is not in the dictionary"),
        ("    instrument: rucam\n", "", "variable rucam_score: item total names no instrument"),
        ("    dataset: reports\n    pattern", "    dataset: report\n    pattern",
         "variable report_id: its dataset report is not in the dictionary"),
        ("    type: continuous\n    unit:", "    type: categorical\n    unit:",
         "variable alt_ratio: a categorical variable has no range"),
        ("    type: date\n    dataset: reports\n  - name: alt_ratio",
         "    type: date\n    values: [{code: 1, label: a}]\n    dataset: reports\n"
         "  - name: alt_ratio",
         "variable drug_start: a date variable has no codes"),
        ("    code_list: yes_no", "    values: [{code: 1, label: 'Yes'}]",
         "variable pregnant: a binary variable has two codes, and this one has 1"),
        ("range: {min: 0, max: 200}", "range: {min: 200, max: 0}",
         "variable alt_ratio: its range's min is above its max"),
        ("range: {min: 0, max: 200}", "range: {min: '0', max: 200}",
         "variable alt_ratio: its range bound '0' is not a number"),
        ("range: {min: 2015-01-01, max: 2024-12-31}", "range: {min: 2015-01-01, max: 2024}",
         "variable onset_date: its range bound 2024 is not an ISO 8601 date, in quotes"),
        ("range: {min: 2015-01-01, max: 2024-12-31}",
         "range: {min: 2015-01-01, max: '2024-12-31T10:00:00'}",
         "variable onset_date: its range bound '2024-12-31T10:00:00' is not an ISO 8601 date"),
        ("applies_if: {variable: sex, in: [2]}", "applies_if: {variable: gender, in: [2]}",
         "variable pregnant: applies_if names gender, which is not in the dictionary"),
        ("applies_if: {variable: sex, in: [2]}", "applies_if: {variable: sex, in: [3]}",
         "variable pregnant: applies_if names code 3, which sex does not have"),
        ("applies_if: {variable: sex, in: [2]}", "applies_if: {variable: pregnant, in: [1]}",
         "variable pregnant: applies_if names the variable itself"),
        ("applies_if: {variable: sex, in: [2]}", "applies_if: {variable: alt_ratio, in: [1]}",
         "variable pregnant: applies_if names alt_ratio, a continuous variable, which has no"),
        ('pattern: "^[0-9]{6}$"', 'pattern: "^[0-9]{6$("',
         "variable report_id: its pattern does not compile"),
        ("    type: date\n    range", "    type: date\n    pattern: x\n    range",
         "variable onset_date: a pattern is for text and identifier variables"),
        ("    unit: multiples", "    within_study_period: true\n    unit: multiples",
         "variable alt_ratio: within_study_period is for date and datetime variables"),
        ("study_period: {start: 2015-01-01, end: 2024-12-31}",
         "study_period: {start: 2025-01-01, end: 2024-12-31}",
         "study_period: start is after end"),
        ("order: [drug_start, onset_date]", "order: [drug_start, alt_ratio]",
         "rule onset_after_start: order compares dates with dates, or numbers with numbers"),
        ("order: [drug_start, onset_date]", "order: [drug_start, onset]",
         "rule onset_after_start: onset is not in the dictionary"),
        ("{code: 0, label: \"No\"}", "{code: 1, label: \"No\"}",
         "code list yes_no: code 1 is given more than once"),
    ],
)  # fmt: skip
def test_what_the_schema_cannot_say_is_refused(
    tmp_path: Path, old: str, new: str, said: str | None
) -> None:
    messages = refused(tmp_path, edited(old, new))
    if said is not None:
        assert any(said in message for message in messages), messages


def test_a_dataset_id_given_twice_is_refused(tmp_path: Path) -> None:
    text = edited("datasets:\n", "datasets:\n  - {id: reports, label: Other}\n")
    assert refused(tmp_path, text) == ["dataset reports is given more than once"]


def test_within_study_period_needs_one(tmp_path: Path) -> None:
    text = edited("study_period: {start: 2015-01-01, end: 2024-12-31}\n", "")
    assert refused(tmp_path, text) == [
        "variable onset_date: within_study_period needs the dictionary's study_period"
    ]


def test_unique_names_one_dataset(tmp_path: Path) -> None:
    text = edited("datasets:\n", "datasets:\n  - {id: drugs, label: Drugs}\n")
    text = text.replace("    type: date\n    dataset: reports",
                        "    type: date\n    dataset: drugs")  # fmt: skip
    text = text.replace("unique: [report_id]}", "unique: [report_id, drug_start]}")
    assert refused(tmp_path, text) == [
        "rule one_row_per_report: unique names variables of more than one dataset"
    ]


@pytest.mark.parametrize(
    "written, read",
    [("010", "the number 8"), ("8:30", "the number 510"), ("1_000", "the number 1000"),
     ("0x1F", "the number 31")],
)  # fmt: skip
def test_a_number_yaml_reads_as_another_is_refused_at_its_line(
    tmp_path: Path, written: str, read: str
) -> None:
    """`010` is 8 to YAML, so the code would never match the data's "010"."""
    path = write(tmp_path, edited("{code: 9, label: not reported}",
                                  f"{{code: {written}, label: not reported}}"))  # fmt: skip
    _dictionary, report = load_dictionary(tmp_path)
    [finding] = report.failures
    assert finding.message.startswith(f"{written} is read by YAML as {read}; write it in quotes")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert written in lines[finding.line - 1]


@pytest.mark.parametrize("word", ["No", "yes", "Off", "on"])
def test_a_word_yaml_reads_as_true_or_false_is_refused_once(tmp_path: Path, word: str) -> None:
    """`label: No` is false to YAML. Said once, as what to write: the schema's "False is not
    of type 'string'" on the same line is the same fault."""
    messages = refused(tmp_path, edited('{code: 0, label: "No"}', f"{{code: 0, label: {word}}}"))
    assert len(messages) == 1
    assert messages[0].startswith(f"{word} is read by YAML as ")
    assert f"write it in quotes, '{word}'" in messages[0]


def test_numbers_written_as_they_read_are_not_refused(tmp_path: Path) -> None:
    write(tmp_path, edited("range: {min: 0, max: 200}", "range: {min: -0.5, max: 200.0}"))
    dictionary, report = load_dictionary(tmp_path)
    assert report.findings == ()
    assert dictionary.variable("alt_ratio").maximum == 200.0


def test_a_time_bound_reads_in_quotes(tmp_path: Path) -> None:
    write(tmp_path, "schema: manuscript-guard/data-dictionary/1\nvariables:\n"
          "  - {name: dose_time, label: Dose, definition: When the dose was given., "
          "type: time, range: {min: '06:00', max: '22:30'}}\n")  # fmt: skip
    dictionary, report = load_dictionary(tmp_path)
    assert report.findings == ()
    assert dictionary.variable("dose_time").maximum == "22:30"


@pytest.mark.parametrize(
    "old, new",
    [
        ("{code: 9, label: not reported}", "{code: 9.0, label: not reported}"),
        ("applies_if: {variable: sex, in: [2]}", "applies_if: {variable: sex, in: [2.0]}"),
        ('reporting: {STROBE: ["14a", 6]}', 'reporting: {STROBE: ["14a", 6.0]}'),
    ],
)
def test_a_code_written_with_a_decimal_point_is_refused(tmp_path: Path, old, new) -> None:
    """JSON Schema takes 9.0 for an integer; as text it is "9.0", which no 9 matches."""
    [message] = refused(tmp_path, edited(old, new))
    assert "is a code with a decimal point; write it" in message


def test_a_decimal_item_number_is_told_to_be_quoted(tmp_path: Path) -> None:
    """RECORD numbers its items 6.1, 6.2: as a number 6.10 would be 6.1."""
    messages = refused(tmp_path, edited('reporting: {STROBE: ["14a", 6]}',
                                        'reporting: {RECORD: [6.1]}'))  # fmt: skip
    assert any("write it in quotes" in m for m in messages), messages


@pytest.mark.parametrize(
    "text",
    [
        "",
        "- just a list\n",
        "schema: manuscript-guard/data-dictionary/1\nvariables: [\n",
        "schema: manuscript-guard/data-dictionary/1\nvariables: []\n---\nsecond: document\n",
        "schema: manuscript-guard/data-dictionary/1\nstudy_period: {start: 2026-02-30, "
        "end: 2026-03-01}\nvariables: []\n",
    ],
)
def test_a_file_that_is_not_a_dictionary_is_refused_without_a_crash(
    tmp_path: Path, text: str
) -> None:
    assert refused(tmp_path, text)


def test_a_file_that_is_not_utf8_is_refused_in_a_sentence(tmp_path: Path) -> None:
    path = tmp_path / DICTIONARY
    path.parent.mkdir(parents=True)
    path.write_bytes(FULL.replace("Sex as reported.", "Sexe déclaré.").encode("cp1252"))
    [message] = [f.message for f in load_dictionary(tmp_path)[1].failures]
    assert "cannot be read" in message and "not UTF-8" in message


def test_each_fault_is_said_at_its_line(tmp_path: Path) -> None:
    path = write(tmp_path, edited("    form: baseline\n", "    form: followup\n"))
    [finding] = load_dictionary(tmp_path)[1].failures
    assert path.read_text(encoding="utf-8").splitlines()[finding.line - 1] == "  - name: sex"
    path = write(tmp_path, edited("    type: identifier", "    type: string"))
    [finding] = load_dictionary(tmp_path)[1].failures
    assert path.read_text(encoding="utf-8").splitlines()[finding.line - 1] == "    type: string"


def test_the_example_dictionary_in_the_schema_s_own_words_is_valid() -> None:
    """The fixture above holds every key the schema names, so a key renamed in one and not
    the other fails here."""
    from manuscript_guard.contracts._schema import load_schema

    schema = load_schema("data-dictionary")
    document = yaml.safe_load(FULL)
    variable_keys = set().union(*(entry.keys() for entry in document["variables"]))
    variable_keys |= {"question", "timing", "recorded_by", "reason"}
    assert variable_keys == set(schema["$defs"]["variable"]["properties"])
    assert set(document) == set(schema["properties"])
