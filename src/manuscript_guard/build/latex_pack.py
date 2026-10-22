"""The LaTeX submission folder (DESIGN.md, "LaTeX manuscripts", "The submission folder", step
10).

`submit` packs a LaTeX manuscript as the source a journal compiles, in one folder, as
submission systems ask. Each document is one file, `manuscript.tex` and `supplementary.tex`:
- each file it inputs is written in where its `\\input` stands, an `\\include`d one between the
  `\\clearpage`s LaTeX puts round it;
- each binding is written as the values file prints it, and `\\usepackage{mgvalues}` as
  `\\usepackage{graphicx}`, which the values file loads;
- each comment's text is taken out and its `%` kept, since a comment can hold a draft and its
  old numbers, and so is what TeX never prints, an `\\iffalse` block's and a `comment`
  environment's.
The author's packages are written the same way beside it. A figure a binding names, and each
file of the manuscript's that LaTeX read for the build, its picture, class or style, is in the
folder under its own name, or its folder's name before it where two have one; each
`\\includegraphics` names it so. A `.bib` the document names holds the cited entries only, and
the `.bbl` LaTeX made is beside it. The folder is then compiled alone, in an empty folder with
an empty TEXMFHOME, and refused where LaTeX stops, a file is not found, or it reads a file of
the project; the PDFs are that compile's.
"""

from __future__ import annotations

import posixpath
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.build.document import BuildError
from manuscript_guard.build.latex import (
    COPY,
    VALUES,
    Compiled,
    _compile,
    _Copy,
    _programs,
    build_latex,
    recorded,
)

#: Where the folder is written in the build's copy, which each build replaces.
STAGED = "submission"
#: Each document's name in the folder.
MAIN, SUPPLEMENT = "manuscript", "supplementary"
#: The extensions pdfTeX's graphicx tries, in its order, for a picture named without one.
_GRAPHICS = (".pdf", ".png", ".jpg", ".mps", ".jpeg", ".jbig2", ".jb2", ".PDF", ".PNG", ".JPG",
             ".JPEG", ".JBIG2", ".JB2", ".eps")  # fmt: skip
