"""The R emitter's data-quality checks count as the Python ones do.

`tests/data/quality` holds one dictionary, one table and the rows each count must find, and
`tests/test_quality.py` holds the Python emitter to them. Here R is held to the same file,
reading the table as text and as `read.csv` types it, and each way of reading a value is
compared value by value with Python's.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
import subprocess
from pathlib import Path

import pytest
from generated import SEED, _whole, times
from test_r_emitter import RSCRIPT

from manuscript_guard import quality
from manuscript_guard.contracts import load_results
from manuscript_guard.contracts.dictionary import Dictionary, Variable
from manuscript_guard.emit import Emitter

pytestmark = pytest.mark.skipif(RSCRIPT is None, reason="R is not installed")

REPO = Path(__file__).resolve().parent.parent
R_DIR = REPO / "r" / "manuscriptguard" / "R"
DATA = Path(__file__).parent / "data" / "quality"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))

PREAMBLE = """
for (package in c("jsonlite", "digest", "yaml")) {
  if (!requireNamespace(package, quietly = TRUE)) { cat("MISSING_DEPS\\n"); quit(status = 3) }
}
source("%(dir)s/emit.R")
source("%(dir)s/quality.R")
"""


def run_r(tmp_path: Path, body: str, cwd: Path | None = None) -> str:
    script = tmp_path / "check.R"
    script.write_text(PREAMBLE % {"dir": R_DIR.as_posix()} + body, encoding="utf-8")
    out = subprocess.run(
        [RSCRIPT, "--vanilla", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd or tmp_path,
    )
    if out.returncode == 3:
        pytest.skip("R packages jsonlite, digest and yaml are not installed")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    return out.stdout


@pytest.mark.parametrize("typed", [False, True], ids=["as text", "as read.csv types it"])
def test_the_shared_table_gives_the_expected_counts(tmp_path: Path, typed: bool) -> None:
    read = ('read.csv("%(csv)s")' if typed else 'read.csv("%(csv)s", colClasses = "character")') % {
        "csv": (DATA / "reports.csv").as_posix()
    }
    body = f"""
data <- {read}
dictionary <- mg_read_dictionary("{(DATA / "design" / "data_dictionary.yaml").as_posix()}")
mask <- data$sex %in% c("1", 1) & data$pregnant %in% c("1", 1)
checked <- mg_check_table(dictionary, data, computed = list(no_pregnant_men = mask))
found <- lapply(checked$found, function(flags) I(which(flags) - 1L))
cat(jsonlite::toJSON(list(rows = checked$rows, counts = found), auto_unbox = TRUE))
"""
    got = json.loads(run_r(tmp_path, body))
    assert got["rows"] == EXPECTED["rows"]
    assert got["counts"] == EXPECTED["counts"]
    assert list(got["counts"]) == list(EXPECTED["counts"])


#: Texts each way of reading a value is asked of, in both languages.
TEXTS = [
    "3",
    " 3.5 ",
    "-1e3",
    ".5",
    "1.",
    "abc",
    "1,5",
    "1e999",
    "+2",
    "",
    "  ",
    "NA",
    "-99",
    "2016-02-01",
    "2016-02-30",
    "0000-01-01",
    "2016-2-1",
    "20160201",
    "2016-02-29",
    "2015-02-29",
    "2016-02-01 08:00",
    "2016-02-01T08:00:59.5",
    "2016-02-01T08:00:00+02:00",
    "2016-02-01T08:00Z",
    "2016-02-01T24:00",
    "2016-02-01T08:60",
    "08:00",
    "23:59:59",
    "8:00",
    "24:00",
    "12:30:60",
    "R01",
    "\N{ARABIC-INDIC DIGIT ONE}",
    "\N{NO-BREAK SPACE}",
]


#: The ways a text is read, each as Python reads it: what both languages must agree on.
WAYS = {
    "number": lambda t: None if (n := quality.number_of(t)) is None else quality.text_of(n),
    "date": quality.date_of,
    "datetime": quality.datetime_of,
    "time": quality.time_of,
    "absent": lambda t: quality.absent(t, frozenset({"-99"})),
}


def read_in_r(tmp_path: Path, texts: list[str]) -> dict[str, list]:
    """Each way of reading each text, as the R emitter reads it."""
    given = tmp_path / "texts.json"
    given.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    body = f"""
