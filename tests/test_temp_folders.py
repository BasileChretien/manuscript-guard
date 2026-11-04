"""A run of the suite leaves behind only the folders of the tests that failed.

Every test that copies the example into `tmp_path` writes a few dozen files, and a full run
writes some three hundred thousand. pytest removes old runs from its own folder, keeping the
newest three, but a folder named with `--basetemp` is never removed: parallel runs need one
each, and two weeks of them left about 120 GB behind on the author's machine. With
`tmp_path_retention_policy = "failed"` in `pyproject.toml`, pytest removes a test's folder as
soon as the test passes, under `--basetemp` as well, and keeps a failed test's folder for
whoever has to look at it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

INNER = """
def test_passes(tmp_path):
    (tmp_path / "written").write_text("a passing test wrote this", encoding="utf-8")


def test_fails(tmp_path):
    (tmp_path / "written").write_text("a failing test wrote this", encoding="utf-8")
    assert False
"""


def test_only_a_failed_tests_folder_is_left_under_basetemp(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "test_inner.py").write_text(INNER, encoding="utf-8")
    base = tmp_path / "base"
    # The run reads this repository's settings and none of its conftest, and no plugin found
    # on the machine, nor the options of the run this test is part of.
    env = {key: value for key, value in os.environ.items()
           if key != "PYTEST_ADDOPTS" and not key.startswith("PYTEST_XDIST")}  # fmt: skip
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Without `--confcutdir`, a run whose settings file is outside its folder collected every
    # folder above the test file. Under the system's temporary folder that read thousands of
    # entries, and failed on one that another program removed meanwhile.
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-c", str(REPO / "pyproject.toml"), "--rootdir", str(inner),
         "--confcutdir", str(inner), "--basetemp", str(base), str(inner / "test_inner.py")],
        cwd=inner,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    printed = finished.stdout + finished.stderr
    assert finished.returncode == 1, printed
    # On POSIX pytest also links `test_failscurrent` to the newest folder of that name. A link
    # holds no files, and the one to the passing test's folder goes with the folder.
    folders = sorted(path.name for path in base.iterdir() if not path.is_symlink())
    assert folders == ["test_fails0"], printed
    written = base / "test_fails0" / "written"
    assert written.read_text(encoding="utf-8") == "a failing test wrote this"
