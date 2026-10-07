"""Refuse to publish a release whose tag does not name the version the package carries.

Run by publish.yml before anything is built:
`python .github/scripts/check_release_tag.py <tag> [<checkout>]`.

The tag is what a reader of PyPI follows back to the source, and the description PyPI shows
links to files at `v<version>`. A release tagged with another number, or with the number
alone, would publish a version nobody can trace and a page of dead links. PyPI keeps a
version for good, so this is checked before the upload and not found after it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: The line of pyproject.toml that gives the version. Read as text, not as TOML, so that the
#: script runs on every Python the package supports; tests/test_version.py holds the line.
VERSION_LINE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


def package_version(checkout: Path) -> str:
    found = VERSION_LINE.findall((checkout / "pyproject.toml").read_text(encoding="utf-8"))
    if len(found) != 1:
        raise SystemExit(f"pyproject.toml gives {len(found)} version lines; one is expected")
    return found[0]


def problem(tag: str, version: str) -> str | None:
    """What is wrong with the tag, in a sentence, or None where it names the version."""
    wanted = f"v{version}"
    if tag == wanted:
        return None
    return f"the release is tagged {tag!r} and pyproject.toml says {version}: tag it {wanted}"


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: check_release_tag.py <tag> [<checkout>]", file=sys.stderr)
        return 2
    checkout = Path(argv[2]) if len(argv) == 3 else Path.cwd()
    wrong = problem(argv[1], package_version(checkout))
    if wrong:
        print(f"::error::{wrong}")
        return 1
    print(f"the tag {argv[1]} names the version in pyproject.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
