"""`inspect`: the project read once, every gate run, and nothing written."""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.findings import FAIL
from manuscript_guard.guide.model import (
    AUTHORS_ONLY,
    LATEX_CHECKER,
    MISSING,
    NO_PROJECT,
    NOT_PAPERS,
    PAPER_SUFFIXES,
    PROJECT,
    UNREADABLE,
    Checker,
    State,
)


def inspect(start: Path, *, stage: str | None = None, cwd: Path | None = None) -> State:
    """Read the project at `start`, or what is there where there is none. Writes nothing,
    and raises nothing: what could not be read is said, in `error` or among the notes."""
    from manuscript_guard.contracts import ContractError
    from manuscript_guard.contracts.project import AUTHORS_FILE, find_root

    here = (cwd or Path.cwd()).resolve()
    if not Path(start).exists():
        # Its parent is not what was asked for: a mistyped folder is said, not replaced.
        return State(kind=MISSING, root=Path(start).absolute(), cwd=here, format=None,
                     stage=None, error=f"{Path(start)} does not exist")  # fmt: skip
    try:
        root = find_root(Path(start))
    except ContractError:
        folder = Path(start).resolve()
        folder = folder if folder.is_dir() else folder.parent
        kind = AUTHORS_ONLY if (folder / AUTHORS_FILE).is_file() else NO_PROJECT
        return State(kind=kind, root=folder, cwd=here, format=None, stage=None,
                     candidates=_candidates(folder))  # fmt: skip
    from manuscript_guard.cli import _gate_run

    try:
        report, project, chosen, deferred, namespace = _gate_run(root, stage=stage)
    except ContractError as exc:
        return State(kind=UNREADABLE, root=root, cwd=here, format=None, error=str(exc),
                     stage=None)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - next always decides; check says what broke
        from manuscript_guard.diagnostics import crashes

        crashes.record(exc, kind=crashes.COMMAND, name="the gates' run")
        return State(kind=UNREADABLE, root=root, cwd=here, format=None, stage=None,
                     error=f"the gates could not be run: {type(exc).__name__}: {exc}; "
                     "`manuscript-guard check` says more")  # fmt: skip
    return _project_state(project, report.findings, chosen, deferred, namespace, here)


def from_run(project, report, stage: str, deferred, namespace, *, cwd: Path):
    """What reads the state of a gate run the caller has already made, `cli._gate_run`'s five
    parts, for `rules.first_action`: the hooks' status line decides on the run it reports and
    does not run the gates again, and reads which numbers one published value reads as and
    where the co-authors' round stands only where the first action turns on them."""
    here = Path(cwd).resolve()

    def read(bindable: bool, checker: bool) -> State:
        return _project_state(project, report.findings, stage, deferred, namespace, here,
                              bindable=bindable, checker=checker)  # fmt: skip

    return read


def _kept(notes: list[str], what: str, work, default):
    """`work()`, or `default` with a note: a part of the state that cannot be read is left
    out and said, and `next` still decides on the rest."""
    try:
        return work()
    except Exception as exc:  # noqa: BLE001 - one unreadable part never costs the decision
        from manuscript_guard.diagnostics import crashes

        crashes.record(exc, kind=crashes.COMMAND, name=what)
        notes.append(f"{what} could not be read, so it is left out: {type(exc).__name__}: {exc}")
        return default


def _candidates(folder: Path) -> tuple[str, ...]:
    """The papers in `folder` itself, by name: a Word document's lock file is none, nor a
    repository's own notes, by their name up to its first stop."""
    if not folder.is_dir():
        return ()
    return tuple(sorted(
        path.name for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in PAPER_SUFFIXES
        and path.name.split(".")[0].lower() not in NOT_PAPERS
        and not path.name.startswith("~$")
    ))  # fmt: skip


