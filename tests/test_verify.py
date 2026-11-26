"""Re-running the analysis, which is the check a recomputed digest cannot pass.

Every other check on `results/` asks whether the file has been disturbed, and that is a
question about a digest. A digest can be recomputed: an adversarial review edited a
fragment, ran sha256 into the sidecar, and G1 saw nothing — then did the same one level up,
changing the input data and rewriting the declared input hash in the same file that was
supposed to protect it.

This asks whether the analysis still produces the numbers. A result cannot be forged into
existence: either the code emits it or it does not.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_project
from manuscript_guard.emit import write_digest
from manuscript_guard.gates import check_freshness
from manuscript_guard.verify import VerifyError, to_report, verify


def run(project: Path):
    loaded, _report = load_project(project)
    return verify(loaded)


def fragment_of(project: Path) -> Path:
    return next((project / "results").glob("*.json"))


def freshness_codes(project: Path) -> set[str]:
    from manuscript_guard.contracts import load_namespace

    loaded, _ = load_project(project)
    _ns, results, _lit, _r = load_namespace(loaded)
    return {f.code for f in check_freshness(loaded, results).findings}


# ---------------------------------------------------------------- the point of it


def test_an_honest_project_reproduces(project: Path) -> None:
    result = run(project)
    assert result.ok, to_report(result).render(project)
    assert sum(len(c.agreed) for c in result.comparisons) > 10


def test_a_re_signed_edit_is_caught_even_though_g1_passes(project: Path) -> None:
    """The attack G1 cannot see, and the reason this command exists.

    Edit a value, recompute the sidecar, and every integrity check is satisfied — the
    fragment is exactly what its digest says it is. It is simply not what the analysis
    produces.
    """
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["value"] = 9.99
    document["values"]["ror.point"]["display"] = "9.99"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)

    assert "results-edited" not in freshness_codes(project), "G1 is satisfied, as expected"

    result = run(project)
    assert not result.ok
    differed = {key for c in result.comparisons for key, _was, _now in c.differed}
    assert "ror.point" in differed
    assert "rerun-differs" in {f.code for f in to_report(result).failures}


def test_a_difference_says_whether_the_analysis_declares_a_seed(project: Path) -> None:
    """Item 18: "set a seed" was said whether the analysis had one or not."""
    from manuscript_guard.verify import _unseeded

    assert "declares no seed" in _unseeded(())
    said = _unseeded(("param.seed",))
    assert "declares param.seed" in said and "no seed" not in said
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["value"] = 9.99
    document["values"]["ror.point"]["display"] = "9.99"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)
    hints = {f.hint for f in to_report(run(project)).failures if f.code == "rerun-differs"}
    assert hints == {_unseeded(())}, "the example declares no seed"


def test_a_version_found_on_another_machine_is_reported_and_reproduces(project: Path) -> None:
    """The example records the Python it ran under, and a re-run elsewhere runs under its own:
    that is the environment, said in a warning, and every result still has to agree."""
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"]["software.python"].update(value="2.7.18", display="2.7.18")
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)

    result = run(project)
    assert result.ok, to_report(result).render(project)
    found = [f for f in to_report(result).warnings if f.code == "rerun-other-software"]
    assert len(found) == 1 and "written with 2.7.18" in found[0].message
    # Round 2 of #306: the version is among the values counted, and not reproduced.
    from manuscript_guard.verify import render

    agreed = sum(len(c.agreed) for c in result.comparisons)
    assert f"{agreed}/{agreed + 1} values reproduced" in render(result, project)


def test_a_fit_s_last_digits_from_another_machine_reproduce(project: Path) -> None:
    """An iterative fit's last digits depend on the machine's linear algebra: CI on macOS
    found the adjusted ratio as 3.844764571463991 where Linux had written 3.844764571464015.
    Both print 3.845, and that is a reproduction; a change in the ninth digit is not."""
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    on_disk = document["values"]["ror_adjusted.point"]
    on_disk["value"] *= 1 + 6e-15
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)
    result = run(project)
    assert result.ok, to_report(result).render(project)

    on_disk["value"] *= 1 + 1e-7
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)
    differed = {key for c in run(project).comparisons for key, _was, _now in c.differed}
    assert differed == {"ror_adjusted.point"}


def test_a_result_relabelled_as_software_on_disk_is_still_a_difference(project: Path) -> None:
    """Which values are versions is read from the re-run, so a fragment edited to call a
    changed result "software" is caught like any other edit."""
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"]["ror.point"].update(value=9.99, display="9.99", role="software")
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)

    result = run(project)
    assert "rerun-differs" in {f.code for f in to_report(result).failures}


def test_edited_input_data_with_a_rewritten_hash_is_caught(project: Path) -> None:
    """The same attack one level up: the declared input hash lives in the file it protects."""
    from manuscript_guard.emit import sha256_of

    data = project / "data" / "reports.csv"
    data.write_text(
        data.read_text(encoding="utf-8") + "R99999,2024,example-drug,hepatic injury,Y,F,75+\n",
        encoding="utf-8",
    )
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["provenance"]["inputs"][0]["sha256"] = sha256_of(data)
    document["provenance"]["inputs"][0]["bytes"] = data.stat().st_size
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)

    assert "input-changed" not in freshness_codes(project), "G1 is satisfied, as expected"
    assert not run(project).ok


def test_a_value_the_analysis_no_longer_emits_is_reported(project: Path) -> None:
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["values"]["ror.invented"] = {"value": 1.0, "display": "1.00", "digits": 2}
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)

    result = run(project)
    assert not result.ok
    assert "ror.invented" in {k for c in result.comparisons for k in c.only_on_disk}


# ---------------------------------------------------------------- honest about itself


def test_an_analysis_that_cannot_run_is_reported_not_passed(project: Path) -> None:
    """Unverifiable and verified must not look the same."""
    (project / "analysis" / "01_disproportionality.py").write_text(
        "raise SystemExit(3)\n", encoding="utf-8"
    )
    result = run(project)
    assert not result.ok
    assert "rerun-failed" in {f.code for f in to_report(result).failures}


def test_a_language_with_no_runner_is_skipped_out_loud(project: Path, monkeypatch) -> None:
    """Skipping must not read as passing, in the exit code as well as in the report.

    This test used to assert `result.ok` on the grounds that nothing was checked so nothing
    failed, and that the report says so in words. The words were true and the exit code was
    not: `all([])` is True, so an R project on a machine without Rscript exited 0, and CI
    reads the exit code. That is the same "not checked looks like checked" failure this
    command was built to close one level down.
    """
    from manuscript_guard import verify as module

    monkeypatch.setattr(module, "RUNNERS", {})
    loaded, _ = load_project(project)
    result = module.verify(loaded)
    assert result.skipped
    assert result.verified_nothing
    assert not result.ok
    assert "not verified" in module.render(result, project)


def test_verify_raises_after_its_report_where_it_cannot_record_the_run(
    project: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "Assurance and verify"): an error writing
    `build/verify.json`, here a folder of that name, is a traceback after `verify` printed
    its report."""
    from manuscript_guard.cli import main

    (project / "build").mkdir(exist_ok=True)
    (project / "build" / "verify.json").mkdir()
    with pytest.raises(OSError):
        main(["verify", str(project)])
    assert "values reproduced by re-running the analysis." in capsys.readouterr().out


