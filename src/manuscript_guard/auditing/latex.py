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

from manuscript_guard.text.latex.mask import NUL, Refusal, read
from manuscript_guard.text.latex.structure import (
    SECOND_DOCUMENT,
    Document,
    Source,
    _target,
    read_past_stop,
    read_tree,
)
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
    #: The input encoding its folder's files declare and were read in, or None for UTF-8
    #: (`text.latex.encodings`).
    encoding: str | None = None


@dataclass
class LatexRead:
    files: list[LatexFile] = field(default_factory=list)
    trees: list[Tree] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    passed_over: list[str] = field(default_factory=list)
    not_audited: list[str] = field(default_factory=list)


def is_entry(path: Path) -> bool:
    """Whether a `.tex` found in a folder starts a document of its own. One that cannot be
    read, UTF-16 with no byte-order mark or a renamed .doc, says nothing of the kind, and is
    passed over: taken for an entry, it failed `--strict` beside a Markdown paper (round 2
    of #463). Named, it is an entry, and its reading fails where it fails."""
    from manuscript_guard.audit import UnreadableText, read_text

    try:
        return bool(_DOCUMENT_CLASS.search(read_text(path)))
    except (OSError, UnreadableText):
        return False


def unreadable_said(path: Path) -> str | None:
    """Why a `.tex` found in a folder cannot be read, or None where it can: what the report
    says of it, rather than that no entry inputs it or that it has no `\\documentclass`."""
    from manuscript_guard.audit import UnreadableText, read_text

    try:
        read_text(path)
    except (OSError, UnreadableText) as exc:
        said = str(exc).removeprefix(f"{path.name}: ")  # the error names the file itself
        return f"{path.as_posix()} could not be read, so it was not audited: {said}"
    return None


