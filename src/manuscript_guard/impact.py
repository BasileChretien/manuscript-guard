"""`impact`: what a change makes stale, read from what the gates already record.

Each gate reads one edge of a graph the project's records already hold: G1 an analysis script
and its declared inputs to a results file, the bindings a results key to the sentences that
quote it, G3 the results to the figure scripts that read them and the figures they draw, G9
a marked step to the Methods paragraph that points at it, G10 a figure to its review, G11 the
manuscript's files to the panel readings that read them, and the co-author's answers to the
items whose sentences they judged. Nothing showed the whole chain, so "I changed the cohort
definition: what now has to be run again, read again or signed again?" had no answer in one
place.

`impact` walks it from a file, transitively, and stores nothing: everything it says is
derived from the records the gates read, so it cannot go stale itself. It is a list of what
depends on the file, not a verdict: whether the dependants have changed is the gates' to say
once the analysis has run again.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.text.placeholders import parse

#: How long git may take to say which files changed.
GIT_SECONDS = 30


@dataclass(frozen=True)
class Place:
    """Where the manuscript names something: the file, the line, and what it names."""

    path: str
    line: int
    names: str


@dataclass
class Impact:
    """Everything that depends on one file, by the edge that reaches it."""

    file: str
    #: How the file enters the graph, or that no record names it.
    role: str
    results: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    bound: list[Place] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    figure_reviews: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    methods: list[Place] = field(default_factory=list)
    readings: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.results or self.keys or self.bound or self.figures or self.readings)


def impact_of(project: Project, results: Results, literature, target: Path) -> Impact:
    """What depends on `target`, a file of the project, transitively."""
    root = project.root.resolve()
    path = (target if target.is_absolute() else Path.cwd() / target).resolve()
    rel = _relative(path, root)
    manuscript = project.path("manuscript").resolve()
    figures_dir = project.path("figures").resolve()

    fragments = [
        f
        for f in results.fragments
        if f.generated_by == rel
        or any(isinstance(i, dict) and i.get("path") == rel for i in f.inputs)
        or Path(f.path).resolve() == path
    ]
    sources = {Path(f.path).resolve() for f in fragments}
    keys = sorted(
        f"results.{key}"
        for key, value in results.values.items()
        if value.source is not None and Path(value.source).resolve() in sources
    )
    keys += sorted(
        f"lit.{key}"
        for key, value in (literature.values.items() if literature is not None else ())
        if value.source is not None and Path(value.source).resolve() == path
    )
    tables = sorted(
        f"table.{key}"
        for key, table in results.tables.items()
        if Path(table.source).resolve() in sources
    )
    steps = sorted(
        name
        for name, step in results.steps.items()
        if Path(step.source).resolve() in sources or step.script == rel
    )

    role = _role(path, rel, fragments, keys, manuscript, figures_dir)
    impact = Impact(file=rel, role=role, results=[_relative(Path(f.path), root) for f in fragments])
    impact.keys = keys
    impact.steps = steps

    analysed = any(key.startswith("results.") for key in keys)
    figures = _figures_reading(figures_dir, root) if analysed else []
    if path.parent == figures_dir and path.suffix.lower() in _SCRIPTS:
        figures += _drawn_by(path, figures_dir, root)
    impact.figures = sorted(set(figures))
    stems = {Path(figure).stem for figure in impact.figures}
    impact.figure_reviews = sorted(
        _relative(figures_dir / f"{stem}.review.yaml", root)
        for stem in stems
        if (figures_dir / f"{stem}.review.yaml").is_file()
    )

    named = set(keys) | set(tables) | {f"figure.{stem}" for stem in stems}
    impact.bound = _places(project, root, named)
    impact.methods = _claims(project, root, set(steps))

    files = {place.path for place in impact.bound} | {place.path for place in impact.methods}
    if path.is_relative_to(manuscript):
        files.add(rel)
    read = {_relative(root / name, manuscript) for name in files if (root / name).is_file()}
    impact.readings = _readings(project, root, read)
    impact.answers = _answers(project, {Path(name).name for name in files})
    return impact


_SCRIPTS = frozenset({".r", ".rmd", ".qmd", ".py", ".jl"})


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _role(path, rel, fragments, keys, manuscript, figures_dir) -> str:
    if any(f.generated_by == rel for f in fragments):
        return "an analysis script that writes results"
    if any(Path(f.path).resolve() == path for f in fragments):
        return "a results file"
    if fragments:
        return "an input the analysis declares"
    if any(key.startswith("lit.") for key in keys):
        return "a record of the literature ledger"
    if path.is_relative_to(manuscript):
        return "a manuscript file"
    if path.parent == figures_dir and path.suffix.lower() in _SCRIPTS:
        return "a figure script"
    return "no record names it"


def _figures_reading(figures_dir: Path, root: Path) -> list[str]:
    """The figures drawn by every figure script that reads the results, as G3 decides it."""
    from manuscript_guard.gates.figures import _reads_results

    found: list[str] = []
    if not figures_dir.is_dir():
        return found
    for script in sorted(figures_dir.iterdir()):
        if script.suffix.lower() in _SCRIPTS and _reads_results(
            script.read_text(encoding="utf-8", errors="replace")
        ):
            found += _drawn_by(script, figures_dir, root)
    return found


def _drawn_by(script: Path, figures_dir: Path, root: Path) -> list[str]:
    """The files a figure script drew: those its render records name, else its stem's."""
    from manuscript_guard import render

    drawn: list[str] = []
    for record in sorted(figures_dir.glob(f"*{render.SUFFIX}")):
        try:
            document = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get("rendered_by") == script.name:
            drawn += [
                _relative(figures_dir / name, root)
                for name in (document.get("outputs") or {})
                if (figures_dir / name).is_file()
            ]
    if drawn:
        return drawn
    return [
        _relative(other, root)
        for other in sorted(figures_dir.glob(f"{script.stem}.*"))
        if other.suffix.lower() in {".svg", ".pdf", ".png", ".tif", ".tiff", ".jpg", ".eps"}
    ]


