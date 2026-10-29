"""A site's receipt: the scripts run where the data are, and what came out, by digest.

Where a custodian keeps the data at their site, the centre that writes the paper cannot run
the analysis, and `verify` there has nothing to run it on. So the site runs it:
`manuscript-guard verify --receipt SITE`, in its copy of the project, runs the script of each
harvest entry naming SITE in a scratch copy, as `verify` does, with the declared output
deleted first, and writes `receipts/<site>.receipt.json`. The receipt says when, with which
version of this tool and of the runner, the script by its path and digest, each input by its
label (its path from the project's root, never where it is on the site's disks) and digests,
the lockfiles, each output by its digest and size, and the exit code. The output the run
wrote is put where the entry declares it, to be sent with the receipt.

Before anything is written, the outputs are held to the custodian's rules, every column of
them, since the outputs are what leaves the site: a count printed below
`custodian.minimum_cell_count`, held back behind a bound tighter than it, or in text no count
can be read from, refuses the receipt. A count held back that a total row or a header gives
away by subtraction is a warning, printed, as `deposit` says it.

A receipt is unsigned: a declaration by whoever ran it, as an attestation is. It proves that
a file with these digests was written, not who wrote it or that the run took place.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.emit import input_digest, lockfile_digest, sha256_of, source_digest
from manuscript_guard.findings import FAIL
from manuscript_guard.harvest.config import Entry, HarvestError, load_entries
from manuscript_guard.harvest.read import read_output
from manuscript_guard.paths import lockfiles

RECEIPT_SCHEMA = "manuscript-guard/receipt/1"
RECEIPTS = "receipts"
#: How long a runner may take to say its version.
VERSION_SECONDS = 30


def receipt_path(root: Path, site: str) -> Path:
    return root / RECEIPTS / f"{site}.receipt.json"


def read_receipt(path: Path) -> dict:
    """The receipt at `path`, refused where it is not one."""
    try:
        document = read_structured(path)
    except ContractError as exc:
        raise HarvestError(str(exc)) from exc
    report = validate(document, "receipt", path)
    if not report.ok:
        raise HarvestError(report.render(path.parent))
    return document


def run_of(receipt: dict, key: str) -> dict | None:
    return next((run for run in receipt["runs"] if run["key"] == key), None)


def _version(command: list[str]) -> str:
    """What the runner says its version is, its first line; "unknown" where it says none."""
    import sys

    if command[0] == sys.executable:
        return f"Python {sys.version.split()[0]}"
    try:
        said = subprocess.run([command[0], "--version"], capture_output=True, text=True,
                              timeout=VERSION_SECONDS, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    lines = (said.stdout or said.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else "unknown"


def _counts_held(project, entry: Entry, output: Path) -> tuple[list[str], list[str]]:
    """What the custodian forbids in the output, which refuses the receipt, and what it may
    give away, which is a warning. The whole file is read, every column of it, since the
    whole file leaves the site, each cell as the output wrote it. A count printed below the
    minimum, or held back behind a bound tighter than it ("<2"), refuses, as G2 reads one
    (`is_count`, `_small`): a cell in a column `counts` names, or in a column the entry does
    not take in, which nothing shows is no count; every one where `counts` names none. A
    count held back that a total row or a header's n gives away (`recoverable_cells`) is a
    warning, as `deposit` says it: a total read from a label may be no sum, and a harvested
    output declares none."""
    from manuscript_guard.contracts.results import Results, Table
    from manuscript_guard.contracts.values import RESULTS, Value
    from manuscript_guard.gates.custodian import (
        UNREAD,
        UNREAD_HINT,
        _small,
        is_count,
        minimum_cell_count,
        recoverable_cells,
    )

    minimum = minimum_cell_count(project)
    if minimum is None:
        return [], []
    table = read_output(output.read_bytes(), output.suffix.lower(),
                        replace(entry, columns=None, digits=None))  # fmt: skip
    counts = entry.counts
    if counts is not None and entry.columns is not None:
        counts = (*counts, *(name for name in table.columns if name not in entry.columns))
    marks = table.counted(entry.key, counts)
    said = []
    for key, cell in table.values(entry.key).items():
        value = Value(key, cell.value, cell.display, RESULTS, unit=cell.unit, label=cell.label,
                      count=marks.get(key))  # fmt: skip
        wrong = _small(value, minimum) if is_count(value) else None
        if wrong is not None:
            said.append(f"{key} is {cell.display}, {wrong} the data custodian's minimum of "
                        f"{minimum}" + (f": {UNREAD_HINT}" if wrong == UNREAD else ""))  # fmt: skip
    source = project.root / "results" / f"{entry.key}.json"
    rows = tuple(tuple("" if c is None else c.display for c in cells) for _n, cells in table.rows)
    held = Table(entry.key, table.columns, rows, None, ("left",) * len(table.columns), True,
                 source)  # fmt: skip
    results = Results({}, (), {entry.key: held})
    found = recoverable_cells(project, results, frozenset({f"results/{entry.key}.json"}))
    refused = said + [f.message for f in found.findings if f.severity == FAIL]
    return refused, [f.message for f in found.findings if f.severity != FAIL]


def make_receipt(project, site: str) -> tuple[Path, list[str], list[str]]:
    """Run each entry naming `site` in a scratch copy and write the receipt; return its path,
    what was written and the custodian's warnings. Refused, with nothing written, where a run
    fails, writes no output, or writes one the custodian forbids."""
    from manuscript_guard.verify import _run, _skip, runner_for

    root = Path(project.root)
    entries = [entry for entry in load_entries(root) if entry.receipt == site]
    if not entries:
        raise HarvestError(f"no entry of harvest.yaml names the site {site!r} as its receipt")
    runs, outputs, warned = [], [], []
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch) / root.name
        try:
            shutil.copytree(root, work, symlinks=True, ignore=_skip)
        except (OSError, shutil.Error) as exc:
            raise HarvestError(f"could not stage a copy of the project: {exc}") from exc
        for entry in entries:
            run, warnings = _run_entry(project, root, work, entry, _run, runner_for)
            runs.append(run)
            warned += [f"{entry.output}: {said}" for said in warnings]
            outputs.append((work / entry.output, root / entry.output))
        receipt = {
            "schema": RECEIPT_SCHEMA, "site": site,
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": {"name": "manuscript-guard", "version": __version__},
            "environment": [{"path": path.relative_to(root).as_posix(),
                             "sha256": lockfile_digest(path)} for path in lockfiles(root)],
            "runs": runs,
        }  # fmt: skip
        written = []
        for made, kept in outputs:
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(made, kept)
            written.append(kept.relative_to(root).as_posix())
    path = receipt_path(root, site)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path, written, warned


def _run_entry(project, root: Path, work: Path, entry: Entry, run, runner_for
               ) -> tuple[dict, list[str]]:  # fmt: skip
    """One entry run in the scratch copy `work`, as its receipt records it, and the
    custodian's warnings of its output."""
    script = work / entry.script
    if not script.is_file():
        raise HarvestError(f"{entry.script}, the script of {entry.key}, is not there")
    command = runner_for(script)
    if command is None:
        raise HarvestError(f"no runner for {script.suffix} on this machine, to run {entry.script}")
    inputs = []
    for given in entry.inputs:
        path = root / given.path
        if not path.is_file():
            raise HarvestError(f"{given.path}, an input of {entry.key}, is not here")
        inputs.append({"label": given.path, "sha256": input_digest(path),
                       "raw_sha256": sha256_of(path), "bytes": path.stat().st_size})  # fmt: skip
    output = work / entry.output
    if output.exists():
        output.unlink()
    try:
        finished = run(script, work, None)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HarvestError(f"{entry.script} could not run: {exc}") from exc
    if finished.returncode != 0:
        tail = (finished.stderr or finished.stdout or "").strip()[-400:]
        raise HarvestError(f"{entry.script} exited {finished.returncode}\n{tail}")
    if not output.is_file():
        raise HarvestError(f"{entry.script} ran but wrote no {entry.output}")
    forbidden, warnings = _counts_held(project, entry, output)
    if forbidden:
        raise HarvestError(f"{entry.output} holds what the data custodian forbids leaving the "
                           "site:\n  " + "\n  ".join(forbidden))  # fmt: skip
    return {
        "key": entry.key,
        "runner": {"command": Path(command[0]).name, "version": _version(command)},
        "script": {"path": entry.script, "sha256": source_digest(script)},
        "inputs": inputs,
        "outputs": [{"path": entry.output, "sha256": input_digest(output),
                     "bytes": output.stat().st_size}],
        "exit_code": finished.returncode,
    }, warnings  # fmt: skip
