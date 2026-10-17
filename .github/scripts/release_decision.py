"""Decide whether a push to main carries a version that has to go to PyPI.

Run by publish.yml, once CI has finished on the commit a push left main at:
`python .github/scripts/release_decision.py --pushed <sha> --ci <conclusion>`. It prints two
lines for the workflow to read, `publish=true` or `publish=false` and `version=<number>`,
and one sentence on stderr saying why.

Every version on main is released, and a release cannot be taken back: PyPI keeps a version
for good and refuses the same number twice. So a version is published exactly once, when a
push raises the number in pyproject.toml to one PyPI does not have, and only after CI has
passed on the commit that push left main at, which is the commit released. A push that
leaves the number alone releases nothing, however much else it changes: the code between a
merge and the bump that follows it carries the old number, and is not that release. Neither
does a push that lowers it, as a bump taken back does. Where the answer cannot be had,
because PyPI or GitHub did not reply, because the commit this push replaced cannot be read,
or because CI did not pass, nothing is published and the run fails.

The commit a push replaced is not in what GitHub tells a workflow that CI finished. It is
read from GitHub's record of the pushes to main (`--pushed`), or given (`--before`).
"""

from __future__ import annotations

import argparse
import json
import os
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
#: A commit as GitHub names it, and a repository as `owner/name`: both go into a URL.
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
#: GitHub's record of the pushes to main, newest first. A push is in it as the commit main
#: was at before it and the commit it left main at, forced or not. One page: CI finishes on a
#: push within hours, and main does not take a hundred pushes in that time.
PUSHES = "https://api.github.com/repos/{repository}/activity?ref=refs/heads/main&per_page=100"


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


def head_of(checkout: Path) -> str:
    shown = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True
    )
    return shown.stdout.strip()


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


def pushes_to_main(repository: str, token: str) -> list[dict]:
    """GitHub's record of the pushes to main. Any failure to read it is an error."""
    if not REPOSITORY.match(repository):
        raise SystemExit(f"{repository!r} is not a repository: nothing is published")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(PUSHES.format(repository=repository), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310 - fixed https
            pushes = json.load(reply)
    except (OSError, ValueError) as failed:
        raise SystemExit(
            f"GitHub's record of the pushes to main could not be read ({failed}): "
            "nothing is published"
        ) from failed
    if not isinstance(pushes, list) or not all(isinstance(push, dict) for push in pushes):
        raise SystemExit("GitHub's record of the pushes to main is not a list of pushes")
    return pushes


def replaced_by(pushed: str, pushes: list[dict]) -> str:
    """The commit main was at before the push that left it at `pushed`. Only one push may
    have done so: where none did, or two from different commits, which one CI tested is not
    known, and nothing says that it raised the number."""
    before = {push.get("before") for push in pushes if push.get("after") == pushed}
    if len(before) != 1:
        said = "no push" if not before else "pushes from more than one commit"
        raise SystemExit(
            f"GitHub's record of the pushes to main shows {said} leaving it at {pushed}: "
            "nothing is published"
        )
    found = before.pop()
    return found if isinstance(found, str) else ""


def numbers_of(version: str) -> tuple[int, ...]:
    """A version as numbers, so that 0.2.9 is below 0.2.10, with the zeros at its end left
    off, so that 0.2 and 0.2.0 are one version, as they are to PyPI."""
    numbers = [int(part) for part in version.split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def decide(
    now: str, before: str | None, published: Callable[[str], bool], *, ci: str
) -> tuple[bool, str]:
    """Whether to publish `now`, and why. `before` is the version of the commit this push
    replaced, or None where that commit cannot be read, as after a forced push. Nothing then
    says that this push is the one that raised the number, and PyPI's lacking it is no proof
    of that, so the run stops. `ci` is how CI concluded on the commit the push left main at.
    A release whose CI did not pass stops the run, where somebody sees it: when a re-run of
    CI's failed jobs passes, this is asked again, and the number is released then."""
    if before is None:
        raise SystemExit(
            "the commit this push replaced cannot be read, so whether this push raised the "
            f"version to {now} is not known: nothing is published. If it did, that number is "
            "passed over: to release what main holds, raise it again in a commit of its own."
        )
    if before == now:
        return False, f"this push left the version at {now}: nothing to release"
    if numbers_of(now) <= numbers_of(before):
        return False, f"the version went from {before} to {now}, not above it: nothing to release"
    if published(now):
        return False, f"{now} is already on PyPI: nothing to release"
    if ci != "success":
        raise SystemExit(
            f"the version went from {before} to {now}, and CI concluded {ci or 'nothing'} on "
            f"this commit: {now} is not released. Re-run CI's failed jobs; when they pass, "
            "this runs again and releases it."
        )
    return True, f"the version went from {before} to {now}, which PyPI does not have: releasing it"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    replaced = parser.add_mutually_exclusive_group(required=True)
    replaced.add_argument(
        "--pushed", help="the commit a push left main at, which is checked out here"
    )
    replaced.add_argument("--before", help="the commit this push replaced")
    parser.add_argument("--ci", required=True, help="how CI concluded on the commit released")
    parser.add_argument("--checkout", type=Path, default=Path.cwd())
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args(argv[1:])

    before = args.before
    if args.pushed is not None:
        if not COMMIT.match(args.pushed):
            raise SystemExit(f"{args.pushed!r} is not a commit: nothing is published")
        # The version is read from the checkout, so it has to be the commit CI tested.
        if head_of(args.checkout) != args.pushed:
            raise SystemExit(f"the checkout is not at {args.pushed}: nothing is published")
        token = os.environ.get("GH_TOKEN", "")
        before = replaced_by(args.pushed, pushes_to_main(args.repository, token))

    now = version_in((args.checkout / "pyproject.toml").read_text(encoding="utf-8"))
    publish, why = decide(now, version_at(before, args.checkout), on_pypi, ci=args.ci)
    print(why, file=sys.stderr)
    print(f"publish={'true' if publish else 'false'}")
    print(f"version={now}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
