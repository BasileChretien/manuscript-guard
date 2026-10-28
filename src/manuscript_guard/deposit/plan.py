"""What a reproducibility package holds and what it leaves out, decided before a byte is
written.

The package is made from a list of what may go, not from the project less what may not: a
folder of the project the list does not name is never looked in, so a file nobody thought of
stays out. What the list does name is looked at file by file:

- `analysis/`, `figures/` and, asked for, `manuscript/`: each file git tracks, where the
  project is a repository. A file beside the scripts that git was never given may be data
  kept out of it on purpose, so it is withheld and said. A link is withheld too, since what it
  points at is outside what the list names. A figure's review record names who reviewed it,
  and is withheld with the panel's records.
- `results/`: each fragment the results hold, with the digest beside it.
- `design/`: the plan, the copy of it the first results kept, the data dictionary and the
  record of the data sources, by name.
- the literature ledger and the reference list; never the stored copies of the cited works,
  which are their publishers' to distribute.
- the files at the root that pin the packages the analysis ran with, and the licence.
- each input the analysis declared, by the author's declaration only: one declared
  synthetic, or listed in `paper.yaml`'s `package.share`. One declared restricted never goes,
  and listing it is refused. Every other input is withheld, and listed with its size and
  digest and how to request it.

The data custodian's rules are applied to what would go: a count below the minimum anywhere
in a fragment refuses the package until the custodian signs it off (`counts.py`), and where
the custodian restricts sending, the package is built only once the custodian has signed off
its list of files and their digests, as it stands.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import subprocess
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.paths import lockfiles
from manuscript_guard.pointers import pointer_at
from manuscript_guard.sign_offs import Signable, digest_of, settle
from manuscript_guard.verify import _is_junction

from .counts import GATE, ROLE, settled_small_counts

DEPOSIT = f"{GATE}/custodian/deposit"

#: The files of `design/` a deposit carries, by name: the plan, the copy of it the first
#: results kept, the data dictionary, and the record of where the data come from. Nothing
#: else of the folder, so the stored copies of the custodians' own pages stay out.
DESIGN_FILES = ("plan.md", "plan.frozen.yaml", "data_dictionary.yaml", "data_sources.yaml")
LITERATURE_FILES = ("ledger.yaml", "references.bib")
#: Withheld by name: the supporting passages (#374) hold the manuscript's own sentences, word
#: for word, and the names of those who judged them (the last round of #388).
WITHHELD_LITERATURE = {"passages.yaml": "the manuscript's own sentences, and who judged "
                                        "their passages"}  # fmt: skip
#: What a project's licence file is called, in the order they are looked for.
LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "LICENCE.txt",
                 "COPYING")  # fmt: skip
#: Files beside the lockfiles that say what the analysis needs.
ENVIRONMENT_FILES = ("pyproject.toml", "DESCRIPTION")
#: What a run or an editor leaves, never anyone's work.
JUNK_DIRECTORIES = frozenset({"__pycache__", ".ipynb_checkpoints", ".Rproj.user",
                              ".pytest_cache", ".mypy_cache", ".ruff_cache"})  # fmt: skip
JUNK_FILES = frozenset({".Rhistory", ".RData", ".DS_Store", "Thumbs.db", "desktop.ini"})
JUNK_SUFFIXES = (".pyc", ".pyo")
REVIEW_RECORD = ".review.yaml"
#: Why an input that is itself a results file of the project goes in: as the results it is.
RESULTS_INPUT = "a results file of this project, deposited with the rest"
#: Why an input that is one of `DESIGN_FILES` goes in: as the record it is, which the package
#: takes whoever reads it. The data checks read the data dictionary, and it is no data.
DESIGN_INPUT = "the analysis plan or its record, deposited with the rest"
#: The files a package writes of its own, at its root.
WRITTEN = ("README.md", "CITATION.cff", "BOUND.md", "INPUTS.md", "paper.yaml", "MANIFEST.yaml",
           "SHA256SUMS", ".zenodo.json", "MODELS.md", "RELATIONS.md",
           "ro-crate-metadata.json", "ro-crate-preview.html", "index.html")  # fmt: skip
#: What a package describes itself with besides CITATION.cff, by the option that asks for it:
#: `--citation` adds .zenodo.json, `--ro-crate` the crate, with the citation files, and
#: `--companion` the crate's preview page and its copy index.html, with the crate.
KINDS = ("", "citation", "ro-crate", "companion")
GIT_SECONDS = 30


class PackageError(Exception):
    """The package could not be planned or written at all."""


@dataclass(frozen=True)
class Entry:
    """A file of the package: where it goes, what it is copied from or holds, its digest."""

    path: str
    why: str
    sha256: str
    size: int
    source: Path | None = None
    data: bytes | None = None


@dataclass(frozen=True)
class Withheld:
    path: str
    why: str


@dataclass(frozen=True)
class Input:
    """A file the analysis declared it read, and whether the package carries it."""

    path: str
    sha256: str
    size: int | None
    read_by: tuple[str, ...]
    included: bool
    why: str


@dataclass(frozen=True)
class Plan:
    name: str
    entries: tuple[Entry, ...]
    withheld: tuple[Withheld, ...]
    inputs: tuple[Input, ...]
    report: Report
    signables: tuple[Signable, ...]
    with_manuscript: bool = False
    #: "", "citation", "ro-crate" or "companion": what the package describes itself with
    #: (`KINDS`).
    kind: str = ""
    #: The pandoc the companion page was written with, as it names itself; MANIFEST.yaml says
    #: it, since the page's bytes depend on it.
    pandoc: str | None = None


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copied(path: Path, at: str, why: str) -> Entry:
    return Entry(at, why, _digest(path), path.stat().st_size, source=path)


def generated(at: str, text: str, why: str) -> Entry:
    data = text.encode("utf-8")
    return Entry(at, why, hashlib.sha256(data).hexdigest(), len(data), data=data)


def name_of(project: Project) -> str:
    """The package's folder name, from the paper's short title: letters and digits only."""
    title = str(project.paper.get("short_title") or project.paper.get("title") or "")
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:60].strip("-")
    return f"{slug}-package" if slug else "package"


#: The program asked which files are tracked.
GIT = "git"


def _ask_git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    """git in the project, in English so that its words can be read, or None where it could
    not be run or did not answer in time."""
    try:
        return subprocess.run(
            [GIT, "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", *args],
            cwd=root, capture_output=True, encoding="utf-8", errors="replace",
            timeout=GIT_SECONDS, check=False, env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"},
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git(root: Path, *args: str) -> str | None:
    done = _ask_git(root, *args)
    return done.stdout if done is not None and done.returncode == 0 else None


def repository(root: Path) -> bool | None:
    """Whether git takes the project for part of a repository: True, False where git says it
    is not one (a `.git` beyond a mount or a ceiling is none), None where git could not say,
    not installed, refusing the folder as of dubious ownership, or out of time."""
    done = _ask_git(root, "rev-parse", "--is-inside-work-tree")
    if done is None:
        return None
    if done.returncode == 0:
        return True
    # Only git's word for none: "not a git repository: <gitdir>" is a `.git` file whose
    # repository has gone, a moved checkout or a pruned worktree (the last fix round of #388).
    return False if "not a git repository (or any" in done.stderr.lower() else None


def tracked_files(root: Path) -> set[str] | None:
    """The files git tracks under `root`, relative to it and in the case the system compares
    names in, or None where it is no repository or git could not be asked: then every file of
    the named folders is taken."""
    if repository(root) is not True:
        return None
    listed = _git(root, "ls-files", "-z")
    return None if listed is None else {os.path.normcase(n) for n in listed.split("\0") if n}


def in_a_repository(root: Path) -> bool:
    """Whether a `.git` folder or file is at the project's root or above it."""
    return any((place / ".git").exists() for place in (root, *root.parents))


