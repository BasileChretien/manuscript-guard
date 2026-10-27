"""Each results value, table and figure the manuscript binds, where it stands: the rows of
BOUND.md, read from a Markdown manuscript or a LaTeX one.

A Markdown file is read as `placeholders.parse` reads it; a LaTeX one as the reader of the
gates reads it (`text/latex/views.bindings`), each binding with the headings in force where
it stands. A LaTeX file nothing inputs is not printed, and is passed over. Past a part the
LaTeX reader refuses, a binding is found by its shape and the headings over it are not known:
`latex_unread` names the first such part, and the package warns of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from manuscript_guard.contracts.project import Project
from manuscript_guard.text.reader import LATEX, manuscript_format

#: The namespaces BOUND.md lists, in the order it lists them.
KINDS = ("results", "table", "figure")
#: The section of a binding above every heading.
NO_HEADING = "before the first heading"


@dataclass(frozen=True)
class BoundRow:
    """One binding: its namespace and key, the file it stands in from the project's root,
    the nearest heading over it, its line, and whether the supplement prints it."""

    namespace: str
    key: str
    file: str
    section: str
    line: int
    supplement: bool


def bound_rows(project: Project) -> list[BoundRow]:
    """Every binding of a results value, table or figure, file by file in the order the
    manuscript's files are read, and in each file in the order they stand."""
    folder = project.path("manuscript")
    if not folder.is_dir():
        return []
    if manuscript_format(folder) == LATEX:
        return _latex_rows(project)
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


def _latex_rows(project: Project) -> list[BoundRow]:
    from manuscript_guard.text.latex.structure import read_document
    from manuscript_guard.text.latex.views import bindings

    folder = project.path("manuscript")
    rows = []
    for supplement in (False, True):
        for source in read_document(folder, supplementary=supplement).sources:
            if source.loose:
                continue
            shown = (folder / source.path).relative_to(project.root).as_posix()
            for placeholder in bindings(source)[0]:
                if placeholder.namespace not in KINDS:
                    continue
                chain = source.chain_at(placeholder.start)
                section = " ".join(chain[-1].title.split()) if chain else ""
                rows.append(BoundRow(placeholder.namespace, placeholder.key, shown,
                                     section or NO_HEADING, placeholder.line,
                                     supplement))  # fmt: skip
    return rows


def latex_unread(project: Project) -> str | None:
    """The first part of a LaTeX manuscript its reader refuses, as `file:line (why)`, or None
    where it reads every part, or the manuscript is Markdown."""
    folder = project.path("manuscript")
    if not folder.is_dir() or manuscript_format(folder) != LATEX:
        return None
    from manuscript_guard.text.latex.structure import read_document

    for supplement in (False, True):
        for path, refusal in read_document(folder, supplementary=supplement).refusals:
            try:
                text = (folder / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return f"manuscript/{path} ({refusal.message})"
            line = text.count("\n", 0, refusal.offset) + 1
            return f"manuscript/{path}:{line} ({refusal.message})"
    return None


__all__ = ["KINDS", "BoundRow", "bound_rows", "latex_unread"]