def read_latex(entries: list[Path], found: list[Path] = ()) -> LatexRead:
    """Each entry's tree, read; `found` the other `.tex` files a folder given held, which are
    passed over where no entry inputs them."""
    from manuscript_guard.audit import UnreadableText, read_text
    from manuscript_guard.text.latex import encodings

    read = LatexRead()
    seen: set[Path] = set()
    classed: set[Path] = set()
    folders: dict[Path, tuple[dict, dict, dict, frozenset, str | None]] = {}
    decoded: dict[tuple[Path, str], tuple[dict, dict, dict, frozenset, str | None]] = {}
    unfollowed: dict[Path, list[str]] = {}
    inside: dict[Path, list[str]] = {}
    for entry in entries:
        folder = entry.parent
        if folder not in folders:
            folders[folder] = _gathered(folder, read_text, UnreadableText, read.unreadable)
        files, packages, classes, unreadable, _encoding = folders[folder]
        name = entry.relative_to(folder).as_posix()
        if name not in files:
            continue
        # The encoding the entry's tree declares, read once with each declaration as
        # UTF-8's so that none stops the reading (round 2 of #637).
        named = encodings.in_tree(read_tree(
            {path: encodings.as_utf8(text) for path, text in files.items()}, name,
            packages={path: encodings.as_utf8(text) for path, text in packages.items()},
            unreadable=unreadable, classes=classes), {**files, **packages})  # fmt: skip
        if named:
            files, packages, classes, unreadable, _encoding = decoded.setdefault(
                (folder, named), _gathered(folder, read_text, UnreadableText, [], named))
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
        read.trees.append(Tree(entry, folder, document, tuple(mine), named))
        unfollowed = {**_unfollowed(document, files, name, folder), **unfollowed}
        for path, blocks in _inside_blocks(document, files, name, folder).items():
            inside.setdefault(path, []).extend(blocks)
        classed.update(folder / path for path in document.classes)
        # A refusal counts only in a file the entry reads. One that holds a document of its
        # own is an entry, or passed over, and so is one nothing inputs: refused there, each
        # was said not to be read though it was, or failed --strict as passed over.
        texts = {source.path: source.text for source in document.sources if not source.loose}
        stops = _stops(document)
        ends = {where: line for where, line in stopped([read.trees[-1]])}
        for where, refusal in document.refusals:
            if where not in texts or refusal.code == SECOND_DOCUMENT:
                continue
            text = texts[where]
            line = text.count("\n", 0, refusal.offset) + 1
            if refusal.end >= 0:
                # A block skipped to its end, and the file read on past it (2026-11-13).
                read.unreadable.append(f"{where}: {_lines(text, refusal)} skipped, which no "
                                       f"check read: {refusal.message}")  # fmt: skip
                continue
            # One the tree makes, an input it cannot follow or an encoding, leaves the file
            # read past it (round 1 of #637: it was said not to be).
            read.unreadable.append(
                f"{where}: not read past line {line}, which is not read as LaTeX, so no check "
                f"read what follows it in the file: {refusal.message}"
                if (where, refusal) in stops else
                f"{where}, line {line}: {refusal.message}; the rest of the file was read"
                + (f" to line {ends[where]}, past which it was not" if where in ends else "")
            )
    for path in sorted({*found, *(p for folder in folders for p in folder.rglob("*.tex"))}):
        if path in seen or path in entries:
            continue
        if path in classed:
            read.passed_over.append(
                f"{path.as_posix()}: a class or a package the paper loads inputs it, so it is "
                "theirs and not the paper's text, and was not read"
            )
        elif (said := unreadable_said(path)) is not None:
            # In an entry's folder it is named already, as what could not be read there.
            if not any(folder in path.parents for folder in folders):
                read.passed_over.append(said)
        elif stopped_in := unfollowed.get(path):
            # The file that inputs it may do so past where its reading stopped (round 1 of
            # #637: the advice was to input it, which the paper did).
            read.passed_over.append(
                f"{path.as_posix()}: no file the audit read inputs it, so it was not read; "
                f"{', and '.join(dict.fromkeys(stopped_in))}, and what a file inputs past "
                "where it stopped is not followed"
            )
        elif blocks := inside.get(path):
            # The paper inputs it, from a block no check reads (round 1 of #674: the advice
            # was to input it, which the paper did).
            read.passed_over.append(
                f"{path.as_posix()}: it is input only from inside a block the reader skipped "
                f"({', '.join(dict.fromkeys(blocks))}), so it was not read; input it outside "
                "the block, or name it"
            )
        else:
            read.passed_over.append(
                f"{path.as_posix()}: no entry inputs it, so it was not read; name it, or "
                "\\input it from the paper's main file"
            )
    return read


def _unfollowed(document: Document, files: dict, entry: str, folder: Path) -> dict:
    """Each file the inputs past where a file of `document` stopped reach, through the files
    they input, by its path, with where that file stopped: the inputs as the reader records
    them, a braceless `\\input` and an `\\import` among them, not one in a comment (round 3
    of #637: typed inputs in the stopped file alone were looked for)."""
    reached = {source.path for source in document.sources if not source.loose}
    said: dict[Path, list[str]] = {}
    for source in document.sources:
        if source.loose or not source.reading.refusals:
            continue
        line = source.text.count("\n", 0, source.reading.refusals[0].offset) + 1
        pending = [put for past in read_past_stop(source) for put in past.inputs]
        while pending:
            put = pending.pop()
            target = _target(entry, put, "", files)[0]
            if target is not None and target not in reached:
                reached.add(target)
                said[folder / target] = [f"{source.path} was not read past line {line}"]
                pending += read(files[target], body=put.body,
                                environments=put.environments).inputs  # fmt: skip
    return said


#: An `\\input` or an `\\include` with its path in braces, as a skipped block holds one.
_BLOCK_INPUT = re.compile(r"\\(?:input|include)(?![A-Za-z@])\s*\{([^{}\n]*)\}")
#: A comment, to its line's end, which inputs nothing.
_BLOCK_COMMENT = re.compile(r"(?<!\\)%[^\n]*")


