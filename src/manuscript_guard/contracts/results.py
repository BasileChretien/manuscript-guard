"""Loading the results namespace from one or more machine-written fragments.

A real project has several analysis scripts, so results live in a directory of fragments
rather than a single file. Each fragment carries its own provenance, which is what lets the
freshness gate say *which* script is stale rather than merely that something is.

A key defined by two fragments is an error. Last-one-wins would make the value of a number
depend on filesystem ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.values import RESULTS, DisplayError, Value, derive_display
from manuscript_guard.findings import Finding, Report, merge_all

FRAGMENT_GLOB = "*.json"


@dataclass(frozen=True)
class Fragment:
    path: Path
    generated_by: str
    generated_at: str
    inputs: tuple[dict, ...]
    vcs: dict
    session: dict
    # Digest of the analysis script as it stood when it wrote this fragment. Optional
    # because fragments written before the field existed do not carry it; G1 falls back to
    # comparing modification times for those, which is what it always did.
    generated_by_sha256: str | None = None


@dataclass(frozen=True)
class Table:
    key: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    caption: str | None
    align: tuple[str, ...]
    quoted: bool
    source: Path


@dataclass(frozen=True)
class Results:
    values: dict[str, Value]
    fragments: tuple[Fragment, ...]
    tables: dict[str, Table] = field(default_factory=dict)

    def get(self, key: str) -> Value | None:
        return self.values.get(key)

    @property
    def quoted_keys(self) -> frozenset[str]:
        return frozenset(k for k, v in self.values.items() if v.quoted)

    @property
    def quoted_tables(self) -> frozenset[str]:
        return frozenset(k for k, t in self.tables.items() if t.quoted)


def load_results(results_dir: Path) -> tuple[Results, Report]:
    """Read and merge every fragment in `results_dir`."""
    if not results_dir.exists():
        return Results({}, ()), Report(
            (
                Finding(
                    gate="G0",
                    code="no-results-dir",
                    message=f"results directory not found: {results_dir}",
                    path=results_dir,
                    hint="run the analysis, or set paths.results in paper.yaml",
                ),
            )
        )

    paths = sorted(results_dir.glob(FRAGMENT_GLOB))
    if not paths:
        return Results({}, ()), Report(
            (
                Finding(
                    gate="G0",
                    code="no-results",
                    message=f"no results fragments in {results_dir}",
                    path=results_dir,
                    hint="an analysis script should write one with emit()",
                ),
            )
        )

    reports: list[Report] = []
    values: dict[str, Value] = {}
    owner: dict[str, Path] = {}
    fragments: list[Fragment] = []
    tables: dict[str, Table] = {}
    table_owner: dict[str, Path] = {}

    for path in paths:
        document = read_structured(path)
        report = validate(document, "results", path)
        reports.append(report)
        if not report.ok or not isinstance(document, dict):
            continue

        prov = document["provenance"]
        fragments.append(
            Fragment(
                path=path,
                generated_by=prov["generated_by"],
                generated_at=prov["generated_at"],
                inputs=tuple(prov.get("inputs", ())),
                vcs=prov.get("vcs", {}),
                session=prov.get("session", {}),
                generated_by_sha256=prov.get("generated_by_sha256"),
            )
        )

        for key, spec in document["values"].items():
            if key in owner:
                reports.append(
                    Report(
                        (
                            Finding(
                                gate="G0",
                                code="duplicate-key",
                                message=f"results key {key!r} is defined twice",
                                path=path,
                                context=f"also defined in {owner[key].name}",
                                hint="rename one, or have a single script own the key",
                            ),
                        )
                    )
                )
                continue
            try:
                display = derive_display(
                    key, spec["value"], spec.get("display"), spec.get("digits")
                )
            except DisplayError as exc:
                reports.append(
                    Report((Finding(gate="G0", code="no-display", message=str(exc), path=path),))
                )
                continue
            owner[key] = path
            values[key] = Value(
                key=key,
                value=spec["value"],
                display=display,
                origin=RESULTS,
                source=path,
                unit=spec.get("unit"),
                quoted=spec.get("quoted", True),
                same_as=spec.get("same_as"),
            )

        for key, spec in document.get("tables", {}).items():
            if key in table_owner:
                reports.append(
                    Report(
                        (
                            Finding(
                                gate="G0",
                                code="duplicate-table",
                                message=f"table {key!r} is defined twice",
                                path=path,
                                context=f"also defined in {table_owner[key].name}",
                            ),
                        )
                    )
                )
                continue
            table_owner[key] = path
            columns = tuple(spec["columns"])
            tables[key] = Table(
                key=key,
                columns=columns,
                rows=tuple(tuple(row) for row in spec.get("rows", ())),
                caption=spec.get("caption"),
                align=tuple(spec.get("align") or ["left"] * len(columns)),
                quoted=spec.get("quoted", True),
                source=path,
            )

    merged = merge_all(reports).with_counts(
        results_fragments=len(fragments),
        results_values=len(values),
        results_tables=len(tables),
    )
    return Results(values, tuple(fragments), tables), merged
