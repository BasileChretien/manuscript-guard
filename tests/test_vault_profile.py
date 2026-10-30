"""`em.profile`: what the profile of a file of the vault gives of each column, and holds back.

The R emitter is held to the same bytes in `tests/test_r_profile.py`; what the profile owes
the custodian over generated tables (no level under the minimum, no centile with fewer rows on
a side, no count a total gives away, no smallest or largest value) in
`tests/test_properties.py`; the synthetic copy drawn from it in
`tests/test_vault_synthesize.py`.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from manuscript_guard.contracts._schema import validate
from manuscript_guard.contracts.dictionary import load_dictionary
from manuscript_guard.emit import Emitter
from manuscript_guard.gates.custodian import recoverable_counts
from manuscript_guard.vault import profile as profiling

FIXTURE = Path(__file__).parent / "data" / "profile"
READ_AS = {"dates": {"discharged": "%d/%m/%Y"}}


def rows_of(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def made(**columns: list) -> dict:
    return profiling.profile(columns, name="t.csv", minimum=5)


def typed(**columns: list) -> dict:
    """The profile of columns the dictionary types continuous."""
    from manuscript_guard.contracts.dictionary import Dictionary, Variable

    variables = tuple(Variable(name, name, "d", "continuous") for name in columns)
    return profiling.profile(columns, name="t.csv", minimum=5,
                             dictionary=Dictionary(Path("d.yaml"), variables))  # fmt: skip


def column(document: dict, name: str) -> dict:
    return next(one for one in document["columns"] if one["name"] == name)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The shared fixture's project, copied: its paper.yaml, dictionary and table."""
    root = tmp_path / "cohort"
    shutil.copytree(FIXTURE, root)
    (root / "analysis").mkdir()
    (root / "analysis" / "profile.py").write_text("", encoding="utf-8")
    return root


# ------------------------------------------------------------------- the shared fixture


def test_the_shared_table_gives_the_expected_bytes(project: Path) -> None:
    """The bytes R is held to as well (`tests/test_r_profile.py`)."""
    em = Emitter(project / "analysis" / "profile.py")
    read_as = {**READ_AS, "header_of": project / "cohort.csv"}
    written = em.profile(rows_of(project / "cohort.csv"), name="cohort.csv", read_as=read_as)
    assert written == project / "profiles" / "data" / "cohort.csv.profile.json"
    assert written.read_bytes() == (FIXTURE / "expected.profile.json").read_bytes()


def test_the_expected_profile_is_one_by_its_schema() -> None:
    document = json.loads((FIXTURE / "expected.profile.json").read_text(encoding="utf-8"))
    assert validate(document, "data-profile", FIXTURE).ok


def test_a_data_frame_gives_the_bytes_a_list_of_rows_does(project: Path) -> None:
    pandas = pytest.importorskip("pandas")
    rows = rows_of(project / "cohort.csv")
    frame = pandas.read_csv(project / "cohort.csv", dtype=str, keep_default_na=False)
    dictionary, _ = load_dictionary(project)
    one, two = (profiling.profile(table, name="cohort.csv", minimum=5, dictionary=dictionary,
                                  read_as=READ_AS) for table in (rows, frame))  # fmt: skip
    assert profiling.dumps(one) == profiling.dumps(two)


# ------------------------------------------------------------------------------ levels


def test_a_level_under_the_minimum_is_folded_into_other_and_its_count_held() -> None:
    found = column(made(group=["a"] * 9 + ["b"] * 6 + ["c"] * 2 + ["d"] * 1 + ["e"] * 4), "group")
    assert found["kind"] == "levels"
    assert [level["level"] for level in found["levels"]] == ["a", "b"]
    assert found["other"] == {"levels": 3, "count": 7}


def test_a_count_the_total_gives_away_is_held_beside_the_smallest_printed() -> None:
    """Rows 18, a 9, b 6, other 3: the 3 is printed "<5", and 18 less 9 and 6 would give it
    away, so the 6 is held back too."""
    found = column(made(group=["a"] * 9 + ["b"] * 6 + ["c"] * 2 + ["d"]), "group")
    assert found["levels"] == [{"level": "a", "count": 9}, {"level": "b", "count": None}]
    assert found["other"] == {"levels": 2, "count": "<5"}
    assert found["missing"] == 0


