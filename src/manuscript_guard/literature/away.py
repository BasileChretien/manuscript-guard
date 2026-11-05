"""The recorded copies of cited works that are kept out of git and not on this computer.

A new project keeps `literature/sources/` out of git and `literature/sources.yaml`, the record
of what was stored there, in it (Basile, 2026-10-20, confirmed 2026-11-05). On a fresh clone
or in CI the copies are then missing for a reason that is not a fault, and each reader of a
copy says so rather than failing: the ledger, an earlier output's values, passages, a methods
review's passages, prose quotations, text recycling and the checker page.

A copy counts as away only where all of these hold (Basile, 2026-11-05): the record lists it,
it is not on this computer, `paper.yaml` does not say the copies are committed
(`literature: {sources_in_git: true}`), and git says its path is ignored. A tracked path is
never ignored, so a project that commits its copies, as one made before this change does,
still fails a deleted copy; so does one where git cannot be asked, or that is not a git
repository. Git is asked once for a loaded project, with every absent recorded path on its
standard input.
"""

from __future__ import annotations

import os
import subprocess
import weakref
from dataclasses import dataclass, field

from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.contracts.project import Project
from manuscript_guard.literature.copies import FOLDER, read_record, recorded_name


@dataclass(frozen=True)
class Away:
    """The names under `literature/sources/` that are recorded, ignored by git and absent,
    each with the work it is a copy of."""

    works: dict[str, str] = field(default_factory=dict)
    #: Where the record says each came from (its `from`): `sync-sources` takes Zotero's copy
    #: again, a folder's with `--from`, and never writes into the name of the author's own,
    #: which comes back from whoever saved it.
    taken_from: dict[str, str] = field(default_factory=dict)

    def holds(self, source_file: str) -> bool:
        """Whether a ledger's `source_file`, relative to `literature/`, is a copy away."""
        return recorded_name(source_file) in self.works

    def source_of(self, source_file: str) -> str | None:
        """Where the record says a copy away came from, by a ledger's `source_file`."""
        return self.taken_from.get(recorded_name(source_file) or "")

    @property
    def keys(self) -> frozenset[str]:
        """The works with a copy away."""
        return frozenset(self.works.values())

    def of(self, citekey: str) -> list[str]:
        """The names away of the copies of work `citekey`, in order."""
        return sorted(name for name, key in self.works.items() if key == citekey)


NOTHING = Away()

#: What `git check-ignore` is given to answer in, as `gates/custodian._git` gives git.
_ENVIRONMENT = {"LC_ALL": "C", "LANGUAGE": "C"}

_SEEN: dict[int, tuple[weakref.ref, Away]] = {}


def away(project: Project) -> Away:
    """The copies away for this project, git asked once for each loaded project."""
    held = _SEEN.get(id(project))
    if held is not None and held[0]() is project:
        return held[1]
    found = kept_away(project)
    number = id(project)
    ref = weakref.ref(project, lambda _gone: _SEEN.pop(number, None))
    _SEEN[number] = (ref, found)
    return found


def kept_away(project: Project) -> Away:
    """The copies away, git asked now: for `sync-sources`, which writes the record again."""
    if project.sources_in_git:
        return NOTHING
    try:
        record = read_record(project)
    except (ContractError, OSError):
        # A record that is not one vouches for no copy: `literature-source-missing` says so
        # in its hint (`recorded_names`).
        return NOTHING
    folder = project.path("literature") / FOLDER
    absent = {name: str(entry["key"]) for name, entry in record.items()
              if not (folder / name).exists()}  # fmt: skip
    if not absent:
        return NOTHING
    paths = {}
    for name in absent:
        try:
            paths[(folder / name).relative_to(project.root).as_posix()] = name
        except ValueError:  # `paths:` can put the literature outside the project
            continue
    ignored = ignored_by_git(project, list(paths))
    works = {paths[path]: absent[paths[path]] for path in sorted(paths) if path in ignored}
    return Away(works, {name: str(record[name]["from"]) for name in works})


def ignored_by_git(project: Project, paths: list[str]) -> frozenset[str]:
    """Those of `paths`, relative to the project's root, that git ignores; none where git
    cannot be asked, as a missing copy then fails as it always did."""
    from manuscript_guard.gates.custodian import GIT_SECONDS

    if not paths:
        return frozenset()
    try:
        asked = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "check-ignore", "--stdin", "-z"],
            cwd=project.root,
            input="".join(f"{path}\0" for path in paths),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_SECONDS,
            check=False,
            env={**os.environ, **_ENVIRONMENT},
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    # 0: some are ignored; 1: none is; anything else, git could not say.
    if asked.returncode != 0:
        return frozenset()
    return frozenset(part for part in asked.stdout.split("\0") if part)


__all__ = ["NOTHING", "Away", "away", "ignored_by_git", "kept_away"]