def git_unanswered(root: Path, tracked: set[str] | None) -> bool:
    """Whether the project is in a repository git could not answer for: git took it for one
    and could not list its files, or could not say, with a `.git` at the root or above."""
    if tracked is not None:
        return False
    found = repository(root)
    return found is True or (found is None and in_a_repository(root))


def _identity(path: Path) -> tuple[int, int] | None:
    """The file a path leads to, as the system tells files apart, or None where it cannot say:
    a file system that gives every file the number 0, as FAT does, tells none apart."""
    try:
        found = os.stat(path)
    except OSError:
        return None
    return (found.st_dev, found.st_ino) if found.st_ino else None


def licence_file(project: Project) -> Path | None:
    """The project's licence file, or the repository's where the project is a folder of one."""
    places = [project.root]
    top = _git(project.root, "rev-parse", "--show-toplevel")
    if top and Path(top.strip()).resolve() != project.root.resolve():
        places.append(Path(top.strip()))
    for place in places:
        for name in LICENCE_FILES:
            if (place / name).is_file():
                return place / name
    return None


def settings(project: Project) -> dict:
    found = project.setting("package")
    return found if isinstance(found, dict) else {}


def _walk(folder: Path) -> Iterator[tuple[Path, str | None]]:
    """Each file under `folder`, in order, with why it is withheld where a link withholds it."""
    if not folder.is_dir():
        return
    for current, directories, files in os.walk(folder):
        kept = []
        for name in sorted(directories):
            path = Path(current) / name
            if name in JUNK_DIRECTORIES:
                continue
            if path.is_symlink() or _is_junction(str(path)):
                yield path, "a link, whose target is outside what a package holds"
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(files):
            if name in JUNK_FILES or name.endswith(JUNK_SUFFIXES):
                continue
            path = Path(current) / name
            yield path, ("a link, whose target is outside what a package holds"
                         if path.is_symlink() else None)  # fmt: skip


