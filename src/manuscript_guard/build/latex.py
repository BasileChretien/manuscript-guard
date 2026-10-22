"""The PDF of a LaTeX manuscript (DESIGN.md, "The build of a LaTeX source", step 9).

`build` compiles a copy of the manuscript in the project's build folder, `build/latex/`, with
latexmk, never the folder the author writes in. Each document, the main text and the
supplement where its entry file declares a class, gets beside its entry file a fresh
`mgvalues.sty` from the results as they stand, `references.bib`, and the rendered figures in a
`figures/` folder, so that the values file names each figure with no `..`.

latexmk runs with `-norc`, so nobody's configuration runs; with `-no-shell-escape`; and with
`-interaction=nonstopmode -halt-on-error -file-line-error`, so the first error stops the build
and names its file and line, which are given back as the manuscript's. TeX Live is kept to the
copy: `openout_any` and `openin_any` are `p`, so no file is written or read by a path that
leaves it, `TEXINPUTS` names the document's folder before the standard trees, and `TEXMFHOME`
an empty folder, so that an author's own folder of packages is not searched. MiKTeX's package
installer is turned off (`-disable-installer`), so a missing package is named rather than
fetched mid-build; MiKTeX refuses an `\\openout` outside the folder by itself, and reads what it
is told to (measured under MiKTeX 24.4 on 2026-10-22). The log's lines are not broken
(`max_print_line`), so a long key is read whole.

The log says which citations and references were left undefined; the build lists them, and
`--submission` fails on them. Each heading LaTeX numbered, as the `.aux` files say, must be one
the reader reads, in the same order (`MisreadError`): a heading a macro makes, which the reader
does not see, is a paper the gates read otherwise than LaTeX prints it.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.build.document import BuildError, MisreadError

#: latexmk's switch for each engine a profile may name.
ENGINES = {"pdflatex": "-pdf", "lualatex": "-lualatex", "xelatex": "-xelatex"}
#: Seconds one document may take to compile before it is stopped.
TIMEOUT = 600
#: The folder of the copy, in the project's build folder.
COPY = "latex"
#: The values file's name, which the build writes for each document.
VALUES = "mgvalues.sty"
#: The file that marks the copy's folder as the build's, which it alone may replace.
MARK = ".manuscript-guard-copy"


class LatexMissing(BuildError):
    """latexmk or the engine is not installed: the PDF cannot be built here."""


@dataclass(frozen=True)
class Compiled:
    """One document compiled: its PDF, each citation or reference LaTeX left undefined, as
    `citation key` or `reference label`, and each of the manuscript's files LaTeX read, by
    its path in the manuscript, none it wrote (step 10)."""

    pdf: Path
    undefined: tuple[str, ...] = ()
    read: tuple[Path, ...] = ()
    #: Each key LaTeX wrote to the `.aux` as cited, through any command (round 1 of step 10).
    cited: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Copy:
    """Where the manuscript is copied, and the folder of each document's entry file in it."""

    root: Path
    source: Path
    folders: tuple[Path, ...]
    #: The folder of the copy that `source` is, in `root`: none for the submission folder
    #: compiled alone, which is copied whole (step 10).
    inner: str = "manuscript"
    #: Each file the build wrote into the copy, a rendered figure over the author's of the
    #: same name among them, which is none of the manuscript's (round 1 of step 10).
    made: frozenset[Path] = frozenset()

    @property
    def manuscript(self) -> Path:
        return self.root / self.inner if self.inner else self.root

    def original(self, path: Path) -> Path:
        """The manuscript's file that `path` of the copy is."""
        try:
            return self.source / path.resolve().relative_to(self.manuscript.resolve())
        except ValueError:
            return path


def build_latex(project, namespace, results, *, engine: str = "pdflatex") -> list[Compiled]:
    """The main text's PDF and, where the manuscript has one, the supplement's."""
    from manuscript_guard.text.latex.structure import ENTRY

    programs = _programs(engine)
    copy = _copy(project, namespace, results)
    return [_compile(project, copy, folder / ENTRY, programs, engine,
                     supplementary=folder != copy.manuscript)
            for folder in copy.folders]  # fmt: skip


