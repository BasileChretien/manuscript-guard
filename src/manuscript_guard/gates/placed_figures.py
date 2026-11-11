"""The figure files a paper places the ordinary way, not through a binding.

Most papers place a figure as LaTeX's `\\includegraphics{...}` or Markdown's `![...](path)`,
and a paper brought in from Word (`init --from`) places each picture as an image in
`manuscript/media/`. Figure review (G10), alternative text and the colour-vision check (G3)
read every figure the paper places, these with those an analysis emits and the manuscript
binds (`{{figure.key}}`, `\\mg{figure.key}`). A placed file is known by its path from the
project's root, `manuscript/figs/fig1.pdf`, and its records stand beside it as an emitted
figure's stand beside it in `figures/`: its review in `fig1.review.yaml`, its alternative
text in `fig1.guard.yaml` under `alt:`.

Found as the build finds them:

* LaTeX: each `\\includegraphics` of the main text's and the supplement's documents, outside
  what TeX never prints, from its entry file's folder, then each folder `\\graphicspath`
  names, and a file the import package imported from its folder as well; a name with no
  extension, or one graphicx does not know, with each extension pdfTeX's graphicx tries, in
  its order (`EXTENSIONS`), the extension outermost, as graphicx loops.
* Markdown: each image outside code, comments and the front matter, its path from the
  project's root, which pandoc runs from. A web address is no file of the paper's, and a
  reference image, `![a][b]`, is not read.

A path that names no file is passed over: the build says so. A file the manuscript reaches
through a link out of the project is checked where the link leads, known by its path through
the link, and named in a note (`figure-outside-project`). A picture in a definition's body
places nothing, even where the command is used (Known gaps).
A file in `figures/` of a figure an analysis emits is that figure, read as it always was.

What a placed figure draws is not traced to the results (G3's number checks read what the
analysis renders in `figures/`): `figure-untraced`, one note that names each such figure.
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, Finding, Report

GATE = "G3"
#: The extensions pdfTeX's graphicx tries, in its order, for a picture named without one, as
#: the submission folder resolves them (`build/latex_pack.py`).
EXTENSIONS = (".pdf", ".png", ".jpg", ".mps", ".jpeg", ".jbig2", ".jb2", ".PDF", ".PNG",
              ".JPG", ".JPEG", ".JBIG2", ".JB2", ".eps")  # fmt: skip
#: `\\graphicspath{{a/}{b/}}`, its list of folders.
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{\s*((?:\{[^{}]*\}\s*)*)\}")
_FOLDER = re.compile(r"\{([^{}]*)\}")
#: A LaTeX comment, an unescaped `%` to its line's end.
_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%[^\n]*")
#: A Markdown image, `![description](path "title"){attributes}`: its path in angle brackets,
#: or bare, where it may hold a pair of parentheses, `f(1).png`, as pandoc reads one.
_IMAGE = re.compile(
    r"!\[(?:[^\[\]\\]|\\.|\[[^\[\]]*\])*\]\(\s*(?:<(?P<angled>[^<>\n]+)>"
    r"|(?P<bare>(?:[^\s()\\]|\\.|\([^\s()]*\))+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
#: A backslash escape in a bare path, which pandoc reads as the character after it.
_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")
#: A run of percent escapes, read as the UTF-8 they spell; a gate imports no network module,
#: `urllib` among them (`tests/test_review_plan.py`).
_PERCENT = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_WEB = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//|#)")


@dataclass(frozen=True)
class Placed:
    """One figure file the paper places, not by a binding."""

    #: The file, as found: through a link where the manuscript reaches it through one.
    path: Path
    #: Its path from the project's root, `/` between folders: what it is known by.
    name: str
    #: Whether only the supplement places it.
    supplementary: bool
    #: Whether the file is outside the project, where a link leads (`figure-outside-project`).
    outside: bool = False

    @property
    def sidecar(self) -> Path:
        """Where its alternative text and print width are written, beside it."""
        return self.path.with_name(f"{self.path.stem}.guard.yaml")


def placed_files(project: Project) -> list[Placed]:
    """Each figure file the manuscript places by `\\includegraphics` or as a Markdown image,
    once, one per figure where it places a figure's exports in two formats, a figure an
    analysis emits and the manuscript binds left out."""
    from manuscript_guard.gates.figure_review import REVIEWABLE, choose

    manuscript = project.path("manuscript")
    if not manuscript.is_dir():
        return []
    root = project.root.absolute()
    real_root = _resolved(root) or root
    found_in, emitted = _read(project, manuscript)
    figures = _resolved(project.path("figures"))
    # By the file a path leads to, the first path that leads there kept: the one the records
    # stand beside, through a link where it goes through one.
    seen: dict[Path, tuple[Path, bool]] = {}
    for written, supplementary in found_in:
        path = Path(os.path.normpath(written))
        found = _resolved(path)
        if found is None or not found.is_file() or found.suffix.lower() not in REVIEWABLE:
            continue
        if found.parent == figures and found.stem in emitted:
            continue
        first, only = seen.get(found, (path, True))
        seen[found] = (first, only and supplementary)
    links = dict(seen.values())
    return [Placed(path, _named(path, root),
                   all(only for other, only in links.items()
                       if (other.parent, other.stem) == (path.parent, path.stem)),
                   outside=not _inside(path, real_root))
            for path in choose(list(links))]  # fmt: skip


#: What `_read` read, by what it read: `check` asks for the placed figures from four gates,
#: and reading the LaTeX documents and the bindings each time took a sixth of its time on a
#: twin of thirty pictures (round 1 of #630). Kept for the last few manuscripts.
_CACHE: dict[tuple[str, str], tuple[tuple[tuple[Path, bool], ...], frozenset[str]]] = {}
_CACHE_SIZE = 4
#: The suffixes of the files what the manuscript places is read from.
_SOURCES = {".md", ".tex", ".sty", ".cls"}


def _read(
    project: Project, manuscript: Path
) -> tuple[tuple[tuple[Path, bool], ...], frozenset[str]]:
    """Each picture the manuscript names, as a path to try, and the names of the figures it
    binds; read once for each content of its sources, so a changed file is read again."""
    from manuscript_guard.gates.figure_files import _placed
    from manuscript_guard.text.reader import LATEX, manuscript_format

    key = (f"{project.root.absolute()}|{manuscript.absolute()}", _sources_digest(manuscript))
    if key in _CACHE:
        return _CACHE[key]
    found_in = tuple(latex_graphics(manuscript) if manuscript_format(manuscript) == LATEX
                     else _markdown(project, manuscript))  # fmt: skip
    try:
        emitted = frozenset(name for name, _supplementary in _placed(project))
    except (ContractError, OSError):
        emitted = frozenset()  # a file that cannot be read is named by the check that reads it
    while len(_CACHE) >= _CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (found_in, emitted)
    return found_in, emitted


def _sources_digest(manuscript: Path) -> str:
    """A digest of every source file's path and bytes under `manuscript`."""
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(manuscript.rglob("*")):
        if path.suffix.lower() in _SOURCES and path.is_file():
            try:
                data = path.read_bytes()
            except OSError:
                data = b"\x00unreadable"
            digest.update(path.relative_to(manuscript).as_posix().encode("utf-8") + b"\x00")
            digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _named(path: Path, root: Path) -> str:
    """`path` from the project's root, as written through any link, `/` between folders."""
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:  # another drive
        return path.name


