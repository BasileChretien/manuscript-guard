"""The data-quality checks: a table held to the data dictionary, counts emitted, no values.

`tests/data/quality` holds one dictionary, one table that breaks each check at least once,
and the rows each count must find. The R emitter is held to the same file
(`tests/test_r_quality.py`), so that a count means the same in either language.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from manuscript_guard import quality
from manuscript_guard.contracts.dictionary import Dictionary, Variable, load_dictionary
from manuscript_guard.emit import Emitter

DATA = Path(__file__).parent / "data" / "quality"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def dictionary() -> Dictionary:
    return quality.read_dictionary(DATA)


def build(root: Path, variables: list[dict], **top: object) -> Dictionary:
    """A dictionary of these entries, read by the loader the checks read it with, so that
    each is one the loader takes."""
    entries = [{"label": e["name"], "definition": "As recorded.", **e} for e in variables]
    document = {"schema": "manuscript-guard/data-dictionary/1", **top, "variables": entries}
    (root / "design").mkdir(parents=True, exist_ok=True)
    (root / "design" / "data_dictionary.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    loaded, report = load_dictionary(root)
    assert loaded is not None and not report.findings, report.findings
    return loaded


def var(name: str = "x", **given: object) -> Variable:
    return Variable(name=name, label=name, definition="As recorded.", **given)  # type: ignore[arg-type]


NONE = Dictionary(path=Path("design/data_dictionary.yaml"), variables=())


def found(counts: list[quality.Count]) -> dict[str, list[int]]:
    return {count.key: list(count.rows) for count in counts}


def text_rows() -> list[dict]:
    with (DATA / "reports.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def pregnant_men(rows: list[dict]) -> list[bool]:
    return [row["sex"] == "1" and row["pregnant"] == "1" for row in rows]


# ---------------------------------------------------------------- the shared table


def test_the_table_read_as_text_gives_the_expected_counts() -> None:
    rows = text_rows()
    total, counts = quality.check(
        dictionary(), rows, computed={"no_pregnant_men": pregnant_men(rows)}
    )
    assert total == EXPECTED["rows"]
    assert found(counts) == EXPECTED["counts"]


def test_the_table_as_columns_gives_the_same_counts() -> None:
    rows = text_rows()
    columns = {name: [row[name] for row in rows] for name in rows[0]}
    _total, counts = quality.check(
        dictionary(), columns, computed={"no_pregnant_men": pregnant_men(rows)}
    )
    assert found(counts) == EXPECTED["counts"]


def test_the_table_as_pandas_types_it_gives_the_same_counts() -> None:
    """pandas reads the version 1.0 as a float, a blank weight as NaN, sex as an integer:
    each is read as the text reader reads its own."""
    pandas = pytest.importorskip("pandas")
    frame = pandas.read_csv(DATA / "reports.csv")
    assert str(frame["version"].dtype) == "float64" and str(frame["sex"].dtype) == "int64"
    mask = ((frame["sex"] == 1) & (frame["pregnant"] == 1)).tolist()
    total, counts = quality.check(dictionary(), frame, computed={"no_pregnant_men": mask})
    assert total == EXPECTED["rows"]
    assert found(counts) == EXPECTED["counts"]


def test_the_counts_are_in_the_dictionary_s_order() -> None:
    rows = text_rows()
    _total, counts = quality.check(
        dictionary(), rows, computed={"no_pregnant_men": pregnant_men(rows)}
    )
    assert [count.key for count in counts] == list(EXPECTED["counts"])


# ---------------------------------------------------------------- how a value is read


@pytest.mark.parametrize(
    ("item", "text"),
    [
        (True, "true"),
        (3, "3"),
        (3.0, "3"),
        (-0.0, "0"),
        (0.1, "0.1"),
        (1 / 3, "0.333333333333333"),
        (2.0**53 - 1, "9007199254740991"),
        (2.0**53, "9.00719925474099e+15"),
        (1e20, "1e+20"),
        (10**20, "100000000000000000000"),
        (math.inf, "inf"),
        (date(2016, 2, 1), "2016-02-01"),
        (datetime(2016, 2, 1, 8, 30, 15, 999), "2016-02-01T08:30:15"),
        (datetime(2016, 2, 1, 8, 30, tzinfo=timezone(timedelta(hours=2))), "2016-02-01T08:30:00"),
        ("01", "01"),
    ],
)
def test_a_value_as_text(item: object, text: str) -> None:
    assert quality.text_of(item) == text


@pytest.mark.parametrize(
    ("item", "number"),
    [
        ("3", 3.0),
        (" 3.5 ", 3.5),
        ("-1e3", -1000.0),
        (".5", 0.5),
        (7, 7.0),
        ("abc", None),
        ("1,5", None),
        ("1e999", None),
        (math.nan, None),
        (True, None),
        ("\N{ARABIC-INDIC DIGIT ONE}", None),
        ("1_000", None),
    ],
)
def test_a_value_as_a_number(item: object, number: float | None) -> None:
    assert quality.number_of(item) == number


@pytest.mark.parametrize(
    ("item", "day"),
    [
        ("2016-02-01", "2016-02-01"),
        ("2016-02-30", None),
        ("0000-01-01", None),
        ("20160201", None),
        ("2016-2-1", None),
        (date(2016, 2, 1), "2016-02-01"),
        (datetime(2016, 2, 1, 23, 59), "2016-02-01"),
        ("2016-02-01T08:00", None),
        (20160201, None),
    ],
)
def test_a_value_as_a_date(item: object, day: str | None) -> None:
    assert quality.date_of(item) == day


@pytest.mark.parametrize(
    ("item", "when"),
    [
        ("2016-02-01 08:00", "2016-02-01T08:00:00"),
        ("2016-02-01T08:00:59.5", "2016-02-01T08:00:59"),
        ("2016-02-01T08:00:00+02:00", "2016-02-01T08:00:00"),
        ("2016-02-01T08:00Z", "2016-02-01T08:00:00"),
        ("2016-02-01T24:00", None),
        ("2016-02-01T08:60", None),
        ("2016-02-01", None),
        (date(2016, 2, 1), "2016-02-01T00:00:00"),
    ],
)
def test_a_value_as_a_date_and_time(item: object, when: str | None) -> None:
    assert quality.datetime_of(item) == when


@pytest.mark.parametrize(
    ("item", "when"),
    [
        ("08:00", "08:00:00"),
        ("23:59:59", "23:59:59"),
        ("08:00:00.5", "08:00:00"),
        ("08:00.5", None),
        ("8:00", None),
        ("24:00", None),
        (time(8, 0), "08:00:00"),
    ],
)
def test_a_value_as_a_time(item: object, when: str | None) -> None:
    assert quality.time_of(item) == when


@pytest.mark.parametrize("item", [None, math.nan, "", "  \t", "-99", -99, -99.0])
def test_a_missing_value(item: object) -> None:
    assert quality.absent(item, frozenset({"-99"}))


@pytest.mark.parametrize("item", ["NA", "0", 0, "\N{NO-BREAK SPACE}", False])
def test_a_value_that_is_there(item: object) -> None:
    """A text "NA" is a value unless the dictionary lists it as a missing code; nought and
    false are values."""
    assert not quality.absent(item, frozenset({"-99"}))


# ---------------------------------------------------------------- one variable


def test_codes_compare_as_text(tmp_path: Path) -> None:
    coded = [{"name": "x", "type": "categorical",
              "values": [{"code": 1, "label": "a"}, {"code": "02", "label": "b"}]}]  # fmt: skip
    dictionary = build(tmp_path, coded)
    result = quality.check_variable(
        dictionary.variables[0], [1, "1", 1.0, "02", 2, "2"], dictionary
    )
    assert result["not_allowed"] == [4, 5]


def test_a_coded_variable_with_no_codes_yet_is_not_asked_for_them() -> None:
    assert quality.checks_of(var(type="categorical"), NONE) == ("missing",)


def test_a_pattern_matches_the_whole_value_in_ascii() -> None:
    coded = var(type="identifier", pattern="R[0-9]{2}|S" + chr(92) + "d")
    values = ["R01", "R012", "xR01", "S1", "S" + chr(0x0661)]
    assert quality.check_variable(coded, values, NONE)["not_matching"] == [1, 2, 4]


def test_a_count_is_a_whole_number_from_nought() -> None:
    result = quality.check_variable(var(type="count"), [0, "3", "3.0", 2.5, -1, "x"], NONE)
    assert result["wrong_type"] == [3, 4, 5]


def test_a_range_holds_both_bounds() -> None:
    ranged = var(type="continuous", minimum=0, maximum=10)
    result = quality.check_variable(ranged, [0, 10, -0.1, 10.5, "x"], NONE)
    assert result == {"missing": [], "wrong_type": [4], "out_of_range": [2, 3]}


def test_a_date_range_is_read_as_dates() -> None:
    ranged = var(type="date", minimum="2016-01-01")
    values = ["2015-12-31", "2016-01-01", date(2015, 1, 1)]
    assert quality.check_variable(ranged, values, NONE)["out_of_range"] == [0, 2]


def test_a_range_bound_that_is_not_of_the_type_is_refused() -> None:
    """The loader refuses it first; the checks do not read a bound they cannot."""
    with pytest.raises(ValueError, match="range min"):
        quality.check_variable(var(type="date", minimum="soon"), ["2016-01-01"], NONE)


def test_the_study_period_needs_the_dictionary_to_give_one() -> None:
    dated = var(type="date", within_study_period=True)
    assert "outside_period" not in quality.check_variable(dated, ["2016-01-01"], NONE)
    period = Dictionary(
        path=NONE.path, variables=(dated,), study_period=("2016-01-01", "2016-12-31")
    )
    result = quality.check_variable(dated, ["2016-01-01", "2016-12-31", "2017-01-01"], period)
    assert result["outside_period"] == [2]


def test_a_variable_that_does_not_apply_is_not_missing(tmp_path: Path) -> None:
    """Asked only of women: blank for a man is as it should be, a value for a man is
    counted, and a blank where the sex is not known is neither."""
    dictionary = build(
        tmp_path,
        [
            {"name": "sex", "type": "binary",
             "values": [{"code": 1, "label": "m"}, {"code": 2, "label": "f"}]},
            {"name": "pregnant", "type": "binary",
             "values": [{"code": 0, "label": "n"}, {"code": 1, "label": "y"}],
             "applies_if": {"variable": "sex", "in": [2]}},
        ],
    )  # fmt: skip
    table = {"sex": ["1", "2", "2", "1", ""], "pregnant": ["", "", "1", "0", ""]}
    _total, counts = quality.check(dictionary, table)
    got = found(counts)
    assert got["pregnant.missing"] == [1]
    assert got["pregnant.not_applicable"] == [3]


# ---------------------------------------------------------------- rules


def test_an_order_rule_skips_a_row_it_cannot_read() -> None:
    start, end = var("start", type="date"), var("end", type="date")
    columns = [
        ["2016-01-01", "2016-03-01", "", "2016-02-30"],
        ["2016-02-01", "2016-02-01", "2016-01-01", "2016-01-01"],
    ]
    assert quality.check_order([start, end], columns) == [1]


def test_an_order_rule_over_a_date_and_a_date_and_time_compares_days() -> None:
    start, end = var("start", type="date"), var("end", type="datetime")
    columns = [["2016-02-01", "2016-02-02"], ["2016-02-01 08:00", "2016-02-01 23:00"]]
    assert quality.check_order([start, end], columns) == [1]


def test_an_order_rule_over_two_families_is_refused() -> None:
    with pytest.raises(ValueError, match="numbers, dates or times"):
        quality.check_order([var(type="date"), var(type="count")], [["2016-01-01"], [3]])


def test_a_key_counts_each_repeat_after_the_first() -> None:
    one, two = var("id", type="identifier"), var("v", type="count")
    columns = [["a", "a", "a", "b", "", "a"], ["1", "1.0", "2", "1", "1", 1]]
    assert quality.check_unique([one, two], columns) == [1, 5]


def test_a_computed_rule_takes_one_truth_value_for_each_row() -> None:
    table = {"report_id": ["R0001", "R0002"]}
    with pytest.raises(ValueError, match="1 truth values for a table of 2 rows"):
        quality.check(dictionary(), table, computed={"no_pregnant_men": [True]})
    with pytest.raises(ValueError, match="other than true or false"):
        quality.check(dictionary(), table, computed={"no_pregnant_men": [True, None]})
    with pytest.raises(ValueError, match="no rule 'nobody'"):
        quality.check(dictionary(), table, computed={"nobody": [True, False]})
    with pytest.raises(ValueError, match="is not `computed: true`"):
        quality.check(dictionary(), table, computed={"start_before_onset": [True, False]})


def test_a_rule_is_checked_only_where_the_table_holds_its_variables() -> None:
    _total, counts = quality.check(dictionary(), {"drug_start": ["2016-01-01"]})
    assert "rule.start_before_onset" not in found(counts)


# ---------------------------------------------------------------- the table


def test_a_variable_with_no_column_is_not_checked() -> None:
    _total, counts = quality.check(dictionary(), {"age": ["34"], "other": ["x"]})
    assert set(found(counts)) == {"age.missing", "age.wrong_type", "age.out_of_range"}


def test_a_table_with_none_of_the_columns_is_refused() -> None:
    with pytest.raises(ValueError, match="no column the data dictionary lists"):
        quality.check(dictionary(), {"other": ["x"]})


def test_columns_of_two_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="not all of one length"):
        quality.check(dictionary(), {"age": ["1", "2"], "sex": ["1"]})


def test_a_dictionary_in_datasets_is_checked_one_at_a_time(tmp_path: Path) -> None:
    split = build(
        tmp_path,
        [
            {"name": "age", "type": "continuous", "dataset": "demo"},
            {"name": "dose", "type": "continuous", "dataset": "drug"},
        ],
        datasets=[{"id": "demo", "label": "D"}, {"id": "drug", "label": "R"}],
    )
    _total, counts = quality.check(split, {"age": [1], "dose": [2]}, dataset="drug")
    assert set(found(counts)) == {"dose.missing", "dose.wrong_type"}
    assert quality.rows_key("drug") == "rows.drug"
    with pytest.raises(ValueError, match="no dataset 'reac'; it lists demo, drug"):
        quality.check(split, {"age": [1]}, dataset="reac")


@pytest.mark.parametrize(
    ("names", "said"),
    [
        (["AGE", "age"], "AGE and age would both"),
        (["a.b", "a_b"], "a.b and a_b"),
        (["rows"], "named rows"),
        (["Rule"], "named Rule"),
    ],
)
def test_two_variables_counted_under_one_key_are_refused(
    tmp_path: Path, names: list[str], said: str
) -> None:
    clashing = build(tmp_path, [{"name": name, "type": "text"} for name in names])
    with pytest.raises(ValueError, match=said):
        quality.check(clashing, {names[0]: ["x"]})


# ---------------------------------------------------------------- the emitter


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    (root / "design").mkdir()
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n'
        "custodian:\n  minimum_cell_count: 5\n",
        encoding="utf-8",
    )
    (root / "analysis" / "run.py").write_text("# analysis\n", encoding="utf-8")
    (root / "design" / "data_dictionary.yaml").write_bytes(
        (DATA / "design" / "data_dictionary.yaml").read_bytes()
    )
    return root


def test_check_data_emits_each_count_unquoted_and_returns_the_rows(scratch: Path) -> None:
    em = Emitter(scratch / "analysis" / "run.py", root=scratch)
    rows = text_rows()
    flags = em.check_data(rows, computed={"no_pregnant_men": pregnant_men(rows)})
    assert flags == EXPECTED["counts"]
    document = json.loads(em.write().read_text(encoding="utf-8"))
    values = document["values"]
    assert values["quality.rows"] == {"value": 13, "display": "13", "quoted": False}
    assert values["quality.dose_time.wrong_type"] == {"value": 2, "display": "<5", "quoted": False}
    assert values["quality.sex.missing"]["display"] == "0"
    assert {key[len("quality.") :] for key in values} - {"rows"} == set(EXPECTED["counts"])
    inputs = [record["path"] for record in document["provenance"]["inputs"]]
    assert inputs == ["design/data_dictionary.yaml"]


def test_a_count_prints_as_itself_with_no_minimum_declared(scratch: Path) -> None:
    (scratch / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    em = Emitter(scratch / "analysis" / "run.py", root=scratch)
    em.check_data({"age": ["150", "-1"]})
    assert em.document()["values"]["quality.age.out_of_range"]["display"] == "2"


def test_check_data_checks_a_table_once(scratch: Path) -> None:
    em = Emitter(scratch / "analysis" / "run.py", root=scratch)
    em.check_data({"age": ["34"]})
    with pytest.raises(ValueError, match="emitted twice"):
        em.check_data({"age": ["34"]})


def test_a_dictionary_that_does_not_read_is_refused_with_its_line(scratch: Path) -> None:
    (scratch / "design" / "data_dictionary.yaml").write_text(
        "schema: manuscript-guard/data-dictionary/1\nvariables:\n  - name: age\n", encoding="utf-8"
    )
    em = Emitter(scratch / "analysis" / "run.py", root=scratch)
    with pytest.raises(ValueError, match="does not read: line 3: .*'label' is a required"):
        em.check_data({"age": ["34"]})


def test_no_dictionary_says_where_one_was_looked_for(scratch: Path) -> None:
    (scratch / "design" / "data_dictionary.yaml").unlink()
    em = Emitter(scratch / "analysis" / "run.py", root=scratch)
    with pytest.raises(FileNotFoundError, match="no data dictionary at"):
        em.check_data({"age": ["34"]})