texts <- as.character(jsonlite::fromJSON("{given.as_posix()}"))
na <- function(x) ifelse(is.na(x), "<none>", as.character(x))
out <- list(
  number = na(mg_text_of(mg_number_of(texts))),
  date = na(mg_date_of(texts)),
  datetime = na(mg_datetime_of(texts)),
  time = na(mg_time_of(texts)),
  absent = mg_absent(texts, c("-99"))
)
cat(jsonlite::toJSON(out))
"""
    return json.loads(run_r(tmp_path, body))


def differences(texts: list[str], in_r: dict[str, list], ways: dict = WAYS) -> list:
    """Each text one way reads otherwise in the two languages: (way, text, Python, R)."""

    def shown(value: object) -> object:
        return "<none>" if value is None else value

    return [
        (way, text, shown(read(text)), by_r)
        for way, read in ways.items()
        for text, by_r in zip(texts, in_r[way], strict=True)
        if shown(read(text)) != by_r
    ]


def test_each_text_is_read_alike(tmp_path: Path) -> None:
    assert differences(TEXTS, read_in_r(tmp_path, TEXTS)) == []


#: The seed the generated texts are drawn from, fixed so that each run draws the same:
#: `MANUSCRIPT_GUARD_SEED` draws them from another, and `MANUSCRIPT_GUARD_MORE_EXAMPLES` draws
#: that many times as many, as for the suite's other generated inputs.
PINNED = 20261021
#: Pieces of the texts a data file holds: digits of a date, a time and a number, their
#: separators, and what comes beside them.
PIECES = (
    "2016", "1999", "0000", "02", "29", "30", "31", "13", "00", "-", ":", "T", " ", "08",
    "23", "24", "59", "60", ".", ".5", "Z", "+02:00", "+0200", "e", "E", "+", "-3", "1e3",
    "7", "99", "\t", "abc", "1_0", ",", "NaN", "Inf", "\N{ARABIC-INDIC DIGIT ONE}",
)  # fmt: skip


def generated_texts(seed: int | None = None, count: int = 3000) -> list[str]:
    """Texts drawn from `seed`: half of them a date, a time or a number in a form near the
    ISO one, each part drawn from in range and out of it, and half of them pieces joined at
    random."""
    rng = random.Random(seed if seed is not None else _whole(SEED, 0) or PINNED)
    count *= times()
    texts = []
    for _ in range(count // 2):
        year, month, day = (
            rng.choice(("2016", "2015", "0000", "1900")),
            f"{rng.randint(0, 13):02}",
            f"{rng.randint(0, 32):02}",
        )
        hour, minute = f"{rng.randint(0, 25):02}", f"{rng.randint(0, 61):02}"
        second = rng.choice(("", f":{rng.randint(0, 61):02}", ":05.25"))
        offset = rng.choice(("", "", "Z", "+02:00", "-0530"))
        texts.append(rng.choice((
            f"{year}-{month}-{day}",
            f"{year}-{month}-{day}{rng.choice('T ')}{hour}:{minute}{second}{offset}",
            f"{hour}:{minute}{second}",
            f"{rng.choice(('', '-', '+'))}{rng.randint(0, 999)}{rng.choice(('', '.', '.25'))}"
            f"{rng.choice(('', 'e3', 'E-2', 'e999'))}",
        )))  # fmt: skip
    for _ in range(count - count // 2):
        pieces = [rng.choice(PIECES) for _ in range(rng.randint(0, 5))]
        texts.append(rng.choice(("", " ")) + "".join(pieces) + rng.choice(("", " ", "\t")))
    return texts


def test_generated_texts_are_read_alike(tmp_path: Path) -> None:
    """Three thousand texts near the forms a reader parses, and around them: Python and R
    read each one way, or the two emitters would count one table differently."""
    texts = generated_texts()
    assert differences(texts, read_in_r(tmp_path, texts)) == []


def test_the_generated_texts_find_a_reader_that_reads_otherwise(tmp_path: Path) -> None:
    """The comparison above would pass two readers that agreed by never being asked the
    case they differ on. A Python reader broken three ways is told from R's on the texts
    drawn: one that keeps a date of 30 February, one that takes a number with blanks
    left on, one that takes the hour 24."""
    texts = generated_texts()
    in_r = read_in_r(tmp_path, texts)
    broken = {
        "date": lambda t: t if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t, re.ASCII) else None,
        "number": lambda t: WAYS["number"](t) if t == t.strip() else None,
        "time": lambda t: (lambda m: f"{m[1]}:{m[2]}:{m[3] or '00'}" if m else None)(
            re.fullmatch(r"(\d{2}):(\d{2})(?::(\d{2}))?", t.strip(" \t"), re.ASCII)
        ),
    }
    for way, read in broken.items():
        assert differences(texts, in_r, {way: read}), way


#: Numbers each language writes as text: a code compared as text has to be the same text.
NUMBERS = [0, 3, 3.0, -0.0, 0.1, 1 / 3, 1e20, 2.5e-7, -12.75, 123456789012.5, math.inf]


def test_each_number_is_written_alike(tmp_path: Path) -> None:
    given = tmp_path / "numbers.txt"
    given.write_text("\n".join(repr(n) for n in NUMBERS), encoding="utf-8")
    body = f"""
