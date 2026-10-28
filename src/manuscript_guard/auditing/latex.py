"""A LaTeX paper as `audit` reads it: an entry file and the tree it inputs.

A `.tex` named is an entry. Its folder's `.tex`, `.sty` and `.cls` files are the files its
`\\input`s are looked for in (`structure.read_tree`), as they are for a project's `main.tex`.
In a folder given, every file with `\\documentclass` is an entry, audited as a paper of its
own: an old draft, a cover letter or a template written in LaTeX is one too, so name the
paper's file to audit it alone. The other files are read where an entry inputs them. A file
no entry inputs is not read, and is named under "Passed over", and so is a file a class or a
package inputs, which is the class's text and not the paper's. A file two entries input is
read once, where the first does.

Each file is read as G2 reads one (`gates.numbers._latex_read`): its numbers where they print,
at the `.tex` line they stand on, by the classifier's rules for a file whose headings and
items are commands. The `thebibliography` is cut as a Markdown paper's reference list is, and
named under "Not audited". Each refusal of the reader in a file the entry reads is a stretch
not read as LaTeX, so it is named under "Could not read", where `--strict` counts it. A file
the entry does not read is refused nothing: one that holds a document of its own is an entry,
or is passed over, and so is one nothing inputs (round 1 of #463).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.text.latex.mask import NUL
from manuscript_guard.text.latex.structure import SECOND_DOCUMENT, Document, Source, read_tree
from manuscript_guard.text.latex.tables import latex_tables
from manuscript_guard.text.latex.views import bindings, markdown_view
from manuscript_guard.text.tables import Table

#: A `\\documentclass` outside a comment, which makes a file found in a folder an entry.
_DOCUMENT_CLASS = re.compile(r"^(?:[^%\n]|\\%)*?\\documentclass(?![A-Za-z@])", re.MULTILINE)


@dataclass(frozen=True)
class LatexFile:
    """One file of a tree, as the audit reads it: `hidden` is what prints, NUL where nothing
    does, with the reference list blanked; `layout` the definitions' bodies."""

    path: Path
    source: Source
    hidden: str
    tables: tuple[Table, ...]
    layout: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Tree:
    """One entry's document: the entry, its folder, and the files it reads, by their path."""

    entry: Path
    folder: Path
    document: Document
    files: tuple[tuple[Path, Source], ...]


@dataclass
class LatexRead:
    files: list[LatexFile] = field(default_factory=list)
    trees: list[Tree] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    passed_over: list[str] = field(default_factory=list)
    not_audited: list[str] = field(default_factory=list)


def is_entry(path: Path) -> bool:
    """Whether a `.tex` found in a folder starts a document of its own."""
    from manuscript_guard.audit import UnreadableText, read_text

    try:
        return bool(_DOCUMENT_CLASS.search(read_text(path)))
    except (OSError, UnreadableText):
        return True


def read_latex(entries: list[Path], found: list[Path] = ()) -> LatexRead:
    """Each entry's tree, read; `found` the other `.tex` files a folder given held, which are
    passed over where no entry inputs them."""
    from manuscript_guard.audit import UnreadableText, read_text

    read = LatexRead()
    seen: set[Path] = set()
    classed: set[Path] = set()
    folders: dict[Path, tuple[dict, dict, dict, frozenset]] = {}
    for entry in entries:
        folder = entry.parent
        if folder not in folders:
            folders[folder] = _gathered(folder, read_text, UnreadableText, read.unreadable)
        files, packages, classes, unreadable = folders[folder]
        name = entry.relative_to(folder).as_posix()
        if name not in files:
            continue
        document = read_tree(files, name, packages=packages, unreadable=unreadable,
                             classes=classes)  # fmt: skip
        mine = []
        for source in document.sources:
            if source.loose:
                continue
            path = folder / source.path
            mine.append((path, source))
            if path in seen:
                continue
            seen.add(path)
            read.files.append(_file(path, source))
            read.not_audited += [
                f"{path.name}: lines {source.text.count(chr(10), 0, start) + 1}-"
                f"{source.text.count(chr(10), 0, end) + 1}, read as the reference list"
                for start, end in source.reading.references
            ]
        read.trees.append(Tree(entry, folder, document, tuple(mine)))
        classed.update(folder / path for path in document.classes)
        # A refusal counts only in a file the entry reads. One that holds a document of its
        # own is an entry, or passed over, and so is one nothing inputs: refused there, each
        # was said not to be read though it was, or failed --strict as passed over.
        texts = {source.path: source.text for source in document.sources if not source.loose}
        for where, refusal in document.refusals:
            if where not in texts or refusal.code == SECOND_DOCUMENT:
                continue
            text = texts[where]
            line = text.count("\n", 0, refusal.offset) + 1
            read.unreadable.append(
                f"{where}: line {line} is not read as LaTeX, so what follows it in the file "
                f"was read as typed: {refusal.message}"
            )
    for path in sorted({*found, *(p for folder in folders for p in folder.rglob("*.tex"))}):
        if path in seen or path in entries:
            continue
        if path in classed:
            read.passed_over.append(
                f"{path.as_posix()}: a class or a package the paper loads inputs it, so it is "
                "theirs and not the paper's text, and was not read"
            )
        else:
            read.passed_over.append(
                f"{path.as_posix()}: no entry inputs it, so it was not read; name it, or "
                "\\input it from the paper's main file"
            )
    return read


def _gathered(folder: Path, read_text, unreadable_error, said: list[str]):
    """The folder's `.tex`, `.sty` and `.cls` files by their path from it, and the files that
    could not be read, which are named."""
    found: list[dict[str, str]] = [{}, {}, {}]
    failed: set[str] = set()
    for which, suffix in enumerate((".tex", ".sty", ".cls")):
        for path in sorted(folder.rglob(f"*{suffix}")):
            if not path.is_file():
                continue
            name = path.relative_to(folder).as_posix()
            try:
                found[which][name] = read_text(path)
            except (OSError, unreadable_error) as exc:
                if suffix == ".tex":
                    failed.add(name)
                said.append(str(exc))
    return found[0], found[1], found[2], frozenset(failed)


def _file(path: Path, source: Source) -> LatexFile:
    placeholders, _malformed = bindings(source)
    scanned = list(markdown_view(source, placeholders, blank=NUL))
    # The reference list is blanked as `gates.numbers._latex_read` blanks it: its years
    # and pages are no numbers of the paper's.
    for start, end in source.reading.references:
        for index in range(start, min(end, len(scanned))):
            if scanned[index] not in "\r\n":
                scanned[index] = NUL
    return LatexFile(path, source, "".join(scanned), tuple(latex_tables(source)),
                     source.reading.bodies)  # fmt: skip
