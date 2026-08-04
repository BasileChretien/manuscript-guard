"""`check` has to survive a hostile or merely careless manuscript.

DESIGN says `check` is safe to run on a manuscript someone sent you, and that claim is why
`verify` is a separate command: `check` never executes project code. But "does not execute
code" is not the same as "cannot be made to hang or exhaust memory", and nothing tested the
second half.

A security review found three ways in, all reachable by accident rather than only by malice:

* a document with many fence-opener-shaped lines and no closer made the fence regex
  quadratic — 3,000 lines pushed `check` past a minute;
* a figure sibling of any size was read whole, and so was the build's source stamp;
* a FIFO in `figures/` blocks a read forever on Linux and macOS, which is where CI runs, and
  nothing in the gate runner bounds wall-clock time.

The budget here is deliberately loose. It is not a benchmark; it is a tripwire for a change
that turns a linear scan into a quadratic one, which has now happened twice in this file's
subject matter.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

BUDGET_SECONDS = 20.0


def timed_check(project: Path) -> float:
    from manuscript_guard.cli import _run_gates

    started = time.perf_counter()
    _run_gates(project, stage="drafting")
    return time.perf_counter() - started


# ---------------------------------------------------------------- pathological text


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("stray fence openers", "".join(f"```lang{i}\n" for i in range(3000))),
        ("stray tilde openers", "".join(f"~~~lang{i}\n" for i in range(3000))),
        ("mixed openers, no closers", "".join(f"{'`' * (3 + i % 4)}x\n" for i in range(3000))),
        ("many short lines", "".join(f"Value {i} was observed.\n" for i in range(5000))),
        ("one very long line", "The ratio was " + "1.0 " * 8000 + "overall.\n"),
        ("nested-looking brackets", "[" * 5000 + "9.99" + "]" * 5000 + "\n"),
        ("many citations", " ".join(f"[@key{i}]" for i in range(3000)) + "\n"),
        ("many headings", "".join(f"## Section {i}\n\nProse.\n\n" for i in range(1500))),
        ("setext underlines", "".join(f"Heading {i}\n---\n\nProse.\n\n" for i in range(1500))),
    ],
    # Explicit ids: pytest builds one from the parameters otherwise, and puts it in
    # PYTEST_CURRENT_TEST — which Windows refuses past 32767 characters, so a 60 KB body
    # turns every case in this table into a collection error rather than a test.
    ids=lambda value: value if isinstance(value, str) and len(value) < 60 else "",
)
def test_check_finishes_on_pathological_prose(project: Path, name: str, body: str) -> None:
    """The specific regression this catches: a linear scan quietly becoming quadratic."""
    (project / "manuscript" / "pathological.md").write_text(body, encoding="utf-8")
    elapsed = timed_check(project)
    assert elapsed < BUDGET_SECONDS, f"{name}: check took {elapsed:.1f}s"


def test_the_fence_scanner_is_linear() -> None:
    """Measured directly, because the gate budget is too coarse to see a slide.

    The regex this replaced took 0.24s at 1,000 opener-shaped lines and 6.09s at 4,000 —
    quadratic. The first attempt at handling unterminated fences reintroduced it at 55s for
    8,000. Doubling the input must not much more than double the time.
    """
    from manuscript_guard.text.fences import fenced_spans

    def measure(count: int) -> float:
        text = "".join(f"```lang{i}\n" for i in range(count))
        started = time.perf_counter()
        fenced_spans(text)
        return time.perf_counter() - started

    small = max(measure(4000), 1e-4)
    large = measure(16000)
    assert large / small < 12, f"4x the input took {large / small:.1f}x the time; not linear"


# ---------------------------------------------------------------- hostile files


def test_an_enormous_source_stamp_is_not_read_whole(project: Path) -> None:
    """`build/*.docx.source.sha256` is read by G1 and had no size cap.

    A digest line is 80 bytes. Anything larger is not a digest, and reading it whole is a
    free memory lever in a command that is supposed to be safe on someone else's project.
    """
    from manuscript_guard.build.document import SOURCE_STAMP

    build = project / "build"
    build.mkdir(exist_ok=True)
    (build / "manuscript.docx").write_bytes(b"PK\x03\x04not really a docx")
    (build / f"manuscript.docx{SOURCE_STAMP}").write_text("0" * (8 * 1024 * 1024), encoding="utf-8")

    elapsed = timed_check(project)
    assert elapsed < BUDGET_SECONDS


def test_a_figure_stem_with_glob_characters_still_finds_its_siblings(project: Path) -> None:
    """`content_digest` globbed on the stem, and a stem is a filename.

    `forest[1].svg` made `Path.glob` match nothing at all — not even the figure itself — so
    the raster sibling was silently dropped from the review digest. That is exactly the gap
    the multi-format digest was added to close, reopened for any figure whose name contains
    a bracket, which is an ordinary thing to write.
    """
    from manuscript_guard.gates.figures import content_digest

    figures = project / "figures"
    for suffix in (".svg", ".png"):
        (figures / f"panel[a]{suffix}").write_bytes((figures / f"forest{suffix}").read_bytes())

    before = content_digest(figures / "panel[a].svg")
    png = figures / "panel[a].png"
    png.write_bytes(png.read_bytes() + b"retouched")
    assert content_digest(figures / "panel[a].svg") != before, (
        "the raster sibling was not part of the digest, so replacing it changed nothing"
    )


@pytest.mark.skipif(os.name == "nt", reason="FIFOs do not exist on Windows")
def test_a_fifo_in_the_figures_directory_does_not_hang_check(project: Path) -> None:
    """Nothing bounds wall-clock time in the gate runner, so a blocking read is forever.

    CI runs Ubuntu and macOS, where an unprivileged `mkfifo` in `figures/` was enough.
    """
    os.mkfifo(project / "figures" / "trap.svg")
    elapsed = timed_check(project)
    assert elapsed < BUDGET_SECONDS


def test_an_enormous_figure_sibling_is_not_read_whole(project: Path) -> None:
    from manuscript_guard.gates.figures import content_digest

    figures = project / "figures"
    (figures / "forest.tif").write_bytes(b"\x00" * (16 * 1024 * 1024))
    started = time.perf_counter()
    content_digest(figures / "forest.svg")
    assert time.perf_counter() - started < BUDGET_SECONDS


# ------------------------------------------------------- running somebody else's analysis


def test_a_junction_is_not_followed_when_staging_a_copy(tmp_path: Path) -> None:
    """`symlinks=True` does not cover a Windows directory junction.

    `os.path.islink` is False for one, so `copytree` walked straight into it and re-copied
    the tree at every level until the OS gave up - reachable by any unprivileged
    `mklink /J`, while the comment in verify.py claimed it had been fixed.

    Written against `st_reparse_tag` rather than `os.path.isjunction`, which arrived in
    Python 3.12: this project supports 3.10, and the first version of the fix returned early
    there. CI caught it on windows-latest/3.10 - the guard was inert on a third of the
    supported matrix while DESIGN said junctions were skipped.
    """
    import subprocess

    from manuscript_guard.verify import _skip

    if sys.platform != "win32":
        pytest.skip("a junction is a Windows construct; copytree handles the symlink case")

    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(root / "loop"), str(root)],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction")

    assert "loop" in _skip(str(root), [entry.name for entry in root.iterdir()])
    assert "analysis" not in _skip(str(root), [entry.name for entry in root.iterdir()])


def test_the_build_and_git_trees_are_still_skipped(tmp_path: Path) -> None:
    from manuscript_guard.verify import _skip

    for name in ("build", ".git", "analysis", "results"):
        (tmp_path / name).mkdir()
    names = [entry.name for entry in tmp_path.iterdir()]
    assert _skip(str(tmp_path), names) == {"build", ".git"}


def test_something_that_cannot_be_stated_is_copied_rather_than_dropped(tmp_path: Path) -> None:
    """Silent omission is the failure this whole command exists to avoid.

    Treating an unreadable entry as a junction would drop a real directory out of the
    verified copy without saying so. `copytree` cannot walk it either, so it raises and the
    run reports that it could not stage a copy — which is the loud failure we want.
    """
    from manuscript_guard.verify import _skip

    assert _skip(str(tmp_path), ["does-not-exist"]) == set()


def test_a_verified_script_cannot_tell_it_is_being_verified(tmp_path: Path) -> None:
    """PYTHONDONTWRITEBYTECODE was set here for tidiness and was a backdoor in miniature.

    It is readable by the script being checked and is not set in an ordinary run, so two
    lines made an analysis honest under verification and dishonest everywhere else - the
    same reason MANUSCRIPT_GUARD_VERIFY was removed.
    """
    import inspect

    from manuscript_guard import verify as module

    source = inspect.getsource(module.verify)
    assert "PYTHONDONTWRITEBYTECODE" not in source.split("miniature")[-1].split("env =")[-1]
    assert "env = dict(os.environ)" in source


def test_a_script_that_never_exits_is_killed_with_its_children(tmp_path: Path) -> None:
    """`subprocess.run(timeout=)` kills the direct child only, and an analysis is usually a
    launcher. The grandchild kept the scratch directory alive and cleanup then failed."""
    import subprocess

    from manuscript_guard import verify as module

    script = tmp_path / "spin.py"
    script.write_text("import time\nwhile True:\n    time.sleep(0.1)\n", encoding="utf-8")
    original = module.TIMEOUT
    module.TIMEOUT = 2
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            module._run(script, tmp_path, dict(os.environ))
    finally:
        module.TIMEOUT = original


def test_output_from_a_verified_script_is_capped(tmp_path: Path) -> None:
    """A script printing steadily filled this process's memory, because the reader was here."""
    import os as _os

    from manuscript_guard.verify import OUTPUT_CAP, _run

    script = tmp_path / "loud.py"
    script.write_text(
        "import sys\nsys.stdout.write('x' * (4 << 20))\n", encoding="utf-8"
    )
    finished = _run(script, tmp_path, dict(_os.environ))
    assert finished.returncode == 0
    assert len(finished.stdout) <= OUTPUT_CAP


def test_an_interrupted_stamp_does_not_leave_an_empty_one(tmp_path: Path) -> None:
    """`write_text` truncates first, so a build interrupted mid-write left an empty stamp -
    which reads as a digest of nothing, so the next check calls a good document stale."""
    import inspect

    from manuscript_guard.build import document

    source = inspect.getsource(document._stamp_source)
    assert "os.replace(pending, stamp)" in source
