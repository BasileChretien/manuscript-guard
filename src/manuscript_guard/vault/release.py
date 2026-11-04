"""`vault release <run> --as <person>`: what a run on the data held in the vault wrote,
read to the custodian's rules, and put into the project on a person's word.

The person runs it at a terminal; the plugin's hook refuses it to an agent. Who releases is
the data custodian where `authors.yaml` names one, and any author otherwise (Basile's
decision 10a). The outbox is read before anything is asked:

- every results file whole, each value, each table cell and the model and variable cards,
  through `deposit.counts.small_in`: a count below the minimum refuses the release unless the
  data custodian has signed off that exact list (`VAULT/custodian/small-counts/<run>`, the
  deposit's pattern), and a count held back that a total gives away (`recoverable`) is a
  warning;
- each harvested output, through `harvest.receipt._counts_held`, as a site's receipt reads it;
- a table column whose values are all different, over at least the minimum of rows, is a
  warning: an identifier, or a value per person;
- the plan the run's first results froze, where it holds the project's plan and nothing
  else, as the results are;
- each other file, which no check reads (a figure, a profile, a CSV no entry harvests), is
  listed, and released only where the person types its path at the terminal (decision 12a).

Where `paper.yaml` says the custodian restricts sending, the release is refused until the data
custodian has signed off that the coding agent's provider may read what is released
(`VAULT/custodian/agent-reads-releases`, decision 11a): a released file is read by the agent,
and through it by its provider, and every release says so.

The files go into the project at their paths, each results file with `provenance.vault`
saying it is released and its digest written again, and the release is recorded in
`approvals/vault-releases/<run>.json`, a person's statement, unsigned.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from manuscript_guard.emit import FROZEN_PLAN
from manuscript_guard.findings import FAIL, INFO, Finding
from manuscript_guard.vault import RELEASE_SCHEMA
from manuscript_guard.vault.run import OUTBOX, RunRefused, read_manifest

GATE = "VAULT"
ROLE = "data_custodian"
AGENT_READS = f"{GATE}/custodian/agent-reads-releases"
SMALL_COUNTS = f"{GATE}/custodian/small-counts"
#: Said at every release, and in the docs.
SENT = ("A file released is read by the coding agent, and through it by its provider: the "
        "agent tool sends what the agent reads to the model that runs it.")  # fmt: skip
#: Where the runs' results files are, from the project's root.
RESULTS = "results"


class Refused(Exception):
    """Why nothing was released, in a sentence for the person at the terminal."""


@dataclass
class Outbox:
    """What a run wrote, as it waits in the vault: its results files, its harvested outputs
    with their entries, and every other file, by path."""

    run: str
    folder: Path
    manifest: dict
    fragments: list[str] = field(default_factory=list)
    harvested: list[tuple[str, object]] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    #: The plan as the run's first results froze it, where it holds the project's plan and
    #: nothing else (`_plan_only`).
    plan: list[str] = field(default_factory=list)


@dataclass
class Reading:
    """What the checks of an outbox found: what refuses it, the small counts, which the
    custodian may sign off, and the warnings shown."""

    refused: list[str] = field(default_factory=list)
    small: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- the outbox


def open_outbox(project, folder: Path, run: str) -> Outbox:
    """The outbox of `run`, its files sorted by kind; refused where the run is not there,
    did not finish, or wrote a link."""
    from manuscript_guard.harvest.config import HarvestError, load_entries

    try:
        manifest = read_manifest(folder, run)
    except RunRefused as exc:
        raise Refused(str(exc)) from exc
    if not manifest.get("finished"):
        raise Refused(f"run {run} did not finish, and nothing it wrote waits in the outbox: "
                      "run `vault run` again")  # fmt: skip
    where = folder / OUTBOX / run
    if not where.is_dir():
        raise Refused(f"run {run} wrote nothing that waits in the outbox ({where})")
    try:
        entries = {entry.output: entry for entry in load_entries(Path(project.root))}
    except HarvestError as exc:
        raise Refused(f"harvest.yaml cannot be read, to know which outputs it harvests: {exc}"
                      ) from exc  # fmt: skip
    box = Outbox(run, where, manifest)
    paths = sorted(path for path in where.rglob("*") if not path.is_dir())
    named = {path.relative_to(where).as_posix() for path in paths}
    for path in paths:
        relative = path.relative_to(where).as_posix()
        if path.is_symlink():
            raise Refused(f"{relative} in the outbox is a link: a release copies files, and "
                          "a link's target is no output of the run")  # fmt: skip
        pure = PurePosixPath(relative)
        if relative.endswith(".sha256") and relative[: -len(".sha256")] in named and \
                str(pure.parent) == RESULTS:  # fmt: skip
            continue  # written again beside its fragment at the release
        if str(pure.parent) == RESULTS and pure.suffix == ".json":
            box.fragments.append(relative)
        elif relative in entries:
            box.harvested.append((relative, entries[relative]))
        elif relative == FROZEN_PLAN.as_posix() and _plan_only(project, path, manifest):
            box.plan.append(relative)
        else:
            box.unread.append(relative)
    return box


#: When a plan was frozen, as `emit.freeze_plan` writes it.
_FROZEN_AT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:[+-]\d\d:\d\d|Z)")


def _plan_only(project, path: Path, manifest: dict) -> bool:
    """Whether the plan the run's first results froze holds the project's plan, its digest,
    a time, a script the run ran and nothing else, and the project has no frozen plan yet:
    then it is released as the results are. Anything else is a file no check reads."""
    from manuscript_guard.emit import PLAN, source_digest

    root = Path(project.root)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        plan = (root / PLAN).read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return (isinstance(record, dict) and not (root / FROZEN_PLAN).exists()
            and set(record) <= {"schema", "frozen_at", "by", "sha256", "plan", "synthetic"}
            and record.get("schema") == "manuscript-guard/plan-frozen/1"
            and record.get("plan") == plan and record.get("sha256") == source_digest(root / PLAN)
            and isinstance(record.get("frozen_at"), str)
            and _FROZEN_AT.fullmatch(record["frozen_at"]) is not None
            and record.get("by") in (manifest.get("ran") or ())
            and record.get("synthetic", False) is False)  # fmt: skip


def _distinct(name: str, values: list[str], minimum: int, where: str) -> str | None:
    if len(values) >= max(minimum, 2) and len(set(values)) == len(values):
        return (f"{where}, column {name!r}: one value per row, over {len(values)} rows: an "
                "identifier, or a value per person?")  # fmt: skip
    return None


def _read_fragments(box: Outbox, minimum: int, found: Reading) -> list[tuple[str, str]]:
    """The checks of the results files; the vault's labels and digests they read."""
    from manuscript_guard.contracts._schema import validate
    from manuscript_guard.contracts.results import load_results
    from manuscript_guard.deposit.counts import small_in
    from manuscript_guard.gates.custodian import _recovered, as_cells, recoverable
    from manuscript_guard.vault import in_vault

    inputs: dict[str, str] = {}
    for relative in box.fragments:
        path = box.folder / relative
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            found.refused.append(f"{relative} is not a results file it can read ({exc})")
            continue
        checked = validate(document, "results", path)
        if not checked.ok:
            found.refused += [f"{relative}: {f.message}" for f in checked.findings]
            continue
        found.small += small_in(document, relative, minimum)
        for record in document["provenance"].get("inputs") or ():
            label = in_vault(record)
            if label is not None:
                inputs[label] = record["sha256"]
    if box.fragments and not found.refused:
        results, _report = load_results(box.folder / RESULTS)
        for key, table in sorted(results.tables.items()):
            if table.generated:
                continue
            relative = table.source.relative_to(box.folder).as_posix()
            found.warnings += [_recovered(f"table.{key} in {relative}: ", one, table.source,
                                          None, declared=False).message
                               for one in recoverable(as_cells(table), minimum)]  # fmt: skip
            for at, name in enumerate(table.columns[1:], 1):
                said = _distinct(name, [str(row[at]) if at < len(row) else ""
                                        for row in table.rows], minimum,
                                 f"{relative}, table.{key}")  # fmt: skip
                found.warnings += [said] if said else []
    return sorted(inputs.items())