#: A package's command, to the brace its list opens with.
_PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{")
#: The bibliography a document names: BibTeX's `\\bibliography{a,b}` and biblatex's
#: `\\addbibresource[...]{a.bib}`, to the brace that opens the names.
_BIBLIOGRAPHY = re.compile(r"\\(?P<command>bibliography|addbibresource)\s*(?:\[[^\]]*\])?\s*\{")
#: An entry of a `.bib` file, to the brace or parenthesis that opens it.
_ENTRY = re.compile(r"@\s*(?P<kind>[A-Za-z]+)\s*(?P<open>[{(])")
#: A field that names other entries the cited one needs: BibTeX's `crossref`, and biblatex's
#: `xdata`, `xref`, `related` and a set's `entryset` (round 1 of step 10).
_NEEDS = re.compile(r"\b(?:crossref|xdata|xref|related|entryset)\s*=\s*[{\"]?\s*"
                    r"(?P<keys>[^}\",]+(?:,[^}\",]+)*)", re.IGNORECASE)  # fmt: skip
#: An environment that writes what it holds to a file, in which `%` is no comment.
_FILECONTENTS = re.compile(r"\\begin\s*\{filecontents\*?\}.*?\\end\s*\{filecontents\*?\}",
                           re.DOTALL)  # fmt: skip
#: Where TeX stops reading a file, at the end of the line it stands on.
_ENDINPUT = re.compile(r"\\endinput(?![A-Za-z@])")
#: An environment whose content TeX reads as characters, where `\\endinput` is text.
_RAW_ENVIRONMENT = re.compile(r"\\begin\s*\{(?P<name>verbatim\*?|Verbatim|lstlisting|comment)\}"
                              r".*?\\end\s*\{(?P=name)\}", re.DOTALL)  # fmt: skip
#: xr's document whose labels the supplement refers to, by its path from the entry's folder.
_EXTERNAL = re.compile(r"\\externaldocument\s*(?:\[[^\]]*\])?\s*\{(?P<path>[^{}]*)\}")
#: A file a document tests for, whose path is the folder's name for it.
_TESTED = re.compile(r"\\IfFileExists\s*\{(?P<path>[^{}]*)\}")


@dataclass(frozen=True)
class LatexPack:
    """The folder written: each file in it the journal is sent, and the PDFs its compile made,
    the main text's first."""

    folder: Path
    files: tuple[Path, ...]
    documents: tuple[Path, ...]
    undefined: tuple[str, ...]


def pack_latex(project, namespace, results, *, engine: str = "pdflatex") -> LatexPack:
    """Build the manuscript as `build` does, write the folder, and compile it alone."""
    from manuscript_guard.build.latex_values import entry_folders
    from manuscript_guard.text.latex.structure import read_document

    built = build_latex(project, namespace, results, engine=engine)
    manuscript = project.path("manuscript")
    folder = project.path("build") / COPY / STAGED
    folder.mkdir()
    documents = []
    for entry_folder in entry_folders(project):
        supplementary = entry_folder != manuscript
        document = read_document(manuscript, supplementary=supplementary)
        for path, refusal in document.refusals:
            raise BuildError(f"{manuscript / path}: the reader refused it ({refusal.message}), "
                             "and the submission folder is written from what it reads")  # fmt: skip
        documents.append((document, supplementary))
    read = {path: None for compiled in built for path in compiled.read}
    writer = _Writer(project, namespace, results, folder, documents, tuple(read))
    writer.cited |= {key for compiled in built for key in compiled.cited}
    written = writer.write()
    alone = _alone(project, folder, [name for name, _ in written], engine)
    # Every file but the documents' PDFs: a picture may be a PDF (round 1 of step 10).
    documents_made = {f"{name}.pdf" for name, _ in written}
    files = tuple(sorted(path for path in folder.iterdir() if path.name not in documents_made))
    undefined = tuple(dict.fromkeys(left for compiled in alone for left in compiled.undefined))
    return LatexPack(folder, files, tuple(compiled.pdf for compiled in alone), undefined)


def _alone(project, folder: Path, names: list[str], engine: str) -> list[Compiled]:
    """Each document of `folder` compiled in a copy of it in an empty folder, its PDF and its
    `.bbl` put in `folder`; or `BuildError` where LaTeX stops, does not find a file, or reads
    one of the project's, as MiKTeX lets it by a path written out in full."""
    programs = _programs(engine)
    compiled = []
    with tempfile.TemporaryDirectory(prefix="manuscript-guard-",
                                     ignore_cleanup_errors=True) as scratch:  # fmt: skip
        root = Path(scratch)
        (root / ".texmfhome").mkdir()
        shutil.copytree(folder, root / STAGED)
        copy = _Copy(root, folder, (root / STAGED,), inner=STAGED)
        for name in names:
            entry = root / STAGED / f"{name}.tex"
            try:
                done = _compile(project, copy, entry, programs, engine,
                                supplementary=name == SUPPLEMENT)  # fmt: skip
            except BuildError as exc:
                raise BuildError(f"the submission folder {folder} does not compile alone, in "
                                 f"an empty folder: {exc}") from exc  # fmt: skip
            reached = [path for path in recorded(entry)[0]
                       if path.is_relative_to(project.root.resolve())]  # fmt: skip
            if reached:
                raise BuildError(f"the submission folder {folder} reads {reached[0]}, which "
                                 "is not in it: a journal compiling it would not have "
                                 "it")  # fmt: skip
            pdf = Path(shutil.copyfile(done.pdf, folder / f"{name}.pdf"))
            if entry.with_suffix(".bbl").is_file():
                shutil.copyfile(entry.with_suffix(".bbl"), folder / f"{name}.bbl")
            compiled.append(Compiled(pdf, done.undefined))
    return compiled


class _Names:
    """Each file's name in the one folder: its own, or where another file has it, its path
    with `-` for each `/`, then a number before it. Compared without case, as the file
    systems of Windows and macOS compare names."""

    def __init__(self, reserved: list[str]) -> None:
        self._taken: dict[str, object] = {name.lower(): None for name in reserved}
        self._given: dict[object, str] = {}

    def claim(self, source: object, relative: str) -> str:
        if source in self._given:
            return self._given[source]
        name = posixpath.basename(relative)
        for candidate in (name, relative.replace("/", "-"),
                          *(f"{n}-{name}" for n in range(2, 10_000))):  # fmt: skip
            if candidate.lower() not in self._taken:
                self._taken[candidate.lower()] = source
                self._given[source] = candidate
                return candidate
        raise BuildError(f"no name is left for {relative} in the submission folder")


class _Writer:
    """The folder's files, written from what the reader read of each document."""

    def __init__(self, project, namespace, results, folder: Path, documents, read) -> None:
        self.project = project
        self.namespace = namespace
        self.results = results
        self.folder = folder
        self.documents = documents
        self.manuscript = project.path("manuscript").resolve()
        self.names = _Names([f"{name}.{suffix}" for name in (MAIN, SUPPLEMENT)
                             for suffix in ("tex", "pdf", "bbl", "aux", "log")])  # fmt: skip
        #: Each file of the manuscript LaTeX read, by its path from the manuscript's folder.
        resolved = [path.resolve() for path in read]
        self.read = {path.relative_to(self.manuscript).as_posix(): path for path in resolved
                     if path.is_relative_to(self.manuscript)}  # fmt: skip
        self.cited: set[str] = set()
        self.bibliographies: dict[str, Path] = {}
        #: Each picture an `\\includegraphics` is written with its name for.
        self.renamed: set[Path] = set()

    def write(self) -> list[tuple[str, bool]]:
        """Write each document and what it needs; each document's name and whether it is the
        supplement, the main text's first."""
        from manuscript_guard.build.latex_values import entries, rendered_figures

        rendered = rendered_figures(self.project)
        #: Where the build puts each rendered figure beside each entry file, from the
        #: manuscript's folder, for a picture named by that path.
        self.placed = {posixpath.join(posixpath.dirname(document.sources[0].path), "figures",
                                      path.name): path
                       for document, _ in self.documents for path in rendered.values()
                       if path is not None}  # fmt: skip
        figures = {}
        for key in sorted(self._bound("figure") & set(rendered)):
            if rendered[key] is not None:
                name = self.names.claim(rendered[key], f"figures/{rendered[key].name}")
                figures[key] = self.folder / name
                shutil.copyfile(rendered[key], figures[key])
        found, _refused = entries(self.folder, self.namespace, self.results, figures)
        self.values = dict(found)
        written = []
        for document, supplementary in self.documents:
            name = SUPPLEMENT if supplementary else MAIN
            self.document, self.entry = document, document.sources[0].path
            self.sources = {source.path: source for source in document.sources}
            self.files = {source.path: source.text for source in document.sources}
            for source in document.sources:
                if source.loose:
                    continue
                if source.path.lower().endswith(".sty"):
                    package = posixpath.basename(source.path)
                    # Claimed by its file, as a path that names it is (round 3 of step 10).
                    claimed = self.names.claim((self.manuscript / source.path).resolve(),
                                               source.path)  # fmt: skip
                    if claimed != package:
                        raise BuildError(f"two of the author's packages are named {package}, "
                                         "and the submission folder holds one")  # fmt: skip
                    self._save(package, self._text(source, depth=0))
                for kind, style in source.reading.declared:
                    if kind == "bst":
                        self._bst(style)
            self._save(f"{name}.tex", self._text(document.sources[0], depth=0))
            written.append((name, supplementary))
        self._files()
        for name, path in self.bibliographies.items():
            self._save(name, _cut(path.read_text(encoding="utf-8", errors="replace"),
                                  None if "*" in self.cited else self.cited))  # fmt: skip
        return written

    def _bound(self, namespace: str) -> set[str]:
        from manuscript_guard.text.latex.views import bindings

        keys = set()
        for document, _supplementary in self.documents:
            for source in document.sources:
                keys |= {found.key for found in bindings(source)[0]
                         if found.namespace == namespace}  # fmt: skip
        return keys

    def _save(self, name: str, text: str) -> None:
        (self.folder / name).write_text(text, encoding="utf-8", newline="")

    def _bst(self, style: str) -> None:
        """A BibTeX style of the manuscript's beside the entry file, which BibTeX reads and the
        recorder does not list."""
        relative = posixpath.join(posixpath.dirname(self.entry), f"{style}.bst")
        path = self.manuscript / relative
        if path.is_file() and self.names.claim(path, relative) == f"{style}.bst":
            shutil.copyfile(path, self.folder / f"{style}.bst")

    def _files(self) -> None:
        """Each other file of the manuscript's LaTeX read, a picture, a class or a style."""
        sources = {source.path for document, _ in self.documents for source in document.sources}
        for relative, path in self.read.items():
            name = posixpath.basename(relative)
            if relative in sources or name == VALUES or path.suffix.lower() == ".bib":
                continue
            claimed = self.names.claim(path, relative)
            if claimed != name and path not in self.renamed:
                # A file named in the source by its name, a class or a picture found through
                # `\\graphicspath`, must keep it: under another's it is another file
                # (round 1 of step 10).
                raise BuildError(f"two files the manuscript reads are named {name}, and the "
                                 "submission folder holds one of them under that name: "
                                 f"rename {self.manuscript / relative}")  # fmt: skip
            shutil.copyfile(path, self.folder / claimed)

    def _text(self, source, *, depth: int) -> str:
        """`source` as the folder holds it."""
        if depth > 64:
            raise BuildError(f"{source.path} inputs files more than 64 deep")
        edits = sorted(self._edits(source, depth), key=lambda edit: (edit[0], edit[1]))
        stop = len(source.text)
        if depth:
            # A file input stops at the line its `\\endinput` is on, and TeX ends its last
            # line as any other: written in, it must not end the document or take the line
            # after it into a comment (round 1 of step 10).
            # Not where TeX reads it as text or keeps it for later: in a `\\verb`, a
            # listing, a file `filecontents` writes or a definition (round 2 of step 10).
            skipped = [*_as_text(source), *source.reading.bodies]
            for found in _ENDINPUT.finditer(source.text):
                if not any(start <= found.start() < end for start, end in skipped):
                    line_end = source.text.find("\n", found.end())
                    stop = len(source.text) if line_end < 0 else line_end
                    edits = [edit for edit in edits if edit[1] <= stop]
                    edits.append((found.start(), found.end(), ""))
                    edits.sort(key=lambda edit: (edit[0], edit[1]))
                    break
        out, at = [], 0
        for start, end, text in edits:
            if start < at:
                raise BuildError(f"{source.path}: two edits of the submission folder meet at "
                                 f"offset {start}; please report this")  # fmt: skip
            out += [source.text[at:start], text]
            at = end
        written = "".join(out) + source.text[at:stop]
        return written if not depth or written.endswith("\n") else written + "\n"

    def _edits(self, source, depth: int) -> list[tuple[int, int, str]]:
        from manuscript_guard.text.latex.structure import resolve
        from manuscript_guard.text.latex.views import bindings

        text, reading = source.text, source.reading
        # A `%` in a file `filecontents` writes is the file's (round 1 of step 10).
        written_out = [found.span() for found in _FILECONTENTS.finditer(text)]
        bibliography, listed = self._bibliography(source)
        kept = [*written_out, *listed]
        edits = [(start + 1, end, "") for start, end in reading.comments
                 if not any(low <= start < high for low, high in kept)]  # fmt: skip
        edits += [(start, end, "") for start, end in reading.unprinted]
        edits += [(found.start, found.end, self._value(found)) for found in bindings(source)[0]]
        for put in reading.inputs:
            target, _why = resolve(self.entry, put.path, self.files)
            if target is None or target not in self.sources:
                continue
            body = self._text(self.sources[target], depth=depth + 1)
            if re.match(r"\\include(?![A-Za-z@])", text[put.offset :]):
                body = f"\\clearpage\n{body}\n\\clearpage"
            edits.append((put.offset, put.end, body))
        for at, name in reading.packages:
            if name == VALUES.removesuffix(".sty"):
                edits += self._without_values(text, at, reading.comments)
        for _start, end, opened in reading.graphics:
            edits += self._picture(source, opened, end)
        edits += self._named_paths(source)
        edits += bibliography
        cited = {found.key for found in reading.cited}
        self.cited |= cited
        return edits

    def _value(self, found) -> str:
        """What the values file prints for the binding `found`."""
        from manuscript_guard.build.latex_values import escaped

        ref = f"{found.namespace}.{found.key}"
        body = self.values.get(ref)
        if body is None:
            return r"\textbf{??}\,\texttt{" + escaped(ref, ref) + "}"
        if found.namespace == "figure":
            options = re.match(r"\\mg\s*(?:\[(?P<options>[^\]\n]*)\])?", found.raw)
            return body.replace("[#1]", f"[{options['options'] or ''}]")
        if found.namespace == "table":
            # The values file's `%` at each end keeps its definition's line breaks out; here
            # the `tabular` stands where the binding did (step 10).
            return body.removeprefix("%\n").removesuffix("%\n")
        return body

    def _without_values(self, text: str, at: int, comments) -> list[tuple[int, int, str]]:
        """`mgvalues` in a package's list written as `graphicx`, which it loads."""
        opened = _PACKAGE.match(text, at)
        if opened is None:
            return []
        close = text.find("}", opened.end())
        edits = []
        for name in re.finditer(r"(?<![\w-])mgvalues(?![\w-])", text[opened.end() : close]):
            start = opened.end() + name.start()
            if not any(begin <= start < end for begin, end in comments):
                edits.append((start, start + len(name.group(0)), "graphicx"))
        return edits

    def _named_paths(self, source) -> list[tuple[int, int, str]]:
        """xr's `\\externaldocument` of the other document, by its name in the folder; and a
        path `\\IfFileExists` tests, of a file the build read, by its name there, where the
        test would otherwise fail and leave out what it guards (round 2 of step 10)."""
        from manuscript_guard.text.latex.structure import ENTRY, SUPPLEMENT_ENTRY

        # A file `filecontents` writes is compiled in the folder, so its paths are rewritten
        # as the document's are (round 4 of step 10).
        text, skipped = source.text, _as_text(source, written_out=False)
        folder = posixpath.dirname(self.entry)
        documents = {posixpath.splitext(ENTRY)[0]: MAIN,
                     posixpath.splitext(SUPPLEMENT_ENTRY)[0]: SUPPLEMENT}  # fmt: skip
        edits = []
        for found in _EXTERNAL.finditer(text):
            joined = posixpath.normpath(posixpath.join(folder, found["path"].strip()))
            if joined in documents and not any(a <= found.start() < b for a, b in skipped):
                edits.append((found.start("path"), found.end("path"), documents[joined]))
        for found in _TESTED.finditer(text):
            joined = posixpath.normpath(posixpath.join(folder, found["path"].strip()))
            name = None if any(a <= found.start() < b for a, b in skipped) else self._held(joined)
            if name is not None:
                edits.append((found.start("path"), found.end("path"), name))
        return edits

    def _held(self, relative: str) -> str | None:
        """The folder's name for the manuscript's file at `relative`: a file the build read,
        an author's package, which keeps its name, or a figure the build rendered beside the
        entry file, copied in; None for one the folder does not hold, a `.tex` file it writes
        in among them (rounds 3 and 4 of step 10)."""
        if relative.lower().endswith(".tex") and relative in self.sources:
            return None
        if relative in self.read:
            self.renamed.add(self.read[relative])
            return self.names.claim(self.read[relative], relative)
        rendered = self.placed.get(relative)
        if rendered is not None:
            name = self.names.claim(rendered, posixpath.join("figures", rendered.name))
            shutil.copyfile(rendered, self.folder / name)
            return name
        return None

    def _picture(self, source, opened: int, end: int) -> list[tuple[int, int, str]]:
        """An `\\includegraphics` of a file of the manuscript's, written with its name in the
        folder. One LaTeX found elsewhere, in the distribution, is left as written."""
        path = source.text[opened + 1 : end - 1].strip()
        if not path or set(path) & set("#\\{}"):
            return []
        folder = posixpath.dirname(self.entry)
        joined = posixpath.normpath(posixpath.join(folder, path))
        if re.match(r"[A-Za-z]:|/", path) or joined == ".." or joined.startswith("../"):
            raise BuildError(f"{self.manuscript / source.path}: \\includegraphics names "
                             f"{path}, outside the manuscript's folder, which the submission "
                             "folder cannot hold; put the file in the manuscript's "
                             "folder")  # fmt: skip
        tried = [joined] if posixpath.splitext(joined)[1] in _GRAPHICS else []
        tried += [joined + extension for extension in _GRAPHICS]
        # A file the build read first, then a figure it rendered, named by the path it has
        # beside the entry file, which is none of the manuscript's (round 2 of step 10).
        for relative in [*(each for each in tried if each in self.read), *tried]:
            name = self._held(relative)
            if name is not None:
                return [(opened, end, "{" + name + "}")]
        return []

    def _bibliography(self, source) -> tuple[list[tuple[int, int, str]], list[tuple[int, int]]]:
        """Each `.bib` a bibliography command names, written with its name in the folder, and
        where each list of names runs; the file is cut to the cited entries when every
        document is written. A comment in the list is taken out with it (round 1 of step 10)."""
        text, reading = source.text, source.reading
        skipped = [*reading.comments, *reading.unprinted]
        edits, spans = [], []
        for found in _BIBLIOGRAPHY.finditer(text):
            if any(start <= found.start() < end for start, end in skipped):
                continue
            close = text.find("}", found.end())
            if close < 0:
                continue
            biblatex = found["command"] == "addbibresource"
            given = []
            listed = re.sub(r"(?<!\\)%[^\n]*", "", text[found.end() : close])
            spans.append((found.end(), close))
            for name in listed.split(","):
                name = name.strip()
                if not name:
                    continue
                file = name if name.lower().endswith(".bib") else f"{name}.bib"
                path = self._bib_file(file)
                if path is None:
                    given.append(name)
                    continue
                claimed = self.names.claim(path, file)
                self.bibliographies[claimed] = path
                given.append(claimed if biblatex else claimed.removesuffix(".bib"))
            edits.append((found.end(), close, ",".join(given)))
        return edits, spans

    def _bib_file(self, file: str) -> Path | None:
        """The file a bibliography's name is, as the build finds it: `references.bib` from
        `literature/`, which the build puts beside each entry file, and any other from the
        manuscript's folder."""
        relative = posixpath.normpath(posixpath.join(posixpath.dirname(self.entry), file))
        if relative.startswith("../") or relative == "..":
            return None
        literature = self.project.path("literature") / "references.bib"
        if posixpath.basename(relative) == "references.bib" and literature.is_file():
            return literature
        path = self.manuscript / relative
        return path if path.is_file() else None


def _as_text(source, *, written_out: bool = True) -> list[tuple[int, int]]:
    """Where TeX reads no command of `source`: a comment, what it never prints, a `\\verb`, a
    listing, and, with `written_out`, a file `filecontents` writes. Not a `\\texttt`, which
    the reader's code spans hold too and where TeX runs commands (round 3 of step 10)."""
    reading, text = source.reading, source.text
    verbs = [(start, end) for start, end in reading.code
             if re.search(r"\\verb\*?$", text[max(0, start - 6) : start])]  # fmt: skip
    files = [found.span() for found in _FILECONTENTS.finditer(text)] if written_out else []
    return [*reading.comments, *reading.unprinted, *verbs, *files,
            *(found.span() for found in _RAW_ENVIRONMENT.finditer(text))]


def _cut(text: str, keys: set[str] | None) -> str:
    """The entries of a `.bib` file a document cites, with those they name in `crossref` and
    `xdata`, each `@string` and `@preamble`, in the file's order; every entry where `keys` is
    None (`\\nocite{*}`)."""
    found: list[tuple[str, str, str]] = []
    at = 0
    while (opened := _ENTRY.search(text, at)) is not None:
        end = _entry_end(text, opened.end() - 1, opened["open"])
        kind = opened["kind"].lower()
        body = text[opened.start() : end]
        key = body[opened.end() - opened.start() :].split(",", 1)[0].strip()
        if kind != "comment":
            found.append((kind, key, body))
        at = end
    # Compared without case, as BibTeX matches a key; keeping an entry Biber would not match
    # costs nothing (round 1 of step 10).
    wanted = None if keys is None else {key.casefold() for key in keys}
    if wanted is not None:
        by_key = {key.casefold(): body for kind, key, body in found
                  if kind not in ("string", "preamble")}  # fmt: skip
        added = set(wanted)
        while added:
            needed = set()
            for key in added & set(by_key):
                for named in _NEEDS.finditer(by_key[key]):
                    needed |= {each.strip().casefold() for each in named["keys"].split(",")}
            added = needed - wanted
            wanted |= added
    kept = [body for kind, key, body in found if kind in ("string", "preamble")
            or wanted is None or key.casefold() in wanted]  # fmt: skip
    return "\n\n".join(kept) + "\n" if kept else ""


def _entry_end(text: str, opened: int, delimiter: str) -> int:
    """Past the brace or parenthesis that closes the entry opened at `opened`, the braces in
    it balanced."""
    depth = 0
    for at in range(opened + 1, len(text)):
        character = text[at]
        if character == "{":
            depth += 1
        elif character == "}":
            if depth == 0 and delimiter == "{":
                return at + 1
            depth -= 1
        elif character == ")" and delimiter == "(" and depth == 0:
            return at + 1
    return len(text)
