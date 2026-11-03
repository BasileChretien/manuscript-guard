"""The vault: the folder where the data are held, which the operating system keeps from the
agent.

The tool does not keep the data from the agent: the operating system does, through a second
account, a container, permissions or a volume that is not mounted. What the tool does is
register where the data are and which files they are (`register`), check from the agent's own
session whether they can be read (`probe`), keep the ordinary path away from them (the shell
guard in `hooks`, and the agent tool's own deny rules in `agent_rules`), and, in later steps,
hold what comes out of a run on them to the custodian's rules and a person's release.

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
#: The variable a run on the real data is given the folder in (`vault run`, a later step).
VARIABLE = "MANUSCRIPT_GUARD_VAULT"
#: The page that says what the vault is and is not.
DOC = "docs/vault.md"