def _read_harvested(project, box: Outbox, minimum: int, found: Reading) -> None:
    from manuscript_guard.harvest.config import HarvestError
    from manuscript_guard.harvest.read import read_output
    from manuscript_guard.harvest.receipt import _counts_held

    for relative, entry in box.harvested:
        path = box.folder / relative
        try:
            refused, warned = _counts_held(project, entry, path)
            table = read_output(path.read_bytes(), path.suffix.lower(),
                                replace(entry, columns=None, digits=None))  # fmt: skip
        except (HarvestError, OSError, ValueError) as exc:
            found.refused.append(f"{relative} cannot be read as entry {entry.key} reads it "
                                 f"({exc})")  # fmt: skip
            continue
        found.refused += [f"{relative}: {said}" for said in refused]
        found.warnings += [f"{relative}: {said}" for said in warned]
        for at, name in enumerate(table.columns):
            values = [cells[at].display if cells[at] is not None else ""
                      for _row, cells in table.rows]  # fmt: skip
            said = _distinct(name, values, minimum, relative)
            found.warnings += [said] if said else []


def read_outbox(project, box: Outbox) -> tuple[Reading, list[tuple[str, str]]]:
    """What the checks of the outbox found, and the vault's labels with the digests its
    results read."""
    from manuscript_guard.gates.custodian import minimum_cell_count

    minimum = minimum_cell_count(project)
    found = Reading()
    if minimum is None:
        found.refused.append("paper.yaml declares no custodian.minimum_cell_count, which every "
                             "check of what leaves the vault holds counts to")  # fmt: skip
        return found, []
    inputs = _read_fragments(box, minimum, found)
    _read_harvested(project, box, minimum, found)
    return found, inputs