class _Collector:
    """The entries and the withheld files, as the rules decide each."""

    def __init__(self, project: Project, tracked: set[str] | None, skip: set[str]) -> None:
        self.root = project.root
        self.tracked = tracked
        # A declared input is held out by its name, in the case the system compares names
        # in, and by the file it is: another name for it, a hard link or the name in another
        # case where the system ignores case, is the input all the same (round 1 of #388).
        self.skip = {os.path.normcase(path) for path in skip}
        self.skip_files = {found for path in skip if inside(path)
                           and (found := _identity(project.root / path))}  # fmt: skip
        self.entries: dict[str, Entry] = {}
        self.withheld: list[Withheld] = []
        self.refused: list[Finding] = []

    def at(self, path: Path) -> str | None:
        """Where the file goes in the package: where it is in the project, read from its
        name and not from where a link leads."""
        try:
            return Path(os.path.normpath(path)).relative_to(self.root).as_posix()
        except ValueError:
            self.refused.append(Finding(GATE, "package-outside", f"{path} is outside the "
                                        "project, and a package holds the project's files "
                                        "where they are in it", path=path))  # fmt: skip
            return None

    def held_out(self, path: Path, at: str) -> bool:
        """Whether the file is a declared input, which goes by the input's rule only."""
        return os.path.normcase(at) in self.skip or _identity(path) in self.skip_files

    def walkable(self, folder: Path, setting: str) -> bool:
        """Whether a folder `paths:` names may be walked: one that is the project itself
        would take every file of it (round 1 of #388), and one outside it none of its own."""
        here = Path(os.path.normpath(folder))
        led, root = here.resolve(), self.root.resolve()
        if led != root and not led.is_relative_to(root):
            self.refused.append(Finding(GATE, "package-outside", f"paths.{setting} leads to "
                                        f"{led}, outside the project", path=self.root /
                                        "paper.yaml", hint=f"keep the {setting} in a folder "
                                        "of the project's own"))  # fmt: skip
            return False
        if here == Path(os.path.normpath(self.root)) or led == root:
            self.refused.append(Finding(GATE, "package-folder-is-root", f"paths.{setting} "
                                        "is the project itself, and a package takes the "
                                        "files of that folder whole", path=self.root /
                                        "paper.yaml", hint=f"keep the {setting} in a folder "
                                        "of its own"))  # fmt: skip
            return False
        return self.at(here) is not None

    def take(self, path: Path, why: str, *, if_tracked: bool = True) -> None:
        at = self.at(path)
        if at is None or at in self.entries or self.held_out(path, at):
            return
        if if_tracked and self.tracked is not None and os.path.normcase(at) not in self.tracked:
            self.withheld.append(Withheld(at, "git does not track it"))
            return
        self.entries[at] = copied(path, at, why)

    def folder(self, folder: Path, why: str, setting: str, *, notes: bool = False) -> None:
        if not folder.is_dir() or not self.walkable(folder, setting):
            return
        for path, linked in _walk(folder):
            at = self.at(path)
            if at is None or self.held_out(path, at):
                continue
            if linked:
                self.withheld.append(Withheld(at, linked))
            elif notes and any(part.startswith(("_", ".")) for part in
                               path.relative_to(folder).parts[:-1]):  # fmt: skip
                self.withheld.append(Withheld(at, "in a folder of notes, whose name begins "
                                              "with _ or ."))  # fmt: skip
            elif path.name.endswith(REVIEW_RECORD):
                self.withheld.append(Withheld(at, "a review record, which names who reviewed"))
            else:
                self.take(path, why)


