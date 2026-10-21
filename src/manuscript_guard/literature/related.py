"""The earlier outputs of the same study or the same data, and the copies taken of them.

A paper written from a database extraction that an abstract, a preprint or an earlier
article already used is held to what those said. `literature/related.yaml` names each
earlier output, what this paper shares with it, and how it is to be compared: through a
copy of its own manuscript-guard project, where an author of this paper can give one, or
through values read from its text with the sentence that states each.

The copy is taken once, by `manuscript-guard related --take`, from a path and a revision the
author supplies, and kept in `literature/related/<id>/` with the digest of every file it
wrote. `check` reads the copy and never the project, so that CI and a co-author's machine,
where the earlier project is not, give the answer the author's does. The pattern is the
lookup's: asked once, recorded, read as data.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text, validate
from manuscript_guard.contracts.project import PAPER_FILE, Project
from manuscript_guard.findings import Finding, Report

GATE = "G8"
RELATED_FILE = "related.yaml"
RELATED_DIR = "related"
SNAPSHOT_FILE = "snapshot.yaml"
SNAPSHOT_SCHEMA = "manuscript-guard/related-snapshot/1"

#: The files of an earlier project a copy holds, beside its results: the plan as it stood when
#: its results were first written, the plan, and its data dictionary.
DESIGN_FILES = ("plan.frozen.yaml", "plan.md", "data_dictionary.yaml")

#: How long git may take to answer for one file of an earlier project.
GIT_SECONDS = 60

#: A file of a copy, as its record names it: one of the two folders, and a name in it.
_COPIED = re.compile(r"^(?:results|design)/(?!\.\.?$)[^/\\]+$")


@dataclass(frozen=True)
class Pair:
    """A key of the earlier project beside this project's key for the same quantity."""

    earlier: str
    here: str
    because: str | None
    manuscript_says: str | None
    line: int | None


@dataclass(frozen=True)
class Recorded:
    """A value read from the earlier output's text or copied outputs, with its sentence."""

    here: str
    value: str
    source_file: str
    locator: str | None
    quote: str
    because: str | None
    manuscript_says: str | None
    line: int | None


@dataclass(frozen=True)
class Apart:
    """Keys both projects emit that are not the same quantity."""

    keys: str
    because: str


@dataclass(frozen=True)
class Output:
    id: str
    kind: str
    citekey: str | None
    title: str | None
    shares: tuple[str, ...]
    project: str | None
    revision: str | None
    files: tuple[str, ...]
    files_unavailable: str | None
    pairs: tuple[Pair, ...]
    not_compared: tuple[Apart, ...]
    values: tuple[Recorded, ...]
    disclosed_by: str | None
    line: int | None

    @property
    def name(self) -> str:
        """How a finding names it: its id, and its citekey or title."""
        return f"{self.id} ({self.citekey or self.title})"

    @property
    def overlaps(self) -> bool:
        """Data or study shared with authors: a publication the journal has to be told of."""
        return "authors" in self.shares and bool({"data", "study"} & set(self.shares))


@dataclass(frozen=True)
class Related:
    path: Path
    outputs: tuple[Output, ...]


def related_path(project: Project) -> Path:
    return project.path("literature") / RELATED_FILE


def snapshot_dir(project: Project, output_id: str) -> Path:
    return project.path("literature") / RELATED_DIR / output_id


def unbound(key: str) -> str:
    """A key as the analysis emits it: `results.cohort.n` is `cohort.n`."""
    return key.removeprefix("results.")


def load_related(project: Project) -> tuple[Related | None, Report]:
    """The record, or None where the project keeps none or it is not in its shape."""
    path = related_path(project)
    if not path.exists():
        return None, Report()
    document = read_structured(path)
    report = validate(document, "related", path, gate=GATE)
    if not report.ok:
        return None, report
    lines = _lines(read_text(path))
    outputs = tuple(
        _output(entry, (lines.get(("outputs", at)), lines, at))
        for at, entry in enumerate(document["outputs"])
    )
    seen: set[str] = set()
    for output in outputs:
        if output.id in seen:
            return None, report.with_findings(
                Finding(
                    gate=GATE,
                    code="related-id-repeated",
                    message=f"two earlier outputs are named {output.id!r}",
                    path=path,
                    line=output.line,
                    hint="give each its own id: its copy is kept under that name",
                )
            )
        seen.add(output.id)
    return Related(path, outputs), report


