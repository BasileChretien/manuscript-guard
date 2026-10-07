"""Shared fixtures: a working copy of the example project, and a check that a scan is linear.

The example is built once per test session and then copied, rather than re-running the
analysis and a matplotlib render for every test. Tests mutate their copy freely, so the
copy has to be per test; only the expensive part is shared.
"""

from __future__ import annotations

import atexit
import faulthandler
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
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

#: Set by CI to the pandoc version it installs. Every test that needs pandoc skips without
#: it, which is right on a contributor's machine and was wrong on CI: no test job had
#: pandoc, and none failed for want of it.
REQUIRE_PANDOC = "MANUSCRIPT_GUARD_REQUIRE_PANDOC"

#: The version on the line that names the program, wherever that line falls in the output.
#: pandoc 3.8 and later print "pandoc"; earlier releases print the name they were started
#: by, which on Windows ends in ".exe", in whatever case `shutil.which` gave the path.
PANDOC_VERSION_LINE = re.compile(r"^pandoc(?i:\.exe)?\s+(\S+)", re.MULTILINE)


#: `check` and `build` say when a copy of the skills in the user's home is from another
#: release. Whoever runs the suite may have such a copy, and the tests that read stderr must
#: not depend on it, in this process or in one they start. So the suite looks in a folder
#: that is not there: one under a directory made for this run and removed after it, so that
#: a test that wrote there by mistake leaves nothing for the next run to read.
_FOR_THIS_RUN = Path(tempfile.mkdtemp(prefix="manuscript-guard-tests-"))
atexit.register(shutil.rmtree, _FOR_THIS_RUN, ignore_errors=True)
os.environ["MANUSCRIPT_GUARD_USER_SKILLS"] = str(_FOR_THIS_RUN / "no-user-skills")


#: How long one generated test may take before the run is stopped, in seconds. Such a test
#: takes seconds, and half a minute on a machine busy with other suites. See
#: `stopped_if_stuck`.
STUCK_AFTER = 900

#: The terminal's own standard error, kept from the one moment pytest is not capturing it.
_TERMINAL: int | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Where pandoc is required, refuse to start without it rather than skip every test that
    needs it. Unset, a missing pandoc still skips them."""
    global _TERMINAL
    try:
        _TERMINAL = os.dup(sys.stderr.fileno())
    except (AttributeError, OSError, ValueError):
        _TERMINAL = None
    wanted = os.environ.get(REQUIRE_PANDOC, "").strip()
    if not wanted:
        return
    found = shutil.which("pandoc")
    if found is None:
        raise pytest.UsageError(f"{REQUIRE_PANDOC}={wanted}, but pandoc is not on PATH")
    try:
        printed = subprocess.run(
            [found, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except OSError as exc:
        raise pytest.UsageError(
            f"{REQUIRE_PANDOC}={wanted}, but {found} did not run: {exc}"
        ) from exc
    line = PANDOC_VERSION_LINE.search(printed)
    version = line.group(1) if line else "unreadable"
    if version != wanted:
        raise pytest.UsageError(f"{REQUIRE_PANDOC}={wanted}, but pandoc on PATH is {version}")


def pytest_unconfigure(config: pytest.Config) -> None:
    global _TERMINAL
    if _TERMINAL is not None:
        os.close(_TERMINAL)
        _TERMINAL = None


@pytest.fixture
def stopped_if_stuck() -> Iterator[None]:
    """Stop the whole run if this test is still going after `STUCK_AFTER` seconds, and say
    where it was.

    A generated input is one nobody chose, and now and then it is the one a pattern
    backtracks on for ever. A test stuck there holds its runner until the job's own limit,
    an hour and a half, and says nothing about which input it was. Nothing in Python can
    interrupt it: the matching is done in C with the interpreter held, so a timer thread
    never gets to run. `faulthandler` watches from a thread of its own, prints where every
    thread stands and ends the process. It prints to the terminal's standard error as it was
    before pytest began capturing: to the captured one, the report would go with the process.

    The limit is no measure of anything, which is why it is long: it is for a hang, and
    `check_linear` below is for a scan that has slowed.
    """
    from generated import times

    faulthandler.dump_traceback_later(
        STUCK_AFTER * times(), exit=True, file=sys.__stderr__ if _TERMINAL is None else _TERMINAL
    )
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


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
#: C speed can hide under the per-item work. Where no one start sees both, a scan is checked
#: from two, as paragraph tagging is: small first, where one in Python fails in seconds, then
#: from where one at C speed shows.
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