numbers <- as.numeric(readLines("{given.as_posix()}"))
cat(jsonlite::toJSON(mg_text_of(numbers)))
"""
    assert json.loads(run_r(tmp_path, body)) == [quality.text_of(n) for n in NUMBERS]


#: Patterns as a dictionary writes them for codes: digits, word characters, blanks, a
#: choice, an anchor of its own, and an optional part.
PATTERNS = [
    r"R\d{4}",
    r"\w+",
    r"[A-Z]{3}\s?\d",
    r"K7[01](\.\d)?",
    r"^\d+$",
    r"(?:PT|LLT)-\d{8}",
    r"\S+ \S+",
]
#: Texts each is matched against: some match, some match only in part or with a digit of
#: another script, and one ends in a line break, which `$` may stop before.
PATTERN_TEXTS = [
    "R0001", "R00001", "r0001", "R" + "\N{ARABIC-INDIC DIGIT ONE}" * 4, "abc_1", "ab-c",
    "\N{LATIN SMALL LETTER E WITH ACUTE}t\N{LATIN SMALL LETTER E WITH ACUTE}", "ABC 1",
    "ABC1", "ABC\t1", "ABC\N{NO-BREAK SPACE}1", "K70", "K71.9", "K72", "K70.", "123",
    "123\n", "PT-10019663", "LLT-1001966", "two words", "two  words", "",
]  # fmt: skip


def test_each_pattern_matches_alike(tmp_path: Path) -> None:
    """A pattern is matched whole by Python's `re` in ASCII and by R's PCRE: the two agree
    on each text, or a code would be counted as not matching in one language only."""
    given = tmp_path / "patterns.json"
    given.write_text(
        json.dumps({"patterns": PATTERNS, "texts": PATTERN_TEXTS}, ensure_ascii=False),
        encoding="utf-8",
    )
    body = f"""
