"""`inspect`: the project read once, every gate run, and nothing written."""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.findings import FAIL
from manuscript_guard.guide.model import (
    AUTHORS_ONLY,
    LATEX_CHECKER,
    NO_PROJECT,
    NOT_PAPERS,
    PAPER_SUFFIXES,
    PROJECT,
    UNREADABLE,
    Checker,
    State,
)


def inspect(start: Path, *, stage: str | None = None, cwd: Path | None = None) -> State:
    """Read the project at `start`, or what is there where there is none. Writes nothing."""
    from manuscript_guard.contracts import ContractError
    from manuscript_guard.contracts.project import AUTHORS_FILE, find_root

    here = (cwd or Path.cwd()).resolve()
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
    return _project_state(project, report.findings, chosen, deferred, namespace, here)


def _candidates(folder: Path) -> tuple[str, ...]:
    """The papers in `folder` itself, by name: a Word document's lock file is none."""
    if not folder.is_dir():
        return ()
    return tuple(sorted(
        path.name for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in PAPER_SUFFIXES
        and path.stem.lower() not in NOT_PAPERS and not path.name.startswith("~$")
    ))  # fmt: skip


def _project_state(project, findings, chosen, deferred, namespace, here: Path) -> State:
    from manuscript_guard.gates.design import study_types
    from manuscript_guard.paper_edit import journals
    from manuscript_guard.text.reader import manuscript_format

    fmt = manuscript_format(project.path("manuscript"))
    failing = any(f.severity == FAIL and f.code == "unclassified-number" for f in findings)
    checker, notes = _checker(project, fmt)
    paper = project.paper
    journal = paper.get("target_journal") if isinstance(paper.get("target_journal"), str) else None
    designs = tuple(
        (key, str(kind.get("label") or key), tuple(str(g) for g in kind.get("guidelines") or ()))
        for key, kind in sorted(study_types().items())
    )
    return State(
        kind=PROJECT, root=project.root, cwd=here, format=fmt, stage=chosen,
        findings=tuple(findings), deferred=dict(deferred),
        bindable=_bindable(project, namespace) if failing else {},
        checker=checker, notes=notes, target_journal=journal,
        english_variant=project.english_variant,
        reporting_guidelines=tuple(str(name) for name in project.reporting_guidelines),
        study_type=project.study_type, journals=tuple(journals(project.root)),
        journal_english=_journal_english(project, journal), study_types=designs,
    )  # fmt: skip


def _bindable(project, namespace) -> dict[str, str]:
    """Each place `bind --apply --only` takes: every unbound number on its line reads as one
    published value, so the command writes those bindings and refuses nothing."""
    from manuscript_guard.binding import label, unbound
    from manuscript_guard.contracts import ContractError

    try:
        items = unbound(project, namespace)
    except ContractError:
        return {}  # the file is one a gate could not read, and that gate says so
    by_label: dict[str, list] = {}
    for item in items:
        by_label.setdefault(label(item, project.root), []).append(item)
    return {
        where: ", ".join(item.binding(item.certain) for item in group)
        for where, group in by_label.items()
        if all(item.certain for item in group)
    }


def _checker(project, fmt: str) -> tuple[Checker | None, tuple[str, ...]]:
    """Where a round of co-authors' checks stands, once one has begun."""
    from manuscript_guard.checking.store import DECISIONS
    from manuscript_guard.text.reader import LATEX

    if fmt == LATEX:
        return None, (LATEX_CHECKER,)
    if not (project.root / DECISIONS).is_file():
        return None, ()
    from manuscript_guard.checking import ItemsError, status
    from manuscript_guard.cli import _checking_items

    told: list[str] = []
    try:
        items = _checking_items(project, None, told=told)
    except ItemsError as exc:
        return None, (*told, f"where the co-authors' checks stand could not be read: {exc}")
    standing = status(project.root, items)
    return Checker(len(items.items), standing.outstanding, len(standing.stale),
                   len(standing.disagreements)), tuple(told)  # fmt: skip


def _journal_english(project, journal: str | None) -> str | None:
    from manuscript_guard.contracts import ContractError, read_structured
    from manuscript_guard.gates.journal import profile_path

    path = profile_path(project, journal) if journal else None
    if path is None:
        return None
    try:
        profile = read_structured(path)
    except ContractError:
        return None
    wanted = profile.get("english_variant") if isinstance(profile, dict) else None
    return wanted if isinstance(wanted, str) else None
