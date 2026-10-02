"""Writing a review record, so that G11 is a checklist rather than a wall.

G11 blocks submission until a panel exists and every reviewer in it has filed a record, and
there was no command that produced one. An author reaching that gate had to read the schema,
work out where the file goes, compute a SHA-256 of a canonical join of their own manuscript,
and get all of it right — for a file the toolkit could write. The predictable outcome is not
a carefully hand-written record; it is `--skip-checks`.

What this deliberately does *not* offer is a way to re-stamp a record after the manuscript
has changed. That one keystroke would turn the whole review system into theatre: the digest
is the only thing distinguishing "somebody read this version" from "somebody read a version".
When the manuscript moves, G11 says to re-review or to accept that the finding list describes
a version nobody will read, and both of those are decisions for a person.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

VERDICTS = ("pass", "minor-revision", "major-revision", "reject")
#: A reader's name is part of a file name, and file systems stop at 255 bytes for the whole
#: of it. Counted in bytes of UTF-8, which is what those limits count.
MAX_READER_NAME = 120
FIGURE_VERDICTS = ("pass", "concerns")


class RecordError(Exception):
    """The record cannot be written, and saying why is more use than writing it wrongly."""


@dataclass(frozen=True)
class Written:
    path: Path
    panel: Path | None


def _yaml_dump(document: dict) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=88)


def _ensure_panel(project, round_number: int, reviewer: str, remit: str, today: date) -> Path:
    """The reviewer belongs to a declared panel, or the record is a note nobody asked for.

    A panel names who is responsible for noticing what. Extending an existing one rather than
    replacing it, because the other reviewers' remits are the round's design.
    """
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.review import panel_path

    path = panel_path(project, round_number)
    document = (read_structured(path) or {}) if path.exists() else None
    reviewers = list((document or {}).get("reviewers") or [])
    if any(entry.get("id") == reviewer for entry in reviewers):
        return path

    # A reviewer who was on an earlier panel keeps their remit unless the caller states a
    # new one. Asking again for every round is friction that teaches people to type
    # anything, and "same reviewer, next round" is the ordinary case a revision produces.
    if not remit:
        remit = _remit_from_earlier_panels(project, reviewer, round_number)
    if not remit:
        where = f"in {path.name}" if document else f"on any panel before round {round_number}"
        raise RecordError(
            f"{reviewer!r} is not {where}. Pass --remit to say what this reviewer is "
            f"responsible for noticing; two reviewers with the same remit are one reviewer, "
            f"which is the question the panel file exists to make somebody answer"
        )

    reviewers.append({"id": reviewer, "remit": remit})
    if document is None:
        document = {
            "schema": "manuscript-guard/panel/1",
            "round": round_number,
            "opened_on": today.isoformat(),
        }
    document["reviewers"] = reviewers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_dump(document), encoding="utf-8", newline="\n")
    return path


def _name_reader(panel: Path, reviewer: str, reader: str) -> None:
    """List `reader` among the readers the panel asks of `reviewer`, if it is not there.

    The panel says who reads each remit, and G11 reads a named file only when the panel
    names its reader. So filing a named reading names the reader, the way filing a record
    puts the reviewer on the panel: a reading the gate would then not count is not filed.
    A reader already listed under another spelling of the same name is left as the panel
    has it.
    """
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.review import reading_slug

    document = read_structured(panel) or {}
    for entry in document.get("reviewers") or []:
        if entry.get("id") != reviewer:
            continue
        listed = [str(name) for name in entry.get("readers") or []]
        if reading_slug(reader) in {reading_slug(name) for name in listed}:
            return
        entry["readers"] = [*listed, reader]
        panel.write_text(_yaml_dump(document), encoding="utf-8", newline="\n")
        return


def _remit_from_earlier_panels(project, reviewer: str, before: int) -> str:
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.review import panels

    for number, path in sorted(panels(project), reverse=True):
        if number >= before:
            continue
        for entry in (read_structured(path) or {}).get("reviewers") or []:
            if entry.get("id") == reviewer:
                return str(entry.get("remit") or "")
    return ""


def write_review(
    project,
    reviewer: str,
    *,
    verdict: str,
    round_number: int = 1,
    reviewed_by: str | None = None,
    remit: str = "",
    summary: str = "",
    reading: str | None = None,
    today: date | None = None,
) -> Written:
    """Record that `reviewer` has read the manuscript as it now stands.

    Written after the reading, not before it: the verdict is required, because a record with
    a placeholder verdict is a claim that somebody looked. Findings are prose and are added
    by editing the file; the point of this command is the part a person cannot be expected to
    get right by hand, which is the digest of what they read.

    `reading` names who made this reading, where the remit is read more than once: a model
    and a co-author, or several models. It is a record of its own beside the reviewer's plain
    one, so a second reader never needs the first one's record to be overwritten.
    """
    import re

    from manuscript_guard.gates.review import (
        file_digests,
        manuscript_digest,
        reading_path,
        reading_slug,
    )

    if not re.fullmatch(r"[a-z][a-z0-9-]*", reviewer):
        raise RecordError(
            f"{reviewer!r} names a file, so it must be lowercase letters, digits and hyphens"
        )
    if verdict not in VERDICTS:
        raise RecordError(f"verdict must be one of {', '.join(VERDICTS)}")
    if round_number < 1:
        raise RecordError("rounds are numbered from 1")
    if reading is not None:
        reading = reading.strip()
        if not reading_slug(reading):
            raise RecordError(
                "--reading names who made this reading and becomes part of the file's name, "
                "so it needs a letter or a digit: openai/<model>, or a person's name"
            )
        if len(reading_slug(reading).encode("utf-8")) > MAX_READER_NAME:
            raise RecordError(
                f"--reading becomes part of the file's name, and this one is over "
                f"{MAX_READER_NAME} bytes; name the reader more shortly"
            )

    today = today or date.today()
    path = reading_path(project, round_number, reviewer, reading)
    if path.exists():
        raise RecordError(
            f"{path.name} already exists in round {round_number}. If the manuscript has "
            f"changed since, re-read it and record the new reading as a further round rather "
            f"than restamping this one — the digest is the only thing separating 'somebody "
            f"read this version' from 'somebody read a version'"
        )

    panel = _ensure_panel(project, round_number, reviewer, remit, today)
    if reading:
        _name_reader(panel, reviewer, reading)

    document = {
        "schema": "manuscript-guard/review/1",
        "round": round_number,
        "reviewer": reviewer,
        **({"reader": reading} if reading else {}),
        "reviewed_by": reviewed_by or reading or reviewer,
        "reviewed_on": today.isoformat(),
        "manuscript_sha256": manuscript_digest(project),
        "file_sha256": dict(sorted(file_digests(project).items())),
        "verdict": verdict,
    }
    if summary:
        document["summary"] = summary
    document["findings"] = []

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Findings go below, each with an id, a severity and the finding itself. An empty\n"
        "# list is a reviewer who found nothing, which is a claim in its own right.\n"
        + _yaml_dump(document),
        encoding="utf-8",
        newline="\n",
    )
    return Written(path=path, panel=panel)


def write_figure_review(
    project,
    figure: str,
    *,
    verdict: str,
    reviewed_by: str | None = None,
    today: date | None = None,
) -> Written:
    """Record that someone has looked at a rendered figure.

    `content_sha256` is a digest of the figure's *content* rather than of the file, and there
    was no way to obtain it: G10 blocked the build asking for a number the toolkit computed
    and never printed.
    """
    from manuscript_guard.gates.figure_review import (
        REQUIRED_CHECKS,
        _representatives,
        review_path,
    )
    from manuscript_guard.gates.figures import content_digest

    if verdict not in FIGURE_VERDICTS:
        raise RecordError(f"verdict must be one of {', '.join(FIGURE_VERDICTS)}")
    if not (reviewed_by or "").strip():
        # Required, unlike a manuscript review, which falls back to the reviewer's panel id.
        # A figure review has no id to fall back to, and the record's whole content is that
        # a particular person looked at a particular rendering.
        raise RecordError("--by is required: a figure review records who looked at it")

    # The same choice the gate makes. A review recorded against the PNG when the gate reads
    # the SVG is a review the gate cannot find, and the figure still reports as unreviewed.
    figures_dir = project.path("figures")
    wanted = Path(figure).stem
    candidates = [p for p in _representatives(figures_dir) if p.stem == wanted]
    if not candidates:
        known = ", ".join(sorted(p.name for p in _representatives(figures_dir))) or "none"
        raise RecordError(f"no reviewable figure called {figure!r}; figures here: {known}")

    path = review_path(candidates[0])
    if path.exists():
        raise RecordError(
            f"{path.name} already exists. Edit it, or delete it and record a fresh reading"
        )

    # Every required check, listed with `ok: false` and the question it asks. Writing them
    # as passed would be the command doing the review; writing none at all produced a file
    # the schema rejects, which reads as a bug rather than as work outstanding. Listed
    # false, the gate names each one that is still false and the file is a to-do list.
    today = today or date.today()
    path.write_text(
        "# One entry per check. Set `ok: true` and write in the note what you actually saw -\n"
        "# a check recorded ok with no note is a tick, and the note is the review.\n"
        + _yaml_dump(
            {
                "schema": "manuscript-guard/figure-review/1",
                "figure": candidates[0].name,
                "content_sha256": content_digest(candidates[0]),
                "reviewed_by": reviewed_by,
                "reviewed_on": today.isoformat(),
                "verdict": verdict,
                "checks": [
                    {"id": check, "ok": False, "note": question}
                    for check, question in REQUIRED_CHECKS.items()
                ],
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    return Written(path=path, panel=None)