def _programs(engine: str) -> tuple[str, str]:
    """latexmk and the engine, or `LatexMissing` naming what is not installed."""
    if engine not in ENGINES:
        raise BuildError(f"the engine {engine!r} is none latexmk is run with here: "
                         f"{', '.join(ENGINES)}")  # fmt: skip
    found = {name: shutil.which(name) for name in ("latexmk", engine)}
    absent = [name for name, path in found.items() if path is None]
    if absent:
        raise LatexMissing(
            f"{' and '.join(absent)} {'is' if len(absent) == 1 else 'are'} not installed, so no "
            "PDF is built; `check` reads the manuscript all the same (TeX Live or MiKTeX, with "
            "latexmk, builds it)"
        )
    return found["latexmk"], found[engine]


def _copy(project, namespace, results) -> _Copy:
    """The manuscript copied to the build folder, each document with its values file, its
    figures and its references, in the folders `paper.yaml` names (round 1 of step 9)."""
    from manuscript_guard.build.latex_values import (
        contents,
        entry_folders,
        rendered_figures,
        results_digest,
    )

    source = project.path("manuscript")
    root = fresh_root(project)
    shutil.copytree(source, root / "manuscript", symlinks=False)
    copy = _Copy(root, source, ())
    folders = tuple(copy.manuscript / folder.relative_to(source)
                    for folder in entry_folders(project))  # fmt: skip
    bib = project.path("literature") / "references.bib"
    digest = results_digest(project.root, results)
    made = set()
    for folder in folders:
        figures = {}
        for key, rendered in rendered_figures(project).items():
            figures[key] = None
            if rendered is not None:
                (folder / "figures").mkdir(exist_ok=True)
                figures[key] = Path(shutil.copyfile(rendered, folder / "figures" / rendered.name))
                made.add(figures[key].resolve())
        written = contents(folder, namespace, results, figures, digest)
        (folder / VALUES).write_text(written.text, encoding="utf-8", newline="\n")
        made.add((folder / VALUES).resolve())
        if bib.is_file():
            shutil.copyfile(bib, folder / "references.bib")
            made.add((folder / "references.bib").resolve())
    (root / ".texmfhome").mkdir()
    return _Copy(root, source, folders, made=frozenset(made))


def fresh_root(project) -> Path:
    """The build's folder in the project's build folder, emptied and marked as the build's;
    or `BuildError` where it would take the author's files (rounds 2 and 3 of step 9)."""
    source = project.path("manuscript")
    root = project.path("build") / COPY
    _may_replace(root, source)
    if root.exists():
        # The mark last, so that a removal stopped by a locked file leaves a folder the next
        # build still knows as its own (round 3 of step 9).
        for path in root.iterdir():
            if path.name != MARK:
                shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / MARK).write_text("made by manuscript-guard build; replaced by each build\n",
                             encoding="utf-8")  # fmt: skip
    return root


def _may_replace(root: Path, source: Path) -> None:
    """Refuse a copy's folder that the build would take the author's files with: one that
    holds the manuscript or is inside it, or one already there that the build did not make.
    `paths.build` may name any folder (round 2 of step 9)."""
    if root.is_symlink() or root.is_file():
        raise BuildError(f"{root} is not a folder the build may replace")
    held, holder = source.resolve(), root.resolve()
    if held.is_relative_to(holder) or holder.is_relative_to(held):
        raise BuildError(f"the build's copy, {root}, and the manuscript, {source}, would be one "
                         "inside the other: name another build folder in paper.yaml")  # fmt: skip
    if root.exists() and not (root / MARK).is_file():
        raise BuildError(f"{root} is there and the build did not make it; each build "
                         "replaces that folder, so move it or name another build folder in "
                         "paper.yaml")  # fmt: skip


def _compile(project, copy: _Copy, entry: Path, programs: tuple[str, str], engine: str, *,
             supplementary: bool, headings: bool = True) -> Compiled:  # fmt: skip
    latexmk, binary = programs
    command = [latexmk, "-norc", ENGINES[engine], "-interaction=nonstopmode", "-recorder",
               "-halt-on-error", "-file-line-error", "-no-shell-escape"]  # fmt: skip
    if _miktex(binary):
        command.append(f"-{engine}={engine} -disable-installer -max-print-line=10000 %O %S")
    # BibTeX's and Biber's paths too, so that a `.bib` of the author's elsewhere is not read
    # (round 2 of step 10).
    here = f"{entry.parent}{os.pathsep}"
    env = {**os.environ, "openout_any": "p", "openin_any": "p", "max_print_line": "10000",
           "TEXINPUTS": here, "BIBINPUTS": here, "BSTINPUTS": here,
           "TEXMFHOME": str(copy.root / ".texmfhome")}  # fmt: skip
    stopped, said = _run(command + [entry.name], entry.parent, env)
    if stopped:
        raise BuildError(f"LaTeX took longer than {TIMEOUT} s on {copy.original(entry)}, "
                         "and was stopped")  # fmt: skip
    log = _read(entry.with_suffix(".log"))
    if not entry.with_suffix(".pdf").is_file() or _ERROR.search(log) or _MISSING.search(log):
        raise BuildError(_first_error(copy, entry, log) or
                         f"latexmk stopped on {copy.original(entry)}: {said[-600:]}")
    if headings:
        _compare_headings(project, copy, entry, supplementary)
    return Compiled(entry.with_suffix(".pdf"), _undefined(log), _recorded(copy, entry),
                    tuple(dict.fromkeys(aux_citations(entry.with_suffix(".aux")))))