# ---------------------------------------------------------------------------- sign-offs


def small_signable(project, run: str, small: list):
    """The small counts of a run's results as one statement the data custodian may sign off,
    or None where they hold none. What is said names where each count is and not the count,
    since a sign-off is kept in the project."""
    from manuscript_guard.gates.custodian import minimum_cell_count
    from manuscript_guard.sign_offs import Signable, digest_of

    if not small:
        return None
    minimum = minimum_cell_count(project)
    findings = tuple(
        Finding(gate=GATE, code="vault-small-count", severity=FAIL,
                message=f"{one.fragment}: {one.where} is below the data custodian's minimum "
                f"of {minimum}, and the release puts the file in the project whole",
                path=Path(project.root) / "paper.yaml",
                hint="hold it back in the analysis, as fewer than the minimum or merged with "
                "another category, and run it again")  # fmt: skip
        for one in small
    )
    digest = digest_of("vault-small-counts", run, minimum,
                       [(one.fragment, one.where, one.count) for one in small])  # fmt: skip
    return Signable(ROLE, f"{SMALL_COUNTS}/{run}", digest, findings)


def agent_signable(project):
    """Where the custodian restricts sending, the statement that the coding agent's provider
    may read what is released; None otherwise."""
    from manuscript_guard.panel.custodian import restricts_sending
    from manuscript_guard.sign_offs import Signable, digest_of

    if not restricts_sending(project):
        return None
    finding = Finding(gate=GATE, code="vault-release-sends", severity=FAIL,
                      message="the data custodian restricts where the data, and what is "
                      "computed from them, may be sent, and a file released from the vault is "
                      "read by the coding agent, and through it by its provider",
                      path=Path(project.root) / "paper.yaml")  # fmt: skip
    return Signable(ROLE, AGENT_READS, digest_of("agent-reads-releases"), (finding,))


def vault_signables(project, finding: str) -> tuple[list, list[str]]:
    """The vault's signables `sign --finding` may be asked for, and what stops one being
    worked out."""
    from manuscript_guard.vault.probe import VaultFileError, local_folder

    if finding == AGENT_READS:
        signable = agent_signable(project)
        return ([signable] if signable else []), []
    if not finding.startswith(f"{SMALL_COUNTS}/"):
        return [], []
    run = finding[len(SMALL_COUNTS) + 1:]
    try:
        folder = local_folder(Path(project.root))
        if folder is None:
            return [], ["no vault is registered on this machine"]
        found, _inputs = read_outbox(project, open_outbox(project, folder, run))
    except (Refused, VaultFileError) as exc:
        return [], [str(exc)]
    signable = small_signable(project, run, found.small)
    return ([signable] if signable else []), []