def _output(entry: dict, where: tuple[int | None, dict, int]) -> Output:
    line, lines, at = where

    def text(key: str, item: dict = entry) -> str | None:
        value = item.get(key)
        return None if value is None else str(value)

    return Output(
        id=entry["id"],
        kind=entry["kind"],
        citekey=text("citekey"),
        title=text("title"),
        shares=tuple(entry["shares"]),
        project=text("project"),
        revision=text("revision"),
        files=tuple(str(f) for f in entry.get("files", ())),
        files_unavailable=text("files_unavailable"),
        pairs=tuple(
            Pair(
                earlier=unbound(pair["earlier"]),
                here=unbound(pair["here"]),
                because=text("because", pair),
                manuscript_says=text("manuscript_says", pair),
                line=lines.get(("outputs", at, "pairs", number)),
            )
            for number, pair in enumerate(entry.get("pairs", ()))
        ),
        not_compared=tuple(
            Apart(keys=unbound(str(apart["keys"])), because=str(apart["because"]))
            for apart in entry.get("not_compared", ())
        ),
        values=tuple(
            Recorded(
                here=unbound(value["here"]),
                value=str(value["value"]),
                source_file=str(value["source_file"]),
                locator=text("locator", value),
                quote=str(value["quote"]),
                because=text("because", value),
                manuscript_says=text("manuscript_says", value),
                line=lines.get(("outputs", at, "values", number)),
            )
            for number, value in enumerate(entry.get("values", ()))
        ),
        disclosed_by=text("disclosed_by"),
        line=line,
    )


def _lines(text: str) -> dict[tuple, int]:
    """The line each output, pair and value starts on, for a finding to point at."""
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return {}
    found: dict[tuple, int] = {}
    if not isinstance(root, yaml.MappingNode):
        return found
    for key, value in root.value:
        if key.value != "outputs" or not isinstance(value, yaml.SequenceNode):
            continue
        for at, item in enumerate(value.value):
            found[("outputs", at)] = item.start_mark.line + 1
            if not isinstance(item, yaml.MappingNode):
                continue
            for name, listed in item.value:
                if name.value in ("pairs", "values") and isinstance(listed, yaml.SequenceNode):
                    for number, node in enumerate(listed.value):
                        found[("outputs", at, name.value, number)] = node.start_mark.line + 1
    return found


# ------------------------------------------------------------------------------ the copy


class TakeError(Exception):
    """The earlier project could not be copied, in a sentence for the author."""


@dataclass(frozen=True)
class Snapshot:
    """A copy as `check` reads it: where it is, what it says of itself, and the files that
    no longer have the digest it gave them, or were added beside them."""

    folder: Path
    manifest: dict
    edited: tuple[str, ...]


def read_snapshot(project: Project, output_id: str) -> tuple[Snapshot | None, str | None]:
    """The copy kept for `output_id`, or None with why where there is none to read."""
    folder = snapshot_dir(project, output_id)
    path = folder / SNAPSHOT_FILE
    if not path.exists():
        return None, None
    try:
        manifest = read_structured(path)
    except ContractError as exc:
        return None, str(exc)
    problems = validate(manifest, "related-snapshot", path).findings
    if problems:
        return None, f"{path.name}: {problems[0].message}"
    edited = []
    for name, digest in sorted(manifest["files"].items()):
        copied = folder / name
        if not copied.is_file() or _sha256(copied.read_bytes()) != digest:
            edited.append(name)
    for part in ("results", "design"):
        for copied in sorted((folder / part).glob("*")):
            if f"{part}/{copied.name}" not in manifest["files"]:
                edited.append(f"{part}/{copied.name}")
    return Snapshot(folder, manifest, tuple(edited)), None