def _project_state(project, findings, chosen, deferred, namespace, here: Path, *,
                   bindable: bool = True, checker: bool = True) -> State:
    """The state `decide` reads. Without `bindable`, no number is asked which published value
    it reads as (a second classification of every number), and without `checker` the
    co-authors' round is not read: `rules.first_action` asks for each only where it counts."""
    from manuscript_guard.gates.design import study_types
    from manuscript_guard.paper_edit import journals
    from manuscript_guard.policy import DRAFTING, STAGES
    from manuscript_guard.text.reader import manuscript_format

    notes: list[str] = []
    fmt = _kept(notes, "the manuscript's format",
                lambda: manuscript_format(project.path("manuscript")), "markdown")
    failing = bindable and any(
        f.severity == FAIL and f.code == "unclassified-number" for f in findings)
    standing = _kept(notes, "where the co-authors' checks stand",
                     lambda: _checker(project, fmt, notes), None) if checker else None
    paper = project.paper if isinstance(project.paper, dict) else {}
    journal = paper.get("target_journal") if isinstance(paper.get("target_journal"), str) else None
    declared = paper.get("stage") if paper.get("stage") in STAGES else DRAFTING
    designs = _kept(notes, "the study designs", lambda: tuple(
        (key, str(kind.get("label") or key), tuple(str(g) for g in kind.get("guidelines") or ()))
        for key, kind in sorted(study_types().items())), ())
    return State(
        kind=PROJECT, root=project.root, cwd=here, format=fmt, stage=chosen,
        declared_stage=declared, findings=tuple(findings), deferred=dict(deferred),
        bindable=_kept(notes, "which numbers read as one published value",
                       lambda: _bindable(project, namespace), {}) if failing else {},
        checker=standing, target_journal=journal,
        english_variant=_kept(notes, "paper.yaml's English",
                              lambda: project.english_variant, None),
        reporting_guidelines=_kept(notes, "paper.yaml's reporting guidelines", lambda: tuple(
            str(name) for name in project.reporting_guidelines), ()),
        study_type=_kept(notes, "paper.yaml's study type", lambda: project.study_type, None),
        journals=_kept(notes, "the journals there are",
                       lambda: tuple(journals(project.root)), ()),
        journal_english=_kept(notes, "the journal's English",
                              lambda: _journal_english(project, journal), None),
        study_types=designs, notes=tuple(notes),
    )  # fmt: skip


def _bindable(project, namespace) -> dict[str, str]:
    """Each place `bind --apply --only` takes: every unbound number on its line reads as one
    published value, so the command writes those bindings and refuses nothing."""
    from manuscript_guard.binding import label, unbound

    by_label: dict[str, list] = {}
    for item in unbound(project, namespace):
        by_label.setdefault(label(item, project.root), []).append(item)
    return {
        where: ", ".join(item.binding(item.certain) for item in group)
        for where, group in by_label.items()
        if all(item.certain for item in group)
    }


def _checker(project, fmt: str, notes: list[str]) -> Checker | None:
    """Where a round of co-authors' checks stands, once one has begun; what reading the items
    would print goes to `notes`. Anything that cannot be read is `_kept`'s to say."""
    from manuscript_guard.checking.store import DECISIONS
    from manuscript_guard.text.reader import LATEX

    if fmt == LATEX:
        notes.append(LATEX_CHECKER)
        return None
    if not (project.root / DECISIONS).is_file():
        return None
    from manuscript_guard.checking import status
    from manuscript_guard.cli import _checking_items

    items = _checking_items(project, None, told=notes)
    standing = status(project.root, items)
    return Checker(len(items.items), standing.outstanding, len(standing.stale),
                   len(standing.disagreements))  # fmt: skip


def _journal_english(project, journal: str | None) -> str | None:
    from manuscript_guard.contracts import read_structured
    from manuscript_guard.gates.journal import profile_path

    path = profile_path(project, journal) if journal else None
    if path is None:
        return None
    profile = read_structured(path)
    wanted = profile.get("english_variant") if isinstance(profile, dict) else None
    return wanted if isinstance(wanted, str) else None
