"""A LaTeX manuscript's files as `\\input` joins them (DESIGN.md, "LaTeX manuscripts").

The entry file is read first, and each file it inputs where its `\\input` stands, depth
first: that order is the order the build prints. A file starts in the state its `\\input`
stands in: body or preamble, inside the environments open there, and under the headings in
force there, so that `p < 0.05` in a file input under `\\section{Methods}` is read under
Methods. A path resolves from the entry file's folder, as TeX resolves it, with `.tex` added
where it has no suffix. The import package's `\\import{folder}{file}` names the file in that
folder of the manuscript's, and `\\subimport{folder}{file}` the file in that folder under the
one the file it stands in was imported from. An `\\input` in an imported file that the entry
file's folder does not hold is looked for in the folder it was imported from, as the package
has LaTeX look for it.

Refused, where the `\\input` stands: a path not written out in full, one outside the
manuscript or under a folder set aside, a file that is not there, and a file that inputs
itself. A bare name input from the preamble that the manuscript does not hold, such as
`\\input{glyphtounicode}`, is the distribution's, and is passed over as a package is. A file
input twice is read once, where it is first input. A package of the author's,
`\\usepackage{macros}` with `macros.sty` beside the entry file, is read as preamble with `@` a
letter; `mgvalues.sty`, which the tool writes, is not. A `.tex` file nothing inputs is read as
loose body under no heading, and is warned of.
"""

from __future__ import annotations

import posixpath
from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from manuscript_guard.text.latex.mask import Heading, Input, Reading, Refusal, read

ENTRY = "main.tex"
SUPPLEMENT_ENTRY = "supplementary/main.tex"
#: The values file the tool writes, never read as the author's package.
VALUES = "mgvalues"
_NOT_WRITTEN_OUT = set("\\#$%{}~")


@dataclass(frozen=True)
class Source:
    """One file of the document: its text, how it reads, the headings over its start, the
    headings in force after each file it inputs, which that file's own headings change, the
    environments its `\\input` stands in, which it is read inside, the file each of its
    inputs names, by where the input stands, as the tree resolved it, and the folder the
    import package imported it from, "" where it imported none (`_target`)."""

    path: str
    text: str
    reading: Reading
    under: tuple[Heading, ...] = ()
    loose: bool = False
    resumes: tuple[tuple[int, tuple[Heading, ...]], ...] = ()
    environments: tuple[str, ...] = ()
    targets: tuple[tuple[int, str], ...] = ()
    imported: str = ""

    def chain_at(self, offset: int) -> tuple[Heading, ...]:
        """The headings in force at `offset` of this file: those it started under, its own,
        and those a file it input left in force where its `\\input` ends. Where an `\\input`
        ends and a heading starts at one offset, the heading comes after (round 1 of #385:
        `\\input{a}\\section{B}` lost B). Found by bisection in the chains worked out once,
        since G2 asks at every number (step 4)."""
        starts, chains = self._chains
        before = bisect_left(starts, offset)
        return chains[before - 1] if before else self.under

    @cached_property
    def _chains(self) -> tuple[list[int], list[tuple[Heading, ...]]]:
        """Where the headings in force change, and what they are from there on."""
        events = sorted(
            [(heading.start, heading, ()) for heading in self.reading.headings]
            + [(end, None, after) for end, after in self.resumes],
            key=lambda event: (event[0], event[1] is not None),
        )
        chain, starts, chains = self.under, [], []
        for start, heading, after in events:
            chain = _folded(chain, heading) if heading is not None else after
            starts.append(start)
            chains.append(chain)
        return starts, chains


def _folded(chain: tuple[Heading, ...], heading: Heading) -> tuple[Heading, ...]:
    """`chain` with `heading` closing the ones of its level or below, then added."""
    return (*(kept for kept in chain if kept.level < heading.level), heading)


def _starts_under(chain: tuple[Heading, ...]) -> tuple[Heading, ...]:
    """The headings a file input at a point starts under: those in force there."""
    return chain