#: A key the `.aux` holds as cited: BibTeX's `\\citation{a,b}`, biblatex's
#: `\\abx@aux@cite{0}{a}`; and the `.aux` of an included file.
_AUX_CITED = re.compile(r"\\citation\{(?P<keys>[^{}]*)\}|\\abx@aux@cite\{[^{}]*\}"
                        r"\{(?P<key>[^{}]*)\}|\\@input\{(?P<input>[^{}]+\.aux)\}")  # fmt: skip


def aux_citations(aux: Path, depth: int = 0) -> list[str]:
    """Each key LaTeX wrote to `aux` and the `.aux` files it inputs as cited, in order: what
    BibTeX or Biber is asked for, whatever command cited it (round 1 of step 10)."""
    keys = []
    for found in _AUX_CITED.finditer(_read(aux)):
        if found["input"] is not None:
            if depth < 8:
                keys += aux_citations(aux.parent / found["input"], depth + 1)
        elif found["key"] is not None:
            keys.append(found["key"].strip())
        else:
            keys += [key.strip() for key in found["keys"].split(",") if key.strip()]
    return keys


#: What LaTeX and the programs latexmk runs write beside a document, which is no file of the
#: author's even where an old one is in the manuscript's folder.
_MADE = frozenset({".aux", ".bbl", ".bcf", ".blg", ".fdb_latexmk", ".fls", ".idx", ".ilg",
                   ".ind", ".lof", ".log", ".lot", ".nav", ".out", ".run.xml", ".snm",
                   ".synctex.gz", ".toc", ".vrb", ".xdv", ".xml"})  # fmt: skip


def recorded(entry: Path) -> tuple[list[Path], set[Path]]:
    """Each file the recorder's `.fls` lists as read for `entry`, in order, and those it lists
    as written (step 10)."""
    where, read, written = entry.parent, [], set()
    for line in _read(entry.with_suffix(".fls")).splitlines():
        kind, _, name = line.partition(" ")
        if kind == "PWD":
            where = Path(name)
        elif kind in ("INPUT", "OUTPUT") and name:
            path = (where / name).resolve()
            (written.add(path) if kind == "OUTPUT" else read.append(path))
    return read, written


def _recorded(copy: _Copy, entry: Path) -> tuple[Path, ...]:
    """Each of the manuscript's files LaTeX read for `entry`, by its path in the manuscript:
    none it wrote, and none the build put in the copy, which the manuscript does not hold
    (step 10)."""
    read, written = recorded(entry)
    found: dict[Path, None] = {}
    for path in read:
        if path in written or path in copy.made or path.suffix.lower() in _MADE \
                or "".join(path.suffixes[-2:]).lower() in _MADE:
            continue
        original = copy.original(path)
        if original != path and original.is_file():
            found[original] = None
    return tuple(found)


def _run(command: list[str], folder: Path, env: dict[str, str]) -> tuple[bool, str]:
    """Run `command`, and stop it and every program it started after `TIMEOUT` seconds. latexmk
    stopped alone left its engine running, which held the pipes open; and under MiKTeX, where
    the engine is no child of latexmk's by the time it runs, stopping latexmk's tree missed it
    (round 1 of step 9). So what it says goes to a file, and on Windows it runs in a job that
    is ended whole, elsewhere in a process group of its own. An interrupt stops them too."""
    said = folder / "latexmk.out"
    job = _Job() if sys.platform == "win32" else None
    try:
        with said.open("w", encoding="utf-8", errors="replace") as out:
            process = subprocess.Popen(command, cwd=folder, env=env, stdout=out,
                                       stderr=subprocess.STDOUT,
                                       start_new_session=job is None)  # fmt: skip
            if job is not None:
                job.take(process)
            try:
                process.wait(timeout=TIMEOUT)
                stopped = False
            except subprocess.TimeoutExpired:
                _stop(process, job)
                stopped = True
            except BaseException:
                with contextlib.suppress(BuildError):
                    _stop(process, job)
                raise
    finally:
        if job is not None:
            job.close()
    return stopped, _read(said)


