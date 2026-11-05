"""The hierarchy of evidence a reading places a work on: the toolkit's, or the project's.

The toolkit's own (`data/evidence_hierarchies.yaml`) holds the Oxford 2011 Levels of
Evidence, in its own words with CEBM's citation. A project may name another in paper.yaml,
`references.hierarchy`, in the same shape; it is then the only one readings are held to.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project

BUILT_IN = Path(__file__).resolve().parent.parent / "data" / "evidence_hierarchies.yaml"


@dataclass(frozen=True)
class Hierarchy:
    """One hierarchy: its id, its name and, on each scale, its levels by number."""

    id: str
    name: str
    scales: dict[str, dict[int, str]]
    citation: str | None = None


def _read(path: Path) -> dict[str, Hierarchy]:
    """The hierarchies of one file, by id, held to their schema; whatever stops them being
    read is raised as `ContractError`, in a sentence that names the file."""
    document = read_structured(path)
    if document is None:
        raise ContractError(f"{path}: no such file")
    report = validate(document, "evidence-hierarchy", path)
    if not report.ok:
        problems = "; ".join(finding.message for finding in report.failures)
        raise ContractError(f"{path}: not a hierarchy of evidence: {problems}")
    found = {}
    for key, entry in document["hierarchies"].items():
        scales: dict[str, dict[int, str]] = {}
        for scale, said in entry["scales"].items():
            levels = {}
            for number, words in said["levels"].items():
                if not str(number).isdigit() or int(number) < 1:
                    raise ContractError(f"{path}: {key}, {scale}: level {number!r} is not a "
                                        "whole number from 1")  # fmt: skip
                levels[int(number)] = str(words)
            scales[str(scale)] = levels
        found[str(key)] = Hierarchy(str(key), str(entry["name"]), scales, entry.get("citation"))
    return found


def hierarchies(project: Project | None = None) -> dict[str, Hierarchy]:
    """The hierarchies readings are held to: the project's, where paper.yaml names a file
    under `references.hierarchy`, else the toolkit's."""
    named = ((project.setting("references") or {}).get("hierarchy")
             if project is not None else None)  # fmt: skip
    if named:
        return _read(project.root / str(named))
    return _read(BUILT_IN)


def level_problem(found: dict[str, Hierarchy], hierarchy: str, scale: str,
                  levels: list[int]) -> str | None:  # fmt: skip
    """Why a reading's hierarchy, scale or levels are not ones `found` holds, or None."""
    if hierarchy not in found:
        return f"no hierarchy {hierarchy!r} (there are: {', '.join(sorted(found))})"
    scales = found[hierarchy].scales
    if scale not in scales:
        return f"{hierarchy} has no scale {scale!r} (it has: {', '.join(scales)})"
    off = sorted({level for level in levels if level not in scales[scale]})
    if off:
        return f"{hierarchy}, {scale} has no level {', '.join(map(str, off))}"
    return None


__all__ = ["BUILT_IN", "Hierarchy", "hierarchies", "level_problem"]
