"""The `lit.` namespace: numbers taken from published work.

Two files feed it. `ledger.yaml` holds values extracted from a source the toolkit stored,
and `attested.yaml` holds values the author read in a source that could not be retrieved.
They are separate files on purpose: keeping author-attested numbers in their own place
means the set resting on a person's word rather than a stored artefact can be reviewed at
a glance, instead of being buried among hundreds of ledger rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.values import (
    ATTESTED,
    LITERATURE,
    DisplayError,
    Value,
    derive_display,
)
from manuscript_guard.findings import Finding, Report, merge_all

LEDGER_FILE = "ledger.yaml"
ATTESTED_FILE = "attested.yaml"

FULL_TEXT = "full-text"
ABSTRACT_ONLY = "abstract-only"
USER_ATTESTED = "user-attested"


@dataclass(frozen=True)
class Literature:
    values: dict[str, Value]
    root: Path

    def get(self, key: str) -> Value | None:
        return self.values.get(key)

    def by_depth(self, depth: str) -> tuple[Value, ...]:
        return tuple(v for v in self.values.values() if (v.detail or {}).get("depth") == depth)


def _add(
    values: dict[str, Value],
    owner: dict[str, Path],
    entry: dict,
    origin: str,
    depth: str,
    path: Path,
    reports: list[Report],
) -> None:
    key = entry["key"]
    if key in owner:
        reports.append(
            Report(
                (
                    Finding(
                        gate="G0",
                        code="duplicate-key",
                        message=f"literature key {key!r} is defined twice",
                        path=path,
                        context=f"also defined in {owner[key].name}",
                        hint="a key may live in the ledger or in attested.yaml, not both",
                    ),
                )
            )
        )
        return
    try:
        display = derive_display(key, entry["value"], entry.get("display"), entry.get("digits"))
    except DisplayError as exc:
        reports.append(
            Report((Finding(gate="G0", code="no-display", message=str(exc), path=path),))
        )
        return
    owner[key] = path
    values[key] = Value(
        key=key,
        value=entry["value"],
        display=display,
        origin=origin,
        source=path,
        unit=entry.get("unit"),
        quoted=True,
        detail={**entry, "depth": depth},
    )


def load_literature(literature_dir: Path) -> tuple[Literature, Report]:
    """Read ledger.yaml and attested.yaml. Neither is required; a project may cite nothing."""
    reports: list[Report] = []
    values: dict[str, Value] = {}
    owner: dict[str, Path] = {}

    ledger_path = literature_dir / LEDGER_FILE
    document = read_structured(ledger_path)
    if document is not None:
        report = validate(document, "ledger", ledger_path)
        reports.append(report)
        if report.ok and isinstance(document, dict):
            for entry in document.get("entries", []):
                _add(values, owner, entry, LITERATURE, entry["depth"], ledger_path, reports)

    attested_path = literature_dir / ATTESTED_FILE
    document = read_structured(attested_path)
    if document is not None:
        report = validate(document, "attested", attested_path)
        reports.append(report)
        if report.ok and isinstance(document, dict):
            for entry in document.get("entries", []):
                _add(values, owner, entry, ATTESTED, USER_ATTESTED, attested_path, reports)

    literature = Literature(values, literature_dir)
    merged = merge_all(reports).with_counts(
        literature_values=len(values),
        literature_full_text=len(literature.by_depth(FULL_TEXT)),
        literature_abstract_only=len(literature.by_depth(ABSTRACT_ONLY)),
        literature_attested=len(literature.by_depth(USER_ATTESTED)),
    )
    return literature, merged