def _stop(process: subprocess.Popen, job: _Job | None) -> None:
    """Stop `process` and every program it started (round 2 of step 9)."""
    if job is not None:
        job.end(process)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        raise BuildError(f"LaTeX ran past its limit and could not be stopped: process "
                         f"{process.pid} is still running") from None  # fmt: skip


class _Job:
    """A Windows job object that ends every process in it when it is ended or closed. Where
    the job cannot be made or the process put in it, `end` stops the process's tree by
    `taskkill` (round 2 of step 9)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel = self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, arguments, returned in (
            ("CreateJobObjectW", [wintypes.LPVOID, wintypes.LPCWSTR], wintypes.HANDLE),
            ("SetInformationJobObject",
             [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD], wintypes.BOOL),
            ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            ("TerminateJobObject", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ):  # fmt: skip
            getattr(kernel, name).argtypes = arguments
            getattr(kernel, name).restype = returned
        self._handle = kernel.CreateJobObjectW(None, None)
        self._taken = False

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]  # fmt: skip

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]  # fmt: skip

        limits = _Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        # 9 is JobObjectExtendedLimitInformation.
        if self._handle and not kernel.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            kernel.CloseHandle(self._handle)
            self._handle = None

    def take(self, process: subprocess.Popen) -> None:
        self._taken = bool(self._handle) and bool(
            self._kernel.AssignProcessToJobObject(self._handle, int(process._handle))
        )

    def end(self, process: subprocess.Popen) -> None:
        if not (self._taken and self._kernel.TerminateJobObject(self._handle, 1)):
            # What taskkill leaves running, `_stop` names (round 3 of step 9).
            with contextlib.suppress(subprocess.TimeoutExpired, OSError):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                               capture_output=True, timeout=60, check=False)  # fmt: skip

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def _miktex(binary: str) -> bool:
    done = subprocess.run([binary, "--version"], capture_output=True, text=True,
                          errors="replace", timeout=60, check=False)  # fmt: skip
    return "MiKTeX" in done.stdout


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


#: An error as `-file-line-error` writes it: `./main.tex:12: Undefined control sequence.`, its
#: path absolute on Windows with its drive (round 2 of step 9).
_ERROR = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^\s:][^:\n]*?\.(?:tex|sty|cls|bbl)):(?P<line>\d+): "
                    r"(?P<said>.+)$", re.MULTILINE)  # fmt: skip
#: A file LaTeX could not find, a package among them, which `-disable-installer` leaves
#: unfetched. MiKTeX names it so, then stops with "Emergency stop" at the line that asked.
_MISSING = re.compile(r"File `(?P<name>[^']+)' not found")


def _first_error(copy: _Copy, entry: Path, log: str) -> str | None:
    """The first error of the log, at the manuscript's file and line; a package not found, by
    its name; and one in the values file, as the build's file, which it writes."""
    missing = _MISSING.search(log)
    if missing is not None and missing["name"].endswith((".sty", ".cls")):
        return (f"{missing['name']} is not installed, and the build does not fetch it: install "
                "it with your TeX distribution's package manager")  # fmt: skip
    if missing is not None:
        return (f"LaTeX found no file {missing['name']!r} from {copy.original(entry)}: the build "
                "reads only what is in the manuscript's folders")  # fmt: skip
    found = _ERROR.search(log)
    if found is None:
        return None
    source = (entry.parent / found["file"]).resolve()
    said = found["said"].strip()
    if source.name == VALUES:
        return f"{source}:{found['line']}: {said} (the values file the build writes)"
    return f"{copy.original(source)}:{found['line']}: {said}"


#: A citation or a reference LaTeX left undefined, as LaTeX, natbib and biblatex warn of it,
#: with either quotation mark.
_UNDEFINED = re.compile(r"(?P<kind>Citation|Reference) [`'](?P<key>[^'\n]+)' on page \d+ "
                        r"undefined")  # fmt: skip


