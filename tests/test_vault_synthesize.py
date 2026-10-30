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
        assert row["region"] in REGIONS, row
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
                            "encoding": "utf-8-sig", "quoting": "all",
                            "newline": "\r\n"}  # fmt: skip

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


@pytest.mark.parametrize(("pattern", "row", "made"), [
    ("AA-99999", 1, "XX-90001"),
    ("99999", 42, "90042"),
    ("a9", 3, "x3"),
    ("9", 12, "2"),
    ("AA", 5, "XX"),
    ("99-99", 7, "99-97"),
    (None, 7, "SYN7"),
])  # fmt: skip
def test_an_identifier_follows_its_pattern_and_looks_like_no_real_one(
    pattern: str | None, row: int, made: str
) -> None:
    assert identifier(pattern, row) == made


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
