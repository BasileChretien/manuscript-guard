"""Taking in the outputs of scripts that do not use the emitter (`manuscript-guard harvest`).

An analysis written before the toolkit, or by someone who will not change it, writes a CSV
or a JSON of its estimates and nothing else. `harvest` reads such a file by the entry of
`harvest.yaml` that names it, and writes a results fragment from it, so that the manuscript
binds its numbers as it binds emitted ones. It never runs anything: that the script writes
the output is declared, and G1 says so of the fragment (`harvest-declared`) until `verify`
has run the script and read the same values from what it wrote, or a site's receipt covers
the run (docs/harvest.md).
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.emit import input_digest, input_digest_matches, sha256_of
from manuscript_guard.harvest.config import (
    HARVEST_FILE,
    Entry,
    HarvestError,
    Input,
    append_entry,
    load_entries,
)
from manuscript_guard.harvest.fragment import document_of, results_path, write_fragment
from manuscript_guard.harvest.receipt import (
    RECEIPTS,
    make_receipt,
    read_receipt,
    receipt_path,
    run_of,
)

__all__ = [
    "HARVEST_FILE",
    "RECEIPTS",
    "Entry",
    "HarvestError",
    "Input",
    "append_entry",
    "harvest_entry",
    "harvested_document",
    "load_entries",
    "make_receipt",
    "read_receipt",
    "receipt_path",
    "results_path",
    "run_of",
    "standing",
]


def harvest_entry(root: Path, entry: Entry) -> Path:
    """Read `entry`'s output and write its fragment; return the fragment's path."""
    return write_fragment(root, entry, harvested_document(root, entry))


def harvested_document(root: Path, entry: Entry) -> dict:
    """The fragment `entry` reads from its output, written nowhere: refused as
    `harvest_entry` refuses it."""
    output = root / entry.output
    if not output.is_file():
        raise HarvestError(f"{entry.output} is not there: run {entry.script}, which writes it, "
                           "and harvest it then")  # fmt: skip
    if entry.receipt is None:
        return document_of(root, entry, output)
    inputs, receipt = _from_receipt(root, entry, output)
    return document_of(root, entry, output, inputs=inputs, receipt=receipt)


def _from_receipt(root: Path, entry: Entry, output: Path) -> tuple[list[dict], dict]:
    """The inputs the site's receipt records for `entry`, by label, and the receipt as the
    fragment records it; refused where the output is not the one the receipt covers."""
    path = receipt_path(root, entry.receipt or "")
    if not path.is_file():
        raise HarvestError(f"{entry.key} is covered by the receipt of {entry.receipt}, and "
                           f"{path.relative_to(root).as_posix()} is not there")  # fmt: skip
    receipt = read_receipt(path)
    run = run_of(receipt, entry.key)
    if receipt["site"] != entry.receipt or run is None:
        raise HarvestError(f"{path.name} records no run of {entry.key} at {entry.receipt}")
    covered = [out for out in run["outputs"] if out["path"] == entry.output]
    if not covered or not input_digest_matches(output, covered[0]["sha256"]):
        raise HarvestError(f"{entry.output} is not the output the receipt of {entry.receipt} "
                           "covers: harvest the file the site sent with it")  # fmt: skip
    flags = {given.path: given for given in entry.inputs}
    inputs = []
    for held in run["inputs"]:
        given = flags.get(held["label"], Input(held["label"]))
        inputs.append({"path": held["label"], "sha256": held["sha256"],
                       "raw_sha256": held["raw_sha256"], "bytes": held["bytes"],
                       **({"restricted": True} if given.restricted else {}),
                       **({"synthetic": True} if given.synthetic else {})})  # fmt: skip
    recorded = {"site": receipt["site"], "path": path.relative_to(root).as_posix(),
                "sha256": input_digest(path), "ran_at": receipt["ran_at"]}  # fmt: skip
    return inputs, recorded


def standing(build: Path, fragment: Path, harvested: dict) -> str:
    """What covers a harvested fragment: "receipt" where a site's receipt is recorded for it,
    "reproduced" where the last `verify` in this checkout re-ran its script and read the same
    values from the fragment as it is (its record in the build folder `build`), "declared"
    otherwise."""
    if harvested.get("receipt"):
        return "receipt"
    import json

    from manuscript_guard.assurance import VERIFIED, VERIFIED_SCHEMA

    try:
        record = json.loads((build / VERIFIED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "declared"
    if not isinstance(record, dict) or record.get("schema") != VERIFIED_SCHEMA:
        return "declared"
    reproduced = record.get("fragments_reproduced")
    if isinstance(reproduced, dict) and reproduced.get(fragment.name) == sha256_of(fragment):
        return "reproduced"
    return "declared"