def _undefined(log: str) -> tuple[str, ...]:
    found = dict.fromkeys(f"{m['kind'].lower()} {m['key']}" for m in _UNDEFINED.finditer(log))
    return tuple(found)


def _compare_headings(project, copy: _Copy, entry: Path, supplementary: bool) -> None:
    """Each heading LaTeX numbered is one the reader reads, in order (`MisreadError`). The
    reader may read more: a heading LaTeX does not number, below `secnumdepth`, is none of the
    `.aux`'s (round 1 of step 9). A title is the reader's where its words are the `.aux`'s in
    order with some left out: the `.aux` holds what an author's macro in the title expands to,
    which the reader blanks, as it does in prose (round 2 of step 9)."""
    written = aux_headings(entry.with_suffix(".aux"))
    read = reader_headings(project, supplementary=supplementary)
    at = 0
    for title in written:
        plain = _plain(title).split()
        while at < len(read) and not any(_within(_plain(name).split(), plain)
                                         for name in read[at]):  # fmt: skip
            at += 1
        if at == len(read):
            raise MisreadError(
                f"LaTeX numbered a heading {title!r} in {copy.original(entry)} that the reader "
                "does not read where LaTeX prints it: the gates read this manuscript otherwise "
                "than LaTeX prints it. A heading a macro makes is one the reader does not see"
            )
        at += 1


def _within(words: list[str], title: list[str]) -> bool:
    """Whether `words` are `title`'s, in order, some of `title`'s left out."""
    left = iter(title)
    return all(word in left for word in words)


#: A numbered heading in the `.aux`, `\\@writefile{toc}{\\contentsline {section}{\\numberline
#: {1}Methods}{2}...}`, its entry's group opening at `entry`; and the `.aux` of an included
#: file, which holds that file's headings.
_TOC = re.compile(r"\\@writefile\{toc\}\{\\contentsline \{\w+\}(?P<entry>\{)\\numberline |"
                  r"\\@input\{(?P<input>[^{}]+\.aux)\}")  # fmt: skip


def aux_headings(aux: Path, depth: int = 0) -> list[str]:
    """The title of each numbered heading LaTeX wrote to `aux` and the `.aux` files it inputs,
    in order: each entry less the number before it."""
    text = _read(aux)
    titles = []
    for found in _TOC.finditer(text):
        if found["input"] is not None:
            if depth < 8:
                titles += aux_headings(aux.parent / found["input"], depth + 1)
            continue
        entry_end = _group_end(text, found.start("entry"))
        number_end = _group_end(text, found.end())
        titles.append(text[number_end : entry_end - 1])
    return titles


def _group_end(text: str, opened: int) -> int:
    """Past the brace group that opens at `opened`."""
    depth = 0
    for at in range(opened, len(text)):
        if text[at] == "{":
            depth += 1
        elif text[at] == "}":
            depth -= 1
            if depth == 0:
                return at + 1
    return len(text)


def reader_headings(project, *, supplementary: bool) -> list[tuple[str, ...]]:
    """Each heading the reader reads that LaTeX may number, in the order the document prints
    them, by its title and its short title for the contents where it has one: no starred
    heading and no abstract."""
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import read_document

    sources = [source for source in read_document(project.path("manuscript"),
                                                  supplementary=supplementary).sources
               if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
    found = []
    for _at, source, start, linear in printed(sources).origins:
        if linear:
            continue
        for heading in source.reading.headings:
            if heading.start == start and heading.end > heading.start:
                after = _after_name(source.text, heading.start)
                if not after.startswith("*"):
                    found.append((heading.title, *_short(after)))
    return found


def _after_name(text: str, start: int) -> str:
    name = re.match(r"\\[A-Za-z]+\s*", text[start:])
    return text[start + (name.end() if name else 0) :]


def _short(after: str) -> tuple[str, ...]:
    """A heading's short title for the contents, `\\section[Short]{Long}`, read as the reader
    reads a title."""
    from manuscript_guard.text.latex.mask import NUL, read

    if not after.startswith("["):
        return ()
    end = after.find("]")
    return (read(after[1:end]).masked.replace(NUL, " "),) if end > 0 else ()


def _plain(title: str) -> str:
    """A title as words, read as the reader reads one, so that a binding or a citation in it,
    which the reader blanks, is blank in the `.aux`'s too."""
    from manuscript_guard.text.latex.mask import NUL, read

    shown = read(title.replace("\\protect", "")).masked.replace(NUL, " ")
    return " ".join(re.findall(r"[^\W_]+", shown.casefold()))
