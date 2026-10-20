"""Which format a manuscript is written in, and its files in that format.

A manuscript is Markdown or LaTeX, never both (DESIGN.md, "LaTeX manuscripts"). The format is
read from the entry file, `manuscript/main.md` or `manuscript/main.tex`, so nothing declares
it a second time. The gates are taught LaTeX one at a time; until a gate reads it, the gate
reads nothing of a LaTeX manuscript and says so (`not-read-in-latex`).
"""

from __future__ import annotations

import codecs
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
    Markdown project into a LaTeX one, or refused it as two formats). One saved as UTF-16 is
    read as such, so that it is a LaTeX entry and reported as not UTF-8, not taken for an
    empty Markdown folder (round 2). A `\\documentclass` in a comment counts as one."""
    try:
        data = (manuscript_dir / ENTRY[LATEX]).read_bytes()
    except OSError:
        return False
    if data[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        data = data.decode("utf-16", errors="replace").encode("utf-8")
    return b"\\documentclass" in data


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
        """The files of one document in the order the build prints them: the entry file
        first, the rest by name. A LaTeX file's place comes from `\\input` once the include
        tree is read; until then it is this order, which nothing yet builds from."""
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