def _resumed(before: tuple[Heading, ...], after: tuple[Heading, ...]) -> tuple[Heading, ...]:
    """The headings in force past an `\\input`: those the input file left in force, its own
    headings with them, as LaTeX reads them on in the file that input it."""
    return after


def _distributed(put: Input) -> bool:
    """An `\\input` from the preamble of a bare name the manuscript does not hold, such as
    `\\input{glyphtounicode}`: TeX finds it in its distribution, as it finds a package, and it
    is not the author's (round 1 of #385: it was refused). So is TeX's form without braces,
    `\\input glyphtounicode`, whose path the reader does not take."""
    name = put.path.strip()
    bare = not set(name) & (_NOT_WRITTEN_OUT | {"/"}) and not name.startswith(("_", "."))
    return not put.body and bare and put.via == "input"


def _target(
    entry: str, put: Input, imported: str, files: Mapping[str, str]
) -> tuple[str | None, str, str]:
    """The file an input names, or None and why not, and the folder the file it names is
    imported from: `imported` is the one the file the input stands in was imported from, ""
    for the entry file's. An `\\input` keeps it, and is looked for there where the entry
    file's folder does not hold it; an `\\import` and a `\\subimport` name a new one."""
    if put.via == "input":
        target, why = resolve(entry, put.path, files)
        if target is None and imported and put.path.strip():
            found, _why = resolve(entry, posixpath.join(imported, put.path), files)
            if found is not None:
                return found, "", imported
        return target, why, imported
    if not put.path.strip():
        said = "a folder and a file are not both written in braces after it"
        return None, f"{said}: write \\{put.via}{{folder}}{{file}}", imported
    folder = put.folder if put.via == "import" else posixpath.join(imported, put.folder)
    target, why = resolve(entry, posixpath.join(folder, put.path), files)
    under = posixpath.normpath(folder)
    return target, why, "" if under == "." else under


@dataclass(frozen=True)
class Document:
    """The files in the order the build prints them, loose ones after, and every refusal with
    the file it is in."""

    sources: tuple[Source, ...]
    refusals: tuple[tuple[str, Refusal], ...]

    @property
    def loose(self) -> tuple[str, ...]:
        return tuple(source.path for source in self.sources if source.loose)


def resolve(entry: str, written: str, files: Mapping[str, str]) -> tuple[str | None, str]:
    """The file an `\\input` names, from the entry file's folder, or None and why not."""
    if not written.strip():
        return None, "no path is written in braces after it: write \\input{path}"
    if set(written) & _NOT_WRITTEN_OUT:
        return None, f"the path {written!r} is not written out in full"
    name = written.strip()
    if not posixpath.splitext(name)[1]:
        name += ".tex"
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(entry), name))
    if posixpath.isabs(name) or joined.startswith("../") or joined == "..":
        return None, f"{written} is outside the manuscript folder"
    if any(part.startswith(("_", ".")) for part in joined.split("/")):
        return None, f"{written} is under a folder set aside, whose name starts with '_' or '.'"
    if joined not in files:
        return None, f"{joined} is not in the manuscript folder"
    return joined, ""


def read_tree(
    files: Mapping[str, str],
    entry: str = ENTRY,
    *,
    packages: Mapping[str, str] | None = None,
    unreadable: frozenset[str] = frozenset(),
) -> Document:
    """The document `entry` begins, its files given by path; `packages` the author's `.sty`
    files; `unreadable` files that could not be read, reported elsewhere and passed over. A
    command one file defines with delimited parameters is refused where another uses it, and
    a command of a class's front matter one file defines is the author's in another, so a
    tree that defines either is read twice, the second time with every file told of them. A
    file nothing inputs defines nothing the document uses (round 2)."""
    document = _read_tree(files, entry, packages or {}, unreadable, frozenset(), frozenset())
    tree = [source for source in document.sources if not source.loose]
    delimited = frozenset(name for source in tree
                          for name in source.reading.delimited)  # fmt: skip
    own = frozenset(name for source in tree for name in source.reading.own)
    if not delimited and not own:
        return document
    return _read_tree(files, entry, packages or {}, unreadable, delimited, own)


