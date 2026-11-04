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
    # 7 rows in 3 levels: 7 is no whole number of 4, so how many levels is never said of it.
    assert found["other"] == {"levels": None, "count": 7}


def test_a_count_the_total_gives_away_is_held_beside_the_smallest_printed() -> None:
    """Rows 18, a 9, b 6, other 3: the 3 is printed "<5", and 18 less 9 and 6 would give it
    away, so the 6 is held back too."""
    found = column(made(group=["a"] * 9 + ["b"] * 6 + ["c"] * 2 + ["d"]), "group")
    assert found["levels"] == [{"level": "a", "count": 9}, {"level": "b", "count": None}]
    assert found["other"] == {"levels": None, "count": "<5"}
    assert found["missing"] == 0


def test_a_count_is_held_beside_wherever_one_is_held_behind_the_minimum() -> None:
    """Two counts held whose sum leaves each open: one is held beside them all the same, so
    that holding says nothing of the sum."""
    found = column(made(group=["a"] * 9 + ["c"] * 2 + [""] * 3), "group")
    assert found["levels"] == [{"level": "a", "count": None}]
    assert found["other"] == {"levels": None, "count": "<5"}
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
                     "encoding": "utf-8", "quoting": "minimal", "newline": "\r\n",
                     "bom": True}  # fmt: skip
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


@pytest.mark.parametrize(("minimum", "rows"), [(5, 3), (2, 1), (5, 0)])
def test_a_table_with_fewer_rows_than_the_minimum_is_not_profiled(minimum: int, rows: int) -> None:
    """Its rows would be a count below the minimum, and behind a minimum of 2 "<2" is 1."""
    with pytest.raises(ValueError, match="fewer rows than"):
        profiling.profile({"x": ["a"] * rows}, name="t.csv", minimum=minimum)


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


# ------------------------------------------------- round 1: counts a reader can work out


def test_a_count_held_back_is_one_or_more_since_nought_is_printed() -> None:
    """98, "<5" and "<5" of 100 rows: nought is printed as 0, so each "<5" is one to four, and
    the two make 2: each is 1. The 98 is held back beside them."""
    assert recoverable_counts(100, [98, "<5", "<5"], 5) == [1, 2]
    found = column(made(x=["a"] * 98 + ["b"] + [""]), "x")
    assert found["levels"] == [{"level": "a", "count": None}]
    assert found["other"]["count"] == "<5" and found["missing"] == "<5"


def test_the_levels_folded_into_other_bound_its_count_from_below() -> None:
    """Four levels of one row each, "<5": the count is four, so how many levels is not said,
    and the 96 beside it, which the rows would give it away by, is held back."""
    found = column(made(x=["a"] * 96 + ["b", "c", "d", "e"]), "x")
    assert found["other"] == {"levels": None, "count": "<5"}
    assert found["levels"] == [{"level": "a", "count": None}]


def test_a_column_whose_counts_cannot_be_held_enough_is_withheld() -> None:
    """Eight rows, two levels of two and four blanks: "<5" and "<5" make 8, each 4, and no
    count is printed that could be held back beside them."""
    found = column(made(x=["a", "a", "b", "b"] + [""] * 4), "x")
    assert found["kind"] == "withheld" and found["missing"] is None
    assert "levels" not in found and "other" not in found
    assert "give" in found["held"]


def test_a_held_count_of_a_minimum_of_two_is_not_printed_as_one() -> None:
    """Behind a minimum of 2, "<2" can only be 1."""
    document = profiling.profile({"x": ["a"] * 9 + ["b"]}, name="t.csv", minimum=2)
    found = column(document, "x")
    assert found["kind"] == "withheld" or found["other"]["count"] is None


def test_the_profile_records_its_dataset_and_a_byte_order_mark(tmp_path: Path) -> None:
    file = tmp_path / "x.csv"
    file.write_bytes(b"\xef\xbb\xbfid,age\n1,2\n")
    mark = chr(0xFEFF)
    document = profiling.profile({mark + "id": ["1"] * 6, "age": ["2"] * 6}, name="x.csv",
                                 minimum=5, read_as={"header_of": file})  # fmt: skip
    assert document["dataset"] is None
    assert [one["name"] for one in document["columns"]] == ["id", "age"]
    assert document["file"]["bom"] is True and document["file"]["encoding"] == "utf-8"
    plain = profiling.profile({"id": ["1"] * 6}, name="x.csv", minimum=5)
    assert plain["file"]["bom"] is False


