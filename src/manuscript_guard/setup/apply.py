"""The project written from the answers: `apply_answers`.

Nothing is written while a question is open. Then every change is worked out and read back
in memory first, so that a setting `paper.yaml` would refuse, or an `authors.yaml` that
would not read back as the authors given, stops the whole of it with the files as they were.
Only then is anything written, in the order the files need: the git repository, `init`, the
settings, the authors, the journal's profile, `.gitignore`, the workflow, and last the date
in the record. A value already there is never replaced: it is kept and said, and a change is
`set`'s, with its guard.
"""

from __future__ import annotations

import datetime
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from manuscript_guard.setup.answers import ANSWERS_FILE, LATER, answer, journal_slug
from manuscript_guard.setup.folder import Folder, read_folder
from manuscript_guard.setup.questions import Step, ask
from manuscript_guard.setup.tools import Tool, prerequisites

#: Seconds `git init` is given.
GIT_LIMIT = 60
GITIGNORE_SOURCES = "literature/sources/*"


@dataclass(frozen=True)
class Change:
    """One thing written, or that would be: the file, the setting, and why it matters."""

    file: str
    what: str
    why: str


@dataclass(frozen=True)
class Applied:
    dry_run: bool
    refused: str | None = None
    open: tuple[str, ...] = ()
    written: tuple[Change, ...] = ()
    kept: tuple[Change, ...] = ()
    notes: tuple[str, ...] = ()
    tools: tuple[Tool, ...] = ()
    after: tuple[Step, ...] = ()

    @property
    def ok(self) -> bool:
        return self.refused is None


class _Refused(Exception):
    pass


# ---------------------------------------------------------------------------- paper.yaml


@dataclass
class _Paper:
    """The edits of `paper.yaml`, each with why, applied in turn to a text."""

    edits: list[tuple[str, str, Any, str]] = field(default_factory=list)  # kind, key, value, why
    kept: list[Change] = field(default_factory=list)

    def run(self, text: str) -> str:
        from manuscript_guard import paper_edit

        for kind, key, value, _why in self.edits:
            try:
                if kind == "value":
                    text = paper_edit.edit(text, key, value, keys=paper_edit.SETUP_KEYS).text
                elif kind == "block":
                    text = paper_edit.edit_block(text, key, value).text
                else:
                    parent, child = key.split(".")
                    text = paper_edit.edit_child(text, parent, child, value).text
            except paper_edit.Refused as exc:
                raise _Refused(f"paper.yaml cannot take `{key}`: {exc}") from exc
        return text


def _english(answers: dict) -> str | None:
    language = answer(answers, "language")
    return language if language in ("en-GB", "en-US") else None


def _journal(answers: dict) -> str | None:
    journal = answer(answers, "journal")
    if isinstance(journal, dict):
        return journal.get("slug") or journal_slug(journal["name"])
    return journal if isinstance(journal, str) and journal not in (LATER, "help") else None


def _fill(paper: _Paper, folder: Folder, key: str, value: Any, why: str, *,
          kind: str = "value", blank: Callable[[Any], bool] | None = None) -> None:  # fmt: skip
    """Write `key` where `paper.yaml` holds nothing for it; keep and say what it holds."""
    if kind == "child":
        parent, child = key.split(".")
        held = (folder.setting(parent) or {}).get(child)
    else:
        held = folder.setting(key)
    empty = blank(held) if blank is not None else held in (None, "", [])
    if not folder.is_project or empty:
        paper.edits.append((kind, key, value, why))
    elif held != value:
        paper.kept.append(Change("paper.yaml", f"{key}: {held}", f"the answer, {value}, is not "
                                 "written over it; `manuscript-guard set` changes it"))  # fmt: skip


