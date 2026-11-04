"""`vault synthesize`: the synthetic copy of a file of the vault, drawn from its released
profile and from nothing else; and the profile script `vault init` starts.

That the same profile and seed give the same bytes is held over generated tables in
`tests/test_properties.py`; here it is held to a file, `tests/data/profile/expected.synthetic
.csv`, so that every platform and Python version CI runs draws those bytes.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.vault import starter
from manuscript_guard.vault.synthesize import Refused, identifier, render, synthesize

FIXTURE = Path(__file__).parent / "data" / "profile"
SEED = "schema: manuscript-guard/synthetic/1\nseed: 20261030\nrows: 60\n"
#: The levels of the fixture's region the profile gives, and the folded ones' "other".
REGIONS = ("East", "North", 'Say "hi"', "South", "West", "other",
           "\N{LATIN CAPITAL LETTER I WITH CIRCUMFLEX}le")  # fmt: skip


@pytest.fixture
def released(tmp_path: Path) -> Path:
    """A project holding the shared fixture's profile, as released, its dictionary and a seed;
    and none of the data."""
    root = tmp_path / "paper"
    (root / "profiles" / "data").mkdir(parents=True)
    (root / "design").mkdir()
    shutil.copy(FIXTURE / "paper.yaml", root / "paper.yaml")
    shutil.copy(FIXTURE / "design" / "data_dictionary.yaml", root / "design")
    shutil.copy(FIXTURE / "expected.profile.json",
                root / "profiles" / "data" / "cohort.csv.profile.json")  # fmt: skip
    (root / "profiles" / "data" / "cohort.csv.synthetic.yaml").write_text(SEED, encoding="utf-8")
    return root


def rows_of(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def edit_profile(root: Path, change) -> None:
    path = root / "profiles" / "data" / "cohort.csv.profile.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


# ------------------------------------------------------------------------------ the copy


def test_the_profile_and_seed_give_the_expected_bytes(released: Path, capsys) -> None:
    assert main(["vault", "synthesize", "--path", str(released)]) == 0
    written = released / "data" / "synthetic" / "cohort.csv"
    assert written.read_bytes() == (FIXTURE / "expected.synthetic.csv").read_bytes()
    assert "60 rows" in capsys.readouterr().out


def test_the_copy_is_in_the_profile_s_shape_and_keeps_the_dictionary_s_rules(
    released: Path,
) -> None:
    synthesize(released, "cohort.csv")
    rows = rows_of(released / "data" / "synthetic" / "cohort.csv")
    profile = json.loads((FIXTURE / "expected.profile.json").read_text(encoding="utf-8"))
    assert list(rows[0]) == [column["name"] for column in profile["columns"]]
    for row in rows:
        day, month, year = row["discharged"].split("/")
        assert row["admitted"] <= f"{year}-{month}-{day}", row
        assert row["patient_id"].startswith("XX-9"), row
        assert row["sex"] in ("1", "2", ""), row
        # The profile holds region's counts back, a level of six rows beside four folded.
        assert row["region"].startswith("SYN"), row
        assert row["age"] == "" or 18 <= int(row["age"]) <= 110, row
    assert len({row["patient_id"] for row in rows}) == len(rows)


def test_the_seed_is_written_on_first_use_and_kept(released: Path) -> None:
    kept = released / "profiles" / "data" / "cohort.csv.synthetic.yaml"
    kept.unlink()
    first = synthesize(released, "cohort.csv")
    seeded = yaml.safe_load(kept.read_text(encoding="utf-8"))
    assert first.seeded and seeded["rows"] == 88 and isinstance(seeded["seed"], int)
    before = first.path.read_bytes()
    again = synthesize(released, "cohort.csv")
    assert not again.seeded
    assert again.path.read_bytes() == before
    assert yaml.safe_load(kept.read_text(encoding="utf-8")) == seeded


def test_a_shape_other_than_plain_csv_is_written_as_the_profile_says(released: Path) -> None:
    def shaped(document: dict) -> None:
        document["file"] = {"format": "csv", "delimiter": ";", "decimal": ",",
                            "encoding": "utf-8", "quoting": "all", "newline": "\r\n",
                            "bom": True}  # fmt: skip

    edit_profile(released, shaped)
    raw = synthesize(released, "cohort.csv").path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf\"patient_id\";\"sex\";")
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert any("," in row["weight"] for row in rows)
    assert not any("." in row["weight"] for row in rows)


def test_a_variable_that_does_not_apply_is_left_empty(released: Path) -> None:
    dictionary = released / "design" / "data_dictionary.yaml"
    document = yaml.safe_load(dictionary.read_text(encoding="utf-8"))
    for entry in document["variables"]:
        if entry["name"] == "age":
            entry["applies_if"] = {"variable": "sex", "in": [2]}
    dictionary.write_text(yaml.safe_dump(document), encoding="utf-8")
    rows = rows_of(synthesize(released, "cohort.csv").path)
    assert all(row["age"] == "" for row in rows if row["sex"] != "2")
    assert any(row["age"] for row in rows if row["sex"] == "2")


def test_a_rule_the_profile_cannot_be_drawn_to_meet_is_refused_by_its_name(
    released: Path,
) -> None:
    def late(document: dict) -> None:
        for column in document["columns"]:
            if column["name"] == "admitted":
                column["centiles"] = {"25": "2025-01", "75": "2025-03"}
                column["missing"] = 0

    edit_profile(released, late)
    with pytest.raises(Refused, match="rule in_before_out"):
        synthesize(released, "cohort.csv")
    assert not (released / "data" / "synthetic" / "cohort.csv").exists()


def test_a_profile_of_another_format_is_refused_with_the_way_on(released: Path, capsys) -> None:
    edit_profile(released, lambda document: document["file"].update(format="xlsx"))
    assert main(["vault", "synthesize", "cohort.csv", "--path", str(released)]) == 2
    said = capsys.readouterr().err
    assert "export the extract to CSV inside the vault" in said
    assert not (released / "data").exists()


def test_a_name_with_no_released_profile_is_refused(released: Path, capsys) -> None:
    assert main(["vault", "synthesize", "visits.csv", "--path", str(released)]) == 2
    assert "no released profile of visits.csv" in capsys.readouterr().err


def test_a_project_with_no_profile_says_so(tmp_path: Path, capsys) -> None:
    (tmp_path / "paper.yaml").write_text("title: x\n", encoding="utf-8")
    assert main(["vault", "synthesize", "--path", str(tmp_path)]) == 2
    assert "no released profile" in capsys.readouterr().err


def test_a_profile_that_is_not_one_is_refused(released: Path) -> None:
    edit_profile(released, lambda document: document.pop("rows"))
    with pytest.raises(Refused, match="not a data profile"):
        synthesize(released, "cohort.csv")


def test_a_seed_file_that_is_not_one_is_refused(released: Path) -> None:
    kept = released / "profiles" / "data" / "cohort.csv.synthetic.yaml"
    kept.write_text("schema: manuscript-guard/synthetic/1\nseed: x\nrows: 3\n", encoding="utf-8")
    with pytest.raises(Refused, match="not a seed file"):
        synthesize(released, "cohort.csv")


def test_synthesize_reads_nothing_of_the_vault(released: Path, monkeypatch) -> None:
    """It needs no vault registered, and opens no file outside the project."""
    import builtins

    real = builtins.open
    opened: list[Path] = []

    def watched(file, *args, **kwargs):
        opened.append(Path(file).resolve())
        return real(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watched)
    synthesize(released, "cohort.csv")
    root = released.resolve()
    assert all(path == root or root in path.parents or "manuscript_guard" in path.parts
               for path in opened), opened  # fmt: skip


@pytest.mark.parametrize(("pattern", "row", "rows", "made"), [
    ("AA-99999", 1, 60, "XX-90001"),
    ("99999", 42, 100, "90042"),
    ("99999", 42, 10000, "00042"),
    ("a9", 3, 9, "x3"),
    ("9", 12, 12, "SYN12"),
    ("AA", 5, 5, "SYN5"),
    ("99-99", 7, 100, "90-07"),
    ("A999", 1, 950, "X001"),
    ("A999", 901, 950, "X901"),
    (None, 7, 7, "SYN7"),
])  # fmt: skip
def test_an_identifier_follows_its_pattern_and_looks_like_no_real_one(
    pattern: str | None, row: int, rows: int, made: str
) -> None:
    assert identifier(pattern, row, rows) == made


def test_a_date_is_written_in_its_format() -> None:
    parts = {"Y": 2019, "m": 3, "d": 7, "H": 8, "M": 5, "S": 9}
    assert render("%d/%m/%Y %H:%M:%S %%", parts) == "07/03/2019 08:05:09 %"


# -------------------------------------------------------------------- the starter script


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    with (root / "paper.yaml").open("a", encoding="utf-8") as file:
        file.write("\ncustodian:\n  minimum_cell_count: 5\n")
    return root


@pytest.fixture
def data(tmp_path: Path) -> Path:
    folder = tmp_path / "data held"
    folder.mkdir()
    (folder / "cohort.csv").write_bytes(b"id,age\n1,40\n")
    (folder / "visits.tsv").write_bytes(b"id\tday\n1\t2020-01-01\n")
    (folder / "extract.xlsx").write_bytes(b"PK")
    return folder


def test_init_starts_the_profile_script_once(paper: Path, data: Path, capsys) -> None:
    assert main(["vault", "init", str(data), "*.*", "--as", "Ada", "--path", str(paper)]) == 0
    script = paper / "analysis" / "00_profile.py"
    text = script.read_text(encoding="utf-8")
    compile(text, str(script), "exec")
    assert "name='cohort.csv'" in text and "name='visits.tsv'" in text
    assert 'delimiter="\\t"' in text and "extract.xlsx: read it as the analysis does" in text
    assert "started analysis/00_profile.py" in capsys.readouterr().out
    script.write_text("# mine\n", encoding="utf-8")
    assert main(["vault", "init", str(data), "cohort.csv", "--as", "Ada",
                 "--path", str(paper)]) == 0  # fmt: skip
    assert script.read_text(encoding="utf-8") == "# mine\n"
    assert "started" not in capsys.readouterr().out


def test_init_starts_an_r_script_where_the_analysis_is_in_r(paper: Path, data: Path) -> None:
    (paper / "analysis" / "01_model.R").write_text("# R\n", encoding="utf-8")
    assert main(["vault", "init", str(data), "cohort.csv", "--as", "Ada",
                 "--path", str(paper)]) == 0  # fmt: skip
    text = (paper / "analysis" / "00_profile.R").read_text(encoding="utf-8")
    assert 'em$profile(read.csv(file.path(vault, "cohort.csv")' in text
    assert not (paper / "analysis" / "00_profile.py").exists()


def test_the_starter_script_refuses_to_run_outside_a_vault_run(
    paper: Path, data: Path, monkeypatch
) -> None:
    monkeypatch.delenv("MANUSCRIPT_GUARD_VAULT", raising=False)
    assert main(["vault", "init", str(data), "cohort.csv", "--as", "Ada",
                 "--path", str(paper)]) == 0  # fmt: skip
    script = paper / "analysis" / "00_profile.py"
    with pytest.raises(SystemExit, match="vault run"):
        exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"),
             {"__file__": str(script), "__name__": "__main__"})  # fmt: skip


def test_the_starter_script_profiles_each_file_under_a_vault_run(
    paper: Path, data: Path, monkeypatch
) -> None:
    """Run as `vault run` will run it, with the folder in MANUSCRIPT_GUARD_VAULT."""
    (data / "cohort.csv").write_bytes(b"id,age\n" + b"".join(
        f"{n},{20 + n % 7}\n".encode() for n in range(40)))  # fmt: skip
    assert main(["vault", "init", str(data), "cohort.csv", "--as", "Ada",
                 "--path", str(paper)]) == 0  # fmt: skip
    monkeypatch.setenv("MANUSCRIPT_GUARD_VAULT", str(data))
    script = paper / "analysis" / "00_profile.py"
    exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"),
         {"__file__": str(script), "__name__": "__main__"})  # fmt: skip
    profile = json.loads((paper / "profiles" / "data" / "cohort.csv.profile.json").read_text(
        encoding="utf-8"))  # fmt: skip
    assert profile["rows"] == 40 and [c["name"] for c in profile["columns"]] == ["id", "age"]
    assert starter.SCRIPT.name == "00_profile"


# ------------------------------------------------- round 1: identifiers, dataset, mark


@pytest.mark.parametrize("pattern", ["A999", "99", "9", "AA-99999", "AA", "9a9"])
@pytest.mark.parametrize("rows", [9, 10, 11, 99, 100, 101, 999, 1000, 1001, 10000, 10001])
def test_an_identifier_is_one_for_each_row_and_keeps_its_pattern_where_it_holds_them(
    pattern: str, rows: int
) -> None:
    from manuscript_guard.vault.profile import shape_of

    made = [identifier(pattern, row, rows) for row in range(1, rows + 1)]
    assert len(set(made)) == rows
    digits = pattern.count("9")
    if digits and rows < 10**digits:
        assert all(shape_of(one) == pattern for one in made)
    else:
        assert all(one.startswith("SYN") for one in made)


def test_a_variable_is_looked_up_in_the_profile_s_dataset(released: Path) -> None:
    dictionary = released / "design" / "data_dictionary.yaml"
    document = yaml.safe_load(dictionary.read_text(encoding="utf-8"))
    """The dictionary's `age` is another dataset's, whose range would raise every age past
    500: the profile of no dataset draws its ages from its own centiles."""
    document["datasets"] = [{"id": "other", "label": "Another table"}]
    for entry in document["variables"]:
        if entry["name"] == "age":
            entry.update(dataset="other", range={"min": 500, "max": 600})
    dictionary.write_text(yaml.safe_dump(document), encoding="utf-8")
    edit_profile(released, lambda profile: profile.update(dataset=None))
    rows = rows_of(synthesize(released, "cohort.csv").path)
    assert any(row["age"] for row in rows)
    assert all(row["age"] == "" or int(row["age"]) < 500 for row in rows)


def test_a_byte_order_mark_is_written_only_where_the_file_had_one(released: Path) -> None:
    def marked(on: bool):
        return lambda document: document["file"].update(bom=on)

    edit_profile(released, marked(True))
    assert synthesize(released, "cohort.csv").path.read_bytes().startswith(b"\xef\xbb\xbf")
    edit_profile(released, marked(False))
    assert not synthesize(released, "cohort.csv").path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_starter_script_reads_a_byte_order_mark(paper: Path, data: Path) -> None:
    assert main(["vault", "init", str(data), "*.*", "--as", "Ada", "--path", str(paper)]) == 0
    assert 'encoding="utf-8-sig"' in (paper / "analysis" / "00_profile.py").read_text("utf-8")
    (paper / "analysis" / "01.R").write_text("", encoding="utf-8")
    (paper / "analysis" / "02.R").write_text("", encoding="utf-8")
    (paper / "analysis" / "00_profile.py").unlink()
    assert main(["vault", "init", str(data), "*.*", "--as", "Ada", "--path", str(paper)]) == 0
    assert 'fileEncoding = "UTF-8-BOM"' in (paper / "analysis" / "00_profile.R").read_text("utf-8")


# ------------------------------------------------- round 2: the dictionary's pattern and codes


def test_an_identifier_meets_the_dictionary_s_pattern(released: Path) -> None:
    dictionary = released / "design" / "data_dictionary.yaml"
    document = yaml.safe_load(dictionary.read_text(encoding="utf-8"))
    for entry in document["variables"]:
        if entry["name"] == "patient_id":
            entry["pattern"] = "PT-[0-9]{5}"
    dictionary.write_text(yaml.safe_dump(document), encoding="utf-8")
    copy = synthesize(released, "cohort.csv")
    ids = [row["patient_id"] for row in rows_of(copy.path)]
    assert all(re.fullmatch(r"PT-[0-9]{5}", one) for one in ids) and len(set(ids)) == len(ids)
    assert not any("patient_id" in note for note in copy.notes)


def test_a_pattern_no_identifier_meets_is_named_in_a_note(released: Path) -> None:
    dictionary = released / "design" / "data_dictionary.yaml"
    document = yaml.safe_load(dictionary.read_text(encoding="utf-8"))
    for entry in document["variables"]:
        if entry["name"] == "patient_id":
            entry["pattern"] = "[a-z]{3}"
    dictionary.write_text(yaml.safe_dump(document), encoding="utf-8")
    copy = synthesize(released, "cohort.csv")
    assert any(note.startswith("patient_id:") for note in copy.notes)


def test_a_coded_column_held_back_is_drawn_from_its_codes(released: Path) -> None:
    def hold(document: dict) -> None:
        for column in document["columns"]:
            if column["name"] == "sex":
                for key in ("levels", "other", "missing_share"):
                    column.pop(key, None)
                column.update(kind="withheld", missing=None, held="held back")

    edit_profile(released, hold)
    rows = rows_of(synthesize(released, "cohort.csv").path)
    assert {row["sex"] for row in rows} <= {"1", "2"} and len({row["sex"] for row in rows}) == 2


# ------------------------------------------- fix-only round: patterns, row by row


def test_a_pattern_anchored_at_both_ends_is_met() -> None:
    from manuscript_guard.vault.synthesize import within

    assert within("^PT-[0-9]{5}$", "XX-90001", set()) == "PT-90001"


def test_the_fill_is_chosen_for_each_row() -> None:
    """Rows past 9999 of `AA-99999` lose the spare 9: a pattern that takes `XX-0...` and
    `PT-1...` is met by each row in its own way."""
    from manuscript_guard.vault.synthesize import within

    pattern = "XX-0[0-9]{4}|PT-1[0-9]{4}"
    assert within(pattern, "XX-00001", set()) == "XX-00001"
    assert within(pattern, "XX-10000", set()) == "PT-10000"


def test_an_identifier_put_within_the_pattern_stays_one_to_a_row() -> None:
    """`PT-12[0-9]{3}` opens over two of the digits, which carry the row's number: putting
    it over them would make rows that differ only there one identifier, so it is not put.
    And a fill a row before took is not taken again."""
    from manuscript_guard.vault.synthesize import within

    used: set = set()
    made = [within("PT-12[0-9]{3}", one, used) for one in ("XX-90001", "XX-91001", "XX-92001")]
    assert made == ["XX-90001", "XX-91001", "XX-92001"]
    taken = {"PT-90001"}
    assert within("PT-[0-9]{5}|PU-[0-9]{5}", "XX-90001", taken) == "PU-90001"
    assert within("PT-[0-9]{5}", "XX-90001", {"PT-90001"}) == "XX-90001"


# ------------------------------------------- a column whose distribution is held back


def _held_count(root: Path, entry: str) -> None:
    """A profile of 200 rows behind 5, 150 of 0, 47 of 1 and 3 blank, the dictionary typing
    it `count`: no centile (all are ties), missing "<5", n held beside it, so no mean."""
    from manuscript_guard.vault import profile as profiling

    (root / "design").mkdir(parents=True)
    (root / "paper.yaml").write_text("title: t\ncustodian: {minimum_cell_count: 5}\n", "utf-8")
    (root / "design" / "data_dictionary.yaml").write_text(
        "schema: manuscript-guard/data-dictionary/1\nvariables:\n" + entry, encoding="utf-8")
    dictionary = profiling.dictionary_of(root)
    document = profiling.profile({"x": ["0"] * 150 + ["1"] * 47 + [""] * 3}, name="t.csv",
                                 minimum=5, dictionary=dictionary)  # fmt: skip
    column = document["columns"][0]
    assert column["n"] is None and "mean" not in column and not column["centiles"]
    profiling.write(root, document)


@pytest.mark.parametrize(("bounds", "allowed"), [
    (", range: {min: 0, max: 1}", {"0", "1"}),
    ("", None),
])  # fmt: skip
def test_a_number_column_whose_distribution_is_held_back_is_still_drawn(
    tmp_path: Path, bounds: str, allowed: set | None
) -> None:
    """Drawn within the dictionary's range where it declares one, else as a withheld column
    is, and said in a note: never every row blank where the profile says some are not."""
    _held_count(tmp_path, f"  - {{name: x, label: X, definition: d, type: count{bounds}}}\n")
    copy = synthesize(tmp_path, "t.csv")
    drawn = [row["x"] for row in rows_of(copy.path)]
    written = [value for value in drawn if value]
    assert len(written) > len(drawn) // 2
    if allowed is not None:
        assert set(written) <= allowed
    else:
        # A count drawn as a value of its type: whole, and drawn again for each row.
        assert all(value.isdigit() for value in written) and len(set(written)) > 5
    how = "within its range" if allowed is not None else "as a value of its type"
    assert any(note.startswith(f"x: drawn without its distribution, {how}")
               for note in copy.notes)  # fmt: skip


def test_a_row_drawn_again_for_a_rule_keeps_its_identifier(released: Path) -> None:
    """Each row's identifier is made once: a row drawn again for a dictionary's rule is not
    given another, nor told its own is taken (the round-2 fix of `_within`)."""
    from manuscript_guard.contracts.dictionary import Variable
    from manuscript_guard.vault.synthesize import _Column, _within

    column = _Column({"name": "id", "kind": "withheld", "type": "identifier", "missing": 0},
                     Variable("id", "id", "d", "identifier", pattern="PT-[0-9]{5}"), 5, 10, 10)
    first = _within(column, "XX-90001", 1)
    assert _within(column, "XX-90001", 1) == first == "PT-90001"
    assert _within(column, "XX-90002", 2) == "PT-90002"


# ------------------------------------------- drawn without a distribution, from the stream


def _project_of(root: Path, entries: str, columns: dict, read_as: dict | None = None) -> None:
    from manuscript_guard.vault import profile as profiling

    (root / "design").mkdir(parents=True)
    (root / "paper.yaml").write_text("title: t\ncustodian: {minimum_cell_count: 5}\n", "utf-8")
    (root / "design" / "data_dictionary.yaml").write_text(
        "schema: manuscript-guard/data-dictionary/1\n" + entries, encoding="utf-8")
    document = profiling.profile(columns, name="t.csv", minimum=5, read_as=read_as,
                                 dictionary=profiling.dictionary_of(root))  # fmt: skip
    profiling.write(root, document)


def test_a_column_drawn_without_its_distribution_can_meet_a_rule(tmp_path: Path) -> None:
    """`serious` is held (n beside an unread "<5"), with no range and no centile; `total` runs
    to 20. Each row drawn again draws `serious` again, so `serious <= total` is met, and the
    copy is written with whole numbers that vary."""
    _project_of(tmp_path,
                "variables:\n"
                "  - {name: serious, label: S, definition: d, type: count}\n"
                "  - {name: total, label: T, definition: d, type: count}\n"
                "rules:\n  - {id: serious_within_total, says: s, order: [serious, total]}\n",
                {"serious": ["0"] * 150 + ["1"] * 47 + ["unknown"] * 3,
                 "total": [str(at % 21) for at in range(200)]})  # fmt: skip
    copy = synthesize(tmp_path, "t.csv")
    rows = rows_of(copy.path)
    serious = [row["serious"] for row in rows if row["serious"]]
    assert len(serious) > 150 and len(set(serious)) > 5
    assert all(value.isdigit() for value in serious)
    assert all(int(row["serious"]) <= int(row["total"]) for row in rows
               if row["serious"] and row["total"])  # fmt: skip
    assert any("serious: drawn without its distribution, as a value of its type" in note
               for note in copy.notes)  # fmt: skip


def test_a_one_ended_range_holds_a_column_drawn_without_its_distribution(tmp_path: Path) -> None:
    _project_of(tmp_path,
                "variables:\n  - {name: x, label: X, definition: d, type: count, "
                "range: {min: 40}}\n",
                {"x": ["40"] * 150 + ["41"] * 47 + ["unknown"] * 3})  # fmt: skip
    values = [int(row["x"]) for row in rows_of(synthesize(tmp_path, "t.csv").path) if row["x"]]
    assert values and min(values) >= 40 and len(set(values)) > 5


@pytest.mark.parametrize(("form", "shaped"), [
    ("%d/%m/%Y", r"[0-9]{2}/[0-9]{2}/[0-9]{4}"),
    ("%Y-%m-%d %H:%M", r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}"),
])  # fmt: skip
def test_a_date_with_no_centile_is_drawn_in_its_format(
    tmp_path: Path, form: str, shaped: str
) -> None:
    """Eight dates behind 5 give no centile: the copy still writes them in the format the
    profile records, each drawn, a date and time with its clock."""
    from datetime import datetime

    days = [datetime(2019, 3, day, 8 + day).strftime(form) for day in range(1, 9)]
    kind = "datetime" if "%H" in form else "date"
    _project_of(tmp_path, f"variables:\n  - {{name: d, label: D, definition: d, type: {kind}}}\n",
                {"d": days}, read_as={"dates": {"d": form}})  # fmt: skip
    copy = synthesize(tmp_path, "t.csv")
    written = [row["d"] for row in rows_of(copy.path) if row["d"]]
    assert written and all(re.fullmatch(shaped, value) for value in written)
    assert all(datetime.strptime(value, form) for value in written)
    assert len(set(written)) > 3
    assert any(note.startswith("d: drawn without its distribution") for note in copy.notes)


def test_a_time_with_no_centile_is_drawn_from_the_stream(tmp_path: Path) -> None:
    _project_of(tmp_path, "variables:\n  - {name: t, label: T, definition: d, type: time}\n",
                {"t": [f"{8 + at}:15".zfill(5) for at in range(8)]})  # fmt: skip
    written = [row["t"] for row in rows_of(synthesize(tmp_path, "t.csv").path) if row["t"]]
    assert len(set(written)) > 3 and all(re.fullmatch(r"[0-9]{2}:[0-9]{2}", one) for one in written)


# ------------------------------------- within a declared range (the last round of #491)


def _held_values(tmp_path: Path, kind: str, bounds: str, values: list[str],
                 read_as: dict | None = None) -> list[str]:  # fmt: skip
    """The values the copy writes of one column `x` of `kind`, the dictionary giving it
    `bounds`, profiled from `values`."""
    _project_of(tmp_path, f"variables:\n  - {{name: x, label: X, definition: d, type: {kind}"
                          f"{bounds}}}\n", {"x": values}, read_as=read_as)  # fmt: skip
    copy = synthesize(tmp_path, "t.csv")
    written = [row["x"] for row in rows_of(copy.path) if row["x"]]
    assert written
    return written


def test_a_date_and_time_drawn_within_a_range_with_a_clock_stays_within_it(
    tmp_path: Path,
) -> None:
    """The day and the clock are drawn together across the range: a row on its first or last
    day is not drawn before `min` or after `max`."""
    from datetime import datetime

    form = "%Y-%m-%d %H:%M"
    days = [datetime(2019, 3, day, 8 + day).strftime(form) for day in range(1, 9)]
    written = _held_values(tmp_path, "datetime",
                           ', range: {min: "2019-03-01T12:00:00", max: "2019-03-02T06:00:00"}',
                           days, read_as={"dates": {"x": form}})  # fmt: skip
    drawn = [datetime.strptime(value, form) for value in written]
    assert all(datetime(2019, 3, 1, 12) <= one <= datetime(2019, 3, 2, 6) for one in drawn)
    assert len(set(drawn)) > 5


def test_a_date_drawn_from_its_distribution_is_kept_within_the_range(tmp_path: Path) -> None:
    """Continued straight beyond the outer centiles, a date is still clamped to the range the
    dictionary declares, as a number is."""
    days = [f"2018-{month:02d}-{day:02d}" for month in range(1, 13) for day in (5, 15, 25)]
    written = _held_values(tmp_path, "date", ', range: {min: "2018-03-01", max: "2018-10-31"}',
                           days * 4, read_as={"dates": {"x": "%Y-%m-%d"}})  # fmt: skip
    assert all("2018-03-01" <= value <= "2018-10-31" for value in written)


def test_a_count_with_only_a_maximum_is_not_piled_on_nought(tmp_path: Path) -> None:
    written = _held_values(tmp_path, "count", ", range: {max: 20}",
                           ["0"] * 150 + ["1"] * 47 + ["unknown"] * 3)  # fmt: skip
    values = [int(value) for value in written]
    assert max(values) <= 20 and min(values) >= 0
    assert values.count(0) < len(values) / 5 and len(set(values)) > 10


@pytest.mark.parametrize(("bounds", "inside"), [
    (', range: {min: "9995-01-01"}', lambda day: "9995-01-01" <= day <= "9999-12-31"),
    (', range: {max: "0003-01-01"}', lambda day: "0001-01-01" <= day <= "0003-01-01"),
])  # fmt: skip
def test_a_one_ended_date_range_near_the_calendar_s_end_is_drawn_within_it(
    tmp_path: Path, bounds: str, inside
) -> None:
    days = [f"2019-03-{day:02d}" for day in range(1, 9)]
    written = _held_values(tmp_path, "date", bounds, days,
                           read_as={"dates": {"x": "%Y-%m-%d"}})  # fmt: skip
    assert all(inside(day) for day in written) and len(set(written)) > 5


def test_a_count_s_bounds_that_are_not_whole_are_rounded_inwards(tmp_path: Path) -> None:
    """Clamped to 40.5 and written as 40 was below the bound: a count's least is 41."""
    written = _held_values(tmp_path, "count", ", range: {min: 40.5, max: 50.5}",
                           [str(30 + at % 31) for at in range(310)])  # fmt: skip
    values = [int(value) for value in written]
    assert min(values) >= 41 and max(values) <= 50
    assert 41 in values


