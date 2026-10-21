"""The data dictionary written out: REDCap's data dictionary, a plain CSV, and the form.

REDCap's columns are held to its template: the eighteen it writes in a data dictionary it
downloads, in its order, as REDCapR and ReproNim's reproschema-py read them (read
2026-10-21). Its field types, validations, choices and branching logic are written as its
Online Designer takes them.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.contracts.dictionary import DICTIONARY, load_dictionary
from manuscript_guard.dictionary_export import (
    CSV_COLUMNS,
    REDCAP_COLUMNS,
    ExportRefused,
    outline,
    plain_csv,
    redcap,
)

PAPER = 'schema: manuscript-guard/paper/1\ntitle: "A study"\nenglish_variant: en-GB\n'

ENTRIES = """\
schema: manuscript-guard/data-dictionary/1
title: Case report form
forms:
  - {id: baseline, label: Baseline visit, timing: at enrolment, recorded_by: research nurse}
  - {id: follow_up, label: Follow-up visit, timing: day 28}
instruments:
  - {id: phq9, name: Patient Health Questionnaire-9, licence: as its holder states it}
code_lists:
  yes_no:
    - {code: 1, label: "Yes"}
    - {code: 0, label: "No"}
variables:
  - {name: weight, label: Weight, definition: Weight on the clinic scale., type: continuous,
     unit: kg, range: {min: 30, max: 250.5}, form: baseline, required: true}
  - {name: record_id, label: Record, definition: The record's number., type: identifier,
     form: baseline, reason: the record's own identifier}
  - name: sex
    label: Sex
    question: What sex were you recorded at birth?
    definition: Sex recorded at birth.
    type: categorical
    values: [{code: 1, label: Male}, {code: 2, label: Female}]
    missing: [{code: 9, label: not stated}]
    form: baseline
  - {name: pregnant, label: Pregnant, definition: Pregnant now., type: binary,
     code_list: yes_no, applies_if: {variable: sex, in: [2]}, form: baseline}
  - {name: seen_at, label: Seen, definition: When seen., type: datetime,
     range: {min: '2026-01-01T08:00:00', max: '2026-12-31T18:30:00'}, form: follow_up}
  - {name: dose_time, label: Dose, definition: When the dose was given., type: time,
     range: {min: '06:00', max: '22:30'}, form: follow_up}
  - {name: visit_date, label: Visit, definition: The visit's date., type: date,
     range: {min: 2026-01-01, max: 2026-12-31}, form: follow_up}
  - {name: phq9_1, label: PHQ-9 item 1, definition: Item 1 as scored., type: ordinal,
     instrument: phq9, item: 1, values: [{code: 0, label: Not at all},
     {code: 3, label: Nearly every day}], form: follow_up}
  - {name: falls, label: Falls, definition: Falls since enrolment., type: count,
     form: follow_up}
  - {name: notes, label: Notes, definition: Free text., type: text}
  - {name: bmi, label: BMI, definition: Weight over height squared., type: continuous,
     derived_from: [weight], derivation: weight over height squared}
"""


def dictionary(root: Path, text: str = ENTRIES):
    path = root / DICTIONARY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    read, report = load_dictionary(root)
    assert read is not None, report.findings
    return read


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_redcap_s_eighteen_columns_in_its_order(tmp_path: Path) -> None:
    written = redcap(dictionary(tmp_path))
    header = next(csv.reader(io.StringIO(written.text)))
    assert header == list(REDCAP_COLUMNS) and len(header) == 18
    assert header[0] == "Variable / Field Name" and header[-1] == "Field Annotation"


def test_the_record_s_identifier_is_the_first_field_and_its_form_the_first(
    tmp_path: Path,
) -> None:
    fields = rows(redcap(dictionary(tmp_path)).text)
    assert [f["Variable / Field Name"] for f in fields] == [
        "record_id", "weight", "sex", "pregnant", "seen_at", "dose_time", "visit_date",
        "phq9_1", "falls", "notes",
    ]  # fmt: skip
    assert [f["Form Name"] for f in fields][:5] == ["baseline"] * 4 + ["follow_up"]
    assert fields[-1]["Form Name"] == "data"


def test_each_type_is_written_as_redcap_takes_it(tmp_path: Path) -> None:
    fields = {f["Variable / Field Name"]: f for f in rows(redcap(dictionary(tmp_path)).text)}
    kind = {name: (f["Field Type"], f["Text Validation Type OR Show Slider Number"],
                   f["Text Validation Min"], f["Text Validation Max"])
            for name, f in fields.items()}  # fmt: skip
    assert kind == {
        "record_id": ("text", "", "", ""),
        "weight": ("text", "number", "30", "250.5"),
        "sex": ("radio", "", "", ""),
        "pregnant": ("radio", "", "", ""),
        "seen_at": ("text", "datetime_ymd", "2026-01-01 08:00", "2026-12-31 18:30"),
        "dose_time": ("text", "time", "06:00", "22:30"),
        "visit_date": ("text", "date_ymd", "2026-01-01", "2026-12-31"),
        "phq9_1": ("radio", "", "", ""),
        "falls": ("text", "integer", "", ""),
        "notes": ("text", "", "", ""),
    }
    sex = fields["sex"]
    assert sex["Choices, Calculations, OR Slider Labels"] == "1, Male | 2, Female | 9, not stated"
    assert sex["Field Label"] == "What sex were you recorded at birth?"
    assert sex["Field Note"] == "missing: 9 not stated"
    assert sex["Field Annotation"] == "Sex recorded at birth."
    assert fields["pregnant"]["Choices, Calculations, OR Slider Labels"] == "1, Yes | 0, No"
    assert fields["pregnant"]["Branching Logic (Show field only if...)"] == "[sex] = '2'"
    assert fields["weight"]["Required Field?"] == "y" and fields["sex"]["Required Field?"] == ""
    assert fields["weight"]["Field Note"] == "unit: kg"


def test_a_condition_on_several_codes_is_one_branching_logic(tmp_path: Path) -> None:
    text = ENTRIES.replace("in: [2]", "in: [1, 2]")
    fields = {f["Variable / Field Name"]: f for f in rows(redcap(dictionary(tmp_path, text)).text)}
    assert fields["pregnant"]["Branching Logic (Show field only if...)"] == \
        "[sex] = '1' or [sex] = '2'"  # fmt: skip


def test_what_redcap_cannot_hold_is_left_out_and_said(tmp_path: Path) -> None:
    text = ENTRIES.replace("type: text}", "type: text, pattern: '^[A-Z]+$'}")
    written = redcap(dictionary(tmp_path, text))
    assert "bmi" not in written.text.split("\r\n", 1)[1]
    assert written.left_out == ("bmi: derived, computed by the analysis",
                                "notes: its pattern is not a REDCap validation")  # fmt: skip


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("{name: record_id, label: Record, definition: The record's number., type: identifier",
         "{name: record_id, label: Record, definition: The record's number., type: text",
         "no variable the form collects is of type identifier"),
        ("{name: falls,", "{name: Falls,", "and not Falls"),
        ("{name: notes,", "{name: notes.free,", "and not notes.free"),
        ("{code: 2, label: Female}]", "{code: 2, label: Female}]\n    form: Baseline", None),
        ("    values: [{code: 1, label: Male}, {code: 2, label: Female}]\n", "",
         "sex has no codes yet"),
    ],
)  # fmt: skip
def test_what_redcap_would_take_otherwise_is_refused(tmp_path: Path, old, new, said) -> None:
    assert old in ENTRIES, old
    text = ENTRIES.replace(old, new, 1)
    if said is None:  # a form id REDCap cannot take is the schema's to refuse
        path = tmp_path / DICTIONARY
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        assert load_dictionary(tmp_path)[0] is None
        return
    with pytest.raises(ExportRefused, match=said):
        redcap(dictionary(tmp_path, text))


def test_a_bound_is_written_with_every_digit_it_has(tmp_path: Path) -> None:
    """Round 1: `:g` kept six digits, and REDCap was given 1.23457e+06 for 1234567.5."""
    text = ENTRIES.replace("range: {min: 30, max: 250.5}",
                           "range: {min: 0.1234567, max: 1234567.5}")
    fields = {f["Variable / Field Name"]: f for f in rows(redcap(dictionary(tmp_path, text)).text)}
    assert (fields["weight"]["Text Validation Min"], fields["weight"]["Text Validation Max"]) \
        == ("0.1234567", "1234567.5")  # fmt: skip


def test_a_small_bound_is_written_in_positional_notation(tmp_path: Path) -> None:
    text = ENTRIES.replace("range: {min: 30, max: 250.5}", "range: {min: 0.00001, max: 250.5}")
    fields = {f["Variable / Field Name"]: f for f in rows(redcap(dictionary(tmp_path, text)).text)}
    assert fields["weight"]["Text Validation Min"] == "0.00001"


def test_a_bound_is_written_in_the_form_redcap_s_validation_reads(tmp_path: Path) -> None:
    text = ENTRIES.replace("min: '2026-01-01T08:00:00'", "min: '2026-01-01'")
    text = text.replace("min: '06:00'", "min: '06:00:00'")
    fields = {f["Variable / Field Name"]: f for f in rows(redcap(dictionary(tmp_path, text)).text)}
    assert fields["seen_at"]["Text Validation Min"] == "2026-01-01 00:00"
    assert fields["dose_time"]["Text Validation Min"] == "06:00"


@pytest.mark.parametrize(
    "old, new, said",
    [
        ("{code: 2, label: Female}", "{code: 2, label: Female | other}", "Female | other"),
        ("{code: 2, label: Female}", "{code: 'a,b', label: Female}", "a,b"),
        ("{code: 2, label: Female}", "{code: 'it''s', label: Female}", "it's"),
        ("{code: 2, label: Female}", "{code: 'a b', label: Female}", "a b"),
    ],
)  # fmt: skip
def test_a_code_or_label_that_would_split_redcap_s_choices_is_refused(
    tmp_path: Path, old: str, new: str, said: str
) -> None:
    """Round 1: `1, Weekly | monthly` was three choices to REDCap."""
    text = ENTRIES.replace(old, new).replace("applies_if: {variable: sex, in: [2]}, ", "")
    with pytest.raises(ExportRefused, match=re.escape(said)):
        redcap(dictionary(tmp_path, text))


def test_a_condition_on_a_variable_the_file_leaves_out_is_refused(tmp_path: Path) -> None:
    """A derived variable is not in REDCap's file, so a branching logic naming it names
    nothing."""
    text = ENTRIES + ("  - {name: older, label: Older, definition: Aged 65 or over., "
                      "type: binary, code_list: yes_no, derived_from: [weight], "
                      "derivation: from the date of birth}\n"
                      "  - {name: frail, label: Frail, definition: Frail., type: binary, "
                      "code_list: yes_no, applies_if: {variable: older, in: [1]}}\n")
    with pytest.raises(ExportRefused, match="frail is asked under older"):
        redcap(dictionary(tmp_path, text))


def test_the_outline_keeps_an_item_as_it_is_numbered(tmp_path: Path) -> None:
    """Round 1: `capitalize()` printed item A1 as "a1"."""
    text = outline(dictionary(tmp_path, ENTRIES.replace("item: 1,", "item: A1,"))).text
    assert "*Item A1 of Patient Health Questionnaire-9:" in text


def test_the_outline_shows_one_bound_alone(tmp_path: Path) -> None:
    text = outline(dictionary(tmp_path, ENTRIES.replace("type: count,\n",
                                                        "type: count, range: {min: 0},\n")))
    assert "   ____ (count, from 0)" in text.text


def test_the_plain_csv_has_one_row_per_variable_and_a_column_per_key(tmp_path: Path) -> None:
    from manuscript_guard.contracts._schema import load_schema

    written = plain_csv(dictionary(tmp_path))
    found = rows(written.text)
    assert list(found[0]) == list(CSV_COLUMNS)
    assert [row["name"] for row in found][-1] == "bmi" and len(found) == 11
    keys = set(load_schema("data-dictionary")["$defs"]["variable"]["properties"])
    # Two keys are written as others: a code list as its codes, a range as its two bounds.
    assert set(CSV_COLUMNS) == keys - {"code_list", "range"} | {"min", "max"}
    sex = next(row for row in found if row["name"] == "sex")
    assert (sex["values"], sex["missing"]) == ("1, Male | 2, Female", "9, not stated")
    pregnant = next(row for row in found if row["name"] == "pregnant")
    assert (pregnant["values"], pregnant["applies_if"]) == ("1, Yes | 0, No", "sex in 2")
    assert next(row for row in found if row["name"] == "bmi")["derived_from"] == "weight"


def test_the_outline_is_the_form_in_its_order(tmp_path: Path) -> None:
    text = outline(dictionary(tmp_path)).text
    assert text.startswith("# Case report form\n\n## Baseline visit\n\n"
                           "When: at enrolment. Recorded by: research nurse.\n")  # fmt: skip
    assert text.index("## Baseline visit") < text.index("## Follow-up visit") \
        < text.index("## Other variables") < text.index("## Derived, not asked")  # fmt: skip
    assert "3. **What sex were you recorded at birth?** (`sex`)" in text
    assert "   - [ ] Female (2)\n   - [ ] not stated (9, missing)" in text
    assert "   *Asked only where Sex is Female.*" in text
    assert "   ____ (continuous, kg, 30 to 250.5)" in text
    assert "*Item 1 of Patient Health Questionnaire-9: the wording and the responses are " \
        "the licensed instrument's.*" in text  # fmt: skip
    assert "- **BMI** (`bmi`): weight over height squared; from `weight`." in text


def test_the_command_writes_each_file_and_says_what_it_left_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "paper.yaml").write_bytes(PAPER.encode("utf-8"))
    dictionary(tmp_path)
    out = tmp_path / "out"
    code = main(["dictionary", str(tmp_path), "--redcap", str(out / "redcap.csv"),
                 "--csv", str(out / "plain.csv"), "--outline", str(out / "form.md")])
    assert code == 0
    printed = capsys.readouterr().out
    assert "bmi: derived, computed by the analysis" in printed
    assert (out / "redcap.csv").read_bytes().startswith(b"Variable / Field Name,Form Name,")
    assert (out / "plain.csv").read_bytes().startswith(b"name,label,definition,")
    assert (out / "form.md").read_text(encoding="utf-8").startswith("# Case report form")


def test_the_command_refuses_with_nothing_to_write_or_nothing_to_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "paper.yaml").write_bytes(PAPER.encode("utf-8"))
    assert main(["dictionary", str(tmp_path), "--csv", str(tmp_path / "x.csv")]) == 2
    assert "design/data_dictionary.yaml" in capsys.readouterr().err
    assert main(["dictionary", str(tmp_path)]) == 2
    assert "--redcap, --csv or --outline" in capsys.readouterr().err
    path = tmp_path / DICTIONARY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ENTRIES.replace("code_list: yes_no", "code_list: no_yes").encode("utf-8"))
    assert main(["dictionary", str(tmp_path), "--csv", str(tmp_path / "x.csv")]) == 1
    assert "its code list no_yes is not in the dictionary" in capsys.readouterr().out
    assert not (tmp_path / "x.csv").exists()
    dictionary(tmp_path, ENTRIES.replace("type: identifier", "type: text"))
    assert main(["dictionary", str(tmp_path), "--redcap", str(tmp_path / "r.csv")]) == 1
    assert "identifier" in capsys.readouterr().err and not (tmp_path / "r.csv").exists()