def test_a_fragment_whose_values_are_a_list_raises_after_the_report(
    project: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "Assurance and verify"): a results fragment whose
    `values` is a list, which its schema check fails already, raises after `verify`'s report
    where it was not re-run, here for want of a runner for its script."""
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_namespace

    (project / "analysis" / "03_other.jl").write_text("# julia\n", encoding="utf-8")
    (project / "results" / "03_other.json").write_text(json.dumps({
        "schema": "manuscript-guard/results/1",
        "provenance": {"generated_by": "analysis/03_other.jl",
                       "generated_at": "2026-01-01T00:00:00+00:00", "inputs": []},
        "values": [1, 2],
    }), encoding="utf-8")  # fmt: skip
    assert "schema-violation" in {f.code for f in load_namespace(load_project(project)[0])[3]
                                  .failures}  # fmt: skip
    with pytest.raises(AttributeError, match="'list' object has no attribute 'items'"):
        main(["verify", str(project)])
    printed = capsys.readouterr().out
    assert "[SKIP] 03_other.json: no runner for .jl on this machine" in printed
    assert "1 fragment(s) not verified." in printed


def test_only_naming_no_fragment_is_an_error(project: Path) -> None:
    """A typo, or a fragment renamed in a CI script, made verify permanently green."""
    loaded, _ = load_project(project)
    with pytest.raises(VerifyError, match="names no fragment"):
        verify(loaded, only=["nosuchfragment"])


def test_only_records_what_it_excluded(project: Path) -> None:
    """`--only` skipped the others with a bare `continue`, before the disclaimer.

    So `verify --only x` reported `fragments_skipped=0` while ignoring a fabricated
    fragment sitting beside it, and said "17/17 values reproduced" — which was true of x and
    silent about everything else.
    """
    import json

    other = project / "results" / "national.json"
    other.write_text(
        json.dumps(
            {
                "schema": "manuscript-guard/results/1",
                "provenance": {"generated_by": "analysis/01_disproportionality.py"},
                "values": {"national.ror": {"value": 3.84, "display": "3.84"}},
            }
        ),
        encoding="utf-8",
    )
    loaded, _ = load_project(project)
    result = verify(loaded, only=["01_disproportionality"])
    assert any(name == "national.json" for name, _why in result.skipped)
    assert "not verified" in __import__(
        "manuscript_guard.verify", fromlist=["render"]
    ).render(result, project)


def test_a_project_with_no_results_says_so(tmp_path: Path) -> None:
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="T")
    loaded, _ = load_project(root)
    with pytest.raises(VerifyError, match="no results fragments"):
        verify(loaded)


def test_the_real_results_are_never_touched(project: Path) -> None:
    """The analysis runs in a scratch copy, so verifying is safe on work in progress."""
    path = fragment_of(project)
    before = path.read_bytes()
    run(project)
    assert path.read_bytes() == before


def test_verify_does_not_leave_a_scratch_tree_behind(project: Path, tmp_path: Path) -> None:
    import tempfile

    before = set(Path(tempfile.gettempdir()).glob("manuscript-guard-verify-*"))
    run(project)
    assert set(Path(tempfile.gettempdir()).glob("manuscript-guard-verify-*")) == before


# ---------------------------------------------------------------- the script digest


def test_editing_the_analysis_is_caught_by_digest_not_by_mtime(project: Path) -> None:
    """`script-newer` compared modification times, and `touch` sets those.

    Editing the analysis and stamping the fragment forward hid the change completely. G1's
    own docstring says hashes are used "because timestamps lie" — which was true of the
    inputs and not of the code that read them.
    """
    import os

    script = project / "analysis" / "01_disproportionality.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    fragment = fragment_of(project)
    forward = script.stat().st_mtime + 600
    os.utime(fragment, (forward, forward))
    write_digest(fragment)

    assert "script-newer" in freshness_codes(project)


def _ci_from_helpers(project: Path, *, declared: bool) -> None:
    """The example with its normal quantile read from two helper modules, one under
    `analysis/` and one in `lib/`, the second declared an input or not, and run again."""
    import subprocess
    import sys

    script = project / "analysis" / "01_disproportionality.py"
    (project / "analysis" / "ci_helper.py").write_text("Z = 1.96\n", encoding="utf-8")
    (project / "lib").mkdir()
    (project / "lib" / "ci_lib.py").write_text("Z = 1.96\n", encoding="utf-8")
    text = script.read_text(encoding="utf-8").replace(
        "        z = round(NormalDist().inv_cdf(1 - alpha / 2), 2)\n",
        "        import sys\n        sys.path.insert(0, str(ROOT / 'lib'))\n"
        "        import ci_helper\n        import ci_lib\n"
        "        assert ci_helper.Z == ci_lib.Z\n        z = ci_lib.Z\n",
    )
    if declared:
        text = text.replace('em = Emitter(__file__, ci_level="95%")',
                            'em = Emitter(__file__, ci_level="95%", inputs=["lib/ci_lib.py"])')
    script.write_text(text, encoding="utf-8")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         cwd=project)  # fmt: skip
    assert out.returncode == 0, out.stderr


def _g1_of(project: Path) -> list[tuple[str, str, str]]:
    from manuscript_guard.cli import _run_gates

    report, *_ = _run_gates(project)
    assert report.ok or "input-changed" in {f.code for f in report.failures}
    return sorted((f.code, f.severity, f.message) for f in report.findings
                  if f.gate == "G1" and f.severity != "info")  # fmt: skip


@pytest.mark.parametrize("declared", [False, True], ids=["imported only", "declared an input"])
def test_a_helper_the_script_imports_is_not_followed(project: Path, declared: bool) -> None:
    """A known gap (DESIGN.md, Known gaps, "G1 fails only on the script that wrote a results
    file and on the inputs it declared"): the 1.96 of the interval moved into a helper and
    changed to 2.58 with nothing run again. `check` passes, warning `analysis-newer` for the
    helper under `analysis/` and saying nothing of the one in `lib/`, and the results hold
    the old values; declared an input, the helper's change fails `input-changed`. `verify`
    sees the change either way."""
    import os
    import time

    from manuscript_guard.contracts import load_namespace

    _ci_from_helpers(project, declared=declared)
    assert _g1_of(project) == []
    before = load_namespace(load_project(project)[0])[0]["results.ror.ci_low"].display
    later = time.time() + 10
    for helper in (project / "analysis" / "ci_helper.py", project / "lib" / "ci_lib.py"):
        helper.write_text("Z = 2.58\n", encoding="utf-8")  # verify's run agrees with itself
        os.utime(helper, (later, later))
    newer = ("analysis-newer", "warn", "analysis/ci_helper.py changed after the newest "
             "results fragment")  # fmt: skip
    changed = ("input-changed", "fail", "input lib/ci_lib.py changed since these results "
               "were written")  # fmt: skip
    assert _g1_of(project) == ([newer, changed] if declared else [newer])
    assert load_namespace(load_project(project)[0])[0]["results.ror.ci_low"].display == before
    assert "rerun-differs" in {f.code for f in to_report(run(project)).failures}
    if not declared:
        # `build` passes the check and writes the old interval.
        from manuscript_guard.cli import main

        if shutil.which("pandoc") is None:
            pytest.skip("pandoc is not installed, so the build is not run")
        assert main(["build", str(project), "--offline"]) == 0
        built = (project / "build" / "manuscript.md").read_text(encoding="utf-8")
        assert f"(95% CI {before} to" in built


def test_an_older_fragment_without_the_digest_still_uses_mtime(project: Path) -> None:
    """A project written before the field existed degrades rather than breaking."""
    import os

    fragment = fragment_of(project)
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["provenance"].pop("generated_by_sha256", None)
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    script = project / "analysis" / "01_disproportionality.py"
    forward = fragment.stat().st_mtime + 600
    os.utime(script, (forward, forward))

    assert "script-newer" in freshness_codes(project)


def test_a_project_copied_for_verification_excludes_build(project: Path) -> None:
    """`build/` is regenerated and can be large; copying it makes verify slow for nothing."""
    (project / "build").mkdir(exist_ok=True)
    (project / "build" / "big.bin").write_bytes(b"0" * 1024)
    assert run(project).ok
    assert (project / "build" / "big.bin").exists()


def test_the_example_verifies_end_to_end() -> None:
    """The worked example is the fixture, so this is the whole loop under one command."""
    root = Path(__file__).resolve().parent.parent / "example"
    if not (root / "results").exists():
        pytest.skip("the example has not been run")
    loaded, _ = load_project(root)
    result = verify(loaded)
    assert result.ok, to_report(result).render(root)


def test_shutil_is_used_rather_than_a_partial_copy(project: Path) -> None:
    """Data files must reach the scratch tree, or every analysis fails for the wrong reason."""
    assert shutil.copytree is not None
    result = run(project)
    assert result.comparisons and result.comparisons[0].ran


def test_the_scratch_copy_has_no_git_a_limit_known_gaps_names(project: Path,
                                                               tmp_path: Path) -> None:  # fmt: skip
    """DESIGN.md, Known gaps: `verify` copies the project without `.git`, so an analysis that
    checks its own git provenance (a commit's place in the history, a tag) cannot run that
    check in the copy. Found taking the athlete-leakage study through the loop. The copy is
    staged with `_skip`, as `verify` stages it."""
    from manuscript_guard.verify import IGNORED_DIRS, _skip

    (project / ".git").mkdir()
    (project / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    copy = tmp_path / "copy"
    shutil.copytree(project, copy, symlinks=True, ignore=_skip)
    assert ".git" in IGNORED_DIRS
    assert not (copy / ".git").exists() and (copy / "analysis").is_dir()


# ------------------------------------------------------- which R, and for how long (item 9)
#
# Found writing a real paper (2026-11-26): `verify` ran whatever Rscript came first on PATH,
# R 4.3.3, while the analysis needed 4.6.1, and said nothing of which R it was; and the cohort
# script, slowed by a virus scanner reading the scratch copy, ran past a limit of 1800 s that
# nothing could raise.


def _limit(project: Path, given: int | None = None) -> int:
    from manuscript_guard.verify import time_limit

    loaded, _ = load_project(project)
    return time_limit(loaded, given)[0]


def _bare(tmp_path: Path) -> Path:
    """A project with nothing to re-run: what refuses an R or a limit refuses before that."""
    root = tmp_path / "bare"
    root.mkdir()
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "B"\nenglish_variant: en-GB\n',
        encoding="utf-8",
    )
    return root


def _with_verify_setting(project: Path, block: str) -> None:
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8") + f"\nverify: {block}\n",
                     encoding="utf-8")  # fmt: skip


def test_the_rscript_named_runs_an_r_script_the_flag_over_the_variable(
    tmp_path: Path, monkeypatch
) -> None:
    import sys

    from manuscript_guard.verify import RSCRIPT_VARIABLE, runner_for

    script = tmp_path / "01_model.R"
    other = shutil.which("git") or sys.executable
    monkeypatch.setenv(RSCRIPT_VARIABLE, other)
    assert runner_for(script)[0] == other
    assert runner_for(script, rscript=sys.executable)[0] == sys.executable
    assert runner_for(tmp_path / "report.Rmd", rscript=sys.executable)[0] == sys.executable
    # A Python script is run with this Python whatever names an R.
    assert runner_for(tmp_path / "01.py", rscript=other)[0] == sys.executable


def test_a_variable_naming_no_program_stops_verify_and_names_it(
    tmp_path: Path, monkeypatch
) -> None:
    from manuscript_guard.verify import RSCRIPT_VARIABLE

    monkeypatch.setenv(RSCRIPT_VARIABLE, str(tmp_path / "R-9.9.9" / "Rscript.exe"))
    with pytest.raises(VerifyError, match=RSCRIPT_VARIABLE):
        run(_bare(tmp_path))


def test_an_rscript_given_that_is_not_there_stops_verify(tmp_path: Path) -> None:
    loaded, _ = load_project(_bare(tmp_path))
    with pytest.raises(VerifyError, match="--rscript"):
        verify(loaded, rscript=str(tmp_path / "Rscript.exe"))


def test_the_limit_is_the_flag_then_the_variable_then_paper_yaml_then_1800(
    project: Path, monkeypatch
) -> None:
    from manuscript_guard.verify import TIMEOUT, TIMEOUT_VARIABLE

    monkeypatch.delenv(TIMEOUT_VARIABLE, raising=False)
    assert _limit(project) == TIMEOUT == 1800
    _with_verify_setting(project, "{timeout: 5400}")
    assert _limit(project) == 5400
    monkeypatch.setenv(TIMEOUT_VARIABLE, "3600")
    assert _limit(project) == 3600
    assert _limit(project, 60) == 60


@pytest.mark.parametrize("given", ["soon", "0", "-5", "1.5"])
def test_a_limit_in_the_variable_that_is_no_whole_number_of_seconds_is_refused(
    project: Path, monkeypatch, given: str
) -> None:
    from manuscript_guard.verify import TIMEOUT_VARIABLE

    monkeypatch.setenv(TIMEOUT_VARIABLE, given)
    with pytest.raises(VerifyError, match=TIMEOUT_VARIABLE):
        _limit(project)


@pytest.mark.parametrize("block", ["{timeout: 0}", "{timeout: soon}", "{limit: 60}"])
def test_paper_yaml_refuses_a_verify_setting_it_cannot_read(project: Path, block: str) -> None:
    _with_verify_setting(project, block)
    _loaded, report = load_project(project)
    assert not report.ok
    assert any("verify" in f.message for f in report.failures), report.render(project)


def test_a_script_past_the_limit_is_stopped_and_says_how_to_raise_it(
    project: Path, monkeypatch
) -> None:
    from manuscript_guard.verify import TIMEOUT_VARIABLE

    monkeypatch.delenv(TIMEOUT_VARIABLE, raising=False)
    (project / "analysis" / "01_disproportionality.py").write_text(
        "import time\ntime.sleep(60)\n", encoding="utf-8"
    )
    loaded, _ = load_project(project)
    result = verify(loaded, timeout=1)
    [comparison] = result.comparisons
    assert not comparison.ran
    assert "1 s" in comparison.error and "--timeout" in comparison.error
    assert TIMEOUT_VARIABLE in comparison.error and "paper.yaml" in comparison.error


def test_verify_says_which_interpreter_ran_each_script(project: Path) -> None:
    import platform
    import sys

    from manuscript_guard.verify import render

    result = run(project)
    [comparison] = result.comparisons
    assert comparison.interpreter == ("Python", platform.python_version(), sys.executable)
    assert f"with Python {platform.python_version()}" in render(result, project)


def test_results_written_with_another_interpreter_are_said_beside_the_comparison(
    project: Path,
) -> None:
    """The values agree, and the run is said to be another environment's, as a version of
    software found other is (`rerun-other-software`)."""
    path = fragment_of(project)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["provenance"]["session"]["version"] = "3.0.0"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)

    result = run(project)
    assert result.ok, to_report(result).render(project)
    [found] = [f for f in to_report(result).warnings if f.code == "rerun-other-interpreter"]
    assert "Python 3.0.0" in found.message


def _r_project(tmp_path: Path, rscript: str, renv_r: str | None = None) -> Path:
    import subprocess

    from test_r_emitter import EMIT_R

    root = tmp_path / "rpaper"
    for sub in ("analysis", "results", "manuscript"):
        (root / sub).mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "R"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    if renv_r is not None:
        (root / "renv.lock").write_text(
            json.dumps({"R": {"Version": renv_r, "Repositories": []}, "Packages": {}}),
            encoding="utf-8",
        )
    script = root / "analysis" / "01_r.R"
    script.write_text(
        'if (!requireNamespace("jsonlite", quietly = TRUE) || '
        '!requireNamespace("digest", quietly = TRUE)) {\n'
        '  cat("MISSING_DEPS\\n"); quit(status = 3)\n}\n'
        f'source("{EMIT_R.as_posix()}")\n'
        'em <- mg_emitter("analysis/01_r.R")\n'
        'em$value("cohort.n", 412L)\n'
        "em$write()\n",
        encoding="utf-8",
    )
    out = subprocess.run([rscript, "--vanilla", str(script)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=root)  # fmt: skip
    if out.returncode == 3:
        pytest.skip("R packages jsonlite and digest are not installed")
    assert out.returncode == 0, out.stderr
    return root


def test_verify_runs_r_with_the_rscript_named_and_says_which(tmp_path: Path) -> None:
    import re

    from test_r_emitter import RSCRIPT

    from manuscript_guard.verify import render

    if RSCRIPT is None:
        pytest.skip("R is not installed")
    root = _r_project(tmp_path, RSCRIPT)
    loaded, _ = load_project(root)
    result = verify(loaded, rscript=RSCRIPT)
    assert result.ok, to_report(result).render(root)
    [comparison] = result.comparisons
    language, version, path = comparison.interpreter
    assert (language, path) == ("R", RSCRIPT)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert f"with R {version} ({RSCRIPT})" in render(result, root)
    assert not to_report(result).warnings


def test_an_r_other_than_the_one_renv_lock_pins_is_warned_of(tmp_path: Path) -> None:
    from test_r_emitter import RSCRIPT

    if RSCRIPT is None:
        pytest.skip("R is not installed")
    root = _r_project(tmp_path, RSCRIPT, renv_r="3.1.0")
    loaded, _ = load_project(root)
    result = verify(loaded, rscript=RSCRIPT)
    [found] = [f for f in to_report(result).warnings if f.code == "rerun-r-not-locked"]
    assert "3.1" in found.message and "renv.lock" in found.message


def test_an_r_of_the_major_and_minor_renv_lock_pins_is_not_warned_of() -> None:
    from manuscript_guard.verify import Comparison, VerifyReport

    ran = Comparison("01_r.json", agreed=("cohort.n",), interpreter=("R", "4.6.1", "Rscript"))
    for pinned, warned in (("4.6.0", False), ("4.6.1", False), ("4.5.2", True)):
        report = VerifyReport(comparisons=[ran], r_pinned=pinned)
        codes = {f.code for f in to_report(report).warnings}
        assert ("rerun-r-not-locked" in codes) is warned, pinned


def test_the_command_refuses_a_limit_that_is_no_number_and_an_r_that_is_not_there(
    tmp_path: Path, capsys
) -> None:
    from manuscript_guard.cli import main

    project = _bare(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        main(["verify", str(project), "--timeout", "0"])
    assert stopped.value.code == 2
    assert main(["verify", str(project), "--rscript", str(tmp_path / "Rscript.exe")]) == 2
    assert "--rscript names" in capsys.readouterr().err
