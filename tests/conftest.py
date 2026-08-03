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
