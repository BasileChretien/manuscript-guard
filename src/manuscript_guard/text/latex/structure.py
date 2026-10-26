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

Two kinds of file the paper does not input are not read at all. A file that a class or a
package the paper loads inputs, by a path written out in full, is the class's, as a list
of journals a journal's class ships beside the paper is: the class is read for the files it
inputs and the packages it loads, and nothing else of it. A file that holds a document of
its own, its own `\\begin{document}`, is another document, never the main text: it is
refused, since the supplement is the one at `supplementary/main.tex`.
"""

from __future__ import annotations

import posixpath
import re
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from manuscript_guard.text.latex.commands import PACKAGE_COMMANDS
from manuscript_guard.text.latex.mask import Heading, Input, Reading, Refusal, read

ENTRY = "main.tex"
SUPPLEMENT_ENTRY = "supplementary/main.tex"
#: The values file the tool writes, never read as the author's package.
VALUES = "mgvalues"
_NOT_WRITTEN_OUT = set("\\#$%{}~")
#: A comment in a class or a package: an unescaped `%` to the end of its line, the
#: backslashes before it kept.
_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%[^\n]*")
#: What a class or a package loads, by a name written out in braces: another class or
#: package, or a file it inputs, `\\input`, LaTeX's `\\@input` and `\\InputIfFileExists`, or
#: TeX's `\\input name` without braces.
_LOADS = re.compile(
    r"\\(?P<how>RequirePackage|RequirePackageWithOptions|usepackage|LoadClass"
    r"|LoadClassWithOptions)[ \t]*(?:\r?\n[ \t]*)?(?:\[[^\]]*\][ \t]*(?:\r?\n[ \t]*)?)?"
    r"\{(?P<names>[^{}]*)\}"
    r"|\\(?:@?input@?|InputIfFileExists\*?|include)[ \t]*(?:\r?\n[ \t]*)?\{(?P<path>[^{}\n]*)\}"
    r"|\\@?input[ \t]+(?P<bare>[^\s{}\\%]+)"
)
#: A command that defines another, by what holds what it defines past its name and its
#: options: `one` braced group, `two` (an environment's code, or a document command's
#: argument specification and code) or `three`, or TeX's `tex` parameter text and a group,
#: past a name that is a command or, for `\\@namedef` and expl3's `c` forms, braced. That
#: code runs where the command is used, not where it stands (rounds 1 and 2 of #445).
_DEFINES = re.compile(
    r"\\(?:(?P<one>(?:re)?newcommandx?|providecommand|DeclareRobustCommand"
    r"|(?:re)?newrobustcmd|providerobustcmd|cs[gex]?def)"
    r"|(?P<two>(?:re)?newenvironment|provideenvironment"
    r"|(?:New|Renew|Provide|Declare)(?:Expandable)?DocumentCommand)"
    r"|(?P<three>(?:New|Renew|Provide|Declare)DocumentEnvironment)"
    r"|(?P<tex>[gex]?def|protected@[ex]def|@namedef"
    r"|cs_(?:new|g?set)(?:_protected)?(?:_nopar)?:[Nc]p?[nxe]))(?![A-Za-z@_:])\*?"
)
#: What a defining command's name after `\\let\\name` stands for: it is copied, not used.
_LET = re.compile(r"\\let[ \t]*\\(?:[A-Za-z@]+|.)[ \t]*=?[ \t]*\Z")
_SPACE = re.compile(r"\s*")
_CONTROL = re.compile(r"\\(?:[A-Za-z@]+|.)", re.DOTALL)
#: The classes whose document is part of another's, printed in it: a `standalone` picture,
#: which the paper places by `\\includestandalone` or as the PDF compiled from it, and a
#: part in the `subfiles` class, which the paper places by `\\subfile` (round 2 of #445).
_PARTS = frozenset({"standalone", "subfiles"})
#: The code a file that holds a document of its own is refused with.
SECOND_DOCUMENT = "tex-second-document"


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
    the file it is in; and the files a class or a package inputs, which are not read
    (`_classes`)."""

    sources: tuple[Source, ...]
    refusals: tuple[tuple[str, Refusal], ...]
    classes: tuple[str, ...] = ()

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
    classes: Mapping[str, str] | None = None,
) -> Document:
    """The document `entry` begins, its files given by path; `packages` the `.sty` files and
    `classes` the `.cls` files the manuscript holds; `unreadable` files that could not be
    read, reported elsewhere and passed over. A command one file defines with delimited
    parameters is refused where another uses it, and a command of a class's front matter one
    file defines is the author's in another, so a tree that defines either is read twice, the
    second time with every file told of them. A file nothing inputs defines nothing the
    document uses (round 2)."""
    styles = (packages or {}, classes or {})
    document = _read_tree(files, entry, styles, unreadable, _Told())
    tree = [source for source in document.sources if not source.loose]
    delimited = frozenset(name for source in tree
                          for name in source.reading.delimited)  # fmt: skip
    own = frozenset(name for source in tree for name in source.reading.own)
    literal = tuple(pair for source in tree for pair in source.reading.literal)
    if not delimited and not own and not literal:
        return _encoded(document)
    # A package's command a file defines is the author's only where no file loads the
    # package: one loaded in another file makes it defined again (2026-10-23).
    loaded = frozenset(name for source in tree for _at, name in source.reading.packages)
    own = frozenset(name for name in own
                    if not set(PACKAGE_COMMANDS.get(name, ())) & loaded)  # fmt: skip
    told = _Told(delimited, own, literal, loaded)
    return _encoded(_read_tree(files, entry, styles, unreadable, told))


