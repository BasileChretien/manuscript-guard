"""What the folder already says, before a question is asked: `read_folder`.

A question is open only where the folder does not answer it: a `paper.yaml` that declares an
English is not asked its English again, an `analysis/` of R scripts is not asked its
language, a filled `authors.yaml` is not asked its authors. What is read here is read from
the files as they are, every call, with nothing kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: The suffixes of the analysis scripts, by the emitter that writes their results.
LANGUAGES = {".py": "python", ".ipynb": "python", ".r": "r", ".rmd": "r", ".qmd": "r"}


class SetupRefused(Exception):
    """Why `setup` cannot work on this folder, in a sentence for the author."""


@dataclass(frozen=True)
class Folder:
    """The folder a project is set up in, as its files stand."""

    root: Path
    #: `paper.yaml`'s settings, or None where the folder holds none: a new project.
    paper: dict | None
    #: `authors.yaml` is missing, or still the placeholder `init` writes.
    authors_blank: bool
    #: The papers in the folder itself, by name: a Word paper may be brought in.
    candidates: tuple[str, ...]
    #: The languages the analysis scripts are written in, as their suffixes say.
    languages: tuple[str, ...]
    #: Results have been written already.
    has_results: bool
    #: The git repository the folder is in, or None.
    repository: Path | None
    #: The repository already has the workflow `init --github-actions` writes.
    workflow: bool
    #: The journals `set target_journal` takes here: the profiles and the shortlist's.
    profiles: tuple[str, ...]
    #: The files that say where the data are, or that earlier work is recorded.
    vault: bool
    data_sources: bool
    related: bool

    @property
    def is_project(self) -> bool:
        return self.paper is not None

    def setting(self, key: str) -> Any:
        return (self.paper or {}).get(key)


def _yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SetupRefused(f"{path.name} cannot be read ({exc}); put it right first, as "
                           "`manuscript-guard check` says") from exc  # fmt: skip


def _outer_project(folder: Path) -> Path | None:
    for above in folder.parents:
        if (above / "paper.yaml").is_file():
            return above
    return None


def _authors_blank(folder: Path) -> bool:
    from manuscript_guard.scaffold import AUTHORS

    path = folder / "authors.yaml"
    if not path.is_file():
        return True
    return _yaml(path) == yaml.safe_load(AUTHORS)


def _languages(folder: Path, paper: dict | None) -> tuple[str, ...]:
    paths = (paper or {}).get("paths")
    name = paths.get("analysis", "analysis") if isinstance(paths, dict) else "analysis"
    analysis = folder / str(name)
    if not analysis.is_dir():
        return ()
    found = {LANGUAGES[path.suffix.lower()] for path in analysis.rglob("*")
             if path.is_file() and path.suffix.lower() in LANGUAGES}  # fmt: skip
    return tuple(sorted(found))


def read_folder(path: Path) -> Folder:
    """The folder at `path`, a project or the place one will be made; `SetupRefused` where
    it is inside another project, or a file it reads cannot be read."""
    from manuscript_guard.github_workflow import WORKFLOW, repository_root
    from manuscript_guard.guide.reading import _candidates
    from manuscript_guard.paper_edit import journals

    folder = Path(path).resolve()
    if not folder.is_dir():
        raise SetupRefused(f"{path} is not a folder")
    paper_file = folder / "paper.yaml"
    paper = None
    if paper_file.is_file():
        read = _yaml(paper_file)
        if not isinstance(read, dict):
            raise SetupRefused("paper.yaml holds no settings; put it right first, as "
                               "`manuscript-guard check` says")  # fmt: skip
        paper = read
    else:
        outer = _outer_project(folder)
        if outer is not None:
            raise SetupRefused(f"this folder is inside the project at {outer}, whose "
                               "paper.yaml is above it; set up that project, from its own "
                               "folder")  # fmt: skip
    repository = repository_root(folder)
    results = folder / "results"
    return Folder(
        root=folder,
        paper=paper,
        authors_blank=_authors_blank(folder),
        candidates=_candidates(folder),
        languages=_languages(folder, paper),
        has_results=results.is_dir() and any(results.glob("*.json")),
        repository=repository,
        workflow=((repository or folder) / WORKFLOW).is_file(),
        profiles=tuple(journals(folder)),
        vault=(folder / "design" / "vault.yaml").is_file(),
        data_sources=(folder / "design" / "data_sources.yaml").is_file(),
        related=(folder / "literature" / "related.yaml").is_file(),
    )
