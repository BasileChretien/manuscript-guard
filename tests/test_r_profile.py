"""The R emitter's profile is the Python one's, byte for byte.

`tests/data/profile` holds a table, its dictionary and the profile `tests/test_vault_profile.py`
holds the Python emitter to; here R is held to the same bytes, reading the table as text and
as `read.csv` types it. Then tables drawn as `tests/generated.py` draws them for the
properties are profiled by both, and each pair of profiles compared.
"""

from __future__ import annotations

import csv
import io
import random
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from generated import PROFILE_KINDS, SEED, _profile_column, _whole, times
from test_r_emitter import RSCRIPT

from manuscript_guard.contracts.dictionary import load_dictionary
from manuscript_guard.vault import profile as profiling

pytestmark = pytest.mark.skipif(RSCRIPT is None, reason="R is not installed")

REPO = Path(__file__).resolve().parent.parent
R_DIR = REPO / "r" / "manuscriptguard" / "R"
FIXTURE = Path(__file__).parent / "data" / "profile"

PREAMBLE = """
for (package in c("jsonlite", "digest", "yaml")) {
  if (!requireNamespace(package, quietly = TRUE)) { cat("MISSING_DEPS\\n"); quit(status = 3) }
}
for (file in c("emit.R", "quality.R", "profile.R")) source(file.path("%(dir)s", file))
"""


def run_r(tmp_path: Path, body: str) -> str:
    script = tmp_path / "profile.R"
    script.write_text(PREAMBLE % {"dir": R_DIR.as_posix()} + body, encoding="utf-8")
    out = subprocess.run([RSCRIPT, "--vanilla", str(script)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=tmp_path)  # fmt: skip
    if out.returncode == 3:
        pytest.skip("R packages jsonlite, digest and yaml are not installed")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    return out.stdout


@pytest.mark.parametrize("typed", [False, True], ids=["as text", "as read.csv types it"])
def test_the_shared_table_gives_the_expected_bytes(tmp_path: Path, typed: bool) -> None:
    root = tmp_path / "cohort"
    shutil.copytree(FIXTURE, root)
    (root / "analysis").mkdir()
    (root / "analysis" / "profile.R").write_text("", encoding="utf-8")
    classes = "" if typed else ', colClasses = "character", na.strings = character()'
    run_r(tmp_path, f"""
setwd("{root.as_posix()}")
data <- read.csv("cohort.csv", check.names = FALSE, encoding = "UTF-8"{classes})
em <- mg_emitter("analysis/profile.R", root = ".")
em$profile(data, name = "cohort.csv",
           read_as = list(header_of = "cohort.csv", dates = list(discharged = "%d/%m/%Y")))
""")
    written = root / "profiles" / "data" / "cohort.csv.profile.json"
    assert written.read_bytes() == (FIXTURE / "expected.profile.json").read_bytes()


#: How many drawn tables both emitters profile.
TABLES = 25


def drawn_tables(seed: int | None = None) -> list[dict]:
    """Tables as `generated.profile_tables` draws them, from a seed: every kind of column in
    each, with texts both languages must write alike among the levels."""
    rng = random.Random(seed if seed is not None else _whole(SEED, 0) or 20261030)
    tables = []
    for _ in range(TABLES * times()):
        minimum = rng.choice((1, 3, 5, 10, 11))
        rows = rng.randint(5 * minimum, 12 * minimum)
        kinds = list(PROFILE_KINDS)
        rng.shuffle(kinds)
        columns = {kind: _profile_column(rng, kind, rows, minimum) for kind in kinds}
        odd = ['say "so"', "back\\slash", "tab\there", "caf\N{LATIN SMALL LETTER E WITH ACUTE}",
               "\N{CJK UNIFIED IDEOGRAPH-4E2D}", "bell" + chr(7)]  # fmt: skip
        columns["levels"] = [
            odd[len(value) % len(odd)] if value.startswith("L") and rng.random() < 0.3 else value
            for value in columns["levels"]
        ]
        types = {kind: PROFILE_KINDS[kind] for kind in kinds if PROFILE_KINDS[kind]}
        tables.append({"minimum": minimum, "types": types, "columns": columns})
    return tables


def _project(folder: Path, table: dict) -> None:
    (folder / "design").mkdir(parents=True)
    (folder / "paper.yaml").write_text(
        f"title: t\ncustodian: {{minimum_cell_count: {table['minimum']}}}\n", encoding="utf-8")
    variables = [{"name": name, "label": name, "definition": "d", "type": kind}
                 for name, kind in table["types"].items()]  # fmt: skip
    (folder / "design" / "data_dictionary.yaml").write_text(yaml.safe_dump(
        {"schema": "manuscript-guard/data-dictionary/1", "variables": variables}),
        encoding="utf-8")  # fmt: skip
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\n")
    names = list(table["columns"])
    writer.writerow(names)
    writer.writerows(zip(*(table["columns"][name] for name in names), strict=True))
    (folder / "table.csv").write_bytes(text.getvalue().encode("utf-8"))


def test_drawn_tables_give_the_same_bytes_in_both_languages(tmp_path: Path) -> None:
    tables = drawn_tables()
    folders = []
    for at, table in enumerate(tables):
        folder = tmp_path / f"t{at}"
        _project(folder, table)
        dictionary, _ = load_dictionary(folder)
        document = profiling.profile(table["columns"], name="table.csv",
                                     minimum=table["minimum"], dictionary=dictionary)  # fmt: skip
        (folder / "python.json").write_bytes((profiling.dumps(document) + "\n").encode("utf-8"))
        folders.append(folder.as_posix())
    listed = ", ".join(f'"{folder}"' for folder in folders)
    run_r(tmp_path, f"""
for (folder in c({listed})) {{
  data <- read.csv(file.path(folder, "table.csv"), colClasses = "character", check.names = FALSE,
                   na.strings = character(), encoding = "UTF-8")
  dictionary <- mg_read_dictionary(file.path(folder, "design", "data_dictionary.yaml"))
  minimum <- mg_minimum_cell_count(folder)
  document <- mg_profile(data, "table.csv", minimum, dictionary)
  writeBin(charToRaw(enc2utf8(paste0(mg_profile_json(document), "\\n"))),
           file.path(folder, "r.json"))
}}
""")
    differing = [folder for folder in folders
                 if (Path(folder) / "r.json").read_bytes()
                 != (Path(folder) / "python.json").read_bytes()]  # fmt: skip
    assert not differing, differing[:3]
