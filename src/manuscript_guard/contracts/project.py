"""Project discovery and the paper/authors configuration.

A project is any directory containing `paper.yaml`. Commands walk upwards to find it, so
they work from anywhere inside the tree, the way git does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.findings import Report, merge_all

PAPER_FILE = "paper.yaml"
AUTHORS_FILE = "authors.yaml"

DEFAULT_PATHS = {
    "analysis": "analysis",
    "results": "results",
    "literature": "literature",
    "manuscript": "manuscript",
    "figures": "figures",
    "build": "build",
}


@dataclass(frozen=True)
class Project:
    root: Path
    paper: dict
    authors: dict | None

    def path(self, which: str) -> Path:
        configured = self.paper.get("paths", {}).get(which, DEFAULT_PATHS[which])
        return self.root / configured

    @property
    def english_variant(self) -> str:
        return self.paper.get("english_variant", "en-GB")

    @property
    def target_journal(self) -> str | None:
        return self.paper.get("target_journal")

    @property
    def reporting_guidelines(self) -> tuple[str, ...]:
        return tuple(self.paper.get("reporting_guideline", ()))

    @property
    def extra_conventions(self) -> tuple[dict, ...]:
        return tuple(self.paper.get("conventions", ()))

    @property
    def extra_terms(self) -> tuple[str, ...]:
        return tuple(self.paper.get("terms", ()))


def find_root(start: Path) -> Path:
    """Walk upwards for the directory holding paper.yaml."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / PAPER_FILE).exists():
            return candidate
    raise ContractError(
        f"no {PAPER_FILE} found in {start} or any parent directory; "
        f"run `manuscript-guard init` to create a project"
    )


def load_project(start: Path | None = None) -> tuple[Project, Report]:
    root = find_root(start or Path.cwd())
    reports: list[Report] = []

    paper_path = root / PAPER_FILE
    paper = read_structured(paper_path) or {}
    reports.append(validate(paper, "paper", paper_path))

    authors_path = root / AUTHORS_FILE
    authors = read_structured(authors_path)
    if authors is not None:
        reports.append(validate(authors, "authors", authors_path))

    return Project(root, paper, authors), merge_all(reports)
