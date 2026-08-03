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
        [RSCRIPT, "--vanilla", str(script)], capture_output=True, text=True, cwd=root
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
  list("r", 3.4211, "3.42", TRUE)
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