def _inside(path: Path, real_root: Path) -> bool:
    found = _resolved(path)
    return found is not None and found.is_relative_to(real_root)


def _decoded(match: re.Match[str]) -> str:
    return bytes.fromhex(match[0].replace("%", "")).decode("utf-8", errors="replace")


def _markdown(project: Project, manuscript: Path) -> list[tuple[Path, bool]]:
    """Each Markdown image's file, from the project's root, and whether the supplement holds
    it."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import is_supplementary, source_files

    found = []
    for path in source_files(manuscript):
        try:
            text = read_text(path)
        except (ContractError, OSError):
            continue  # a file that cannot be read is named by the check that reads it
        supplementary = is_supplementary(manuscript, path)
        found += [(project.root / target, supplementary) for target in images(text)]
    return found


def images(text: str) -> list[str]:
    """The path of each image a Markdown text places, outside code, comments and the front
    matter, as written, with its percent escapes read where they are written; a web address
    left out."""
    from manuscript_guard.text.masking import (
        _code_spans,
        blank,
        fenced_blocks,
        front_matter_end,
        html_comments,
    )

    fences = fenced_blocks(text)
    spans = [(fence.start, fence.end) for fence in fences]
    spans += [(0, front_matter_end(text)), *html_comments(text, fences), *_code_spans(text)]
    found = []
    for match in _IMAGE.finditer(blank(text, spans)):
        target = (match["angled"] or match["bare"]).strip()
        if target and not _WEB.match(target):
            if match["bare"]:
                target = _ESCAPED.sub(r"\1", target)
            found.append(_PERCENT.sub(_decoded, target))
    return found


def latex_graphics(manuscript: Path) -> list[tuple[Path, bool]]:
    """Each `\\includegraphics`'s file in the main text's document and in the supplement's,
    and whether it is the supplement's."""
    from manuscript_guard.text.latex.structure import ENTRY, SUPPLEMENT_ENTRY, read_document

    found = []
    for supplementary in (False, True):
        entry = SUPPLEMENT_ENTRY if supplementary else ENTRY
        try:
            document = read_document(manuscript, supplementary=supplementary)
        except (ContractError, OSError):
            continue
        tree = [source for source in document.sources if not source.loose]
        folders = graphics_folders(source.text for source in tree)
        for source in tree:
            for written in included(source):
                hit = resolve_graphic(manuscript, entry, source.imported, folders, written)
                if hit is not None:
                    found.append((hit, supplementary))
    return found


