"""Shared fixtures: a working copy of the example project.

The example is built once per test session and then copied, rather than re-running the
analysis and a matplotlib render for every test. Tests mutate their copy freely, so the
copy has to be per test; only the expensive part is shared.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

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


@pytest.fixture(scope="session")
def built_example(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The example with its analysis run once. Never mutated; copied by `project`."""
    root = tmp_path_factory.mktemp("built") / "paper"
    shutil.copytree(EXAMPLE, root, ignore=IGNORE)
    for stale in (root / "results").glob("*"):
        stale.unlink()
    run_analysis(root)
    return root


@pytest.fixture
def project(built_example: Path, tmp_path: Path) -> Path:
    """A fresh, mutable copy of the built example."""
    root = tmp_path / "paper"
    shutil.copytree(built_example, root, ignore=IGNORE)
    return root
