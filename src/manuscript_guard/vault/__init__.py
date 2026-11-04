"""The vault: the folder where the data are held, which the operating system keeps from the
agent.

The tool does not keep the data from the agent: the operating system does, through a second
account, a container, permissions or a volume that is not mounted. What the tool does is
register where the data are and which files they are (`register`), check from the agent's own
session whether they can be read (`probe`), keep the ordinary path away from them (the shell
guard in `hooks`, and the agent tool's own deny rules in `agent_rules`), run the analysis on
them in a copy of the project inside the folder (`run`), and hold what that run wrote to the
custodian's rules and a person's release (`release`).

This module and `probe` import nothing heavy: the hooks read them on every shell command.
"""

from __future__ import annotations

from pathlib import PurePosixPath

#: Where the files of the vault are registered, by digest, in the project. Committed.
REGISTRY = PurePosixPath("design/vault.yaml")
#: Where this machine keeps the vault's absolute path. Never committed.
LOCAL_FOLDER = PurePosixPath(".manuscript-guard")
LOCAL = LOCAL_FOLDER / "vault.local.yaml"
#: The schemas of the two files.
REGISTRY_SCHEMA = "manuscript-guard/vault/1"
LOCAL_SCHEMA = "manuscript-guard/vault-local/1"
#: The variable a run on the real data is given the folder in, by `vault run`.
VARIABLE = "MANUSCRIPT_GUARD_VAULT"
#: The variable `vault run` gives the run's id in, which a fragment records.
RUN_VARIABLE = "MANUSCRIPT_GUARD_VAULT_RUN"
#: The page that says what the vault is and is not.
DOC = "docs/vault.md"
#: Where the synthetic copies are, which `em.vault_input` reads outside a run.
SYNTHETIC = PurePosixPath("data/synthetic")
#: How an input read from the vault is recorded in a fragment: `vault:<label>`.
PREFIX = "vault:"
#: Where a person's release of a run is recorded, one file per run, and its schema.
RELEASES = PurePosixPath("approvals/vault-releases")
RELEASE_SCHEMA = "manuscript-guard/vault-release/1"
#: What a run tells the agent, in the project: the error summary, and its schema.
SUMMARY = LOCAL_FOLDER / "vault" / "last-run.json"
SUMMARY_SCHEMA = "manuscript-guard/vault-run/1"


def checked_label(label: object) -> str:
    """The label as given, where it names a file inside the vault's folder as `vault init`
    registers one (a path from the folder, with forward slashes, no `.` or `..`); refused
    otherwise, with a sentence that says why."""
    if not isinstance(label, str) or not label:
        raise ValueError("vault_input takes the file's label, its path inside the vault's "
                         "folder as design/vault.yaml registers it")  # fmt: skip
    parts = label.split("/")
    if ("\\" in label or label.startswith("/") or (len(label) > 1 and label[1] == ":")
            or any(part in ("", ".", "..") for part in parts)):  # fmt: skip
        raise ValueError(f"vault_input({label!r}): a label is the file's path inside the "
                         "vault's folder, with forward slashes, as design/vault.yaml registers "
                         "it: no folder above it, no drive and no backslash")  # fmt: skip
    return label


def in_vault(record: object) -> str | None:
    """The label of a fragment's input read from the vault, or None where it is no such
    input."""
    if not isinstance(record, dict):
        return None
    path = record.get("path")
    if isinstance(path, str) and path.startswith(PREFIX):
        return path[len(PREFIX):]
    return None
