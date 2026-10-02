"""Compare a built wheel's manuscript_guard files with the ones git tracks in the package.

Run by CI's wheel job: `python .github/scripts/check_wheel_files.py <wheel> [<checkout>]`.

Using the wheel notices some missing files and not others, because a fresh project reads only
part of the package's data. Ten of the 32 data files could be dropped from a wheel and the
job's `init`, `check` and `build --offline` still passed. The two file lists have to be equal,
so the check names every file that is tracked and not shipped, and every file that is shipped
and not tracked (a generated checklist profile is one, and carries text that may not be
redistributed).
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

IMPORT_NAME = "manuscript_guard/"
PACKAGE_DIR = "src/manuscript_guard"

# Tracked outside the package and taken into it when the wheel is built (pyproject.toml,
# force-include): where git has them, and where the wheel does.
FORCED = {"plugin/skills/": "manuscript_guard/skills/"}


def wheel_files(wheel: Path) -> set[str]:
    """The package's files in the wheel, as `manuscript_guard/...` (not the dist-info)."""
    with zipfile.ZipFile(wheel) as archive:
        return {
            name
            for name in archive.namelist()
            if name.startswith(IMPORT_NAME) and not name.endswith("/")
        }


def tracked_files(root: Path) -> set[str]:
    """What git tracks under the package, as `manuscript_guard/...` to match the wheel."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", PACKAGE_DIR, *(place.rstrip("/") for place in FORCED)],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return {in_the_wheel(name) for name in listed.split("\0") if name}


def in_the_wheel(name: str) -> str:
    """Where a tracked file is expected in the wheel."""
    for tracked, shipped in FORCED.items():
        if name.startswith(tracked):
            return shipped + name[len(tracked) :]
    return name[len("src/") :]


def compare(shipped: set[str], tracked: set[str]) -> tuple[list[str], list[str]]:
    """(tracked but not shipped, shipped but not tracked), each sorted."""
    return sorted(tracked - shipped), sorted(shipped - tracked)


def report(missing: list[str], unexpected: list[str]) -> int:
    for name in missing:
        print(f"missing from the wheel: {name}")
    for name in unexpected:
        print(f"in the wheel, not tracked by git: {name}")
    return 1 if missing or unexpected else 0


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    wheel = Path(argv[1])
    root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
    shipped, tracked = wheel_files(wheel), tracked_files(root)
    if not tracked:
        print(f"git tracks nothing under {PACKAGE_DIR} in {root}", file=sys.stderr)
        return 2
    status = report(*compare(shipped, tracked))
    if status == 0:
        print(f"the wheel holds all {len(tracked)} files git tracks in the package, and no others")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
