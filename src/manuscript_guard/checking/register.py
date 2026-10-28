"""The register of the pages a project has built, and what an answers file is held to.

`checks/bundles.csv` gets one row for every page `checker build` writes: when, for whom (the
name and the ORCID iD the page carries), the page's identifier, the SHA-256 of the random
token written into it, the digest of the items it carries, how many, and the file. The token
itself is not kept: the page holds it, and so does the answers file the page writes.

So an answers file that names a page in the register is held to it. Its token must hash to the
one recorded, and the name and ORCID iD in it must be the ones the page was built for, or
`checker import` refuses the file. That stops an answers file being edited to read as another
co-author's, and one page's answers being passed off as another page's. It does **not** say who
answered: whoever holds the page holds the token, the corresponding author who sent it among
them. The name on an answer is a claim; the token says which page it came from.

An answers file that names no page in the register, one written by a page built before the
register existed (`checking-answers/1`) or on another clone, is recorded, and its decisions
read as **claimed**: the name is the file's word and nothing more. A `/1` file that names a
registered page is refused, because no registered page writes one.

Append-only, like `checks/decisions.csv`, and for the same reason; the hooks keep an agent's
editor out of it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

REGISTER = "checks/bundles.csv"
FIELDS = ["built_on", "person", "orcid", "bundle", "token_sha256", "state", "items", "file"]
#: 128 bits: more than anyone will guess, short enough to read in a JSON file.
TOKEN_BYTES = 16


def new_token() -> str:
    """A fresh token for one page. Module-level, so that a test can put its own in."""
    return secrets.token_hex(TOKEN_BYTES)


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def state_of(digests: list[str]) -> str:
    """The digest of what a page asked: its items' own digests, in the page's order."""
    return hashlib.sha256(json.dumps(list(digests)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Row:
    built_on: str
    person: str
    orcid: str
    bundle: str
    token_sha256: str
    state: str
    items: str
    file: str


def register_path(project_root: Path) -> Path:
    return project_root / REGISTER


def read_register(project_root: Path) -> dict[str, Row]:
    """Every page built, by its identifier. A page's identifier digests its token, so two
    builds never share one."""
    path = register_path(project_root)
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            Row(**{field: str(row.get(field) or "") for field in FIELDS})
            for row in csv.DictReader(handle)
            if row.get("bundle")
        ]
    return {row.bundle: row for row in rows}


def append_row(project_root: Path, row: Row) -> None:
    path = register_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerow(row.__dict__)