def test_two_counts_held_whose_sum_leaves_each_open_are_not_held_further() -> None:
    found = column(made(group=["a"] * 9 + ["c"] * 2 + [""] * 3), "group")
    assert found["levels"] == [{"level": "a", "count": 9}]
    assert found["other"] == {"levels": 1, "count": "<5"}
    assert found["missing"] == "<5"


def test_the_dictionary_types_a_column_and_orders_its_levels(tmp_path: Path) -> None:
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "data_dictionary.yaml").write_text(
        "schema: manuscript-guard/data-dictionary/1\nvariables:\n"
        "  - {name: grade, label: G, definition: d, type: ordinal, values: "
        "[{code: low, label: l}, {code: mid, label: m}, {code: high, label: h}]}\n",
        encoding="utf-8")  # fmt: skip
    dictionary, _ = load_dictionary(tmp_path)
    document = profiling.profile({"grade": ["high"] * 5 + ["low"] * 6 + ["mid"] * 7},
                                 name="t.csv", minimum=5, dictionary=dictionary)  # fmt: skip
    found = column(document, "grade")
    assert (found["type"], found["typed_by"]) == ("ordinal", "dictionary")
    assert [level["level"] for level in found["levels"]] == ["low", "mid", "high"]


def test_missing_codes_and_blanks_are_missing_and_a_share_is_given_from_the_minimum() -> None:
    found = column(made(x=["a"] * 10 + [""] * 5 + [None] * 5), "x")
    assert found["missing"] == 10
    assert float(found["missing_share"]) == 0.5
    held = column(made(x=["a"] * 10 + ["b"] * 10 + [""] * 2), "x")
    assert held["missing"] == "<5" and "missing_share" not in held


# --------------------------------------------------------------------- numbers and dates


def test_numbers_give_a_mean_an_sd_and_centiles_with_enough_rows_each_side() -> None:
    values = [str(number) for number in range(1, 61)] * 2 + ["1.5"]
    found = column(made(x=values), "x")
    assert found["kind"] == "number" and found["n"] == 121
    assert float(found["mean"]) == pytest.approx(sum(float(v) for v in values) / 121, 1e-5)
    assert set(found["centiles"]) == {"5", "10", "25", "50", "75", "90", "95"}
    assert found["decimals"] == 0
    assert "1" not in found["centiles"].values() and "60" not in found["centiles"].values()


def test_a_centile_with_fewer_than_the_minimum_beside_it_is_not_given() -> None:
    values = ["1"] * 20 + [str(number) for number in range(2, 62)] * 2 + ["99"] * 12
    found = column(made(x=values), "x")
    centiles = found["centiles"]
    assert "5" not in centiles and "10" not in centiles
    assert "95" not in centiles and "90" in centiles and "25" in centiles


def test_a_value_that_is_no_number_is_unread_and_few_rows_give_no_mean() -> None:
    found = column(typed(x=[str(n) for n in range(60)] + ["n/a", "?"]), "x")
    assert found["unread"] == "<5"
    small = column(typed(x=["1", "2", "3", "4"] + [""] * 20), "x")
    assert small["n"] == "<5" and "mean" not in small and small["centiles"] == {}


def test_dates_are_given_to_the_month_and_a_format_reads_them(tmp_path: Path) -> None:
    days = [f"{day:02d}/{month:02d}/2019" for month in range(1, 13) for day in (3, 14, 25)] * 2
    document = profiling.profile({"seen": days}, name="t.csv", minimum=5,
                                 read_as={"dates": {"seen": "%d/%m/%Y"}})  # fmt: skip
    found = column(document, "seen")
    assert (found["type"], found["kind"], found["format"]) == ("date", "date", "%d/%m/%Y")
    assert found["centiles"]["50"] == "2019-06"
    assert all(len(value) == 7 for value in found["centiles"].values())


def test_times_are_given_to_the_hour() -> None:
    found = column(made(at=[f"{hour:02d}:{minute:02d}" for hour in range(6, 20)
                            for minute in (5, 35, 50, 55)] * 2), "at")  # fmt: skip
    assert found["kind"] == "time"
    assert all(value.endswith(":00") for value in found["centiles"].values())


