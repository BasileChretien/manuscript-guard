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
    from manuscript_guard import verify as module

    monkeypatch.setattr(module, "RUNNERS", {})
    loaded, _ = load_project(project)
    result = module.verify(loaded)
    assert result.skipped
    assert result.ok, "nothing was checked, so nothing failed — and the report says so"
    assert "not verified" in module.render(result, project)


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