def _inside_blocks(document: Document, files: dict, entry: str,
                   folder: Path) -> dict[Path, list[str]]:  # fmt: skip
    """Each file an `\\input` or an `\\include` inside a block the reader skipped names, by
    its path, with the block, as `file, lines A-B`: no check read the block, so the reader
    followed none of them (round 1 of #674)."""
    from manuscript_guard.text.latex.mask import Input

    said: dict[Path, list[str]] = {}
    for source in document.sources:
        if source.loose:
            continue
        for block in source.reading.skipped:
            held = _BLOCK_COMMENT.sub(lambda found: " " * len(found.group(0)),
                                      source.text[block.offset : block.end])  # fmt: skip
            for put in _BLOCK_INPUT.finditer(held):
                at = block.offset + put.start()
                target = _target(entry, Input(at, at + len(put.group(0)), put.group(1).strip(),
                                              True, ()), "", files)[0]  # fmt: skip
                if target is not None:
                    said.setdefault(folder / target, []).append(
                        f"{source.path}, {_lines(source.text, block)}")
    return said


def _stops(document: Document) -> set[tuple[str, Refusal]]:
    """Each refusal of `document` at which its file's reading stopped, with the file's path:
    not one the tree makes, which leaves the file read past it."""
    return {(source.path, refusal) for source in document.sources
            for refusal in source.reading.refusals}  # fmt: skip


def stopped(trees: list[Tree]) -> list[tuple[str, int]]:
    """Each file a tree reads that the reader stopped in, by its path in the folder, with the
    line it stopped on, once: what the audit's summary says, since past that line no check
    read it (Basile, 2026-11-11: it said "nothing reported" of a paper read to its preamble)."""
    said: list[tuple[str, int]] = []
    for tree in trees:
        texts = {source.path: source.text for _path, source in tree.files}
        stops = _stops(tree.document)
        for where, refusal in tree.document.refusals:
            if where not in texts or (where, refusal) not in stops:
                continue
            one = (where, texts[where].count("\n", 0, refusal.offset) + 1)
            if one not in said:
                said.append(one)
    return said


def _lines(text: str, block: Refusal) -> str:
    """The lines a skipped block runs over, its first to the one its end stands on: "line 4"
    or "lines 4-9"."""
    first = text.count("\n", 0, block.offset) + 1
    last = text.count("\n", 0, max(block.end - 1, block.offset)) + 1
    return f"line {first}" if first == last else f"lines {first}-{last}"


def skipped(trees: list[Tree]) -> list[tuple[str, str]]:
    """Each block a tree's reader skipped in a file it reads, by the file's path in the folder,
    with the lines it runs over, once: what the audit's summary says beside where a file
    stopped, since no check read those lines (2026-11-13)."""
    said: list[tuple[str, str]] = []
    for tree in trees:
        texts = {source.path: source.text for _path, source in tree.files}
        for where, refusal in tree.document.refusals:
            if where in texts and refusal.end >= 0:
                one = (where, _lines(texts[where], refusal))
                if one not in said:
                    said.append(one)
    return said


def _gathered(folder: Path, read_text, unreadable_error, said: list[str],
              named: str | None = None):  # fmt: skip
    """The folder's `.tex`, `.sty` and `.cls` files by their path from it, the files that
    could not be read, which are named, and the input encoding they were read in: `named`,
    one of `encodings.CODECS` that an entry's tree declares, else UTF-8 (None). Read in it,
    each declaration of it is written as UTF-8's (`encodings.as_utf8`)."""
    from manuscript_guard.text.latex import encodings

    paths: list[tuple[int, str, Path]] = []
    for which, suffix in enumerate((".tex", ".sty", ".cls")):
        paths += [(which, path.relative_to(folder).as_posix(), path)
                  for path in sorted(folder.rglob(f"*{suffix}")) if path.is_file()]  # fmt: skip
    codec = encodings.CODECS[named] if named else None
    found: list[dict[str, str]] = [{}, {}, {}]
    failed: set[str] = set()
    for which, name, path in paths:
        try:
            text = read_text(path, codec)
        except (OSError, unreadable_error) as exc:
            if which == 0:
                failed.add(name)
            said.append(str(exc))
            continue
        found[which][name] = encodings.as_utf8(text) if codec else text
    return found[0], found[1], found[2], frozenset(failed), named


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
