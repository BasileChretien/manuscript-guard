"""Which document a revision is marked up against, kept when the round is opened.

`respond --open` records the manuscript as the journal received it, and the marked-up copy
needs the document itself: its numbers as they printed then, its figures, its reference list.
So the round keeps a copy of it beside the rendered text, in
`revision/round-<n>/submitted/`: the document of the submission pack where that was built
from the manuscript as it stands, and otherwise the one in `build/` where that was. One built
from anything else is not what the journal received, and is not kept: the marked-up copy is
then made against a document named with `build --marked-up --since`, or one put in the
round's folder by hand.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.markedup import FORMS, Made, MarkedUpError, write

#: The documents a round keeps, the paper and its supplement, by the names the build gives.
PAPER, SUPPLEMENT = "manuscript.docx", "supplementary.docx"
#: Where marked-up copies are written: not `build/` itself, where `check` holds every
#: document to the source.
FOLDER = "marked-up"


def round_folder(project: Project, number: int) -> Path:
    from manuscript_guard.gates.revision import REVISION_DIR, SUBMITTED_DIR

    return project.root / REVISION_DIR / f"round-{number}" / SUBMITTED_DIR


def _current(project: Project, document: Path) -> bool:
    """Whether `document` was built from the manuscript as it stands."""
    from manuscript_guard.gates.review import document_digest
    from manuscript_guard.roundtrip import RoundTripError, stamp_of

    if not document.is_file():
        return False
    try:
        return stamp_of(document) == document_digest(project)
    except RoundTripError:
        return False


def _sent(project: Project, name: str) -> Path | None:
    """The document called `name` the journal received, if one in `build/` is current: the
    submission pack's first, since the pack is what was sent."""
    build = project.path("build")
    for candidate in (build / "submission" / name, build / name):
        if _current(project, candidate):
            return candidate
    return None


def keep_sent(project: Project, number: int) -> tuple[list[Path], str | None]:
    """Copy the documents the journal received into round `number`'s folder. The copies
    kept, and what to say where the paper's was not."""
    folder = round_folder(project, number)
    kept = []
    for name in (PAPER, SUPPLEMENT):
        found = _sent(project, name)
        if found is None:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, folder / name)
        kept.append(folder / name)
    if any(path.name == PAPER for path in kept):
        return kept, None
    relative = (folder / PAPER).relative_to(project.root).as_posix()
    return kept, (
        f"no document in build/ was built from the manuscript as it stands, so none is kept "
        f"as the one the journal received; put the file you sent at {relative}, or name it "
        f"with `build --marked-up --since`, for the marked-up copy"
    )


def sent_copy(project: Project, number: int, name: str = PAPER) -> Path | None:
    found = round_folder(project, number) / name
    return found if found.is_file() else None


@dataclass(frozen=True)
class Asked:
    """What a marked-up copy is to be made against, and how."""

    before: Path
    after: Path
    target: Path
    round_number: int | None


def target_for(project: Project, after: Path, form: str) -> Path:
    """Where the marked-up copy of the built `after` goes: build/marked-up/, by its name,
    `.highlighted` before the suffix for the highlighted form."""
    if form not in FORMS:
        raise MarkedUpError(f"no marked-up copy of the form {form!r}")
    name = after.name if form == "tracked" else f"{after.stem}.highlighted{after.suffix}"
    return project.path("build") / FOLDER / name


def make(project: Project, asked: Asked, form: str) -> Made:
    """Write the marked-up copy asked for, dated today."""
    return write(
        asked.before,
        asked.after,
        asked.target,
        date=date.today().isoformat(),
        form=form,
        round_number=asked.round_number,
    )


def describe(made: Made) -> str:
    """The changes a copy shows, in a line."""
    order = (
        "words inserted", "words deleted", "words reformatted", "paragraphs edited",
        "paragraphs restyled", "blocks inserted", "blocks deleted", "blocks replaced",
        "tables edited", "rows inserted", "rows deleted",
    )  # fmt: skip
    shown = [f"{made.counts[k]} {k}" for k in order if made.counts.get(k)]
    return ", ".join(shown) if shown else "no change"