def _standing(project, signable) -> tuple[bool, list[Finding]]:
    """Whether the signable stands signed off, and its findings as they stand."""
    from manuscript_guard.sign_offs import settle

    settled = list(settle(project, signable))
    return all(one.severity == INFO for one in settled), settled


# ---------------------------------------------------------------------------- who and what


def releaser(project, said: str) -> tuple[str, str | None, str]:
    """Who releases: the data custodian where authors.yaml names one, else any author. Their
    name, ORCID iD and the role they release in; refused where `said` is neither."""
    from manuscript_guard.approvals import NoSuchAuthor, find_author, name_of
    from manuscript_guard.sign_offs import holder, is_holder

    if not said.strip():
        raise Refused("--as names who releases")
    try:
        custodian = holder(project, ROLE)
    except NoSuchAuthor as exc:
        raise Refused(f"roles: data_custodian in authors.yaml: {exc}") from exc
    if custodian is not None:
        if not is_holder(project, custodian, said):
            raise Refused(f"{said!r} is not the data custodian: authors.yaml names "
                          f"{custodian.name}, who releases what leaves the vault")  # fmt: skip
        return custodian.name, custodian.orcid, ROLE
    try:
        author = find_author(project, said)
    except NoSuchAuthor as exc:
        raise Refused(f"{exc}; where authors.yaml names no data custodian, an author "
                      "releases") from exc  # fmt: skip
    return name_of(author), author.get("orcid"), "author"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _released_bytes(path: Path) -> bytes:
    """A results file as it goes into the project: `provenance.vault` saying it is released."""
    data = path.read_bytes()
    document = json.loads(data.decode("utf-8"))
    vault = document.get("provenance", {}).get("vault")
    if not isinstance(vault, dict):
        return data
    document["provenance"]["vault"] = {**vault, "released": True}
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_release(project, box: Outbox, named: list[str], who: tuple[str, str | None, str],
                  inputs: list[tuple[str, str]], warnings: list[str],
                  signed: list[str]) -> Path:  # fmt: skip
    """Put the results, the harvested outputs and the files named into the project, and
    record the release. Returns the record's path."""
    from manuscript_guard.emit import sha256_of, write_digest
    from manuscript_guard.vault.records import release_file

    root = Path(project.root)
    files = []
    for relative, kind in ([(one, "results") for one in box.fragments]
                           + [(one, "harvested") for one, _entry in box.harvested]
                           + [(one, "plan") for one in box.plan]
                           + [(one, "named") for one in named]):  # fmt: skip
        source, target = box.folder / relative, root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "results":
            target.write_bytes(_released_bytes(source))
            write_digest(target)
        else:
            shutil.copyfile(source, target)
        files.append({"path": relative, "sha256": sha256_of(target),
                      "bytes": target.stat().st_size, "kind": kind})  # fmt: skip
    name, orcid, role = who
    manifest = box.manifest
    record = {
        "schema": RELEASE_SCHEMA, "run": box.run, "released_by": name,
        **({"orcid": str(orcid)} if orcid else {}), "role": role, "released_at": _now(),
        "ran_at": manifest.get("ran_at", ""), "commit": manifest.get("commit"),
        "scripts": list(manifest.get("scripts") or ()), "ran": list(manifest.get("ran") or ()),
        "inputs": [{"label": label, "sha256": digest} for label, digest in inputs],
        "files": files, "warnings": warnings, "signed_off": signed,
    }  # fmt: skip
    path = release_file(root, box.run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")  # fmt: skip
    return path


__all__ = ["AGENT_READS", "SENT", "SMALL_COUNTS", "Outbox", "Reading", "Refused",
           "agent_signable", "open_outbox", "read_outbox", "releaser", "small_signable",
           "vault_signables", "write_release"]