@dataclass(frozen=True)
class _Told:
    """What each file of a tree is told of the others: the commands they define with
    delimited parameters, the commands that are the author's, those defined with a parameter
    text and no parameter, and the packages they load."""

    delimited: frozenset[str] = frozenset()
    own: frozenset[str] = frozenset()
    literal: tuple[tuple[str, str], ...] = ()
    loaded: frozenset[str] = frozenset()

    def read(self, text: str, **given) -> Reading:
        return read(text, delimited=self.delimited, own=self.own, literal=self.literal,
                    loaded=self.loaded, **given)  # fmt: skip


def _encoded(document: Document) -> Document:
    """`document` with an input encoding other than UTF-8 that a file of its tree sets, which
    the reader accepts since that file is ASCII, refused where another file of the tree is
    not: TeX reads every file in it (2026-10-23)."""
    tree = [source for source in document.sources if not source.loose]
    other = next((source.path for source in tree if not source.text.isascii()), None)
    if other is None:
        return document
    said = f"the input encoding is not UTF-8, in which {other} is read"
    refused = [(source.path, Refusal("tex-refused", at, said))
               for source in tree for at in source.reading.encodings]  # fmt: skip
    return Document(document.sources, (*document.refusals, *refused),
                    document.classes) if refused else document  # fmt: skip


def _classes(
    entry: str, tree: list[Source], files: Mapping[str, str],
    styles: tuple[Mapping[str, str], Mapping[str, str]],
) -> frozenset[str]:  # fmt: skip
    """The `.tex` files a class or a package the tree loads inputs, and the files they input
    in turn: a class's, not the author's text, though the manuscript folder holds them, as a
    journal's class holds a list of its journals in a file it inputs. A class or a package
    counts where the manuscript holds it, found as LaTeX finds it, from the entry file's
    folder; its comments are passed over, and so is a path it builds with a command, which
    names no file here, and a load inside a definition's body, which runs where the command
    is used and may print there (`_bodies`). A file the tree inputs too is the tree's
    (`_theirs`)."""
    packages, classes = styles
    folder = posixpath.dirname(entry)

    def held(name: str, suffix: str, among: Mapping[str, str]) -> list[str]:
        path = posixpath.normpath(posixpath.join(folder, name.strip() + suffix))
        return [path] if name.strip() and path in among else []

    todo = [path for source in tree for kind, name in source.reading.declared if kind == "class"
            for path in held(name, ".cls", classes)]  # fmt: skip
    todo += [path for source in tree for _at, name in source.reading.packages
             for path in held(name, ".sty", packages)]  # fmt: skip
    texts = {**files, **packages, **classes}
    done: set[str] = set()
    inputs: set[str] = set()
    while todo:
        path = todo.pop()
        if path in done:
            continue
        done.add(path)
        text = _COMMENT.sub(r"\1", texts[path])
        bodies = _bodies(text)
        starts = [start for start, _end in bodies]
        for load in _LOADS.finditer(text):
            before = bisect_right(starts, load.start()) - 1
            if before >= 0 and load.start() < bodies[before][1]:
                continue
            if load["names"] is not None:
                among = classes if load["how"].startswith("LoadClass") else packages
                suffix = ".cls" if among is classes else ".sty"
                todo += [found for name in load["names"].split(",")
                         for found in held(name, suffix, among)]  # fmt: skip
                continue
            target, _why = resolve(entry, load["path"] or load["bare"] or "", files)
            if target is not None:
                inputs.add(target)
                todo.append(target)
    return _theirs(frozenset(inputs), tree)


def _theirs(inputs: frozenset[str], tree: list[Source]) -> frozenset[str]:
    """Of the files a class inputs, those the tree does not read: one the paper inputs too
    is the paper's, read where the paper inputs it."""
    return inputs - {source.path for source in tree}


