"""Writing `results/<key>.json` from an output, as the emitter writes a fragment.

The values and the table go through the Python emitter (`emit.Emitter`), so that a harvested
fragment is held to every rule an emitted one is: a display is a rendering of its value, a
text cell carries no number no gate can trace, and a table cell is one the emitter formatted.
Each cell is a value, `<key>.<row>.<column>`, written as an intermediate (`quoted: false`):
an output has more cells than a paper quotes, and the table, `table.<key>`, is what is placed.

The provenance is the emitter's, with the declared script and its digest now, and the inputs
as the emitter writes them, so that G1 holds them unchanged. To it `harvested` is added: the
output's path, its digests and size, the entry it was read by, and that the script's writing
it is declared (`attribution: declared`). Where a site's receipt covers the output, the
inputs are the receipt's, by label, since the data are at the site, and the receipt's digest
is recorded beside them.
"""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard.contracts.values import DisplayError
from manuscript_guard.emit import Emitter, freeze_plan, input_digest, sha256_of, write_digest
from manuscript_guard.harvest.config import Entry, HarvestError
from manuscript_guard.harvest.read import read_output


def results_path(root: Path, entry: Entry) -> Path:
    return root / "results" / f"{entry.key}.json"


def document_of(root: Path, entry: Entry, output: Path, *, inputs: list[dict] | None = None,
                receipt: dict | None = None) -> dict:  # fmt: skip
    """The fragment `entry` reads from `output`, under the project at `root`. `inputs`, where
    given, are written as they are; otherwise each input is digested where it is."""
    script = root / entry.script
    if not script.is_file():
        raise HarvestError(f"{entry.script}, the script declared to write {entry.output}, is "
                           "not there")  # fmt: skip
    try:
        data = output.read_bytes()
    except OSError as exc:
        raise HarvestError(f"{entry.output} cannot be read: {exc}") from exc
    table = read_output(data, output.suffix.lower(), entry)
    emitter = Emitter(script=script, root=root)
    if inputs is None:
        for given in entry.inputs:
            if not (root / given.path).exists():
                raise HarvestError(f"{given.path}, an input of {entry.key}, is not there")
            emitter.add_input(given.path, restricted=given.restricted, synthetic=given.synthetic)
    try:
        for key, cell in table.values(entry.key).items():
            emitter.value(key, cell.value, display=cell.display, unit=cell.unit, quoted=False,
                          label=cell.label)  # fmt: skip
        emitter.table(entry.key, list(table.columns), [
            ["" if found is None else Emitter.cell("{}", (found.value, found.display))
             for found in cells] for _name, cells in table.rows], quoted=entry.quoted)  # fmt: skip
        document = emitter.document()
        for key, counted in table.counted(entry.key, entry.counts).items():
            document["values"][key]["count"] = counted
    except (DisplayError, ValueError) as exc:
        raise HarvestError(f"{entry.output}: {exc}") from exc
    provenance = document["provenance"]
    # The emitter's session is this process's Python, which ran nothing of the analysis.
    provenance.pop("session", None)
    if inputs is not None:
        provenance["inputs"] = inputs
    provenance["harvested"] = {
        "output": entry.output, "sha256": input_digest(output), "raw_sha256": sha256_of(output),
        "bytes": len(data), "spec": entry.spec(), "attribution": "declared",
        **({"receipt": receipt} if receipt is not None else {}),
    }  # fmt: skip
    return document


def write_fragment(root: Path, entry: Entry, document: dict) -> Path:
    """Write the fragment and its digest; refused over a results file `harvest` did not
    write, which an analysis did."""
    path = not_emitted(root, entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8", newline="\n")
    write_digest(path)
    synthetic = bool(entry.inputs) and all(given.synthetic for given in entry.inputs)
    freeze_plan(root, root / entry.script, synthetic=synthetic)
    return path


def not_emitted(root: Path, entry: Entry) -> Path:
    """The results file of `entry`, refused where it is one an analysis wrote."""
    path = results_path(root, entry)
    if path.exists():
        try:
            held = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = None
        if not (isinstance(held, dict) and (held.get("provenance") or {}).get("harvested")):
            raise HarvestError(f"{path.name} is there already and harvest did not write it; "
                               "give the entry another key")  # fmt: skip
    return path