def graphics_folders(texts) -> list[str]:
    """The folders the `\\graphicspath` of each text names, in order, comments left out."""
    folders: list[str] = []
    for text in texts:
        for match in _GRAPHICSPATH.finditer(_COMMENT.sub(r"\1", text)):
            folders += [found.strip() for found in _FOLDER.findall(match[1]) if found.strip()]
    return list(dict.fromkeys(folders))


def included(source) -> list[str]:
    """The path each `\\includegraphics` of a LaTeX file names, where TeX prints it, as
    written: not in what TeX never prints, nor in a definition's body, which prints only
    where the command is used (round 1 of #630); one built by a command or a parameter,
    `#1`, is no path."""
    reading = source.reading
    out = []
    for start, end, opened in reading.graphics:
        if any(begin <= start < finish for begin, finish in (*reading.unprinted,
                                                             *reading.bodies)):  # fmt: skip
            continue
        written = source.text[opened + 1 : end - 1].strip().strip('"').strip()
        if written and not set(written) & set("#\\{}"):
            out.append(written)
    return out


def resolve_graphic(
    manuscript: Path, entry: str, imported: str, folders: list[str], written: str
) -> Path | None:
    """The file an `\\includegraphics{written}` places, as graphicx finds it: each extension
    in turn, and for each, the entry file's folder, the folder an imported file came from,
    then each folder of `\\graphicspath`. None where none is a file."""
    base = posixpath.dirname(entry)
    places = [base, *([posixpath.join(base, imported)] if imported else [])]
    places += [posixpath.join(base, folder) for folder in folders]
    names = [written] if posixpath.splitext(written)[1] in EXTENSIONS else []
    names += [written + extension for extension in EXTENSIONS]
    for name in names:
        for place in places:
            candidate = manuscript / posixpath.normpath(posixpath.join(place, name))
            if candidate.is_file():
                return candidate
    return None


def check_placed(project: Project) -> Report:
    """One note naming each placed figure outside `figures/`, whose numbers are not traced
    to the results, and one naming each the manuscript reaches outside the project, through
    a link."""
    from manuscript_guard.gates.figure_review import under

    figures = project.path("figures")
    placed = placed_files(project)
    untraced = [found for found in placed if not under(found.path, figures)]
    outside = [found for found in placed if found.outside]
    findings = ([_untraced(untraced)] if untraced else []) + (
        [_outside(outside)] if outside else [])  # fmt: skip
    return Report(tuple(findings))


def _outside(outside: list[Placed]) -> Finding:
    names = ", ".join(found.name for found in outside)
    return Finding(
        gate=GATE,
        code="figure-outside-project",
        severity=INFO,
        message=f"{len(outside)} placed figure(s) are outside the project, where a link in it "
        f"leads: {names}. Each is reviewed, described and read where the link leads, and its "
        "review and guard file are kept there, out of the project's history",
        path=outside[0].path,
        hint="copy the file into the project, beside the manuscript, so that the paper's "
        "repository holds what it prints and the records of it",
    )


def _untraced(untraced: list[Placed]) -> Finding:
    names = ", ".join(placed.name for placed in untraced)
    return Finding(
        gate=GATE,
        code="figure-untraced",
        severity=INFO,
        message=f"the numbers drawn in {len(untraced)} placed figure(s) are not traced to the "
        f"results, since no analysis emits them: {names}",
        path=untraced[0].path,
        hint="render a figure from a script that reads the results, into figures/, and place "
        "it by binding, \\mg{figure.key} or {{figure.key}}: G3 then reads what it draws. Its "
        "review, alternative text and colours are checked either way",
    )