def inside(path: str) -> bool:
    """Whether a path written in a record names a place inside the project: relative, with no
    step above where it starts, on any system."""
    pure = PurePosixPath(path.replace("\\", "/"))
    return bool(path) and not pure.is_absolute() and not PureWindowsPath(path).drive \
        and ".." not in pure.parts  # fmt: skip


def canonical(path: str) -> str:
    """A path a record declares, in one spelling: forward slashes and no `.` step, so that
    `./data/raw.csv` and `data\\raw.csv` are `data/raw.csv` (round 2 of #388)."""
    return posixpath.normpath(str(path).replace("\\", "/"))


def _key(path: str) -> str:
    """What two declared paths are compared by: one spelling, in the case the system
    compares names in."""
    return os.path.normcase(canonical(path))


def _declared(results: Results) -> dict[str, dict]:
    """Each input the runs declared, by its path in one spelling: the scripts that read it,
    whether any run calls it restricted, and whether every run calls it synthetic."""
    declared: dict[str, dict] = {}
    for fragment in results.fragments:
        for record in fragment.inputs:
            if not isinstance(record, dict) or not record.get("path"):
                continue
            seen = declared.setdefault(_key(record["path"]), {
                "path": canonical(record["path"]), "read_by": [], "synthetic": True,
                "restricted": False, "outside": False, "record": record})  # fmt: skip
            # As written: "data/../x.csv" spelt one way is "x.csv", and is another file where
            # `data` is a link (the fix round of #388).
            seen["outside"] |= not inside(str(record["path"]))
            seen["read_by"].append(fragment.generated_by)
            seen["restricted"] |= bool(record.get("restricted"))
            # Synthetic only where every run that read it says so.
            seen["synthetic"] &= bool(record.get("synthetic"))
    return declared


def _share_findings(project: Project, declared: dict[str, dict], shared: dict[str, str]) -> list:
    """`package.share` naming an input no run declared, or one declared restricted."""
    refused = []
    for key, path in shared.items():
        if key not in declared:
            refused.append(Finding(GATE, "package-share-unknown", f"package.share lists "
                                   f"{path}, which no analysis declares it read",
                                   path=project.root / "paper.yaml",
                                   hint="list an input as its path in the results' provenance "
                                   "says it, or take it out of the list"))  # fmt: skip
        elif declared[key]["restricted"]:
            refused.append(Finding(GATE, "package-share-restricted", f"package.share lists "
                                   f"{path}, which the analysis declares restricted",
                                   path=project.root / "paper.yaml",
                                   hint="a restricted input stays in the custodian's hands; "
                                   "take it out of package.share"))  # fmt: skip
    return refused


