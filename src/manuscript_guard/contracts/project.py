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


def _held(value: object) -> str:
    """What YAML made of a value, in the words an author would use for it."""
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "a yes or no"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "settings"
    return "something else"


def _settings(paper: object, path: Path) -> dict:
    """The parsed `paper.yaml`, once it is known to be what `Project` reads it as.

    The schema reports a wrong shape as a finding, but `Project` is asked where the results
    are before there is a report to print, and a list or a line of text has no `paths` to
    ask: `check` ended in `AttributeError`, the finding was never seen, and the hooks took
    the traceback for a fault of the tool. So the two things every command needs of this
    file are held here, and said in a sentence: that it is settings, and that each folder it
    names is named in text. Everything else in it is still the schema's to report.
    """
    if paper is None:  # an empty file: nothing set yet, and the schema says what to add
        return {}
    if not isinstance(paper, dict):
        cause = (
            " (a line such as `title:My paper`, with no space after the colon, is read as text)"
            if isinstance(paper, str)
            else ""
        )
        raise ContractError(
            f"{path}: holds {_held(paper)} where the settings of the paper are expected, "
            f"one `key: value` to a line{cause}"
        )
    if "paths" not in paper:
        return paper
    paths = paper["paths"]
    if not isinstance(paths, dict):
        raise ContractError(
            f"{path}: `paths` holds {_held(paths)} where a folder is expected for each name "
            f"it changes, as in `results: output`, indented on a line of its own"
        )
    for which in DEFAULT_PATHS:
        if which in paths and not isinstance(paths[which], str):
            raise ContractError(
                f"{path}: `paths.{which}` holds {_held(paths[which])} where the name of a "
                f"folder is expected, as in `{which}: {DEFAULT_PATHS[which]}`"
            )
    return paper


def load_project(start: Path | None = None) -> tuple[Project, Report]:
    root = find_root(start or Path.cwd())
    reports: list[Report] = []

    paper_path = root / PAPER_FILE
    paper = _settings(read_structured(paper_path), paper_path)
    reports.append(validate(paper, "paper", paper_path))

    authors_path = root / AUTHORS_FILE
    authors = read_structured(authors_path)
    if authors is not None:
        # A distinct code, because an unfinished author block is a to-do rather than a
        # broken contract, and the stage policy defers it until the manuscript exists.
        reports.append(validate(authors, "authors", authors_path, code="authors-incomplete"))

    return Project(root, paper, authors), merge_all(reports)