def _bodies(text: str) -> list[tuple[int, int]]:
    """Where each definition in a class's or a package's text holds what it defines, in
    order, from the brace that opens it to past the one that closes it: what is there runs
    where the command is used, so an `\\input` in it is not the class's own but whatever
    file uses the command's (round 1 of #445: `\\newcommand{\\abstracttext}{\\input{abstract}}`
    in a package made the paper's abstract the package's). A body that is not closed runs to
    the end of the text. A definition inside a body is part of it."""
    spans: list[tuple[int, int]] = []
    at = 0
    while (found := _DEFINES.search(text, at)) is not None:
        at = found.end()
        if _LET.search(text, max(found.start() - 80, 0), found.start()):
            continue
        if found["tex"]:
            at = _SPACE.match(text, at).end()
            name = _CONTROL.match(text, at)
            if name is None and text.startswith("{", at):
                at = _closing(text, at)
            opened = _next_brace(text, name.end() if name else at)
            if opened < 0:
                continue
            at = _closing(text, opened)
            spans.append((opened, at))
            continue
        groups = 1 if found["one"] else 2 if found["two"] else 3
        at = _SPACE.match(text, at).end()
        name = _CONTROL.match(text, at)
        at = name.end() if name else _closing(text, at) if text.startswith("{", at) else at
        while text.startswith("[", at := _SPACE.match(text, at).end()):
            at = _closing(text, at, "[", "]")
        opened = at
        for _group in range(groups):
            at = _SPACE.match(text, at).end()
            if not text.startswith("{", at):
                break
            at = _closing(text, at)
        if at > opened:
            spans.append((opened, at))
    return spans


def _next_brace(text: str, at: int) -> int:
    """Where the first `{` from `at` stands, not one a backslash escapes, or -1."""
    while at < len(text):
        if text[at] == "\\":
            at += 2
            continue
        if text[at] == "{":
            return at
        at += 1
    return -1


def _closing(text: str, opened: int, opener: str = "{", closer: str = "}") -> int:
    """Past the `closer` that closes the `opener` at `opened`, braces balanced inside it and
    an escaped one passed over, or the end of the text where none does."""
    depth, at = 0, opened
    while at < len(text):
        char = text[at]
        if char == "\\":
            at += 2
            continue
        if char == "{" and opener != "{":
            at = _closing(text, at)
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return at + 1
        at += 1
    return len(text)


def own_document(text: str) -> int:
    """Where a file opens a document of its own, at its `\\begin{document}`, or -1 where it
    opens none: read as an entry file is, it opens in its preamble and does not read on as
    body, so a `\\begin{document}` in a comment, a listing or an `\\iffalse` block opens none.
    One refused in that preamble before it reaches a `\\begin{document}` opens none either:
    it is read past its refusal, which fails it, as a file nothing inputs is (round 1 of
    #445: it was taken for a second document at its first character and not read). Nor does
    a `standalone` picture or a `subfiles` part, which the paper prints (`_PARTS`)."""
    reading = read(text)
    if reading.body_start <= 0:
        return -1
    if {name for kind, name in reading.declared if kind == "class"} & _PARTS:
        return -1
    return max(text.rfind("\\begin", 0, reading.body_start), 0)


def _read_tree(
    files: Mapping[str, str],
    entry: str,
    styles: tuple[Mapping[str, str], Mapping[str, str]],
    unreadable: frozenset[str],
    told: _Told,
) -> Document:
    """`read_tree`, each file told what `told` holds."""
    packages = styles[0]
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
        reading = told.read(text, body=body, environments=environments)
        place = len(sources)
        sources.append(Source(path, text, reading, under, environments=environments,
                              imported=imported))  # fmt: skip
        refusals.extend((path, refusal) for refusal in reading.refusals)
        for _at, name in reading.packages:
            style = posixpath.join(posixpath.dirname(entry), f"{name}.sty")
            if name != VALUES and style in packages and style not in seen:
                seen.add(style)
                package = told.read(packages[style], body=False, package=True)
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
    classes = _classes(entry, sources, files, styles)
    for path in sorted(files):
        if path in seen or path in classes:
            continue
        text = files[path]
        begins = own_document(text)
        if begins >= 0:
            said = (f"{path} holds a document of its own, with its own \\begin{{document}}, "
                    f"and is not read as part of {entry}'s")  # fmt: skip
            refusals.append((path, Refusal(SECOND_DOCUMENT, begins, said)))
            continue
        reading = told.read(text, body=True, loose=True)
        sources.append(Source(path, text, reading, loose=True))
        refusals.extend((path, refusal) for refusal in reading.refusals)
    return Document(tuple(sources), tuple(refusals), tuple(sorted(classes)))


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
    classes, _ = gathered("*.cls")
    entry = SUPPLEMENT_ENTRY if supplementary else ENTRY
    return read_tree(files, entry, packages=packages, unreadable=unreadable, classes=classes)
