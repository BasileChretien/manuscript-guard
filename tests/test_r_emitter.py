"""The R emitter must produce a fragment the Python gates accept.

Cross-language agreement is the whole reason the results file is a contract rather than an
implementation detail, so it gets a test that actually runs R rather than a promise in the
documentation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_results, validate
from manuscript_guard.emit import read_digest, sha256_of

REPO = Path(__file__).resolve().parent.parent
EMIT_R = REPO / "r" / "manuscriptguard" / "R" / "emit.R"


def find_rscript() -> str | None:
    found = shutil.which("Rscript")
    if found:
        return found
    candidates = sorted(Path("C:/Program Files/R").glob("R-*/bin/x64/Rscript.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


RSCRIPT = find_rscript()
pytestmark = pytest.mark.skipif(RSCRIPT is None, reason="R is not installed")

SCRIPT = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(root)s/analysis/01_r.R", inputs = "%(root)s/data/tiny.csv")
em$value("cohort.n_reports", 4000L)
em$value("cohort.n_sites", 12)
em$value("ror.point", 3.4211, digits = 2)
em$value("model.aic", 918.22, digits = 1, quoted = FALSE)
em$value("cohort.label", "2015-2024")
em$interval("prr", 2.5104, 1.8022, 3.4411, digits = 2)
em$interval("prr", low = 1.9411, high = 3.1002, level = "90%%", digits = 2)
em$table(
  "baseline",
  list("Group", em$cell("Exposed (n = {})", 412L), "ROR", "p", "n/N"),
  list(
    list(
      "Hepatic injury",
      77L,
      em$cell("{} (95%% CI {} to {})", list(3.84, 2), list(2.10, 2), list(7.02, 2)),
      em$cell("{}", list(0.00000032, "<0.001")),
      em$cell("{}/{}", 77L, 412L)
    )
  ),
  caption = "Reports by group."
)
em$code_list(
  "outcome_codes",
  list(
    list(concept = "Hepatic injury", system = "ICD-10", codes = c("K71.0", "K71.9")),
    list(concept = "Hepatic injury", system = "MedDRA PT", codes = c("10019663"))
  ),
  caption = "Code lists used to identify the outcome (RECORD 6.1)."
)
em$write()
"""


@pytest.fixture
def r_project(tmp_path: Path) -> Path:
    root = tmp_path / "rpaper"
    for sub in ("analysis", "data", "manuscript", "results"):
        (root / sub).mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "R"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "data" / "tiny.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (root / "analysis" / "01_r.R").write_text("# placeholder\n", encoding="utf-8")

    script = tmp_path / "run.R"
    script.write_text(
        SCRIPT % {"emit": EMIT_R.as_posix(), "root": root.as_posix()}, encoding="utf-8"
    )
    out = subprocess.run(
        [RSCRIPT, "--vanilla", str(script)],
        capture_output=True,
        text=True,
        # R reports errors in the system locale, which on this machine is not cp1252 and on
        # CI is not the same as here. Decoding with the default killed the harness with a
        # UnicodeDecodeError, which reads as a failure in the code under test.
        encoding="utf-8",
        errors="replace",
        cwd=root,
    )
    if out.returncode == 3:
        pytest.skip("R packages jsonlite and digest are not installed")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    return root


def test_r_fragment_matches_the_schema(r_project: Path) -> None:
    fragment = r_project / "results" / "01_r.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    report = validate(document, "results", fragment)
    assert report.ok, report.render()


def test_r_fragment_loads_and_formats_like_python(r_project: Path) -> None:
    results, report = load_results(r_project / "results")
    assert report.ok, report.render()
    assert results.values["cohort.n_reports"].display == "4000"
    assert results.values["cohort.n_sites"].display == "12", "whole-number doubles read as counts"
    assert results.values["ror.point"].display == "3.42"
    assert results.values["model.aic"].quoted is False
    assert results.values["cohort.label"].display == "2015-2024"


def test_r_writes_a_usable_digest_sidecar(r_project: Path) -> None:
    fragment = r_project / "results" / "01_r.json"
    assert read_digest(fragment) == sha256_of(fragment)


def test_r_can_express_an_interval_at_all(r_project: Path) -> None:
    """The sentence a disproportionality paper exists to carry, from R.

    R had only `value()`, so an R analysis could publish three keys named point, ci_low and
    ci_high and no gate could know they were one estimate. `interval-reversed` therefore
    could not fire on an R project, whatever the manuscript said — the check was Python-only
    without anything saying so.
    """
    results, report = load_results(r_project / "results")
    assert report.ok, report.render()
    assert results.values["prr.point"].display == "2.51"
    low, high = results.values["prr.ci_low"], results.values["prr.ci_high"]
    assert (low.bounds, low.bound) == ("prr.point", "low")
    assert (high.bounds, high.bound) == ("prr.point", "high")


def test_r_and_python_derive_the_same_keys_for_a_level(r_project: Path) -> None:
    """The same call in either language has to produce the same keys.

    Otherwise a manuscript's bindings depend on which language the analysis was written in,
    and porting an analysis silently breaks every sentence that quotes the second interval.
    """
    from manuscript_guard.emit import Emitter

    results, report = load_results(r_project / "results")
    assert report.ok, report.render()

    python = Emitter(r_project / "analysis" / "01_r.R", root=r_project)
    python.interval("prr", 2.5104, 1.8022, 3.4411, digits=2)
    python.interval("prr", low=1.9411, high=3.1002, level="90%", digits=2)

    from_r = {k for k in results.values if k.startswith("prr.")}
    assert from_r == set(python.document()["values"]), from_r
    assert results.values["prr.ci90_low"].level == "90%"
    assert results.values["prr.ci90_low"].display == "1.94"


