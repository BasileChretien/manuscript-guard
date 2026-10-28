"""Each results value, table and figure the manuscript binds, where it stands: the rows of
BOUND.md, read from a Markdown manuscript or a LaTeX one.

A Markdown file is read as `placeholders.parse` reads it; a LaTeX one as the reader of the
gates reads it (`text/latex/views.bindings`), each binding with the headings in force where
it stands. Of a LaTeX manuscript only the `.tex` files its documents print are read: a file
nothing inputs, a second document beside the entry and the author's packages are passed
over. Past a part the LaTeX reader refuses in a file it reads, a binding is found by its
shape and the heading over it is not known: its row says so (`PAST_REFUSAL`), and
`latex_unread` names the first refusal such a row stands after, which the package warns of.
"""

from __future__ import annotations

from dataclasses import dataclass

from manuscript_guard.contracts.project import Project
from manuscript_guard.text.reader import LATEX, manuscript_format

#: The namespaces BOUND.md lists, in the order it lists them.
KINDS = ("results", "table", "figure")
#: The section of a binding above every heading.
NO_HEADING = "before the first heading"
#: The section of a binding found past a part the LaTeX reader refused.
PAST_REFUSAL = "after a part the reader refused; heading not known"


@dataclass(frozen=True)
class BoundRow:
    """One binding: its namespace and key, the file it stands in from the project's root,
    the nearest heading over it, its line, whether the supplement prints it, and whether it
    stands past a part the LaTeX reader refused, where no heading is known."""

    namespace: str
    key: str
    file: str
    section: str
    line: int
    supplement: bool
    past_refusal: bool = False


def bound_rows(project: Project) -> list[BoundRow]:
    """Every binding of a results value, table or figure, file by file in the order the
    manuscript's files are read, and in each file in the order they stand."""
    folder = project.path("manuscript")
    if not folder.is_dir():
        return []
    if manuscript_format(folder) == LATEX:
        return [row for row, _refusal in _latex_rows(project)]
    return _markdown_rows(project)


def _section_at(text: str, line: int) -> str:
    from manuscript_guard.text.sections import split_sections

    title = ""
    for section in split_sections(text):
        if section.line <= line:
            title = section.title
    return title or NO_HEADING


def _markdown_rows(project: Project) -> list[BoundRow]:
    from manuscript_guard.gates.numbers import SUPPLEMENTARY, source_files
    from manuscript_guard.text.placeholders import parse

    folder = project.path("manuscript")
    rows = []
    for path in source_files(folder):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        shown = path.relative_to(project.root).as_posix()
        parts = path.relative_to(folder).parts
        supplement = len(parts) > 1 and parts[0] == SUPPLEMENTARY
        for placeholder in parse(text)[0]:
            if placeholder.namespace in KINDS:
                rows.append(BoundRow(placeholder.namespace, placeholder.key, shown,
                                     _section_at(text, placeholder.line), placeholder.line,
                                     supplement))  # fmt: skip
    return rows


def _latex_rows(project: Project) -> list[tuple[BoundRow, str | None]]:
    """Each row of a LaTeX manuscript, with where the refusal it stands past is, as
    `file:line (why)`, or None."""
    from manuscript_guard.text.latex.structure import read_document
    from manuscript_guard.text.latex.views import bindings

    folder = project.path("manuscript")
    rows = []
    for supplement in (False, True):
        for source in read_document(folder, supplementary=supplement).sources:
            if source.loose or not source.path.lower().endswith(".tex"):
                continue
            shown = (folder / source.path).relative_to(project.root).as_posix()
            refusals = source.reading.refusals
            # As `views._uses` reads a file: past its first refusal, bindings by their shape.
            refused = refusals[0].offset if refusals else None
            for placeholder in bindings(source)[0]:
                if placeholder.namespace not in KINDS:
                    continue
                if refused is not None and placeholder.start >= refused:
                    line = source.text.count("\n", 0, refused) + 1
                    where = f"{shown}:{line} ({refusals[0].message})"
                    rows.append((BoundRow(placeholder.namespace, placeholder.key, shown,
                                          PAST_REFUSAL, placeholder.line, supplement, True),
                                 where))  # fmt: skip
                    continue
                chain = source.chain_at(placeholder.start)
                section = " ".join(chain[-1].title.split()) if chain else ""
                rows.append((BoundRow(placeholder.namespace, placeholder.key, shown,
                                      section or NO_HEADING, placeholder.line, supplement),
                             None))  # fmt: skip
    return rows


def latex_unread(project: Project) -> str | None:
    """The first refusal of the LaTeX reader that a row of BOUND.md stands past, as
    `file:line (why)`, or None where no row does or the manuscript is Markdown. A refusal in
    a file BOUND.md does not read, or with no binding after it, changes no row."""
    folder = project.path("manuscript")
    if not folder.is_dir() or manuscript_format(folder) != LATEX:
        return None
    return next((where for _row, where in _latex_rows(project) if where), None)


__all__ = ["KINDS", "NO_HEADING", "PAST_REFUSAL", "BoundRow", "bound_rows", "latex_unread"]
