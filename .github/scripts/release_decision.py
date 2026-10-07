"""Decide whether a push to main carries a version that has to go to PyPI.

Run by publish.yml: `python .github/scripts/release_decision.py --before <sha>`. It prints
two lines for the workflow to read, `publish=true` or `publish=false` and `version=<number>`,
and one sentence on stderr saying why.

Every version on main is released, and a release cannot be taken back: PyPI keeps a version
for good and refuses the same number twice. So a version is published exactly once, when a
push raises the number in pyproject.toml to one PyPI does not have. A push that leaves the
number alone releases nothing, however much else it changes: the code between a merge and
the bump that follows it carries the old number, and is not that release. Neither does a
push that lowers it, as a bump taken back does. Where the answer cannot be had, because
PyPI did not reply or because the commit this push replaced cannot be read, nothing is
published and the run fails.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

PROJECT = "manuscript-guard"
#: The line of pyproject.toml that gives the version. Read as text, not as TOML, so that the
#: script runs on every Python the package supports; tests/test_version.py holds the line.
#: Digits and dots only: the number goes into a tag's name and a line of the workflow's
#: output, and a release whose number is anything else is not one this project makes.
VERSION_LINE = re.compile(r'^version\s*=\s*"(\d+(?:\.\d+)+)"\s*$', re.MULTILINE)
#: What git gives as the commit before the first push of a branch: no commit at all.
NO_COMMIT = re.compile(r"^0*$")


def version_in(pyproject: str) -> str:
    found = VERSION_LINE.findall(pyproject)
    if len(found) != 1:
        raise SystemExit(f"pyproject.toml gives {len(found)} version lines; one is expected")
    return found[0]


def version_at(commit: str, checkout: Path) -> str | None:
    """The version pyproject.toml gave at a commit, or None where there is none to read."""
    if NO_COMMIT.match(commit):
        return None
    shown = subprocess.run(
        ["git", "show", f"{commit}:pyproject.toml"],
        cwd=checkout,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return version_in(shown.stdout) if shown.returncode == 0 else None


def status_of(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=30) as reply:  # noqa: S310 - a fixed https URL
            return reply.status
    except urllib.error.HTTPError as refused:
        return refused.code


def on_pypi(version: str, status: Callable[[str], int] = status_of) -> bool:
    """Whether PyPI already has this version. Anything but a plain yes or no is an error."""
    code = status(f"https://pypi.org/pypi/{PROJECT}/{version}/json")
    if code == 200:
        return True
    if code == 404:
        return False
    raise SystemExit(f"PyPI answered {code} for {PROJECT} {version}: nothing is published")


def numbers_of(version: str) -> tuple[int, ...]:
    """A version as numbers, so that 0.2.9 is below 0.2.10, with the zeros at its end left
    off, so that 0.2 and 0.2.0 are one version, as they are to PyPI."""
    numbers = [int(part) for part in version.split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def decide(now: str, before: str | None, published: Callable[[str], bool]) -> tuple[bool, str]:
    """Whether to publish `now`, and why. `before` is the version of the commit this push
    replaced, or None where that commit cannot be read, as after a forced push. Nothing then
    says that this push is the one that raised the number, and PyPI's lacking it is no proof
    of that, so the run stops."""
    if before is None:
        raise SystemExit(
            "the commit this push replaced cannot be read, so whether this push raised the "
            f"version is not known: nothing is published. If {now} is to be released, raise "
            "the number again in a commit of its own."
        )
    if before == now:
        return False, f"this push left the version at {now}: nothing to release"
    if numbers_of(now) <= numbers_of(before):
        return False, f"the version went from {before} to {now}, not above it: nothing to release"
    if published(now):
        return False, f"{now} is already on PyPI: nothing to release"
    return True, f"the version went from {before} to {now}, which PyPI does not have: releasing it"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", default="", help="the commit this push replaced")
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    args = parser.parse_args(argv[1:])

    now = version_in((args.checkout / "pyproject.toml").read_text(encoding="utf-8"))
    publish, why = decide(now, version_at(args.before, args.checkout), on_pypi)
    print(why, file=sys.stderr)
    print(f"publish={'true' if publish else 'false'}")
    print(f"version={now}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