# -------------------------------------------------------------------------- withheld


def test_a_column_of_different_values_is_withheld_with_the_pattern_they_share() -> None:
    found = column(made(id=[f"PT-{n:04d}" for n in range(30)]), "id")
    assert found == {"name": "id", "type": "text", "typed_by": "values", "kind": "withheld",
                     "missing": 0, "pattern": "AA-9999"}  # fmt: skip
    mixed = column(made(id=[f"P{n}" for n in range(30)]), "id")
    assert "pattern" not in mixed


def test_many_different_texts_are_withheld_and_few_are_levels() -> None:
    many = [f"w{n % 60}" for n in range(120)]
    assert column(made(x=many), "x")["kind"] == "withheld"
    assert column(made(x=[f"w{n % 50}" for n in range(120)]), "x")["kind"] == "levels"


def test_a_pattern_is_given_only_from_the_minimum() -> None:
    found = column(made(id=["AB1", "CD2", "EF3"] + [""] * 20), "id")
    assert "pattern" not in found


# ------------------------------------------------------------------------- the file


def test_the_header_is_sniffed_and_read_as_says_the_rest(tmp_path: Path) -> None:
    file = tmp_path / "x.csv"
    file.write_bytes(b"\xef\xbb\xbfa;b;c\r\n1,5;2;3\r\n")
    shape, _ = profiling.file_shape("x.csv", {"header_of": file, "decimal": ","})
    assert shape == {"format": "csv", "delimiter": ";", "decimal": ",",
                     "encoding": "utf-8-sig", "quoting": "minimal", "newline": "\r\n"}  # fmt: skip
    assert profiling.file_shape("x.tsv", None)[0]["delimiter"] == "\t"
    assert profiling.file_shape("x.xlsx", None)[0]["format"] == "xlsx"


@pytest.mark.parametrize("read_as", [
    {"sheet": 1}, {"decimal": ";"}, {"quoting": "some"}, {"dates": {"a": "%d %b %Y"}},
    {"dates": {"a": "%Y-%m"}}, {"dates": ["a"]}, {"newline": "\r"},
])  # fmt: skip
def test_what_read_as_cannot_say_is_refused(read_as: dict) -> None:
    with pytest.raises(ValueError, match="profile: "):
        profiling.profile({"a": ["1"]}, name="t.csv", minimum=5, read_as=read_as)


@pytest.mark.parametrize("name", ["", "/abs.csv", "../up.csv", "a/../b.csv", "C:/x.csv",
                                  "a\\b.csv", " pad.csv", "dir/"])  # fmt: skip
def test_a_name_that_is_no_file_of_the_vault_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="profile: "):
        profiling.profile({"a": ["1"]}, name=name, minimum=5)


def test_a_project_with_no_custodian_minimum_is_refused(tmp_path: Path) -> None:
    (tmp_path / "paper.yaml").write_text("title: x\n", encoding="utf-8")
    (tmp_path / "analysis").mkdir()
    em = Emitter(tmp_path / "analysis" / "p.py", root=tmp_path)
    with pytest.raises(ValueError, match="minimum_cell_count"):
        em.profile({"a": ["1"]}, name="t.csv")
    assert not (tmp_path / "profiles").exists()


def test_a_table_with_fewer_rows_than_the_minimum_holds_back_its_rows() -> None:
    document = made(x=["a", "b", "a"])
    assert document["rows"] == "<5"
    assert column(document, "x")["levels"] == []


# ------------------------------------------------------------- the custodian's reading


@pytest.mark.parametrize(("total", "shown", "found"), [
    (20, [12, "<5", 5], [1]),
    (20, [12, "<5", None], []),
    (19, [12, "<5", "<5"], []),
    (20, [12, "<5", "<5"], [1, 2]),
    (8, ["<5", "<5"], [0, 1]),
    (20, [20, 0], []),
])  # fmt: skip
def test_a_count_held_back_is_given_away_only_by_a_line_that_closes_on_it(
    total: int, shown: list, found: list
) -> None:
    assert recoverable_counts(total, shown, 5) == found