def _taken_as_record(file: Path, key: str, tracked: set[str] | None) -> bool:
    """Whether a declared input is taken as the design record: where the records' loop takes
    it, on this computer and committed where the project is a repository (round on c4c78959),
    and not a link, which the loop would follow and is refused here. Otherwise the input goes
    by the inputs' rule, as before. An undeclared record that is a link is still followed."""
    return file.is_file() and not file.is_symlink() and (tracked is None or key in tracked)


def _inputs(project: Project, results: Results,
            tracked: set[str] | None = None) -> tuple[list[Input], list[Finding]]:  # fmt: skip
    """Each declared input, and whether the author's declarations let it go."""
    declared = _declared(results)
    shared = {_key(path): str(path) for path in settings(project).get("share") or []}
    refused = _share_findings(project, declared, shared)
    out = []
    produced = {_key(f.path.relative_to(project.root).as_posix()) for f in results.fragments}
    records = {_key(f"design/{name}") for name in DESIGN_FILES}
    for key, seen in sorted(declared.items(), key=lambda item: item[1]["path"]):
        path, record = seen["path"], seen["record"]
        digest = str(record.get("raw_sha256") or record.get("sha256") or "")
        size = record.get("bytes") if isinstance(record.get("bytes"), int) else None
        read_by = tuple(sorted(set(seen["read_by"])))
        file = project.root / path
        if seen["outside"] or not inside(path):
            # A fragment is a file anyone can write: a path out of the project would be read
            # from outside it and written outside the package.
            included, why = False, "a path outside the project"
            refused.append(Finding(GATE, "package-outside", f"a results file declares the "
                                   f"input {path}, which is not a path inside the project",
                                   path=project.root, hint="an input is declared by its "
                                   "path from the project's root"))  # fmt: skip
        elif seen["restricted"]:
            # Before a results file is taken as results: a declaration that it is restricted
            # is the author's, and holds (round 2 of #388).
            included, why = False, "declared restricted"
        elif key in produced:
            included, why = True, RESULTS_INPUT
        elif key in records and _taken_as_record(file, key, tracked):
            included, why = True, DESIGN_INPUT
        elif not (seen["synthetic"] or key in shared):
            included, why = False, "not declared shareable"
        elif not file.is_file():
            included, why = False, "not on this computer"
        elif pointer_at(file) is not None:
            included, why = False, "not fetched: a Git LFS or git-annex pointer is at its path"
        else:
            included = True
            why = "declared synthetic" if seen["synthetic"] else "listed in package.share"
        out.append(Input(path, digest, size, read_by, included, why))
    return _held_to_the_withheld(project, out), refused


def _held_to_the_withheld(project: Project, inputs: list[Input]) -> list[Input]:
    """Each input that goes, held to the files of those that do not: another name for a
    withheld file, a hard link or its name in another case on a system that ignores case, is
    withheld with it (the fix round of #388)."""
    kept = {found for i in inputs if not i.included and inside(i.path)
            and (found := _identity(project.root / i.path))}  # fmt: skip
    return [
        replace(i, included=False, why="the same file as an input that is withheld")
        if i.included and _identity(project.root / i.path) in kept
        else i
        for i in inputs
    ]


def deposit_id(with_manuscript: bool, kind: str = "") -> str:
    """The id the custodian signs a package off by: a package with the manuscript is
    another package, and so is one that describes itself with other files (`KINDS`)."""
    said = f"{DEPOSIT}-with-manuscript" if with_manuscript else DEPOSIT
    return f"{said}-{kind}" if kind else said


