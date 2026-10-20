"""G0: a manuscript is written in one format, and a gate not yet taught LaTeX says so.

The format is read from the entry file (`text/reader.py`). A folder holding both `main.md`
and `main.tex` is refused (`two-formats`): which one the paper is would be a guess. In a LaTeX
manuscript, a Markdown file the gates would read is refused too (`other-format-file`): left
alone, it would be text that no gate reads and no build prints. Both fail at every stage, as
`manuscript-unreadable` does.

The gates are taught LaTeX one at a time (DESIGN.md, "LaTeX manuscripts"). Until a gate reads
it, the gate does not run on a LaTeX manuscript and reports one `not-read-in-latex` instead.
That finding fails from `submission` and is a note before it, so a manuscript only part of the
gates can read is never passed for submission.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.reader import ENTRY, LATEX, MARKDOWN, manuscript_format

GATE = "G0"


def check_format(project: Project) -> Report:
    """`two-formats` for a folder with both entry files; `other-format-file` for each Markdown
    file the gates would read in a LaTeX manuscript."""
    folder = project.path("manuscript")
    if (folder / ENTRY[MARKDOWN]).is_file() and (folder / ENTRY[LATEX]).is_file():
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="two-formats",
                    message=f"{_shown(project, folder)} holds both {ENTRY[MARKDOWN]} and "
                    f"{ENTRY[LATEX]}: a manuscript is written in one format, and which one this "
                    "is would be a guess",
                    path=folder / ENTRY[LATEX],
                    hint="keep the entry file you write in, and move the other into a folder "
                    "whose name starts with '_'",
                ),
            )
        )
    if manuscript_format(folder) != LATEX:
        return Report()
    return Report(
        tuple(
            Finding(
                gate=GATE,
                code="other-format-file",
                message=f"{_shown(project, path)} is Markdown in a LaTeX manuscript: no gate "
                "reads it and no build prints it",
                path=path,
                hint="write it in LaTeX and \\input it from main.tex, or move it into a "
                "folder whose name starts with '_'",
            )
            for path in source_files(folder)
        )
    )


def not_read_in_latex(gate: str) -> Finding:
    """The one finding a gate not yet taught LaTeX reports instead of running."""
    return Finding(
        gate=gate,
        code="not-read-in-latex",
        message=f"{gate} does not read LaTeX yet, so it read nothing of this manuscript",
        hint="a LaTeX manuscript cannot pass submission until every gate reads it",
    )


def _shown(project: Project, path) -> str:
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:  # `paths:` can put the manuscript outside the project
        return str(path)