def _places(project: Project, root: Path, named: set[str]) -> list[Place]:
    """Each binding of the manuscript that names one of `named`."""
    from manuscript_guard.gates.numbers import source_files

    found: list[Place] = []
    if not named:
        return found
    for path in source_files(project.path("manuscript")):
        for placeholder in parse(read_text(path))[0]:
            if placeholder.ref in named:
                found.append(Place(_relative(path, root), placeholder.line, placeholder.ref))
    return found


def _claims(project: Project, root: Path, steps: set[str]) -> list[Place]:
    """The Methods paragraphs that point at one of `steps`, where their anchors stand."""
    from manuscript_guard.gates.methods import anchored

    if not steps:
        return []
    claims, _open = anchored(project)
    return [
        Place(_relative(claim.path, root), claim.line, "method." + ", method.".join(claim.steps))
        for claim in claims
        if steps & set(claim.steps)
    ]


def _readings(project: Project, root: Path, files: set[str]) -> list[str]:
    """The panel readings that read any of `files` (paths under manuscript/), as G11 judges
    them: by the files a reading lists, or the whole manuscript where it lists none."""
    review = root / "review"
    if not files or not review.is_dir():
        return []
    found = []
    for record in sorted(review.glob("round-*/*.yaml")):
        try:
            document = yaml.safe_load(record.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict) or "verdict" not in document:
            continue
        read = document.get("file_sha256")
        if not isinstance(read, dict) or not read or files & set(read):
            found.append(_relative(record, root))
    return found


def _answers(project: Project, names: set[str]) -> list[str]:
    """The co-author answers given on items whose sentences stand in one of the files
    `names` (by file name, as the items record them)."""
    from manuscript_guard.checking.produce import produce
    from manuscript_guard.checking.store import read_decisions

    if not names:
        return []
    decisions = read_decisions(project.root)
    if not decisions:
        return []
    document, _unread = produce(project)
    touched = {
        item["id"]
        for item in document.get("items", [])
        if any(sentence.get("section") in names for sentence in item.get("sentences") or [])
    }
    return [
        f"{decision.by} on {decision.title!r} ({decision.status}, {decision.when})"
        for decision in decisions
        if decision.id in touched
    ]


class NoChanges(Exception):
    """Git could not say which files changed."""


def changed_files(project: Project, since: str = "HEAD") -> list[Path]:
    """The files of the project that differ from `since`, and those git does not track yet."""
    root = project.root.resolve()

    def git(*args: str) -> list[str]:
        command = ["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args]
        try:
            done = subprocess.run(
                command, cwd=root, capture_output=True, text=True, timeout=GIT_SECONDS,
                check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NoChanges(f"git could not be asked: {error}") from error
        if done.returncode != 0:
            raise NoChanges(done.stderr.strip() or f"git {' '.join(args)} failed")
        return [line for line in done.stdout.splitlines() if line.strip()]

    names = git("diff", "--name-only", "--relative", since, "--", ".")
    names += git("ls-files", "--others", "--exclude-standard", "--", ".")
    return [root / name for name in sorted(set(names))]


def as_json(impacts: list[Impact]) -> str:
    return json.dumps([asdict(impact) for impact in impacts], indent=2, ensure_ascii=False)


def as_text(impact: Impact) -> list[str]:
    """The lines `impact` prints for one file."""
    lines = [f"{impact.file}: {impact.role}"]
    if impact.empty and not impact.steps:
        return lines + ["  nothing the gates record depends on it"]

    def listed(label: str, items: list[str]) -> None:
        if items:
            lines.append(f"  {label} ({len(items)}):")
            lines.extend(f"    {item}" for item in items)

    listed("results it writes or feeds", impact.results)
    listed("keys in them", impact.keys)
    listed("where the manuscript binds them", [
        f"{place.path}:{place.line}  {place.names}" for place in impact.bound
    ])  # fmt: skip
    listed("figures drawn from them", impact.figures)
    listed("figure reviews to read again", impact.figure_reviews)
    listed("marked steps", impact.steps)
    listed("Methods paragraphs pointing at them", [
        f"{place.path}:{place.line}  {place.names}" for place in impact.methods
    ])  # fmt: skip
    listed("panel readings of those files", impact.readings)
    listed("co-author answers on those files", impact.answers)
    return lines