def _deposit_signable(
    project: Project, entries: list[Entry], with_manuscript: bool, kind: str = ""
) -> Signable | None:
    from manuscript_guard.panel.custodian import restricts_sending

    if not restricts_sending(project):
        return None
    results = [entry.path for entry in entries if entry.path.startswith("results/")]
    finding = Finding(
        GATE, "package-not-authorised",
        f"the data custodian restricts where the results may be sent, and this package "
        f"deposits {len(entries)} files, {len(results)} of them results",
        path=project.root / "paper.yaml",
    )  # fmt: skip
    digest = digest_of("deposit", sorted((entry.path, entry.sha256) for entry in entries))
    return Signable(ROLE, deposit_id(with_manuscript, kind), digest, (finding,))


def _licence_findings(project: Project, licence: Path | None) -> list[Finding]:
    found = []
    if licence is None:
        found.append(Finding(GATE, "package-licence-missing", "the project has no licence "
                             "file, and a deposit without one may not be reused",
                             path=project.root, hint="add the licence you choose as LICENSE "
                             "at the project's root; the tool does not choose one"))  # fmt: skip
    if not settings(project).get("licence"):
        found.append(Finding(GATE, "package-licence-undeclared", "paper.yaml declares no "
                             "package.licence, which CITATION.cff names the deposit's licence "
                             "by", path=project.root / "paper.yaml", hint="its SPDX "
                             "identifier: `licence: MIT`, or `licence: [MIT, CC-BY-4.0]`"))
    return found


def plan_package(project: Project, results: Results, *, with_manuscript: bool = False,
                 citation: bool = False, ro_crate: bool = False,
                 companion: bool = False) -> Plan:  # fmt: skip
    """Everything the package would hold and leave out, and what stops it. `citation` adds
    .zenodo.json beside CITATION.cff; `ro_crate` adds ro-crate-metadata.json, RELATIONS.md
    and, where the analysis fitted models, MODELS.md, and implies `citation`; `companion`
    adds the crate's preview page, ro-crate-preview.html, and index.html, its copy, and
    implies `ro_crate`. The page is written with pandoc, and is refused without it."""
    from .texts import generated_entries

    kind = ("companion" if companion else "ro-crate" if ro_crate else "citation" if citation
            else "")  # fmt: skip
    pandoc = None
    if companion:
        from .prose import pandoc_version

        pandoc = pandoc_version()
        if pandoc is None:
            raise PackageError("--companion writes the page's prose with pandoc, which is not "
                               "on PATH; install it (https://pandoc.org/installing.html), or "
                               "package without --companion")  # fmt: skip

    if not results.fragments:
        raise PackageError(f"no results in {project.path('results')}: there is nothing to "
                           "package; run the analysis first")  # fmt: skip
    tracked = tracked_files(project.root)
    inputs, refused = _inputs(project, results, tracked)
    collect = _Collector(project, tracked, {i.path for i in inputs
                                            if i.why not in (RESULTS_INPUT, DESIGN_INPUT)})
    licence = _collect(collect, project, results, inputs, with_manuscript)
    findings = refused + collect.refused + _licence_findings(project, licence)
    if git_unanswered(project.root, tracked):
        findings.append(Finding(GATE, "package-git-unanswered", "the project is in a git "
                                "repository, and git could not say which files it tracks, so "
                                "what is kept out of git cannot be kept out of the package",
                                path=project.root, hint="run `git status` there: git may not "
                                "be on PATH, or may refuse the folder as of dubious "
                                "ownership"))  # fmt: skip
    findings += _notes(project, inputs, kind) + _described(project, results, kind)
    entries = sorted(collect.entries.values(), key=lambda entry: entry.path)
    findings += _names_taken(project, entries)
    entries += generated_entries(project, results, inputs, entries, with_manuscript,
                                 in_git=tracked is not None, kind=kind)
    entries.sort(key=lambda entry: entry.path)
    signables: list[Signable] = []
    produced = {_key(f.path.relative_to(project.root).as_posix()):
                f.path.relative_to(project.root).as_posix() for f in results.fragments}  # fmt: skip
    withheld_results = frozenset(produced[_key(i.path)] for i in inputs
                                 if not i.included and _key(i.path) in produced)  # fmt: skip
    small, settled = settled_small_counts(project, results, withheld_results)
    if small is not None:
        signables.append(small)
        findings += settled
    deposit = _deposit_signable(project, entries, with_manuscript, kind)
    if deposit is not None:
        signables.append(deposit)
        findings += settle(project, deposit)
    away = [i for i in inputs if not i.included]
    report = Report(tuple(findings)).with_counts(files_packaged=len(entries),
                                                 inputs_withheld=len(away))  # fmt: skip
    withheld = collect.withheld + [Withheld(i.path, i.why) for i in away]
    return Plan(name_of(project), tuple(entries), tuple(sorted(withheld, key=lambda w: w.path)),
                tuple(inputs), report, tuple(signables), with_manuscript, kind,
                pandoc)  # fmt: skip


