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


def _printed_at(sources: list) -> dict[str, tuple[int, ...]]:
    """Where each file of a document starts in what the build prints, as the offsets of the
    `\\input`s that lead to it from the entry: a place in a file is then its file's key and
    its offset, and two places compare as they are printed."""
    keys: dict[str, tuple[int, ...]] = {}
    for source in sources:  # in the order the build prints them, each after its parent
        keys.setdefault(source.path, ())
        for offset, target in source.targets:
            keys.setdefault(target, (*keys[source.path], offset))
    return keys


def _first_refusal(document) -> tuple[tuple[int, ...], str] | None:
    """Where the first refusal of a document stands in what the build prints, and the
    refusal as `file:line (why)`: the reader's in a `.tex` file it reads, or the tree's at a
    place in one, an `\\input` it cannot follow. A package's or a class's refusal stands in
    no place of the text the build prints, and a second document beside the entry is not
    read at all."""
    read = {source.path: source for source in document.sources if not source.loose}
    keys = _printed_at(list(read.values()))
    found = sorted(
        (((*keys[at], refusal.offset), at, refusal) for at, refusal in document.refusals
         if at in read and at in keys and at.lower().endswith(".tex")),
        key=lambda one: (one[0], one[1]),
    )  # fmt: skip
    if not found:
        return None
    key, at, refusal = found[0]
    line = read[at].text.count("\n", 0, refusal.offset) + 1
    return key, f"manuscript/{at}:{line} ({refusal.message})"


def _documents(project: Project) -> list[tuple[bool, object]]:
    from manuscript_guard.text.latex.structure import read_document

    folder = project.path("manuscript")
    return [(supplement, read_document(folder, supplementary=supplement))
            for supplement in (False, True)]  # fmt: skip


def _latex_rows(project: Project) -> list[tuple[BoundRow, str | None]]:
    """Each row of a LaTeX manuscript, with the refusal it is printed after, as
    `file:line (why)`, or None: what is printed after the document's first refusal, in that
    file or in any file read after it, stands where no heading is known."""
    from manuscript_guard.text.latex.views import bindings

    folder = project.path("manuscript")
    rows = []
    for supplement, document in _documents(project):
        read = [source for source in document.sources if not source.loose]
        keys = _printed_at(read)
        first = _first_refusal(document)
        for source in read:
            if not source.path.lower().endswith(".tex"):
                continue
            shown = (folder / source.path).relative_to(project.root).as_posix()
            for placeholder in bindings(source)[0]:
                if placeholder.namespace not in KINDS:
                    continue
                if first is not None and (*keys.get(source.path, ()), placeholder.start) \
                        >= first[0]:  # fmt: skip
                    rows.append((BoundRow(placeholder.namespace, placeholder.key, shown,
                                          PAST_REFUSAL, placeholder.line, supplement, True),
                                 first[1]))  # fmt: skip
                    continue
                chain = source.chain_at(placeholder.start)
                section = " ".join(chain[-1].title.split()) if chain else ""
                rows.append((BoundRow(placeholder.namespace, placeholder.key, shown,
                                      section or NO_HEADING, placeholder.line, supplement),
                             None))  # fmt: skip
    return rows


def latex_unread(project: Project) -> str | None:
    """What BOUND.md cannot place of a LaTeX manuscript, said as a clause, or None where it
    places every binding or the manuscript is Markdown: each `.tex` file holding a binding
    that nothing the reader reads inputs, which it does not list, with the refusal the reader
    stopped at where there is one; and the first refusal a row is printed after, whose
    heading is not known. A refusal with nothing bound after it changes no row."""
    from manuscript_guard.text.latex.views import bindings

    folder = project.path("manuscript")
    if not folder.is_dir() or manuscript_format(folder) != LATEX:
        return None
    said = []
    for _supplement, document in _documents(project):
        loose = [f"manuscript/{source.path}" for source in document.sources
                 if source.loose and source.path.lower().endswith(".tex")
                 and any(p.namespace in KINDS for p in bindings(source)[0])]  # fmt: skip
        if loose:
            first = _first_refusal(document)
            said.append(", ".join(loose) + (" holds" if len(loose) == 1 else " hold")
                        + " bindings, and nothing the reader reads inputs "
                        + ("it" if len(loose) == 1 else "them") + ", so they are not listed"
                        + (f" (the reader stops at {first[1]})" if first else ""))
    past = next((where for _row, where in _latex_rows(project) if where), None)
    if past is not None:
        said.append(f"past {past}, which the reader refuses, each binding is listed with no "
                    "heading known")  # fmt: skip
    return "; ".join(said) or None


__all__ = ["KINDS", "NO_HEADING", "PAST_REFUSAL", "BoundRow", "bound_rows", "latex_unread"]
