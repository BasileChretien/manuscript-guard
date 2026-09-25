"""Shared fixtures: a working copy of the example project, and a check that a scan is linear.

The example is built once per test session and then copied, rather than re-running the
analysis and a matplotlib render for every test. Tests mutate their copy freely, so the
copy has to be per test; only the expensive part is shared.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "example"

SCRIPTS = (
    "analysis/00_simulate.py",
    "analysis/01_disproportionality.py",
    "figures/forest.py",
)

IGNORE = shutil.ignore_patterns("build", "__pycache__", ".pytest_cache")


def run_analysis(root: Path) -> None:
    for script in SCRIPTS:
        out = subprocess.run(
            [sys.executable, str(root / script)], capture_output=True, text=True, cwd=root
        )
        assert out.returncode == 0, f"{script} failed:\n{out.stdout}\n{out.stderr}"


def restamp_figure_review(root: Path) -> None:
    """Re-stamp the figure review after the fixture re-renders the figure.

    The digest ignores render timestamps and generated element ids, but not the path data
    itself, and a different matplotlib or font stack draws the same figure differently. So a
    review committed against one machine's render reads as stale on another — correctly, in
    the sense that the bytes really did change, but uselessly here: this fixture re-renders
    the figure as part of building itself, which is exactly the moment a real author would
    re-stamp the review.

    Deliberately not a general escape hatch. The staleness tests edit the SVG directly and
    still fail as they should.
    """
    import yaml

    from manuscript_guard.gates import content_digest, review_path

    svg = root / "figures" / "forest.svg"
    path = review_path(svg)
    if not (svg.exists() and path.exists()):
        return
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["content_sha256"] = content_digest(svg)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


@pytest.fixture(scope="session")
def built_example(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The example with its analysis run once. Never mutated; copied by `project`."""
    root = tmp_path_factory.mktemp("built") / "paper"
    shutil.copytree(EXAMPLE, root, ignore=IGNORE)
    for stale in (root / "results").glob("*"):
        stale.unlink()
    run_analysis(root)
    restamp_figure_review(root)
    return root


@pytest.fixture
def project(built_example: Path, tmp_path: Path) -> Path:
    """A fresh, mutable copy of the built example."""
    root = tmp_path / "paper"
    shutil.copytree(built_example, root, ignore=IGNORE)
    return root


# ---------------------------------------------------------------------------- linear time

#: A linear scan takes 8 times as long on 8 times the input, and a quadratic one 64 times.
#: The bound is twice linear and a quarter of quadratic: a scan whose quadratic part is a
#: seventh of its time on the smaller input reads 8 + 56/7 = 16, and fails. It is a check
#: for scans, not for n log n, which comes close: sorting shuffled integers read 10.5 to 13.6.
LINEAR_FACTOR = 8
LINEAR_BOUND = 16.0
#: Below this, one preemption decides the ratio. The input is doubled until the smaller
#: case's best time reaches this, so a fast machine measures what a slow one does. The size
#: a test starts from is the smallest it times. Too large, and a quadratic that has come back
#: is timed at eight times a slow case, for minutes; too small, and a quadratic that runs at
#: C speed hides under the per-item work, so it goes no smaller than where one would show.
LINEAR_FLOOR_SECONDS = 0.02
#: Growth costs nothing unless a test never reaches the floor, so the cap only has to be far
#: past where the fastest runner gets there: CI's were up to about four times this machine.
LINEAR_MAX_GROWTH = 4096
#: Every time is a best of three: interference only ever adds time, so one slow sample says
#: nothing. A ratio between the bound and twice it is measured five times more before it
#: fails; a linear scan does not read twice the bound on its best runs.
LINEAR_REPEATS = 3
LINEAR_CONFIRM = 5

Clock = Callable[[], float]


def _seconds(work: Callable[[Any], object], given: Any, clock: Clock) -> float:
    """One timing, with the garbage collector off while it runs, as `timeit` does: a full
    collection falls on whichever sample happens to trigger it."""
    # Imported here, not at the top, to keep clear of the import block other branches edit.
    import gc

    collecting = gc.isenabled()
    gc.disable()
    try:
        started = clock()
        work(given)
        return clock() - started
    finally:
        if collecting:
            gc.enable()


def _best_ratio(
    work: Callable[[Any], object],
    small: Any,
    large: Any,
    times: tuple[list, list],
    repeats: int,
    clock: Clock,
) -> float:
    """Measure the two sizes in alternation, so a slow spell falls on both, and keep each
    size's best."""
    for _ in range(repeats):
        times[0].append(_seconds(work, small, clock))
        times[1].append(_seconds(work, large, clock))
    return min(times[1]) / min(times[0])


def check_linear(
    build: Callable[[int], Any],
    work: Callable[[Any], object],
    size: int,
    what: str,
    *,
    clock: Clock = time.perf_counter,
) -> None:
    """Fail unless `work(build(8 * n))` takes under 16 times as long as `work(build(n))`.

    Each of these tests once rested on a single timing per size (one on a best of three, one
    size after the other), or on a budget, and a busy runner decided the fence scanner's few
    milliseconds: at four times the input, a macOS job read 13.5 for a scan that is linear,
    against a bound of 12. So inputs are built off the clock; `n` starts at `size` and
    doubles until the smaller case's best of three takes 20 ms; the sizes are measured in
    alternation, and each keeps its best; and a ratio just over the bound is measured again
    before it fails. `clock` is for testing this function.
    """
    for growth in (2**step for step in range(LINEAR_MAX_GROWTH.bit_length())):
        count = size * growth
        small = build(count)
        work(small)  # imports, caches and compiled patterns, off the clock
        best = min(_seconds(work, small, clock) for _ in range(LINEAR_REPEATS))
        if best >= LINEAR_FLOOR_SECONDS:
            break
    else:
        raise ValueError(
            f"{what}: {count} items took under {LINEAR_FLOOR_SECONDS}s, too little to time;"
            " start from a larger size"
        )
    large = build(count * LINEAR_FACTOR)
    times: tuple[list, list] = ([], [])
    ratio = _best_ratio(work, small, large, times, LINEAR_REPEATS, clock)
    if LINEAR_BOUND <= ratio < 2 * LINEAR_BOUND:
        ratio = _best_ratio(work, small, large, times, LINEAR_CONFIRM, clock)
    assert ratio < LINEAR_BOUND, (
        f"{what}: {LINEAR_FACTOR}x the input ({count} to {count * LINEAR_FACTOR}) took"
        f" {ratio:.1f}x the time; linear is {LINEAR_FACTOR}, quadratic {LINEAR_FACTOR ** 2}"
    )


@pytest.fixture
def assert_linear() -> Callable[..., None]:
    """`check_linear`, for a test to call."""
    return check_linear