@pytest.mark.parametrize("centre", ["23:00", "00:00"])
def test_a_time_about_one_centile_by_midnight_wraps_round_it(centre: str) -> None:
    """Drawn two hours either side of its one centile, a time near midnight is carried round
    to the other side, not piled on 23:59 or 00:00."""
    from collections import Counter

    from manuscript_guard.vault.synthesize import _Column, _time

    column = _Column({"name": "t", "kind": "time", "type": "time", "centiles": {"50": centre},
                      "missing": 0, "unread": 0, "n": 100}, None, 5, 100, 100)  # fmt: skip
    drawn = Counter(_time(column, at / 1000).text for at in range(1000))
    assert max(drawn.values()) < 20
    assert all(re.fullmatch(r"(2[0-3]|[01][0-9]):[0-5][0-9]", one) for one in drawn)


def test_a_time_is_kept_within_the_dictionary_s_range() -> None:
    """Round 1 of #498: carried round midnight, a time near the end of a declared range left
    it, where base held it at 23:59; every time drawn is kept within the range."""
    from types import SimpleNamespace

    from manuscript_guard.vault.synthesize import _Column, _time

    evening = SimpleNamespace(minimum="20:00", maximum="23:59")
    column = _Column({"name": "t", "kind": "time", "type": "time", "centiles": {"50": "23:00"},
                      "missing": 0, "unread": 0, "n": 100}, evening, 5, 100, 100)  # fmt: skip
    drawn = {_time(column, at / 1000).text for at in range(1000)}
    assert all("20:00" <= one <= "23:59" for one in drawn), sorted(drawn)[:5]


@pytest.mark.parametrize(("kind", "bounds", "values", "read_as"), [
    ("count", ", range: {min: 40}", ["40"] * 150 + ["41"] * 47 + ["unknown"] * 3, None),
    ("date", ', range: {min: "2019-03-01"}', [f"2019-03-{day:02d}" for day in range(1, 9)],
     {"dates": {"x": "%Y-%m-%d"}}),
])  # fmt: skip
def test_a_number_and_a_date_with_one_declared_end_are_said_alike(
    tmp_path: Path, kind: str, bounds: str, values: list[str], read_as: dict | None
) -> None:
    _project_of(tmp_path, f"variables:\n  - {{name: x, label: X, definition: d, type: {kind}"
                          f"{bounds}}}\n", {"x": values}, read_as=read_as)  # fmt: skip
    notes = synthesize(tmp_path, "t.csv").notes
    assert any(note.startswith("x: drawn without its distribution, from its one end")
               for note in notes), notes  # fmt: skip