BRACKET_CHECK = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(root)s/analysis/01_r.R", inputs = "%(root)s/data/tiny.csv")
ok <- tryCatch({ em$interval("ror", 12.0, 2.10, 7.02, digits = 2); TRUE },
               error = function(e) FALSE)
if (isTRUE(ok)) { cat("ACCEPTED\\n"); quit(status = 1) }
cat("REFUSED\\n")
"""


def test_r_refuses_an_interval_that_does_not_bracket_its_estimate(r_project: Path) -> None:
    """Mirroring the Python emitter, which has refused this since it gained `interval()`."""
    script = r_project / "bracket.R"
    script.write_text(
        BRACKET_CHECK % {"emit": EMIT_R.as_posix(), "root": r_project.as_posix()},
        encoding="utf-8",
    )
    out = subprocess.run(
        [RSCRIPT, "--vanilla", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=r_project,
    )
    if out.returncode == 3:
        pytest.skip("R packages jsonlite and digest are not installed")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    assert "REFUSED" in out.stdout


DISPLAY_CHECK = """
source("%(emit)s")
cases <- list(
  list("ror", 0.9487, "3.84 (95%% CI 2.10 to 7.02)", FALSE),
  list("ror", 0.9487, "3.84", FALSE),
  list("n", 41200, "99999", FALSE),
  list("ror", 0.9487, "0.95", TRUE),
  list("n", 41200, "41,200", TRUE),
  list("pct", 12.4, "12.4%%", TRUE),
  list("lab", "2015-2024", "2015-2024", TRUE),
  list("r", 3.4211, "3.42", TRUE),
  # Comparators. R had no branch for these at all, so a p-value too small to state was
  # legal in Python and an error in R - the divergence this whole test exists to prevent,
  # and it survived here until a cross-language *table* test tripped over it. The cases
  # below are the ones test_emit.py asserts on the Python side.
  list("p", 0.0000004, "<0.001", TRUE),
  list("p", 0.0000004, "< 0.001", TRUE),
  list("n", 1200, ">1000", TRUE),
  list("p", 0.04, "≤0.05", TRUE),
  list("p", 0.4, "<0.001", FALSE),
  list("n", 900, ">1000", FALSE),
  # Scientific notation, in the two spellings a paper uses. R had only the programmer's one,
  # and its tolerance was computed from the mantissa alone - so it accepted a display of
  # "9.99e-6" for a value of 1.2e-6 while Python refused it. A live divergence in the
  # cross-language contract that this harness missed because no case carried an exponent.
  list("p", 0.0000000032, "3.2e-9", TRUE),
  list("p", 0.0000000032, "3.2 × 10⁻⁹", TRUE),
  list("p", 0.0000000032, "3.2 x 10^-9", TRUE),
  list("p", 0.0000000032, "3.2 × 10⁻⁸", FALSE),
  list("p", 3.2, "3.2 × 10⁻⁹", FALSE),
  list("v", 0.0000012, "1.2 × 10⁻⁶", TRUE),
  list("v", 0.0000012, "9.99 × 10⁻⁶", FALSE)
)
for (c in cases) {
  ok <- tryCatch({ mg_check_display(c[[1]], c[[2]], c[[3]]); TRUE }, error = function(e) FALSE)
  if (!identical(ok, c[[4]])) {
    cat("MISMATCH:", c[[1]], c[[3]], "expected", c[[4]], "got", ok, "\\n")
    quit(status = 1)
  }
}
cat("AGREED\\n")
"""


def test_r_and_python_agree_on_what_a_display_may_be(tmp_path: Path) -> None:
    """The results fragment is a cross-language contract.

    A rule enforced on one side only is a rule an author steps around by switching language,
    so the display check added to the Python emitter had to be mirrored in R — and the two
    have to keep agreeing. These are the same cases `tests/test_emit.py` asserts for Python.
    """
    script = tmp_path / "display.R"
    script.write_text(DISPLAY_CHECK % {"emit": EMIT_R.as_posix()}, encoding="utf-8")
    out = subprocess.run([RSCRIPT, "--vanilla", str(script)], capture_output=True, text=True)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    assert "AGREED" in out.stdout


def test_r_writes_lf_endings_like_the_python_emitter(r_project: Path) -> None:
    """`writeLines(x, path)` opens a text connection, which is CRLF on Windows.

    `useBytes = TRUE` does not change that — it concerns encoding, not line endings. So an
    R analysis on Windows produced a byte-different fragment from the same analysis on
    Linux, and because the guarantee is a byte digest over the file, a co-author checking
    it out on the other platform saw `results-edited` on a file nobody had touched.
    """
    for name in ("01_r.json", "01_r.json.sha256"):
        raw = (r_project / "results" / name).read_bytes()
        assert b"\r\n" not in raw, name


# --------------------------------------------------- tables, across the language boundary


def test_r_emits_a_table_the_schema_accepts(r_project: Path) -> None:
    fragment = r_project / "results" / "01_r.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    report = validate(document, "results", fragment)
    assert report.ok, report.render()
    assert document["tables"]["baseline"]["rows"][0][4] == "77/412"
    assert document["tables"]["baseline"]["columns"][1] == "Exposed (n = 412)"
    assert document["tables"]["baseline"]["rows"][0][3] == "<0.001"
    assert document["code_lists"]["outcome_codes"][0]["codes"] == ["K71.0", "K71.9"]


def test_an_r_table_passes_the_gate_that_judges_a_python_one(r_project: Path) -> None:
    """The point of moving the cell rule out of the emitter.

    G2 reads the fragment, so it applies to a table whichever language wrote it. If R could
    emit tables the gate did not judge, "tables are emitted, not written" would be a rule an
    author steps around by switching language.
    """
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import _emitted_tables

    results, report = load_results(r_project / "results")
    assert report.ok, report.render()
    assert not _emitted_tables(results, Classifier.load()).findings


def test_the_same_table_from_both_languages_produces_the_same_fragment(
    r_project: Path, tmp_path: Path
) -> None:
    """The contract is the fragment, so the fragments have to agree."""
    from manuscript_guard.emit import Emitter

    root = tmp_path / "pypaper"
    (root / "analysis").mkdir(parents=True)
    (root / "results").mkdir()
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "P"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    script = root / "analysis" / "01_r.py"
    script.write_text("# placeholder\n", encoding="utf-8")

    em = Emitter(script, root=root)
    em.value("cohort.n_reports", 4000)
    em.table(
        "baseline",
        ["Group", em.cell("Exposed (n = {})", 412), "ROR", "p", "n/N"],
        [
            [
                "Hepatic injury",
                77,
                em.cell("{} (95% CI {} to {})", (3.84, 2), (2.10, 2), (7.02, 2)),
                em.cell("{}", (0.00000032, "<0.001")),
                em.cell("{}/{}", 77, 412),
            ]
        ],
        caption="Reports by group.",
    )
    em.code_list(
        "outcome_codes",
        [
            {"concept": "Hepatic injury", "system": "ICD-10", "codes": ["K71.0", "K71.9"]},
            {"concept": "Hepatic injury", "system": "MedDRA PT", "codes": ["10019663"]},
        ],
        caption="Code lists used to identify the outcome (RECORD 6.1).",
    )
    python = em.document()
    r = json.loads((r_project / "results" / "01_r.json").read_text(encoding="utf-8"))

    assert r["tables"] == python["tables"]
    assert r["code_lists"] == python["code_lists"]


def test_r_refuses_a_number_typed_into_a_cell(tmp_path: Path) -> None:
    """The refusal has to be in both emitters, not only in the gate: a message naming the
    call you just made is worth more than a finding two commands later."""
    root = tmp_path / "rp"
    (root / "analysis").mkdir(parents=True)
    (root / "results").mkdir()
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "R"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "analysis" / "x.R").write_text("# placeholder\n", encoding="utf-8")
    script = tmp_path / "bad.R"
    script.write_text(
        f'source("{EMIT_R.as_posix()}")\n'
        f'em <- mg_emitter("{root.as_posix()}/analysis/x.R")\n'
        'em$table("t", list("Group", "n"), list(list("Exposed", "9999")))\n',
        encoding="utf-8",
    )
    out = subprocess.run(
        [RSCRIPT, "--vanilla", str(script)],
        capture_output=True,
        text=True,
        # R reports errors in the system locale, which on this machine is not cp1252 and on
        # CI is not the same as here. Decoding with the default killed the harness with a
        # UnicodeDecodeError, which reads as a failure in the code under test.
        encoding="utf-8",
        errors="replace",
        cwd=root,
    )
    assert out.returncode != 0
    assert "number written as text" in out.stderr


ROUNDING_CHECK = """
source("%(emit)s")
# A rounding that turns a real number into zero is not a rounding of it.
bad <- tryCatch({ mg_display("p", 0.0000000032, NULL, 2); TRUE }, error = function(e) FALSE)
if (isTRUE(bad)) { cat("ACCEPTED 0.00\n"); quit(status = 1) }
neg <- tryCatch({ mg_display("d", -0.000000001, NULL, 2); TRUE }, error = function(e) FALSE)
if (isTRUE(neg)) { cat("ACCEPTED -0.00\n"); quit(status = 1) }
# A value that really is zero still rounds.
if (!identical(mg_display("z", 0, NULL, 2), "0.00")) { cat("ZERO BROKEN\n"); quit(status = 1) }
if (!identical(mg_display("r", 3.4211, NULL, 2), "3.42")) { cat("BROKEN\n"); quit(status = 1) }
cat("AGREED\n")
"""


def test_r_and_python_agree_that_rounding_to_zero_is_not_rounding(tmp_path: Path) -> None:
    """The same case `tests/test_emit.py` asserts for Python.

    A p-value of 3.2e-9 emitted with two decimal places was published as "0.00" in either
    language, which is the emitter printing a number that is not the number.
    """
    script = tmp_path / "rounding.R"
    script.write_text(ROUNDING_CHECK % {"emit": EMIT_R.as_posix()}, encoding="utf-8")
    out = subprocess.run(
        [RSCRIPT, "--vanilla", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "AGREED" in out.stdout


def test_both_emitters_digest_a_script_the_same_way(tmp_path: Path) -> None:
    """`generated_by_sha256` is written by whichever emitter ran and read by one gate.

    If R and Python disagree about a script's digest, an R-written fragment and a
    Python-written one describe the same file differently, and G1's answer depends on which
    language the analysis happened to be in. Both normalise line endings, because git rewrites
    them on checkout and CRLF instead of LF cannot change what a script computed.
    """
    from manuscript_guard.emit import source_digest

    variants = {
        "lf.py": b"x = 1\ny = 2\n",
        "crlf.py": b"x = 1\r\ny = 2\r\n",
        "cr.py": b"x = 1\ry = 2\r",
        "changed.py": b"x = 1\ny = 3\n",
    }
    for name, content in variants.items():
        (tmp_path / name).write_bytes(content)

    probe = tmp_path / "probe.R"
    # The same MISSING_DEPS guard the other R script in this file carries. Without it a
    # runner that has R but not `digest` — which is every windows-latest runner in this
    # repository's CI — dies inside mg_source_digest with a bare non-zero exit. That used to
    # be swallowed by a blanket skip, so this test was quietly not running on Windows at all;
    # tightening the skip is what surfaced it.
    probe.write_text(
        'if (!requireNamespace("digest", quietly = TRUE)) {\n'
        '  cat("MISSING_DEPS\\n"); quit(status = 3)\n'
        "}\n"
        f'source("{EMIT_R.as_posix()}")\n'
        f'for (f in commandArgs(trailingOnly = TRUE)) cat(mg_source_digest(f), "\n")\n',
        encoding="utf-8",
        newline="\n",
    )
    names = list(variants)
    result = subprocess.run(
        [RSCRIPT, "--vanilla", str(probe), *[str(tmp_path / n) for n in names]],
        capture_output=True, text=True, timeout=120, check=False)
    # Skip only for the one condition that genuinely means "R cannot run this here". Skipping
    # on any non-zero exit would turn a syntax error or a digest regression in emit.R into a
    # skipped test, which reads exactly like a passing one.
    if "MISSING_DEPS" in result.stdout:
        pytest.skip("R is present but jsonlite/digest is not installed")
    assert result.returncode == 0, f"the R probe failed: {result.stderr.strip()[:400]}"

    from_r = dict(zip(names, result.stdout.split(), strict=True))
    for name in names:
        assert from_r[name] == source_digest(tmp_path / name), f"{name}: R and Python disagree"

    # And the normalisation must be real on both sides, not agreement on doing nothing.
    assert from_r["lf.py"] == from_r["crlf.py"] == from_r["cr.py"]
    assert from_r["changed.py"] != from_r["lf.py"]


PARAMETERS_R = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(script)s")
alpha <- em$parameter("alpha", 0.025)
z <- qnorm(1 - alpha / 2)
min_cases <- em$parameter("signal.min_cases", 3L)
em$parameter("forgotten", 7L)
signal <- 5 >= em$parameter("inline", 2L)
ratio <- em$parameter("ratio", 0.123456, digits = 2)
em$software("R")
em$software("stats")
em$write()
"""