def _paper_edits(folder: Folder, answers: dict) -> _Paper:
    from manuscript_guard.gates.design import study_types
    from manuscript_guard.guide.rules import ENGLISH_NAMES
    from manuscript_guard.scaffold import UNTITLED

    paper = _Paper()
    title = answer(answers, "title")
    if folder.is_project and isinstance(title, str) and title.strip():
        _fill(paper, folder, "title", title, "the document's title",
              blank=lambda held: held in (None, "", UNTITLED))
    english = _english(answers)
    if folder.is_project and english:
        _fill(paper, folder, "english_variant", english,
              f"G14 holds the spelling to {ENGLISH_NAMES[english]}")
    design = answer(answers, "study_type")
    if isinstance(design, str):
        label = (study_types().get(design) or {}).get("label", "the design")
        _fill(paper, folder, "study_type", design, f"the plan is asked for the sections a "
              f"{label} needs")  # fmt: skip
    guidelines = answer(answers, "reporting_guideline")
    if isinstance(guidelines, list) and guidelines:
        _fill(paper, folder, "reporting_guideline", guidelines, "G5 asks for each one's "
              "checklist, every item answered by a quoted sentence")  # fmt: skip
    journal = _journal(answers)
    if journal:
        _fill(paper, folder, "target_journal", journal, "G4 holds the paper to the "
              "journal's rules, once its profile is filled from its own page")  # fmt: skip
    stage = answer(answers, "stage")
    if isinstance(stage, str):
        _fill(paper, folder, "stage", stage, f"the findings due by {stage} are held now",
              blank=lambda held: held in (None, "design"))
    registration = answer(answers, "registration")
    if isinstance(registration, list):
        _fill(paper, folder, "registration", [{"id": ident} for ident in registration],
              "G12 holds the paper to each registration", kind="block")  # fmt: skip
    count = answer(answers, "data.minimum_cell_count")
    if isinstance(count, int):
        _fill(paper, folder, "custodian.minimum_cell_count", count, f"a count below {count} "
              "that the manuscript binds fails G2 from internal review", kind="child")  # fmt: skip
    if answer(answers, "repository.sources_in_git") is True:
        _fill(paper, folder, "literature.sources_in_git", True, "the stored copies are "
              "committed, and CI holds every quote to its copy", kind="child")  # fmt: skip
    return paper


# ---------------------------------------------------------------------------- the files


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def _ignored_now(folder: Folder) -> list[str]:
    """`.gitignore`'s lines as they are, or as `init` writes them where it will."""
    from manuscript_guard.scaffold import GITIGNORE

    path = folder.root / ".gitignore"
    if path.is_file() or folder.is_project:
        return _lines(path)
    return GITIGNORE.splitlines()


def _shown(value: Any) -> str:
    """A setting's value as the summary says it."""
    from manuscript_guard.paper_edit import written

    if isinstance(value, list) and value and isinstance(value[0], dict):
        return ", ".join(str(entry.get("id")) for entry in value)
    return written(value)


def _gitignore(folder: Folder, answers: dict, lines: list[str]) -> tuple[list[str], list[Change]]:
    """`.gitignore`'s lines with the data's folder added and, where the stored sources are to
    be committed, their line taken out; and what changed."""
    changes = []
    data_folder = answer(answers, "data.folder")
    keep_out = (answer(answers, "data.where") == "project"
                and answer(answers, "data.publishable") is False)
    if keep_out and isinstance(data_folder, str):
        line = data_folder.strip("/") + "/"
        if not {line, line.rstrip("/"), "/" + line} & {entry.strip() for entry in lines}:
            lines = [*lines, "", "# The data, which may not be published (setup).", line]
            changes.append(Change(".gitignore", line, "no commit holds the data"))
    if answer(answers, "repository.sources_in_git") is True and GITIGNORE_SOURCES in lines:
        lines = [entry for entry in lines if entry != GITIGNORE_SOURCES]
        changes.append(Change(".gitignore", f"{GITIGNORE_SOURCES} taken out", "the stored "
                              "copies of the cited works are committed"))  # fmt: skip
    return lines, changes


def _recorded(text: str, today: str) -> str:
    """`design/setup.yaml` with the day the project was written from it."""
    kept = [line for line in text.splitlines() if not line.startswith("applied_on:")]
    return "\n".join([*kept, f"applied_on: {today}"]) + "\n"


