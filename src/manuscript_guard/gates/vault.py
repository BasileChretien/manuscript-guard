"""G1 of results from the data held in the vault: registered, unchanged, and released.

A fragment's input read from the vault (`em.vault_input`) is recorded as `vault:<label>`
with its digests, and is compared with the digest `design/vault.yaml` registers for that
label, never read: the file is outside the project and, where the separation holds, cannot be
read from here.

- A label `design/vault.yaml` does not register is `vault-input-unregistered`, a failure.
- A digest other than the registered one is `vault-input-changed`, a failure: the results
  are from data other than those registered, an extract before or after the one in the
  registry (`vault init --refresh` after a new extract makes every earlier result fail here,
  until it is run again).
- A fragment with such an input that no record under `approvals/vault-releases/` holds by
  its digest is `vault-result-unreleased`: a warning while the paper is written and a
  failure from internal review on, as a count below the custodian's minimum is. It catches a
  fragment copied in from the outbox by hand, one edited after its release, and a run made
  with MANUSCRIPT_GUARD_VAULT set by hand outside `vault run`.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.emit import sha256_of
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.vault import REGISTRY, in_vault

GATE = "G1"
_HINT = ("run the analysis on the vault with `manuscript-guard vault run`, and release "
         "what it wrote with `manuscript-guard vault release <run> --as <you>`, at a "
         "terminal")  # fmt: skip


def _inputs(project: Project, fragment, registry: dict[str, dict]) -> list[Finding]:
    found = []
    for record in fragment.inputs:
        label = in_vault(record)
        if label is None:
            continue
        entry = registry.get(label)
        if entry is None:
            found.append(Finding(
                gate=GATE, code="vault-input-unregistered", path=fragment.path,
                message=f"{fragment.path.name} read vault:{label}, which {REGISTRY} does not "
                "register",
                hint=f"register it with `manuscript-guard vault init`, or read a label "
                f"{REGISTRY} holds, and run it again"))  # fmt: skip
        elif entry.get("sha256") != record.get("sha256"):
            found.append(Finding(
                gate=GATE, code="vault-input-changed", path=fragment.path,
                message=f"{fragment.path.name} read vault:{label} with a digest other than "
                f"the one {REGISTRY} registers: these results are from other data than those "
                "registered",
                context=f"written {fragment.generated_at} by {fragment.generated_by}",
                hint=f"where the extract is new, `vault init --refresh`, then "
                f"{_HINT}"))  # fmt: skip
    return found


def _unreleased(project: Project, fragment, records: list[dict], due: bool) -> Finding | None:
    relative = fragment.path.relative_to(project.root).as_posix()
    digest = sha256_of(fragment.path)
    named = [record for record in records for one in record["files"]
             if one["path"] == relative and one["kind"] == "results"]  # fmt: skip
    if any(one["path"] == relative and one["sha256"] == digest
           for record in named for one in record["files"]):  # fmt: skip
        return None
    if named:
        last = named[-1]
        why = (f"it is not the file released on {str(last['released_at'])[:10]} "
               f"(run {last['run']}): changed since")
    elif isinstance(fragment.vault, dict) and fragment.vault.get("released") is True:
        why = "it says it was released, and no record of a release holds it"
    else:
        why = ("no person has released it: copied from the vault's outbox by hand, or "
               "written by a run outside `vault run`")
    return Finding(
        gate=GATE, code="vault-result-unreleased", severity=FAIL if due else WARN,
        path=fragment.path,
        message=f"{fragment.path.name} holds results from the data held in the vault, and "
        f"{why}",
        hint=_HINT)  # fmt: skip


def check_vault_results(project: Project, results: Results, stage: str) -> Report:
    """The findings of each fragment that read the vault; none where none did."""
    from manuscript_guard.policy import INTERNAL_REVIEW, stage_index
    from manuscript_guard.vault.probe import VaultFileError, registered
    from manuscript_guard.vault.records import read_releases

    vaulted = [fragment for fragment in results.fragments
               if any(in_vault(record) is not None for record in fragment.inputs)]  # fmt: skip
    if not vaulted:
        return Report()
    try:
        registry = {entry["label"]: entry for entry in registered(project.root)}
    except VaultFileError as exc:
        return Report((Finding(gate="G0", code="schema-violation", message=str(exc),
                               path=project.root / REGISTRY),))  # fmt: skip
    records, faults = read_releases(project.root)
    due = stage_index(stage) >= stage_index(INTERNAL_REVIEW)
    findings = list(faults)
    for fragment in vaulted:
        findings += _inputs(project, fragment, registry)
        unreleased = _unreleased(project, fragment, records, due)
        findings += [unreleased] if unreleased else []
    return Report(tuple(findings))


__all__ = ["check_vault_results"]