PARAMETERS_PY = """
from statistics import NormalDist
from manuscript_guard.emit import Emitter
em = Emitter(__file__)
alpha = em.parameter("alpha", 0.025)
z = NormalDist().inv_cdf(1 - alpha / 2)
min_cases = em.parameter("signal.min_cases", 3)
em.parameter("forgotten", 7)
signal = 5 >= em.parameter("inline", 2)
ratio = em.parameter("ratio", 0.123456, digits=2)
em.software("python")
em.write()
"""


def _parameter_project(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "P"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    return root


def _run_r(script: Path, root: Path) -> subprocess.CompletedProcess:
    out = subprocess.run(
        [RSCRIPT, "--vanilla", str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=root,
    )  # fmt: skip
    if out.returncode == 3:
        pytest.skip("R packages jsonlite and digest are not installed")
    return out


def test_r_and_python_declare_and_read_parameters_alike(tmp_path: Path) -> None:
    """One meaning in two languages: the same calls give the same keys, values, displays,
    and the same answer to whether the script reads what it declared."""
    import runpy

    root = _parameter_project(tmp_path)
    r_script = root / "analysis" / "params.R"
    r_script.write_text(
        PARAMETERS_R % {"emit": EMIT_R.as_posix(), "script": r_script.as_posix()},
        encoding="utf-8",
    )
    out = _run_r(r_script, root)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    py_script = root / "analysis" / "params.py"
    py_script.write_text(PARAMETERS_PY, encoding="utf-8")

    def written(name: str) -> dict:
        path = root / "results" / name
        document = json.loads(path.read_text(encoding="utf-8"))
        validate(document, "results", path)
        return document["values"]

    from_r = written("params.json")
    runpy.run_path(str(py_script), run_name="__main__")
    from_python = written("params.json")
    params_r = {k: v for k, v in from_r.items() if k.startswith("param.")}
    params_py = {k: v for k, v in from_python.items() if k.startswith("param.")}
    assert params_r == params_py
    assert params_py["param.alpha"] == {
        "value": 0.025, "display": "0.025", "role": "parameter", "read": True,
    }  # fmt: skip
    assert [params_py[f"param.{k}"]["read"] for k in ("signal.min_cases", "forgotten")] == [
        False,
        False,
    ]


UNFOLLOWED_R = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(script)s")
cfg <- list()
cfg$alpha <- em$parameter("in_a_list", 0.05)
cfg[["beta"]] <- em$parameter("in_a_list_by_name", 0.2)
env <- new.env()
env$min_cases <- em$parameter("in_an_environment", 3L)
both <- list(low = em$parameter("an_argument", 1L))
returned <- function() {
  1
  em$parameter("returned", 2L)  # the value of the block
}
returned_too <- function() {
  em$parameter("returned_too", 6L)
  # a line of comment after it
}
dropped <- function() {
  em$parameter("dropped", 4L)  # not the last
  1
}
signal <- returned() + returned_too() + dropped() + cfg$alpha + env$min_cases
level <- em$parameter("assigned_again", 0.1)
level <- 0.5
if (signal > 0) em$parameter("unbraced", 5L)
em$write()
"""


def test_r_claims_nothing_where_a_parameter_goes_unfollowed(tmp_path: Path) -> None:
    """Into a list or an environment the value is not followed, and R says nothing of it, as
    Python says nothing of an attribute. So does a call that is the value of its block,
    which a comment typed after it used to turn into a parameter never read. The last two
    are the limits DESIGN.md writes down: a name spelt the same anywhere in the file is a
    read, and so is a call with no braces round it and nothing reading it."""
    root = _parameter_project(tmp_path)
    script = root / "analysis" / "unfollowed.R"
    script.write_text(
        UNFOLLOWED_R % {"emit": EMIT_R.as_posix(), "script": script.as_posix()},
        encoding="utf-8",
    )
    out = _run_r(script, root)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    path = root / "results" / "unfollowed.json"
    values = json.loads(path.read_text(encoding="utf-8"))["values"]
    read = {
        key.removeprefix("param."): entry.get("read")
        for key, entry in values.items()
        if key.startswith("param.")
    }
    assert read == {
        "in_a_list": None,
        "in_a_list_by_name": None,
        "in_an_environment": None,
        "an_argument": True,
        "returned": None,
        "returned_too": None,
        "dropped": False,
        "assigned_again": True,
        "unbraced": True,
    }


def test_r_software_is_the_version_the_session_loaded(tmp_path: Path) -> None:
    root = _parameter_project(tmp_path)
    script = root / "analysis" / "soft.R"
    script.write_text(
        PARAMETERS_R % {"emit": EMIT_R.as_posix(), "script": script.as_posix()},
        encoding="utf-8",
    )
    out = _run_r(script, root)
    assert out.returncode == 0, out.stderr
    values = json.loads((root / "results" / "soft.json").read_text(encoding="utf-8"))["values"]
    for key in ("software.r", "software.stats"):
        assert values[key]["role"] == "software" and values[key]["label"] is True
        assert values[key]["value"] == values[key]["display"]


@pytest.mark.parametrize(
    ("call", "refusal"),
    [
        ('em$software("splines")', "has not loaded it"),
        ('em$parameter("Alpha", 0.05)', "lowercase letters"),
    ],
)
def test_r_refuses_what_python_refuses(tmp_path: Path, call: str, refusal: str) -> None:
    root = _parameter_project(tmp_path)
    script = root / "analysis" / "refused.R"
    script.write_text(
        f'source("{EMIT_R.as_posix()}")\nem <- mg_emitter("{script.as_posix()}")\n{call}\n',
        encoding="utf-8",
    )
    out = _run_r(script, root)
    assert out.returncode != 0 and refusal in out.stderr, out.stderr


MODEL_R = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(script)s")
data <- read.csv("%(data)s", stringsAsFactors = FALSE)
em$variable("g", "categorical", label = "group", levels = c("a", "b", "c"), reference = "a",
            values = data$g)
fit <- glm(y ~ x + g, data = data, family = binomial())
em$model("adjusted", fit, name = "Adjusted model", description = "The primary analysis.",
         unit = "pid")
em$model("subset", glm(y ~ x, data = data, family = binomial(), subset = pid < 40),
         name = "On a subset", unit = "pid")
em$write()
"""


OFFSET_R = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(script)s")
d <- data.frame(event = c(0, 1, 0, 1, 0, 0, 1, 0), x = 1:8,
                time = c(2, 3, 1.5, 4, 2.5, 3.5, 1, 2))
em$variable("event", "binary", label = "event", levels = c(0, 1))
em$variable("x", "continuous", label = "x")
em$model("rate", glm(event ~ x + offset(log(time)), family = poisson, data = d), name = "Rate")
em$model("risk", glm(event ~ x, family = poisson, data = d), name = "Risk")
em$write()
"""


def test_r_records_an_offset(tmp_path: Path) -> None:
    """Round 1 of #289: a Poisson model of events over person-time is a rate model."""
    root = _parameter_project(tmp_path)
    script = root / "analysis" / "offset.R"
    script.write_text(OFFSET_R % {"emit": EMIT_R.as_posix(), "script": script.as_posix()},
                      encoding="utf-8")  # fmt: skip
    out = _run_r(script, root)
    assert out.returncode == 0, out.stderr
    models = json.loads((root / "results" / "offset.json").read_text(encoding="utf-8"))["models"]
    assert models["rate"]["offset"] is True
    assert "offset" not in models["risk"]


def test_r_and_python_read_the_same_model_from_the_same_data(tmp_path: Path) -> None:
    """One card in two languages: how each variable entered, the counts, the events by level
    and the kind of model agree; only the formula's spelling is each language's own."""
    pd = pytest.importorskip("pandas")
    sm = pytest.importorskip("statsmodels.api")
    smf = pytest.importorskip("statsmodels.formula.api")
    import random

    from manuscript_guard.contracts.models import engine_of
    from manuscript_guard.emit import Emitter

    root = _parameter_project(tmp_path)
    draw = random.Random(2)
    rows = [
        {"y": int(draw.random() < 0.3), "x": i % 10, "g": "abc"[i % 3], "pid": i // 3}
        for i in range(300)
    ]
    data = pd.DataFrame(rows)
    data["x"] = data["x"].astype(float)
    data.loc[7, "x"] = float("nan")
    csv = root / "data.csv"
    data.to_csv(csv, index=False, na_rep="NA")

    script = root / "analysis" / "model.R"
    script.write_text(
        MODEL_R % {"emit": EMIT_R.as_posix(), "script": script.as_posix(), "data": csv.as_posix()},
        encoding="utf-8",
    )
    out = _run_r(script, root)
    assert out.returncode == 0, out.stderr
    path = root / "results" / "model.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    validate(document, "results", path)
    from_r = document["models"]["adjusted"]

    em = Emitter(root / "analysis" / "model.R", root=root)
    fit = smf.glm("y ~ x + C(g, Treatment('a'))", data, family=sm.families.Binomial()).fit()
    em.model("adjusted", fit, name="Adjusted model", description="The primary analysis.",
             unit="pid")  # fmt: skip
    on_subset = smf.glm("y ~ x", data, subset=data["pid"] < 40, family=sm.families.Binomial())
    em.model("subset", on_subset.fit(), name="On a subset", unit="pid")
    from_python = em.document()["models"]["adjusted"]
    # Round 1 of #268: the units of the rows a subset leaves, counted alike.
    assert em.document()["models"]["subset"]["unit"] == document["models"]["subset"]["unit"]
    assert document["models"]["subset"]["unit"] == {"column": "pid", "units": 40}
    # Item 36: the rows each fit used, by their labels: R numbers rows from 1 and pandas from
    # 0, and the eighth row, with no x, is in neither.
    from manuscript_guard.emit import rows_digest

    assert from_r["rows_sha256"] == rows_digest(str(i) for i in range(1, 301) if i != 8)
    assert "offset" not in from_r
    assert from_python["rows_sha256"] == rows_digest(str(i) for i in range(300) if i != 7)

    def facts(card: dict) -> dict:
        entered = sorted(
            (r["variables"][0], r["as"], tuple(r.get("levels", ())), r.get("reference"))
            for t in card["terms"] for r in t["entered"]
        )  # fmt: skip
        keep = ("parameters", "n_input", "n_used", "n_dropped", "converged", "events",
                "events_by_level", "name", "description", "unit")  # fmt: skip
        return {
            "kind": engine_of(card["engine"]).kind,
            "outcome": card["outcome"]["variables"],
            "entered": entered,
            **{key: card.get(key) for key in keep},
        }

    assert facts(from_r) == facts(from_python)
    assert from_python["unit"] == {"column": "pid", "units": 100}
    assert (from_r["covariance"], from_python["covariance"]) == ("model-based", "nonrobust")
    assert document["variables"]["g"]["observed"] == {
        "distinct": 3, "missing": 0, "levels": ["a", "b", "c"],
    }  # fmt: skip


NEEDS_R = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
em <- mg_emitter("%(script)s")
record <- function(key, fit) em$model(key, fit, name = key)
em$value("fits", 1L)
"""

FITS_R = NEEDS_R + """
set.seed(1)
n <- 300
d <- data.frame(
  y = rbinom(n, 1, 0.4), drug = sample(c("X", "Y"), n, TRUE), age = rnorm(n, 50, 10),
  stage = sample(c("I", "II", "III", "IV"), n, TRUE), score = rnorm(n, 5, 2),
  stringsAsFactors = FALSE
)
d$exposed <- d$drug == "X"
em$variable("y", "binary", label = "the outcome", levels = c(0, 1), values = d$y)
em$variable("exposed", "binary", label = "exposure", levels = c(FALSE, TRUE),
            values = d$exposed)
em$variable("age", "continuous", label = "age")
em$variable("stage", "categorical", label = "stage", levels = c("I", "II", "III", "IV"),
            reference = "I", values = d$stage)
em$variable("score", "continuous", label = "score")
knots <- c(40, 60)
age_breaks <- c(0, 40, 60, 120)
cutoff <- 5
late <- c("III", "IV")
record("logical", glm(y ~ exposed, binomial, data = d))
record("spline", glm(y ~ splines::ns(age, knots = knots), binomial, data = d))
record("bands", glm(y ~ cut(age, breaks = age_breaks), binomial, data = d))
record("linear", lm(score ~ splines::ns(age, knots = knots), data = d))
record("dichotomised", glm(I(score > cutoff) ~ I(stage == "IV") + age, binomial, data = d))
record("negated", glm(y ~ I(!(stage %%in%% late)), binomial, data = d))
record("bare", glm(y ~ age >= 65, binomial, data = d))
record("factored", glm(y ~ factor(stage), binomial, data = d))
record("as_logical", glm(y ~ factor(stage == "IV"), binomial, data = d))
record("trend", glm(y ~ as.numeric(factor(stage)), binomial, data = d))
record("no_y", glm(y ~ factor(stage), binomial, data = d, y = FALSE))
yy <- d$y
aa <- d$age
record("vectors", glm(yy ~ splines::ns(aa, knots = knots), binomial))
em$write()
"""


def _judged_from_r(root: Path, text: str, **paths: str) -> tuple[dict, dict[str, set[str]]]:
    """The fragment an R script wrote, and what G15 says of each model in it."""
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.gates import check_models

    (root / "manuscript").mkdir()
    (root / "manuscript" / "main.md").write_text("# Methods\n\nText.\n", encoding="utf-8")
    script = root / "analysis" / "fits.R"
    script.write_text(
        text % {"emit": EMIT_R.as_posix(), "script": script.as_posix(), **paths}, encoding="utf-8"
    )
    out = _run_r(script, root)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    path = root / "results" / "fits.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert validate(document, "results", path).ok
    project, _ = load_project(root)
    _namespace, results, _literature, loaded = load_namespace(project)
    assert loaded.ok, loaded.render(root)
    said: dict[str, set[str]] = {key: set() for key in document["models"]}
    for finding in check_models(project, results).findings:
        key = finding.message.split("'")[1] if finding.message.startswith("model '") else ""
        said.setdefault(key, set()).add(finding.code)
    return document, said


@pytest.fixture(scope="module")
def r_fits(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict[str, set[str]]]:
    return _judged_from_r(_parameter_project(tmp_path_factory.mktemp("fits")), FITS_R)


def _entered_in(document: dict, key: str) -> list[dict]:
    return [record for term in document["models"][key]["terms"] for record in term["entered"]]


def test_a_logical_predictor_in_r_is_a_binary_variable_entered_as_a_number(r_fits) -> None:
    """R gives a logical no `xlevels`, so the term is a number, and writes its two values
    FALSE and TRUE. Declared binary, that is what it is, and nothing is reported."""
    document, said = r_fits
    assert _entered_in(document, "logical") == [
        {"expression": "exposed", "variables": ["exposed"], "as": "numerical"}
    ]
    exposed = document["variables"]["exposed"]
    assert exposed["levels"] == ["FALSE", "TRUE"]
    assert exposed["observed"] == {"distinct": 2, "missing": 0, "levels": ["FALSE", "TRUE"]}
    assert said["logical"] == set() and "" not in said, said


@pytest.mark.parametrize(
    ("key", "variables", "codes"),
    [
        ("spline", ["age"], set()),
        # Bands of a continuous variable are a warning, as they were; `age_breaks` is not read.
        ("bands", ["age"], {"model-number-as-categories"}),
        # An lm keeps no copy of its data: the call's `data` is read again.
        ("linear", ["age"], set()),
        ("negated", ["stage"], set()),
        # With no `data` there are no columns to tell `knots` from: every name, as before.
        ("vectors", ["aa", "knots"], {"model-variable-undeclared"}),
    ],
)
def test_r_keeps_the_names_that_are_columns_of_the_data(
    r_fits, key: str, variables: list[str], codes: set[str]
) -> None:
    document, said = r_fits
    assert [record["variables"] for record in _entered_in(document, key)] == [variables]
    assert said[key] == codes


def test_r_knows_a_comparison_and_g15_does_not_hold_it_to_its_variable(r_fits) -> None:
    """`I(stage == "IV")` is a logical, entered as a number, of a variable declared
    categorical; `I(score > cutoff)` a binary outcome of a continuous one."""
    document, said = r_fits
    card = document["models"]["dichotomised"]
    assert card["outcome"] == {
        "expression": "I(score > cutoff)", "variables": ["score"], "comparison": True,
    }  # fmt: skip
    assert _entered_in(document, "dichotomised") == [
        {"expression": 'I(stage == "IV")', "variables": ["stage"], "as": "numerical",
         "comparison": True},
        {"expression": "age", "variables": ["age"], "as": "numerical"},
    ]  # fmt: skip
    assert card["events"] > 0 and said["dichotomised"] == set()
    for key in ("negated", "bare"):
        assert [r.get("comparison") for r in _entered_in(document, key)] == [True], key
        assert said[key] == set()


@pytest.mark.parametrize(
    ("key", "codes"),
    [
        ("factored", set()),
        ("trend", {"model-categories-as-number"}),
        # A comparison inside another call is not known for one, and is held to `stage`.
        ("as_logical", {"model-level-undeclared", "model-reference"}),
    ],
)
def test_r_marks_nothing_else_a_comparison(r_fits, key: str, codes: set[str]) -> None:
    document, said = r_fits
    assert not any("comparison" in record for record in _entered_in(document, key))
    assert "comparison" not in document["models"][key]["outcome"]
    assert said[key] == codes


def test_r_counts_the_events_of_a_fit_that_kept_its_outcome_and_of_no_other(r_fits) -> None:
    """`glm(..., y = FALSE)` keeps no outcome: no events are recorded for it, where 0 was."""
    models = r_fits[0]["models"]
    kept = models["factored"]
    assert kept["events"] == sum(kept["events_by_level"]["stage"].values()) > 0
    assert not {"events", "events_by_level"} & set(models["no_y"])


GROUPED_R = NEEDS_R + """
t <- read.csv("%(data)s", stringsAsFactors = FALSE)
t$n <- t$s + t$f
t$p <- t$s / t$n
t$q <- t$p * 0.999
for (name in c("s", "f", "n")) em$variable(name, "count", label = name)
em$variable("p", "continuous", label = "proportion of cases")
em$variable("q", "continuous", label = "another proportion")
em$variable("x", "binary", label = "exposure", levels = c(0, 1), values = t$x)
em$variable("g", "categorical", label = "group", levels = c("a", "b", "c"), reference = "a",
            values = t$g)
record("grouped", glm(cbind(s, f) ~ x + g, binomial, data = t))
record("of_n", glm(cbind(s, n - s) ~ x + g, binomial, data = t))
record("proportion", glm(p ~ x + g, binomial, weights = n, data = t))
record("unread", suppressWarnings(glm(q ~ x + g, binomial, weights = n, data = t)))
em$write()
"""


def test_r_and_python_read_the_same_grouped_table(tmp_path: Path) -> None:
    """`cbind(events, failures)`, and a proportion with the trials as weights, are fitted to
    the proportion of each row: its sum was recorded as the events, 1 for a table of 85. Both
    languages now record the events and the trials the table holds, and by level."""
    pd = pytest.importorskip("pandas")
    sm = pytest.importorskip("statsmodels.api")
    smf = pytest.importorskip("statsmodels.formula.api")
    import warnings

    from manuscript_guard.emit import read_statsmodels

    table = pd.DataFrame({
        "s": [10, 20, 30, 25, 0, 0], "f": [90, 80, 70, 75, 100, 100],
        "x": [0, 1, 0, 1, 0, 1], "g": ["a", "a", "b", "b", "c", "c"],
    })  # fmt: skip
    root = _parameter_project(tmp_path)
    csv = root / "table.csv"
    table.to_csv(csv, index=False)
    document, said = _judged_from_r(root, GROUPED_R, data=csv.as_posix())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # no events at level c, which is the point
        fit = smf.glm("s + f ~ x + C(g)", table, family=sm.families.Binomial()).fit()
    from_python = read_statsmodels(fit)

    def facts(card: dict) -> tuple:
        return card["events"], card["trials"], card["n_used"], card["events_by_level"]

    counted = (85, 600, 6, {"g": {"a": 30, "b": 55, "c": 0}})
    models = document["models"]
    assert facts(from_python) == counted
    for key in ("grouped", "of_n", "proportion"):
        assert facts(models[key]) == counted, key
        assert said[key] - {"model-not-converged"} == {"model-empty-level"}, key
    assert sorted(models["grouped"]["outcome"]["variables"]) == from_python["outcome"]["variables"]
    assert models["of_n"]["outcome"] == {"expression": "cbind(s, n - s)", "variables": ["s", "n"]}
    assert models["proportion"]["outcome"]["variables"] == ["p"]
    # A proportion whose events are not whole numbers is no table of counts: nothing is read.
    assert not {"events", "trials", "events_by_level"} & set(models["unread"])


STEPS_R = """
if (!requireNamespace("jsonlite", quietly = TRUE) || !requireNamespace("digest", quietly = TRUE)) {
  cat("MISSING_DEPS\\n"); quit(status = 3)
}
source("%(emit)s")
half <- function(x) x / 2
em <- mg_emitter("%(script)s")
a <- 10
b <- 20
em$step("ror", {
  # the ratio
  ror <- a / b
})
em$step("ci", {
  se <- half(sqrt(1 / a + 1 / b))
})
em$value("ror", ror, digits = 2)
em$value("se", se, digits = 3)
em$write()
"""

STEPS_PY = """
import math
from manuscript_guard.emit import Emitter


def half(x):
    return x / 2


em = Emitter(__file__)
a, b = 10, 20
with em.step("ror"):
    # the ratio
    ror = a / b
with em.step("ci"):
    se = half(math.sqrt(1 / a + 1 / b))
em.value("ror", ror, digits=2)
em.value("se", se, digits=3)
em.write()
"""


def _steps_from_r(root: Path, text: str) -> dict:
    script = root / "analysis" / "steps.R"
    script.write_text(
        text % {"emit": EMIT_R.as_posix(), "script": script.as_posix()}, encoding="utf-8"
    )
    out = _run_r(script, root)
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    path = root / "results" / "steps.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert validate(document, "results", path).ok
    return document["steps"]


def test_r_and_python_mark_steps_alike(tmp_path: Path) -> None:
    """The same steps in either language: the lines of the code inside the step, a digest,
    and the analysis's own functions it calls. The digests are each language's own."""
    import runpy

    root = _parameter_project(tmp_path)
    from_r = _steps_from_r(root, STEPS_R)
    (root / "analysis" / "steps.py").write_text(STEPS_PY, encoding="utf-8")
    runpy.run_path(str(root / "analysis" / "steps.py"))
    from_python = json.loads((root / "results" / "steps.json").read_text(encoding="utf-8"))
    from_python = from_python["steps"]
    shape = {name: {k: v for k, v in s.items() if k != "digest"} for name, s in from_r.items()}
    assert shape == {"ror": {"lines": [12, 12]}, "ci": {"lines": [15, 15], "follows": ["half"]}}
    assert {name: {k: v for k, v in step.items() if k not in ("digest", "lines")}
            for name, step in from_python.items()} == {"ror": {}, "ci": {"follows": ["half"]}}


def test_r_reads_a_step_as_code(tmp_path: Path) -> None:
    root = _parameter_project(tmp_path)
    before = _steps_from_r(root, STEPS_R)
    commented = _steps_from_r(root, STEPS_R.replace("# the ratio", "# the ratio of a to b"))
    assert commented["ror"]["digest"] == before["ror"]["digest"]
    changed = _steps_from_r(root, STEPS_R.replace("ror <- a / b", "ror <- b / a"))
    assert changed["ror"]["digest"] != before["ror"]["digest"]
    assert changed["ci"]["digest"] == before["ci"]["digest"]
    helper = _steps_from_r(root, STEPS_R.replace("x / 2", "x / 3"))
    assert helper["ci"]["digest"] != before["ci"]["digest"], "a function it calls is its code"


@pytest.mark.parametrize(
    ("call", "refusal"),
    [
        ('em$step("CI", { x <- 1 })', "lowercase letters"),
        ('em$step("a", { x <- 1 })\nem$step("a", { x <- 2 })', "two different blocks"),
    ],
)
def test_r_refuses_the_steps_python_refuses(tmp_path: Path, call: str, refusal: str) -> None:
    root = _parameter_project(tmp_path)
    script = root / "analysis" / "refused.R"
    # A step's digest needs the digest package, which an R without it cannot compute.
    needs = PARAMETERS_R.split("source(")[0]
    script.write_text(
        f'{needs}source("{EMIT_R.as_posix()}")\nem <- mg_emitter("{script.as_posix()}")\n{call}\n',
        encoding="utf-8",
    )
    out = _run_r(script, root)
    assert out.returncode != 0 and refusal in out.stderr, out.stderr