def take(project: Project, output: Output, *, today: date | None = None) -> Path:
    """Copy the earlier project's results and design files into this project, and record
    what was copied with each file's digest. Returns the record's path."""
    if output.project is None:
        raise TakeError(f"{output.id}: no `project` names its manuscript-guard project")
    source = project.root / output.project
    if not source.is_dir():
        raise TakeError(f"{output.id}: {output.project} is not a folder")
    read = _Reader(source, output.revision)
    paper = read(PAPER_FILE)
    if paper is None:
        raise TakeError(
            f"{output.id}: {output.project} has no {PAPER_FILE}"
            + (f" at {output.revision}" if output.revision else "")
            + ", so it is not a manuscript-guard project; record its values from its "
            "outputs instead (`files:` and `values:`)"
        )
    results_dir = _results_dir(paper)
    wanted = {
        f"results/{name}": f"{results_dir}/{name}"
        for name in read.listed(results_dir)
        if name.endswith(".json") or name.endswith(".json.sha256")
    }
    if not any(name.endswith(".json") for name in wanted):
        raise TakeError(
            f"{output.id}: {output.project} has no results in {results_dir}/"
            + (f" at {output.revision}" if output.revision else "")
            + "; run its analysis, or name the revision its paper was made from"
        )
    wanted.update({f"design/{name}": f"design/{name}" for name in DESIGN_FILES})
    copied = {name: data for name, there in wanted.items() if (data := read(there)) is not None}
    stamp = (read.commit, read.uncommitted(results_dir, "design"))
    return _write(project, output, copied, stamp, today or date.today())


def _results_dir(paper: bytes) -> str:
    try:
        settings = yaml.safe_load(paper.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        settings = None
    paths = settings.get("paths") if isinstance(settings, dict) else None
    chosen = paths.get("results") if isinstance(paths, dict) else None
    return str(chosen).strip("/") if isinstance(chosen, str) and chosen.strip() else "results"


def _write(
    project: Project,
    output: Output,
    copied: dict[str, bytes],
    stamp: tuple[str | None, bool],
    today: date,
) -> Path:
    """Write the copy, replacing only what an earlier copy of this one wrote."""
    folder = snapshot_dir(project, output.id)
    record = folder / SNAPSHOT_FILE
    try:
        before = read_structured(record)
    except ContractError:
        before = None
    listed = before.get("files") if isinstance(before, dict) else None
    # Only names in the copy's own two folders: a record edited to name another file
    # deletes nothing.
    ours = {name for name in listed or () if _COPIED.match(str(name))}
    for part in ("results", "design"):
        for found in sorted((folder / part).glob("*")):
            name = f"{part}/{found.name}"
            if name not in ours:
                raise TakeError(
                    f"{output.id}: {found} was not written by `related --take`, and is not "
                    "written over; move it out of the copy's folder"
                )
    for name in ours:
        (folder / name).unlink(missing_ok=True)
    for name, data in copied.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    commit, uncommitted = stamp
    manifest: dict = {
        "schema": SNAPSHOT_SCHEMA,
        "id": output.id,
        "project": output.project,
        "revision": output.revision,
        "commit": commit,
    }
    if output.revision is None and uncommitted:
        manifest["uncommitted"] = True
    manifest["taken_on"] = today.isoformat()
    manifest["files"] = {name: _sha256(data) for name, data in sorted(copied.items())}
    text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100)
    record.write_bytes(text.encode("utf-8"))
    return record


class _Reader:
    """The earlier project's files at its revision, through git, or as they stand."""

    def __init__(self, source: Path, revision: str | None) -> None:
        self.source = source
        self.revision = revision
        if revision is not None:
            found = _git(source, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")
            if found is None:
                raise TakeError(f"{source}: git knows no revision {revision!r} there")
            self.commit: str | None = found.decode("ascii").strip()
        else:
            head = _git(source, "rev-parse", "--verify", "--quiet", "HEAD")
            self.commit = head.decode("ascii").strip() if head else None

    def uncommitted(self, *folders: str) -> bool:
        """Whether the files copied as they stand differ from the commit recorded."""
        if self.revision is not None or self.commit is None:
            return False
        changed = _git(self.source, "status", "--porcelain", "--", *folders)
        return bool(changed and changed.strip())

    def __call__(self, name: str) -> bytes | None:
        if self.revision is None:
            path = self.source / name
            return path.read_bytes() if path.is_file() else None
        return _git(self.source, "cat-file", "blob", f"{self.commit}:./{name}")

    def listed(self, folder: str) -> list[str]:
        """The names of the files directly in `folder`."""
        if self.revision is None:
            path = self.source / folder
            return sorted(p.name for p in path.glob("*") if p.is_file()) if path.is_dir() else []
        found = _git(self.source, "ls-tree", "--name-only", "-z", f"{self.commit}:./{folder}")
        if found is None:
            return []
        return sorted(name for name in found.decode("utf-8").split("\0") if name)


def _git(source: Path, *args: str) -> bytes | None:
    """What git prints, or None where it fails or is not there."""
    try:
        done = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            timeout=GIT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
