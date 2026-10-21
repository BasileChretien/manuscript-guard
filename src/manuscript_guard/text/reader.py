"""Which format a manuscript is written in, and its files in that format.

A manuscript is Markdown or LaTeX, never both (DESIGN.md, "LaTeX manuscripts"). The format is
read from the entry file, `manuscript/main.md` or `manuscript/main.tex`, so nothing declares
it a second time. The gates are taught LaTeX one at a time; until a gate reads it, the gate
reads nothing of a LaTeX manuscript and says so (`not-read-in-latex`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MARKDOWN = "markdown"
LATEX = "latex"

#: The files of each format the gates read, by the pattern `source_files` walks them with.
GLOBS = {MARKDOWN: "*.md", LATEX: "*.tex"}
#: The entry file of each format, which `printed_order` puts first.
ENTRY = {MARKDOWN: "main.md", LATEX: "main.tex"}


def manuscript_format(manuscript_dir: Path) -> str:
    """LaTeX where the entry file is `main.tex` and there is no `main.md`; Markdown otherwise,
    which every project was before LaTeX was read. A folder holding both is Markdown here and
    refused by G0 (`two-formats`)."""
    latex = latex_entry(manuscript_dir)
    return LATEX if latex and not (manuscript_dir / ENTRY[MARKDOWN]).is_file() else MARKDOWN


def latex_entry(manuscript_dir: Path) -> bool:
    """Whether `main.tex` is a LaTeX document's entry file: it declares its class. A file of
    that name without `\\documentclass` is a fragment, a header pandoc includes for instance,
    and a Markdown manuscript beside it stays one (round 1 of #370: such a file turned a
    Markdown project into a LaTeX one, or refused it as two formats). One saved as UTF-16 or
    UTF-32, with a byte-order mark or without, is seen too, so that it is a LaTeX entry and
    not taken for an empty Markdown folder (rounds 2 and 3). A `\\documentclass` in a comment
    counts as one."""
    try:
        data = (manuscript_dir / ENTRY[LATEX]).read_bytes()
    except OSError:
        return False
    return any(_CLASS.encode(encoding) in data for encoding in _ENCODINGS)


_CLASS = "\\documentclass"
_ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")


@dataclass(frozen=True)
class Reader:
    """The manuscript's files, read in its format. Built once for a project by `reader_for`.

    It lists files for now. The masks, sections, bindings and citations the gates read come
    to it one step at a time, each as a gate is taught LaTeX."""

    manuscript_dir: Path
    format: str

    def files(self, *, main_text_only: bool = False) -> list[Path]:
        """Every source of the manuscript's format, as `source_files` lists Markdown ones."""
        from manuscript_guard.gates.numbers import source_files

        return source_files(
            self.manuscript_dir, main_text_only=main_text_only, glob=GLOBS[self.format]
        )

    def printed_order(self, paths: list[Path], *, supplementary: bool) -> list[Path]:
        """The files of one document in the order the build prints them: for Markdown the
        entry file first and the rest by name; for LaTeX the order `\\input` reads them in, a
        file nothing inputs after them by name."""
        if self.format == LATEX:
            from manuscript_guard.text.latex.structure import read_document

            document = read_document(self.manuscript_dir, supplementary=supplementary)
            rank = {source.path: index for index, source in enumerate(document.sources)}

            def placed(path: Path) -> tuple[int, str]:
                name = path.relative_to(self.manuscript_dir).as_posix()
                return rank.get(name, len(rank)), name

            return sorted(paths, key=placed)
        if supplementary:
            return sorted(paths, key=lambda path: path.name)
        entry = ENTRY[self.format]
        first = [path for path in paths if path.name == entry]
        rest = sorted((path for path in paths if path.name != entry), key=lambda p: p.name)
        return first + rest


def reader_for(project) -> Reader:
    """The reader of a project's manuscript."""
    folder = project.path("manuscript")
    return Reader(folder, manuscript_format(folder))


def manuscript_files(project, *, main_text_only: bool = False) -> list[Path]:
    """Every source of a project's manuscript, in its format."""
    return reader_for(project).files(main_text_only=main_text_only)


@dataclass(frozen=True)
class Bound:
    """One manuscript file with its bindings, the `Placeholder` records of
    `placeholders.parse`: its text as typed, and as Markdown writes it, which for a LaTeX file
    is its Markdown view (`text/latex/views.py`), `\\mg{results.key}` as `{{results.key}}` at
    the same offsets, and for a Markdown file the text itself."""

    path: Path
    text: str
    view: str
    placeholders: list
    latex: bool = False


def bound_files(project) -> list[Bound]:
    """Each manuscript file with its bindings, in its format. A Markdown file that cannot be
    read raises `Unreadable`, as `read_text` does; a LaTeX one is passed over by the include
    tree, and named by the check that reads every file first."""
    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.views import files

        return [Bound(found.path, found.text, found.view, list(found.placeholders), latex=True)
                for found in files(folder)]  # fmt: skip
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.placeholders import parse

    bound = []
    for path in source_files(folder):
        text = read_text(path)
        bound.append(Bound(path, text, text, parse(text)[0]))
    return bound


def citation_uses(project) -> list:
    """Every citation of the manuscript, as `zotero.find_citations` gives the `CitationUse`
    records: a Markdown file's `[@key]` and `@key`, and a LaTeX file's citation commands
    (`text/latex/cite.py`), `\\nocite{*}` as each key of `references.bib`. A Markdown file
    that cannot be read raises `Unreadable`, as `read_text` does."""
    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.gates.citations import bib_keys
        from manuscript_guard.text.latex.cite import citations
        from manuscript_guard.text.latex.views import files

        every = tuple(sorted(bib_keys(project)))
        return [use for found in files(folder) for use in citations(found.source, found.path,
                                                                     every)]  # fmt: skip
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.zotero import find_citations

    uses = []
    for path in source_files(folder):
        uses.extend(find_citations(read_text(path), path))
    return uses
