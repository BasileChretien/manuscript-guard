"""One number for the command line tool and the plugin.

The plugin's skills call the command line tool, so a skill that names an option the installed
copy lacks fails at the user's keyboard. Two version numbers made that invisible: the plugin
moved with every change and the package sat at 0.1.0, so `pip install --upgrade` found
nothing newer and left an older copy in place, and `--version` could not say which release
anyone had. Now they are the same number, and each place that carries it is checked here.

What this cannot see is a change that left the number alone. The policy for that is that the
maintainer raises it on `main` after each merge that changes `src/` or `plugin/`, and that a
pull request does not touch it (CONTRIBUTING.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from manuscript_guard import __version__
from manuscript_guard.cli import main

REPO = Path(__file__).resolve().parent.parent


def declared_versions() -> dict[str, str]:
    """Every place a release number is written down, by where."""
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    written = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert written, "pyproject.toml declares no version"
    manifest = json.loads(
        (REPO / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    market = json.loads(
        (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    (entry,) = [p for p in market["plugins"] if p["name"] == manifest["name"]]
    return {
        "pyproject.toml": written.group(1),
        "manuscript_guard.__version__": __version__,
        "plugin/.claude-plugin/plugin.json": manifest["version"],
        ".claude-plugin/marketplace.json": entry["version"],
    }


def test_the_package_and_the_plugin_carry_one_version() -> None:
    versions = declared_versions()
    assert len(set(versions.values())) == 1, (
        f"these disagree, and every plugin bump bumps the package too: {versions}"
    )


def test_the_version_is_a_number_pip_can_order() -> None:
    """`pip install --upgrade` decides on the number, so it has to be plain dotted digits."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_the_command_prints_it(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == declared_versions()["pyproject.toml"]
