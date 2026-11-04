"""The records of a person's release of a run on the data held in the vault.

`vault release` writes one per run, at `approvals/vault-releases/<run>.json`
(`manuscript-guard/vault-release/1`). G1 holds a fragment that read the vault to the digest a
record gives it, and `vault run` lists the scripts changed since the run released last. A
record is a person's statement, unsigned, as an approval is: the hooks put to the person an
agent's write or edit of a file under `approvals/vault-releases/`, and a shell command that
names the folder (round 1 of #490).
"""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard.findings import Finding
from manuscript_guard.vault import RELEASES


def release_file(root: Path, run: str) -> Path:
    return root.joinpath(*RELEASES.parts, f"{run}.json")


def read_releases(root: Path) -> tuple[list[dict], list[Finding]]:
    """Every record of a release, in the order the runs were made, and a finding for each
    file there that is not one."""
    from manuscript_guard.contracts._schema import validate

    folder = root.joinpath(*RELEASES.parts)
    records, faults = [], []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else ():
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            faults.append(Finding(gate="G0", code="schema-violation", path=path,
                                  message=f"{path.name}: not a record of a release it can "
                                  f"read ({exc})"))  # fmt: skip
            continue
        checked = validate(document, "vault-release", path)
        if not checked.ok:
            faults += list(checked.findings)
            continue
        if path.stem != document["run"]:
            faults.append(Finding(gate="G0", code="schema-violation", path=path,
                                  message=f"{path.name} records the release of run "
                                  f"{document['run']}, whose record is {document['run']}.json"))
            continue
        records.append(document)
    from manuscript_guard.vault.run import run_key

    return sorted(records, key=lambda record: run_key(record["run"])), faults


def last_release(root: Path) -> dict | None:
    """The record of the run released last, by the run's id, which is its time and then its
    number; None where none has been."""
    records, _faults = read_releases(root)
    return records[-1] if records else None


__all__ = ["last_release", "read_releases", "release_file"]
