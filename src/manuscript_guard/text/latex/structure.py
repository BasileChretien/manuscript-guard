"""A LaTeX manuscript's files as `\\input` joins them (DESIGN.md, "LaTeX manuscripts").

The entry file is read first, and each file it inputs where its `\\input` stands, depth
first: that order is the order the build prints. A file starts in the state its `\\input`
stands in: body or preamble, inside the environments open there, and under the headings in
force there, so that `p < 0.05` in a file input under `\\section{Methods}` is read under
Methods. A path resolves from the entry file's folder, as TeX resolves it, with `.tex` added
where it has no suffix.

Refused, where the `\\input` stands: a path not written out in full, one outside the
manuscript or under a folder set aside, a file that is not there, and a file that inputs
itself. A file input twice is read once, where it is first input. A package of the author's,
`\\usepackage{macros}` with `macros.sty` beside the entry file, is read as preamble with `@` a
letter; `mgvalues.sty`, which the tool writes, is not. A `.tex` file nothing inputs is read as
loose body under no heading, and is warned of.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.text.latex.mask import Heading, Reading, Refusal, read

ENTRY = "main.tex"
SUPPLEMENT_ENTRY = "supplementary/main.tex"
#: The values file the tool writes, never read as the author's package.
VALUES = "mgvalues"
_NOT_WRITTEN_OUT = set("\\#$%{}~")


@dataclass(frozen=True)
class Source:
    """One file of the document: its text, how it reads, the headings over its start, and
    the headings in force after each file it inputs, which that file's own headings change."""

    path: str
    text: str
    reading: Reading
    under: tuple[Heading, ...] = ()
    loose: bool = False
    resumes: tuple[tuple[int, tuple[Heading, ...]], ...] = ()

    def chain_at(self, offset: int) -> tuple[Heading, ...]:
        """The headings in force at `offset` of this file: those it started under, its own,
        and those a file it input left in force where its `\\input` ends."""
        events = sorted(
            [(heading.start, heading, ()) for heading in self.reading.headings]
            + [(end, None, after) for end, after in self.resumes],
            key=lambda event: event[0],
        )
        chain = self.under
        for start, heading, after in events:
            if start >= offset:
                break
            chain = _folded(chain, heading) if heading is not None else after
        return chain


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


@dataclass(frozen=True)
class Document:
    """The files in the order the build prints them, loose ones after, and every refusal with
    the file it is in."""

    sources: tuple[Source, ...]
    refusals: tuple[tuple[str, Refusal], ...]

    @property
    def loose(self) -> tuple[str, ...]:
        return tuple(source.path for source in self.sources if source.loose)


def heading_chain(
    under: tuple[Heading, ...], headings: tuple[Heading, ...], offset: int
) -> tuple[Heading, ...]:
    """The headings in force at `offset` of a file: those it started under, then its own
    before `offset`, each closing the ones of its level or below."""
    chain = under
    for heading in headings:
        if heading.start >= offset:
            break
        chain = _folded(chain, heading)
    return chain


def resolve(entry: str, written: str, files: Mapping[str, str]) -> tuple[str | None, str]:
    """The file an `\\input` names, from the entry file's folder, or None and why not."""
    if not written.strip() or set(written) & _NOT_WRITTEN_OUT:
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
    files; `unreadable` files that could not be read, reported elsewhere and passed over."""
    packages = packages or {}
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
    ) -> tuple[Heading, ...]:
        """Read one file and the files it inputs, where they stand, and give the headings
        in force at its end."""
        text = files[path]
        reading = read(text, body=body, environments=environments)
        place = len(sources)
        sources.append(Source(path, text, reading, under))
        refusals.extend((path, refusal) for refusal in reading.refusals)
        for _at, name in reading.packages:
            style = posixpath.join(posixpath.dirname(entry), f"{name}.sty")
            if name != VALUES and style in packages and style not in seen:
                seen.add(style)
                package = read(packages[style], body=False, package=True)
                sources.append(Source(style, packages[style], package))
                refusals.extend((style, refusal) for refusal in package.refusals)
        events = sorted(
            [(heading.start, heading, None) for heading in reading.headings]
            + [(put.offset, None, put) for put in reading.inputs],
            key=lambda event: event[0],
        )
        current, resumes = under, []
        for _start, heading, put in events:
            if heading is not None:
                current = _folded(current, heading)
                continue
            target, why = resolve(entry, put.path, known)
            if target in unreadable:
                continue
            if target is None:
                refusals.append((path, Refusal("tex-refused", put.offset, why)))
                continue
            if target in chain:
                said = f"{target} inputs itself, through {' > '.join((*chain, target))}"
                refusals.append((path, Refusal("tex-refused", put.offset, said)))
                continue
            if target in seen:
                continue
            seen.add(target)
            after = visit(target, put.body, put.environments, _starts_under(current),
                          (*chain, target))  # fmt: skip
            current = _resumed(current, after)
            resumes.append((put.end, current))
        sources[place] = Source(path, text, reading, under, resumes=tuple(resumes))
        return current

    if entry in files:
        seen.add(entry)
        visit(entry, None, (), (), (entry,))
    for path in sorted(files):
        if path not in seen:
            text = files[path]
            reading = read(text, body=True, loose=True)
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
