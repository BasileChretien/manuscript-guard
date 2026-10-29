"""harvest.yaml: the outputs a script writes without the emitter, each taken in as results.

An entry names the output, the script declared to write it and the data it read:

    entries:
      - key: cohort
        output: output/cohort.csv
        script: analysis/cohort.R
        inputs:
          - path: data/extract.csv
            restricted: true
        row_key: group

`harvest` reads the file and writes `results/<key>.json`; it runs nothing. The file is
validated against `harvest.schema.json`, and an entry is added only at the end of the
file, its text read back to be the entries it held and the new one (as `set` writes
paper.yaml), so that the author's comments stay where they were.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, validate

HARVEST_FILE = "harvest.yaml"
OUTPUT_SUFFIXES = (".csv", ".tsv", ".json")
_HEAD = (
    "# Outputs a script writes without the emitter, taken in by `manuscript-guard harvest`.\n"
    "# Each becomes results/<key>.json; harvest runs nothing (docs/harvest.md).\n"
    "entries:\n"
)


class HarvestError(Exception):
    """An output, an entry or a receipt that cannot be taken in, said in words."""


@dataclass(frozen=True)
class Input:
    path: str
    restricted: bool = False
    synthetic: bool = False

    def spec(self) -> dict:
        return {"path": self.path, **({"restricted": True} if self.restricted else {}),
                **({"synthetic": True} if self.synthetic else {})}  # fmt: skip


@dataclass(frozen=True)
class Entry:
    key: str
    output: str
    script: str
    inputs: tuple[Input, ...] = ()
    row_key: str | None = None
    columns: tuple[str, ...] | None = None
    digits: int | dict[str, int] | None = None
    receipt: str | None = None
    #: Whether the table is to be placed, as `em.table(quoted=...)`: False for working output.
    quoted: bool = True
    #: The columns whose cells are counts, held to the custodian's minimum; None for every
    #: whole number with no unit, as G2 reads an emitted value.
    counts: tuple[str, ...] | None = None

    def spec(self) -> dict:
        """The entry as harvest.yaml writes it, and as the fragment records it."""
        spec: dict = {"key": self.key, "output": self.output, "script": self.script,
                      "inputs": [given.spec() for given in self.inputs]}  # fmt: skip
        for name in ("row_key", "digits", "receipt"):
            if getattr(self, name) is not None:
                spec[name] = getattr(self, name)
        if self.columns is not None:
            spec["columns"] = list(self.columns)
        if not self.quoted:
            spec["quoted"] = False
        if self.counts is not None:
            spec["counts"] = list(self.counts)
        return spec

    @classmethod
    def from_spec(cls, spec: dict) -> Entry:
        columns, counts = spec.get("columns"), spec.get("counts")
        return cls(
            key=spec["key"], output=spec["output"], script=spec["script"],
            inputs=tuple(Input(str(given["path"]), bool(given.get("restricted", False)),
                               bool(given.get("synthetic", False)))
                         for given in spec.get("inputs") or ()),
            row_key=spec.get("row_key"),
            columns=tuple(columns) if columns is not None else None,
            digits=spec.get("digits"), receipt=spec.get("receipt"),
            quoted=spec.get("quoted", True) is not False,
            counts=tuple(counts) if counts is not None else None,
        )  # fmt: skip

    def digits_for(self, column: str) -> int | None:
        if isinstance(self.digits, dict):
            return self.digits.get(column)
        return self.digits


def load_entries(root: Path) -> list[Entry]:
    """The entries of `root`'s harvest.yaml, none where there is no file; refused where the
    file breaks its schema, or two entries share a key or an output."""
    path = root / HARVEST_FILE
    if not path.exists():
        return []
    try:
        document = read_structured(path)
    except ContractError as exc:
        raise HarvestError(str(exc)) from exc
    report = validate(document, "harvest", path)
    if not report.ok:
        raise HarvestError(report.render(root))
    entries = [Entry.from_spec(spec) for spec in document["entries"]]
    for name in ("key", "output"):
        seen = [getattr(entry, name) for entry in entries]
        twice = sorted({one for one in seen if seen.count(one) > 1})
        if twice:
            raise HarvestError(f"{path}: two entries share the {name} {twice[0]!r}")
    return entries


def entry_for(root: Path, key: str) -> Entry:
    for entry in load_entries(root):
        if entry.key == key:
            return entry
    raise HarvestError(f"{root / HARVEST_FILE} has no entry {key!r}")


def append_entry(root: Path, entry: Entry) -> Path:
    """Add `entry` at the end of harvest.yaml, writing the file where there is none. Refused,
    with nothing written, where an entry has its key or its output, or where the text with
    the entry added would not read back as the entries before and this one."""
    path = root / HARVEST_FILE
    before = load_entries(root)
    for held in before:
        if held.key == entry.key or held.output == entry.output:
            raise HarvestError(
                f"{path} already has an entry for {held.key!r} ({held.output}); edit it there, "
                "or give another key")  # fmt: skip
    dumped = yaml.safe_dump([entry.spec()], sort_keys=False, allow_unicode=True)
    held = path.read_bytes().decode("utf-8") if path.exists() else None
    # The list indented, as `init` and this command write it, or not, as `yaml.safe_dump`
    # writes it: whichever reads back as the entries before and this one.
    for indent in ("  ", ""):
        block = "".join(f"{indent}{line}\n" for line in dumped.splitlines())
        if held is None:
            text = _HEAD + block
        else:
            text = held + ("" if held.endswith("\n") else "\n") + block
        if _reads_as(text, [*before, entry]):
            path.write_bytes(text.encode("utf-8"))
            return path
    raise HarvestError(
        f"{path} does not end in its list of entries, so one added at its end would not read "
        "as one of them; add it there by hand")  # fmt: skip


def _reads_as(text: str, entries: list[Entry]) -> bool:
    try:
        reread = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    listed = reread.get("entries") if isinstance(reread, dict) else None
    return isinstance(listed, list) and all(isinstance(spec, dict) for spec in listed) and [
        Entry.from_spec(spec) for spec in listed] == entries