def _git_init(root: Path, run: Callable) -> None:
    try:
        done = run(["git", "init", "-q"], cwd=root, capture_output=True, text=True,
                   timeout=GIT_LIMIT, check=False)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _Refused(f"git init could not be run: {exc}") from exc
    if done.returncode != 0:
        raise _Refused(f"git init failed: {(done.stderr or '').strip()}")


@dataclass
class _Plan:
    paper: _Paper
    base: str | None  # paper.yaml as it is, or as init would write it
    authors: str | None
    profile: str | None
    ignore: list[str]
    changes: list[Change]
    git: bool
    workflow: bool


def _plan(folder: Folder, answers: dict) -> _Plan:
    from manuscript_guard import paper_edit
    from manuscript_guard.scaffold import UNTITLED, checked_title, paper_text
    from manuscript_guard.setup.authors_file import AuthorsRefused, authors_data, checked_authors

    changes: list[Change] = []
    start = answer(answers, "start")
    if folder.is_project:
        base = paper_edit.read(folder.root / "paper.yaml")[1]
    else:
        title = answer(answers, "title")
        given = title if isinstance(title, str) and title.strip() else UNTITLED
        base = paper_text(checked_title(given, latex=start == "latex"), _english(answers))
        how = {"markdown": "manuscript/main.md", "latex": "manuscript/main.tex"}.get(
            start, f"manuscript/main.md, from {start}")
        changes.append(Change("(the project)", f"made with {how}", "the files every check "
                              "reads, each written where none is"))  # fmt: skip
        if _english(answers):
            changes.append(Change("paper.yaml", f"english_variant: {_english(answers)}",
                                  "G14 holds the spelling to it"))
    paper = _paper_edits(folder, answers)
    paper.run(base)  # refused here, before anything is written
    changes += [Change("paper.yaml", f"{key}: {_shown(value)}", why)
                for _kind, key, value, why in paper.edits]
    authors = None
    if folder.authors_blank and isinstance(answer(answers, "authors"), list):
        try:
            data = authors_data(answers)
            authors = checked_authors(data)
        except AuthorsRefused as exc:
            raise _Refused(str(exc)) from exc
        changes.append(Change("authors.yaml", f"{len(data['authors'])} author(s), "
                              f"{len(data['affiliations'])} affiliation(s)", "the title page "
                              "and the declarations are built from it"))  # fmt: skip
    profile = _journal(answers)
    if profile and profile in folder.profiles:
        profile = None
    if profile:
        changes.append(Change(f"profiles/journals/{profile}.yaml", "the annotated template",
                              "to be filled from the journal's own instructions page"))
    lines, ignored = _gitignore(folder, answers, _ignored_now(folder))
    changes += ignored
    git = answer(answers, "repository.git") is True and folder.repository is None
    if git:
        changes.append(Change("(the folder)", "a git repository", "history dates the plan "
                              "before the results"))  # fmt: skip
    workflow = answer(answers, "repository.github_actions") is True and not folder.workflow
    if workflow:
        changes.append(Change(".github/workflows/manuscript-guard.yml", "the workflow",
                              "check runs on each push and pull request"))
    return _Plan(paper, base, authors, profile, lines if ignored else [], changes, git, workflow)


def _notes(answers: dict) -> list[str]:
    notes = []
    if answer(answers, "language") == "other":
        notes.append("No English is declared. The numbers, the citations and the sources are "
                     "checked as for a paper in English; the writing checks (G6, G14 and the "
                     "abbreviation rules) read English, and their findings on another "
                     "language are not to be taken as they stand.")
    start = answer(answers, "start")
    if isinstance(start, str) and start.lower().endswith(".docx") and not answer(answers, "title"):
        notes.append(f"The title is the one {start}'s Title style holds.")
    return notes