def _read_tree(
    files: Mapping[str, str],
    entry: str,
    packages: Mapping[str, str],
    unreadable: frozenset[str],
    delimited: frozenset[str],
    own: frozenset[str],
) -> Document:
    """`read_tree`, each file told of the commands `delimited` and `own` name."""
    known = {**files, **dict.fromkeys(unreadable, "")}
    sources: list[Source] = []
    refusals: list[tuple[str, Refusal]] = []
    seen: set[str] = set()

    def visit(
        path: str,
        body: bool | None,
        environments: tuple[str, ...],
        under: tuple[Heading, ...],
        chain: tuple[str, ...],
        imported: str = "",
    ) -> tuple[Heading, ...]:
        """Read one file and the files it inputs, where they stand, and give the headings
        in force at its end; `imported` the folder it was imported from (`_target`)."""
        text = files[path]
        reading = read(text, body=body, environments=environments, delimited=delimited,
                       own=own)  # fmt: skip
        place = len(sources)
        sources.append(Source(path, text, reading, under, environments=environments,
                              imported=imported))  # fmt: skip
        refusals.extend((path, refusal) for refusal in reading.refusals)
        for _at, name in reading.packages:
            style = posixpath.join(posixpath.dirname(entry), f"{name}.sty")
            if name != VALUES and style in packages and style not in seen:
                seen.add(style)
                package = read(packages[style], body=False, package=True, delimited=delimited,
                               own=own)  # fmt: skip
                sources.append(Source(style, packages[style], package))
                refusals.extend((style, refusal) for refusal in package.refusals)
        events = sorted(
            [(heading.start, heading, None) for heading in reading.headings]
            + [(put.offset, None, put) for put in reading.inputs],
            key=lambda event: event[0],
        )
        current, resumes, targets = under, [], []
        for _start, heading, put in events:
            if heading is not None:
                current = _folded(current, heading)
                continue
            target, why, folder = _target(entry, put, imported, known)
            if target in unreadable or (target is None and _distributed(put)):
                continue
            if target is None:
                refusals.append((path, Refusal("tex-refused", put.offset, why)))
                continue
            if target in chain:
                said = f"{target} inputs itself, through {' > '.join((*chain, target))}"
                refusals.append((path, Refusal("tex-refused", put.offset, said)))
                continue
            targets.append((put.offset, target))
            if target in seen:
                continue
            seen.add(target)
            after = visit(target, put.body, put.environments, _starts_under(current),
                          (*chain, target), folder)  # fmt: skip
            current = _resumed(current, after)
            resumes.append((put.end, current))
        sources[place] = Source(path, text, reading, under, resumes=tuple(resumes),
                               environments=environments, targets=tuple(targets),
                               imported=imported)  # fmt: skip
        return current

    if entry in files:
        seen.add(entry)
        visit(entry, None, (), (), (entry,))
    for path in sorted(files):
        if path not in seen:
            text = files[path]
            reading = read(text, body=True, loose=True, delimited=delimited, own=own)
            sources.append(Source(path, text, reading, loose=True))
            refusals.extend((path, refusal) for refusal in reading.refusals)
    return Document(tuple(sources), tuple(refusals))


def read_document(manuscript_dir: Path, *, supplementary: bool = False) -> Document:
    """The main text's document, or the supplement's, read from the manuscript folder."""
    from manuscript_guard.contracts._schema import Unreadable, read_text
    from manuscript_guard.gates.numbers import is_supplementary, source_files

    def gathered(glob: str) -> tuple[dict[str, str], frozenset[str]]:
        found, failed = {}, set()
        for path in source_files(manuscript_dir, glob=glob):
            if is_supplementary(manuscript_dir, path) != supplementary:
                continue
            name = path.relative_to(manuscript_dir).as_posix()
            try:
                found[name] = read_text(path)
            except Unreadable:
                failed.add(name)
        return found, frozenset(failed)

    files, unreadable = gathered("*.tex")
    packages, _ = gathered("*.sty")
    entry = SUPPLEMENT_ENTRY if supplementary else ENTRY
    return read_tree(files, entry, packages=packages, unreadable=unreadable)