def _collect(collect: _Collector, project: Project, results: Results, inputs: list[Input],
             with_manuscript: bool) -> Path | None:  # fmt: skip
    """Every file the rules let go, into `collect`; the licence file, where there is one."""
    for found in inputs:
        if found.included and found.why not in (RESULTS_INPUT, DESIGN_INPUT):
            collect.entries[found.path] = copied(project.root / found.path, found.path,
                                                 f"an input the analysis read, {found.why}")
    for fragment in sorted(results.fragments, key=lambda f: f.path.name):
        at = collect.at(fragment.path)
        if at is None or collect.held_out(fragment.path, at):
            continue  # declared restricted by a script that read it
        collect.take(fragment.path, "a results file", if_tracked=False)
        sidecar = fragment.path.with_name(fragment.path.name + ".sha256")
        if sidecar.is_file():
            collect.take(sidecar, "the digest of a results file", if_tracked=False)
    collect.folder(project.path("analysis"), "an analysis script", "analysis")
    collect.folder(project.path("figures"), "a figure, its script or its records", "figures")
    for name in DESIGN_FILES:
        if (project.root / "design" / name).is_file():
            collect.take(project.root / "design" / name, "the analysis plan or its record")
    for name in LITERATURE_FILES:
        if (project.path("literature") / name).is_file():
            collect.take(project.path("literature") / name, "the literature ledger or the "
                         "reference list")  # fmt: skip
    for name, why in WITHHELD_LITERATURE.items():
        held = project.path("literature") / name
        if held.is_file() and (at := collect.at(held)):
            collect.withheld.append(Withheld(at, why))
    sources = project.path("literature") / "sources"
    if sources.is_dir() and any(sources.iterdir()) and (at := collect.at(sources)):
        collect.withheld.append(Withheld(f"{at}/", "stored copies of cited works, their "
                                         "publishers' to distribute"))  # fmt: skip
    for path in lockfiles(project.root) + [project.root / name for name in ENVIRONMENT_FILES]:
        if path.is_file():
            collect.take(path, "what the analysis ran with")
    licence = licence_file(project)
    if licence is not None:
        collect.entries[licence.name] = copied(licence, licence.name, "the licence")
    if with_manuscript:
        collect.folder(project.path("manuscript"), "the manuscript", "manuscript",
                       notes=True)
    return licence


def _names_taken(project: Project, entries: list[Entry]) -> list[Finding]:
    """A file collected at a name the package writes of its own, or two at one name in the
    case a system that ignores case reads them: one would be written over the other, and
    SHA256SUMS would name both."""
    seen: dict[str, str] = {os.path.normcase(name).casefold(): name for name in WRITTEN}
    found = []
    for entry in entries:
        key = entry.path.casefold()
        if key in seen:
            found.append(Finding(GATE, "package-name-taken", f"{entry.path} ({entry.why}) "
                                 f"would be written at {seen[key]}, which the package holds "
                                 "already", path=project.root / entry.path, hint="move or "
                                 "rename the file in the project"))  # fmt: skip
        seen.setdefault(key, entry.path)
    return found