def test_the_centile_index_is_exact_for_a_large_table() -> None:
    assert profiling._centile_index(95, 30_000_000) == 28_500_000 - 1
    assert profiling._centile_index(5, 21) == 1


# ------------------------------------------------- round 2: what the choices themselves say


def held(found: dict) -> bool:
    return found["kind"] == "withheld" and found.get("held") == profiling.HELD


def test_a_count_held_beside_is_the_minimum_or_more_and_at_most_those_after_it() -> None:
    """15 rows, a 9, b 5, c 1: b is held beside c's "<5"; a reader knows b was printed, so 5
    or more, and the smaller, so 8 at most: b is 5 and c is 1. The column is withheld."""
    assert held(column(made(x=["a"] * 9 + ["b"] * 5 + ["c"]), "x"))


def test_of_two_counts_alike_the_first_is_held_and_a_reader_knows_it() -> None:
    """a 10, b 10, and 4 rows of c: a is held, at most b's 10, and 24 rows leave c 4."""
    assert held(column(made(x=["a"] * 10 + ["b"] * 10 + ["c"] * 4), "x"))


@pytest.mark.parametrize("folded", [list("bcdefg"), ["b"] * 4 + ["c"] * 4])
def test_how_many_levels_are_folded_is_not_said_where_it_gives_their_rows(folded: list) -> None:
    """Six levels of one row, or two of four, printed beside their count: each folded
    level's rows. 6 is no whole number of 4, and 8 is two fours."""
    found = column(made(x=["a"] * (100 - len(folded)) + folded), "x")
    assert found["other"]["levels"] is None and isinstance(found["other"]["count"], int)


def test_how_many_levels_are_folded_is_said_where_it_gives_nothing() -> None:
    """12 rows in 4 levels of 1, 2, 4 and 5... of under 5 each: 12 is three fours, and 4
    levels are neither 12 nor 3, so saying 4 leaves each level's rows open."""
    found = column(made(x=["a"] * 88 + ["b"] + ["c"] * 3 + ["d"] * 4 + ["e"] * 4), "x")
    assert found["other"] == {"levels": 4, "count": 12}


def test_how_many_levels_a_held_count_folds_is_never_said() -> None:
    for folded in (["b"], ["b", "c"], list("bcd"), list("bcde")):
        found = column(made(x=["a"] * 96 + folded), "x")
        assert found["other"]["levels"] is None, folded


def test_dictionary_codes_whose_folded_rows_are_given_withhold_the_column(tmp_path: Path) -> None:
    """Three codes, two of four rows folded: 8 rows in two codes of under 5 are four each."""
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "data_dictionary.yaml").write_text(
        "schema: manuscript-guard/data-dictionary/1\nvariables:\n"
        "  - {name: g, label: G, definition: d, type: categorical, values: "
        "[{code: x, label: x}, {code: y, label: y}, {code: z, label: z}]}\n",
        encoding="utf-8")  # fmt: skip
    dictionary, _ = load_dictionary(tmp_path)
    document = profiling.profile({"g": ["x"] * 40 + ["y"] * 4 + ["z"] * 4}, name="t.csv",
                                 minimum=5, dictionary=dictionary)  # fmt: skip
    assert held(column(document, "g"))


def test_a_pattern_that_gives_the_missing_count_away_is_left_out() -> None:
    """Six rows, five identifiers and one blank: a pattern says five have a value."""
    found = column(made(id=["P1", "P2", "P3", "P4", "P5", ""]), "id")
    assert found["missing"] == "<5" and "pattern" not in found


def test_the_centiles_of_a_number_bound_its_rows_held_beside() -> None:
    """Eleven numbers, one that is none and fifty blanks: the eleven are held beside the one,
    and a median given says there are eleven at least: 12 less the one is eleven."""
    document = typed(x=[str(n) for n in range(11)] + ["n/a"] + [""] * 50)
    assert held(column(document, "x"))


def test_how_many_levels_are_folded_is_not_said_beside_a_count_held_beside() -> None:
    """Behind 3, 18 rows: 10 of one level, folded levels of 2, 2, 1 and 1, and 2 missing. The 6
    folded rows are held beside the missing "<3"; saying 4 levels would say the count was a
    whole number of 2, so 6 and not 7, and the missing 2 (the oracle, round 2)."""
    document = profiling.profile({"x": ["a"] * 10 + ["b", "b", "c", "c", "d", "e", "", ""]},
                                 name="t.csv", minimum=3)  # fmt: skip
    found = column(document, "x")
    assert held(found) or found["other"]["levels"] is None