def _write(folder: Folder, answers: dict, plan: _Plan, today: str, run: Callable,
           done: list[str]) -> list[str]:  # fmt: skip
    """Write what `plan` says, in order, naming in `done` each file as it is written; the
    notes `init --from` gives of a Word paper."""
    from manuscript_guard import __version__, paper_edit
    from manuscript_guard.github_workflow import write_github_workflow
    from manuscript_guard.paths import SHIPPED_JOURNALS
    from manuscript_guard.scaffold import UNTITLED, init_project

    root, notes = folder.root, []
    if plan.git:
        _git_init(root, run)
        done.append("the git repository")
    start, title = answer(answers, "start"), answer(answers, "title")
    given = title if isinstance(title, str) and title.strip() else None
    if not folder.is_project and isinstance(start, str) and start.lower().endswith(".docx"):
        from manuscript_guard.from_word import init_from_word, what_was_done

        _created, converted = init_from_word(root, root / start, title=given,
                                             english=_english(answers))  # fmt: skip
        notes.append(what_was_done(root / start, converted))
        done.append("the project")
    elif not folder.is_project:
        init_project(root, title=given or UNTITLED, latex=start == "latex",
                     english=_english(answers))  # fmt: skip
        done.append("the project")
    path = root / "paper.yaml"
    mark, text = paper_edit.read(path)
    edited = plan.paper.run(text)
    if edited != text:
        paper_edit.write(path, mark + edited)
        done.append("paper.yaml")
    if plan.authors is not None:
        (root / "authors.yaml").write_text(plan.authors, encoding="utf-8", newline="\n")
        done.append("authors.yaml")
    if plan.profile:
        target = root / "profiles" / "journals" / f"{plan.profile}.yaml"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source = (SHIPPED_JOURNALS / "TEMPLATE.yaml").read_text(encoding="utf-8")
            target.write_text(source, encoding="utf-8", newline="\n")
            done.append(f"profiles/journals/{plan.profile}.yaml")
    ignore = root / ".gitignore"
    lines, ignored = _gitignore(folder, answers, _lines(ignore))
    if ignored:
        ignore.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        done.append(".gitignore")
    if plan.workflow:
        write_github_workflow(root, __version__)
        done.append("the workflow")
    record = root / ANSWERS_FILE
    record.write_text(_recorded(record.read_text(encoding="utf-8"), today), encoding="utf-8",
                      newline="\n")  # fmt: skip
    return notes


def apply_answers(root: Path, *, dry_run: bool = False, today: str | None = None,
                  run: Callable = subprocess.run, which: Callable | None = None,
                  env: dict | None = None) -> Applied:  # fmt: skip
    """Write the project at `root` from its `design/setup.yaml`; with `dry_run`, say what
    would be written and write nothing. `SetupRefused` where the folder cannot be set up."""
    import shutil

    from manuscript_guard.contracts import ContractError
    from manuscript_guard.setup.answers import load_answers

    folder = read_folder(root)
    answers = load_answers(folder.root)
    asked = ask(folder, answers)
    if not asked.ready:
        still = tuple(q.id for q in asked.questions) + tuple(place for place, _ in asked.waiting)
        return Applied(dry_run, refused="questions are still open", open=still)
    try:
        plan = _plan(folder, answers)
    except (_Refused, ContractError) as exc:
        return Applied(dry_run, refused=str(exc))
    tools = prerequisites(answer(answers, "analysis"), run=run, which=which or shutil.which,
                          env=env)  # fmt: skip
    notes = _notes(answers)
    if not dry_run:
        done: list[str] = []
        try:
            notes += _write(folder, answers, plan, today or datetime.date.today().isoformat(),
                            run, done)  # fmt: skip
        except (_Refused, ContractError, OSError) as exc:
            wrote = ", ".join(done) or "nothing"
            return Applied(False, refused=f"{exc}; written before it: {wrote}",
                           kept=tuple(plan.paper.kept))  # fmt: skip
    return Applied(dry_run, written=tuple(plan.changes), kept=tuple(plan.paper.kept),
                   notes=tuple(notes), tools=tools, after=asked.after)  # fmt: skip