def _notes(project: Project, inputs: list[Input], kind: str = "") -> list[Finding]:
    """A withheld input with no way to obtain it, no lockfile, a part of a LaTeX manuscript
    whose bindings BOUND.md cannot place, and licences a Zenodo record cannot take."""
    from .bound import latex_unread
    from .metadata import licence_note

    found = []
    away = sum(not i.included for i in inputs)
    if away and not settings(project).get("request"):
        found.append(Finding(GATE, "package-request-missing", f"the package withholds {away} "
                             "input(s), and paper.yaml says nothing of how to obtain them",
                             path=project.root / "paper.yaml", hint="say it in "
                             "package.request: who to apply to, and on what terms"))  # fmt: skip
    if not lockfiles(project.root):
        found.append(Finding(GATE, "package-no-lockfile", "the project pins no packages (no "
                             "requirements file or lockfile at its root), so the package says "
                             "only the language versions the results were written with",
                             severity=WARN, path=project.root))  # fmt: skip
    unread = latex_unread(project)
    if unread is not None:
        found.append(Finding(GATE, "package-bound-not-read", "BOUND.md does not place every "
                             f"binding of the LaTeX manuscript: {unread}", severity=WARN,
                             hint="put the part right, as `check` says of it, and package "
                             "again"))  # fmt: skip
    note = licence_note(project) if kind else None
    if note is not None:
        found.append(Finding(GATE, "package-zenodo-licence", note, severity=WARN,
                             path=project.root / "paper.yaml"))  # fmt: skip
    return found


def _described(project: Project, results: Results, kind: str) -> list[Finding]:
    """What refuses the files a package describes itself with: a Zenodo record with no one
    to name as its creators, and a crate with no day to give as published, which RO-Crate
    1.1 requires of its root."""
    from .crate import date_published
    from .metadata import creators_note

    found = []
    nobody = creators_note(project) if kind else None
    if nobody is not None:
        found.append(Finding(GATE, "package-no-creators", nobody, path=project.root /
                             "authors.yaml", hint="list the authors, each with a given or a "
                             "family name, in authors.yaml; the tool names no one it is not "
                             "told of"))  # fmt: skip
    if kind == "ro-crate" and date_published(project, results) is None:
        found.append(Finding(GATE, "package-crate-undated", "an RO-Crate gives the day it was "
                             "published, and paper.yaml gives no package.date and no results "
                             "file records a date that can be read", path=project.root /
                             "paper.yaml", hint="write the day the deposit is published as "
                             "package.date, `date: 2026-11-02`; the tool reads no clock"))
    said = settings(project).get("date")
    if kind and said and not _a_day(str(said)):
        found.append(Finding(GATE, "package-date-invalid", f"package.date is {said}, which is "
                             "no day of the calendar, and the crate and .zenodo.json would "
                             "give it as the day the deposit is published", path=project.root /
                             "paper.yaml", hint="write the day as YYYY-MM-DD, one that "
                             "exists: `date: 2026-02-28`"))  # fmt: skip
    return found


def _a_day(text: str) -> bool:
    """Whether `text` is a day of the calendar written YYYY-MM-DD: the schema's pattern lets
    2026-02-30 through."""
    from datetime import date

    try:
        return len(text) == 10 and date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def package_signables(project: Project, results: Results) -> list[Signable]:
    """What the data custodian may sign off of the package as it stands, with the manuscript
    and without it."""
    if not results.fragments:
        return []
    found: dict[str, Signable] = {}
    for with_manuscript in (False, True):
        for kind in KINDS:
            try:
                planned = plan_package(project, results, with_manuscript=with_manuscript,
                                       citation=kind == "citation", ro_crate=kind == "ro-crate",
                                       companion=kind == "companion")  # fmt: skip
            except PackageError:
                if kind != "companion":
                    raise
                continue  # no pandoc, or a page that cannot be made: nothing to sign
            for signable in planned.signables:
                found.setdefault(signable.id, signable)
    return list(found.values())


__all__ = ["DEPOSIT", "KINDS", "Entry", "Input", "PackageError", "Plan", "Withheld",
           "deposit_id", "package_signables", "plan_package"]  # fmt: skip
