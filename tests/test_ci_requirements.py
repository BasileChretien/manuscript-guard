"""A run that is meant to have pandoc must not pass by skipping everything that needs it.

Every test that needs pandoc skips without it. On a contributor's machine that is right; on
CI it hid the build, the import round trip and every check on what pandoc prints, because
no job installed pandoc and each one passed. CI now installs it and sets
`MANUSCRIPT_GUARD_REQUIRE_PANDOC` to the version, and `conftest.py` refuses to start a
session where that version is not the pandoc on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
REQUIRE = "MANUSCRIPT_GUARD_REQUIRE_PANDOC"
PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")


def collect(required: str | None, *, without_pandoc: bool = False) -> tuple[int, str]:
    """Start a session that only collects this file, and say how it ended."""
    env = {key: value for key, value in os.environ.items() if key != REQUIRE}
    # Only this repository's conftest is under test, and third-party plugins found on a
    # crowded machine took most of a start of 20 seconds.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if required is not None:
        env[REQUIRE] = required
    if without_pandoc:
        # Only Python's own directory: the session still starts, and pandoc is not on PATH.
        env["PATH"] = str(Path(sys.executable).parent)
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         str(Path(__file__).resolve())],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return finished.returncode, finished.stdout + finished.stderr


def installed_version() -> str:
    assert PANDOC is not None
    printed = subprocess.run([PANDOC, "--version"], capture_output=True, text=True).stdout
    return printed.split()[1]


def test_a_required_pandoc_that_is_missing_stops_the_run() -> None:
    code, output = collect("3.9.0.2", without_pandoc=True)
    assert code == pytest.ExitCode.USAGE_ERROR, output
    assert "pandoc is not on PATH" in output


@needs_pandoc
def test_a_required_pandoc_of_another_version_stops_the_run() -> None:
    """A pinned version is what the tests were written against: another may print the same
    document differently, and the difference would be read as a defect or hidden as none."""
    code, output = collect("0.0.0")
    assert code == pytest.ExitCode.USAGE_ERROR, output
    assert f"pandoc on PATH is {installed_version()}" in output


@needs_pandoc
def test_the_required_pandoc_lets_the_run_start() -> None:
    code, output = collect(installed_version())
    assert code == pytest.ExitCode.OK, output


def test_without_the_requirement_a_missing_pandoc_only_skips() -> None:
    """A contributor without pandoc still gets a run: the tests that need it skip."""
    code, output = collect(None, without_pandoc=True)
    assert code == pytest.ExitCode.OK, output