given <- jsonlite::fromJSON("{given.as_posix()}")
out <- lapply(given$patterns, function(p) {{
  variable <- list(name = "x", type = "text", pattern = p)
  mg_check_variable(variable, given$texts, list())$not_matching
}})
cat(jsonlite::toJSON(out))
"""
    by_r = json.loads(run_r(tmp_path, body))
    for pattern, matched_in_r in zip(PATTERNS, by_r, strict=True):
        variable = Variable(name="x", label="x", definition="x", type="text", pattern=pattern)
        empty = Dictionary(path=Path("design/data_dictionary.yaml"), variables=(variable,))
        found = quality.check_variable(variable, PATTERN_TEXTS, empty)["not_matching"]
        in_python = [row in found for row in range(len(PATTERN_TEXTS))]
        missing = [row for row, text in enumerate(PATTERN_TEXTS) if not text.strip(" \t\r\n")]
        in_r = [flag and row not in missing for row, flag in enumerate(matched_in_r)]
        assert in_python == in_r, pattern


def _project(root: Path, minimum: int | None) -> Path:
    for sub in ("analysis", "design", "results"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    custodian = "" if minimum is None else f"custodian:\n  minimum_cell_count: {minimum}\n"
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "R"\nenglish_variant: en-GB\n' + custodian,
        encoding="utf-8",
    )
    (root / "design" / "data_dictionary.yaml").write_bytes(
        (DATA / "design" / "data_dictionary.yaml").read_bytes()
    )
    for name in ("run_r.R", "run_py.py"):
        (root / "analysis" / name).write_text("# placeholder\n", encoding="utf-8")
    return root


def test_both_emitters_write_the_same_counts(tmp_path: Path) -> None:
    """A fragment from each, of the same table under a minimum of five, each in a project of
    its own (one key has one owner): the same keys, the same values, the same displays, and
    the dictionary declared as an input of each."""
    in_r = _project(tmp_path / "in_r", minimum=5)
    body = f"""
em <- mg_emitter("{(in_r / "analysis" / "run_r.R").as_posix()}")
data <- read.csv("{(DATA / "reports.csv").as_posix()}", colClasses = "character")
men <- data$sex == "1" & data$pregnant == "1"
flags <- em$check_data(data, computed = list(no_pregnant_men = men))
stopifnot(identical(which(flags[["age.out_of_range"]]), 3L))
em$write()
"""
    run_r(tmp_path, body, cwd=in_r)
    in_python = _project(tmp_path / "in_python", minimum=5)
    em = Emitter(in_python / "analysis" / "run_py.py", root=in_python)
    with (DATA / "reports.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    mask = [row["sex"] == "1" and row["pregnant"] == "1" for row in rows]
    em.check_data(rows, computed={"no_pregnant_men": mask})
    em.write()

    written = {}
    for root in (in_r, in_python):
        results, report = load_results(root / "results")
        assert report.ok, report.findings
        (fragment,) = results.fragments
        assert [record["path"] for record in fragment.inputs] == ["design/data_dictionary.yaml"]
        written[root.name] = {
            key: (v.value, v.display, v.quoted) for key, v in results.values.items()
        }
    assert written["in_r"] == written["in_python"]
    assert written["in_r"]["quality.age.out_of_range"] == (1, "<5", False)


def test_r_refuses_what_python_refuses(tmp_path: Path) -> None:
    body = f"""
dictionary <- mg_read_dictionary("{(DATA / "design" / "data_dictionary.yaml").as_posix()}")
said <- function(expr) tryCatch({{ expr; "nothing" }}, error = function(e) conditionMessage(e))
cat(said(mg_check_table(dictionary, list(report_id = c("R0001", "R0002")),
                        computed = list(no_pregnant_men = TRUE))), "\\n")
cat(said(mg_check_table(dictionary, list(report_id = c("R0001", "R0002")),
                        computed = list(no_pregnant_men = c(TRUE, NA)))), "\\n")
cat(said(mg_check_table(dictionary, list(other = "x"))), "\\n")
cat(said(mg_check_table(dictionary, list(age = "1"), dataset = "reac")), "\\n")
clash <- dictionary
clash$variables[[2]]$name <- "REPORT_ID"
cat(said(mg_check_table(clash, list(age = "1"))), "\\n")
"""
    said = run_r(tmp_path, body).splitlines()
    assert "1 truth values for a table of 2 rows" in said[0]
    assert "other than TRUE or FALSE" in said[1]
    assert "no column the data dictionary lists" in said[2]
    assert "lists no dataset reac; it lists none" in said[3]
    assert "report_id and REPORT_ID would both be counted under quality.report_id" in said[4]
